"""陣書き S4 の CLI: 型紙の写真を `jin check` / `jin fmt` が受け、`jin render --sheet S|M` が型紙と手本を描く。

写真は `tests/glyph_photo.py` が手本から合成し、Claude の応答は `anthropic.Anthropic` を差し替えて生の HTTP 応答で返す
(ネットワークと API キーを使わない)。送らないはずの経路では、要求が 1 つでも出たら落ちる client に差し替える。
サブコマンドは 9 個のまま(画像は check / fmt だけが受ける・glyph 設計書 §9 #11)。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from jin_cli.main import app
from jin_core.check import check_text
from jin_core.v2.model import JinFileV2
from jin_glyph import recognize
from jin_render.v2.sheet import render_sheet
from typer.testing import CliRunner

from tests.glyph_photo import refusing_transport_client, replay_client, synthetic_photo

REPO_ROOT = Path(__file__).resolve().parents[3]
FIB = REPO_ROOT / "examples-v2/fib/fib.jin"
PADDLE = REPO_ROOT / "examples-v2/paddle/paddle.jin"
RECORDINGS = REPO_ROOT / "tests/fixtures/recognize/fib-S.synthetic"

runner = CliRunner()


def run(*args: str):
    return runner.invoke(app, list(args))


def fib_model() -> JinFileV2:
    model = check_text(FIB.read_text(encoding="utf-8"), FIB.name).model
    assert isinstance(model, JinFileV2)
    return model


@pytest.fixture(scope="module")
def fib_photo_bytes() -> bytes:
    return synthetic_photo(fib_model())


@pytest.fixture
def photo(fib_photo_bytes: bytes, tmp_path: Path) -> Path:
    path = tmp_path / "fib.jpg"
    path.write_bytes(fib_photo_bytes)
    return path


@pytest.fixture
def requests(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """認識器の client を録画の再生に差し替え、出た要求を積む。"""
    sent: list[dict] = []
    responses = [
        json.loads(p.read_text(encoding="utf-8")) for p in sorted(RECORDINGS.glob("*.json"))
    ]
    monkeypatch.setattr(recognize.anthropic, "Anthropic", lambda: replay_client(responses, sent))
    return sent


@pytest.fixture
def no_sending(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(recognize.anthropic, "Anthropic", refusing_transport_client)


def test_check_reads_a_photo_says_it_sends_it_and_saves_the_scene_graph(
    photo: Path, requests: list[dict]
) -> None:
    result = run("check", str(photo))
    assert result.exit_code == 0, result.output
    assert "Anthropic の API" in result.stderr and "--offline" in result.stderr
    scene = json.loads((photo.parent / "fib.jinscene.json").read_text(encoding="utf-8"))
    assert scene["sheet"] == "S"
    assert len(requests) == len(list(RECORDINGS.glob("*.json")))


def test_a_second_check_reuses_the_scene_graph_without_sending(
    photo: Path, requests: list[dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert run("check", str(photo)).exit_code == 0
    monkeypatch.setattr(recognize.anthropic, "Anthropic", refusing_transport_client)
    result = run("check", str(photo))
    assert result.exit_code == 0, result.output
    assert "Anthropic の API" not in result.stderr


def test_offline_without_a_scene_graph_fails_without_sending(photo: Path, no_sending: None) -> None:
    result = run("check", "--offline", str(photo))
    assert result.exit_code == 2
    assert "--offline" in result.stderr
    assert not (photo.parent / "fib.jinscene.json").exists()


def test_offline_reads_the_saved_scene_graph(
    photo: Path, requests: list[dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert run("check", str(photo)).exit_code == 0
    monkeypatch.setattr(recognize.anthropic, "Anthropic", refusing_transport_client)
    assert run("check", "--offline", str(photo)).exit_code == 0
    out = photo.parent / "back.jin"
    assert run("fmt", "--offline", str(photo), "--out", str(out)).exit_code == 0
    assert out.read_text(encoding="utf-8") == FIB.read_text(encoding="utf-8")


def test_fmt_writes_the_canonical_jin_from_a_photo_and_keeps_the_scene_graph(
    photo: Path, requests: list[dict]
) -> None:
    out = photo.parent / "back.jin"
    result = run("fmt", str(photo), "--out", str(out))
    assert result.exit_code == 0, result.output
    assert out.read_text(encoding="utf-8") == FIB.read_text(encoding="utf-8")
    # 写真は読み直すと費用がかかるので fmt でも場面グラフを残す
    assert (photo.parent / "fib.jinscene.json").exists()


def test_a_scene_graph_of_another_photo_is_not_overwritten_and_nothing_is_sent(
    photo: Path, no_sending: None
) -> None:
    scene = photo.parent / "fib.jinscene.json"
    scene.write_text('{"image": {"sha256": "other"}}\n', encoding="utf-8")
    result = run("check", str(photo))
    assert result.exit_code == 2
    assert "上書きしません" in result.stderr
    assert scene.read_text(encoding="utf-8") == '{"image": {"sha256": "other"}}\n'


def test_a_recognize_failure_is_one_line_and_exit_2(
    photo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = json.loads((RECORDINGS / "00-align.json").read_text(encoding="utf-8"))
    body["content"] = []
    body["stop_reason"] = "refusal"
    body["stop_details"] = {"type": "refusal", "category": None, "explanation": None}
    monkeypatch.setattr(recognize.anthropic, "Anthropic", lambda: replay_client([body], []))
    result = run("check", str(photo))
    assert result.exit_code == 2
    assert "断りました" in result.stderr
    assert not (photo.parent / "fib.jinscene.json").exists()


def test_a_png_that_is_not_a_full_circle_is_never_sent(
    fib_photo_bytes: bytes, tmp_path: Path, no_sending: None
) -> None:
    """PNG は完全陣の決定的デコーダだけ。写真を PNG で渡しても API へは回さず、.jpg で渡すよう言う。"""
    import io

    from PIL import Image

    png = tmp_path / "fib.png"
    Image.open(io.BytesIO(fib_photo_bytes)).save(png, "PNG")
    result = run("check", str(png))
    assert result.exit_code == 2
    assert ".jpg" in result.stderr and "送りません" in result.stderr


def test_a_directory_scan_does_not_pick_up_photos(photo: Path, no_sending: None) -> None:
    shutil.copy(FIB, photo.parent / "fib.jin")
    result = run("check", str(photo.parent))
    assert result.exit_code == 0, result.output
    assert "1 ファイル" in result.stderr


# ---- jin render --sheet -------------------------------------------------------------------------


@pytest.mark.parametrize("grade", ["S", "M"])
def test_render_sheet_prints_the_blank_sheet(grade: str) -> None:
    result = run("render", "--sheet", grade)
    assert result.exit_code == 0, result.output
    assert result.stdout == render_sheet(grade)  # type: ignore[arg-type]


def test_render_sheet_with_a_file_draws_the_copybook(tmp_path: Path) -> None:
    out = tmp_path / "fib-S.svg"
    result = run("render", str(FIB), "--sheet", "S", "-o", str(out))
    assert result.exit_code == 0, result.output
    assert out.read_text(encoding="utf-8") == render_sheet("S", fib_model())


def test_render_sheet_refuses_a_program_that_does_not_fit() -> None:
    result = run("render", str(PADDLE), "--sheet", "S")
    assert result.exit_code == 2
    assert "陣が 3 個" in result.stderr


@pytest.mark.parametrize(
    "args",
    [
        ["render", "--sheet", "L"],
        ["render", "--sheet", "S", "--full"],
        ["render", "--sheet", "S", "--focus", "Fib"],
        ["render"],
    ],
)
def test_render_sheet_rejects_bad_combinations(args: list[str]) -> None:
    assert run(*args).exit_code == 2
