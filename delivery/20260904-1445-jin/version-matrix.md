# version-matrix — jin-lang（Phase 0 / Phase 1 ラウンド）

実装 Stage 1 `tech-version-check`（B-11）の出力。対象は **Phase 0（仕様書・examples）と Phase 1（jin-core / jin-cli）**。
Phase 2 以降（jin-adk / jin-render / jin-lsp / apps/editor）で使う版も、後続ラウンドの手戻り防止のため一次証拠から転記して残す。

## 0. 一次証拠（primary evidence）の出典

本表の値は**このセッションでの推測ではなく実測**である。出典は 2 系統:

| 出典 | 取得方法 | 取得日 | 参照 |
|---|---|---|---|
| **E1: ADK 実測プローブ** | 親セッションが `uv venv` 隔離環境へ実インストールし `inspect` / Pydantic `model_fields` を走査。PyPI JSON API で最新安定版を取得 | 2026-09-04 | `delivery/20260904-1445-jin/adk-api-probe.md` |
| **E2: LSP / lark 実測プローブ** | 親セッションが `uv venv` 隔離環境へ `pygls==2.1.1` / `pytest-lsp==1.0.1` / `lark==1.3.1` を実インストールし `inspect` と実パースで確認 | 2026-09-04 | `delivery/20260904-1445-jin/lsp-api-probe.md` |
| **E3: 本ラウンドの PyPI JSON API 取得** | `curl https://pypi.org/pypi/<pkg>/json` を本セッションで実行 | 2026-09-04T06:52:39Z | 本ファイル §3 の該当行 |

E1 / E2 は隔離環境への**実インストール後の introspection 結果**であり、公式サイトへの WebFetch より強い証拠である。
そのため本スキルの既定手順（context7 → WebFetch → WebSearch）に優先して E1 / E2 を採用した。
E1 / E2 に載っていない 5 パッケージ（import-linter / ruff / pytest / pytest-cov / hatchling）のみ E3 で補った。

## 1. 言語ランタイム

| 対象 | 採用 | 公式最新 / 実測 | 要求ランタイム | 取得日時 | 出典 |
|---|---|---|---|---|---|
| Python | `>=3.12`（要件書 §1.1・pyproject に宣言） | **`uv sync` が選んだのは 3.14.6**（実測 `uv run python -c "import sys;print(sys.version)"` → `3.14.6 (main, Jun 10 2026)`）。E1 が記録したホストの 3.13.1 とは別 | — | 2026-09-04T07:20 | 本セッション実測 + E1 |
| uv | 0.7.8（ローカル実測 `uv --version`） | 0.7.8 | — | 2026-09-04T06:52 | 本セッション実行 |
| Node.js | v22.12.0 / pnpm 10.15.1 | — | apps/editor（Phase 5）でのみ使用。本ラウンド対象外 | 2026-09-04 | E1 |

`.nvmrc` は本ラウンドでは作成しない（Phase 5 の apps/editor 着手時に作る。Node を使う成果物が本ラウンドに無いため）。

> **⚠️ Python 版の食い違い（人間判断が要る点）**: NFR-ENV-001 は実行環境を 3.13.1 と記録しているが、
> 本ラウンドで `uv sync` が作った `.venv` は **3.14.6** だった（マシンに 3.14.6 があり `requires-python = ">=3.12"` を満たすため）。
> 全 225 テストは 3.14.6 で通っている。要件は「3.12+」なので違反ではない。
> ただし CI と開発者マシンで版が揺れると再現性が落ちる。`.python-version` を置いて固定するかどうかは
> **要件書に根拠が無いため AI が決めない**（T-002）。人間に確認してもらう論点として
> `implementation-notes.md` の確認要求ブロックに挙げた。
> なお Phase 2 で `google-adk 2.8.0`（`requires_python >=3.10`）を 3.14 系に入れられるかは未検証である。

## 2. メイン FW / コアライブラリ（Phase 1 で実際に使う）

| パッケージ | 採用宣言 | 公式最新（実測） | requires_python | 取得日時 | 出典 |
|---|---|---|---|---|---|
| pydantic | `>=2.13,<3` | 2.13.5 | >=3.9 | 2026-09-04 | E1 |
| lark | `>=1.3,<2` | 1.3.1 | >=3.8 | 2026-09-04 | E2 |
| typer | `>=0.27,<1` | 0.27.2 | >=3.10 | 2026-09-04 | E1 |

