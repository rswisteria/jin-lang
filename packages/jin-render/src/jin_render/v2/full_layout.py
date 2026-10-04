"""完全陣の配置: 銘環の升の位置と、連環陣(陣の塊の棚・陣の周りの手順陣の軌道)の中心(glyph 設計書 §2)。

単位は升(銘環の 1 字)。純関数で、同じモデルから同じ配置を返す。

- 銘環: 1 周目の内縁は図の外接 + `FULL_RING_GAP`。1 周目の 12 時に始まりの印、時計回りに升。周の最後の升が `cont` で、
  1 つ外の周の 12 時から続ける。1 周の升の数は升の中心の周の長さ ÷ 1 升
- 陣ごとの塊: 陣の周りに手順陣を 12 時から `rites[]` の順に等角。距離は隣り合う円が `FULL_ORBIT_GAP` 以上離れるまで広げる
- 塊の詰め方(#118): 塊を root → 残りの陣(`circles[]` の順)で、額縁の内側の左上から棚に詰める(`shelf`)。塊の大きさは陣の中心から
  上下左右への最大の張り出し `e`(正方形 2e)で、棚の上端に揃え、左から `FULL_ORBIT_GAP` を空けて並べ、入らなければ次の段へ。
  額縁の一辺は詰められる最小の値(半辺を `HALF_STEP` 刻みで広げて探す)。陣が 1 つなら塊は額縁の中心に来る(以前の配置と同じ)。
  root が未定義なら circles[0](既存の描画と同じ)
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from jin_core.v2.glyph import START_MARK
from jin_core.v2.model import JinFileV2

from jin_render import geometry as base
from jin_render.v2 import geometry as geo
from jin_render.v2.inscribe import InkCell, Inscription, inscribe


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
    inscription: Inscription  # 配置に使った銘帯(描く側が組み直さない)


def ring_capacity(ring: int, inner: float) -> int:
    """1 周の升の数。升は正立の 1×1 なので、隣の中心との弦が FULL_CELL_PITCH(√2)以上なら
    どの向きでも x か y の差が 1 以上になり重ならない(最終レビュー #2)。"""
    radius = inner + 0.5 + ring * geo.FULL_RING_PITCH
    half_chord = min(1.0, geo.FULL_CELL_PITCH / (2.0 * radius))
    return max(4, math.floor(math.pi / math.asin(half_chord)))


def slot_kinds(count: int, inner: float) -> list[tuple[int, int, str]]:
    """count 字を並べたときの (周, 周の中の番号, 種類) の列。種類は start / cont / cell。"""
    out = [(0, 0, "start")]
    ring, slot, left = 0, 1, count
    while left:
        # 周の最後の 1 升は、まだ 2 字以上残っていれば継ぎの紋にして外の周へ。残りが 1 字ならその字で周が埋まって終わるので、
        # 周の升の数を越える番号には来ない
        if slot == ring_capacity(ring, inner) - 1 and left > 1:
            out.append((ring, slot, "cont"))
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
    for ring, slot, what in slot_kinds(len(cells), inner):
        if what == "start":
            cell = InkCell("struct", START_MARK, owner.pointer, owner.kind)
        elif what == "cont":
            cell = InkCell("glyph", "cont", owner.pointer, owner.kind)
        else:
            cell = next(queue)
        angle = base.TOP_ANGLE + 360.0 * slot / ring_capacity(ring, inner)
        placed.append(RingCell(cell, ring, angle, ring_slot_center(cx, cy, inner, ring, slot)))
    return placed


def ring_slot_center(
    cx: float, cy: float, inner: float, ring: int, slot: int
) -> tuple[float, float]:
    """銘環の (周, 周の中の番号) の升の中心(升の単位)。デコーダも同じ式で位置を求める。"""
    angle = base.TOP_ANGLE + 360.0 * slot / ring_capacity(ring, inner)
    radius = inner + 0.5 + ring * geo.FULL_RING_PITCH
    rad = math.radians(angle)
    return (cx + radius * math.cos(rad), cy + radius * math.sin(rad))


def ring_outer(count: int, inner: float) -> float:
    """count 字の銘環の最外周の外縁の半径。"""
    rings = max(ring for ring, _, _ in slot_kinds(count, inner)) + 1
    return inner + rings * geo.FULL_RING_PITCH


def circle_inner() -> float:
    return geo.FULL_CIRCLE_EXTENT * geo.FULL_DIAGRAM_R + geo.FULL_RING_GAP


def rite_inner() -> float:
    return geo.FULL_RITE_EXTENT * geo.FULL_DIAGRAM_R + geo.FULL_RING_GAP


def orbit_distance(center_radius: float, sat_radii: Sequence[float]) -> float:
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


def orbit_centers(cx: float, cy: float, distance: float, n: int) -> list[tuple[float, float]]:
    out = []
    for k in range(n):
        rad = math.radians(base.TOP_ANGLE + 360.0 * k / n)
        out.append((cx + distance * math.cos(rad), cy + distance * math.sin(rad)))
    return out


def frame_positions(count: int, half: float) -> list[tuple[float, float]]:
    """額縁の銘帯の升の中心: 額縁の内側を左上から時計回りに巡る(四隅の護符の区画は飛ばす)。足りなければ内側の周へ。"""
    out: list[tuple[float, float]] = []
    inset = 1.5
    while len(out) < count:
        h = half - inset
        lo, hi = -h + geo.FULL_TALISMAN + 0.5, h - geo.FULL_TALISMAN - 0.5
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
        inset += geo.FULL_RING_PITCH
    return out[:count]


def frame_rows(count: int, half: float) -> int:
    """count 字の額縁の銘帯が使う周の数(`frame_positions` の内側への周の数)。"""
    rows, left, inset = 0, count, 1.5
    while left > 0:
        h = half - inset
        steps = max(0, math.floor(2.0 * (h - geo.FULL_TALISMAN - 0.5)) + 1)
        if steps == 0:
            return rows + 1_000_000  # 額縁が小さすぎて収まらない(呼び手が額縁を広げる)
        left -= 4 * steps
        rows += 1
        inset += geo.FULL_RING_PITCH
    return rows


#: 額縁の余白(`FULL_FRAME_MARGIN`)に収まる額縁の銘帯の周の数(1.5 + 2 × 1.6 + 0.5 = 5.2 < 6)。
FRAME_ROWS = 3


def frame_capacity(half: float, rows: int = FRAME_ROWS) -> int:
    """額縁の銘帯の rows 周に入る升の数(読み手が額縁の銘帯を最後まで辿る上限)。"""
    total, inset = 0, 1.5
    for _ in range(rows):
        h = half - inset
        total += 4 * max(0, math.floor(2.0 * (h - geo.FULL_TALISMAN - 0.5)) + 1)
        inset += geo.FULL_RING_PITCH
    return total


#: 塊が複数のとき、額縁の半辺を広げて探す刻み(升)
HALF_STEP = 0.25


def cluster_layout(
    circle_radius: float, rite_radii: Sequence[float]
) -> tuple[list[tuple[float, float]], float]:
    """陣の塊: 手順陣の中心(陣の中心からの相対位置)と、陣の中心から上下左右への最大の張り出し。"""
    distance = orbit_distance(circle_radius, rite_radii)
    local = orbit_centers(0.0, 0.0, distance, len(rite_radii))
    extent = max(
        [circle_radius]
        + [max(abs(x), abs(y)) + r for (x, y), r in zip(local, rite_radii, strict=True)]
    )
    return local, extent


def frame_margin(frame_count: int, half: float) -> float:
    """額縁の余白: 額縁の銘帯と**その次の 1 升**が FRAME_ROWS 周を超えるなら、超えた周の分だけ広げる。

    次の 1 升まで余白に収めるので、銘帯の後ろには必ず余白の中の空の升があり、デコーダは空の升まで読めば止まる
    (銘帯がちょうど 3 周で終わっても、4 周目の位置にある陣の升を読み込まない)。"""
    return geo.FULL_FRAME_MARGIN + geo.FULL_RING_PITCH * max(
        0, frame_rows(frame_count + 1, half) - FRAME_ROWS
    )


def shelf(extents: Sequence[float], half: float, margin: float) -> list[tuple[float, float]] | None:
    """塊(張り出し e の正方形)を額縁の内側の左上から棚に詰めた中心の列。入らなければ None。

    デコーダ(`jin_glyph.decode`)は同じ規則を 1 つずつ辿る: 塊の中心は棚の今の位置 (x, top) から右下への対角線
    (x + e, top + e)の上にあるので、e を知らなくても対角線を走査して陣の始まりの印を探せる。"""
    width = 2.0 * (half - margin)
    left = -half + margin
    x = top = row = 0.0
    out: list[tuple[float, float]] = []
    eps = 1e-9
    for e in extents:
        if 2.0 * e > width + eps:
            return None
        if x > 0.0 and x + 2.0 * e > width + eps:
            top += row + geo.FULL_ORBIT_GAP
            x = row = 0.0
        out.append((left + x + e, left + top + e))
        x += 2.0 * e + geo.FULL_ORBIT_GAP
        row = max(row, 2.0 * e)
    return out if top + row <= width + eps else None


def place(model: JinFileV2) -> Placement:
    inscription = inscribe(model)
    circle_radius = {
        ci: ring_outer(len(cells), circle_inner()) for ci, cells in inscription.circles.items()
    }
    rite_radius = {
        key: ring_outer(len(cells), rite_inner()) for key, cells in inscription.rites.items()
    }

    # 陣ごとの塊(陣の中心からの相対位置と張り出し)
    local: dict[int, list[tuple[float, float]]] = {}
    extent: dict[int, float] = {}
    for ci, circle in enumerate(model.circles):
        radii = [rite_radius[(ci, ri)] for ri in range(len(circle.rites))]
        local[ci], extent[ci] = cluster_layout(circle_radius[ci], radii)

    names = [c.name for c in model.circles]
    root = names.index(model.root) if model.root in names else 0
    order = [root] + [ci for ci in range(len(model.circles)) if ci != root]
    extents = [extent[ci] for ci in order]
    count = len(inscription.frame)
    half = max(extents) + geo.FULL_FRAME_MARGIN
    while True:
        margin = frame_margin(count, half)
        # 余白が広がった分だけ半辺も広げてから詰める(陣 1 つなら塊はちょうど中心に来る)
        half = max(half, max(extents) + margin)
        packed = shelf(extents, half, margin)
        if packed is not None and frame_margin(count, half) == margin:
            break
        half += HALF_STEP
    centers = dict(zip(order, packed, strict=True))
    rites = {
        (ci, ri): (centers[ci][0] + dx, centers[ci][1] + dy)
        for ci in centers
        for ri, (dx, dy) in enumerate(local[ci])
    }
    return Placement(
        circles=dict(sorted(centers.items())),
        rites=dict(sorted(rites.items())),
        circle_radius=circle_radius,
        rite_radius=rite_radius,
        half=half,
        inscription=inscription,
    )


__all__ = [
    "FRAME_ROWS",
    "HALF_STEP",
    "Placement",
    "RingCell",
    "circle_inner",
    "cluster_layout",
    "frame_capacity",
    "frame_margin",
    "frame_positions",
    "frame_rows",
    "orbit_centers",
    "orbit_distance",
    "place",
    "ring_capacity",
    "ring_cells",
    "ring_outer",
    "ring_slot_center",
    "rite_inner",
    "shelf",
    "slot_kinds",
]
