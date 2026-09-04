# 再レビュー（修正ラウンド 1）— wiring

実測日: 2026-09-04 / レビュアー: rv1-wiring
基準状態: `uv run pytest` 442 passed / `lint-imports` 3 contracts kept / `.venv` = Python 3.14.6 / `uv` = 0.7.8（ローカル）

**実装者の報告・コメント・rationale は一切採用していない。** 判定はすべて下記の実行結果に基づく。
CI が実際に使う uv は `astral-sh/setup-uv@v5` が入れる最新版なので、検証には **uv 0.12.9（2026-09-01 リリース）**を
`$CLAUDE_JOB_DIR/tmp` にダウンロードして併用した（ローカルの 0.7.8 との差が W-01 の判定を分けたため）。

## Summary

- **確認対象: 7 件（W-01 / W-02 / W-03 / W-04 / W-05 / W-06 / W-11）**
- **defect-gone: 6 件 / 未消滅（部分）: 1 件（W-05）/ 判定不能: 0 件**
  - defect-gone: W-01（条件つき・下記 N-01 参照）/ W-02 / W-03 / W-04 / W-06 / W-11
  - 部分的に未消滅: **W-05** — `|` 区切り構文が正しく効くことは実測で確認できたが、
    **その書き方を強制する機械的な検査が無い**。Phase 2 で素朴な直列に書いても全テストが緑のまま通る。
- **新設 `test_packaging_contract.py` が「常に PASS する書き方」になっていないか**:
  **なっていない（合格）。** 未登録パッケージ `packages/jin-zz` を足すと 4 本が名指しで赤くなり、
  `packages/` 自体を消すと import 時に `iterdir()` が例外を出して rc=2（collection error）で落ちる。
  `test_at_least_one_package_exists`（>=2）が parametrize 空振りの防波堤として機能している。
  ただし **残る穴が 2 つ**: (a) `tests/` ディレクトリを持たないパッケージは `pytest.skip` で静かに素通りする、
  (b) layers 契約の**兄弟順序**を検査しない（= W-05 残件）。
  併せて新設の `test_ci_contract.py` も 6 通りの ci.yml 変異すべてを正しい名前のテストで捕まえた（後述の表）。
- **W-05: Phase 2 で兄弟パッケージを足したときに一方向が静かに許可されるか**:
  **許可される。** 隔離ツリーで実測 —
  `layers = [jin_cli, jin_lsp, "jin_adk | jin_render", jin_core]` は `jin_adk→jin_render` と
  `jin_render→jin_adk` の**両方**を BROKEN にする（構文は正しく効く）。
  一方 `layers = [jin_cli, jin_adk, jin_render, jin_core]`（素朴な直列）は
  `jin_render→jin_adk` **だけ**を BROKEN にし、`jin_adk→jin_render` を**静かに許す**。
  そして後者の書き方でも `test_packaging_contract.py` は **27 passed（全緑）**。
  防波堤は `pyproject.toml:58-64` のコメントと CLAUDE.md のチェックリストという**文章のみ**。
- **修正が入れた新規欠陥: 2 件**（N-01 medium / N-02 low。いずれも下記「新規欠陥」節）
- **作業ツリー復旧**:
  `pyproject.toml` / `schemas/jin.schema.json` / `.python-version` / `.github/workflows/ci.yml` /
  `examples/` はバックアップとバイト一致で復旧済み。`packages/` に残骸なし。
  フルスイート 442 passed / `lint-imports` 3 kept / `jin check`・`jin fmt --check` ともに rc=0 に復帰。
  **`uv.lock` はレビュー開始時のスナップショットと 4 行だけ差がある**（`resolution-markers` ブロックの追加のみ）。
  **出所は特定できない。** 私の変異操作は毎回直後に md5 一致を確認しており、この 4 行は私の操作では発生していない。
  レビュー中に別のエージェントが同じツリーで `packages/jin-adk` を一時的に作成・削除していたが、
  タイムスタンプ（`uv.lock` 18:20 / `jin-adk/pyproject.toml` 18:21）は因果を裏づけないので、
  そこまでは主張しない。
  影響は無いことを実測で確認済み: 現在の `uv.lock` は `uv lock --check`（uv 0.12.9）が **EXIT=0**、
  `[manifest].members` は `jin-cli / jin-core / jin-workspace` の 3 件、`jin-adk` の痕跡ゼロ。
  **修正ラウンドが作った側（`resolution-markers` 無し）も** 隔離コピーで uv 0.12.9 に掛けて
  `uv lock --check` **EXIT=0** / `UV_LOCKED=1 uv sync` **EXIT=0**（lock 無変更）を確認したので、
  この 4 行の差は cosmetic であり、どちらの状態でも CI は通る。
  レビュー開始時のスナップショットは `/Users/toyota/.claude/jobs/8b3a6b62/tmp/ul2.bak` に残してあるので、
  厳密に戻したい場合はこれを使えばよい。

