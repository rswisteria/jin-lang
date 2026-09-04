"""トレース JSONL（要件書 §3.4）。

スキーマ: `{ "seq", "ts", "agent", "kind": "model|tool|transfer|escalate|final",
"name", "pointer", "input", "output" }`。

**ADK の `Event` をそのまま書くのではない**（`adk-api-probe.md` / `docs/spec/adk-mapping.md` §2.4）。
実測どおり `Event` は pointer を持たず、フィールド名も一致しない。ここで作るのは
**Jin 側の派生スキーマ**であり、`agent` は `Event.author`、`ts` は `Event.timestamp` から取る。

`pointer` は ADR-009 の対応表（`PointerMap`）を引いて埋める。レンダラの `data-jin` と
同じ鍵なので、**必ずモデルに解決できる pointer** でなければならない
（`tests/test_trace.py` が examples 2 本の全行について実際に解決して確かめる）。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from jin_adk.pointers import PointerMap

#: 要件書 §3.4 の `kind`。この 5 つ以外を出さない。
TraceKind = Literal["model", "tool", "transfer", "escalate", "final"]

#: トレース 1 行のキー（順序も含めて固定する）。要件書 §3.4 の並びそのもの。
TRACE_KEYS: tuple[str, ...] = (
    "seq",
    "ts",
    "agent",
    "kind",
    "name",
    "pointer",
    "input",
    "output",
)

#: `kind` の許容値（`TraceKind` の実行時版。テストが両者の一致を固定する）。
TRACE_KINDS: tuple[str, ...] = ("model", "tool", "transfer", "escalate", "final")


@dataclass(frozen=True, slots=True)
class TraceEvent:
    """トレース 1 行。"""

    seq: int
    ts: str
    agent: str
    kind: TraceKind
    name: str
    pointer: str
    input: Any = None
    output: Any = None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "ts": self.ts,
            "agent": self.agent,
            "kind": self.kind,
            "name": self.name,
            "pointer": self.pointer,
            "input": self.input,
            "output": self.output,
        }

    def to_jsonl(self) -> str:
        return json.dumps(self.to_json_dict(), ensure_ascii=False)


def format_timestamp(timestamp: float | None) -> str:
    """`Event.timestamp`（epoch 秒・実測）を ISO 8601 の UTC 文字列にする。

    生の float のままだと人が読めず、タイムゾーンの解釈も残る。UTC に固定して
    「どの時計で測ったか」を文字列自身に持たせる。`None` は ADK が値を入れ損ねた
    ときにだけ起きる。捏造せず、その時刻を持たないことが分かる空文字にする。
    """
    if timestamp is None:
        return ""
    return datetime.fromtimestamp(timestamp, UTC).isoformat()


def _jsonable(value: Any) -> Any:
    """トレースに載せられる素の JSON 値へ落とす。

    ADK の値には Pydantic モデルや `bytes` が混ざる。`json.dumps` が落ちると
    **トレースが 1 行も残らない**ので、落とせないものは型名の文字列に落とす。
    黙って捨てず、「何かがあったが JSON にできなかった」ことは残す。
    """
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            return _jsonable(dump(mode="json", exclude_none=True))
        except Exception as exc:  # noqa: BLE001 - ADK 側の実装に依存するため型を絞れない
            # 何が落ちたかはトレース行に残す。握り潰すと「値が無い」と区別が付かない。
            return f"<{type(value).__name__}: model_dump 失敗 {type(exc).__name__}>"
    return f"<{type(value).__name__}>"


class TraceBuilder:
    """ADK の `Event` 列を §3.4 の派生スキーマへ写す。

    1 つの `Event` が複数行になることがある（function_call と function_response、
    テキストと transfer が同じイベントに載る）。**取りこぼさず、順序を保つ。**
    """

    def __init__(self, pointer_map: PointerMap, model_of: dict[str, str] | None = None) -> None:
        self.pointers = pointer_map
        #: エージェント名 → `core`（モデル ID）。`kind: model` の `name` に使う。
        self.model_of = model_of or {}
        self._seq = 0

    def _next(self) -> int:
        self._seq += 1
        return self._seq

    def _agent_pointer(self, agent: str) -> str:
        return self.pointers.agents.get(agent, "")

    def events_from(self, event: Any) -> Iterator[TraceEvent]:
        author = getattr(event, "author", "") or ""
        ts = format_timestamp(getattr(event, "timestamp", None))
        actions = getattr(event, "actions", None)

        content = getattr(event, "content", None)
        parts = list(getattr(content, "parts", None) or []) if content is not None else []

        texts: list[str] = []
        for part in parts:
            call = getattr(part, "function_call", None)
            if call is not None:
                name = getattr(call, "name", "") or ""
                yield TraceEvent(
                    seq=self._next(),
                    ts=ts,
                    agent=author,
                    kind="tool",
                    name=name,
                    pointer=self.pointers.tools.get(author, {}).get(
                        name, self._agent_pointer(author)
                    ),
                    input=_jsonable(getattr(call, "args", None)),
                )
                continue
            response = getattr(part, "function_response", None)
            if response is not None:
                name = getattr(response, "name", "") or ""
                yield TraceEvent(
                    seq=self._next(),
                    ts=ts,
                    agent=author,
                    kind="tool",
                    name=name,
                    pointer=self.pointers.tools.get(author, {}).get(
                        name, self._agent_pointer(author)
                    ),
                    output=_jsonable(getattr(response, "response", None)),
                )
                continue
            text = getattr(part, "text", None)
            if text:
                texts.append(text)

        if texts:
            yield TraceEvent(
                seq=self._next(),
                ts=ts,
                agent=author,
                kind="model",
                name=self.model_of.get(author, ""),
                # `core` の pointer があればそちらを指す（発火したのはモデルなので）。
                pointer=self.pointers.cores.get(author, self._agent_pointer(author)),
                output="".join(texts),
            )

        transfer = getattr(actions, "transfer_to_agent", None) if actions is not None else None
        if transfer:
            yield TraceEvent(
                seq=self._next(),
                ts=ts,
                agent=author,
                kind="transfer",
                name=transfer,
                pointer=self.pointers.delegates.get(author, {}).get(
                    transfer, self._agent_pointer(transfer)
                ),
            )

        if actions is not None and getattr(actions, "escalate", None):
            yield TraceEvent(
                seq=self._next(),
                ts=ts,
                agent=author,
                kind="escalate",
                name=author,
                pointer=self.pointers.exits.get(author, self._agent_pointer(author)),
            )

        is_final = getattr(event, "is_final_response", None)
        if callable(is_final) and is_final() and texts:
            yield TraceEvent(
                seq=self._next(),
                ts=ts,
                agent=author,
                kind="final",
                name=author,
                pointer=self._agent_pointer(author),
                output="".join(texts),
            )


def write_jsonl(path: Any, events: list[TraceEvent]) -> None:
    """1 行 1 JSON で書く（要件書 §3.4）。改行は LF 固定。"""
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.writelines(event.to_jsonl() + "\n" for event in events)


__all__ = [
    "TRACE_KEYS",
    "TRACE_KINDS",
    "TraceBuilder",
    "TraceEvent",
    "TraceKind",
    "format_timestamp",
    "write_jsonl",
]
