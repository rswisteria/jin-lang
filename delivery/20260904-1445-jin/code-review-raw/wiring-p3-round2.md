# Stage 5 再レビュー: wiring — Phase 3 (jin-render) 修正ラウンド 2

レビュア: rereview-p3-r2-wiring / 2026-09-06 / 対象ブランチ `feat/jin-phase3-render`（worktree `.claude/worktrees/jin-phase3-6`・ベース origin/main `32c215e`）。
入力: `code-review-raw/wiring-p3-round1.md`（F-W-P3-101〜106・部分残存 F-W-P3-006 / 008）/ `phase3-fix-round-2-instructions.md` / `implementation-notes.md` P3-R2。
worktree に書いたのは本ファイル 1 つ。変異・探針スクリプトは job tmp（下記）。レビュー中に他エージェント（親の置換記録）が
`docs/adr/ADR-021-*.md` を `ADR-022-*.md` に差し替えた（1 回目の rsync で `file has vanished`）。実装者の責任範囲ではないが、記録との整合を F-W-P3-205 に書く。

## 実測した環境・コマンド（隔離コピーのパス・件数）

| 項目 | 実測 |
|---|---|
| 隔離コピー | `/home/wisteria/.claude/jobs/e2bcfe94/tmp/rereview2-wiring/tree/`（`.git` / `.venv` / `__pycache__` / `.pytest_cache` / `.claude` を除いて rsync。`PYTHONDONTWRITEBYTECODE=1`・`TMPDIR` はコピー内・`-p no:cacheprovider`） |
| import 先の確認 | `jin_render` / `jin_cli` / `jin_adk` / `jin_core` の `__file__` が 4 つともコピー側を指すことを毎回印字（`rr2-mutate.py`） |
| スクリプト | `rr2-mutate.py`（M-A〜M-H・M-C2）/ `stdout-probe.sh`（標準出力の異常系 10 通り）/ `devmode-probe.sh` / `mutate-only-probe.sh`。いずれも `/home/wisteria/.claude/jobs/e2bcfe94/tmp/rereview2-wiring/` |
| `UV_LOCKED=1 uv sync`（worktree） | EXIT 0（Resolved 79 / Checked 76・lock 更新なし） |
| `uv run lint-imports`（worktree） | **3 kept / 0 broken** |
| `uv run ruff check .` / `ruff format --check .` | All checks passed / 77 files already formatted |
| `uv run pytest packages/jin-render/tests`（worktree・単独） | **302 passed**（4 snapshots）。`jin_adk` を import せずに通る |
| `uv run pytest packages/jin-cli/tests`（worktree・単独） | **169 passed** / 18 warnings |
| 全スイート（隔離コピー・`PYTHONPATH`=コピーの `packages/*/src`） | **1190 passed**, 68 warnings, 6 snapshots（notes R2.3 と一致） |
| `mutate_p3.py` 全件（隔離コピーから起動・`TMPDIR`=コピー内 `mtmp/`） | baseline green（383 passed）・**70/70 caught**・SKIP 0・rc 0・`imports from:` はコピー配下・期待 GREEN 2 本（`CLI-follow-symlink-upfront-only` / `STAR-pre-fix-star-shape-stays`）・`mtmp/` と `/tmp` に `jin-mutate-p3-*` / `jin-run-*` の残骸 0 |
| `MUTATE_ONLY=NOPE` | `!! MUTATE_ONLY に存在しない変異名: ['NOPE']`・rc 1・**24 ms** |
| `MUTATE_ONLY=CLI-build-success-unsafe,CLI-stdout-oserror-traceback,TRACE-splitlines` | 3/3 caught（`TRACE-splitlines` は **5 failed / 1 passed** = notes A-2 行の記述と一致）・rc 0・残骸 0 |
| CI（`.github/workflows/ci.yml`） | 差分なし。`uv run` 行 11・`MINIMUM_UV_COMMANDS = 9` 不変。R2 で足したテスト（`/dev/full` への実書き込み・`skipif` 付き / umask 復元 / `child_env` 2 本）は Linux runner でそのまま成立。**追加が要るステップは無い** |

再レビュー変異の結果（隔離コピー・すべてファイルを戻してバイト一致を assert）:

