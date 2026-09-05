# 再レビュー（Phase 2 修正ラウンド 1）— wiring

実測日: 2026-09-05 / レビュアー: review-wiring-p2 / ブランチ `feat/jin-phase2-adk`（未コミットの作業ツリー）
基準状態（隔離コピーを作り直し・uv 0.12.9 実バイナリ + 隔離 venv `UV_PROJECT_ENVIRONMENT`・`UV_LOCKED=1`）:
`uv lock --check` EXIT=0 / `uv sync` EXIT=0 / `lint-imports` **Analyzed 51 files, 143 dependencies / 3 kept** / ruff 59 files /
`uv run pytest` **770 passed**（2 snapshots passed）/ スキーマドリフト・`jin check`・`jin fmt --check examples` とも rc=0。
`uv.lock` は前回レビュー開始時と **md5 一致**（`3e23308b…`。修正ラウンドで lock は 1 バイトも動いていない）。

**実装者の対応表（P2-R1.1 A-8 / A-9・P2-R1.7）は「どこを直したか」の索引としてだけ使い、判定はすべて下記の実測に基づく。**
破壊的な変異は隔離コピー（`scratchpad/review-wiring`）でのみ行い、各変異後にバックアップから復旧して実ツリーと md5 一致を確認した。
実ツリーへの書き込みは本報告書 1 件のみ。

## Summary

- **確認対象 8 件: defect-gone 7 件（001 / 002 / 003 / 005 / 007 / 008 / 009）/ 部分残存 1 件（004）**
- **新規: 3 件（F-W-P2-101 low・修正で持ち込まれた / F-W-P2-102 low・観察 / F-W-P2-103 low・Phase 1 からの既存事項）。CI を落とすもの・マージを止めるものは無い。**
- 前回の注入表 M1〜M12 を再実行: **全件、名指しのテストで赤**。前回素通りだった **M7（jin-cli 自身の pyproject の依存欠落）** と
  **M12b（`__import__` だけ）** が新テストで赤になり、**M9（jin_core → jin_adk）** は生の網 `test_jin_core_imports_no_other_jin_package` が拾う。
- forbidden 契約（`任意コード実行の実装は jin_cli.resolver と jin_adk.runtime に閉じる`）: `jin_core → jin_adk.runtime` は **BROKEN**、
  `jin_adk` 内部からの `jin_adk.runtime` import は **KEPT**（import-linter の仕様: source と forbidden が重なるペアは検査から外れる・下記 §3）。
  偽 `jin_lsp` を足した Phase 4 の形でも `jin_lsp → jin_adk.runtime`（直接）と `jin_lsp → jin_adk.codegen → jin_adk → jin_adk.runtime`（間接）の**両方が BROKEN**。
- `mutate_p2.py`: 実ツリーは **バイト同一**（`git status` の md5・対象 6 ファイルの md5・`__pycache__` 0 件が前後で一致）。コピー側の
  `jin_adk.__file__` を印字してから走る。59/59 caught。ただし **1 回走るたびに `/tmp/jin-run-*` を 3 個残す**（F-W-P2-101）。
- cwd シャドウの新テストは CI 条件（`PYTHONPATH` 未設定・cwd = ルート）で緑、`insert(0, cwd)` に戻すと**別プロセス版と in-process 版の 2 本が赤**。
  ただし ADK が `authlib` を遅延 import する実装事実に依存する（F-W-P2-102・観察）。

---

## 1. finding 別の判定

