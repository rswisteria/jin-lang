"""完全陣のラテン層の清書体: 1 字を 6×8 の点で描く(glyph 設計書 §9 #25・プレイヤーの `canvas.text` と同じ字形)。

ASCII(U+0020〜U+007E)は `font_data.ASCII` の 5×7、それ以外は k6x8(`font_data.CODEPOINTS` / `BITMAPS`)、
どちらにも無い字は □(プレイヤーの `BOX` と同じ)。点は升の中央に 8 × 8 の格子で置き、1 点を塗った正方形にする。
base64 の展開は import のときに 1 回だけ行い、結果は変更できない値(bytes とタプル)として持つ。
"""

from __future__ import annotations

import base64
from bisect import bisect_left

from jin_render.svg import fmt_coord
from jin_render.v2.font_data import ASCII, BITMAPS, CODEPOINTS

GRID = 8  # 升を 8 × 8 の格子に割り、字形の 6 列を中央に置く
_BOX = "7F4141417F"
_PACKED = base64.b64decode(CODEPOINTS)
_CODES: tuple[int, ...] = tuple(
    int.from_bytes(_PACKED[i : i + 2], "big") for i in range(0, len(_PACKED), 2)
)
_BITMAPS = base64.b64decode(BITMAPS)


def _columns(ch: str) -> bytes:
    if ch in ASCII:
        return bytes.fromhex(ASCII[ch])
    index = bisect_left(_CODES, ord(ch))
    if index < len(_CODES) and _CODES[index] == ord(ch):
        return _BITMAPS[index * 6 : index * 6 + 6]
    return bytes.fromhex(_BOX)


def pixels(ch: str) -> tuple[tuple[int, int], ...]:
    """字の点 (列, 行) の並び(列 0〜5・行 0〜7・左上が原点)。"""
    return tuple(
        (col, row) for col, bits in enumerate(_columns(ch)) for row in range(8) if bits >> row & 1
    )


def char_d(ch: str, x: float, y: float, size: float) -> str:
    """字を左上 (x, y)・一辺 size の升に描く `d`(点ごとの閉じた正方形。塗って使う)。点が無ければ空文字。"""
    p = size / GRID
    left = x + p  # 6 列を 8 列の中央に置く
    parts = []
    for col, row in pixels(ch):
        x0, y0 = left + col * p, y + row * p
        x1, y1 = x0 + p, y0 + p
        parts.append(
            f"M{fmt_coord(x0)} {fmt_coord(y0)} L{fmt_coord(x1)} {fmt_coord(y0)} "
            f"L{fmt_coord(x1)} {fmt_coord(y1)} L{fmt_coord(x0)} {fmt_coord(y1)} Z"
        )
    return " ".join(parts)


__all__ = ["GRID", "char_d", "pixels"]