| 変異 | 回したテスト | 結果 | 判定 |
|---|---|---|---|
| BASELINE | `test_cli_contract` + `test_render_contract` + `test_build_run` + `test_render.py` | 127 passed | 緑 |
| **M-A**: `child_env` の前置を `if False:` に（= 上書き） | `test_cli_contract -k "child_env_keeps or env_with_stubs_puts"` | **2 failed** | RED（F-W-P3-101 の網が効く） |
| **M-A2**: 前置を**後置**に（`[inherited, extra]`） | 同上 | **2 failed** | RED（順序まで検査している。`in` 判定ではない） |
| **M-B**: `build` の成功文言を生の `{path}` に | `test_build_run -k build_success_message` | **1 failed** | RED（B-5） |
| M-H（対照）: B-5 のテストの `--out` から U+0007 を外す | 同上 | 1 passed | 制御文字が load-bearing（対照として妥当） |
| **M-C2**: `child_env` 本体を `raise RuntimeError` に | `test_render_contract -k "trace_written_by_jin_run or live_run_produces"` | **2 failed + 1 error** | RED（端到端 2 param と `live_trace` fixture の 3 つとも `child_env` を通る） |
| M-C: `env_with_stubs` からスタブを外す（`child_env(extra)` だけ） | `-k trace_written_by_jin_run` | 2 passed | **緑のまま**。pipeline.jin に `ref` が無いのでスタブは不要。欠陥ではない（下表） |
| **M-G**: 端到端 `core` param の U+2028 を外す | 同上 | 1 failed / 1 passed | RED（`core` param は空虚でない。「U+2028 が生で載らない（テストが空虚になっている）」の assert が落ちる） |
| **M-D**: `_write_stdout_bytes` の `os.devnull` 差し替えを外す | `test_render.py -k full_stdout` | **1 failed** | RED（`test_render.py:416` `assert 120 == 1`・stderr に `Exception ignored while flushing sys.stdout`。notes の「exit 1 が 120 に化ける」は事実） |
| M-E: `if sys.stdout is None:` を `if False:` に | `test_render.py` + `test_render_contract.py` 全部 | 58 passed | **緑のまま**（F-W-P3-202） |

## 前回 finding の判定

| finding | 判定 | 根拠（実測） |
|---|---|---|
| F-W-P3-006（部分残存: conftest docstring） | **defect-gone** | `packages/jin-render/tests/conftest.py:3-5` が `test_packaging_contract.py::test_package_tests_only_import_the_jin_packages_that_package_depends_on` を名指しし、「`test_every_package_declares_…` は `src/` しか見ない」と併記。両関数は実在（`test_packaging_contract.py:299` / `:323`） |
| F-W-P3-008（部分残存: build 側） | **defect-gone** | `main.py:689` `typer.echo(f"書き出しました: {_safe(str(path))}")`。M-B RED・`CLI-build-success-unsafe` RED（70/70 の中）。ただし stdout 自体が書けない時の挙動は render / build とも別問題（F-W-P3-201） |
| F-W-P3-101 `child_env` 前置の固定テスト無し | **defect-gone** | `test_cli_contract.py:317-341` の 2 本。M-A（上書き）・M-A2（後置）とも 2 failed。`monkeypatch.setenv` で実環境を作ってから `child_env` を呼ぶので、開発者の `PYTHONPATH` が空でも意味を持つ |
| F-W-P3-102 conftest docstring | **defect-gone** | 上の 006 と同じ |
| F-W-P3-103 tests の動的 import は網を素通り | **記録のみ（妥当）** | R2.2 の 8。「テストは配布物でなく、任意コード実行契約の対象外」は design.yaml の forbidden contract の対象（`jin_core` / `jin_adk`）とも整合。F-V-P3-009 / 108 で実物の `__import__` は消えている |
| F-W-P3-104 build 成功文言 | **defect-gone** | 上の 008 と同じ |
| F-W-P3-105 R1.2 項 3 の根拠 | **defect-gone** | 端到端が `core` / `output` の 2 param（`test_render_contract.py:230-291`）。`core` param は `jin check` exit 0 → `jin run --model fake` → raw に U+2028 → `jin render --trace` exit 0 を assert。docstring に「R1 の記述は誤りだった」と明記。M-G で空虚でないこと、M-C2 で `child_env` 経由であることを実測。`TRACE-splitlines` は 5 failed（3 + 2 param） |
| F-W-P3-106 「1 warning」 | **defect-gone** | notes R1.4（`:1446`）を「68 warnings（`-W ignore::DeprecationWarning` 付きの値だった）」に。実測 68 と一致 |

## 親の問い (3): `_write_stdout_bytes` の `os.devnull` 差し替えは既存の stdout 経路・typer の終了処理と干渉するか

**干渉しない。** 根拠:

- 呼び出し元は **1 箇所だけ**（`main.py:1064`・`render` の `out is None` 経路。grep で `def` 以外の出現はこれのみ）。`jin dump`（`typer.echo`・`:641`）/
  `jin schema`（`sys.stdout.write`・`:614`）/ `jin check` / `jin fmt` / `jin build` / `jin run` は `_write_stdout_bytes` に到達しないので、差し替えが触ることは無い
  （実測: `dump` / `schema` を `> /dev/full` にすると R1 以前と同じ rc 120 + トレースバック。悪化も改善もしていない）
- 差し替えは `except OSError` の中でだけ起きる。正常経路（実測 `jin render R > file`・`| head`）では `sys.stdout` は触られない
- `sys.stdout is None` は起動時に fd 1 が無いときだけ（`preexec_fn=os.close(1)` で実測・上の F-W-P3-202）。分岐は 1 行 + exit 1 で、`typer.echo(err=True)` は stderr なので None 側を触らない。
  stderr も閉じている場合（`2>&-`）も rc 1（実測）
- typer / click の終了処理: `typer.Exit(1)` → click `standalone_mode` の `sys.exit(1)` → インタプリタ終了時の `flush_std_files` が差し替え後の `/dev/null` を flush するので
  120 に化けない（M-D で差し替えを外すと `assert 120 == 1` で赤・実測）。`sys.__stdout__`（元のオブジェクト）は残るが、終了時 flush の対象は `sys.stdout` だけで、実測で
  `Exception ignored` は出ない
- テスト間の漏れ: CliRunner は `isolation()` の `finally` で `sys.stdout` を復元するので、in-process で `OSError` 分岐を踏んでも次のテストに `/dev/null` は残らない
  （ただし現状この分岐を in-process で踏むテストは無く、`/dev/full` は別プロセス）
- **残存**: ライブラリとして `jin_cli.main` を呼ぶ側（Phase 4 の LSP は契約上 `jin_cli` を import しないので該当しない）がこの分岐を踏むと、そのプロセスの `sys.stdout` は以後
  `/dev/null` のまま。CLI（直後に exit）では問題ない。閉じられない fd が 1 本残る（F-W-P3-203）

## Findings（修正が持ち込んだ・残した新規欠陥）

### F-W-P3-201 [confidence 70] `-o` 経路の成功文言（`typer.echo`）は stdout が書けないとき今も rich トレースバック + **exit 120**（F-S-P3-103 の修正は SVG を stdout に出す経路だけ）
- 場所: `packages/jin-cli/src/jin_cli/main.py:1076`（`render` の `typer.echo(f"書き出しました: …")`）、`:689`（`build` の同文言）。対照: `_write_stdout_bytes`（`:922-953`）
- 内容（実測・`stdout-probe.sh`・worktree の venv）:

  | コマンド | rc | stderr |
  |---|---|---|
  | `jin render R > /dev/full` | **1** | 1 行「標準出力に書けません（No space left on device）」。`Exception ignored` 無し |
  | `jin render R >&-` | **1** | 1 行「標準出力が閉じています」 |
  | `jin render R --trace T > /dev/full` | 1 | 同上 1 行 |
  | `jin render R > /dev/full 2>&-` | 1 | （stderr も閉）落ちない |
  | **`jin render R -o out.svg --force > /dev/full`** | **120** | rich の `OSError: [Errno 28]` トレースバック + `Exception ignored while flushing sys.stdout`。**SVG は書けている**（`cmp` で通常の stdout 出力と一致・5822 B） |
  | `jin render R -o out.svg --force >&-` | 0 | （click の `echo` は stdout None なら黙って戻る）ファイルは書けている（`cmp` 一致・5822 B）。fd 1 が空いているので `mkstemp` が fd 1 を受け取るはずだが `sys.stdout` は None なので無害（この 1 点は読解） |
  | `jin dump P > /dev/full` / `jin schema > /dev/full` | 120 | 同じトレースバック（Phase 1 から。P3 の変更で悪化も改善もしていない） |
  | `jin check P > /dev/full` | 0 | 診断 0 件なので stdout に何も書かない |

  `render -o` の成功文言は `typer.echo` → `sys.stdout.write` → `OSError` が typer の pretty-exception に渡って exit 1、
  その後インタプリタ終了時の flush が同じ `OSError` で **120** に化ける（`_write_stdout_bytes` が `os.devnull` 差し替えで
  避けている経路と同じ）。fail-open ではない（ファイルは書けて rc は非 0）が、R2 で「標準出力側も 1 行 + exit 1 にそろえる」と
  書いた主張（`main.py:941-942` のコメント・notes F-S-P3-103 行）は `-o` 無しの経路にしか当てはまらない。`build` も同じ。
