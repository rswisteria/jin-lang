"""銘環と連環陣の配置(`jin_render.v2.full_layout`)。単位は升。"""

from __future__ import annotations

import itertools
import math
from pathlib import Path

import pytest
from jin_core.check import check_text
from jin_core.v2.glyph import START_MARK
from jin_core.v2.model import JinFileV2
from jin_render.v2 import geometry as geo
from jin_render.v2.full_layout import place, ring_cells, ring_outer
from jin_render.v2.inscribe import InkCell

REPO_ROOT = Path(__file__).resolve().parents[3]
PROGRAMS = sorted((REPO_ROOT / "examples-v2").glob("*/*.jin")) + sorted(
    (REPO_ROOT / "tests/fixtures/v2-programs").glob("*.jin")
)


def load(path: Path) -> JinFileV2:
    model = check_text(path.read_text(encoding="utf-8"), path.name).model
    assert isinstance(model, JinFileV2)
    return model


def band(n: int) -> list[InkCell]:
    head = [InkCell("struct", "s_rite", "/x", "rite")]
    return head + [InkCell("latin", "a", "/x/name", "rite") for _ in range(n - 1)]


def test_a_long_band_wraps_onto_outer_rings_with_cont() -> None:
    placed = ring_cells(band(500), 0.0, 0.0, 10.0)
    rings = sorted({c.ring for c in placed})
    assert len(rings) >= 2
    assert placed[0].ring == 0 and placed[0].cell.v == START_MARK and placed[0].angle == geo_top()
    for ring in rings[:-1]:
        on_ring = [c for c in placed if c.ring == ring]
        assert on_ring[-1].cell.v == "cont", ring
    payload = [
        c.cell for c in placed if not (c.cell.v in (START_MARK, "cont") and c.cell.t != "latin")
    ]
    assert len(payload) == 500


def geo_top() -> float:
    return -90.0


def test_ring_cells_do_not_overlap() -> None:
    placed = ring_cells(band(300), 3.0, -2.0, 8.0)
    for ring in {c.ring for c in placed}:
        on_ring = [c for c in placed if c.ring == ring]
        for a, b in itertools.pairwise(on_ring):
            # 升は正立の 1×1 の正方形。重ならないのは x か y の差が 1 以上のとき(最終レビュー #2)
            dx, dy = abs(a.center[0] - b.center[0]), abs(a.center[1] - b.center[1])
            assert max(dx, dy) >= 1.0 - 1e-9, (ring, a.angle, b.angle)


def test_ring_outer_matches_the_rings_used() -> None:
    placed = ring_cells(band(300), 0.0, 0.0, 8.0)
    last = max(c.ring for c in placed)
    assert ring_outer(300, 8.0) == pytest.approx(8.0 + (last + 1) * geo.FULL_RING_PITCH)


@pytest.mark.parametrize("path", PROGRAMS, ids=lambda p: p.stem)
def test_no_two_circles_overlap(path: Path) -> None:
    placement = place(load(path))
    discs = [(placement.circles[i], placement.circle_radius[i]) for i in placement.circles] + [
        (placement.rites[k], placement.rite_radius[k]) for k in placement.rites
    ]
    for (c1, r1), (c2, r2) in itertools.combinations(discs, 2):
        assert math.dist(c1, c2) >= r1 + r2 + geo.FULL_ORBIT_GAP - 1e-6, path.name
    for center, radius in discs:
        assert abs(center[0]) + radius <= placement.half - geo.FULL_FRAME_MARGIN + 1e-6
        assert abs(center[1]) + radius <= placement.half - geo.FULL_FRAME_MARGIN + 1e-6


def test_placement_is_deterministic() -> None:
    model = load(REPO_ROOT / "examples-v2/tetris/tetris.jin")
    assert place(model) == place(model)


def test_fib_has_a_single_cluster_with_the_root_at_the_centre() -> None:
    placement = place(load(REPO_ROOT / "examples-v2/fib/fib.jin"))
    assert placement.circles == {0: (0.0, 0.0)}
    assert set(placement.rites) == {(0, 0), (0, 1)}
