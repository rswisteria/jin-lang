"""決定的デコーダ: Jin が描いた完全陣の PNG → 場面グラフ(陣書き S3・設計書 §3.4)。API は使わない。

完全陣の配置の規則(`jin_render.v2.full_layout` / `full.frame_positions`)を共有し、root の陣から順に銘環の位置を辿って升を読む。

1. 升の大きさ: 左上の護符(一辺 3 升・外枠 0.2〜2.8 升・中の塗り 0.9〜2.1 升)を対角線に沿って走査し、外枠の 2 本の間隔 ÷ 2.6
2. 銘環: 1 周目の 12 時の始まりの印から順に読み、周の最後が `cont` なら外の周へ、空の升で終わる
3. 衛星(手順陣)と第 1 軌道(陣): 中心から真上へ 0.1 升刻みで始まりの印を探し、前後 0.5 升を 0.02 升刻みで
   (ずらさない差で)合わせ込んでから頭の構造の印を確かめて距離を決める。数は `orbit_centers` の全位置で読める最大の n(12 から 1 へ)
4. 2 回目: 1 回目で数えた字数から `full_layout` と同じ式で陣・衛星・軌道の中心を求め直して読む(走査のずれを持ち越さない)
5. 額縁の銘帯: `frame_positions` の順に空の升まで

場面グラフの図形の id: `frame` / 陣 `c<k>`(`c0` は中心の root、`c1`… は第 1 軌道の 12 時から時計回り)/ 手順陣 `r<k>_<j>`。
銘帯は図形ごとに 1 本で、銘環の銘帯は始まりの印と継ぎの紋も含む(構文解析器が JIN301 / JIN304 を見る)。
"""

from __future__ import annotations

import hashlib
import io
import struct
from dataclasses import dataclass

from jin_core.v2.glyph import START_MARK
from jin_render.v2 import geometry as g2
from jin_render.v2.full import frame_positions
from jin_render.v2.full_layout import (
    circle_inner,
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
_REFINE_STEP = 0.02
_MAX_ORBIT = 12
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
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
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
    他の塊の銘環より必ず先に当たる。第 1 軌道は root の塊の外から探す。"""
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


def _count_around(
    canvas: _Canvas, cx: float, cy: float, distance: float, inner: float, head: str
) -> int:
    for n in range(_MAX_ORBIT, 0, -1):
        centers = orbit_centers(cx, cy, distance, n)
        if all(_heads_at(canvas, x, y, inner, head) for x, y in centers):
            return n
    return 0


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

    # 1 回目(構造を知る): 走査で見つけたおおよその位置で読み、陣・手順陣の数と各銘環の字数を数える。
    # 走査の距離は 0.1 升ほどずれ、塊をまたぐと積み重なって升を読み違えるので、2 回目は配置の規則
    # (`place` と同じ ring_outer / orbit_distance / orbit_centers)で正確な中心を求め直して読む
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
        n = _count_around(canvas, cx, cy, distance, rite_inner(), "s_rite")
        sats = [
            _payload_count(_read_ring(canvas, x, y, rite_inner()))
            for x, y in orbit_centers(cx, cy, distance, n)
        ]
        return count, sats

    def exact(count: int, sats: list[int]) -> tuple[float, float, float]:
        """(陣の銘環の半径, 衛星の距離, 塊の半径)。`full_layout.place` と同じ式。"""
        radius = ring_outer(count, circle_inner())
        radii = [ring_outer(c, rite_inner()) for c in sats]
        distance = orbit_distance(radius, radii)
        return radius, distance, max([radius] + [distance + r for r in radii])

    clusters = [survey(0.0, 0.0)]
    first = exact(*clusters[0])[2] + g2.FULL_ORBIT_GAP + circle_inner() + g2.FULL_RING_PITCH
    rough = _scan_up(canvas, 0.0, 0.0, first, circle_inner(), "s_circle")
    if rough is not None:
        m = _count_around(canvas, 0.0, 0.0, rough, circle_inner(), "s_circle")
        clusters += [survey(x, y) for x, y in orbit_centers(0.0, 0.0, rough, m)]

    # 2 回目(正確な位置で読む)
    reaches = [exact(*c)[2] for c in clusters]
    orbit = orbit_distance(reaches[0], reaches[1:])
    centers = [(0.0, 0.0)] + orbit_centers(0.0, 0.0, orbit, len(clusters) - 1)
    for k, ((cx, cy), (count, sats)) in enumerate(zip(centers, clusters, strict=True)):
        add(f"c{k}", "ring.circle", (cx, cy), _read_ring(canvas, cx, cy, circle_inner()))
        distance = exact(count, sats)[1]
        for j, (x, y) in enumerate(orbit_centers(cx, cy, distance, len(sats))):
            add(f"r{k}_{j}", "ring.rite", (x, y), _read_ring(canvas, x, y, rite_inner()))

    frame_cells: list[tuple[Read, tuple[float, float]]] = []
    for at in frame_positions(4 * int(2 * canvas.half), canvas.half):
        read = canvas.read(*at)
        if read.t == "empty":
            break
        frame_cells.append((read, at))
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
