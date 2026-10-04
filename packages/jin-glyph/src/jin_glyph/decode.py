"""決定的デコーダ: Jin が描いた完全陣の PNG → 場面グラフ(陣書き S3・設計書 §3.4)。API は使わない。

完全陣の配置の規則(`jin_render.v2.full_layout` / `full.frame_positions`)を共有し、root の陣から順に銘環の位置を辿って升を読む。

1. 升の大きさ: 左上の護符(一辺 3 升・外枠 0.2〜2.8 升・中の塗り 0.9〜2.1 升)を対角線に沿って走査し、外枠の 2 本の間隔 ÷ 2.6
2. 銘環: 1 周目の 12 時の始まりの印から順に読み、周の最後が `cont` なら外の周へ、空の升で終わる
3. 額縁の銘帯: `frame_positions` の順に空の升まで。字数から額縁の余白(`frame_margin`)と陣の塊を詰める棚の左上・幅が決まる
4. 陣の塊(#118・`full_layout.shelf`): 棚の今の位置 (x, top) から右下への対角線 (x + e, top + e) を走査して陣の始まりの印を探し、
   見つけた陣の字数から求めた張り出し e の位置と合うものを採る。この段に無ければ次の段の左端から、どちらにも無ければ終わる
5. 衛星(手順陣): 陣の中心から真上へ 0.1 升刻みで始まりの印を探し、前後 0.5 升を 0.02 升刻みで(ずらさない差で)合わせ込んでから
   頭の構造の印を確かめて距離を決める。数は `orbit_centers` の全位置で読める最大の n(12 から 1 へ)
6. 2 回目: 1 回目で数えた字数から `full_layout` と同じ式で陣・衛星の中心を求め直して読む(走査のずれを持ち越さない)

場面グラフの図形の id: `frame` / 陣 `c<k>`(`c0` は左上の root、`c1`… は棚の順)/ 手順陣 `r<k>_<j>`。
銘帯は図形ごとに 1 本で、銘環の銘帯は始まりの印と継ぎの紋も含む(構文解析器が JIN301 / JIN304 を見る)。
"""

from __future__ import annotations

import hashlib
import io
import math
import struct
from dataclasses import dataclass

from jin_core.v2.glyph import START_MARK
from jin_render.v2 import geometry as g2
from jin_render.v2.full import frame_positions
from jin_render.v2.full_layout import (
    circle_inner,
    cluster_layout,
    frame_capacity,
    frame_margin,
    orbit_centers,
    orbit_distance,
    ring_capacity,
    ring_outer,
    ring_slot_center,
    rite_inner,
)
from PIL import Image

from jin_glyph.cells import MIN_CELL_PX, Read, distance_to, read_cell
from jin_glyph.scene import Band, Cell, Figure, ImageInfo, JinScene

_SCAN_STEP = 0.1
#: 対角線の走査の刻み(升)。1 歩で縦横の両方が動くので、真上の走査より細かくしないと始まりの印を踏み外す(倍率 3 で実測)
_DIAGONAL_STEP = 0.04
_REFINE_STEP = 0.02
#: 衛星(手順陣)の数の上限 = 1 つの陣の手順の数の上限(JIN020 の 12)
_MAX_SATELLITES = 12
#: 見つけた陣の中心と、その字数から求めた棚の上の中心の差の上限(升)。これより離れていれば別の塊
_MATCH = 0.75
#: 額縁の銘帯を読む周の数の上限(配置は 3 周を超えると余白を広げて収めるので、空の升までいくつでも読む)
_MAX_FRAME_ROWS = 64
_LOCATE_REACH = 0.3  # 1 回目の中心を合わせ込む範囲(升)
_LOCATE_STEP = 0.05
#: Jin が描いた画像では最も近い候補が正しい(倍率 3 の構造の印は差が 130 前後まで開く)。これより離れていたら読めない升
DECODE_UNKNOWN_DISTANCE = 250.0
#: 読む画像の画素数の上限(20000 px 四方・グレースケールで 400 MB)。othello の完全陣は 2 倍で 2.2 億画素
MAX_PIXELS = 400_000_000


