"""完全陣: プログラムの情報をすべて載せた 1 枚の SVG(陣書き S2・glyph 設計書 §2・正典 glyph.md §8)。

既存の陣の図と手順の図を**そのまま**使い(入れ子の参照は点になる深さ 1 で描く)、`<text>` を取り除いてから、
連環陣の位置に置き、外周に銘環を巡らせる。既存の出力(`render_v2`)には触れない。

描く順(後が上): 額縁 → 四隅の護符 → 額縁の銘帯 → 円どうしを結ぶ線 → 陣の図 → 手順陣の図 → 銘環の升。
座標は升の単位で決め、`FULL_CELL_PX` 倍して `fmt_coord` で書く。`<text>` は 1 つも出さない(銘文は線の紋とドットの字)。
円どうしを結ぶ線は、陣と手順陣のへその緒・`summon` の道具 → 呼ぶ手順陣・flow の弦・委譲の 4 種(参照の正本は銘文)。
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from jin_core.v2.model import JinFileV2

from jin_render import geometry as geo
from jin_render.svg import INK, Node, document, fmt_coord
from jin_render.v2 import geometry as g2
from jin_render.v2 import shapes
from jin_render.v2.font import char_d
from jin_render.v2.full_layout import (
    Placement,
    RingCell,
    circle_inner,
    place,
    ring_cells,
    rite_inner,
)
from jin_render.v2.glyph_paths import glyph_d
from jin_render.v2.inscribe import InkCell, circle_ring, frame_band, rite_ring
from jin_render.v2.layout import BUILTIN_FORMS, _Builder
from jin_render.v2.rite import draw_rite

_TEXT_TAGS = ("text", "textPath")


def _without_text(node: Node) -> Node:
    """`<text>` / `<textPath>` を木から取り除く(完全陣は文字をすべて線とドットで描く)。"""
    node.children = [_without_text(child) for child in node.children if child.tag not in _TEXT_TAGS]
    return node


class _Canvas:
    """升の座標(原点が額縁の中心)を px に写す。"""

    def __init__(self, half: float) -> None:
        self.half = half
        self.unit = g2.FULL_CELL_PX

    def px(self, x: float, y: float) -> tuple[float, float]:
        return ((x + self.half) * self.unit, (y + self.half) * self.unit)

    def frame(self, x: float, y: float) -> geo.Frame:
        cx, cy = self.px(x, y)
        return geo.Frame(cx, cy, g2.FULL_DIAGRAM_R * self.unit)


def _square_d(canvas: _Canvas, x0: float, y0: float, x1: float, y1: float) -> str:
    a, b = canvas.px(x0, y0)
    c, d = canvas.px(x1, y1)
    return (
        f"M{fmt_coord(a)} {fmt_coord(b)} L{fmt_coord(c)} {fmt_coord(b)} "
        f"L{fmt_coord(c)} {fmt_coord(d)} L{fmt_coord(a)} {fmt_coord(d)} Z"
    )


def _cell_node(canvas: _Canvas, cell: InkCell, center: tuple[float, float]) -> Node | None:
    x0, y0 = canvas.px(center[0] - 0.5, center[1] - 0.5)
    if cell.t == "latin":
        d = char_d(cell.v, x0, y0, canvas.unit)
        if not d:
            return None
        return Node(
            "path",
            [("d", d), ("fill", INK), ("stroke", "none")],
            pointer=cell.pointer,
            kind=cell.kind,
            accent_attr="fill",
        )
    return Node(
        "path", [("d", glyph_d(cell.v, x0, y0, canvas.unit))], pointer=cell.pointer, kind=cell.kind
    )


def _ring_group(canvas: _Canvas, pointer: str, kind: str, placed: Sequence[RingCell]) -> Node:
    group = shapes.group(pointer, kind)
    for item in placed:
        node = _cell_node(canvas, item.cell, item.center)
        if node is not None:
            group.children.append(node)
    return group


def _frame_positions(count: int, half: float) -> list[tuple[float, float]]:
    """額縁の銘帯の升の中心: 額縁の内側を左上から時計回りに巡る(四隅の護符の区画は飛ばす)。足りなければ内側の周へ。"""
    out: list[tuple[float, float]] = []
    inset = 1.5
    while len(out) < count:
        h = half - inset
        lo, hi = -h + g2.FULL_TALISMAN + 0.5, h - g2.FULL_TALISMAN - 0.5
        steps = max(0, math.floor(hi - lo) + 1)
        edge = [lo + k for k in range(steps)]
        ring = (
            [(x, -h) for x in edge]
            + [(h, y) for y in edge]
            + [(x, h) for x in reversed(edge)]
            + [(-h, y) for y in reversed(edge)]
        )
        if not ring:
            break
        out += ring
        inset += g2.FULL_RING_PITCH
    return out[:count]


def _stage(canvas: _Canvas, model: JinFileV2) -> Node:
    half = canvas.half
    group = shapes.group("/stage", "stage")
    group.children.append(
        shapes.path(_square_d(canvas, -half, -half, half, half), "/stage", "stage")
    )
    t = g2.FULL_TALISMAN
    corners = ((-half, -half), (half - t, -half), (-half, half - t), (half - t, half - t))
    for n, (x, y) in enumerate(corners):
        group.children.append(
            shapes.path(
                _square_d(canvas, x + 0.2, y + 0.2, x + t - 0.2, y + t - 0.2), "/stage", "stage"
            )
        )
        cx, cy = canvas.px(x + t / 2, y + t / 2)
        if n == 1:  # 右上だけ丸(向きの印)
            group.children.append(
                shapes.circle((cx, cy), 0.6 * canvas.unit, "/stage", "stage", filled=True)
            )
        else:
            group.children.append(
                Node(
                    "path",
                    [
                        (
                            "d",
                            _square_d(
                                canvas,
                                x + t / 2 - 0.6,
                                y + t / 2 - 0.6,
                                x + t / 2 + 0.6,
                                y + t / 2 + 0.6,
                            ),
                        ),
                        ("fill", INK),
                    ],
                    pointer="/stage",
                    kind="stage",
                    accent_attr="fill",
                )
            )
    cells = frame_band(model)
    for cell, center in zip(cells, _frame_positions(len(cells), half), strict=False):
        node = _cell_node(canvas, cell, center)
        if node is not None:
            group.children.append(node)
    return group


def _link(
    canvas: _Canvas,
    a: tuple[float, float],
    ra: float,
    b: tuple[float, float],
    rb: float,
    pointer: str,
    kind: str,
    *,
    dashed: bool = False,
) -> Node | None:
    """2 つの円を、互いの最外周の外で結ぶ線(重なる・近すぎるときは描かない)。"""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length <= ra + rb:
        return None
    ux, uy = dx / length, dy / length
    sx, sy = canvas.px(a[0] + ux * ra, a[1] + uy * ra)
    ex, ey = canvas.px(b[0] - ux * rb, b[1] - uy * rb)
    return shapes.line((sx, sy), (ex, ey), pointer, kind, dashed=dashed)


def _links(
    canvas: _Canvas, model: JinFileV2, placement: Placement, index_of: dict[str, int]
) -> list[Node]:
    out: list[Node | None] = []
    for ci, circle in enumerate(model.circles):
        center, radius = placement.circles[ci], placement.circle_radius[ci]
        for ri in range(len(circle.rites)):
            out.append(
                _link(
                    canvas,
                    center,
                    radius,
                    placement.rites[(ci, ri)],
                    placement.rite_radius[(ci, ri)],
                    f"/circles/{ci}/rites/{ri}",
                    "rite",
                )
            )
        for j, sigil in enumerate(circle.sigils):
            if sigil.kind != "summon" or sigil.circle not in index_of:
                continue
            target = index_of[sigil.circle]
            found = [
                k for k, rite in enumerate(model.circles[target].rites) if rite.name == sigil.rite
            ]
            key = (target, found[0]) if found else None
            if key is None:
                continue
            out.append(
                _link(
                    canvas,
                    center,
                    radius,
                    placement.rites[key],
                    placement.rite_radius[key],
                    f"/circles/{ci}/sigils/{j}",
                    "sigil",
                    dashed=True,
                )
            )
        if circle.flow is not None:
            for j, name in enumerate(circle.flow.steps):
                if name in index_of and index_of[name] != ci:
                    t = index_of[name]
                    out.append(
                        _link(
                            canvas,
                            center,
                            radius,
                            placement.circles[t],
                            placement.circle_radius[t],
                            f"/circles/{ci}/flow/steps/{j}",
                            "flow-edge",
                        )
                    )
        for j, name in enumerate(circle.delegate):
            if name in index_of and index_of[name] != ci:
                t = index_of[name]
                out.append(
                    _link(
                        canvas,
                        center,
                        radius,
                        placement.circles[t],
                        placement.circle_radius[t],
                        f"/circles/{ci}/delegate/{j}",
                        "delegate",
                        dashed=True,
                    )
                )
    return [node for node in out if node is not None]


def render_full(model: JinFileV2) -> str:
    """完全陣の SVG。schema を通るモデルなら意味エラーを含んでいても例外を投げない。"""
    placement = place(model)
    canvas = _Canvas(placement.half)
    index_of: dict[str, int] = {}
    for position, circle in enumerate(model.circles):
        index_of.setdefault(circle.name, position)
    form_names = frozenset(form.name for form in model.forms) | frozenset(BUILTIN_FORMS)
    builder = _Builder(model=model, index_of=index_of, form_names=form_names)

    body: list[Node] = [_stage(canvas, model)]
    links = shapes.group("/circles", "circle")  # 線の既定(黒・1 px)を効かせる入れ物
    links.children.extend(_links(canvas, model, placement, index_of))
    body.append(links)
    for ci, (x, y) in placement.circles.items():
        body.append(_without_text(builder.draw_circle(ci, canvas.frame(x, y), 1)))
        placed = ring_cells(circle_ring(model, ci), x, y, circle_inner())
        body.append(_ring_group(canvas, f"/circles/{ci}", "circle", placed))
    for (ci, ri), (x, y) in placement.rites.items():
        body.append(_without_text(draw_rite(model, ci, ri, canvas.frame(x, y), index_of)))
        placed = ring_cells(rite_ring(model, ci, ri), x, y, rite_inner())
        body.append(_ring_group(canvas, f"/circles/{ci}/rites/{ri}", "circle", placed))
    return document([], body, 2.0 * placement.half * canvas.unit)


__all__ = ["render_full"]
