"""完全陣の配置: 銘環の升の位置と、連環陣(陣の第 1 軌道・手順陣の第 2 軌道)の中心(glyph 設計書 §2)。

単位は升(銘環の 1 字)。純関数で、同じモデルから同じ配置を返す。

- 銘環: 1 周目の内縁は図の外接 + `FULL_RING_GAP`。1 周目の 12 時に始まりの印、時計回りに升。周の最後の升が `cont` で、
  1 つ外の周の 12 時から続ける。1 周の升の数は升の中心の周の長さ ÷ 1 升
- 陣ごとの塊: 陣の周りに手順陣を 12 時から `rites[]` の順に等角。距離は隣り合う円が `FULL_ORBIT_GAP` 以上離れるまで広げる
- root の塊を中央に、残りの陣の塊を第 1 軌道に同じ規則で並べる(root が未定義なら circles[0]・既存の描画と同じ)
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from jin_core.v2.glyph import START_MARK
from jin_core.v2.model import JinFileV2

from jin_render import geometry as base
from jin_render.v2 import geometry as geo
from jin_render.v2.inscribe import InkCell, circle_ring, rite_ring


@dataclass(frozen=True)
class RingCell:
    cell: InkCell
    ring: int
    angle: float
    center: tuple[float, float]


@dataclass(frozen=True)
class Placement:
    circles: dict[int, tuple[float, float]]
    rites: dict[tuple[int, int], tuple[float, float]]
    circle_radius: dict[int, float]  # 銘環の最外周の外縁まで
    rite_radius: dict[tuple[int, int], float]
    half: float  # 額縁の半辺


def _capacity(ring: int, inner: float) -> int:
    """1 周の升の数。升は正立の 1×1 なので、隣の中心との弦が FULL_CELL_PITCH(√2)以上なら
    どの向きでも x か y の差が 1 以上になり重ならない(最終レビュー #2)。"""
    radius = inner + 0.5 + ring * geo.FULL_RING_PITCH
    half_chord = min(1.0, geo.FULL_CELL_PITCH / (2.0 * radius))
    return max(4, math.floor(math.pi / math.asin(half_chord)))


def _slots(count: int, inner: float) -> list[tuple[int, int, str]]:
    """count 字を並べたときの (周, 周の中の番号, 種類) の列。種類は start / cont / cell。"""
    out = [(0, 0, "start")]
    ring, slot, left = 0, 1, count
    while left:
        if slot == _capacity(ring, inner) - 1 and left > 1:
            out.append((ring, slot, "cont"))
            ring, slot = ring + 1, 0
            continue
        if slot == _capacity(ring, inner):
            ring, slot = ring + 1, 0
            continue
        out.append((ring, slot, "cell"))
        slot += 1
        left -= 1
    return out


def ring_cells(cells: Sequence[InkCell], cx: float, cy: float, inner: float) -> list[RingCell]:
    """銘帯の升の列を、中心 (cx, cy)・内縁 inner の銘環に並べる。"""
    owner = cells[0] if cells else InkCell("struct", START_MARK, "", "circle")
    queue = iter(cells)
    placed: list[RingCell] = []
    for ring, slot, what in _slots(len(cells), inner):
        if what == "start":
            cell = InkCell("struct", START_MARK, owner.pointer, owner.kind)
        elif what == "cont":
            cell = InkCell("glyph", "cont", owner.pointer, owner.kind)
        else:
            cell = next(queue)
        angle = base.TOP_ANGLE + 360.0 * slot / _capacity(ring, inner)
        radius = inner + 0.5 + ring * geo.FULL_RING_PITCH
        rad = math.radians(angle)
        placed.append(
            RingCell(cell, ring, angle, (cx + radius * math.cos(rad), cy + radius * math.sin(rad)))
        )
    return placed


def ring_outer(count: int, inner: float) -> float:
    """count 字の銘環の最外周の外縁の半径。"""
    rings = max(ring for ring, _, _ in _slots(count, inner)) + 1
    return inner + rings * geo.FULL_RING_PITCH


def circle_inner() -> float:
    return geo.FULL_CIRCLE_EXTENT * geo.FULL_DIAGRAM_R + geo.FULL_RING_GAP


def rite_inner() -> float:
    return geo.FULL_RITE_EXTENT * geo.FULL_DIAGRAM_R + geo.FULL_RING_GAP


def _orbit(center_radius: float, sat_radii: Sequence[float]) -> float:
    """中心の円の周りに衛星を等角に並べる距離(衛星どうしも中心とも FULL_ORBIT_GAP 以上離す)。"""
    if not sat_radii:
        return 0.0
    biggest = max(sat_radii)
    distance = center_radius + geo.FULL_ORBIT_GAP + biggest
    n = len(sat_radii)
    if n >= 2:
        distance = max(
            distance, (2.0 * biggest + geo.FULL_ORBIT_GAP) / (2.0 * math.sin(math.pi / n))
        )
    return distance


def _around(cx: float, cy: float, distance: float, n: int) -> list[tuple[float, float]]:
    out = []
    for k in range(n):
        rad = math.radians(base.TOP_ANGLE + 360.0 * k / n)
        out.append((cx + distance * math.cos(rad), cy + distance * math.sin(rad)))
    return out


def place(model: JinFileV2) -> Placement:
    circle_radius = {
        ci: ring_outer(len(circle_ring(model, ci)), circle_inner())
        for ci in range(len(model.circles))
    }
    rite_radius = {
        (ci, ri): ring_outer(len(rite_ring(model, ci, ri)), rite_inner())
        for ci, circle in enumerate(model.circles)
        for ri in range(len(circle.rites))
    }

    # 陣ごとの塊(陣の中心からの相対位置)
    local: dict[int, list[tuple[float, float]]] = {}
    cluster: dict[int, float] = {}
    for ci, circle in enumerate(model.circles):
        radii = [rite_radius[(ci, ri)] for ri in range(len(circle.rites))]
        distance = _orbit(circle_radius[ci], radii)
        local[ci] = _around(0.0, 0.0, distance, len(radii))
        cluster[ci] = max([circle_radius[ci]] + [distance + r for r in radii])

    names = [c.name for c in model.circles]
    root = names.index(model.root) if model.root in names else 0
    others = [ci for ci in range(len(model.circles)) if ci != root]
    distance = _orbit(cluster[root], [cluster[ci] for ci in others])
    centers = {root: (0.0, 0.0)} | dict(
        zip(others, _around(0.0, 0.0, distance, len(others)), strict=True)
    )

    rites = {
        (ci, ri): (centers[ci][0] + dx, centers[ci][1] + dy)
        for ci in centers
        for ri, (dx, dy) in enumerate(local[ci])
    }
    extent = max(
        [max(abs(x), abs(y)) + circle_radius[ci] for ci, (x, y) in centers.items()]
        + [max(abs(x), abs(y)) + rite_radius[key] for key, (x, y) in rites.items()]
    )
    return Placement(
        circles=dict(sorted(centers.items())),
        rites=dict(sorted(rites.items())),
        circle_radius=circle_radius,
        rite_radius=rite_radius,
        half=extent + geo.FULL_FRAME_MARGIN,
    )


__all__ = [
    "Placement",
    "RingCell",
    "circle_inner",
    "place",
    "ring_cells",
    "ring_outer",
    "rite_inner",
]
