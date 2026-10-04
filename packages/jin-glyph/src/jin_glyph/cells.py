"""升の読み取り: 完全陣の PNG の升 1 つを、既知の字形との照合で読む(陣書き S3・設計書 §3.4)。API は使わない。

- 升を `GRID` × `GRID` の格子に縮めた「塗られた割合」(0〜255)を、候補の理想の格子と比べ、差の総和が最小のものを採る
  (Pillow の `ImageChops.difference` と `ImageStat` で C の速さで数える)
- 候補は線の字(`jin_render.v2.glyph_paths` の紋・構造の印・始まりの印。線の太さは完全陣と同じ 1/12 升)と、
  ドットの字(升を 8 × 8 に縮めた列 1〜6 の点の並びを、`font.dot_groups` の逆引きの表で引いた 1 字)
- 同じ点の並びの字が複数あれば ASCII → 小さい符号位置の順で 1 つに決める(`duplicate_dot_groups` が組を返す)
- 点が無い升は `empty`、どの候補とも差が `UNKNOWN_DISTANCE` を超える升は `unknown`
- 読める大きさの下限は 1 升 `MIN_CELL_PX` px(完全陣の SVG を 2 倍以上で PNG にしたもの)。1 倍(12 px・線 1 px)では
  ÷ の点のような細部が潰れて取り違える(glyph.md §9)
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import Literal

from jin_core.v2.glyph import START_MARK, STRUCT_MARKS
from jin_render.v2 import geometry as g2
from jin_render.v2.font import dot_groups
from jin_render.v2.glyph_paths import GLYPH_PATHS
from PIL import Image, ImageChops, ImageDraw, ImageStat

GRID = 24
#: ドットの字の点(8 × 8 の 1 目)が「ある」とみなす暗さの割合
DOT_FRACTION = 0.5
#: 点が無いとみなす格子の暗さの総和(0〜255 の値の総和)
EMPTY_INK = 255.0
#: どの候補ともこれより離れていたら unknown(格子の差の総和 ÷ 255 = 塗りの食い違いの目数)。全字形の往復テストで決めた値
UNKNOWN_DISTANCE = 120.0
#: 読める升の大きさの下限(px)
MIN_CELL_PX = 2.0 * g2.FULL_CELL_PX
_CANVAS = 240  # 理想の格子を描く下書きの一辺(px)
_NEAR = 10  # ずらして測り直す近い候補の数
_STRUCT_IDS = frozenset(m.id for m in STRUCT_MARKS) | {START_MARK}


@dataclass(frozen=True)
class Read:
    t: Literal["latin", "glyph", "struct", "empty", "unknown"]
    v: str
    distance: float


def _ink(gray: Image.Image) -> Image.Image:
    """白地の濃淡を「塗られた割合」(0 = 白・255 = 黒)にする。"""
    return ImageChops.invert(gray)


def _distance(a: Image.Image, b: Image.Image) -> float:
    return ImageStat.Stat(ImageChops.difference(a, b)).sum[0] / 255.0


def _flatten(gid: str) -> list[list[tuple[float, float]]]:
    """字形の画を折れ線の列にする(3 次ベジェは 12 分割)。座標は下書きの px。"""
    scale = _CANVAS / 100.0
    lines: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    start = (0.0, 0.0)
    for op, nums in GLYPH_PATHS[gid]:
        if op == "M":
            if len(current) > 1:
                lines.append(current)
            start = (nums[0] * scale, nums[1] * scale)
            current = [start]
        elif op == "L":
            current.append((nums[0] * scale, nums[1] * scale))
        elif op == "C":
            x0, y0 = current[-1]
            x1, y1, x2, y2, x3, y3 = (v * scale for v in nums)
            for k in range(1, 13):
                t = k / 12.0
                u = 1.0 - t
                current.append(
                    (
                        u**3 * x0 + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t**3 * x3,
                        u**3 * y0 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t**3 * y3,
                    )
                )
        else:  # Z
            current.append(start)
    if len(current) > 1:
        lines.append(current)
    return lines


def _line_ideal(gid: str) -> Image.Image:
    image = Image.new("L", (_CANVAS, _CANVAS), 255)
    draw = ImageDraw.Draw(image)
    width = _CANVAS / g2.FULL_CELL_PX  # 完全陣の線の太さ 1 px / 升 12 px
    for line in _flatten(gid):
        draw.line(line, fill=0, width=round(width), joint="curve")
        for x, y in (line[0], line[-1]):
            draw.ellipse((x - width / 2, y - width / 2, x + width / 2, y + width / 2), fill=0)
    return _ink(image.resize((GRID, GRID), Image.Resampling.BOX))


def _dot_bits_at(image: Image.Image, box: tuple[float, float, float, float]) -> int:
    """升を 8 × 8 に縮め、列 1〜6 の点の並びをビットにする(`font.pixels` の (列, 行) と同じ並べ方)。"""
    dots = _ink(image.resize((8, 8), Image.Resampling.BOX, box=box))
    bits = 0
    for i, value in enumerate(dots.get_flattened_data()):
        col, row = i % 8, i // 8
        if 1 <= col <= 6 and value / 255.0 > DOT_FRACTION:
            bits |= 1 << ((col - 1) * 8 + row)
    return bits


@functools.cache
def _dot_ideal(bits: int) -> Image.Image:
    image = Image.new("L", (_CANVAS, _CANVAS), 255)
    draw = ImageDraw.Draw(image)
    p = _CANVAS / 8
    for col in range(6):
        for row in range(8):
            if bits >> (col * 8 + row) & 1:
                x = (1 + col) * p
                draw.rectangle((x, row * p, x + p - 1, row * p + p - 1), fill=0)
    return _ink(image.resize((GRID, GRID), Image.Resampling.BOX))


_LINE_IDEALS: dict[str, Image.Image] = {gid: _line_ideal(gid) for gid in GLYPH_PATHS}
#: 点の並び(ビット)→ 字の組。組と順は `font.dot_groups`(銘文が `esc u` で書く字の判定 `font.readable` と同じ表)
_DOT_GROUPS: dict[int, tuple[str, ...]] = {
    sum(1 << (col * 8 + row) for col, row in dots): chars for dots, chars in dot_groups().items()
}


def _shifted_boxes(
    box: tuple[float, float, float, float], cell_px: float, size: tuple[int, int] | None = None
) -> list[tuple[float, float, float, float]]:
    """升を ±1 目ずらした 8 つの升(画像の外にはみ出すものは除く)。"""
    unit = cell_px / GRID
    x0, y0, x1, y1 = box
    width, height = size if size is not None else (float("inf"), float("inf"))
    return [
        (x0 + dx * unit, y0 + dy * unit, x1 + dx * unit, y1 + dy * unit)
        for dx in (-1, 0, 1)
        for dy in (-1, 0, 1)
        if (dx, dy) != (0, 0)
        and x0 + dx * unit >= 0
        and y0 + dy * unit >= 0
        and x1 + dx * unit <= width
        and y1 + dy * unit <= height
    ]


def duplicate_dot_groups() -> list[tuple[str, ...]]:
    """同じ点の並びを持つ字の組(先頭が読み取りで採る字)。"""
    return [tuple(group) for group in _DOT_GROUPS.values() if len(group) > 1]


def distance_to(
    image: Image.Image, center_px: tuple[float, float], cell_px: float, gid: str
) -> float:
    """升と線の字 gid の差(ずらさない)。升の位置を合わせ込むのに使う(`read_cell` はずれを吸うので位置に鈍い)。"""
    cx, cy = center_px
    box = (cx - cell_px / 2, cy - cell_px / 2, cx + cell_px / 2, cy + cell_px / 2)
    return _distance(
        _ink(image.resize((GRID, GRID), Image.Resampling.BOX, box=box)), _LINE_IDEALS[gid]
    )


def read_cell(
    image: Image.Image,
    center_px: tuple[float, float],
    cell_px: float,
    unknown_distance: float = UNKNOWN_DISTANCE,
) -> Read:
    """画像(グレースケール・白地)の、中心 center_px・一辺 cell_px の升を読む。"""
    cx, cy = center_px
    box = (cx - cell_px / 2, cy - cell_px / 2, cx + cell_px / 2, cy + cell_px / 2)
    observed = _ink(image.resize((GRID, GRID), Image.Resampling.BOX, box=box))
    if ImageStat.Stat(observed).sum[0] < EMPTY_INK:
        return Read("empty", "", 0.0)
    # 線は升の 1/12 の細さなので、升が格子 1 目(升の 1/24)ずれるだけで二重枠の差が中の記号の差を上回る。
    # ずれ 0 で全候補を測り、近い候補(構造の印が入れば構造の印と始まりの印すべて)を ±1 目ずらした升でも測って最小を採る
    first = sorted((_distance(observed, ideal), gid) for gid, ideal in _LINE_IDEALS.items())
    near = {gid for _, gid in first[:_NEAR]}
    if near & _STRUCT_IDS:
        near |= _STRUCT_IDS
    near.add(START_MARK)  # 始まりの印は細く、1 目のずれで上位から落ちる(走査の手がかり)
    boxes = _shifted_boxes(box, cell_px, image.size)
    shifted = [_ink(image.resize((GRID, GRID), Image.Resampling.BOX, box=b)) for b in boxes]
    best: tuple[float, str, str] | None = None
    for distance, gid in first:
        if gid in near:
            distance = min([distance] + [_distance(view, _LINE_IDEALS[gid]) for view in shifted])
        if best is None or distance < best[0]:
            best = (distance, "struct" if gid in _STRUCT_IDS else "glyph", gid)
    # ドットの字も同じずれで測る(線の字だけずらすと、ずれた升でドットの字が線の字に負ける: o → flow_loop)
    for b, view in [(box, observed), *zip(boxes, shifted, strict=True)]:
        bits = _dot_bits_at(image, b)
        group = _DOT_GROUPS.get(bits)
        if group:
            distance = _distance(view, _dot_ideal(bits))
            if best is None or distance <= best[0]:
                best = (distance, "latin", group[0])
    assert best is not None
    if best[0] > unknown_distance:
        return Read("unknown", best[2], best[0])
    return Read(best[1], best[2], best[0])  # type: ignore[arg-type]


__all__ = ["MIN_CELL_PX", "Read", "distance_to", "duplicate_dot_groups", "read_cell"]