- 変異検証: 該当テスト無し（この経路のテストは存在しない）。
- 提案: 成功文言の `typer.echo` を `_write_stdout_bytes` と同じ扇に載せる（`_echo_or_exit(text)`: `OSError` → 1 行 stderr + devnull 差し替え + `Exit(1)`）か、
  「`-o` の成功文言は best-effort」と notes に 1 行書いて記録のみにする。dump / schema は Phase 1 の挙動なので P3 では記録のみでよい。

### F-W-P3-202 [confidence 60] `sys.stdout is None`（fd 1 が閉じている）分岐にテストが無い
- 場所: `packages/jin-cli/src/jin_cli/main.py:928-931`
- 内容: M-E（分岐を `if False:` に）で `test_render.py` + `test_render_contract.py` 58 passed。実挙動は正しい（上表 `>&-` で 1 行 + exit 1）が、
  R2 で足したコードに固定テストが無いのは指示書の規律（修正ごとに固定テスト）に反する。分岐を消したときの文言は未実測（変異で緑なので、どのテストも見ていないことだけが事実）。
- 変異検証: M-E 緑。
- 提案: `test_a_full_stdout_is_one_line_not_a_traceback` の隣に別プロセス 1 本。**作り方に注意**（`closed-stdout-probe.py` で実測）:
  `sys.stdout is None` になるのは**インタプリタ起動前に** fd 1 が無いときだけなので、
  `subprocess.run([jin, "render", …], preexec_fn=lambda: os.close(1), stderr=PIPE)` で rc 1・stderr「標準出力が閉じています」（実測）。
  `python -c "import os; os.close(1); …app(…)"` は起動後に閉じるので `sys.stdout` は生きた `TextIOWrapper` のままで、`OSError(EBADF)` 側に落ちる
  （実測: rc 1・「標準出力に書けません（Bad file descriptor）」）。この形では None 分岐を固定できない。
  `mutate_p3.py` に `CLI-stdout-none-branch-dead` を 1 件。

### F-W-P3-203 [confidence 35] `os.devnull` 差し替えのファイルオブジェクトが閉じられず、`PYTHONDEVMODE=1` で `ResourceWarning` が 1 行出る
- 場所: `packages/jin-cli/src/jin_cli/main.py:950-951`
- 内容（実測・`devmode-probe.sh`）: `PYTHONDEVMODE=1 jin render R > /dev/full` → rc 1・1 行の文言のあとに
  `<sys>:0: ResourceWarning: unclosed file <_io.TextIOWrapper name='/dev/null' mode='w' encoding='UTF-8'>`。既定モードでは出ない。
  終了直前のプロセスでの 1 fd なので実害は無い。
- 提案: `sys.stdout = None` にする（CPython の終了時 flush は `sys.stdout` が `None` なら飛ばす・click の `echo` も None なら黙る）。
  変える場合は M-D と同じ `/dev/full` テストが 1 を保つことを再実測する。あるいは記録のみ。

### F-W-P3-204 [confidence 50] `mutate_p3.py` の期待 GREEN の表示文言が `STAR-pre-fix-star-shape-stays` に当てはまらない
- 場所: `delivery/20260904-1445-jin/phase3-mutations/mutate_p3.py:880`（`status = "GREEN (expected: 二層目が守る)"` は `EXPECT_GREEN` 全体に共通）
- 内容: 70 本の出力に `STAR-pre-fix-star-shape-stays GREEN (expected: 二層目が守る)` と出る（実測）。この変異の GREEN の理由は「星形テストは配置の恒等化では落ちない」であり、
  シンボリックリンクの二層防御とは無関係。R2.2 の 12 で「理由をエントリのコメントに書いた」とあるが、機械が印字する理由文は間違ったまま。
  次に読む人が「二層目」を探す。
- 提案: `EXPECT_GREEN` を `dict[str, str]`（名前 → 理由）にして `status` に理由を差し込む。

### F-W-P3-205 [confidence 40] notes R2.1 A-4 行の「ADR-021」は、親の置換記録（ADR-022 に切り直し）で存在しないファイル名になった
- 場所: `implementation-notes.md:1501`（「ADR-021 と `decision_record` は触っていない」）。実物: `docs/adr/ADR-022-DP-IMPL-JIN-P3-LOOP-STAR-ORDER-01.md`（ADR-021 は無い）。
  `implementation-plan.json:1804` / `auto-decisions.json:201` の `adr_ref` は ADR-022 を指す。`implement-ledger.md:284` に切り直しの記録あり
- 内容: 実装者が書いた時点では正しかった（時系列で親の作業が後）。記録の整合だけの問題。
- 提案: 「ADR-021（親の置換記録で ADR-022 に切り直し）」と 1 語足す。

