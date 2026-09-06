# Stage 5 review: wiring — Phase 3 (jin-render)

レビュア: review-p3-wiring / 2026-09-06 / 対象ブランチ `feat/jin-phase3-render`（worktree `.claude/worktrees/jin-phase3-6`・ベース origin/main `32c215e`）。

**開示**: レビュー対象はレビュー開始時点の `git status`（変更 11 / 未追跡 6）。作業中に他のエージェント（auto-decider・他レビュア）が
`auto-decisions.*` / `auto-review.html` / `implement-ledger.md` / `docs/pending-decisions.md` / `docs/adr/ADR-019` / `ADR-020` を書き足しているが、
本レビュアが worktree に書いたのは本ファイル 1 つだけ。注入・変異スクリプトは job tmp（下記）に置いた。

## 実測した環境・コマンド（隔離コピーのパス・件数）

| 項目 | 実測 |
|---|---|
| 隔離コピー | `/home/wisteria/.claude/jobs/e2bcfe94/tmp/review-wiring/tree/`（`packages` / `tests` / `examples` / `pyproject.toml` / `schemas` / `scripts` / `docs` / `delivery` / `.github` / `jin-requirements.md` を複製。`__pycache__` 除外・`PYTHONDONTWRITEBYTECODE=1`・`TMPDIR` はコピー内） |
| import 先の確認 | `jin_render.__file__` / `jin_cli.__file__` / `jin_adk.__file__` がコピー側を指すことを毎回印字 |
| スクリプト | `review-wiring-inject.py`（import-linter 注入 8 件）/ `review-wiring-mutate2.py`（追加変異 M1〜M5）/ `review-wiring-m3a-full.py`（M3a 全件）/ `review-wiring-plan-paths.py`（plan の参照パス実在確認）。いずれも `/home/wisteria/.claude/jobs/e2bcfe94/tmp/` |
| `UV_LOCKED=1 uv sync`（worktree） | EXIT 0（Resolved 79 / Checked 76） |
| `uv lock --check` | EXIT 0 |
| `uv run lint-imports` | 3 kept / 0 broken（Analyzed 59 files, 174 dependencies） |
| `uv run ruff check .` / `ruff format --check .` | All checks passed / 77 files already formatted |
| `uv run pytest`（worktree・`-p no:cacheprovider`） | **1005 passed**, 68 warnings（実装者の記録 1005 と一致） |
| `uv run pytest packages/jin-render/tests`（単独） | 153 passed（4 snapshots）。`jin_adk` を import せずに通る |
| `packages/jin-cli/tests/test_render.py` + `tests/contract/test_render_contract.py` | 34 passed（`jin run --model fake` を実プロセスで回す fixture を含む） |
| `mutate_p3.py`（全件） | **42/42 caught**（41 RED + 1 EXPECT_GREEN）・rc 0・`/tmp/jin-mutate-p3-*` 残骸 0・`/tmp/jin-run-*` 残骸 0。`git status` は実行前後で同一 |
| `MUTATE_ONLY=CLI-overwrite` | `1/1 mutations caught (subset of 42; MUTATE_ONLY=CLI-overwrite)`・rc 0 |
| `MUTATE_ONLY=nope` | `!! MUTATE_ONLY に存在しない変異名: ['nope']`・rc 1（ただし baseline 3.8 s を回した**あと**に出る。F-W-P3-009） |
| import-linter 注入（隔離コピー） | 8 件すべて BROKEN（表は F-W-P3-002 に） |
| `git check-ignore` | `packages/jin-render/src/jin_render/__pycache__/*.pyc` は `.gitignore` で無視される（コミットに混ざらない） |

import-linter 注入の実測（`lint-imports --no-cache`・cwd=コピー・`PYTHONPATH`=コピーの `packages/*/src`）:

| 注入先 | 注入行 | 結果 | BROKEN になった契約 |
|---|---|---|---|
| `jin_render/svg.py` | `import jin_adk` | rc 1 | jin レイヤは一方向 |
| `jin_render/svg.py` | `import google.adk` | rc 1 | jin_core / jin_render は google-adk に依存しない |
| `jin_render/svg.py` | `from jin_cli.resolver import ImportResolver` | rc 1 | 一方向 + 任意コード実行の実装は … に閉じる |
| `jin_render/svg.py` | `from jin_adk.runtime import run_model` | rc 1 | 一方向 + google-adk + 任意コード実行 |
| `jin_render/svg.py` | `import jin_cli` | rc 1 | 一方向 |
| `jin_render/layout.py` | `from google.adk.agents import LlmAgent` | rc 1 | google-adk |
| `jin_adk/trace.py` | `import jin_render` | rc 1 | 一方向（兄弟の逆向きも落ちる = `"jin_adk \| jin_render"` が効いている） |
| `jin_core/pointer.py` | `import jin_render` | rc 1 | 一方向 |

