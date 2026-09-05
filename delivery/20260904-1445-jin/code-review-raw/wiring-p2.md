# Stage 5 review: wiring — 実装ラウンド 2（Jin Phase 2・jin-adk）

実測日: 2026-09-05 / レビュアー: review-wiring-p2 / ブランチ `feat/jin-phase2-adk`（未コミットの作業ツリー）
基準状態（隔離コピー・uv 0.12.9 + 隔離 venv）: `uv run pytest` **696 passed**（jin-adk 130 / test_build_run 29）/
`lint-imports` **Analyzed 50 files, 139 dependencies / 3 kept** / ruff 58 files / スキーマドリフト・`jin check`・`jin fmt --check` とも rc=0。

**実装者の報告・コメント・rationale は採用していない。** 判定はすべて下記の実行結果に基づく。
破壊的な変異はすべて **リポジトリの隔離コピー**（`scratchpad/review-wiring`）で行い、実ツリーには本報告書以外を 1 バイトも書いていない。
CI の実挙動は ci.yml がピンする **uv 0.12.9 の実バイナリ**（x86_64 linux・scratchpad にダウンロード）と
`UV_PROJECT_ENVIRONMENT` を逃がした隔離 venv で 9 ステップすべてを再現した（ローカルの uv 0.12.10 でも併走）。

## Summary

- **finding 総数: 9 件（high 0 / medium 2 / low 7）。CI を落とす欠陥・静かに壊れている配線は見つからなかった。**
- **CI 破綻の最有力候補（`uv.lock` の `revision = 2 → 3` と `resolution-markers` の書き換えを、ci.yml がピンする uv 0.12.9 が受け付けるか）は defect 無し。**
  0.12.9 で `uv lock --check` EXIT=0 / `UV_LOCKED=1 uv sync` EXIT=0 / 9 ステップ全 rc=0 / `uv.lock` は最後まで md5 一致（`3e23308b…`）。
- **パッケージ追加の 5 箇所 + 1 は 6/6 とも名指しで赤くなる**（下表 M1〜M6）。W-05 の兄弟検査は Phase 3 の偽 `jin-render` で赤くなることを実測（M13）。
- **import-linter は 3 方向とも BROKEN**（jin_adk→jin_cli / jin_core→jin_adk / jin_adk→jin_cli.resolver）。
  ただし jin_core→jin_adk は **import-linter 系のテストしか拾わない**（生の検査 2 本は素通り・F-W-P2-003）。
- 上位 5 件: F-W-P2-001（jin-cli 自身の pyproject の依存欠落を pytest が拾わない）/ F-W-P2-002（`mutate_p2.py` が実ツリーを書き換える dev コマンドとして CLAUDE.md に載った）/
  F-W-P2-003（jin_core→jin_adk の生の網が無い）/ F-W-P2-004（`build-errors/` fixture が正準形契約の外）/ F-W-P2-005（importlib 検査の盲点 `__import__`）。
- 作業ツリー: 実ツリーは無変更（`git status` の件数・`uv.lock` / `pyproject.toml` / `packages/jin-cli/pyproject.toml` の md5 は開始時と一致）。
  隔離コピーは各変異のあとバックアップから復旧し、最後に無変異で 3 契約 kept / `uv lock --check` EXIT=0 を再確認した。

---

## 観点別の実測（team-lead の 8 項目）

### 1. パッケージ追加の 5 箇所 + 1 — 6/6 名指しで赤（下の注入表 M1〜M6）

