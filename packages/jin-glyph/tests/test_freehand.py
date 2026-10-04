"""フリーハンドの位置推定の純関数(`jin_glyph.freehand`・陣書き S6)。画像は Pillow で描いた図形で、API は使わない。"""

from __future__ import annotations

import math

import pytest
from jin_core.v2.glyph import START_MARK
from jin_glyph.freehand import (
    TOP,
    RingText,
    assemble,
    band_half_width,
    frame_blobs,
    refine_inset,
    refine_ring,
    ring_blobs,
    ring_kind,
)
from jin_glyph.scene import Cell
from PIL import Image, ImageDraw

CELL = 30.0


def blank(size: int = 600) -> Image.Image:
    return Image.new("L", (size, size), 235)


def on_circle(center: tuple[float, float], radius: float, angle: float) -> tuple[float, float]:
    rad = math.radians(angle)
    return (center[0] + radius * math.cos(rad), center[1] + radius * math.sin(rad))


def stroke(draw: ImageDraw.ImageDraw, at: tuple[float, float], size: float = 0.7 * CELL) -> None:
    """手描きの字の代わり: 升の中の縦線 1 本と横線 1 本(つながった画)。"""
    x, y = at
    h = size / 2
    draw.line((x - h, y, x + h, y), fill=20, width=3)
    draw.line((x, y - h, x, y + h), fill=20, width=3)


def dots(draw: ImageDraw.ImageDraw, at: tuple[float, float]) -> None:
    """点の字(ドットの清書体や手描きの「:」の代わり): 字の大きさの 0.15 倍の隙間で離れた点が 3 つ横に並ぶ。"""
    x, y = at
    for k in (-1, 0, 1):
        cx = x + k * 0.3 * CELL
        draw.ellipse((cx - 2, y - 2, cx + 2, y + 2), fill=20)


def test_ring_blobs_follow_the_circle_clockwise_from_the_start() -> None:
    image = blank()
    draw = ImageDraw.Draw(image)
    center, radius = (300.0, 300.0), 200.0
    angles = [TOP + k * 360.0 / 20 for k in range(9)]  # 12 時から時計回りに 9 字(間隔 ≈ 2 字)
    for angle in angles:
        stroke(draw, on_circle(center, radius, angle))
    blobs = ring_blobs(image, center, radius, 0.75 * CELL, TOP, CELL)
    assert len(blobs) == len(angles)
    for blob, angle in zip(blobs, angles, strict=True):
        x, y = on_circle(center, radius, angle)
        assert blob.box[0] <= x <= blob.box[2] and blob.box[1] <= y <= blob.box[3]
    assert blobs[0].direction == "left to right"  # 12 時の接線は右向き
    assert blobs[5].direction == "top to bottom"  # 3 時(90°)の接線は下向き


def test_a_character_made_of_separate_dots_is_one_blob() -> None:
    image = blank()
    draw = ImageDraw.Draw(image)
    center, radius = (300.0, 300.0), 200.0
    dots(draw, on_circle(center, radius, TOP))
    stroke(draw, on_circle(center, radius, TOP + 12.0))
    blobs = ring_blobs(image, center, radius, 0.75 * CELL, TOP, CELL)
    assert len(blobs) == 2


def test_the_blob_straddling_the_start_comes_first_and_the_one_just_before_comes_last() -> None:
    image = blank()
    draw = ImageDraw.Draw(image)
    center, radius = (300.0, 300.0), 200.0
    for angle in (TOP + 1.0, TOP + 15.0, TOP - 15.0):
        stroke(draw, on_circle(center, radius, angle))
    blobs = ring_blobs(image, center, radius, 0.75 * CELL, TOP, CELL)
    xs = [(b.box[0] + b.box[2]) / 2 for b in blobs]
    assert len(blobs) == 3
    assert xs[0] == pytest.approx(on_circle(center, radius, TOP + 1.0)[0], abs=CELL / 2)
    assert xs[1] > xs[0] > xs[2]  # 時計回り: 右へ進み、12 時の手前の字が最後


def test_ink_off_the_band_is_not_read() -> None:
    image = blank()
    draw = ImageDraw.Draw(image)
    center, radius = (300.0, 300.0), 200.0
    draw.ellipse((300 - 120, 300 - 120, 300 + 120, 300 + 120), outline=20, width=3)  # 図形の円
    stroke(draw, on_circle(center, radius, 0.0))
    assert len(ring_blobs(image, center, radius, 0.75 * CELL, TOP, CELL)) == 1


def test_refine_ring_pulls_a_rough_centre_and_radius_onto_the_ink() -> None:
    image = blank()
    draw = ImageDraw.Draw(image)
    center = (300.0, 310.0)
    radii = (150.0, 200.0)
    for radius in radii:
        for k in range(24):
            stroke(draw, on_circle(center, radius, TOP + k * 15.0), size=0.5 * CELL)
    refined, got = refine_ring(image, (309.0, 302.0), (160.0, 191.0), CELL)
    assert math.dist(refined, center) < 1.5
    assert got == pytest.approx(radii, abs=1.5)


def test_refine_ring_keeps_the_rough_values_without_ink() -> None:
    assert refine_ring(blank(), (300.0, 300.0), (200.0,), CELL) == ((300.0, 300.0), [200.0])


