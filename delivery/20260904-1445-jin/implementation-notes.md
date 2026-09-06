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

---

# implementation-notes — 実装ラウンド 2/5（Jin Phase 2・jin-adk）

- 対象: **Jin Phase 2（`jin-adk`: build / run / trace / FakeLlm と `jin build` / `jin run`）** = Issue #3
- implementer: `impl-p2` / 実行日: 2026-09-05 / ブランチ `feat/jin-phase2-adk` / 既存ラン `delivery/20260904-1445-jin/` を extend
- 環境: Python 3.14.7 / uv 0.12.10 / google-adk 2.8.0（`version-matrix.md` §8）
- 記録先はこのファイルの本節と `decision-conformance.md` §2.13〜§2.21 / §4.1。`implement-ledger.md` は親が書く

## P2-1. 生成戦略

| 生成物 | 導出元 | 再生成 | ドリフト検出 |
|---|---|---|---|
| `<out>/<root_name>/agent.py` / `__init__.py` / `.env.example` | 意味モデル（`jin_core.model.JinFile`）→ `jin_adk.codegen.generate` → Jinja2 テンプレート `templates/agent.py.j2` | `jin build <file> --out <dir>` | syrupy スナップショット `packages/jin-adk/tests/__snapshots__/test_codegen.ambr`（examples 2 本）+ 別プロセス・別 `PYTHONHASHSEED` のバイト一致 |
| pointer 対応表（ADR-009） | 同じ `generate` の戻り値 `GeneratedProject.pointers`（生成物とは別） | 毎回生成（ファイルには書かない） | `test_every_pointer_in_the_map_resolves_in_the_model` |

方針: `.jin` 由来の文字列は **すべて `py_literal`** を通す（`json.dumps` ベース）。識別子として埋めるのは
`isidentifier()` + 予約語 + 予約名を通した circle 名と、`check_ref_format` を通した `ref` だけ。
テンプレートは値を受け取るだけで `.jin` の生の値に触れない（`templates/__init__.py` の docstring）。

要件書 §3.2 の生成コード例と比べた差分（意図的）: (a) 複数行の rune は三重引用符ではなく 1 行 1 リテラルの暗黙連結
（エスケープを `py_literal` 1 本に閉じるため）、(b) `import` の並びは §3.2 と同じ（`google.adk.agents` → `google.adk.tools` →
`agent_tool` → `ref` のモジュール初出順）、(c) ヘッダに ADR-008 / ADR-009 の注記。実測 API との差分は `adk-mapping.md` §2 のとおり
（`max_iterations` / `session_service` 必須）。

## P2-2. Stage 0 / 1: pre

- `implementation-skill-planner`: `implementation-plan.json` の `skill_plan[]` に `jin_phase: 2` のエントリを追記（tech-version-check /
  tdd-protocol / wiring-check / spec-coverage / decision-conformance-check / verification-status-aggregation / parallel-code-review）。
  scaffold-bootstrap / dependency-availability-check / reserved-name-check / error-handling-coverage / smoke-run はラウンド 1 と同じ理由で
  `not_applicable`（Python の uv ワークスペース・DB なし・HTTP サーフェスなし）。dependency-availability-check 相当は
  `uv lock` → `UV_LOCKED=1 uv sync` EXIT 0（75 パッケージ）で代替した
- `tech-version-check`: `version-matrix.md` §8（google-adk 2.8.0 / jinja2 3.1.6 / syrupy 6.0.0 を PyPI JSON と probe で突き合わせ・一致）
- **申し送り §0-A（JIN012 / JIN013 の統合）は Issue #2 で実施済みなので再実施していない**（`uv run pytest` 521 passed から開始）

## P2-3. Stage 2: core（TDD）

実装単位ごとに Red を先に観測した（証跡は `implementation-plan.json` `verification_status.evidence[]` の `[jin_phase=2][tdd-red]`）:

| 単位 | Red の観測 | Green |
|---|---|---|
| `jin_adk.codegen` | `ModuleNotFoundError: No module named 'jin_adk.codegen'`（collection error） | 64 passed（2 snapshots） |
| `jin_adk.fake_llm` | `ModuleNotFoundError: No module named 'jin_adk.fake_llm'` | 6 passed |
| `jin_adk.trace` | `ModuleNotFoundError: No module named 'jin_adk.trace'` | 9 passed |
| `jin_adk.build` | `ModuleNotFoundError: No module named 'jin_adk.build'` | 16 passed |
| `jin_adk.runtime` | `ModuleNotFoundError: No module named 'jin_adk.fake_llm'`（同 import） | 33 passed |
| `jin_cli` build / run | 新規 `test_build_run.py` 29 件のうち 1 件が実アサーション失敗（`WriteRefused` の名前衝突・下記）→ 修正 | 29 passed |

Red 観測の途中で拾った実装上の欠陥（テストが無ければ気づかなかったもの）:

1. **`jin_cli.main` の `WriteRefused` 名前衝突**: `from jin_adk.build import WriteRefused` を書いたが、同モジュールが fmt 用に
   同名クラスを定義しており、クラス定義が import を上書きして `except WriteRefused` が効かなかった（実バイナリで
   トレースバックが出る状態）。`BuildWriteRefused` の別名 import に変更。`test_build_refuses_to_overwrite_without_force` が検出
2. **`google.adk.tools` の遅延 import**: `builtin` の候補一覧を `dir()` + `getattr` で作ると `MCPToolset` が `mcp` 未インストールで
   `ModuleNotFoundError` になった。名指しの 1 属性だけを getattr し、ImportError は「使えない名前」として扱う形に変更
3. **`importlib.resources` も importlib**: テンプレート読込に `importlib.resources.files` を使うと契約テスト
   `test_the_only_module_importing_importlib_is_the_cli_resolver` の offender が 3 つになる。`Path(__file__).with_name(...)` に変更し、
   importlib を使うのは `jin_adk/runtime.py` と `jin_cli/resolver.py` の 2 つに保った

実装した決定（根拠は `decision-conformance.md` §2.13〜§2.21）: `.env.example` のキー（実測 4 件）/ `flow.exit` の比較規則 /
`research.*` スタブ / layers `"jin_adk"` 単独 / ruff 後処理なし / state seed / cwd を sys.path へ / StateCheckAgent 1 定義 /
`final` と `escalate` の定義。

Issue #3 の「罠」11 件への対処: 1 スタブ（§2.15）/ 2 比較型（§2.14）/ 3 任意コード実行（§4.1・`guard:` 6 箇所・0700・エスケープ）/
4 runtime 依存（§2.17・ruff を足さない）/ 5 トリップワイヤ（`test_later_packages_do_not_exist_yet` から `jin_adk` だけ除外、
importlib の `expected` に `runtime.py` を**追加**・`>=` に緩めていない）/ 6 `.env.example`（§2.13）/ 7 FakeLlm 差し替え
（`swap_models` が `sub_agents` と `AgentTool.agent` を走査、StateCheckAgent は触らない・`test_swap_models_*`）/
8 `ts` はスナップショット外（スナップショットは agent.py だけ。トレースはスキーマ検証 + pointer 解決）/
9 NFR-FAIL-001 fixture 14 本（`tests/fixtures/build-errors/`・`jin check` は通り `generate` は落ちる）/
10 StateCheckAgent 重複（§2.20）/ 11 書き込み先の安全（`build.py`・`dir_fd` + `O_EXCL` + `O_NOFOLLOW` + `root_name` 再検査）。

## P2-4. Stage 3: post（wiring-check）

「宣言した配線が効いているか」を実測で確認した:

| 配線 | 宣言 | 効いている証拠 |
|---|---|---|
| `pyproject.toml` の 5 箇所 + `tests/__init__.py` | `[project].dependencies` / `[tool.uv.sources]` / `root_packages` / `layers` / resolver 隔離契約の `source_modules` | `tests/contract/test_packaging_contract.py` 31 passed（W-03 / W-05 の網羅検査）。`lint-imports`: **Analyzed 36 → 50 files**（jin_adk 追加分）、3 kept |
| `jin-cli` → `jin-adk` の依存 | `packages/jin-cli/pyproject.toml` | `uv lock` / `UV_LOCKED=1 uv sync` EXIT 0。`jin build` / `jin run` が実バイナリで動く（`test_cli_contract.py`） |
| CI | `.github/workflows/ci.yml` は変更不要（`uv sync` が workspace の jin-adk を入れる） | `tests/contract/test_ci_contract.py` 20 passed。**本ブランチで Actions は未実行**（`pipeline_e2e = not_run`） |
| syrupy | dev group | `2 snapshots passed` |
| 契約の更新 | `test_later_packages_do_not_exist_yet` から `jin_adk` を除外 / importlib offender に `runtime.py` を追加 / `test_adk_version_contract.py` 新設 / `guard:` 検査を `jin_adk.{build,runtime,codegen}` に拡張 | いずれも緑。`guard:` の嘘（`BUILD-guard-lie`）で赤を実測 |

## P2-5. Stage 4: verify

### P2-5.1 spec-coverage（design.yaml `implementation_phases.items[2].verification.machine` 8 条件・verbatim）

| # | 条件 | 結果 | 検証（このセッションの実測） |
|---|---|---|---|
| 1 | 生成 agent.py のスナップショット（syrupy）が examples 2 本について安定 | **PASS** | `test_codegen.py::test_generated_agent_py_snapshot[researcher/pipeline]` 2 snapshots passed + `test_cli_contract.py::test_build_output_is_byte_identical_across_processes_with_different_hash_seeds`（`PYTHONHASHSEED=0` / `12345` の別プロセスでバイト一致） |
| 2 | 生成モジュールを import して ADK オブジェクト木を検証する（tools の型 / sub_agents の名前 / callback の同一性）。モデル呼び出しはしない | **PASS** | `test_runtime.py::test_researcher_object_tree`（`[FunctionTool, FunctionTool, AgentTool, LongRunningFunctionTool]` / `before_model_callback is research.guards.pii_filter`）/ `::test_pipeline_object_tree`（`["Drafter","Reviewer","Refine"]` / `max_iterations == 3` / `Refine_exit_check` が末尾） |
| 3 | 生成プロジェクトのディレクトリ構造が §3.1 と一致する | **PASS** | `test_build.py::test_layout_matches_requirements_section_3_1`（`.env.example` / `Researcher/__init__.py` / `Researcher/agent.py` の 3 つ）+ `test_build_run.py::test_build_writes_the_project_layout` |
| 4 | google-adk 2.8.0 に対する生成モジュールの import テストが通る（NFR-VER-001） | **PASS** | `test_adk_version_contract.py::test_installed_google_adk_matches_the_version_the_templates_were_probed_against`（`importlib.metadata.version("google-adk") == "2.8.0"`）+ 条件 2 の import |
| 5 | jin run --model fake が examples 2 本で最後まで通り exit 0 | **PASS** | `test_cli_contract.py::test_run_with_fake_model_exits_zero_in_a_real_process[researcher/pipeline]`（実バイナリ・`PYTHONPATH=tests/fixtures/stubs`）+ `test_build_run.py::test_run_with_fake_model_completes_and_writes_a_valid_trace` |
| 6 | トレース JSONL の全行が §3.4 のスキーマを満たす | **PASS** | `test_runtime.py::test_run_with_fake_llm_completes_and_every_pointer_resolves`（キー順 = `TRACE_FIELDS`、kind ∈ 5 種、seq 連番、JSON 化可）+ CLI 側（JSONL を読み直して検査） |
| 7 | トレース JSONL の全 pointer がモデルに解決できる | **PASS** | 同上（`jin_core.pointer.resolve_pointer` で全行）。pointer null は 0 件（`pointer を解決できませんでした` が stderr に出ない） |
| 8 | ADK に対応物のない Jin 構造がコンパイル時エラーになる（NFR-FAIL-001・黙って落とさないことの fixture テスト） | **PASS** | `tests/fixtures/build-errors/` 14 本。`test_codegen.py::test_build_error_fixture_passes_jin_check_but_fails_to_generate`（`jin check` は 0 error、`generate` は `BuildError` + hint + 解決可能な pointer）+ `test_build_run.py::test_build_fails_loudly_on_structures_without_an_adk_counterpart`（exit 1・ファイルを作らない）。`jin check tests/fixtures/build-errors` → `14 ファイル / error 0 件` |

### P2-5.2 「検査が落ちる」ことの実測（申し送り §8-3）

`delivery/20260904-1445-jin/phase2-mutations/mutate_p2.py`（__pycache__ 削除 + `PYTHONDONTWRITEBYTECODE=1`）で
**31 変異**を流した。結果は同ディレクトリの `result.txt`。

- 29 変異が赤（期待どおり）。2 変異（`BUILD-overwrite-dir-only` / `BUILD-pkg-symlink-upfront-only`）は**緑が正しい**:
  ディレクトリ単位の事前判定だけを消してもファイル単位の `O_EXCL` が、`lstat` の事前判定だけを消しても `O_NOFOLLOW` が拒む
  （二層防御）。両方を消す変異（`-both`）は赤。`build.py` の docstring に「本体は `O_NOFOLLOW` / `O_EXCL`、事前判定は文言のため」と明記
- 初回実行で **偽緑 3 件**を発見して直した: (a) ヘッダの主張テストが「再生成」の語だけを見ていて ADR-008 の文を消しても通った →
  「反映されない」「`jin build` で再生成すること」「pointer は付かない」を名指しで固定、(b) ファイル単位の `O_EXCL` を通る
  テストが無かった（ディレクトリ単位で先に拒まれる）→ `.env.example` だけが既存のケースを追加し、拒否時に作りかけの
  パッケージディレクトリを片付ける修正も入れた、(c) 上記の二層防御を harness 側で「片方だけ消しても緑」と明示
- 完了前レビュー（advisor）で **実データ喪失の経路を 1 件**検出して直した: `--force` のとき `O_TRUNC` で開いていたため、3 つ目（`.env.example` がリンクで ELOOP）で拒まれると前 2 つが **0 バイトで残っていた**（docstring の「中途半端に残さない」がこの経路で嘘・Phase 1 V-1 と同型）。常に `O_EXCL` で試し、既存かつ `--force` のときだけ `O_TRUNC` なしで開き直し、3 つとも開けたあとに `os.ftruncate`（`guard: write_project -> os.ftruncate`）。拒否時は今作ったものだけ unlink する。固定: `test_build.py::test_force_does_not_truncate_existing_files_when_a_later_file_is_refused`（バイト一致）、変異 `BUILD-force-truncates-early`（赤）

### P2-5.3 CI と同じ 8 コマンド（2026-09-05T10:30Z・本セッション実測）

| コマンド | 結果 |
|---|---|
| `UV_LOCKED=1 uv sync` | `Checked 75 packages` EXIT 0 |
| `uv run lint-imports` | Analyzed 50 files, 139 dependencies / **3 kept, 0 broken** |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 58 files already formatted |
| `uv run pytest` | **696 passed**, 45 warnings（jin-core 294 / jin-cli 112 / jin-adk 130 / contract 98 / spec 62）。warnings は google-adk 2.8.0 の `SequentialAgent` / `LoopAgent` DeprecationWarning と google-genai の Python 3.14 警告（`version-matrix.md` §8.3 #11） |
| `uv run jin schema \| diff -u schemas/jin.schema.json -` | 差分なし（モデルは変えていない） |
| `uv run jin check examples` | `2 ファイル / error 0 件 / warning 0 件` EXIT 0 |
| `uv run jin fmt --check examples` | EXIT 0 |

### P2-5.4 human_only（**実施していない・`not_run`**）

- 「実 adk run / adk web での対話動作」: API キーとネットワークが要るため実施していない。PR レビューへ送る
- レビュアが実機で踏む前に知っておくべきこと: **`examples/researcher` を `adk run` で単体実行すると、初回ターンで
  `{findings}` が未設定のため ADK が `KeyError` を出す**（実測・`decision-conformance.md` §2.18）。`jin run` は宣言済み state を
  seed するので通るが、生成物単体では通らない。これは要件書 §3.2 の例そのものが持つ性質で、Phase 2 では
  HANDOFF Q-JIN-P2-01 として人間へ返す

## P2-6. verification_status（verification-status-aggregation）

| キー | 値 |
|---|---|
| `overall` | **verified**（`required_layers = [backend_unit]` が passed・failed なし。**pipeline_e2e not_run** — 本ブランチで GitHub Actions 未実行 / **human_only not_run** — 実 adk run 未実施） |
| `scope_labels` | `["backend-unit-verified", "tdd-red-evidenced"]` |
| `layers.backend_unit` | passed（696 passed / 変異 31/31） |
| `layers.container_smoke` / `browser_e2e` | not_applicable |
| `layers.pipeline_e2e` | **not_run**（ラウンド 1 の `passed` は main の Phase 0+1 に対するもの。本ブランチの CI は親が PR で回す） |

`overall = verified` は **backend_unit に限った判定**。ラウンド 1 と同じく最終値は親が Stage 5 レビュー後に再導出する
（実装者は `verified` の根拠を上表に置くが、レビューでの再判定を妨げない）。`replay-commands.md` に Phase 2 節を追記した。

## P2-7. HANDOFF（human-decision-request・いずれも non-blocking）

```json
{
  "type": "human-decision-request",
  "round": "2/5 (Jin Phase 2)",
  "questions": [
    {
      "id": "Q-JIN-P2-01",
      "severity": "spec",
      "title": "examples/researcher の {findings} は adk run 単体では初回に KeyError で落ちる",
      "detail": "google-adk 2.8.0 は instruction の {key} が session.state に無いと KeyError で実行を落とす（instructions_utils.py:174・実測）。researcher.jin の Researcher は自分の output_key `findings` を rune で参照しているため、初回ターンでは必ず未設定になる。Phase 2 では `jin run` が .jin の宣言済み state を None で seed して machine 条件 5（exit 0）を満たした（decision-conformance.md §2.18）。生成物単体（human_only の adk run）ではこの seed は効かない。",
      "options": [
        "現状のまま（jin run だけ seed。adk run 単体で落ちることを README / adk-mapping.md §6 に明記済み）を承認する",
        "生成物側に before_agent_callback で宣言済み state を seed するコードを埋め込む（§3.2 の形から離れ、利用者の guards と同居する）",
        "要件書 §2.2 の例を `{findings?}` 相当に変える（Jin の rune 文法に ADK の optional 記法を取り込む仕様変更）"
      ],
      "recommendation": "1 つ目。2 は生成物の純粋さ（ADR-008 / ADR-009 の趣旨）を崩し、3 は要件書の変更。",
      "blocking": false
    },
    {
      "id": "Q-JIN-P2-02",
      "severity": "spec",
      "title": "flow.exit の等値比較の規則（要件書に規定なし）",
      "detail": "output_key は LLM の応答を str で入れる（実測）。equals: true と \"true\" をどう突き合わせるかを、『文字列は JSON として読み同じ JSON 型で比較（\"True\" / \"1\" は不一致、\"3.0\" = 3）』と決めた（docs/spec/model.md §3.4 の flow-exit-equality 表 / decision-conformance.md §2.14）。16 ケースのテストで一致・不一致を固定済み。",
      "options": [
        "この規則を承認する",
        "大文字小文字を無視する（\"True\" = true）など緩める",
        "文字列比較のみにする（equals: true は \"true\" とだけ一致）"
      ],
      "recommendation": "1 つ目。",
      "blocking": false
    },
    {
      "id": "Q-JIN-P2-03",
      "severity": "maintenance",
      "title": "google-adk 2.8.0 で SequentialAgent / LoopAgent が Workflow への移行を理由に DeprecationWarning",
      "detail": "構築時に `DeprecationWarning: SequentialAgent is deprecated in favor of Workflow and will be removed in a future version. Workflow cannot yet be used as an LlmAgent sub-agent` が出る（version-matrix.md §8.3 #11）。docs/spec/adk-mapping.md（人間確定の正典）は Sequential/Parallel/LoopAgent を指定しているので Phase 2 では変えていない。2.x の将来版で消えると生成物が動かなくなる。",
      "options": [
        "2.8.0 固定（TARGET_ADK_VERSION）のまま進め、Workflow への移行は別 Issue で扱う",
        "今 Workflow API を実測して adk-mapping.md を改訂する（要件書 §2.1 の対応表も変わる）"
      ],
      "recommendation": "1 つ目（Workflow は LlmAgent の sub-agent にできないと ADK 自身が言っており、Jin の delegate と両立しない）。",
      "blocking": false
    },
    {
      "id": "Q-JIN-P2-04",
      "severity": "security",
      "title": "jin run が cwd を sys.path の先頭に足すこと",
      "detail": "console script は cwd を sys.path に含めないため、ref（research.tools）を cwd から解決できるよう jin run が sys.path.insert(0, cwd) する（decision-conformance.md §2.19）。jin run は元々任意コード実行であり攻撃面は広がらないが、明示的に承認を得たい。",
      "options": ["承認する", "PYTHONPATH だけに委ねる（cwd を足さない）", "`--path <dir>` オプションで明示させる"],
      "recommendation": "1 つ目（adk run と同じ体験）。",
      "blocking": false
    },
    {
      "id": "Q-JIN-P2-05",
      "severity": "spec",
      "title": "トレース kind の final / escalate の定義",
      "detail": "要件書 §3.4 は 5 種を列挙するだけ。final = 実行全体の最後の行が model のときだけ付け替える（loop の終了判定で終わると final は無い）、escalate = StateCheckAgent の判定イベントを一致しなかった回も含む、partial は行にしない、と決めた（adk-mapping.md §2.4 trace-kinds 表）。Phase 6 のトレースリプレイの見え方に効く。",
      "options": ["承認する", "final を root agent の is_final_response に限定する", "一致しなかった判定は escalate ではなく別扱いにする（enum 追加＝要件書変更）"],
      "recommendation": "1 つ目。",
      "blocking": false
    }
  ]
}
```