### 2. import-linter
- `Analyzed 50 files, 139 dependencies`。`root_packages` から `jin_adk` を外すと **36 files / 80 dependencies に減って 3 kept のまま**＝契約対象外になるが、`test_every_package_is_a_root_package[jin-adk]` が赤くなる（M3）。差の 14 files は jin_adk の `.py` 7 本と、`include_external_packages = true` で jin_adk 経由に入る外部ルート（google / jinja2 など）の分。
- `layers = ["jin_cli", "jin_adk", "jin_core"]` で **jin_adk→jin_cli**（M8）と **jin_core→jin_adk**（M9）がともに layers 契約 BROKEN。forbidden 契約は **jin_adk→jin_cli.resolver**（M10）を BROKEN にする。
- `"jin_adk | jin_render"` を jin_render 不在で書くと EXIT 1 になるという implementer の主張（decision-conformance §2.16）を隔離コピーで追試: `lint-imports` → `Missing layer 'jin_render': module jin_render does not exist.` **rc=1**（主張は正確。単独表記は妥当）。単独表記の帰結（片方しか無いペアは `independence_violations` が素通し）は round-2 O-3 で既知であり、**偽 jin-render を足した瞬間に `test_layers_contract_keeps_sibling_packages_in_one_element` が赤になる**ことを M13 で実測した。`|` に直せば緑に戻る（M13b）。

### 3. importlib の厳密一致
- expected は `jin_adk/runtime.py` と `jin_cli/resolver.py` の 2 モジュール。`jin_adk/trace.py` に `import importlib` を足すと名指しで赤（M11）。
- src 側 grep（`__import__` / `importlib` の別名 / `exec(` / `eval(` / `runpy` / `import_module`）: `runtime.py` の `importlib.util.spec_from_file_location` と `jin_cli/resolver.py` の `importlib.import_module` 以外にヒット無し（`.j2` テンプレートも 0 件）。`templates/__init__.py` は `importlib.resources` を避けて `Path(__file__)` で読む（コメントに理由あり）。
- **検査の限界**: `__import__('os')` だけを注入すると素通り（M12b・F-W-P2-005）。

### 4. CI（`.github/workflows/ci.yml` は本ブランチで無変更）
| ステップ | uv 0.12.9 / 隔離 venv / `UV_LOCKED=1` | 備考 |
|---|---|---|
| Show Python version | rc=0（3.14.7・ここで暗黙 sync が走り 75 packages インストール） | google-adk 2.8.0 込みでキャッシュありなら数十秒 |
| `uv lock --check`（追加検証） | rc=0 `Resolved 78 packages` | revision 3 の lock を 0.12.9 が受け付ける |
| Sync dependencies (`uv sync`) | rc=0 `Checked 75 packages`・lock 無変更 | |
| lint-imports | rc=0 3 kept | |
| ruff check / format --check | rc=0 / 58 files | `tests/fixtures/stubs` と `packages/jin-adk` を含む |
| Test | rc=0 **696 passed** 45 warnings 38.9s / 2 snapshots passed | `--snapshot-update` は addopts にも ci.yml にも無い |
| Detect JSON Schema drift | rc=0 | |
| Check examples / fmt --check | rc=0 / rc=0 | |

- `uv.lock` の差分は **追加のみ**（削除行は `revision = 2` と marker 1 行だけ）。既存パッケージの版は 1 つも動いていない。追加パッケージは 53 件で、内訳は `jin-adk` / `google-adk 2.8.0` / `jinja2 3.1.6` / `syrupy 6.0.0` の 4 件 + 推移依存 49 件。
- `.env` 不要: 生成コードは dotenv を import しない（コメントで ADK 側の `load_dotenv_for_agent` を説明するのみ）。テストは `--model fake` でネットワークに出ない。
- `tests/contract/test_ci_contract.py`（テスト関数 16 本）は ci.yml 無変更なので意味を保つ（`MINIMUM_UV_COMMANDS = 9` は現状 9 件と一致）。
- **GitHub Actions 定型項目**（`github-actions-wiring.md`）: `workflow_run` / `workflow_call` / `pull_request_target` / `workflow_dispatch` / `continue-on-error` / `if: always()` / `|| true` / `set +e` / `secrets.` / `id-token` を grep → **0 件**。ワークフローは ci.yml 1 本、トリガは `push`（main）と `pull_request` のみ。GHA-01〜06 はすべて非該当（W-10 と同じ結論）。`permissions: contents: read` は最小。

