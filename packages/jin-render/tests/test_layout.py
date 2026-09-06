"""`jin_render.render` の `data-jin` 契約とレイアウト規則（docs/spec/layout.md §2 / §3 / §5 / §6）。

design.yaml `implementation_phases.items[3].verification.machine` の 3 / 4 / 6 をここで固定する。
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from jin_core.check import check_file
from jin_core.model import JinFile
from jin_core.pointer import pointer_exists
from jin_render import DATA_JIN_KINDS, RenderError, render
from jin_render import geometry as geo
from jin_render.layout import RUNE_ELLIPSIS, RUNE_MAX_CHARS, fit_rune
from jin_render.svg import ACCENT

from .conftest import (
    ERROR_FIXTURES,
    SVG_NS,
    contract_elements,
    load_model,
    model_from,
    pointers,
)

#: 数値を書き出す幾何・体裁属性。`data-*` / `id` / `href` は対象外（座標ではない）。
NUMERIC_ATTRS = frozenset(
    {
        "cx",
        "cy",
        "r",
        "x",
        "y",
        "x1",
        "y1",
        "x2",
        "y2",
        "d",
        "width",
        "height",
        "viewBox",
        "font-size",
        "stroke-width",
        "stroke-dasharray",
    }
)
#: そのうち、現在の描画が**実際に書き出す**もの。`x` / `y` は将来 `<text>` を絶対座標で
#: 置くときの受け皿で、今は 1 つも出ない（出ない属性を並べても丸めは守れない）。
EMITTED_NUMERIC_ATTRS = NUMERIC_ATTRS - {"x", "y"}
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
THREE_DECIMALS = re.compile(r"^-?\d+\.\d{3}$")


def model_json(model: JinFile) -> dict:
    """pointer の解決に使う素の JSON（`resolve_pointer` は素の値を辿る）。"""
    return model.model_dump(mode="json", by_alias=True)


# --------------------------------------------------------------------------------------
# machine 3 / 4: 全要素が data-jin と data-jin-kind を持ち、pointer がモデルに解決できる
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["researcher", "pipeline"])
def test_every_element_carries_both_attributes(name: str, request: pytest.FixtureRequest) -> None:
    model = request.getfixturevalue(name)
    for focus in [circle.name for circle in model.circles]:
        svg = render(model, focus=focus)
        elements = contract_elements(svg)
        assert elements, focus
        for element in elements:
            assert element.get("data-jin") is not None, (focus, element.tag)
            assert element.get("data-jin-kind") is not None, (focus, element.tag)


@pytest.mark.parametrize("name", ["researcher", "pipeline"])
def test_every_kind_is_one_of_the_nine(name: str, request: pytest.FixtureRequest) -> None:
    """layout.md §3 の 9 種だけ。**10 種目を増やさない。**"""
    model = request.getfixturevalue(name)
    for focus in [circle.name for circle in model.circles]:
        for element in contract_elements(render(model, focus=focus)):
            assert element.get("data-jin-kind") in DATA_JIN_KINDS


@pytest.mark.parametrize("name", ["researcher", "pipeline"])
def test_every_pointer_resolves_in_the_model(name: str, request: pytest.FixtureRequest) -> None:
    model = request.getfixturevalue(name)
    document = model_json(model)
    for focus in [circle.name for circle in model.circles]:
        for pointer in pointers(render(model, focus=focus)):
            assert pointer is not None, (focus, "data-jin が無い要素がある")
            assert pointer_exists(document, pointer), (focus, pointer)


@pytest.mark.parametrize("name", ["researcher", "pipeline"])
def test_every_referent_resolves_in_the_model(name: str, request: pytest.FixtureRequest) -> None:
    """`data-jin-ref`（参照先 circle）もモデルに解決できること。"""
    model = request.getfixturevalue(name)
    document = model_json(model)
    for element in contract_elements(render(model)):
        ref = element.get("data-jin-ref")
        if ref is not None:
            assert pointer_exists(document, ref), ref


def test_the_nine_kinds_are_all_drawn(researcher: JinFile, pipeline: JinFile) -> None:
    """検査が空虚にならない側: 9 種すべてが実際に描かれていること。

    `delegate` は examples 2 本のどちらにも無い（researcher は `summon`、pipeline は `flow`）ので、
    合成モデルを 1 本足す。
    """
    delegating = model_from(
        [{"name": "A", "core": "m", "delegate": ["B"]}, {"name": "B", "core": "m"}], "A"
    )
    seen: set[str] = set()
    for model in (researcher, pipeline, delegating):
        for circle in model.circles:
            for element in contract_elements(render(model, focus=circle.name)):
                seen.add(element.get("data-jin-kind", ""))
    assert seen == set(DATA_JIN_KINDS), sorted(set(DATA_JIN_KINDS) - seen)


def test_the_same_pointer_may_appear_more_than_once(pipeline: JinFile) -> None:
    """`data-jin` は ID ではなく鍵（layout.md §3）。環と核と紋が同じ circle を指す。"""
    found = pointers(render(pipeline))
    assert len(found) > len(set(found))


# --------------------------------------------------------------------------------------
# 数値の書き出しは丸め関数 1 本だけを通る（layout.md §4）
# --------------------------------------------------------------------------------------
def dashed_model() -> JinFile:
    """破線を使う 2 種（解決しない summon の点線・delegate の点線）を含むモデル。

    examples 2 本には `stroke-dasharray` が出ないので、`DASH` の桁が崩れても
    `test_all_geometry_numbers_are_written_with_three_decimals` が緑のままだった
    （F-V-P3-001）。属性の**取りこぼし**を防ぐため、下の検査はこのモデルも回す。
    """
    circles = [
        {
            "name": "A",
            "core": "m",
            "instruction": {"rune": "破線と文字"},
            "delegate": ["B"],
            "tools": [{"name": "s", "kind": "summon", "circle": "Missing"}],
            "boundary": {"await": ["nothere"]},
        },
        {"name": "B", "core": "m"},
    ]
    return model_from(circles, "A")


@pytest.mark.parametrize("name", ["researcher", "pipeline", "dashed"])
def test_all_geometry_numbers_are_written_with_three_decimals(
    name: str, request: pytest.FixtureRequest
) -> None:
    """素の float 文字列化が混ざると桁が不揃いになるので、正規表現で落とす。"""
    model = dashed_model() if name == "dashed" else request.getfixturevalue(name)
    svg = render(model)
    root = ET.fromstring(svg)
    checked = 0
    seen: set[str] = set()
    for element in root.iter():
        for attribute, value in element.attrib.items():
            if attribute not in NUMERIC_ATTRS:
                continue
            seen.add(attribute)
            for number in NUMBER.findall(value):
                assert THREE_DECIMALS.match(number), (attribute, value, number)
                checked += 1
    assert checked > 20, checked


def test_every_numeric_attribute_is_covered_by_at_least_one_model(
    researcher: JinFile, pipeline: JinFile
) -> None:
    """`NUMERIC_ATTRS` の各属性が、検査に使うモデルのどれかに**実際に現れる**こと。

    出てこない属性を並べても丸めは守れない（F-V-P3-001: `stroke-dasharray` がそれだった）。
    """
    seen: set[str] = set()
    for model in (researcher, pipeline, dashed_model()):
        root = ET.fromstring(render(model))
        for element in root.iter():
            seen.update(element.attrib)
    assert EMITTED_NUMERIC_ATTRS <= seen, sorted(EMITTED_NUMERIC_ATTRS - seen)
    # 受け皿として置いてあるだけの属性は、実際に出ていないことも固定する
    assert not (NUMERIC_ATTRS - EMITTED_NUMERIC_ATTRS) & seen


def test_the_svg_uses_no_elliptical_arc_command(researcher: JinFile) -> None:
    """`A` の large-arc / sweep フラグは 1 文字の 0 / 1 でなければならず 3 桁固定と両立しない。

    検査は `d` 属性の値だけを対象にする。SVG 全文だと rune の英文（`A tool` など）に
    誤反応する（F-V-P3-021）。
    """
    for model in (
        researcher,
        model_from([{"name": "A", "core": "m", "instruction": {"rune": "A tool L 1"}}], "A"),
    ):
        for element in ET.fromstring(render(model)).iter():
            d = element.get("d")
            if d is not None:
                assert not re.search(r"\bA\b", d), d


def test_no_style_element_is_emitted(researcher: JinFile) -> None:
    """要件書 §2.5「`<style>` 不使用、属性で完結」。"""
    assert "<style" not in render(researcher)
    assert " style=" not in render(researcher)


# --------------------------------------------------------------------------------------
# machine 6: focus を切り替えると展開対象の circle が変わる
# --------------------------------------------------------------------------------------
def test_focus_changes_the_expanded_circle(pipeline: JinFile) -> None:
    root_svg = render(pipeline)
    drafter_svg = render(pipeline, focus="Drafter")
    assert root_svg != drafter_svg
    assert pointers(root_svg)[0] == "/circles/0"
    assert pointers(drafter_svg)[0] == "/circles/2"


def test_the_default_focus_is_the_root_circle(pipeline: JinFile) -> None:
    assert render(pipeline) == render(pipeline, focus="Pipeline")


def test_focus_expands_only_depth_one(pipeline: JinFile) -> None:
    """深さ 1 まで展開し、それ以下は点（layout.md §2）。

    Pipeline → Refine（深さ 1・展開）→ Critic / Rewriter（深さ 2・点）。
    """
    svg = render(pipeline)
    found = set(pointers(svg))
    assert "/circles/1/flow" in found, "Refine（深さ 1）の弦が描かれていない"
    assert "/circles/1/flow/steps/0" in found, "Critic（深さ 2）の点が無い"
    assert "/circles/4/core" not in found, "深さ 2 の circle の中まで展開している"


def test_an_unknown_focus_names_the_candidates(pipeline: JinFile) -> None:
    with pytest.raises(RenderError) as excinfo:
        render(pipeline, focus="Draftr")
    message = str(excinfo.value)
    assert "Draftr" in message
    assert "Drafter" in message
    assert "Pipeline" in message


# --------------------------------------------------------------------------------------
# 配置規則（layout.md §2 / §2.1）
# --------------------------------------------------------------------------------------
def test_rings_are_drawn_only_when_they_exist(researcher: JinFile) -> None:
    """存在しない環は描かず、**半径も詰めない**（layout.md §1）。"""
    bare = model_from([{"name": "Bare", "core": "m"}], "Bare")
    radii = _ring_radii(render(bare))
    assert radii == [], radii

    full = _ring_radii(render(researcher))
    scale = geo.UNIT_PX
    for radius in (geo.RING_INSTRUCTION, geo.RING_TOOLS, geo.RING_STATE):
        assert any(value == pytest.approx(radius * scale) for value in full), (radius, full)


def _ring_radii(svg: str) -> list[float]:
    """焦点の circle の環（`<circle data-jin="/circles/N" data-jin-kind="circle">`）の半径。"""
    out: list[float] = []
    for element in contract_elements(svg):
        if element.tag != f"{{{SVG_NS}}}circle" or element.get("data-jin-kind") != "circle":
            continue
        if element.get("data-jin") != "/circles/0":
            continue
        out.append(float(element.get("r", "0")))
    return out


def test_a_flow_circle_draws_no_ring(pipeline: JinFile) -> None:
    """核なし circle（flow だけ）は環を 1 本も持たない。"""
    assert _ring_radii(render(pipeline)) == []


def test_a_circle_without_a_core_draws_no_core_element(pipeline: JinFile) -> None:
    """Pipeline は flow だけの circle。入れ子の Drafter などは核を持つので、焦点の circle で見る。"""
    assert _by_pointer(render(pipeline), "/circles/0/core") == []
    assert _by_pointer(render(pipeline, focus="Drafter"), "/circles/2/core") != []


def test_tool_glyphs_sit_on_the_tools_ring(researcher: JinFile) -> None:
    svg = render(researcher)
    frame = geo.root_frame()
    for element in _by_pointer(svg, "/circles/0/tools/0"):
        if element.tag != f"{{{SVG_NS}}}circle":
            continue
        distance = math.hypot(
            float(element.get("cx", "0")) - frame.cx, float(element.get("cy", "0")) - frame.cy
        )
        assert distance == pytest.approx(geo.RING_TOOLS * frame.scale, abs=0.01)


def _by_pointer(svg: str, pointer: str) -> list:
    return [e for e in contract_elements(svg) if e.get("data-jin") == pointer]


def _loop_svg(n: int) -> str:
    steps = [f"S{i}" for i in range(n)]
    circles = [{"name": "L", "flow": {"kind": "loop", "steps": steps, "max": 2}}]
    circles += [{"name": name, "core": "m"} for name in steps]
    return render(model_from(circles, "L"))


def _slot_centers(n: int) -> list[tuple[float, float]]:
    frame = geo.root_frame()
    return [geo.point(frame, geo.FLOW_RING, geo.angle_at(slot, n)) for slot in range(n)]


@pytest.mark.parametrize(("n", "step"), [(5, 2), (6, 1), (8, 3)])
def test_loop_edges_follow_the_star_polygon(n: int, step: int) -> None:
    """{n/k} の辺が**角位置**として `s → (s+k) mod n` を結ぶこと（星形そのもの）。

    `k = n//2` の変異は n=6 / n=8 で割れる。どの節がどの角位置に載るかは
    `test_loop_nodes_are_placed_so_the_arrows_follow_the_visit_order` が見る。
    """
    slots = _slot_centers(n)
    drawn = _edge_endpoints(_loop_svg(n), "/circles/0/flow")
    expected = {(s, (s + step) % n) for s in range(n)}
    actual = {(_nearest(slots, start), _nearest(slots, end)) for start, end in drawn}
    assert actual == expected, (actual, expected)


@pytest.mark.parametrize("n", [3, 4, 5, 6, 7, 8, 9, 10, 11, 12])
def test_loop_nodes_are_placed_so_the_arrows_follow_the_visit_order(n: int) -> None:
    """要件書 §2.5「辺の順を訪問順に一致させる」（F-C-P3-002 / DP-IMPL-JIN-P3-LOOP-STAR-ORDER-01）。

    矢じりの向きは実行順でなければならない。節 j を角位置 `(j*k) mod n` に置くことで
    「星形」と「矢じりが実行順」を同時に満たす。ここでは**節の名前**の側から見る:
    どの矢印も、`flow.steps` で隣り合う 2 つ（j → j+1 mod n）を結ぶ。
    """
    svg = _loop_svg(n)
    slots = _slot_centers(n)
    # 角位置 → 節の添字（節の紋の中心がどの角位置にあるか）
    slot_of_step: dict[int, int] = {}
    for j in range(n):
        found = _by_pointer(svg, f"/circles/0/flow/steps/{j}")
        assert found, j
        center = _center_of(found)
        slot_of_step[j] = _nearest(slots, center)
    assert sorted(slot_of_step.values()) == list(range(n)), "角位置への写像が全単射でない"

    step_of_slot = {slot: j for j, slot in slot_of_step.items()}
    drawn = _edge_endpoints(svg, "/circles/0/flow")
    actual = {
        (step_of_slot[_nearest(slots, start)], step_of_slot[_nearest(slots, end)])
        for start, end in drawn
    }
    assert actual == {(j, (j + 1) % n) for j in range(n)}, actual


@pytest.mark.parametrize("n", [2, 3, 4])
def test_a_small_loop_keeps_the_array_order_placement(n: int) -> None:
    """`n < 5` は k=1（星形にならない）。配置は配列順のまま。"""
    svg = _loop_svg(n)
    slots = _slot_centers(n)
    for j in range(n):
        center = _center_of(_by_pointer(svg, f"/circles/0/flow/steps/{j}"))
        assert _nearest(slots, center) == j


def _center_of(elements: list) -> tuple[float, float]:
    """参照の紋（外枠の `<circle>`）の中心。"""
    for element in elements:
        if element.get("cx") is not None:
            return (float(element.get("cx")), float(element.get("cy")))
    raise AssertionError("中心を持つ要素が無い")


def _edge_endpoints(
    svg: str, pointer: str
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    out = []
    for element in _by_pointer(svg, pointer):
        d = element.get("d", "")
        numbers = [float(value) for value in NUMBER.findall(d)]
        # 先頭の `M x y L x y` が線分の本体（続きは矢じり）
        out.append(((numbers[0], numbers[1]), (numbers[2], numbers[3])))
    return out


def _nearest(nodes: list[tuple[float, float]], point: tuple[float, float]) -> int:
    return min(
        range(len(nodes)), key=lambda i: math.hypot(nodes[i][0] - point[0], nodes[i][1] - point[1])
    )


def test_parallel_draws_no_chord() -> None:
    """要件書 §2.5: `parallel` = 弦なし対称配置。"""
    circles = [
        {"name": "P", "flow": {"kind": "parallel", "steps": ["A", "B"]}},
        {"name": "A", "core": "m"},
        {"name": "B", "core": "m"},
    ]
    svg = render(model_from(circles, "P"))
    assert _by_pointer(svg, "/circles/0/flow") == []
    # 参照 1 つにつき wrapper `<g>` と見える外枠の `<circle>` の 2 要素（B-1）
    assert len(_by_pointer(svg, "/circles/0/flow/steps/0")) == 2


def test_await_cuts_the_boundary_ring(researcher: JinFile) -> None:
    """`await` の紋の角度に境界環の欠けを作る（要件書 §2.5）。"""
    svg = render(researcher)
    arcs = [
        element for element in _by_pointer(svg, "/circles/0") if element.tag == f"{{{SVG_NS}}}path"
    ]
    assert len(arcs) == 2, "欠けのある境界環が 2 本の弧になっていない"
    awaits = _by_pointer(svg, "/circles/0/boundary/await/0")
    assert len(awaits) == 1
    assert awaits[0].get("data-jin-kind") == "await"


def test_an_unresolved_await_is_drawn_dashed_at_twelve_o_clock() -> None:
    """JIN070（`await` 対象が `tools` に無い）。欠けを作れないので破線の印にする。"""
    circles = [
        {
            "name": "A",
            "core": "m",
            "tools": [{"name": "t", "kind": "builtin", "builtin": "google_search"}],
            "boundary": {"await": ["missing"]},
        }
    ]
    svg = render(model_from(circles, "A"))
    marks = _by_pointer(svg, "/circles/0/boundary/await/0")
    assert len(marks) == 1
    assert marks[0].get("stroke-dasharray") is not None
    rings = [e for e in _by_pointer(svg, "/circles/0") if e.tag == f"{{{SVG_NS}}}path"]
    assert rings == [], "解決できない await が境界環を切ってしまっている"


def test_out_states_are_drawn_thicker(researcher: JinFile) -> None:
    """`out: true` だけが ADK の output_key になる（要件書 §3.3）。"""
    svg = render(researcher)
    plain = _by_pointer(svg, "/circles/0/state/0")[0]
    out_state = _by_pointer(svg, "/circles/0/state/1")[0]
    assert plain.get("stroke-width") is None
    assert out_state.get("stroke-width") is not None


def test_the_exit_mark_sits_at_the_centre() -> None:
    """星形には閉じ目の辺が一意に定まらないので中心に置く（layout.md §6）。"""
    circles = [
        {
            "name": "L",
            "flow": {
                "kind": "loop",
                "steps": ["A"],
                "exit": {"key": "k", "equals": True},
            },
        },
        {"name": "A", "core": "m", "state": [{"name": "k", "type": "bool", "out": True}]},
    ]
    svg = render(model_from(circles, "L"))
    marks = _by_pointer(svg, "/circles/0/flow/exit")
    assert len(marks) == 1
    numbers = [float(value) for value in NUMBER.findall(marks[0].get("d", ""))]
    frame = geo.root_frame()
    assert numbers[0] == pytest.approx(frame.cx)
    assert numbers[1] == pytest.approx(frame.cy - geo.EXIT_MARK * frame.scale)


def test_no_exit_mark_without_an_exit(pipeline: JinFile) -> None:
    svg = render(pipeline, focus="Refine")
    assert len(_by_pointer(svg, "/circles/1/flow/exit")) == 1
    plain = model_from(
        [
            {"name": "L", "flow": {"kind": "loop", "steps": ["A"], "max": 2}},
            {"name": "A", "core": "m"},
        ],
        "L",
    )
    assert _by_pointer(render(plain), "/circles/0/flow/exit") == []


# --------------------------------------------------------------------------------------
# rune と textPath（layout.md §6）
# --------------------------------------------------------------------------------------
def test_text_path_ids_are_unique_even_when_a_circle_is_drawn_twice() -> None:
    """同じ circle を 2 回 summon しても `<path id>` が重複しないこと。"""
    circles = [
        {
            "name": "A",
            "core": "m",
            "tools": [
                {"name": "x", "kind": "summon", "circle": "B"},
                {"name": "y", "kind": "summon", "circle": "B"},
            ],
        },
        {"name": "B", "core": "m", "instruction": {"rune": "b"}},
    ]
    svg = render(model_from(circles, "A"))
    ids = re.findall(r'<path id="([^"]+)"', svg)
    assert len(ids) == 2
    assert len(set(ids)) == 2
    for value in ids:
        assert re.match(r"^[A-Za-z_][A-Za-z0-9_.\-]*$", value), value


def test_the_rune_is_truncated_deterministically() -> None:
    long = "あ" * 200
    fitted = fit_rune(long)
    assert len(fitted) == RUNE_MAX_CHARS
    assert fitted.endswith(RUNE_ELLIPSIS)
    assert fit_rune(long) == fitted


def test_newlines_in_the_rune_become_single_spaces() -> None:
    assert fit_rune("a\n\nb\tc") == "a b c"


def test_a_hostile_rune_cannot_break_out_of_the_svg() -> None:
    """Phase 5 のエディタは SVG を DOM に埋め込む。タグとして解釈させない。"""
    hostile = "</svg><script>alert(1)</script>"
    circles = [{"name": "A", "core": "m", "instruction": {"rune": hostile}}]
    svg = render(model_from(circles, "A"))
    assert "<script" not in svg
    assert "</svg>" == svg.splitlines()[-1]
    assert "&lt;/svg&gt;&lt;script&gt;" in svg


def test_names_are_not_emitted_into_the_svg() -> None:
    """circle 名 / tool 名 / state 名は SVG に**現れない**（F-V-P3-002）。

    以前は「敵対的な circle 名が属性から抜け出さない」という名前だったが、名前は
    そもそも出力に載らないので、属性エスケープを素通しにしても緑のままだった。
    属性エスケープを守るのは `test_svg.py` の単体テストであり、ここが固定するのは
    「`.jin` の識別子は描画に出ない」という別の性質である。
    """
    circles = [
        {
            "name": "ZZNAME",
            "core": "m",
            "tools": [{"name": "ZZTOOL", "kind": "builtin", "builtin": "google_search"}],
            "state": [{"name": "ZZSTATE", "type": "str"}],
        }
    ]
    svg = render(model_from(circles, "ZZNAME"))
    for token in ("ZZNAME", "ZZTOOL", "ZZSTATE"):
        assert token not in svg, token


# --------------------------------------------------------------------------------------
# 壊れたモデルでも落ちない（layout.md §5 / NFR-AVAIL-001）
# --------------------------------------------------------------------------------------
MODELABLE_ERROR_FIXTURES = sorted(
    path for path in ERROR_FIXTURES.glob("*.jin") if check_file(path).model is not None
)


def test_there_are_modelable_error_fixtures() -> None:
    """走査が壊れて 0 件になったら下の parametrize が空虚になる。"""
    assert len(MODELABLE_ERROR_FIXTURES) >= 10


@pytest.mark.parametrize("path", MODELABLE_ERROR_FIXTURES, ids=lambda p: p.name)
def test_render_never_raises_on_a_model_with_semantic_errors(path: Path) -> None:
    """schema を通るモデルなら意味エラーがあっても例外を投げない（Phase 4 のエラー回復）。"""
    model = load_model(path)
    svg = render(model)
    for element in contract_elements(svg):
        assert element.get("data-jin") is not None
        assert element.get("data-jin-kind") in DATA_JIN_KINDS


def test_a_circular_summon_does_not_expand_forever() -> None:
    """JIN012。展開が深さ 1 で止まることを構造で固定する。"""
    circles = [
        {"name": "A", "core": "m", "tools": [{"name": "b", "kind": "summon", "circle": "B"}]},
        {"name": "B", "core": "m", "tools": [{"name": "a", "kind": "summon", "circle": "A"}]},
    ]
    svg = render(model_from(circles, "A"))
    groups = [
        element for element in _by_pointer(svg, "/circles/0") if element.tag == f"{{{SVG_NS}}}g"
    ]
    assert len(groups) == 1, "自分自身の陣が 2 回展開されている"
    assert "/circles/1/tools/0" in pointers(svg)


def test_a_self_summon_terminates() -> None:
    circles = [
        {"name": "A", "core": "m", "tools": [{"name": "a", "kind": "summon", "circle": "A"}]}
    ]
    svg = render(model_from(circles, "A"))
    assert pointers(svg).count("/circles/0/tools/0") >= 2


def test_an_unresolved_reference_is_drawn_dashed_with_the_referring_pointer() -> None:
    """JIN011。`data-jin` は参照側の pointer（layout.md §5）。"""
    circles = [
        {
            "name": "A",
            "core": "m",
            "tools": [{"name": "x", "kind": "summon", "circle": "Nope"}],
            "delegate": ["AlsoNope"],
        }
    ]
    svg = render(model_from(circles, "A"))
    tool = _by_pointer(svg, "/circles/0/tools/0")
    glyph = [element for element in tool if element.tag == f"{{{SVG_NS}}}circle"]
    assert len(glyph) == 1
    assert glyph[0].get("stroke-dasharray") is not None
    assert glyph[0].get("data-jin-ref") is None
    delegate = [
        element
        for element in _by_pointer(svg, "/circles/0/delegate/0")
        if element.tag == f"{{{SVG_NS}}}circle"
    ]
    assert delegate[0].get("data-jin-ref") is None


def test_an_unresolved_root_falls_back_to_the_first_circle_with_a_mark() -> None:
    """JIN060。落ちずに `circles[0]` を描き、破線 + `data-jin-root="unresolved"` を付ける。"""
    model = load_model(ERROR_FIXTURES / "JIN060_root_not_found.jin")
    svg = render(model)
    root = contract_elements(svg)[0]
    assert root.get("data-jin") == "/circles/0"
    assert root.get("data-jin-root") == "unresolved"
    assert root.get("stroke-dasharray") is not None


def test_an_explicit_focus_is_not_marked_unresolved() -> None:
    model = load_model(ERROR_FIXTURES / "JIN060_root_not_found.jin")
    svg = render(model, focus=model.circles[0].name)
    assert contract_elements(svg)[0].get("data-jin-root") is None


def test_an_empty_circles_list_renders_an_empty_canvas() -> None:
    """`JinFile.circles` は空リストを許す（`model.py` に min_length が無い）。"""
    empty = model_from([], "Nothing")
    svg = render(empty)
    assert contract_elements(svg) == []
    assert svg.startswith("<svg ")
    assert svg.endswith("</svg>\n")


def test_duplicate_circle_names_pick_the_first_declaration() -> None:
    """JIN010。落ちない・順序に依らない。"""
    circles = [
        {"name": "A", "core": "first", "tools": [{"name": "s", "kind": "summon", "circle": "A"}]},
        {"name": "A", "core": "second"},
    ]
    svg = render(model_from(circles, "A"))
    assert pointers(svg)[0] == "/circles/0"
    refs = {
        element.get("data-jin-ref")
        for element in contract_elements(svg)
        if element.get("data-jin-ref")
    }
    assert refs == {"/circles/0"}


# --------------------------------------------------------------------------------------
# 参照の紋は**見える**（F-C-P3-003）／入れ子の実寸で止まる（F-C-P3-005）
# --------------------------------------------------------------------------------------
def _summon_model(inner: dict) -> JinFile:
    circles = [
        {"name": "A", "core": "m", "tools": [{"name": "s", "kind": "summon", "circle": "B"}]},
        inner,
    ]
    return model_from(circles, "A")


def test_a_summon_draws_a_visible_outline_that_the_tool_row_highlights() -> None:
    """wrapper `<g>` の朱は入れ子 `<g>` の `stroke` に断たれるので、参照側 pointer を持つ
    **描画要素**（外枠の円）を wrapper 直下に置く。tool 行 1 本でそれが赤くなること。"""
    model = _summon_model({"name": "B", "core": "m", "instruction": {"rune": "b"}})
    svg = render(model, trace=[{"seq": 1, "pointer": "/circles/0/tools/0"}])
    outlines = [
        element
        for element in contract_elements(svg)
        if element.tag == f"{{{SVG_NS}}}circle"
        and element.get("data-jin") == "/circles/0/tools/0"
        and element.get("data-jin-ref") == "/circles/1"
    ]
    assert len(outlines) == 1, "参照の紋に当たる描画要素が無い"
    assert outlines[0].get("data-jin-fired") == "1"
    assert outlines[0].get("stroke") == ACCENT


@pytest.mark.parametrize(
    ("inner", "reach"),
    [
        ({"name": "B", "core": "m"}, geo.CORE_RADIUS),
        (
            {"name": "B", "core": "m", "instruction": {"rune": "b"}},
            geo.RING_INSTRUCTION + geo.RUNE_FONT,
        ),
        (
            {"name": "B", "core": "m", "state": [{"name": "k", "type": "str"}]},
            geo.RING_STATE + geo.STATE_HALF,
        ),
        (
            {
                "name": "B",
                "core": "m",
                "boundary": {"guards": [{"on": "before_tool", "ref": "g"}]},
            },
            geo.RING_BOUNDARY + geo.GUARD_TICK_HALF,
        ),
    ],
)
def test_the_summon_outline_follows_the_inner_circles_actual_reach(
    inner: dict, reach: float
) -> None:
    """外枠は `RING_BOUNDARY` 固定ではなく、入れ子が**実際に**届く半径で決まる（F-C-P3-005）。"""
    svg = render(_summon_model(inner))
    outline = _center_of_circle(svg, "/circles/0/tools/0")
    expected = (geo.NESTED_SCALE * reach + geo.SUMMON_GAP) * geo.root_frame().scale
    assert outline == pytest.approx(expected, abs=0.001)


def _center_of_circle(svg: str, pointer: str) -> float:
    for element in _by_pointer(svg, pointer):
        if element.tag == f"{{{SVG_NS}}}circle":
            return float(element.get("r"))
    raise AssertionError(pointer)


def test_the_radial_line_stops_at_the_summon_outline() -> None:
    """放射線は外枠に接して止まる（内側でも外側でもない）。"""
    svg = render(_summon_model({"name": "B", "core": "m"}))
    frame = geo.root_frame()
    line = next(
        element
        for element in _by_pointer(svg, "/circles/0/tools/0")
        if element.tag == f"{{{SVG_NS}}}line"
    )
    end = (float(line.get("x2")), float(line.get("y2")))
    center = geo.point(frame, geo.RING_TOOLS, geo.angle_at(0, 1))
    gap = math.hypot(end[0] - center[0], end[1] - center[1])
    outline = _center_of_circle(svg, "/circles/0/tools/0")
    assert gap == pytest.approx(outline, abs=0.001)


def test_a_flow_circle_with_state_and_delegate_still_draws_them() -> None:
    """核なしでも `state` / `boundary` があれば環は描く（layout.md §1・§5）。

    `jin check` を通らないモデルでも描く（NFR-AVAIL-001）。核が無いときの破線は
    中心点から出る。この分岐はスナップショットにも 1 件も無かった（F-C-P3-012）。
    """
    circles = [
        {
            "name": "F",
            "flow": {"kind": "sequence", "steps": ["A"]},
            "state": [{"name": "k", "type": "str"}],
            "delegate": ["A"],
            "boundary": {"guards": [{"on": "before_agent", "ref": "g"}]},
        },
        {"name": "A", "core": "m"},
    ]
    svg = render(model_from(circles, "F"))
    radii = _ring_radii(svg)
    scale = geo.UNIT_PX
    assert any(v == pytest.approx(geo.RING_STATE * scale) for v in radii), radii
    assert any(v == pytest.approx(geo.RING_BOUNDARY * scale) for v in radii), radii

    line = next(
        element
        for element in contract_elements(svg)
        if element.get("data-jin") == "/circles/0/delegate/0" and element.tag == f"{{{SVG_NS}}}line"
    )
    frame = geo.root_frame()
    assert (float(line.get("x1")), float(line.get("y1"))) == pytest.approx((frame.cx, frame.cy))


# --------------------------------------------------------------------------------------
# flow の弦は節が何個あっても消えない（F-C-P3-101）
# --------------------------------------------------------------------------------------
#: 節の中身 3 種。`_outer_extent` が返す半径が小さい順（core だけ / examples 同型 / 最大）。
NODE_BODIES = {
    "core-only": {"core": "m"},
    "examples-like": {
        "core": "m",
        "instruction": {"rune": "r"},
        "state": [{"name": "k", "type": "str"}],
    },
    "largest": {
        "core": "m",
        "instruction": {"rune": "r"},
        "state": [{"name": "k", "type": "str"}],
        "boundary": {"guards": [{"on": "before_agent", "ref": "g"}]},
    },
}


def _flow_model(kind: str, n: int, body: dict) -> JinFile:
    steps = [f"S{i}" for i in range(n)]
    flow: dict = {"kind": kind, "steps": steps}
    if kind == "loop":
        flow["max"] = 2
    circles: list[dict] = [{"name": "F", "flow": flow}]
    circles += [{"name": name, **body} for name in steps]
    return model_from(circles, "F")


def _chord_bodies(svg: str) -> list[float]:
    """各弦の**本体**（矢じりを除いた `M x y L x y`）の長さ。"""
    out = []
    for start, end in _edge_endpoints(svg, "/circles/0/flow"):
        out.append(math.hypot(end[0] - start[0], end[1] - start[1]))
    return out


@pytest.mark.parametrize("body_name", sorted(NODE_BODIES))
@pytest.mark.parametrize("n", list(range(3, 13)))
@pytest.mark.parametrize("kind", ["sequence", "loop"])
def test_every_flow_chord_is_drawn_whatever_the_node_count(
    kind: str, n: int, body_name: str
) -> None:
    """訪問順を示す弦が**モデルの大きさで黙って消えない**こと。

    修正前は節の外枠が固定縮尺 0.28 だったので、隣接節の中心距離が外枠 2 つ分より
    短くなると `_arrow_d` が `None` を返し、`/circles/0/flow` を指す要素が 1 つも
    無くなっていた（examples 同型で n>=7、最大の中身で n>=6・F-C-P3-101）。
    要件書 §2.5 の「開いた弦列(矢印)」に例外は無い。
    """
    svg = render(_flow_model(kind, n, NODE_BODIES[body_name]))
    bodies = _chord_bodies(svg)
    expected = n - 1 if kind == "sequence" else n
    assert len(bodies) == expected, (kind, n, body_name, len(bodies))
    # layout.md §6 の文言どおり「本体長は `2 * (ARROW_HEAD + ε)` 以上」を見る。
    # 矢じりだけを下限にすると ε を消す変異が緑のままだった（F-V-P3-207）。
    floor = 2 * (geo.ARROW_HEAD + geo.FLOW_NODE_EPSILON) * geo.root_frame().scale
    assert min(bodies) >= floor - 0.001, (kind, n, body_name, min(bodies), floor)


@pytest.mark.parametrize("n", [3, 6, 7, 12])
def test_a_shrunk_flow_node_shrinks_its_contents_too(n: int) -> None:
    """外枠だけを詰めて中身がはみ出す形にしない（B-1）。

    入れ子の中で最も外側に届く要素（境界環）が、外枠の内側に収まっていること。
    """
    svg = render(_flow_model("sequence", n, NODE_BODIES["largest"]))
    outline = next(
        element
        for element in _by_pointer(svg, "/circles/0/flow/steps/0")
        if element.tag == f"{{{SVG_NS}}}circle"
    )
    radius = float(outline.get("r"))
    center = (float(outline.get("cx")), float(outline.get("cy")))
    inner = [
        element
        for element in contract_elements(svg)
        if element.get("data-jin") == "/circles/1" and element.tag == f"{{{SVG_NS}}}circle"
    ]
    assert inner, "入れ子の環が描かれていない"
    for element in inner:
        offset = math.hypot(
            float(element.get("cx")) - center[0], float(element.get("cy")) - center[1]
        )
        assert offset + float(element.get("r")) <= radius + 0.001, (n, element.get("r"), radius)


def test_a_small_flow_keeps_the_full_nested_scale() -> None:
    """節が少ないうちは縮尺 0.28（上限）のまま。examples のスナップショットが動かない根拠。"""
    svg = render(_flow_model("sequence", 3, NODE_BODIES["examples-like"]))
    outline = next(
        element
        for element in _by_pointer(svg, "/circles/0/flow/steps/0")
        if element.tag == f"{{{SVG_NS}}}circle"
    )
    natural = geo.NESTED_SCALE * (geo.RING_STATE + geo.STATE_HALF) + geo.SUMMON_GAP
    assert float(outline.get("r")) == pytest.approx(natural * geo.root_frame().scale, abs=0.001)


@pytest.mark.parametrize(("n", "nested"), [(19, True), (20, False), (40, False)])
def test_a_crowded_flow_falls_back_to_points(n: int, nested: bool) -> None:
    """兄弟間隔が点の半径すら下回るところまで詰まったら小陣をやめて点にする。

    `flow.steps` にモデル側の上限は無い（`jin_core.model.Flow`）ので、n はいくらでも
    大きくなりうる。**境界は n = 20**（`0.55 * sin(pi/20) - 0.06 = 0.0260 < 0.03`。
    n = 19 は 0.0305 でまだ小陣）。layout.md §6 の実測値をここで固定する。
    """
    crowded = render(_flow_model("sequence", n, NODE_BODIES["core-only"]))
    glyphs = _by_pointer(crowded, "/circles/0/flow/steps/0")
    is_nested = any(element.tag == f"{{{SVG_NS}}}g" for element in glyphs)
    assert is_nested is nested, (n, [e.tag for e in glyphs])
    if not nested:
        assert len(glyphs) == 1 and glyphs[0].tag == f"{{{SVG_NS}}}circle"


@pytest.mark.parametrize("n", [3, 5, 6, 8, 12])
@pytest.mark.parametrize("body_name", sorted(NODE_BODIES))
def test_the_chord_gap_matches_the_drawn_node(n: int, body_name: str) -> None:
    """弦が空ける隙間と、実際に描かれた節の外枠が**同じ半径**であること。

    半径を決める場所が 2 つあると、いつか片方だけ動いて「弦が紋を突き抜ける」
    または「弦が紋から離れて浮く」図になる。`_flow_extent` と `_flow_nodes` は
    どちらも `_reference_size` から採ることでこれを防ぐ。
    """
    svg = render(_flow_model("sequence", n, NODE_BODIES[body_name]))
    outline = next(
        element
        for element in _by_pointer(svg, "/circles/0/flow/steps/0")
        if element.tag == f"{{{SVG_NS}}}circle"
    )
    center = (float(outline.get("cx")), float(outline.get("cy")))
    radius = float(outline.get("r"))
    # 節 0 に接する弦（sequence なので 0 → 1 の 1 本）の始点との距離
    starts = [
        start
        for start, _end in _edge_endpoints(svg, "/circles/0/flow")
        if math.hypot(start[0] - center[0], start[1] - center[1]) < radius * 3
    ]
    assert starts, (n, body_name)
    gap = min(math.hypot(s[0] - center[0], s[1] - center[1]) for s in starts)
    assert gap == pytest.approx(radius, abs=0.01), (n, body_name, gap, radius)


@pytest.mark.parametrize("bad", ["\ufffe", "\uffff"])
def test_a_rune_with_a_noncharacter_still_parses_as_xml(bad: str) -> None:
    """描画側の出力契約: `jin check` を通る `.jin` なら必ず読める SVG になる。

    `render` を通す統合テストなので `test_svg.py`（`jin_render.svg` の単体）ではなく
    ここに置く（F-V-P3-108）。`xml_chars` そのものの単体は `test_svg.py`。

    `jin_core` は C0 / C1 / DEL / 孤立サロゲートを既に拒む（`_reject_bad_chars`）が、
    **非文字 U+FFFE / U+FFFF は通す**。これらは XML 1.0 の `Char` に無いので、
    そのまま書くと `xml.etree` が SVG 全体を拒む。`jin_core` の検証は変えずに
    （診断コードを増やさずに）描画側で U+FFFD に落とす（F-S-P3-005）。
    """
    circles = [{"name": "A", "core": "m", "instruction": {"rune": f"a{bad}b"}}]
    svg = render(model_from(circles, "A"))
    assert bad not in svg
    ET.fromstring(svg)  # 例外が出ないこと自体が主張


@pytest.mark.parametrize(
    ("n", "chords", "body_at_least_head"),
    [
        # 点に落ちたあとの 2 つの境界（layout.md §6・F-C-P3-205）
        (31, True, True),  # 本体 >= 矢じり
        (32, True, False),  # 弦は描かれるが本体が矢じりより短い
        (57, True, False),  # まだ描かれる
        (58, False, False),  # 弦そのものが消える
    ],
)
def test_the_two_crowding_boundaries(n: int, chords: bool, body_at_least_head: bool) -> None:
    """節が詰まったときの境界は 2 つある。R2 は片方だけを見て「n>=32 で消える」と書いた。

    - `2*FLOW_RING*sin(pi/n) - 2*POINT_RADIUS >= ARROW_HEAD` を割るのが **n = 32**
      （矢じりが本体より長くなる。弦は描かれる）
    - `2*FLOW_RING*sin(pi/n) <= 2*POINT_RADIUS` で `_arrow_d` が `None` を返すのが **n = 58**
      （弦そのものが消える）
    """
    svg = render(_flow_model("sequence", n, NODE_BODIES["core-only"]))
    bodies = _chord_bodies(svg)
    assert bool(bodies) is chords, (n, len(bodies))
    if chords:
        head = geo.ARROW_HEAD * geo.root_frame().scale
        assert (min(bodies) >= head) is body_at_least_head, (n, min(bodies), head)
