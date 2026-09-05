# Stage 5 security review — Phase 2 修正ラウンド 2（defect-gone 判定）

- 対象: `feat/jin-phase2-adk` 作業ツリー（修正ラウンド 2 反映後・2026-09-06 実測）。隔離コピーを作り直し
  （`git ls-files --cached --others` → scratchpad、`__pycache__` 除去、`PYTHONPATH=<copy>/packages/*/src`、
  `jin_adk.__file__` / `jin_cli.__file__` がコピー側を指すことを確認）。CLI は **`python -P`**（cwd を `sys.path` に自動追加しない）で起動。
  **実ツリーはこのレポート以外変更していない**
- baseline: **787 passed**（`-p no:cacheprovider`）
- 判定対象: round-1 新規 F-S-P2-101 / 102 / 103 / 104、F-C-P2-103、ラウンド 2 の変更全体（`implementation-notes.md` P2-R2.1 / P2-R2.2）

## 0. 要約

| finding | 判定 | 一言 |
|---|---|---|
| F-S-P2-102 ツール内 `sys.exit(0)` が exit 0 | **defect-gone** | 実プロセスで `sys.exit(0)` / `sys.exit(3)` → **exit 1**・stderr 1 行・トレースバック無し。同期 `run_model` も `RunError`。`KeyboardInterrupt` は exit 130 で素通し（飲まない）。`writer.close()` は冪等、トレース最終行は tool 行のまま（偽 `final` 無し） |
| F-S-P2-101 cwd が Runner 実行中に残る | **defect-gone** | `_sys_path_window` は例外 / `SystemExit` / `RunError` / 元からある値 / 同じ値 2 回 / 窓の中で他人が消した、の全ケースで `sys.path` を元に戻す。cwd の `anthropic/` は `pipeline.jin --model fake` でも走らない（0 件・exit 0）。`generate()` が窓の前に済むので不正 builtin 経由の `mcp` シャドウも消えた |
| F-S-P2-103 テンプレートの組み込み名 | **defect-gone** | `RESERVED_NAMES` に 7 名追加。AST テストはテンプレートに `len(` を足すと `RESERVED_NAMES に無い名前: ['len']` で赤（実測） |
| F-S-P2-104 `--force` で既存が 0 バイト | **defect-gone** | tmp + `os.replace`。ENOSPC 注入で既存 3 ファイル無傷・残骸無し。残骸 / 既存リンク / tmp 名に仕込んだリンク / 既存がディレクトリ、すべて拒否 |
| F-C-P2-103 既存トレースが 0644 のまま | **defect-gone** | 既存 644 → 実行後 600（実測）。`fchmod` 失敗は exit 1 の 1 行（空の 0600 ファイルが残る・fd は exit まで保持・Info） |
| ハーネス（TMPDIR / MUTATE_ONLY / 判定） | **問題なし** | 隔離コピーから起動して **66/66 caught**、`/tmp/jin-run-*` 残骸 0（前後とも）。判定は `returncode == 1 ∧ failed` のまま |

**新規（ラウンド 2 が持ち込んだ / 見えた）**

| ID | severity | conf | 一言 |
|---|---|---|---|
| **F-S-P2-201** | **Medium** | 95 | ツール関数が `asyncio.CancelledError` を投げると、**root が LlmAgent のとき exit 0**・`1 イベント`・エラー行無し（ADK の `_cleanup_root_task` が root の cancel を warning で握る）。`sys.exit(0)` と同じ「失敗を成功に見せる」fail-open だが、今回の修正が入れた `except CancelledError: raise` の外側（ADK 内）で吸われる |
| F-S-P2-202 | Low | 95 | 同じ入力で **root が workflow agent のとき**（`sequence` の子ツール）は `CancelledError` が `asyncio.run` から素通りし、CLI が **フルトレースバック**（100 行超）で exit 1。P2-R2.2 #2 で足した `except (KeyboardInterrupt, asyncio.CancelledError): raise` が、shutdown 由来でない CancelledError も再送出するため。exit 1 なので fail-open ではないが T-1 型 |
| F-S-P2-203 | Low | 85 | 3 ファイル目の `os.replace` が失敗すると 1〜2 ファイル目は差し替え済みで **部分適用**になる（`agent.py` 新 / `__init__.py` `.env.example` 旧）。メッセージはどれが差し替わったか言わない |
| F-S-P2-204 | Info | 90 | `--force` の差し替えは既存ファイルのモードを引き継がない（利用者が `chmod 600` した `agent.py` が 0644 に戻る。旧 `ftruncate` 方式では保たれていた） |
| F-S-P2-205 | Info | 80 | `MUTATE_ONLY` で部分実行しても最終行が `N/N mutations caught` になり、`result.txt` だけ見ると全件と区別できない |