### 5. テスト収集
- `--collect-only`（`-o addopts=--import-mode=importlib`）: **696 tests collected**、うち `packages/jin-adk/tests` **130**（ファイル 5 本すべて）、`packages/jin-cli/tests/test_build_run.py` 29。
- `packages/jin-adk/tests/__snapshots__/test_codegen.ambr` は `git check-ignore` に**掛からない**（`.gitignore` は `.venv/ __pycache__/ *.pyc .pytest_cache/ .ruff_cache/ .import_linter_cache/` のみ）。`packages/jin-adk/` は丸ごと未追跡なので `git add` で一緒に入る。
- syrupy の挙動を実測: `.ambr` を消すと `test_generated_agent_py_snapshot[researcher/pipeline]` が **FAILED（自動生成しない）**、テンプレートに 1 行足すと **FAILED（stale）**。コミット忘れ・更新忘れのどちらも CI で赤くなる。

### 6. エントリポイント
- `uv run jin --help`: check / fmt / schema / dump / **build / run** の 6 つ。`jin render` / `jin lsp` / `jin editor` は **rc=2（No such command）**。
- `packages/jin-cli/pyproject.toml` の `dependencies` と `[tool.uv.sources]` に `jin-adk` あり。`uv.lock` の `jin-cli` の `requires-dist` にも `jin-adk (editable)` が記録されている。
- `uv build --package jin-adk --wheel`: wheel に `jin_adk/templates/agent.py.j2` が**含まれる**（editable でない配布でも `render_agent_py` が動く）。

### 7. スタブ供給の配線
- 実ツリー / 隔離 venv とも `python -c "import research"` → **ModuleNotFoundError**（誤って import 可能になっていない）。
- in-process テスト（`test_runtime.py` / `test_build_run.py`）は autouse fixture の `monkeypatch.syspath_prepend(STUBS)` と teardown の `sys.modules` 掃除。実バイナリを叩く `test_cli_contract.py` は `env_extra={"PYTHONPATH": stubs}` で渡す（`{**os.environ, **env_extra}` なので**上書き**。CI では未設定なので無害・F-W-P2-007）。
- `pipeline.jin` は `ref` を持たない（0 件）ので README の `jin run examples/pipeline/... --model fake` は PYTHONPATH 無しで rc=0（実測）。`researcher.jin` は 5 件の `ref` を持ち、スタブが要る。

### 8. `jin run` の一時ディレクトリ
- `tempfile.mkdtemp(prefix="jin-run-")` は **`TMPDIR` を尊重**（`TMPDIR=$S/tmpx` で `…/tmpx/jin-run-xexhwnxn/Pipeline/agent.py`）。0700。
- 後始末: 正常終了 / import 失敗（`RunError`）/ `run_model` 完走のいずれでも **TMPDIR 配下に残骸ゼロ**（`__pycache__/agent.cpython-314.pyc` が一時ディレクトリ内に作られるが `rmtree` で一緒に消える）。`finally` なので実行中の例外でも消える。
- `sys.modules`: `_jin_run_<uuid>` は残らない（0 件）。`research` / `research.tools` / `research.guards` は**残る**（利用者のモジュールなので妥当）。`rmtree(ignore_errors=True)` は消せなかったときに黙る（F-W-P2-008）。

---

## 注入検証の表

隔離コピーで 1 箇所ずつ壊し、`tests/contract/test_packaging_contract.py` / `test_dependency_direction.py` / `test_adk_version_contract.py` を隔離 venv の python で実行（実バイナリ `jin` / `lint-imports` も隔離 venv 経由でコピーのソースを指すことを `jin_adk.__file__` で確認済み）。毎回バックアップから復旧し md5 一致を確認。