class DecodeError(ValueError):
    """Jin が描いた完全陣として読めない画像。"""


@dataclass
class _Canvas:
    image: Image.Image
    cell: float  # 升の px
    half: float  # 額縁の半辺(升)

    def px(self, x: float, y: float) -> tuple[float, float]:
        return ((x + self.half) * self.cell, (y + self.half) * self.cell)

    def read(self, x: float, y: float) -> Read:
        cx, cy = self.px(x, y)
        h = self.cell / 2
        width, height = self.image.size
        if cx - h < 0 or cy - h < 0 or cx + h > width or cy + h > height:
            return Read("empty", "", 0.0)  # 画像の外にはみ出す升は読まない
        return read_cell(self.image, (cx, cy), self.cell, DECODE_UNKNOWN_DISTANCE)

    def inside(self, x: float, y: float) -> bool:
        return abs(x) < self.half - 0.5 and abs(y) < self.half - 0.5

    def box(self, x: float, y: float) -> tuple[float, float, float, float]:
        cx, cy = self.px(x, y)
        h = self.cell / 2
        return (round(cx - h, 3), round(cy - h, 3), round(cx + h, 3), round(cy + h, 3))


def _load(data: bytes) -> Image.Image:
    """PNG を白地のグレースケールにする。大きさは IHDR を自分で読んで `MAX_PIXELS` で断る。

    完全陣は大きく(othello は 2 倍で 14749 px 四方・2.2 億画素)、Pillow の爆弾検査(既定 1.8 億画素で例外)に掛かる。
    自分の上限で先に断ったうえで、開く間だけ Pillow の上限を外す。"""
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise DecodeError("PNG ではありません")
    width, height = struct.unpack(">II", data[16:24])
    if width * height > MAX_PIXELS:
        raise DecodeError(f"画像が大きすぎます({width} × {height}。{MAX_PIXELS} 画素まで)")
    limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = None
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    finally:
        Image.MAX_IMAGE_PIXELS = limit
    if image.mode in ("RGBA", "LA", "P", "PA"):
        # RGBA のまま合成すると 4 倍の大きさの複製が並ぶので、グレースケールと不透明度に分けて白地へ重ねる
        gray, alpha = image.convert("LA").split()
        return Image.composite(gray, Image.new("L", image.size, 255), alpha)
    return image.convert("L")


def _cell_size(image: Image.Image) -> float:
    """左上の護符の外枠の 2 本(0.2 升・2.8 升)の間隔から升の px を求める。"""
    limit = min(image.size) // 4
    runs: list[tuple[int, int]] = []
    start = None
    for i in range(limit):
        dark = image.getpixel((i, i)) < 128
        if dark and start is None:
            start = i
        elif not dark and start is not None:
            runs.append((start, i))
            start = None
    if len(runs) < 3:
        raise DecodeError("左上の護符が見つかりません(Jin が描いた完全陣の PNG ではない)")
    fill = max(range(len(runs)), key=lambda k: runs[k][1] - runs[k][0])  # 中の塗りが最も長い
    if fill == 0 or fill == len(runs) - 1:
        raise DecodeError("左上の護符の形が読めません")
    before, after = runs[fill - 1], runs[fill + 1]
    center = lambda run: (run[0] + run[1] - 1) / 2
    rough = (center(after) - center(before)) / 2.6
    # 精密に: 中の塗り(0.9〜2.1 升・一辺 1.2 升)を通る行の暗さの総和は縁のぼかしがあっても幅 × 255 に保たれる。
    # しきい値の位置から求めると 0.5% ずれ、額縁の中心から遠い升ほど位置がずれて読めなくなる
    rows = range(round(1.3 * rough), round(1.7 * rough) + 1)
    lo, hi = round(0.55 * rough), round(2.45 * rough)
    widths = [sum(255 - image.getpixel((x, y)) for x in range(lo, hi)) / 255.0 for y in rows]
    # 塗りの正方形にも額縁の <g> の線(1 升の 1/12)がかかるので、幅は 1.2 升 + 1/12 升
    cell = sum(widths) / len(widths) / (1.2 + 1.0 / g2.FULL_CELL_PX)
    if cell < MIN_CELL_PX - 0.5:
        raise DecodeError(
            f"升が小さすぎます({cell:.1f} px。{MIN_CELL_PX:.0f} px 以上・完全陣の SVG を 2 倍以上で PNG に)"
        )
    return cell


