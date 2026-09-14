"""ランタイム部（`runtime.wat`）+ 生成部を 1 つの module にして `wasmtime.wat2wasm` で束ねる（jil.md §6.1）。

`game.wasm` = ヘッダ（コメント 3 行）+ `(module` + ランタイム部 + 生成部 + `)` を assemble したもの。
自前の binary writer は書かず、外部の実行ファイル（`wasm-tools`）にも依存しない。同じ WAT は
同じバイト列になる（`wasmgc-api-probe.md` A.4）。manifest は Lua 経路と共通部（`jin_wasm.program.manifest_base`）
を共有し、`target: "wasm-gc"` と `wasm`（sha256）を後ろに足す（`jil` は無い）。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jin_core.v2.model import JinFileV2
from jin_wasm.program import manifest_base
from wasmtime import wat2wasm

from jin_wasmgc.codegen import generate_program, header

RUNTIME_WAT = Path(__file__).with_name("runtime.wat")

#: `game.manifest.json` の `target` の値（runtime.md §9 / jil.md §6.8。無ければ `"lua"`）。
TARGET = "wasm-gc"

#: バンドルの本体ファイル名（`game.lua` の代わり。jil.md §6.8）。
GAME_WASM = "game.wasm"


@dataclass(frozen=True, slots=True)
class GeneratedWasm:
    """`jin build --target wasm-gc` / `jin run --target wasm-gc` が受け取る生成物。"""

    wat: str
    wasm: bytes
    manifest: dict[str, Any]
    debug: bool


def runtime_source() -> str:
    """`runtime.wat`（ランタイム部）の本文。"""
    return RUNTIME_WAT.read_text(encoding="utf-8")


def module_text(program: str, *, source_name: str | None) -> str:
    """ヘッダ + `(module` + ランタイム部 + 生成部 + `)`。"""
    return (
        header(source_name)
        + "(module\n"
        + runtime_source()
        + "\n  ;; ---------------------------------------------------------------- program\n"
        + program
        + ")\n"
    )


def assemble(
    model: JinFileV2, *, source_name: str | None = None, debug: bool = False
) -> GeneratedWasm:
    """`game.wasm` と `game.manifest.json` を作る。診断に error があれば `CodegenError`。"""
    program = generate_program(model, debug=debug)
    wat = module_text(program, source_name=source_name)
    wasm = bytes(wat2wasm(wat))  # wat2wasm は bytearray を返す
    manifest = manifest_base(model, source_name=source_name, debug=debug)
    manifest["target"] = TARGET
    manifest["wasm"] = hashlib.sha256(wasm).hexdigest()
    return GeneratedWasm(wat=wat, wasm=wasm, manifest=manifest, debug=debug)


__all__ = [
    "GAME_WASM",
    "RUNTIME_WAT",
    "TARGET",
    "GeneratedWasm",
    "assemble",
    "module_text",
    "runtime_source",
]