---

## 1. F-S-P2-102 — defect-gone（実プロセス・台本つき FakeLlm でツールを呼ばせる）

`ex_<mode>/__init__.py` の `fn` が各モードの動作をし、`app()` を直接呼ぶ小スクリプトを `python -P` で実行して終了コードを取った:

| ツールの動作 | exit | stderr（ADK の警告を除く） | `Traceback` | トレース |
|---|---|---|---|---|
| `sys.exit(0)` | **1** | `exit0.jin: 実行に失敗しました（SystemExit: 0）。ref の関数が sys.exit() を呼んでいます。関数側を直してください` | 0 | 1 行（tool 呼び出し）。偽 `final` 無し |
| `sys.exit(3)` | **1** | 同上（`SystemExit: 3`） | 0 | 同上 |
| `os._exit(0)` | 0 | （無し） | 0 | 0 行（既存 `OLD` のまま） — Phase 1 §4 で受容済みの残存・変化なし |
| `raise KeyboardInterrupt` | 130 | `Root node R was cancelled.` | 0 | 1 行 — `except SystemExit` が飲んでいない |
| `raise RuntimeError("boom")` | 1 | `…（RuntimeError: boom）…` | 3（ADK の `logging` が `exc_info=True` で出す関数側のもの。`jin_cli` / `jin_adk` のフレームは 0 件・実測） | 2 行（`final` に `error_code`） |
| `raise asyncio.CancelledError()` | **0** | `Root node R was cancelled.` / `1 イベント（session: jin）` | 0 | 1 行 — **F-S-P2-201** |

同期 `run_model` に `sys.exit(0)` ツール → `RunError: 実行に失敗しました（SystemExit: 0）…`（実測）。
`typer.Exit` の MRO は `Exit → RuntimeError → Exception` なので `except SystemExit` に巻き込まれない（実測）。
`except` の順（`RunError` → `KeyboardInterrupt: raise` → `SystemExit`）は正しい。`run_model_async` の `except (KeyboardInterrupt, CancelledError)` 枝の
`writer.close()` と CLI `finally` の `sink.close()` は別オブジェクト（`TraceWriter.close` は `_pending=None` にするので二重呼び出しでも行は増えない）。

## 2. F-S-P2-101 — defect-gone

```
$ ls                       # anthropic/（raise RuntimeError('SHADOW…')）mcp/ research/
$ jin run $S/examples/pipeline/pipeline.jin go --model fake 2>&1 | grep -c SHADOW    → 0   exit=0
$ jin run $S/examples/researcher/researcher.jin go --model fake  （ref = cwd の research.*）→ SHADOW 0   exit=0
$ jin run badbuiltin.jin go --model fake（builtin: "nope"・cwd に mcp/）           → SHADOW 0   exit=1（BuildError）
$ jin run lazy.jin …（ref の関数が呼び出し時に cwd の lazydep を import）           → exit 1（文書どおりの残存: 窓の外では解決できない）
```

`_sys_path_window` の in-process 検査（`sys.path` を前後で比較）:

| ケース | 結果 |
|---|---|
| 窓の中で `ValueError` | 取り除かれる |
| 窓の中で `SystemExit` | 取り除かれる |
| 元から `sys.path` にある値 | 足さない・取り除かない（個数 1 のまま） |
| 同じ値を 2 回渡す | 中では 2 個、後は 0 個 |
| 窓の中で第三者が `remove` 済み | `suppress(ValueError)` で例外なし |
| 位置 | 末尾（`sys.path[-1]`） |
| `load_generated` で import 失敗（`RunError`） | 取り除かれる |
| 全ケース後 | `sys.path == 実行前` |

`hazard: _sys_path_window -> sys.path.append` / `guard: _sys_path_window -> sys.path.remove` は実在の関数・実コード（`test_guard_claims` 緑）。
CLI の `hazard: run -> sys.path.append` は消えており、`main.py` に `sys.path` への書き込みは無い。
不正 builtin の `mcp` 経路が消えたのは、CLI が `generate()` を `run_model_async` の**前**に済ませ、窓は `_import_agent_module` だけを包むため
（`runtime.py` docstring の「窓の中では `google.adk.tools` の遅延 import が任意依存を cwd から探す経路が残る」は、生成モジュールの
`from google.adk.tools import <有効な builtin>` に限られ、`__all__` 全走査はもう窓の外）。

## 3. F-S-P2-103 — defect-gone

隔離コピーの `agent.py.j2` の `_state_matches` に `_ = len(text)` を 1 行足して `-k reserved_names`:

