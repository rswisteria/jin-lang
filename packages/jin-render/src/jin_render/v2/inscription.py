"""鑑賞ページの銘環の帯(陣書き S7・glyph 設計書 §6 / §9 #52〜・正典 stage.md §2.2)。

プログラムの銘文(額縁の銘帯 → 陣ごとに陣の銘環 → 手順の銘環・モデルの順)を 1 本の帯につなぎ、
通常の図(`render_v2`)と**同じ座標系**(1000 px 四方・中心 (500, 500)・正規化 1.0 = 400 px)の
環 `BAND_INNER` 〜 `BAND_OUTER` に螺旋で並べた SVG。鑑賞ページはこれを写すだけで升を置き直さない。

- 升の中身は完全陣と同じ `inscribe`(`frame_band` / `circle_ring` / `rite_ring`)、並べ方は完全陣の銘環と同じ
  `full_layout.ring_cells`(12 時に始まりの印・時計回り・周の終わりの継ぎの紋で外の周へ)。違うのは大きさだけで、
  升の一辺は帯に収まる最大の値(`BAND_CELL_MAX` で頭打ち)
- 升は持ち主の pointer(欄の pointer)と kind(13 種のまま)を持つ。`<text>` は出さない
- 純関数。完全陣・型紙の出力には触れない(往復の契約のバイト一致はそのまま)
"""

from __future__ import annotations

from jin_core.v2.model import JinFileV2

from jin_render import geometry as geo
from jin_render.svg import INK, Node, document
from jin_render.v2 import shapes
from jin_render.v2.font import char_d
from jin_render.v2.full_layout import ring_cells, ring_outer
from jin_render.v2.glyph_paths import glyph_d
from jin_render.v2.inscribe import InkCell, circle_ring, frame_band, rite_ring

#: 帯の内縁。手順の図の環の外へ抜ける線の先(0.95 + 0.05 + 0.07 = 1.07・`STEP_TAIL`)より外。
BAND_INNER = 1.10
#: 帯の外縁。鑑賞ページが陣を収める半径 1.45(stage.md §4)の内。額縁(半辺 1.18)とは高さで分ける。
BAND_OUTER = 1.30
#: 升の一辺の上限(短い銘文で字が額縁ほどに大きくならないように)。
BAND_CELL_MAX = 0.06
#: 升の一辺を探す刻み(上限から 1 刻みずつ縮め、収まった最初の値)。
_SHRINK = 0.97


def band_cells(model: JinFileV2) -> list[InkCell]:
    """帯に並べる升の列(額縁の銘帯 → 陣ごとに陣の銘環 → その手順の銘環)。"""
    cells = list(frame_band(model))
    for ci, circle in enumerate(model.circles):
        cells += circle_ring(model, ci)
        for ri in range(len(circle.rites)):
            cells += rite_ring(model, ci, ri)
    return cells


def band_cell_size(count: int) -> float:
    """count 字の帯の升の一辺(正規化単位)。最外周の外縁(完全陣と同じ `ring_outer`)が `BAND_OUTER` に収まる最大の値。"""
    size = BAND_CELL_MAX
    while True:
        if ring_outer(count, BAND_INNER / size) * size <= BAND_OUTER:
            return size
        size *= _SHRINK


def render_inscription(model: JinFileV2) -> str:
    """銘環の帯の SVG。schema を通るモデルなら意味エラーを含んでいても例外を投げない。"""
    cells = band_cells(model)
    size = band_cell_size(len(cells))
    unit = geo.UNIT_PX * size  # 升 1 つの px
    center = geo.CANVAS_PX / 2.0
    group = shapes.group("/stage", "stage")  # 線の既定(黒・1 px)を効かせる入れ物
    for item in ring_cells(cells, 0.0, 0.0, BAND_INNER / size):
        x0 = center + (item.center[0] - 0.5) * unit
        y0 = center + (item.center[1] - 0.5) * unit
        cell = item.cell
        if cell.t == "latin":
            d = char_d(cell.v, x0, y0, unit)
            if d:
                group.children.append(
                    Node(
                        "path",
                        [("d", d), ("fill", INK), ("stroke", "none")],
                        pointer=cell.pointer,
                        kind=cell.kind,
                        accent_attr="fill",
                    )
                )
            continue
        group.children.append(
            Node(
                "path", [("d", glyph_d(cell.v, x0, y0, unit))], pointer=cell.pointer, kind=cell.kind
            )
        )
    return document([], [group], geo.CANVAS_PX)


__all__ = [
    "BAND_CELL_MAX",
    "BAND_INNER",
    "BAND_OUTER",
    "band_cell_size",
    "band_cells",
    "render_inscription",
]