契約そのものは全方向で実際に落ちる。問題は「契約を**静かに緩める**変更を pytest が拾うか」で、下の F-W-P3-001 / 002 がその欠落。

## Findings

### F-W-P3-001 [confidence 95] google-adk 禁止契約の `source_modules` から `jin_render` を外しても全 1005 テストが緑（トリップワイヤ無し）
- 場所: `pyproject.toml:87-92`（`name = "jin_core / jin_render は google-adk に依存しない"` / `source_modules = ["jin_core", "jin_render"]`）、`tests/contract/test_packaging_contract.py:170-185`（`test_resolver_isolation_contract_covers_every_package_but_the_cli`）
- 内容: design.yaml rule 4「jin-render は google-adk に依存しない」を機械で落とすのはこの `source_modules` 1 行だけ。resolver 隔離契約には「`root_packages − {jin_cli}` が全部 `source_modules` に載っていること」を見る網（`test_resolver_isolation_contract_covers_every_package_but_the_cli`）があるが、**google-adk 契約には同型の網が無い**。`test_import_linter_contracts_are_declared` は契約**名**に `google-adk` が含まれることしか見ない。Phase 4 で `jin_lsp` を足すとき、CLAUDE.md チェックリスト 5 の「両方の forbidden 契約に足す」を片方だけやっても何も赤くならない。
- 変異検証: 隔離コピーで `source_modules = ["jin_core"]` に戻し、(a) `test_dependency_direction.py` + `test_packaging_contract.py` → 56 passed、(b) **全スイート → 1005 passed / 0 failed**（`review-wiring-m3a-full.py`）。対照: resolver 契約から `jin_render` を外す（M3b）と `test_resolver_isolation_contract_covers_every_package_but_the_cli` が 1 failed、layers を素朴な直列にする（M3c）と `test_layers_contract_keeps_sibling_packages_in_one_element` が 1 failed。google-adk 側だけ網が無い。
- 提案: `test_packaging_contract.py` に `test_adk_isolation_contract_covers_every_package_but_jin_adk`（または design.yaml の rules から「google-adk … に依存しない」と書かれた主語を拾って期待集合を作る版）を足す。期待集合は `root_packages − {jin_adk, jin_cli}`（jin_cli は jin_adk 経由で ADK に到達するので対象外・rule 6）。合わせて `test_import_linter_contracts_are_declared` の名前検査に依存しない形にする。

### F-W-P3-002 [confidence 90] `test_import_linter_actually_bites_on_a_forbidden_import` は `jin_core` にしか注入しない（Phase 3 で足した `jin_render` 側は pytest 上「宣言してあるだけ」）
- 場所: `tests/contract/test_dependency_direction.py:100-107`（parametrize 3 件・すべて `canonical.py` = jin_core）
- 内容: Phase 3 の変更は forbidden 2 本の `source_modules` と layers の `|` 要素に `jin_render` を足すことだったが、注入テストは 1 件も増えていない（差分はトリップワイヤの parametrize のみ）。上の表のとおり契約は実際に落ちるので実害は無いが、F-W-P3-001 の網が無い状態でこの注入も無いと、`jin_render` に対する契約は「pyproject.toml の文字列が正しいこと」だけに依存する。層契約の**兄弟の逆向き**（`jin_adk → jin_render`）も注入されていない。W-05 の主張「`|` 構文は両方向を BROKEN にする」は reviewer 実測のコメントとしてしか残っていない。
- 変異検証: 本レビューの注入 8 件（上表）が代替。既存 parametrize では jin_render を対象にしたものが 0 件であることを読んで確認。
- 提案: parametrize を `(package, target_file, injected, keyword)` に広げ、少なくとも `("jin_render", "svg.py", "import google.adk", "google-adk")` / `("jin_render", "svg.py", "import jin_adk", "一方向")` / `("jin_adk", "trace.py", "import jin_render", "一方向")` / `("jin_render", "svg.py", "from jin_cli.resolver import ImportResolver", "jin_cli.resolver")` の 4 件を足す。`copy_sources` は既に全パッケージを写しているので `target = tmp_path / package / target_file` にするだけ。

