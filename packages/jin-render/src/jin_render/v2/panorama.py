"""全景: すべての陣の図とすべての手順の図を 1 枚に並べた SVG(鑑賞ページの全景・正典 stage.md §2.3・Issue #132)。

既定の図(`render_v2`)は v2 layout.md §1 のとおり深さ 1 まで展開して以下は点にするので、手順の中身・孫の陣・
`summon` だけで使う陣が描かれない。全景は完全陣(`jin_render.v2.full`)と**同じ配置**(`full_layout.place`)に、
陣の図・手順の図・円どうしを結ぶ線・額縁を描き、銘文は描かない(名前の `<text>` は残す)。

全景の銘(`render_panorama_inscription`)は同じ座標系に額縁の銘帯と陣 / 手順ごとの銘環(詠唱帯を含む)だけを描く。
全景と全景の銘を重ねると完全陣と同じ絵になる(`<text>` と四隅の護符を除く)。配置は銘環の大きさ込みで決まるので、
銘を出さない全景では陣の周りに銘環の分の余白が残る(鑑賞ページの「銘」で埋まる)。

純関数で、完全陣・既定の図・鑑賞ページの帯(`jin_render.v2.inscription`)の出力には触れない。
"""

from __future__ import annotations

from jin_core.v2.model import JinFileV2

from jin_render.svg import Node, document
from jin_render.v2 import shapes
from jin_render.v2.full import (
    _Canvas,
    _cell_node,
    _frame_band_nodes,
    _links,
    _ring_group,
    _roles,
    _square_d,
)
from jin_render.v2.full_layout import (
    circle_inner,
    frame_positions,
    place,
    ring_cells,
    rite_inner,
)
from jin_render.v2.layout import circle_drawer, circle_index
from jin_render.v2.rite import draw_rite


def render_panorama(model: JinFileV2) -> str:
    """全景の SVG。schema を通るモデルなら意味エラーを含んでいても例外を投げない。"""
    placement = place(model)
    canvas = _Canvas(placement.half)
    index_of = circle_index(model)
    draw_circle = circle_drawer(model)
    half = canvas.half
    stage = shapes.group("/stage", "stage")
    stage.children.append(
        shapes.path(_square_d(canvas, -half, -half, half, half), "/stage", "stage")
    )
    body: list[Node] = [stage]
    links = shapes.group("/circles", "circle")  # 線の既定(黒・1 px)を効かせる入れ物
    links.children.extend(_links(canvas, model, placement, index_of))
    body.append(links)
    for ci, (x, y) in placement.circles.items():
        body.append(draw_circle(ci, canvas.frame(x, y), 1))
    for (ci, ri), (x, y) in placement.rites.items():
        body.append(draw_rite(model, ci, ri, canvas.frame(x, y), index_of))
    return document([], body, 2.0 * placement.half * canvas.unit)


def render_panorama_inscription(model: JinFileV2) -> str:
    """全景の銘の SVG(全景と同じ座標系)。額縁の銘帯 → 陣の銘環 → 手順の銘環の順。"""
    placement = place(model)
    canvas = _Canvas(placement.half)
    cells = placement.inscription.frame
    stage = shapes.group("/stage", "stage")
    centers = frame_positions(len(cells), canvas.half)
    stage.children.extend(_frame_band_nodes(canvas, cells, centers))
    for cell, center, role in zip(cells, centers, _roles(cells), strict=True):
        node = _cell_node(canvas, cell, center, bead=role == "in")
        if node is not None:
            stage.children.append(node)
    body: list[Node] = [stage]
    for ci, (x, y) in placement.circles.items():
        placed = ring_cells(placement.inscription.circles[ci], x, y, circle_inner())
        body.append(_ring_group(canvas, f"/circles/{ci}", "circle", placed, (x, y), circle_inner()))
    for (ci, ri), (x, y) in placement.rites.items():
        placed = ring_cells(placement.inscription.rites[(ci, ri)], x, y, rite_inner())
        body.append(
            _ring_group(canvas, f"/circles/{ci}/rites/{ri}", "circle", placed, (x, y), rite_inner())
        )
    return document([], body, 2.0 * placement.half * canvas.unit)


__all__ = ["render_panorama", "render_panorama_inscription"]