def _is(read: Read, t: str, v: str) -> bool:
    return read.t == t and read.v == v


def _read_ring(
    canvas: _Canvas, cx: float, cy: float, inner: float
) -> list[tuple[Read, tuple[float, float]]]:
    """銘環を読む(始まりの印と継ぎの紋も含む)。最初が始まりの印でなければ空の列。"""
    first = ring_slot_center(cx, cy, inner, 0, 0)
    head = canvas.read(*first)
    if not _is(head, "struct", START_MARK):
        return []
    out = [(head, first)]
    ring, slot = 0, 1
    while True:
        capacity = ring_capacity(ring, inner)
        if slot == capacity:
            ring, slot = ring + 1, 0
            continue
        at = ring_slot_center(cx, cy, inner, ring, slot)
        if not canvas.inside(*at):
            break
        read = canvas.read(*at)
        if read.t == "empty":
            break
        if read.t == "unknown":
            raise DecodeError(
                f"升が読めません(中心 {canvas.px(*at)}・最も近い {read.v} との差 {read.distance:.0f})"
            )
        out.append((read, at))
        if slot == capacity - 1 and _is(read, "glyph", "cont"):
            ring, slot = ring + 1, 0
            continue
        slot += 1
    return out


def _payload_count(cells: list[tuple[Read, tuple[float, float]]]) -> int:
    return sum(
        1
        for read, _ in cells
        if not _is(read, "struct", START_MARK) and not _is(read, "glyph", "cont")
    )


def _heads_at(canvas: _Canvas, cx: float, cy: float, inner: float, head: str) -> bool:
    """中心 (cx, cy)・内縁 inner の銘環が、始まりの印 + 頭の構造の印 head で始まるか。"""
    start = ring_slot_center(cx, cy, inner, 0, 0)
    if not canvas.inside(*start) or not _is(canvas.read(*start), "struct", START_MARK):
        return False
    return _is(canvas.read(*ring_slot_center(cx, cy, inner, 0, 1)), "struct", head)


def _scan_up(
    canvas: _Canvas, cx: float, cy: float, start: float, inner: float, head: str
) -> float | None:
    """中心から真上へ距離 d を走査し、中心 (cx, cy − d)・内縁 inner の銘環が head で始まる最初の d。

    手順陣を探すのは核のある陣だけ(核は手順を名指すので 1 つ以上ある)。最も近い衛星(12 時)は陣の塊の内側にあり、
    他の塊の銘環より必ず先に当たる。"""
    d = start
    while canvas.inside(cx, cy - d - inner):
        # 粗い刻みでは始まりの印だけを見る(頭の構造の印は升が少しずれると読み違える)。見つけたら距離を合わせ直して確かめる
        if _is(canvas.read(*ring_slot_center(cx, cy - d, inner, 0, 0)), "struct", START_MARK):
            exact = _refine(canvas, cx, cy, d, inner)
            if _heads_at(canvas, cx, cy - exact, inner, head):
                return exact
        d += _SCAN_STEP
    return None


def _is_flow(cells: list[tuple[Read, tuple[float, float]]]) -> bool:
    """陣の核の銘帯(s_circle から次の構造の印まで)に flow の種別の紋があれば核なし陣(手順を持たない)。"""
    for read, _ in cells[2:]:
        if read.t == "struct":
            break
        if read.t == "glyph" and read.v.startswith("flow_"):
            return True
    return False


def _refine(canvas: _Canvas, cx: float, cy: float, near: float, inner: float) -> float:
    """始まりの印との(ずらさない)差が最小になる距離を、near の前後 0.5 升で細かく探す。"""
    best = (float("inf"), near)
    d = near - 0.5
    while d <= near + 0.5:
        x, y = ring_slot_center(cx, cy - d, inner, 0, 0)
        if canvas.inside(x, y):
            distance = distance_to(canvas.image, canvas.px(x, y), canvas.cell, START_MARK)
            if distance < best[0]:
                best = (distance, d)
        d += _REFINE_STEP
    return best[1]