```
E       AssertionError: RESERVED_NAMES に無い名前: ['len']
```

（元に戻して緑）。`_free_names` が拾う自由名は `AsyncGenerator BaseAgent Event EventActions InvocationContext ValueError _state_matches bool float int isinstance json object str` の 14 個で、全部 `RESERVED_NAMES` にある。
検査対象は `has_exit` のときだけ描画される `_state_matches` / `StateCheckAgent`（pipeline で描画される）。それ以外のテンプレート部分は
`LlmAgent(...)` 等の呼び出しだけで、その名前は元から `RESERVED_NAMES` にある。

## 4. F-S-P2-104 — defect-gone（残存 2 件は §6）

| ケース | 結果 |
|---|---|
| `.agent.py.jin-tmp` の残骸 + `--force` | `…/.agent.py.jin-tmp が残っています（前回の書き込みの残骸）…` exit 1。既存 3 ファイル無傷 |
| 既存 `agent.py` がリンク + `--force` | `agent.py がシンボリックリンクなので書き込みを拒みました` exit 1。victim 無傷・リンクも残る・tmp 残骸 0 |
| `--force` で 2 回目の `os.write` を ENOSPC | `WriteRefused: … No space left on device`。既存 3 ファイル **bytes 一致**・残骸 0 |
| tmp 名に攻撃者がリンクを仕込む + `--force` | `O_EXCL \| O_NOFOLLOW` が EEXIST → 「残っています」で拒否。victim 無傷 |
| 既存 `agent.py` がディレクトリ + `--force` | `os.replace` が EISDIR → `書き込みに失敗しました: Is a directory` exit 1・tmp 残骸 0 |
| `--force` で既存なし | tmp を使わず直接作成（`agent.py` `__init__.py` のみ） |
| 3 ファイル目の `os.replace` を EACCES | **部分適用**（→ F-S-P2-203） |
| 既存 0600 の `agent.py` を `--force`（umask 022） | 0644 になる（→ F-S-P2-204） |

TOCTOU: `lstat` で「リンクでない」と見てから `os.replace` までに `agent.py` をリンクへ差し替えられても、`replace` はリンクを辿らず
リンク自体を置き換えるので、リンク先は無傷（docstring の主張どおり）。`dir_fd` 相対で名前は定数（`__init__.py` / `agent.py` / `.env.example` /
`.<name>.jin-tmp`）なので `<out>` の外へ出る経路は無い。`guard: _move_into_place -> os.replace` / `guard: _open_for_write -> stat.S_ISLNK` は実コードに在る。

## 5. F-C-P2-103 — defect-gone

```
$ echo OLD > t.jsonl; chmod 644 t.jsonl; jin run pipeline.jin go --model fake --trace t.jsonl; stat -c %a t.jsonl   → 600
```

`os.fchmod` を `PermissionError` に差し替え → `トレースを開けません（Operation not permitted）…` exit 1。`O_CREAT` の後に失敗するので
新規の空 0600 ファイルが残り、fd は exit まで閉じられない（既存ファイルの内容は `O_TRUNC` 無しなので無傷）。Info。

## 6. 新規

### F-S-P2-201 【Medium / confidence 95】ツール関数の `asyncio.CancelledError` で、root が LlmAgent のとき exit 0 になる

- 再現（`ex_cancel/__init__.py` の `fn` が `raise asyncio.CancelledError()`、root = LlmAgent `R`）:

```
$ python -P run_cancel.py; echo "REAL exit=$?"
[1] R tool fn /circles/0/tools/0 {"query": "q"}
Root node R was cancelled.
1 イベント（session: jin）
REAL exit=0                    # トレースは tool 呼び出し 1 行だけ。final も error_code も無い
```

- 機序: ADK 2.8.0 `runners.py:1045-1065` `_cleanup_root_task` は root タスクの `CancelledError` を **`logger.warning('Root node %s was cancelled.')`
  で握って正常復帰**する（`Exception` は re-raise するが `CancelledError` は `BaseException` なので別枝）。`runner.run_async` が普通に終わるので
  `run_model_async` の新しい `except (KeyboardInterrupt, CancelledError)` には届かず、jin は成功として `RunResult` を返す
- 同期 `run_model` でも同じ（`rows=[('tool','R')]` で正常復帰）
- 脅威モデルは F-S-P2-102 と同じ（`ref` の作者が「失敗を成功に見せる」）。`sys.exit(0)` は塞がったが、`raise asyncio.CancelledError()` は
  1 行で同じ効果を得る。`os._exit(0)` と違いプロセスは正常に続くので、後続の「N イベント」表示や exit 0 が本物に見える
