# CLAUDE.md — jin-lang

Jin(陣) は Google ADK 上の LLM エージェントを魔法陣として記述・編集・実行・デバッグするための言語処理系である。

## 正典（ここに書いてあることが優先する）

| 正典 | 内容 |
|---|---|
| `jin-requirements.md` | 上位要件書。`docs/superpowers/specs/2026-09-04-jin-overview.md` は同一内容の写し（テストで一致を担保） |
| `schemas/jin.schema.json` | `.jin` の JSON Schema。**Pydantic 定義から生成する。手で編集しない** |
| `docs/spec/model.md` | モデル仕様（意味論とキー） |
| `docs/spec/adk-mapping.md` | Jin 要素 → ADK クラスの対応 |
| `docs/spec/layout.md` | 決定的レイアウトと `data-jin` 契約 |
| `docs/spec/diagnostics.md` | 診断コード一覧（JINxxx） |
| `docs/spec/ops.md` | 意味編集オペレーション一覧 |

意味モデルの**唯一の真実**は `packages/jin-core/src/jin_core/model.py` の Pydantic 定義である。
モデルを変えたら `uv run python scripts/generate_schema.py` を実行して `schemas/jin.schema.json` をコミットする
（CI がドリフトを検出する）。

## パッケージ境界（依存は一方向）

```
jin-core  ←  jin-adk | jin-render  ←  jin-lsp  ←  jin-cli            # v1
jin-core  ←  jin-adk | jin-render | jin-wasm  ←  jin-lsp  ←  jin-cli # Jin v2 Phase 2 以降（設計書 §1.2 / §11 #21）
jin-core  ←  jin-adk | jin-render | jin-wasm  ←  jin-lsp | jin-wasmgc  ←  jin-cli   # v2.1 Issue #53 以降（jil.md §6.1 / 設計書 §11 #56）
```

（`jin-adk` と `jin-render` は**兄弟**であり互いに依存しない。import-linter の layers 契約では
1 要素に `"jin_adk | jin_render"` と `|` 区切りで書く。別要素に並べると片方向だけを禁じる、
実際より強い順序を宣言してしまう）

Phase 4 時点で 5 パッケージすべてが実在し（`jin-core` / `jin-adk` / `jin-render` / `jin-lsp` / `jin-cli`）、
Jin v2 の Phase 2 で 6 つ目の `jin-wasm`（`jin-core` と `lupa` だけに依存する 3 つ目の兄弟）が加わった。
v2.1（Issue #53 / #73）で 7 つ目の **`jin-wasmgc`**（wasm-GC を直接出す第 2 の生成系。`jin-core` / `jin-wasm` /
`wasmtime` に依存し、`jin-lsp` の**兄弟**。layers では `"jin_lsp | jin_wasmgc"`）が加わった。**`wasmtime`
（wheel 31 MB）を `jin-wasm` の必須依存に足さない**（`jin-lsp` が `jin_wasm.codegen` を import しているので
LSP のインストールに乗る）。`jin_wasmgc` を import するのは `jin_cli` だけ。
`jin-adk` は ADK の語彙（LlmAgent / Runner / BaseLlm …）がリポジトリ内で現れてよい唯一のパッケージ。

- `jin-core` は他の `jin-*` に依存しない（最下層）
- **`jin-core` / `jin-render` は `google-adk` に依存しない。** ADK の語彙は `jin-adk` 側にだけ現れる
- **`jin-render` は `jin-core` と標準ライブラリだけに依存する。** `jin-adk` は**兄弟**であり
  import すると layers 契約が BROKEN になる（トレースの型を `jin_adk.trace` から取らない。
  overlay に要るのは `seq` と `pointer` だけなので `jin_render.overlay` に最小の読み取り型を置く）
- **`jin-lsp` は `jin-core` と `jin-render` に依存し、`jin-adk` には依存しない。** hover の ADK クラス名は
  `docs/spec/adk-mapping.md` 由来の静的な辞書（`jin_lsp.adk_names`）から引く。`jin-adk` を入れると
  LSP の起動のたびに `google-adk` 全体の import を待つことになる（Claude Code の起動体感に直撃する）
- **`apps/editor` は LSP プロトコルにのみ依存し、Python パッケージを直接 import しない。**
  例外は `schemas/` の生成物 3 つ（`jin.schema.json` / Phase 5 からの `jin-v2.schema.json` /
  `abilities.json`。プロパティパネルのフォームを手書きしないために読む。コピーを置かず直接読む）。
  Python 側は import-linter、**TS 側は eslint の
  `no-restricted-imports`**（`apps/editor/eslint.config.js`）が落とす。
  **通信路の例外が 1 本ある**: 実行（Issue #34）だけは LSP を通らず、`jin editor` が配る
  静的サーバと**同一オリジンの `POST /run`**（SSE）へ投げる。ws には same-origin 制限が無く
  防御がトークン一致だけになるのに対し、HTTP ならカスタムヘッダが CORS の preflight を
  強制するためで（`docs/spec/ops.md` §5.2）、`jin/…` は 6 種のまま増えない。
  import の禁止はこれで変わらない。
  規則が**実際に落ちる**ことは `apps/editor/test/dependencyDirection.test.ts` が
  禁止 import を食わせて確かめる
- **`apps/stage`（鑑賞ページ）は Python パッケージもリポジトリのファイルも読まない**（`schemas/` の例外も無い）。
  SVG・名前の表・トレースはエディタから postMessage（`stage.scene` / `stage.trace`）で受け取る。
  **three と mediabunny はここにだけある**（エディタとプレイヤーに入れない・`tests/contract/test_stage_contract.py`）。
  禁止は eslint の `no-restricted-imports`（`apps/stage/eslint.config.js`）で、落ちることは
  `apps/stage/test/dependencyDirection.test.ts` が確かめる

この一方向性は **import-linter** で機械的に落とす（`pyproject.toml` の `[tool.importlinter]`）。
`uv run lint-imports` がローカルでも CI でも走る。契約の正本は
`delivery/20260904-1445-jin/design.yaml` の `architecture.dependency_direction.rules`（8 行）。

`ref` を実際に import する実装（`ImportResolver`）は **`jin_cli` にだけ置く**。`jin_core` は
`RefResolver` プロトコルしか知らない。`jin run` の import 実装は `jin_adk.runtime` にだけ置く。
どちらも import-linter の forbidden contract「任意コード実行の実装は `jin_cli.resolver` と `jin_adk.runtime` に閉じる」
で落とす（下の「`--resolve` と `jin run` の危険性」を参照）。
動的 import（`importlib` / `__import__` / `exec` / `eval` / `runpy`）を使うモジュールは `jin_cli/resolver.py` と
`jin_adk/runtime.py`（`jin run`）の 2 つだけで、`tests/contract/test_packaging_contract.py`
（`test_dynamic_imports_are_confined_to_the_cli_resolver_and_jin_run`）が厳密一致で固定する。
**例外は `importlib.metadata` ただ 1 つ**（Issue #36）。読むのは `.dist-info` の METADATA ファイルで
モジュールを import しないので、走査の `INERT_IMPORTLIB_SUBMODULES` で除いてある
（`jin --version` が版をここから引く）。**`importlib.util` / `importlib.machinery` をここに足さない。**
緩和が広がっていないことは `test_the_scan_still_catches_real_dynamic_imports` が固定する。

### パッケージを足すときのチェックリスト

パッケージ名は `pyproject.toml` の複数箇所に現れる。**列挙を 1 つでも落とすと静かに壊れる**
（テストが収集されない / 契約が緩む）ので、`packages/<name>/` を作ったら次を全部直す:

1. `[project].dependencies` — ワークスペースの依存に足す
2. `[tool.uv.sources]` — `{ workspace = true }` を足す
3. `[tool.importlinter].root_packages` — 契約の対象にする
4. layers 契約の `layers` — **兄弟は 1 要素に `"jin_adk | jin_render | jin_wasm"` と `|` 区切りで書く**
   （別要素に並べると実際の契約より強い順序を宣言してしまう）。ただし**兄弟がまだ存在しない間は単独で書く**:
   存在しないパッケージを `|` で並べると import-linter 2.14 が `Missing layer` で EXIT 1 になる（Phase 2 で実測）。
   2 つ目を足すときに `|` に直す
5. forbidden 契約の `source_modules` — 「google-adk に依存しない」「任意コード実行の実装は `jin_cli.resolver` と
   `jin_adk.runtime` に閉じる」の対象に加える（`jin_cli` 自身は後者の対象外）
6. `packages/<name>/tests/__init__.py` — 無いと同名テストファイル 1 個でスイート全体が `Interrupted` になる
7. **依存する側の `packages/<x>/pyproject.toml`** の `dependencies` と `[tool.uv.sources]` — workspace の推移で
   手元では動いてしまうが、単体インストールで `ModuleNotFoundError` になる
   （`tests/contract/test_packaging_contract.py::test_every_package_declares_the_jin_packages_it_imports`）

8. `tests/contract/test_guard_claims.py` の期待集合 — そのパッケージに `guard:` /
   `hazard:` を書いたモジュールがあるなら名指しで足す（走査が壊れて対象が消えたときに気づくため）

チェックリストの外で足す場所が 3 つある（`jin-wasmgc` を足したときに実測・Issue #73）:
`tests/contract/test_dependency_direction.py` の `PLANNED_PACKAGES`（`packages/` の実体と等号）と
`test_import_linter_actually_bites_on_a_forbidden_import` の parametrize（新しい層からの禁止 import を注入して
実際に落ちることを見る）、そして `uv lock`（CI は `UV_LOCKED=1` で lock のずれを落とす）。

`testpaths` は `packages` をディレクトリごと指すので追記は要らない。
1〜7 の抜けは `tests/contract/test_packaging_contract.py` が名指しで落とす。8 は `tests/contract/test_guard_claims.py::test_the_scan_finds_the_modules_that_carry_claims` が**走査結果のパッケージ名と期待集合の等号**で自己検出する（名指しではない）。

## 実装の進み具合