### F-W-P3-003 [confidence 90] `jin render -o <存在しないディレクトリ>/x.svg` が「書き込む直前にファイルが消えました」と言う
- 場所: `packages/jin-cli/src/jin_cli/main.py:257-263`（`_WRITE_ERRNO_HINTS[errno.ENOENT]`）、`main.py:374-378`（`tempfile.mkstemp(dir=path.parent)` の `OSError` → `_classify_write_failure`）、`main.py:889-892`（`_write_svg`）
- 内容: `_WRITE_ERRNO_HINTS` の ENOENT 文言は `fmt`（対象ファイルが**在る**前提で、その親ディレクトリも在る）のために書かれた。`allow_create=True` の `jin render -o` ではこの前提が崩れ、`mkstemp(dir=path.parent)` が親ディレクトリ不在で ENOENT を投げると、存在したことのないファイルについて「消えました」と出る。exit 1 なので fail-open ではないが、利用者が直すべきこと（ディレクトリを作る）が伝わらない。`docs/spec/layout.md` §8 / README の `jin render` 節にも `-o` の親ディレクトリの扱いは書かれていない。
- 再現: `uv run jin render examples/pipeline/pipeline.jin -o <tmp>/nope/out.svg` → `…/nope/out.svg: 書き込む直前にファイルが消えました（No such file or directory）` / rc 1（実測）。
- 変異検証: 該当無し（文言の欠陥。テストも無い）。
- 提案: `_write_svg` で `path.parent.is_dir()` を先に見て `WriteRefused("出力先のディレクトリがありません: <parent>")` を返す（`jin build` の `write_project` が `--out` を `mkdir` する流儀に合わせて**作らない**のが安全側。作るなら README に書く）。または `_classify_write_failure` に `allow_create` を渡して ENOENT の文言を分岐する。`test_render.py` に「親ディレクトリ不在 → exit 1 + 文言」を 1 本足す。

### F-W-P3-004 [confidence 85] `test_render_contract.py::live_trace` が開発者の `PYTHONPATH` を**上書き**する（F-W-P2-007 の再発）。mutate_p3 配下ではこのサブプロセスがコピーではなく実ツリーの `jin_cli` / `jin_adk` を読む
- 場所: `tests/contract/test_render_contract.py:106`（`env={**os.environ, "PYTHONPATH": str(STUBS)}`）。対照: `tests/contract/test_cli_contract.py:257-260`（F-W-P2-007 で「前置」に直した `_run`）
- 内容: 同じリポジトリの `_run` が Phase 2 修正ラウンドで「開発者の既存 PYTHONPATH を捨てない」と直した箇所と同型。実害 2 つ: (1) `PYTHONPATH` 経由で環境を組む利用者（ブリーフの `PYTHONPATH=<copy>/packages/*/src … -m pytest` 方式・`mutate_p3.py` の `_env`）では、`jin run` サブプロセスだけが**実ツリーの editable install** に解決される。`mutate_p3.py` は `jin_render.__file__` / `jin_cli.__file__` がコピーを指すことを印字して「隔離」を主張するが、`T_RENDER_CONTRACT` を含む 5 変異（`CONTRACT-core-no-pointer` / `CONTRACT-tenth-kind` / `OVL-exact-only` / `OVL-no-referent` / `OVL-no-ref-attribute`）と baseline では `jin run` が実ツリーで走る。`jin_adk` を変異させる項目が無いので結果には効いていないが、Phase 4 以降で trace 側を変異させると**変異が効かないまま緑**になる。(2) `pipeline.jin` は `ref` を持たないので `STUBS` 自体が不要（researcher 版を足したときに初めて要る）。
- 変異検証: `mutate_p3.py` 実行時の `_env` と fixture の `env` を読んで確認（`PYTHONPATH` が `STUBS` のみになる）。実行結果への影響は無し（42/42）。
- 提案: `test_cli_contract._run` と同じく前置にする（`os.pathsep.join([STUBS, os.environ.get("PYTHONPATH", "")])`）。共通ヘルパを `tests/conftest.py` に 1 つ置いて 2 ファイルから使うと再発しない。

### F-W-P3-005 [confidence 90] `test_render.py::test_the_help_lists_render` は `render` コマンドが無くても緑（偽 green）
- 場所: `packages/jin-cli/tests/test_render.py:216-218`、`packages/jin-cli/src/jin_cli/main.py:109-113`（app の `help=` に `… / run / render）` と書いてある）
- 内容: `jin --help` の出力には Typer の Commands パネルだけでなく app の説明文も含まれ、そこに `render` の語がある。よって `@app.command()` を外して**サブコマンドが消えても**このテストは通る。
- 変異検証（M1・隔離コピー）: `render` の `@app.command()` を削除 → `-k the_help_lists_render` **1 passed**（緑のまま）。同じ変異でファイル全体は 15 failed / 9 passed なので配線抜けそのものは他のテストが拾う。severity は低いが、このテストは「何も検査していない」。
- 提案: `runner.invoke(app, ["render", "--help"]).exit_code == 0` に替える、または `--help` 出力を `Commands` 以降で切ってから `render` を探す。