---

## finding 別の判定

| ID | 判定 | 根拠（実行したコマンドと出力） |
|---|---|---|
| **W-01** uv.lock が CI で何も保証していない | **defect-gone（条件つき）** | CI の全ステップを `UV_LOCKED=1` + uv 0.12.9 で再現。**stale lock を注入**（`pyproject.toml` の dev グループに `mypy>=1.0` を追加、`uv.lock` 据え置き）した状態で:<br>・`UV_LOCKED=1 uv sync --frozen`（= ci.yml:44）→ `warning: Ignoring UV_LOCKED because --frozen was provided` / **EXIT=0** / lock 無変更<br>・`UV_LOCKED=1 uv run lint-imports`（= ci.yml:49）→ **EXIT=2** `error: The lockfile at uv.lock needs to be updated, but UV_LOCKED=1 was provided.` / **lock は書き換わらない**<br>旧欠陥の本体（「CI の途中で lock が黙って書き換わり、コミット済み lock と別の解決でテストが走る」）は**消滅**。ただし落ちるのは 2 番目のステップで、`Sync dependencies` ステップ自身は宣言した検査をしていない → **N-01** 参照。<br>クリーンツリーでの全ステップ再現（uv 0.12.9）は 9 ステップすべて rc=0、`uv.lock` は最後まで `same`。 |
| **W-02** import-linter の自己テストが実契約を検証していない | **defect-gone** | 修正後は `setup_cfg_from(real_importlinter_section())`（test_dependency_direction.py:39-60）が `pyproject.toml` の `[tool.importlinter]` を tomllib で読んで setup.cfg に写す。**実契約を壊して自己テストが赤くなるかを 2 通りで実測**:<br>(a) `forbidden_modules = ["google"]` → `["gogle"]` に typo → `test_import_linter_actually_bites_on_a_forbidden_import[...google-adk]` が **FAILED**（「違反を注入したのに import-linter が通ってしまった」）<br>(b) `source_modules = ["jin_core"]` → `["jin_kore"]` に typo → **4 本が FAILED**（`test_import_linter_passes_on_the_real_tree` / 注入テスト 2 本「'google-adk' の契約が BROKEN になっていない。BROKEN: []」/ `test_injected_config_is_generated_from_the_real_contracts`）<br>いずれも `pyproject.toml` 復旧後は該当テストが緑に戻る。旧レビューで指摘した「実契約が常に KEPT になっても両テストが緑」は**再現しない**。<br>加えて BROKEN になった**契約名まで照合**する実装（:138-146）が入っており、「別の契約が代わりに落ちているだけ」の偽 green も塞がれている。 |
| **W-03** testpaths ハードコードで新パッケージのテストが黙って走らない | **defect-gone** | `testpaths = ["tests", "packages"]`（pyproject.toml:35）に変更。隔離コピーで Phase 2 を模して `packages/jin-adk` / `packages/jin-render` を**チェックリスト通り全項目登録**して足し、`packages/jin-adk/tests/test_adk_smoke.py` に `assert False` を置いた:<br>→ `FAILED packages/jin-adk/tests/test_adk_smoke.py::test_should_be_collected_and_fail` が**収集されて失敗**。旧状態（合計 225 のまま新テストが 1 件も収集されない）は**再現しない**。<br>登録漏れ側も実測: `packages/jin-zz` を pyproject を直さずに足すと 4 本が名指しで赤 —<br>`test_every_package_test_directory_is_a_package[jin-zz]` / `test_every_package_is_a_root_package[jin-zz]`（`assert 'jin_zz' in ['jin_core','jin_cli','jin_adk','jin_render']`）/ `test_every_package_appears_in_the_layers_contract[jin-zz]` / `test_every_package_is_declared_in_the_workspace[jin-zz]`（`assert 'jin-zz' in [...]`）。 |
| **W-04** スキーマドリフトの 2 重の網が独立していない | **defect-gone** | ci.yml でステップ順を入れ替え（`Test`:61 → `Detect JSON Schema drift`:67）、検出方法を**ツリーを書き換えない比較**に変更（`uv run jin schema \| diff -u schemas/jin.schema.json -`、ci.yml:68）。<br>`schemas/jin.schema.json` の `"title": "JinFile"` → `"CORRUPTED"` を注入して実測:<br>・ドリフトステップ → **EXIT=1**、差分を `-  "title": "CORRUPTED"` / `+  "title": "JinFile"` として出力<br>・**ステップ実行後もツリーは書き換わらない**（`grep -c CORRUPTED` = 1 のまま）<br>・pytest 側の独立した網 `test_committed_schema_has_no_drift` も **FAILED**<br>旧欠陥（生成スクリプトが先にツリーを直してしまい pytest 側が必ず緑になる／`git diff` が未追跡ファイルを見ない）は**両方とも消滅**。ci.yml の順序と方式は `test_ci_contract.py` の 2 本が固定しており、順序を入れ替える変異で両方が赤くなることも実測済み（下表）。 |
| **W-05** layers 契約が兄弟パッケージの追加を想定していない | **未消滅（部分修正）** | **(1) 構文は正しく効く（確認済み）** — 隔離ツリーに `jin_core/jin_cli/jin_adk/jin_render/jin_lsp` を置き、`jin_adk→jin_render` と `jin_render→jin_adk` を両方注入:<br>・`layers = [jin_cli, jin_lsp, "jin_adk \| jin_render", jin_core]` → **両方 BROKEN**（`jin_render.uses_adk -> jin_adk` と `jin_adk.uses_render -> jin_render` の 2 件を報告）<br>・`layers = [jin_cli, jin_lsp, jin_adk, jin_render, jin_core]` → **`jin_render→jin_adk` の 1 件のみ BROKEN**、`jin_adk→jin_render` は**報告されない**（= 静かに許可）<br>**(2) しかし正しい書き方が強制されていない** — 隔離コピーで jin_adk / jin_render を**素朴な直列**で登録した状態:<br>`pytest tests/contract/test_packaging_contract.py` → **27 passed（全緑）**、`test_every_package_appears_in_the_layers_contract` も 4 passed。<br>原因は test_packaging_contract.py:110 が `{name.strip() for layer in layers for name in layer.split("\|")}` と**フラットな集合**に潰しており、「各パッケージが宣言に登場するか」しか見ていないこと。**兄弟の同居（順序）は検査対象外**。<br>したがって W-05 の実害（Phase 2 で一方向が静かに許可される）は依然として発生しうる。防波堤は `pyproject.toml:58-64` のコメントと CLAUDE.md のチェックリストのみ。 |
| **W-06** CI の Python バージョンが浮いている | **defect-gone** | `.python-version` = `3.14` を新設。**実際に uv の選ぶ版を決めることを実測**: `uv python find` は `.python-version` = 3.14 で `/opt/homebrew/opt/python@3.14/bin/python3.14` を返し、3.12 に書き換えると `error: No interpreter found for Python 3.12` になる（= ファイルが実効的に効いている）。現行 `.venv` も Python **3.14.6**。<br>ci.yml:40-41 に `uv run python -c "import sys; print(sys.version)"` があり、実際に使った版がログに残る。<br>整合性: `.python-version` 3.14 ≥ `requires-python = ">=3.12"`（pyproject / uv.lock 双方）。`ruff target-version = "py312"` は**最低構文ターゲット**であり `requires-python` の下限と一致しているので矛盾しない（3.14 で走らせても問題ない）。<br>`test_ci_contract.py` の 4 本が固定しており、`.python-version` 削除 → 2 本 FAILED、`3.11`（下限未満）→ `test_pinned_python_satisfies_requires_python` FAILED、`setup-uv` に `python-version: "3.12"` を書き足す（二重管理）→ `test_ci_does_not_hardcode_a_python_version` FAILED を実測。<br>残る観察（欠陥ではない）: `requires-python = ">=3.12"` と宣言しつつ CI は 3.14 のみを検証する。宣言した下限 3.12 は誰も検証しない。修正前も浮いていて 3.12 を踏む保証は無かったので**悪化ではない**が、matrix を持たない限り下限は未検証のまま。 |
| **W-11** permissions / concurrency / timeout-minutes が未指定 | **defect-gone** | ci.yml:9-10 `permissions: contents: read` / :13-15 `concurrency: group + cancel-in-progress: true` / :21 `timeout-minutes: 15` を追加。読んだだけでなく**変異で落ちることを実測**（下表）。`test_every_job_has_a_timeout` は `jobs:` 配下のジョブ数と `timeout-minutes:` の行数を数えるので、ジョブを増やして timeout を付け忘れても落ちる（現状 1 ジョブ）。 |

