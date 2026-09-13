"""v2 の図で繰り返し使う小さな要素（文字 / 円 / 線 / `<g>`）。

すべて `jin_render.svg.Node` を返す純関数。座標は呼び出し側が px にしてから渡す
（`fmt_coord` はここで通す）。文字は `stroke="none"` + `fill` で描き、強調は `fill` を差し替える
（v1 の rune と同じ・layout.md §6「強調の描き方」）。
"""

from __future__ import annotations

from jin_render.paths import Point, line_to, move
from jin_render.svg import DASH, FONT_FAMILY, INK, STROKE_WIDTH, Node, fmt_coord

#: 名前を切り詰めたことを示す記号（v1 の rune と同じ）。
ELLIPSIS = "…"


def initial(name: str) -> str:
    """頭文字（大文字）。`Name` は `[A-Za-z_][A-Za-z0-9_]*` なので 1 文字目は必ずある。"""
    return name[:1].upper()


def clip(name: str, max_chars: int) -> str:
    """`max_chars` を超える名前を決定的に切り詰める（`max_chars - 1` 文字 + `…`）。"""
    if len(name) <= max_chars:
        return name
    return name[: max_chars - 1] + ELLIPSIS


def group(pointer: str, kind: str) -> Node:
    """陣 / 手順の図の `<g>`。線の既定（黒・1 px・丸い端）をここに置く。"""
    return Node(
        "g",
        [
            ("fill", "none"),
            ("stroke", INK),
            ("stroke-width", fmt_coord(STROKE_WIDTH)),
            ("stroke-linecap", "round"),
            ("stroke-linejoin", "round"),
        ],
        pointer=pointer,
        kind=kind,
    )


def text(center: Point, size_px: float, content: str, pointer: str, kind: str) -> Node:
    """中央揃えの 1 行の文字。"""
    return Node(
        "text",
        [
            ("x", fmt_coord(center[0])),
            ("y", fmt_coord(center[1])),
            ("stroke", "none"),
            ("fill", INK),
            ("font-family", FONT_FAMILY),
            ("font-size", fmt_coord(size_px)),
            ("text-anchor", "middle"),
            ("dominant-baseline", "central"),
        ],
        pointer=pointer,
        kind=kind,
        text=content,
        accent_attr="fill",
    )


def circle(
    center: Point,
    radius_px: float,
    pointer: str,
    kind: str,
    *,
    dashed: bool = False,
    ref: str | None = None,
    filled: bool = False,
) -> Node:
    attrs = [
        ("cx", fmt_coord(center[0])),
        ("cy", fmt_coord(center[1])),
        ("r", fmt_coord(radius_px)),
    ]
    if dashed:
        attrs.append(("stroke-dasharray", DASH))
    if filled:
        attrs += [("stroke", "none"), ("fill", INK)]
    return Node(
        "circle",
        attrs,
        pointer=pointer,
        kind=kind,
        ref=ref,
        accent_attr="fill" if filled else "stroke",
    )


def line(start: Point, end: Point, pointer: str, kind: str, *, dashed: bool = False) -> Node:
    attrs = [
        ("x1", fmt_coord(start[0])),
        ("y1", fmt_coord(start[1])),
        ("x2", fmt_coord(end[0])),
        ("y2", fmt_coord(end[1])),
    ]
    if dashed:
        attrs.append(("stroke-dasharray", DASH))
    return Node("line", attrs, pointer=pointer, kind=kind)


def path(d: str, pointer: str, kind: str, *, dashed: bool = False, ref: str | None = None) -> Node:
    attrs = [("d", d)]
    if dashed:
        attrs.append(("stroke-dasharray", DASH))
    return Node("path", attrs, pointer=pointer, kind=kind, ref=ref)


def square_d_at(center: Point, half_px: float) -> str:
    """軸に平行な正方形（額縁と型紙の印章。角度を持たない）。"""
    cx, cy = center
    corners = [
        (cx - half_px, cy - half_px),
        (cx + half_px, cy - half_px),
        (cx + half_px, cy + half_px),
        (cx - half_px, cy + half_px),
    ]
    return " ".join(
        [move(corners[0]), line_to(corners[1]), line_to(corners[2]), line_to(corners[3]), "Z"]
    )


__all__ = [
    "ELLIPSIS",
    "circle",
    "clip",
    "group",
    "initial",
    "line",
    "path",
    "square_d_at",
    "text",
]
