"""陣書き S3 の CLI: `jin check` / `jin fmt` が完全陣の画像(PNG)と場面グラフ(`.jinscene.json`)を受ける。

サブコマンドは 9 個のまま(画像は check / fmt だけが受ける・glyph 設計書 §9 #11)。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import cairosvg
import pytest
from jin_cli.main import app
from jin_core.check import check_text
from jin_render.v2.full import render_full
from typer.testing import CliRunner

REPO_ROOT = Path(__file__).resolve().parents[3]
FIB = REPO_ROOT / "examples-v2/fib/fib.jin"
SCENE_ERRORS = REPO_ROOT / "tests/fixtures/errors/scene"

runner = CliRunner()


def run(*args: str):
    return runner.invoke(app, list(args))


@pytest.fixture(scope="module")
def fib_png(tmp_path_factory: pytest.TempPathFactory) -> Path:
    model = check_text(FIB.read_text(encoding="utf-8"), FIB.name).model
    path = tmp_path_factory.mktemp("png") / "fib.png"
    path.write_bytes(
        cairosvg.svg2png(bytestring=render_full(model).encode(), scale=2, background_color="white")
    )
    return path


def test_check_reads_a_png_and_writes_its_scene_graph(fib_png: Path, tmp_path: Path) -> None:
    png = tmp_path / "fib.png"
    shutil.copy(fib_png, png)
    result = run("check", str(png))
    assert result.exit_code == 0, result.output
    scene = tmp_path / "fib.jinscene.json"
    assert json.loads(scene.read_text(encoding="utf-8"))["sheet"] == "full"


def test_check_reads_a_scene_graph(fib_png: Path, tmp_path: Path) -> None:
    png = tmp_path / "fib.png"
    shutil.copy(fib_png, png)
    assert run("check", str(png)).exit_code == 0
    result = run("check", str(tmp_path / "fib.jinscene.json"))
    assert result.exit_code == 0, result.output


def test_fmt_writes_the_canonical_jin_from_a_png(fib_png: Path, tmp_path: Path) -> None:
    out = tmp_path / "back.jin"
    result = run("fmt", str(fib_png), "--out", str(out))
    assert result.exit_code == 0, result.output
    assert out.read_text(encoding="utf-8") == FIB.read_text(encoding="utf-8")


def test_fmt_of_an_image_needs_out_and_does_not_overwrite(fib_png: Path, tmp_path: Path) -> None:
    assert run("fmt", str(fib_png)).exit_code == 2
    out = tmp_path / "exists.jin"
    out.write_text("keep", encoding="utf-8")
    result = run("fmt", str(fib_png), "--out", str(out))
    assert result.exit_code == 2
    assert out.read_text(encoding="utf-8") == "keep"


def test_out_is_only_for_an_image(tmp_path: Path) -> None:
    assert run("fmt", str(FIB), "--out", str(tmp_path / "x.jin")).exit_code == 2


@pytest.mark.parametrize(
    "path", sorted(SCENE_ERRORS.glob("*.jinscene.json")), ids=lambda p: p.name.split("_")[0]
)
def test_a_broken_scene_graph_is_a_scene_diagnostic(path: Path) -> None:
    code = path.name.split("_")[0]
    result = run("check", "--json", str(path))
    diagnostics = json.loads(result.stdout)
    assert [d["code"] for d in diagnostics] == [code]
    assert diagnostics[0]["file"] == str(path)
    assert result.exit_code == (0 if code == "JIN306" else 1)


def test_a_png_that_is_not_a_full_circle_is_refused(tmp_path: Path) -> None:
    png = tmp_path / "blank.png"
    png.write_bytes(
        cairosvg.svg2png(
            bytestring=b'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"/>'
        )
    )
    result = run("check", str(png))
    assert result.exit_code == 2
    assert "護符" in result.output
    assert not (tmp_path / "blank.jinscene.json").exists()


def test_the_scene_graph_is_not_written_through_a_symlink(fib_png: Path, tmp_path: Path) -> None:
    png = tmp_path / "fib.png"
    shutil.copy(fib_png, png)
    target = tmp_path / "elsewhere.json"
    target.write_text("keep", encoding="utf-8")
    (tmp_path / "fib.jinscene.json").symlink_to(target)
    result = run("check", str(png))
    assert result.exit_code == 2
    assert target.read_text(encoding="utf-8") == "keep"


def test_a_directory_scan_still_reads_only_jin_files(fib_png: Path, tmp_path: Path) -> None:
    shutil.copy(fib_png, tmp_path / "fib.png")
    result = run("check", str(tmp_path))
    assert result.exit_code == 0
    assert not (tmp_path / "fib.jinscene.json").exists()


def test_an_edited_scene_graph_of_the_same_image_is_read_not_overwritten(
    fib_png: Path, tmp_path: Path
) -> None:
    # 最終レビュー #2・glyph.md §5: 隣の .jinscene.json の image.sha256 が画像と一致すればそれを読む(手直しを消さない)
    png = tmp_path / "fib.png"
    shutil.copy(fib_png, png)
    assert run("check", str(png)).exit_code == 0
    scene_path = tmp_path / "fib.jinscene.json"
    scene = json.loads(scene_path.read_text(encoding="utf-8"))
    scene["bands"][0]["cells"][0]["unsure"] = ["?"]
    edited = json.dumps(scene, ensure_ascii=False, indent=2) + "\n"
    scene_path.write_text(edited, encoding="utf-8")
    result = run("check", "--json", str(png))
    assert result.exit_code == 0, result.output
    assert [d["code"] for d in json.loads(result.stdout)] == ["JIN306"]
    assert scene_path.read_text(encoding="utf-8") == edited
    out = tmp_path / "back.jin"
    assert run("fmt", str(png), "--out", str(out)).exit_code == 0


def test_a_scene_graph_of_another_image_is_not_overwritten(fib_png: Path, tmp_path: Path) -> None:
    png = tmp_path / "fib.png"
    shutil.copy(fib_png, png)
    scene_path = tmp_path / "fib.jinscene.json"
    other = (SCENE_ERRORS / "JIN306_unsure_cell.jinscene.json").read_text(encoding="utf-8")
    scene_path.write_text(other, encoding="utf-8")
    result = run("check", str(png))
    assert result.exit_code == 2
    assert "別の画像" in result.output
    assert scene_path.read_text(encoding="utf-8") == other