### ci.yml 変異テスト（新設 `test_ci_contract.py` が本当に落ちるか）

隔離コピーで ci.yml を 6 通りに壊し、毎回 `pytest tests/contract/test_ci_contract.py` を実行した結果。

| 変異 | rc | 赤くなったテスト |
|---|---|---|
| `permissions:` ブロックを削除 | 1 | `test_workflow_declares_least_privilege` |
| `concurrency:` を `xconcurrency:` に | 1 | `test_workflow_declares_concurrency` |
| `timeout-minutes: 15` を削除 | 1 | `test_every_job_has_a_timeout` |
| `UV_LOCKED: "1"` → `"0"` | 1 | `test_uv_locked_is_set_for_the_whole_job` |
| `Test` と `Detect JSON Schema drift` の順序を入れ替え | 1 | `test_schema_drift_check_runs_after_the_tests` / `test_schema_drift_check_does_not_rewrite_the_tree` |
| `setup-uv` に `python-version: "3.12"` を追記 | 1 | `test_ci_does_not_hardcode_a_python_version` |
| （無変異） | 0 | — |

---

## 新規欠陥（修正が入れたもの）

### N-01 [MEDIUM] confidence 92 — `UV_LOCKED` と `--frozen` が同一ステップで衝突しており、`Sync dependencies` ステップは lock 検証をしていない。しかも挙動が uv のバージョンで変わる

