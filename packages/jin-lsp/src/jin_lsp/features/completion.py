"""completion（要件書 §6.2）。

出す候補は 4 種類:

1. **スキーマ由来のキー** — その位置のモデルクラス（Pydantic）が持つフィールド
2. **enum 値** — `Literal` で絞られたフィールド（`kind` / `flow.kind` / `guards[].on` …）
3. **参照名** — `tools[].circle` / `flow.steps` / `delegate` の位置で circle 名、
   `boundary.await` の位置で**同じ circle の** tool 名
4. **rune 内 `{` の後** — 可視な state key

1 と 2 は `jin_core.check.models_at` が返すクラスから引く。**キー名を書き写さない**
（モデルを変えたら追随する）。
"""

from __future__ import annotations

from typing import Any, Literal, Union, get_args, get_origin

from jin_core.check import models_at
from jin_core.pointer import parent_of, split_pointer
from lsprotocol import types
from pydantic import BaseModel

from jin_lsp import locate, positions
from jin_lsp.session import DocumentState

#: rune の中で state key を補完する引き金。`{{` は文字通りの `{` なので引き金にしない
#: （`docs/spec/model.md` §3.1 のエスケープ規則）。
RUNE_TRIGGER = "{"


def _field_names(models: list[type[BaseModel]]) -> list[str]:
    """モデルが許すキー名（JSON 側の名前 = alias 優先）。順序はモデル定義の順。"""
    names: list[str] = []
    for model in models:
        for name, info in model.model_fields.items():
            alias = info.alias or name
            if alias not in names:
                names.append(alias)
    return names


def _literal_values(annotation: Any) -> list[str]:
    """`Literal["a", "b"]`（Optional / Union に包まれていても）から値を取り出す。"""
    origin = get_origin(annotation)
    if origin is Literal:
        return [str(value) for value in get_args(annotation)]
    if origin in (Union, type(int | str)):
        found: list[str] = []
        for argument in get_args(annotation):
            found.extend(_literal_values(argument))
        return found
    return []


def _enum_values(models: list[type[BaseModel]], key: str) -> list[str]:
    values: list[str] = []
    for model in models:
        for name, info in model.model_fields.items():
            if (info.alias or name) != key:
                continue
            for value in _literal_values(info.annotation):
                if value not in values:
                    values.append(value)
    return values


def _item(label: str, kind: types.CompletionItemKind, detail: str = "") -> types.CompletionItem:
    return types.CompletionItem(label=label, kind=kind, detail=detail)


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
    model = state.model_for_display
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
    parent = parent_of(pointer) or ""
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

    # ---- 2. enum 値 ------------------------------------------------------------
    key = tokens[-1] if tokens else ""
    enum = _enum_values(_enum_models(parent, document), key)
    if enum:
        items.extend(_item(value, types.CompletionItemKind.EnumMember, key) for value in enum)
        return types.CompletionList(is_incomplete=False, items=items)

    # ---- 1. スキーマ由来のキー --------------------------------------------------
    # カーソルが値の上にあるなら、その値を持つオブジェクト（= 親）のキーを出す。
    for candidate in (pointer, parent):
        names = _field_names(models_at(candidate, document))
        if names:
            items.extend(_item(name, types.CompletionItemKind.Property, "key") for name in names)
            break
    return types.CompletionList(is_incomplete=False, items=_dedupe(items))


def _enum_models(parent: str, document: Any) -> list[type[BaseModel]]:
    """enum の候補を集めるモデル一覧。

    `tools[]` は `kind` による**判別共用体**なので、`models_at("/circles/0/tools/0")` は
    ソースに書かれている `kind` を見て 1 つに絞ってしまう（`jin_core.check._model_at`）。
    それでは「今 `"tool"` と書いてあるところに `builtin` / `summon` も置ける」という
    補完が出せない。要素の pointer が配列の添字で終わるときは、**配列そのもの**の
    pointer で引き直して候補を全部得る。
    """
    models = models_at(parent, document)
    tokens = split_pointer(parent)
    if tokens and tokens[-1].isdigit():
        container = parent_of(parent)
        if container is not None:
            for model in models_at(container, document):
                if model not in models:
                    models.append(model)
    return models


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


def _dedupe(items: list[types.CompletionItem]) -> list[types.CompletionItem]:
    """同じラベルを 2 回出さない（別の circle に同名の state key があるとき）。"""
    seen: set[str] = set()
    unique: list[types.CompletionItem] = []
    for item in items:
        if item.label not in seen:
            seen.add(item.label)
            unique.append(item)
    return unique


__all__ = ["RUNE_TRIGGER", "complete"]