## 3. 開発ツール（E1 / E2 に無く本ラウンドで実測した分）

| パッケージ | 採用宣言 | 公式最新 | requires_python | 取得日時 | 根拠 URL |
|---|---|---|---|---|---|
| pytest | `>=9.1,<10` | 9.1.1 | >=3.10 | 2026-09-04T06:52:39Z | https://pypi.org/pypi/pytest/json |
| import-linter | `>=2.14,<3` | 2.14 | >=3.10 | 2026-09-04T06:52:39Z | https://pypi.org/pypi/import-linter/json |
| ruff | `>=0.16,<1` | 0.16.6 | >=3.7 | 2026-09-04T06:52:39Z | https://pypi.org/pypi/ruff/json |
| hatchling（build backend） | `>=1.32`（build-system requires） | 1.32.0 | >=3.10 | 2026-09-04T06:52:39Z | https://pypi.org/pypi/hatchling/json |
| pytest-cov | 本ラウンドでは**採用しない** | 7.1.0 | >=3.9 | 2026-09-04T06:52:39Z | https://pypi.org/pypi/pytest-cov/json |

`pytest-cov` を入れない理由: design.yaml / requirements.json のいずれにもカバレッジ目標値が無い。
値の無い閾値ゲートを AI が勝手に置かない（T-002）。必要なら人間が `test_coverage_target` を決めてから入れる。

## 4. Phase 2 以降で使う版（本ラウンドでは install しない・転記のみ）

| パッケージ | 版 | 用途 Phase | 出典 |
|---|---|---|---|
| google-adk | 2.8.0（`>=2.8,<3`） | 2 | E1 |
| pygls[ws] | 2.1.1（`>=2.1,<3`。**`[ws]` extra 必須**） | 4 | E2 |
| lsprotocol | pygls が `==2025.0.0` に厳密ピン。**別途ピンし直さない** | 4 | E2 |
| pytest-lsp | 1.0.1 | 4 | E2 |
| syrupy | 6.0.0 | 3 | E1 |
| jinja2 | 3.1.6 | 2 | E1 |

## 5. 既知の非互換性 / 警戒事項（能動調査）

| # | 対象 | 内容 | 出典 | 本ラウンドへの影響 |
|---|---|---|---|---|
| 1 | pygls 1.x → 2.x（メジャー更新） | `LanguageServer` の import パスが `pygls.server` → **`pygls.lsp.server`** に変わっている。1.x の書き方は 2.x で `ImportError`。コンストラクタは `name` / `version` が必須の位置引数 | E2 §1 | Phase 4。本ラウンドでは pygls を install しないため影響なし |
| 2 | pygls 2.1.1 の WebSocket | 素の `pygls` には `websockets` が入らない（実測 `ModuleNotFoundError`）。依存宣言は **`pygls[ws]`** にしないと `jin lsp --ws` が実行時に落ちる | E2 §1 | Phase 4 |
| 3 | pytest-lsp 1.0.1 | `ClientServerConfig` は `server_command`（stdio サブプロセス）しか受け取らず、**ws 往復テストは張れない**。ws 用ハーネスは自前で書く必要がある | E2 §2 | Phase 4。「pytest-lsp が ws も見る」前提で計画しない |
| 4 | lark 1.3.1 | **JSON 文法は同梱されていない**（`lark/grammars/` は lark / python / common / unicode のみ）。`.jin` 用 JSON 文法は自前で書く。`%import common.ESCAPED_STRING` / `SIGNED_NUMBER` / `WS` は使える | E2 §3 | **本ラウンドに直撃**。JSON 文法は `packages/jin-core/src/jin_core/parser.py` のインライン定数 `JIN_JSON_GRAMMAR` として自作した（`.lark` ファイルは作っていない。wheel への `force-include` 設定が不要になるため） |
| 5 | lark 1.3.1 の位置 | `propagate_positions=True` で `Tree.meta` に `line` / `column` / `end_line` / `end_column`。位置が無い枝では `meta.empty` が True になるので**参照前に確認する** | E2 §3 | 本ラウンドで対応済み（`jin_core.parser`） |
| 6 | lark と LSP の基点差 | **lark は 1 始まり / LSP は 0 始まり**。要件書 §5 の診断 JSON は基点を規定していない | E2 §3 | **本ラウンドで決定**（後述・`decision-conformance.md` DP-JIN-POINTER-RANGE-01 の追加確定値） |
| 7 | google-adk 2.8.0 | `LoopAgent` の反復上限フィールドは **`max_iterations`**（`max` ではない）。`Runner` は全キーワード引数で `session_service` 必須 | E1 | Phase 2 |
| 8 | import-linter 2.x | メジャー 2 系。外部パッケージ（`google.adk`）を対象にするには `include_external_packages = True` が要る。本ラウンドで実際に契約違反を注入して**落ちること**を確認済み（§7） | E3 + 本セッション実測 | 本ラウンド |
| 9 | pytest 9.x | メジャー更新（8→9）。本ラウンドで使う機能（`tmp_path` / `parametrize` / `raises`）に破壊的変更の影響は観測されなかった（全テスト実行で確認）。網羅的な破壊的変更調査は未実施 | E3 + 本セッション実測 | 本ラウンド |
| 10 | **GitHub Actions の action 版（`actions/checkout@v4` / `astral-sh/setup-uv@v5`）** | **未検証**。`.github/workflows/ci.yml` に書いた 2 つの `uses:` は**記憶で書いた値**であり、本ラウンドでは実測できていない（GitHub API が rate limit で応答: `API rate limit exceeded for 210.172.0.33`・2026-09-04T07:37Z）。最新のメジャータグが v4 / v5 のままかは未確認 | 未検証 | ワークフローは本ラウンドで実行していない（`pipeline_e2e = not_run`）。**PR で CI が初めて走るときにここが原因で落ちる可能性がある**。仮 ID `DP-JIN-GHA-VERSION-UNVERIFIED` として親へ確認要求（`implementation-notes.md` §6 Q-JIN-IMPL-08）|

