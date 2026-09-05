# Stage 5 review — correctness 再レビュー（Phase 2 / 修正ラウンド 1）

- 対象: `feat/jin-phase2-adk` 作業ツリー（修正ラウンド 1 反映後・`git status` の全変更 + untracked）。
  判定対象は前回の F-C-P2-001〜024 と、修正が新たに持ち込んだ欠陥（`F-C-P2-1NN`）
- 方法（前回と同じ）:
  1. 隔離コピーを作り直し（`scratchpad/review-correctness-r1/`・`git ls-files` で複製・`PYTHONPATH` でコピー側を優先。
     `jin_adk.__file__` がコピー側を指すことを起動時に確認）。素の状態は **770 passed in 23.87s**
  2. 前回の再現スクリプト `exp1_collisions.py` / `exp2_trace.py` / `exp3_misc.py` をそのまま再実行し、加えて
     ラウンド 1 の新規コード向けに `exp4_newcode.py` を書いて実測（`classify` の行順・transfer と他応答の同居・
     `_check_root_is_not_a_child` 3 経路・`_adk_tool_name` の重複 4 形・`run_model_async`・`_LazyTruncateSink`）
  3. 前回緑のまま生き残った変異（M2 / M3 / M21 / M22 / M34 / M47 / M48）と snapshot だけが守っていた変異（M1 / M50）を
     同じハーネス（`mutate.py`）で再実行し、全スイートで赤になるかを実測。M1 / M50 は snapshot を除いた意味論テストだけでも赤になるかを別に確認
  4. 実ツリーは一切変更していない（本ファイルの追加のみ）
- 自己申告（implementation-notes P2-R1.1 / R1.2 / R1.7）は読んだが根拠にしていない

判定の語: **defect-gone** = 前回の再現入力で欠陥が消えたことを実測 / **残存** = 欠陥または一部が残る / **新規** = 修正が持ち込んだもの。

## 要約

| 分類 | 件数 | ID |
|---|---|---|
| defect-gone | 22 | 001 002 003 004 005 006 007 008 009 010 011 012 013 014 015 016 017 018 019 020 021 024 |
| 残存（記録のみで妥当・条件付き） | 2 | 022（記録のみ・指示書 C）、023（仕様に追記済み・設計どおり） |
| 新規 | 3 | F-C-P2-101（transfer と同居した他ツールの応答行が消える）、F-C-P2-102（`CancelledError` を `RunError` に化かす）、F-C-P2-103（既存トレースファイルの権限は 0600 にならない） |

修正が持ち込んだ欠陥で「実際に誤った結果が出る」のは F-C-P2-101 の 1 件（confidence 100・end-to-end で実測）。
残り 2 件は低。P2-R1.2 の 7 件はいずれも妥当（下記 §3）。

---

## 1. 前回 finding ごとの判定

### F-C-P2-001 `ref` の callable 名 = builtin 名 → **defect-gone**
- 修正: `codegen.generate` の `taken` に `_builtin_names(model)`（別 circle なら別名 import）+ 同 circle は F-C-P2-002 の重複検査
- 実測: 前回の再現 1b（同 circle）は `BuildError ... tools[0] と tools[1] は ADK 上で同じツール名 'google_search'`。
  別 circle（`exp4` 4g）は `from mytools import google_search as mytools__google_search` になり、
  `R.tools = [GoogleSearchTool]` / `S.tools = [(FunctionTool, 'google_search')]` と両方が生きる
- P2-R1.2 #2（BuildError ではなく別名化）は妥当。別 circle では ADK のツール名空間が別なので実害が無く、同 circle は #1 の検査が拒む