## P2-8. Stage 5 レビュー依頼（親が実施）

- 対象ファイル: `packages/jin-adk/**`（src 7 + templates 2 + tests 5 + snapshots 1）/ `packages/jin-cli/src/jin_cli/main.py` /
  `packages/jin-cli/tests/{test_cli.py,test_build_run.py}` / `packages/jin-cli/pyproject.toml` / `pyproject.toml` / `uv.lock` /
  `tests/contract/{test_packaging_contract,test_dependency_direction,test_cli_contract,test_adk_version_contract}.py` /
  `tests/spec/test_spec_consistency.py` / `tests/fixtures/{build-errors,stubs}/**` / `docs/spec/{adk-mapping,model}.md` /
  `CLAUDE.md` / `README.md` / `delivery/20260904-1445-jin/{adk-api-probe,version-matrix,decision-conformance,implementation-notes,replay-commands}.md` /
  `delivery/20260904-1445-jin/implementation-plan.json` / `delivery/20260904-1445-jin/phase2-mutations/`
- `decision-conformance.md` のパス: `delivery/20260904-1445-jin/decision-conformance.md`（Phase 2 の constraints は §1 の **P2** 行 12 件 + §2.13〜§2.21 + §4.1）
- `verification_status.overall`: **verified**（backend_unit のみ。pipeline_e2e not_run / human_only not_run）
- サーフェス別追加観点: security は design.yaml `review_axes_note` (1)（`jin run` の一時ディレクトリとエスケープ）→ §4.1 の表を入力に。
  correctness は `_state_matches` の 16 ケースと `classify` の分岐、conventions は `guard:` 記法の拡張と `WriteRefused` 別名、
  wiring は `pyproject.toml` の layers（`"jin_adk"` 単独・Phase 3 で `|`）と importlib offender の厳密一致


---

# Phase 2 修正ラウンド 1（P2-R1）— Stage 5 レビュー 78 件への対応（2026-09-05・impl-p2）

指示書: `delivery/20260904-1445-jin/phase2-fix-round-1-instructions.md`。生出力: `code-review-raw/{correctness,conventions,wiring,security}-p2.md`。
規律: 新しい防御は**壊して赤くなる**ことを隔離コピー上のハーネス（`phase2-mutations/mutate_p2.py`・書き換え済み）で実測し、
仕様（`docs/spec/*.md`）とコードを同時に直し、`guard:` / `hazard:` 記法で主張を固定した。

## P2-R1.0 結果の要約

| 項目 | 値 |
|---|---|
| `uv run pytest` | **770 passed**（jin-core 294 / jin-cli 107 / jin-adk 178 / contract 129 / spec 62）。ラウンド 2 の 696 から +74 |
| 変異ハーネス（隔離コピー） | **59/59 caught**（うち 2 件は二層防御で「緑が正しい」）。`result.txt`。実ツリー不変（`imports from: /tmp/jin-mutate-*/...` を印字） |
| CI 同等 8 コマンド | すべて EXIT 0（P2-R1.4） |
| fixture | `tests/fixtures/build-errors/` **20 本**（+6）。`jin check` 0 error・`jin fmt --check` EXIT 0・正準形契約（`formattable_paths`）の対象に入れた |
| スナップショット | `--snapshot-update` で 2 本を意図して更新。差分は **ヘッダ `# source: "pipeline.jin"`（引用符付き・F-S-P2-001）と `_state_matches` の `expected.strip()`（A-5）の 2 箇所だけ**（目視で確認） |
| **A-3-1（chosen 到着後に反映済み・下の P2-R1.7）** | ~~**未着手**~~ A-3-1: cwd を `sys.path` のどこに足すか（`DP-IMPL-JIN-P2-SYSPATH-01`・auto-decider の再判断待ち）。コードは `sys.path.insert(0, cwd)` のまま。記法は `hazard:` に変え、危険性の文言（「cwd のモジュールも実行される」）は CLAUDE.md / README / adk-mapping.md §6 / `run` の docstring へ先に入れた。chosen が届いたら `run` / `hazard:` / `mutate_p2.py` の `CLI-no-cwd` / decision-conformance §2.19 を同時に追従する |

## P2-R1.1 対応表（finding ID → 変更箇所 → 固定するテスト → 変異）

「変異」列は `mutate_p2.py` の名前。すべて `RED (expected)` を実測（`result.txt`）。

### A-1 名前の衝突・重複（NFR-FAIL-001）

| finding | 変更箇所 | 固定するテスト | 変異 |
|---|---|---|---|
| F-C-P2-001（ref が builtin を上書き） | `codegen.generate`: `taken` に `_builtin_names(model)` を加え `_plan_imports` が別名化 | `test_codegen.py::test_ref_named_like_a_builtin_in_another_circle_is_aliased_not_shadowed` | `FAIL-builtin-not-taken` |
| F-C-P2-002（ADK ツール名の重複） | `codegen._validate_core_circle`: `_adk_tool_name`（tool → callable 名 / builtin → 名 / summon → circle 名）を circle 内で集計し BuildError（pointer は 2 つ目・hint「別名の関数に包むか 1 つにまとめる」） | `::test_same_callable_name_in_one_circle_is_a_build_error` / `::test_builtin_and_callable_with_the_same_adk_name_in_one_circle_is_a_build_error` / fixture `adk_tool_name_duplicate` | `FAIL-adk-tool-dup` |
| F-C-P2-003 / F-V-P2-011（circle 名 = builtin 名） | `codegen._validate`: `circle.name in builtins` → BuildError（pointer `/circles/i/name`） | `::test_circle_named_like_a_builtin_is_rejected` / fixture `builtin_name_collision` | `FAIL-builtin-circle-collision` |
| F-S-P2-002（NFKC） | `codegen._check_identifier` / `build._check_root_name`: `unicodedata.normalize("NFKC", name) != name` を拒む | `::test_non_nfkc_circle_name_is_rejected`（4 種）/ `::test_generated_assignments_bind_each_name_exactly_once`（AST: Assign target 集合 = circles + checkers）/ `test_build.py::...[ｒｏｏｔ＿ａｇｅｎｔ]` / fixture `circle_name_not_nfkc` | `FAIL-no-nfkc` / `BUILD-root-not-nfkc` |
| `test_same_callable_name_from_two_modules_gets_aliased` | 「BuildError になる」へ書き換え。別 circle なら別名化される旨は `::test_same_callable_name_in_different_circles_gets_aliased` | 同上 | — |
| `RuntimeTable.bind_tools` の「同名は None」経路 | **残した**（指示書は「到達不能なら消す」。実測で到達可能: コンパイル時は ref の attribute 名、実行時は `func.__name__`。スタブに `search_again = web_search` を足して `jin run` で null pointer + unresolved を実測） | `test_runtime.py::test_runtime_tool_name_collision_is_reported_as_unresolvable_not_hidden` / `test_trace.py::test_duplicate_tool_names_...`（モデルを `pkg_a:run` / `pkg_b:go` にして `bind_tools` を直接叩く） | `TRACE-dup-first-wins` |
| §3.1 の表 | `circle_name_not_nfkc` / `builtin_name_collision` / `adk_tool_name_duplicate` / `root_has_parent` / `flow_circle_with_instruction` / `flow_circle_with_delegate` の行を追加（`test_build_error_table_covers_every_fixture` が拾う） | `tests/spec/...::test_build_error_table_covers_every_fixture` | — |

### A-2 ファイル名経由の注入と書き込み失敗

| finding | 変更箇所 | 固定するテスト | 変異 |
|---|---|---|---|
| F-S-P2-001（改行入りファイル名がヘッダを文にする） | `codegen._header`: `py_literal(source_name)`（`guard: _header -> py_literal(source_name)`）。CLI `_require_jin_file`: `_has_unsafe_chars(file.name)` なら exit 2 | `test_codegen.py::test_source_name_cannot_inject_statements`（4 種・AST body の種類）/ `::test_jin_strings_cannot_inject_statements` に `source_name` を追加 / `test_build_run.py::test_unsafe_file_names_are_rejected_at_the_entry` | `ESC-header-raw-source-name` / `CLI-filename-unchecked` |
| F-S-P2-005（孤立サロゲートで書き込みが途中で失敗・`--force` で 0 バイト） | `codegen._EXTRA_ESCAPES` に `\udcXX` を追加（`py_literal` が生成物を常に UTF-8 で書ける形にする）。`build.write_project`: `text.encode("utf-8")` を **open より前**に済ませ bytes を `os.write`（`guard: write_project -> text.encode("utf-8")`）。CLI `_safe` / `_has_unsafe_chars` はサロゲートも対象（`typer.echo` 自体が落ちることを実測してから） | `test_codegen.py::test_py_literal_roundtrips[bad\udcff.jin]` / `test_build.py::test_unencodable_content_is_refused_before_any_file_is_touched` / `test_build_run.py::...[bad\udcff.jin]` | `ESC-surrogate-passthrough` / `BUILD-encode-late` / `CLI-safe-narrow` |
| F-C-P2-020（`WriteRefused` 以外で片付けない） | `write_project`: `except BaseException` で今作ったものだけ unlink / rmdir | `test_build.py::test_write_failure_after_open_cleans_up_only_what_it_created`（`os.write` を ENOSPC に差し替え） | `BUILD-cleanup-only-on-refusal` |
| F-S-P2-004（`OSError` のトレースバック） | `build._open_out_dir`（`out.mkdir` / `os.open`）と `_open_package_dir`（`os.mkdir` の ENAMETOOLONG）を `WriteRefused` に包む。`write_project` 全体も `except OSError` で包む | `test_build.py::test_out_that_is_a_regular_file_is_refused_without_a_traceback` / `::test_over_long_root_name_is_refused_not_a_traceback` / `test_build_run.py::test_build_reports_write_failures_without_a_traceback` | `BUILD-oserror-traceback` |
| F-S-P2-016（ファイル名を `_safe` に通さない 2 分岐） | `_require_jin_file` に統合（dump / build / run の 3 箇所の重複も解消・F-V-P2-023） | `test_build_run.py::test_unsafe_file_names_are_rejected_at_the_entry`（存在しない改行入り名でも `
` 表示） | `CLI-filename-unchecked` |
| F-S-P2-007（`<out>` 自体のリンク） | `_open_out_dir`: `O_RDONLY \| O_DIRECTORY \| O_NOFOLLOW`。Linux はリンクに対して ELOOP ではなく **ENOTDIR** を返す（実測）ので両方を見て `is_symlink()` で文言を分ける | `test_build.py::test_out_itself_is_not_followed_when_it_is_a_symlink` | `BUILD-follow-out-symlink` |

### A-3 `jin run` の cwd と `--trace`

| finding | 変更箇所 | 固定するテスト | 変異 |
|---|---|---|---|
| F-S-P2-003（cwd） | **位置は未着手（auto-decider 待ち）**。文言だけ先行: CLAUDE.md / README / adk-mapping.md §6 / `run` docstring / decision-conformance §2.19 の注記 | `test_build_run.py::test_run_adds_cwd_to_sys_path`（既存） | `CLI-no-cwd`（既存） |
| F-S-P2-006 / F-C-P2-009（`--trace` が失敗時に 0 バイト） | CLI `run`: `generate()` → `_open_trace`（`O_TRUNC` 無し）→ `_LazyTruncateSink` が最初の行の直前に `ftruncate`、正常終了時は `finish()` で必ず切り詰め（0 行の成功で古い内容を今回のトレースに見せない） | `test_build_run.py::test_failed_run_does_not_empty_an_existing_trace`（BuildError と RunError の両方）/ `::test_successful_run_replaces_the_previous_trace` | `CLI-trace-truncate-on-open` |
| F-S-P2-008（0644） | `_open_trace`: `0o600`。根拠は decision-conformance §2.22 | `::test_trace_file_is_created_owner_only` | `CLI-trace-world-readable` |

### A-4 トレースの分類と仕様表

| finding | 変更箇所 | 固定するテスト | 変異 |
|---|---|---|---|
| F-C-P2-004（transfer の function_call が tool 行） | `trace.classify`: `TRANSFER_TOOL_NAME` の function_call は行にしない（unresolved にも積まない）。§2.4 の `transfer` 行に 2 event 構造と「行にするのは応答側」を明記 | `test_trace.py::test_transfer_function_call_is_not_a_tool_row` / `test_runtime.py::test_delegate_transfer_end_to_end_has_no_stray_tool_row`（delegate の end-to-end・unresolved 空） | `TRACE-transfer-call-as-tool` |
| F-C-P2-005 / F-C-P2-018 / F-V-P2-009（escalate 2 種） | `classify`: 非 checker の `actions.escalate` は tool 行の**後**に `escalate`（name = author / pointer `/circles/i`）。§2.4 の表を 2 行に分け、`trace.KIND_POINTERS` を追加して spec テストで pointer 列を kind ごとに突合 | `test_trace.py::test_non_checker_escalate_keeps_the_tool_row_and_adds_an_escalate_row` / `tests/spec/...::test_trace_kinds_table_matches_the_implementation`（pointer 列・escalate 2 行） | `TRACE-escalate-swallows-tool` |
| F-C-P2-007（text + function_call） | `classify`: text があれば `model` 行を先に出す | `test_trace.py::test_text_and_function_call_in_one_event_give_model_then_tool_rows` | `TRACE-drop-text-with-call` |
| F-C-P2-021（error event） | `classify`: `error_code` / `error_message` があれば `output` を `{"error_code","error_message"}` に | `::test_model_error_event_is_not_shown_as_an_empty_successful_response` | `TRACE-error-hidden` |
| F-C-P2-006（summon 先が黒箱） | §2.4 / §6 に明記。Phase 3 への申し送りを `phase2-handoff.md` §6 に追加 | — | — |
| F-C-P2-017（`--session`） | help 文と §6 に「ラベル・永続化しない」 | — | — |
| F-C-P2-023（`tools[].name` は LLM に見えない） | §2.2 に 1 段落 | — | — |

### A-5 / A-6 / A-7

| finding | 変更箇所 | 固定するテスト | 変異 |
|---|---|---|---|
| F-C-P2-008 / 012（`equals` の空白・bool と数値） | `agent.py.j2` `_state_matches`: `expected.strip()`。model.md §3.4 の表を「両辺」に | `test_runtime.py::test_state_matches_semantics` に `(" yes","yes")` / `(" yes "," yes")` / `(1,"true",False)` / `(0,"false",False)` / `(1,"1",True)` | `TMPL-equals-not-stripped` / `TMPL-bool-as-number` |
| F-C-P2-016（root に親） | `codegen._check_root_is_not_a_child`（steps / delegate / summon・pointer は参照側）。`DP-REVIEW-JIN-P2-001` を `undecided[]` に起票 | `test_codegen.py::test_root_with_a_parent_is_rejected`（3 種）/ fixture `root_has_parent` | `FAIL-root-parent` |
| F-C-P2-010（同種 guard 2 件） | テストのみ（実装は正しかった） | `test_runtime.py::test_two_guards_of_the_same_kind_become_a_list_in_declaration_order` | `GEN-guards-first-only` |
| F-C-P2-011（添字対応） | テストのみ | `::test_tool_call_rows_use_the_declared_index_not_the_first_tool`（`publish` = tools[3]） | `TRACE-bind-first-index` |
| F-C-P2-013 / F-V-P2-010（flow circle の instruction / delegate / await） | fixture 2 本追加。`await` 枝は **残した**（`JinFile.model_validate` 直呼びでは到達する: 実測 OK・`jin check` は JIN070 で先に落ちるので fixture は作れない → §3.1 の行から `await` を外し、表の下に注記）。文言も F-V-P2-026 に合わせて直した | fixture `flow_circle_with_instruction` / `flow_circle_with_delegate` | `FAIL-skip-validate`（一括） |
| F-C-P2-014（`ts`） | テストのみ | `test_trace.py::test_ts_is_taken_from_the_event_timestamp` | `TRACE-ts-zero` |
| F-C-P2-015（flow の description / delegate の順序） | テストのみ | `test_runtime.py::test_flow_circle_description_and_delegate_order_survive_generation` | `GEN-delegate-reversed` |
| F-C-P2-024 / F-V-P2-019（`or` の空虚） | `assert rows[0].name == "Stranger"` に絞り、`table.unresolved` も見る | `test_trace.py::test_unknown_author_gets_a_null_pointer_not_a_dropped_row` | `TRACE-drop-unknown` |

### A-8 契約テストと配線

| finding | 変更箇所 | 固定するテスト | 変異 |
|---|---|---|---|
| F-W-P2-003 | `test_dependency_direction.py::test_jin_core_imports_no_other_jin_package`（AST・`jin_*` のうち `jin_core` 以外） | 同左 | — |
| F-W-P2-005 | `test_packaging_contract.py`: `dynamic_import_sites`（AST: `importlib*` / `runpy` の import、`__import__` / `exec` / `eval` の呼び出し、`runpy.*`）。名前を `test_importlib_is_confined_to_the_cli_resolver_and_jin_run` に（F-V-P2-001） | `::test_dynamic_import_detector_sees_each_form`（5 形・非空虚性） | — |
| F-W-P2-001 | `::test_every_package_declares_the_jin_packages_it_imports`（各 `packages/<p>/src` が import する `jin_*` が自分の `dependencies` と `[tool.uv.sources]` にある）。CLAUDE.md チェックリスト 7 項目目 | 同左 | — |
| F-W-P2-004 | `tests/conftest.py` `formattable_paths` に `build-errors` を追加 | 正準形契約 20 本が対象に | — |
| F-W-P2-007 | `test_cli_contract._run`: `PYTHONPATH` を前置 | — | — |
| F-V-P2-004 / F-V-P2-005 / F-S-P2-010 | `tests/contract/test_guard_claims.py` を新設し `packages/*/src` を走査（列挙しない）。`guard:` と **`hazard:`**（危険の所在: `_import_agent_module -> importlib.util.spec_from_file_location` / `run -> sys.path.insert`）を同じ規則で照合。`_open_trace -> os.O_NOFOLLOW` / `_truncate -> os.ftruncate` / `_header -> py_literal(source_name)` / `_check_identifier -> unicodedata.normalize` / `write_project -> text.encode("utf-8")` などを追加。test_cli.py からは移設して削除 | `test_guard_claims.py` 21 件（`::test_hazard_tags_mark_the_dangerous_operations_not_defenses` / `::test_the_scan_finds_the_modules_that_carry_claims`） | `BUILD-guard-lie` |
| F-V-P2-002 | `test_help_lists_only_phase1_commands` → `test_help_lists_phase1_commands` | — | — |
| F-W-P2-008 | `runtime.load_generated`: `shutil.rmtree(directory, onexc=_report_cleanup_failure)`（stderr に 1 行・`RunError` にしない） | `test_runtime.py::test_cleanup_failure_is_reported_on_stderr_not_swallowed`（0500 で消せなくする） | `RUN-cleanup-silent` |
| F-C-P2-019 | `runtime.run_model_async` を公開。CLI は `asyncio.run(run_model_async(project=...))`。同期 `run_model` はループ無しの呼び出し側（テスト）用に残す | `::test_run_model_async_can_be_awaited_from_a_running_loop` | — |
| F-S-P2-014 | `_safe` に U+2028 / U+2029（+ サロゲート） | `test_build_run.py::test_unsafe_file_names_are_rejected_at_the_entry` | `CLI-safe-narrow` |

### A-9 文書・成果物

