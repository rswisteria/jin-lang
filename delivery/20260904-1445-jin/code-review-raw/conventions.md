# Stage 5 review: conventions — 実装ラウンド 1（Jin Phase 0+1）

レビュー実施: 2026-09-04 / 観点: conventions（規約準拠・命名衝突・プロジェクト規約との整合）
判断材料: コード・生成物・`delivery/` の成果物のみ。実装者の報告・コメント・rationale は未検証の主張として扱った。

## Summary

- **finding 総数: 21 件**
- **confidence 90 以上: 4 件**（A-1 / A-2 / A-3 / C-1）
- **節ごとの内訳**

| 節 | 主題 | 件数 | high | medium | low |
|---|---|---|---|---|---|
| A | 拡張性（後続 4 ラウンドで壊れる決め打ち） | 6 | 2 | 3 | 1 |
| B | 規約準拠（要件書 §1.1 / §1.2） | 3 | 0 | 1 | 2 |
| C | ドキュメントと実装の乖離 | 4 | 0 | 2 | 2 |
| D | テスト配置規約（ADR-003） | 6 | 0 | 2 | 4 |
| E | 日本語ドキュメントの体裁 | 1 | 0 | 0 | 1 |
| G | 実行環境の版固定（親からの追加確認事項） | 1 | 0 | 1 | 0 |
| 合計 | | **21** | **2** | **9** | **10** |

- **指摘なしで PASS を確認した項目**
  - 要件書 §8 末尾が指定する CLAUDE.md の 4 点は**全て書かれている**。パッケージ境界 `CLAUDE.md:21-33` / `uv run pytest` `CLAUDE.md:53` / `schemas/jin.schema.json` と `docs/spec/*.md` が正典 `CLAUDE.md:5-15` / 生成コードは編集しない `CLAUDE.md:71`。
  - 命名の一貫性は**三者（コード・仕様書・テスト）で完全に一致**。診断コード 14 件（正典 12 + 提案 2）が `diagnostics.py:72-92` / `docs/spec/diagnostics.md` §2-3 / `tests/fixtures/errors/*.jin` 14 本 / `semantic.py`+`check.py` の emit 箇所で一致。意味オペレーション 19 件が `ops.py:426-445` / `docs/spec/ops.md` §2 / 要件書 §6.3 で一致。`data-jin-kind` 9 種が `docs/spec/layout.md:71-81` と要件書 §2.5 で一致。JSON キー語彙 12 行が `docs/spec/adk-mapping.md` と要件書 §2.1 で一致。
  - design.yaml `implementation_phases.items[0]` の deliverables 8 件、`items[1]` の 4 件とも**過不足なく実在**。
  - コード中の FR/NFR ID（`FR-ARCH-002` `NFR-DEP-001` `FR-MODEL-001` `NFR-TEST-001` `NFR-DET-002` `NFR-SSOT-001` `FR-CLI-002` ほか）は全て `requirements.json` に実在。
  - `decision-conformance.md` の「全 225 テスト」は実測 225（`pytest --collect-only` で確認）で正確。
  - 依存バージョンは全て実在・実インストール済み（pydantic 2.13.5 / lark 1.3.1 / typer 0.27.2 / pytest 9.1.1 / ruff 0.16.6 / import-linter 2.14）。`version-matrix.md` の実測記録は信頼できる。
  - README の使用例 5 行のうち 4 行はそのまま動作（`check` / `fmt --check` / `schema` / `dump` を実行して確認）。
  - 括弧の表記は統一されている（後述 E-2）。全テスト 225 件が緑。

- **作業ツリーへの変更: 残していない**
  - A-1 の再現のため `packages/jin-cli/tests/test_model.py` を一時作成したが、削除済み。`__pycache__` も除去済み。`git status --short` で確認し、レビュー開始時と同一の状態（`delivery/design.yaml` と `implement-ledger.md` が M、それ以外は実装一式が `??`）。

- **前提（親への申し送り）**
  - レビュー対象は**ワーキングツリー**。`git status` 上、実装一式（`packages/` `tests/` `docs/spec/` `schemas/` `pyproject.toml` `CLAUDE.md` `README.md` `.github/`）は全て untracked で、HEAD は `f6a37e0 first commit`（要件書のみ）。コミットは存在しない。