- 食い違う主張: `runtime.py` docstring / `decision-conformance.md` §4.1「実行中の `SystemExit` を成功扱いにしない」の意図（失敗を成功にしない）

**注意（実測）**: 「最後の行が tool 呼び出しで応答も `final` も無い」という形は、**`boundary.await` の正規の pause と同じ**である。
`researcher.jin` の `publish`（LongRunningFunctionTool）を台本 FakeLlm で呼ばせ、スタブが `None` を返す（= 人間の確認待ち）と:

```
[1] Researcher tool publish /circles/0/tools/3 {"text": "draft"}
1 イベント（session: jin）        REAL exit=0   rows=1（tool 呼び出し行だけ）
```

つまり「tool 行で終わって exit 0」だけを失敗にすると `await` を持つ全 `.jin` が exit 1 になる。検知は **long-running でない**呼び出しに限る。

修正案:
1. **jin 側の検知（long-running を除く）**: `_run_async` の終了後、最後の行が `tool` の呼び出し（`output is None`）で応答も `final` も無く、
   **かつ**その function_call の `id` が `Event.long_running_tool_ids` に無い（= `.jin` の `await` 対象でない）なら
   「ツール呼び出しの応答を待たずに実行が終わった」として `RunError`。ADK の cancel 吸収は LlmAgent 単体の root で起きるので、
   通常ツールでこの形になる正常経路は無い（正常終了はモデルのテキスト応答 = `final`、`await` の pause は long-running の呼び出し行）
2. ADK の warning を拾う案（`logging.getLogger("google_adk.google.adk.runners")` に一時ハンドラを付け `Root node … was cancelled` を見る）は
   トレースの形に依らないが ADK の内部文言に依存する。1 を主にして 2 を補助にする
3. テスト: `test_build_run.py` に「ツールが `CancelledError` → exit 1・1 行」、`test_runtime.py` に `run_model` → `RunError`。変異 1 件

### F-S-P2-202 【Low / confidence 95】root が workflow agent のとき、同じ入力でフルトレースバック（exit 1）

- 再現（`cancel2.jin`: `Seq`（sequence）→ `A`（ツール `fn` が `raise asyncio.CancelledError()`）→ `B`）:

```
$ python -P run_cancel2.py 2>&1 | grep -c Traceback; echo "REAL exit=$?"
[1] A tool fn /circles/1/tools/0 {"query": "q"}
Traceback (most recent call last): … 100 行超（typer → asyncio.run → runtime.run_model_async:276 → _run_async:230 → ADK … → ex_cancel2/__init__.py:3）
asyncio.exceptions.CancelledError
REAL exit=1
```

- 機序: SequentialAgent 配下では `CancelledError` が `runner.run_async` から**外へ出る**（root タスクの cancel ではなく子の例外として伝播）。
  `run_model_async` の `except (KeyboardInterrupt, asyncio.CancelledError): raise`（P2-R2.2 #2 で追加。shutdown 中の未処理例外を避けるため）が
  それをそのまま再送出し、`asyncio.run` も再送出し、CLI に `CancelledError` の受け口が無いので typer がトレースバックを出す
- P2-R2.2 #2 の判断（shutdown 由来の `CancelledError` を `RunError` にしない）は正しいが、**ツール由来**の `CancelledError` まで同じ枝に入っている。
  両者は `asyncio.current_task().cancelling()` で区別できる。実測（ツールを `asyncio.gather(create_task(...))` で別タスクにした最小形 =
  ADK の `handle_function_call_list_async` と同じ構造）:

```
  tool_raises（CancelledError を投げる）: except 内で cancelling() = 0   -> asyncio.run は CancelledError
  tool_exits（sys.exit(0)）:              except 内で cancelling() = 1   -> asyncio.run は SystemExit 0
```

修正案: `run_model_async` の枝を
```
except asyncio.CancelledError:
    writer.close()
    if asyncio.current_task().cancelling():   # shutdown 由来（SystemExit / KeyboardInterrupt の巻き添え）
        raise
    raise RunError("実行に失敗しました（CancelledError: ref の関数が asyncio.CancelledError を投げました）…")
```
にし、CLI `run` と同期 `run_model` にも保険として `except asyncio.CancelledError` → 1 行・exit 1 を置く。F-S-P2-201 の修正案 1 と合わせると
CancelledError の 2 経路がどちらも exit 1・1 行になる。変異 `RUN-cancelled-to-runerror` は「常に RunError」に戻す変異なので、
`cancelling()` 分岐を入れても赤のまま（shutdown 由来を RunError にすると caplog の asyncio ERROR が出る）。

