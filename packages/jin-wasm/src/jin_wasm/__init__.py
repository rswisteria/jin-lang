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
v1 の `jin run` が持つ「`ref` の import = 任意コード実行」の危険性は、`agent` の sigil を持たない
v2 には無い（`agent`・runtime.md §11 は `jin_cli` が v1 の陣を走らせる。`jin_wasm` は問いを tick 結果の
`asks` で出し、答える呼び出し可能を `run_headless(answer=...)` で受けるだけで、v1 を知らない）。
"""

from jin_wasm.jil import JIL_FORBIDDEN, JIL_VERSION, TRACE_KINDS

__all__ = ["JIL_FORBIDDEN", "JIL_VERSION", "TRACE_KINDS"]