| ID | 判定 | 根拠（実行したコマンドと出力） |
|---|---|---|
| **F-W-P2-001** jin-cli 自身の pyproject の依存欠落を pytest が拾わない | **defect-gone** | M7（`dependencies` と `[tool.uv.sources]` から `jin-adk` を除く）→ **`test_every_package_declares_the_jin_packages_it_imports[jin-cli]` FAILED**。M7b（`sources` だけ欠く）→ 同テストの `sources` 側 assert で FAILED。`uv lock --check` も EXIT=1（従来どおり）。副次: M8 / M10 で `jin_adk` が `jin_cli` を import する注入も同テストの `[jin-adk]` が拾う（`jin_cli` は `jin-adk` の依存に無いため）。CLAUDE.md チェックリストは 7 項目になり、`test_claude_md_has_the_package_addition_checklist` の対象語は据え置き（文言の存在確認のみ・従来どおり） |
| **F-W-P2-002** 実ツリーを書き換える変異スクリプトが開発コマンドに載った | **defect-gone**（新規 F-W-P2-101 あり） | 実ツリーで `uv run python delivery/…/mutate_p2.py` を 2 回実行。前後で `git status --short` の md5（`1a891571…`）と `uv.lock` / `pyproject.toml` / `jin_adk/*.py` / `jin_cli/main.py` の md5（`dbd309fa…`）が**一致**、`packages` / `tests` の `__pycache__` は 0 → 0。起動時に `imports from: /tmp/jin-mutate-…/packages/jin-adk/src/jin_adk/__init__.py` を印字し、コピーを指さなければ `return 2` で中止する分岐がある。59/59 caught・所要 59 秒。コピー `/tmp/jin-mutate-*` は終了後に残らない（0 件）。CLAUDE.md の開発コマンドとして残すことは**妥当**（実ツリーを触らない・`uv run` なので stale lock の扱いは他の開発コマンドと同じ）。残る 1 点は下記 F-W-P2-101 |
| **F-W-P2-003** jin_core → jin_adk の生の網が無い | **defect-gone** | M9（`jin_core/canonical.py` に `import jin_adk`）→ **`test_jin_core_imports_no_other_jin_package` FAILED**（メッセージ `…/canonical.py: jin_adk`）+ `test_every_package_declares_the_jin_packages_it_imports[jin-core]` + import-linter 系 2 本。F1（`from jin_adk.runtime import run_model`）でも同じ 4 本。AST ベースで `jin_*` のうち `jin_core` 以外を全部見るので Phase 3 / 4 の `jin_render` / `jin_lsp` にも効く |
| **F-W-P2-004** `build-errors/` fixture が正準形契約と CI の fmt チェックの外 | **部分残存**（前提の誤りは前回レビュー側） | implementer は前回の修正案どおり `conftest.formattable_paths` に `build-errors` を加えた（`formattable_paths` を受ける round-trip テスト **9 本**の対象になる）。**しかし fixture を非正準にしても赤くならない**: `two_out_states.jin` の末尾に空行 2 つを足して `tests/contract` + `tests/spec` を実行 → **191 passed（全緑）**、同じファイルに `jin fmt --check` → rc=1。原因は、前回の finding が「round-trip 契約はディスク上の正準形を検査している」と**誤って前提していた**こと。実際には round-trip 契約は `dumps(model)` と `dumps(model(dumps(model)))` を比べるだけで**ファイルのバイト列を一度も見ていない**（F-W-P2-103）。`tests/fixtures/errors/` も Phase 1 から同じく素通り（JIN030 fixture で実測）。`examples/` だけは `test_fmt_check_on_examples_exits_zero` と `test_example_ends_with_single_newline` が守る（同じ変異で 2 本 FAILED を実測）。ci.yml の `jin fmt --check examples`（:89）も未変更。**修正案**: `test_fmt_check_on_examples_exits_zero` を `examples` + `tests/fixtures/build-errors` + `tests/fixtures/errors` の formattable 分に広げる（`jin fmt --check` はディレクトリを受けるので 1 行ずつ）。severity は low のまま（現物は 14 本とも正準形） |
| **F-W-P2-005** importlib 検査の盲点（`__import__`） | **defect-gone** | `dynamic_import_sites`（AST）に置き換わり、M11 `import importlib` / M12 `from importlib import … as` / **M12b `__import__('os')`** / M12c `exec('1')` / M12d `import runpy` / M12e `eval('1')` の 6 形すべてで **`test_importlib_is_confined_to_the_cli_resolver_and_jin_run` FAILED**。検出器の非空虚性は `test_dynamic_import_detector_sees_each_form` 5 パラメータ（`import os` では空になることも同テストで固定）。expected は `runtime.py` / `resolver.py` の 2 モジュールで厳密一致のまま |
| **F-W-P2-007** `_run` の `PYTHONPATH` が上書き | **defect-gone** | `test_cli_contract.py:29-31` が既存 `PYTHONPATH` を後ろに連結。`PYTHONPATH=/nonexistent/x` を付けて `test_run_with_fake_model_exits_zero_in_a_real_process[researcher/pipeline]` → **2 passed**（スタブは前置で見つかり、既存値も落ちない: 連結結果 `stubs:/nonexistent/x` を確認）。`PYTHONPATH` 未設定（CI 条件）でも従来どおり緑 |
| **F-W-P2-008** `rmtree(ignore_errors=True)` で後始末失敗が黙る | **defect-gone** | `runtime.py:128` が `shutil.rmtree(directory, onexc=_report_cleanup_failure)`（stderr に 1 行・`RunError` にしない）。`onexc` は Python 3.12+ で `requires-python >= 3.12` と整合。固定するテスト `test_cleanup_failure_is_reported_on_stderr_not_swallowed`（0500 で消せなくして stderr を見る）は 770 に含まれ緑、`mutate_p2.py` の `RUN-cleanup-silent`（`ignore_errors=True` に戻す）は RED を実測 |
| **F-W-P2-009** README の `out/` / `t.jsonl` が gitignore に無い | **defect-gone** | README の例は `--out /tmp/out` / `--trace /tmp/t.jsonl` に変更（CLAUDE.md と一致）。`.gitignore` は無変更だが、文書どおりに叩いてもリポジトリ内に何も残らないので実害は消えた。`out/` を ignore に足すかは任意 |

