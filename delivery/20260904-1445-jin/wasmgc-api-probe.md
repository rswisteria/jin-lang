# wasm-GC 実測 probe（Issue #53・`jin build --target wasm-gc`）

計測日: 2026-09-15。作業ディレクトリ `/home/wisteria/.claude/jobs/3ab877a1/tmp/gc`（git リポジトリの外）。
Python 3.14.7 / uv 0.12.10（`uv run --with wasmtime python <script>`）、Node v22.16.0（V8 12.4.254.21）、
Playwright 1.62.0 の chromium-1234（`~/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome --version`）。
すべての値はこのディレクトリのスクリプト（`probe.py` / `probe2.py` / `probe3.py` / `probe2.mjs`）を実行して得た生出力から転記した。推測値は無い。

目的は設計書 §4.1 の表の「直接 wasm-GC 出力」行に残っていた **△ wasmtime（GC 対応の確認要）** を実測で埋め、
jil.md §6 を「含み」から仕様に書き換えるための事実を固定すること。

## 計測値一覧

| 項目 | 実測 |
|---|---|
| wasmtime（PyPI）の版 | `wasmtime 48.0.0`（`importlib.metadata.version("wasmtime")`。`wasmtime.__version__` は**無い**） |
| wheel の形とサイズ | `py3-none-manylinux1_x86_64`（純 Python の束 + `_wasmtime.so`）。展開後 **31 MB**（`du -sh` の uv キャッシュ） |
| WAT → wasm | **`wasmtime.wat2wasm(str) -> bytes`** が wasm-GC の構文（`struct` / `array` / `ref` / `array.new_default` / `struct.get` / `br_table`）をそのまま通す。外部の実行ファイルは要らない |
| 決定性 | 同じ WAT を別プロセスで 2 回 assemble して sha256 が一致（`dacac344…` / `dacac344…`） |
| GC の有効化 | **既定の `wasmtime.Config()` で instantiate と実行が通る。** `Config` に `wasm_gc` / `wasm_function_references` / `wasm_reference_types` という属性は**無い**（`hasattr` すべて False。GC は既定で有効） |
| 文字列の入り（ホスト → wasm） | ホストが線形メモリに UTF-8 を `Memory.write(store, bytes, ptr)` で置き、`boot(ptr, len)` が読む。非 ASCII（`あいう😀`）を含む 58 バイトが同じ長さで届く |
| 文字列の出（wasm → ホスト） | `tick` が線形メモリに JSON を書いて長さを返し、ホストが `Memory.read(store, 0, n)` で読む。`{"pc":1}` が届く |
| 往復コスト | `tick` 呼び出し + `read`（8 バイト）で **14 µs/回**（1 万回平均。lupa の table 変換 35 µs、Wasmoon の JSON 文字列 35.5 µs より速い） |
| 状態機械の再開 | `struct` に持った `pc` を `br_table` で選ぶ最小形が動く（`tick` 0 → `pc` 1、1 → 2、以後 2 のまま）。`wait` の変換の足場 |
| fuel（命令数の上限に相当） | `Config().consume_fuel = True` + `Store.set_fuel(1000)` で `boot` が 15、`tick` が 45 消費（`get_fuel` 985 → 940）。**wasmtime だけの機能でブラウザには無い**ので上限には使わない（下の判断） |
| Node（V8 12.4）で同じ binary | `WebAssembly.instantiate` で同じ `probe2.wasm` が instantiate され、`boot` / `tick` が同じ値を返す |
| Chromium の版 | Playwright 1.62.0 の chromium-1234 = **Google Chrome for Testing 151.0.7922.34**（wasm-GC は Chrome 119 で出荷済み。設計書 §0） |

## A. wasmtime（Python）

### A.1 版と GC の既定

```
$ uv run --with wasmtime python probe.py probe.wasm
wasmtime version: {}                      # __version__ は無い（vars に version を含む名前が無い）
wat2wasm ok, bytes: 261
wasm_gc False
wasm_function_references False
wasm_reference_types False
boot(7) -> 7.0
tick(3) -> 7 {"t":3}
```

