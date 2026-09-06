"""`jin_render.geometry`: 配置規則と星形多角形（docs/spec/layout.md §1 / §2 / §2.1）。"""

from __future__ import annotations

import math

import pytest
from jin_render import geometry as geo


def test_ring_radii_are_the_requirement_values() -> None:
    """要件書 §2.5 / layout.md §1 の 4 本。実装で勝手に変えない。"""
    assert geo.RING_RADII == (
        ("instruction", 0.35),
        ("tools", 0.55),
        ("state", 0.75),
        ("boundary", 0.95),
    )


def test_twelve_o_clock_is_the_first_position() -> None:
    """12 時位置から時計回り（layout.md §2）。SVG は y 軸が下向きなので `-90°` が真上。"""
    frame = geo.root_frame()
    x, y = geo.point(frame, 1.0, geo.angle_at(0, 4))
    assert x == pytest.approx(frame.cx)
    assert y == pytest.approx(frame.cy - frame.scale)


def test_positions_go_clockwise_on_screen() -> None:
    """4 分割の 1 番目は右（3 時）、2 番目は下（6 時）。反時計回りに描いていないこと。"""
    frame = geo.root_frame()
    right = geo.point(frame, 1.0, geo.angle_at(1, 4))
    bottom = geo.point(frame, 1.0, geo.angle_at(2, 4))
    assert right[0] == pytest.approx(frame.cx + frame.scale)
    assert right[1] == pytest.approx(frame.cy)
    assert bottom[1] == pytest.approx(frame.cy + frame.scale)


@pytest.mark.parametrize(
    ("n", "expected"), [(3, 1), (4, 1), (5, 2), (6, 1), (7, 3), (8, 3), (9, 4), (10, 3), (12, 5)]
)
def test_star_step_matches_the_declared_formula(n: int, expected: int) -> None:
    """layout.md §2.1: `k = max{ j : 1 <= j < n/2 かつ gcd(n, j) == 1 }`。`n < 5` は k = 1。"""
    assert geo.star_step(n) == expected


def test_star_step_is_not_half_of_n() -> None:
    """変異「k を n//2 にする」を捕まえる側の非空虚性。n=6 / n=8 で値が割れる。"""
    assert geo.star_step(6) != 6 // 2
    assert geo.star_step(8) != 8 // 2


def test_angle_at_rejects_an_empty_ring() -> None:
    with pytest.raises(ValueError):
        geo.angle_at(0, 0)


def test_nested_frame_scales_but_keeps_the_ratio() -> None:
    frame = geo.root_frame()
    nested = frame.nested(100.0, 200.0, geo.NESTED_SCALE)
    assert nested.cx == 100.0
    assert nested.cy == 200.0
    assert nested.scale == pytest.approx(frame.scale * geo.NESTED_SCALE)


def test_nested_circle_fits_inside_the_boundary_ring() -> None:
    """入れ子の小陣（深さ 1）が境界環をはみ出さないこと。"""
    assert geo.RING_TOOLS + geo.NESTED_SCALE * geo.RING_BOUNDARY < geo.RING_BOUNDARY + 0.001


def test_trace_ring_is_outside_the_boundary_and_inside_the_canvas() -> None:
    """トレースの点は境界環の外・キャンバスの中（要件書 §4）。"""
    half_extent = (geo.CANVAS_PX / 2.0) / geo.UNIT_PX
    assert geo.RING_BOUNDARY < geo.TRACE_RING
    assert geo.TRACE_RING + geo.TRACE_DOT_RADIUS < half_extent


@pytest.mark.parametrize("sweep", [90.0, 180.0, 360.0, -120.0, 30.0])
def test_arc_segments_stay_on_the_circle(sweep: float) -> None:
    """3 次ベジェ近似が円周から離れないこと（制御点の係数 4/3*tan(θ/4) の確認）。"""
    frame = geo.root_frame()
    radius = geo.RING_BOUNDARY
    start, segments = geo.arc_segments(frame, radius, geo.TOP_ANGLE, sweep)
    points = [start] + [segment[2] for segment in segments]
    for x, y in points:
        assert math.hypot(x - frame.cx, y - frame.cy) == pytest.approx(radius * frame.scale)
    # 各セグメントの中点（t=0.5）も円周のごく近くにあること
    current = start
    for c1, c2, end in segments:
        mid = tuple((current[i] + 3 * c1[i] + 3 * c2[i] + end[i]) / 8.0 for i in range(2))
        error = abs(math.hypot(mid[0] - frame.cx, mid[1] - frame.cy) - radius * frame.scale)
        assert error < 0.05, error
        current = end


def test_arc_segments_split_at_ninety_degrees() -> None:
    _, segments = geo.arc_segments(geo.root_frame(), 1.0, 0.0, 360.0)
    assert len(segments) == 4


def test_complement_of_no_gap_is_the_whole_circle() -> None:
    assert geo.complement_arcs([]) == [(0.0, 360.0)]


def test_complement_splits_around_one_gap() -> None:
    arcs = geo.complement_arcs([(10.0, 30.0)])
    assert arcs == [(0.0, 10.0), (30.0, 330.0)]


def test_complement_handles_a_gap_that_wraps_past_zero() -> None:
    """12 時ちょうどにある `await` の欠けは 0° をまたぐ。"""
    arcs = geo.complement_arcs([(-8.0, 8.0)])
    assert arcs == [(8.0, 344.0)]


def test_complement_merges_overlapping_gaps() -> None:
    arcs = geo.complement_arcs([(10.0, 40.0), (30.0, 60.0)])
    assert arcs == [(0.0, 10.0), (60.0, 300.0)]


def test_complement_is_empty_when_gaps_cover_everything() -> None:
    assert geo.complement_arcs([(0.0, 360.0)]) == []
