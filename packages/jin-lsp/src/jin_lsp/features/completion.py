"""completion（要件書 §6.2）。

出す候補は 4 種類:

1. **スキーマ由来のキー** — その位置のモデルクラス（Pydantic）が持つフィールド
2. **enum 値** — `Literal` で絞られたフィールド（`kind` / `flow.kind` / `guards[].on` …）
3. **参照名** — `tools[].circle` / `flow.steps` / `delegate` の位置で circle 名、
   `boundary.await` の位置で**同じ circle の** tool 名
4. **rune 内 `{` の後** — 可視な state key

1 と 2 は `jin_core.check.models_at` が返すクラスから引く（`jin_lsp.features.schema_items`）。
**キー名を書き写さない**（モデルを変えたら追随する）。

v2（`version: 2`）のドキュメントは `jin_lsp.features.v2.complete` へ振る（設計書 §8）。
キーと enum の引き方（`schema_items`）は v2 も共用する。
"""

from __future__ import annotations

from typing import Any

from jin_core.pointer import split_pointer
from lsprotocol import types

from jin_lsp import locate, positions
from jin_lsp.features import v2
from jin_lsp.features.schema_items import dedupe as _dedupe
from jin_lsp.features.schema_items import enum_then_keys
from jin_lsp.features.schema_items import item as _item
from jin_lsp.session import DocumentState

#: rune の中で state key を補完する引き金。`{{` は文字通りの `{` なので引き金にしない
#: （`docs/spec/model.md` §3.1 のエスケープ規則）。
RUNE_TRIGGER = "{"


def _circle_names(model: Any) -> list[str]:
    return [circle.name for circle in model.circles]


def _rune_prefix(lines: list[str], position: types.Position, state: DocumentState) -> bool:
    """カーソルが rune の中の `{` の直後にあるか。

    `{{` は「文字通りの `{`」なので引き金にしない。カーソル直前の 2 文字を見る。
    """
    jin_position = positions.from_lsp_position(lines, position)
    line_index = jin_position.line - 1
    if not (0 <= line_index < len(lines)):
        return False
    before = lines[line_index][: jin_position.col - 1]
    return before.endswith(RUNE_TRIGGER) and not before.endswith(RUNE_TRIGGER * 2)


def complete(state: DocumentState | None, position: types.Position) -> types.CompletionList:
    """カーソル位置に応じた候補を返す。

    壊れたテキスト（打鍵の途中は**必ず壊れている**）では `model` が無いので、
    `last_good` の**素の JSON 値**ではなくモデルから参照名を出す。キーと enum は
    現在のテキストの pointer から引きたいが、それも壊れていれば得られない。
    どちらも得られないときは**空の候補**を返す（何も出さないほうが、
    間違った候補を出して LLM に書かせるより良い）。
    """
    if state is None:
        return types.CompletionList(is_incomplete=False, items=[])
    if state.model_v2_for_display is not None:
        return v2.complete(state, position)
    model = state.model_v1_for_display
    table = state.table_for_display
    if model is None or table is None:
        return types.CompletionList(is_incomplete=False, items=[])

    lines = state.lines_for_display
    items: list[types.CompletionItem] = []

    # ---- 4. rune 内 `{` の後 → state key ---------------------------------------
    if _rune_prefix(lines, position, state):
        for circle in model.circles:
            items.extend(
                _item(member.name, types.CompletionItemKind.Variable, f"state / {circle.name}")
                for member in circle.state
            )
        return types.CompletionList(is_incomplete=False, items=_dedupe(items))

    jin_position = positions.from_lsp_position(lines, position)
    pointer = locate.pointer_at(table, jin_position)
    if pointer is None:
        return types.CompletionList(is_incomplete=False, items=[])

    tokens = split_pointer(pointer)
    document = model.model_dump(by_alias=True, mode="json")

    # ---- 3. 参照名 -------------------------------------------------------------
    if _is_circle_reference(tokens):
        items.extend(
            _item(name, types.CompletionItemKind.Class, "circle") for name in _circle_names(model)
        )
    elif _is_await_reference(tokens):
        owner = int(tokens[1])
        if owner < len(model.circles):
            items.extend(
                _item(tool.name, types.CompletionItemKind.Method, f"tool / kind: {tool.kind}")
                for tool in model.circles[owner].tools
            )
    if items:
        return types.CompletionList(is_incomplete=False, items=_dedupe(items))

    # ---- 2. enum 値 → 1. スキーマ由来のキー（`schema_items.enum_then_keys`）------------
    return types.CompletionList(is_incomplete=False, items=enum_then_keys(pointer, document))


def _is_circle_reference(tokens: list[str]) -> bool:
    """circle 名を書く位置か（`root` / `delegate[]` / `flow.steps[]` / `tools[].circle`）。"""
    if tokens == ["root"]:
        return True
    if tokens[:1] != ["circles"] or len(tokens) < 3:
        return False
    rest = tokens[2:]
    if rest[0] == "delegate":
        return True
    if rest[:2] == ["flow", "steps"]:
        return True
    return len(rest) == 3 and rest[0] == "tools" and rest[2] == "circle"


def _is_await_reference(tokens: list[str]) -> bool:
    """tool 名を書く位置か（`boundary.await[]`）。"""
    return (
        tokens[:1] == ["circles"]
        and len(tokens) >= 4
        and tokens[1].isdigit()
        and tokens[2:4] == ["boundary", "await"]
    )


__all__ = ["RUNE_TRIGGER", "complete"]
