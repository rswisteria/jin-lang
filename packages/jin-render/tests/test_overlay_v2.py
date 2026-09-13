"""v2 のトレース overlay（docs/spec/v2/layout.md §6）。

`tests/fixtures/traces/paddle-v2.jsonl` は `jin run examples-v2/paddle/paddle.jin --ticks 3 --debug --trace`
の出力（38 行・seq 0 始まり）。実行結果との突合は `tests/contract/test_render_contract_v2.py`。
"""

from __future__ import annotations

import pytest
from jin_core.v2.model import JinFileV2
from jin_render import render
from jin_render.overlay import TraceRowError, read_trace

from .conftest import contract_elements, fired_pointers, trace_rows_v2


def test_the_fixture_has_the_expected_shape() -> None:
    rows = trace_rows_v2()
    assert len(rows) == 38
    assert [row["seq"] for row in rows] == list(range(38))
    assert rows[0]["kind"] == "enter" and rows[0]["pointer"] == "/circles/1"
    assert [row["kind"] for row in rows].count("frame") == 3
    assert all(row["pointer"] == "/stage" for row in rows if row["kind"] == "frame")


def test_seq_zero_is_accepted_for_v2_but_not_by_the_v1_default() -> None:
    rows = [{"seq": 0, "pointer": None}]
    assert [row.seq for row in read_trace(rows, min_seq=0)] == [0]
    with pytest.raises(TraceRowError):
        read_trace(rows)
    with pytest.raises(TraceRowError):
        read_trace([{"seq": -1, "pointer": None}], min_seq=0)


def test_upto_zero_fires_only_the_enter_row(paddle: JinFileV2) -> None:
    svg = render(paddle, focus="Play", trace=trace_rows_v2(), upto=0)
    assert fired_pointers(svg) == {"/circles/1"}
    dots = [e for e in contract_elements(svg) if e.get("data-jin-seq") is not None]
    assert [e.get("data-jin-seq") for e in dots] == ["0"]
    assert all(
        e.get("data-jin") == "/circles/1" and e.get("data-jin-kind") == "circle" for e in dots
    )


def test_step_rows_fall_on_the_rite_glyph_in_the_circle_view(paddle: JinFileV2) -> None:
    """`/circles/1/rites/2/steps/2`（set）は祖先一致で手順環の小陣 `/circles/1/rites/2` に落ちる。"""
    rows = trace_rows_v2()
    svg = render(paddle, focus="Play", trace=rows, upto=7)
    fired = fired_pointers(svg)
    assert "/circles/1/rites/2" in fired  # step（rite 行 + set 行）
    assert "/circles/1/rites/0" in fired  # begin
    assert "/circles/1/boundary/on/0" in fired  # event 行
    assert "/circles/1/rites/2/steps/2" not in fired  # 陣の図にステップの要素は無い


def test_step_rows_fire_step_glyphs_and_edges_in_the_rite_view(paddle: JinFileV2) -> None:
    rows = trace_rows_v2()
    svg = render(paddle, focus="Play/step", trace=rows)
    fired = fired_pointers(svg)
    assert "/circles/1/rites/2/steps/2" in fired
    assert "/circles/1/rites/2/steps/3" in fired
    assert "/circles/1/rites/2" in fired  # rite 行は図の `<g>` と環に完全一致
    # 焦点の外の行（enter / begin / paint）はどの要素にも当たらず、点にだけ数える。
    assert "/circles/1" not in fired and "/circles/1/rites/0" not in fired
    dots = [e for e in contract_elements(svg) if e.get("data-jin-seq") is not None]
    assert len(dots) == 38
    assert all(e.get("data-jin") == "/circles/1/rites/2" for e in dots)


def test_frame_rows_never_highlight_the_stage(paddle: JinFileV2) -> None:
    svg = render(paddle, focus="Play", trace=trace_rows_v2())
    stage = [e for e in contract_elements(svg) if e.get("data-jin-kind") in ("stage", "form")]
    assert stage and not any(e.get("data-jin-fired") for e in stage)
    # `frame` 行も点には数える（全 38 行）。
    assert sum(1 for e in contract_elements(svg) if e.get("data-jin-seq") is not None) == 38


def test_rows_of_a_nested_circle_hit_it_through_the_referent_rule(paddle: JinFileV2) -> None:
    """root（Game）の図では Play は入れ子の小陣で、`/circles/1/…` の行は `data-jin-ref` で当たる。"""
    svg = render(paddle, trace=trace_rows_v2(), upto=0)
    fired = fired_pointers(svg)
    assert "/circles/0/flow/steps/0" in fired  # Game の flow の節（参照側）
    assert "/circles/1" in fired  # 入れ子の Play の `<g>`（enter 行の完全一致）


def test_upto_without_a_trace_is_refused(paddle: JinFileV2) -> None:
    with pytest.raises(ValueError):
        render(paddle, upto=3)
    with pytest.raises(ValueError):
        render(paddle, trace=[], upto=-1)


def test_an_empty_trace_draws_no_dots_and_no_accent(paddle: JinFileV2) -> None:
    svg = render(paddle, focus="Play", trace=[])
    assert "data-jin-seq" not in svg and "data-jin-fired" not in svg
