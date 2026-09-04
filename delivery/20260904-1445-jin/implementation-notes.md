# implementation-notes — 実装ラウンド 1/5（Jin Phase 0 + Phase 1）

`seeds-strategy.md` に相当する生成戦略ノート。本案件に seed / 初期化スクリプトは無いため、
代わりに「何をどういう方針で生成したか」と Stage 1〜4 の実行記録をここに残す。

- 対象: **Jin Phase 0（仕様書と examples）と Phase 1（jin-core + jin-cli の check / fmt / schema / dump）**
- Phase 2 以降（jin-adk / jin-render / jin-lsp / apps/editor）は**別ラウンドの implementer が担当**。着手していない
- implementer: `impl-p01` / 実行日: 2026-09-04

## 1. 生成戦略

### 1.1 何を「生成」したか

本案件に DB seed もマスタ生成も無い。生成物にあたるのは次の 2 つで、どちらも**手書きせず 1 箇所から導出する**方針にした。

| 生成物 | 導出元 | 再生成コマンド | ドリフト検出 |
|---|---|---|---|
| `schemas/jin.schema.json` | `jin_core.model` の Pydantic 定義 | `uv run python scripts/generate_schema.py` | CI と `test_committed_schema_has_no_drift` |
| `.jin` の正準形テキスト | 意味モデル（`jin_core.canonical.dumps`） | `uv run jin fmt` | `uv run jin fmt --check` |

直列化の関数は 1 本しか置いていない（`jin_core.schema_export.serialize` / `jin_core.canonical.dumps`）。
生成スクリプトと CLI が同じ関数を通るので「`jin schema` の標準出力がコミット済みファイルとバイト一致」が構造的に保証される。

### 1.2 examples を先に書いて後から正準形と突き合わせた

Phase 0 の `examples/` は要件書 §2.2 の JSON をそのまま手書きした（Phase 0 時点では Pydantic も writer も無い）。
Phase 1 で canonical writer ができたあと `jin fmt --check examples` が exit 0 であることを確認している。
これが **Phase 0 と Phase 1 の閉じ**であり、「仕様書に書いた正準形の規則」と「実装した writer」が一致していることの証拠になる。

### 1.3 仕様書を機械可読な定型で書いた

