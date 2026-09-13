"""jin-wasm: Jin v2 の実行系（設計書 §4 / docs/spec/v2/runtime.md / jil.md）。

- `jin_wasm.codegen` — `JinFileV2` → JIL（`game.lua` の生成部）と `game.manifest.json`
- `jin_wasm.prelude` — `prelude.lua`（表示リスト / 入力 / PCG32 / スケジューラ / トレース / JSON）を読む
- `jin_wasm.jil` — JIL の契約（版・禁止語・トレース kind）と禁止語の走査
- `jin_wasm.runtime` — lupa（`lupa.lua54`）でのヘッドレス実行（`jin run`）
- `jin_wasm.jinrec` — 入力ログ / 録画（`.jinrec`）の読み書き
- `jin_wasm.bundle` — `jin build` のバンドル書き出し

依存は `jin_core` と `lupa` だけ。`jin_adk` / `jin_render` は兄弟であり import しない
（import-linter の layers 契約）。ホストが Lua を呼ぶ関数は `boot` / `tick` の 2 つだけで、
Lua はホストを呼ばない（runtime.md §1）。JIL には `require` も `load` も無く、
v1 の `jin run` が持つ「`ref` の import = 任意コード実行」の危険性は v2 には無い。
"""

from jin_wasm.jil import JIL_FORBIDDEN, JIL_VERSION, TRACE_KINDS

__all__ = ["JIL_FORBIDDEN", "JIL_VERSION", "TRACE_KINDS"]
