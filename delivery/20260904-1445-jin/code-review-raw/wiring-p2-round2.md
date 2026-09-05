# 再レビュー（Phase 2 修正ラウンド 2）— wiring

実測日: 2026-09-06 / レビュアー: review-wiring-p2 / ブランチ `feat/jin-phase2-adk`（未コミットの作業ツリー）
基準状態（隔離コピーを作り直し・uv 0.12.9 実バイナリ + 隔離 venv `UV_PROJECT_ENVIRONMENT`・`UV_LOCKED=1`・`PYTHONPATH` 未設定・cwd = コピーのルート・uid 1000・`anthropic` 未インストール = CI ランナーと同じ条件）:
`uv lock --check` EXIT=0 / `uv sync` EXIT=0 / `lint-imports` **Analyzed 51 files, 143 dependencies / 3 kept**（R1 と同数）/ ruff **60 files**（R1 の 59 + `tests/fixtures/stubs/exits_tool.py`）/
`uv run pytest -rs` **787 passed・skipped 0**（2 snapshots passed）/ スキーマドリフト・`jin check`・`jin fmt --check examples` とも rc=0。
`uv.lock` は前回・前々回と **md5 一致**（`3e23308b…`）。`.github/workflows/ci.yml` は無変更。

**implementer の対応表（P2-R2.1 / P2-R2.2）は索引としてだけ使い、判定はすべて下記の実測に基づく。**
破壊的な変異は隔離コピー（`scratchpad/review-wiring`）でのみ行い、各変異後にバックアップから復旧して実ツリーと md5 一致を確認した。
実ツリーへの書き込みは本報告書 1 件のみ（`mutate_p2.py` の実行は実ツリーで行ったが、前後で不変を確認・§3）。

## Summary

- **確認対象 4 件: defect-gone 4 件（F-W-P2-004 / 101 / 102 / 103）。残存 0 件。**
- **新規: 4 件（F-W-P2-201 / 202 / 203 / 204・すべて low）。CI を落とすもの・マージを止めるものは無い。**
- 親の前提の訂正: `test_tool_sys_exit_at_runtime_is_a_failure` は**別プロセスではなく** `CliRunner` 在中。実プロセス版は存在しない（F-W-P2-204）。
- 新テストは CI 条件で緑（skip 0 件）。`test_fmt_check_on_every_formattable_fixture_exits_zero` は `build-errors/` と `errors/` のどちらを非正準にしても赤、
  `anthropic` 版の cwd 検査は窓の `finally` を消すと赤。
- `mutate_p2.py`: `/tmp/jin-run-*` の増分 0・実ツリー不変（前後で md5 一致）・66/66 caught・SKIP 0 件（親の環境で SKIP だった 2 件は本時点の作業ツリーでは RED）。`SKIP` は exit 1 だが、`MUTATE_ONLY` の typo は 0/0 で exit 0 になる（F-W-P2-203）。
- `.gitignore` に scratch 系を足す必要は無い（§4）。

---

## 1. finding 別の判定