design.yaml `implementation_phases.items[0].note` が
「テストは Markdown を機械可読な形で読むため、docs/spec/*.md の該当箇所はパースしやすい定型で書くことを Phase 0 の執筆制約とする」
としているので、突合対象のブロックを `<!-- machine-readable: <ID> -->` … `<!-- /machine-readable -->` で囲み、
中身を Markdown 表に統一した。テストはこのマーカーを頼りに表を読む。散文は自由に書いてよい。

マーカー ID 一覧:

| ファイル | マーカー ID |
|---|---|
| `model.md` | `root-keys` / `circle-keys` / `tool-kinds` / `guard-on-values` / `reference-edges` / `upstream-rule` / `canonical-rules` |
| `adk-mapping.md` | `adk-vocabulary` |
| `layout.md` | `ring-radii` / `data-jin-kinds` |
| `diagnostics.md` | `diagnostic-stages` / `diagnostics-canonical` / `diagnostics-proposed` / `diagnostic-precedence` / `position-base` |
| `ops.md` | `ops-list` / `rename-cascade` |

## 2. Stage 1: pre — 初期構築

### 2.1 tech-version-check

`delivery/20260904-1445-jin/version-matrix.md` を参照。

**一次証拠の扱い**: 親が隔離 venv に実インストールして introspection した `adk-api-probe.md` /
`lsp-api-probe.md` を primary evidence として使い、公式サイトへの WebFetch より優先した
（実インストール後の introspection のほうが強い証拠であるため）。
両プローブに無い 5 パッケージ（import-linter / ruff / pytest / pytest-cov / hatchling）だけ
本セッションが PyPI JSON API で実測し、取得日時と URL を version-matrix.md に記録した。

### 2.2 not_applicable にしたスキル（skipped ではない）

| スキル | 理由 |
|---|---|
| `scaffold-bootstrap` | Python の uv ワークスペースであり `rails new` 相当のジェネレータを持つ FW を使わない。対応 FW（rails / nextjs / laravel）のいずれにも該当しない |
| `reserved-name-check` | DB を持たず `db_schema.tables[]` が空。テーブル名も ORM モデル名も無いので予約語衝突の検査対象が存在しない |
| `wiring-check` / `error-handling-coverage` | middleware / routes / CSRF / HTTP エラー応答という配線の概念が本案件に無い（CLI + ライブラリ） |
| `smoke-run` | 起動するサーバが無く HTTP 200 の検査対象が無い。代替スモークを §4.3 に記録した |

いずれも「省略指示を受けたから飛ばした」のではなく「検査対象が構造的に存在しない」ため
`not_applicable` とした。`skipped` に書き換えていない。

### 2.3 依存解決（dependency-availability-check）

`Gemfile` / `package.json` / `composer.json` が無いので、対応する言語別レシピの代わりに uv の解決で確認した。

```
$ uv sync
Prepared 11 packages in 2m 02s
Installed 23 packages in 116ms
 + annotated-doc==0.0.5 / annotated-types==0.8.0 / click==8.5.0 / grimp==3.16 / import-linter==2.14
 + iniconfig==2.3.0 / jin-cli==0.1.0 (workspace) / jin-core==0.1.0 (workspace) / lark==1.3.1
 + markdown-it-py==4.2.0 / mdurl==0.1.2 / packaging==26.3 / pluggy==1.6.0 / pydantic==2.13.5
 + pydantic-core==2.46.5 / pygments==2.21.0 / pytest==9.1.1 / rich==15.0.0 / ruff==0.16.6
 + shellingham==1.5.4 / typer==0.27.2 / typing-extensions==4.16.0 / typing-inspection==0.4.4
exit=0
```

宣言した依存はすべて解決され、`uv.lock` が生成された。

**実測で分かった注意点**: `uv` が作った `.venv` の Python は **3.14.6** だった
（`requires-python = ">=3.12"` を満たすマシン上の最新版が選ばれた）。
NFR-ENV-001 が記録するホストの 3.13.1 とは別である。全 225 テストは 3.14.6 で通っている。
版を固定するかどうかは §6 の確認要求ブロックに挙げた。

## 3. Stage 2: core — 実装本体

### 3.1 実装方式は design.yaml の decision_record に従った（記憶で選び直していない）

| DP | 採用した方式 | 実装箇所 |
|---|---|---|
| DP-JIN-CANONICAL-01（ADR-005） | `jin_core.canonical` に独自 writer。Pydantic のフィールド定義順を走査 | `packages/jin-core/src/jin_core/canonical.py` |
| DP-JIN-POINTER-RANGE-01（ADR-006） | Lark の木を 1 回走査して pointer→range の完全表。Pydantic の `loc` を pointer に変換して引く。JIN002 は Pydantic に一本化 | `parser.py` / `pointer.py` / `check.py` |
| DP-JIN-SEMANTIC-GAPS-01（ADR-007） | 循環参照と多重親を jin-core の意味検査で検出（新規コード 2 件） | `semantic.py` |
| DP-COMMON-11（ADR-004） | import-linter で layered contract を宣言 | `pyproject.toml` `[tool.importlinter]` / `tests/contract/test_dependency_direction.py` |
| DP-COMMON-09（ADR-003） | パッケージ単位の垂直分割 + `tests/contract/` の横断契約テスト | `packages/*/tests/` / `tests/contract/` |
| tdd_strategy | TDD（既定） | §4.1 の tdd-red / tdd-green |

### 3.2 実装時に決めた値（親からの必須手続き）

**根拠つきの記録は `delivery/20260904-1445-jin/decision-conformance.md` §2 が正本**。ここでは値だけ再掲する。

| 判断 | 値 |
|---|---|
| 新規 JIN 診断コードの採番（DP-JIN-SEMANTIC-GAPS-01） | **JIN012 = 循環参照 / JIN013 = 多重親**（01x = 名前と参照の整合性ブロックの空き番号） |
| 診断の行・列の基点（`lsp-api-probe.md` §3） | **1 始まり**（line / col とも）/ `range.end` は排他 / 列は Unicode コードポイント単位 |
| 横断契約 fixture の共有方法（DP-COMMON-09） | リポジトリ直下 `tests/conftest.py` + 単一 pytest rootdir |
| JIN011 と専用コードの優先順位（要件書 §2.4 の内部重なり） | より具体的なコードが勝つ。JIN011 は summon / delegate のみ |
| JIN050 の「上流」の定義（要件書に定義が無い） | sequence = 先行兄弟の部分木 / loop = 全兄弟の部分木 / parallel = なし / delegate = 親→子のみ / summon = なし |
| `tools[kind=builtin]` の `name` | 3 種すべて必須 |

いずれも `implementation-plan.json` の `decision_record[]` に
`DP-IMPL-JIN-*` として `ai_provisional`（`decided_by_kind: ai_agent` / `review_status: pending_human_review`）で記録した。

### 3.3 実装しなかったもの（意図的）

- **`jin build` / `jin run` / `jin render` / `jin lsp` / `jin editor`**: サブコマンドごと未定義にした。
  空実装を置くと `jin --help` に出てしまい「あるのに動かない」状態になる。
  未定義なら typer が "No such command" で落ちるので未実装であることが正しく伝わる。
  `packages/jin-cli/src/jin_cli/main.py` の docstring に Phase 対応表を書いた
- **丸め桁数（DP-JIN-SVG-DETERMINISM-01）**: Phase 3 で決める旨を `docs/spec/layout.md` §4 に書き、値は入れていない
- **`jin/open` / `jin/save`（DP-JIN-EDITOR-PROTOCOL-01）**: 仮称であり人間承認が要るので
  `docs/spec/ops.md` の 19 件の表に含めていない（§5 に理由を明記）
- **`.env.example`**: `jin build`（Phase 2）の成果物。キー名を推測で書かないという禁止事項を守った

### 3.4 `jin_core.ops` を実装した理由

design.yaml Phase 1 の `verification.machine` に ops の動作条件は入っていないが、
要件書 §11 Phase 1 の括弧書き（「jin-core(… 正準形、ops)」）と §1.2 のパッケージ構成が
ops を jin-core の構成要素に挙げているため、19 オペレーションを純関数として実装した。
LSP への露出（`jin/applyOps` / `jin/ops`）は Phase 4 の担当なので触っていない。

## 4. Stage 4: verify — 動作検証

### 4.1 TDD の実施状況

Phase 1 の 7 実装単位すべてで Red を先に観測した。証拠は `implementation-plan.json`
`verification_status.evidence[]` の `[tdd-red]` / `[tdd-green]` 行。

**Phase 0 の突合テストだけは TestAfter** である（仕様書が成果物で、テストはその一致検査であるため）。
tdd-protocol の Iron Law に従い `tdd-red` の証跡は**書かず欠落のままにし**、
引き下げの根拠を `implementation-plan.json` の `decision_record[DP-IMPL-JIN-TDD-P0-01]` に記録した。
代わりに 3 種のミューテーションでテストが実際に落ちることを実測している（偽 green でないことの担保）。

### 4.2 spec-coverage — machine 条件を 1 つずつ検証した

`smoke-run` / `spec-coverage` の Rails / iOS 前提の検査（UC↔routes 網羅・root 500 不発生）は本案件に対象が無いので、
design.yaml の machine 条件そのものを 1 件ずつコマンドで検証する形に置き換えた。

#### Phase 0（`implementation_phases.items[0].verification.machine`）

| # | 条件 | 結果 | 検証コマンドと証拠 |
|---|---|---|---|
| 1 | diagnostics.md の JIN コード集合が §2.4 の 12 件と過不足なく一致 | **PASS** | `uv run pytest tests/spec/test_spec_consistency.py -k 'diagnostics_canonical or proposed or stage_table or precedence'` → 6 passed。突合は要件書 §2.4 の表をパースして生成した集合と比較している（テスト内に 12 件をベタ書きしていない） |
| 2 | ops.md の意味オペレーション集合が §6.3 の 19 件と一致 | **PASS** | `... -k 'ops_match'` → 1 passed |
| 3 | layout.md の環半径が §2.5 の 4 値と一致 | **PASS** | `... -k 'ring_radii'` → 1 passed |
| 4 | layout.md の `data-jin-kind` が §2.5 の 9 種と一致 | **PASS** | `... -k 'data_jin_kinds'` → 1 passed |
| 5 | adk-mapping.md の Jin キー集合が §2.1 対応表の **11 行**と一致 | **PASS（件数の記述は転記誤り）** | `... -k 'adk_vocabulary'` → 2 passed。**要件書 §2.1 の表は実測 12 行**（`awk '/^### 2.1 語彙と ADK 対応/,/^circle は 2 種類/' jin-requirements.md \| grep -c '^\| \`'` → `12`）。requirements.json `FR-MODEL-002.vocabulary[]` も 12 件。上流 2 系統が一致するので 12 行を正とし、集合の一致は PASS。design.yaml 側の「11 行」を転記誤りとして §6 で確認要求を返した |
| 6 | examples 2 本が JSON として parse でき §2.2 掲載の内容と意味的に一致 | **PASS** | `... -k 'example'` → 7 passed。要件書 §2.2 の 2 つの ```json ブロックを抽出して `json.loads` した結果と examples の内容を `==` で比較している |