### F-C-P2-002 同じ ADK ツール名が 1 circle に 2 つ → **defect-gone**（コンパイル時に判定できる範囲）
- 修正: `_validate_core_circle` の `_adk_tool_name` 集計 → `BuildError`（pointer は 2 つ目）
- 実測（`exp3` 3a / `exp4` 4f）: 同一 ref 2 回・別モジュール同名・builtin と ref 同名・summon と ref 同名の 4 形すべて `BuildError`（pointer `/circles/0/tools/1`）
- 残る経路（実装者も明記・P2-R1.2 #1）: 利用者モジュールが `search_again = web_search` と束縛していると attribute 名が違うので
  コンパイル時検査を通り、実行時の `FunctionTool.name` は両方 `web_search` になる。`exp4` 4h: `jin build` は通り、`jin run` は
  tool 行を `pointer: null` にして `unresolved` に「同名の ADK ツール 'web_search' が 2 つ以上あり」を出す。
  これは import なしには判定できない（`jin build` が import しないのは設計）ので **残存ではなく既知の限界**として扱う。
  ただし stderr の文言は「どの tools[] か決められない」であり、「片方が呼べない（ADK が shadow した）」という実害を伝えていない
  （低・F-C-P2-002 の文言指摘は未対応。§3.1 の表 `adk_tool_name_duplicate` 行にも実行時の別名束縛の残存は書かれていない）

### F-C-P2-003 circle 名 = builtin 名 → **defect-gone**
- 実測（`exp1` 1a）: `BuildError: circle 名 'google_search' は builtin ツール 'google_search' の import 名と衝突します`（pointer `/circles/1/name`）

### F-C-P2-004 delegate transfer の余計な `tool` 行 → **defect-gone**
- 実測（`exp2` 2a）: 行は `transfer Worker /circles/0/delegate/0` → `final`（Worker）の 2 行だけ。`unresolved: []`。
  `test_runtime.py::test_delegate_transfer_end_to_end_has_no_stray_tool_row` が end-to-end で固定

### F-C-P2-005 / F-C-P2-018 `exit_loop` の応答行と `escalate` 2 種 → **defect-gone**
- 実測（`exp2` 2b）: `tool exit_loop`（呼び出し）→ `tool exit_loop`（応答・`output: {"result": null}`）→ `escalate A /circles/1`。
  `docs/spec/adk-mapping.md` §2.4 の表は `escalate` を 2 行に分け、`trace.KIND_POINTERS` と突合される

### F-C-P2-006 summon 先が黒箱 → **defect-gone**（仕様に明記）
- §2.4 / §6「summon 先の内部イベントは行にならない」、`phase2-handoff.md` §6 に Phase 3 への申し送り。挙動自体は ADK 由来で変わらない（`exp2` 2c は前回と同じ 3 行）

### F-C-P2-007 text + function_call → **defect-gone**
- 実測（`exp2` 2d）: `model`（`output: "I will search"`）→ `tool web_search` の 2 行。`exp4` 4c: `model → tool → escalate` の順

### F-C-P2-008 `equals` の前後空白 → **defect-gone**
- 実測（`exp2` 2f）: `_state_matches(' yes', ' yes') = True`。model.md §3.4 の表は「両辺」に。M50（`expected.strip()` を外す）は
  全スイートで赤（結果は §2 の表）

### F-C-P2-009 `--trace` が BuildError で空になる → **defect-gone**
- 実測（`exp3` 3e）: `two_out_states.jin` で exit 1 のあと trace は `b'{"keep": true}\n'` のまま。`exp4` 4j: 行を 1 つも書かず `finish()` → 0 バイト（0 行成功の仕様どおり）、
  `open` + `close` だけ → 旧内容そのまま、1 行書く → 旧内容が消えて新しい 1 行

### F-C-P2-010 同種 guard 複数 → **defect-gone**（テスト追加）
- M2 が `test_two_guards_of_the_same_kind_become_a_list_in_declaration_order` で赤

### F-C-P2-011 `bind_tools` の添字 → **defect-gone**（テスト追加）
- M3 の結果は §2 の表（`test_tool_call_rows_use_the_declared_index_not_the_first_tool` が `publish` = tools[3] を見る）

### F-C-P2-012 bool を数値に一致させない枝 → **defect-gone**（テスト追加）
- `test_state_matches_semantics` に `(1,"true",False)` / `(0,"false",False)` / `(1,"1",True)`。M1 の意味論のみ再実行は §2 の表

### F-C-P2-013 flow circle の instruction / delegate / await → **defect-gone**
- fixture `flow_circle_with_instruction` / `flow_circle_with_delegate` を追加。M21 / M22 の結果は §2 の表。
  `await` 枝は残した（P2-R1.2 #3）: `jin check` 経由では JIN070 が先に落ちるが `JinFile.model_validate` 直呼びでは到達する、
  §3.1 の表から `await` を外して注記 — 妥当。前回の指摘は「到達不能なら消すか、到達不能である旨を書く」であり、後者を満たす

