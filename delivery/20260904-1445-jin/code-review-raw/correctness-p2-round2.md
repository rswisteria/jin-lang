# Stage 5 review — correctness 再レビュー（Phase 2 / 修正ラウンド 2）

- 対象: `feat/jin-phase2-adk` 作業ツリー（修正ラウンド 2 反映後）。判定対象は前回の新規 3 件（F-C-P2-101 / 102 / 103）と
  F-C-P2-002 の文言、ラウンド 2 全体の変更（`phase2-fix-round-2-instructions.md` A〜D・`implementation-notes.md` P2-R2.1 / P2-R2.2）
- 方法（前回と同じ）:
  1. 隔離コピーを作り直し（`scratchpad/review-correctness-r2/`・`git ls-files` で複製・`PYTHONPATH` でコピー側を優先・`jin_adk.__file__` で確認）。
     素の状態は **787 passed in 25.27s**
  2. ラウンド 0 / 1 の再現スクリプト `exp1`〜`exp4` をそのまま再実行し、ラウンド 2 の新規コード向けに `exp5_round2.py` を書いて実測
     （`classify` の同居 6 パターン・並列 transfer の end-to-end・`_sys_path_window` の重複 / 例外 / 実行中・`write_project` の tmp+replace 6 経路・
     `_open_trace` の既存ファイル・CLI の `SystemExit`・`RESERVED_NAMES` と生成物の自由名・`run_model_async` のキャンセル）
  3. 変異: ラウンド 0 / 1 で緑だった 9 件（M1 / M2 / M3 / M21 / M22 / M34 / M47 / M48 / M50）と、ラウンド 2 の新規コード向け 12 件（R2-1〜R2-12）を
     `mutate_r2.py` で全スイートに対して実行
  4. 実ツリーは一切変更していない（本ファイルの追加のみ）。終了後に `diff -q` でコピーの 6 ファイルが実ツリーと一致することを確認
- 自己申告（P2-R2.1 / R2.2）は読んだが根拠にしていない

## 要約

| 分類 | 件数 | ID |
|---|---|---|
| defect-gone | 4 | F-C-P2-101、F-C-P2-102、F-C-P2-103、F-C-P2-002（文言） |
| 残存 | 0 | — |
| 新規 | 1（低） | F-C-P2-201（`--force` の差し替えで既存ファイルの権限が 0644 に戻る） |

ラウンド 0 / 1 の全 finding（001〜024・101〜103）は現在の作業ツリーで再現しない（`exp1`〜`exp4` の出力は前回の defect-gone 判定と同一）。
P2-R2.2 の 7 件はいずれも妥当（§4）。変異 21 件（旧 9 + 新 12）はすべて赤（§2）。

---

## 1. 前回 finding ごとの判定

### F-C-P2-101 transfer と同居した他ツールの応答行 → **defect-gone**
- 修正: `trace.classify` が transfer 分岐で早期 return せず、`TRANSFER_TOOL_NAME` 以外の応答を `tool` 行にしてから `transfer` 行（`trace.py:214-280`）
- 実測（`exp4` 4a 再実行 / `exp5` 5a・5b）:
  - `classify` 単体: `[('tool', 'web_search', {'result': 'r'}), ('transfer', 'W', None)]`
  - end-to-end（1 応答に `web_search` + `transfer_to_agent` の function_call を返す LLM）:
    `tool web_search`（呼び出し）→ `tool web_search`（応答 `{'result': 'stub-search:q'}`）→ `transfer W /circles/0/delegate/0` → `final`（W）。`unresolved: []`
  - 同居パターン: text + call + transfer_call → `model, tool`（transfer の function_call は行にしない）/ text + response + transfer → `model, tool, transfer` /
    transfer + escalate → `transfer, escalate` / transfer の actions だけ（parts 無し）→ `transfer` のみ（余計な `model` 行なし）/ transfer の function_call だけ → `[]`
- 仕様 §2.4 の `transfer` 行に同居の扱いと行順を追記済み。変異 R2-1（早期 return の再導入）/ R2-2（行順を逆に）は §2 の表

### F-C-P2-102 `CancelledError` を `RunError` に化かす → **defect-gone**
- 修正: `runtime.py:284-288` `except (KeyboardInterrupt, asyncio.CancelledError): writer.close(); raise`
- 実測（`exp5` 5h）: `run_model_async` をタスクにして `cancel()` → `CancelledError propagated`（`RunError` にならない）
- `test_cancelled_error_propagates_from_run_model_async` は LLM 呼び出しの最中（`Hanging.generate_content_async` が `asyncio.Event().wait()`）で
  `task.cancel()` し `pytest.raises(asyncio.CancelledError)` で待つ。キャンセルが Runner の中まで届く経路を本当に見ている。変異 R2-3 は §2 の表