---

## A. 拡張性 — 後続 4 ラウンドで壊れる決め打ち

### A-1 [severity: high / confidence: 95] `packages/*/tests/` に `__init__.py` が無く、テストファイル名が衝突するとコレクション全体が中断する

`packages/jin-core/tests/` と `packages/jin-cli/tests/` には `__init__.py` が無い（`tests/` `tests/spec/` `tests/contract/` には有る）。pytest の既定 importmode は `prepend` なので、`__init__.py` の無いテストディレクトリではモジュール名 = ファイル basename になり、**全パッケージ横断で basename がグローバルに一意でないといけない**。

実測で再現。`packages/jin-cli/tests/test_model.py` を置いて `uv run pytest` を実行すると:

```
ERROR collecting packages/jin-cli/tests/test_model.py
import file mismatch:
imported module 'test_model' has this __file__ attribute:
  /Users/toyota/PycharmProjects/jin-lang/packages/jin-core/tests/test_model.py
which is not the same as the test file we want to collect:
  /Users/toyota/PycharmProjects/jin-lang/packages/jin-cli/tests/test_model.py
HINT: remove __pycache__ / .pyc files and/or use a unique basename for your test file modules
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
```

1 ファイルの名前衝突で**スイート全体が Interrupted** になる（該当ファイルだけスキップされるのではない）。既存の basename は `test_model.py` `test_check.py` `test_parser.py` `test_canonical.py` `test_ops.py` `test_schema_export.py` `test_cli.py` で、`jin-adk` / `jin-render` / `jin-lsp` が自然に付けたくなる名前（`test_model.py`、`test_ops.py`、`test_parser.py`、`test_check.py`）と正面から重なる。

修正はどちらか一方で足りる: 各 `packages/*/tests/` に空の `__init__.py` を置く（`tests/` 側と規約が揃う）か、`pyproject.toml` に `[tool.pytest.ini_options] importmode = "importlib"` を足す。ADR-003 は「パッケージ単位の垂直分割」を採ったのに、その分割が成立するための前提が抜けている。

> 親が独立に再現して確認済み。

### A-2 [severity: high / confidence: 95] パッケージ一覧が `pyproject.toml` に 5 箇所ハードコードされている

`[tool.uv.workspace] members = ["packages/*"]`（`pyproject.toml:15`）だけが glob で、他は全て列挙:

| 箇所 | 行 | 内容 |
|---|---|---|
| `[project] dependencies` | `pyproject.toml:6-9` | `jin-core` / `jin-cli` |
| `[tool.uv.sources]` | `pyproject.toml:17-19` | 同上 |
| `[tool.pytest] testpaths` | `pyproject.toml:32` | `packages/jin-core/tests`, `packages/jin-cli/tests` |
| `[tool.importlinter] root_packages` | `pyproject.toml:45` | `jin_core`, `jin_cli` |
| `importlinter.contracts[0] layers` | `pyproject.toml:51-54` | 2 層 |

`testpaths` については `["tests", "packages"]` にすれば追随不要になる（pytest は `packages/*/tests/` を再帰収集する）。他の 4 箇所は uv / import-linter の仕様上どうしても列挙が必要だが、**Phase 2 で 4 箇所を同時に直す必要がある**ことがどこにも書かれていない。`CLAUDE.md` の「実装の進み具合」表（`CLAUDE.md:37-44`）に、パッケージ追加時のチェックリストとして明記するのが妥当。

### A-3 [severity: medium / confidence: 90] Phase 2 着手時に A-1 と A-3 で 2 種類の失敗が同時に出る

`tests/contract/test_dependency_direction.py:125-131` の `test_later_packages_do_not_exist_yet` は `packages/jin-adk` が現れた瞬間に赤くなる意図的なトリップワイヤで、docstring にその旨が書かれている（設計として妥当）。ただし A-1 の名前衝突は **collection 段階で全スイートを止める**ため、Phase 2 の実装者は「トリップワイヤが赤い」ではなく「テストが 1 件も走らない」状態から始めることになる。トリップワイヤの docstring（`:127-130`）に、パッケージ追加時にやることとして A-2 の 4 箇所と A-1 を併記しておくと、意図した誘導が機能する。

