"""ADK `Event` → 要件書 §3.4 のトレース行 `{seq, ts, agent, kind, name, pointer, input, output}`。

トレース JSONL は **ADK Event そのものではなく Jin 側の派生スキーマ**（adk-api-probe.md）。
`agent` は `Event.author`、`ts` は `Event.timestamp` から取る。DP-COMMON-14: トレースは
`--trace` 指定時だけ書く成果物であり、ログではない（ログは stderr）。

## pointer の引き方（ADR-009 案 B）

コード生成時の `PointerMap`（ADK 識別子 → JSON Pointer）を、import 後の agent 木で
ADK 上のツール名に結び付けた `RuntimeTable` で引く:

| kind | 判定 | pointer | name |
|---|---|---|---|
| `escalate`（checker） | author が StateCheckAgent（一致しなかった回も） | `/circles/i/flow/exit` | loop circle 名 |
| `escalate`（`actions.escalate`） | `exit_loop` などが立てた `actions.escalate`。同じ event の `tool` 行の**後**に出す | `/circles/i` | author |
| `transfer` | `actions.transfer_to_agent`（function_response 側の event） | `/circles/i/delegate/k` | 転送先 agent 名 |
| `tool` | function_call / function_response の part（1 part = 1 行）。`transfer_to_agent` の function_call は行にしない（応答側が `transfer` 行になる） | `/circles/i/tools/j` | ADK のツール名 |
| `model` | テキスト part（function_call と同居するときも出す・text → tool の順）、または part の無い event。`error_code` / `error_message` を持つ event は `output` が `{"error_code", "error_message"}` | `/circles/i/core` | `core` のモデル文字列 |
| `final` | 実行全体の**最後**の `model` 行を `TraceWriter.close()` が付け替える | 同上 | 同上 |

正典は `docs/spec/adk-mapping.md` §2.4（`KIND_POINTERS` と表の pointer 列を
`tests/spec/test_spec_consistency.py::test_trace_kinds_table_matches_the_implementation` が突合する）。

**引けなかったものは `pointer: null` にして行は落とさない**（ADR-009 constraint / NFR-FAIL-001）。
`RuntimeTable.unresolved` に理由を残し、CLI が stderr に出す。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from google.adk.events import Event

from jin_adk.codegen import PointerMap

#: 要件書 §3.4 のキー順。
TRACE_FIELDS = ("seq", "ts", "agent", "kind", "name", "pointer", "input", "output")
#: 要件書 §3.4 の kind。
KINDS = frozenset({"model", "tool", "transfer", "escalate", "final"})
#: kind ごとの pointer の形（adk-mapping.md §2.4 の表と突合する）。
KIND_POINTERS: dict[str, frozenset[str]] = {
    "model": frozenset({"/circles/i/core"}),
    "tool": frozenset({"/circles/i/tools/j"}),
    "transfer": frozenset({"/circles/i/delegate/k"}),
    "escalate": frozenset({"/circles/i/flow/exit", "/circles/i"}),
    "final": frozenset({"/circles/i/core"}),
}
#: ADK の transfer は「model が `transfer_to_agent(agent_name=...)` を function_call」→
#: 「その function_response event に `actions.transfer_to_agent` が立つ」の 2 event（2.8.0 実測）。
#: 行にするのは後者（`transfer`）だけ。前者を `tool` にすると `.jin` に無いツール名として
#: pointer null + stderr の苦情になる（correctness review F-C-P2-004）。
TRANSFER_TOOL_NAME = "transfer_to_agent"


@dataclass(frozen=True)
class TraceRow:
    seq: int
    ts: float
    agent: str
    kind: str
    name: str
    pointer: str | None
    input: Any
    output: Any

    def to_json_dict(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in TRACE_FIELDS}

    def with_seq(self, seq: int) -> TraceRow:
        return TraceRow(
            seq, self.ts, self.agent, self.kind, self.name, self.pointer, self.input, self.output
        )

    def with_kind(self, kind: str) -> TraceRow:
        return TraceRow(
            self.seq, self.ts, self.agent, kind, self.name, self.pointer, self.input, self.output
        )


@dataclass
class RuntimeTable:
    """`PointerMap` + 実行時に確定する ADK ツール名。

    ADK のツール名は `FunctionTool.name == func.__name__` で、`.jin` の `tools[].name` ではない
    （実測）。生成コードの `tools=[...]` は `.jin` の宣言順なので、import 後の
    `agent.tools[j].name` を添字 j の pointer に結び付ける（`bind_tools`）。

    同名の扱い: コンパイル時（`jin_adk.codegen._validate_core_circle`）は ref の **attribute 名**で
    重複を拒むが、実行時の名前は **`func.__name__`** で、利用者モジュールが `run = other` /
    `from x import f as g` と束縛していれば両者はずれる。したがって `bind_tools` の「同名は None」
    経路は到達可能であり、残してある（`test_trace.py::test_duplicate_tool_names_...` が
    `bind_tools` を直接叩いて固定）。
    """

    pointers: PointerMap
    #: (agent 名, ADK ツール名) → pointer（同名が 2 つあれば None = 対応不能）
    tool_pointer: dict[tuple[str, str], str | None] = field(default_factory=dict)
    #: 引けなかった理由（重複はまとめる）
    unresolved: list[str] = field(default_factory=list)

    @classmethod
    def from_pointer_map(cls, pointers: PointerMap) -> RuntimeTable:
        return cls(pointers=pointers)

    def bind_tools(self, agent_name: str, adk_tool_names: list[str]) -> None:
        entry = self.pointers.agents.get(agent_name)
        for j, tool_name in enumerate(adk_tool_names):
            key = (agent_name, tool_name)
            if entry is None or j >= len(entry.tools):
                self.tool_pointer[key] = None
                self._note(
                    f"agent '{agent_name}' のツール '{tool_name}' に対応する tools[{j}] が無い"
                )
            elif key in self.tool_pointer:
                self.tool_pointer[key] = None
                self._note(
                    f"agent '{agent_name}' に同名の ADK ツール '{tool_name}' が 2 つ以上あり、"
                    "ADK 上で同じ名前になるので片方が呼べません（どの tools[] か決められないので "
                    "pointer は null）。ref の別名 import は FunctionTool.name == func.__name__ を変えません"
                )
            else:
                self.tool_pointer[key] = entry.tools[j]

    def _note(self, reason: str) -> None:
        if reason not in self.unresolved:
            self.unresolved.append(reason)

    # ---- 参照 -------------------------------------------------------------------------
    def agent_pointer(self, author: str) -> str | None:
        entry = self.pointers.agents.get(author)
        if entry is None:
            self._note(f"agent '{author}' は .jin に無い（pointer: null）")
            return None
        return entry.pointer

    def core_pointer(self, author: str) -> tuple[str | None, str]:
        entry = self.pointers.agents.get(author)
        if entry is None:
            self._note(f"agent '{author}' は .jin に無い（pointer: null）")
            return None, author
        if entry.core is None:
            return entry.pointer, author
        return entry.core, entry.model or author

    def tool(self, author: str, tool_name: str) -> str | None:
        key = (author, tool_name)
        if key not in self.tool_pointer:
            self._note(f"agent '{author}' のツール '{tool_name}' は .jin に無い（pointer: null）")
            return None
        return self.tool_pointer[key]

    def delegate(self, author: str, target: str) -> str | None:
        entry = self.pointers.agents.get(author)
        pointer = entry.delegate.get(target) if entry is not None else None
        if pointer is None:
            self._note(
                f"agent '{author}' から '{target}' への transfer は delegate に無い（pointer: null）"
            )
        return pointer

    def exit_of(self, checker: str) -> tuple[str | None, str]:
        loop = self.pointers.exit_checkers[checker]
        entry = self.pointers.agents[loop]
        return entry.exit, loop


def _jsonable(value: Any) -> Any:
    """`input` / `output` を JSON にできる値へ落とす（Pydantic / bytes などは文字列化）。"""
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return json.loads(json.dumps(value, default=str))
    return value


def classify(event: Event, table: RuntimeTable) -> list[TraceRow]:
    """Event を 0 個以上のトレース行にする（`seq` は 0 のまま。`TraceWriter` が振る）。

    部分応答（`partial=True` のストリーミング断片）は落とす。同じテキストが確定イベントで
    もう一度来るので、行にすると二重になる。

    1 event から複数行が出る順序: `model`（テキスト part）→ `tool`（function_call / response）
    → `transfer`（`actions.transfer_to_agent`）→ `escalate`（`actions.escalate`）。
    `transfer_to_agent` の function_call / function_response は行にしない（`TRANSFER_TOOL_NAME`。
    後者は `transfer` 行で出る）。**transfer と同じ event に同居する他ツールの応答行は残す**
    （LLM が 1 ターンで `web_search` と `transfer_to_agent` を並列に呼ぶと ADK は応答を 1 event に
    まとめる。transfer 分岐で早期 return すると `web_search` の応答行が消え、呼び出し行と対に
    ならない・F-C-P2-101 = ラウンド 1 の F-C-P2-004 修正が持ち込んだ回帰）。
    """
    if event.partial:
        return []
    author = event.author
    ts = float(event.timestamp)
    actions = event.actions

    if author in table.pointers.exit_checkers:
        pointer, loop = table.exit_of(author)
        meta = (event.custom_metadata or {}).get("state_check") or {}
        return [
            TraceRow(
                0,
                ts,
                author,
                "escalate",
                loop,
                pointer,
                {"key": meta.get("key"), "expected": meta.get("expected")},
                {"actual": _jsonable(meta.get("actual")), "matched": bool(actions.escalate)},
            )
        ]
    transfer_target = actions.transfer_to_agent or None

    calls = event.get_function_calls()
    responses = event.get_function_responses()
    text = "".join(
        part.text
        for part in (event.content.parts if event.content and event.content.parts else [])
        if part.text and not part.thought
    )
    error = (
        {"error_code": event.error_code, "error_message": event.error_message}
        if event.error_code or event.error_message
        else None
    )

    rows: list[TraceRow] = []
    if text or error or not (calls or responses or transfer_target):
        # F-C-P2-007: function_call と同居するテキストも捨てない。F-C-P2-021: モデル呼び出しの失敗を
        # 空応答の正常終了に見せない
        pointer, model_name = table.core_pointer(author)
        rows.append(TraceRow(0, ts, author, "model", model_name, pointer, None, error or text))
    for call in calls:
        name = call.name or ""
        if name == TRANSFER_TOOL_NAME:
            continue
        rows.append(
            TraceRow(
                0,
                ts,
                author,
                "tool",
                name,
                table.tool(author, name),
                _jsonable(dict(call.args or {})),
                None,
            )
        )
    for response in responses:
        name = response.name or ""
        if name == TRANSFER_TOOL_NAME:
            continue
        rows.append(
            TraceRow(
                0,
                ts,
                author,
                "tool",
                name,
                table.tool(author, name),
                None,
                _jsonable(dict(response.response or {})),
            )
        )
    if transfer_target:
        # F-C-P2-101: 同居する他ツールの応答行（上）を出してから transfer 行（行順 tool → transfer）
        rows.append(
            TraceRow(
                0,
                ts,
                author,
                "transfer",
                transfer_target,
                table.delegate(author, transfer_target),
                {"to": transfer_target},
                None,
            )
        )
    if actions.escalate:
        # F-C-P2-005: `exit_loop` の応答 event。tool 行を消さず、その後に escalate 行を足す
        rows.append(
            TraceRow(0, ts, author, "escalate", author, table.agent_pointer(author), None, None)
        )
    return rows


class TraceSink(Protocol):
    """`TraceWriter` が JSONL を書く先。`write` しか呼ばない（開く・切り詰める・閉じるは持ち主の責務）。

    `IO[str]`（`open()` の戻り）も、CLI の `_LazyTruncateSink`（最初の行の直前に切り詰める
    duck-typed な sink）も、この Protocol に適合する（F-V-P2-104）。
    """

    def write(self, text: str, /) -> int: ...


class TraceWriter:
    """行を 1 件遅らせて出す（最後の `model` 行を `final` に付け替えるため）。

    `sink` に JSONL を書き、`on_row` に各行を渡す（stdout 表示用）。どちらも省略可。
    """

    def __init__(
        self,
        table: RuntimeTable,
        *,
        sink: TraceSink | None = None,
        on_row: Callable[[TraceRow], None] | None = None,
    ) -> None:
        self._table = table
        self._sink = sink
        self._on_row = on_row
        self._pending: TraceRow | None = None
        self._seq = 0
        self.rows: list[TraceRow] = []

    def push(self, event: Event) -> None:
        for row in classify(event, self._table):
            self._seq += 1
            row = row.with_seq(self._seq)
            if self._pending is not None:
                self._emit(self._pending)
            self._pending = row

    def close(self) -> None:
        if self._pending is not None:
            last = self._pending
            if last.kind == "model":
                last = last.with_kind("final")
            self._emit(last)
            self._pending = None

    def _emit(self, row: TraceRow) -> None:
        self.rows.append(row)
        if self._sink is not None:
            self._sink.write(json.dumps(row.to_json_dict(), ensure_ascii=False) + "\n")
        if self._on_row is not None:
            self._on_row(row)


__all__ = [
    "KINDS",
    "KIND_POINTERS",
    "TRACE_FIELDS",
    "TRANSFER_TOOL_NAME",
    "RuntimeTable",
    "TraceRow",
    "TraceSink",
    "TraceWriter",
    "classify",
]