| finding | 対応 |
|---|---|
| F-V-P2-003 | CLAUDE.md の「Phase 4 の jin-lsp は jin_core にしか依存しない」を design.yaml rule 5 と整合する文に。forbidden 契約を「任意コード実行の実装は `jin_cli.resolver` と `jin_adk.runtime` に閉じる」に改名し、`forbidden_modules` に `jin_adk.runtime` を追加（`lint-imports` 3 kept を実測してから）。Phase 4 で `jin_lsp` を `source_modules` に足す申し送りを `phase2-handoff.md` §6 に追加。契約名を参照する docstring（`jin_core/resolver.py` / `jin_cli/resolver.py` / 契約テスト）も追従 |
| F-V-P2-013 | CLAUDE.md: cwd の追加は CLI、`run_model` は `sys.path` を触らない |
| F-V-P2-020 | CLAUDE.md チェックリスト 4 に「兄弟がまだ無い間は単独で書く」 |
| F-V-P2-024 | CLAUDE.md: 文字列**値**は `py_literal`、識別子は検査済みのものだけ |
| F-V-P2-006（plan の extend） | `round.jin_phases` を `[0,1,2]` に / `review_status_note` を追記形に / `milestones` の削除行を復元 / **`scope_labels` は schema の enum（`backend-unit-verified` / `container-smoke-verified` / `browser-e2e-verified` / `pipeline-e2e-verified`）に限られるため指示の `pipeline-verified(phase0-1)` は入れられない**。ラウンド 1 の `pipeline-verified` もラウンド 2 の `tdd-red-evidenced` も enum 外だったので `backend-unit-verified` だけに戻し、Phase 0+1 の pipeline passed / Phase 2 の not_run を `note` に残した |
| F-V-P2-007 | decision-conformance §1 の `out_of_scope` 4 行を HEAD から復元し、直下に P2 行。§4.1 を本ラウンドの修正で更新。§2.22（trace 0600）/ §2.23（R1 で決めた挙動の根拠）を追加 |
| F-V-P2-008 | version-matrix #15 を実測どおり（`result.output` は stdout + stderr）に訂正 |
| F-V-P2-012 / F-W-P2-009 | README の「そのまま動く」を pipeline / researcher で分けて書き、例の出力先を `/tmp` に |
| F-V-P2-014 | 新規コードの死んだ `# noqa: PLR0124` を消した（`math.isnan` / `math.isinf` に）。`DP-REVIEW-JIN-002` は未決のまま |
| F-W-P2-002 / F-S-P2-011 | `mutate_p2.py` を隔離コピー上で変異する形に（`packages` / `tests` / `examples` / `pyproject.toml` を複製、`PYTHONPATH` でコピー側の `src` を優先、起動時に `jin_adk.__file__` を印字）。判定は `returncode == 1 and "failed" in summary`。`RUN-plain-mkdir` を本来の形（`tempfile.mktemp` + `Path.mkdir`）に |
| F-C-P2-022 / F-S-P2-012 / 013 / 015 / F-W-P2-006 / conventions < 70 | 記録のみ（指示書 C）。F-S-P2-015 は上記の修正で解消 |

## P2-R1.2 指示書と実物が食い違い、指示どおりにしなかったもの（理由つき）

1. **A-1-2「`bind_tools` の同名は None 経路は到達不能」→ 到達可能なので残した。** 実測: スタブに `search_again = web_search` を置き、
   `ref: research.tools:web_search` と `research.tools:search_again` を同じ circle に書くと、コンパイル時検査（attribute 名）は通り、
   実行時の `FunctionTool.name` は両方 `web_search` になる。`jin run` は tool 行を pointer null + unresolved で出す（黙らない）。
   `trace.py` の docstring と `test_runtime.py::test_runtime_tool_name_collision_...` で固定。
2. **A-1-1「ref 束縛名 vs builtin 名は BuildError」→ 別名化（同 circle 内は A-1-2 の重複検査が BuildError）。** builtin 名を `taken` に入れると
   `_plan_imports` は別名 import にする（correctness 側の提案と同じ）。別 circle なら実害が無く、同 circle なら ADK のツール名が
   重なるので A-1-2 が拒む。circle 名 vs builtin 名は BuildError。
3. **A-7「`await` 枝が到達不能なら消す」→ 残した。** `JinFile.model_validate` を直接呼ぶと flow circle + `boundary.await` は通る（実測）。
   `jin check` 済みなら JIN070 で先に落ちるので fixture は作れない。§3.1 の行から `await` を外し、表の下に注記した。
4. **A-9「`scope_labels` に `pipeline-verified(phase0-1)` を残す」→ schema 違反のため `note` で代替**（上の表・F-V-P2-006）。
5. **A-8「`run` に `guard: run -> os.O_NOFOLLOW` を足す」→ `O_NOFOLLOW` は `_open_trace` に移したので `guard: _open_trace -> os.O_NOFOLLOW`。**
   記法は「トークンが在る関数」を名指しする規則なので、`run` を名指しすると嘘になる。
6. **A-10「`run_model_async` を公開し CLI だけが `asyncio.run` する」→ 同期の `run_model` も残した**（テスト 45 件が使う・docstring に
   「ループが稼働している場所では async 版」と明記）。CLI は `asyncio.run(run_model_async(...))`。
7. **`hazard:` の対象**: `_import_agent_module -> importlib.util.spec_from_file_location` と `run -> sys.path.insert` の 2 件。
   `except BaseException`（E-A 型）は裸の名前で記法上書けないので、従来どおりテスト + 変異（`RUN-swallow-systemexit`）で代替。

## P2-R1.3 TDD の Red 証跡

新しい防御は、実装を入れる前に対応テストを書いて赤を確認した（同一セッション・順序は本節のとおり）。代表例（実測出力）:

```
# 実装前（F-S-P2-001 の再現テストだけを先に書いた状態）
FAILED packages/jin-adk/tests/test_codegen.py::test_source_name_cannot_inject_statements[...]  # body に Expr / Import が混入
# 実装後 → 88 passed
```

- codegen（A-1 / A-2-1 / A-5 / A-6）を先に実装し、`test_codegen.py` を更新した時点で **旧テスト 2 件が赤**
  （`test_same_callable_name_from_two_modules_gets_aliased` / `test_trace.py::test_duplicate_tool_names_...`）→ 仕様変更の意図どおりで書き換え
- build.py の `O_DIRECTORY \| O_NOFOLLOW` は当初 ELOOP を期待して赤（実測は ENOTDIR）→ 実装を実測に合わせた
- 変異ハーネスの各行が「実装を壊すと赤」の証跡（`result.txt`・59 件）

## P2-R1.4 CI と同じ 8 コマンド（2026-09-05・修正後に実測）

| コマンド | 結果 |
|---|---|
| `UV_LOCKED=1 uv sync` | EXIT 0（Resolved 78 / Checked 75。lock は不変） |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 59 files already formatted |
| `uv run pytest` | **770 passed**, 59 warnings（google-adk の DeprecationWarning・既知 #11） |
| `uv run lint-imports` | Analyzed 51 files, 143 dependencies（ラウンド 2 の 50 / 139 から増分 = 新モジュール無し・runtime の import 追加分）。Contracts: 3 kept, 0 broken（契約名を「任意コード実行の実装は jin_cli.resolver と jin_adk.runtime に閉じる」に改名・`forbidden_modules` に `jin_adk.runtime` を追加） |
| `uv run jin check examples` | 2 ファイル / error 0 件 |
| `uv run jin fmt --check examples` | EXIT 0 |
| `uv run jin schema \| diff -u schemas/jin.schema.json -` | 差分なし |

追加: `jin check tests/fixtures/build-errors` 20 ファイル / error 0 件、`jin fmt --check tests/fixtures/build-errors` EXIT 0。

## P2-R1.5 verification_status

`overall` は変えない（`verified`・backend_unit のみ）。修正の完了は同一観点の reviewer による再レビューで確定するため、
`review_status_note` に「再レビューで defect-gone が確認されるまでクローズしない」を追記した。
human_only（実 `adk run` / `adk web`）は引き続き **`not_run`**。pipeline_e2e は本ブランチで **`not_run`**。

## P2-R1.6 Stage 5 再レビュー依頼（親が実施）

- **変更ファイル**: `packages/jin-adk/src/jin_adk/{codegen,build,runtime,trace}.py`、`templates/agent.py.j2`、`packages/jin-cli/src/jin_cli/main.py`、
  `packages/jin-{core,cli}/src/*/resolver.py`（契約名の docstring）、`packages/jin-adk/tests/{test_codegen,test_trace,test_runtime,test_build}.py`、
  `packages/jin-adk/tests/__snapshots__/test_codegen.ambr`、`packages/jin-cli/tests/{test_cli,test_build_run}.py`、
  `tests/contract/{test_guard_claims（新規）,test_dependency_direction,test_packaging_contract,test_cli_contract}.py`、`tests/conftest.py`、
  `tests/spec/test_spec_consistency.py`、`tests/fixtures/build-errors/`（+6）、`tests/fixtures/stubs/research/tools.py`、
  `docs/spec/{adk-mapping,model}.md`、`CLAUDE.md`、`README.md`、`pyproject.toml`、
  `delivery/20260904-1445-jin/{implementation-plan.json,decision-conformance.md,version-matrix.md,replay-commands.md,phase2-handoff.md,phase2-mutations/*}`、
  `docs/pending-decisions.md`（生成器で再生成。auto-decider の AI 仮決定表も同時に反映された）
- **未対応と判断したもの**: 上の P2-R1.2 の 7 件（理由つき）と、指示書 C の記録のみ項目。**A-3-1（cwd の位置）は親の指示で待機中**
- **decision-conformance**: `delivery/20260904-1445-jin/decision-conformance.md` §1（`out_of_scope` 4 行を復元・P2 行はそのまま）/ §2.19 注記 / §2.22 / §2.23 / §4.1
- **サーフェス別の追加観点**: security は `_require_jin_file` の集合と `_open_trace` / `_LazyTruncateSink` の順序、`write_project` の `BaseException` 片付け、`_open_out_dir` の ENOTDIR 分岐。
  correctness は `classify` の行順（model → tool → escalate）と `KIND_POINTERS`。wiring は `test_guard_claims.py` の走査範囲と `dynamic_import_sites`、`forbidden_modules` に `jin_adk.runtime` を足した契約。
  conventions は plan の `scope_labels`（schema 準拠に戻した点）

## P2-R1.7 A-3-1 の反映（chosen 到着後・DP-IMPL-JIN-P2-SYSPATH-01 = `sys.path.append`）

| 変更 | 内容 |
|---|---|
| `jin_cli/main.py` `run` | `sys.path.insert(0, cwd)` → `sys.path.append(cwd)`（既に含まれていれば足さない）。`hazard: run -> sys.path.append`。`run_model` は触らない |
| テスト | `test_run_adds_cwd_to_sys_path` を「含まれる・先頭ではない」に。`tests/contract/test_cli_contract.py::test_cwd_cannot_shadow_an_installed_package_in_a_real_process` を追加（F-S-P2-003 の再現入力 = cwd の `authlib/__init__.py`。**別プロセス**で見る: 同一プロセスでは ADK の遅延 import が済んでいて再現せず、in-process 版は `insert(0)` でも緑のままだったので捨てた） |
| 変異 | `CLI-no-cwd` の before を追従。`CLI-cwd-first`（`insert(0, ...)` に戻す）を追加 → 赤 |
| 文書 | decision-conformance §2.19（「攻撃面を広げない」を撤回・残存を明記）/ §4.1、CLAUDE.md、README、adk-mapping.md §6 |
| 残存（明記） | ADK が任意依存として遅延 import する未インストールの名前（`mcp` など）は末尾でも cwd から解決される。利用者向けの防御線（信頼しない cwd で実行しない）は維持 |

## P2-R2 修正ラウンド 2（2026-09-05・`phase2-fix-round-2-instructions.md` A → B → C）

**先に回帰を塞いだ。** 修正ラウンド 1 で `asyncio.run` を CLI へ出した結果、ツール実行中の `sys.exit(0)` が exit 0 になっていた（F-S-P2-102・High）。
再発防止: `asyncio.run` を呼ぶ側は必ず `except SystemExit` で包む（CLI `run` / 同期 `run_model`。Phase 4 の pygls への申し送りは handoff §6）。
変異 `RUN-swallow-systemexit-at-runtime` / `RUN-swallow-systemexit-in-run_model` が包みを外すと赤になる。

### P2-R2.1 対応表

| 指示 | 変更 | Red → Green の証跡 |
|---|---|---|
| A-1 CLI `run` / 同期 `run_model` の `asyncio.run` を包む | `jin_cli/main.py` `run`: `except KeyboardInterrupt: raise` / `except SystemExit as exc:` → `<file>: 実行に失敗しました（SystemExit: <code>）。ref の関数が sys.exit() を呼んでいます…` を stderr・exit 1・トレースバック無し。`jin_adk/runtime.py` `run_model`: 同じ包みで `RunError`。**追加**: `run_model_async` の `except BaseException` の前に `except (KeyboardInterrupt, asyncio.CancelledError): writer.close(); raise` を置いた（着手前の実測で、`CancelledError` を `RunError` にすると asyncio が shutdown 中の未処理例外としてトレースバックを stderr に出していた） | 着手前の実測: 同期 `run_model` から `SystemExit(0)` が素通り + `RunError: CancelledError` のトレースバック。修正後: `test_build_run.py::test_tool_sys_exit_at_runtime_is_a_failure` / `test_runtime.py::test_system_exit_in_a_tool_at_runtime_is_a_run_error`（`caplog` で asyncio ロガーの ERROR 無し・`mkdtemp` スパイで一時ディレクトリ残らず）。変異 `RUN-swallow-systemexit-at-runtime` / `RUN-swallow-systemexit-in-run_model` / `RUN-cancelled-to-runerror` 各 1 failed。**実プロセスでも確認**（CliRunner の外で `jin_cli.main.app(["run", …])` を台本つき FakeLlm で実行: exit 1・stderr は ADK の警告 + `実行に失敗しました（SystemExit: 0）…` の 1 行・`Traceback` / `asyncio` の文字列無し・`/tmp/jin-run-*` 残らず。CliRunner 内では pytest の logging プラグインが asyncio ロガーを吸うため、`"asyncio" not in result.output` は実質 `caplog` 側の検査が担う） |
| A-2 docstring / handoff | `run_model_async` docstring「`SystemExit` は捕まえない（捕まえられない）。`asyncio.run` を呼ぶ側が包む」。`phase2-handoff.md` §6 に pygls 向け 1 項目 | — |
| A-3 テスト | 上の 2 本。スタブ `tests/fixtures/stubs/exits_tool.py`（`boom(x)` が `sys.exit(0)`）。CLI 側は `monkeypatch.setattr(jin_cli.main, "FakeLlm", lambda: FakeLlm(responses=[FakeToolCall("boom"…), "done"]))` | 同上 |
| A-4 変異 | `RUN-swallow-systemexit-at-runtime`（CLI の `except SystemExit` を `raise` 素通しに）+ 上記 2 件 | 3/3 赤 |
| A-5 文言 | `runtime.py` モジュール docstring（import 中 / 実行中の両方）/ `decision-conformance.md` §4.1 に実行中の行を追加 / `adk-mapping.md` §6 手順 8 | — |
| B-1 `extra_sys_path` | `load_generated` / `run_model_async` / `run_model(**kwargs)` に `extra_sys_path: Sequence[str] = ()`。`_sys_path_window`（contextmanager）が `_import_agent_module` の前に append・`finally` で remove（元からある値は足さない・取り除かない。`suppress(ValueError)`）。CLI は `extra_sys_path=[os.getcwd()]` を渡すだけで `sys.path` を触らない（`import sys` は残る: `sys.stderr` 等で使用） | `test_runtime.py::test_extra_sys_path_is_present_only_during_the_import`（窓の中で末尾・`yield` 時点で無い・元からある `STUBS` は残る・import 失敗でも外す） |
| B-2 `hazard:` / `guard:` | `hazard: _sys_path_window -> sys.path.append` / `guard: _sys_path_window -> sys.path.remove`。`main.py` の `hazard: run -> sys.path.append` は削除。`test_guard_claims.py::test_hazard_tags_mark_the_dangerous_operations_not_defenses` の規則を「`sys.path.append` は hazard・`sys.path.remove` は guard・それ以外の `sys.path.*` は hazard 限定」に変更（旧規則は `sys.path.*` 全部 hazard 限定で、guard を書いた瞬間に落ちた） | guard 検査 4 モジュール緑 |
| B-3 テスト | `test_run_adds_cwd_to_sys_path` を「`_import_agent_module` を包んで窓の中の `sys.path` を観測: cwd が含まれ・先頭ではない / 実行後は含まれない」に書き換え。`tests/contract/test_cli_contract.py::test_cwd_cannot_supply_an_uninstalled_optional_dependency_during_the_run`（`anthropic/` 版・別プロセス・`anthropic` 未インストールを `skipif` で前提化・ADK が実行中に遅延 import する事実への依存を docstring に明記 = F-W-P2-102） | 変異 `RUN-cwd-stays-after-import`（`finally` の remove を消す = Runner 実行中も cwd が残る = append 実装と同じ状態）で **3 failed**（`adds_cwd` / `present_only_during` / `anthropic` 版）。`authlib` 版は窓方式では反応しない（docstring に明記・インストール済み名の記録として残す） |
| B-4 ハーネス | `CLI-no-cwd` の before を `extra_sys_path=[os.getcwd()]` → `[]` に。`CLI-cwd-first` は CLI に append が無くなったので **`RUN-cwd-first`**（runtime の `append` → `insert(0)`）に移した。`RUN-cwd-stays-after-import` を追加。SKIP 0 件 | 64/64 caught |
| B-5 文書 | `decision-conformance.md` §2.19（修正ラウンド 2 の注記: 経緯 insert → append → 窓・chosen・「攻撃面を広げない」は窓の中に限って成り立つと書き直し・残存 2 件）/ §4.1（新行）、`CLAUDE.md`（`jin run` を名指しした禁止事項は既存・cwd の箇条書きを窓方式に・`SystemExit` の箇条書き追加）、`README.md`、`adk-mapping.md` §6 手順 3 | — |
| C F-V-P2-101 | `jin_cli/resolver.py` / `jin_core/resolver.py` の docstring を design.yaml rule 5（jin-lsp は jin_core / jin_adk / jin_render に依存し jin_cli には依存しない）に揃え、`jin_adk.runtime` への到達は Phase 4 の forbidden contract で機械化と明記 | — |
| C F-V-P2-102 | `test_dynamic_imports_are_confined_to_the_cli_resolver_and_jin_run` に改名。`CLAUDE.md` / `runtime.py` の「`importlib` を使うモジュールは 2 つだけ」を「動的 import（importlib / `__import__` / exec / eval / runpy）を使う」に。handoff §6 の参照も追従 | — |
| C F-V-P2-104 | `jin_adk.trace.TraceSink(Protocol)`（`write(text, /) -> int` のみ。`TraceWriter` は `write` しか呼ばない）。`TraceWriter.sink` / `run_model_async.trace_sink` の注釈を差し替え。`__all__` に追加 | — |
| C F-S-P2-103 | `RESERVED_NAMES` に `isinstance` / `str` / `bool` / `int` / `float` / `ValueError` / `object` を追加。hint の全列挙をやめ `jin_adk.codegen.RESERVED_NAMES` を指す文に。`test_codegen.py::test_reserved_names_cover_every_free_name_the_template_uses`（生成物の `FunctionDef` / `ClassDef` = `_state_matches` / `StateCheckAgent` の自由名 ⊆ `RESERVED_NAMES`・非空虚を assert）/ `test_reserved_generated_name_is_rejected` を 6 名でパラメタ化。`adk-mapping.md` §3.1 の行に組み込み名を追記 | 追加前に `str` / `isinstance` で `generate` が通っていた（テストが赤）→ 追加で緑 |
| C F-S-P2-104 | **tmp + `os.replace` を採用**（文言だけの案ではなく喪失経路そのものを消す）。`_open_for_write` は既存ファイルを開かず、`lstat` でリンクなら拒み、`.<name>.jin-tmp` を `O_EXCL \| O_NOFOLLOW` で作る（残骸があれば「残っています」で拒む）。全部書けたあと `_move_into_place` が `os.replace(src_dir_fd=, dst_dir_fd=)`。失敗時は一時ファイルと今作ったものだけ片付け（差し替え済みの tmp は `FileNotFoundError` を無視）。`guard: write_project -> os.ftruncate` → `guard: _move_into_place -> os.replace` + `guard: _open_for_write -> stat.S_ISLNK` | `test_build.py::test_force_write_failure_keeps_the_existing_files_intact`（2 回目の `os.write` を ENOSPC・既存 3 ファイルを先に書き換えてから比較・残骸なし）/ `::test_force_succeeds_by_replacing_through_a_temporary_file` / `::test_leftover_temporary_file_is_refused_not_overwritten`。変異 `BUILD-truncate-in-place`（旧方式に戻す）/ `BUILD-replace-early`（ファイルごとに即差し替え）/ `BUILD-follow-symlink`（before を `lstat` 判定に差し替え）各 1 failed。**`BUILD-replace-early` は初回 GREEN だった**: 再生成と同じ内容を差し替えても bytes が変わらず見えない → テストで既存 3 ファイルを `hand edited` にしてから比較する形に直して赤を確認 |
| C F-W-P2-004 / 103 | `tests/contract/test_cli_contract.py::test_fmt_check_on_every_formattable_fixture_exits_zero`（`formattable_paths` のうち `fixtures` 配下をファイルごとに `jin fmt --check`。既存の examples テストは名前どおり残す）。`test_text_roundtrip_is_byte_identical` の docstring を「`dumps` の冪等性・ディスクは読まない・ディスクは上の fmt テストが見る」に | — |
| C F-W-P2-101 | `mutate_p2.py` `_env` が `TMPDIR=<copy>/tmp` を渡す。全件実行後 `ls /tmp \| grep -c jin-run-` = 0 | 実測 |
| C F-W-P2-102 | `anthropic` 版の docstring に依存する 2 事実（未インストール名 / ADK の実行中遅延 import）を明記 | — |
| C F-V-P2-103 / 105 | チェックリスト検査に「依存する側」と `test_every_package_declares_the_jin_packages_it_imports` の 2 トークン追加。root skip を `requires_non_root = pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() == 0, …)` に | — |

