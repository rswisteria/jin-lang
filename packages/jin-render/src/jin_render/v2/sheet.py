"""型紙(モード 2)の SVG(陣書き S4・`jin render --sheet S|M`・glyph 設計書 §2.5・正典 glyph.md §10)。

幾何は `jin_render.v2.sheet_layout.sheet_layout` だけから取る(写真から升を切り出す `jin_glyph.recognize` と同じ表)。
刷るもの: 額縁・四隅の護符(完全陣と同じ `talisman_nodes`)・等級の印・各環の核の円と 12 の目盛りと始まりの印・
書く升の枠・続きの帯の番号。`<text>` は使わない(字はドットの清書体)。

**色は黒の 1 色で、案内(升の枠・目盛り・番号・環の名前)は `stroke-opacity` / `fill-opacity` を下げて薄く刷る**。
読み取りは升の内側だけを見るので、薄い枠はペンの線と混ざらない(2 色 + 強調 1 色の規律の範囲)。
"""

from __future__ import annotations

import math

from jin_core.v2.glyph import START_MARK
from jin_core.v2.model import JinFileV2

from jin_render import geometry as base
from jin_render.svg import INK, Node, document, fmt_coord
from jin_render.v2 import shapes
from jin_render.v2.font import char_d
from jin_render.v2.full import _Canvas, _cell_node, _square_d, talisman_nodes
from jin_render.v2.glyph_paths import glyph_d
from jin_render.v2.sheet_layout import (
    SHEET_GRADE_CELL,
    Grade,
    Ring,
    Sheet,
    fill_sheet,
    sheet_layout,
)

#: 案内の線と字の濃さ(升の枠・目盛り・帯の番号・環の名前)
GUIDE_OPACITY = "0.35"
#: 升の枠の一辺(升。隣の升との間に隙間を残す)
CELL_FRAME = 0.9
#: 環の名前(核の円の中の 2 字)の 1 字の大きさ(升)
RING_LABEL = 1.0
#: 目盛りの長さ(升)
TICK = 0.4


def _guide_group(pointer: str, kind: str) -> Node:
    group = shapes.group(pointer, kind)
    group.attrs.append(("stroke-opacity", GUIDE_OPACITY))
    return group


def _dots(
    canvas: _Canvas,
    text: str,
    center: tuple[float, float],
    size: float,
    pointer: str,
    kind: str,
    *,
    guide: bool,
) -> Node | None:
    """字の並びをドットの清書体で中央に描く(1 字 size 升)。"""
    x0 = center[0] - size * len(text) / 2.0
    y0 = center[1] - size / 2.0
    parts = []
    for i, ch in enumerate(text):
        px, py = canvas.px(x0 + i * size, y0)
        d = char_d(ch, px, py, size * canvas.unit)
        if d:
            parts.append(d)
    if not parts:
        return None
    attrs = [("d", " ".join(parts)), ("fill", INK), ("stroke", "none")]
    if guide:
        attrs.append(("fill-opacity", GUIDE_OPACITY))
    return Node("path", attrs, pointer=pointer, kind=kind, accent_attr="fill")


def _cell_frames(
    canvas: _Canvas, centers: list[tuple[float, float]], pointer: str, kind: str
) -> Node:
    h = CELL_FRAME / 2.0
    d = " ".join(_square_d(canvas, x - h, y - h, x + h, y + h) for x, y in centers)
    return shapes.path(d, pointer, kind)


def _ring_label(ring: Ring) -> str:
    if ring.owner.startswith("c"):
        return "陣" + str(int(ring.owner[1:]) + 1)
    return "手" + str(int(ring.owner.split("_")[1]) + 1)


def _ring(canvas: _Canvas, sheet: Sheet, ring: Ring) -> list[Node]:
    cx, cy = ring.center
    unit = canvas.unit
    solid = shapes.group(ring.pointer, "circle")
    solid.children.append(
        shapes.circle(canvas.px(cx, cy), ring.diagram * unit, ring.pointer, "circle")
    )
    guide = _guide_group(ring.pointer, "circle")
    # 12 の目盛り(銘環の 1 周目の内縁から内へ)
    ticks = []
    for k in range(12):
        rad = math.radians(base.TOP_ANGLE + 30.0 * k)
        a = canvas.px(
            cx + (ring.inner - TICK) * math.cos(rad), cy + (ring.inner - TICK) * math.sin(rad)
        )
        b = canvas.px(cx + ring.inner * math.cos(rad), cy + ring.inner * math.sin(rad))
        ticks.append(f"M{fmt_coord(a[0])} {fmt_coord(a[1])} L{fmt_coord(b[0])} {fmt_coord(b[1])}")
    guide.children.append(shapes.path(" ".join(ticks), ring.pointer, "circle"))
    slots = sheet.of(ring.owner)
    guide.children.append(
        _cell_frames(canvas, [s.center for s in slots if s.kind == "cell"], ring.pointer, "circle")
    )
    label = _dots(
        canvas, _ring_label(ring), (cx, cy), RING_LABEL, ring.pointer, "circle", guide=True
    )
    if label is not None:
        guide.children.append(label)
    for s in slots:
        if s.kind == "start":
            x0, y0 = canvas.px(s.center[0] - 0.5, s.center[1] - 0.5)
            solid.children.append(
                shapes.path(glyph_d(START_MARK, x0, y0, unit), ring.pointer, "circle")
            )
    return [guide, solid]


def _filled(canvas: _Canvas, sheet: Sheet, model: JinFileV2) -> Node:
    """写し書きの手本: プログラムの銘帯を升に清書体で書き込む(`fill_sheet`)。"""
    group = shapes.group("/stage", "stage")
    centers = {(s.owner, s.index): s.center for s in sheet.slots}
    for key, cell in fill_sheet(sheet, model).items():
        node = _cell_node(canvas, cell, centers[key])
        if node is not None:
            group.children.append(node)
    return group


def render_sheet(grade: Grade, model: JinFileV2 | None = None) -> str:
    """等級の型紙の SVG。`model` を渡すとその銘帯を書き込んだ手本になる(収まらなければ `SheetOverflow`)。
    同じ入力から常に同じバイト列。"""
    sheet = sheet_layout(grade)
    canvas = _Canvas(sheet.half)
    half = sheet.half
    stage = shapes.group("/stage", "stage")
    stage.children.append(
        shapes.path(_square_d(canvas, -half, -half, half, half), "/stage", "stage")
    )
    stage.children.extend(talisman_nodes(canvas))
    mark = _dots(
        canvas, grade, sheet.grade_mark(), SHEET_GRADE_CELL, "/stage", "stage", guide=False
    )
    if mark is not None:
        stage.children.append(mark)
    guide = _guide_group("/stage", "stage")
    guide.children.append(
        _cell_frames(canvas, [s.center for s in sheet.of("frame")], "/stage", "stage")
    )
    strips = [o for o in sheet.owners() if o.startswith("strip")]
    cells = [s.center for o in strips for s in sheet.of(o) if s.kind == "cell"]
    if cells:
        guide.children.append(_cell_frames(canvas, cells, "/stage", "stage"))
    for n, owner in enumerate(strips, start=1):
        head = sheet.of(owner)[0]
        number = str(n)
        node = _dots(canvas, number, head.center, 1.0 / len(number), "/stage", "stage", guide=True)
        if node is not None:
            guide.children.append(node)
    body = [stage, guide]
    for ring in sheet.rings:
        body.extend(_ring(canvas, sheet, ring))
    if model is not None:
        body.append(_filled(canvas, sheet, model))
    return document([], body, 2.0 * half * canvas.unit)


__all__ = ["render_sheet"]