| Phase | 内容 | 状態 |
|---|---|---|
| 0 | 仕様書 5 本 + examples 2 本 + 突合テスト | 実装済み |
| 1 | `jin-core` + `jin-cli`（check / fmt / schema / dump） | 実装済み |
| 2 | `jin-adk`（build / run / trace / FakeLlm） | 実装済み |
| 3 | `jin-render`（render / focus / trace overlay） | 実装済み |
| 4 | `jin-lsp`（stdio + ws）+ Claude Code プラグイン | 実装済み |
| 5 | `apps/editor` 編集モード + `jin editor` | 実装済み |
| 6 | `apps/editor` デバッグモード（トレースリプレイ） | 実装済み |
| — | エディタからの実行（Issue #34・要件書 §7.2 の「v1.1」を前倒し） | 実装済み |
| v2-0 | Jin v2（汎用ビジュアル言語）の設計書と `docs/spec/v2/` 8 本 + `examples-v2/` + probe | 実装済み |
| v2-1 | `jin_core.v2`（model / expr / semantic / ops）+ `jin-v2.schema.json` / `abilities.json` + version 振り分け | 実装済み |
| v2-2 | `jin-wasm`（jil / prelude.lua / codegen / lupa runtime / jinrec / bundle）+ `jin run` / `jin build` の v2 分岐 | 実装済み |
| v2-3 | `jin_render.v2`（額縁 / 型紙 / 4 環 / 手順の図 / トレースオーバーレイ・13 種）+ `jin render` と `jin/renderSvg` の v2 | 実装済み |
| v2-4 | `apps/player`（Wasmoon ホスト / canvas / 入力 / 音 / `.jinrec` 録画 / 最小 UI / postMessage）+ `jin build` の同梱と `--single` + パリティ e2e | 実装済み |
| v2-5 | LSP の v2（hover / completion / `jin/applyOps` + 応答の JIL）+ エディタの v2（式エディタ / 13 種 / 32 ops）+ 実行パネル（`/play/` iframe・ライブリロード） | 実装済み |
| v2-6 | デバッグ（`.jinrec` の再生・スクラブで記憶環の値と画面・`assert` のバッジ・実行パネルの録画と書き出し） | 実装済み |
| v2.1 | 状態を保ったライブリロード（`tick` 結果の `snapshot` → `boot` の `manifest.resume`・`jin.load` の `keep`・jil: 2） | 実装済み |
| v2.1 | `storage`（`get` / `set`・`boot` の `manifest.storage` → `tick` 結果の `storage`・`localStorage`・録画ヘッダの `storage`・式の `num(str)`・jil: 3） | 実装済み |
| v2.1 | 式の正準化（`canonical.dumps` が `x-jin-expr` の欄を AST から書き戻す・`jin_core.v2.expr.unparse`・読めない式は元のまま） | 実装済み |
| v2.1 | 鑑賞ページ（`apps/stage`・金環の 3D・発動の演出・MP4 / WebM / PNG の書き出し・エディタの「鑑賞」モード・`jin editor` の `/stage/`） | 実装済み |
| v2.1 | `canvas.text` の ASCII 以外の字形（k6x8ゴシックの 7001 字・JIS X 0208 の全区点・`player.js` に同梱・幅は 1 コードポイント = 6 のまま） | 実装済み |
| v2.1 | 文字列の順序 `cmp(a, b)`（-1 / 0 / 1・コードポイント順 = UTF-8 のバイト順・プレリュードはバイトを比べて `strcoll` を通さない・jil: 4） | 実装済み |
| v2.1 | `jin run --storage`（記憶の JSON を起動時に読み・終了時に書き戻す・無ければ空・`--input` があれば録画のヘッダが正で読み書きしない・書き戻しは `_write_atomically`） | 実装済み |
| v2.1 | エディタの図の操作（Shift クリックの範囲で `wrapSteps` / `extractRite` を `count` > 1・列を跨ぐステップのドラッグは `removeStep` + `addStep` の合成・陣を陣 / 手順に落として `addDelegate` / `addSigil` の `summon`） | 実装済み |
| v2.1 | v1 の陣（LLM エージェント）を v2 から呼ぶ `agent` の sigil（Issue #54・設計書 §11 #55・runtime.md §11。問いは tick 結果の `asks`・答えは入力イベント `reply`・答えるのはヘッドレスの `jin_cli.agents.AgentHost` だけ・`jin run --model fake` / `--record`・jil: 6） | 実装済み |
| v2.1 | 文字入力 `input.text()`（この tick に確定した文字列・入力スナップショットの `text` イベント・プレイヤーは見えない入力欄と `compositionend`・`.jinrec` の版は 1 のまま・jil: 5） | 実装済み |
| v2.1 | `jin build --target wasm-gc`（wasm-GC を直接出す第 2 の生成系。Issue #53・設計書 §11 #56・jil.md §6・`wasmgc-api-probe.md`。新しい兄弟パッケージ `jin-wasmgc` + WAT → `wasmtime.wat2wasm`・引数も戻りも JSON 1 本を線形メモリで・ヘッドレスは wasmtime・`wait` は状態機械） | 仕様確定。実装は Sub-Issue #73〜#76（#73 = パッケージ + WAT 生成系の最小形 + fib の公開 state 一致: **実装済み**。#74 = ランタイム部（文字列 / list / 型紙 / JSON / 数値の書式と strtod / PCG32 / 能力 / 純関数 / 効果 / エラー機構 / 命令数の上限）+ `on` の配達 + 6 本の fixture の release `--frames` 一致: **実装済み**。#75 = スケジューラ（陣の順 / flow / transfer / emit / summon / guard / `asks` + `reply`）+ `wait` の状態機械 + debug（トレース / `snapshot` / `resume`）+ 17 本の debug `--trace` / `--frames` 一致: **実装済み**。#76 = プレイヤーの `WasmGcHost` + manifest の `target` + `--single` + ブラウザの e2e + `runtime.wat` の生成物化: **実装済み**。Issue #53 完了） |

### Jin v2.1（`--target wasm-gc`・`jin-wasmgc`）の要点（正典は `docs/spec/v2/jil.md` §6・設計書 §11 #56・`wasmgc-api-probe.md`）

- **解析は `jin_wasm.program` で共有する**（`analyze` → `Program`: 型付き AST・型紙 / 陣 / 手順 / state / sigil の
  添字・`wait` の閉包・`manifest_base`）。Lua の `jin_wasm.codegen` も WAT の `jin_wasmgc.codegen` もここから読み、
  `typed_nodes` を呼び直さない。切り出しで Lua の生成物は 1 バイトも動いていない（34 本の `jil` sha が不変）
- **`game.wasm` = ヘッダ 3 行 + `(module` + `jin_wasmgc/runtime.wat`（ランタイム部。プレリュードに相当・**生成物**）+
  生成部 + `)` を `wasmtime.wat2wasm` で束ねたもの**（`jin_wasmgc.assemble`）。自前の binary writer も `wasm-tools`
  も無い。`wat2wasm` は bytearray を返すので `bytes` にしてから bundle へ渡す。`jil` の版は Lua 経路と共有
  （ヘッダ `;; jin: 2  jil: 7  target: wasm-gc`）
- **ホストが呼ぶ export は `input(n)` / `boot(n)` / `tick(n) -> (ptr, len)` の 3 つ**（`jin_wasmgc.runtime.WasmGcHost`）。
  引数は `{"seed", "manifest"}` / `{"t", "inputs"}` の JSON を線形メモリに書き、`tick` の結果を読む。`boot` に結果は
  無い。**instantiate も fuel を消費する**ので `Instance()` の前に `set_fuel` する。プレイヤー側は `apps/player/src/host.ts`
  の **`WasmGcHost`**（`JinHost` と同じ `Host` の口・`Player` はどちらかを知らない）。`memory.grow` で JS の
  `memory.buffer` は detach されるので、バイト列を先に作り → `input(n)` → **その後に** `memory.buffer` を取って書く
  （vitest は `input` が毎回 grow する echo module で固定する）。trap は `HostError`
- **module は trap しない**（trap = 生成系のバグ・`WasmGcRunError` が名指しする）。**エラーは例外ではなくフラグ**
  （`runtime.wat` の `$ERR` が `$ERRED` / `$ERRMSG` / `$DONE` を立てる）: 効果はフラグが立っていたら何もしない、
  生成部はエラーし得るステップ（添字を含む式・cast・ループ）と手順の呼び出しの後にフラグを見て返る、tick は
  `publish_all` / `ADVANCE` を飛ばし boot は飛ばさない（プレリュードの `pcall` の範囲の写し。Issue #74）
- **命令数の上限は module 内のカウンタ**（`$bud`。生成部がループの戻り辺と手順の呼び出しに埋める。値 10^7 と文は
  `jin_wasm.runtime._SETUP` と同じで、`tests/contract/test_wasmgc_runtime_contract.py` が突き合わせる 3 つ目）。
  wasmtime の fuel（`FUEL_PER_CALL` = 10^11）は保険。両経路は**同じ tick で止まり** release の `error` / `done` が
  一致する（回数は単位が違うので同じでなくてよい・jil.md §6.6）
- 名前は WAT の識別子に埋めない（`$S<i>` / `$P<i>` / `$r<i>_<j>` / `$l<n>` / 型紙 `$F<k>`（`$F0` = Pointer はランタイム部）。
  添字は 0 始まり = JSON Pointer）。値は wasm-GC のヒープ（`str` = `(array i8)` の UTF-8・list = 要素の表現ごとの
  `$Lf` / `$Li` / `$Lr`（`anyref` の要素は読むときに `ref.cast`）・型紙 = struct）。公開 state の鍵などは data 区画
  （生成部は `DATA_BASE` = 2048 から。ランタイム部の文字列は [0, 2048) に閉じ、契約テストが配置を突き合わせる）、
  式の文字列リテラルは passive の data から `array.new_data`。JSON の数値は `$put_jn`（NaN / Infinity は文字列）
- **数値の書式（`$put_num`）と strtod は module の中の多倍長（10^9 進）**。書式はプレリュードの `%.{p}e` 探索の写し
  （p + 1 桁に最近接・偶数丸めした候補を、隣の double との中点と正確に比べて往復するかを見る）で、Python の repr と
  割れる 2 の冪の一部（区間が非対称な値）も **Lua に付く**。共有 fixture は `tests/fixtures/numbers.jsonl`
  （`scripts/generate_number_fixture.py`。9136 行・`str` = Lua の出力が正・`repr` との差は 2 の冪 92 件だけ）で、
  両経路の単体テストが同じ行を読む。strtod は Clinger の速い経路 + AlgorithmR（`num(str)` と JSON の読み手の両方）
- **既知の差（jil.md §6.4）**: `each` の本文で反復中の list を縮めると Lua は nil を読んで後で落ち、wasm は添字が長さを
  超えた時点で抜ける。`sub` の NaN の添字は Lua が位置付きの文で落ち、wasm は ""。深い再帰は Lua が "stack overflow"
  の文、wasm は call stack の trap。`sin` / `cos` / `atan2` は fdlibm の移植で 1 ulp 以内（バイト一致は保証しない。
  |x| ≥ 2^19·π/2 の還元は Payne-Hanek を移植していないので精度が落ちる）
- **`runtime.wat` は生成物で手で編集しない**（Issue #76 で切り替え）。正典は `packages/jin-wasmgc/runtime/`（部品
  `01_head.wat` … `05_sched.wat` と data 区画の文字列表 `strings.json`）で、`uv run python scripts/generate_runtime_wat.py`
  が `@K:name@` / `@OFF:name@` / `@LEN:name@` / `@DATA@` / `@LISTS@` の目印を番地と本文に置き換えて書く。文字列を足す /
  変えるときは `strings.json` を直して再生成する（番地は表の順に詰めて振る）。ずれは pytest の `--check`
  （`test_codegen.py::test_runtime_wat_is_generated_from_its_parts`）と CI の `--stdout | diff` が 2 重に見る。
  `test_runtime_strings_stay_below_the_program_data_base` は生成物の番地と長さを data 区画と独立に突き合わせる（生成器が
  壊れたときの網）。data 区画は 130 件・1157 バイトで [0, 2048) に収まっている
- **`returns` 付きの手順が末尾まで `return` せずに抜ける形は生成の時点で拒む**（Lua は nil を返して次の算術で
  error 行になるが wasm に nil は無い。Sub-Issue ではなく恒久。JIN213 / JIN202 はこの形を落とさない）
- `.jin` の `%` は Lua の `luai_nummod`（`$fmod` を b·2^k の引き算で正確に求めてから符号を b に合わせる）。
  `loop count` の回数は f64 のまま比べる（`i32.trunc` は NaN / 巨大な値で trap する）
- **スケジューラはランタイム部が陣の添字で持ち、生成部は「添字 → 陣ごとの関数」の振り分けを出す**（Issue #75）。
  陣の生存（status / paused / pending / cursor / delegate / published）は `runtime.wat` の配列（boot で `$N` の
  大きさに確保。ランタイム部の global は後ろに来る生成部の `$N` を定数式で参照できない）、tick の手順（配達 / 再開 /
  イベント / 確定 / 検査 / 進行・`ADVANCE_LIMIT` 1000）/ `ORDER` / `ENTER` / `FINISH` / `TRANSFER` / `EMIT` / `ASK` /
  `snapshot` / `restore_from` / `repair_flows` はプレリュードの写し。生成部が出す `$prog_*`（`flow` / `child` / `init` /
  `publish` / `core` / `has_on` / `on_*` / `deliver` / `reply` / `resume` / `until` / `name` / `find` / `guards` / `dump` /
  `restore` …）の一覧は `runtime.wat` の先頭コメント。`event` / `rite` / `cast` / `set` / `transfer` / `finish` / `assert`
  行は生成部が、`enter` / `exit` / `emit` / `wait` / `error` / `frame` 行はランタイム部が積む（`$row`。kind は番号）