## 2. 注入表の再実行（M1〜M13 + 新規）

隔離コピー・隔離 venv・`PYTHONPATH` 未設定。対象は `tests/contract/test_packaging_contract.py` / `test_dependency_direction.py` / `test_adk_version_contract.py`。
注入は `from __future__ import annotations` の直後に行い、前回混入した SyntaxError の副作用を排除した。

| ID | 壊した箇所 | 名指しで赤くなったテスト | 前回との差 |
|---|---|---|---|
| M1 | root `dependencies` から `jin-adk` | `test_every_package_is_declared_in_the_workspace[jin-adk]` | 同じ |
| M2 | root `[tool.uv.sources]` から `jin-adk` | 同上（`uv lock --check` EXIT=2） | 同じ |
| M3 | `root_packages` から `jin_adk` | `test_every_package_is_a_root_package[jin-adk]` + import-linter 系 4 本。`lint-imports` 自体が rc=1: `Invalid forbidden module jin_adk.runtime: subpackages of external packages are not valid.`（root から外れた `jin_adk` は外部パッケージ扱いになり、その下位 `jin_adk.runtime` を forbidden に書けない・`forbidden.py:233-238`） | **強化**（前回は lint-imports が 36 files / 3 kept で素通り。forbidden に `jin_adk.runtime` を足したことで root_packages の欠落が import-linter 自身のエラーになる） |
| M4 | layers から `jin_adk` | `test_every_package_appears_in_the_layers_contract[jin-adk]` | 同じ |
| M5 | forbidden `source_modules` から `jin_adk` | `test_resolver_isolation_contract_covers_every_package_but_the_cli` | 同じ |
| M6 | `jin-adk/tests/__init__.py` 削除 | `test_every_package_test_directory_is_a_package[jin-adk]` | 同じ |
| **M7** | `jin-cli/pyproject.toml` から `jin-adk` | **`test_every_package_declares_the_jin_packages_it_imports[jin-cli]`** | **素通り → 赤** |
| M7b | 同 `[tool.uv.sources]` だけ欠く | 同上 | 新規 |
| M8 | `jin_adk/codegen.py` ← `jin_cli.main` | `test_jin_adk_does_not_import_jin_cli_or_later_packages` / import-linter 系 2 本 / `…declares_the_jin_packages_it_imports[jin-adk]`。lint-imports: layers + forbidden BROKEN | +1 本 |
| **M9** | `jin_core/canonical.py` ← `import jin_adk` | **`test_jin_core_imports_no_other_jin_package`** / `…declares…[jin-core]` / import-linter 系 2 本 | **生の網が拾うようになった** |
| M10 | `jin_adk/runtime.py` ← `jin_cli.resolver` | M8 と同じ 4 本。lint-imports: layers + forbidden BROKEN（`jin_adk.runtime -> jin_cli.resolver`） | +1 本 |
| M11 / M12 | `import importlib` / `from importlib import … as` | `test_importlib_is_confined_to_the_cli_resolver_and_jin_run` | 同じ（改名） |
| **M12b** | `__import__('os')` だけ | **同上** | **素通り → 赤** |
| M12c / d / e | `exec('1')` / `import runpy` / `eval('1')` | 同上 | 新規 |
| M13 | 偽 `jin-render` + 素朴な直列 | 前回実測済み（`test_layers_contract_keeps_sibling_packages_in_one_element`）。本ラウンドで該当コードに変更なし | 再実行せず |

