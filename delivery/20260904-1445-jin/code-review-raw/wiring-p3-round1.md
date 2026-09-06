# Stage 5 再レビュー: wiring — Phase 3 (jin-render) 修正ラウンド 1

レビュア: rereview-p3-wiring / 2026-09-06 / 対象ブランチ `feat/jin-phase3-render`（worktree `.claude/worktrees/jin-phase3-6`・ベース origin/main `32c215e`）。
入力: `code-review-raw/wiring-p3.md`（F-W-P3-001〜011）/ `phase3-fix-round-1-instructions.md` / `implementation-notes.md` P3-R1（R1.1 / R1.2 / R1.6）。
worktree に書いたのは本ファイル 1 つ（`git status --short` は開始時 36 行 → 本ファイル追加で 37 行）。変異・探針スクリプトは job tmp（下記）。

## 実測した環境・コマンド（隔離コピーのパス・件数）

| 項目 | 実測 |
|---|---|
| 隔離コピー | `/home/wisteria/.claude/jobs/e2bcfe94/tmp/rereview-wiring/tree/`（`.git` / `.venv` / `__pycache__` / `.pytest_cache` / `.claude` を除いて rsync。`PYTHONDONTWRITEBYTECODE=1`・`TMPDIR` はコピー内・`-p no:cacheprovider`） |
| import 先の確認 | `jin_render` / `jin_cli` / `jin_adk` / `jin_core` の `__file__` が 4 つともコピー側を指すことを毎回印字 |
| スクリプト | `rr-wiring-mutate.py`（M3a / M1 / M2a〜e / M6 / M7）・`tree/delivery/.../phase3-mutations/mutate_probe.py`（`mutate_p3.py` + PROBE 1 件。コピー側にだけ置いた）・`u2028-probe.py`（R1.2 の 3 の根拠確認）。いずれも `/home/wisteria/.claude/jobs/e2bcfe94/tmp/rereview-wiring/` |
| `UV_LOCKED=1 uv sync`（worktree） | EXIT 0（Resolved 79 / Checked 76・lock 更新なし） |
| `uv run lint-imports`（worktree） | **3 kept / 0 broken** |
| `uv run pytest packages/jin-render/tests`（worktree・単独） | **219 passed**（4 snapshots）。`jin_adk` を import せずに通る |
| `uv run pytest packages/jin-cli/tests`（worktree・単独） | 165 passed / 18 warnings |
| 全スイート（隔離コピー・`PYTHONPATH`=コピーの `packages/*/src`） | **1100 passed**, 68 warnings, 6 snapshots（notes R1.4 の 1100 と一致。warnings 数は不一致・下記） |
| `mutate_p3.py` 全件（隔離コピーから起動） | baseline green（296 passed）・**59/59 caught**・SKIP 0・rc 0・`imports from:` はコピー配下・`mtmp/` と `/tmp` に `jin-mutate-p3-*` / `jin-run-*` の残骸 0 |
| `MUTATE_ONLY=NOPE` | `!! MUTATE_ONLY に存在しない変異名: ['NOPE']`・rc 1・**27 ms**（コピー作成も baseline も走らない） |
| PROBE（`mutate_probe.py`・`MUTATE_ONLY=PROBE-adk-seq-step`） | `jin_adk/trace.py` の `self._seq += 1` → `+= 2` で `test_render_contract.py -k "committed_fixture_matches or live_run_produces_rows"` が **1 failed / 1 passed**（RED）。= `live_trace` の `jin run` サブプロセスが**コピー側の `jin_adk`** を読む |
| CI（`.github/workflows/ci.yml`） | 差分なし。`uv run` 行は 11・`test_ci_contract.MINIMUM_UV_COMMANDS = 9` 不変・契約テストは全スイートで通過。**追加が要るステップは無い** |

再レビュー変異の結果（隔離コピー・すべてファイルを戻してバイト一致を確認）:

| 変異 | 回したテスト | 結果 | 判定 |
|---|---|---|---|
| BASELINE | `test_packaging_contract` + `test_dependency_direction` + `test_render.py` | 107 passed | 緑 |
| **M3a**: google 契約の `source_modules` → `["jin_core"]` | 同上 2 契約ファイル | **2 failed** / 63 passed: `test_adk_isolation_contract_covers_every_package_but_jin_adk_and_jin_cli`（`source_modules に {'jin_render'} が無い`）**と** `test_import_linter_actually_bites_on_a_forbidden_import[jin_render-svg.py-import google.adk-google-adk]`（`違反を注入したのに import-linter が通ってしまった`） | RED（**独立な 2 網**。後者が赤になること自体が「注入設定は実契約から生成されている」の証明） |
| M3a を `tests/contract` 全体で | 162 件 | 2 failed / 160 passed | RED（他の契約テストは巻き込まれない） |
| **M1**: `render` の `@app.command()` を外す | `test_render.py -k registered_subcommand` | 1 failed | RED |
| M1（対照） | `test_render.py -k help_lists_render` | 1 passed | 緑のまま（docstring が「呼べることは下のテストで見る」と明記・intended） |
| **M2**: `packages/jin-render/tests/test_svg.py` に `import jin_adk`（トップレベル） | `test_packaging_contract -k package_tests_only` | 1 failed（`[jin-render]`）/ 3 passed | RED |
| M2b: 同・関数の中で `import jin_adk` | 同上 | 1 failed | RED（`ast.walk` が入れ子も拾う） |
| M2c: 同・`from jin_cli.main import app` | 同上 | 1 failed | RED |
| M2d: `packages/jin-adk/tests/test_trace.py` に `import jin_cli` | 同上 | 1 failed（`[jin-adk]`） | RED（許可集合が jin-adk でも効く） |
| M2e: 同・`importlib.import_module('jin_adk')` | 同上 | 4 passed | **緑のまま**（F-W-P3-103） |
| M6: `tests/conftest.py::child_env` の前置を `if False:` に | `tests/contract -k "child_env or env_with_stubs or PYTHONPATH or pythonpath"` | rc 5（**0 件選択**） | 固定テスト無し（F-W-P3-101） |
| M7: A-8 の parametrize で `jin_adk→jin_render` の keyword を `"google-adk"` に | `test_dependency_direction -k actually_bites` | 1 failed / 6 passed | RED（keyword は実際に検査されている・注入テストが空虚でない） |

## 前回 finding の判定（F-W-P3-001〜011）

| finding | 判定 | 根拠（実測） |
|---|---|---|
| F-W-P3-001 google 契約の網無し | **defect-gone** | M3a で 2 網が独立に赤（上表）。契約の特定は `forbidden_modules == ["google"]`（名前非依存・指示どおり）。`next(...)` が見つからなければ `StopIteration` でエラー = 赤側に倒れる |
| F-W-P3-002 注入が `jin_core` のみ | **defect-gone** | parametrize 7 件（`jin_render/svg.py` × 3・`jin_adk/trace.py` → `import jin_render` 1）。M7 で keyword が検査されていることを確認 |
| F-W-P3-003 親ディレクトリ不在の文言 | **defect-gone** | `main.py:953-955` `parent.is_dir()` → `WriteRefused("出力先のディレクトリがありません: …")`（作らない）。README 41 行目に「親ディレクトリは作らない」。`test_a_missing_parent_directory_is_refused_without_creating_it`。変異 `CLI-create-parent` は 59/59 の中で RED |
| F-W-P3-004 `live_trace` の `PYTHONPATH` 上書き | **defect-gone** | `tests/conftest.py::child_env` / `env_with_stubs`（前置）。`test_cli_contract._run`（`child_env(env_extra)`）・`_scripted_run`（`env_with_stubs()`）・`test_render_contract.live_trace` と端到端テスト（`env_with_stubs()`）の 4 箇所が使う。`mutate_p3._env` も前置。**PROBE で `jin run` サブプロセスがコピー側 `jin_adk` を読むことを実測**（上表）。ただし前置そのものの固定テストは無い（F-W-P3-101） |
| F-W-P3-005 `test_the_help_lists_render` が空虚 | **defect-gone** | `test_render_is_a_registered_subcommand`（`["render", "--help"]` exit 0 + `trace` / `focus` / `force` の語）。M1 で赤。旧テストは残っているが docstring が「サブコマンドとして呼べることは下で見る」と明記 |
| F-W-P3-006 tests の `jin_adk` import を落とす網無し | **部分残存（網は gone・docstring は残存）** | 網: `test_package_tests_only_import_the_jin_packages_that_package_depends_on`。M2a〜d で赤。許可集合 = 自パッケージ + `dependencies` の `jin-*`（jin-core: {jin_core} / jin-adk: {jin_adk, jin_core} / jin-render: {jin_render, jin_core} / jin-cli: {jin_cli, jin_core, jin_adk, jin_render}）。`tests.conftest` は `jin_` で始まらないので集まらない（`pythonpath = ["."]` で解決・Phase 2 の `test_cli.py` と同じ経路）。**残存**: `packages/jin-render/tests/conftest.py:3-4` は依然「`test_every_package_declares_the_jin_packages_it_imports` はテストも走査する」と書く。その関数は今も `src/` だけを走査する（`test_packaging_contract.py:299-318`）。A-11 の「conftest docstring を実物に合わせる」が未消化（F-W-P3-102） |
| F-W-P3-007 `-o` が入力 `.jin` と同一 | **defect-gone** | `main.py:956-958`（`--force` でも拒む）。`test_writing_over_the_input_jin_is_refused`。変異 `CLI-overwrite-the-input` RED |
| F-W-P3-008 成功文言が `_safe` を通らない | **部分残存** | `render`（`main.py:1040`）は `_safe(str(out))` に。`build`（`main.py:686` `typer.echo(f"書き出しました: {path}")`）は**生のまま**。前回 finding も指示書 D も「成功メッセージも `_safe` を通す」（両方）（F-W-P3-104） |
| F-W-P3-009 `MUTATE_ONLY` typo 検査の位置 | **defect-gone** | `main()` 冒頭・27 ms で rc 1（上表） |
| F-W-P3-010 CI に `jin render` スモーク無し | 記録のみ（指示どおり） | `ci.yml` 差分なし。R1 で足したテストに CI 側の追加ステップを要するものは無い（`PYTHONIOENCODING=ascii` の別プロセステスト・umask 3 値の in-process テストはいずれも Linux runner で成立） |
| F-W-P3-011 `-o <dir> --force` の文言 | **defect-gone** | `main.py:951-952` `path.is_dir()` → 専用文言。`test_a_directory_as_the_output_is_refused`（`"ディレクトリ" in output`・旧挙動の `既にあります…` / `Is a directory` のどちらにも無い語なので旧コードで赤になる） |