- **`wait` は早送りの状態機械**（jil.md §6.5）: 閉包に入る手順だけ局所をフレーム `$W<i>_<j>` に持ち上げ、
  `$r<i>_<j>w(frame)` が毎 tick 先頭から `pc` まで早送りする（`if` の cond は評価せず再開点の枝へ・再開点を含まない
  loop は loop ごと飛ばす・含む loop はヘッダを飛ばす）。`until` は最も内側のフレームで評価（`$u<n>`）。
  **早送り中に再開点を含まない loop に入ると抜けられない**（ヘッダを飛ばすため。`test_wait_ticks_and_until_inside_loops…`
  が固定する）
- **`jin_wasmgc.runtime.run_headless_wasm` は `answer` / `replay` を `jin_wasm.runtime.answer_asks` で処理する**
  （v1 の陣への問いの答えを次の tick の `reply` に積む実装は 1 つ。再実装しない）
- 生成できない構文は無く、Sub-Issue #73〜#76 で Issue #53 は閉じた。release の manifest は共通部 + `target: "wasm-gc"` +
  `wasm`（sha256）で `jil` は無い。**Lua 経路の manifest に `target` は足さない**（無ければ `"lua"`）。
  **`jin build --target wasm-gc` は `game.wasm` + `game.manifest.json` + 同梱されたプレイヤーの `index.html` / `player.js`**
  を書く（`wasmoon.wasm` は書かない・`PLAYER_FILES_WASMGC`。`PLAYER_FILES` 自体は変えない）。`--single` は
  `window.JIN_BUNDLE = { manifest, game: base64 }`（Lua 経路の `{ jil, manifest, wasm }` とは別の形。プレイヤーは `game` の
  有無で見分ける）。プレイヤーは `game.manifest.json` の `target` で `game.lua` + Wasmoon か `game.wasm` + `WasmGcHost` かを
  選ぶ。**エディタの `jin.load` は JIL のまま**（LSP の生成は Lua 経路・設計書 §8）。ブラウザのパリティは
  `apps/player/e2e/wasmgc.spec.ts`（録画 → Lua と wasm-GC の両方の `jin run --input` と全行一致・`--single` の wasm-gc 版）
- **生成部を変えたらスナップショットを更新する**: `uv run pytest packages/jin-wasmgc --snapshot-update`
  （`packages/jin-wasmgc/tests/__snapshots__/`・Lua 側と同じ 5 本 × debug / release）。パリティは
  `tests/contract/test_wasmgc_parity.py`（`jin run --target lua` と `--target wasm-gc` を実プロセスで走らせ、19 本
  × release / debug の `--frames` / `--trace` のバイト一致 + 実行時エラーの行 + `paddle-v2.jsonl` の全行一致）。
  単体では `packages/jin-wasmgc/tests/test_runtime.py` が**生の tick 結果の文字列**（trace / snapshot / asks 込み）を
  Lua と比べる（`json.loads` を通すと 1 / 1.0 とエスケープの違いが消える）。ランタイム部の内側は `tests/conftest.py` の
  `Probe`（test だけの export を足した module）で叩く。resume は `packages/jin-wasmgc/tests/test_resume.py`

### Jin v2（汎用ビジュアル言語・wasm 実行）の要点

正典は `docs/superpowers/specs/2026-09-13-jin-v2-general-design.md`（設計書）と `docs/spec/v2/*.md`。
**v1 の正典・契約テストには触れない**（サブコマンド 9 個 / `data-jin-kind` 9 種 / `jin/` 6 種 /
`CANONICAL_CODES` 14 件はそのまま）。v2 は別の集合を別のテストで固定する。

- **振り分けは `jin_core.check.root_model_for` 1 か所**（`version: 2` だけが `JinFileV2` へ）。
  `canonical.dumps` は Pydantic 汎用なので v2 にそのまま効く。`CheckResult.model` は `JinFile | JinFileV2`
- **schema は別ファイル** `schemas/jin-v2.schema.json`（`jin schema --version 2`）。`jin.schema.json` は
  1 バイトも変えない（`apps/editor` がルート `properties` を直接読む）。`schemas/abilities.json` の正本は
  `jin_core.v2.abilities`。3 つとも `uv run python scripts/generate_schema.py` で再生成する
- **診断は JIN2xx の別番号帯**（`jin_core.diagnostics.V2_CODES`）。意味が同じ JIN001 / 002 / 010 / 011 /
  012 / 013 / 020 / 022 / 060 は共有。fixture は `tests/fixtures/errors/v2/`（v1 の走査は非再帰なので混ざらない）
- **式（葉）は `jin_core.v2.expr` のインライン Lark 文法**。式内の位置 → JSON 文字列リテラル内の列は
  `jin_core.v2.spans` だけが換算する
- **`examples-v2/` は恒久的に `examples/` の外**（`examples/` は v1 の契約が「3 本」と数える）。
  CI は `examples-v2` にも `check` / `fmt --check` を掛ける
- **`jin run` / `jin build` の v2 は `jin_wasm`**（正典は `docs/spec/v2/runtime.md` / `jil.md`）、
  **`jin render` の v2 は `jin_render.v2`**（正典は `docs/spec/v2/layout.md`）。入口は `jin_render.render` 1 本で、
  `JinFileV2` を受けたら `jin_render.v2.render_v2` へ振る（CLI / LSP は version を見ない）。`--focus` は
  `陣名` か `陣名/手順名`（手順の図）。LSP は v2 で **診断 / `jin/model` / `jin/renderSvg` / formatting / `jin/save` /
  hover / completion / `jin/applyOps`** に答える（Phase 5）。definition / references / documentSymbol / rename /
  codeAction は v1 のモデル（`DocumentState.model_v1`）にだけ効く（v2 のそれらは設計書 §8 に無い・§11 #36）。
  **`jin editor` で v2 の `.jin` を開くと v2 のエディタになる**（下の「Jin v2 Phase 5 の要点」）
- **v2 の `data-jin-kind` は 13 種**（`jin_render.DATA_JIN_KINDS_V2`。v1 の 9 種とは別集合で、`stage` / `form` /
  `circle` / `core` / `rite` / `sigil` / `state` / `on` / `guard` / `delegate` / `flow-edge` / `step` / `step-edge`）。
  v1 の規律（`fmt_coord` 1 本 / 3 桁固定 / 楕円弧 `A` 不使用 / 2 色 + 強調 1 色 / `<style>` 不使用）と `geometry` /
  `svg` / `paths` / `ornament` / `overlay` を共有し、v2 で決めること（額縁 1.18・印章・手順の図の弧の割り当て・
  実装で確定した値）は v2 layout.md §3 / §8 に書いてある。**環の半径 4 本は v1 と同じ値**
- **v2 のトレースの `seq` は 0 始まり**（runtime.md §5）。overlay は `read_trace(rows, min_seq=0)` で読み、
  v1 の既定（1 始まり）は変えない。`frame` 行（`/stage`）は額縁を強調せず点にだけ数える。
  `tests/fixtures/traces/paddle-v2.jsonl`（`jin run --ticks 3 --debug --trace`・38 行）が jin-render のテスト用で、
  実行結果との全行一致は `tests/contract/test_render_contract_v2.py` が見る
- **v2 の SVG スナップショット**は `packages/jin-render/tests/__snapshots__/test_snapshots_v2.ambr`（7 本）。
  `jin_render.v2.geometry` の値や描き方を直したら `uv run pytest packages/jin-render --snapshot-update` で更新し、
  差分を読んでからコミット。paddle に `delegate` が無いので 13 種目は `tests/fixtures/v2-programs/transfer.jin` で
  補う（設計書 §11 #30。paddle は §2.2 と突合されるので書き換えない）
- **JIL は Lua 5.4 の静的サブセット**（`jin_wasm.jil.JIL_FORBIDDEN` は jil.md §2 と等号）。`game.lua` =
  ヘッダ + `prelude.lua`（そのまま連結）+ 生成部 + `return { boot = boot, tick = tick }`。生成部が定義するのは
  `DEBUG` / `ROOT` / `FPS` / `CIRCLES[i]` / `R[i][j]` / `JF[k]` / `JR[k]`（型紙の読み手・debug だけ）だけで、
  プレリュード先頭のコメントと 1:1（`tests/contract/test_jil_contract.py` の `PROGRAM_ASSIGNMENTS`）。JIL の版は **7**
  （jil.md §1。v2.1 で `CIRCLES[i]` に `restore` / `prestore` / `pdump`、`tick` 結果に `snapshot` / `resume` が加わって 2、
  プレリュードに `H.storage` / `F.num`、`tick` 結果に `storage` が加わって 3、プレリュードに `F.cmp` が加わって 4、`H.input.text` と `JS` の制御文字の範囲指定が加わって 5、`ASK`（v1 の陣への問い）と入力イベント `reply` の配達・`tick` 結果の `asks`・`snapshot` の `asked` が加わって 6、プレリュードに `LIVE` が加わり `STOP(i, live)` が「この呼び出しで active でなくなった」ときだけ真になって 7（Issue #87 / #89。生成部が自陣の手順への `cast` の前に `LIVE(i)` を局所に取る。release の生成部が動いた唯一の版）。**自陣の手順への `cast` の直後の中断検査は「呼ぶ前の生存」との比較**で、呼ぶ前から active でない陣（未 entered の summon の呼び先・done の陣・`on exit` の中）は止めない）。
  **名前を Lua の識別子に埋め込まない**（`S[i].k_j` / `R[i][j]` / `f_j` / `l_n`。添字は Lua の 1 始まり、pointer は 0 始まり）。
  `num` は常に float（`160.0`）。`tests/contract/test_jil_contract.py` がプレリュードと全生成物を走査する
- **`jin run`（v2）は `agent` の sigil が無ければ任意コードを実行しない**（`agent` は下の「危険性」の段）。`lupa.lua54` を明示し（既定の `LuaRuntime` は Lua 5.5.1）、
  `register_builtins=False` + `python` テーブルと `load` / `os` / `io` / `debug` … を nil にしてから JIL を読む。
  命令数の上限（`INSTRUCTION_BUDGET` = 10^7 / boot と tick ごと）は `debug.sethook` の count hook。
  **Lua の hook はスレッドごと**なので、ホストは JIL を読む前に `JIN_ARM()` / `JIN_HOOK(co)` の 2 つの
  グローバルを置き（読んだ後に消す）、プレリュードが `boot` / `tick` の先頭と毎 `coroutine.resume` の前に
  呼ぶ（Phase 4 で確定。`wait` を含む手順の無限ループはこれが無いと止まらない・設計書 §11 #32）。
  ホストが呼ぶ Lua の関数は `boot` / `tick` の 2 つだけで、戻り値は JSON 文字列 1 本（Lua のテーブルは境界を越えない）
- **数値の書式は Python の `repr(float)` と同じ配置**（runtime.md §6・設計書 §11 #23）。トレース・表示リスト・
  `str()` の 3 つが同じ規則。`test_prelude.py` が非整数 700 件で固定する
- **`jin build`（v2）は `<out>/` に `game.lua` / `game.manifest.json` / `assets/` を書く**（`jin_wasm.bundle`。
  `jin_adk.build` と同じ `O_EXCL` / `O_NOFOLLOW` / `dir_fd` の規律）。asset は `.jin` の親ディレクトリの中に閉じる。
  プレイヤー（`index.html` / `player.js` / `wasmoon.wasm`）は `scripts/sync_player.py` が `apps/player/dist` から
  `jin_wasm/player/`（gitignore・wheel には入る）に同梱していれば一緒に書く。無ければ stderr に 1 行出して game.* だけ書く。
  **`--single` は `index.html` 1 本**（`player.js` インライン + `window.JIN_BUNDLE` に JIL / manifest / wasm の base64。
  asset があれば拒む・設計書 §11 #34）。テストは `bundle.PLAYER_DIR` を monkeypatch して同梱あり / なしの両分岐を固定し、
  CI の player ジョブだけが `JIN_REQUIRE_PLAYER=1` で「有る側」を要求する
