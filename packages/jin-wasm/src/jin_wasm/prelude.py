"""`prelude.lua` を読む（jil.md §1 の `<prelude>`）。

`importlib.resources` は使わない（`tests/contract/test_packaging_contract.py` の動的 import 走査が
`importlib.metadata` 以外の `importlib` を落とす）。パッケージディレクトリの中の同名ファイルを
`Path(__file__)` から読む。wheel に入ることは `uv build --wheel packages/jin-wasm` で実測した
（`jin_wasm/prelude.lua` が一覧に出る）。
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

PRELUDE_PATH = Path(__file__).with_name("prelude.lua")


@cache
def prelude_source() -> str:
    """`prelude.lua` の全文（末尾は改行 1 つ）。"""
    text = PRELUDE_PATH.read_text(encoding="utf-8")
    return text if text.endswith("\n") else text + "\n"


__all__ = ["PRELUDE_PATH", "prelude_source"]