### F-C-P2-014 `ts` → **defect-gone**（テスト追加・M34 は §2 の表）

### F-C-P2-015 flow の description / delegate 順序 → **defect-gone**（テスト追加・M47 / M48 は §2 の表）

### F-C-P2-016 root に親 → **defect-gone**
- `_check_root_is_not_a_child`。実測（`exp4` 4e）: steps / delegate / summon の 3 経路すべて `BuildError`、pointer は参照側
  （`/circles/1/flow/steps/0` / `/circles/1/delegate/0` / `/circles/1/tools/0/circle`）でモデルに解決できる。
  root 自身が自分を参照する形は JIN012 が先に落とす。`jin check` 側の診断化は DP-REVIEW-JIN-P2-001 として未決（妥当）

### F-C-P2-017 `--session` → **defect-gone**（help 文と §6 に「ラベル・永続化しない」。挙動は `exp3` 3h のとおり不変で、仕様と一致）

### F-C-P2-019 `asyncio.run` の再入 → **defect-gone**
- `run_model_async` を公開、CLI は `asyncio.run(run_model_async(project=...))`。`exp4` 4i: 稼働中ループから `await` できる。
  同期 `run_model` を残した判断（P2-R1.2 #6）は妥当（docstring に使い分けを明記）

### F-C-P2-020 `WriteRefused` 以外で片付けない → **defect-gone**（`write_project` が `except BaseException` で今作ったものだけ片付け。`test_write_failure_after_open_cleans_up_only_what_it_created` が ENOSPC を注入）

### F-C-P2-021 error event → **defect-gone**
- `exp4` 4b: error だけ → `model` 行 `output = {"error_code": "X", "error_message": "boom"}`。text と error が同居する event は error の辞書が優先され text は落ちる
  （仕様 §2.4 の表どおり。text を残したければ `{"error_code", "error_message", "text"}` にする案があるが、失敗を隠さない目的は満たしている・低）

### F-C-P2-022 `BaseToolset` builtin → **残存（記録のみ・妥当）**
- 指示書 C のとおり記録のみ。2.8.0 の `google.adk.tools.__all__` に toolset のインスタンスは無いので現状の実害は無い

### F-C-P2-023 `tools[].name` は LLM に見えない → **残存（設計どおり・仕様に追記済み）**
- §2.2 に 1 段落追加。挙動は変えない方針（要件書 §3.2 の例と一致）で妥当

### F-C-P2-024 `or` の空虚 → **defect-gone**（`assert rows[0].name == "Stranger"` + `table.unresolved`）

## 2. 変異検証の再実行（隔離コピー・全スイート・`-x`）

素の状態: **770 passed in 23.87s**。ハーネス `scratchpad/review-correctness-r1/mutate.py`（前回と同じ・M50 は「`expected.strip()` を外す」に置換）。
終了後に `diff -q` でコピーの 3 ファイルが実ツリー（ラウンド 1 時点）と一致することを確認済み。

| # | 対象 | 注入した変異 | 前回 | 今回（全スイート） |
|---|---|---|---|---|
| M1 | `agent.py.j2` `_state_matches` | `and not isinstance(value, bool)` を削除 | snapshot のみ赤 | **RED**。snapshot を除いた `test_runtime.py` 単体でも `test_state_matches_semantics[1-true-False]` / `[0-false-False]` の 2 件が赤（2 failed, 43 passed） |
| M2 | `codegen._callback_lines` | `value = names[0]` | GREEN | **RED**（`test_two_guards_of_the_same_kind_become_a_list_in_declaration_order`） |
| M3 | `trace.RuntimeTable.bind_tools` | `entry.tools[j]` → `entry.tools[0]` | GREEN | **RED**（`test_tool_call_rows_use_the_declared_index_not_the_first_tool`） |
| M21 | `codegen._validate_flow_circle` | `instruction` の検査を無効化 | GREEN | **RED**（fixture `flow_circle_with_instruction`） |
| M22 | `codegen._validate_flow_circle` | `delegate` の検査を無効化 | GREEN | **RED**（fixture `flow_circle_with_delegate`） |
| M34 | `trace.classify` | `ts = 0.0` | GREEN | **RED**（`test_ts_is_taken_from_the_event_timestamp`） |
| M47 | `codegen._emit_workflow_agent` | flow circle の `description` を落とす | GREEN | **RED**（`test_flow_circle_description_and_delegate_order_survive_generation`） |
| M48 | `codegen._emit_llm_agent` | `sub_agents` を逆順 | GREEN | **RED**（同上） |
| M50 | `agent.py.j2` `_state_matches` | `expected.strip()` を外す（ラウンド 0 の挙動に戻す） | snapshot のみ赤 | **RED**。snapshot を除いた `test_runtime.py` 単体でも `[ yes-yes-True]` / `[ yes - yes-True]` の 2 件が赤 |
| M12 / M17 / M25 | （ラベル前方一致で同時に走った対照） | — | RED | **RED**（M17 は新テスト `test_ref_named_like_a_builtin_in_another_circle_is_aliased_not_shadowed`、M25 は `test_delegate_transfer_end_to_end_has_no_stray_tool_row` で赤） |

