"""独自リクエストの params を**素の JSON のまま**受け取るための converter。

pygls 2.1.1 は、型を知らないメソッド（`jin/model` / `jin/applyOps` …）の `params` を
`namedtuple(..., rename=True)` で作った `pygls.protocol.Object` に変換する
（`pygls/protocol/__init__.py` の `_dict_to_object`・2026-09-07 実測）。

`rename=True` は **Python の識別子にできないキーを `_0` / `_1` へ黙って置き換える**。
`.jin` のモデルはまさにそういうキーを持つ:

| キー | 使えない理由 |
|---|---|
| `await`（`boundary.await`） | Python の予約語 |
| `$schema` | `$` が識別子に使えない |

つまり素の pygls のままだと、`jin/applyOps` に `{"op": "setGuard", "value": {...}}` の
ような **モデルの一部を載せたオペレーション**を送ったとき、`await` や `$schema` が
`_0` に化けて**黙って壊れる**。JSON Pointer（`/circles/0`）をキーに持つ辞書も同様である。

そこで未知メソッドの `params` は変換せず dict のまま渡す。LSP の標準メソッドは
`structure_message` が `get_message_type(method)` で型を引き当てるので、この変更の
影響を受けない（`lsprotocol` の型付き構造化がそのまま働く）。

guard: jin_converter -> converter.register_structure_hook
"""

from __future__ import annotations

from typing import Any

from cattrs import Converter
from pygls.protocol import JsonRPCNotification, JsonRPCRequestMessage, default_converter


def keep_params_plain(obj: dict[str, Any], cls: type) -> Any:
    """`params` を触らずにメッセージを組み立てる（`_params_field_structure_hook` の代わり）。"""
    return cls(**obj)


def jin_converter() -> Converter:
    """`default_converter()` から「未知メソッドの params を Object にする」フックだけ外す。

    guard: jin_converter -> converter.register_structure_hook
    """
    converter = default_converter()
    converter.register_structure_hook(JsonRPCRequestMessage, keep_params_plain)
    converter.register_structure_hook(JsonRPCNotification, keep_params_plain)
    return converter


__all__ = ["jin_converter", "keep_params_plain"]