def _locate(canvas: _Canvas, x: float, y: float, inner: float) -> tuple[float, float]:
    """中心 (x, y) の前後 `_LOCATE_REACH` 升の平面で、銘環の始まりの印が(ずらさない差で)最もよく合う中心。

    1 回目の中心は走査の距離のずれを含み、陣の塊の向こう側の衛星ではそのずれが 2 倍になる(中心のずれ + 距離のずれ)。"""
    steps = round(_LOCATE_REACH / _LOCATE_STEP)
    best = (float("inf"), x, y)
    for i in range(-steps, steps + 1):
        for j in range(-steps, steps + 1):
            cx, cy = x + i * _LOCATE_STEP, y + j * _LOCATE_STEP
            sx, sy = ring_slot_center(cx, cy, inner, 0, 0)
            if canvas.inside(sx, sy):
                distance = distance_to(canvas.image, canvas.px(sx, sy), canvas.cell, START_MARK)
                if distance < best[0]:
                    best = (distance, cx, cy)
    return best[1], best[2]


def _count_around(
    canvas: _Canvas,
    cx: float,
    cy: float,
    distance: float,
    inner: float,
    head: str,
    most: int,
) -> list[tuple[float, float]]:
    """`orbit_centers` の全位置(合わせ込んだ中心)で head の銘環が読める最大の n(most 以下)の中心の列。

    真の数 N が most を超えると N の約数に化ける(13 → 1・15 → 5)。most は軌道に載りうる数の上限にすること。"""
    for n in range(most, 0, -1):
        found = []
        for x, y in orbit_centers(cx, cy, distance, n):
            x, y = _locate(canvas, x, y, inner)
            if not _heads_at(canvas, x, y, inner, head):
                break
            found.append((x, y))
        else:
            return found
    return []


