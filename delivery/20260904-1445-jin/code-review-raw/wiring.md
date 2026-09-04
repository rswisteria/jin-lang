# Stage 5 review: wiring — 実装ラウンド 1（Jin Phase 0+1）

> 生出力。reviewer は `rv1-wiring`。親（team-lead）が受領内容を転記した。
> 基準状態: 225 passed / lint-imports 2 kept / ruff 32 files / `jin check`・`fmt --check` とも rc=0。

## Summary
- finding 総数: 13 件（critical 1 / high 2 / medium 4 / low 6）
- confidence 90 以上: W-01(95) / W-03(90) / W-04(90) / W-06(90) / W-10(95) / W-11(90) / W-12 は 70
- 全て実測。可能なものは「壊して落ちるか」まで確認。作業ツリーは復旧済み（`uv.lock` はバックアップとバイト一致）
- **親が独立に再現して確認したもの: W-01 / W-03**

---

## W-01 [CRITICAL] confidence 95 — uv.lock が CI で何も保証していない
`.github/workflows/ci.yml:18` `uv sync --frozen`

`--frozen` は「ロックを更新しない」であって「ロックが最新か検証する」ではない。さらに後続の裸の `uv run`（ci.yml:23,27,28,34,39,43,47）は既定で再ロック＋同期する。

実測（pyproject.toml の dev グループに `mypy>=1.0` を追加し uv.lock は据え置き）:
- `uv sync --frozen` → `Audited 23 packages` / rc=0（警告なし、mypy 未インストール、uv.lock 無変更）
- 続けて `uv run lint-imports` → rc=0、**uv.lock が書き換わり mypy を含む 5 パッケージがインストールされた**（diff に resolution-markers 追加、ast-serialize 等が出現）

pyproject と uv.lock がずれていても CI は素通りし、**コミット済み uv.lock とは別の解決結果でテストが走る**。再現性ゼロ。

修正（`--frozen`→`--locked` の単純置換では不十分。後続の裸 `uv run` が再ロックするため）:
```yaml
jobs:
  test:
    env:
      UV_LOCKED: "1"     # 全 uv sync / uv run がロック一致をアサートする
```
あるいは先頭に `uv lock --check` を独立ステップで置いたうえで `UV_FROZEN: "1"` を job env に置く。

**親の独立再現（2026-09-04 16:55）**: 同手順で `uv sync --frozen` rc=0 / uv.lock 無変更 → `uv run lint-imports` 後に uv.lock が変化（resolution-markers と ast-serialize が出現）。確認済み。

## W-02 [HIGH] confidence 85 — import-linter の自己テストが「本番の契約」を検証していない
`tests/contract/test_dependency_direction.py:36-46`（INJECTED_CONFIG）, `:88-116`, `:66-72`

`test_import_linter_actually_bites_on_a_forbidden_import` は `pyproject.toml:42-60` の実契約ではなく、テスト内に**手書きで複製した** setup.cfg に対して「噛む」ことを確認している。もう一方の `test_import_linter_contracts_are_declared` は契約名の部分文字列（"一方向" / "google-adk"）と `include_external_packages is True` を見るだけ。

結果、`source_modules` を `["jin_kore"]` に typo する、`forbidden_modules` を `["gogle"]` にする、といった変更で**実契約が常に KEPT になっても両テストとも green のまま**。

実測（現時点では実契約は正しく噛む）:
- 実ツリーの canonical.py に `import google.adk` 注入 → `lint-imports` rc=1、`jin_core.canonical -> google (l.1)` を報告（google-adk 未インストールでも静的解析で検出）
- 実ツリーの canonical.py に `import jin_cli.main` 注入 → layers 契約 BROKEN、rc=1
- どちらも復旧後 rc=0

修正: 自己テストが tomllib で pyproject の `[tool.importlinter]` を読み、それを tmp の設定に変換して注入する（手書き複製をやめる）。