#### Phase 1（`implementation_phases.items[1].verification.machine`）

| # | 条件 | 結果 | 検証コマンドと証拠 |
|---|---|---|---|
| 1 | §2.4 の 12 コードそれぞれに fixture があり、対応コードをちょうど 1 つだけ出す | **PASS** | `uv run pytest packages/jin-core/tests/test_check.py -k 'exactly_its_own_code or every_documented_code'` → 15 passed。fixture は 14 本（正典 12 + 追加提案 2）。JIN040 のみ `--resolve` 付きで検査する（付けないと出ないコードのため）。他の fixture は `--resolve` なし（付けると `research.tools:*` が解決できず JIN040 が混入して「1 つだけ」が壊れる） |
| 2 | examples 2 本が jin check で error 0 件（exit 0） | **PASS** | `uv run jin check examples` → `2 ファイル / error 0 件 / warning 0 件` / `rc=0` |
| 3 | Pydantic から生成した JSON Schema がコミット済みとバイト一致 | **PASS** | 実証は 2 つ。(a) `uv run pytest packages/jin-core/tests/test_schema_export.py::test_committed_schema_has_no_drift` → PASS（ファイルの内容と `serialize(build_schema())` を文字列比較している）。(b) `uv run jin schema \| diff - schemas/jin.schema.json` → 差分なし。**`git diff --exit-code -- schemas/jin.schema.json` は本ラウンドでは空振りである**（implementer は commit しないため `schemas/jin.schema.json` は untracked で、git diff は常に 0 を返す）。CI（`.github/workflows/ci.yml`）ではコミット後に走るので同ステップは有効に機能する |
| 4 | 冪等性: examples と全 fixture について `fmt(fmt(x)) == fmt(x)` | **PASS（範囲を明示）** | `uv run pytest tests/contract/test_canonical_contract.py -k 'idempotent or unformattable_set or formattable_set'` → 3 passed。対象は examples 2 + モデルになる fixture 12 = 14 本。`JIN001` / `JIN002` の fixture はモデルにならないので `fmt(x)` が存在しない。**黙って除外せず**、除外集合がちょうど `{JIN001, JIN002}` であることをテストで固定し（`test_unformattable_set_is_exactly_the_two_documented_codes`）、この 2 本については「fmt が拒否してファイルを書き換えない」を別の契約として検証した（`test_fmt_refuses_unformattable_fixtures_without_touching_them` → 1 passed） |
| 5 | 意味保存: `model(fmt(x)) == model(x)` | **PASS** | `... -k 'semantics_preserved or text_roundtrip'` → 2 passed |
| 6 | 正準形の 4 規則（2 スペース / スキーマ定義順 / 非 ASCII 非エスケープ / 末尾改行）が出力に対して検査される | **PASS** | `... -k 'rule1 or rule2 or rule3 or rule4 or rule5 or rule6'` → 7 passed。キー順の期待値は Pydantic の `model_fields` から導出しており、モデルを変えるとテストも追随する |
| 7 | 省略可能キーが既定値のとき出力されない | **PASS** | `... -k 'rule7'` → 2 passed |
| 8 | jin dump の JSON スナップショットが安定し、pointer→range 対応表の全 pointer がモデルに解決できる | **PASS** | `uv run pytest tests/contract/test_cli_contract.py::test_dump_is_stable_across_processes_with_different_hash_seeds tests/contract/test_pointer_contract.py` → 10 passed。安定性は **`PYTHONHASHSEED` を変えた別プロセス 2 回**で比較している（同一プロセス内の一致は辞書順序依存を検出できず偽 green になりうるため） |
| 9 | jin schema の標準出力が `schemas/jin.schema.json` とバイト一致 | **PASS** | `uv run jin schema \| diff - schemas/jin.schema.json` → 差分なし / `BYTE_IDENTICAL` |