| ID | 判定 | 根拠（実行したコマンドと出力） |
|---|---|---|
| **F-W-P2-004** `build-errors/` fixture が正準形契約の外（部分残存） | **defect-gone** | 新テスト `tests/contract/test_cli_contract.py::test_fmt_check_on_every_formattable_fixture_exits_zero` が `formattable_paths` のうち `fixtures` 配下（errors の整形可能 14 本 + build-errors 20 本 = **34 本**）を**ファイルごとに** `jin fmt --check` へ渡す。実測: `build-errors/two_out_states.jin` の末尾に空行 2 つ → **FAILED**、`errors/JIN030_….jin` に同じ変異 → **FAILED**（Phase 1 から素通りだった `errors/` も塞がった）、`errors/JIN001_….jin`（モデルにならない）に同じ変異 → passed（対象外・設計どおり）。ci.yml は `jin fmt --check examples` のままだが、pytest ステップがこのテストを走らせるので CI でも赤くなる |
| **F-W-P2-101** `mutate_p2.py` が `/tmp/jin-run-*` を残す | **defect-gone** | `_env()` が `TMPDIR=<copy>/tmp` を渡し（`mutate_p2.py:381-388`）、コピーは `finally` の `rmtree` で消える。実測は §3（実行前後の `/tmp/jin-run-*` 件数が同じ） |
| **F-W-P2-102** cwd シャドウ検査が ADK の遅延 import に依存（観察） | **defect-gone（記録として）** | `test_cwd_cannot_supply_an_uninstalled_optional_dependency_during_the_run` の docstring が依存する 2 事実（`anthropic` 未インストール / ADK が実行中に遅延 import）を明記し、(1) を `skipif` で前提化。**噛むこと**: コピーの `runtime.py` にハーネスの `RUN-cwd-stays-after-import` と同じ変異（`_sys_path_window` の `finally` から `sys.path.remove(entry)` を消す = cwd が Runner 実行中も残る = append 実装相当）を適用し、CI 条件で `-k "cwd or extra_sys_path"` → **3 failed, 1 passed**: 赤は `…uninstalled_optional_dependency…` / `test_run_adds_cwd_to_sys_path` / `test_extra_sys_path_is_present_only_during_the_import`、緑は `…shadow_an_installed_package…`（インストール済み名は窓方式でも末尾でも本物が勝つ、という docstring の主張どおり）。復旧後 md5 一致。`skipif` の評価は F-W-P2-201 |
| **F-W-P2-103** round-trip 契約はディスクを読まない（docstring 不一致） | **defect-gone** | `test_text_roundtrip_is_byte_identical` の docstring を「`dumps` の冪等性・ディスク上のバイト列は読まない・ディスクは `test_fmt_check_on_every_formattable_fixture_exits_zero` が見る」に訂正（`test_canonical_contract.py:82-87`）。実装は据え置きで、ディスク検査は上の新テストが担う（004 で実測） |

## 2. 新テストの CI 条件での成立

| テスト | 条件 | 実測 |
|---|---|---|
| `test_fmt_check_on_every_formattable_fixture_exits_zero` | `_run` は `cwd=REPO_ROOT` 既定・絶対パスで渡す・`PYTHONPATH` 不要 | 緑。変異で赤（§1） |
| `test_cwd_cannot_supply_an_uninstalled_optional_dependency_during_the_run` | `skipif(find_spec("anthropic") is not None)`。`anthropic` は **`uv.lock` に無い**（`grep -c '^name = "anthropic"'` = 0）ので `UV_LOCKED=1 uv sync` の CI に入る経路は無い | 緑（skip せず実行）。`anthropic/` をダミーで `PYTHONPATH` に置くと `1 skipped`。CI の `-q` 出力では summary 行に `N skipped` と出るだけで**失敗しない**（F-W-P2-201） |
| `requires_non_root`（`test_cleanup_failure_…` ほか test_cli 5 本） | GitHub の hosted runner は非 root ユーザーで走る（ここでは uid 1000 で再現） | 緑（skip 0）。root コンテナで走らせると黙って skip（`-q` の summary に出る）。`test_runtime.py:125` と `test_cli.py:431` で `geteuid` 無し OS の扱いが逆（前者 skip / 後者実行）— Windows 想定外なので記録のみ（F-W-P2-202） |
| `test_tool_sys_exit_at_runtime_is_a_failure` | **別プロセスではない**: `packages/jin-cli/tests/test_build_run.py:360` は `CliRunner` 在中で `jin_cli.main.FakeLlm` を monkeypatch。`exits_tool` は autouse fixture の `syspath_prepend(STUBS)` で供給 | 緑。実プロセス版は implementer が手動で確認したとの申告のみで**テストとしては存在しない**（P2-R2.1 A-1）。`asyncio` の shutdown ログ検査は `caplog` 側が担う（docstring どおり） |

`tests/fixtures/stubs/exits_tool.py` は実ツリーで `uv run python -c "import exits_tool"` → **ModuleNotFoundError**（`research` も同じ）。誤って import 可能にはなっていない。

