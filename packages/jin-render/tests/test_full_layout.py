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


@pytest.mark.parametrize("name", ["fib", "tetris"])
def test_the_public_geometry_reproduces_the_layout(name: str) -> None:
    # S3: デコーダは配置の規則を再実装せず、この公開の関数だけで位置を求める
    from jin_render.v2.full import frame_positions
    from jin_render.v2.full_layout import (
        circle_inner,
        orbit_centers,
        orbit_distance,
        ring_capacity,
        ring_slot_center,
        rite_inner,
        slot_kinds,
    )
    from jin_render.v2.inscribe import circle_ring, rite_ring

    model = load(REPO_ROOT / f"examples-v2/{name}/{name}.jin")
    placement = place(model)
    for ci, (cx, cy) in placement.circles.items():
        cells = circle_ring(model, ci)
        placed = ring_cells(cells, cx, cy, circle_inner())
        kinds = slot_kinds(len(cells), circle_inner())
        assert [
            (p.ring, p.cell.v if k == "cont" else None)
            for p, (_, _, k) in zip(placed, kinds, strict=True)
        ] == [(r, "cont" if k == "cont" else None) for r, _, k in kinds]
        for p, (ring, slot, _) in zip(placed, kinds, strict=True):
            assert ring_slot_center(cx, cy, circle_inner(), ring, slot) == pytest.approx(p.center)
            assert slot < ring_capacity(ring, circle_inner())
        rites = [k for k in placement.rites if k[0] == ci]
        if rites:
            radii = [placement.rite_radius[k] for k in rites]
            distance = orbit_distance(placement.circle_radius[ci], radii)
            assert orbit_centers(cx, cy, distance, len(rites)) == pytest.approx(
                [placement.rites[k] for k in rites]
            )
            for k in rites:
                assert len(rite_ring(model, *k)) >= 1
    assert len(frame_positions(10, placement.half)) == 10
    assert rite_inner() > circle_inner()


def test_slot_kinds_never_overrun_a_ring() -> None:
    """周の番号は周の升の数を越えず、各周の最後の升は継ぎの紋か列の最後の字(到達しない枝を消した根拠)。"""
    from jin_render.v2.full_layout import ring_capacity, slot_kinds

    for inner in (6.0, 13.5, 27.5):
        for count in range(400):
            kinds = slot_kinds(count, inner)
            assert sum(1 for *_, what in kinds if what == "cell") == count
            for ring, slot, what in kinds:
                assert slot < ring_capacity(ring, inner)
                if what == "cont":
                    assert slot == ring_capacity(ring, inner) - 1


def _extent(placement, ci: int) -> float:
    cx, cy = placement.circles[ci]
    parts = [((cx, cy), placement.circle_radius[ci])] + [
        (placement.rites[k], placement.rite_radius[k]) for k in placement.rites if k[0] == ci
    ]
    return max(max(abs(x - cx), abs(y - cy)) + r for (x, y), r in parts)


@pytest.mark.parametrize("path", PROGRAMS, ids=lambda p: p.stem)
def test_clusters_are_packed_on_shelves_from_the_top_left(path: Path) -> None:
    """#118: 陣の塊(張り出し e の正方形)は root → circles[] の順に、額縁の内側の左上から棚に詰める。
    塊どうしは FULL_ORBIT_GAP 以上離れ、同じ段の塊は上端が揃い、段は上から下へ。"""
    from jin_render.v2.full_layout import frame_margin

    model = load(path)
    placement = place(model)
    names = [c.name for c in model.circles]
    root = names.index(model.root) if model.root in names else 0
    order = [root] + [ci for ci in range(len(model.circles)) if ci != root]
    margin = frame_margin(len(placement.inscription.frame), placement.half)
    left = -placement.half + margin
    boxes = []
    for ci in order:
        (cx, cy), e = placement.circles[ci], _extent(placement, ci)
        boxes.append((cx - e, cy - e, cx + e, cy + e))
    first = boxes[0]
    assert first[0] == pytest.approx(left) and first[1] == pytest.approx(left)
    for a, b in itertools.combinations(boxes, 2):
        apart_x = max(a[0], b[0]) - min(a[2], b[2])
        apart_y = max(a[1], b[1]) - min(a[3], b[3])
        assert max(apart_x, apart_y) >= geo.FULL_ORBIT_GAP - 1e-6, path.name
    for prev, box in itertools.pairwise(boxes):
        same_row = box[1] == pytest.approx(prev[1])
        assert same_row or box[1] > prev[1], path.name  # 段は下へ
        if same_row:
            assert box[0] > prev[0], path.name  # 同じ段は右へ
        else:
            assert box[0] == pytest.approx(left), path.name  # 新しい段は左端から


def test_a_single_circle_stays_in_the_middle() -> None:
    """陣が 1 つなら塊は額縁の中心(以前の配置と同じ・fib / clicker の完全陣はバイト不変)。"""
    model = load(REPO_ROOT / "examples-v2/fib/fib.jin")
    placement = place(model)
    assert placement.circles == {0: (0.0, 0.0)}
    assert placement.half == pytest.approx(_extent(placement, 0) + geo.FULL_FRAME_MARGIN)


@pytest.mark.parametrize(
    ("name", "most"),
    [("paddle", 268.0), ("tetris", 387.0), ("othello", 448.0)],
)
def test_the_packing_shrinks_programs_with_several_circles(name: str, most: float) -> None:
    """#118 の実測(glyph.md §8): 以前は paddle 307.7・tetris 543.1・othello 614.5 升。"""
    placement = place(load(REPO_ROOT / "examples-v2" / name / f"{name}.jin"))
    assert 2.0 * placement.half <= most