**15/15 PASS。**

### 4.3 スモーク（smoke-run の代替）

```
$ uv run pytest
225 passed in 2.47s

$ uv run jin check examples
2 ファイル / error 0 件 / warning 0 件
exit=0

$ uv run jin fmt --check examples
exit=0

$ uv run lint-imports
jin レイヤは一方向（jin_core が最下層） KEPT
jin_core は google-adk に依存しない KEPT
Contracts: 2 kept, 0 broken.

$ uv run ruff check .
All checks passed!

$ uv run ruff format --check .
28 files already formatted
```

テスト内訳（225 件）:

| ファイル | 件数 |
|---|---|
| `tests/spec/test_spec_consistency.py` | 25 |
| `tests/contract/test_canonical_contract.py` | 13 |
| `tests/contract/test_pointer_contract.py` | 9 |
| `tests/contract/test_dependency_direction.py` | 9 |
| `tests/contract/test_cli_contract.py` | 7 |
| `packages/jin-core/tests/test_model.py` | 10 |
| `packages/jin-core/tests/test_canonical.py` | 15 |
| `packages/jin-core/tests/test_schema_export.py` | 7 |
| `packages/jin-core/tests/test_parser.py` | 27 |
| `packages/jin-core/tests/test_check.py` | 46 |
| `packages/jin-core/tests/test_ops.py` | 34 |
| `packages/jin-cli/tests/test_cli.py` | 23 |

### 4.4 依存契約が「効いている」ことの実測

宣言しただけで満足しないよう、`jin_core` のコピーに `import google.adk` を注入して import-linter が落ちることを確認した。

```
no adk BROKEN
Contracts: 0 kept, 1 broken.
jin_core is not allowed to import google:
-   jin_core.canonical -> google (l.1)
（exit 1）
```

`google.adk` は**インストールされていない**が、import-linter は静的解析なので検出できる。
実物のツリーは触っていない（一時ディレクトリのコピーに注入した）。

### 4.5 human_only の条件

design.yaml `implementation_phases.items[0].verification.human_only`:
「仕様全体に自己矛盾がないことの最終判断（§11 の文言そのもの）。ADR-001 に従い PR レビューで代替する」

