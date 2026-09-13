"""jin-wasm のテスト用ヘルパ。プレリュードの局所関数を、チャンクの末尾で返して Python から触る。"""

from __future__ import annotations

from typing import Any

import pytest
from jin_wasm.prelude import prelude_source
from jin_wasm.runtime import sandboxed_runtime

#: プレリュードの局所のうち、単体テストで直接叩くもの。
EXPOSED = (
    "NUMSTR",
    "JS",
    "JN",
    "JV",
    "JL",
    "rng_step",
    "rng_seed",
    "H",
    "F",
    "E",
    "AT",
    "SETAT",
    "prepare_inputs",
)


def prelude_internals() -> Any:
    """プレリュード + `return { NUMSTR = NUMSTR, … }` を読んだ Lua テーブル。"""
    runtime = sandboxed_runtime()
    tail = "return { " + ", ".join(f"{n} = {n}" for n in EXPOSED) + " }\n"
    return runtime.execute(prelude_source() + tail), runtime


@pytest.fixture(scope="module")
def prelude_and_runtime() -> tuple[Any, Any]:
    return prelude_internals()


@pytest.fixture(scope="module")
def prelude(prelude_and_runtime: tuple[Any, Any]) -> Any:
    """`prelude_and_runtime` と同じランタイム（別々に作ると Lua の値を混ぜられない）。"""
    return prelude_and_runtime[0]


def program(body: str) -> str:
    """手書きの生成部を足した JIL（jil.md §1 の 3 部構成）。"""
    return prelude_source() + "\n-- program\n" + body + "\nreturn { boot = boot, tick = tick }\n"
