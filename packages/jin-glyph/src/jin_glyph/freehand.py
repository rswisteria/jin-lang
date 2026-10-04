"""フリーハンド(モード 1 = 白紙に描いた陣・陣書き S6)の位置推定の純関数(設計書 §3.6・正典 glyph.md §12)。

型紙の幾何(`jin_render.v2.sheet_layout`)の代わりに、Claude が返したおおよその形(額縁の四隅・環の中心と周の半径・
始まりの印・字の大きさ)から、升を手元の画素で切り出す。Claude の座標は字の数分の 1 ずれうるので(§9 #38 と同じ)、
升の位置そのものは Claude に返させず、ここで詰める:

1. 環の詰め直し(`refine_ring`): 周の帯の墨の画素に同心円を最小二乗で当てはめ(中心は共有・半径は周ごと)、中心と半径を詰める
2. 切り分け(`ring_blobs` / `frame_blobs`): 周(円)や額縁の行(正方形の内側を巡る道)に沿って、帯の墨を道の長さの座標に
   射影し、字の大きさの `GAP` 倍より狭い隙間はつなぐ。1 つの塊に字が 2 つ入ってよい(読み手が並びの向きに従って複数返す)。
   字の中の隙間(手描きの点や離れた画)で字を割らないよう、つなぐ側に寄せてある
3. 組み立て(`assemble`): 銘帯の最初の構造の印で環の種類(陣 / 手順陣)を決め、完全陣の配置の規則(`jin_render.v2.full_layout`)の
   逆で `c<k>` / `r<k>_<j>` を振る。陣は棚の順(root が左上・段ごとに左から・#118)、手順陣は持ち主(最も近い陣)の周りを
   12 時から時計回り。12 時ちょうどの環が手のずれで最後に回らないよう、数え始めを隣との間隔の半分だけ手前に置く

座標は正面化した画像(額縁を正方形にしたもの・y が下向き)の画素。角度は度で `atan2(dy, dx)`(時計回りが増える向き)。
画像ライブラリは Pillow だけ(numpy も OpenCV も入れない)。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from jin_core.v2.glyph import START_MARK, STRUCT_MARKS
from PIL import Image

from jin_glyph.scene import Band, Cell, Figure

#: 12 時の角度(画像の座標で y が下向き)
TOP = -90.0
#: 地より DARK_DELTA 以上暗い画素を墨とみなす(`recognize.DARK_DELTA` と同じ値)
DARK_DELTA = 60
#: 周の帯の半幅(字の大きさに対する比)。手描きの字は周の線から ±0.5 字、正立の字が斜めの位置で ±0.7 字まで広がる
BAND = 0.75
#: 周どうしが近いときは帯の半幅を周の間隔のこの割合までに縮める(隣の周の字を拾わない)
BAND_OF_PITCH = 0.48
#: 道に沿ってこれより狭い隙間はつなぐ(字の大きさに対する比)
GAP = 0.3
#: 詰め直しで墨を集める幅(字の大きさに対する比)と回数・中心が動いてよい上限(字)
REFINE_REACH = 0.9
REFINE_ROUNDS = 3
REFINE_LIMIT = 1.5
#: 当てはめに入れる周の墨の画素の下限(字の大きさ × この値。字 2〜3 個ぶん)
_MIN_TURN_INK = 6.0

_OWNER_OF = {m.id: m.owner for m in STRUCT_MARKS}

Point = tuple[float, float]
Box = tuple[int, int, int, int]


@dataclass(frozen=True)
class Blob:
    """道に沿った墨の塊 1 つ。`s0` / `s1` は道の長さの座標(px)、`box` は正面図の画素の外接矩形(x0, y0, x1, y1・右下は排他)、
    `direction` は塊の中の字の並びの向き(読み手への指示)。"""

    s0: float
    s1: float
    box: Box
    direction: str


def paper_level(gray: Image.Image) -> int:
    """地(紙)の明るさ: 明るい側から 25% の画素の値。"""
    histogram = gray.histogram()
    count = sum(histogram)
    seen = 0
    for value in range(255, -1, -1):
        seen += histogram[value]
        if seen >= count * 0.25:
            return value
    return 255


def _direction(dx: float, dy: float) -> str:
    """道の進む向き (dx, dy) → 字の並びの向きのことば。"""
    if abs(dx) >= abs(dy):
        return "left to right" if dx > 0 else "right to left"
    return "top to bottom" if dy > 0 else "bottom to top"


# ---- 墨の画素 -----------------------------------------------------------------------------------


def _annulus(
    gray: Image.Image, center: Point, inner: float, outer: float, dark: int
) -> list[tuple[int, int]]:
    """中心 center・半径 [inner, outer] の輪の中の墨の画素。行ごとに x の範囲を求めて輪の外を見ない。"""
    cx, cy = center
    pixels = gray.load()
    assert pixels is not None
    width, height = gray.size
    out: list[tuple[int, int]] = []
    for y in range(max(0, math.floor(cy - outer)), min(height, math.ceil(cy + outer) + 1)):
        dy = y + 0.5 - cy
        if abs(dy) > outer:
            continue
        half_outer = math.sqrt(outer * outer - dy * dy)
        half_inner = math.sqrt(inner * inner - dy * dy) if abs(dy) < inner else 0.0
        for lo, hi in ((cx - half_outer, cx - half_inner), (cx + half_inner, cx + half_outer)):
            for x in range(max(0, math.floor(lo)), min(width, math.ceil(hi) + 1)):
                dx = x + 0.5 - cx
                r = math.hypot(dx, dy)
                if inner <= r <= outer and pixels[x, y] < dark:  # type: ignore[operator]
                    out.append((x, y))
    return out


def _solve(matrix: list[list[float]]) -> list[float] | None:
    """拡大係数行列の連立一次方程式(部分ピボットのガウスの消去法)。解けなければ None。"""
    n = len(matrix)
    rows = [row[:] for row in matrix]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(rows[r][col]))
        if abs(rows[pivot][col]) < 1e-9:
            return None
        rows[col], rows[pivot] = rows[pivot], rows[col]
        for r in range(n):
            if r != col:
                factor = rows[r][col] / rows[col][col]
                rows[r] = [a - factor * b for a, b in zip(rows[r], rows[col], strict=True)]
    return [rows[i][n] / rows[i][i] for i in range(n)]


def refine_ring(
    gray: Image.Image, center: Point, radii: Sequence[float], cell: float
) -> tuple[Point, list[float]]:
    """環の中心と周の半径を、周の帯の墨に同心円を当てはめて詰める。

    x² + y² = 2a·x + 2b·y + c_k(周 k の円)を最小二乗で解く(Kåsa の当てはめを中心の共有に広げたもの)。
    帯の幅は隣の周との間隔の `BAND_OF_PITCH` 倍まで(隣の周の字を拾って周どうしが寄らないように)。
    字の少ない周(`_MIN_TURN_INK` 未満)は当てはめに入れず Claude の半径のまま。墨が足りない・解けない・
    中心が `REFINE_LIMIT` 字より動いた(図形の線に引かれた)ときは Claude の値のまま。
    """
    if not radii:
        return center, list(radii)
    dark = paper_level(gray) - DARK_DELTA
    cx, cy = center
    current = list(radii)
    for _ in range(REFINE_ROUNDS):
        turns: list[tuple[int, list[tuple[float, float]]]] = []
        for i, r in enumerate(current):
            reach = band_half_width(current, i, cell, REFINE_REACH)
            ink = [
                (x + 0.5 - cx, y + 0.5 - cy)
                for x, y in _annulus(gray, (cx, cy), max(0.0, r - reach), r + reach, dark)
            ]
            if len(ink) >= _MIN_TURN_INK * cell:
                turns.append((i, ink))
        if not turns:
            return center, list(radii)
        k = len(turns)
        # 未知数 (a, b, c_1 … c_k)。座標は今の中心からの相対(桁を揃える)
        normal = [[0.0] * (k + 3) for _ in range(k + 2)]
        for t, (_, ink) in enumerate(turns):
            for px, py in ink:
                rhs = px * px + py * py
                entries = ((0, 2.0 * px), (1, 2.0 * py), (2 + t, 1.0))
                for p, vp in entries:
                    for q, vq in entries:
                        normal[p][q] += vp * vq
                    normal[p][k + 2] += vp * rhs
        solution = _solve(normal)
        if solution is None:
            return center, list(radii)
        a, b, *cs = solution
        if any(c + a * a + b * b <= 0.0 for c in cs):
            return center, list(radii)
        cx, cy = cx + a, cy + b
        for (i, _), c in zip(turns, cs, strict=True):
            current[i] = math.sqrt(c + a * a + b * b)
    if math.dist((cx, cy), center) > REFINE_LIMIT * cell:
        return center, list(radii)
    return (cx, cy), current


def refine_inset(gray: Image.Image, side: int, inset: float, cell: float) -> list[float]:
    """額縁の行の内側への距離を、辺ごとに(上・右・下・左)行の帯の墨の重心で詰める。墨が無い辺は元の値。"""
    dark = paper_level(gray) - DARK_DELTA
    pixels = gray.load()
    assert pixels is not None
    reach = REFINE_REACH * cell
    margin = round(3.0 * cell)  # 四隅(護符や角の飾り)を避ける
    out: list[float] = []
    for edge in range(4):
        total = weight = 0.0
        lo, hi = max(0, math.floor(inset - reach)), min(side, math.ceil(inset + reach) + 1)
        for depth in range(lo, hi):
            for along in range(margin, side - margin):
                if edge == 0:
                    x, y = along, depth
                elif edge == 1:
                    x, y = side - 1 - depth, along
                elif edge == 2:
                    x, y = along, side - 1 - depth
                else:
                    x, y = depth, along
                if pixels[x, y] < dark:  # type: ignore[operator]
                    total += depth + 0.5
                    weight += 1.0
        out.append(total / weight if weight else inset)
    return out


# ---- 切り分け -----------------------------------------------------------------------------------


def _runs(
    samples: list[tuple[float, int, int]], gap: float, period: float | None, min_ink: int
) -> list[tuple[float, float, list[tuple[int, int]]]]:
    """(道の座標, x, y) の墨を道に沿った塊に分ける。period があれば道は閉じていて、端をまたぐ塊をつなぐ。"""
    if not samples:
        return []
    samples = sorted(samples)
    groups: list[list[tuple[float, int, int]]] = [[samples[0]]]
    for sample in samples[1:]:
        if sample[0] - groups[-1][-1][0] < gap:
            groups[-1].append(sample)
        else:
            groups.append([sample])
    if period is not None and len(groups) > 1:
        wrap = samples[0][0] + period - samples[-1][0]
        if wrap < gap:
            last = groups.pop()
            groups[0] = [(s - period, x, y) for s, x, y in last] + groups[0]
    out = []
    for group in groups:
        if len(group) < min_ink:
            continue
        out.append((group[0][0], group[-1][0], [(x, y) for _, x, y in group]))
    return out


def _bbox(pixels: list[tuple[int, int]]) -> Box:
    return (
        min(x for x, _ in pixels),
        min(y for _, y in pixels),
        max(x for x, _ in pixels) + 1,
        max(y for _, y in pixels) + 1,
    )


def _min_ink(cell: float) -> int:
    """これより墨の画素が少ない塊は塵(紙のしみ・JPEG の雑音)として捨てる。"""
    return max(4, round(0.01 * cell * cell))


def ring_blobs(
    gray: Image.Image, center: Point, radius: float, half_width: float, start: float, cell: float
) -> list[Blob]:
    """中心 center・半径 radius の周に沿った墨の塊を、角度 start(度)から時計回りの順に。

    最初の塊は start に最も近い塊(start を含む塊があればそれ)。1 周目なら始まりの印、2 周目以降なら 12 時の升。
    """
    dark = paper_level(gray) - DARK_DELTA
    cx, cy = center
    samples: list[tuple[float, int, int]] = []
    for x, y in _annulus(gray, center, max(0.0, radius - half_width), radius + half_width, dark):
        angle = math.degrees(math.atan2(y + 0.5 - cy, x + 0.5 - cx))
        samples.append((math.radians((angle - start) % 360.0) * radius, x, y))
    period = 2.0 * math.pi * radius
    runs = _runs(samples, GAP * cell, period, _min_ink(cell))
    if not runs:
        return []

    def distance(run: tuple[float, float, list[tuple[int, int]]]) -> float:
        s0, s1, _ = run
        if s0 <= 0.0 <= s1:
            return 0.0
        return min(abs(s0 % period - period), abs(s0), abs(s1 % period), abs(period - s1))

    first = min(range(len(runs)), key=lambda i: (distance(runs[i]), runs[i][0]))
    ordered = runs[first:] + runs[:first]
    out = []
    for s0, s1, pixels in ordered:
        mid = math.radians(start) + ((s0 + s1) / 2.0) / radius
        out.append(Blob(s0, s1, _bbox(pixels), _direction(-math.sin(mid), math.cos(mid))))
    return out


def ring_turns(
    gray: Image.Image, center: Point, radii: Sequence[float], start: float, cell: float
) -> list[list[Blob]]:
    """環の周ごとの塊(内の周から)。1 周目の最初の塊(始まりの印)の前の縁から半字進んだ角度を、2 周目以降の 12 時にする。

    Claude の始まりの印の位置のずれは外の周ほど弧の長さで効き、12 時の升と 2 つ目の升を取り違える(clicker の陣の 2 周目で実測)。
    """
    turns: list[list[Blob]] = []
    for k, radius in enumerate(radii):
        blobs = ring_blobs(gray, center, radius, band_half_width(radii, k, cell), start, cell)
        if k == 0 and blobs:
            start = (
                start + math.degrees((blobs[0].s0 + 0.5 * cell) / radius) + 180.0
            ) % 360.0 - 180.0
        turns.append(blobs)
    return turns


def frame_blobs(
    gray: Image.Image, side: int, insets: Sequence[float], half_width: float, cell: float
) -> list[Blob]:
    """額縁の行(正方形の内側を、上・右・下・左の辺ごとに insets だけ入った道)に沿った墨の塊を、左上から時計回りの順に。"""
    dark = paper_level(gray) - DARK_DELTA
    pixels = gray.load()
    assert pixels is not None
    top, right, bottom, left = insets
    x0, x1 = left, side - right
    y0, y1 = top, side - bottom
    lengths = (x1 - x0, y1 - y0, x1 - x0, y1 - y0)
    offsets = [0.0]
    for length in lengths[:-1]:
        offsets.append(offsets[-1] + length)
    samples: list[tuple[float, int, int]] = []
    width, height = gray.size
    lo_x, hi_x = max(0, math.floor(x0 - half_width)), min(width, math.ceil(x1 + half_width) + 1)
    lo_y, hi_y = max(0, math.floor(y0 - half_width)), min(height, math.ceil(y1 + half_width) + 1)
    for y in range(lo_y, hi_y):
        py = y + 0.5
        for x in range(lo_x, hi_x):
            px = x + 0.5
            # 道の 4 辺のうち最も近い辺へ射影する
            candidates = (
                (abs(py - y0), 0, px - x0),
                (abs(px - x1), 1, py - y0),
                (abs(py - y1), 2, x1 - px),
                (abs(px - x0), 3, y1 - py),
            )
            near, edge, along = min(candidates)
            if near > half_width or not (-half_width <= along <= lengths[edge] + half_width):
                continue
            if pixels[x, y] < dark:  # type: ignore[operator]
                samples.append((offsets[edge] + along, x, y))
    out = []
    heading = ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))
    for s0, s1, ink in _runs(samples, GAP * cell, None, _min_ink(cell)):
        mid = (s0 + s1) / 2.0
        edge = max((i for i in range(4) if offsets[i] <= mid), default=0)
        out.append(Blob(s0, s1, _bbox(ink), _direction(*heading[edge])))
    return out


def band_half_width(radii: Sequence[float], index: int, cell: float, scale: float = BAND) -> float:
    """周 index の帯の半幅: 字の大きさの scale 倍。隣の周が近ければ間隔の BAND_OF_PITCH 倍まで縮める。"""
    width = scale * cell
    for other in (index - 1, index + 1):
        if 0 <= other < len(radii):
            width = min(width, BAND_OF_PITCH * abs(radii[other] - radii[index]))
    return width


# ---- 組み立て -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class RingText:
    """読んだ環 1 つ: 中心(正面図の画素・写真の画素)と、始まりの印から時計回りの升(継ぎの紋を含む)。"""

    center: Point
    at: Point
    cells: list[Cell]
    radius: float = 0.0  # 最も外の周の半径(正面図の画素)。陣の塊の左上を求めるのに使う


def ring_kind(cells: Sequence[Cell]) -> str | None:
    """銘帯の最初の構造の印(始まりの印を除く)から、陣 `circle` か手順陣 `rite` か。どちらでもなければ None。"""
    for cell in cells:
        if cell.t == "struct" and cell.v != START_MARK:
            owner = _OWNER_OF.get(cell.v)
            return owner if owner in ("circle", "rite") else None
    return None


def _clockwise(center: Point, points: Sequence[Point]) -> list[int]:
    """center の周りの points を 12 時から時計回りの順の添字に。数え始めは隣との間隔の半分だけ手前(12 時の環のずれを吸う)。"""
    if not points:
        return []
    lead = 180.0 / len(points)

    def key(i: int) -> float:
        dx, dy = points[i][0] - center[0], points[i][1] - center[1]
        return (math.degrees(math.atan2(dy, dx)) - TOP + lead) % 360.0

    return sorted(range(len(points)), key=key)


def _reading_order(rings: Sequence[RingText], owned: dict[int, list[int]]) -> list[int]:
    """陣の塊を完全陣の棚の順(`full_layout.shelf`: root が左上、段ごとに左から)に並べる。

    塊の左上は、陣の中心から上下左右への最大の張り出し e(陣と手順陣の環の中心 ± 半径)で求める。同じ段の塊は上端が揃うので、
    上端の差が最も小さい塊の e 以内なら同じ段とする(次の段は少なくとも 2e 下にある)。"""

    def corner(circle: int) -> tuple[float, float, float]:
        cx, cy = rings[circle].center
        reach = max(
            max(abs(rings[i].center[0] - cx), abs(rings[i].center[1] - cy)) + rings[i].radius
            for i in [circle, *owned[circle]]
        )
        return cx - reach, cy - reach, reach

    corners = {c: corner(c) for c in owned}
    tolerance = min(reach for _, _, reach in corners.values())
    rows: list[list[int]] = []
    for c in sorted(owned, key=lambda c: (corners[c][1], corners[c][0])):
        if rows and corners[c][1] - corners[rows[-1][0]][1] <= tolerance:
            rows[-1].append(c)
        else:
            rows.append([c])
    return [c for row in rows for c in sorted(row, key=lambda c: corners[c][0])]


def assemble(
    rings: Sequence[RingText], frame_cells: list[Cell], middle: Point, middle_at: Point
) -> tuple[list[Figure], list[Band]]:
    """読んだ環と額縁の升 → 場面グラフの図形と銘帯(`jin_glyph.parse` が読む id: `frame` / `c<k>` / `r<k>_<j>`)。

    陣は完全陣の棚の順(`_reading_order`: root `c0` が左上、段ごとに左から)、手順陣は最も近い陣の周りを 12 時から時計回り。

    陣でも手順陣でもない環・陣の無い手順陣は `u<n>`(kind `ring`)として残し、構文解析器が JIN305 で知らせる。
    """
    kinds = [ring_kind(r.cells) for r in rings]
    circle_list = [i for i, k in enumerate(kinds) if k == "circle"]
    rite_list = [i for i, k in enumerate(kinds) if k == "rite"]
    ids: dict[int, str] = {}
    if circle_list:
        owned: dict[int, list[int]] = {i: [] for i in circle_list}
        for i in rite_list:
            owner = min(circle_list, key=lambda c: math.dist(rings[c].center, rings[i].center))
            owned[owner].append(i)
        order = _reading_order(rings, owned)
        for k, i in enumerate(order):
            ids[i] = f"c{k}"
        for k, owner in enumerate(order):
            mine = owned[owner]
            for j, n in enumerate(_clockwise(rings[owner].center, [rings[i].center for i in mine])):
                ids[mine[n]] = f"r{k}_{j}"
    unknown = 0
    for i in range(len(rings)):
        if i not in ids:
            ids[i] = f"u{unknown}"
            unknown += 1

    def sort_key(i: int) -> tuple[int, int, int]:
        fid = ids[i]
        if fid.startswith("c"):
            return (0, int(fid[1:]), 0)
        if fid.startswith("r"):
            k, j = fid[1:].split("_")
            return (1, int(k), int(j))
        return (2, int(fid[1:]), 0)

    figures = [Figure(id="frame", kind="frame", at=_round(middle_at))]
    bands = [Band(owner="frame", cells=frame_cells)]
    for i in sorted(range(len(rings)), key=sort_key):
        fid = ids[i]
        kind = {"c": "circle", "r": "rite"}.get(fid[0], "ring")
        figures.append(Figure(id=fid, kind=kind, at=_round(rings[i].at)))
        bands.append(Band(owner=fid, cells=rings[i].cells))
    return figures, bands


def _round(point: Point) -> Point:
    return (round(point[0], 1), round(point[1], 1))


__all__ = [
    "BAND",
    "GAP",
    "TOP",
    "Blob",
    "RingText",
    "assemble",
    "band_half_width",
    "frame_blobs",
    "paper_level",
    "refine_inset",
    "refine_ring",
    "ring_blobs",
    "ring_kind",
    "ring_turns",
]