→ **実施していない。`not_run` として記録した。PR レビューで人間が判定する。**
実施済みと報告していない。

## 5. verification_status

| キー | 値 |
|---|---|
| `overall` | **verified** |
| `scope_labels` | `["backend-unit-verified"]` |
| `required_layers` | `["backend_unit"]` |
| `layers.backend_unit` | passed |
| `layers.container_smoke` | not_applicable（HTTP サーバが無い） |
| `layers.browser_e2e` | not_applicable（ブラウザ UI が無い。Phase 5–6 の apps/editor は本ラウンド外） |
| `layers.pipeline_e2e` | **not_run**（GitHub Actions 上での実行はしていない） |

`required_layers` を `[backend_unit]` と明示したのは、既定の `[container_smoke]` のままだと
本案件では構造的に `verified` に到達できないため。

**`overall = verified` は backend_unit レイヤに限った verified である**。
GitHub Actions の実パイプライン通しは未検証で、Phase 0 の human_only 条件も未実施であることを
`scope_labels` と本節で明示している。

`overall = verified` なので `replay-commands.md` の生成は必須ではないが、
後続ラウンドと PR レビュワーが同じ検証を再走できるよう生成した（`delivery/20260904-1445-jin/replay-commands.md`）。

## 6. 確認要求ブロック（人間判断が要る点）

> AskUserQuestion は使わず、親（auto-decider 経由）へ返す確認要求として記載する。