## Findings（修正が持ち込んだ・残した新規欠陥）

### F-W-P3-101 [confidence 75] `child_env` の「前置」に固定テストが無い（同じ欠陥が F-W-P2-007 → F-W-P3-004 と 2 度出た経路）
- 場所: `tests/conftest.py:38-49`（`child_env`）、notes R1.1 B-2 行「固定するテスト: 既存の子プロセステスト全部」
- 内容: 前置を `if False:`（= 上書き）に戻しても、どのテストも赤くならない（M6: `tests/contract -k "child_env or env_with_stubs or PYTHONPATH or pythonpath"` は 0 件選択・rc 5）。既存の子プロセステストは「上書きでも前置でも」通る（開発者の `PYTHONPATH` が空なら差が無い）ので、固定テストになっていない。指示書の規律「修正ごとに固定するテストを足す」に反する。3 箇所を 1 箇所に寄せたので再発面は小さくなったが、寄せた 1 箇所を守る網が無い。
- 変異検証: M6（上表）。
- 提案: `tests/contract/test_conftest_helpers.py`（または `test_cli_contract.py`）に 2 本: `monkeypatch.setenv("PYTHONPATH", "/inherited")` で `child_env({"PYTHONPATH": "/x"})["PYTHONPATH"] == "/x" + os.pathsep + "/inherited"`、`monkeypatch.delenv("PYTHONPATH")` で `== "/x"`。`mutate_p3.py` に `if False:` 変異を 1 件。

### F-W-P3-102 [confidence 90] `packages/jin-render/tests/conftest.py` の docstring が今も存在しない網を根拠にしている（A-11 の未消化）
- 場所: `packages/jin-render/tests/conftest.py:3-4`
- 内容: 「`test_every_package_declares_the_jin_packages_it_imports` はテストも走査する」と書くが、その関数は `_jin_imports(package / "src" / module)` のまま（`test_packaging_contract.py:316`）。テストを走査するのは新設の `test_package_tests_only_import_the_jin_packages_that_package_depends_on`（`:323-350`）。指示書 A-11 は「conftest docstring を実物に合わせる」を名指ししており、notes R1.1 A-11 行にもその記述が無い（対応漏れ）。前回 F-W-P3-006 の「記録と実物の不一致」がそのまま残っている。
- 提案: 関数名を `test_package_tests_only_import_the_jin_packages_that_package_depends_on` に差し替える（1 行）。