| ID | 抜いた / 壊した箇所 | 期待 | 実測（名指しで赤くなったテスト） |
|---|---|---|---|
| M1 | root `[project].dependencies` から `jin-adk` | 名指し | `test_every_package_is_declared_in_the_workspace[jin-adk]`。`uv lock --check` も EXIT=1 |
| M2 | root `[tool.uv.sources]` から `jin-adk` | 名指し | 同上。`uv lock --check` EXIT=2（`missing an entry in tool.uv.sources`） |
| M3 | `root_packages` から `jin_adk` | 名指し | `test_every_package_is_a_root_package[jin-adk]`。lint-imports は **36 files / 3 kept で素通り**（=この 1 本だけが守っている） |
| M4 | layers から `jin_adk` | 名指し | `test_every_package_appears_in_the_layers_contract[jin-adk]` |
| M5 | resolver 隔離契約の `source_modules` から `jin_adk` | 名指し | `test_resolver_isolation_contract_covers_every_package_but_the_cli` |
| M6 | `packages/jin-adk/tests/__init__.py` 削除 | 名指し | `test_every_package_test_directory_is_a_package[jin-adk]` |
| M7 | **`packages/jin-cli/pyproject.toml`** の `dependencies` / `sources` から `jin-adk` | pytest 契約は無い想定 | **pytest 全緑（素通り）**。`uv lock --check`（0.12.9）EXIT=1 → CI の `UV_LOCKED=1 uv sync` で落ちる（F-W-P2-001） |
| M8 | `jin_adk/codegen.py` に `import jin_cli.main` | layers BROKEN | lint-imports rc=1: layers BROKEN + resolver 契約 BROKEN（`jin_adk.codegen -> jin_cli.main -> jin_cli.resolver`）。pytest: `test_jin_adk_does_not_import_jin_cli_or_later_packages` / `test_import_linter_passes_on_the_real_tree` / `test_injected_config_is_generated_from_the_real_contracts` |
| M9 | `jin_core/canonical.py` に `import jin_adk` | layers BROKEN | lint-imports rc=1: layers BROKEN（`jin_core.canonical -> jin_adk`）。pytest: `test_import_linter_passes_on_the_real_tree` / `test_injected_config_…` の **2 本のみ**。生の検査 `test_jin_core_source_does_not_mention_adk`（"google" しか見ない）/ `test_jin_core_does_not_import_jin_cli` は**素通り**（F-W-P2-003） |
| M10 | `jin_adk/runtime.py` に `from jin_cli.resolver import ImportResolver` | forbidden BROKEN | lint-imports rc=1: layers BROKEN + **resolver 契約 BROKEN**（`jin_adk.runtime -> jin_cli.resolver`）。pytest は M8 と同じ 3 本 |
| M11 | `jin_adk/trace.py` に `import importlib` | 名指し | `test_the_only_module_importing_importlib_is_the_cli_resolver` |
| M12 | 同 `from importlib import import_module as _im` | 拾う | 拾う（M11 と同じテスト） |
| M12b | 同 `_m = __import__('os')` だけ | 素通り（限界） | **素通り**（F-W-P2-005） |
| M13 | 偽 `packages/jin-render`（チェックリスト 6 項目充足）+ layers を素朴な直列 `[jin_cli, jin_adk, jin_render, jin_core]` | W-05 検査が赤 | `test_layers_contract_keeps_sibling_packages_in_one_element` + tripwire `test_later_packages_do_not_exist_yet[jin_render]` |
| M13b | 同上を `"jin_adk \| jin_render"` に直す | 全緑 | packaging contract 全緑 |
| S1 | `.ambr` を削除 | FAILED | `test_generated_agent_py_snapshot[*]` FAILED・`.ambr` は自動生成されない |
| S2 | `agent.py.j2` に 1 行追加 | FAILED | 同テスト FAILED（stale） |