```json
{
  "kind": "human-decision-request",
  "source": "implementer impl-p01 / 実装ラウンド 1（Jin Phase 0 + 1）+ fix-now 修正ラウンド 1・2",
  "run_dir": "delivery/20260904-1445-jin",
  "questions": [
    {
      "id": "Q-JIN-IMPL-01",
      "severity": "must_fix_before_merge",
      "title": "design.yaml Phase 0 の machine 条件 5 が「§2.1 対応表の 11 行」と書いているが、上流はいずれも 12 行",
      "detail": "要件書 jin-requirements.md §2.1 の表は実測 12 行（circles[] / core / instruction.rune / tools[] / delegate[] / state[] / flow.kind=sequence / flow.kind=parallel / flow.kind=loop / boundary.guards[] / boundary.await[] / root）。requirements.json の FR-MODEL-002.vocabulary[] も 12 件。design.yaml だけが 11 行と書いている。実装は上流 2 系統に合わせて 12 行にし、突合テストで固定した。",
      "options": [
        "design.yaml の『11 行』を『12 行』に訂正する（推奨・上流 2 系統と一致させる）",
        "12 行が誤りで 11 行が正しいなら、要件書 §2.1 と requirements.json の両方を直す"
      ],
      "recommendation": "1 つ目。design.yaml は設計成果物であり、要件書と requirements.json の 2 系統が一致している以上そちらが正典。",
      "blocking": false,
      "note": "implementer は他モジュール由来の成果物（design.yaml）を無言で書き換えないため、訂正は親に委ねる。"
    },
    {
      "id": "Q-JIN-IMPL-02",
      "severity": "spec_change_approval",
      "title": "新規 JIN 診断コード JIN012（循環参照）/ JIN013（多重親）の採番と、要件書 §2.4 への追加の承認",
      "detail": "DP-JIN-SEMANTIC-GAPS-01 の constraints が『採番値は Phase 0 の docs/spec/diagnostics.md 執筆時に決定し根拠を残す』『要件書 §2.4 への追加であり仕様変更として人間の承認を要する』としている。採番の根拠は docs/spec/diagnostics.md §3.1（10 の位のブロック構造に基づき 01x = 名前と参照の整合性の空き番号を使用）。docs/spec/diagnostics.md では正典表（§2・12 件）と追加提案表（§3・2 件）を別の表に分け、§3 冒頭に未承認である旨を明記してある。",
      "options": [
        "JIN012 / JIN013 の採番を承認し、要件書 §2.4 の表に 2 行追加する",
        "別の番号（例: 03x ブロック）に採り直す",
        "追加自体を却下し、DP-JIN-SEMANTIC-GAPS-01 の案 B / 案 C に切り替える（実装のやり直しが必要）"
      ],
      "recommendation": "1 つ目。循環参照はレンダラの入れ子展開が無限再帰する実害があり、多重親は ADK の BaseAgent.parent_agent が単一値であることに反する。どちらも jin check の段階で落とせないと成功条件 3（LLM が jin check → 修正のループで直せる）が成立しない。",
      "blocking": false
    },
    {
      "id": "Q-JIN-IMPL-03",
      "severity": "spec_clarification",
      "title": "要件書 §2.4 の JIN011 と専用コード（JIN031 / JIN050 / JIN060 / JIN070）の重なりの解き方",
      "detail": "§2.4 の JIN011 行は『未解決の参照（summon / delegate / steps / await / {key}）』と 5 種を挙げるが、steps / await / {key} には同じ表に JIN031 / JIN070 / JIN050 という専用コードがある。§9 の『fixture は対応コードを 1 つだけ出す』を成立させるには優先順位が要る。実装は『より具体的なコードが勝つ』とし、JIN011 の守備範囲を summon と delegate の 2 種にした（docs/spec/diagnostics.md §4 の表が正本）。",
      "options": [
        "この優先順位で確定し、要件書 §2.4 の JIN011 行の括弧書きを『summon / delegate』に直す",
        "別の優先順位にする"
      ],
      "recommendation": "1 つ目。専用コードのほうが hint を具体化できる（await なら自 circle の tool 名一覧など）ので NFR-LLM-001 にも合う。",
      "blocking": false
    },
    {
      "id": "Q-JIN-IMPL-04",
      "severity": "spec_clarification",
      "title": "JIN050 の「flow 上流 circle」の定義（要件書に定義が無い）",
      "detail": "実装した定義は docs/spec/model.md §5 の表: sequence = 先行する兄弟枝の部分木 / loop = すべての兄弟枝の部分木 / parallel = なし / delegate = 親→子のみ / summon = なし。要件書 §2.2 の pipeline.jin がこの定義でちょうど通る（Critic の {draft} は Refine の外・Pipeline 前段の Drafter が出す）ことが妥当性の一次証拠。",
      "options": [
        "この定義で確定する",
        "別の定義にする（例: loop でも先行兄弟のみ）"
      ],
      "recommendation": "1 つ目。loop で全兄弟を含めるのは、2 周目以降どの兄弟も先に実行されうるという ADK の LoopAgent の実行意味論に合わせたもの。",
      "blocking": false
    },
    {
      "id": "Q-JIN-IMPL-05",
      "severity": "spec_clarification",
      "title": "tools[kind=builtin] にも name を必須にした（要件書 §2.2 の例は name を書いていない）",
      "detail": "要件書 §2.2 の判別共用体の説明は builtin の例を { \"kind\": \"builtin\", \"builtin\": \"google_search\" } と書いており name が無い。実装は 3 種すべてで name を必須にした。name は circle 内一意の ID として boundary.await[]・moveTool / rename・JSON Pointer の安定性に使われるため。",
      "options": [
        "3 種すべて name 必須で確定し、要件書 §2.2 の例に name を足す",
        "builtin だけ name を任意にし、欠けたら builtin 値を name として補う"
      ],
      "recommendation": "1 つ目。既定値を後から補う案は『名前が ID』（§10 #11）という原則を暗黙の生成で濁す。",
      "blocking": false
    },
    {
      "id": "Q-JIN-IMPL-06",
      "severity": "environment",
      "title": "開発・CI の Python バージョンを固定するか",
      "detail": "NFR-ENV-001 は実行環境を Python 3.13.1 と記録しているが、uv sync が作った .venv は 3.14.6 だった（requires-python = '>=3.12' を満たすマシン上の最新版が選ばれた）。全 225 テストは 3.14.6 で通っている。要件は『3.12+』なので違反ではないが、開発者マシンと CI で版が揺れると再現性が落ちる。また Phase 2 で google-adk 2.8.0 を 3.14 系へ入れられるかは未検証。 【修正ラウンド 1 追記】wiring review W-06 の指示で CI の版固定が必要になったが、本問は未回答で auto-decisions.md にも裁定が無い。AI が推奨版を決めるべき論点ではないので、`.python-version` には**本ラウンドの 434 テストを実際に通した処理系（3.14。実測 3.14.6）という事実だけ**を置いた。uv がこのファイルをネイティブに読むので CI もこれに従う（`setup-uv@v5` には `python-version-file` 入力が存在しないことを action.yml で実測済み）。**この値は暫定であり、本問の回答で確定する。** 根拠は decision-conformance.md §2.10。",
      "options": [
        ".python-version を置いて固定する（値は人間が決める）",
        "固定せず >=3.12 のままにする"
      ],
      "recommendation": "なし（案件で判断）。固定する版の値は要件書に根拠が無いため AI が決めない（T-002）。",
      "blocking": false
    },
    {
      "id": "Q-JIN-IMPL-08",
      "severity": "unverified_value",
      "title": ".github/workflows/ci.yml の action 版が未検証（actions/checkout@v4 / astral-sh/setup-uv@v5）",
      "detail": "2 つの uses: は記憶で書いた値であり実測できていない。GitHub API が rate limit で応答した（API rate limit exceeded for 210.172.0.33 / 2026-09-04T07:37Z）。ワークフローは本ラウンドで実行していない（pipeline_e2e = not_run）ので、PR で CI が初めて走るときにここが原因で落ちる可能性がある。仮 ID DP-JIN-GHA-VERSION-UNVERIFIED。",
      "options": [
        "親が gh 認証つきで最新のメジャータグを確認して固定する",
        "PR で CI を実際に走らせて落ちたら直す"
      ],
      "recommendation": "1 つ目。version-matrix.md §5 の行 10 に未検証であることを記録済み。",
      "blocking": false
    },
    {
      "id": "Q-JIN-IMPL-07",
      "severity": "review_hint",
      "title": "jin check --resolve が任意の Python モジュールを import する点の扱い",
      "detail": "JIN040 の検査（--resolve 指定時のみ）は importlib.import_module で .jin に書かれたモジュールを実際に import する。既定はオフ。CLI のヘルプに『Python 参照を実際に import して JIN040 を検査する』と書いてあるが、README / CLAUDE.md には警告を書いていない。 【修正ラウンド 1 で対応済み】security review S1 / S2 / S19 として構造的に修正した。import 実装は jin_cli.resolver.ImportResolver にのみ置き、jin_core は RefResolver プロトコルだけを知る。隔離は import-linter の forbidden contract で機械的に落とす。警告は README / CLAUDE.md / CLI ヘルプの 3 箇所に書いた。**本問は「対応方針の是非」だけが残っている。**",
      "options": [
        "修正ラウンド 1 の対応（プロトコル注入 + import-linter 契約 + 3 箇所の警告）でよい",
        "さらに強める（例: --resolve を別プロセスへ隔離する / 既定で無効化してもオプトインを設定ファイルに移す）"
      ],
      "recommendation": "1 つ目。別プロセス隔離は Phase 4 で LSP が ws を開くときに再検討するのが妥当。",
      "blocking": false
    },
    {
      "id": "Q-JIN-IMPL-09",
      "severity": "spec_change",
      "title": "`.jin` の文字列に長さ制限と文字種制限を入れたこと（S13）",
      "detail": "security review S13（S6 / S3 / D-1 の共通の根）への対応として、要件書に規定の無い制限を新たに入れた: 識別子 128 文字 / 自由記述 65536 文字 / $schema 2048 文字、識別子は制御文字を全面禁止・自由記述は \\n \\r \\t のみ許可、孤立サロゲート（U+D800〜U+DFFF）は全面禁止。**これは `.jin` 言語の受理範囲を狭める仕様変更である。** 既存の examples 2 本と fixture 18 本はすべて通ることを実測した。値と根拠は decision-conformance.md §2.7。実装は jin_core/model.py の MAX_IDENT_LENGTH / MAX_TEXT_LENGTH / MAX_URL_LENGTH と _reject_bad_chars。違反は段 2 の JIN002 になる。",
      "options": [
        "この制限と値（128 / 65536 / 2048）を承認する",
        "制限は入れるが値を変える（希望値を指定する）",
        "制限を入れず、S6 / S3 / D-1 は表示側・計算側の対処だけで閉じる"
      ],
      "recommendation": "1 つ目。値を変える場合も jin_core/model.py の定数 3 つを直すだけで済む形にしてある。",
      "blocking": false
    },
    {
      "id": "Q-JIN-IMPL-10",
      "severity": "spec_change",
      "title": "これまで受理していた入力を新たに JIN001 で拒むようにしたこと（C-2 / S4）",
      "detail": "correctness review C-2 と security review S4 への対応として、段 1（構文）で 2 種類の入力を新たに拒むようにした。(a) 同一オブジェクト内の重複キー（例: {\"core\": \"a\", \"core\": \"b\"}）→ JIN001。RFC 8259 は扱いを未定義にしているが、後勝ちにすると 1 つの JSON Pointer が 2 つの range を持ち、docs/spec/model.md §6 の「pointer は唯一の鍵」が破れる。(b) 値の入れ子が 64 段を超えるファイル → JIN001。上限が無いと parser._walk の再帰が Python の再帰上限（実測 1000 段で RecursionError）に当たり、診断ではなくトレースバックが表に出る。妥当な .jin の最大の深さは 7 段なので 64 は約 9 倍の余裕がある（decision-conformance.md §2.8）。**どちらも要件書には書かれていない受理範囲の縮小である。**",
      "options": [
        "両方とも承認する（重複キー拒否 / 入れ子 64 段上限）",
        "重複キーは拒否するが入れ子の上限値を変える",
        "重複キーは後勝ちのまま許し、model.md §6 の主張のほうを弱める"
      ],
      "recommendation": "1 つ目。(a) を許すと pointer が診断・描画・トレースを結ぶ唯一の鍵という前提そのものが崩れる。",
      "blocking": false
    },
    {
      "id": "Q-JIN-IMPL-11",
      "severity": "behavior_change",
      "title": "`jin fmt` が「ディレクトリに書けないがファイルには書ける」状況で非原子的な直接書き込みに退避すること（N2）",
      "detail": "conventions N2 への対応として `jin fmt` の書き込みを原子的差し替え（tempfile.mkstemp + shutil.copymode + os.replace）に変えたところ、ディレクトリが読み取り専用（例: chmod 555）でファイル自体は書ける場合に PermissionError で機能後退する。実装では AtomicWriteUnavailable を捕まえ、os.access(path, os.W_OK) が真なら直接書き込みに退避し「原子的に差し替えできませんでした。直接書き込みました（中断すると内容が壊れる可能性があります）」という警告を出す。**中断時にファイルが壊れうる経路を残す判断であり、要件書に規定が無い。** 値と根拠は decision-conformance.md §2.11。回帰テストは packages/jin-cli/tests/test_cli.py の test_fmt_falls_back_to_in_place_write_in_a_read_only_directory と test_fmt_reports_a_diagnostic_when_neither_file_nor_directory_is_writable。",
      "options": [
        "退避 + 警告を承認する（推奨・現在の実装）",
        "退避せず exit 1 で拒む（原子性を常に守るが、読み取り専用ディレクトリ下では fmt が一切使えなくなる）",
        "退避は明示フラグ（例: --force-in-place）でのみ許す"
      ],
      "recommendation": "1 つ目。原子性を守れないことを黙って隠すのではなく警告として出しており、退避しない場合は N2 が指摘した機能後退そのものが残る。3 つ目にする場合は jin_cli/main.py の _write_canonical にフラグを通すだけで済む。",
      "blocking": false
    },
    {
      "id": "Q-JIN-IMPL-12",
      "severity": "maintenance",
      "title": "CI の uv を 0.12.9 に固定したこと（N-01）と、その版を上げるときの手順",
      "detail": "N-01（UV_LOCKED と `uv sync --frozen` の衝突）への対応として .github/workflows/ci.yml の astral-sh/setup-uv に version: \"0.12.9\" を指定した。この版は親レビュアが lock 検証済みと明記した版であり、本リポジトリでも `uv lock --check` EXIT=0 / stale lock で `uv sync` EXIT=1（正しく落ちる）/ `.python-version` を尊重して Python 3.14.6 を選ぶことを実測した（decision-conformance.md §2.12）。**固定値は人間が今後保守する対象なので、上げる手順を明文化しておきたい。** ピンは tests/contract/test_ci_contract.py の test_uv_version_is_pinned が「version: が存在し latest でない」ことを固定している（特定の版番号は固定していないので、版を上げてもテストは通る）。",
      "options": [
        "0.12.9 固定と、上げるときは decision-conformance.md §2.12 の 2 コマンド（uv lock --check / stale lock で uv sync が非 0）を再実測してから上げる、という運用を承認する",
        "版を固定せず latest に戻す（lock 検証が効く保証を失う）",
        "Dependabot 等の自動更新対象にする（更新のたびに上記 2 コマンドを CI で回す）"
      ],
      "recommendation": "1 つ目。3 つ目は望ましいが、CI に検証ジョブを足す作業は Phase 1 の範囲外。",
      "blocking": false
    }
  ]
}
```