## 6. 複数候補が残った技術判断（DP 起票）

**なし。** 本案件は要件書 §1.1 の技術選定表（11 領域）と §10 決定事項（11 件）を人間が確定済みで、
design.yaml `architecture.predetermined_constraints` がそれを設計制約として下ろしている。
Stage 1 で選び直す余地のある技術判断は発生しなかった。

ただし本ラウンドで**値そのものを決めた**判断が 3 件ある。これらは技術選定ではなく実装判断であり、
design.yaml `decision_record[].constraints[]` の「実装時に決定し根拠を残す」限定句に対応する。
値と根拠は `delivery/20260904-1445-jin/decision-conformance.md` に記録した:

| 判断 | 対応 DP | 決めた値 |
|---|---|---|
| 新規 JIN 診断コードの採番 | DP-JIN-SEMANTIC-GAPS-01 | JIN012（循環参照）/ JIN013（多重親） |
| 診断の行・列の基点 | DP-JIN-POINTER-RANGE-01（E2 §3 の指摘） | **1 始まり**（line / col とも） |
| 横断契約テストの fixture 共有方法 | DP-COMMON-09 | リポジトリ直下 `tests/conftest.py` + 単一 pytest rootdir |

## 7. 依存の実在確認（dependency-availability-check）

`uv sync` の実行結果を `delivery/20260904-1445-jin/implementation-notes.md` §依存解決 に記録した。
宣言した全依存がロックファイルに解決され、`uv run pytest` が起動することを確認済み。

---

## 8. Phase 2（jin-adk）ラウンドの実測 — 2026-09-05（impl-p2）

Stage 1 `tech-version-check` の Phase 2 分。一次証拠は §0 の E1（`adk-api-probe.md`）と、本ラウンドで
親が Python 3.14.7 の隔離 venv に google-adk 2.8.0 を実インストールして再実測した結果（`implement-ledger.md` 2026-09-05 行）。
PyPI JSON API にも本セッションから到達できたので E3 で突き合わせた。

### 8.1 言語ランタイム（本ラウンドの実測）

| 対象 | 実測 | 取得方法 |
|---|---|---|
| Python | **3.14.7**（`uv run python -c "import sys; print(sys.version)"`） | `.python-version` = `3.14` を uv が読む |
| uv | **0.12.10**（`uv --version`）。CI は `setup-uv` で 0.12.9 固定（変更なし） | 本セッション実行 |

### 8.2 Phase 2 で新たに install した依存