- **生成部を変えたらスナップショットを更新する**: `uv run pytest packages/jin-wasm --snapshot-update`
  （`packages/jin-wasm/tests/__snapshots__/`。生成部 5 本（paddle / clicker / fib / tetris / othello）× debug / release と paddle 60 tick のゴールデン）。
  差分を読んでからコミット。examples-v2 が使わない経路（parallel / transfer / emit / key / pointer / wait until /
  each / summon / agent / 実行時エラー / assert / sequence）は `tests/fixtures/v2-programs/` の 14 本が固定する（v2.1 の `storage` / `text_input` / `agent` を含む）
- v2 の ops は `jin_core.v2.ops.OPERATIONS`（32 件・`docs/spec/v2/ops.md` §2 と等号）。`extractRite` の逆は
  オペレーション列で、`apply_ops` が undo 順に平らにする
- **エディタの図の操作は `apps/editor/src/v2/actions.ts` が `EditV2`（`ops` + 適用後に選ぶ要素 `select`）で返す**
  （ops.md §5・設計書 §11 #52）。範囲選択は選択の鍵 `step` に `count` を足すだけで種別を増やさない。
  ドラッグは `dropOps` 1 本で、**同じ列は `moveStep`、列を跨ぐ移動は `removeStep` + `addStep` の合成**（2 件目の
  pointer は `pointerAfterRemoval` で削除後に数え直す）、陣 → 陣 / 手順は `addDelegate` / `addSigil`（`summon`）。
  33 個目のオペレーションを作らず、`App.tsx` に v2 の op 名を書かない（契約テストが v1 の 19 件に閉じる）

v1 のサブコマンドは 9 つで揃った（`check` / `fmt` / `schema` / `dump` / `build` / `run` /
`render` / `lsp` / `editor`）。空実装を先に置くと `jin --help` が嘘をつくので、
未実装のものはサブコマンドごと存在させない。Phase 4 まではこれを
「未定義であること」の検査（typer の `No such command`）で見ていたが、Phase 5 で
最後の `editor` が実装されて parametrize が空になった。**空の parametrize はテストごと
収集されずに消える**ので、`test_no_command_is_defined_beyond_the_v1_set` が
「v1 の集合と過不足なく一致する」側から固定する形に反転させた。

Phase 2 の要点（正典は `docs/spec/adk-mapping.md` §2.3 / §2.4 / §3.1 / §6）:

- 生成コードのテンプレートは `packages/jin-adk/src/jin_adk/templates/agent.py.j2`。引数名は
  google-adk **2.8.0** の実測（`delivery/20260904-1445-jin/adk-api-probe.md`）に固定。
  `jin_adk.TARGET_ADK_VERSION` と入っている版が違うと `tests/contract/test_adk_version_contract.py` が赤くなる
- 生成 `agent.py` のスナップショットは `packages/jin-adk/tests/__snapshots__/`（syrupy）。
  テンプレートを直したら `uv run pytest packages/jin-adk --snapshot-update` で更新し、差分を読んでからコミット
- ADK に対応物のない構造は `jin check` ではなく `jin build` / `jin run` が `BuildError` で落とす
  （NFR-FAIL-001）。一覧と fixture は `docs/spec/adk-mapping.md` §3.1 と `tests/fixtures/build-errors/`。
  **診断コードは増やさない**
- `examples/researcher` の `ref`（`research.tools` / `research.guards`）はリポジトリに実体が無い。
  テストは `tests/fixtures/stubs/` のスタブを `sys.path` / `PYTHONPATH` に載せる

Phase 3 の要点（正典は `docs/spec/layout.md`）:

- **座標を SVG に書き出す経路は `jin_render.svg.fmt_coord` 1 本だけ**（DP-JIN-SVG-DETERMINISM-01・
  ADR-010）。丸め桁数は 3 桁固定小数で、根拠は layout.md §4 と `decision-conformance.md` §2 の
  両方に書いてある。`-0.0` は `0.0` に正規化する。SVG の楕円弧 `A` は使わない（フラグが 1 文字固定で
  3 桁と両立しない）ので円弧は 3 次ベジェで描く
- `jin_render.render` が**唯一の入口**。CLI の `jin render` と Phase 4 の `jin/renderSvg` は
  この関数だけを呼ぶ（要件書 §4 最終項）
- `jin_render` は**純関数**。ファイルを読まず、モジュールレベルの可変状態を持たない（DP-COMMON-07）。
  schema を通るモデルなら**意味エラーを含んでいても例外を投げない**（Phase 4 のエラー回復・layout.md §5）
- `data-jin-kind` は 9 種のみ。10 種目を増やさない。トレースの点は `circle`（layout.md §7.4）。
  Jin v2 の 13 種（`DATA_JIN_KINDS_V2`）は**別集合**で、v1 の 9 種には触れない
- SVG スナップショットは `packages/jin-render/tests/__snapshots__/`（syrupy）。
  レイアウトを直したら `uv run pytest packages/jin-render --snapshot-update` で更新し、差分を読んでからコミット

Phase 4 の要点（正典は要件書 §6 / `docs/spec/ops.md` §5〜§6 / `docs/spec/diagnostics.md` §5.1）:

- **pygls / pytest-lsp の API は記憶で書かない。** 一次証拠は
  `delivery/20260904-1445-jin/lsp-api-probe.md`（1.x → 2.x で import パスから変わっている）
- **位置変換は `jin_lsp.positions` の 1 モジュールだけ**が行う（1 始まり・コードポイント ↔
  0 始まり・UTF-16）。UTF-16 換算は pygls の `PositionCodec` に委ね、`guard:` 記法で固定する
- **stdio では stdout が JSON-RPC の通信路**である（DP-COMMON-14）。`jin_lsp` に `print(` と
  `sys.stdout.*` を 1 つも置かない（`tests/contract/test_lsp_contract.py` が AST で走査して落とす）。
  ログは `jin_lsp.logs.configure` が stderr へ固定する
- **未知メソッドの params / result は `jin_lsp.protocol.jin_converter` を通す。** 素の pygls は
  `namedtuple(rename=True)` に変換するので、`await` / `$schema` / JSON Pointer のような
  識別子にできないキーが**黙って `_0` に化ける**（実測）。同じ理由で `jin/model` の
  pointer→range 対応表は辞書ではなく**配列**で返す
- last-good モデルは**1 世代だけ**（DP-COMMON-07）。構文エラー中も hover / renderSvg が
  直前の正常モデルで答える（NFR-AVAIL-001）。SVG はキャッシュしない
- `didChange` は **150 ms デバウンス**して古い要求をキャンセルする。`didOpen` は待たない
  （NFR-PERF-001 の計測にデバウンス値を混ぜない）
- **オペレーションを 20 個目にしない**（要件書 §6.3 の v1 は 19 件）。参照 1 個の書き換えも
  既存オペレーションの合成で書く（`jin_lsp.features.edits._reference_replacement`）
- プラグインの `skills/jin-lang/reference/` は `docs/spec/model.md` と `schemas/jin.schema.json` の
  **コピー**。手で編集せず `uv run python scripts/sync_plugin_reference.py` で同期する
  （ずれても `jin check` は通るので静かに効く）

Phase 5 の要点（正典は要件書 §7 / `docs/spec/ops.md` §5 / `delivery/20260904-1445-jin/editor-api-probe.md`）:

- **エディタは 1 本の線も描かない。** SVG は `jin/renderSvg` から受け取り、`data-jin` で
  ヒットテストするだけ（要件書 §0「レンダラは Python 1 本」）。位置が要るとき（診断バッジ）は
  描かれた要素の `getBBox()` を使い、レイアウト規則を再実装しない。
  `tests/contract/test_editor_contract.py::test_the_editor_never_draws_the_magic_circle_itself` が
  `createElementNS(ns, "path" / "line" / "text" …)` を禁じる
- **エディタは独自のモデル状態を持たない。** 編集はすべて `jin/applyOps` を往復し、
  返ってきたモデルと SVG で置き換える。undo / redo はサーバが返した `inverses` を積むだけ
- **フォームは `schemas/jin.schema.json` から生成する。** `apps/editor/src/form/` に欄の名前は
  1 つも書かれていない。証拠は `test/schemaForm.test.ts`（schema に架空のキーを足すと欄が増える）。
  コピーを置かず**リポジトリの schema を直接読む**（`vite.config.ts` の `server.fs.allow`）
- **表示状態は 5 つ**（未接続 / 取得中 / 正常 / ステイル / 表示不能・DP-COMMON-19）。
  **3 に潰さない**。分岐は `default` を書かず `assertNever` で閉じ、
  `test/exhaustiveness.fixture.ts` の `@ts-expect-error` が
  「分岐を足すと tsc が落ちる / 網羅性を緩めても tsc が落ちる」を両側から固定する
- 選択は **circle 名 + 種別 + 要素名**で持つ（DP-COMMON-16）。生 pointer で持つと
  `moveTool` の並び替えで選択が別要素に飛ぶ。変換は `src/state/selection.ts` の
  `resolveSelection` **1 本**だけが行う
- **API は記憶で書かない。** pygls の ws が binary フレームで送ること、`start_ws` が
  1 接続で終わること、版の互換範囲はすべて `editor-api-probe.md` に実測がある
- `apps/editor` の版は**完全一致で固定**する（`^` / `~` を使わない）。
  レンダラの出力とバイト比較するテストがあるので、ツールチェーンが黙って動くと切り分けができない

Jin v2 Phase 4（`apps/player`）の要点（正典は `docs/spec/v2/runtime.md` §8〜§10 / 設計書 §11 #32〜#35）:

- **`apps/player` は Python パッケージを import しない。** 読む生成物は `schemas/abilities.json` だけ（キー名 / op 名の
  リテラルをソースに書かない）。TS 側は eslint の `no-restricted-imports`（`apps/player/eslint.config.js`）、Python 側は
  `tests/contract/test_player_contract.py` が走査する。JIL と manifest は `jin build` の出力（`game.lua` /
  `game.manifest.json`）を fetch するか、`--single` の `window.JIN_BUNDLE` から読む
- **ホストが呼ぶ Lua の関数は `boot` / `tick` の 2 つだけ**（`src/host.ts`）。サンドボックスの順序・消すグローバル・
  `JIN_ARM` / `JIN_HOOK` を置く Lua（`HOOK_SETUP`）・命令数の上限は `jin_wasm.runtime` と**同じ**で、契約テストが
  文字列で突き合わせる（`error` 行の文がホストで変わるとパリティが割れる）。Wasmoon の `Thread.setTimeout` は
  コルーチンの中で PANIC するので使わない。`new LuaFactory()` は引数無しだと unpkg へ fetch するので常に URL を渡す
- **パリティは構成で保証する**: `inputs` と `.jinrec` は同じ reducer（`src/input.ts` の `InputReducer` =
  `InputState.apply` の写し）から出し、`tests/fixtures/jinrec/reducer.*` を Python と TS の両方が検算する。録画は
  `boot` し直して tick 0 から。e2e（`e2e/parity.spec.ts`）は実ブラウザで録画 → `jin run --input` → トレースを
  **JSON として読んでから全行一致**
- **API は記憶で書かない。** Wasmoon の実測は `delivery/20260904-1445-jin/wasm-api-probe.md` §A（1.16.0。§A.10 が Phase 4）
- ツールチェーンは `apps/editor` と同じ版で完全一致（契約テストが両者の共通 devDependencies を突き合わせる）。
  `pnpm e2e` は Playwright 1.62.0 の chromium（`pnpm exec playwright install chromium`）と `uv sync` 済みの Python が要る
- **`canvas.text` の ASCII 以外の字形は `src/glyphs.ts`（生成物・手で編集しない）**（v2.1・設計書 §11 #49）。
  原本は `apps/player/fonts/k6x8/k6x8_gothic.bdf`（改変しない。digest を `scripts/generate_glyphs.py` の
  `BDF_SHA256` と同じディレクトリの README に固定）。直したら `uv run python scripts/generate_glyphs.py` で
  再生成する（pytest の `--check` と CI の player ジョブの `--stdout | diff` が 2 重に見る）。ASCII は `src/font.ts` の
  5×7 のまま、幅は字形によらず 1 コードポイント = 6。字形は `stage.assets` の font にしない（埋め込みのプレイヤーは
  asset を読めないので、エディタの実行パネルで描けなくなる）