## 3. forbidden 契約の改名と `jin_adk.runtime` の追加

`source_modules = ["jin_core", "jin_adk"]` / `forbidden_modules = ["jin_cli.resolver", "jin_adk.runtime"]`。

**`jin_adk` 自身が `jin_adk.runtime` を import しても契約に掛からない理由**（import-linter 2.14 `contracts/forbidden.py:44-48` の docstring）:
> Where the source and forbidden modules overlap (the same module is in both, or one is a subpackage containing the other),
> the source module is not forbidden from importing the forbidden module; such pairs are skipped.

つまり `(jin_adk, jin_adk.runtime)` のペアは**検査そのものから外れる**（緩められているのではなく、そもそも対象外）。
`(jin_core, jin_adk.runtime)` は重ならないので検査される。実測:

| ID | 注入 | lint-imports | pytest |
|---|---|---|---|
| F1 | `jin_core/canonical.py` ← `from jin_adk.runtime import run_model` | **3 契約とも BROKEN**（forbidden: `jin_core.canonical -> jin_adk.runtime`。google-adk 契約も `jin_adk.runtime -> google` の間接鎖で落ちる） | 4 本（§2 M9 と同じ） |
| F2 | `jin_adk/codegen.py` ← `from jin_adk.runtime import RunError` | **3 kept**（対象外・設計どおり） | 契約テストは緑（`test_test_fixtures_and_cli_discover_the_same_files` の赤は runtime→codegen の循環 import による注入側の副作用） |
| F3 | `jin_adk/__init__.py` ← `from jin_adk.runtime import run_model` | **3 kept** | 全緑 |
| L0 | 偽 `packages/jin-lsp` を root_packages / layers に足し **source_modules に足し忘れ** | — | **`test_resolver_isolation_contract_covers_every_package_but_the_cli` FAILED** |
| L1 | 同・6 項目充足・無違反 | 3 kept（52 files） | 全緑 |
| L2 | `jin_lsp` ← `jin_adk.runtime`（直接） | **forbidden BROKEN**（`jin_lsp -> jin_adk.runtime`） | — |
| L3 | `jin_lsp` ← `jin_cli.resolver` | layers + forbidden BROKEN | — |
| L4 | `jin_lsp` ← `jin_adk.codegen` | 3 kept（許される経路・design.yaml rule 5 と整合） | — |
| **L4 + F3** | `jin_lsp` ← `jin_adk.codegen` かつ `jin_adk/__init__.py` ← `jin_adk.runtime` | **forbidden BROKEN**: `jin_lsp -> jin_adk.codegen (l.3)` → `jin_adk.codegen -> jin_adk (l.60)` → `jin_adk -> jin_adk.runtime (l.25)` の**間接鎖を報告** | — |