### F-W-P3-103 [confidence 40] パッケージテストの動的 import（`importlib.import_module("jin_adk")` / `pytest.importorskip`）は新しい網を素通りする
- 場所: `tests/contract/test_packaging_contract.py:282-296`（`_jin_imports` は `ast.Import` / `ast.ImportFrom` だけ）
- 内容: M2e（`importlib.import_module('jin_adk')` を `test_svg.py` に注入）で 4 passed。`test_dynamic_imports_are_confined_to_the_cli_resolver_and_jin_run` は `src` だけを見るので、tests 側の動的 import は誰も見ない。ADR-003 の「単体テストは自分の層より上を見ない」を意図的に破るには十分な抜け道だが、うっかりで書く形ではない。
- 提案: 記録のみで可。塞ぐなら `_jin_imports` に `importlib.import_module` / `pytest.importorskip` の第 1 引数が文字列定数のケースを足す（`DYNAMIC_IMPORT_CALLS` の走査を tests にも掛ける）。

### F-W-P3-104 [confidence 80] `jin build` の成功メッセージは `_safe` を通っていない（F-W-P3-008 の半分）
- 場所: `packages/jin-cli/src/jin_cli/main.py:685-686`（`for path in written: typer.echo(f"書き出しました: {path}")`）。対照: `main.py:1040`（`render` は `_safe(str(out))`）
- 内容: 前回 finding は「`build` も同じなので Phase 3 固有ではない。両方とも `_safe` にそろえる」。指示書 D は「成功メッセージも `_safe` を通す」。notes R1.1 D 表は「成功時の文言も `_safe` を通す（`test_the_success_message_does_not_carry_control_characters`）」と書くが `render` 側だけ。`written` は `--out` 由来のパスなので argv の制御文字が tty にそのまま出る（`render` 側と同じ経路）。severity は低い（D 帯）。
- 提案: `typer.echo(f"書き出しました: {_safe(str(path))}")`。`test_build_run.py` に `test_the_success_message_does_not_carry_control_characters` の build 版を 1 本。

### F-W-P3-105 [confidence 90] R1.2 の 3 の根拠「`core` の U+2028 はトレースの `name` に載る経路が無い」は事実と違う（結論は無害・指示どおりの端到端は実行可能だった）
- 場所: `implementation-notes.md` P3-R1.2 の 3、`packages/jin-adk/src/jin_adk/trace.py:139-146`（`core_pointer` は `name = entry.model or author` を返す = `.jin` の `core` 値そのもの）
- 内容（実測・`u2028-probe.py`・隔離コピー・`--model fake`）: `pipeline.jin` の `core` を `"gemini flash"` にした `.jin` は `jin check` **exit 0 / 診断 0**、`jin run --model fake --trace` は **exit 0・11 行**、トレースの 1 行目は `"name": "gemini flash"`（**生の U+2028 が載る**・`splitlines()` 12 / `\n` 分割 11）、`jin render --trace` は **exit 0**（修正は効いている）。つまり指示書 A-1 の「`core` に U+2028 を含む `.jin` → `jin run` → `jin render` が exit 0」は**そのまま実行可能**で、notes の「`name` に載る経路が無い」は誤り（`Ident` は C0 / C1 / DEL / サロゲートしか拒まない・`model.py:49-66`・U+2028 は通る。ここまでは notes も正しい）。差し替えられた端到端テスト（`output` に U+2028）自体は空虚でなく有効。
- 提案: 根拠の文を「`name` にも載る（`core_pointer` は `entry.model` を返す）。`output` 経路のほうを選んだのは FakeLlm 差し替えで両方を 1 本で見られるため」等、実物に合う説明に直す。安ければ `core` 経路の 1 param を足す（`.jin` を 1 つ書くだけ・`FakeLlm` 差し替え不要）。

### F-W-P3-106 [confidence 30] R1.4 の「`uv run pytest` 1100 passed, **1 warning**」は再現しない
- 場所: `implementation-notes.md` P3-R1.4
- 内容: 隔離コピーの全スイートは 1100 passed / **68 warnings**、worktree の `packages/jin-cli/tests` 単独でも 18 warnings（ADK の `SequentialAgent is deprecated` ほか）。前回レビュー時点（1005 件）も 68 warnings だった。件数の欠陥ではないが、どの呼び方で 1 になったのか（`-p no:warnings`？ `-W` 環境変数？）が記録に無く、次のラウンドで「warnings が増えた」と誤読される。
- 提案: R1.4 に実行コマンドを 1 行添える、または 68 に直す。

## 実装者の対応表（R1.1）と実物の照合