（M8〜M12 の初回は docstring より前に注入して `from __future__` の SyntaxError を誘発し、`test_cli.py` の collection error という副作用が混ざった。表は `from __future__` の後ろに注入し直した再実行の結果。）

---

## Findings

### F-W-P2-001 [MEDIUM] confidence 85 — パッケージ自身の `pyproject.toml` の依存欠落を pytest 契約が拾わない
`packages/jin-cli/pyproject.toml:8-12` / `tests/contract/test_packaging_contract.py:236-245`（`test_every_package_is_declared_in_the_workspace` は root の pyproject しか見ない）

M7 の実測: `jin-cli` 自身の `dependencies` と `[tool.uv.sources]` から `jin-adk` を消しても **pytest は全緑**。落とすのは `uv lock --check`（EXIT=1）と CI の `UV_LOCKED=1` だけで、CI では最初の `uv run`（`Show Python version` ステップ。N-01 と同じく `Sync dependencies` より前）で止まる。ローカルの `uv run pytest` は既定で lock を**黙って更新して**通る。
静かに壊れるもの: workspace の推移で `jin_adk` が入るので手元では動くが、`jin-cli` を単体でインストールした環境で `jin` が `ModuleNotFoundError: jin_adk` になる。CLAUDE.md のチェックリスト（root の 5 箇所）は「依存する側の pyproject」を項目に持たない。
修正案: `test_packaging_contract.py` に「各 `packages/<p>/src/<m>/**.py` が import している `jin_*` が、その `packages/<p>/pyproject.toml` の `dependencies` に列挙されている」1 本を足す（AST で `jin_` 前置の import を集めて突合）。CLAUDE.md のチェックリストに 7 項目目「依存する側の `packages/<x>/pyproject.toml` にも足す」を追記。

### F-W-P2-002 [MEDIUM] confidence 80 — 実ツリーを書き換える変異スクリプトが「開発コマンド」として CLAUDE.md に載った
`CLAUDE.md:101`（`uv run python delivery/20260904-1445-jin/phase2-mutations/mutate_p2.py`）/ `delivery/20260904-1445-jin/phase2-mutations/mutate_p2.py:16,207-211`

スクリプトは `ROOT = parents[3]`（= 実リポジトリ）の `packages/jin-adk/src/**` と `packages/jin-cli/src/jin_cli/main.py` を `write_text` で**その場で書き換え**、`finally` で戻す。加えて `packages/` と `tests/` の `__pycache__` を毎回 `rmtree` する。`finally` は SIGKILL / OOM / 端末クローズでは走らないので、途中で落ちると **31 変異のどれかが実ツリーに残る**（`git diff` で気づけるが、未追跡の `packages/jin-adk/` は差分に出ない）。また `uv run` を `UV_LOCKED` 無しで呼ぶので stale な lock を黙って書き換える（W-01 と同型）。
Phase 1 の `fix-round-1-mutations/mutate*.py` も同じ形式だが、Phase 1 では CLAUDE.md の「開発コマンド」節には載せていなかった。
修正案: 変異はコピー（`shutil.copytree` → tmp）で行うか、少なくとも CLAUDE.md からは外して `delivery/` の replay 手順にとどめる。残す場合は「実ツリーを書き換える・クリーンな作業ツリーでだけ走らせる」を 1 行添える。

### F-W-P2-003 [LOW] confidence 90 — jin_core → jin_adk の「生の網」が無い（import-linter を差し替えると守れない）
`tests/contract/test_dependency_direction.py:167-180`

M9 の実測: `jin_core/canonical.py` に `import jin_adk` を注入すると赤くなるのは import-linter 系の 2 本だけ。`test_jin_core_source_does_not_mention_adk` は `"google"` を、`test_jin_core_does_not_import_jin_cli` は `"jin_cli"` を見るだけで、`jin_adk` は素通り。`test_jin_adk_does_not_import_jin_cli_or_later_packages`（jin_adk 側の生の網）には対応物が jin_core 側に無い。
修正案: `test_jin_core_does_not_import_jin_cli` を「`jin_core` 以外の `jin_*` を一切 import しない」（design.yaml rule 1 のワイルドカードそのもの）に広げる。