## W-03 [HIGH] confidence 90 — testpaths のハードコードで新パッケージのテストが黙って走らない
`pyproject.toml:32` `testpaths = ["tests", "packages/jin-core/tests", "packages/jin-cli/tests"]`

実測: `packages/jin-adk/`（pyproject.toml + src/jin_adk/__init__.py + tests/test_adk_placeholder.py に `assert False`）を作って `uv run pytest` → `1 failed, 224 passed`（= 合計 225。基準と同数）。落ちたのは `test_later_packages_do_not_exist_yet[jin_adk]` のみで、**新パッケージの失敗テストは 1 件も収集されていない**。同時に `lint-imports` は `Analyzed 29 files`（基準と同じ）のまま 2 kept — jin_adk は `root_packages`（pyproject.toml:45）に無いので解析対象外。

救い: `tests/contract/test_dependency_direction.py:124-131` の tripwire が jin_adk / jin_render / jin_lsp の 3 名について確実に赤くなる（実測で赤くなった）。ただし
- tripwire のメッセージ（:129-130）は「import-linter の layers 契約に足すこと」しか言っておらず、**`testpaths` への追加に言及していない**
- 3 つの名前のハードコード。`jin-plugin` など想定外の名前は完全に素通り

修正: `packages/*/pyproject.toml` をディスクから列挙し、`testpaths` と `root_packages` の両方がそれを網羅していることを assert する契約テストを 1 本追加。

**親の独立再現（2026-09-04 16:57）**: 同手順で新パッケージの `assert False` が 1 件も収集されず、`Analyzed 29 files` も不変。確認済み。

## W-04 [MEDIUM] confidence 90 — スキーマドリフト検出の 2 重の網が独立していない
`ci.yml:32-35` / `packages/jin-core/tests/test_schema_export.py:52-59`

`Detect JSON Schema drift` は `generate_schema.py` を走らせて**ファイルを上書きしてから** `git diff --exit-code` する。その後 `ci.yml:39` の pytest が `test_committed_schema_has_no_drift` を走らせるが、その時点でファイルは既に再生成済みなので**必ず通る**。

実測（schemas/jin.schema.json の title を "CORRUPTED" に改竄）:
1. `pytest packages/jin-core/tests/test_schema_export.py` → FAILED（テスト単体は正しく噛む）
2. CI の順序を再現: `generate_schema.py`（written）→ `git diff --exit-code -- schemas/jin.schema.json` → rc=0
3. その後もう一度 pytest → 7 passed（ドリフトは消えている）

現状は「穴」ではなく「脆さ」。ただし git diff 行が弱まった瞬間に 2 つの網が同時に無力化される。現ツリーでは schemas/jin.schema.json が未コミットなため、step 2 は「未追跡ゆえに diff なし」で通っている。`.gitignore` への誤混入・パス typo・リネームのいずれでも静かに green になる。

修正案: 書き換えない検査にする（`uv run jin schema | diff - schemas/jin.schema.json`）か、drift ステップを Test の後ろへ移す。

## W-05 [MEDIUM] confidence 80 — layers 契約が兄弟パッケージの追加を想定していない
`pyproject.toml:48-54`

design.yaml:143-144 のルール 3・4 は jin-adk と jin-render を**互いに独立な兄弟**として定義している。import-linter の `layers` は既定で厳密な直列順で、独立な兄弟は 1 行に `"jin_adk | jin_render"` と書く必要がある。今後のラウンドで単純に行を追加すると**兄弟間の一方向が静かに許可される**。

同じ箇所でもう 1 点: design.yaml:144 は「jin-render は google-adk に依存しない」も求めるが、forbidden 契約は `source_modules = ["jin_core"]` のみ。jin-render 追加時に広げないと機械で担保されない。

## W-06 [MEDIUM] confidence 90 — CI の Python バージョンが浮いている
`ci.yml:14-15`（setup-uv に python-version 指定なし）/ `.python-version` ファイルなし