### F-C-P2-103 既存トレースの権限 → **defect-gone**
- 修正: `main.py:662-663` `_open_trace` が open 後に `os.fchmod(fd, 0o600)`
- 実測（`exp5` 5e）: 既存 0644 のファイルを指定 → `existing mode: 0o600`、内容は `'OLD\n'` のまま（切り詰めない）。`exp4` 4j も `mode 0o600`。
  §6 手順 7 を「新規は `O_CREAT` の mode、既存でも `fchmod`」に更新済み。変異 R2-6 は §2 の表

### F-C-P2-002 文言 → **defect-gone**
- 実測（`exp4` 4h）: `unresolved` の文言が「ADK 上で同じ名前になるので片方が呼べません（どの tools[] か決められないので pointer は null）。ref の別名 import は FunctionTool.name == func.__name__ を変えません」に

## 2. 変異検証（隔離コピー・全スイート・`-x`）

素の状態: **787 passed in 25.27s**。ハーネス `scratchpad/review-correctness-r2/mutate_r2.py`。`-x` で最初の赤しか出ないので、
guard-claims（`tests/contract/test_guard_claims.py`）が先に赤になった 3 件（R2-5 / R2-6 / R2-9）と R2-3 は、その契約テストを除いた
意味論のテストだけでも赤になるかを別に再実行した（右列の括弧）。

| # | 対象 | 注入した変異 | 結果（全スイート・`-x`） |
|---|---|---|---|
| M1 | `_state_matches` | bool 除外を消す | RED（snapshot。ラウンド 1 で `[1-true-False]` / `[0-false-False]` が意味論でも赤を確認済み） |
| M2 | `_callback_lines` | 先頭の 1 つに潰す | RED `test_two_guards_of_the_same_kind_become_a_list_in_declaration_order` |
| M3 | `bind_tools` | 添字を常に 0 | RED `test_tool_call_rows_use_the_declared_index_not_the_first_tool` |
| M21 / M22 | `_validate_flow_circle` | instruction / delegate の検査を無効化 | RED（fixture `flow_circle_with_instruction` / `_delegate`） |
| M34 | `classify` | `ts = 0.0` | RED `test_ts_is_taken_from_the_event_timestamp` |
| M47 / M48 | `_emit_workflow_agent` / `_emit_llm_agent` | description を落とす / sub_agents 逆順 | RED `test_flow_circle_description_and_delegate_order_survive_generation` |
| M50 | `_state_matches` | `expected.strip()` を外す | RED（snapshot。ラウンド 1 で `[ yes-yes-True]` 等が意味論でも赤を確認済み） |
| R2-1 | `classify` | transfer 分岐で早期 return（F-C-P2-101 再導入） | **RED** `test_transfer_keeps_the_sibling_tool_response_rows` |
| R2-2 | `classify` | transfer 行を tool 応答行の前に出す（行順） | **RED** 同上（行順まで固定されている） |
| R2-3 | `run_model_async` | `CancelledError` 分岐を消す（F-C-P2-102 再導入） | **RED** `test_system_exit_in_a_tool_at_runtime_is_a_run_error`（`-k cancelled_error` 単体でも `test_cancelled_error_propagates_from_run_model_async` が赤） |
| R2-4 | `_sys_path_window` | `finally` で外さない | **RED** `test_cwd_cannot_supply_an_uninstalled_optional_dependency_during_the_run`（別プロセス） |
| R2-5 | `_sys_path_window` | `insert(0)` にする | **RED** guard-claims（除外しても `test_extra_sys_path_is_present_only_during_the_import` / `test_run_adds_cwd_to_sys_path` の 2 件が赤） |
| R2-6 | `_open_trace` | `fchmod` を消す（F-C-P2-103 再導入） | **RED** guard-claims（除外しても `test_existing_trace_file_is_made_owner_only` が赤） |
| R2-7 | CLI `run` | `except SystemExit` を消す | **RED** `test_tool_sys_exit_at_runtime_is_a_failure` |
| R2-8 | `run_model`（同期） | `except SystemExit` を消す | **RED** `test_system_exit_in_a_tool_at_runtime_is_a_run_error` |
| R2-9 | `_move_into_place` | 一時ファイルを差し替えない | **RED** guard-claims（除外しても `test_force_overwrites_the_three_generated_files` ほか 3 件が赤） |
| R2-10 | `write_project` | 失敗時に一時ファイルを消さない | **RED** `test_refuses_when_only_env_example_exists_and_leaves_nothing_behind` |
| R2-11 | `RESERVED_NAMES` | `isinstance` を外す | **RED** `test_reserved_generated_name_is_rejected[isinstance]` |
| R2-12 | `classify` | `transfer_to_agent` の function_call を tool 行にする | **RED** `test_delegate_transfer_end_to_end_has_no_stray_tool_row` |

21 件すべて赤。ラウンド 0 / 1 で塞いだ穴はラウンド 2 で緑に戻っていない。

## 3. ラウンド 2 の新規コード（実測して問題なかったもの）