### A-4 [severity: medium / confidence: 60] import-linter が design.yaml の 8 ルールのうち 2 本しか機械化していない（かつ兄弟関係を表現できない形）

`design.yaml:140-148` の 8 ルールに対し、現状の契約は 2 本（`pyproject.toml:48-60`）:

- ルール 1（jin-core は他の jin-\* に依存しない）→ `layers = [jin_cli, jin_core]` で部分的に担保
- ルール 2（jin-core は google-adk に依存しない）→ `forbidden` で担保。違反注入テスト（`test_dependency_direction.py:76-104`）で実効性も確認済み

ルール 3〜6 は対象パッケージが未存在なので現時点で機械化不能、ルール 7（apps/editor）は `test_editor_contract_is_not_yet_enforced`（`:134-143`）で未対応であることを明示、ルール 8 は DP 未決 —— ここまでは正直で良い設計。

懸念は形式のほう。ルール 3 / 4 は「jin-adk と jin-render は互いに依存しない」という**兄弟独立性**を含むが、import-linter の `layers` 契約は単純なリストでは兄弟を表現できず、同一層に置くには `layers` 要素内の `:` 区切り（`jin_adk : jin_render`）か `independence` 契約の併用が要る。今の 2 層リストをそのまま伸ばすと、`layers = [jin_cli, jin_lsp, jin_adk, jin_render, jin_core]` のような**実際の契約より強い順序**を書いてしまい、jin-adk → jin-render の誤った依存が通る／通らないが偶然で決まる。`CLAUDE.md:31-33` が「契約の正本は design.yaml の 8 行」と宣言している以上、最終形の契約構造を今のうちにコメントで書き置いたほうが安全。

### A-5 [severity: medium / confidence: 55] CLI サブコマンドが単一モジュール + トップレベル import で登録されている

`packages/jin-cli/src/jin_cli/main.py` は 4 コマンドを `@app.command()` で直接登録し、`jin_core.*` をモジュールトップで import している（`main.py:26-29`）。Phase 2 以降で `jin build` / `jin run` / `jin render` / `jin lsp` / `jin editor` の 5 コマンドが加わると、`jin --help` を打つだけで `jin_adk`（→ `google-adk` → Jinja2）と `jin_lsp`（→ pygls）が全部ロードされる。

依存方向としては違反ではない（jin-cli は最上層で、design.yaml ルール 6 が明示的に許可）。問題は起動コストと `main.py` の肥大。typer には `app.add_typer()` があるので、`jin_cli/commands/{check,fmt,build,render,lsp}.py` に分割して遅延 import する形が Phase 2 で必要になる。`main.py:1-16` の docstring が「未実装コマンドはサブコマンドごと存在させない」という方針を丁寧に書いているのは良いが、**どう足すか**は書かれていない。

### A-6 [severity: low / confidence: 45] `jin_core/__init__.py` が実質空で、公開 API の境界が宣言されていない

`packages/jin-core/src/jin_core/__init__.py:1` は `from __future__ import annotations` の 1 行のみ。各モジュール（`model.py:128` / `diagnostics.py:112` / `ops.py:480` 等）は `__all__` を丁寧に定義しているのに、パッケージレベルでは何も再エクスポートしていない。結果として消費者は `from jin_core.check import check_file` のように**内部モジュール構成に直接依存**する。

design.yaml `boundary_contracts` は jin-core が外へ出す境界を「意味モデル / JSON Pointer / 診断 / 意味オペレーション」の 4 本と定義している。この 4 本を `jin_core/__init__.py` の `__all__` として明示すれば、Phase 2〜4 の 3 パッケージが内部モジュールの再配置に巻き込まれなくなる。現状は 2 パッケージなので実害が出ていないだけ。

---

## B. 規約準拠（要件書 §1.1 / §1.2）

### B-1 [severity: medium / confidence: 70] syrupy が dev 依存に無い

要件書 §1.1（`jin-requirements.md:57`）はテスト基盤を「pytest、syrupy、pytest-lsp、Playwright」と定めており、design.yaml も 2 箇所（`design.yaml:62` / `design.yaml:112`）で syrupy を挙げている。`version-matrix.md:67` は syrupy 6.0.0 を実測済みで、用途 Phase を「3」と記録している。しかし `pyproject.toml:23-27` の dev グループには入っていない（実測: `importlib.metadata` で MISSING）。

