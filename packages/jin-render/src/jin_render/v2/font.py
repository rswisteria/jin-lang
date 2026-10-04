"""完全陣のラテン層の清書体: 1 字を 6×8 の点で描く(glyph 設計書 §9 #25・プレイヤーの `canvas.text` と同じ字形)。

ASCII(U+0020〜U+007E)は `font_data.ASCII` の 5×7、それ以外は k6x8(`font_data.CODEPOINTS` / `BITMAPS`)、
どちらにも無い字は □(プレイヤーの `BOX` と同じ)。点は升の中央に 8 × 8 の格子で置き、1 点を塗った正方形にする。
ASCII の 5 列の字形は 6 列の枠の左詰め(k6x8 の字と半列ずれて見える)。**中央に寄せない**: 寄せるには半点ずらす必要があり、
デコーダ(`jin_glyph.cells`)が読む 8 × 8 の格子から外れる。プレイヤーの `canvas.text` も 6 幅の送りに左詰めで描く(#119 で判断)。
base64 の展開は import のときに 1 回だけ行い、結果は変更できない値(bytes とタプル)として持つ。
"""

from __future__ import annotations

import base64
import functools
from bisect import bisect_left

from jin_render.svg import fmt_coord
from jin_render.v2.font_data import ASCII, BITMAPS, CODEPOINTS

GRID = 8  # 升を 8 × 8 の格子に割り、字形の 6 列を中央に置く
#: 文字列の中身の字の点を描く珠の半径(格子 1 目に対して)。0.5 だと 1 目の 1/3 ずれた升で塗りの割合が読み取りのしきい値
#: (`jin_glyph.cells.DOT_FRACTION` = 0.5)すれすれになる。0.55 ならずれても 0.6 を超え、隣の目へのはみ出しは 0.1 未満(Issue #129)
BEAD_RADIUS = 0.55
_KAPPA = 0.5522847498
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


@functools.cache
def dot_groups() -> dict[tuple[tuple[int, int], ...], tuple[str, ...]]:
    """点の並び → その並びを持つ字の組(ASCII → k6x8 の小さい符号位置の順)。点の無い字は入らない。

    読み取り(`jin_glyph.cells`)は点の並びを組の先頭の字に読む。7001 字を展開するので初めて呼んだときに 1 回だけ作る。"""
    groups: dict[tuple[tuple[int, int], ...], list[str]] = {}
    for ch in [c for c in ASCII if c != " "] + [chr(code) for code in _CODES]:
        dots = pixels(ch)
        if dots:
            groups.setdefault(dots, []).append(ch)
    return {dots: tuple(chars) for dots, chars in groups.items()}


def readable(ch: str) -> bool:
    """升に描いた字が点の並びから同じ字に読み戻せるか(字形があり、同じ点の並びの組の先頭)。

    字形の無い字は □ で描かれ、□ と同じ点の字(囗)に読める。銘文はこれが偽の字を `esc u` + 符号位置で書く(S3)。"""
    group = dot_groups().get(pixels(ch))
    return group is not None and group[0] == ch


def char_d(ch: str, x: float, y: float, size: float, *, bead: bool = False) -> str:
    """字を左上 (x, y)・一辺 size の升に描く `d`(点ごとの閉じた図形。塗って使う)。点が無ければ空文字。

    点は既定で正方形、`bead` なら珠(格子の目の中心に半径 `BEAD_RADIUS` 目の円・3 次ベジェ 4 本)。珠は完全陣の
    文字列の中身にだけ使う(詠唱帯・glyph.md §8)。読み取りは目の塗りの割合を見るので、どちらも同じ字に読める。"""
    p = size / GRID
    left = x + p  # 6 列を 8 列の中央に置く
    parts = []
    for col, row in pixels(ch):
        x0, y0 = left + col * p, y + row * p
        if bead:
            parts.append(_bead_d(x0 + p / 2, y0 + p / 2, BEAD_RADIUS * p))
            continue
        x1, y1 = x0 + p, y0 + p
        parts.append(
            f"M{fmt_coord(x0)} {fmt_coord(y0)} L{fmt_coord(x1)} {fmt_coord(y0)} "
            f"L{fmt_coord(x1)} {fmt_coord(y1)} L{fmt_coord(x0)} {fmt_coord(y1)} Z"
        )
    return " ".join(parts)


def _bead_d(cx: float, cy: float, r: float) -> str:
    k = _KAPPA * r
    f = fmt_coord
    return (
        f"M{f(cx)} {f(cy - r)} "
        f"C{f(cx + k)} {f(cy - r)} {f(cx + r)} {f(cy - k)} {f(cx + r)} {f(cy)} "
        f"C{f(cx + r)} {f(cy + k)} {f(cx + k)} {f(cy + r)} {f(cx)} {f(cy + r)} "
        f"C{f(cx - k)} {f(cy + r)} {f(cx - r)} {f(cy + k)} {f(cx - r)} {f(cy)} "
        f"C{f(cx - r)} {f(cy - k)} {f(cx - k)} {f(cy - r)} {f(cx)} {f(cy - r)} Z"
    )


__all__ = ["BEAD_RADIUS", "GRID", "char_d", "dot_groups", "pixels", "readable"]
