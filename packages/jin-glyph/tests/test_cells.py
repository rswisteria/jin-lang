"""升の読み取り(`jin_glyph.cells.read_cell`)。完全陣と同じ描き方の升を PNG にして、元の字に戻ることを固定する。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jin_core.v2.glyph import STRUCT_MARK_OF
from jin_glyph.cells import duplicate_dot_groups, read_cell
from jin_render.v2.glyph_paths import GLYPH_PATHS
from jin_render.v2.inscribe import expr_cells, to_expr

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


def test_a_character_whose_dots_are_shared_is_inscribed_by_its_code_point() -> None:
    # k6x8 の同じ点の並びの字は ASCII → 小さい符号位置(組の先頭)に読む。組の先頭でない字は銘文が esc u で書くので往復する
    shared = [ch for group in duplicate_dot_groups() for ch in group[1:]]
    assert shared
    text = json.dumps("".join(shared), ensure_ascii=False)
    cells = expr_cells(text, "/x", "step")
    assert [c.v for c in cells if c.t == "glyph"].count("esc") == len(shared)
    assert json.loads(to_expr(cells)) == "".join(shared)


@pytest.mark.parametrize("dx, dy", [(1, 0), (-1, 0), (0, 1), (0, -1)])
def test_a_cell_off_by_one_grid_step_still_reads_back(dx: int, dy: int) -> None:
    # S3: デコーダの 1 回目の中心は 0.04 升ほどずれる。倍率 2 では格子 1 目(升の 1/24 = 1 px)。線の字だけずれを吸うと
    # ドットの字が線の字に負けた(o → flow_loop・othello の陣の核)
    for t, v in [(kind_of(gid), gid) for gid in GLYPH_PATHS] + [("latin", ch) for ch in LATIN]:
        image, (cx, cy), cell = cell_image(t, v, 2)
        read = read_cell(image, (cx + dx * cell / 24, cy + dy * cell / 24), cell)
        assert (read.t, read.v) == (t, v), (dx, dy, v, read)
