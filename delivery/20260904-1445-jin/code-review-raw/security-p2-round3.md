# Stage 5 security review — Phase 2 修正ラウンド 3（最終確認・範囲限定）

- 対象: `feat/jin-phase2-adk` 作業ツリー（修正ラウンド 3 反映後・2026-09-06 実測）。隔離コピーを作り直し
  （`__pycache__` 除去、`PYTHONPATH=<copy>/packages/*/src`、`jin_adk.__file__` がコピー側）。CLI は `python -P` で起動。
  **実ツリーはこのレポート以外変更していない**
- baseline: **799 passed**。変異ハーネス（隔離コピーから起動・自己複製・`TMPDIR` コピー内）: **70/70 caught**、`/tmp/jin-run-*` 残骸 0
- 判定対象: F-S-P2-201 / 202 / 203 / 204 / 205 と、ラウンド 3 が持ち込んだ回帰の有無

## 0. 要約

| finding | 判定 | 一言 |
|---|---|---|
| F-S-P2-201 ツール由来 `CancelledError`（root=LlmAgent）が exit 0 | **defect-gone** | 実プロセスで **exit 1**・1 行（`ツール 'fn' が応答を返さずに実行が終了しました…`）・トレースバック無し・「N イベント」無し。`run_model_async` 単体（pygls 経路・保険なし）でも `RunError` |
| F-S-P2-202 同（root=sequence）がフルトレースバック | **defect-gone** | exit 1・1 行（`…（CancelledError: ref の関数が asyncio.CancelledError を投げました）…`）・`Traceback` / `asyncio.exceptions` 0 件。`run_model_async` 単体でも `RunError`。外からの cancel（`asyncio.timeout`）は `TimeoutError` として伝播 = `Task.cancelling()` の分岐が正しく効いている |
| F-S-P2-203 部分適用が黙る | **defect-gone** | 差し替え順は `__init__.py` → `.env.example` → `agent.py`（実測）。3 回目の `replace` 失敗で `agent.py は前の内容のまま`・他 2 つは新・文言に両方を列挙 |
| F-S-P2-204 既存 mode を引き継がない | **defect-gone** | `agent.py` 0600 / `.env.example` 0640 が `--force` 後も保たれる（実測）。ただし `fchmod` 失敗時に残骸が出る → F-S-P2-301 |
| F-S-P2-205 `MUTATE_ONLY` の最終行 | **defect-gone** | `1/1 mutations caught (subset of 70; MUTATE_ONLY=…)`。存在しない名前は rc 1 |
| 誤検知（並列ツール / `transfer_to_agent` / summon / `await` の pause） | **無し** | 4 経路すべて exit 0（§2） |
| ラウンド 3 が持ち込んだ回帰 | **1 件（Low）** | F-S-P2-301: tmp の `fchmod` 失敗で `.<name>.jin-tmp` と fd が残る |

**新規**

| ID | severity | conf | 一言 |
|---|---|---|---|
| F-S-P2-301 | Low | 95 | `_open_for_write` が tmp を `os.open` した**後**に `os.fchmod` し、失敗すると tmp の fd と `.<name>.jin-tmp` が片付けられない（`opened` に積む前に例外）。次の `--force` は「残骸が残っています」で拒まれる。既存ファイルは無傷 |

## 1. 実プロセスの終了コード（`python -P`・台本つき FakeLlm でツールを呼ばせる）