### P2-R2.2 指示と違う判断（理由つき）

1. **`guard: run -> SystemExit` は書けなかった。** `test_guard_claims.py` は裸の名前をトークンとして認めない（U-1 / E-B: 部分一致で素通りするため）。
   `except SystemExit` は属性参照でも呼び出しでもないので、`main.py` の docstring に「`guard:` では主張できない。固定はテストと変異」と書き、
   `RUN-swallow-systemexit-at-runtime` / `RUN-swallow-systemexit-in-run_model` で機械化した。
2. **`CancelledError` の再送出を足した**（指示に無い）。着手前の実測で `RunError: CancelledError` のトレースバックが stderr に漏れていた
   （asyncio がループを畳むときにメインコルーチンをキャンセルし、`except BaseException` がそれを `RunError` にすると
   「unhandled exception during asyncio.run() shutdown」になる）。テストは `caplog` で asyncio ロガーの ERROR 無しを固定
   （pytest の logging プラグインが root にハンドラを付けるので stderr には出ない）。変異 `RUN-cancelled-to-runerror` で赤。
3. **`CLI-cwd-first` は `RUN-cwd-first` へ移した。** CLI に `sys.path.append` が無くなったので「before を追従」は不可能。`insert(0)` の防御は
   runtime 側の同名変異で残した。
4. **「append 実装に戻すと赤」は `RUN-cwd-stays-after-import` で確認した。** CLI に append の置き場所が無いため文字どおりには戻せない。
   `finally` の remove を消すと「Runner 実行中も cwd が `sys.path` に残る」= append 実装と同じ状態になり、`anthropic` 版が別プロセスで赤（3 failed）。
5. **F-S-P2-104 は tmp + `os.replace`**（指示書が許した代替）。`ftruncate` 方式のままの文言修正では喪失経路が残るため。連鎖して
   `guard: write_project -> os.ftruncate` と変異 `BUILD-force-truncates-early` / `BUILD-follow-symlink`（再 open の行が消えた）を差し替えた。
6. **F-W-P2-004 は既存テストを広げず新テストを足した。** `test_fmt_check_on_examples_exits_zero` の名前を保つため。
7. **ハーネスに `MUTATE_ONLY`（環境変数・カンマ区切り）を足した。** 新規変異だけを先に実測するため。省略時は全件（既定の挙動は不変）。

### P2-R2.3 件数

| 項目 | R1 後 | R2 後 |
|---|---|---|
| `uv run pytest` | 770 passed | **784 passed**（+14: A 2 / B 2 / C 10。skip 0） |
| 変異（隔離コピー・`result.txt`） | 59/59 | **64/64 caught**（+7 新規 / −2 差し替え。二層防御の緑 2 件は不変） |
| `/tmp/jin-run-*` の残骸 | 3 個 / 回 | 0 |
| guard / hazard 主張 | — | `sys.path.append`（hazard）/ `sys.path.remove`（guard）/ `os.replace` / `stat.S_ISLNK` を追加、`os.ftruncate`（build）/ `run -> sys.path.append` を削除 |

### P2-R2.4 CI と同じ 8 コマンド（2026-09-05 21:53 JST・修正後に実測）

| コマンド | 結果 |
|---|---|
| `UV_LOCKED=1 uv sync` | EXIT 0（Resolved 78 / Checked 75。lock 不変） |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 60 files already formatted |
| `uv run pytest` | **784 passed**, 61 warnings（google-adk の DeprecationWarning・既知） |
| `uv run lint-imports` | Analyzed 51 files, 143 dependencies. Contracts: 3 kept, 0 broken |
| `uv run jin check examples` | 2 ファイル / error 0 件 |
| `uv run jin fmt --check examples` | EXIT 0 |
| `uv run jin schema \| diff -u schemas/jin.schema.json -` | 差分なし |

追加: `jin check tests/fixtures/build-errors` 20 ファイル / error 0、`jin fmt --check tests/fixtures/build-errors` EXIT 0。
変異ハーネス全件 64/64 caught（`git status --porcelain` の md5 が実行前後で一致 = 実ツリー不変）。

### P2-R2.5 Stage 5 再レビュー依頼（親が実施）

- **変更ファイル**: `packages/jin-adk/src/jin_adk/{runtime,trace,build,codegen}.py`、`packages/jin-cli/src/jin_cli/{main,resolver}.py`、
  `packages/jin-core/src/jin_core/resolver.py`、`packages/jin-adk/tests/{test_runtime,test_build,test_codegen}.py`、
  `packages/jin-cli/tests/test_build_run.py`、`tests/contract/{test_guard_claims,test_cli_contract,test_canonical_contract,test_packaging_contract}.py`、
  `tests/fixtures/stubs/exits_tool.py`（新規）、`docs/spec/adk-mapping.md`、`CLAUDE.md`、`README.md`、
  `delivery/20260904-1445-jin/{decision-conformance.md,phase2-handoff.md,implementation-notes.md,implementation-plan.json,implement-ledger.md,replay-commands.md,phase2-mutations/mutate_p2.py,phase2-mutations/result.txt}`
- **未対応と判断したもの**: なし（A / B / C 全件対応）。D（correctness の再レビュー分）は未着。
- **extend 規律**: `decision-conformance.md` §2.19 は注記の追記（見出し末尾に「→ 修正ラウンド 2 で import 窓へ」を追加）、§4.1 の既存 2 行（cwd / build）は削除せず末尾に「→ 修正ラウンド 2 で差し替え」を書き足し、新行を下に追加した。`implement-ledger.md` は `[R2][impl-p2]` 1 行の追記のみ。
- **`RUN-cwd-stays-after-import` の 3 failed**: `-k "adds_cwd or present_only_during_the_import or uninstalled_optional_dependency"` が選ぶのはちょうど 3 テスト（3 failed / 102 deselected）なので、`anthropic` 版が赤に含まれることは算術で確定する。
- **重点観点**: security は `_sys_path_window` の `finally`（`suppress(ValueError)` が正しいか）と `run` の `except` 順（`RunError` → `KeyboardInterrupt` → `SystemExit`）、
  `build.py` の `os.replace` 経路（差し替え順・残骸拒否・リンク判定の TOCTOU が「リンクの消滅」に留まること）。correctness は `CancelledError` 再送出で
  `writer.close()` が二重に呼ばれないか（`_run_async` 正常終了時は `close` 済み・例外時のみここで close）。wiring は `RUN-cwd-stays-after-import` の 3 failed に
  `anthropic` 版が含まれること（`result.txt`）。conventions は `TraceSink` の位置（`trace.py`）と `requires_non_root` マーカー。

### P2-R2.6 verification_status

`overall` は触らない（`verified`〔backend_unit のみ〕のまま・最終値は再レビュー後に親が再導出。**訂正 2026-09-06（F-V-P2-201）**: 当初「partially_verified のまま」と書いたが plan の実値は R1 以降ずっと `verified` であり、記述側の誤りだった）。`evidence[]` に `[jin_phase=2][fix-round-2][tdd-red / syspath / mutation / ci-equivalent / spec]` の 5 行を追加、`tasks[]` に `T-P2-R2`、`milestones[]` に 1 行。schema（`implementation-plan.schema.json` v1）で検証済み。human_only（実 `adk run` / `adk web`）は引き続き **`not_run`**、pipeline_e2e は本ブランチで **`not_run`**。

### P2-R2.7 D（correctness の再レビュー分・2026-09-05 追記分）

| ID | 変更 | Red → Green の証跡 |
|---|---|---|
| F-C-P2-101（100・ラウンド 1 の F-C-P2-004 修正が持ち込んだ回帰） | `trace.classify`: transfer 分岐の早期 `return` をやめ、`transfer_target` を保持したまま function_call / function_response を走査。応答のうち `TRANSFER_TOOL_NAME` は行にせず、他ツールの応答を `tool` 行にしてから `transfer` 行を足す（行順 `model → tool → transfer → escalate`）。`model` 行の条件に `transfer_target` を加え、bare な transfer event（テキスト・call・response 無し）で余計な `model` 行が出ないようにした（既存 `test_transfer_points_at_the_delegate_entry` が守る） | `test_trace.py::test_transfer_keeps_the_sibling_tool_response_rows`（reviewer の `exp4` 4a: function_response 2 つ + `actions.transfer_to_agent`。修正前は transfer 行のみ = 赤 → 修正後 `[tool web_search, transfer Worker]`・`unresolved` 空）。変異 `TRACE-transfer-drops-siblings`（transfer のとき応答走査を空にする）1 failed。既存 `TRACE-transfer-call-as-tool` は 2 failed のまま |
| F-C-P2-102（80） | ラウンド 2 の A で入れた `except (KeyboardInterrupt, asyncio.CancelledError): writer.close(); raise` が defect-gone であることをテストで固定 | `test_runtime.py::test_cancelled_error_propagates_from_run_model_async`（LLM 呼び出しの中で永久に待つ `FakeLlm` 派生を差し、Runner の中に入ってから `task.cancel()` → `CancelledError` がそのまま伝わり `RunError` にならない）。変異 `RUN-cancelled-to-runerror` の target に追加 → **2 failed**（A のテストとこのテスト） |
| F-C-P2-103（100） | `jin_cli/main.py` `_open_trace`: `os.open(..., 0o600)` のあとに **`os.fchmod(fd, 0o600)`**。既存の 0644 ファイルを `--trace` に指定し直しても所有者のみに絞る。`guard: _open_trace -> os.fchmod`。仕様 §6 手順 7「0600 で作る」→「新規は mode・既存でも `fchmod` で 0600」、§2.22 は旧文を打ち消し線で残して変更理由を追記（extend） | `test_build_run.py::test_existing_trace_file_is_made_owner_only`（0644 で作った既存ファイル → 実行後 0600・旧内容は残らない。修正前は 0644 のまま = 赤）。変異 `CLI-trace-world-readable` を「`fchmod` の mode を 0644」に差し替え（新規・既存の 2 テスト赤）、`CLI-trace-keep-existing-mode`（`fchmod` を消す）で既存版だけ赤 |
| F-C-P2-002 文言（低） | `RuntimeTable.bind_tools` の unresolved 文言を「…同名の ADK ツール 'X' が 2 つ以上あり、ADK 上で同じ名前になるので片方が呼べません（どの tools[] か決められないので pointer は null）。ref の別名 import は FunctionTool.name == func.__name__ を変えません」に。§3.1 `adk_tool_name_duplicate` 行に実行時の別名束縛の残存を追記 | 既存 `test_runtime.py::test_runtime_tool_name_collision_is_reported_as_unresolvable_not_hidden` の assert（先頭一致）は不変で緑 |

**D 反映後のゲート（2026-09-05 22:08 JST・ハーネスは 22:2x に再実行）**: 8 コマンド全緑（`pytest` **787 passed** / lint-imports 3 kept / schema 差分なし）+ build-errors の check / fmt --check 緑。
変異ハーネス **66/66 caught**（`result.txt` を更新。`git status --porcelain` の md5 が前後で一致・`/tmp/jin-run-*` 残骸 0）。
初回の全件実行で `TRACE-drop-text-with-call` / `CLI-trace-follow-symlink` が `SKIP (pattern not found)`（D で `classify` の条件式と `_open_trace` の open 行が変わった）→ before を追従させて再実行し 66/66。`implementation-plan.json` の `evidence[]` に `[fix-round-2][correctness]` 行を追加。**未対応と判断したもの: なし**（D 4 件すべて対応）。

再レビュー依頼（D 分の追加ファイル）: `packages/jin-adk/src/jin_adk/trace.py`、`packages/jin-cli/src/jin_cli/main.py`、
`packages/jin-adk/tests/{test_trace,test_runtime}.py`、`packages/jin-cli/tests/test_build_run.py`、`docs/spec/adk-mapping.md`（§2.4 / §3.1 / §6）、
`delivery/20260904-1445-jin/{decision-conformance.md（§2.22）,phase2-mutations/mutate_p2.py,phase2-mutations/result.txt}`。
重点: correctness は `classify` の行順（`model → tool → transfer → escalate`）と bare transfer event で `model` 行が出ないこと、
`Hanging` LLM でのキャンセルが Runner の中で起きていること（`reached` を待ってから cancel）。security は `fchmod` が `O_NOFOLLOW` で開いた fd に対して行われること。

## P2-R3 修正ラウンド 3（2026-09-06・`phase2-fix-round-3-instructions.md` A / B / C）

### P2-R3.1 対応表

| ID | 変更 | Red → Green の証跡 |
|---|---|---|
| **A: F-S-P2-201**（Medium・95）ツール関数の `asyncio.CancelledError` が root=LlmAgent で exit 0 | 着手前の実測（ADK 2.8.0）: function_call には `id` が付く / `await` の pause は `Event.long_running_tool_ids` に id が入る / sequence 配下の cancel は `cancelling()==0` で Runner から素通り。実装: `runtime._run_async` が function_call の id（`TRANSFER_TOOL_NAME` を除く）と function_response の id、`long_running_tool_ids` を集め `(state, unanswered)` を返す。`_unanswered` = 応答の無い呼び出しのうち long-running でないもの。`run_model_async` は `unanswered` があれば `RunError("ツール 'fn' が応答を返さずに実行が終了しました（キャンセルされた可能性…）")` | `test_runtime.py::test_tool_cancelled_error_is_a_run_error_not_a_success[llm]`（修正前: `rows=[tool]` で正常終了 = 赤）/ `test_build_run.py::test_tool_cancelled_error_is_a_failure[llm]`（exit 1・トレースバック無し・「N イベント」行無し）。誤検知防止: `::test_await_pause_is_not_mistaken_for_a_missing_tool_response` / `::test_await_pause_still_exits_zero`（researcher の `publish` を `None` を返す関数に差し替え・exit 0・tool 行 1 本）。変異 `RUN-ignore-unanswered-tool`（検知を消す → llm 2 件赤・sequence 2 件は別層で緑）/ `RUN-await-pause-as-failure`（long-running を除外しない → pause の 2 件赤） |
| **A: F-S-P2-202**（Low・95）root=workflow で `CancelledError` がフルトレースバック | `run_model_async` の `except CancelledError`: `asyncio.current_task().cancelling()` が真（shutdown / 外からの cancel）なら再送出、0 なら `RunError("…CancelledError: ref の関数が asyncio.CancelledError を投げました…")`。同期 `run_model` と CLI `run` に保険の `except CancelledError` → 1 行・exit 1 | `test_runtime.py::test_tool_cancelled_error_under_a_workflow_root_is_a_run_error_from_run_model_async`（保険に頼らず `run_model_async` 単体で `RunError`）/ `::…[sequence]` / `test_build_run.py::…[sequence]` / `::test_cli_turns_a_stray_cancelled_error_into_one_line`（runtime を差し替えて `CancelledError` を直接出す → CLI の保険で 1 行）。既存 `test_cancelled_error_propagates_from_run_model_async`（外からの cancel は伝播）は緑のまま。変異 `RUN-cancelled-passthrough`（`if True:` で常に再送出 → `run_model_async` 単体テストが赤。同期 / CLI の保険があるため `run_model` 経由のテストでは見えない = 二層）/ `RUN-cancelled-to-runerror` の before を `cancelling()` 分岐に追従（2 failed のまま）/ `CLI-cancelled-traceback`（CLI の保険を素通し → 1 failed） |
| A-4 文書 | `runtime.py` モジュール docstring・`run_model_async` docstring、`adk-mapping.md` §6 手順 8、`decision-conformance.md` §4.1 に行を追加 | — |
| B: F-S-P2-203 部分適用 | `write_project` の差し替えループを `agent.py` が最後になる順に。`os.replace` の失敗を `WriteRefused("<path> の差し替えに失敗しました: … <新しい側> は新しい内容、<残り> は前の内容のままです（部分適用）。jin build --force を再実行してください")` に（`_partial_apply_note`）。原子性は追求しない | `test_build.py::test_partial_apply_on_replace_failure_is_named_in_the_message`（3 回目の `os.replace` を EACCES に → `agent.py` は前のまま・他 2 つは新しい・文言に両方） |
| B: F-S-P2-204 = **C: F-C-P2-201** 既存 mode を引き継がない | `_open_for_write` が tmp を開いたあと `os.fchmod(fd, stat.S_IMODE(info.st_mode))`（`info` は `lstat` 済み）。`guard: _open_for_write -> os.fchmod` | `test_build.py::test_force_keeps_the_existing_file_mode_F_S_P2_204_F_C_P2_201`（`agent.py` 0600 / `.env.example` 0640 が `--force` 後も保たれる。修正前は umask の 0644 = 赤） |
| B: F-S-P2-205 / F-W-P2-203 `MUTATE_ONLY` | 部分実行の最終行を `N/N mutations caught (subset of M; MUTATE_ONLY=…)` に。存在しない名前は `!! MUTATE_ONLY に存在しない変異名` を出して rc 1。0 件選択も rc 1 | `MUTATE_ONLY=nope` → rc 1（実測） |
| B: F-W-P2-201 `anthropic` の skipif | `skipif` を廃止し、テスト冒頭で `assert find_spec("anthropic") is None`（lock に入ったら失敗して前提を見直させる） | 実行（skip せず）緑 |
| B: F-W-P2-204 実プロセス版 | `tests/contract/test_cli_contract.py::test_tool_failures_are_exit_1_without_a_traceback_in_a_real_process[exits_tool / cancel_tool]`: `jin_cli.main.FakeLlm` を台本つきに差し替えて `app()` を呼ぶ小スクリプトを `sys.executable -P -c` で別プロセス実行（CLI に台本の口を足さない）。exit 1・stderr に `SystemExit` / `応答を返さず`・`Traceback` と `asyncio.exceptions` 無し・「N イベント」無し | 緑（実プロセス） |
| B: F-W-P2-202 / F-V-P2-205 `requires_non_root` | `tests/conftest.py` に 1 定義（`not hasattr(os, "geteuid") or os.geteuid() == 0` で skip）。`test_cli.py` / `test_runtime.py` は `from tests.conftest import requires_non_root`。**単独実行（`uv run pytest packages/jin-adk/tests`）で `tests.conftest` が見つからない**（importlib モードは sys.path を触らない）ため `pyproject.toml` の pytest 設定に `pythonpath = ["."]` を追加（理由をコメントに） | 単独実行 / 全体 / ハーネス（`python -m pytest`・コピー）の 3 経路で緑 |
| B: F-V-P2-203 hint | `別の名前にしてください（例: {name}_circle）。{name!r} は生成コードが使う名前（組み込み名を含む・jin_adk.codegen.RESERVED_NAMES）です` | 既存テスト緑 |
| B: F-V-P2-204 改名 | `test_run_adds_cwd_to_sys_path` → `test_cwd_is_on_sys_path_only_while_importing_the_generated_module`。ハーネスの `-k adds_cwd` 3 箇所を `only_while_importing` に追従 | — |

スタブ追加: `tests/fixtures/stubs/cancel_tool.py`（`fn` が `asyncio.CancelledError` を投げる）。

### P2-R3.2 指示と違う判断（理由つき）

1. **`pyproject.toml` に `pythonpath = ["."]` を足した**（指示に無い）。`requires_non_root` を `tests/conftest.py` に集約すると
   `packages/*/tests` から `tests.conftest` を import することになり、importlib モードでは単独実行で `ModuleNotFoundError` になった。
   CLAUDE.md の開発コマンド `uv run pytest packages/jin-core/tests` を壊さないための最小の変更。
2. **`RUN-cancelled-passthrough` の target は `run_model_async` 単体のテスト**。同期 `run_model` / CLI の保険が働くため、`run_model` 経由の
   テストではこの変異が見えない（二層防御）。Phase 4 の pygls はその保険を持たないので、単体で `RunError` になることを別テストで固定した。
3. **`agent.py` を最後に差し替える順**（reviewer の提案・指示は文言のみ）。1 行の `sorted` で、部分適用時に「`agent.py` だけ新しい」を避けられる。
4. 実プロセス版（F-W-P2-204）は **CLI に台本の口を足さず**、`FakeLlm` を差し替える小スクリプトを別プロセスで実行する形にした
   （環境変数での切替は本番 CLI の入力を増やす）。`cancel_tool` 版も同じ仕組みでパラメタ化。

### P2-R3.3 件数とゲート（2026-09-06 00:29 JST）

| 項目 | R2 後 | R3 後 |
|---|---|---|
| `uv run pytest` | 787 passed | **799 passed** |
| 変異（隔離コピー・`result.txt`） | 66/66 | **70/70 caught**（+4: `RUN-ignore-unanswered-tool` / `RUN-await-pause-as-failure` / `RUN-cancelled-passthrough` / `CLI-cancelled-traceback`。SKIP 0） |
| 8 コマンド + build-errors 2 件 | 全緑 | 全緑（lint-imports 3 kept・schema 差分なし） |
| 実ツリー / `/tmp` | 不変 / 0 | 不変（`git status --porcelain` の md5 一致）/ 0 |

