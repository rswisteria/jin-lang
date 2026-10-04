"""フリーハンド(モード 1・陣書き S6)の認識(`jin_glyph.recognize` の型紙なしの経路)。ネットワークと API キーは使わない。

写真は完全陣(手描きの手本と同じ視覚文法)を斜めから撮った JPEG に見立てたもの、Claude の応答は正解から合成したもの
(`tests/glyph_photo.synthetic_free_responses`・本物の録画ではない)。ずれたら `UPDATE_RECORDINGS=1` で書き直す。
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest
from jin_core.canonical import dumps
from jin_core.check import check_text
from jin_core.v2.glyph import START_MARK
from jin_core.v2.model import JinFileV2
from jin_glyph.parse import parse_scene
from jin_glyph.recognize import (
    FREE_SYSTEM,
    RecognizeError,
    Recognizer,
    glyph_table,
    recognize_photo,
)
from PIL import Image

from tests.glyph_photo import (
    _message,
    replay_client,
    synthetic_free_photo,
    synthetic_free_responses,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
RECORDINGS = REPO_ROOT / "tests" / "fixtures" / "recognize" / "fib-free.synthetic"
NAMES = ("align", "frame", "layout")


def load(name: str) -> JinFileV2:
    path = REPO_ROOT / "examples-v2" / name / f"{name}.jin"
    model = check_text(path.read_text(encoding="utf-8"), path.name).model
    assert isinstance(model, JinFileV2)
    return model


def source(name: str) -> str:
    return (REPO_ROOT / "examples-v2" / name / f"{name}.jin").read_text(encoding="utf-8")


def recordings() -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(RECORDINGS.glob("*.json"))]


@pytest.fixture(scope="module")
def fib_photo() -> bytes:
    return synthetic_free_photo(load("fib"))


def read(photo: bytes, responses: list[dict], requests: list[dict] | None = None):
    return recognize_photo(
        photo,
        recognizer=Recognizer(
            client=replay_client(responses, [] if requests is None else requests)
        ),
    )


def test_the_recorded_responses_match_their_generator() -> None:
    """fixture は正解から合成した応答。ずれたら UPDATE_RECORDINGS=1 で書き直す。"""
    expected = synthetic_free_responses(load("fib"))
    if os.environ.get("UPDATE_RECORDINGS"):
        RECORDINGS.mkdir(parents=True, exist_ok=True)
        for old in RECORDINGS.glob("*.json"):
            old.unlink()
        for n, body in enumerate(expected):
            name = NAMES[n] if n < len(NAMES) else "blobs"
            text = json.dumps(body, ensure_ascii=False, indent=2) + "\n"
            (RECORDINGS / f"{n:02d}-{name}.json").write_text(text, encoding="utf-8")
    assert recordings() == expected


def test_a_photo_of_a_freehand_fib_reads_back_to_fib(fib_photo: bytes) -> None:
    """完了の条件(設計書 §6 S6)の機械の側: 白紙に描いた fib の写真 → 場面グラフ → 構文解析で元の .jin とバイト一致。"""
    requests: list[dict] = []
    scene = read(fib_photo, recordings(), requests)
    assert scene.sheet == "free"
    assert [f.id for f in scene.figures] == ["frame", "c0", "r0_0", "r0_1"]
    model, diagnostics = parse_scene(scene, file="fib.jinscene.json")
    assert diagnostics == []
    assert model is not None and dumps(model) == source("fib")
    assert len(requests) == len(recordings())


def test_the_freehand_requests(fib_photo: bytes) -> None:
    """型紙の位置合わせ → 額縁の四隅(写真)→ 環の形(正面図)→ 塊の読み。フリーハンドの要求は始まりの印を含む字形表と別の system。"""
    requests: list[dict] = []
    read(fib_photo, recordings(), requests)
    bodies = [r["body"] for r in requests]
    assert isinstance(bodies[0]["system"], str) and bodies[0]["system"] != FREE_SYSTEM
    assert all(b["system"] == FREE_SYSTEM for b in bodies[1:])
    for body in bodies[:3]:
        assert [b["type"] for b in body["messages"][0]["content"]] == ["image", "text"]
    import base64

    table = base64.standard_b64encode(_png(glyph_table(with_start=True))).decode()
    for body in bodies[3:]:
        content = body["messages"][0]["content"]
        assert content[0]["cache_control"] == {"type": "ephemeral"}
        assert content[0]["source"]["data"] == table
        labels = [b["text"] for b in content[2:] if b["type"] == "text"]
        assert labels[0].startswith("#1 (") and labels[0].endswith(")")
        assert len(labels) == len([b for b in content[2:] if b["type"] == "image"])
    assert START_MARK in FREE_SYSTEM


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def test_the_boxes_are_in_photo_coordinates(fib_photo: bytes) -> None:
    scene = read(fib_photo, recordings())
    width, height = scene.image.width, scene.image.height
    for band in scene.bands:
        assert band.cells
        for cell in band.cells:
            assert cell.box is not None
            x0, y0, x1, y1 = cell.box
            assert 0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height
            assert x1 - x0 < 150 and y1 - y0 < 150  # 1 升 ≈ 36 px(塊は字 2〜3 個まで)
    frame = next(f for f in scene.figures if f.id == "frame")
    assert frame.at == pytest.approx((width / 2, height / 2), rel=0.05)


@pytest.mark.parametrize(("turn", "misjudge"), [(1, 0), (2, 3)])
def test_a_turned_photo_reads_back_even_when_claude_misjudges_the_top(
    turn: int, misjudge: int
) -> None:
    """陣が写真の中で回っていても読める。Claude が描き手の上を取り違えても(四隅を 90° ずらして返す)、
    額縁の中心に最も近い環の始まりの印の向きで直す。"""
    model = load("fib")
    photo = synthetic_free_photo(model, turn)
    scene = read(photo, synthetic_free_responses(model, turn, misjudge))
    parsed, diagnostics = parse_scene(scene, file="fib.jinscene.json")
    assert diagnostics == [] and parsed is not None and dumps(parsed) == source("fib")


def test_clicker_reads_back_with_inscriptions_of_several_turns() -> None:
    """clicker(523 升)は陣と手順陣の銘環が何周にもなる(継ぎの紋で外の周へ)。手描きの規模の上限(設計書 §9 #8)。"""
    model = load("clicker")
    scene = read(synthetic_free_photo(model), synthetic_free_responses(model))
    assert any(c.v == "cont" for band in scene.bands for c in band.cells)
    parsed, diagnostics = parse_scene(scene, file="clicker.jinscene.json")
    assert diagnostics == [] and parsed is not None and dumps(parsed) == source("clicker")


def test_a_ring_without_a_start_mark_is_reported_by_the_parser(fib_photo: bytes) -> None:
    """始まりの印を読めなかった環は、そのまま場面グラフに残し構文解析器が JIN301 で知らせる(認識器は印を補わない)。"""
    responses = recordings()
    for body in responses[3:]:
        payload = json.loads(body["content"][1]["text"])
        for blob in payload["blobs"]:
            blob["symbols"] = [s for s in blob["symbols"] if s["v"] != START_MARK]
        body["content"][1]["text"] = json.dumps(payload, ensure_ascii=False)
    scene = read(fib_photo, responses)
    _, diagnostics = parse_scene(scene, file="fib.jinscene.json")
    assert {d.code for d in diagnostics} == {"JIN301"}


def test_a_reading_outside_the_contract_becomes_a_question_mark(fib_photo: bytes) -> None:
    responses = recordings()
    payload = json.loads(responses[3]["content"][1]["text"])
    payload["blobs"][-1]["symbols"] = [{"t": "glyph", "v": "plus", "unsure": []}]
    del payload["blobs"][-2]  # 返ってこなかった塊
    responses[3]["content"][1]["text"] = json.dumps(payload, ensure_ascii=False)
    scene = read(fib_photo, responses)
    values = [(c.v, c.unsure) for band in scene.bands for c in band.cells if c.v == "?"]
    assert ("?", ["glyph:plus"]) in values
    assert ("?", ["(読めませんでした)"]) in values


def test_a_frame_with_other_than_four_corners_is_refused(fib_photo: bytes) -> None:
    responses = recordings()[:2]
    frame = json.loads(responses[1]["content"][1]["text"])
    frame["corners"] = frame["corners"][:3]
    with pytest.raises(RecognizeError, match="四隅を 4 つ"):
        read(fib_photo, [responses[0], _message(frame, 1)])