### F-W-P2-004 [LOW] confidence 85 — `tests/fixtures/build-errors/*.jin`（14 本）が正準形契約と CI の fmt チェックの外にある
`tests/conftest.py:51-58`（`formattable_paths` は `examples` + `fixtures/errors` のみ）/ `.github/workflows/ci.yml` 末尾（`jin fmt --check examples`）

W-08 と同型。新しい fixture 集合が `canonical` 往復契約と `jin fmt --check` の対象に入っていない。現時点では 14 本とも正準形（`jin fmt --check tests/fixtures/build-errors` rc=0・`jin check` 0 error）だが、次に fixture を足した人が非正準で置いても何も赤くならない。`test_spec_consistency.py:724-732` は adk-mapping.md §3.1 との**件数・名前の対応**しか見ない。
修正案: `formattable_paths` に `fixtures/build-errors` を加える（全部モデルになるので UNFORMATTABLE の除外は不要）。

### F-W-P2-005 [LOW] confidence 90 — importlib 厳密一致テストの正規表現が守るべき主張より狭い
`tests/contract/test_packaging_contract.py:204-207`

行頭の `import importlib` / `from importlib` だけを見る。M12b: `_m = __import__('os')` は素通り。`exec(` / `runpy` / `importlib` を別モジュール経由で受け取る形も同様。現状の src にはいずれも無い（grep 0 件）ので欠陥ではなく検査の幅の問題。
修正案: AST で `ast.Import` / `ast.ImportFrom` の `importlib*` と、`ast.Call` の `__import__` / `exec` / `eval` / `runpy.*` を集める（`test_jin_core_never_imports_importlib` は既に AST ベースなので同じ書き方に揃える）。

### F-W-P2-006 [LOW] confidence 75 — Phase 2 の CI 実行は未実施のまま（`pipeline_e2e = not_run`）
`delivery/20260904-1445-jin/implementation-notes.md:529`

本レビューの 9 ステップ再現は「uv 0.12.9 実バイナリ + `.python-version` 3.14 + 隔離 venv」で GitHub Actions に最も近い形だが、ランナー（ubuntu-latest・キャッシュ無し）での google-adk 2.8.0 のインストール時間と `timeout-minutes: 15` の余裕は未計測。`uv sync` はローカルキャッシュありで 38ms、Test は 40s。冷たいランナーでも 15 分を超える材料は無いが、実測は PR の Actions 結果で確認すること（W-06 と同じ扱い）。

### F-W-P2-007 [LOW] confidence 80 — `test_cli_contract._run` の `PYTHONPATH` は追記ではなく上書き
`tests/contract/test_cli_contract.py:26,165`

`{**os.environ, **env_extra}` なので `PYTHONPATH=tests/fixtures/stubs` は開発者の既存 `PYTHONPATH` を**捨てる**。CI では未設定なので無害。ただし本レビューの隔離コピーで `PYTHONPATH` にコピーの `src` を載せて走らせた最初の実行では、このテストだけが `.venv/bin/jin`（実ツリーの editable）を叩いていた（以後は隔離 venv で再実行）。`PYTHONPATH` に頼る開発者はこの 1 本だけ別環境で走る。
修正案: `os.pathsep.join([stubs, os.environ.get("PYTHONPATH", "")])` で前置する。

### F-W-P2-008 [LOW] confidence 70 — `rmtree(ignore_errors=True)` で後始末の失敗が黙る
`packages/jin-adk/src/jin_adk/runtime.py:118`

一時ディレクトリ（0700・`TMPDIR` 配下）の削除失敗（NFS / Windows のファイルロック / 生成コードがディレクトリ内に書いたもの）は何も出ない。生成コードは `ref` 先の任意コードを走らせるので、ディレクトリ内に残骸を作る余地はある。動作としては正常系・異常系ともに残骸ゼロを実測済み。
修正案: `onexc` で stderr に 1 行出す（`RunError` にはしない）。

