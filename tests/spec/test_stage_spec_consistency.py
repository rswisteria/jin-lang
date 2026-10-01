"""鑑賞ページの正典 `docs/spec/v2/stage.md` と、runtime.md / v2 layout.md の突合。

設計書: docs/superpowers/specs/2026-09-17-jin-stage-design.md §2 / §4.2。
"""

from __future__ import annotations

import json
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


def stage_powers() -> dict[str, str]:
    """力 → 宝玉（stage.md §2.1）。"""
    return {
        backticked(power)[0]: backticked(gem)[0]
        for power, gem in machine_table(STAGE, "stage-powers")
    }


def stage_state_gems() -> dict[str, str]:
    """記憶の型 → 宝玉（型紙の行は「型紙」のまま）。"""
    return {
        (backticked(kind) or [kind])[0]: backticked(gem)[0]
        for kind, gem in machine_table(STAGE, "stage-state-gems")
    }


def stage_gems() -> dict[str, tuple[int, float, int | None]]:
    """宝玉 → (色, 屈折率, 2 色目)。色は 0xRRGGBB の整数。"""
    table: dict[str, tuple[int, float, int | None]] = {}
    for gem, color, ior, second in machine_table(STAGE, "stage-gems"):
        seconds = backticked(second)
        table[backticked(gem)[0]] = (
            int(backticked(color)[0].lstrip("#"), 16),
            float(ior),
            int(seconds[0].lstrip("#"), 16) if seconds else None,
        )
    return table


def stage_metals() -> list[tuple[str, str, int, float]]:
    """地金の行（順, 地金, 色, 粗さ）を表の順に。"""
    return [
        (order, backticked(metal)[0], int(backticked(color)[0].lstrip("#"), 16), float(roughness))
        for order, metal, color, roughness in machine_table(STAGE, "stage-metals")
    ]


def test_every_gem_named_by_the_meaning_tables_has_a_color() -> None:
    named = set(stage_powers().values()) | set(stage_state_gems().values())
    named |= {"topaz", "diamond", "ruby", "garnet", "emerald", "gold", "onyx", "crystal"}
    assert named <= set(stage_gems()), named - set(stage_gems())


def test_the_powers_are_the_namespaces_of_the_abilities_and_the_two_sigil_kinds() -> None:
    abilities = json.loads((REPO_ROOT / "schemas" / "abilities.json").read_text(encoding="utf-8"))
    namespaces = {namespace["name"] for namespace in abilities["namespaces"]}
    assert set(stage_powers()) == namespaces | {"summon", "agent"}


def test_the_metals_start_at_the_root_and_cycle_through_three_others() -> None:
    metals = stage_metals()
    assert [order for order, *_ in metals] == ["root", "1", "2", "3"]
    assert len({metal for _, metal, _, _ in metals}) == 4


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


def test_strength_is_one_of_three_words_and_frame_only_beats() -> None:
    """設計書 2026-10-01 §5.1: `frame` は陣の鼓動（`pulse`・強さ `beat`）。発動の演出ではない。"""
    effects = stage_effects()
    assert {strength for _, strength in effects.values()} <= {"once", "habit", "beat"}
    assert effects["frame"] == ("pulse", "beat")
    assert [kind for kind, (_, strength) in effects.items() if strength == "beat"] == ["frame"]
    once = {kind for kind, (_, strength) in effects.items() if strength == "once"}
    assert once == {"enter", "exit", "emit", "transfer", "finish", "assert", "error"}


def test_the_ring_radii_named_by_the_stage_are_the_layout_radii() -> None:
    layout = [float(row[1]) for row in machine_table(LAYOUT, "ring-radii")]
    stage = [float(row[1]) for row in machine_table(STAGE, "stage-ring-layers")]
    assert stage == layout == [0.35, 0.55, 0.75, 0.95]
