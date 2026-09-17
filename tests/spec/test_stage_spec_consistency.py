"""鑑賞ページの正典 `docs/spec/v2/stage.md` と、runtime.md / v2 layout.md の突合。

設計書: docs/superpowers/specs/2026-09-17-jin-stage-design.md §2 / §4.2。
"""

from __future__ import annotations

import re
from pathlib import Path

from jin_render import DATA_JIN_KINDS_V2

REPO_ROOT = Path(__file__).resolve().parents[2]
STAGE = REPO_ROOT / "docs/spec/v2/stage.md"
RUNTIME = REPO_ROOT / "docs/spec/v2/runtime.md"
LAYOUT = REPO_ROOT / "docs/spec/v2/layout.md"

#: 層の表に載せず、形から層を決める種別（環の半径 / ステップの深さ）。
COMPUTED_KINDS = {"circle", "step", "step-edge"}


def machine_table(path: Path, name: str) -> list[list[str]]:
    """`<!-- machine-readable: name -->` から閉じ印までの表の本文行を、セルの列にして返す。"""
    text = path.read_text(encoding="utf-8")
    match = re.search(
        rf"<!-- machine-readable: {re.escape(name)} -->\n(.*?)<!-- /machine-readable -->",
        text,
        re.DOTALL,
    )
    assert match is not None, f"{path.name} に {name} の表が無い"
    rows = [line for line in match.group(1).splitlines() if line.startswith("|")]
    return [[cell.strip() for cell in row.strip("|").split("|")] for row in rows[2:]]


def backticked(cell: str) -> list[str]:
    return re.findall(r"`([^`]+)`", cell)


def stage_layers() -> dict[str, tuple[int, float]]:
    """種別 → (層, 高さ)。"""
    table: dict[str, tuple[int, float]] = {}
    for layer, height, kinds in machine_table(STAGE, "stage-layers"):
        for kind in backticked(kinds):
            assert kind not in table, f"{kind} が 2 つの層にある"
            table[kind] = (int(layer), float(height))
    return table


def stage_effects() -> dict[str, tuple[str, str]]:
    """トレースの kind → (演出名, 強さ)。"""
    return {
        backticked(kind)[0]: (
            backticked(effect)[0] if backticked(effect) else "",
            strength.strip("`"),
        )
        for kind, effect, strength in machine_table(STAGE, "stage-effects")
    }


def test_every_drawn_kind_has_a_layer_or_is_computed_from_its_shape() -> None:
    assert set(stage_layers()) | COMPUTED_KINDS == set(DATA_JIN_KINDS_V2)
    assert not set(stage_layers()) & COMPUTED_KINDS


def test_the_layers_are_the_six_heights_of_the_design() -> None:
    heights = sorted({value for value in stage_layers().values()})
    assert heights == [(0, -0.32), (1, 0.0), (2, 0.07), (3, 0.14), (4, 0.21), (5, 0.28)]


def test_the_effect_table_covers_exactly_the_trace_kinds_of_the_runtime() -> None:
    runtime_kinds = {backticked(row[0])[0] for row in machine_table(RUNTIME, "trace-kinds")}
    assert set(stage_effects()) == runtime_kinds
    assert len(runtime_kinds) == 13


def test_strength_is_one_of_three_words_and_frame_does_not_glow() -> None:
    effects = stage_effects()
    assert {strength for _, strength in effects.values()} <= {"once", "habit", "none"}
    assert effects["frame"] == ("", "none")
    once = {kind for kind, (_, strength) in effects.items() if strength == "once"}
    assert once == {"enter", "exit", "emit", "transfer", "finish", "assert", "error"}


def test_the_ring_radii_named_by_the_stage_are_the_layout_radii() -> None:
    layout = [float(row[1]) for row in machine_table(LAYOUT, "ring-radii")]
    stage = [float(row[1]) for row in machine_table(STAGE, "stage-ring-layers")]
    assert stage == layout == [0.35, 0.55, 0.75, 0.95]