## 3. `mutate_p2.py`（ハーネスの構造）

実ツリーで `uv run python delivery/20260904-1445-jin/phase2-mutations/mutate_p2.py` を実行（所要 67 秒）:

| 観測 | 実行前 | 実行後 |
|---|---|---|
| `/tmp/jin-run-*` の個数 | 0 | **0**（R1 では 1 回につき +3） |
| `/tmp/jin-mutate-*` の個数 | — | 0（コピーは消えている） |
| `git status --short` の md5 | `7ef42a32…` | **一致** |
| `uv.lock` / `pyproject.toml` / `jin_adk/*.py` / `jin_cli/main.py` の md5 | `8f4d7415…` | **一致** |
| `packages` / `tests` 配下の `__pycache__` | 0 | 0 |
| 起動時の印字 | `imports from: /tmp/jin-mutate-hv7myrig/packages/jin-adk/src/jin_adk/__init__.py`（コピーを指す） | |
| 結果 | **66/66 mutations caught・SKIP 0 件・rc=0**。`RUN-swallow-systemexit-at-runtime` / `RUN-cwd-stays-after-import`（3 failed）/ `RUN-cwd-first`（2 failed）/ `CLI-no-cwd` いずれも RED | |

親の環境で SKIP になった `TRACE-drop-text-with-call` / `CLI-trace-follow-symlink` は、本レビュー時点の作業ツリーでは **pattern not found にならず RED**（implementer の追従が反映済み）。

- **`SKIP` は exit 1**: `main()` の戻り値は `0 if caught == len(mutations) and skipped == 0 else 1`（`:463`）。`SKIP (pattern not found)` を caught に数えない（`:438`）。
- **`TMPDIR` はコピー内**: `_env()` が `copy / "tmp"` を作って渡す（`:385-388`）。`load_generated` の `mkdtemp` はこれを尊重する（R0 §8 で実測済み）。
- **実ツリー不変**: 変異は `tempfile.mkdtemp(prefix="jin-mutate-")` に複製した `packages` / `tests` / `examples` / `pyproject.toml` に対して行い、`PYTHONPATH` にコピーの `src` を前置、起動時に `jin_adk.__file__` / `jin_cli.__file__` がコピーを指さなければ `return 2`。
- **`MUTATE_ONLY`**: 環境変数のカンマ区切りで絞る。**存在しない名前を渡すと 0 件で exit 0**（§5 F-W-P2-203）。

## 4. `.gitignore`

現状 `.venv/ __pycache__/ *.pyc .pytest_cache/ .ruff_cache/ .import_linter_cache/`。scratch 系を足す必要は**無い**:

- `out/` / `t.jsonl`: README / CLAUDE.md の例は `/tmp/out` / `/tmp/t.jsonl` に統一済みで、リポジトリ内に書く導線が無い。`git status --short --ignored` にも残骸なし。
- `*.jin-tmp`: `jin build --force` が `<out>/<root>/` 内に `.<name>.jin-tmp` を `O_EXCL` で作り `os.replace` で差し替える（`build.py:122-123`）。残骸が出るのは `--out` をリポジトリ内に向けて途中で落ちたときだけで、そのときは「残っています」で次回拒む設計なので**隠さないほうが良い**（ignore すると残骸に気づけない）。
- `jin fmt` の `.<name>.tmp`（`main.py:358-359`・Phase 1 から）も同じ理由で ignore しない。

なお、このマシンでは `/tmp/out` が **0 バイトの通常ファイル**（5 月作成・本案件と無関係）として存在し、README の `--out /tmp/out` はそのまま叩くと失敗する。`jin build` は
`… を出力先ディレクトリにできません: File exists` を出して rc=1（トレースバック無し）で、配線の欠陥ではない。

## 5. 新規

### F-W-P2-201 [LOW] confidence 70 — `anthropic` 版の `skipif` は「lock が保証する前提」を skip で表現しており、崩れたとき黙る
`tests/contract/test_cli_contract.py:219-222`