`requires-python = ">=3.12"` だけなので、CI は ubuntu-latest ランナーが持つ任意の 3.12+ を拾う。design.yaml:56 は実行環境実測を 3.13.1 と記録しており、ローカルと CI がずれる。`target-version = "py312"` との組み合わせで挙動差が出る余地。

修正: `.python-version` を置く（uv が自動で尊重）か、setup-uv に `python-version:` を明示。

**親の追加実測（2026-09-04 17:03）**: ローカル `.venv` の実体は **Python 3.14.6**。design.yaml の記録（3.13.1）と既に乖離している。

## W-07 [MEDIUM] confidence 75 — design.yaml が CI 必須と定めた 2 本目の受け皿が CI 側に無い
`design.yaml:149-155` / `ci.yml` 全体

design.yaml の enforcement は「CI が jin-core → google-adk と apps/editor → Python パッケージの 2 本を必ず落とすこと」と明記。1 本目は機能しているが、2 本目について **CI に pnpm/Node のジョブが 1 つも存在しない**。

現ラウンドで apps/editor が未作成という判断は妥当で、`test_editor_contract_is_not_yet_enforced`（:134-144）が明示的に固定している（設計として誠実）。ただし ci.yml には Node/pnpm を足すための構造が一切なく、tripwire が赤くなっても**それは pytest の失敗であって「pnpm 側の検査が無い」ことを CI が語るわけではない**。Phase 5 で apps/editor を足す人が pytest の赤を「テストを差し替える」だけで消す動線になっている。

同様に、要件書 §9 が求める `claude plugin validate` の CI 実行（Phase 4）も受け皿がなく、W-03 の 3 名リストにも含まれていない。

## W-08 [LOW] confidence 85 — conftest の examples 収集が深さ固定
`tests/conftest.py:40` `sorted((REPO_ROOT / "examples").glob("*/*.jin"))`

`example_paths` / `formattable_paths` は canonical 契約テスト 10 本と pointer 契約テスト 5 本のほぼ全てを駆動するが、glob が `*/*.jin` 固定。一方 CLI 側の `_collect`（`packages/jin-cli/src/jin_cli/main.py:44`）は `rglob("*.jin")`。

`examples/foo.jin`（トップ直下）や `examples/a/b/c.jin`（2 階層下）を足すと、**`jin check examples` は検証するのに正準形・pointer の契約テストからは静かに外れる**。`test_formattable_set_is_not_empty` の `>= 14` はマジックナンバーで examples の件数を守っていない。

修正: conftest も `rglob("*.jin")` にそろえる。

## W-09 [LOW] — ruff の lint ルールセットが既定のまま
`pyproject.toml:35-40`（`[tool.ruff.lint]` の select が無い）

`ruff check` の既定は E4/E7/E9 + F のみ。CI の "Lint" ステップが捕まえるのは構文エラーと未使用 import 程度で、import 順序（I）・bugbear（B）・pyupgrade（UP）などは一切走らない。「lint が CI にある」ことと「lint が意味のある量を検査している」ことは別。

## W-10 [LOW] confidence 95 — workflow_run 系の定型項目は本 CI に非該当（確認済み）
`ci.yml:3-6`

- トリガは `push`（branches: [main]）と `pull_request` のみ。**`workflow_run` / `workflow_call` / `pull_request_target` はいずれも不使用**（grep 済み・0 ヒット）。したがって定型 4 項目は全て非該当
- ワークフローは ci.yml 1 本のみ。上流／下流関係が存在しない
- **握り潰しは無し**: `continue-on-error` / `|| true` / `set +e` / `if: always()` は 0 件（grep 済み）。複数行 `run` は GitHub Actions 既定の `bash -e`