`implementation-plan.json` は `evidence[]` に `[fix-round-3]` 行を追記のみ。human_only / pipeline_e2e は `not_run` のまま。

### P2-R3.4 最終確認の残り 1 件（F-S-P2-301・Low・2026-09-06）

| ID | 変更 | 証跡 |
|---|---|---|
| F-S-P2-301（ラウンド 3 の F-S-P2-204 修正が持ち込んだ） | `_open_for_write`: tmp への `os.fchmod` を `try` に入れ、失敗時は `os.close(fd)` + `os.unlink(tmp, dir_fd=)`（`suppress(OSError)`）してから `WriteRefused("<path> のモード（0600）を一時ファイルへ引き継げません: …。既存のファイルは変わっていません")`。`opened` に積む前の例外なので呼び出し側の片付けが届かなかった | `test_build.py::test_fchmod_failure_on_the_temporary_file_leaves_no_leftover`（`os.fchmod` を EPERM に → 残骸 0・既存 3 ファイル無傷・`monkeypatch.undo()` 後の `--force` が通る）。変異 `BUILD-fchmod-leftover`（片付けを消す）1 failed |

F-C-P2-301（重複 id 時の文言）は親の判断で記録のみ・対応なし。ゲート（2026-09-06 00:41 JST）: 8 コマンド + build-errors 2 件 全緑・**800 passed**・変異 **71/71**（SKIP 0・実ツリー不変・`/tmp` 残骸 0）。

---

# implementation-notes — 実装ラウンド 3/5（Jin Phase 3・jin-render）

実装者: `impl-p3` / 2026-09-06 / 対象 Issue: **#4**
作業ツリー: `.claude/worktrees/jin-phase3-6`（ブランチ `feat/jin-phase3-render`）。コミットは親が行う。
申し送りの正本: `delivery/20260904-1445-jin/phase3-handoff.md`（§1〜§12 をすべて満たした）。

## P3-1. 成果物と件数

| 項目 | 値 |
|---|---|
| `uv run pytest` | **811 passed → 1005 passed**（+194・0 failed / 0 skipped） |
| 変異ハーネス | **42/42 caught**（41 RED + 1 EXPECT_GREEN。SKIP 0・実ツリー不変・`/tmp` 残骸 0） |
| CI と同じ 8 ゲート | 全緑（§P3-5 に実測値） |
| SVG スナップショット | 4 本（`packages/jin-render/tests/__snapshots__/test_snapshots.ambr`） |
| HANDOFF | 5 件（すべて non-blocking・推奨案で実装済み。§P3-6） |

新規ファイル:

```
packages/jin-render/pyproject.toml
packages/jin-render/src/jin_render/{__init__,geometry,svg,ornament,overlay,layout}.py
packages/jin-render/tests/{__init__,conftest,test_geometry,test_svg,test_layout,test_overlay,test_determinism,test_snapshots}.py
packages/jin-render/tests/__snapshots__/test_snapshots.ambr
packages/jin-cli/tests/test_render.py
tests/contract/test_render_contract.py
tests/fixtures/traces/pipeline-fake.jsonl
delivery/20260904-1445-jin/phase3-mutations/mutate_p3.py
```

変更ファイル:

```
pyproject.toml                                   dependencies / uv.sources / root_packages / layers / forbidden 2 本
uv.lock                                          uv lock（新しい外部依存は無い）
packages/jin-cli/pyproject.toml                  dependencies / uv.sources に jin-render
packages/jin-cli/src/jin_cli/main.py             render サブコマンド + _read_trace_rows / _write_svg / _write_atomically(allow_create)
tests/contract/test_dependency_direction.py      トリップワイヤの parametrize から jin_render を外す
docs/spec/layout.md                              §3.1 / §5 / §6 / §7 / §8 を追加、§4 に丸め桁数と根拠
CLAUDE.md                                        Phase 3 = 実装済み / パッケージ境界 / 開発コマンド / Phase 3 の要点
README.md                                        jin render の使い方・構成
delivery/20260904-1445-jin/decision-conformance.md   §1 に P3 行 7 件 + §2.24（確定値 7 件）
delivery/20260904-1445-jin/implementation-plan.json  extend（round.index=3 / skill_plan 2 / tasks 3 / domain_checks 3 / evidence 7 / undecided 5）
```

## P3-2. 設計（申し送り §2 / §3 の制約をどう満たしたか）

- **依存**: `jin_render` が import するのは `jin_core` と標準ライブラリだけ。`jin_adk` は兄弟なので
  import しない。したがって**トレースの型を `jin_adk.trace` から取らず**、`jin_render.overlay` に
  最小の読み取り型（`seq: int` / `pointer: str | None` だけ・他のキーは無視）を置いた。
  動的 import（`importlib` / `__import__` / `exec` / `eval` / `runpy`）は 0 件で、
  `test_dynamic_imports_are_confined_to_the_cli_resolver_and_jin_run` の厳密一致（2 モジュール）を変えていない。
- **公開 API は 1 本**: `jin_render.render(model, *, focus=None, trace=None, upto=None) -> str`。
  CLI の `jin render` と Phase 4 の `jin/renderSvg` はこれだけを呼ぶ。
  `tests/contract/test_render_contract.py::test_the_cli_and_the_library_produce_the_same_svg` が
  CLI（別プロセス）とライブラリの出力のバイト一致を固定する。
- **純関数**: モジュールレベルの可変状態なし。`<textPath>` の id 連番を持つ `_Builder` は
  `render` の呼び出しごとに作る局所オブジェクト。ファイルを読まない（`open` / `Path` を import していない）。
- **CLI の書き込み**: `jin fmt` の `_write_atomically` を再利用した。新規作成（`-o` の対象がまだ無い）を
  許すため `allow_create: bool = False` を足し、**True のときだけ** `copymode` の代わりに
  `os.chmod(temporary, 0o644)`（`jin build` の生成物と同じモード）に落とす。既定は従来どおりで、
  `fmt` の「書き込む直前にファイルが消えました」（ENOENT）経路は残っている。新しい書き込み経路は作っていない。
- **`--trace` の読み取り**: 1 行 1 JSON オブジェクト。壊れた行は行番号つきで exit 2、JSON オブジェクトで
  ない行も exit 2、`seq` / `pointer` の型違いも exit 2（`ValueError` を CLI が受ける）。
  空行だけは読み飛ばす（末尾の余分な改行）。**黙って読み飛ばさない**（NFR-FAIL-001）。

## P3-3. 実装で確定した値（要件書に無いもの）

**全件が `docs/spec/layout.md` §6 と `decision-conformance.md` §2.24 の両方に書いてある**
（仕様側とコード側は同じ欠陥・片方だけ直さない）。主なもの:

| 値 | 決めたもの | 根拠の要点 |
|---|---|---|
| 丸め桁数 | 3 桁固定小数（`format(x, ".3f")`） | (a) 1000 px 角キャンバスで 0.001 px は DPR 4 でも 1 デバイスピクセルの 1/4000、(b) 最大座標 1000 px（キャンバスの縁）の倍精度 1 ULP は約 1.1e-13 px で刻みの 10 桁下。`test_svg.py::test_rounding_step_is_far_above_the_float_noise` が数値で固定 |
| `-0.0` | `0.0` に正規化 | `cos(90°)` 級の符号は libm で揺れ、`-0.000` と `0.000` がスナップショットをずらす |
| 楕円弧 `A` | **使わない**（3 次ベジェで描く） | `A` の large-arc / sweep フラグは 1 文字の 0 / 1 でなければならず、3 桁固定と両立しない（`0.000` は文法違反）。同じ理由で `transform` も使わない（書き出し経路が 2 本になる） |
| キャンバス | 1000 px 角 / 正規化 1.0 = 400 px | 半幅 1.25 正規化単位。境界環 0.95 の外にトレースの点（1.10）を置いても収まる |
| 強調色 | `#cc0000`（朱） | 白地に 5.9:1 / 黒線に 3.6:1 のコントラスト。**要件値ではない**（HANDOFF） |
| 入れ子の縮尺 | 0.28（**上限**） | `0.55 + 0.28 * 1.01 + 0.04 = 0.873 < 0.95` で外枠ごと境界環をはみ出さない（R1 の外枠追加と R2 の兄弟間隔で更新。現行の式とflow の節の縮小規則は `docs/spec/layout.md` §6） |
| `flow.exit` の印 | 中心（半径 0）の菱形 | 星形多角形には「閉じ目の辺」が一意に定まらない。核なし circle は中心が空いている |
| rune の切り詰め | 43 文字（超えたら 42 文字 + `…`） | 指示環の周長 / 文字の高さ = `2π*0.35/0.05 ≈ 43.98`。**比なので縮尺に依らず同じ位置**で切れる |

**環を発明していない。** 半径 1.0 の「陣の外周」を足す案は採らなかった（layout.md §1 の 4 環を
崩し、「環を持たない circle は環を描かない」というテストと矛盾する）。`/circles/i` を指す可視要素は
陣の `<g>` そのもので、子要素は `stroke` を自分で持たず group から継承する。したがって
`escalate`（`/circles/i`）が来ると陣全体が朱くなる — これはその行の意味そのものである。

## P3-4. TDD の Red 証跡

**Red 1（パッケージ追加のトリップワイヤ）**: `packages/jin-render/` を作った直後（`pyproject.toml` を
1 行も直す前）に `uv run pytest tests/contract` を回した実測:

```
FAILED tests/contract/test_dependency_direction.py::test_later_packages_do_not_exist_yet[jin_render]
FAILED tests/contract/test_packaging_contract.py::test_every_package_is_a_root_package[jin-render]
FAILED tests/contract/test_packaging_contract.py::test_every_package_appears_in_the_layers_contract[jin-render]
FAILED tests/contract/test_packaging_contract.py::test_every_package_is_declared_in_the_workspace[jin-render]
```

チェックリスト 7 点（ルート `pyproject.toml` の 5 箇所 + `packages/jin-cli/pyproject.toml` +
`packages/jin-render/tests/__init__.py`）と `uv lock` で緑に戻した。`layers` は
`"jin_adk | jin_render"` と **1 要素**に書いた（別要素に並べると実契約より強い順序になる・W-05）。
`google-adk` の forbidden 契約は名前を「jin_core / jin_render は google-adk に依存しない」へ改名し、
`test_import_linter_contracts_are_declared` が見る `"google-adk"` の語を残した。

**Red 2（実装前のテスト）**: `jin_render` の各モジュールを空のまま
`packages/jin-render/tests/test_*.py` を先に書き、`ImportError` / `AttributeError` で赤いことを
確かめてから実装を入れた。テストを書いた順は geometry → svg → layout → overlay → determinism →
snapshots で、各段で「赤 → 実装 → 緑」を回した。

**Red 3（自分のテストの誤り 3 件）**: layout のテストを最初に回したとき 3 件が赤くなり、
いずれも**テスト側**の誤りだったので実装ではなくテストを直した。記録として残す:

| 赤くなったテスト | 原因 | 直し方 |
|---|---|---|
| `test_the_nine_kinds_all_appear_across_the_examples` | examples 2 本のどちらにも `delegate` が無い | 合成モデルを 1 本足して 9 種を網羅（テスト名も `..._are_all_drawn` に変更） |
| `test_a_circle_without_a_core_draws_no_core_element` | focus=Pipeline の入れ子（Drafter）は核を持つ | 焦点の circle の pointer（`/circles/0/core`）だけを見る形に直した |
| `test_a_circular_summon_does_not_expand_forever` | 環と `<g>` が同じ pointer を持つので count が 2 になる | `<g>` の個数を数える形に直した（`data-jin` は ID ではなく鍵・layout.md §3.1） |

**Red 4（`guard:` 記法のトークン）**: `tests/contract/test_guard_claims.py` の `CLAIM` 正規表現は
トークンを `(\S+)` で拾うので、**空白を含むトークンは途中で切れて `SyntaxError`** になる。
`guard: attr_value -> escape(value, _ATTR_ENTITIES)` が実測で赤くなり、空白を詰めた
`escape(value,_ATTR_ENTITIES)` に直した（`ast.dump` の比較なので空白の有無は影響しない）。
`guard: _write_svg -> _write_atomically` も**裸の名前**として `GuardTokenTooLoose` で落ちたので、
呼び出しの形（`_write_atomically(path,text,allow_create=True)`）に直した。**Phase 4 の実装者向けの罠。**

## P3-5. CI と同じ 8 ゲート（2026-09-06・`__pycache__` 削除 + `PYTHONDONTWRITEBYTECODE=1` で実測）

| # | コマンド | 結果 |
|---|---|---|
| 1 | `UV_LOCKED=1 uv sync` | EXIT 0（Resolved 79 packages / Checked 76 packages） |
| 2 | `uv run ruff check .` | All checks passed! |
| 3 | `uv run ruff format --check .` | 77 files already formatted |
| 4 | `uv run pytest` | **1005 passed**（0 failed / 0 skipped。ベースライン 811） |
| 5 | `uv run lint-imports` | Contracts: **3 kept, 0 broken**（Analyzed 59 files, 174 dependencies・実測） |
| 6 | `uv run jin schema \| diff -u schemas/jin.schema.json -` | 差分なし（`model.py` を変えていない） |
| 7 | `uv run jin check examples` | 2 ファイル / error 0 件 / warning 0 件（EXIT 0） |
| 8 | `uv run jin fmt --check examples` | EXIT 0 |

変異ハーネス: `uv run python delivery/20260904-1445-jin/phase3-mutations/mutate_p3.py` → **42/42 caught**
（EXIT 0・SKIP 0）。内訳は申し送り §10 が名指しした 7 種を含む:

| 申し送りの指示 | 変異名 | 結果 |
|---|---|---|
| 丸め関数を素の `str()` に替える | `DET-plain-str` / `DET-repr` / `DET-two-decimals` | RED |
| `data-jin` を 1 要素だけ落とす | `CONTRACT-core-no-pointer` / `CONTRACT-ring-no-pointer` | RED |
| 装飾を sha256 でなく固定にする | `ORN-fixed` / `ORN-builtin-hash` | RED |
| 祖先一致を消す | `OVL-exact-only` / `OVL-no-referent` / `OVL-no-ref-attribute` | RED |
| XML エスケープを外す | `ESC-attr-passthrough` / `ESC-text-passthrough` / `ESC-quoteattr-style` | RED |
| `focus` を無視する | `FOCUS-ignored` / `FOCUS-unknown-silent` | RED |
| k を `n//2` にする | `STAR-n-half` / `STAR-always-one` / `STAR-reversed` | RED |

`CLI-follow-symlink-upfront-only` だけは **GREEN が正しい**（`_write_svg` の事前判定を消しても
`_write_atomically` の `Path(path).is_symlink()` が拒む二層防御）。両層を消す
`CLI-follow-symlink-both` で赤くなることを別に実測した（`EXPECT_GREEN` の門を見える形にしてある）。

machine 条件 8 項目（design.yaml `implementation_phases.items[3].verification.machine`）の対応:

| # | machine 条件 | 固定するテスト |
|---|---|---|
| 1 | SVG スナップショットが examples 2 本で安定 | `test_snapshots.py`（4 本。**正規化せず素のバイト列**で比較・理由は §P3-7） |
| 2 | 同一入力 2 回でバイト一致 | `test_determinism.py::test_two_renders_in_one_process_are_byte_identical` |
| 3 | 全要素が `data-jin` / `data-jin-kind` を持ち、全 pointer がモデルに解決できる | `test_layout.py::test_every_element_carries_both_attributes` / `::test_every_pointer_resolves_in_the_model` / `tests/contract/test_render_contract.py::test_every_rendered_pointer_is_in_the_model_pointer_space` |
| 4 | `data-jin-kind` が §2.5 の 9 種 | `test_layout.py::test_every_kind_is_one_of_the_nine` +（空虚防止）`::test_the_nine_kinds_are_all_drawn` |
| 5 | `upto` を増やすと強調が単調増加 | `test_overlay.py::test_highlights_grow_monotonically_with_upto` |
| 6 | `focus` を切り替えると展開対象が変わる | `test_layout.py::test_focus_changes_the_expanded_circle` / `::test_focus_expands_only_depth_one` |
| 7 | 異なる `PYTHONHASHSEED` の別プロセス 2 回でバイト一致 | `test_determinism.py::test_two_processes_with_different_hash_seeds_agree`（seed 0 / 4242）+ overlay 版 |
| 8 | 装飾が rune を変えると変わり、変えなければ変わらない | `test_determinism.py::test_the_ornament_changes_when_the_rune_changes` / `::test_the_ornament_does_not_change_when_the_rune_stays` / `::test_the_ornament_uses_sha256_not_the_builtin_hash` |

human_only（図としての可読性・魔法陣としての見た目の妥当性）は **`not_run`**。実装者は判定しない。
`pipeline_e2e` も **`not_run`**（implementer は commit / push しないので GitHub Actions は未実行。
Phase 2 の実機結果は `evidence[]` の `[jin_phase=2][pipeline]` に残してある）。

## P3-6. HANDOFF（human-decision-request・いずれも non-blocking・推奨案で実装済み）

`implementation-plan.json` の `undecided[]` / `undecided_details[]` に登録した 5 件。
親が auto-decider に回して `ai_provisional` で記録すること。

| DP ID | 論点 | 選択肢 | 推奨 |
|---|---|---|---|
| `DP-IMPL-JIN-P3-ROUNDING-01` | SVG 座標の丸め桁数 | (1) 3 桁のまま (2) 別の桁数 | **(1)**。根拠 2 点（px 解像度 / 浮動小数ノイズ）を実測済み。変えるとスナップショット 4 本が全更新なので Phase 4 着手前が安い |
| `DP-IMPL-JIN-P3-ACCENT-COLOR-01` | 強調 1 色の値 | (1) `#cc0000` (2) 別の色（定数 1 つ + スナップショット 1 本） | **(1)**。要件書に値が無い（T-002）。白地 5.9:1 / 黒線 3.6:1 のコントラストで選んだ |
| `DP-IMPL-JIN-P3-OVERLAY-REFERENT-01` | trace overlay の強調規則（祖先一致 + referent 規則） | (1) この規則 (2) `data-jin` を参照先にする（hit-test が壊れる） (3) 参照要素を強調しない（root 焦点でトレースがほぼ見えない） | **(1)**。規則は layout.md §7.1・機械固定は `test_render_contract.py::test_every_live_pointer_resolves_at_the_root_focus` |
| `DP-IMPL-JIN-P3-SVG-ROOT-CONTRACT-01` | `<svg>` と `<defs>` を `data-jin` 契約の対象外にする解釈 | (1) 対象外 (2) `<svg>` に `data-jin=""` を付けて 10 種目の kind を足す | **(1)**。(2) は要件書 §2.5 の 9 種を変えることになる |
| `DP-IMPL-JIN-P3-RENDER-ON-ERROR-01` | error 診断があるファイルを `jin render` が描くか | (1) 既定で拒む・オプションを足さない (2) `--force` で描けるようにする | **(1)**。ライブラリ側（`jin_render.render`）は意味エラーを含むモデルでも図を出すので、Phase 4/5 の体験には影響しない |

**修正ラウンド 1 で足した 1 件**（`undecided[]` に追加登録した 6 件目）:

| DP ID | 論点 | 選択肢 | 推奨 |
|---|---|---|---|
| `DP-IMPL-JIN-P3-LOOP-STAR-ORDER-01` | `loop` の星形多角形で、矢じりの向きを実行順に一致させる方法 | (a) 節 j を角位置 `(j*k) mod n` に置き、辺は `j → (j+1) mod n`（星形と訪問順の両立） (b) 配置と辺は現状のまま矢じりを外す（向きの主張をやめる） (c) 現状のまま（要件書 §2.5 と食い違う） | **(a)**。親判定で (a) を実装済み。`gcd(n,k)=1` なので写像は全単射で、星形の見た目は変わらない。変えたのは「どの節がどの角位置に載るか」だけ |

質問セット（auto-decider へ）:

1. 要件書 §2.5「辺の順を訪問順に一致させる」は、**矢じりの向き**が `flow.steps` の順を指すことを
   意味するという解釈でよいか（それとも「星形の辺を訪問順で辿れる」だけの意味か）
2. (a) は `loop` の節の角位置を変えるので、n>=5 の loop を含む `.jin` のスナップショットが動く。
   examples 2 本に loop は無いので今回の差分は 0 だが、Phase 5 のエディタが位置を覚える設計に
   するなら、この変更は Phase 4 着手前に確定させたい。その前提でよいか
3. `n < 5` は k=1 なので配置は配列順のまま（`test_a_small_loop_keeps_the_array_order_placement`）。
   これで良いか

未決のまま持ち越すもの: `DP-REVIEW-JIN-P2-002`（空トレースの印）。Phase 3 は申し送り §9 の指示どおり
「空トレース（0 行）は点 0 個・強調なし」で描き、判断を待つ（`test_overlay.py::test_an_empty_trace_draws_no_dot_and_no_highlight` が現在の挙動を固定）。

## P3-7. 判断の記録（指示と違う判断・迷った点）