`anthropic` が `uv.lock` に無い以上、CI で skip になる経路は現状無い。しかし将来 `anthropic` が（例えば ADK の extra 経由で）lock に入った瞬間、この検査は
**`-q` の summary に `1 skipped` と出るだけで緑のまま**になり、F-S-P2-101 の実プロセス検査が消える。前提は lock が保証しているので、`skipif` ではなく
`assert importlib.util.find_spec("anthropic") is None, "…lock に anthropic が入った。別の未インストール名に差し替えること"` と**失敗にする**ほうが、
W-02 / N-01 と同じ「検査が存在する ≠ 検査が効いている」の型を避けられる。`requires_non_root` の skip は環境（root）由来なので skip のままで妥当。

### F-W-P2-202 [LOW] confidence 60 — `requires_non_root` の 2 定義が `geteuid` の無い OS で逆に振る舞う（記録）
`packages/jin-adk/tests/test_runtime.py:125-128` / `packages/jin-cli/tests/test_cli.py:431-434`

前者は `not hasattr(os, "geteuid") or …` で skip、後者は `hasattr(os, "geteuid") and …` で実行。Linux / macOS では同じ。Windows は本案件の対象外なので実害は無いが、
1 箇所（`tests/conftest.py`）に寄せれば差が消える。

### F-W-P2-203 [LOW] confidence 85 — `MUTATE_ONLY` に存在しない名前を渡すと 0/0 で exit 0
`delivery/20260904-1445-jin/phase2-mutations/mutate_p2.py:432-433, 463`

実測: `MUTATE_ONLY=nope uv run python …/mutate_p2.py` → `baseline: green` の後 **`0/0 mutations caught`・rc=0**。変異名の typo が「全部 caught」に見える。`only - {m[0] for m in MUTATIONS}` が空でなければ `return 2` にするのが 1 行の直し。

### F-W-P2-204 [LOW] confidence 80 — ツール実行中の `sys.exit` を「実プロセスで exit 1・stderr にトレースバック無し」と固定するテストが無い
`packages/jin-cli/tests/test_build_run.py:360-399`（`CliRunner` 在中）/ `implementation-notes.md` P2-R2.1 A-1（実プロセスは手動確認のみ）

`test_tool_sys_exit_at_runtime_is_a_failure` は in-process（`CliRunner` + `jin_cli.main.FakeLlm` の monkeypatch）で、pytest の logging プラグインが asyncio ロガーを吸うため
「asyncio の shutdown ログが stderr に出ない」は `caplog` 側の検査でしか見えていない（docstring も自認）。`jin run --model fake` にはツール呼び出しを台本で指定する
手段が無いので、`tests/contract/test_cli_contract.py` の `_run` 経由では同じ入力を作れない。実プロセスでの exit 1 / `Traceback` 無し / asyncio ログ無しは
implementer の手動実測（A-1）だけが根拠で、回帰したときに気づく網が無い。
修正案: `FakeLlm` に環境変数（例 `JIN_FAKE_SCRIPT=<json>`）か `--model fake:<script.json>` のような台本入力を 1 つ足し、`_run` から `exits_tool:boom` を踏ませる別プロセス版を 1 本置く。
台本入力を増やしたくなければ、`python -c "from jin_cli.main import app; app(['run', …])"` を `subprocess` で起動して monkeypatch 相当をその中で行う形でもよい。

## 6. 復旧の記録

| 対象 | 状態 |
|---|---|
| 実ツリー | 本報告書以外は無変更。`mutate_p2.py` 2 回実行（全件 + `MUTATE_ONLY=nope`）の前後で `git status` / 対象ファイル md5 / `__pycache__` 件数が一致（§3） |
| 隔離コピー `scratchpad/review-wiring` | 作り直し後、各変異はバックアップから復旧（対象ファイルの md5 は実ツリーと一致） |
| 隔離 venv `scratchpad/venv-ci` | 作り直し（uv 0.12.9）。実ツリーの `.venv` は未使用 |
| `/tmp/jin-run-*` | R1 の 35 個は本レビュー開始時点で 0 個（親が削除済み）。本ラウンドの実行で増えていない（§3） |