- **一致を確認**: A-7（テスト名・`forbidden_modules == ["google"]`・変異の赤）/ A-8（7 param・4 件追加）/ A-9（`parent.is_dir()`・作らない・README・テスト・`CLI-create-parent`）/ A-10（`["render", "--help"]`・`CLI-render-not-registered`）/ A-11（網・許可集合。**docstring は未対応**）/ B-2（`child_env` / `env_with_stubs`・両ファイル・`_env` 前置）/ D の F-W-P3-007 / 009 / 011（テストと文言）/ 変異 59 本（`MUTATIONS` 要素数 59・59/59 caught・rc 0）/ `UV_LOCKED=1 uv sync` / lint-imports 3 kept / 1100 passed。
- **不一致**: 上の F-W-P3-102（A-11 の docstring）/ F-W-P3-104（D の「成功メッセージも」は render 側だけ）/ F-W-P3-105（R1.2 の 3 の根拠）/ F-W-P3-106（warnings 数）。
- `mutate_p3.py` の `where` 検査は `jin_render` / `jin_cli` の 2 つしか印字しないが、`_env` の `PYTHONPATH` は `packages/*/src` 4 つを並べるので `jin_adk` / `jin_core` もコピー側（PROBE で実証）。欠陥ではない。

## R1.2（指示と違えた判断 9 件）の 1 行評価

1. **`0o644 & ~umask`（`0o666` でなく）**: 妥当。`jin_adk/build.py:147,162` は `os.open(name, O_CREAT|O_EXCL, 0o644, dir_fd=…)` で、指示書の `0o666` は umask 0o002 で実物と食い違う。`test_the_created_mode_matches_what_jin_build_writes` が実物と突合するので、どちらが動いても赤。
2. **stdout を `sys.stdout.buffer` へ UTF-8 で書く**: 妥当。指示の「1 行 exit 1」より強い解（ロケール非依存で `-o` と同一バイト）。別プロセスの `PYTHONIOENCODING=ascii` テストがあり、変異 `CLI-stdout-locale` は RED。
3. **端到端の U+2028 を `core` でなく `output` に置いた**: **根拠が事実と違う**（F-W-P3-105）。`core` の U+2028 は `jin check` を通り、`name` に生で載り、`jin render --trace` は exit 0（実測）。差し替え先のテストは有効なので結論は無害だが、指示どおりの端到端は実行可能だった。
4. **U+000B / U+000C を対象から外した**: 妥当。`json.dumps` は 0x20 未満を `\uXXXX` に逃がすので JSONL に生では現れない（`ensure_ascii=False` でも同じ）。
5. **B-5 の実効範囲は U+FFFE / U+FFFF だけ**: 妥当。`_reject_bad_chars`（`model.py:49-66`）が C0 / C1 / DEL / サロゲートを拒むことを確認。`jin_core` の検証は変えていない（診断コード不変）。
6. **F-S-P3-011 に上限を付けない**: 妥当（CLAUDE.md「具体値を推測で置かない」に従う）。ストリーム読みで 2 重コピーが消えたことは `_read_trace_rows` の `path.open(newline="\n")` で確認。判断は notes に残っている（指示の「記録のみでもよいが判断を書く」を満たす）。
7. **F-C-P3-013 は A-3 で関数ごと消えた**: 妥当（`pointer_prefixes` は `overlay.py` に無い・`grep` 0 件）。
8. **plan の `$comment` を触らない**: 妥当。指示書 E が「`undecided[]` 以外は触らない」と明記。F-V-P3-013 は conventions 側で再評価される項目。
9. **F-W-P3-010 / F-S-P3-013 は記録のみ**: 妥当（指示どおり）。TOCTOU の説明（負けても `os.replace` がリンクの実体を置き換えるだけ）は `_write_atomically` の `Path(path).is_symlink()` 二層目と整合。

## 変異で緑のままだったテスト（偽 green の候補）

| 変異 | 回したテスト | 結果 | 対応 |
|---|---|---|---|
| M6: `child_env` の前置を殺す | `tests/contract`（`-k child_env …`） | 0 件選択 | F-W-P3-101（固定テスト無し） |
| M2e: tests に `importlib.import_module('jin_adk')` | `test_packaging_contract -k package_tests_only` | 4 passed | F-W-P3-103（記録） |
| M1: `@app.command()` を外す（対照） | `-k help_lists_render` | 1 passed | intended（隣の `registered_subcommand` が赤・docstring 明記） |

赤くなった対照: M3a（2 網）/ M1 / M2a〜d / M7 / PROBE（`jin_adk` 変異が `jin run` サブプロセス経由で赤）/ `mutate_p3.py` 58 RED + 1 期待 GREEN。

## 総合

defect-gone 8 / 部分残存 2（F-W-P3-006 の docstring・F-W-P3-008 の build 側）/ 記録のみ 1（F-W-P3-010・指示どおり）。新規 6 件（confidence 90: 2 件 = 102 / 105。いずれも記録・文言の欠陥で、コードの防御は全部実測で効いている）。