| 入力 | exit | stderr（ADK の警告と `was cancelled` を除く最終行） | `Traceback` / `asyncio.exceptions` | 「N イベント」行 | トレース |
|---|---|---|---|---|---|
| root=LlmAgent、ツールが `raise asyncio.CancelledError()` | **1** | `llm_cancel.jin: ツール 'fn' が応答を返さずに実行が終了しました（キャンセルされた可能性。ref の関数が asyncio.CancelledError を投げていないか確認してください）` | 0 / 0 | 無し | 1 行（tool 呼び出し） |
| root=sequence、子ツールが同上 | **1** | `seq_cancel.jin: 実行に失敗しました（CancelledError: ref の関数が asyncio.CancelledError を投げました）。--trace で…` | 0 / 0 | 無し | 1 行 |
| root=LlmAgent、`sys.exit(0)` | 1 | `…（SystemExit: 0）。ref の関数が sys.exit() を呼んでいます…` | 0 / 0 | 無し | 1 行 |
| root=sequence、`sys.exit(0)` | 1 | 同上 | 0 / 0 | 無し | 1 行 |
| `raise KeyboardInterrupt` | 130 | （無し・素通し） | 0 / 0 | 無し | 1 行 |
| `raise RuntimeError("boom")` | 1 | `…（RuntimeError: boom）…` | 3（ADK の logging・jin のフレーム無し）/ 0 | 無し | 2 行（`final` に `error_code`） |
| `await` の正規 pause（`publish` が `None` を返す） | **0** | `1 イベント（session: jin）` | 0 / 0 | あり | 1 行（tool 呼び出し） |

`run_model_async` 単体（`asyncio.run` を素で呼ぶ・保険なし）:

```
llm_cancel: RunError: ツール 'fn' が応答を返さずに実行が終了しました…
seq_cancel: RunError: 実行に失敗しました（CancelledError: ref の関数が asyncio.CancelledError を投げました）…
llm_exit:   SystemExit 0                          # 仕様どおり（asyncio が再送出。包むのは呼び出し側・docstring に明記）
external cancel（asyncio.timeout(0.5) で遅いツールを切る）: TimeoutError propagated
```

最後の行が `Task.cancelling()` 分岐の実証: 外からの cancel は `cancelling() ≥ 1` で再送出され `RunError` にならない。
ツール由来（`cancelling() == 0`）だけが `RunError` になる。shutdown 由来（`sys.exit`）は上の表で `SystemExit` の 1 行になっており、
`CancelledError` 由来の文言に化けていない。

## 2. 「応答の無い function_call」検出の誤検知

`_run_async` は `TRANSFER_TOOL_NAME` を除く function_call の `id` を `pending` に入れ、function_response の `id` で消し、
`Event.long_running_tool_ids` に入った id を除外する。誤検知しうる 4 形を台本 LLM（`BaseLlm` を直接実装）で実測:

| 形 | 結果 |
|---|---|
| 並列ツール呼び出し（1 event に function_call 2 個 → 応答は別 event） | exit 0・`[1] a in [2] b in [3] a out [4] b out [5] final` |
| `transfer_to_agent`（delegate） | exit 0・`[1] R transfer D /circles/0/delegate/0` → `[2] D final` |
| summon（`AgentTool` の呼び出し） | exit 0・`[1] R tool Summ … [2] R tool Summ {"result": "done"} [3] final` |
| `await`（LongRunningFunctionTool が `None` を返す正規 pause） | exit 0・tool 呼び出し 1 行（§1 の表） |

`id` を持たない function_call（FakeLlm が id 無しで出す → ADK が付与）は `call.id` が真になってから `pending` に入る。
id 無しのまま来た呼び出しは検知対象外（見逃し側に倒れる。ADK 2.8.0 は常に付与するので実害なし）。

## 3. F-S-P2-203 / 204 / 205

```
>>> 既存 3 ファイルを "hand edited" にし、3 回目の os.replace を EACCES に
WriteRefused: o/Pipeline/agent.py の差し替えに失敗しました: Permission denied。o/Pipeline/__init__.py / o/.env.example は新しい内容、
              o/Pipeline/agent.py は前の内容のままです（部分適用）。jin build --force を再実行してください
  replace order: ['__init__.py', '.env.example', 'agent.py']    agent.py old / __init__ new / env new   leftovers: []
>>> agent.py 0600 / .env.example 0640 → --force 成功後: agent.py 0o600  .env.example 0o640
$ MUTATE_ONLY=nope …          → !! MUTATE_ONLY に存在しない変異名: ['nope']   rc=1
$ MUTATE_ONLY=CLI-accept-any-model … → 1/1 mutations caught (subset of 70; MUTATE_ONLY=CLI-accept-any-model)   rc=0
```