### F-W-P3-006 [confidence 90] jin-render のテストが `jin_adk` を import しても何も落ちない。conftest の docstring「packaging contract はテストも走査する」は事実と違う
- 場所: `packages/jin-render/tests/conftest.py:3-4`（`test_every_package_declares_the_jin_packages_it_imports` は「テストも走査する」と主張）、`tests/contract/test_packaging_contract.py:334`（`_jin_imports(package / "src" / module)` = **src だけ**）
- 内容: design.yaml rule 4 / ADR-003 で「jin-render のパッケージテストは jin_core と標準ライブラリしか見ない」と決めているが、それを落とす網は無い。docstring は存在しない網を根拠にしている（記録と実物の不一致）。
- 変異検証（M2・隔離コピー）: `packages/jin-render/tests/test_svg.py` に `import jin_adk` を注入 → `test_packaging_contract.py` + `test_dependency_direction.py` **56 passed**（緑のまま）。
- 提案: `_jin_imports` の走査対象に `package / "tests"` を足し、jin-render / jin-core の tests については `jin_adk` / `jin_cli` を禁止（許可集合を `pyproject.toml` の `dependencies` + 自分自身 + `tests`（共有 conftest）に限る）。conftest の docstring は網を足すまで「守っているのは規律のみ」に直す。

### F-W-P3-007 [confidence 70] `jin render a.jin -o a.jin --force` が入力の `.jin` を SVG で上書きする
- 場所: `packages/jin-cli/src/jin_cli/main.py:876-892`（`_write_svg` は `out` と `file` の同一性を見ない）
- 再現: `pipeline.jin` を tmp に複製 → `jin render self.jin -o self.jin --force` → rc 0・`self.jin` の先頭が `<svg …` になる（実測）。
- 内容: `--force` を明示しているので契約違反ではないが、`fmt` が「書き換えるのは正準形だけ」と守っているファイルを `render` が壊せる。`jin build` は `--out` がディレクトリなのでこの経路が無い。`-o` を `.jin` と同名にするのは補完ミスで起こりうる。
- 提案: `_write_svg` の前で `out.resolve() == file.resolve()` なら `WriteRefused("入力の .jin と同じパスには書けません")`（1 行）。

### F-W-P3-008 [confidence 50] 成功メッセージ `書き出しました: {out}` が `_safe` を通らない（`build` と同型・既存パターンの踏襲）
- 場所: `packages/jin-cli/src/jin_cli/main.py:953`（`render`）、`main.py:665`（`build`・同じ）
- 内容: エラー側は `_safe(str(out))` を通しているが成功側は生。`typer.echo` は非 tty では ANSI を落とす（実測: パイプ経由では `aRED.svg` になった）が、tty では argv 由来の制御文字がそのまま端末に出る。`build` も同じなので Phase 3 固有ではない。
- 提案: 両方とも `_safe(str(out))` にそろえる。

### F-W-P3-009 [confidence 40] `MUTATE_ONLY` の typo 検査がコピー作成 + baseline（約 4 s）の**あと**に走る
- 場所: `delivery/20260904-1445-jin/phase3-mutations/mutate_p3.py:main()`（`baseline` → `only` の順）
- 内容: `MUTATE_ONLY=nope` は rc 1 と `!! 存在しない変異名` を出す（F-W-P2-203 の要求は満たす）が、先に baseline 210 件を回してから気づく。使い勝手のみ。
- 提案: `only` の検査を `copy_tree` より前に移す。

### F-W-P3-010 [confidence 35] CI に `jin render` を別プロセスで叩くスモークが無い（必須ではない・提案）
- 場所: `.github/workflows/ci.yml`（`jin check examples` / `jin fmt --check examples` はあるが `jin render` は無い）
- 内容: プロセス境界をまたぐ検査は `tests/contract/test_render_contract.py::test_the_cli_and_the_library_produce_the_same_svg`（researcher 1 本）と `test_determinism.py`（`PYTHONHASHSEED` 別プロセス）が担っており、`uv run pytest` の中で走る。CI の**ステップ**としては無いので、`jin check examples` と同じ「examples 2 本を render して exit 0」を 1 行足すとログで見える。`test_ci_contract.MINIMUM_UV_COMMANDS = 9` は足すなら 10 に上げる。
- 提案: 任意。足す場合は `uv run jin render examples/researcher/researcher.jin > /dev/null && uv run jin render examples/pipeline/pipeline.jin > /dev/null`。