- **`runtime._sys_path_window`**（`exp5` 5c）: 末尾に足し（`inside tail: [..., '/x/two']`）、抜けると `sys.path` は完全に元どおり（例外時も）。
  元からある値（STUBS）は足さず取り除かない。`extra_sys_path` 内の重複は 2 回足して 2 回取り除くので残らない。
  実行中の観測: `FakeLlm` の中で `STUBS in sys.path` は **False**（import 窓の外）で、ツール関数は `sys.modules` 経由で動き `rows: 1` で完走。
  窓の中で import 先モジュールが同じ entry を自分で足した場合は 1 つ残る（それは呼び出し先の変更であり、窓が消すべきものではない）
- **`build.write_project` の tmp + `os.replace`**（`exp5` 5d）: 初回書き込みの `written` は 3 ファイルの本来のパス。`--force` 無しで既存 → 拒否・既存無傷・tmp 無し。
  `--force` → 差し替え後に tmp 無し。3 つ目（`.env.example` がリンク）で拒否 → `agent.py` 無傷・リンク先無傷・tmp 無し。
  残骸 `.agent.py.jin-tmp` があれば拒否し、残骸も既存も触らず、先に開いた `.__init__.py.jin-tmp` は片付く。
  `os.write` に ENOSPC を注入 → `WriteRefused`（トレースバック無し）・既存無傷・leftovers は `__init__.py` / `agent.py` のみ
- **CLI `run` の `SystemExit`**（`exp5` 5f）: ツール関数の `sys.exit(0)` → exit 1・stderr に `実行に失敗しました（SystemExit: 0）`・トレースバック無し。
  トレースは `finally` で閉じられ、それまでの行（`tool die` の呼び出し行）が残り mode 0600。同期 `run_model` は `RunError`
- **`RESERVED_NAMES`**（`exp5` 5g）: 生成物の `_state_matches` / `StateCheckAgent` から Load 文脈の `Name` を集め、局所名
  （`actual` / `ctx` / `expected` / `key` / `matched` / `self` / `text` / `value`）を除いた自由名は **すべて `RESERVED_NAMES` に含まれる**（差集合は空）。
  局所名と同じ circle 名（`value`）は衝突しない: import でき `_state_matches('true', True) = True`。`test_reserved_names_cover_every_free_name_the_template_uses` は
  同じ集合を非空虚（`{"isinstance", "str", "ValueError", "json", "BaseAgent"} <= free`）つきで固定している。変異 R2-11 は §2 の表
- **`TraceSink` Protocol**: `write(text, /) -> int` のみ。`TraceWriter` は `write` しか呼ばず、`_LazyTruncateSink` / `IO[str]` の両方が適合する（`exp5` 5f で CLI 経路、`exp2` で `IO[str]` 経路を実行）

## 4. P2-R2.2（指示と違う判断）7 件の判定

| # | 判断 | 判定 | 根拠 |
|---|---|---|---|
| 1 | `guard: run -> SystemExit` は書かず、テスト + 変異で固定 | **正しい** | 記法上の制約。変異 R2-7 / R2-8 が赤（§2） |
| 2 | `CancelledError` の再送出を追加 | **正しい**（前回の F-C-P2-102 そのもの） | `exp5` 5h・変異 R2-3 |
| 3 | `CLI-cwd-first` → `RUN-cwd-first` | **正しい** | CLI に `sys.path` 操作が無くなった（`main.py` に `sys.path` の参照が無いことを grep で確認）。変異 R2-5 が赤（§2） |
| 4 | append 実装への差し戻しは `RUN-cwd-stays-after-import` で代替 | **正しい** | 変異 R2-4（`finally` で外さない）が赤（§2） |
| 5 | F-S-P2-104 は tmp + `os.replace` | **正しい**（喪失経路を消す方が文言より強い） | `exp5` 5d の 6 経路 |
| 6 | fmt --check のテストを別に足す | correctness の対象外 | — |
| 7 | `MUTATE_ONLY` | correctness の対象外 | — |

## 5. 新規 finding

### F-C-P2-201 — `--force` の差し替えで既存ファイルの権限が 0644 に戻る
- confidence: **100**（`exp5` 5d: `agent.py` を 0600 にしてから `write_project(force=True)` → `mode after replace: 0o644`）
- 場所: `packages/jin-adk/src/jin_adk/build.py:157-159`（一時ファイルを `0o644` で作る）/ `:169-175`（`os.replace` で既存を置き換える）
- 何が起きるか: ラウンド 1 までの `ftruncate` 方式は既存 inode を書き換えるので所有者・権限が保たれたが、tmp + `os.replace` は新しい inode に置き換えるので
  利用者が `chmod 600` していた `agent.py` / `.env.example` が `0644 & ~umask` に戻る。`.env.example` は値を書かない雛形なので実害は小さいが、
  `docs/spec/adk-mapping.md` §3.1 / `build.py` の docstring はこの挙動変化を書いていない
- 修正案: tmp を作る前に既存の `st_mode` を `lstat` で読み、`os.fchmod(fd, mode)` で引き継ぐ（新規は従来どおり 0644）。または仕様に「`--force` は権限を引き継がない」と明記
- 分類: 新規（ラウンド 2 の F-S-P2-104 対応が持ち込んだ挙動変化・低）
