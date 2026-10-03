"""升の読み取り(`jin_glyph.cells.read_cell`)。完全陣と同じ描き方の升を PNG にして、元の字に戻ることを固定する。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jin_core.v2.glyph import STRUCT_MARK_OF
from jin_glyph.cells import duplicate_dot_groups, read_cell
from jin_render.v2.glyph_paths import GLYPH_PATHS

from .helpers import cell_image

REPO_ROOT = Path(__file__).resolve().parents[3]
STRUCT_IDS = set(STRUCT_MARK_OF.values()) | {"start"}
LATIN = [chr(c) for c in range(0x21, 0x7F)] + ["ま", "あ", "陣", "□"]


def kind_of(gid: str) -> str:
    return "struct" if gid in STRUCT_IDS else "glyph"


@pytest.mark.parametrize("scale", [2, 3, 4])
def test_every_line_glyph_reads_back(scale: int) -> None:
    for gid in GLYPH_PATHS:
        image, center, cell = cell_image(kind_of(gid), gid, scale)
        read = read_cell(image, center, cell)
        assert (read.t, read.v) == (kind_of(gid), gid), (scale, gid, read)


@pytest.mark.parametrize("scale", [2, 3, 4])
def test_every_latin_character_reads_back(scale: int) -> None:
    for ch in LATIN:
        image, center, cell = cell_image("latin", ch, scale)
        read = read_cell(image, center, cell)
        assert (read.t, read.v) == ("latin", ch), (scale, ch, read)


def test_an_empty_cell_is_empty() -> None:
    image, center, cell = cell_image("latin", " ", 2)
    assert read_cell(image, center, cell).t == "empty"


def test_no_fixture_string_uses_a_character_whose_dots_are_shared() -> None:
    # k6x8 の同じ点の並びの字は ASCII → 小さい符号位置に決めて読む。fixture の文字列にそういう字があれば往復しない
    shared = {ch for group in duplicate_dot_groups() for ch in group[1:]}
    programs = sorted((REPO_ROOT / "examples-v2").glob("*/*.jin")) + sorted(
        (REPO_ROOT / "tests/fixtures/v2-programs").glob("*.jin")
    )
    used = set(
        "".join(
            json.dumps(json.loads(p.read_text(encoding="utf-8")), ensure_ascii=False)
            for p in programs
        )
    )
    assert not (used & shared), sorted(used & shared)