1. **スナップショットを正規化しない**（design.yaml machine 1 は「（正規化後）」と書いている）。
   `render` の出力は既にバイト単位で決定的で、machine 2 / 7 を別テストで固定している。正規化を挟むと
   「正規化で消える差分」（座標の桁揺れ・属性順の入れ替わり・要素順の変化）が検出できなくなる。
   どれも意味のある回帰なので**素のバイト列**で比較した。
2. **`<svg>` の背景を塗らない**。塗ると `data-jin` を持たない描画要素（`<rect>`）ができ、
   契約の例外がもう 1 つ増える。SVG の既定どおり透明にし、埋め込む側の地色を使う。
3. **深さ 1 の入れ子はその circle を丸ごと同じ規則で描く**（核・環・紋・rune・装飾まで）。
   そのため `focus=root` でも `/circles/2/core` のような下位の pointer が**完全一致**で解決する。
   referent 規則が要るのは深さ 2 以降（点になった参照）だけである。両方が必要なことは
   `test_overlay.py` の 2 本（`..._nearest_ancestor` / `..._under_its_referent`）で別々に固定した。
4. **祖先一致の非空虚性のために合成トレース行を 1 件置いた**。入れ子を再帰で描くと、コミット済み
   トレースの 11 行はすべて完全一致か referent で解決してしまい、「祖先一致だけが効く」ケースが無い。
   `/circles/1/flow/max`（Refine に `max: 3` があるのでモデルには解決するが描画要素は無い）を
   使って `/circles/1/flow`（弦）に落ちることを固定した。
5. **loop の辺にも矢じりを付けた**。要件書 §2.5 は `sequence` にだけ「（矢印）」と書いているが、
   §2.1 が「辺の順は訪問順に一致させる」と要求しており、矢じりが無いと訪問順を目で追えない。
   `parallel` は仕様どおり弦を描かない。
6. **`await` が `tools` に無いとき（JIN070）は境界環を切らない**。角度が決まらないので欠けを
   作れない。12 時位置に破線の刻印を置き、`test_layout.py::test_an_unresolved_await_is_drawn_dashed_at_twelve_o_clock`
   が「境界環が弧に割れていない」ことまで固定する。
7. **重複 circle 名（JIN010）は先に宣言されたほうを採る**。`{c.name: i for ...}` の後勝ちにすると
   「後ろに足した重複が前の参照先を奪う」ことになり、書き手の直感と逆になる。
8. **`--trace` の空行は読み飛ばす**。末尾の余分な改行は「壊れた行」ではない。それ以外
   （JSON でない / オブジェクトでない / 型違い）はすべて exit 2 にした。
9. ~~**`jin render -o` の新規ファイルは `os.chmod(temporary, 0o644)` で作る（umask を無視する）**~~
   → **修正ラウンド 1 でレビューに覆された**（F-S-P3-004 / F-V-P3-015・親判定）。現在は
   `_new_file_mode()` が `0o644 & ~umask` を返し、`jin build` の実効モードにそろえてある。
   当時の根拠 (b)（umask の往復が別スレッドの作るファイルに漏れる）は**撤回する**: `jin render`
   は CLI の単一スレッドで、この往復の間に他のファイルを作らない。Phase 4 の LSP が
   `jin_render` を組み込むときも、書き出しを行うのは `jin_cli` の側だけである。
   根拠 (a)（`mkstemp` の 0600 のままにしない）は残る。(c)（SVG は秘匿対象ではない）は
   「だから緩めてよい」の理由にはならない — umask は利用者の指定であり、実装が上書きする
   ものではない。詳細は P3-R1.1 の C-2 行。

## P3-8. Stage 5 レビュー依頼（親が実施）

レビュー対象（4 軸: correctness / conventions / wiring / security）:

- **実装**: `packages/jin-render/src/jin_render/{geometry,svg,ornament,overlay,layout}.py`（計 約 1100 行）、
  `packages/jin-cli/src/jin_cli/main.py` の `render` / `_read_trace_rows` / `_write_svg` /
  `_write_atomically`（`allow_create` の追加）
- **テスト**: `packages/jin-render/tests/`（6 ファイル）、`packages/jin-cli/tests/test_render.py`、
  `tests/contract/test_render_contract.py`
- **仕様**: `docs/spec/layout.md`（§3.1 / §4 / §5 / §6 / §7 / §8）
- **記録**: `decision-conformance.md` §1 の P3 行 7 件 と §2.24、`implementation-plan.json`、
  `phase3-mutations/mutate_p3.py`

特に見てほしい点:

1. **`jin_render` が本当に純関数か**（モジュールレベルの可変状態・辞書順序依存・`id()` 依存）。
   `fired_indices` は要素の**添字**で集合を作っており `id()` を使っていないが、走査順に依存が無いかを見てほしい。
2. **`data-jin` 契約の穴**: `<svg>` / `<defs>` を除外した解釈（HANDOFF）と、追加属性 4 種が
   Phase 5 のエディタのヒットテストを壊さないか。
3. **XML エスケープ**: 属性値とテキストノードの両方を通しているか。`href="#jin-rune-N"` の id 生成に
   利用者入力が混ざっていないか（混ざっていない = 連番）。
4. **`_write_atomically(allow_create=True)` の追加**が `fmt` の既存経路（ENOENT を WriteRefused にする）を
   壊していないか。`packages/jin-cli/tests/test_cli.py` は 2026-09-06 の実測で **75 passed**（以前ここに書いていた「42 件」は出所不明の数だった・F-V-P3-023）。
5. **overlay の強調規則**が「発火していないのに強調される」方向へ広すぎないか（祖先一致は
   `/circles` まで登るので、理論上は `/circles` を指す要素があれば全体が光る。現状そんな要素は無い）。

`verification_status`: `backend_unit = passed` / `container_smoke = not_applicable` /
`browser_e2e = not_applicable` / `pipeline_e2e = **not_run**` / `overall = verified`（
`scope_labels = ["backend-unit-verified"]` の範囲での判定）。human_only は `not_run`。

## P3-R1. 修正ラウンド 1（Phase 3 Stage 5 レビューの 62 件）

指示書: `delivery/20260904-1445-jin/phase3-fix-round-1-instructions.md`。
生出力: `delivery/20260904-1445-jin/code-review-raw/{correctness,conventions,wiring,security}-p3.md`。

### R1.0 まとめ

| | 前 | 後 |
|---|---|---|
| テスト | 1005 passed | **1100 passed** |
| 変異（`mutate_p3.py`） | 42 本 / 42 caught（うち 1 本は期待 GREEN） | **59 本 / 59 caught**（うち 1 本は期待 GREEN・SKIP 0） |
| CI 8 ゲート | 全緑 | 全緑（下の R1.4） |
| スナップショット | 4 本 | 4 本（3 本更新・R1.1 の B-1 行） |

指示書の A（11）・B（9）・C（2）は**全件**対応した。D 節は 28 項目（重複を除いた
finding ID は 32 件）を列挙しており、そのうち **24 項目を直し、4 項目**（F-C-P3-013 /
F-V-P3-013 / F-W-P3-010 / F-S-P3-013）は理由を添えて記録のみにした（R1.2 の 7〜9）。

### R1.1 finding → 変更 → 固定するテスト → 変異

| # | finding | 変更 | 固定するテスト | 変異（RED を実測） |
|---|---|---|---|---|
| A-1 | F-C-P3-001 / F-S-P3-003 | `_read_trace_rows` を `path.open(newline="\n")` のストリーム読みにし、行末の `\r` を 1 つ落とす。テスト側 7 箇所の `splitlines()` も `split("\n")` に | `test_render.py::test_a_row_containing_a_unicode_line_break_is_read`（U+2028 / U+2029 / U+0085）、`test_crlf_line_endings_are_accepted`、端到端 `test_render_contract.py::test_a_trace_written_by_jin_run_is_readable_by_jin_render` | `TRACE-splitlines` |
| A-2 | F-S-P3-001 | `except ValueError` / `except RecursionError` → exit 2。`seq` の上限 `2^63-1` | `test_a_huge_integer_seq_exits_two`、`test_a_deeply_nested_json_row_exits_two`、`test_overlay.py::test_a_seq_outside_the_range_is_refused` | `TRACE-no-recursion-guard`、`OVL-no-seq-upper-bound`、`OVL-brief-raw-repr` |
| A-3 | F-S-P3-002 | `pointer_prefixes` を廃し、`by_pointer` の鍵を走査して最長一致を採る（`is_ancestor_or_same`） | `test_ancestor_matching_is_segment_wise`（7 param）、`test_a_huge_pointer_does_not_blow_up_memory_or_time`（5 万段） | `OVL-exact-only`、`OVL-prefix-not-segment-wise` |
| A-4 | F-V-P3-001 | `DASH` を `fmt_coord` で組み立てる | `test_all_geometry_numbers_are_written_with_three_decimals[dashed]`、`test_every_numeric_attribute_is_covered_by_at_least_one_model` | `DASH-raw-literal` |
| A-5 | F-V-P3-002 | 空虚なテストを `test_names_are_not_emitted_into_the_svg` に置き換え、`svg.py` docstring を実物（rune のテキストノードだけ）に合わせた | 同名テスト | `ESC-attr-passthrough`（単体テストが守っていることの再確認） |
| A-6 | F-V-P3-003 | `test_at_least_one_live_pointer_resolves_for_each_focus` に改名 | 同名テスト | — |
| A-7 | F-W-P3-001 | google-adk 隔離契約の網羅テスト（契約は `forbidden_modules == ["google"]` で探す） | `test_packaging_contract.py::test_adk_isolation_contract_covers_every_package_but_jin_adk_and_jin_cli` | `pyproject.toml` の google 契約の `source_modules` を `["jin_core"]` に落とすと **1 failed**（`AssertionError: google-adk 隔離契約の source_modules に {'jin_render'} が無い`）。戻して緑・ファイルはバイト一致を確認（2026-09-06 実測） |
| A-8 | F-W-P3-002 | 注入テストを `(package, target_file, injected, keyword)` に広げ 4 ケース追加 | `test_import_linter_actually_bites_on_a_forbidden_import`（7 param） | テスト自身が変異（違反注入）である |
| A-9 | F-W-P3-003 / F-S-P3-012 / F-C-P3-006 | `_write_svg` が親ディレクトリの不在を拒む（**作らない**）。README に 1 行 | `test_a_missing_parent_directory_is_refused_without_creating_it` | `CLI-create-parent` |
| A-10 | F-W-P3-005 | `jin render --help` が exit 0 で返ることを見る | `test_render_is_a_registered_subcommand` | `CLI-render-not-registered` |
| A-11 | F-W-P3-006 | `_jin_imports` の走査を `packages/<p>/tests/` にも掛ける | `test_package_tests_only_import_the_jin_packages_that_package_depends_on` | `packages/jin-render/tests/test_svg.py` に `import jin_adk` を足すと `[jin-render]` param が **1 failed**（`jin-render/tests が ['jin_adk'] を import している`）。戻して緑・ファイルはバイト一致を確認（2026-09-06 実測） |
| B-1 | F-C-P3-003 / F-C-P3-005 | `summon` の外枠（参照側 pointer・kind `tool`・`data-jin-ref`）を wrapper 直下に描く。放射線と弦の終端を `_outer_extent` から導く | `test_a_summon_draws_a_visible_outline_that_the_tool_row_highlights`、`test_the_summon_outline_follows_the_inner_circles_actual_reach`（4 param）、`test_the_radial_line_stops_at_the_summon_outline` | `SUMMON-no-outline`、`SUMMON-fixed-extent` |
| B-2 | F-W-P3-004 | `tests/conftest.py` に `child_env` / `env_with_stubs` を置き、`test_cli_contract._run` と `test_render_contract.live_trace` の両方をそこへ寄せた（`mutate_p3.py` の `_env` は既に前置済み） | 既存の子プロセステスト全部 | — |
| B-3 | F-V-P3-004 | `TraceRowError` が並びの位置を持ち、CLI が受理行の実ファイル行番号へ写して `path:N:` を出す | `test_a_bad_row_reports_the_real_file_line_number`（空行 3 本入り） | `CLI-row-index-as-line` |
| B-4 | F-V-P3-008 / F-C-P3-010 | 「1300 px 級 / 2.3e-13」→「最大 1000 px / 約 1.1e-13」を layout.md §4・decision-conformance §2.24.1・notes の 3 箇所で直し、テストの `largest` を `geo.CANVAS_PX` から導く | `test_rounding_step_is_far_above_the_float_noise` | `DET-two-decimals`（既存） |
| B-5 | F-S-P3-005 | `xml_chars` が XML 1.0 `Char` の外を U+FFFD に落とす。`attr_value` / `text_value` の両方が通る | `test_a_character_outside_xml_char_becomes_the_replacement_character`（7 param）、`test_a_rune_with_a_noncharacter_still_parses_as_xml` | `ESC-xml-chars-passthrough` |
| B-6 | F-V-P3-005 | `_write_svg` の `guard:` を `_write_atomically(...)` 1 本にし、事前 5 条件を「文言のための早期判定（防御ではない）」と散文で書いた | `test_guard_claims.py` | `CLI-follow-symlink-both`（既存・二層目を消すと赤） |
| B-7 | F-V-P3-006 | guard 走査の期待集合に `jin-render/src/jin_render/svg.py`。CLAUDE.md のチェックリストに 8 項目目 | `test_the_scan_finds_the_modules_that_carry_claims`、`test_claude_md_has_the_package_addition_checklist` | — |
| B-8 | F-V-P3-007 | layout.md §7.2 の表を書き写した pointer → kind テスト | `test_a_pointer_lands_on_the_kind_the_table_says`（7 param）、`test_the_flow_exit_mark_lands_on_the_flow_edge_kind`、`test_a_pointer_with_no_element_falls_back_to_its_ancestor` | `CONTRACT-tenth-kind`（既存）ほか |
| B-9 | F-C-P3-004 / F-S-P3-007 / F-V-P3-019 | `read_trace` が `seq < 1` を拒む（上限と 1 本の条件） | `test_a_seq_outside_the_range_is_refused`、`test_a_seq_below_one_exits_two` | `OVL-accept-seq-zero` |
| C-1 | F-C-P3-002 | 節 j を角位置 `(j*k) mod n` に置き、辺を `j → (j+1) mod n` に。layout.md §2.1 / §6 とテストを同時に直した。HANDOFF 登録 | `test_loop_nodes_are_placed_so_the_arrows_follow_the_visit_order`（n=3..12）、`test_a_small_loop_keeps_the_array_order_placement`、既存の `test_loop_edges_follow_the_star_polygon` | `STAR-slot-identity`（**実測は R2 で訂正**: 配置を恒等に戻すと辺 j→j+1 が単純多角形になるので `test_loop_edges_follow_the_star_polygon[5-2]` / `[8-3]` が赤・訪問順テストは緑。2 本が独立に効くことは `STAR-pre-fix-visit-order` と `STAR-pre-fix-star-shape-stays` が示す・F-C-P3-104）、`STAR-reversed` |
| C-2 | F-S-P3-004 / F-V-P3-015 | `_new_file_mode()` = `0o644 & ~umask`。P3-7 項 9 を「レビューで覆された」に書き換え、根拠 (b) を撤回 | `test_the_output_file_is_created_with_the_generated_file_mode`（umask 0o022/0o002/0o077）、`test_the_created_mode_matches_what_jin_build_writes`（`jin build` の実物と突合） | `CLI-ignore-umask`、`CLI-new-file-0600` |

D（低確度）で直したもの:

| finding | 変更 |
|---|---|
| F-C-P3-007 | 到達しない `accent_attr="fill"` を外し、理由をコメントに |
| F-C-P3-008 | テスト docstring の存在しない規則番号を §7.1 の実際の項目名に |
| F-C-P3-009 / F-V-P3-012 | 「24 バイト目」→「添字 24（= 25 バイト目）」を 3 箇所で統一 |
| F-C-P3-011 / F-S-P3-009 / F-W-P3-008 / F-V-P3-016 | 成功時の文言も `_safe` を通す（`test_the_success_message_does_not_carry_control_characters`） |
| F-C-P3-012 | 核なし circle + `state` / `boundary` / `delegate` の描画テストを追加 |
| F-V-P3-009 | `__import__("xml.etree.ElementTree", …)` を通常 import に |
| F-V-P3-010 | 「`docs/spec/model.md` §3.3」→「CLAUDE.md / ADR-012」 |
| F-V-P3-011 | 効かない `# noqa: TRY004` と規則名の言及を外す |
| F-V-P3-014 | 恒等関数 `radii_or` を消し、`approx in list` を `any(...)` に |
| F-V-P3-017 | `ARROW_HEAD` を `geometry.py` へ移す（`layout.py` は再輸出）。layout.md §6 に「導出値は layout.py」 |
| F-V-P3-018 | `__init__.py` に「サブモジュールの `__all__` は契約ではない」を 1 行 |
| F-V-P3-020 | `_await_angles` / `_flow_extent` / `_flow_slots` の `assert` を引数の型で置き換え |
| F-V-P3-021 | 楕円弧の検査を `d` 属性だけに絞り、rune に `A tool L 1` を含むモデルでも回す |
| F-V-P3-022 | `test_determinism.py` の関数内 import を先頭へ |
| F-V-P3-023 | 「既存 42 件」→ 2026-09-06 実測の **75 passed** |
| F-V-P3-024 | layout.md 冒頭の Phase 区分を実際の追記範囲に |
| F-V-P3-025 | `pointers()` の既定値 `""` をやめ `None` を返す。呼ぶ側で `is not None` を先に見る |
| F-S-P3-006 | `except UnicodeDecodeError` の枝を `test_a_trace_that_is_not_utf8_exits_two` で通す |
| F-S-P3-008 | `brief()` がメッセージに載せる値を 80 文字で切る（4300 桁超の int は `repr` 自体が落ちるので型名に） |
| F-S-P3-010 | `sys.stdout.buffer.write(svg.encode("utf-8"))`。R1.2 の 2 行目も参照 |
| F-S-P3-011 | `--trace` をストリーム読みにした（全読み + `splitlines` の 2 重コピーをやめた） |
| F-W-P3-007 | `-o` が入力の `.jin` と同じなら `--force` でも拒む |
| F-W-P3-009 | `MUTATE_ONLY` の綴り検査を baseline の**前**に移した（`MUTATE_ONLY=NOPE` で即 exit 1 を実測） |
| F-W-P3-011 | `-o` がディレクトリなら専用の文言で拒む |

### R1.2 指示書と違えた判断

1. **C-2 のテスト期待値を `0o666 & ~umask` ではなく `0o644 & ~umask` にした。** 指示書は
   「`jin build` に合わせる」と「`0o666 & ~umask` を assert する」を並べているが、umask 0o002 では
   前者が 0o644、後者が 0o664 で食い違う。`jin build` は `os.open(name, O_CREAT | O_EXCL, 0o644)`
   （`jin_adk/build.py`）なので実効モードは `0o644 & ~umask`。**実物にそろえるほうを採った**。
   `test_the_created_mode_matches_what_jin_build_writes` が `jin build` の出力と実測で突き合わせる
   ので、どちらかが動けば落ちる。
2. **F-S-P3-010 を「1 行 exit 1 に包む」ではなく `sys.stdout.buffer` への UTF-8 書き出しにした。**
   包むだけだと「rune が日本語の `.jin` は `PYTHONIOENCODING=ascii` では描けない」ままで、
   `-o` は UTF-8 固定なのに stdout はロケール依存という非対称も残る。バイト列で書けば
   `test_stdout_and_the_output_file_are_byte_identical` の主張がロケールに依らず成立する。
   この差は CliRunner の中では測れない（stdout が常に UTF-8）ので、別プロセスで
   `PYTHONIOENCODING=ascii` を渡す `test_render_contract.py::test_stdout_is_utf8_even_when_the_locale_cannot_encode_the_rune` を置いた。
3. ~~**A-1 の端到端テストは `.jin` の `core` ではなくモデル出力に U+2028 を置いた**~~
   → **修正ラウンド 2 で訂正**（F-V-P3-103 / F-W-P3-105）。ここに書いた理由
   「`core` に U+2028 を入れても `name` に載る経路が無い」は**誤り**だった。`Ident` の検証は
   C0 / C1 / DEL / 孤立サロゲートしか拒まないので U+2028 は通り、`model` 行の `name` は
   `.jin` の `core` そのものなので、**普通の `jin run --model fake --trace` で生の U+2028 が
   JSONL に載る**（2026-09-06 実測: `jin check` exit 0・11 行が `splitlines()` では 19 行）。
   同じ段落で「`name` は `.jin` の `core` そのもの」と書いておきながら逆の結論を出していた。
   R1 で `output` 経路を選んだのは「`FakeLlm` の台本で 3 種の区切り文字を 1 度に混ぜられる」
   ためであって、`core` 経路が無かったからではない。R2 で端到端テストを
   **`core` / `output` の 2 param** にした。