### F-S-P2-203 【Low / confidence 85】3 ファイル目の `os.replace` 失敗で部分適用

```
>>> os.replace を 3 回目だけ EACCES にして write_project(p2, d, force=True)
WriteRefused(3rd replace): o3 への書き込みに失敗しました: Permission denied
  changed: ['Pipeline/agent.py'] | unchanged: ['Pipeline/__init__.py', '.env.example'] | leftovers: []
```

3 つを 1 つのトランザクションにはできない（`renameat2` の `RENAME_EXCHANGE` でも 2 つまで）。到達条件は「同じディレクトリに tmp を
作れて書けたのに `replace` だけ失敗」（ディレクトリの書き込み権限が途中で消える / EIO）で稀。修正はメッセージだけでよい:
「`<差し替え済みの名前>` は新しい内容、`<残り>` は前の内容のままです。`jin build --force` をやり直してください」。
`agent.py` を最後に差し替える順にすれば「`agent.py` が新しくて `__init__.py` が古い」より害の少ない組み合わせになる（`__init__.py` は不変の 3 行）。

### F-S-P2-204 【Info / confidence 90】`--force` が既存ファイルのモードを引き継がない

`umask 077` で作った `agent.py`（0600）を `umask 022` で `--force` すると 0644。旧方式（`ftruncate`）では既存の inode を書き換えるので
モードが保たれていた。生成物は秘密を含まないので実害は薄いが、挙動が変わったことは §2.23 か docstring に書く。
保ちたいなら `_open_for_write` で `os.fchmod(fd, stat.S_IMODE(info.st_mode))`（`info` は既に `lstat` 済み）。

### F-S-P2-205 【Info / confidence 80】`MUTATE_ONLY` の部分実行が全件と同じ最終行になる

`caught/len(mutations)` は絞り込み後の分母なので、`MUTATE_ONLY=CLI-no-cwd` で走らせても `1/1 mutations caught`。`result.txt` を
それで上書きすると全件実測に見える。最終行に `(MUTATE_ONLY: <names>)` を付けるか、`MUTATE_ONLY` 時は `result.txt` へ書かない運用にする。
今回の `result.txt`（66 行・全名前）と私の隔離コピー実行（66/66）は一致しているので、現状の申告は本物。

## 7. ハーネス

隔離コピーの `delivery/…/mutate_p2.py` を起動（`ROOT` = コピー側。さらにハーネス自身が `tempfile.mkdtemp` へ複製し `TMPDIR=<copy>/tmp`）:

```
copy: /tmp/jin-mutate-wfba0sbt
imports from: /tmp/jin-mutate-wfba0sbt/packages/jin-adk/src/jin_adk/__init__.py
imports from: /tmp/jin-mutate-wfba0sbt/packages/jin-cli/src/jin_cli/__init__.py
baseline: green (256 passed, 65 warnings in 2.46s)
…（64 件 RED (expected)、二層防御の 2 件 GREEN (expected)）
66/66 mutations caught          HARNESS EXIT 0
/tmp/jin-run-* : 実行前 0 → 実行後 0
```

`TMPDIR` はコピー内に作られ（`mkdir(exist_ok=True)`）、コピーごと `rmtree` される。`_is_red` / `_is_green` は round-1 のまま。
新規変異 `RUN-swallow-systemexit-at-runtime` / `RUN-swallow-systemexit-in-run_model` / `RUN-cancelled-to-runerror` /
`RUN-cwd-stays-after-import` / `RUN-cwd-first` / `BUILD-truncate-in-place` / `BUILD-replace-early` / `CLI-trace-keep-existing-mode` は
いずれも `N failed` の summary で赤。網に無いのは F-S-P2-201 / 202（`CancelledError` の 2 経路）。

## 8. 総評

round-1 の 4 件と F-C-P2-103 は**全部 defect-gone**で、実装は round-1 で指摘した形（窓・tmp + replace・AST での列挙固定）どおりに入っている。
ラウンド 2 が持ち込んだ穴は `CancelledError` の扱いに集中している: root の形によって **exit 0（201）** か **フルトレースバック（202）** の
どちらかになり、どちらも `sys.exit` を塞いだときの規律（失敗は exit 1・1 行）から外れる。201 は ADK が root の cancel を warning で握る仕様に
起因するので jin 側で「ツール呼び出しの応答無しで終わった」を失敗にする検知が要る。202 は `Task.cancelling()` で 1 分岐。
どちらも `.jin` / `ref` の作者が意図的にやる場合の話で、通常の利用で踏む経路ではない。

DONE_WITH_CONCERNS