def decode_png(data: bytes) -> JinScene:
    image = _load(data)
    cell = _cell_size(image)
    canvas = _Canvas(image, cell, image.size[0] / cell / 2.0)
    figures: list[Figure] = []
    bands: list[Band] = []

    def add(
        fid: str, kind: str, at: tuple[float, float], cells: list[tuple[Read, tuple[float, float]]]
    ) -> None:
        figures.append(Figure(id=fid, kind=kind, at=canvas.px(*at)))
        bands.append(
            Band(
                owner=fid,
                cells=[Cell(t=read.t, v=read.v, box=canvas.box(*pos)) for read, pos in cells],
            )  # type: ignore[arg-type]
        )

    # 額縁の銘帯を先に読む: 字数で額縁の余白(`frame_margin`)が決まり、陣の塊を詰める棚の左上と幅が決まる
    frame_cells: list[tuple[Read, tuple[float, float]]] = []
    # 配置は銘帯の次の 1 升まで余白に収める(`frame_margin`)ので、空の升まで読めば陣の升を読み込まずに止まる
    for at in frame_positions(frame_capacity(canvas.half, rows=_MAX_FRAME_ROWS), canvas.half):
        read = canvas.read(*at)
        if read.t == "empty":
            break
        frame_cells.append((read, at))
    margin = frame_margin(len(frame_cells), canvas.half)
    left = -canvas.half + margin
    width = 2.0 * (canvas.half - margin)

    # 1 回目(構造を知る): 塊の陣を見つけ、陣・手順陣の数と各銘環の字数を数える。
    # 走査の距離は 0.1 升ほどずれ、塊をまたぐと積み重なって升を読み違えるので、2 回目は配置の規則
    # (`place` と同じ ring_outer / cluster_layout / 棚)で正確な中心を求め直して読む
    def survey(cx: float, cy: float) -> tuple[int, list[int]]:
        cells = _read_ring(canvas, cx, cy, circle_inner())
        if len(cells) < 2 or not _is(cells[1][0], "struct", "s_circle"):
            raise DecodeError(f"陣の銘環が読めません(中心 {canvas.px(cx, cy)})")
        count = _payload_count(cells)
        if _is_flow(cells):
            return count, []
        first = (
            ring_outer(count, circle_inner())
            + g2.FULL_ORBIT_GAP
            + rite_inner()
            + g2.FULL_RING_PITCH
        )
        distance = _scan_up(canvas, cx, cy, first, rite_inner(), "s_rite")
        if distance is None:
            return count, []
        centers = _count_around(canvas, cx, cy, distance, rite_inner(), "s_rite", _MAX_SATELLITES)
        return count, [_payload_count(_read_ring(canvas, x, y, rite_inner())) for x, y in centers]

    def exact(count: int, sats: list[int]) -> tuple[float, float]:
        """(衛星の距離, 塊の張り出し)。`full_layout.place` と同じ式。"""
        radius = ring_outer(count, circle_inner())
        radii = [ring_outer(c, rite_inner()) for c in sats]
        _, extent = cluster_layout(radius, radii)
        return orbit_distance(radius, radii), extent

    def find(ax: float, ay: float, most: float) -> tuple[tuple[int, list[int]], float] | None:
        """棚の今の位置 (ax, ay) から右下への対角線(中心 (ax + e, ay + e))で、張り出し e が most 以下の塊を探す。
        見つけた陣を数え、その字数から求めた張り出しの位置と、見つけた中心が合うものだけを採る。"""
        e = circle_inner() + g2.FULL_RING_PITCH  # 最も小さい陣の銘環の外縁
        most = min(most, (left + width - ay) / 2.0)  # 塊は棚の下端(額縁の余白の内側)を越えない
        while e <= most + _DIAGONAL_STEP:
            cx, cy = ax + e, ay + e
            start = ring_slot_center(cx, cy, circle_inner(), 0, 0)
            if canvas.inside(*start) and _is(canvas.read(*start), "struct", START_MARK):
                x, y = _locate(canvas, cx, cy, circle_inner())
                if _heads_at(canvas, x, y, circle_inner(), "s_circle"):
                    cluster = survey(x, y)
                    extent = exact(*cluster)[1]
                    # 画像から求めた額縁の半辺は 0.02 升ほどずれるので、入るかどうかも同じ許容で見る
                    if (
                        math.dist((x, y), (ax + extent, ay + extent)) < _MATCH
                        and extent <= most + _MATCH
                    ):
                        return cluster, extent
            e += _DIAGONAL_STEP
        return None

    clusters: list[tuple[int, list[int]]] = []
    centers: list[tuple[float, float]] = []
    x = top = row = 0.0
    while True:
        hit = find(left + x, left + top, (width - x) / 2.0)
        if hit is None and x > 0.0:  # この段に入らなければ次の段の左端から
            top, x, row = top + row + g2.FULL_ORBIT_GAP, 0.0, 0.0
            hit = find(left, left + top, width / 2.0)
        if hit is None:
            break
        cluster, extent = hit
        clusters.append(cluster)
        centers.append((left + x + extent, left + top + extent))
        x += 2.0 * extent + g2.FULL_ORBIT_GAP
        row = max(row, 2.0 * extent)
    if not clusters:
        raise DecodeError("陣の銘環が見つかりません")

    # 2 回目(正確な位置で読む)
    for k, ((cx, cy), (count, sats)) in enumerate(zip(centers, clusters, strict=True)):
        add(f"c{k}", "ring.circle", (cx, cy), _read_ring(canvas, cx, cy, circle_inner()))
        distance = exact(count, sats)[0]
        for j, (x2, y2) in enumerate(orbit_centers(cx, cy, distance, len(sats))):
            add(f"r{k}_{j}", "ring.rite", (x2, y2), _read_ring(canvas, x2, y2, rite_inner()))
    add("frame", "frame", (0.0, 0.0), frame_cells)

    return JinScene(
        jinscene=1,
        sheet="full",
        image=ImageInfo(
            sha256=hashlib.sha256(data).hexdigest(), width=image.size[0], height=image.size[1]
        ),
        figures=figures,
        bands=bands,
    )


__all__ = ["DecodeError", "decode_png"]
