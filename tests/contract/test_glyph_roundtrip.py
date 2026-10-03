"""陣書き S3 の往復の契約: `.jin` → 完全陣の SVG → PNG(cairosvg・2 倍)→ `decode_png` → `parse_scene` → 正準形が元とバイト一致。

画像は `.jin` の 2 つ目の直列化(glyph 設計書 §0)。examples-v2 と `tests/fixtures/v2-programs/` の全本で、診断が空で戻ることを見る。
root が circles[0] でない並び(`root_not_first.jin`)と、空の then / 空の loop / 入れ子 3 段(`nested_blocks.jin`)も含む。
大きい完全陣(othello は 2 倍で 14749 px 四方)は 1 本で数十秒かかる。
"""

from __future__ import annotations

from pathlib import Path

import cairosvg
import pytest
from jin_core.canonical import dumps
from jin_core.check import check_text
from jin_core.v2.model import JinFileV2
from jin_glyph.decode import decode_png
from jin_glyph.parse import parse_scene
from jin_render.v2.full import render_full

REPO_ROOT = Path(__file__).resolve().parents[2]
PROGRAMS = sorted((REPO_ROOT / "examples-v2").glob("*/*.jin")) + sorted(
    (REPO_ROOT / "tests/fixtures/v2-programs").glob("*.jin")
)


def test_the_round_trip_covers_the_review_focus_fixtures() -> None:
    names = {p.stem for p in PROGRAMS}
    assert {"root_not_first", "nested_blocks"} <= names


@pytest.mark.parametrize("path", PROGRAMS, ids=lambda p: p.stem)
def test_the_full_circle_png_reads_back_byte_for_byte(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    model = check_text(text, path.name).model
    assert isinstance(model, JinFileV2)
    png = cairosvg.svg2png(
        bytestring=render_full(model).encode(), scale=2, background_color="white"
    )
    scene = decode_png(png)
    parsed, diagnostics = parse_scene(scene, file=f"{path.stem}.jinscene.json")
    assert [(d.code, d.pointer, d.message) for d in diagnostics] == []
    assert parsed is not None
    assert dumps(parsed) == dumps(model) == text