## 7. 後続ラウンドへの引き継ぎ

| 事項 | 内容 |
|---|---|
| `implementation-plan.json` | 本ラウンドが新規作成した。後続は **extend** すること。`skill_plan[]` / `tasks[]` は要素に `jin_phase` フィールド、`verification_status.evidence[]` は文字列先頭の `[jin_phase=N][kind]` タグで Phase を示す（schema が evidence[] を文字列配列と定めているため） |
| import-linter | `packages/jin-adk` / `jin-render` / `jin-lsp` を作ったら `pyproject.toml` の layers 契約に足すこと。`tests/contract/test_dependency_direction.py::test_later_packages_do_not_exist_yet` が赤くなって気づける |
| apps/editor | 作ったら `test_editor_contract_is_not_yet_enforced` が赤くなる。DP-COMMON-11 の 2 本目（pnpm 側の静的検査）を足してからテストを差し替えること |
| 位置変換 | `jin_core` は 1 始まり・コードポイント単位。Phase 4 の `jin-lsp` に位置変換モジュールを 1 本作り、基点（−1）と UTF-16 コードユニット換算の両方をそこだけで行う（`docs/spec/diagnostics.md` §5.1） |
| 丸め桁数 | Phase 3 で決めて `docs/spec/layout.md` §4 に根拠を追記する（DP-JIN-SVG-DETERMINISM-01） |
| `jin/open` / `jin/save` | 人間承認を得てから `docs/spec/ops.md` §2 の表に足す（DP-JIN-EDITOR-PROTOCOL-01） |
| `pygls[ws]` | 依存宣言には必ず `[ws]` extra を付ける。素の pygls には websockets が入らない（`lsp-api-probe.md` §1） |
| pytest-lsp | ws のラウンドトリップは張れない。ws 用ハーネスは自前で書く（`lsp-api-probe.md` §2） |
| `LoopAgent` | 反復上限の引数名は `max_iterations`（`max` ではない。`adk-api-probe.md`） |