前回生き残った 7 件と snapshot だけが守っていた 2 件のすべてが、意味論のテストで赤になった。

> **注記（ラウンド 2 について）**: 本レビューの実測はラウンド 1 反映時点の作業ツリーの複製に対して行った。親の連絡によると
> その後ラウンド 2（`runtime._sys_path_window` / `build.write_project` の tmp+replace / `classify` の変更・784 passed）が入っている。
> **ラウンド 2 の内容は未確認**。F-C-P2-101 の該当箇所（`classify` の transfer 分岐）はラウンド 2 で触られている可能性があるので、
> ラウンド 2 のレビューでは `exp4_newcode.py` 4a と本文の end-to-end 再現（2 つの function_call を返す LLM）を再実行して判定すること。

## 3. P2-R1.2（指示と違う判断）7 件の判定

| # | 判断 | 判定 | 根拠 |
|---|---|---|---|
| 1 | `bind_tools` の同名経路を残す | **正しい** | `exp4` 4h で到達を実測（`search_again = web_search`）。コンパイル時は attribute 名、実行時は `func.__name__` で、import なしには一致させられない |
| 2 | ref 束縛名 vs builtin 名は別名化（同 circle は重複検査） | **正しい** | `exp4` 4g（別 circle で両方生きる）/ 4f `builtin+ref`（同 circle は BuildError） |
| 3 | `await` 枝を残す | **正しい** | `JinFile.model_validate` 直呼びで到達する（ライブラリ利用の防御）。§3.1 の表から外して注記した点も前回の指摘に合う |
| 4 | `scope_labels` を schema の enum に合わせる | 正しさの判定対象外（correctness ではない）。schema 違反を避ける判断は妥当 | — |
| 5 | `guard: _open_trace -> os.O_NOFOLLOW` | **正しい** | `run` には `O_NOFOLLOW` が無い（`main.py:649` の `_open_trace` にある）。記法は在る関数を名指しする規則 |
| 6 | 同期 `run_model` を残す | **正しい** | テストが使う。CLI は async 版を `asyncio.run` する（`main.py:752`） |
| 7 | `hazard:` は 2 件 | **正しい** | `except BaseException` は裸の名前で記法上書けない。変異 `RUN-swallow-systemexit` で代替 |

A-3-1（`sys.path.append`・P2-R1.7）: `main.py:731-733` で末尾に足す。`test_run_adds_cwd_to_sys_path` が「含まれる・先頭ではない」を見る。
correctness の観点では `research.*` の解決は変わらない（`exp2` / `exp3` の研究者 example が通る）。

## 4. 新規 finding

### F-C-P2-101 — transfer と同じ event に乗った他ツールの応答行が消える
- confidence: **100**（end-to-end で実測）
- 場所: `packages/jin-adk/src/jin_adk/trace.py:209-222`（`classify` の `if actions.transfer_to_agent:` が function_response 走査より先に `return` する）
- 何が起きるか: LLM が 1 ターンで `web_search(...)` と `transfer_to_agent(agent_name=...)` を並列に呼ぶと、ADK は両方の応答を
  1 つの function_response event にまとめ、その `actions.transfer_to_agent` を立てる。`classify` は transfer 行だけを返すので、
  `web_search` の**応答行**（`output` = 戻り値）が出ない（呼び出し行はある）。呼び出しと応答が対にならず、`web_search` が
  失敗したのか成功したのか読めない。ラウンド 1 で F-C-P2-004 を「transfer 行だけにする」形で直した際に持ち込まれた
  （前回は transfer 分岐が同じ位置にあったが、function_call 側の処理と併せて見直す機会だった）