## 変異で緑のままだったテスト（偽 green の候補）

| 変異 | 回したテスト | 結果 | 対応 |
|---|---|---|---|
| M-E: `sys.stdout is None` 分岐を殺す | `test_render.py` + `test_render_contract.py` | 58 passed | F-W-P3-202 |
| M-C: `env_with_stubs` からスタブを外す | `-k trace_written_by_jin_run` | 2 passed | intended（pipeline.jin は `ref` を持たないのでスタブ不要。M-C2 で `child_env` 経由であることは別途 RED。欠陥ではない） |
| M-H: B-5 テストの制御文字を外す（対照） | `-k build_success_message` | 1 passed | intended（M-B が RED なので網は効いている） |

赤くなった対照: M-A / M-A2 / M-B / M-C2 / M-D / M-G / `mutate_p3.py` 68 RED + 2 期待 GREEN。

## 実装者の記録（notes / conformance / plan / layout.md）と実物の不一致

- **一致を確認**: R2.0 / R2.3 の数値（1190 passed・68 warnings・6 snapshots・70/70・baseline 383・3 kept・Checked 76・77 files）/ A-2（2 param・`TRACE-splitlines` 5 failed）/ A-3（docstring の関数名が実在）/
  B-5（`_safe`・テスト名・変異名）/ F-W-P3-101 行（2 テスト・前置の順序まで検査）/ F-S-P3-103 行の「exit 1 が 120 に化ける」（M-D で実証）/ F-W-P3-106 行（68）/
  R2.2 の 1（`model.md §3.3` の誤引用は `codegen.py:27,73` と `adk-mapping.md:124` の 3 箇所に残る・grep 一致）/ R2.2 の 4（layout.md:265 に n >= 32 の記述）/
  `jin_render.__all__` に `brief`・`main.py:105` は `from jin_render import … brief`。
- **不一致**: F-W-P3-201（「標準出力側も 1 行 + exit 1」は `-o` 無し経路だけ）/ F-W-P3-204（機械が印字する GREEN の理由文）/ F-W-P3-205（ADR-021 の名前）。

## R2.2（指示と違えた判断 12 件）の 1 行評価

1. **Phase 2 の `model.md §3.3` 3 箇所は触らない**: 妥当。grep で 3 箇所を確認（`codegen.py:27,73` / `adk-mapping.md:124`）。P3 diff に混ぜない判断は範囲限定レビューの規律と整合。親の判断待ちで良い。
2. **`FLOW-no-node-limit` が最初 GREEN → テストを足す側に倒した**: 妥当。`test_the_chord_gap_matches_the_drawn_node` と `FLOW-extent-no-limit` の 2 本が 70/70 の中で RED。
3. **道具環の紋の重なりは別件**: 妥当（finding に無い）。起票は correctness / conventions の判断に委ねる。
4. **n >= 32 で弦が消えうるのは幾何の限界**: layout.md:265 に明記済み。診断コードを増やさない判断は CLAUDE.md と整合。受容するかは親（R2.5 の 2）。
5. **F-C-P3-103 記録のみ**: 妥当（`jin_adk.trace` は書かない・BOM 付き空行の理由も筋が通る）。
6. **F-S-P3-102 記録のみ**: 妥当（R1.2 項 6 と同じ根拠・値を推測で置かない）。
7. **F-S-P3-104 記録のみ**: 妥当（`--force` 明示・境界を越えない）。
8. **F-W-P3-103 記録のみ**: 妥当（上表）。
9. **F-V-P3-104 にテストを足さない**: 妥当。競合窓の再現は不安定。読解の結果（`SymlinkWriteRefused` だけ前置しない・`main.py:1068-1072`）は実物と一致。
10. **`--upto` は 4300 桁未満**: 妥当（`sys.int_info.str_digits_check_threshold` 既定 4300・テストは 1000 桁）。
11. **紋の重なりを 5 件に数える**: 3 と同じ。数え方の説明として整合。
12. **`STAR-pre-fix-star-shape-stays` を `EXPECT_GREEN` に**: 判断は妥当（「主張そのもの」の GREEN）。ただし機械の印字文言が「二層目が守る」のまま（F-W-P3-204）。

## 総合

前回 8 件（新規 6 + 部分残存 2）: **defect-gone 7 / 記録のみ 1**（F-W-P3-103・妥当）。新規 5 件（confidence 90 以上 0 件。最高 70 = F-W-P3-201。
fail-open 0・コードの防御は全部実測で効いている）。ゲート 8 本全緑・70/70・実ツリー不変・残骸 0・CI 追加ステップ不要。
