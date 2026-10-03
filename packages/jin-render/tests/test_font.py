"""ラテン層のドット字形(`jin_render.v2.font`)。ASCII はプレイヤーの 5×7、それ以外は k6x8(spec §9 #25)。

字形のデータ `font_data.py` は `scripts/generate_glyphs.py` の生成物(プレイヤーの `font.ts` / `glyphs.ts` と同じ原本)。
"""

from __future__ import annotations

import re

from jin_render.v2.font import char_d, pixels
from jin_render.v2.font_data import ASCII

#: apps/player/src/font.ts の "A"(列ごと・bit0 が最上段)
A_COLUMNS = "7E1111117E"
BOX = (
    {(0, r) for r in range(7)}
    | {(4, r) for r in range(7)}
    | {(c, 0) for c in range(5)}
    | {(c, 6) for c in range(5)}
)


def from_hex(hex10: str) -> set[tuple[int, int]]:
    cols = [int(hex10[i : i + 2], 16) for i in range(0, 10, 2)]
    return {(c, r) for c, bits in enumerate(cols) for r in range(8) if bits >> r & 1}


def test_ascii_table_covers_the_printable_range() -> None:
    assert sorted(ASCII) == [chr(c) for c in range(0x20, 0x7F)]
    assert ASCII["A"] == A_COLUMNS


def test_pixels_of_ascii_follow_the_player_table() -> None:
    assert set(pixels("A")) == from_hex(A_COLUMNS)
    assert pixels(" ") == ()


def test_non_ascii_comes_from_k6x8() -> None:
    ma = set(pixels("ま"))
    assert ma
    assert all(0 <= c < 6 and 0 <= r < 8 for c, r in ma)


def test_a_missing_character_is_drawn_as_a_box() -> None:
    assert set(pixels("\U0001f600")) == BOX


def test_char_d_writes_three_decimals() -> None:
    d = char_d("A", 1.5, 2.25, 12.0)
    assert d
    for num in re.findall(r"-?\d+(?:\.\d+)?", d):
        assert re.fullmatch(r"-?\d+\.\d{3}", num), num
    assert char_d(" ", 0.0, 0.0, 12.0) == ""