| パッケージ | 採用宣言 | PyPI 最新（E3・2026-09-05T09:55:31Z） | uv.lock が解決した版 | requires_python | 出典 |
|---|---|---|---|---|---|
| google-adk | `>=2.8,<3`（要件書 §1.1「2.x 系」） | 2.8.0 | **2.8.0** | >=3.10 | https://pypi.org/pypi/google-adk/json + E1 |
| jinja2 | `>=3.1,<4` | 3.1.6 | **3.1.6** | >=3.7 | https://pypi.org/pypi/jinja2/json + E1 |
| syrupy（dev） | `>=6.0,<7` | 6.0.0 | **6.0.0** | >=3.10 | https://pypi.org/pypi/syrupy/json + E1 |

E1（2026-09-04）と E3（2026-09-05）の値は一致した。`uv lock` → `UV_LOCKED=1 uv sync` は EXIT 0（75 パッケージ）。
生成コードのテンプレートが前提にする版は `jin_adk.TARGET_ADK_VERSION = "2.8.0"` に固定し、
`tests/contract/test_adk_version_contract.py` が「入っている版 == 固定値」を検査する（版を上げるときは probe を取り直す）。

### 8.3 既知の非互換性 / 警戒事項（Phase 2 で実測したもの）

| # | 対象 | 内容 | 出典 | 対処 |
|---|---|---|---|---|
| 11 | google-adk 2.8.0 `SequentialAgent` / `LoopAgent` | 構築時に **`DeprecationWarning: ... deprecated in favor of Workflow and will be removed in a future version. Workflow cannot yet be used as an LlmAgent sub-agent`** が出る。動作はする | 実行時警告（`adk-api-probe.md` Phase 2 節） | `docs/spec/adk-mapping.md` は人間確定の正典なので Workflow へ変えない。`implementation-notes.md` Phase 2 節の HANDOFF Q-JIN-P2-03 で人間へ提示 |
| 12 | google-adk 2.8.0 `instruction` テンプレート | `{{lit}}` をエスケープではなく変数 `lit` として解釈。未設定 key は `KeyError` で実行が落ちる | `google/adk/utils/instructions_utils.py:41,174` | コンパイル時エラー（`adk-mapping.md` §3.1）+ `jin run` の state seed（同 §6） |
| 13 | google-adk 2.8.0 `google.adk.tools` | `__getattr__` で遅延 import。`MCPToolset` は任意依存 `mcp` が無いと `ModuleNotFoundError` | `google/adk/tools/__init__.py:60-140` | `builtin` の解決は名指しの 1 属性だけ getattr し、ImportError は「使えない名前」として扱う |
| 14 | import-linter 2.14 の `layers` | 存在しないパッケージを `"jin_adk \| jin_render"` と `\|` 結合で書くと `Missing layer 'jin_render': module jin_render does not exist.` で EXIT 1 | 本セッション実測（`scratchpad/lintprobe`） | Phase 2 は `"jin_adk"` 単独。Phase 3 で `\|` 結合（`pyproject.toml` のコメント） |
| 15 | click 8.5.0 / typer 0.27.2 の `CliRunner` | ~~`result.output` は stdout のみ~~ → **訂正（修正ラウンド 1・F-V-P2-008 の実測）**: `result.output` は stdout + stderr の**混在**。stdout だけは `result.stdout`、stderr だけは `result.stderr` | conventions reviewer の実測（`"hint:" in result.output` = True / `result.stdout` = False / `result.stderr` = True） | Phase 2 の CLI テストは `result.output` で stdout と stderr の両方の文言を見ている（`hint:` / `--force` / `JIN060` は stderr 由来）。stdout だけを見たいときは `result.stdout` |
| 16 | `jin_cli.main` の同名クラス | `jin_cli.main` は fmt 用に `WriteRefused` を定義しており、`jin_adk.build.WriteRefused` を同名で import するとクラス定義が import を上書きして `except` が効かない（テストで検出） | 本セッション実測 | `BuildWriteRefused` の別名で import |
| 17 | ADK のログ | `Runner` 実行中に `Skipping missing token usage metadata for agent R and model fake` などが logging（stderr）へ出る | 実行結果 | DP-COMMON-14 どおりログは stderr、トレースは `--trace` の JSONL。混ざらない |

### 8.4 Phase 2 で値を確定した実装判断

技術選定の DP 起票は無し（要件書 §1.1 / §10 が人間確定済み）。実装判断として決めた値は
`decision-conformance.md` §2.13〜§2.21 に根拠つきで記録した。
