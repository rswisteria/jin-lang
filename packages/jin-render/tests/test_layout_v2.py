"""`jin_render.v2` の `data-jin` 契約とレイアウト規則（docs/spec/v2/layout.md §1〜§5 / §7 / §8）。"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from jin_core.check import check_file
from jin_core.pointer import pointer_exists
from jin_core.v2.model import JinFileV2
from jin_render import DATA_JIN_KINDS, DATA_JIN_KINDS_V2, RenderError, render
from jin_render import geometry as geo
from jin_render.svg import ACCENT
from jin_render.v2 import geometry as g2
from jin_render.v2.layout import split_focus, type_resolves
from jin_render.v2.rite import CAST_HOST, CAST_RITE, CAST_SUMMON, classify_cast, place_block

from .conftest import (
    ERROR_FIXTURES_V2,
    EXAMPLES_V2,
    PROGRAMS_V2,
    SVG_NS,
    contract_elements,
    kinds,
    load_model_v2,
    model_v2_from,
    pointers,
)
from .test_layout import NUMERIC_ATTRS

ALL_V2_FILES = sorted(EXAMPLES_V2.glob("*/*.jin")) + sorted(PROGRAMS_V2.glob("*.jin"))


def _focuses(model: JinFileV2) -> list[str | None]:
    out: list[str | None] = [None]
    for circle in model.circles:
        out.append(circle.name)
        out += [f"{circle.name}/{rite.name}" for rite in circle.rites]
    return out


# ---------------------------------------------------------------- 契約（§4）


@pytest.mark.parametrize("path", ALL_V2_FILES, ids=lambda p: p.name)
def test_every_element_carries_both_attributes_and_a_v2_kind(path: Path) -> None:
    """描かれたすべての要素が `data-jin` と 13 種の `data-jin-kind` を持つ。v1 の 9 種は混ぜない。"""
    model = load_model_v2(path)
    for focus in _focuses(model):
        svg = render(model, focus=focus)
        assert all(pointer is not None for pointer in pointers(svg)), (path, focus)
        drawn = kinds(svg)
        assert drawn <= set(DATA_JIN_KINDS_V2), (path, focus, drawn - set(DATA_JIN_KINDS_V2))
        assert not (drawn & (set(DATA_JIN_KINDS) - set(DATA_JIN_KINDS_V2))), (path, focus)


@pytest.mark.parametrize("path", ALL_V2_FILES, ids=lambda p: p.name)
def test_every_pointer_and_referent_resolves_in_the_model(path: Path) -> None:
    model = load_model_v2(path)
    document = model.model_dump(mode="json", by_alias=True)
    for focus in _focuses(model):
        for element in contract_elements(render(model, focus=focus)):
            assert pointer_exists(document, element.get("data-jin", "")), (
                path,
                focus,
                element.attrib,
            )
            ref = element.get("data-jin-ref")
            if ref is not None:
                assert pointer_exists(document, ref), (path, focus, element.attrib)
                assert re.fullmatch(r"/circles/\d+", ref), ref


def test_the_thirteen_kinds_are_all_drawn_by_paddle_and_transfer(paddle: JinFileV2) -> None:
    """設計書 §12 の完了条件「13 種が paddle で全部出る」。

    paddle には `delegate` が無い（§2.2 の例に縛られる）ので、`delegate` だけは
    `tests/fixtures/v2-programs/transfer.jin` で補う（設計書 §11 #30）。
    """
    drawn: set[str] = set()
    for focus in (None, "Play", "Play/step"):
        drawn |= kinds(render(paddle, focus=focus))
    assert set(DATA_JIN_KINDS_V2) - drawn == {"delegate"}, sorted(drawn)
    drawn |= kinds(render(load_model_v2(PROGRAMS_V2 / "transfer.jin")))
    assert drawn == set(DATA_JIN_KINDS_V2)


def test_data_jin_kinds_v2_has_thirteen_distinct_values() -> None:
    assert len(DATA_JIN_KINDS_V2) == 13
    assert len(set(DATA_JIN_KINDS_V2)) == 13


# ---------------------------------------------------------------- 決定性の書式（v1 §4 を継承）


@pytest.mark.parametrize("focus", [None, "Play", "Play/step", "Result/show"])
def test_all_geometry_numbers_are_written_with_three_decimals(
    paddle: JinFileV2, focus: str | None
) -> None:
    svg = render(paddle, focus=focus)
    for element in ET.fromstring(svg).iter():
        for name, value in element.attrib.items():
            if name not in NUMERIC_ATTRS:
                continue
            for number in re.findall(r"-?\d+(?:\.\d+)?", value):
                assert re.fullmatch(r"-?\d+\.\d{3}", number), (name, value)


def test_no_elliptical_arc_and_no_style(paddle: JinFileV2) -> None:
    svg = render(paddle, focus="Result/show")  # `wait` で環に欠けができる
    assert 'data-jin-kind="step"' in svg
    for element in ET.fromstring(svg).iter(f"{{{SVG_NS}}}path"):
        assert " A " not in element.get("d", "")
    assert "<style" not in svg


# ---------------------------------------------------------------- 額縁と型紙（§1）


def test_the_stage_and_the_form_seals_are_drawn_in_every_view(paddle: JinFileV2) -> None:
    for focus in (None, "Play", "Play/step"):
        svg = render(paddle, focus=focus)
        elements = contract_elements(svg)
        stage = [e for e in elements if e.get("data-jin-kind") == "stage"]
        assert [e.get("data-jin") for e in stage] == ["/stage"] * len(stage)
        texts = [e for e in stage if e.tag == f"{{{SVG_NS}}}text"]
        assert [t.text for t in texts] == ["320×180 @60"]
        forms = [e for e in elements if e.get("data-jin-kind") == "form"]
        assert {e.get("data-jin") for e in forms} == {"/forms/0"}
        assert [e.text for e in forms if e.tag == f"{{{SVG_NS}}}text"] == ["B"]


def test_form_seals_follow_the_array_order_to_the_right() -> None:
    model = model_v2_from(
        [{"name": "A", "core": "go", "rites": [{"name": "go", "steps": []}]}],
        "A",
        forms=[{"name": f"F{i}", "fields": [{"name": "x", "type": "num"}]} for i in range(3)],
    )
    seals = [
        e
        for e in contract_elements(render(model))
        if e.get("data-jin-kind") == "form" and e.tag == f"{{{SVG_NS}}}text"
    ]
    xs = [float(e.get("x", "")) for e in seals]
    assert [e.get("data-jin") for e in seals] == ["/forms/0", "/forms/1", "/forms/2"]
    assert xs == sorted(xs)
    assert math.isclose(xs[1] - xs[0], g2.FORM_SEAL_PITCH * geo.UNIT_PX, abs_tol=0.001)


# ---------------------------------------------------------------- 環と中身（§2）


def _rings(svg: str, base: str) -> list[float]:
    """`base` を指す `<circle>` のうち中心にあるもの（環）の半径（正規化）。"""
    out = []
    for e in contract_elements(svg):
        if e.tag != f"{{{SVG_NS}}}circle" or e.get("data-jin") != base:
            continue
        if float(e.get("cx", "")) == 500.0 and float(e.get("cy", "")) == 500.0:
            out.append(round(float(e.get("r", "")) / geo.UNIT_PX, 3))
    return sorted(out)


def test_rings_are_drawn_only_when_they_exist(paddle: JinFileV2, fib: JinFileV2) -> None:
    assert _rings(render(paddle, focus="Play"), "/circles/1") == [0.35, 0.55, 0.75, 0.95]
    # fib は sigils も boundary も無い: 手順環と記憶環だけ（半径は詰めない）。
    assert _rings(render(fib), "/circles/0") == [0.35, 0.75]


def test_a_flow_circle_draws_no_ring_and_no_core(paddle: JinFileV2) -> None:
    svg = render(paddle)  # root = Game（flow: loop）
    assert _rings(svg, "/circles/0") == []
    assert not any(e.get("data-jin") == "/circles/0/core" for e in contract_elements(svg))
    # flow の弦 2 本（loop: 0→1, 1→0）+ exit の印。
    edges = [e for e in contract_elements(svg) if e.get("data-jin-kind") == "flow-edge"]
    assert {e.get("data-jin") for e in edges} >= {"/circles/0/flow", "/circles/0/flow/exit"}


def test_the_core_names_the_core_rite_and_links_to_it(paddle: JinFileV2) -> None:
    svg = render(paddle, focus="Play")
    core = [e for e in contract_elements(svg) if e.get("data-jin") == "/circles/1/core"]
    texts = [e.text for e in core if e.tag == f"{{{SVG_NS}}}text"]
    assert texts == ["begin"]
    lines = [e for e in core if e.tag == f"{{{SVG_NS}}}line"]
    assert len(lines) == 1  # 核 → `core` の手順（begin = rites[0]・12 時）
    assert float(lines[0].get("x1", "")) == 500.0
    assert float(lines[0].get("y2", "")) < float(lines[0].get("y1", ""))
    # 装飾は `core` の手順の正準 JSON から（塗り潰しの小円・pointer は core）。
    dots = [e for e in core if e.tag == f"{{{SVG_NS}}}circle" and e.get("fill") == "#000000"]
    assert 3 <= len(dots) <= 8


def test_rites_sigils_and_marks_carry_initials(paddle: JinFileV2) -> None:
    svg = render(paddle, focus="Play")
    texts = {
        (e.get("data-jin"), e.text) for e in contract_elements(svg) if e.tag == f"{{{SVG_NS}}}text"
    }
    assert ("/circles/1/rites/0", "B") in texts  # begin
    assert ("/circles/1/rites/3", "P") in texts  # paint
    assert ("/circles/1/sigils/0", "C") in texts  # canvas
    assert ("/circles/1/boundary/on/0", "T") in texts  # tick


def test_on_marks_come_before_guard_marks_on_one_equal_angle_sequence() -> None:
    model = model_v2_from(
        [
            {
                "name": "A",
                "core": "go",
                "rites": [{"name": "go", "steps": []}],
                "boundary": {
                    "on": [{"event": "tick", "rite": "go"}],
                    "guards": [{"assert": "true"}, {"assert": "true"}],
                },
            }
        ],
        "A",
    )
    svg = render(model)
    marks = [
        e
        for e in contract_elements(svg)
        if e.get("data-jin-kind") in ("on", "guard") and e.tag == f"{{{SVG_NS}}}path"
    ]
    assert [e.get("data-jin") for e in marks] == [
        "/circles/0/boundary/on/0",
        "/circles/0/boundary/guards/0",
        "/circles/0/boundary/guards/1",
    ]
    # 3 つで 120 度ずつ: 最初の頂点（12 時）の x 座標が 500 / 500 + r sin120° / 500 − r sin120°。
    xs = [float(e.get("d", "").split()[1]) for e in marks]
    assert xs[0] == 500.0 and xs[1] > 500.0 and xs[2] < 500.0


def test_out_states_are_drawn_double_and_unknown_types_get_a_question_mark() -> None:
    model = model_v2_from(
        [
            {
                "name": "A",
                "core": "go",
                "rites": [{"name": "go", "steps": []}],
                "state": [
                    {"name": "a", "type": "num", "init": "0", "out": True},
                    {"name": "b", "type": "Nope", "init": "0"},
                    {"name": "c", "type": "list<Pointer>", "init": "[]"},
                ],
            }
        ],
        "A",
    )
    elements = contract_elements(render(model))
    by_pointer: dict[str, list[ET.Element]] = {}
    for e in elements:
        by_pointer.setdefault(e.get("data-jin", ""), []).append(e)
    assert [e.tag for e in by_pointer["/circles/0/state/0"]] == [f"{{{SVG_NS}}}path"] * 2
    assert [e.text for e in by_pointer["/circles/0/state/1"] if e.tag == f"{{{SVG_NS}}}text"] == [
        "?"
    ]
    assert [e.tag for e in by_pointer["/circles/0/state/2"]] == [f"{{{SVG_NS}}}path"]


@pytest.mark.parametrize(
    ("type_text", "expected"),
    [
        ("num", True),
        ("list<list<str>>", True),
        ("Pointer", True),
        ("Ball", True),
        ("Nope", False),
        ("list<Nope>", False),
        ("list<", False),
    ],
)
def test_type_resolution(type_text: str, expected: bool) -> None:
    assert type_resolves(type_text, frozenset({"Ball", "Pointer"})) is expected


# ---------------------------------------------------------------- 入れ子と参照（§1 / §7）


def test_summon_nests_one_level_and_points_beyond() -> None:
    model = load_model_v2(PROGRAMS_V2 / "summon.jin")
    svg = render(model, focus="Main")
    root = ET.fromstring(svg)
    groups = [g for g in root.iter(f"{{{SVG_NS}}}g") if g.get("data-jin-kind") == "circle"]
    assert [g.get("data-jin") for g in groups] == ["/circles/0", "/circles/1"]
    sigil = [e for e in contract_elements(svg) if e.get("data-jin") == "/circles/0/sigils/0"]
    # 放射線（ref 無し）+ 外枠の `<g>` と円（ref 有り）。
    assert [e.get("data-jin-ref") for e in sigil].count("/circles/1") == 2


def test_an_unresolved_summon_is_a_dashed_dot_without_a_referent() -> None:
    model = model_v2_from(
        [
            {
                "name": "A",
                "core": "go",
                "rites": [{"name": "go", "steps": []}],
                "sigils": [{"name": "s", "kind": "summon", "circle": "Nope", "rite": "x"}],
            }
        ],
        "A",
    )
    sigil = [
        e for e in contract_elements(render(model)) if e.get("data-jin") == "/circles/0/sigils/0"
    ]
    dots = [e for e in sigil if e.tag == f"{{{SVG_NS}}}circle"]
    assert (
        len(dots) == 1 and dots[0].get("stroke-dasharray") and "data-jin-ref" not in dots[0].attrib
    )


def test_delegates_are_dashed_lines_and_referent_dots() -> None:
    model = load_model_v2(PROGRAMS_V2 / "transfer.jin")
    delegate = [e for e in contract_elements(render(model)) if e.get("data-jin-kind") == "delegate"]
    assert {e.get("data-jin") for e in delegate} == {"/circles/0/delegate/0"}
    assert any(e.tag == f"{{{SVG_NS}}}line" and e.get("stroke-dasharray") for e in delegate)
    assert any(
        e.tag == f"{{{SVG_NS}}}circle" and e.get("data-jin-ref") == "/circles/1" for e in delegate
    )


def test_an_unresolved_core_is_drawn_dashed_without_a_link() -> None:
    model = load_model_v2(ERROR_FIXTURES_V2 / "JIN011_unresolved_core.jin")
    core = [e for e in contract_elements(render(model)) if e.get("data-jin-kind") == "core"]
    circles = [e for e in core if e.tag == f"{{{SVG_NS}}}circle"]
    assert circles and all(e.get("stroke-dasharray") for e in circles)
    assert not any(e.tag == f"{{{SVG_NS}}}line" for e in core)


def test_an_unresolved_root_falls_back_to_the_first_circle_with_a_mark() -> None:
    model = load_model_v2(ERROR_FIXTURES_V2 / "JIN060_root_not_found.jin")
    svg = render(model)
    group = next(
        g for g in ET.fromstring(svg).iter(f"{{{SVG_NS}}}g") if g.get("data-jin") == "/circles/0"
    )
    assert group.get("data-jin-root") == "unresolved"
    assert 'data-jin-root="unresolved"' not in render(model, focus=model.circles[0].name)


MODELABLE_ERROR_FIXTURES = sorted(
    path for path in ERROR_FIXTURES_V2.glob("*.jin") if check_file(path).model is not None
)


def test_there_are_modelable_v2_error_fixtures() -> None:
    assert len(MODELABLE_ERROR_FIXTURES) >= 15


@pytest.mark.parametrize("path", MODELABLE_ERROR_FIXTURES, ids=lambda p: p.name)
def test_render_never_raises_on_a_model_with_semantic_errors(path: Path) -> None:
    """v2 layout.md §7: schema を通るモデルなら意味エラーを含んでいても例外を投げない（全 focus）。"""
    model = load_model_v2(path)
    for focus in _focuses(model):
        svg = render(model, focus=focus)
        ET.fromstring(svg)


def test_empty_rites_and_empty_boundaries_do_not_divide_by_zero() -> None:
    model = model_v2_from(
        [
            {
                "name": "A",
                "core": "go",
                "rites": [{"name": "go", "steps": []}],
                "boundary": {},
            }
        ],
        "A",
    )
    svg = render(model, focus="A/go")
    assert _rings(svg, "/circles/0/rites/0") == []  # ステップが無ければ環も無い
    assert any(e.get("data-jin") == "/circles/0/rites/0/name" for e in contract_elements(svg))
    assert _rings(render(model), "/circles/0") == [0.35, 0.95]


# ---------------------------------------------------------------- focus（§1 / §3）


def test_an_unknown_focus_names_the_candidates(paddle: JinFileV2) -> None:
    with pytest.raises(RenderError) as circle_error:
        render(paddle, focus="Nope")
    assert "Game" in str(circle_error.value) and "Play" in str(circle_error.value)
    with pytest.raises(RenderError) as rite_error:
        render(paddle, focus="Play/nope")
    assert "begin" in str(rite_error.value) and "paint" in str(rite_error.value)


@pytest.mark.parametrize("focus", ["A/", "/x", "A/b/c"])
def test_a_malformed_focus_is_refused(focus: str) -> None:
    with pytest.raises(RenderError):
        split_focus(focus)


def test_the_default_focus_is_the_root_circle(paddle: JinFileV2) -> None:
    assert render(paddle) == render(paddle, focus="Game")


# ---------------------------------------------------------------- 手順の図（§3）


def test_place_block_puts_nested_blocks_inside_the_parent_arc() -> None:
    model = model_v2_from(
        [
            {
                "name": "A",
                "core": "go",
                "rites": [
                    {
                        "name": "go",
                        "steps": [
                            {"do": "set", "target": "x", "expr": "1"},
                            {
                                "do": "if",
                                "cond": "true",
                                "then": [{"do": "finish"}, {"do": "finish"}],
                                "else": [{"do": "return"}],
                            },
                        ],
                    }
                ],
                "state": [{"name": "x", "type": "num", "init": "0"}],
            }
        ],
        "A",
    )
    top = place_block(model.circles[0].rites[0].steps, "/r/steps", 0, geo.TOP_ANGLE - 90.0, 360.0)
    assert [round(p.angle, 3) for p in top] == [-90.0, 90.0]  # 12 時と 6 時
    assert all(p.width == 180.0 for p in top)
    branch = top[1]
    # then は親の弧 [0, 180] の前半 [0, 90] を 2 等分、else は後半 [90, 180]。
    assert [round(p.angle, 3) for p in branch.then] == [22.5, 67.5]
    assert [round(p.angle, 3) for p in branch.else_] == [135.0]
    assert [p.depth for p in branch.then] == [1, 1]
    assert [p.pointer for p in branch.then] == ["/r/steps/1/then/0", "/r/steps/1/then/1"]
    assert branch.else_[0].pointer == "/r/steps/1/else/0"


def test_the_rite_view_draws_depth_rings_steps_and_edges(paddle: JinFileV2) -> None:
    svg = render(paddle, focus="Play/step")
    assert _rings(svg, "/circles/1/rites/2") == [0.75, 0.95]  # 深さ 0 と 1
    elements = contract_elements(svg)
    steps = {e.get("data-jin") for e in elements if e.get("data-jin-kind") == "step"}
    assert "/circles/1/rites/2/steps/0" in steps
    assert "/circles/1/rites/2/steps/6/then/2" in steps  # then の中の cast
    edges = [e for e in elements if e.get("data-jin-kind") == "step-edge"]
    assert {e.get("data-jin") for e in edges} >= {
        "/circles/1/rites/2/steps/0",
        "/circles/1/rites/2/steps/6/then/2",
    }
    core = [e for e in elements if e.get("data-jin") == "/circles/1/rites/2/name"]
    assert [e.text for e in core if e.tag == f"{{{SVG_NS}}}text"] == ["step"]


def test_wait_cuts_the_ring_of_its_depth(paddle: JinFileV2) -> None:
    svg = render(paddle, focus="Result/show")  # steps: set, wait
    ring = [
        e
        for e in contract_elements(svg)
        if e.get("data-jin") == "/circles/2/rites/0" and e.tag == f"{{{SVG_NS}}}path"
    ]
    # `wait` は 2 番目（6 時）。欠けが 12 時起点の相対角の途中にあるので弧は 2 本になる。
    assert len(ring) == 2
    assert sum(e.get("d", "").count(" C ") for e in ring) >= 4


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("canvas.clear", CAST_HOST),
        ("serve", CAST_RITE),
        ("dbl", CAST_SUMMON),
        ("nope.x", None),
        ("nope", None),
    ],
)
def test_cast_classification_uses_only_the_name_tables(
    paddle: JinFileV2, target: str, expected: str | None
) -> None:
    circle = paddle.circles[1].model_copy(
        update={
            "sigils": list(paddle.circles[1].sigils)
            + [{"name": "dbl", "kind": "summon", "circle": "Result", "rite": "show"}]
        }
    )
    circle = type(circle).model_validate(circle.model_dump(by_alias=True))
    assert classify_cast(circle, target) == expected


def test_every_step_kind_has_a_glyph() -> None:
    """11 種のステップがそれぞれ `step` 要素を 1 つ以上持つ。"""
    steps = [
        {"do": "set", "target": "x", "expr": "1"},
        {"do": "let", "name": "y", "expr": "1"},
        {"do": "cast", "target": "canvas.clear", "args": ['"#000"']},
        {"do": "if", "cond": "true", "then": [{"do": "break"}]},
        {"do": "loop", "kind": "each", "name": "i", "in": "[]", "steps": [{"do": "break"}] * 5},
        {"do": "loop", "kind": "count", "times": "3", "steps": [{"do": "return"}]},
        {"do": "wait", "ticks": "1"},
        {"do": "emit", "circle": "A", "message": "m"},
        {"do": "return"},
        {"do": "finish"},
        {"do": "transfer", "circle": "A"},
    ]
    model = model_v2_from(
        [
            {
                "name": "A",
                "core": "go",
                "rites": [{"name": "go", "steps": steps}],
                "state": [{"name": "x", "type": "num", "init": "0"}],
                "sigils": [{"name": "canvas", "kind": "host", "host": "canvas"}],
                "delegate": ["A"],
            }
        ],
        "A",
    )
    svg = render(model, focus="A/go")
    drawn = {e.get("data-jin") for e in contract_elements(svg) if e.get("data-jin-kind") == "step"}
    for index in range(len(steps)):
        assert f"/circles/0/rites/0/steps/{index}" in drawn, index
    assert "/circles/0/rites/0/steps/4/steps/4" in drawn  # loop の中（深さ 1）


def test_nesting_beyond_depth_three_is_clamped_to_the_innermost_ring() -> None:
    model = load_model_v2(ERROR_FIXTURES_V2 / "JIN211_nesting_too_deep.jin")
    circle = model.circles[0]
    svg = render(model, focus=f"{circle.name}/{circle.rites[0].name}")
    rings = _rings(svg, "/circles/0/rites/0")
    assert rings == [0.35, 0.55, 0.75, 0.95]


# ---------------------------------------------------------------- 名前は SVG に出ない（頭文字と核の手順名だけ）


def test_only_initials_and_the_core_rite_name_reach_the_svg() -> None:
    model = model_v2_from(
        [
            {
                "name": "Alpha_secret",
                "core": "Verylongritename",
                "rites": [{"name": "Verylongritename", "steps": []}],
                "state": [{"name": "hidden_state", "type": "num", "init": "0"}],
                "sigils": [{"name": "sig", "kind": "host", "host": "canvas"}],
            }
        ],
        "Alpha_secret",
    )
    svg = render(model)
    assert (
        "Alpha_secret" not in svg
        and "hidden_state" not in svg
        and "sig" not in svg.replace("sigil", "")
    )
    texts = [e.text for e in contract_elements(svg) if e.tag == f"{{{SVG_NS}}}text"]
    assert "Verylon…" in texts  # 8 文字に切り詰め
    assert "C" in texts and "V" in texts


def test_accent_is_absent_without_a_trace(paddle: JinFileV2) -> None:
    assert ACCENT not in render(paddle, focus="Play")
