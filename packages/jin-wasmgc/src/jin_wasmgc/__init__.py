"""jin-wasmgc: Jin v2 の第 2 の生成系（wasm-GC を直接出す。docs/spec/v2/jil.md §6・設計書 §11 #56）。

- `jin_wasmgc.codegen` — `JinFileV2` → WAT の生成部（`jin_wasm.program` の解析を再利用する）
- `jin_wasmgc.assemble` — ランタイム部（`runtime.wat`）+ 生成部を `wasmtime.wat2wasm` で束ねる
- `jin_wasmgc.runtime` — wasmtime でのヘッドレス実行（`jin run --target wasm-gc`）

依存は `jin_core` / `jin_wasm` / `wasmtime` だけ。`jin_lsp` とは兄弟であり互いに import しない
（import-linter の layers 契約）。ホストが呼ぶ export は `input(n)` / `boot(n)` / `tick(n)` の 3 つで、
引数も戻りも UTF-8 の JSON 1 本を線形メモリで越える（jil.md §6.2）。module は import を持たず
ホストを呼ばない。`jin run --target wasm-gc` が任意コードを実行しないのは Lua 経路と同じ
（`agent` の sigil があれば `jin_cli` が v1 の陣を走らせる。runtime.md §11）。

Sub-Issue A（#73）の範囲: `num` / `bool` の式・`let` / `set` / `if` / `loop` / `break` / `return` /
`finish` / 自陣の手順への `cast`・`out` の state・release ビルド。文字列 / list / 型紙 / 純関数 /
ホスト能力 / 命令数の上限は #74、`wait` / `emit` / `transfer` / flow / `on` / guard / debug は #75、
プレイヤー側は #76。
"""

#: wasmtime（PyPI）の版。probe（`wasmgc-api-probe.md`）で実測した版に固定し、入っている版と違えば
#: `tests/contract/test_wasmgc_version_contract.py` が赤くなる（`jin_adk.TARGET_ADK_VERSION` と同じ規律）。
TARGET_WASMTIME_VERSION = "48.0.0"

__all__ = ["TARGET_WASMTIME_VERSION"]