- 再現（実ツリーの editable install・`FakeLlm` を継承して 1 応答に 2 つの function_call を返す LLM で `run_model`）:
  ```
     tool web_search /circles/0/tools/0 {'query': 'q'} None
     transfer W /circles/0/delegate/0 {'to': 'W'} None      # web_search の応答行が無い
     final m /circles/1/core None done
  ```
  `classify` 単体（`exp4` 4a）: parts = [function_response web_search, function_response transfer_to_agent] + `actions.transfer_to_agent="W"` → `[('transfer', 'W', ...)]` のみ
- 修正案: transfer 分岐を早期 `return` にせず、`responses` のうち `TRANSFER_TOOL_NAME` 以外を `tool` 行にしてから `transfer` 行を足す
  （行順は `tool → transfer`）。§2.4 の `transfer` 行に「同居する他ツールの応答行は残す」を追記。テストは 4a の event を `classify` に通す形で固定できる

### F-C-P2-102 — `run_model_async` が `asyncio.CancelledError` を `RunError` に化かす
- confidence: **80**（読解）
- 場所: `runtime.py:235-242`（`except KeyboardInterrupt: raise` / `except BaseException as exc: raise RunError`）
- 何が起きるか: F-C-P2-019 の対応で「稼働中のイベントループから呼べる」ことを公開した。その呼び出し側（Phase 4 の LSP など）が
  タスクをキャンセルすると、`CancelledError`（3.8+ は `BaseException` 派生）が `RunError("実行に失敗しました（CancelledError: ）")` に
  変換され、キャンセルが「実行失敗」として握りつぶされる（asyncio の規約ではキャンセルは伝播させる）。同期 CLI では踏まない
- 修正案: `except (KeyboardInterrupt, asyncio.CancelledError): raise`

### F-C-P2-103 — 既存のトレースファイルは 0600 にならない
- confidence: **100**（`exp4` 4j: 既存 0644 のファイルに `_open_trace` → `finish()` 後も `0o644`）
- 場所: `main.py:644-649`（`_open_trace` は `O_CREAT` の mode に 0600 を渡すだけ。既存ファイルの mode は変えない）
- 何が起きるか: 仕様 §6 手順 7「**0600** で作る」は新規作成のときだけ成り立つ。前回 0644 で作った（ラウンド 0 の生成物）
  トレースを `--trace` で指定し直すと、今回のツール引数・state がそのまま world-readable のファイルに書かれる
- 修正案: 既存ファイルなら `os.fchmod(fd, 0o600)` するか、仕様に「既存ファイルの権限は変えない」と明記する（security 軸のトリアージに委ねる）

## 5. 新規コードで確認して問題なかったもの

- `classify` の行順は `model → tool → escalate`（`exp4` 4c）。`transfer_to_agent` の function_call だけの event は行を出さない（余計な `model` 行も出ない）
- 最後の event が text + function_call のときは最後の行が `tool` なので `final` は付かない（`exp4` 4d・仕様どおり）
- `_check_root_is_not_a_child` は root 自身の循環を JIN012 に委ね、3 経路の pointer がモデルに解決できる
- `_adk_tool_name` は `kind: tool` の ref 形式不正を `None` にして `_plan_imports` の BuildError に委ねる（二重報告しない）
- `_LazyTruncateSink` は `os.fdopen(fd, "w")` が切り詰めないことに依存しているが、これは Python の仕様どおり（`exp4` 4j「open+close only → 旧内容そのまま」で実測）
- `shutil.rmtree(onexc=)` は Python 3.12+ の引数で、`requires-python >= 3.12` と整合
- `KIND_POINTERS` と §2.4 の表は `tests/spec/...::test_trace_kinds_table_matches_the_implementation` が突合し、`escalate` の 2 形を含む
