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
jin-core  ←  jin-adk / jin-render  ←  jin-lsp / jin-cli
```

Phase 2 時点で実在するのは `jin-core` / `jin-adk` / `jin-cli`。`jin-adk` は ADK の語彙
（LlmAgent / Runner / BaseLlm …）がリポジトリ内で現れてよい唯一のパッケージ。

- `jin-core` は他の `jin-*` に依存しない（最下層）
- **`jin-core` は `google-adk` に依存しない。** ADK の語彙は `jin-adk` 側にだけ現れる
- `apps/editor` は LSP プロトコルにのみ依存し、Python パッケージを直接 import しない

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

### パッケージを足すときのチェックリスト

パッケージ名は `pyproject.toml` の複数箇所に現れる。**列挙を 1 つでも落とすと静かに壊れる**
（テストが収集されない / 契約が緩む）ので、`packages/<name>/` を作ったら次を全部直す:

1. `[project].dependencies` — ワークスペースの依存に足す
2. `[tool.uv.sources]` — `{ workspace = true }` を足す
3. `[tool.importlinter].root_packages` — 契約の対象にする
4. layers 契約の `layers` — **兄弟は 1 要素に `"jin_adk | jin_render"` と `|` 区切りで書く**
   （別要素に並べると実際の契約より強い順序を宣言してしまう）。ただし**兄弟がまだ存在しない間は単独で書く**:
   存在しないパッケージを `|` で並べると import-linter 2.14 が `Missing layer` で EXIT 1 になる（Phase 2 で実測）。
   2 つ目を足すときに `|` に直す
5. forbidden 契約の `source_modules` — 「google-adk に依存しない」「任意コード実行の実装は `jin_cli.resolver` と
   `jin_adk.runtime` に閉じる」の対象に加える（`jin_cli` 自身は後者の対象外）
6. `packages/<name>/tests/__init__.py` — 無いと同名テストファイル 1 個でスイート全体が `Interrupted` になる
7. **依存する側の `packages/<x>/pyproject.toml`** の `dependencies` と `[tool.uv.sources]` — workspace の推移で
   手元では動いてしまうが、単体インストールで `ModuleNotFoundError` になる
   （`tests/contract/test_packaging_contract.py::test_every_package_declares_the_jin_packages_it_imports`）

`testpaths` は `packages` をディレクトリごと指すので追記は要らない。
1〜7 の抜けは `tests/contract/test_packaging_contract.py` が名指しで落とす。

## 実装の進み具合

| Phase | 内容 | 状態 |
|---|---|---|
| 0 | 仕様書 5 本 + examples 2 本 + 突合テスト | 実装済み |
| 1 | `jin-core` + `jin-cli`（check / fmt / schema / dump） | 実装済み |
| 2 | `jin-adk`（build / run / trace / FakeLlm） | 実装済み |
| 3 | `jin-render`（render / focus / trace overlay） | 未着手 |
| 4 | `jin-lsp`（stdio + ws）+ Claude Code プラグイン | 未着手 |
| 5–6 | `apps/editor`（編集モード / デバッグモード） | 未着手 |

`jin render` / `jin lsp` / `jin editor` は**まだ定義していない**。
空実装を先に置くと `jin --help` が嘘をつくので、未実装のものはサブコマンドごと存在させない。

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
uv run jin build examples/researcher/researcher.jin --out /tmp/out   # ADK プロジェクト生成
PYTHONPATH=tests/fixtures/stubs uv run jin run examples/pipeline/pipeline.jin "go" --model fake --trace /tmp/t.jsonl
uv run python delivery/20260904-1445-jin/phase2-mutations/mutate_p2.py   # 防御を壊して赤くなることの実測（隔離コピー上で変異する・実ツリーは書き換えない）
```

テスト配置は ADR-003（パッケージ単位の垂直分割 + 横断契約テスト）:

- `packages/<pkg>/tests/` — そのパッケージ単体
- `tests/spec/` — 要件書と `docs/spec/*.md` の突合
- `tests/contract/` — パッケージ横断契約（依存方向 / 正準形の往復無損失 / pointer 空間の一致）
- `tests/fixtures/errors/JINxxx_*.jin` — 各診断コードの fixture（**対応コードをちょうど 1 つだけ出す**）
- `tests/fixtures/build-errors/*.jin` — `jin check` は通るが `jin build` が落とす構造（NFR-FAIL-001）
- `tests/fixtures/stubs/` — examples の `ref` が指す `research.*` と、異常系テスト用の `exits_tool`（`sys.exit` を呼ぶツール）のスタブ

## 書くときの約束

- **生成コードは編集しない。** `jin build` の出力（Phase 2 以降）はテンプレートを直して再生成する
- **テストはネットワークと API キーを必要としない。** モデル呼び出しはせず `FakeLlm` に差し替える（Phase 2）
- 正準形の規則は `jin_core.canonical` の 1 箇所にだけ実装する。Pydantic 設定や後処理へ分散させない
- 診断の行・列は **1 始まり・end 排他・コードポイント単位**。LSP（0 始まり / UTF-16）への変換は
  `jin-lsp` の 1 モジュールだけが行う（`docs/spec/diagnostics.md` §5.1）
- 具体値（しきい値・バージョン）を推測で置かない。要件書に無い値は決めた根拠を仕様書に残す

## `--resolve` と `jin run` の危険性

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
- 既定（`--resolve` なし）では import は一切行わない。JIN040 が出ないだけで、他の診断は全部出る
- `--resolve` の import は **`ref` 1 件ごとに子プロセス**（`python -P -m jin_cli.resolver <ref>`）で行い、
  **30 秒**でタイムアウトする（ADR-018 / DP-JIN-RESOLVE-ISOLATION-01・値の根拠は `docs/spec/diagnostics.md` §2.1）。
  同一プロセスで import すると 1 ファイル目の `ref` が `jin_core.semantic.analyze` を差し替えて 2 ファイル目の
  本物の JIN060 を消せる（実測済み）。CLI は `SubprocessResolver` だけを使い、同一プロセスで import する
  `ImportResolver` は子の中でだけ動く。タイムアウト・子の異常終了・結果行の欠落はすべて JIN040（fail-closed）。
  `-P` で cwd を子の `sys.path` に足さない（cwd 解決経路を新設しない）。**子は同じ権限で走るので S1
  （任意コード実行）は残る**。汚染再現テストは `packages/jin-cli/tests/test_cli.py::test_check_resolve_isolates_files_from_each_other`
- `--resolve` の実装は `packages/jin-cli/src/jin_cli/resolver.py`（親 `SubprocessResolver` + 子 `ImportResolver`）だけにある。
  `jin_core` には置かない。Phase 4 の `jin-lsp` は `jin_core` / `jin_adk` / `jin_render` に依存できる
  （design.yaml rule 5）ので、ws で公開されるコードパスから `jin_cli.resolver` と `jin_adk.runtime` を
  **import しない**ことを Phase 4 の契約で機械化する（`phase2-handoff.md` §6: forbidden contract の
  `source_modules` に `jin_lsp` を足す）。現在の forbidden contract は `jin_core` / `jin_adk` からの到達を落とす
