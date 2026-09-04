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

**ADK の語彙が現れてよいのは `jin-adk` だけ。** `jin-adk` の中でも `google.adk` を import するのは
実行系（`fake_llm` / `loader` / `run`）だけで、コード生成（`codegen` / `project`）はテキストしか作らない
（`jin build` に ADK のロード＝数秒を強いないため）。`jin_cli` も `build` / `run` の**関数の中で**
`jin_adk` を import する。

- `jin-core` は他の `jin-*` に依存しない（最下層）
- **`jin-core` は `google-adk` に依存しない。** ADK の語彙は `jin-adk` 側にだけ現れる
- `apps/editor` は LSP プロトコルにのみ依存し、Python パッケージを直接 import しない

この一方向性は **import-linter** で機械的に落とす（`pyproject.toml` の `[tool.importlinter]`）。
`uv run lint-imports` がローカルでも CI でも走る。契約の正本は
`delivery/20260904-1445-jin/design.yaml` の `architecture.dependency_direction.rules`（8 行）。

`ref` を実際に import する実装（`ImportResolver`）は **`jin_cli` にだけ置く**。`jin_core` は
`RefResolver` プロトコルしか知らない。これも import-linter の forbidden contract
「ref の解決実装（任意コード実行）は jin_cli に閉じる」で落とす（下の「`--resolve` の危険性」を参照）。

### パッケージを足すときのチェックリスト

パッケージ名は `pyproject.toml` の複数箇所に現れる。**列挙を 1 つでも落とすと静かに壊れる**
（テストが収集されない / 契約が緩む）ので、`packages/<name>/` を作ったら次を全部直す:

1. `[project].dependencies` — ワークスペースの依存に足す
2. `[tool.uv.sources]` — `{ workspace = true }` を足す
3. `[tool.importlinter].root_packages` — 契約の対象にする
4. layers 契約の `layers` — **兄弟は 1 要素に `"jin_adk | jin_render"` と `|` 区切りで書く**
   （別要素に並べると実際の契約より強い順序を宣言してしまう）
5. forbidden 契約の `source_modules` — 「google-adk に依存しない」「resolver は jin_cli に閉じる」の
   対象に加える（`jin_cli` 自身は後者の対象外）
6. `packages/<name>/tests/__init__.py` — 無いと同名テストファイル 1 個でスイート全体が `Interrupted` になる
7. 共有 fixture は **`packages/<name>/conftest.py`**（`tests/` の 1 つ上）に置く。
   `packages/<name>/tests/conftest.py` に置くと**スイート全体が collection error で止まる**
   （6 で必須にした `tests/__init__.py` のせいで、リポジトリ直下の `tests/conftest.py` と
   どちらも `tests.conftest` に解決され、2 つ目の登録で `ValueError: Plugin already registered` になる）。
   しかも**パッケージ単体で走らせると緑**なので気づきにくい。テストモジュールからの
   `from .conftest import ...` も同じ理由で禁止（共有は fixture で渡す）

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
```

テスト配置は ADR-003（パッケージ単位の垂直分割 + 横断契約テスト）:

- `packages/<pkg>/tests/` — そのパッケージ単体
- `tests/spec/` — 要件書と `docs/spec/*.md` の突合
- `tests/contract/` — パッケージ横断契約（依存方向 / 正準形の往復無損失 / pointer 空間の一致）
- `tests/fixtures/errors/JINxxx_*.jin` — 各診断コードの fixture（**対応コードをちょうど 1 つだけ出す**）

## 書くときの約束

- **生成コードは編集しない。** `jin build` の出力はテンプレート（`jin_adk.codegen`）を直して再生成する
- **テストはネットワークと API キーを必要としない。** モデル呼び出しはせず `FakeLlm` に差し替える
  （`jin_adk.fake_llm`。`summon` の先まで差し替えること。`sub_agents` だけ辿ると `AgentTool` の
  内側に実モデルが残る）
- **ADK の実 API を記憶で書かない。** 正本は `delivery/20260904-1445-jin/adk-api-probe.md` と、
  実物に対して assert する `packages/jin-adk/tests/test_adk_surface.py`
- 正準形の規則は `jin_core.canonical` の 1 箇所にだけ実装する。Pydantic 設定や後処理へ分散させない
- 診断の行・列は **1 始まり・end 排他・コードポイント単位**。LSP（0 始まり / UTF-16）への変換は
  `jin-lsp` の 1 モジュールだけが行う（`docs/spec/diagnostics.md` §5.1）
- 具体値（しきい値・バージョン）を推測で置かない。要件書に無い値は決めた根拠を仕様書に残す

## `--resolve` の危険性（jin check）

`jin check --resolve` は `.jin` の `tools[].ref` / `boundary.guards[].ref` が指すモジュールを
**実際に import する**。Python の import は**モジュールのトップレベルを実行する**ので、これは
`.jin` を書いた相手に、このプロセスの権限で**任意のコードを実行させる**ことと同じである。

- `--resolve` は**自分が中身を確認した `.jin` にだけ**使う。人から受け取ったファイル・CI で自動取得した
  ファイル・LLM が生成したファイルには使わない
- 既定（`--resolve` なし）では import は一切行わない。JIN040 が出ないだけで、他の診断は全部出る
- 実装は `packages/jin-cli/src/jin_cli/resolver.py` の `ImportResolver` だけにある。
  `jin_core` には置かない（Phase 4 の `jin-lsp` は `jin_core` にしか依存しないので、
  ws で公開されるコードパスからこの実装へ到達できない）。この隔離は import-linter の
  forbidden contract で機械的に落とす

## `jin run` の危険性

`jin run` は `.jin` から生成したコードを一時ディレクトリへ書き出して **import する**（要件書 §3.4）。
生成コードは `tools[].ref` / `boundary.guards[].ref` が指すモジュールを import するので、
`jin check --resolve` と**同じ危険性**がある: `.jin` を書いた相手に、このプロセスの権限で
任意のコードを実行させることになる。

違いは「`jin run` は実行するためのコマンドなので、それが目的である」ことだけ。
出どころの分からない `.jin` には使わないこと。`--model fake` はモデル呼び出しを止めるだけで、
**`ref` の import は止めない**。

実装は `packages/jin-adk/src/jin_adk/loader.py` の 1 モジュールに閉じてある
（`jin_adk` の中で `importlib` を使うのはここだけ。`tests/contract/test_packaging_contract.py` が固定）。