4. **A-1 の対象から U+000B / U+000C を外した。** `splitlines()` はこの 2 つでも割るが、
   `json.dumps` は 0x20 未満を必ず `` 形式へ逃がすので JSONL に生では現れない。
   生で置くと JSON 自身が不正になる（実測: `Invalid control character at`）。理由をテストの
   docstring に残した。
5. **B-5 の実効範囲は U+FFFE / U+FFFF だけである。** C0 / C1 / DEL / 孤立サロゲートは
   `jin_core.model._reject_bad_chars` が既に拒むので、`.jin` からは届かない。`xml_chars` は
   それらに対しては多層防御であり、**新しく閉じた穴は非文字 2 つ**。テストは単体（7 param）で
   全クラスを見つつ、端到端では U+FFFE / U+FFFF だけを回す。指示どおり `jin_core` の検証は
   変えていない（診断コードを増やさない）。
6. **F-S-P3-011 に上限は付けなかった。** ストリーム読みにしたことで常駐は「行 1 本 + 受理した
   dict」になり、全読み + `splitlines` の 2 重コピーは消えた。バイト数の上限は「正当な長い
   トレースを拒む」側の誤りを作るので、閾値の根拠が無いまま置かない（CLAUDE.md「具体値を
   推測で置かない」）。
7. **F-C-P3-013（`pointer_prefixes("/")`）は A-3 で関数ごと消えた**ので、記録のみ。
8. **F-V-P3-013（`implementation-plan.json` の `$comment` に Phase 3 の追記）は行わなかった。**
   指示書 E は同ファイルについて「`undecided[]` への登録以外は触らない」と書いており、
   他エージェントが `decision_record` を書き込み中である。衝突を避けて見送った。
9. **F-W-P3-010 / F-S-P3-013 は記録のみ**（指示どおり）。ただし当時の文言
   「負けても起きるのは『`--force` 無しで上書き』ではない」は**不正確**だった
   （修正ラウンド 2 で訂正・security 再レビューの不一致 3）。`exists()` の判定と
   `os.replace` の間に別プロセスが通常ファイルを作れば、`--force` 無しでもそれを
   置き換える。同一ユーザーのローカル競合であり権限境界は越えないが、
   「上書きそのものが起きない」わけではない。記録のみとする判断は変えない。

### R1.3 Red の実測（バッチごと）

| バッチ | 先に足したテストの failed |
|---|---|
| 2（トレース読み取り: A-1 / A-2 / B-3 / B-9） | `test_a_row_containing_a_unicode_line_break_is_read` が U+2028 / U+2029 / U+0085 の 3 param で `exit 2`。修正後に緑（VT / FF の 2 param は JSON 自身が不正だったので param から外した） |
| 3（描画: B-1 / C-1） | `test_parallel_draws_no_chord` が `assert 2 == 1`（外枠が増えた）。スナップショット 3 本 failed。差分を読んでから `--snapshot-update` |
| 5（契約: A-7 / A-8 / A-11 / B-5 / B-7 / A-10） | `test_guard_claims_point_at_real_guards[jin-render/.../svg.py]`（claim の綴りが実装とずれた）と `test_render_is_a_registered_subcommand`（help の折り返し）の 2 件 failed → どちらもテスト側の書き方を直した |
| 変異 | 修正前の実装に対して 59 本中 58 本が RED。残る `CLI-stdout-locale` は CliRunner の stdout が常に UTF-8 で緑だったため、別プロセスの `PYTHONIOENCODING=ascii` テストを足して RED を実測 |

スナップショット差分（3 本更新）の内訳: `<circle data-jin=".../tools/2" data-jin-ref>` と
`<circle data-jin=".../flow/steps/{0,1,2}">` の**外枠 4 本の追加**、および flow の弦 2 本と
放射線 1 本の**終端座標の変化**（`RING_BOUNDARY` 固定から実寸へ）。`data-jin-kind` の値・
要素の種類・描画順はどれも変わっていない（9 種のまま）。

### R1.4 CI 8 ゲートの再実測（2026-09-06）

| ゲート | 結果 |
|---|---|
| `UV_LOCKED=1 uv sync` | Resolved 79 / Checked 76（lock 更新なし） |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 77 files already formatted |
| `uv run pytest` | **1100 passed**, 68 warnings, 6 snapshots passed（「1 warning」と書いていたのは `-W ignore::DeprecationWarning` を付けた実行の値だった・F-W-P3-106。素の `uv run pytest` は 68） |
| `uv run lint-imports` | Contracts: 3 kept, 0 broken |
| `uv run jin schema \| diff - schemas/jin.schema.json` | 差分なし |
| `uv run jin check examples` | 2 ファイル / error 0 / warning 0 |
| `uv run jin fmt --check examples` | exit 0 |

変異: `uv run python delivery/20260904-1445-jin/phase3-mutations/mutate_p3.py` →
baseline green（296 passed）・**59/59 caught**・SKIP 0・`/tmp` 残骸 0。
`CLI-follow-symlink-upfront-only` だけが期待どおり GREEN（二層防御の片方を消しただけ）。

### R1.5 verification_status

`backend_unit = passed` / `container_smoke = not_applicable` / `browser_e2e = not_applicable` /
`pipeline_e2e = not_run` / `overall = verified`（`scope_labels = ["backend-unit-verified"]` の
範囲での判定）。human_only は `not_run` のまま。

### R1.6 再レビュー依頼（親が実施）

重点的に見てほしいもの:

1. **C-1 の意味**。「星形の見た目は変えずに矢じりだけ実行順にする」が要件書 §2.5 の読みとして
   正しいか（HANDOFF `DP-IMPL-JIN-P3-LOOP-STAR-ORDER-01` の質問 1）。examples に loop が無いので
   スナップショットには 1 px も出ていない = **今回の変更を目で確かめる材料が無い**
2. **B-1 の外枠**が新しい `data-jin-kind` を作っていないこと（`tool` / `flow-edge` の使い回し）。
   1 つの pointer に 2 要素（wrapper `<g>` と外枠 `<circle>`）が付くので、Phase 5 の hit-test が
   「どちらを掴むか」を決める必要がある
3. **C-2 の umask**。`0o644 & ~umask` が `jin build` と同じで正しいか。`os.umask` の往復を
   `jin render -o` の中で 1 回行うことの是非
4. R1.2 の 9 件（指示と違えた判断）が妥当か
5. `_outer_extent` の到達半径の列挙（`layout.py`）が `_rings` / `_tools` / `_guards` などの
   実際の描画と食い違っていないか。食い違うと外枠だけが中身と合わなくなる

## P3-R2. 修正ラウンド 2（Phase 3 再レビューの新規 30 件 + 部分残存 8 件）

指示書: `delivery/20260904-1445-jin/phase3-fix-round-2-instructions.md`。
生出力: `delivery/20260904-1445-jin/code-review-raw/{correctness,conventions,wiring,security}-p3-round1.md`。

### R2.0 まとめ

| | 前（R1 後） | 後 |
|---|---|---|
| テスト | 1100 passed | **1190 passed** |
| 変異（`mutate_p3.py`） | 59 本 / 59 caught | **70 本 / 70 caught**（SKIP 0・うち 2 本は期待 GREEN） |
| CI 8 ゲート | 全緑 | 全緑（R2.3） |
| スナップショット | 4 本 | 4 本（**差分 0**・B-1 の理由は下記） |

指示書の A（4）・B（5）は**全件**。C 節は 20 項目（finding ID にすると 20 件）を列挙しており、**15 項目を直し、5 項目**（F-C-P3-103 / F-S-P3-102 / F-S-P3-104 / F-W-P3-103、および「道具環の紋の重なり」）を理由付きで記録のみにした（R2.2）。

### R2.1 対応表

| # | finding | 変更 | 固定するテスト | 変異 |
|---|---|---|---|---|
| A-1 | F-V-P3-101（= 010 の残存） | `docs/spec/layout.md` §5 と `layout.py` の `RenderError` docstring の `model.md §3.3` を「CLAUDE.md / ADR-012」に。`model.md` §3.3 は State の定義であって採番の規律ではない | — | — |
| A-2 | F-V-P3-103 / F-W-P3-105 | 端到端テストを **`core` / `output` の 2 param** に。R1.2 項 3 の誤った理由を訂正 | `test_render_contract.py::test_a_trace_written_by_jin_run_is_readable_by_jin_render[core/output]`（`jin check` が通ることと U+2028 が生で載ることを先に assert） | `TRACE-splitlines`（対象を `test_render_contract.py` まで広げて再実測: **5 failed** = U+2028/2029/0085 の 3 param + 端到端 `core` / `output` の 2 param） |
| A-3 | F-W-P3-102（= 006 の部分残存） | `packages/jin-render/tests/conftest.py` の docstring が実物の網（`test_package_tests_only_import_the_jin_packages_that_package_depends_on`）を名指しするよう修正 | — | — |
| A-4 | F-C-P3-104 | 変異 `STAR-slot-identity` の効き方を実測どおりに 3 箇所（notes R1.1 C-1 行 / `mutate_p3.py` のコメント / `undecided_details` の note）で訂正。**ADR-022（起票時は ADR-021）と `decision_record` は触っていない**（親が置換記録） | — | 新規 2 本（下記） |
| B-1 | F-C-P3-101 | flow の節の外枠を兄弟間隔から決める。半径を返す関数を `_reference_size` 1 本にし、`_flow_nodes`（紋）と `_flow_extent`（弦の隙間）の両方がそこから採る。超過分は**外枠・中身・隙間を同じ係数で**縮める | `test_every_flow_chord_is_drawn_whatever_the_node_count`（n=3..12 × 中身 3 種 × sequence/loop = 60 param）、`test_a_shrunk_flow_node_shrinks_its_contents_too`、`test_the_chord_gap_matches_the_drawn_node`、`test_a_small_flow_keeps_the_full_nested_scale`、`test_a_crowded_flow_falls_back_to_points` | `FLOW-node-scale-fixed`、`FLOW-no-node-limit`、`FLOW-extent-no-limit` |
| B-2 | F-V-P3-102 | `test_the_scan_finds_the_modules_that_carry_claims` に「走査結果の**パッケージ名集合** == 期待集合」を追加。CLAUDE.md の文を「1〜7 は名指し / 8 は自己検出」に分割 | 同テスト + `test_claude_md_has_the_package_addition_checklist` | CLAUDE.md の 8 項目目を消して実測。**期待語を `test_guard_claims.py` にした最初の版は緑のまま**だった（直後の解説文にも同じ語があるため）ので、8 項目目にしか無い語に替えて **1 failed** を実測 |
| B-3 | F-V-P3-105（= 007 の部分残存） | layout.md §7.2 に弦と節の 2 行、§3 の `flow-edge` 行の対象列に「節」（`machine-readable` の第 1 セルは不変）。指示は「`POINTER_KINDS` に同じ 2 行」だったが `FLOW_POINTER_KINDS` を別に立てた（理由は R2.2 項 13・F-V-P3-210） | `test_a_flow_pointer_lands_on_the_kind_the_table_says`（2 param） | `KIND-chord-as-circle`、`KIND-flow-node-as-tool` |
| B-4 | F-V-P3-106 | `undecided_details[DP-IMPL-JIN-P3-ROUNDING-01].phase_impact` を「最大座標 1000 px / 約 1.1e-13 px」に | — | — |
| B-5 | F-W-P3-104（= 008 の半分） | `jin build` の成功文言も `_safe` を通す | `test_build_run.py::test_the_build_success_message_does_not_carry_control_characters` | `CLI-build-success-unsafe` |

**B-1 のスナップショット差分は 0。** examples の flow は pipeline の n=3 だけで、上限は
`0.55 * sin(60°) − 0.06 ≈ 0.416`、節の natural は 0.264 なので制限に掛からない。
`--snapshot-update` を使わずに 4 本（+ trace overlay 2 本）が通ることを確認した。
縮み始める n は実測で core のみ 13 / examples 同型 5 / 最大 5（layout.md §6 の表）。

**A-4 の新しい変異 2 本**（`STAR-pre-fix-visit-order` / `STAR-pre-fix-star-shape-stays`）は
同じ「修正前挙動」（配置は恒等 + 辺 `j → (j+k) mod n`）を当て、前者は
`test_loop_nodes_are_placed_so_the_arrows_follow_the_visit_order` だけを見て **7 param 赤**、
後者は `test_loop_edges_follow_the_star_polygon` だけを見て **3 param 緑**（`EXPECT_GREEN`）。
これで「星形のテストと訪問順のテストが独立に効く」が機械の実測になった。
`_flow_slots` と `_flow_edges` の 2 箇所を同時に変えるので `main()` で特例扱いしている
（`CLI-follow-symlink-both` と同じ手）。

C（低）で直したもの:

| finding | 変更 |
|---|---|
| F-S-P3-101 | `_write_svg` の docstring を「文言のための 4 条件」と「実効防御 1 条件（入力 `.jin` の上書き拒否）」に分け、後者に `guard: _write_svg -> path.resolve()==source.resolve()` を追加 |
| F-V-P3-113 | `_new_file_mode` に `guard: _new_file_mode -> os.umask(mask)`（復元の主張） |
| F-W-P3-101 | `child_env` / `env_with_stubs` の前置を固定する 2 テスト（既存 `PYTHONPATH` が残ること） |
| F-C-P3-102 | `_outer_extent` の docstring と layout.md §6 を「**主要素の外接半径**（四角の角 0.0029 / 0.0016 は隙間 0.04 に吸収）」に |
| F-V-P3-104 | 二層目（`SymlinkWriteRefused`）だけ `render` 側で前置しない。競合時にパスが 2 回出るのをやめた |
| F-V-P3-107 | `enumerate` + `_ = position` の残り 1 箇所 |
| F-V-P3-108 | `test_a_rune_with_a_noncharacter_still_parses_as_xml`（`render` を通す統合テスト）を `test_svg.py` から `test_layout.py` へ移動 |
| F-V-P3-109 | トリップワイヤ docstring の「7 項目」に 8 項目目を追記 |
| F-V-P3-110 | `test_a_huge_pointer_is_matched_in_linear_time` に改名（memory を測っていないので名前から外した） |
| F-V-P3-111 | `POINTER_KINDS` のコメントを「§7.2 と §3 から人が起こした対応」に |
| F-V-P3-112 | notes P3-3 の「0.55 + 0.28 * 0.95 = 0.816」を現行の式に（§6 参照） |
| F-C-P3-105 | `test_determinism.py` のサブプロセス script に残っていた `splitlines()` を `split("\n")` に |
| F-S-P3-103 | `_write_stdout_bytes` の `sys.stdout is None` と `OSError`（`> /dev/full` など）を 1 行 + exit 1 に。stderr 側の EPIPE は握り潰す。**インタプリタ終了時の flush も同じ OSError で落ちて exit 1 が 120 に化ける**（実測）ので、書けない stdout を `os.devnull` に差し替えてから抜ける。テスト `test_a_full_stdout_is_one_line_not_a_traceback`（`/dev/full` へ実書き込み）・変異 `CLI-stdout-oserror-traceback` で赤 |
| F-S-P3-105 | `_new_file_mode` が umask を復元することを固定するテスト（`guard:` 主張に歯を付ける）。変異 `CLI-umask-not-restored` で赤 |
| F-S-P3-106 | `--upto` の負数を `brief()` に通す（80 文字で切る）。変異 `CLI-upto-raw-value` で赤 |
| F-W-P3-106 | R1.4 の「1 warning」を素の `uv run pytest` の実測値 **68 warnings** に |
| F-V-P3-018 との整合 | `jin_cli` が `jin_render.overlay.brief` をサブモジュールから取っていたので `jin_render.__all__` に足し、`from jin_render import brief` に統一（「契約は `__init__.__all__` の名前だけ」と自分で書いた規律に合わせる） |

### R2.2 指示と違えた判断 / 直さなかったもの

1. ~~**A-1 の `model.md §3.3` は Phase 3 の 2 箇所だけ直した。**~~ 残りは 3 箇所ではなく
   **4 箇所**だった（`docs/spec/adk-mapping.md:168` が抜けていた・F-C-P3-204 / F-V-P3-202）。
   **修正ラウンド 3 で親判定により全部直した**（R3.1 の A-3 行。引用先だけの変更で
   `machine-readable` ブロック外・`tests/spec` の対象外）。grep で残り 0 を確認済み。
2. **`FLOW-no-node-limit` が最初 GREEN だった**（節の紋だけ制限を外しても弦の本数は
   変わらない）。これは「半径を決める場所が 2 つある」ことを検出するテストが無い、
   という別の穴だったので、`test_the_chord_gap_matches_the_drawn_node`（弦の隙間と
   描かれた外枠が同じ半径であること）を足し、`FLOW-extent-no-limit` も追加した。
   変異が緑だったことを「変異が悪い」で片付けず、テストを足す側に倒した。
3. **B-1 は道具環の紋（`summon`）には適用しない。** 紋は放射線で結ばれるだけで弦を
   持たないので、消える弦が無い。ただし `tools` 12 個（JIN020 の上限）では隣接距離
   0.285 に対し最大の紋 0.32 が重なりうる。**これは今回の finding に無い別件**なので
   直していない（記録のみ）。
4. **境界は 2 つある**（修正ラウンド 3 で実測に訂正・F-C-P3-205）。n >= 20 で節を点
   （半径 0.03）に落としたあと、
   (a) **n >= 32** で弦の本体が矢じり（0.05）より短くなる（`2*0.55*sin(pi/n) - 0.06 < 0.05`）。
   矢じりが本体からはみ出すが**弦は描かれる**。
   (b) **n >= 58** で弦そのものが消える（`2*0.55*sin(pi/n) <= 0.06` で `_arrow_d` が `None`）。
   R2 に「n >= 32 で弦がまた消える」と書いたのは (a) と (b) を混同したもので、
   消えるのは 58 からである。`flow.steps` にモデル側の個数上限は無いので、どちらも
   環半径を変えない限り解けない幾何の限界である。layout.md §6 に両方書いた。
   **診断コードは増やさない**（CLAUDE.md）。
5. **F-C-P3-103（Unicode 空白だけの行を空行扱い）は記録のみ。** ただし当時書いた理由
   「ASCII に狭めると BOM 付き空行が壊れた行になる」は**誤り**だった（修正ラウンド 3 で
   訂正・F-C-P3-203）。`str.strip()` は U+FEFF を落とさないので、**BOM だけの行は現状で
   既に exit 2** である（実測: `bom.jsonl:2: JSON として読めません（Unexpected UTF-8 BOM）`）。
   落ちるのは U+3000 / U+00A0 など `str.isspace()` が真になる空白だけである。
   判断〔記録のみ〕は変えない。理由を書き直す: (a) `jin_adk.trace` は空白だけの行を
   書かないので実害が無い、(b) 「空行」の定義を狭めると**今受理しているファイルが
   exit 2 になる**方向で、手で書いたのではないファイルに対しては拒否側の誤りのほうが
   costly、(c) どちらが正しいかを決める記述が要件書にも仕様にも無い（CLAUDE.md
   「具体値を推測で置かない」）。現状の挙動は下のテストで固定した。
6. **F-S-P3-102（1 行長の上限）は記録のみ。** R1.2 項 6 と同じ理由。ストリーム読みで
   常駐は 1 行ぶんになったが、1 行そのものの上限は閾値の根拠が無いまま置かない。
7. **F-S-P3-104（FIFO + `--force`）は記録のみ。** `-o` に名前付きパイプを渡すと
   `mkstemp` + `os.replace` は FIFO を通常ファイルで置き換える（読み手がいれば
   ブロックはしない）。シンボリックリンクと違い境界を越えず、`--force` を明示した
   利用者の指定どおりの動作である。
8. **F-W-P3-103（tests の動的 import は網を素通り）は記録のみ。** `test_packaging_contract.py`
   の動的 import 検査は `src/` だけを見る。テスト側の `__import__` は F-V-P3-009 / 108 で
   実際に消したが、機械化はしていない。テストコードは配布物ではなく、
   「任意コード実行の実装は 2 モジュールに閉じる」契約の対象外である。
9. **`F-V-P3-104`（二層目でパスが 2 回出る）にテストを足していない。** 二層目
   （`_write_atomically` の `os.replace` 直前の `is_symlink`）が発火するのは、事前判定を
   通過したあとに別プロセスがリンクを作った競合時だけである。この窓を安定に再現する
   テストは書けないので、変更（`render` 側で `SymlinkWriteRefused` だけ前置しない）は
   読解で確認した。既存の `test_a_symlinked_output_is_refused` は事前判定側を通る。
10. **`--upto` に届く桁数は 4300 未満である。** Python の `int()` が 4300 桁で
   `ValueError` を投げ、typer が先に「Invalid value」で exit 2 にする。`brief()` の
   効果を見るテストは 1000 桁で書いた（5000 桁では `brief` まで到達しない）。
11. **「道具環の紋の重なり」は C の記録のみ 5 件に数えている**（上の 3 と同じもの）。
12. **`STAR-pre-fix-star-shape-stays` を `EXPECT_GREEN` に入れた。** 変異ハーネスの
   「GREEN は原則として捕まえ損ね」という規律の例外を 2 本目として作ることになるが、
   ここでの GREEN は**主張そのもの**（星形テストは配置の恒等化では落ちない）なので、
   `CLI-follow-symlink-upfront-only` と同じ扱いにした。理由をエントリのコメントに書いてある。
