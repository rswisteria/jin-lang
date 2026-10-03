"""型紙(モード 2)の幾何: 等級(S / M)→ 書き込む升の並び(陣書き S4・glyph 設計書 §2.5・正典 glyph.md §10)。

型紙を描く側(`jin_render.v2.sheet`)と、写真から升を切り出す側(`jin_glyph.recognize`)は**この関数の結果だけ**を読む
(レイアウトを二重に実装しない)。単位は升(手描きの 1 字・印刷で 5 mm)、原点は額縁の中心、y は下向き。

- 銘環は完全陣と同じ規則(`full_layout.ring_capacity` / `ring_slot_center`): 1 周目の 12 時に始まりの印(印刷)、時計回りに升、
  外の周へ。字数で周回数が決まる完全陣と違い、型紙の周回数は等級で固定
- 額縁の銘帯は完全陣と同じ `frame_positions`(額縁の内側を左上から時計回り・四隅の護符の区画を飛ばす)の 1 周
- **続きの帯**(strip): 銘環と額縁の銘帯から溢れた分を書く横一列の升。余白から自動で切り出し、上から下・左から右に番号を振る。
  銘帯の最後の升が継ぎの紋 `cont` なら、まだ使っていない帯を番号の順に取って続ける(帯の最後が `cont` なら次の帯へ)。
  番号は書かせない(読み手は升の並びだけで決まる)
- 等級 S は 1 陣 × 4 手順(陣を中央・手順陣を斜め 4 方向に右上から時計回り)、M は 3 陣 × 各 4 手順(15 の環を 4 × 4 の格子に
  行の順で置く。16 個目の区画は続きの帯に回す)。手順は番号の小さい環から詰めて使う(飛ばすと JIN302)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from jin_core.v2.model import JinFileV2

from jin_render.v2 import geometry as geo
from jin_render.v2.full import frame_positions
from jin_render.v2.full_layout import ring_capacity, ring_slot_center
from jin_render.v2.inscribe import InkCell, circle_ring, frame_band, rite_ring

Grade = Literal["S", "M"]
GRADES: tuple[Grade, ...] = ("S", "M")

#: 印刷したときの 1 升(mm)。手描きの升 5 mm(設計書 §2.4 / §9 #8)
SHEET_CELL_MM = 5.0
#: 環の中の図(核の円)の半径と、図から銘環の 1 周目の内縁まで
SHEET_DIAGRAM_R = 2.5
SHEET_RING_GAP = 1.0
#: 環の周回数(S は 4 周 = 120 升、M は 2 周 = 36 升)
SHEET_TURNS: dict[Grade, int] = {"S": 4, "M": 2}
SHEET_DIAGRAM_R_M = 2.0
#: 環どうし・環と帯の隙間(升)
SHEET_GAP = 0.6
#: 続きの帯の升の間隔(横)と行の間隔(縦)。行は銘環の周の間隔と同じ
SHEET_STRIP_PITCH = 1.2
SHEET_STRIP_ROW = geo.FULL_RING_PITCH
#: 帯の最短の升の数(番号の升を除く)
SHEET_STRIP_MIN = 4
#: 額縁の半辺(升)。S / M とも A3 の短辺(297 mm)に 5 mm の升で刷れる大きさ
SHEET_HALF = 28.5
#: 等級の印(額縁の左上の護符の右)の大きさ(升)
SHEET_GRADE_CELL = 1.5

SlotKind = Literal["start", "cell", "label"]


@dataclass(frozen=True)
class Slot:
    """升 1 つ。`kind` は start(印刷した始まりの印)/ cell(書く升)/ label(印刷した帯の番号)。"""

    owner: str  # 図形の id(frame / c<k> / r<k>_<j> / strip<n>)
    index: int  # その持ち主の中の順番(読む順)
    center: tuple[float, float]
    kind: SlotKind


@dataclass(frozen=True)
class Ring:
    owner: str  # c<k> / r<k>_<j>
    pointer: str  # 骨格プログラムでの pointer(/circles/k・/circles/k/rites/j)
    center: tuple[float, float]
    inner: float  # 銘環の 1 周目の内縁
    turns: int
    diagram: float  # 図(核の円)の半径

    @property
    def outer(self) -> float:
        return self.inner + self.turns * geo.FULL_RING_PITCH


@dataclass(frozen=True)
class Sheet:
    grade: Grade
    half: float
    rings: tuple[Ring, ...]
    slots: tuple[Slot, ...]  # 読む順: 額縁 → 環(rings の順)→ 続きの帯(番号の順)

    def owners(self) -> list[str]:
        return list(dict.fromkeys(s.owner for s in self.slots))

    def of(self, owner: str) -> list[Slot]:
        return [s for s in self.slots if s.owner == owner]

    def talismans(self) -> list[tuple[float, float]]:
        """四隅の護符の中心(左上・右上・左下・右下)。右上だけ中が丸(向きの印)。完全陣と同じ一辺 3 升。"""
        t = geo.FULL_TALISMAN
        h = self.half - t / 2
        return [(-h, -h), (h, -h), (-h, h), (h, h)]

    def grade_mark(self) -> tuple[float, float]:
        """等級の印(ラテンの S / M・印刷)の中心。額縁の銘帯の上辺の先頭(左上の護符の右隣・その升は銘帯から外す)。"""
        return _grade_mark(self.half)


def _grade_mark(half: float) -> tuple[float, float]:
    # 額縁の銘帯の上辺の最初の 2 升の真ん中(frame_positions の最初の升は -(half - 1.5) + 護符 + 0.5)
    first = -(half - 1.5) + geo.FULL_TALISMAN + 0.5
    return (first + 0.5, -half + 1.5)


def _ring_slots(ring: Ring) -> list[Slot]:
    out: list[Slot] = []
    cx, cy = ring.center
    for turn in range(ring.turns):
        for slot in range(ring_capacity(turn, ring.inner)):
            kind: SlotKind = "start" if turn == 0 and slot == 0 else "cell"
            center = ring_slot_center(cx, cy, ring.inner, turn, slot)
            out.append(Slot(ring.owner, len(out), center, kind))
    return out


def _rings_S() -> list[Ring]:
    inner = SHEET_DIAGRAM_R + SHEET_RING_GAP
    turns = SHEET_TURNS["S"]
    outer = inner + turns * geo.FULL_RING_PITCH
    # 手順陣は中央の陣と隣どうしが SHEET_GAP 離れる距離で、斜め 4 方向(右上から時計回り)
    distance = 2.0 * outer + SHEET_GAP
    rings = [Ring("c0", "/circles/0", (0.0, 0.0), inner, turns, SHEET_DIAGRAM_R)]
    for j in range(4):
        rad = math.radians(-45.0 + 90.0 * j)
        center = (distance * math.cos(rad), distance * math.sin(rad))
        rings.append(
            Ring(f"r0_{j}", f"/circles/0/rites/{j}", center, inner, turns, SHEET_DIAGRAM_R)
        )
    return rings


def _rings_M() -> list[Ring]:
    inner = SHEET_DIAGRAM_R_M + SHEET_RING_GAP
    turns = SHEET_TURNS["M"]
    outer = inner + turns * geo.FULL_RING_PITCH
    pitch = 2.0 * outer + SHEET_GAP
    rings: list[Ring] = []
    owners = [
        (f"c{k}", f"/circles/{k}") if j < 0 else (f"r{k}_{j}", f"/circles/{k}/rites/{j}")
        for k in range(3)
        for j in range(-1, 4)
    ]
    for n, (owner, pointer) in enumerate(owners):
        row, col = divmod(n, 4)
        center = ((col - 1.5) * pitch, (row - 1.5) * pitch)
        rings.append(Ring(owner, pointer, center, inner, turns, SHEET_DIAGRAM_R_M))
    return rings


def _frame_slots(half: float) -> list[Slot]:
    # 額縁の 1 周目だけ(frame_positions は足りなければ内側の周へ回る。1 周目は額縁から 1.5 升の線の上)
    h = half - 1.5
    first = [
        p
        for p in frame_positions(4 * math.ceil(2.0 * half), half)
        if math.isclose(abs(p[0]), h) or math.isclose(abs(p[1]), h)
    ]
    gx, gy = _grade_mark(half)
    reach = 1.0
    first = [p for p in first if not (math.isclose(p[1], gy) and abs(p[0] - gx) < reach)]
    return [Slot("frame", n, p, "cell") for n, p in enumerate(first)]


def _clear(x: float, y: float, rings: list[Ring], half: float) -> bool:
    """升 (x, y) の正方形が環・額縁の銘帯(と護符・等級の印)と重ならないか。"""
    limit = half - 1.5 - 0.5 - SHEET_GAP  # 額縁の銘帯の内側
    if abs(x) + 0.5 > limit or abs(y) + 0.5 > limit:
        return False
    for ring in rings:
        dx = max(abs(x - ring.center[0]) - 0.5, 0.0)
        dy = max(abs(y - ring.center[1]) - 0.5, 0.0)
        if math.hypot(dx, dy) < ring.outer + SHEET_GAP:
            return False
    return True


def _sector(v: float, half: float) -> int:
    return -1 if v < -half / 3.0 else (1 if v > half / 3.0 else 0)


def _strip_slots(rings: list[Ring], half: float) -> list[Slot]:
    """余白を横一列の帯に切る。番号は 上の区画 → 中段の左 → 中段の右 → 下の区画、区画の中は上から。
    各帯の先頭の升は番号(印刷)。"""
    limit = half - 2.0
    rows = math.floor(2.0 * limit / SHEET_STRIP_ROW)
    columns = math.floor(2.0 * limit / SHEET_STRIP_PITCH)
    x0 = -(columns - 1) * SHEET_STRIP_PITCH / 2.0
    y0 = -(rows - 1) * SHEET_STRIP_ROW / 2.0
    runs: list[list[tuple[float, float]]] = []
    for r in range(rows):
        y = y0 + r * SHEET_STRIP_ROW
        run: list[tuple[float, float]] = []
        for c in range(columns + 1):
            x = x0 + c * SHEET_STRIP_PITCH
            if c < columns and _clear(x, y, rings, half):
                run.append((x, y))
                continue
            if len(run) >= SHEET_STRIP_MIN + 1:
                runs.append(run)
            run = []

    def key(run: list[tuple[float, float]]) -> tuple[int, int, float, float]:
        cx = (run[0][0] + run[-1][0]) / 2.0
        return (_sector(run[0][1], half), _sector(cx, half), run[0][1], run[0][0])

    out: list[Slot] = []
    for n, run in enumerate(sorted(runs, key=key)):
        owner = f"strip{n}"
        out.append(Slot(owner, 0, run[0], "label"))
        out.extend(Slot(owner, i, p, "cell") for i, p in enumerate(run[1:], start=1))
    return out


def sheet_layout(grade: Grade) -> Sheet:
    """等級の型紙の幾何。純関数で、同じ等級から同じ並びを返す。"""
    if grade not in GRADES:
        raise ValueError(f"型紙の等級は S か M です: {grade!r}")
    rings = _rings_S() if grade == "S" else _rings_M()
    half = SHEET_HALF
    slots = _frame_slots(half)
    for ring in rings:
        slots += _ring_slots(ring)
    slots += _strip_slots(rings, half)
    return Sheet(grade=grade, half=half, rings=tuple(rings), slots=tuple(slots))


class SheetOverflow(ValueError):
    """プログラムが型紙に収まらない(陣・手順の数か、続きの帯の升が足りない)。"""


def _program_bands(sheet: Sheet, model: JinFileV2) -> dict[str, list[InkCell]]:
    """持ち主の id → 銘帯の升(銘環の始まりの印と継ぎの紋は含まない。完全陣の銘帯と同じ中身)。"""
    names = [c.name for c in model.circles]
    root = names.index(model.root) if model.root in names else 0
    order = [root] + [ci for ci in range(len(model.circles)) if ci != root]
    circles = sum(1 for r in sheet.rings if r.owner.startswith("c"))
    if len(order) > circles:
        raise SheetOverflow(
            f"陣が {len(order)} 個あります(等級 {sheet.grade} の型紙は {circles} 個まで)"
        )
    bands: dict[str, list[InkCell]] = {"frame": frame_band(model)}
    for k, ci in enumerate(order):
        bands[f"c{k}"] = circle_ring(model, ci)
        rites = model.circles[ci].rites
        slots = sum(1 for r in sheet.rings if r.owner.startswith(f"r{k}_"))
        if len(rites) > slots:
            raise SheetOverflow(
                f"陣 {names[ci]} の手順が {len(rites)} 個あります(型紙は 1 陣に {slots} 個まで)"
            )
        for j in range(len(rites)):
            bands[f"r{k}_{j}"] = rite_ring(model, ci, j)
    return bands


def fill_sheet(sheet: Sheet, model: JinFileV2) -> dict[tuple[str, int], InkCell]:
    """プログラムを型紙の升に割り付ける((持ち主, 升の順番) → 升の中身)。写し書きの手本と、認識器のテストの正解。

    持ち主ごとに銘帯を升の順に置き、収まらなければ最後の升を継ぎの紋 `cont` にして、まだ使っていない続きの帯へ番号の順に続ける
    (帯の最後の升も同じ)。読み手(`jin_glyph.recognize`)はこの逆を行う。root は `c0` に置く(完全陣の場面グラフと同じ)。
    """
    bands = _program_bands(sheet, model)
    strips = [o for o in sheet.owners() if o.startswith("strip")]
    out: dict[tuple[str, int], InkCell] = {}

    def place(owner: str, cells: list[InkCell]) -> list[InkCell]:
        """owner の書く升に置き、置ききれなかった残り(継ぎの紋の後ろ)を返す。"""
        slots = [s for s in sheet.of(owner) if s.kind == "cell"]
        if len(cells) <= len(slots):
            rest: list[InkCell] = []
        else:
            cells, rest = cells[: len(slots) - 1], cells[len(slots) - 1 :]
            cells = cells + [InkCell("glyph", "cont", rest[0].pointer, rest[0].kind)]
        for slot, cell in zip(slots, cells, strict=False):
            out[(owner, slot.index)] = cell
        return rest

    queue = iter(strips)
    for owner in sheet.owners():
        if owner.startswith("strip") or owner not in bands:
            continue
        rest = place(owner, bands[owner])
        while rest:
            strip = next(queue, None)
            if strip is None:
                raise SheetOverflow(
                    f"続きの帯が足りません(等級 {sheet.grade} の型紙に収まりません)"
                )
            rest = place(strip, rest)
    return out


__all__ = [
    "GRADES",
    "SHEET_CELL_MM",
    "SHEET_HALF",
    "Grade",
    "Ring",
    "Sheet",
    "SheetOverflow",
    "Slot",
    "fill_sheet",
    "sheet_layout",
]
