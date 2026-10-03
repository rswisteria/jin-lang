"""型紙(陣書き S4・`jin render --sheet S|M`・glyph.md §10)の幾何と SVG。

幾何は `sheet_layout` の 1 関数で、描く側と写真から切り出す側(`jin_glyph.recognize`)が同じ表を読む。
SVG を直したら `uv run pytest packages/jin-render --snapshot-update` で更新し、差分を読んでからコミット。
"""

from __future__ import annotations

import itertools
import math
import re
from pathlib import Path

import pytest
from jin_core.check import check_file
from jin_render.v2 import geometry as geo
from jin_render.v2.inscribe import circle_ring, frame_band, rite_ring
from jin_render.v2.sheet import render_sheet
from jin_render.v2.sheet_layout import (
    GRADES,
    SHEET_CELL_MM,
    SHEET_GRADE_CELL,
    sheet_layout,
)

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("grade", GRADES)
def test_no_two_slots_overlap(grade: str) -> None:
    """升は正立の 1 × 1。どの 2 升も x か y の差が 1 以上(重なると書いた字が隣の升に入る)。"""
    centers = [s.center for s in sheet_layout(grade).slots]
    for (ax, ay), (bx, by) in itertools.combinations(centers, 2):
        assert abs(ax - bx) >= 1.0 - 1e-9 or abs(ay - by) >= 1.0 - 1e-9


@pytest.mark.parametrize("grade", GRADES)
def test_every_slot_is_inside_the_frame_and_off_the_talismans_and_the_grade_mark(
    grade: str,
) -> None:
    sheet = sheet_layout(grade)
    t = geo.FULL_TALISMAN
    gx, gy = sheet.grade_mark()
    for s in sheet.slots:
        x, y = s.center
        assert abs(x) + 0.5 <= sheet.half and abs(y) + 0.5 <= sheet.half
        for tx, ty in sheet.talismans():
            assert abs(x - tx) >= t / 2 + 0.5 or abs(y - ty) >= t / 2 + 0.5
        assert (
            abs(x - gx) >= SHEET_GRADE_CELL / 2 + 0.5 or abs(y - gy) >= SHEET_GRADE_CELL / 2 + 0.5
        )


@pytest.mark.parametrize("grade", GRADES)
def test_every_ring_has_one_printed_start_at_twelve_oclock(grade: str) -> None:
    sheet = sheet_layout(grade)
    for ring in sheet.rings:
        slots = sheet.of(ring.owner)
        assert [s.kind for s in slots].count("start") == 1
        start = slots[0]
        assert start.kind == "start"
        assert math.isclose(start.center[0], ring.center[0], abs_tol=1e-9)
        assert start.center[1] < ring.center[1]


def test_the_sheet_is_a_square_of_five_millimetre_cells_that_fits_the_short_side_of_a3() -> None:
    for grade in GRADES:
        assert 2 * sheet_layout(grade).half * SHEET_CELL_MM <= 290.0


def test_the_owners_follow_the_reading_order() -> None:
    assert sheet_layout("S").owners()[:6] == ["frame", "c0", "r0_0", "r0_1", "r0_2", "r0_3"]
    m = sheet_layout("M").owners()
    assert m[:16] == ["frame"] + [
        f"c{k}" if j < 0 else f"r{k}_{j}" for k in range(3) for j in range(-1, 4)
    ]
    for sheet in (sheet_layout("S"), sheet_layout("M")):
        strips = [o for o in sheet.owners() if o.startswith("strip")]
        assert strips == [f"strip{n}" for n in range(len(strips))]
        for owner in strips:
            assert sheet.of(owner)[0].kind == "label"


def _cells(sheet, owner: str) -> int:
    return sum(1 for s in sheet.of(owner) if s.kind == "cell")


@pytest.mark.parametrize("name", ["fib", "clicker"])
def test_fib_and_clicker_fit_the_s_sheet(name: str) -> None:
    """完了の条件の 2 本(設計書 §6 S4)が S の型紙に収まる(溢れた分は続きの帯へ。継ぎの紋 1 升を足して数える)。"""
    model = check_file(ROOT / "examples-v2" / name / f"{name}.jin").model
    sheet = sheet_layout("S")
    assert len(model.circles) == 1 and len(model.circles[0].rites) <= 4
    need = [(len(frame_band(model)), _cells(sheet, "frame"))]
    need.append((len(circle_ring(model, 0)), _cells(sheet, "c0")))
    need += [
        (len(rite_ring(model, 0, j)), _cells(sheet, f"r0_{j}"))
        for j in range(len(model.circles[0].rites))
    ]
    overflow = sum(n - cap + 1 for n, cap in need if n > cap)
    strips = [o for o in sheet.owners() if o.startswith("strip")]
    assert overflow <= sum(_cells(sheet, o) for o in strips)


@pytest.mark.parametrize("grade", GRADES)
def test_the_sheet_svg_is_deterministic_and_has_no_text(grade: str) -> None:
    svg = render_sheet(grade)
    assert svg == render_sheet(grade)
    assert "<text" not in svg
    assert set(re.findall(r'data-jin-kind="([^"]+)"', svg)) <= {"stage", "circle"}


@pytest.mark.parametrize("grade", GRADES)
def test_sheet_svg_snapshot(grade: str, snapshot) -> None:
    assert render_sheet(grade) == snapshot


def test_an_unknown_grade_is_refused() -> None:
    with pytest.raises(ValueError):
        sheet_layout("L")  # type: ignore[arg-type]