結論: Phase 4 で `jin_lsp` を `source_modules` に足せば（足し忘れは L0 のテストが拾う）、`jin_lsp` から `jin_adk.runtime` へは直接・間接とも到達できない形になっている。
`jin_adk/__init__.py` が将来 `run_model` を再エクスポートしても、それだけでは緑（F3）だが、`jin_lsp` が `jin_adk` のどこかを import した瞬間に間接鎖で赤くなる（L4+F3）。
契約名を参照する `test_import_linter_contracts_are_declared` は `"jin_cli.resolver" in n and "jin_adk.runtime" in n` に更新済み、注入テストは 3 パラメータ（google / `jin_cli.resolver` / `jin_adk.runtime`）で BROKEN になった契約名まで照合する。

## 4. cwd シャドウの新テスト（`test_cwd_cannot_shadow_an_installed_package_in_a_real_process`）

- CI 条件（`PYTHONPATH` 未設定・cwd = リポジトリルート・隔離 venv）: `-k "cwd_cannot_shadow or run_with_fake_model"` → **3 passed**。テスト自身が `cwd=tmp_path`（`authlib/__init__.py` を置いた一時ディレクトリ）で `jin` を起動するので、pytest の cwd や `PYTHONPATH` には依存しない。`_run(cwd=…)` の追加で `JIN` は `sys.executable` の隣を指したまま（隔離 venv の `jin` を叩いたことを `jin_adk.__file__` で確認）。
- **噛むこと**: `main.py:733` を `sys.path.insert(0, cwd)` に戻す → **`test_cwd_cannot_shadow_an_installed_package_in_a_real_process` と `test_run_adds_cwd_to_sys_path` の 2 本が FAILED**。`mutate_p2.py` の `CLI-cwd-first` も RED。
- 観察（F-W-P2-102）: `import jin_cli.main` / `import google.adk.runners` の時点で `authlib` は `sys.modules` に**無い**（実測 False / False）ので、現状このテストは実行時の遅延 import を確かに捉えている。google-adk が `authlib` を eager import する版に上がると、`insert(0)` に戻しても cwd の `authlib` は読まれず**テストが黙って空振りする**（`test_adk_version_contract` が 2.8.0 に固定しているので今は起きない）。

## 5. 修正が新たに持ち込んだ配線の問題

### F-W-P2-101 [LOW] confidence 95 — `mutate_p2.py` は 1 回走るごとに `/tmp/jin-run-*` を 3 個残す
`delivery/20260904-1445-jin/phase2-mutations/mutate_p2.py:216-229`（`RUN-no-cleanup` / `RUN-cleanup-silent`）と `_env()`（`TMPDIR` を設定しない）

後始末を壊す変異は**設計どおり**一時ディレクトリを残すが、`TMPDIR` がコピー内へ向けられていないため、残骸は**システムの `/tmp`** に落ちる。
実測: `/tmp/jin-run-*` は実行前 32 個 → 実行後 **35 個**（増分 3 つの mtime は実行時刻と一致・中身は `Pipeline/`・0700）。
本日 19:23〜21:16 の 18 クラスタ・35 個が溜まっており、implementer / 各 reviewer の実行分と一致する。実ツリーは無傷なので F-W-P2-002 の判定は変えないが、
「隔離コピー上で変異する・実ツリーは 1 バイトも書き換えない」という docstring の約束のすぐ外側で、利用者の `/tmp` を汚す。
修正案: `_env()` で `TMPDIR=str(copy / "tmp")` を渡す（`copy` は `finally` で `rmtree` されるので残骸も一緒に消える）。`test_cleanup_failure_is_reported_on_stderr_not_swallowed` 自身は `finally` で消すので、本体テストは汚さない。

### F-W-P2-102 [LOW] confidence 60 — cwd シャドウ検査は ADK の `authlib` 遅延 import に依存する（観察）
`tests/contract/test_cli_contract.py:161-183`

