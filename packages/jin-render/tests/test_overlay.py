"""trace overlay（要件書 §4 / docs/spec/layout.md §7）。

design.yaml `implementation_phases.items[3].verification.machine` の 5（`upto` を増やすと
強調要素が単調増加する）をここで固定する。
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from jin_core.model import JinFile
from jin_core.pointer import pointer_exists
from jin_render import render
from jin_render.overlay import (
    BRIEF_MAX,
    SEQ_MAX,
    TraceRowError,
    brief,
    is_ancestor_or_same,
    read_trace,
)
from jin_render.svg import ACCENT

from .conftest import SVG_NS, contract_elements, fired_pointers, model_from, trace_rows


def row(seq: int, pointer: str | None) -> dict[str, Any]:
    return {"seq": seq, "ts": 0.0, "agent": "x", "kind": "model", "name": "n", "pointer": pointer}


# --------------------------------------------------------------------------------------
# 読み取り: 黙って捨てない（NFR-FAIL-001）
# --------------------------------------------------------------------------------------
def test_extra_keys_are_ignored() -> None:
    rows = read_trace([{"seq": 1, "pointer": None, "whatever": object()}])
    assert rows[0].seq == 1
    assert rows[0].pointer is None


def test_rows_are_sorted_by_seq() -> None:
    rows = read_trace([row(3, "/a"), row(1, "/b"), row(2, None)])
    assert [r.seq for r in rows] == [1, 2, 3]


@pytest.mark.parametrize(
    "bad",
    [
        {"pointer": "/a"},
        {"seq": "1", "pointer": "/a"},
        {"seq": 1.0, "pointer": "/a"},
        {"seq": True, "pointer": "/a"},
        {"seq": 1},
        {"seq": 1, "pointer": 3},
        {"seq": 1, "pointer": ["/a"]},
    ],
)
def test_a_malformed_row_is_refused(bad: dict[str, Any]) -> None:
    """型違いの行を読み飛ばすと「発火していない」と区別できなくなる。"""
    with pytest.raises(ValueError):
        read_trace([bad])


def test_a_non_mapping_row_is_refused() -> None:
    with pytest.raises(ValueError):
        read_trace([["seq", 1]])  # type: ignore[list-item]


@pytest.mark.parametrize(
    "seq", [0, -1, -(2**63), SEQ_MAX + 1, pytest.param(10**5000, id="10**5000")]
)
def test_a_seq_outside_the_range_is_refused(seq: int) -> None:
    """`jin_adk.trace` の `seq` は 1 始まりの連番（adk-mapping §6）。

    0 / 負数は「1 始まり」の契約を破る（F-C-P3-004 / F-S-P3-007 / F-V-P3-019）。
    5000 桁の整数は `json.loads` を通ってしまい、以降の比較・ソートで CPU を食う
    （F-S-P3-001）。どちらも上限・下限 1 本で閉じる。
    """
    with pytest.raises(ValueError):
        read_trace([row(seq, "/a")])


def test_the_seq_bounds_are_inclusive() -> None:
    assert [r.seq for r in read_trace([row(1, None), row(SEQ_MAX, None)])] == [1, SEQ_MAX]


@pytest.mark.parametrize(
    "value", [pytest.param(10**5000, id="10**5000"), pytest.param("x" * 100_000, id="long-str")]
)
def test_the_message_does_not_carry_a_huge_value(value: object) -> None:
    """F-S-P3-008: `!r` をそのまま載せると 1 行で端末とログが埋まる。

    4300 桁超の int は `repr` 自体が `ValueError` を投げる（Python の int_max_str_digits）。
    「読めない値の報告」でさらに落ちないことも同時に見る。
    """
    text = brief(value)
    assert len(text) <= BRIEF_MAX + 1


def test_a_huge_seq_is_refused_without_stringifying_it() -> None:
    with pytest.raises(TraceRowError) as caught:
        read_trace([row(10**5000, "/a")])
    assert len(str(caught.value)) < 200


def test_the_error_carries_the_position_in_the_sequence() -> None:
    """B-3 / F-V-P3-004: CLI が `path:N:` を出すには「何行目か」が要る。"""
    with pytest.raises(TraceRowError) as caught:
        read_trace([row(1, None), row(2, None), {"seq": 3}])
    assert caught.value.index == 2


@pytest.mark.parametrize(
    ("candidate", "pointer", "expected"),
    [
        ("/circles/2/core", "/circles/2/core", True),
        ("/circles/2", "/circles/2/core", True),
        ("/circles", "/circles/2/core", True),
        ("/circles/2/core", "/circles/2", False),
        # 「/ 区切り」でないと `/circles/1` が `/circles/10/core` の祖先になってしまう
        ("/circles/1", "/circles/10/core", False),
        ("/circles/1", "/circles/1x", False),
        ("", "/circles/2", False),
    ],
)
def test_ancestor_matching_is_segment_wise(candidate: str, pointer: str, expected: bool) -> None:
    assert is_ancestor_or_same(candidate, pointer) is expected


def test_a_huge_pointer_is_matched_in_linear_time(pipeline: JinFile) -> None:
    """F-S-P3-002: pointer の祖先を materialize していたので、深さ n で O(n^2) バイト使っていた。

    50 000 段（約 100 KB）の pointer は `jin run` のトレースには現れないが、`--trace` は
    **外部データ**なので手で書けば通る。走査を要素側に向けたので、深さに比例するのは
    「1 回の startswith」だけになる。
    """
    deep = "/circles/0" + "/x" * 50_000
    start = time.monotonic()
    svg = render(pipeline, trace=[row(1, deep)])
    # 指示書は「1 秒以内」。実測は 0.01 秒未満なので 1.0 で十分な余裕がある
    assert time.monotonic() - start < 1.0
    # `/circles/0` が祖先として当たる（黙って捨てない）
    assert fired_pointers(svg) == {"/circles/0"}


def test_upto_without_a_trace_is_refused(pipeline: JinFile) -> None:
    with pytest.raises(ValueError):
        render(pipeline, upto=3)


def test_a_negative_upto_is_refused(pipeline: JinFile) -> None:
    with pytest.raises(ValueError):
        render(pipeline, trace=[], upto=-1)


# --------------------------------------------------------------------------------------
# 強調規則（layout.md §7）
# --------------------------------------------------------------------------------------
def test_an_exact_pointer_is_highlighted(pipeline: JinFile) -> None:
    svg = render(pipeline, trace=[row(1, "/circles/1/flow/exit")])
    assert fired_pointers(svg) == {"/circles/1/flow/exit"}
    assert f'stroke="{ACCENT}"' in svg


def test_a_pointer_with_no_element_falls_back_to_the_nearest_ancestor(pipeline: JinFile) -> None:
    """§7.1 の「末尾から削って祖先を探す」段。`/circles/1/flow/max` はモデルに解決するが描画要素は無い。

    完全一致だけに縮めると、この行は何も強調しなくなる。
    """
    document = pipeline.model_dump(mode="json", by_alias=True)
    assert pointer_exists(document, "/circles/1/flow/max"), "fixture 側の前提が崩れている"
    assert "/circles/1/flow/max" not in {
        element.get("data-jin") for element in contract_elements(render(pipeline))
    }
    svg = render(pipeline, trace=[row(1, "/circles/1/flow/max")])
    assert fired_pointers(svg) == {"/circles/1/flow"}


def test_a_reference_element_is_highlighted_by_a_pointer_under_its_referent(
    pipeline: JinFile,
) -> None:
    """§7.1 規則 2（`data-jin-ref` 一致・DP-IMPL-JIN-P3-OVERLAY-REFERENT-01）。

    focus=Pipeline のとき Critic（`/circles/4`）は Refine の中の**深さ 2 の点**として描かれ、
    その `data-jin` は参照側 `/circles/1/flow/steps/0` である。トレースの行は参照先
    `/circles/4/core` なので、祖先一致だけでは何も強調されない。
    """
    svg = render(pipeline, trace=[row(1, "/circles/4/core")])
    assert fired_pointers(svg) == {"/circles/1/flow/steps/0"}
    fired = [element for element in contract_elements(svg) if element.get("data-jin-fired") == "1"]
    assert fired[0].get("data-jin-ref") == "/circles/4"


def test_a_null_pointer_highlights_nothing_but_still_counts_as_a_dot(pipeline: JinFile) -> None:
    svg = render(pipeline, trace=[row(1, None), row(2, None)])
    assert fired_pointers(svg) == set()
    assert len(_dots(svg)) == 2


def test_an_unresolvable_pointer_highlights_nothing(pipeline: JinFile) -> None:
    svg = render(pipeline, trace=[row(1, "/nowhere/9")])
    assert fired_pointers(svg) == set()
    assert len(_dots(svg)) == 1


def _dots(svg: str) -> list:
    return [
        element for element in contract_elements(svg) if element.get("data-jin-seq") is not None
    ]


# --------------------------------------------------------------------------------------
# machine 5: upto を増やすと強調要素が単調増加する
# --------------------------------------------------------------------------------------
def test_highlights_grow_monotonically_with_upto(pipeline: JinFile) -> None:
    rows = trace_rows()
    assert len(rows) == 11, "コミット済みトレースの行数が変わった"
    previous: set[str] = set()
    for upto in range(len(rows) + 2):
        current = fired_pointers(render(pipeline, trace=rows, upto=upto))
        assert previous <= current, (upto, previous - current)
        previous = current
    assert previous == fired_pointers(render(pipeline, trace=rows))


def test_the_number_of_dots_follows_upto(pipeline: JinFile) -> None:
    """境界環の外側に「発火したイベント数」ぶんの点（要件書 §4）。"""
    rows = trace_rows()
    for upto in range(len(rows) + 1):
        svg = render(pipeline, trace=rows, upto=upto)
        assert len(_dots(svg)) == sum(1 for r in rows if r["seq"] <= upto), upto


def test_dot_positions_do_not_move_as_upto_grows(pipeline: JinFile) -> None:
    """点の角度はトレース**全体**の行数で決まるので、既に置いた点は動かない。"""
    rows = trace_rows()
    placed: list[tuple[str, str]] = []
    for upto in range(len(rows) + 1):
        dots = _dots(render(pipeline, trace=rows, upto=upto))
        current = [(dot.get("cx", ""), dot.get("cy", "")) for dot in dots]
        assert current[: len(placed)] == placed, upto
        placed = current


def test_an_empty_trace_draws_no_dot_and_no_highlight(pipeline: JinFile) -> None:
    """DP-REVIEW-JIN-P2-002 は未決。Phase 3 は「0 行 = 点 0 個・強調なし」で描く。"""
    svg = render(pipeline, trace=[])
    assert _dots(svg) == []
    assert fired_pointers(svg) == set()


def test_a_trace_never_changes_the_pointer_contract(pipeline: JinFile) -> None:
    """点も `data-jin` / `data-jin-kind` を持ち、kind は 9 種の `circle`（layout.md §7）。"""
    svg = render(pipeline, trace=trace_rows())
    for dot in _dots(svg):
        assert dot.get("data-jin") == "/circles/0"
        assert dot.get("data-jin-kind") == "circle"


def test_every_pointer_of_the_committed_trace_resolves_at_the_root_focus(
    pipeline: JinFile,
) -> None:
    """申し送り §4: focus=root で全 pointer が何かの要素に解決すること。

    referent 規則が無いと `/circles/4/core` / `/circles/5/core` が解決しなくなる。
    """
    rows = trace_rows()
    for record in rows:
        svg = render(pipeline, trace=[record])
        assert fired_pointers(svg), record["pointer"]


def test_the_focus_decides_which_events_are_visible(pipeline: JinFile) -> None:
    """focus を変えると同じトレースでも強調される要素が変わる。"""
    rows = trace_rows()
    at_root = fired_pointers(render(pipeline, trace=rows))
    at_drafter = fired_pointers(render(pipeline, focus="Drafter", trace=rows))
    assert at_root != at_drafter
    assert at_drafter == {"/circles/2/core"}


def test_dots_are_not_matched_by_their_own_pointer(pipeline: JinFile) -> None:
    """点は強調計算の**あと**に足す。焦点の circle を指す行が点を赤くしないこと。"""
    svg = render(pipeline, trace=[row(1, "/circles/0")])
    for dot in _dots(svg):
        assert dot.get("data-jin-fired") is None


def test_a_group_highlight_covers_the_whole_circle(pipeline: JinFile) -> None:
    """`escalate`（StateCheckAgent 以外）の pointer は `/circles/i`（adk-mapping §2.4）。"""
    svg = render(pipeline, trace=[row(1, "/circles/0")])
    groups = [
        element
        for element in contract_elements(svg)
        if element.tag == f"{{{SVG_NS}}}g" and element.get("data-jin") == "/circles/0"
    ]
    assert len(groups) == 1
    assert groups[0].get("data-jin-fired") == "1"
    assert groups[0].get("stroke") == ACCENT


def test_a_summoned_circle_stays_unfired_when_only_the_tool_row_appears() -> None:
    """summon 先の内部イベントはトレースに現れない（adk-mapping §2.4 / phase2-handoff §6）。

    「呼ばれた」（tool 行 → 紋が強調）と「中で何が起きたかは不明」（入れ子の中は未強調）を
    描き分ける。
    """
    circles = [
        {"name": "A", "core": "m", "tools": [{"name": "s", "kind": "summon", "circle": "B"}]},
        {"name": "B", "core": "m", "instruction": {"rune": "b"}},
    ]
    model = model_from(circles, "A")
    svg = render(model, trace=[row(1, "/circles/0/tools/0")])
    assert fired_pointers(svg) == {"/circles/0/tools/0"}
    inside = [
        element
        for element in contract_elements(svg)
        if (element.get("data-jin") or "").startswith("/circles/1")
    ]
    assert inside
    assert all(element.get("data-jin-fired") is None for element in inside)


# --------------------------------------------------------------------------------------
# pointer の末尾 → 当たる要素の `data-jin-kind`（layout.md §7.2 と §3 から起こした対応）
# --------------------------------------------------------------------------------------
#: `(pointer, 期待する data-jin-kind)`。layout.md §7.2 の「pointer → 当たるもの」の表と
#: §3 の 9 種表から**人が起こした**対応であって、§7.2 の行の写しではない（§7.2 は
#: pointer と描画要素の対応を書き、kind は §3 の表が決める・F-V-P3-111）。
#: 値をコードから作らない（作ると実装が変わったとき期待も一緒に動く・F-V-P3-007）。
#: 核ありの circle で確かめるもの。
POINTER_KINDS = [
    ("/circles/0", "circle"),
    ("/circles/0/core", "core"),
    ("/circles/0/tools/0", "tool"),
    ("/circles/0/delegate/0", "delegate"),
    ("/circles/0/state/0", "state"),
    ("/circles/0/boundary/guards/0", "guard"),
    ("/circles/0/instruction/rune", "rune"),
]

#: 核なし（flow だけ）の circle で確かめるもの。弦と節は上のモデルに現れないので
#: 別のモデルが要る（この 2 行が無いと kind を入れ替えても全テストが緑・F-V-P3-105）。
FLOW_POINTER_KINDS = [
    ("/circles/0/flow", "flow-edge"),
    ("/circles/0/flow/steps/0", "flow-edge"),
]


def _kinds_at(svg: str, pointer: str) -> set[str]:
    return {
        element.get("data-jin-kind", "")
        for element in contract_elements(svg)
        if element.get("data-jin") == pointer
    }


@pytest.mark.parametrize(("pointer", "kind"), POINTER_KINDS)
def test_a_pointer_lands_on_the_kind_the_table_says(pointer: str, kind: str) -> None:
    circles = [
        {
            "name": "A",
            "core": "m",
            "instruction": {"rune": "r"},
            "tools": [{"name": "t", "kind": "builtin", "builtin": "google_search"}],
            "state": [{"name": "k", "type": "str"}],
            "delegate": ["B"],
            "boundary": {"guards": [{"on": "before_tool", "ref": "g"}], "await": ["t"]},
        },
        {"name": "B", "core": "m"},
    ]
    svg = render(model_from(circles, "A"))
    assert _kinds_at(svg, pointer) == {kind}, pointer


@pytest.mark.parametrize(("pointer", "kind"), FLOW_POINTER_KINDS)
def test_a_flow_pointer_lands_on_the_kind_the_table_says(pointer: str, kind: str) -> None:
    """layout.md §7.2 の弦（`/circles/i/flow`）と節（`/circles/i/flow/steps/j`）の行。"""
    circles = [
        {"name": "F", "flow": {"kind": "sequence", "steps": ["A", "B"]}},
        {"name": "A", "core": "m"},
        {"name": "B", "core": "m"},
    ]
    svg = render(model_from(circles, "F"))
    assert _kinds_at(svg, pointer) == {kind}, pointer


def test_the_await_pointer_lands_on_the_await_kind() -> None:
    circles = [
        {
            "name": "A",
            "core": "m",
            "tools": [{"name": "t", "kind": "builtin", "builtin": "google_search"}],
            "boundary": {"await": ["t"]},
        }
    ]
    svg = render(model_from(circles, "A"))
    assert _kinds_at(svg, "/circles/0/boundary/await/0") == {"await"}


def test_the_flow_exit_mark_lands_on_the_flow_edge_kind() -> None:
    """layout.md §7.2: `/circles/i/flow/exit` は中心の菱形（`flow-edge`）。"""
    circles = [
        {
            "name": "L",
            "flow": {
                "kind": "loop",
                "steps": ["A", "B"],
                "max": 3,
                "exit": {"key": "done", "equals": True},
            },
        },
        {"name": "A", "core": "m"},
        {"name": "B", "core": "m"},
    ]
    svg = render(model_from(circles, "L"))
    assert _kinds_at(svg, "/circles/0/flow/exit") == {"flow-edge"}


def test_a_pointer_with_no_element_falls_back_to_its_ancestor() -> None:
    """layout.md §7.2 末尾: `/circles/i/flow/max` は祖先一致で `/circles/i/flow`（弦）に落ちる。"""
    circles = [
        {"name": "L", "flow": {"kind": "sequence", "steps": ["A", "B"]}},
        {"name": "A", "core": "m"},
        {"name": "B", "core": "m"},
    ]
    svg = render(model_from(circles, "L"), trace=[row(1, "/circles/0/flow/max")])
    assert fired_pointers(svg) == {"/circles/0/flow"}
