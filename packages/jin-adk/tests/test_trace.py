"""`TraceBuilder` の単体テスト（要件書 §3.4 / ADR-009）。

`test_run.py` は実行して出たイベントしか見られない。`FakeLlm` はツールを呼ばず
転送もしないので、**`kind: tool` と `kind: transfer` の経路が実行では通らない**。
実モデルを呼ばずにその経路を通すために、ここでは ADK の `Event` を直接組み立てる
（実物の `Event` / `EventActions` / `google.genai.types` を使う。モックにすると
「Jin 側のスキーマ」だけを検査して ADK 側の形を取り違えたままになる）。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from google.adk.events import Event, EventActions
from google.genai import types
from jin_adk.codegen import generate
from jin_adk.trace import TraceBuilder, format_timestamp
from jin_core.canonical import dumps
from jin_core.pointer import pointer_exists

REPO_ROOT = Path(__file__).resolve().parents[3]
RESEARCHER = REPO_ROOT / "examples" / "researcher" / "researcher.jin"


def builder_for(load_jin: Callable, path: Path):
    model = load_jin(path)
    project = generate(model)
    return (
        TraceBuilder(
            project.pointer_map,
            model_of={c.name: c.core for c in model.circles if c.core is not None},
        ),
        model,
    )


def test_function_call_becomes_a_tool_line_pointing_at_the_tool(load_jin: Callable) -> None:
    builder, model = builder_for(load_jin, RESEARCHER)
    event = Event(
        author="Researcher",
        timestamp=1.0,
        content=types.Content(
            role="model",
            parts=[
                types.Part(function_call=types.FunctionCall(name="search", args={"query": "陣"}))
            ],
        ),
    )
    lines = list(builder.events_from(event))
    assert len(lines) == 1
    assert lines[0].kind == "tool"
    assert lines[0].name == "search"
    # tools[].name は circle 内一意でしかないので、表は必ずエージェント名で切る（ADR-009）。
    assert lines[0].pointer == "/circles/0/tools/0"
    assert lines[0].input == {"query": "陣"}
    assert lines[0].output is None
    assert pointer_exists(json.loads(dumps(model)), lines[0].pointer)


def test_function_response_becomes_a_tool_line_with_the_output(load_jin: Callable) -> None:
    builder, _ = builder_for(load_jin, RESEARCHER)
    event = Event(
        author="Researcher",
        timestamp=2.0,
        content=types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        name="publish", response={"status": "pending"}
                    )
                )
            ],
        ),
    )
    lines = list(builder.events_from(event))
    assert len(lines) == 1
    assert lines[0].kind == "tool"
    assert lines[0].name == "publish"
    assert lines[0].pointer == "/circles/0/tools/3"
    assert lines[0].output == {"status": "pending"}


def test_the_same_tool_name_in_two_circles_resolves_to_different_pointers(
    tmp_path: Path, load_jin: Callable, minimal_jin: Callable, write_jin: Callable
) -> None:
    """ADR-009 が案 A（実行時の逆引き）を採らなかった理由そのもの。

    `tools[].name` は circle 内一意なので、同名 tool が 2 つの circle にあると
    名前だけでは引けない。`Event.author` で切ることで正しい pointer になる。
    """
    payload = minimal_jin(
        circles=[
            {
                "name": "Root",
                "core": "m",
                "instruction": {"rune": "x"},
                "tools": [{"name": "shared", "kind": "tool", "ref": "a:one"}],
                "delegate": ["Child"],
            },
            {
                "name": "Child",
                "core": "m",
                "instruction": {"rune": "y"},
                "tools": [{"name": "shared", "kind": "tool", "ref": "b:two"}],
            },
        ]
    )
    builder, _ = builder_for(load_jin, write_jin(tmp_path, "a.jin", payload))

    def call(author: str) -> str:
        event = Event(
            author=author,
            timestamp=1.0,
            content=types.Content(
                role="model",
                parts=[types.Part(function_call=types.FunctionCall(name="shared", args={}))],
            ),
        )
        return next(iter(builder.events_from(event))).pointer

    assert call("Root") == "/circles/0/tools/0"
    assert call("Child") == "/circles/1/tools/0"


def test_transfer_points_at_the_delegate_entry(
    tmp_path: Path, load_jin: Callable, minimal_jin: Callable, write_jin: Callable
) -> None:
    payload = minimal_jin(
        circles=[
            {"name": "Root", "core": "m", "instruction": {"rune": "x"}, "delegate": ["Child"]},
            {"name": "Child", "core": "m", "instruction": {"rune": "y"}},
        ]
    )
    builder, model = builder_for(load_jin, write_jin(tmp_path, "a.jin", payload))
    event = Event(author="Root", timestamp=3.0, actions=EventActions(transfer_to_agent="Child"))
    lines = list(builder.events_from(event))
    assert [line.kind for line in lines] == ["transfer"]
    assert lines[0].name == "Child"
    assert lines[0].pointer == "/circles/0/delegate/0"
    assert pointer_exists(json.loads(dumps(model)), lines[0].pointer)


def test_a_text_event_produces_a_model_line_and_a_final_line(load_jin: Callable) -> None:
    """最終応答は `model` と `final` の 2 行になる（発火した要素と結果を両方残す）。"""
    builder, _ = builder_for(load_jin, RESEARCHER)
    event = Event(
        author="Researcher",
        timestamp=4.0,
        content=types.Content(role="model", parts=[types.Part(text="答え")]),
    )
    lines = list(builder.events_from(event))
    assert [line.kind for line in lines] == ["model", "final"]
    assert lines[0].name == "gemini-2.5-flash"
    assert lines[0].pointer == "/circles/0/core"
    assert lines[1].pointer == "/circles/0"
    assert lines[0].output == lines[1].output == "答え"


def test_a_partial_event_is_not_final(load_jin: Callable) -> None:
    """途中経過（`partial`）を `final` にしない。"""
    builder, _ = builder_for(load_jin, RESEARCHER)
    event = Event(
        author="Researcher",
        timestamp=5.0,
        partial=True,
        content=types.Content(role="model", parts=[types.Part(text="途中")]),
    )
    assert [line.kind for line in builder.events_from(event)] == ["model"]


def test_seq_increases_across_events(load_jin: Callable) -> None:
    builder, _ = builder_for(load_jin, RESEARCHER)
    first = Event(
        author="Researcher",
        timestamp=1.0,
        content=types.Content(role="model", parts=[types.Part(text="a")]),
    )
    second = Event(
        author="Researcher",
        timestamp=2.0,
        content=types.Content(role="model", parts=[types.Part(text="b")]),
    )
    seqs = [line.seq for line in builder.events_from(first)]
    seqs += [line.seq for line in builder.events_from(second)]
    assert seqs == [1, 2, 3, 4]


def test_an_event_with_nothing_in_it_produces_no_lines(load_jin: Callable) -> None:
    """空のイベントで空行を作らない（`seq` が飛ぶ）。"""
    builder, _ = builder_for(load_jin, RESEARCHER)
    assert list(builder.events_from(Event(author="Researcher", timestamp=1.0))) == []


def test_format_timestamp_is_utc() -> None:
    assert format_timestamp(0.0) == "1970-01-01T00:00:00+00:00"
    assert format_timestamp(None) == "", "時刻が無いときに捏造しない"


def test_non_json_values_are_labelled_not_dropped() -> None:
    """`json.dumps` できない値でトレースを 1 行も残せなくならないこと。"""
    from jin_adk.trace import _jsonable

    class Opaque:
        pass

    assert _jsonable(Opaque()) == "<Opaque>"
    assert _jsonable({"a": [Opaque()]}) == {"a": ["<Opaque>"]}
    assert json.dumps(_jsonable({"a": Opaque()}))


def test_an_unknown_agent_falls_back_to_an_empty_pointer_not_a_wrong_one(
    load_jin: Callable,
) -> None:
    """表に無いエージェントの行に、**別の要素の pointer** を当てない。

    嘘の pointer を出すと、エディタが無関係な場所を光らせる。空のほうがまだよい。
    """
    builder, _ = builder_for(load_jin, RESEARCHER)
    event = Event(
        author="ImNotInTheModel",
        timestamp=1.0,
        content=types.Content(role="model", parts=[types.Part(text="a")]),
    )
    assert all(line.pointer == "" for line in builder.events_from(event))