def test_frame_blobs_go_clockwise_from_the_top_left() -> None:
    image = blank()
    draw = ImageDraw.Draw(image)
    inset = 45.0
    marks = [
        (150.0, inset),
        (300.0, inset),
        (600 - inset, 200.0),
        (300.0, 600 - inset),
        (inset, 400.0),
    ]
    for mark in marks:
        stroke(draw, mark)
    blobs = frame_blobs(image, 600, (inset,) * 4, 0.75 * CELL, CELL)
    centers = [((b.box[0] + b.box[2]) / 2, (b.box[1] + b.box[3]) / 2) for b in blobs]
    assert centers == pytest.approx(marks, abs=3.0)
    assert [b.direction for b in blobs] == [
        "left to right",
        "left to right",
        "top to bottom",
        "right to left",
        "bottom to top",
    ]


def test_refine_inset_finds_each_row_per_edge() -> None:
    image = blank()
    draw = ImageDraw.Draw(image)
    for x in range(120, 480, 40):
        stroke(draw, (x, 40.0))  # 上の行は 40 px
        stroke(draw, (x, 600 - 50.0))  # 下の行は 50 px
    got = refine_inset(image, 600, 45.0, CELL)
    assert got[0] == pytest.approx(40.0, abs=1.5)
    assert got[2] == pytest.approx(50.0, abs=1.5)
    assert got[1] == got[3] == 45.0  # 墨の無い辺は元のまま


def test_band_half_width_shrinks_between_close_turns() -> None:
    assert band_half_width([100.0], 0, CELL) == pytest.approx(0.75 * CELL)
    assert band_half_width([100.0, 130.0, 200.0], 1, CELL) == pytest.approx(0.48 * 30.0)


def _ring(head: str, center: tuple[float, float], radius: float = 0.0) -> RingText:
    cells = [Cell(t="struct", v=START_MARK), Cell(t="struct", v=head), Cell(t="latin", v="x")]
    return RingText(center=center, at=center, cells=cells, radius=radius)


def test_ring_kind_comes_from_the_first_structure_mark() -> None:
    assert ring_kind(_ring("s_circle", (0, 0)).cells) == "circle"
    assert ring_kind(_ring("s_rite", (0, 0)).cells) == "rite"
    assert ring_kind(_ring("s_set", (0, 0)).cells) is None
    assert ring_kind([Cell(t="struct", v=START_MARK)]) is None


def test_assemble_names_the_rings_like_the_full_circle_layout() -> None:
    """陣は棚の順(左上が root)、手順陣は持ち主の周りを 12 時から時計回り(12 時の環が少し左に倒れていても先頭)。"""
    rings = [
        _ring("s_rite", (300.0, 520.0)),  # 6 時 → r0_1
        _ring("s_circle", (900.0, 300.0)),  # 2 つ目の陣 → c1
        _ring("s_rite", (296.0, 80.0)),  # ほぼ 12 時(少し左)→ r0_0
        _ring("s_circle", (310.0, 300.0)),  # 中心に近い → c0(root)
        _ring("s_rite", (900.0, 80.0)),  # c1 の手順陣 → r1_0
        _ring("s_set", (600.0, 600.0)),  # 陣でも手順陣でもない → u0
    ]
    figures, bands = assemble(rings, [], (320.0, 320.0), (1.0, 2.0))
    assert [f.id for f in figures] == ["frame", "c0", "c1", "r0_0", "r0_1", "r1_0", "u0"]
    assert [f.kind for f in figures] == [
        "frame",
        "circle",
        "circle",
        "rite",
        "rite",
        "rite",
        "ring",
    ]
    assert [b.owner for b in bands] == [f.id for f in figures]
    assert figures[0].at == (1.0, 2.0)
    assert figures[1].at == (310.0, 300.0)


def test_circles_are_numbered_in_the_shelf_order_of_the_full_circle() -> None:
    """#118: 完全陣は陣の塊を左上から棚に詰める。root は額縁の中心ではなく左上の塊、残りは段ごとに左から。
    手描きのずれ(上端が数画素揃わない)は同じ段とみなす。"""
    # c0: 中心 (130, 155)・張り出し 60 → 上端 95。c1: 手順陣が 12 時に 140 離れて張り出し 170 → 中心は上端 95 + 170。
    # 2 段目は 1 段目の高さ 340 の下
    rings = [
        _ring("s_circle", (700.0, 268.0), 60.0),  # 1 段目の右(上端は 98・手描きのずれ 3)→ c1
        _ring("s_circle", (130.0, 500.0), 60.0),  # 2 段目 → c2
        _ring("s_circle", (130.0, 155.0), 60.0),  # 左上(額縁の中心から遠い)→ c0
        _ring("s_rite", (700.0, 128.0), 30.0),  # c1 の 12 時 → r1_0
    ]
    figures, _ = assemble(rings, [], (450.0, 450.0), (0.0, 0.0))
    at = {f.id: f.at for f in figures}
    assert at["c0"] == (130.0, 155.0)
    assert at["c1"] == (700.0, 268.0)
    assert at["c2"] == (130.0, 500.0)
    assert at["r1_0"] == (700.0, 128.0)


def test_a_rite_without_any_circle_is_left_for_the_parser() -> None:
    figures, _ = assemble([_ring("s_rite", (0.0, 0.0))], [], (0.0, 0.0), (0.0, 0.0))
    assert [f.id for f in figures] == ["frame", "u0"]