### F-W-P3-011 [confidence 40] `-o` がディレクトリのとき `--force` を付けると `Is a directory` だけが出る
- 場所: `main.py:390`（`os.replace(temporary, path)` の `IsADirectoryError` → `_classify_write_failure` の strerror 素通し）
- 再現: `-o <dir>` → `既にあります。上書きするなら --force を付けてください`（rc 1）。`-o <dir> --force` → `<dir>: Is a directory`（rc 1）。1 回目の助言に従うと 2 回目で英語の strerror だけになる。
- 提案: `_write_svg` で `path.is_dir()` を先に見て「出力先はファイルのパスです（ディレクトリが指定されました）」を出す。

## 変異で緑のままだったテスト（偽 green の候補）

| 変異 | 回したテスト | 結果 | 対応 finding |
|---|---|---|---|
| M3a: google-adk 契約の `source_modules` から `jin_render` を外す | **全スイート 1005 件** | 1005 passed / 0 failed | F-W-P3-001 |
| M1: `render` の `@app.command()` を外す | `test_render.py -k the_help_lists_render` | 1 passed | F-W-P3-005（同じ変異でファイル全体は 15 failed。配線抜け自体は拾われる） |
| M2: `packages/jin-render/tests/test_svg.py` に `import jin_adk` | `test_packaging_contract.py` + `test_dependency_direction.py` | 56 passed | F-W-P3-006 |

赤くなった対照（正しく効いている網）: M3b（resolver 契約から `jin_render` を外す）→ 1 failed / M3c（layers を素朴な直列）→ 1 failed /
M4（`_write_svg` が `_write_atomically` を経ずに `write_text`）→ 1 failed（`test_render.py` + `test_guard_claims.py`）/
M5（`allow_create` の枝を常に通す = `fmt` の `copymode` を殺す）→ `test_cli.py` + `test_render.py -k "mode or perm or fmt"` で 1 failed（`fmt` のモード引き継ぎは壊れない）。
`mutate_p3.py` 42 件は全件期待どおり（`CLI-follow-symlink-upfront-only` の GREEN は二層目 `Path(path).is_symlink()` が守っていることを `CLI-follow-symlink-both` の RED で裏取り済み）。

## 実装者の記録（notes / conformance / plan / layout.md）と実物の不一致

- **不一致**: `packages/jin-render/tests/conftest.py:3-4` の「`test_every_package_declares_the_jin_packages_it_imports` はテストも走査する」。実物は `src/` だけを走査する（F-W-P3-006）。
- **不一致（弱）**: `mutate_p3.py` docstring と notes P3-1 の「実ツリー不変・隔離コピー上で変異」は書き込みについては正しいが、`test_render_contract.py::live_trace` の `jin run` サブプロセスは実ツリーの editable install を読む（F-W-P3-004）。「実ツリーを 1 バイトも書き換えない」は成立、「全部コピー側で走る」は不成立。
- **一致を確認**: notes P3-5 の 8 ゲート（`UV_LOCKED=1 uv sync` EXIT 0 / ruff 2 本 / pytest **1005 passed** / lint-imports **3 kept** / schema diff 無し / check examples / fmt --check examples）、変異 **42/42**（`MUTATIONS` の要素数 42 と一致）、SVG スナップショット 4 本、`uv.lock` の差分が `jin-render` の追加だけ（新しい外部依存なし）、`packages/jin-cli/pyproject.toml` の `dependencies` / `[tool.uv.sources]`、ルート `pyproject.toml` の 5 箇所、`packages/jin-render/tests/__init__.py`、CLAUDE.md のチェックリスト 7 項目の記述、`implementation-plan.json` が参照するパス（127 件・P3 分は全部実在）。
- **記録側の不足（欠陥ではない）**: `tests/fixtures/traces/pipeline-fake.jsonl` の生成コマンドは `phase3-handoff.md` §4 と CLAUDE.md の開発コマンドにあり、`test_the_committed_fixture_matches_a_live_run` が `ts` 以外の 5 フィールドで実行結果と突合するので再現性は機械で担保されている。fixture 自体に出典を書く場所（JSONL にコメントは書けない）が無いので、CLAUDE.md の説明行（`jin run --model fake の出力（11 行）`）に「`ts` は実行ごとに変わる・突合は contract test」を一言足すと親切。