13. **B-3 の「`POINTER_KINDS` に同じ 2 行」を別リスト `FLOW_POINTER_KINDS` にした**
   （Phase 3 修正ラウンド 4 で追記・F-V-P3-210）。`flow` の節を持つのは**核なし** circle で、
   既存の `POINTER_KINDS` は核ありのモデルで確かめている。同じ parametrize に混ぜると
   期待値の隣にモデルの分岐が要り、表と実装の対応が読めなくなる。リストとテストを
   分けて、どちらも `layout.md` §7.2 の 1 行ずつに対応させた。

### R2.3 CI 8 ゲートの再実測（2026-09-06）

| ゲート | 結果 |
|---|---|
| `UV_LOCKED=1 uv sync` | Checked 76 packages（lock 更新なし） |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 77 files already formatted |
| `uv run pytest` | **1190 passed**, 68 warnings, 6 snapshots passed |
| `uv run lint-imports` | Contracts: 3 kept, 0 broken |
| `uv run jin schema \| diff - schemas/jin.schema.json` | 差分なし |
| `uv run jin check examples` | 2 ファイル / error 0 / warning 0 |
| `uv run jin fmt --check examples` | exit 0 |

変異: baseline green（383 passed）・**70/70 caught**・SKIP 0・`/tmp` 残骸 0。
期待 GREEN は 2 本（`CLI-follow-symlink-upfront-only` / `STAR-pre-fix-star-shape-stays`）。

`implementation-plan.json` は `undecided_details` の 2 件（`DP-IMPL-JIN-P3-ROUNDING-01` の
`phase_impact` と `DP-IMPL-JIN-P3-LOOP-STAR-ORDER-01` の `note`）だけを変更した。
**私はこのラウンドで `decision_record` を触っていない**（差分検査で確認）。
件数を「22 件」と書いていたが実物は **23 件**である（Phase 3 修正ラウンド 4 で訂正・F-C-P3-302）。数は親の `record.py` が増やすものなので、ここでは「触っていない」だけを主張する。

### R2.4 verification_status

`backend_unit = passed` / `container_smoke = not_applicable` / `browser_e2e = not_applicable` /
`pipeline_e2e = not_run` / `overall = verified`（`scope_labels = ["backend-unit-verified"]` の
範囲での判定）。human_only は `not_run` のまま。

### R2.5 再レビュー依頼（範囲限定）

R2 で触った範囲だけ見ていただきたい:

1. **B-1 の縮小規則**（`_reference_size` / `_flow_node_limit`）。式が layout.md §6 と一致するか。
   「外枠・中身・隙間を同じ係数で縮める」が本当に中身をはみ出させないか（n=3/6/7/12 で
   `test_a_shrunk_flow_node_shrinks_its_contents_too` が見ているが、境界環以外の要素は見ていない）
2. **R2.2 の 4（n >= 32 で弦が消える）を仕様として許容してよいか。** 許容しないなら
   環半径か `flow.steps` の個数上限の話になり、要件書に戻る
3. **R2.2 の 3（道具環の紋の重なり）** を別 finding として起票すべきか
4. A-4 の 2 本の変異が「独立性の証拠」として十分か（`EXPECT_GREEN` を 1 本増やしたこと含む）
5. R2.2 の 1（Phase 2 に残る `model.md §3.3` の誤引用 3 箇所）を今のうちに直すか

## P3-R3. 修正ラウンド 3（Phase 3 再々レビューの新規 26 件・最終）

指示書: `delivery/20260904-1445-jin/phase3-fix-round-3-instructions.md`。
生出力: `delivery/20260904-1445-jin/code-review-raw/*-p3-round2.md`。

### R3.0 まとめ

| | 前（R2 後） | 後 |
|---|---|---|
| テスト | 1190 passed | **1201 passed** |
| 変異（`mutate_p3.py`） | 70 本 / 70 caught | **75 本 / 75 caught**（SKIP 0・うち 2 本は期待 GREEN） |
| CI 8 ゲート | 全緑 | 全緑（R3.3） |
| スナップショット | 4 本 | 4 本（差分 0・描画の変更なし） |

指示書の A（3）・B（4）は**全件**。C 節が名指しする finding は 10 件で、**8 件を直し**
（F-C-P3-102 / F-V-P3-108 / 109 / 203 / 204 / 207 / F-W-P3-204 / 205）、**2 件は記録のみ**
（F-S-P3-203 / F-W-P3-203。指示が「記録のみで可」としたもの）。F-V-P3-111 は R2 で対応済み。
**（R4 追記・F-V-P3-303 / 親）**: 上の数えは C 節の「F-V-P3-203〜210 の残り」を 4 件（205 / 208 / 209 / 210）取りこぼしていた。
実際は R3 で 14 件のうち 8 件を直し、4 件は未対応・未記録のまま R4 へ持ち越した（R4 で 205 / 208 / 210 を修正・209 は記録のみ）。
**指示に無い変更は増やしていない**（付随の 2 件は R3.2 の 1 に理由を書いた）。

### R3.1 対応表

| # | finding | 変更 | 固定するテスト | 変異 |
|---|---|---|---|---|
| A-1 | F-C-P3-202 / F-V-P3-201 / F-S-P3-201 | 一層目の `SymlinkWriteRefused` の文言に**パスを戻す**（二層目と同じ `path: 理由` の形）。`render` 側の「前置しない」はそのままなので、どちらの層でもパスは 1 回だけ出る | `test_a_symlinked_output_is_refused` に `str(link) in result.output` と `count(...) == 1` を追加 | `CLI-symlink-message-without-path` |
| A-2 | F-C-P3-203 | R2.2 項 5 の理由を事実に書き直した（**BOM だけの行は現状で既に exit 2**。`str.strip()` は U+FEFF を落とさない）。判断〔記録のみ〕は変えない | `test_a_bom_only_line_is_refused`、`test_a_unicode_whitespace_only_line_is_skipped`（U+3000 / U+00A0） | — |
| A-3 | F-C-P3-204 / F-V-P3-202 | `model.md §3.3` の誤引用を Phase 2 側の **4 箇所**（`jin_adk/codegen.py` の 2 行、`adk-mapping.md:124` と `:168`）で「CLAUDE.md / ADR-012」に。R2.2 項 1 の「3 箇所」も 4 に訂正 | 既存の `tests/spec`（`machine-readable` 外なので影響なし） | — |
| B-1 | F-C-P3-201 | **fix-later**。`DP-REVIEW-JIN-P3-001` を `undecided[]` / `undecided_details[]` に起票。`layout.md` §6 に「道具環の紋は縮尺を詰めない（既知の重なり）」と、表の「12 個並べても重ならない」が `tool` / `builtin` 限定であることを明記。**コードは変えていない** | — | — |
| B-2 | F-C-P3-205 | `layout.md` §6 の「n >= 32 で弦が消える」を実測の 2 境界に分けた（**32 <= n <= 57 は描かれるが本体 < 矢じり / n >= 58 で消える**）。R2.2 項 4 も訂正 | `test_the_two_crowding_boundaries`（n=31/32/57/58）、`test_a_crowded_flow_falls_back_to_points` を n=19/20/40 の 3 param に（点へ落ちる境界は **n=20**） | `FLOW-point-fallback-off` |
| B-3 | F-W-P3-201 | 成功文言の出力を `_echo_or_exit` に通し、書けなければ 1 行 stderr + exit 1。`-o` 無し経路の後始末も `_fail_on_stdout` に共通化（`build` の成功文言も同じヘルパ） | `test_a_full_stdout_on_the_success_message_is_one_line_not_a_traceback`（`/dev/full`。SVG 自体は書けていることも見る） | `CLI-success-message-raw-echo` |
| B-4 | F-W-P3-202 / F-S-P3-202 | `sys.stdout is None` 分岐にテストを追加（`preexec_fn` で fd 1 を閉じる） | `test_a_closed_stdout_is_one_line_not_a_traceback` | `CLI-no-closed-stdout-branch` |

C（低）で直したもの:

| finding | 変更 |
|---|---|
| F-C-P3-102 の残り | `layout.py` の `_reference` 内コメント 1 行を「主要素の外接半径 + 隙間」に |
| F-V-P3-108 の残り | 関数内 import 2 箇所（`test_overlay.py` の `time` / `test_determinism.py` の `hashlib`）を先頭へ |
| F-V-P3-109 の残り | `test_packaging_contract.py:305` の「チェックリスト 7 項目目」に「（全 8 項目）」 |
| F-W-P3-204 | `mutate_p3.py` の期待 GREEN の印字理由を `EXPECT_GREEN_REASON` で 2 種類に分けた（`two-layer` と「主張そのもの」）。名前の集合は `EXPECT_GREEN = set(EXPECT_GREEN_REASON)` に畳み、**片方にだけ足す事故**を作らない |
| F-W-P3-205 | notes R2.1 の `ADR-021` を「ADR-022（起票時は ADR-021）」に |
| F-V-P3-203 | トリップワイヤ docstring の「7 項目である」を 8 に。列挙の順序（6 / 8 / 7）も 1〜8 に並べ替え |
| F-V-P3-204 | `test_render.py` の関数内 `import subprocess` / `import sys`（3 関数 × 2）を先頭へ |
| F-V-P3-207 | 弦の本体長の下限を `2 * (ARROW_HEAD + ε)` に（layout.md §6 の文言どおり）。矢じりだけを下限にしていたので **ε を消す変異が緑のままだった**（レビューの M-B1b）。変異 `FLOW-limit-drops-epsilon` で **18 failed** を実測 |
| F-S-P3-101 の残り | `main.py` のモジュール docstring が「5 条件すべてが防御ではない」のままだったので、R2 の関数 docstring と同じ 4 + 1 の形に（R3.2 の 1） |

### R3.2 指示と違えた判断 / 記録のみ

1. **指示に無い変更は 2 つ**。どちらも指示された修正に付随して見つかったもので、
   独立に持ち込んだ変更は無い。
   - `main.py` のモジュール docstring。R2 の F-S-P3-101 で関数 docstring を
     「文言のための 4 条件 + 実効防御 1 条件」に分けたが、モジュール docstring は
     「5 条件は防御ではない」のまま残っていた。A-1 で同じ段落を触るので同時に直した。
     **安全主張が実装と食い違ったまま残る**のはこのラウンドで潰している defect と
     同じ型であり、放置する理由が無い。
   - `test_a_crowded_flow_falls_back_to_points` の n=19/20 化と
     `FLOW-point-fallback-off`。B-2 で §6 の閾値を実測に直したとき、点へ落ちる境界
     （n=20）を通るテストが 1 本も無いことに気づいた（詳細は項 3）。B-2 が指示した
     のは n=31/32/57/58 の側だけなので、この 2 本は指示の範囲外である。
2. **`CLI-symlink-message-without-path` は最初 GREEN だった。** `before` の文字列が
   一層目と二層目のどちらにも一致し、`replace(..., 1)` が**二層目**を書き換えていた
   （ruff が一層目の raise を 1 行に畳んだ結果、両者の形が同じになった）。直前の
   コメント行まで含めて一意にし、RED を実測した。変異の的が外れていたのであって
   テストが弱かったのではない。
3. **`FLOW-point-fallback-off` も最初 GREEN だった。** 点へ落ちる境界（n=20）を通る
   テストが無く、`test_a_crowded_flow_falls_back_to_points` は n=40（どちらの実装でも
   点）だけを見ていた。n=19/20 を足して RED を実測した。R2 の `FLOW-no-node-limit` と
   同じで、**変異が緑だったらテストを足す側に倒す**。
4. **B-3 の共通化で 4 本の変異が SKIP になった**（`CLI-follow-symlink-*` 2 本 /
   `CLI-stdout-oserror-traceback` / `CLI-build-success-unsafe`）。すべて `before` を
   現行コードに合わせ直し、SKIP 0 に戻してから caught 数を数えた。
5. **F-S-P3-203〜205 / F-W-P3-203 は記録のみ**（指示どおり）。
6. **`DP-REVIEW-JIN-P3-001` はコードを変えていない。** 紋の重なりを直す (a)(b) は
   どちらも図の見た目を変え、examples のスナップショットは動かないが Phase 5 の
   hit-test の設計に影響する。rune 帯との交差は環半径の話で要件書 §2.5 に戻るため、
   実装者の判断で選べない。判断期限は Phase 5 のエディタ着手前。

### R3.3 CI 8 ゲートの再実測（2026-09-06）

| ゲート | 結果 |
|---|---|
| `UV_LOCKED=1 uv sync` | Checked 76 packages（lock 更新なし） |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 77 files already formatted |
| `uv run pytest` | **1201 passed**, 68 warnings, 6 snapshots passed |
| `uv run lint-imports` | Contracts: 3 kept, 0 broken |
| `uv run jin schema \| diff - schemas/jin.schema.json` | 差分なし |
| `uv run jin check examples` | 2 ファイル / error 0 / warning 0 |
| `uv run jin fmt --check examples` | exit 0 |

変異: baseline green（394 passed）・**75/75 caught**・SKIP 0・`/tmp` 残骸 0。

`implementation-plan.json` の変更は `undecided[]` と `undecided_details[]` への
`DP-REVIEW-JIN-P3-001` の追加**だけ**（既存の `undecided_details` も含めて他は不変）。
`decision_record`（**23 件**。「22 件」は誤り・F-C-P3-302）は**私が触っていない**という主張であって、
件数が動かないという主張ではない。増減させるのは親の `record.py` である。ADR ファイルは触っていない。

### R3.4 verification_status

`backend_unit = passed` / `container_smoke = not_applicable` / `browser_e2e = not_applicable` /
`pipeline_e2e = not_run` / `overall = verified`（`scope_labels = ["backend-unit-verified"]` の
範囲での判定）。human_only は `not_run` のまま。

## P3-R4. 修正ラウンド 4（最終確認レビューの新規 3 件 + 部分残存・**文言とテスト 1 本**）

指示書: `delivery/20260904-1445-jin/phase3-fix-round-4-instructions.md`。
生出力: `delivery/20260904-1445-jin/code-review-raw/*-p3-round3.md`。

**コードの挙動は変えていない。** 変えたのは (1) `build` 側に無かったテストと変異、
(2) symlink 拒否文言の**語順**、(3) 仕様書・記録の文言と数字である。

### R4.0 まとめ

| | 前（R3 後） | 後 |
|---|---|---|
| テスト | 1201 passed | **1202 passed** |
| 変異（`mutate_p3.py`） | 75 本 / 75 caught | **77 本 / 77 caught**（SKIP 0・うち 2 本は期待 GREEN） |
| CI 8 ゲート | 全緑 | 全緑（R4.3） |
| スナップショット | 4 本 | 4 本（差分 0） |

### R4.1 対応表（指示書の 6 行）

| # | finding | 変更 | 固定するテスト | 変異 |
|---|---|---|---|---|
| 1 | F-C-P3-303 / F-W-P3-301 | なし（`build` は R3 で既に `_echo_or_exit` を通っていた）。**テストと変異が無かった**だけ | `test_build_run.py::test_a_full_stdout_on_the_build_success_message_is_one_line_not_a_traceback`（`/dev/full`。exit 1・**stderr がちょうど 1 行**・生成物は出来ている） | `CLI-build-success-raw-echo` |
| 2 | F-C-P3-301 / F-V-P3-302 | `layout.md` §6 の相互参照 2 箇所の向きを入れ替えた（表セル「上記」→「下記」、段落「下の表」→「上の表」） | — （`tests/spec` は `machine-readable` しか読まない） | — |
| 3 | F-C-P3-302 / F-W-P3-302 | notes R2.3 / R3.3 の「`decision_record` 22 件」を実数 **23 件** に訂正し、主張を「**私は触っていない**」に書き直した（件数を動かすのは親の `record.py`） | — | — |
| 4 | F-V-P3-301 | symlink 拒否文言を **`path: 理由`** にそろえた。**3 箇所**（`_write_svg` の一層目 / `_write_atomically` の二層目 / `_write_in_place` の ELOOP 退避路）。他の `WriteRefused` 4 条件・`fmt` の表示と同じ形 | `test_a_symlinked_output_is_refused` に `result.output.startswith(f"{link}: シンボリックリンク")` を追加（**並び**を見る。R3 は有無と回数しか見ていなかった） | `CLI-symlink-message-order` |
| 5 | F-V-P3-303 | 未対応と指摘された 4 件のうち **3 件を修正・1 件は記録のみ**（下表）。R3.0 の数え（「C は 8 項目」）は 205 / 208 / 209 / 210 を数に入れていなかった | 下表 | — |
| 6 | F-V-P3-203 / 204 の残り | `test_packaging_contract.py` の「計 7 項目」→「計 8 項目」。関数内 import 2 箇所（`test_render.py` の `_new_file_mode` / `test_render_contract.py` の `ElementTree`）を先頭へ | 既存 | — |

項 5 の内訳:

| finding | 対応 |
|---|---|
| F-V-P3-205 | `test_overlay.py` の節見出しコメント「§7.2 の表を**書き写す**」→「§7.2 と §3 から起こした対応」（3 行下の説明と食い違っていた） |
| F-V-P3-208 | `decision-conformance.md` §2.24.3 を「入れ子の縮尺 **上限** 0.28（flow の節は §2.24.1c で兄弟間隔まで縮む・n >= 20 なら点）」に。`layout.md` §7.2 の `/circles/i/flow/steps/j` 行に「節が多い（n >= 20）ときは解決しても点」を追加 |
| F-V-P3-209 | **記録のみ。** `implementation-plan.json` の `evidence[]` は親の台帳である（R2 / R3 の指示は「`undecided` 以外を触らない」）。finding 本文も「所管は親」と書いている。**私が足すと、実装者が親の台帳に書く前例になる**ので足さない。親が最終ラウンド後に `[jin_phase=3][fix-round-4][mutation] 77/77` と `[gates] 1202 passed` を足す想定 |
| F-V-P3-210 | notes R2.1 B-3 行に理由を書き足し、R2.2 に項 13 として「同じリストに入れると核あり / 核なしでモデルを分岐させる必要があるため別リストにした」を追記 |

### R4.2 指示と違えた判断 / 記録のみ

1. **項 4 は 3 箇所を直した**（指示は箇所数を書いていない）。一層目だけを直すと
   二層目・退避路の文言と並びが割れ、`fmt` にも `理由: path` が残る。
   レビューの提案 (a)「一層目・二層目・`fmt` を `path: 理由` に」に合わせた。
2. **`fmt` は同じ文言を `{path}: 書き込めません（… {exc}）` で包むので、パスが 2 回出る。**
   これは並びの変更で生じたものではなく **R3 以前から**そうである（`fmt` は
   `SymlinkWriteRefused` を基底の `WriteRefused` として扱うため）。`render` 側の
   F-V-P3-104 と同型だが、`fmt` の表示を変えるのは項 4 の範囲外なので**直していない**。
   次のラウンドがあるなら `fmt` の `unwritable` 分岐で `SymlinkWriteRefused` を
   別に捕まえるのが筋である。
3. **項 1 でコードは変えていない。** `build` の `_echo_or_exit` は R3 の B-3 で入っており、
   欠けていたのはテストと変異だけだった。`CLI-build-success-raw-echo` を足して
   **1 failed** を実測した（`-k` が新しい 1 本だけを選ぶため）。
4. **F-V-P3-209 は記録のみ**（上表の理由）。

### R4.3 CI 8 ゲートの再実測（2026-09-06）

| ゲート | 結果 |
|---|---|
| `UV_LOCKED=1 uv sync` | Checked 76 packages（lock 更新なし） |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 77 files already formatted |
| `uv run pytest` | **1202 passed**, 68 warnings, 6 snapshots passed |
| `uv run lint-imports` | Contracts: 3 kept, 0 broken |
| `uv run jin schema \| diff - schemas/jin.schema.json` | 差分なし |
| `uv run jin check examples` | 2 ファイル / error 0 / warning 0 |
| `uv run jin fmt --check examples` | exit 0 |

変異: baseline green・**77/77 caught**・SKIP 0・`/tmp` 残骸 0。
新規 2 本はどちらも **1 failed** を実測（`CLI-symlink-message-order` /
`CLI-build-success-raw-echo`）。期待 GREEN は R3 と同じ 2 本のまま。

`implementation-plan.json` は**このラウンドでは 1 バイトも触っていない**（項 5 の
F-V-P3-209 を含む）。ADR ファイルも触っていない。R3 開始時に取った控えと突き合わせると
`decision_record`（23 件）は同一で、差があるのは `skill_plan` の 1 要素追加
（`parallel-code-review` の実施記録）である。**これは親の書き戻し**であり、
R3.3 の「plan の変更は `DP-REVIEW-JIN-P3-001` の追加だけ」は**私の編集について**の主張である。

### R4.4 verification_status

`backend_unit = passed` / `container_smoke = not_applicable` / `browser_e2e = not_applicable` /
`pipeline_e2e = not_run` / `overall = verified`（`scope_labels = ["backend-unit-verified"]` の
範囲での判定）。human_only は `not_run` のまま。
