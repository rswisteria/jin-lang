"""`jin_adk.trace`: ADK Event → 要件書 §3.4 のトレース行。

ADR-009 constraint「引けなかったイベントは pointer を null にして黙って落とさず、
対応不能であることを明示する」をここで固定する。`ts` はスナップショットに入れない。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from google.adk.events import Event, EventActions
from google.genai import types
from jin_adk.codegen import generate
from jin_adk.trace import (
    KIND_POINTERS,
    KINDS,
    TRACE_FIELDS,
    TRANSFER_TOOL_NAME,
    RuntimeTable,
    TraceWriter,
    classify,
)
from jin_core.check import check_file

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPO_ROOT / "examples"


def table_for(name: str) -> RuntimeTable:
    result = check_file(EXAMPLES / name / f"{name}.jin")
    assert result.model is not None
    return RuntimeTable.from_pointer_map(generate(result.model).pointers)


def text_event(author: str, text: str) -> Event:
    return Event(author=author, content=types.Content(role="model", parts=[types.Part(text=text)]))


def test_schema_constants_match_the_requirements() -> None:
    assert TRACE_FIELDS == ("seq", "ts", "agent", "kind", "name", "pointer", "input", "output")
    assert KINDS == frozenset({"model", "tool", "transfer", "escalate", "final"})


def test_unknown_author_gets_a_null_pointer_not_a_dropped_row() -> None:
    table = table_for("researcher")
    rows = classify(text_event("Stranger", "hi"), table)
    assert len(rows) == 1
    assert rows[0].pointer is None
    assert rows[0].agent == "Stranger" and rows[0].kind == "model"
    assert rows[0].name == "Stranger"
    assert table.unresolved  # 理由が残る（黙らない）


def test_ts_is_taken_from_the_event_timestamp() -> None:
    """adk-mapping.md §2.4「`ts` は `Event.timestamp`」（F-C-P2-014: 型だけ見ると 0.0 でも通る）。"""
    table = table_for("researcher")
    event = Event(
        author="Researcher",
        timestamp=1725500000.25,
        content=types.Content(role="model", parts=[types.Part(text="x")]),
    )
    assert classify(event, table)[0].ts == 1725500000.25


def test_unknown_tool_name_gets_a_null_pointer() -> None:
    table = table_for("researcher")
    event = Event(
        author="Researcher",
        content=types.Content(
            role="model",
            parts=[types.Part(function_call=types.FunctionCall(name="ghost_tool", args={"a": 1}))],
        ),
    )
    rows = classify(event, table)
    assert [r.kind for r in rows] == ["tool"]
    assert rows[0].pointer is None and rows[0].name == "ghost_tool"
    assert rows[0].input == {"a": 1}


def test_transfer_points_at_the_delegate_entry() -> None:
    from jin_core.model import JinFile

    model = JinFile.model_validate(
        {
            "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
            "version": 1,
            "root": "Boss",
            "circles": [
                {"name": "Boss", "core": "m", "delegate": ["Worker"]},
                {"name": "Worker", "core": "m"},
            ],
        }
    )
    table = RuntimeTable.from_pointer_map(generate(model).pointers)
    event = Event(author="Boss", actions=EventActions(transfer_to_agent="Worker"))
    rows = classify(event, table)
    assert [(r.kind, r.name, r.pointer) for r in rows] == [
        ("transfer", "Worker", "/circles/0/delegate/0")
    ]
    assert rows[0].input == {"to": "Worker"}
    # delegate に無い相手への transfer は pointer null
    stray = classify(Event(author="Boss", actions=EventActions(transfer_to_agent="Nobody")), table)
    assert stray[0].pointer is None and stray[0].kind == "transfer"


def test_transfer_function_call_is_not_a_tool_row(delegating_table: RuntimeTable) -> None:
    """F-C-P2-004: ADK の transfer は「function_call → response 側の `actions.transfer_to_agent`」の 2 event。
    前者を `tool` 行にすると `.jin` に無いツールとして pointer null + stderr の苦情になる。行にしない。"""
    call = Event(
        author="Boss",
        content=types.Content(
            role="model",
            parts=[
                types.Part(
                    function_call=types.FunctionCall(
                        name=TRANSFER_TOOL_NAME, args={"agent_name": "Worker"}
                    )
                )
            ],
        ),
    )
    assert classify(call, delegating_table) == []
    assert delegating_table.unresolved == []
    # テキストが同居していれば model 行だけが出る
    with_text = Event(
        author="Boss",
        content=types.Content(
            role="model",
            parts=[
                types.Part(text="任せます"),
                types.Part(
                    function_call=types.FunctionCall(
                        name=TRANSFER_TOOL_NAME, args={"agent_name": "Worker"}
                    )
                ),
            ],
        ),
    )
    assert [r.kind for r in classify(with_text, delegating_table)] == ["model"]


def test_transfer_keeps_the_sibling_tool_response_rows() -> None:
    """F-C-P2-101（ラウンド 1 の F-C-P2-004 修正が持ち込んだ回帰）: LLM が 1 ターンで `web_search` と
    `transfer_to_agent` を並列に呼ぶと ADK は応答を 1 つの function_response event にまとめ、その
    `actions.transfer_to_agent` を立てる。transfer 分岐で早期 return すると `web_search` の応答行が消えて
    呼び出し行と対にならない。行順は tool → transfer。transfer 自身の function_response は行にしない。"""
    from jin_core.model import JinFile

    model = JinFile.model_validate(
        {
            "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
            "version": 1,
            "root": "Boss",
            "circles": [
                {
                    "name": "Boss",
                    "core": "m",
                    "tools": [{"name": "s", "kind": "tool", "ref": "research.tools:web_search"}],
                    "delegate": ["Worker"],
                },
                {"name": "Worker", "core": "m"},
            ],
        }
    )
    table = RuntimeTable.from_pointer_map(generate(model).pointers)
    table.bind_tools("Boss", ["web_search"])
    event = Event(
        author="Boss",
        actions=EventActions(transfer_to_agent="Worker"),
        content=types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        name="web_search", response={"result": "stub-search:q"}
                    )
                ),
                types.Part(
                    function_response=types.FunctionResponse(name=TRANSFER_TOOL_NAME, response={})
                ),
            ],
        ),
    )
    rows = classify(event, table)
    assert [(r.kind, r.name, r.pointer) for r in rows] == [
        ("tool", "web_search", "/circles/0/tools/0"),
        ("transfer", "Worker", "/circles/0/delegate/0"),
    ]
    assert rows[0].output == {"result": "stub-search:q"} and rows[0].input is None
    assert rows[1].input == {"to": "Worker"}
    assert table.unresolved == []


@pytest.fixture
def delegating_table() -> RuntimeTable:
    from jin_core.model import JinFile

    model = JinFile.model_validate(
        {
            "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
            "version": 1,
            "root": "Boss",
            "circles": [
                {"name": "Boss", "core": "m", "delegate": ["Worker"]},
                {"name": "Worker", "core": "m"},
            ],
        }
    )
    return RuntimeTable.from_pointer_map(generate(model).pointers)


def test_text_and_function_call_in_one_event_give_model_then_tool_rows() -> None:
    """F-C-P2-007: Gemini は「検索します」+ function_call を 1 応答で返す。テキストを捨てない。"""
    table = table_for("researcher")
    event = Event(
        author="Researcher",
        content=types.Content(
            role="model",
            parts=[
                types.Part(text="検索します"),
                types.Part(function_call=types.FunctionCall(name="web_search", args={"q": 1})),
            ],
        ),
    )
    rows = classify(event, table)
    assert [(r.kind, r.output if r.kind == "model" else r.input) for r in rows] == [
        ("model", "検索します"),
        ("tool", {"q": 1}),
    ]
    assert rows[0].pointer == "/circles/0/core"


def test_non_checker_escalate_keeps_the_tool_row_and_adds_an_escalate_row() -> None:
    """F-C-P2-005: `exit_loop` の応答 event は `actions.escalate` を持つ。tool 行を消さず escalate 行を足す。
    name = author / pointer = `/circles/i`（checker 由来の escalate とは別の行・§2.4 の 2 行目）。"""
    table = table_for("researcher")
    table.bind_tools("Researcher", ["web_search", "fetch_page", "Summarizer", "publish"])
    event = Event(
        author="Researcher",
        actions=EventActions(escalate=True),
        content=types.Content(
            role="model",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(name="web_search", response={"r": 1})
                )
            ],
        ),
    )
    rows = classify(event, table)
    assert [(r.kind, r.name, r.pointer) for r in rows] == [
        ("tool", "web_search", "/circles/0/tools/0"),
        ("escalate", "Researcher", "/circles/0"),
    ]
    assert rows[0].output == {"r": 1}


def test_model_error_event_is_not_shown_as_an_empty_successful_response() -> None:
    """F-C-P2-021: `error_code` / `error_message` を持つ event は output が error の辞書になる。"""
    table = table_for("researcher")
    event = Event(author="Researcher", error_code="RESOURCE_EXHAUSTED", error_message="quota")
    rows = classify(event, table)
    assert [r.kind for r in rows] == ["model"]
    assert rows[0].output == {"error_code": "RESOURCE_EXHAUSTED", "error_message": "quota"}


def test_kind_pointer_shapes_cover_every_kind() -> None:
    assert set(KIND_POINTERS) == set(KINDS)


def test_state_check_event_is_an_escalate_row_even_when_not_matched() -> None:
    table = table_for("pipeline")
    event = Event(
        author="Refine_exit_check",
        actions=EventActions(escalate=False),
        custom_metadata={
            "state_check": {"key": "approved", "expected": True, "actual": "no", "matched": False}
        },
    )
    rows = classify(event, table)
    assert rows[0].kind == "escalate"
    assert rows[0].pointer == "/circles/1/flow/exit"
    assert rows[0].name == "Refine"
    assert rows[0].input == {"key": "approved", "expected": True}
    assert rows[0].output == {"actual": "no", "matched": False}


def test_partial_streaming_events_are_skipped() -> None:
    table = table_for("researcher")
    event = Event(
        author="Researcher",
        partial=True,
        content=types.Content(role="model", parts=[types.Part(text="par")]),
    )
    assert classify(event, table) == []


def test_duplicate_tool_names_inside_one_agent_are_reported_as_unresolvable() -> None:
    """同名の ADK ツールが 1 agent に 2 つあると添字で引けない。黙って片方に寄せず null にする。

    コンパイル時（`codegen._validate_core_circle`）は ref の attribute 名で重複を拒むが、実行時の
    名前は `func.__name__` で、`run = other` のような束縛があれば attribute 名と一致しない。
    この経路は到達可能なので残す（`test_runtime.py::test_runtime_tool_name_collision_...` が実測）。
    """
    from jin_core.model import JinFile

    model = JinFile.model_validate(
        {
            "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
            "version": 1,
            "root": "R",
            "circles": [
                {
                    "name": "R",
                    "core": "m",
                    "tools": [
                        {"name": "a", "kind": "tool", "ref": "pkg_a:run"},
                        {"name": "b", "kind": "tool", "ref": "pkg_b:go"},
                    ],
                }
            ],
        }
    )
    table = RuntimeTable.from_pointer_map(generate(model).pointers)
    table.bind_tools("R", ["run", "run"])
    event = Event(
        author="R",
        content=types.Content(
            role="model", parts=[types.Part(function_call=types.FunctionCall(name="run", args={}))]
        ),
    )
    rows = classify(event, table)
    assert rows[0].pointer is None
    assert table.unresolved  # 対応不能であったことが記録される


def test_writer_relabels_the_last_model_row_as_final_and_writes_jsonl(tmp_path: Path) -> None:
    table = table_for("researcher")
    out = tmp_path / "t.jsonl"
    with out.open("w", encoding="utf-8") as handle:
        writer = TraceWriter(table, sink=handle)
        writer.push(text_event("Researcher", "first"))
        writer.push(text_event("Researcher", "second"))
        writer.close()
    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").split("\n") if line]
    assert [line["kind"] for line in lines] == ["model", "final"]
    assert [line["seq"] for line in lines] == [1, 2]
    assert all(list(line) == list(TRACE_FIELDS) for line in lines)
    assert lines[1]["output"] == "second"


def test_writer_does_not_relabel_a_tool_row_as_final(tmp_path: Path) -> None:
    table = table_for("researcher")
    rows = []
    writer = TraceWriter(table, on_row=rows.append)
    writer.push(text_event("Researcher", "x"))
    writer.push(
        Event(
            author="Researcher",
            content=types.Content(
                role="model",
                parts=[types.Part(function_call=types.FunctionCall(name="web_search", args={}))],
            ),
        )
    )
    writer.close()
    assert [r.kind for r in rows] == ["model", "tool"]