該当: `.github/workflows/ci.yml:26`（`UV_LOCKED: "1"`）と `.github/workflows/ci.yml:44`（`run: uv sync --frozen`）

同じコマンドに「lock を更新するな」（`--frozen`）と「lock がずれていたら失敗せよ」（`UV_LOCKED`）を同時に渡している。
**uv のバージョンによって結果が変わる**（クリーンツリーでの実測）:

| uv | `UV_LOCKED=1 uv sync --frozen` |
|---|---|
| **0.12.9**（2026-09-01。`setup-uv@v5` が今日入れる版） | `warning: Ignoring UV_LOCKED because --frozen was provided` / **EXIT=0** |
| **0.7.8**（このリポジトリのローカル環境） | `error: the argument '--frozen' cannot be used with '--locked'` / **EXIT=2**（クリーンツリーでも無条件に失敗） |

帰結は 2 つ。

1. ci.yml:23-26 のコメントは「UV_LOCKED=1 で**全ての** uv コマンドに『lock を書き換えるなら失敗せよ』を課す」と書いてあるが、
   **その直後の 1 行がまさに例外**になっている。lock 検証が最初に効くのは次のステップ（`Check dependency direction`）で、
   失敗メッセージも「依存方向の検査」という無関係な名前のステップに出る。
2. `setup-uv@v5` に `version:` 入力が無いため uv の版は固定されていない。将来 uv が 0.7.8 系の
   厳格な扱いに戻る／`setup-uv` が古い uv を入れる状況になれば、**CI は全実行がこの 1 行で落ちる**。
   ローカルでこのリポジトリの uv（0.7.8）を使って CI を再現しようとした人は今すぐ踏む。

修正は 1 語削るだけ: **ci.yml:44 を `run: uv sync` にする**（`UV_LOCKED` が job env にあるので `--locked` 相当が効く）。
隔離コピー（uv 0.12.9）で両方を同じ stale lock（dev グループに `mypy>=1.0` を追加、`uv.lock` 据え置き）に掛けた実測:

| コマンド | EXIT | 出力 | lock |
|---|---|---|---|
| `UV_LOCKED=1 uv sync --frozen`（現行 ci.yml:44） | **0** | `warning: Ignoring UV_LOCKED because --frozen was provided` / `Checked 23 packages` | 無変更 |
| `UV_LOCKED=1 uv sync`（提案） | **1** | `error: The lockfile at uv.lock needs to be updated, but UV_LOCKED=1 was provided.` | 無変更 |

クリーンツリーでは提案形も `Resolved 25 packages` で EXIT=0（誤検知しない）。

なお `test_ci_contract.py::test_uv_locked_is_set_for_the_whole_job`（:38-59）は
**env に `UV_LOCKED: "1"` があるかしか見ておらず**、それが `--frozen` に打ち消されていることは検出しない。
これは本レビューの W-02 で指摘した「検査が存在することと検査が実際に落ちることは別」と同型なので、
併せて「`run:` 行に `--frozen` が無いこと」も固定するとよい。

### N-02 [LOW] confidence 85 — `tests/` を持たないパッケージは packaging contract を静かに素通りする

該当: `tests/contract/test_packaging_contract.py:56-58` および `:73-75`（どちらも `pytest.skip`）

隔離コピーで `packages/jin-render/tests/` を削除して実測:

```
SKIPPED [1] tests/contract/test_packaging_contract.py:58: jin-render はまだテストディレクトリを持たない
SKIPPED [1] tests/contract/test_packaging_contract.py:75: jin-render はまだテストディレクトリを持たない
```

`testpaths` 網羅と `__init__.py` の 2 本が skip になるだけで、スイート全体は緑。
「テストを 1 本も持たないパッケージ」を作れてしまい、W-03 で塞いだはずの
「新パッケージのテストが CI で走らない」状態に別経路で到達できる。
severity は低い（テストが無いパッケージは他の contract テストで root_packages / layers / workspace の
登録漏れは捕まる）が、`skip` ではなく `fail` にするか、少なくとも
「Phase 2 以降のパッケージは tests/ を必ず持つ」を別の 1 本で固定するのが安全。

---

## W-05 の申し送り（Phase 2 実装者向け）

Phase 2 で `jin-adk` / `jin-render` を足すとき、**`pyproject.toml` の layers を次の形にすること**:

```toml
layers = [
  "jin_cli",
  "jin_lsp",
  "jin_adk | jin_render",   # ← 兄弟は 1 要素に "|" 区切り。行を分けると片方向が静かに通る
  "jin_core",
]
```

行を分けた場合に何が起きるかは本レビューで実測済み（上表 W-05 欄）。
**現状これを機械で強制する検査は無い**ので、`test_packaging_contract.py` に
「design.yaml の dependency_direction.rules から『互いに依存しない』ペアを読み、
そのペアが layers の同一要素に `|` で並んでいること」を確かめる 1 本を足すのが根本策。
簡易版としては「`jin_adk` と `jin_render` が同じ layer 要素に入っていること」を直書きしても、
現状（=文章のみ）より確実に強い。

---

## 復旧の記録

| 対象 | 状態 |
|---|---|
| `pyproject.toml` | バックアップとバイト一致（`diff -q` OK） |
| `schemas/jin.schema.json` | バックアップとバイト一致（`diff -q` OK） |
| `.python-version` | `3.14`（変更なし） |
| `.github/workflows/ci.yml` | 変異は隔離コピーでのみ実施。実物は未変更 |
| `packages/` | `jin-cli` / `jin-core` の 2 件のみ。残骸なし |
| `examples/` | 未変更 |
| `uv.lock` | `uv lock --check` **EXIT=0**、members 3 件、`jin-adk` の痕跡ゼロ。レビュー開始時スナップショットとの差は `resolution-markers`（4 行）のみで、これは別エージェントが 18:21 に `packages/jin-adk` を一時作成していた時間帯の変化と一致する。私の各実験は直後に md5 一致まで確認済み |
| `.venv` | Python 3.14.6（未再作成。uv 0.12.9 の検証は `UV_PROJECT_ENVIRONMENT` を別ディレクトリに逃がして実施し、検証後に削除） |
| フルスイート | `uv run pytest` **442 passed** |
| `lint-imports` | **3 contracts kept, 0 broken** |
| `jin check examples` / `jin fmt --check examples` | いずれも rc=0 |