Jin v2 Phase 5（LSP の v2 + エディタの v2 + 実行パネル）の要点（正典は設計書 §8 / §11 #36〜#38、`docs/spec/v2/ops.md` §5、
`docs/spec/v2/runtime.md` §10）:

- **式の欄は schema の印 `x-jin-expr` だけで決める。** `jin_core.v2.model.Expr` が `jin-v2.schema.json` に出す
  （`jin.schema.json` は 1 バイトも変えない）。エディタ（`apps/editor/src/form/schemaForm.ts` の `isExpr`）も LSP
  （`jin_core.v2.model.expr_fields`）も欄の名前を書き写さない。`args`（`list[Expr]`）だけは配列でも欄にする
- **式エディタは `jin_core.v2.expr` を再実装しない。** 候補は LSP 標準の `textDocument/completion`（`jin/…` は 6 種の
  まま）。位置は `jin/model` の `pointers` と現在のテキストから換算し（`apps/editor/src/v2/position.ts`・
  コードポイント → UTF-16）、リテラルの**先頭**で求めて、候補をカーソル直前のトークン（識別子と `.`）で前方一致させる。
  サーバ（`jin_lsp.features.v2`）は `名前空間.メンバ` / `陣名.key` / `局所.欄` の点付きラベルを含めて返す
- **hover / completion の v2 は `jin_core.v2.semantic.analyze_model`**（式の AST / 型 / 位置ごとのスコープの写し）から
  引く。スコープは意味検査の副産物として `_check` / `_step` / `_rite` / `_circle_body` で記録し、`Analysis.scope_at` が
  pointer の祖先へ遡る（打鍵途中で構文エラーの式でも、そのステップのスコープで候補が出る）
- **`jin/applyOps` の v2 は `jin_core.v2.ops`**（32 件）。応答は `warnings` と `jil` / `manifest` / `jilError`
  （`jin_lsp.jil.generated`・常に debug ビルド・best-effort）を持ち、`jin/model` も v2 なら同じ 3 つを載せる。
  式に構文 / 型エラーが残っていれば `ok: true` のまま `jil: null`（ops.md §1）。**jin-lsp は jin-wasm に依存する**が
  import するのは `jin_wasm.codegen`（と `jil`）だけで、`tests/contract/test_lsp_contract.py` が AST で固定する
- **エディタの v2 は別ファイルに隔離する**（`apps/editor/src/v2/`: `selection.ts` / `dispatch.ts` / `actions.ts` /
  `position.ts` / `ExprEditor.tsx` / `PropertyPanelV2.tsx`）。v1 のファイル（`form/dispatch.ts` / `App.tsx`）は v1 の
  19 件だけ、`src/v2/` は v2 の 32 件だけを送る（契約テストが両側から固定）。選択は名前で持つ（DP-COMMON-16）が、
  `on` は `event`、`guard` は `assert`、ステップは 陣 + 手順名 + 手順内パス。直接のオペレーションが無い欄は合成で書き、
  **33 個目を作らない**（description / sigil の host / on の event / do。ops.md §5）
- **loop / if の本文へは「本文に追加」（`jin-add-step-inside`・v2.1）**。「ステップを追加」は選択の直後、ドラッグの
  落とし先は既にあるステップなので、**空の本文には図に要素が無く、この操作でしか入れられない**（`actions.ts` の
  `addStepInside` / `insideListOf`。`loop` は `…/steps`、`if` は `…/then` の末尾。`else` と範囲選択には効かない）
- **境界のイベントは「イベントを追加」（`jin-add-on`・Issue #95）**。選択中の**手順**を呼ぶ `on` を既存の `setOn` で足す
  （`event` は schema の `OnHandler.event` の enum からまだ使われていない先頭・全部使われていれば `notice`・足した `on` を選ぶ。
  `actions.ts` の `addOn`）。`on` の欄の編集は従来どおり（`event` は `removeOn` + `setOn` の合成）
- **手順の引数（`Rite.params`）はフォームの行の表**（v2.1）。印は schema の **`x-jin-inline`**（`jin_core.v2.model.
  INLINE_SCHEMA_MARK`。`Rite.params` にだけ付き、`test_the_rite_params_carry_the_inline_mark_in_the_schema` が
  「他の配列には付かない」を固定）で、`schemaForm.ts` は印のある「スカラ欄だけのオブジェクトの配列」を `rowList`
  にする（列は要素 schema `Param` から。欄の名前を書き写さない）。`dispatch.ts` は**名前だけ**の変更を `rename`
  （参照が追随）、追加 / 削除 / 型を `setRiteSignature` に換算し、新しい行は空き番 + `num`（`defaultRowV2`）
- **実行パネルは同一オリジンの iframe `/play/`**（`apps/editor/src/run/RunPanel.tsx`）。`jin editor` が
  `--player-dist` > `apps/player/dist` > `jin_wasm.bundle.PLAYER_DIR` の順に探して配る（`translate_path` の正規化を
  通すので `/play/../` で抜けない）。JIL は `jin.load`、操作は `jin.control`、トレースは `jin.trace` で話し（Phase 6 で 7 語に増えた。下の Phase 6 の要点）、
  **`POST /run` は使わない**。プレイヤーは iframe の中では fetch せず `jin.load` を待つ。走っている間の描き直しは
  1 秒に 1 回（`LIVE_REFRESH_MS`）、行数は 4000 で頭打ち（`MAX_LIVE_ROWS`）。asset（絵と音）は埋め込みでは読めない
- `apps/editor` が読む生成物は `jin.schema.json` / `jin-v2.schema.json` / `abilities.json` の 3 つ（いずれも Pydantic
  定義から生成してコミットした成果物。コピーを置かない）。eslint の禁止規則は変えていない
- スモークは `apps/editor/e2e/v2.spec.ts`（要 `apps/player` の `pnpm build`。CI の editor ジョブが e2e の前にビルドする）

Jin v2 Phase 6（デバッグ: 録画の再生・記憶環の値・`assert` のバッジ）の要点（正典は設計書 §8 / §11 #39〜#41、
`docs/spec/v2/runtime.md` §5 / §7 / §10、`docs/spec/v2/layout.md` §6）:

- **`.jinrec` の読み手はプレイヤー**（`apps/player/src/jinrec.ts` = `jin_wasm.jinrec.read_jinrec` の写し。書き手
  `recorder.ts` と同じ app）。壊れ方は `tests/fixtures/jinrec/broken/`（`broken.expected.json`）を Python と TS の
  両方が**同じ行番号**で検算する。エディタは 1 行目に `"jinrec"` があるかしか見ず（`RunPanel` の `looksLikeJinrec`）、
  生のテキストを `jin.replay` で渡す。`apps/editor` から `apps/player` の TS は import しない
- **再生は tick 0 からヘッダの seed で、同じ reducer を通す**（`Player.replay`）。終わったら止まったまま。
  `apps/player/e2e/replay.spec.ts` が `tests/fixtures/jinrec/paddle-120.jinrec` で `jin run --input` と全行一致を見る
- **記憶環の値と `assert` はエディタが積算する**（`apps/editor/src/debug/values.ts`。runtime.md §5 が「スクラバの
  仕事」と書いた範囲だけ: `enter` / `exit` の output で陣の state 全部、`set` で 1 つ、`assert` は guard ごと、
  `frame` は `upto` の位置の最後の 1 枚 → `jin.frame` でプレイヤーに描かせる）。**オーバーレイ（発火の強調と点）は
  作らない**（`data-jin-fired` / `data-jin-seq` を書かない契約はそのまま）
- **ラベルは SVG の外の HTML 層**（`SvgCanvas` の `labels`。位置は `getBoundingClientRect()`）。`createElementNS` で
  `<text>` を作らない契約テストがあるので SVG の中に置かない。値は脇の表（`jin-state-values`）にも全部出す
- **行数の上限は出どころで分ける**（`App.tsx`）: 走らせている間は `MAX_LIVE_ROWS`（4000・古い行を落とす）、
  録画の再生は `MAX_REPLAY_ROWS`（60000・落とさず、超えたら載せない）。古い行を落とすと `enter` 行が消えて
  値の積算が黙って狂うため。描き直しはプレイヤーが止まった知らせ（`jin.status` の `running: false`）で行う。
  **ws の 1 メッセージの上限は `jin_lsp.server.WS_MAX_MESSAGE_BYTES`（64 MiB）**: `jin/renderSvg` はトレース行を
  丸ごと載せるので、`websockets` の既定 1 MiB のままだと数千行で接続が 1009 で閉じ「表示できません: Connection is
  disposed」になる（tetris の録画の再生で実測。`test_ws_roundtrip.py::test_a_render_request_with_a_large_trace_…`）
- **親とプレイヤーの語彙は 7 語**（`jin.load` / `jin.control` / `jin.replay` / `jin.frame` は親から、`jin.trace` /
  `jin.status` / `jin.recording` は親へ）。`tests/contract/test_editor_contract.py` が `RunPanel.tsx` と `main.ts` から
  抜いた集合の**等号**で固定する。語彙はこの 2 ファイルの外に書かない
- 録画の書き出しは親のダウンロード（`<jin 名>-seed<seed>-<ticks>t.jinrec`）。埋め込みでは録画・再生とも asset は読めない

Jin v2.1（状態を保ったライブリロード）の要点（正典は `docs/spec/v2/runtime.md` §1.3 / §10、jil.md §1 / §5、
設計書 §8 / §11 #42〜#44）:

- **経路はデバッグビルドの `tick` 結果の `snapshot` → 次の `boot` の `manifest.resume`**。ホストが呼ぶ Lua の関数は
  `boot` / `tick` の 2 つのまま。プレリュード（`restore_from` / `repair_flows`）が**陣を名前で照合**して生存 / state /
  公開 state の確定値 P / tick / seq / PCG32 を写す。root が照合できなければ通常の boot（`resume.mode = "fresh"`）。
  `wait` 中の手順と未配達の `emit` は捨てる。復元の知らせは直後の tick 結果に 1 回だけ（`resume`）。
  release には `snapshot` が無い。lupa 側の証拠は `packages/jin-wasm/tests/test_resume.py`
  （「途切れずに走らせた列と、途中で差し替えて続けた列が行（seq 込み）も画面も乱数列も一致」）
- **ホストの値の形を `type(v) == "table"` で見ない**（lupa は table、Wasmoon は proxy の userdata）。読み手
  `RREC` / `RN` / `RB` / `RSTR` / `RL` / `JR[k]` は欄の読み取りと `ipairs` で形を見て、合わなければ nil（init のまま）。
  数値は `+ 0.0` で float に揃える。PCG32 の 64 bit 状態は `"0x…"` の 16 進**文字列**で越える（jil.md §5 の唯一の例外）
- **Wasmoon は JS の `null` を Lua に積めない**（proxy が欄を読んだ瞬間に PANIC でエンジンごと落ちる。probe §A.11 の実測）。
  `apps/player/src/host.ts` の `boot` は `withoutNulls` で `null` を欄ごと落としてから渡す（核なし陣の `state` /
  `delegate` が `null`）。JS → Lua に新しい JSON 由来の値を渡すときは同じ写しを通す
- **プレイヤーは前のプレイヤーから引き継ぐ**（`Player.resumeFrom`）: tick / seed / reducer / 押下状態
  （`InputCollector.adopt`）/ トレース / 直近の画面。録画は止める。`fresh` ならその tick を捨てて `reboot`。
  `jin.status` の **`generation`**（boot し直すたびに増え、続けたときは変わらない）で親（`App.onStatus`）が走らせた行を
  捨てるかを決める（seq が 0 に戻るので）。読み込みは直列（`loading` の promise 鎖）
- **v2 の実行パネルはモードを切り替えても外さない**（`App.tsx` で `hidden={mode !== "debug"}`）。式の欄は編集モードにしか
  無く、外すと iframe ごとプレイヤーが消える。「編集しても状態を保つ」（`jin-keep-state`・既定 on）は ref で読み、
  切り替えただけでは `jin.load` を送り直さない