### F-W-P2-009 [LOW] confidence 60 — README の `jin build … --out out` が書く `out/` と `t.jsonl` は `.gitignore` に無い
`README.md`（開発コマンド）/ `.gitignore`

リポジトリ直下で README どおりに叩くと未追跡の `out/` と `t.jsonl` が残り、`git add -A` で混入する。CLAUDE.md 側は `/tmp/out` / `/tmp/t.jsonl` を使っているので README と CLAUDE.md で例が揃っていない。

---

## 問題なしと確認した配線

- **uv workspace / lock**: `[manifest].members` は jin-adk / jin-cli / jin-core / jin-workspace の 4 件。`uv.lock` の変更は追加のみ（既存の版は不動）。uv 0.12.9 / 0.12.10 のどちらでも `uv lock --check` EXIT=0、`UV_LOCKED=1 uv sync` で lock は変わらない。
- **import-linter の対象**: 50 files / 139 dependencies。`root_packages` から `jin_adk` を欠くと 36 files / 80 dependencies に減る（M3）。差 14 = jin_adk の 7 モジュール + jin_adk が引き込む外部ルート。
- **console script**: `.venv/bin/jin` / 隔離 venv の `jin` とも build / run を持ち、render / lsp / editor は No such command。`lint-imports` も隔離 venv に入る。
- **wheel**: `jin_adk` の wheel に `templates/agent.py.j2` が同梱される。
- **テスト収集**: 696 収集 = 696 実行。jin-adk 130 / test_build_run 29 / test_adk_version_contract 3。`packages/jin-adk/tests/__init__.py` あり。`__snapshots__` は ignore されない。
- **syrupy**: 欠落・stale とも FAILED。`--snapshot-update` は設定にもワークフローにも無い（CLAUDE.md が手動更新手順として案内するのみ）。
- **スタブ**: `research` は実ツリー・隔離 venv とも import 不可。ruff の対象には入る（58 files）。
- **GitHub Actions**: ci.yml 無変更。`workflow_run` 系・握り潰し系は 0 件。`test_ci_contract.py` 16 本は意味を保つ。
- **一時ディレクトリ**: `TMPDIR` 尊重・0700・例外時も削除・`sys.modules` に `_jin_run_*` は残らない。
- **エスカレーション経路**: `jin run` が `sys.path[0]` に cwd を足す件は CLAUDE.md / README に危険性として明記され、`test_run_adds_cwd_to_sys_path` が固定している（security 軸の範囲なので判定はしない）。

## 復旧の記録

| 対象 | 状態 |
|---|---|
| 実ツリー | 本報告書以外は無変更。`uv.lock` / `pyproject.toml` / `packages/jin-cli/pyproject.toml` の md5 は開始時と一致。`out/` / `t.jsonl` / `dist/` / `jin-render` の残骸なし。レビュー中に `git status` へ増えた `auto-decisions.{json,md}` / `docs/adr/ADR-015〜017` / `docs/pending-decisions.md` は並行する auto-decider の書き込みで、本レビューの操作ではない |
| 隔離コピー `scratchpad/review-wiring` | 各変異後にバックアップから復旧（対象ファイルの md5 は実ツリーと一致）。偽 `jin-render` は削除済み。最終確認: pytest 契約 全緑 / lint-imports 3 kept / `uv lock --check` EXIT=0 |
| 隔離 venv `scratchpad/venv-ci` | `UV_PROJECT_ENVIRONMENT` で分離。実ツリーの `.venv` は未使用・未変更 |
| ダウンロード資材 | `scratchpad/uv129/`（uv 0.12.9 x86_64 linux）/ `scratchpad/wheels/jin_adk-0.1.0-py3-none-any.whl` |
