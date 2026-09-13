"""SVG の `d` 属性を組み立てる純関数（`docs/spec/layout.md` §4）。

v1 の `jin_render.layout` と v2 の `jin_render.v2` が**同じ関数**で線を引く。
数値はすべて `fmt_coord` を通す（座標を書き出す経路は 1 本・DP-JIN-SVG-DETERMINISM-01）。
楕円弧 `A` は使わず、円弧は `geometry.arc_segments` の 3 次ベジェで描く。
"""

from __future__ import annotations

import math

from jin_render import geometry as geo
from jin_render.svg import DASH, Node, fmt_coord

Point = tuple[float, float]


def move(point: Point) -> str:
    return f"M {fmt_coord(point[0])} {fmt_coord(point[1])}"


def line_to(point: Point) -> str:
    return f"L {fmt_coord(point[0])} {fmt_coord(point[1])}"


def curve_to(c1: Point, c2: Point, end: Point) -> str:
    return (
        f"C {fmt_coord(c1[0])} {fmt_coord(c1[1])} "
        f"{fmt_coord(c2[0])} {fmt_coord(c2[1])} "
        f"{fmt_coord(end[0])} {fmt_coord(end[1])}"
    )


def arc_d(frame: geo.Frame, radius: float, start_deg: float, sweep_deg: float) -> str:
    start, segments = geo.arc_segments(frame, radius, start_deg, sweep_deg)
    return " ".join([move(start)] + [curve_to(*segment) for segment in segments])


def square_d(frame: geo.Frame, angle_deg: float, radius: float, half: float) -> str:
    """半径方向と接線方向に辺を持つ正方形。`transform` を使わずに 4 頂点を直接計算する。"""
    cx, cy = geo.point(frame, radius, angle_deg)
    theta = math.radians(angle_deg)
    ux, uy = math.cos(theta), math.sin(theta)
    vx, vy = -math.sin(theta), math.cos(theta)
    size = half * frame.scale
    corners = [
        (cx + size * (ux + vx), cy + size * (uy + vy)),
        (cx + size * (-ux + vx), cy + size * (-uy + vy)),
        (cx + size * (-ux - vx), cy + size * (-uy - vy)),
        (cx + size * (ux - vx), cy + size * (uy - vy)),
    ]
    return " ".join(
        [move(corners[0]), line_to(corners[1]), line_to(corners[2]), line_to(corners[3]), "Z"]
    )


def diamond_d(frame: geo.Frame, radius: float) -> str:
    """枠の中心に置く菱形（v1 の `flow.exit` の印）。4 頂点を直接計算する。"""
    size = radius * frame.scale
    cx, cy = frame.cx, frame.cy
    corners = [(cx, cy - size), (cx + size, cy), (cx, cy + size), (cx - size, cy)]
    return " ".join(
        [move(corners[0]), line_to(corners[1]), line_to(corners[2]), line_to(corners[3]), "Z"]
    )


def polygon_d(center: Point, radius_px: float, count: int, step: int, start_deg: float) -> str:
    """中心 `center`・外接半径 `radius_px` の閉多角形。`step > 1` なら星形 {count/step}。

    頂点は `start_deg` から時計回りに等角で置き、`i -> (i + step) mod count` の順に結ぶ
    （`gcd(count, step) == 1` のとき 1 筆で全頂点を通る・layout.md §2.1）。
    """
    vertices = []
    for index in range(count):
        theta = math.radians(start_deg + 360.0 * index / count)
        vertices.append(
            (center[0] + radius_px * math.cos(theta), center[1] + radius_px * math.sin(theta))
        )
    order = [(index * step) % count for index in range(count)]
    parts = [move(vertices[order[0]])]
    parts += [line_to(vertices[position]) for position in order[1:]]
    parts.append("Z")
    return " ".join(parts)


def arrow_d(start: Point, end: Point, gap_start: float, gap_end: float, head: float) -> str | None:
    """両端を `gap_*` だけ詰めた線分。`head > 0` なら終端に矢じりを足す。

    詰めたあとに長さが残らない（節が重なっている）ときは `None`（描かない）。
    """
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= gap_start + gap_end:
        return None
    ux, uy = dx / length, dy / length
    tail = (start[0] + ux * gap_start, start[1] + uy * gap_start)
    tip = (end[0] - ux * gap_end, end[1] - uy * gap_end)
    parts = [move(tail), line_to(tip)]
    if head > 0.0:
        back = (tip[0] - ux * head, tip[1] - uy * head)
        wing = head * 0.5
        nx, ny = -uy, ux
        parts += [
            move((back[0] + nx * wing, back[1] + ny * wing)),
            line_to(tip),
            line_to((back[0] - nx * wing, back[1] - ny * wing)),
        ]
    return " ".join(parts)


def dot(center: Point, radius: float, pointer: str, kind: str, *, ref: str | None) -> Node:
    """参照の点。`ref` が `None` なら解決できない参照で、破線の空円（layout.md §5）。"""
    attrs = [
        ("cx", fmt_coord(center[0])),
        ("cy", fmt_coord(center[1])),
        ("r", fmt_coord(radius)),
    ]
    if ref is None:
        attrs.append(("stroke-dasharray", DASH))
    return Node("circle", attrs, pointer=pointer, kind=kind, ref=ref)


__all__ = [
    "Point",
    "arc_d",
    "arrow_d",
    "curve_to",
    "diamond_d",
    "dot",
    "line_to",
    "move",
    "polygon_d",
    "square_d",
]