上記 §4。今は正しく噛む。google-adk の版を上げるときに `authlib` が eager import になっていないか（`python -c "import google.adk.runners, sys; print('authlib' in sys.modules)"` が False のまま）を `adk-api-probe.md` の取り直し項目に足しておくと、空振りに気づける。
あるいは cwd に置く名前を「ADK が import する実在パッケージ」ではなく「どこにも無い名前を `ref` で import する `.jin`」に変えれば ADK の実装に依存しなくなるが、そのときは `append` でも cwd から解決されるので `insert(0)` との差が出ない。現行の形が最も直接的なので、記録のみ。

### F-W-P2-103 [LOW] confidence 90 — round-trip 契約はディスク上の正準形を検査していない（docstring と実装の不一致・Phase 1 からの既存事項）
`tests/contract/test_canonical_contract.py:81-86`（`test_text_roundtrip_is_byte_identical`）

docstring は「ファイル → モデル → ファイルがバイト同一（正準形のファイルに限る）」だが、実装は `canonical = dumps(check_file(path).model)` と
`dumps(check_text(canonical).model)` を比べており、`path.read_bytes()` は登場しない。よって `formattable_paths` に何を足しても
「その fixture が正準形で置かれているか」は検査されない（`examples/` は別の 2 本が守る・`errors/` と `build-errors/` は誰も守らない）。
F-W-P2-004 の部分残存の根本原因。修正案は F-W-P2-004 と同じ（`jin fmt --check` を fixture ディレクトリにも掛ける）か、
このテストに `path.read_text(encoding="utf-8") == canonical` の 1 行を足して docstring どおりにする。

### その他（欠陥なし・確認事項）
- `uv.lock`: 修正ラウンドで無変更（md5 `3e23308b…` 一致）。`uv lock --check`（0.12.9 / 0.12.10）EXIT=0。
- syrupy: `packages/jin-adk/tests/__snapshots__/test_codegen.ambr` は更新されている（md5 `a01d5be0…` → `31623d63…`。テンプレート変更に追従）。`git check-ignore` に掛からず、`packages/jin-adk/` ごと未追跡なので `git add` で一緒に入る。`2 snapshots passed`。
- `.github/workflows/ci.yml`: 無変更（`git diff --stat -- .github` 空）。`test_ci_contract.py` 16 本・`MINIMUM_UV_COMMANDS = 9` は現状と一致。
- 新設 `tests/contract/test_guard_claims.py` は 770 に含まれて収集されている（`packages/*/src` を走査する形で、モジュールを列挙しない）。
- `test_every_package_declares_the_jin_packages_it_imports` の依存名の切り出し（`split("[")…split("=")`）は `jin-core` / `jin-adk` の素の名前には十分。将来 `jin-adk[extra]>=0.2` のような指定でも先頭語だけ取るので誤検知しない。

## 6. 復旧の記録

| 対象 | 状態 |
|---|---|
| 実ツリー | 本報告書以外は無変更。`mutate_p2.py` 2 回実行の前後で `git status` / 対象ファイルの md5 一致。`__pycache__` 0 件のまま |
| 隔離コピー `scratchpad/review-wiring` | 作り直し後、各変異はバックアップから復旧（対象ファイルの md5 は実ツリーと一致）。偽 `jin-lsp` は削除済み。最終確認: 契約テスト全緑 / `lint-imports` 3 kept（51 files）/ `uv lock --check` EXIT=0 |
| 隔離 venv `scratchpad/venv-ci` | 作り直し（uv 0.12.9・`UV_PROJECT_ENVIRONMENT`）。実ツリーの `.venv` は未使用 |
| `/tmp/jin-run-*` | 私の `mutate_p2.py` 実行で増えた 3 個を含め **35 個が残っている**（F-W-P2-101 の証拠として未削除。`rm -rf /tmp/jin-run-*` で消せる・すべて所有者 wisteria・0700） |