- **隠れている間はプレイヤーを止めておく**（Issue #66・設計書 §11 #54）。`RunPanel` は `hidden` の変化で
  `jin.control` の `suspend` / `wake` を送るだけで、止める / 起こすの判断はプレイヤー（`main.ts`）が持つ
  （`suspend` は走っていたかを覚え、止められている間の `jin.load` は走り出さずに保留し、`wake` で走る）。
  見えないゲームが走ると親が 1 秒ごとに図を描き直し、編集のドラッグと重なる（#64 のフレークの根）。
  語彙は 7 語のまま。`tests/contract/test_editor_contract.py::test_the_hidden_run_panel_suspends_the_player`
- 語彙は 7 語のまま（`jin.load` に `keep`、`jin.status` に `generation` の**欄**が増えただけ）。e2e は
  `apps/player/e2e/reload.spec.ts`（Wasmoon 経路で tick / 公開 state / 世代が続き seq が途切れない）と
  `apps/editor/e2e/v2.spec.ts`（走らせて止める → 編集モードで式を直す → 戻ると続く → 外すと世代が進む）

Jin v2.1（`storage`）の要点（正典は `docs/spec/v2/abilities.md` §8、expr.md §4.1、runtime.md §1.2 / §4 / §7 / §10、
設計書 §11 #45〜#47）:

- **ホスト境界は変えない。** 入りは `boot(seed, manifest)` の `manifest.storage`（ホストが持つ記憶の写し）、出は `tick` の
  戻り値の `storage`（書き込みの一覧 `[[key, val], …]`・書き込みがあった tick だけ・**release でも出る**・`public` の直後）。
  `boot` の核で書いた分は最初の `tick` の結果に載る（空にするのは返した後・`TRACE` と同じ）
- **プレリュードは写しを `pairs` で写さない**（禁止語）。`STORAGE_BASE`（参照のまま読むだけ）+ `STORE`（自分の書き込み）の
  2 段で、`get` は `STORE` → `RSTR(STORAGE_BASE[key])` → `""`。lupa は table、Wasmoon は proxy で届く
- **`num(str)` は受ける形を閉じてある**（expr.md §4.1: `str()` が出す形と JSON の数値の形だけ。それ以外は 0。`tonumber` は
  16 進・空白・`inf` を通すので先にパターンで弾く）。`storage.get` の `""`（無い鍵）は 0 になる
- **プレイヤーの `Player.store`（`Map`）が正**。すべての boot（最初から / 録画 / 差し替え / 再生）で写しを渡し、書き込みを
  反映して `localStorage` の `jin.storage:<manifest.file>` に丸ごと書き戻す。**再生はスクラッチ**（ヘッダの写しから始まり
  永続化しない。次の `reboot` で本物に戻る）。録画のヘッダ `storage` は録画の boot に渡した写し（非空のときだけ・版は 1 のまま・
  読み手は Python / TS とも object で値が文字列を検査し、壊れ fixture 2 本を両側で検算）。`jin run --input` は同じ写しで boot する
- 「記憶を消す」は `jin.control` の `forget`（語彙は 7 語のまま）と iframe の中のボタン。空にして boot し直す
- fixture は `tests/fixtures/v2-programs/storage.jin`（12 本目）。証拠は `packages/jin-wasm/tests/test_storage.py`
  （1 回目の記憶を 2 回目に渡すと続く）、`apps/player/e2e/storage.spec.ts`（`localStorage` に残り読み直しで続く →
  録画のヘッダの写しで `jin run --input` と全行一致 → 再生は上書きしない → 記憶を消す）、`apps/editor/e2e/v2.spec.ts`

Jin v2.1（文字入力）の要点（正典は `docs/spec/v2/abilities.md` §3、runtime.md §1.1 / §7、jil.md §1、設計書 §11 #53）:

- **ウィジェットではなく読み取り** `input.text() -> str`（read）。プレリュードは状態を持たず、`INPUTS.events` の `text` イベントをつなぐだけなので snapshot / resume に触らない。文字列を保つのはプログラムの `state`
- **入力スナップショットの形は変えない**（`events` に `{kind: "text", text}` が並ぶだけ）。reducer は Python （`InputState.apply`）と TS（`InputReducer`）の**両方に明示の分岐**が要る（TS は key 以外を pointer として扱っていた）。共有 fixture `tests/fixtures/jinrec/reducer.*` に text の行がある
- **集め手（`apps/player/src/input.ts`）は見えない `<input id="text">` にフォーカスを置く**（canvas は文字も IME も受けない）。合成中でない `input` と `compositionend` のたびに値を取り出して空にし（`event.data` は読まない）、制御文字と対にならないサロゲートを落とす。合成中のキーは集めず、入力欄からのキーは既定動作を止めない。`main.ts` のフォーカスは `collector.focus()` を通す
- **`.jinrec` の版は 1 のまま**（`EVENT_KINDS` に `text`・壊れ fixture `text-not-str` / `text-control`）。古い読み手は未知の kind を行番号付きで断る
- **プレリュードで `%c` を使わない**（`iscntrl` がロケールに従い、UTF-8 のロケールの lupa で非 ASCII を壊した。`tests/contract/test_jil_contract.py::test_the_prelude_does_not_use_locale_dependent_character_classes`）
- 証拠: `packages/jin-wasm/tests/test_codegen.py`（同じ tick の文字をつなぎ、`len` はコードポイント）、`apps/player/test/input.test.ts`（合成イベント・既定動作・落とす文字）、`apps/player/e2e/text_input.spec.ts`（打つ・`insertText` の非 ASCII・Backspace → 録画 → `jin run --input` と全行一致）

Jin v2.1（式の正準化）の要点（正典は `docs/spec/v2/expr.md` §8、model.md §9、設計書 §2.4 / §11 #15 / #48）:

- **正準化は `jin_core.canonical.dumps` の 1 か所**（規則 8）。schema の印 `x-jin-expr` を持つ欄（`jin_core.v2.model.expr_fields`・
  `functools.cache`）の式を `parse_expr` → `jin_core.v2.expr.unparse` で書き戻す。**欄を名前で書き写さない**（`jin_render.v2.layout` は
  紋章のハッシュに `Rite` 単体を `dumps` に渡すので、印で見分けないとそこで効かない）。v1 の `Text` に印は無いので v1 の出力は不変
- **読めない式は 1 文字も動かさない**（`canonical_expr` が `ExprSyntaxError` / 溢れた数値の `ValueError` を受けて元のまま）。
  JIN201 は `jin check` が出す。整形が入力を壊す経路は無い
- **括弧は優先順位と結合で要るときだけ**（`(a and b) or c` → `a and b or c`・`cmp` は連鎖しないので `(a < b) == c` は必須・
  `-(-x)` は読みやすさのため）。空白は演算子の両側と `,` `:` の後ろに 1 つ。数値は runtime.md §6 の `str(x)` と同じ書式
  （`format_number`。jin-core は jin-wasm を import できないので一致は `packages/jin-wasm/tests/test_prelude.py` が見る）。
  文字列は `encode_string`（`expr.py` からは関数内 import。`canonical` → `v2.expr` の循環を避ける）
- **`cast.target` も同じ規則**（`canvas . rect` → `canvas.rect`）。check は名前の形を要求するので整形前は JIN202、整形後は通る。
  整形が消す診断はこれだけ（`tests/contract/test_canonical_contract_v2.py` が固定）
- **エディタは式を解析しない**（設計書 §8 の原則のまま）。`ExprEditor` は Enter で確定した打ちかけを ref に覚え、打ち直していなければ
  `jin/applyOps` が返した正準形で draft を差し替える（揃えないと blur で同じ式を二重に確定し undo に積まれる）。
  `apps/editor/test/exprEditor.test.tsx` が `@testing-library/react` で固定する（初めてのコンポーネントテスト）
- 証拠: `packages/jin-core/tests/test_v2_canonical.py`（字面の規則・ランダム AST 3000 本の往復と冪等）、
  `tests/contract/test_canonical_contract_v2.py`（examples-v2 / v2-programs / errors/v2 の冪等と式の AST 保存・
  `tests/fixtures/canonical/v2/messy.jin` → `messy.expected.jin` のバイト一致）、`apps/editor/e2e/v2.spec.ts`
  （`score+ (1)` を Enter → `score + 1` → 保存が `jin fmt` と一致）。examples-v2 と fixture は元から正準だったので紋章のハッシュと
  SVG スナップショットは動いていない（動いたら印字器が正準な式を書き換えた合図）

Jin v2.1（鑑賞ページ）の要点（正典は `docs/spec/v2/stage.md`、設計書 `docs/superpowers/specs/2026-09-17-jin-stage-design.md`）:

- **配置の元は SVG だけ。** stage は `viewBox` を `[-1.25, 1.25]` に写すだけで座標を計算しない（`apps/stage/src/scene.ts`）。
  層は種別・陣の核の半径・ステップの深さから決める（`apps/stage/src/layers.ts` の表は stage.md と等号）。高さは層の値 × 陣の単位
  （`layerHeight`・層の group は陣ごと。掛けないと入れ子の小陣が塔になる）。`crown` / `crack` などの陣全体の演出は行の pointer の陣を光らせる（`effects.ts` の `glowTarget`）
- **絵は時刻の関数。** トレースを畳み込んで発火ごとの強さを決め（`effects.ts`。慣れの規則: 毎 tick の繰り返しは 0.15 の
  うなり、値が変わった `set` と一度きりの kind だけ強い）、時刻 `t` の光を返す。`src/` のうち `main.ts` 以外で
  `Math.random` / `Date.now` / `performance.now` / `new Date(` を使わない（乱数は `seq` を種にした mulberry32・契約テストが走査）。
  祖先へ遡るのは `/` 区切りの段一致（`names.ts` の `nearestInScene`。overlay の規則 1 と同じ）
- **`TraceRow.circle` は null になりうる**（`frame` 行・runtime.md §5）。stage は `frame` を読み飛ばして光らせない
- **書き出しは 1 コマずつ**（WebCodecs + Mediabunny 1.57.0・`exporter.ts`。実時間の録画はしない）。MP4（H.264）→ WebM（VP9）→ 不可。
  保証は場面の列までで、ピクセル一致は保証しない。ファイルは `stage.file` で親に渡し、**親がダウンロードさせる**。中止したら何も渡さない（仕上げの最中に押しても）。
  書き出しは押した瞬間の入力（トレース・構図・銘・範囲）の写しで描き、**途中で届いた `stage.scene` / `stage.trace` は種類ごとに最後の 1 つを
  取っておき、終わってから当てる**（1 本の書き出しの中で場面を変えない・`main.ts`）
- **線の太さは描画の高さに比例する**（`linewidth = 基準 × 高さ(CSS px) / 1080`・頭打ちなし）。three 0.186 の `LineSegments2` は
  `resolution` を CSS px のビューポートで上書きするので、プレビュー（倍率 2 など）と書き出し（出力の大きさ・倍率 1）で画面に対する太さが揃う。
  目視で決めた値（ブルーム・自発光・光線の上限など）は stage.md §7 に置き場所と根拠つきで並べてある。変えたら表も直す
- **エディタとの語彙は 4 語**（`stage.scene` / `stage.trace` / `stage.status` / `stage.file`）。書いてよいのは
  `apps/editor/src/stage/StagePanel.tsx` と `apps/stage/src/messages.ts` だけで、プレイヤーの 7 語とは混ざらない（契約テストが等号で固定）。
  `StagePanel` は同じ scene / trace を送り直さず（ref で直前の値を覚える・iframe を読み直したら送り直す）、stage は `stage.trace` を
  受けても巻き戻さない（今の tick を新しい範囲に収めるだけ。書き出しの範囲は人が打ち直していなければ全体へ広げる）
