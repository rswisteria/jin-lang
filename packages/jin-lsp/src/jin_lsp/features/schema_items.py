"""completion のうち **Pydantic のモデル定義から引く**部分（キー名 / enum 値）。

v1（`jin_lsp.features.completion`）と v2（`jin_lsp.features.v2`）が共用する。
`jin_core.check.models_at` は `version` で v1 / v2 のクラスを振り分けるので、ここは版を知らない。
**キー名を書き写さない**（モデルを変えたら追随する）。
"""

from __future__ import annotations

from typing import Any, Literal, Union, get_args, get_origin

from jin_core.check import models_at
from jin_core.pointer import parent_of, split_pointer
from lsprotocol import types
from pydantic import BaseModel


def field_names(models: list[type[BaseModel]]) -> list[str]:
    """モデルが許すキー名（JSON 側の名前 = alias 優先）。順序はモデル定義の順。"""
    names: list[str] = []
    for model in models:
        for name, info in model.model_fields.items():
            alias = info.alias or name
            if alias not in names:
                names.append(alias)
    return names


def literal_values(annotation: Any) -> list[str]:
    """`Literal["a", "b"]`（Optional / Union に包まれていても）から値を取り出す。"""
    origin = get_origin(annotation)
    if origin is Literal:
        return [str(value) for value in get_args(annotation)]
    if origin in (Union, type(int | str)):
        found: list[str] = []
        for argument in get_args(annotation):
            found.extend(literal_values(argument))
        return found
    return []


def enum_values(models: list[type[BaseModel]], key: str) -> list[str]:
    values: list[str] = []
    for model in models:
        for name, info in model.model_fields.items():
            if (info.alias or name) != key:
                continue
            for value in literal_values(info.annotation):
                if value not in values:
                    values.append(value)
    return values


def enum_models(parent: str, document: Any) -> list[type[BaseModel]]:
    """enum の候補を集めるモデル一覧。

    `tools[]`（v1）/ ステップ（v2 の `do`）は**判別共用体**なので、`models_at` は
    ソースに書かれているタグを見て 1 つに絞ってしまう（`jin_core.check._model_at`）。
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


def item(label: str, kind: types.CompletionItemKind, detail: str = "") -> types.CompletionItem:
    return types.CompletionItem(label=label, kind=kind, detail=detail)


def dedupe(items: list[types.CompletionItem]) -> list[types.CompletionItem]:
    """同じラベルを 2 回出さない（別の circle に同名の state key があるとき）。"""
    seen: set[str] = set()
    unique: list[types.CompletionItem] = []
    for entry in items:
        if entry.label not in seen:
            seen.add(entry.label)
            unique.append(entry)
    return unique


def enum_then_keys(pointer: str, document: Any) -> list[types.CompletionItem]:
    """pointer の位置で出せる enum 値、無ければキー名（v1 / v2 共通の末尾）。"""
    tokens = split_pointer(pointer)
    parent = parent_of(pointer) or ""
    key = tokens[-1] if tokens else ""
    enum = enum_values(enum_models(parent, document), key)
    if enum:
        return [item(value, types.CompletionItemKind.EnumMember, key) for value in enum]
    # カーソルが値の上にあるなら、その値を持つオブジェクト（= 親）のキーを出す。
    for candidate in (pointer, parent):
        names = field_names(models_at(candidate, document))
        if names:
            return dedupe([item(name, types.CompletionItemKind.Property, "key") for name in names])
    return []


__all__ = [
    "dedupe",
    "enum_models",
    "enum_then_keys",
    "enum_values",
    "field_names",
    "item",
    "literal_values",
]