Phase 1 の machine 条件「`jin dump` の JSON スナップショットが安定」は、`tests/contract/test_cli_contract.py:53-63` で `PYTHONHASHSEED` を変えた別プロセス 2 回の出力比較として実装されている。これは**決定性の検証**であり、要件書 §9 が「モデル｜`jin dump` の JSON スナップショット」と書いている**保存済みスナップショットとの突合**ではない。実装としては前者のほうが辞書順序依存を検出できて優れているが、§1.1 の技術選定に対する逸脱であることは事実で、`version-matrix.md` が syrupy を「Phase 3 用」と読み替えた根拠は要件書側にない（§9 はモデル・コード生成・レンダラの 3 箇所でスナップショットを要求している）。

### B-2 [severity: low / confidence: 55] `jin-requirements.md` がリポジトリ直下にあり、§1.2 の構成表に無い

要件書 §12 は「この文書を `docs/superpowers/specs/2026-09-04-jin-overview.md` に置いてコミット」と指示し、§1.2 のリポジトリ構成表にも `jin-requirements.md` は現れない。実際には両方に同一内容が置かれ、`CLAUDE.md:9` がルート側を正典と宣言、`tests/spec/test_spec_consistency.py:127-132` がバイト一致を担保している。

二重管理そのものはテストで守られているので実害はないが、§1.2 に無いファイルがルートに増えていることと、これが C-2 の原因になっている点は指摘しておく。

### B-3 [severity: low / confidence: 40] `ruff check` が実質ノーオペレーション

`[tool.ruff]`（`pyproject.toml:35-40`）に `[tool.ruff.lint]` の `select` が無い。ruff の既定 select は `E4, E7, E9, F` のみで、import 整列（`I`）も行長（`E501`）も pyupgrade（`UP`）も効いていない。`line-length = 100` はフォーマッタにしか効かないので、CI の `uv run ruff check .`（`ci.yml:27`）はほぼ構文エラー検出だけ。要件書 §1.1 が名指ししているのは `ruff format` なので規約違反ではないが、CI ステップ名が "Lint" である以上、実効範囲が期待とずれている。

---

## C. ドキュメントと実装の乖離

### C-1 [severity: medium / confidence: 92] `version-matrix.md:77` が実在しないファイルを「自作した」と記録している

> `jin_core/grammar/jin_json.lark` を自作した

このファイルもディレクトリも存在しない（`find packages -name "*.lark"` → 0 件）。実際の文法は `packages/jin-core/src/jin_core/parser.py:33` のインライン raw 文字列定数 `JIN_JSON_GRAMMAR` で、`parser.py:52-53` の `Lark(JIN_JSON_GRAMMAR, ...)` に渡されている。`parser.py:212` の `__all__` にも公開されている。

インライン定数にしたこと自体は妥当な選択（`hatchling` の wheel に `.lark` を同梱する `force-include` 設定が不要になる）。問題は、`version-matrix.md` が「一次証拠に基づく実測記録」を名乗る文書であるのに、実装の所在を誤記している点。この文書は後続 4 ラウンドの実装者が最初に読む依存情報の正本なので、Phase 4 で LSP が文法を差し替えるときに存在しないパスを探すことになる。該当セルを `jin_core/parser.py:JIN_JSON_GRAMMAR` に訂正すべき。

なお、この誤記は `version-matrix.md:77` の 1 箇所だけ（`implementation-notes.md` / `docs/spec/*.md` / `CLAUDE.md` には出てこない）。

### C-2 [severity: medium / confidence: 85] ruff の除外設定が非対称で、`ruff format .` が正典の要件書を書き換えうる

`pyproject.toml:40` の `extend-exclude = ["delivery", "docs", ".venv"]` は `docs/` を除外するが、リポジトリ直下の `jin-requirements.md` は除外されない。

ruff 0.16.6 は Markdown 内の Python コードブロックを実際にフォーマットする（実測: `x=1` を含む `.md` に `ruff format` → "1 file reformatted"、`x = 1` に書き換わることを確認）。`pyproject.toml:38-39` のコメントが主張する挙動は正しく、この点で実装者の rationale は裏付けられている。