実測（各検査が実際に噛むこと）:
- examples の `"root"` を `"rooot"` に改竄 → `jin check examples` rc=1（要件書 §5「error があれば exit 1」）
- examples に空行を注入 → `jin fmt --check examples` rc=1（同「--check は差分があれば exit 1」）
- 復旧後いずれも rc=0

## W-11 [LOW] confidence 90 — permissions / concurrency / timeout-minutes が未指定
`ci.yml:8-11`

`permissions:` が無くトークン権限はリポジトリ設定既定に依存（`pull_request` はフォークからは常に read-only なので実害は小さいが明示が定石）。`concurrency:` が無いので同一 PR への連続 push でジョブが重複。`timeout-minutes` も未指定（既定 360 分）。

推奨: `permissions: {contents: read}` と `concurrency: {group: ${{ github.workflow }}-${{ github.ref }}, cancel-in-progress: true}`。

## W-12 [LOW] confidence 70 — actions のバージョンがミュータブルタグ
`ci.yml:12,15` `actions/checkout@v4` / `astral-sh/setup-uv@v5`

メジャータグ参照。サプライチェーン厳格化を求めるなら SHA ピン。本案件のリスクは低い。setup-uv に `enable-cache: true` が無く毎回フル解決（速度のみ）。

## W-13 [LOW] confidence 80 — packages/*/tests に __init__.py が無い
`packages/jin-core/tests/` / `packages/jin-cli/tests/`

`tests/` 側には `__init__.py` があるが packages 側には無い。rootdir ベースの sys.path 挿入で解決されるため、**モジュール basename がグローバルに一意である必要**がある。現状 12 ファイル全て一意で収集漏れはゼロ。将来の衝突は import file mismatch で落ちる（静かにスキップはしない）ので severity は低いが `__init__.py` を置くほうが堅牢。

> 注: conventions reviewer は同じ事象を **A-1 [high / confidence 95]** として、衝突時に
> `Interrupted: 1 error during collection` でスイート**全体**が停止することまで実測している。
> 親も独立に再現済み（2026-09-04 16:59）。severity は conventions 側の評価を採る。

---

## 問題なしと確認した配線

- **uv workspace**: ルート `pyproject.toml:14` `members = ["packages/*"]` と `[tool.uv.sources]` の workspace 指定が解決される。`uv.lock:5-11` の manifest.members は jin-cli / jin-core / jin-workspace の 3 件で一致。`jin-cli/pyproject.toml:11` にも workspace 指定があり単体でも解決可能
- **console_scripts**: `packages/jin-cli/pyproject.toml:8-9` `jin = "jin_cli.main:app"` が実際に動く。`.venv/bin/jin --help` が Phase 1 の 4 コマンドのみを表示。`tests/contract/test_cli_contract.py:22` は `Path(sys.executable).parent / "jin"` を直接叩くので **entry point の配線そのものがテストされている**（typer の CliRunner だけで済ませていない点は良い）
- **CLI exit code**: 要件書 §5 の 2 条件が実装（`main.py:106, 148-150`）・単体テスト（`test_cli.py:44-56`）・プロセス越し契約テスト（`test_cli_contract.py:31-34, 66, 96-99`）の 3 層で担保。warning のみは exit 0 という区別も明示的にテスト済み
- **ruff の対象範囲**: `ruff check . --show-files` で 32 ファイル、packages/ 配下の src と tests、scripts/、tests/ を全て含む。`extend-exclude` の delivery / docs / .venv は意図通り
- **テスト収集**: ディスク上の test_*.py 12 本 = 収集 12 本、漏れゼロ
- `uv run jin check examples` の rglob は要件書 §9 の `examples/**/*.jin` を満たす（W-08 の conftest 側だけが深さ固定）

## 優先順位の推奨（reviewer による）

W-01（CI が再現性を全く保証していない・1 行で直る）→ W-03 + W-02（次ラウンドで新パッケージが検査から漏れる直接原因）→ W-04（順序入れ替えだけ）→ W-05（jin-adk / jin-render 追加時に必ず踏む）