- **`jin editor` は `/stage/` を `/play/` と同じ規則で配る**（`translate_path` が 2 つの前置きを同じ正規化に通すので `/stage/../` で抜けない。
  `--stage-dist` > `apps/stage/dist` の順に探し、**同梱版は無い**。サブコマンドは 9 個のまま）。「鑑賞」モードでも実行パネルの iframe は
  外さない（鑑賞ページも `hidden` で隠すだけ）
- **API は記憶で書かない。** three 0.186.0 / Mediabunny 1.57.0 / WebCodecs の可否は
  `delivery/20260904-1445-jin/stage-api-probe.md`
- 単体テストは `apps/stage/test/`（fixture の `play.svg` はレンダラの出力と一致することを契約テストが見る。
  レイアウトを変えたら `uv run jin render examples-v2/paddle/paddle.jin --focus Play -o apps/stage/test/fixtures/play.svg`
  で作り直す）。e2e は `apps/stage/e2e/`（単独で PNG と 1 秒の動画を書き出して Node で読み戻す）と
  `apps/editor/e2e/stage.spec.ts`（録画を再生して鑑賞モードに行が届く）。防御を壊して赤くなることの実測は
  `delivery/20260904-1445-jin/stage-mutations/`（10 件。e2e は回さない）

Phase 6 の要点（正典は要件書 §7.2 / `docs/spec/layout.md` §7）:

- **サーバ側のプロトコルを増やさない。** トレース JSONL は**ブラウザ**が
  `<input type="file">` で読む（`apps/editor/src/trace/parse.ts`）。`jin/openTrace` のような
  リクエストを足すのは要件書 §6.3 の 4 種（+ ADR-011 の 2 種）への追加で人間承認が要り、
  `jin lsp --ws` の口も広がる（`tests/contract/test_editor_contract.py::test_the_debug_mode_does_not_add_a_new_lsp_request`）
- **TS 側で行の契約を二重に実装しない。** `parse.ts` が見るのは
  `jin_cli.main._read_trace_rows` と同じ範囲（`\n` 区切り / `\r` と BOM / 空行の読み飛ばし /
  JSON オブジェクトであること）だけで、`seq` / `pointer` の契約は `jin_render.overlay.read_trace` が持つ
- **フィルタの一致は overlay の規則 1 と同じ**（`jin_render.overlay.is_ancestor_or_same` の写し）。
  `/` 区切りの段一致であって前方一致ではない（`/circles/2` は `/circles/20/core` を拾わない）。
  referent 規則（`data-jin-ref`）は**使わない**
- **エディタは `data-jin-fired` / `data-jin-seq` を 1 つも書かない。** オーバーレイを描くのは
  `jin_render` 1 本で、同じ `upto` なら同じ SVG になる（machine 2）
- トレースは `ViewState` の**外**に置く（5 状態を増やさない）。編集しても保持される
- 壊れたトレースで**図を消さない**。`.jin` は壊れていないので `trace` を外して描き直し、理由を残す

## 開発コマンド

```bash
uv sync                                   # 依存を入れる
uv run pytest                             # 全テスト（ネットワーク・API キー不要）
uv run pytest packages/jin-core/tests     # jin-core だけ
uv run ruff check . && uv run ruff format .
uv run lint-imports                       # 依存方向の契約
uv run python scripts/generate_schema.py  # JSON Schema を再生成
uv run jin check examples                 # examples の診断
uv run jin fmt --check examples           # examples が正準形か
uv run jin check examples-v2 && uv run jin fmt --check examples-v2   # Jin v2 の例（examples/ の外に置く。設計書 §11 #18）
uv run jin schema --version 2             # Jin v2 の JSON Schema（CI が schemas/jin-v2.schema.json と diff する）
uv run jin run examples-v2/paddle/paddle.jin --ticks 300 --trace /tmp/t.jsonl --frames /tmp/f.jsonl   # Jin v2 のヘッドレス実行（lupa。標準出力は最後の公開 state）
uv run jin run examples-v2/paddle/paddle.jin --target wasm-gc --ticks 300 --trace /tmp/t.jsonl --frames /tmp/f.jsonl   # 同（wasm-GC を wasmtime で。trace / frames は Lua 経路とバイト一致）
uv run python scripts/generate_number_fixture.py --check   # 数値の書式の共有 fixture（tests/fixtures/numbers.jsonl）がずれていないか
uv run jin build examples-v2/fib/fib.jin --target wasm-gc --out /tmp/dist-gc   # game.wasm + game.manifest.json（target: "wasm-gc"）+ 同梱していれば index.html / player.js（--single も可）
uv run python scripts/generate_runtime_wat.py --check   # jin_wasmgc/runtime.wat が部品（packages/jin-wasmgc/runtime/）からの生成物とずれていないか
uv run python scripts/generate_tutorial_figures.py --check   # docs/tetris-tutorial.md の図（docs/images/tutorial/*.svg + ステップの表）が段階サンプルからの生成物とずれていないか（--check 無しで書き直す）
uv run jin run tests/fixtures/v2-programs/storage.jin --ticks 3 --storage /tmp/memory.json   # 同（記憶を実行をまたいで読み書き。2 回目は runs が 2）
uv run jin build examples-v2/paddle/paddle.jin --out /tmp/dist   # Jin v2 のバンドル（game.lua / game.manifest.json + 同梱していれば index.html / player.js / wasmoon.wasm）
uv run jin build examples-v2/paddle/paddle.jin --out /tmp/single --single   # 同（index.html 1 本。要 sync_player）
uv run python scripts/sync_player.py      # apps/player/dist を jin_wasm/player/ に同梱（--check でずれ検出・--remove で外す）
uv run jin render examples-v2/paddle/paddle.jin -o /tmp/p.svg              # Jin v2 の陣（root の額縁 + 入れ子の小陣）
uv run jin render examples-v2/paddle/paddle.jin --focus Play/step --trace /tmp/t.jsonl --upto 12   # 手順の図 + overlay（seq 0 始まり）
uv run jin build examples/researcher/researcher.jin --out /tmp/out   # ADK プロジェクト生成
PYTHONPATH=tests/fixtures/stubs uv run jin run examples/pipeline/pipeline.jin "go" --model fake --trace /tmp/t.jsonl
uv run jin render examples/researcher/researcher.jin -o /tmp/r.svg      # 魔法陣 SVG（-o 無しは stdout）
uv run jin render examples/pipeline/pipeline.jin --trace tests/fixtures/traces/pipeline-fake.jsonl --upto 5   # trace overlay
uv run jin lsp                            # LSP サーバ（stdio・Claude Code / VS Code 向け）
uv run jin lsp --ws 8765 --root .         # 同（WebSocket・ブラウザのエディタ向け。--root は jin/open / jin/save を許す範囲）
uv run python scripts/sync_plugin_reference.py          # プラグインの reference/ を正典から同期
uv run python scripts/sync_plugin_reference.py --check   # 同期がずれていたら exit 1（CI が走らせる）
claude plugin validate --strict plugins/claude-code/jin  # Claude Code プラグインの検証（CI の plugin job と同じ）
uv run python delivery/20260904-1445-jin/phase2-mutations/mutate_p2.py   # 防御を壊して赤くなることの実測（隔離コピー上で変異する・実ツリーは書き換えない）
uv run python delivery/20260904-1445-jin/phase3-mutations/mutate_p3.py   # 同上（Phase 3・jin-render）
uv run python delivery/20260904-1445-jin/phase4-mutations/mutate_p4.py   # 同上（Phase 4・jin-lsp）
uv run python delivery/20260904-1445-jin/phase5-mutations/mutate_p5.py   # 同上（Phase 5・apps/editor。pytest と pnpm の両方を回す）
uv run python delivery/20260904-1445-jin/phase6-mutations/mutate_p6.py   # 同上（Phase 6・デバッグモード）
uv run python delivery/20260904-1445-jin/issue9-mutations/mutate_i9.py   # 同上（Issue #9・symlink 走査 / ランディレクトリ解決 / uv allowlist）
cd apps/editor && pnpm install && pnpm build && pnpm lint && pnpm test && pnpm e2e   # エディタの全ゲート
cd apps/editor && pnpm demo               # README の Jin v2 デモ動画（docs/images/editor-v2-tetris-demo.gif / .mp4）を撮り直す（台本は demo/v2-tetris.spec.ts・自動操縦で遊ぶ・要 ffmpeg と apps/player の dist）
cd apps/editor && pnpm demo:fib           # チュートリアル動画（docs/images/editor-v2-fib-tutorial.gif / .mp4）を撮り直す（台本は demo/v2-fib-tutorial.spec.ts: 空の陣から fib.jin をバイト一致まで組む → 鑑賞モードの 3D → 実行 → 発動の演出を MP4 に書き出す。要 ffmpeg と apps/player / apps/stage の dist。共通部は demo/helpers.ts、変換は demo/encode.mjs <名前> [compact]。fib は 3D の粒で GIF が肥大するので compact）
cd apps/player && pnpm install && pnpm build && pnpm lint && pnpm test && pnpm e2e   # プレイヤーの全ゲート（e2e は実ブラウザで録画 → jin run --input → トレース一致。要 uv sync と pnpm build）
cd apps/stage && pnpm install && pnpm build && pnpm lint && pnpm test && pnpm e2e   # 鑑賞ページの全ゲート（e2e は WebGL と WebCodecs を実ブラウザで）
uv run python delivery/20260904-1445-jin/stage-mutations/mutate_stage.py   # 鑑賞ページの防御を壊して赤くなることの実測（隔離コピー上・pytest と pnpm の両方）
uv run jin editor examples/pipeline/pipeline.jin --no-browser            # 視覚エディタ（要 dist。URL を stderr へ）
uv run jin editor examples/showcase/showcase.jin --no-browser          # 同（9 種すべてが描かれる 3 本目の example）
uv run jin editor examples-v2/paddle/paddle.jin --no-browser          # Jin v2 の視覚エディタ（式エディタ + 実行パネル。要 apps/editor と apps/player の dist）
```

テスト配置は ADR-003（パッケージ単位の垂直分割 + 横断契約テスト）:

- `packages/<pkg>/tests/` — そのパッケージ単体
- `tests/spec/` — 要件書と `docs/spec/*.md` の突合
- `tests/contract/` — パッケージ横断契約（依存方向 / 正準形の往復無損失 / pointer 空間の一致）
- **`delivery/<ラン>/` を直書きしない**（DP-REVIEW-JIN-005）。`tests.conftest.delivery_run()` が
  `delivery/` から辞書順最新の `*-jin` を解決する。直書きが戻らないことは
  `tests/contract/test_packaging_contract.py::test_no_test_hardcodes_a_delivery_run_directory` が走査で固定する
- `tests/fixtures/errors/JINxxx_*.jin` — 各診断コードの fixture（**対応コードをちょうど 1 つだけ出す**）
- `tests/fixtures/build-errors/*.jin` — `jin check` は通るが `jin build` が落とす構造（NFR-FAIL-001）
- `tests/fixtures/stubs/` — examples の `ref` が指す `research.*` と、異常系テスト用の `exits_tool`（`sys.exit` を呼ぶツール）のスタブ
- `examples/` は **3 本**。`researcher` / `pipeline` は**要件書 §2.2 掲載**で、本文の JSON との一致を
  `tests/spec/test_spec_consistency.py::test_examples_match_requirements_section_2_2` が固定する
  （この 2 本は §2.2 を直さない限り増減しない）。`showcase` は Issue #5〜#7 の人手判定用に足した
  3 本目で、**`data-jin-kind` 9 種すべてを既定 focus で描く唯一のファイル**である
  （`tests/contract/test_render_contract.py::test_the_showcase_example_draws_all_nine_kinds`。
  9 種が揃う理由が消えていないことは `test_the_other_two_examples_lack_exactly_the_delegate_kind` が見る）。
  **design.yaml の machine 条件が言う「examples 2 本」は引き続き researcher / pipeline を指す**ので、
  スナップショット（`jin-render` / `jin-adk`）と machine 条件 5 の parametrize に showcase を足さない。
  showcase の `builtin` は `exit_loop` である（`google_search` は Gemini 以外のモデルを拒み、
  `--model fake` が `ValueError` で落ちる。委譲と同じ陣にも置けない・
  `tests/contract/test_cli_contract.py::test_the_showcase_example_runs_with_the_fake_model`）