しかし帰結として:

- `jin-requirements.md` は §3.2 に ```python ブロックを持つ（生成コードの例）
- その完全同一コピー `docs/superpowers/specs/2026-09-04-jin-overview.md` は `docs/` 配下なので除外される
- `CLAUDE.md:55` は開発者に `uv run ruff format .` を実行させる

つまり、要件書の Python ブロックが将来 ruff の整形結果と 1 バイトでもずれた時点で、`ruff format .` が**人間が書いた正典側だけを書き換え**、`test_requirements_copies_are_identical`（`test_spec_consistency.py:127`）が赤くなる。CI の `ruff format --check .`（`ci.yml:28`）も落ちる。

現状は両方とも "already formatted" なので潜在的だが、`extend-exclude` に `jin-requirements.md` を加える（= 2 つの写しを同じ扱いにする）だけで解消する。そもそも人間が書いた要件書を自動整形の対象にすべきではない。

### C-3 [severity: low / confidence: 35] GitHub Actions の版は実在するが 3 メジャー遅れ

`version-matrix.md:83` は `actions/checkout@v4` と `astral-sh/setup-uv@v5` を「記憶で書いた値・未検証・PR で CI が初めて走るときに落ちる可能性がある」と記録し、`DP-JIN-GHA-VERSION-UNVERIFIED` として親へ確認要求を上げている。

`git ls-remote --tags` で実測したところ、**両方とも v7 が最新で、v4 / v5 のタグも実在**する（GitHub API は rate limit だったので ls-remote で確認）。したがって `ci.yml:12` / `ci.yml:15` が原因で CI が落ちることはない。「未検証・落ちる可能性」という記録は解消してよく、残る論点は「3 メジャー古い版を使い続けるか」だけ。Node 20 系ランタイムの deprecation 警告は出るはず。

### C-4 [severity: low / confidence: 30] README の `a.jin` はそのままでは動かない

`README.md:14` の `uv run jin check --json a.jin` を実行すると `ファイルがありません: a.jin` で exit 2 になる（`main.py:48-49`）。プレースホルダとして読めば問題ないが、同じブロックの他 4 行が全て実行可能なコピペ可能コマンドなので、この行だけ粒度が違う。`examples/researcher/researcher.jin` にすれば揃う。

---

## D. テスト配置規約（ADR-003）

### D-1 [severity: medium / confidence: 80] パッケージ単体テストがリポジトリ直下の成果物を読んでいる

ADR-003（`docs/adr/ADR-003-DP-COMMON-09.md:24`）は「パッケージ横断の契約はどの単一パッケージにも属さないため `tests/contract/` に置く」と定め、`CLAUDE.md:62-67` は `packages/<pkg>/tests/` を「そのパッケージ単体」と規定している。以下がこの規約から外れている:

- `packages/jin-core/tests/test_ops.py:91-100` — `Path(__file__).resolve().parents[3] / "docs" / "spec" / "ops.md"` を読んで `OPERATIONS` と突合。これは `tests/spec/test_spec_consistency.py:203-208` の `test_ops_match_requirements` とほぼ同じ検査で、しかも要件書ではなく仕様書とだけ突合しているので冗長。`parents[3]` はディレクトリ階層のハードコードでもある。
- `packages/jin-core/tests/test_model.py:100-106` — `parents[3] / "examples/*/*.jin"` を読んで `JinFile.model_validate`。`tests/conftest.py:38-40` に `example_paths` fixture があるのに使っていない。

どちらも `tests/spec/` か `tests/contract/` へ移すのが規約どおり。放置すると Phase 3 以降で「どこに書けばいいか」の判断基準が消える。

### D-2 [severity: medium / confidence: 75] machine-readable マーカー 17 個中 8 個に消費者が無く、`model.md` の主要な表がテストされていない

`docs/spec/*.md` の各文書は §0 で「機械が読む表・箇条書きは直前に `<!-- machine-readable: <ID> -->` マーカーを置く」という契約を宣言している（例: `docs/spec/model.md:10`）。定義されたマーカーは 17 個だが、テストが読んでいるのは 9 個だけ。

消費者の無い 8 個: `root-keys` / `circle-keys` / `tool-kinds` / `guard-on-values` / `reference-edges` / `upstream-rule` / `canonical-rules`（以上 `model.md`）/ `rename-cascade`（`ops.md`）。

このうち `model.md` の 4 つは、正準形のキー順という**破ると出力バイト列が変わる**性質を記述しているので影響が大きい。手作業で `model.py` と突合したところ、現時点では完全に一致していた:

| マーカー | model.md | model.py | 判定 |
|---|---|---|---|
| `root-keys` | `$schema` / `version` / `root` / `circles` | `JinFile`（`model.py:118-125`） | 一致 |
| `circle-keys` | name / core / description / instruction / tools / delegate / state / flow / boundary | `Circle`（`model.py:104-115`） | 一致（順序も） |
| `tool-kinds` | tool→ref / builtin→builtin / summon→circle | `ToolFunction` / `ToolBuiltin` / `ToolSummon`（`model.py:48-72`） | 一致 |
| `guard-on-values` | before/after × agent/model/tool の 6 値 | `GuardOn`（`model.py:19-26`） | 一致（順序も） |

つまり**現状はドリフトしていない**が、それを守る仕組みが無い。`packages/jin-core/tests/test_model.py:81-97` の `test_field_order_matches_spec` は docstring に「`docs/spec/model.md` §3 の表の順であること」と書きながら、実際には表を読まず期待値リストをコード内にハードコードしている。マーカーが既に置いてあるのだから、`machine_block()` で読んで突合するだけで済む。8 個のマーカーが「機械可読と宣言されているが誰も読まない」状態は、次のラウンドで「マーカーは飾り」という誤った学習を与える。

### D-3 [severity: low / confidence: 50] 突合テストの要件書側パーサが散文の言い回しに依存している

design.yaml `implementation_phases.items[0].note` は「テストは Markdown を機械可読な形で読むため、docs/spec/\*.md の該当箇所はパースしやすい定型で書く」ことを Phase 0 の執筆制約としている。**`docs/spec/*.md` 側はこの制約をきちんと守っており**（マーカー + 表の形式が全文書で統一されている）、`table_rows()`（`test_spec_consistency.py:49-64`）も行頭 `|` を見るだけの素直な実装で脆くない。

脆いのは**要件書側**を読む 4 関数。要件書は Phase 0 の成果物ではなく人間が書いた上流文書なのでマーカーが打てず、散文を正規表現で削っている:

- `req_ops()`（`:97-101`）— `ln.startswith("オペレーション(v1):")` で行を特定し、`line.split("。各オペレーションは", 1)[0]` で末尾を切る。この日本語の言い回しが変わると `split` は**例外を出さず行全体を返し**、後続の `findall` が余分な項目を拾う。件数 assert（`:205`）が受け止めるので沈黙はしないが、失敗メッセージは原因を指さない。
- `req_ring_radii()`（`:104-107`）— 「環の半径は固定」を含む行を探し `(instruction|tools|state|boundary) (\d\.\d+)` で抽出。
- `req_data_jin_kinds()`（`:110-114`）— 要件書**全文**への `re.search(r'data-jin-kind="([^"]+)"', text)` で、最初のヒットだけを使う。要件書の別箇所に同属性の例が増えると静かに間違ったものを読む。
- `section()`（`:32-46`）の停止条件が `r"^各コードに fixture"` `r"^circle は 2 種類"` `r"^形式上の決定事項"` という本文の書き出し。

`first_code_span()`（`:78-81`）の「バッククォートが無ければセルをそのまま返す」フォールバックも、比較対象が食い違ったときに読みにくい差分を出す。今は全テストが通っているので実害はないが、「要件書を 1 文字直すと突合テストが落ちる（しかも理由が読み取りにくい）」構造であることは、この設計の代償として記録しておくべき。

### D-4 [severity: low / confidence: 40] import-linter 契約の存在確認が日本語の契約名に対する assert

`tests/contract/test_dependency_direction.py:62-68` は `any("一方向" in n for n in names)` / `any("google-adk" in n for n in names)` と、`pyproject.toml:49,57` に書かれた**人間向けの契約名文字列**を検査している。契約名を推敲するだけでテストが落ち、逆に名前だけ残して `type` や `layers` を壊しても通る。`type` / `layers` / `source_modules` / `forbidden_modules` の構造を見るべき（実効性は `:76-104` の違反注入テストが担保しているので、severity は低い）。

### D-5 [severity: low / confidence: 35] `tests/contract/test_cli_contract.py:16` が conftest をモジュールとして import している

`from tests.conftest import UNFORMATTABLE_CODES, fixture_code`。`tests/__init__.py` があるので動くが、conftest は fixture 提供の場であって import 対象ではないのが一般的な規約。共有定数は `tests/_helpers.py` のような通常モジュールへ出すほうが、`tests/` を package にしている前提（= A-1 の非対称性）への依存も減る。

### D-6 [severity: low / confidence: 30] 実行ファイルのパス組み立てが POSIX 前提

`tests/contract/test_dependency_direction.py:30` の `Path(sys.executable).parent / "lint-imports"` と `tests/contract/test_cli_contract.py:19` の `Path(sys.executable).parent / "jin"` は Windows（`Scripts/` かつ `.exe`）で解決しない。CI は ubuntu-latest 単体（`ci.yml:10`）で開発は darwin なので現状問題ないが、`shutil.which()` を使えば移植性の心配が消える。なお `test_dependency_direction.py:16` の `import shutil` は `copytree` 用に既に入っている。

---

## E. 日本語ドキュメントの体裁

### E-1 [severity: low / confidence: 35] 言語指定の無いコードフェンスが 3 箇所

`CLAUDE.md:23`（パッケージ境界の図）、`README.md:22`（構成ツリー）、`docs/spec/layout.md:45`（図か擬似コード）。他のコードブロックは全て `bash` / `json` / `python` を指定しているので、この 3 箇所だけ揃っていない。ツリー図は `text` を付けるのが通例。

### E-2 [指摘なし / confidence: 90] 括弧の表記は統一されている

新規に書かれた文書（`CLAUDE.md` / `README.md` / `docs/spec/*.md` 5 本）は日本語文中で全角括弧に統一されており、半角括弧が地の文に混入している箇所はゼロだった（`grep -n "[ぁ-んァ-ヶ一-龥]("` で 0 ヒット）。半角の `Jin(陣)` は上流の要件書の表記を踏襲したもので、`README.md:1` / `CLAUDE.md:3` / 両 `pyproject.toml` の description で一貫している。見出し階層も全文書 `#` → `##` → `###` の 3 段で崩れなし。

---

## G. 実行環境の版固定（親からの追加確認事項）

### G-1 [severity: medium / confidence: 85] Python の版がどこにも固定されておらず、`ruff target-version` を含めて三者三様になっている

親の実測どおり、`.venv` の Python は **3.14.6** だった（本セッションでも `uv run python -c "import sys; print(sys.version)"` → `3.14.6 (main, Jun 10 2026)` を再確認）。現状の版に関する宣言は次の 4 つで、**どれも実行される Python を固定していない**:

| 宣言 | 場所 | 値 |
|---|---|---|
| `requires-python` | `pyproject.toml:5` / `packages/jin-core/pyproject.toml:5` / `packages/jin-cli/pyproject.toml:5` | `>=3.12`（下限のみ・上限なし） |
| `uv.lock` | `uv.lock:3` | `requires-python = ">=3.12"` のみ。解決済みインタプリタ版は記録されない |
| ruff `target-version` | `pyproject.toml:37` | `py312` |
| design.yaml の実行環境記録 | `design.yaml:56` | 「実行環境実測 3.13.1」 |
| `.python-version` | — | **存在しない**（`ls` で確認） |
| CI の Python 指定 | `.github/workflows/ci.yml:14-15` | `astral-sh/setup-uv@v5` のみ。`python-version` 入力も `actions/setup-python` も無い |

conventions の観点で問題が 3 つある。

**(1) 「同じコマンドが同じ結果を出す」が担保されていない。** `CLAUDE.md:52` は `uv sync` を唯一の環境構築手順として提示しているが、`uv` は `requires-python` を満たす**マシン上で最も新しい**インタプリタを選ぶので、開発者ごとに 3.12 / 3.13 / 3.14 が混在しうる。実際に design.yaml の記録（3.13.1）とローカル（3.14.6）が既に乖離している。CI も `python-version` を指定していないので、ubuntu-latest のイメージ更新や uv のダウンロード先の変更で、ある日を境に別の版になる。`decision-conformance.md` が誇る「全 225 テストが通る」は 3.14.6 での結果であって、CI が回す版での結果ではない。

**(2) `ruff target-version = "py312"` だけが版を固定しており、しかも実際の実行版より古い。** これは規約として一貫していない。3.14 で動かすコードを 3.12 相当としてリント／フォーマットしているので、3.13 / 3.14 で導入された構文（例: `type` 文の拡張、PEP 695 系の記法）を書くと ruff の判定と実行時の挙動がずれる。ruff は `target-version` を省略すれば `requires-python` から推論するので、**明示している `py312` を消して `requires-python` に一本化する**のが最も整合的（現状の `>=3.12` から py312 が推論されるので挙動は変わらず、将来 `requires-python` を上げたときに追随漏れが起きない）。逆に版を上げたいなら 3 つの `requires-python` と `target-version` を同時に直す必要があり、これも A-2 と同じ「複数箇所ハードコード」の一種。

**(3) 実装者自身が論点として認識しているが、未解決のまま。** `version-matrix.md:30-36` の警告ブロックが「CI と開発者マシンで版が揺れると再現性が落ちる。`.python-version` を置いて固定するかどうかは要件書に根拠が無いため AI が決めない（T-002）」として `implementation-notes.md` の確認要求へ回している。**T-002 の運用としては正しい**（要件書 §1.1 は「Python 3.12+」としか書いておらず、具体値の捏造を避けた判断は妥当）。ただし現状は「決めていない」ではなく「事実上 3.14.6 で開発され、CI では別の版で検証される」という決まり方をしているので、未決のまま Phase 2 に進むと、`google-adk 2.8.0`（`requires_python >=3.10`・`version-matrix.md:36` が 3.14 系での動作未検証と明記）の導入時に「ローカルでは入らないが CI では入る」といった切り分けの難しい事象を招く。

推奨は次のいずれか（どちらも人間の確認が要る）:

- **A 案（最小）**: `ci.yml` の `astral-sh/setup-uv` に `python-version` を明示し、CI 側だけでも固定する。開発者マシンの揺れは残るが、緑の意味が定まる。
- **B 案（推奨）**: リポジトリ直下に `.python-version` を置き、`uv sync` と CI の両方が同じ版を選ぶようにする。合わせて `ruff` の `target-version` を削除して `requires-python` からの推論に任せる。版の宣言箇所が `requires-python`（3 ファイル）+ `.python-version` の 2 種類に収束する。

いずれにせよ、決めた版は `design.yaml:56` の「実行環境実測 3.13.1」という記録と食い違うので、design.yaml 側も同時に訂正するか、`version-matrix.md` の警告ブロックに「3.13.1 は設計時点の記録であり、実装ラウンド 1 の実測は 3.14.6」と明記して両立させる必要がある。

---

## 優先順位の提案

Phase 2 に入る前に潰すべきは **A-1**（テスト名衝突・実測で再現済み・スイート全停止）と **C-1**（存在しないファイルパスの記録）の 2 件。A-1 は空 `__init__.py` を 2 つ置くだけ、C-1 は 1 セルの訂正で終わる。

次点が **C-2**（人間が書いた正典を自動整形が壊しうる）、**A-2**（4 箇所同時修正の必要性がどこにも書かれていない）、**G-1**（Phase 2 で google-adk を入れる直前に決めておくべき）。いずれも「今は緑だが、次に誰かが普通の操作をした瞬間に壊れる」型。

**D-2** は現状ドリフトが無いことを手で確認したので緊急ではないが、`test_field_order_matches_spec` を「表を読む」形に変えるコストが小さいわりに、正準形のバイト列という壊れると痛い性質を守れる。

**B-1**（syrupy）は要件書 §1.1 に対する明確な逸脱だが、代替実装（別プロセス 2 回の突合）のほうが検出力が高いという主張には技術的な理がある。要件どおり syrupy を入れるか、要件側を「決定性検証で代替」と改めるかは人間の判断。