`probe.py` の WAT は `(type $vec (struct (field $x (mut f64)) (field $y (mut f64))))` と `(type $arr (array (mut i32)))` を持ち、
`boot` が `struct.new` / `struct.get`、`tick` が `array.new_default` / `array.set` / `array.get` を使う。
`Config` に GC 関連の属性が無く、それでも通るので **GC は既定で有効**と判断した。

版は `importlib.metadata.version("wasmtime")` で `48.0.0`（`probe2.py` の 1 行目）。

### A.2 文字列の入りと出・状態機械・往復コスト

```
$ uv run --with wasmtime python probe2.py
wasmtime 48.0.0
bytes 425 sha256 8961a09013a4ebe8
boot -> 58 expected 58
tick 0 -> {"pc":1}
tick 1 -> {"pc":2}
tick 2 -> {"pc":2}
budget 2
tick+read µs/回 14.05
```

`probe2.py` の WAT: `(type $str (array (mut i8)))` と `(type $frame (struct (field $pc (mut i32)) (field $x (mut f64))))`。
`boot(ptr, len)` は線形メモリの `[ptr, ptr+len)` を `array i8` に写して `array.len` を返す。`tick` はグローバルに持った
`$frame` の `pc` を `br_table` で分岐し、進むたびに `$budget` を 1 足す（戻り辺ごとに数えるカウンタの最小形）。

### A.3 fuel

```
$ uv run --with wasmtime python probe3.py
fuel after boot 985
fuel after tick 940
```

`consume_fuel` は wasmtime のエンジン側の機能で、ブラウザの `WebAssembly` には対応物が無い。両ホストで同じ tick に
同じ `error` 行を出すには module の中で数えるしかないので、命令数の上限は **生成部が戻り辺と呼び出しに埋めるカウンタ**で
掛ける（jil.md §6.6）。fuel はヘッドレスの保険（生成系のバグで module が止まらないとき）にだけ使える。

### A.4 決定性

```
$ for i in 1 2; do uv run --with wasmtime python -c "...wat2wasm(WAT)... sha256"; done
dacac3440f4a61cd3966dcfffd81e1e72493cb5e78aff3dcde8edbd591d7d741
dacac3440f4a61cd3966dcfffd81e1e72493cb5e78aff3dcde8edbd591d7d741
```

## B. Node / Chromium

### B.1 同じ binary が V8 で走る

```
$ node probe2.mjs
boot -> 33 expected 33
tick 0 {"pc":1}
tick 1 {"pc":2}
tick 2 {"pc":2}
node v22.16.0 v8 12.4.254.21-node.26
```

`WebAssembly.instantiate(bytes, {})` に import は 1 つも要らない（module はホストを呼ばない。設計書 §4.3 のまま）。
文字列は `TextEncoder` で `Uint8Array` に直して `memory.buffer` へ `set` し、結果は `TextDecoder` で読む。

### B.2 Chromium の版

```
$ ~/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome --version
Google Chrome for Testing 151.0.7922.34
```

（`pnpm e2e` が使う版。wasm-GC は Chrome 119 で出荷済みなので Playwright の e2e は追加の設定なしに wasm-GC を走らせられる。
実ブラウザでの instantiate は Sub-Issue D の e2e が見る）

## C. 判断（jil.md §6 に書いた根拠）

1. **WAT を出して `wasmtime.wat2wasm` で束ねる**（A.1 / A.4）。自前の binary writer を書かず、`wasm-tools` のような外部の実行ファイルも足さない。
   Lua 生成系と同じ「テキストを出す生成系」になるので、スナップショットと契約テストの手口をそのまま使える
2. **入りも出も UTF-8 の JSON 1 本を線形メモリで越える**（A.2 / B.1）。wasm-GC の `array` / `struct` はホストから読めない。
   `manifest.resume`（任意の JSON）と `manifest.storage` を受けるには汎用の JSON の読み手が module に要るので、`seed` / `t` / `inputs` も
   同じ読み手で読む方が経路が 1 本になる。往復 14 µs は Lua 経路より速い
3. **ヘッドレスは wasmtime で走らせる**（A.1）。既定の `Config()` で足りる。wheel は 31 MB あるので、`jin_lsp` が import する
   `jin_wasm` の必須依存には**足さず**、新しい兄弟パッケージ `jin-wasmgc` に置く
4. **命令数の上限は module の中のカウンタ**（A.3）。fuel はブラウザに無い