- `tests/fixtures/traces/pipeline-fake.jsonl` — `jin run --model fake` の出力（11 行）。`jin-render` の
  テストは `jin_adk` を import できないのでこれを読む（実行結果との突合は `tests/contract/test_render_contract.py`）
- `docs/samples/tetris/` — 入門教材 `docs/tetris-tutorial.md` の段階サンプル 9 本（`01-canvas` … `09-tetris`。**最終段は
  `examples-v2/tetris/tetris.jin` とバイト一致**なので tetris.jin を直したら `09-tetris.jin` も同じに直す）。
  `tests/contract/test_docs_tetris_tutorial.py` が check / fmt / 90 tick の実行 / 本文の図がサンプルからの生成物と一致すること /
  12 ステップ・3 段の上限を見る。`examples-v2/` の本数（4 本）には数えない。**本文のコード例は JSON ではなく図**:
  `<!-- figure: <段階> <陣/手順> -->` … `<!-- /figure -->` の間（`jin render` の手順の図に番号ラベルを重ねた
  `docs/images/tutorial/*.svg` + 番号 → 記号 → Do → 内容の表）は `uv run python scripts/generate_tutorial_figures.py`
  の生成物で手で編集しない（`--check` を pytest が呼ぶ。ラベルの位置はレンダラの `place_block` / `geo.point` で求める）

## 書くときの約束

- **生成コードは編集しない。** `jin build` の出力（Phase 2 以降）はテンプレートを直して再生成する
- **テストはネットワークと API キーを必要としない。** モデル呼び出しはせず `FakeLlm` に差し替える（Phase 2）
- 正準形の規則は `jin_core.canonical` の 1 箇所にだけ実装する。Pydantic 設定や後処理へ分散させない
- 診断の行・列は **1 始まり・end 排他・コードポイント単位**。LSP（0 始まり / UTF-16）への変換は
  `jin-lsp` の 1 モジュールだけが行う（`docs/spec/diagnostics.md` §5.1）
- 具体値（しきい値・バージョン）を推測で置かない。要件書に無い値は決めた根拠を仕様書に残す

## `--resolve` と `jin run` の危険性（と `jin lsp --ws`）

`jin check --resolve` は `.jin` の `tools[].ref` / `boundary.guards[].ref` が指すモジュールを
**実際に import する**。Python の import は**モジュールのトップレベルを実行する**ので、これは
`.jin` を書いた相手に、このプロセスの権限で**任意のコードを実行させる**ことと同じである。

**`jin run` も同じ危険性を持つ。** 生成コードを一時ディレクトリ（`tempfile.mkdtemp`・0700）に書いて
import し、その生成コードが `ref` のモジュールを import する。`--model fake` はモデル呼び出しを
ネットワークに出さないだけで、`ref` の import は行う。import の実装は `packages/jin-adk/src/jin_adk/runtime.py` だけにある（`jin_core` には置かない）。
**cwd は `jin_adk.runtime` が `extra_sys_path` で頼まれたときだけ、生成モジュール（`agent.py`）の import の間だけ
`sys.path` の末尾に足し、import が終わったら（例外時も）`finally` で必ず外す**（`_sys_path_window`）。CLI の `run` が
`[os.getcwd()]` を渡し、CLI 自身は `sys.path` を触らない。Runner 実行中は cwd が `sys.path` に無い
（ライブラリとして呼ぶ側は渡さなければ cwd 解決を得られない）。`.jin` 由来の文字列**値**は `jin_adk.codegen.py_literal` で
必ず Python リテラルにしてからテンプレートへ渡し（式へ流れない）、識別子として埋め込むもの（circle 名 /
`builtin` 名 / `ref` のモジュール）は検査済み（`isidentifier()` + NFKC 正規形 + 予約語 / 予約名 / `check_ref_format`）
のものだけ。`.jin` の**ファイル名**も入力であり、ヘッダには `py_literal` を通して載せる。
安全主張は `guard: <関数名> -> <トークン>` 記法（危険な操作の所在は `hazard:`）で `jin_cli/main.py` /
`jin_adk/{build,runtime,codegen}.py` に書き、`tests/contract/test_guard_claims.py` が `packages/*/src` を走査して固定する。

- `--resolve` と **`jin run`** は**自分が中身を確認した `.jin` にだけ**使う。人から受け取ったファイル・
  CI で自動取得したファイル・LLM が生成したファイルには使わない（`--model fake` でも `ref` は import される）
- `jin run` は cwd を**生成モジュールの import の間だけ** `sys.path` の末尾に足し、import が終わったら必ず外す
  （DP-IMPL-JIN-P2-SYSPATH-01 の再々判断）。Runner 実行中は cwd が `sys.path` に無いので、ADK が LLM 要求のたびに
  遅延 import する**未インストール**の任意依存（`anthropic` / `openai` / `a2a` / `bcrypt` / `simplejson` / `chardet` /
  `socks` …）を cwd から解決させる経路は無い（security review F-S-P2-101。この経路を再び作らない）。
  **残存**: (1) import 窓の間は cwd のモジュール（`ref` 先・`builtin` の遅延 import 先。`google.adk.tools` が
  `mcp` などを探す窓を含む）がこのプロセスの権限で実行される。**信頼しないディレクトリを cwd にして `jin run` しない**。
  (2) `ref` 先のモジュールが自分の関数の中で実行時に遅延 import する名前は cwd から解決できない（`PYTHONPATH` に委ねる）
- ツール関数の `sys.exit()` は asyncio が `SystemExit` を**ループの外へ再送出**する（コルーチン側の
  `except BaseException` には `CancelledError` しか届かない）。`asyncio.run` を呼ぶ側（CLI の `run`・同期 `run_model`・
  Phase 4 の pygls）が `except SystemExit` で包んで失敗扱いにする（F-S-P2-102。`sys.exit(0)` を exit 0 にしない）
- **ディレクトリを渡したときの走査は symlink を対象にしない**（DP-REVIEW-JIN-001）。`Path.rglob` は
  ディレクトリ symlink こそ辿らないが**ファイル symlink は拾って読む**ので、`jin check <dir>` が
  対象ディレクトリの外にあるファイルを読み、その存在・パース可否・JSON のキー名を診断に載せていた。
  **名指しされた symlink は従来どおり読む**（走査が範囲を越えるのが問題であって、ユーザーが指したものではない）。
  飛ばしたことは 1 行出す。**残存**: 判定と読み取りの間には窓がある（TOCTOU）。`fmt` の書き込みは
  下位の `O_NOFOLLOW` / `os.replace` が競合なしで拒むが、読み取りにはその段が無い
- **v2 の `.jin` に `agent` の sigil があると、`jin run`（v2）はその v1 の `.jin` を v1 と同じ経路で走らせる**
  （`jin_cli.agents.AgentHost` → `jin_adk.runtime.run_model`。runtime.md §11・設計書 §11 #55）。つまり v1 の `ref` の
  import = S1 が v2 の `jin run` にも入る。`--model fake` でも `ref` は import される。`file` は対象の `.jin` の
  親ディレクトリの中に閉じ（リンクと外を拒む・`resolve_agent_file`）、`--input`（録画の再生）では v1 を呼ばない。
  **`agent` を持つ `.jin` も、自分が中身（v1 側も）を確認したものにだけ `jin run` する**。`jin_wasm` は v1 を
  知らず（`run_headless(answer=...)` で答える呼び出し可能を受けるだけ）、ブラウザのプレイヤーは答えない
- 既定（`--resolve` なし）では import は一切行わない。JIN040 が出ないだけで、他の診断は全部出る
- `--resolve` の import は **`ref` 1 件ごとに子プロセス**（`python -P -m jin_cli.resolver <ref>`）で行い、
  **30 秒**でタイムアウトする（ADR-018 / DP-JIN-RESOLVE-ISOLATION-01・値の根拠は `docs/spec/diagnostics.md` §2.1）。
  同一プロセスで import すると 1 ファイル目の `ref` が `jin_core.semantic.analyze` を差し替えて 2 ファイル目の
  本物の JIN060 を消せる（実測済み）。CLI は `SubprocessResolver` だけを使い、同一プロセスで import する
  `ImportResolver` は子の中でだけ動く。タイムアウト・子の異常終了・結果行の欠落はすべて JIN040（fail-closed）。
  `-P` で cwd を子の `sys.path` に足さない（cwd 解決経路を新設しない）。**子は同じ権限で走るので S1
  （任意コード実行）は残る**。汚染再現テストは `packages/jin-cli/tests/test_cli.py::test_check_resolve_isolates_files_from_each_other`
- `--resolve` の実装は `packages/jin-cli/src/jin_cli/resolver.py`（親 `SubprocessResolver` + 子 `ImportResolver`）だけにある。
  `jin_core` には置かない。`jin-lsp` は `jin_core` / `jin_render` に依存する（design.yaml rule 5）が、
  ws で公開されるコードパスから `jin_cli.resolver` と `jin_adk.runtime` へ**到達しない**ことを
  forbidden contract の `source_modules`（`jin_lsp` を含む）で機械化してある。
  **`jin_lsp` は `jin_adk` を依存にも持たない**ので二重の網になっている
- **`jin editor <file>` は `jin lsp --ws --root <file の親>` と同じ口を、`--root` を書かずに開く。**
  ビルド済みエディタを 127.0.0.1 で静的配信し、同じプロセスで LSP(ws) を起動してブラウザを開く。
  防御は下の `--ws` と同じ 4 段で、root は**対象ファイルの親ディレクトリだけ**。
  起動トークンは URL の**フラグメント**（`#token=`）で渡す（フラグメントは HTTP 要求にも
  `Referer` にも載らないので静的サーバのログにも出ない。残存: 履歴に残り、同一ページの JS は読める）。
  静的配信の根は `dist` に固定する（`directory=` を渡さないと cwd を配る）。
  **信頼しないディレクトリの `.jin` を `jin editor` で開かないこと**
- **`jin editor` は実行の口も開く**（Issue #34）。同じ静的サーバの `POST /run` が
  `python -P -m jin_cli.main run` を**子プロセス**で起こし、`--trace` の JSONL を tail して
  SSE で返す。`jin lsp --ws` にこの口は無い。防御は 5 段（`Origin` 検査 / カスタムヘッダ
  `X-Jin-Token` のトークン一致 / 対象ファイルの固定 / 同時 1 本 / 終了時に子を残さない）で、
  正本は `docs/spec/ops.md` §5.2。**トークンを body や query に置いてはいけない**
  （`Content-Type` 次第で simple request になり、preflight 無しで他オリジンから撃たれる。
  カスタムヘッダが preflight を強制することが防御の核心）。子に `-P` を付けるのは
  cwd を子の `sys.path[0]` に居座らせないため（F-S-P2-101 の経路を作らない）。
  **残存**: 子は同じ権限で走るので S1（任意コード実行）は残り、トークンを握った攻撃者は
  `jin/save` と組み合わせて連鎖を自力で完結できる
- **`jin lsp --ws PORT` はローカルに WebSocket の待ち受けを開く。** WebSocket には
  ブラウザの same-origin 制限が無いので、開いている任意のページが `ws://127.0.0.1:PORT` へ
  繋いでリクエストを打てる。ファイルを読み書きする `jin/open` / `jin/save`（ADR-011）は
  そのため **既定で無効**で、`--root <ディレクトリ>` を明示したときだけ、そのディレクトリ配下の
  `.jin` に限って有効になる。加えて起動トークン（起動時に stderr へ出す）の一致を要求し、
  書き先が symlink なら拒む。4 段の防御と残存（Origin 未検査）は `docs/spec/ops.md` §5.1 が正本。
  **hover は `ref` の docstring を出さない。** 出すには `ref` のモジュールを import する必要があり、
  hover のたびに任意コード実行になる（要件書 §6.2 からの意図的な逸脱・decision-conformance §2.25.6）