### F-S-P2-301 【Low / confidence 95】tmp の `fchmod` 失敗で残骸と fd が残る（ラウンド 3 の F-S-P2-204 修正が持ち込んだ）

- `build.py` `_open_for_write`: tmp を `os.open` → `os.fchmod(fd, S_IMODE(info.st_mode))` → `return (fd, tmp)`。`fchmod` が失敗すると
  例外は `try` の外で上がり、呼び出し側の `opened` / `open_fds` にはまだ積まれていないので `except BaseException` の片付けが届かない
- 実測（`os.fchmod` を `PermissionError` に差し替え）:

```
fchmod fail -> WriteRefused: o への書き込みに失敗しました: Operation not permitted
agent.py intact: True | leftovers: ['.__init__.py.jin-tmp']        # 次の --force は「残骸が残っています」で拒まれる
```

- 到達条件: 自分が作った tmp に対する `fchmod` が失敗する = 実質 EPERM が出ない通常環境では起きない（NFS の一部・`setgid` ディレクトリで
  グループビットを立てる場合など）。既存ファイルは無傷で fail-closed。Low
- 修正: `fchmod` を `try` に入れ、失敗時に `os.close(fd)` + `os.unlink(tmp, dir_fd=dir_fd)` してから `WriteRefused`（または `fchmod` を
  `write_project` 側に移して `opened` に積んだ後で行う）。テストは `os.fchmod` を差し替えて残骸 0 を assert

## 4. 回帰の探索（ラウンド 3 の変更）

- `pyproject.toml` の `pythonpath = ["."]`: pytest 実行時にだけリポジトリ直下が `sys.path` に入る。製品コード（`jin_cli` / `jin_adk`）の
  import 経路は変わらない。`jin run` の cwd 窓とは無関係（実プロセス実測は `-P` + `PYTHONPATH` のみ）
- `agent.py` を最後に差し替える順: `sorted(opened, key=lambda o: o[5] == "agent.py")` は安定ソートなので他 2 つの相対順は保たれる（実測順のとおり）
- 実プロセス版テスト（`FakeLlm` 差し替えスクリプトを `sys.executable -P -c` で実行）: CLI に台本の口は無い（`main.py` に環境変数の読み取り無し）
- `run` の `except` 順: `RunError` → `KeyboardInterrupt: raise` → `asyncio.CancelledError` → `SystemExit`。`typer.Exit` は `RuntimeError` 系で無関係。
  `KeyboardInterrupt` は exit 130 で素通し（上の表）
- `_run_async` の `writer.close()` は完走時のみ、例外時は `run_model_async` 側で 1 回。二重呼び出し無し
- ハーネス: 新規 4 変異（`RUN-ignore-unanswered-tool` / `RUN-await-pause-as-failure` / `RUN-cancelled-passthrough` / `CLI-cancelled-traceback`）を含む 70/70、
  判定は `returncode == 1 ∧ failed` のまま

## 5. 総評

F-S-P2-201 〜 205 は**すべて defect-gone**。`CancelledError` の 2 経路は CLI と `run_model_async` 単体の両方で exit 1・1 行になり、
`await` の pause / 並列呼び出し / transfer / summon を誤検知しない。外からの cancel は `Task.cancelling()` で正しく素通しされる。
ラウンド 3 の新規は F-S-P2-301（tmp の `fchmod` 失敗で残骸・Low・既存は無傷）の 1 件だけで、コミットの前提条件にはしない。

DONE_WITH_CONCERNS
