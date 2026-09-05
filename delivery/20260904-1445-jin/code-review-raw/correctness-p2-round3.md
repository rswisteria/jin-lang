# Stage 5 review — correctness 最終確認（Phase 2 / 修正ラウンド 3・範囲限定）

- 対象: ラウンド 3 で `runtime._run_async` / `_unanswered` に入った「応答の無い function_call（long-running を除く）→ `RunError`」検出
  （F-S-P2-201 対応）の**誤検知と見逃し**、および F-C-P2-201（`--force` の mode 引き継ぎ）の defect-gone
- 方法: 隔離コピー（`scratchpad/review-correctness-r3/`・素の状態 **799 passed in 26.22s**）で `run_model` を直接叩く
  `exp6_unanswered.py`（台本つき `FakeLlm` 派生 `Script` で 1 応答に複数 part を返す）。実ツリーは一切変更していない（本ファイルの追加のみ）

## 要約

| 分類 | 件数 |
|---|---|
| defect-gone | 1（F-C-P2-201） |
| 誤検知 | 0（7 観点すべて `RunError` にならない） |
| 見逃し | 0（本当に応答が無い 4 形はすべて `RunError`） |
| 新規 | 1（低・文言の精度・F-C-P2-301） |

## 1. 誤検知の確認（すべて OK・`RunError` にならない）

| # | 観点 | 入力 | 結果 |
|---|---|---|---|
| (1) | 並列ツール呼び出し | 1 応答に `web_search` + `fetch_page` の function_call 2 つ | OK。行は call 2 + response 2 + `final`。ADK は応答を 1 event にまとめ、両 id が消える |
| (2) | `transfer_to_agent` | Boss → W の transfer | OK（`transfer` → `final`）。`TRANSFER_TOOL_NAME` は pending に入れない |
| (3) | summon（AgentTool） | `Summarizer` を呼ぶ | OK（call / response / `final`）。AgentTool の応答も id つきで返る |
| (4) | `await` の long-running が `None` を返す正規 pause | `boundary.await: [w]`・`wait_human -> None` | OK。行は `tool wait_human`（呼び出し）だけで終了し、`long_running_tool_ids` に id が入るので pending から除外される |
| (4b) | 対照: 同じ関数を `await` 無しで | `wait_human -> None`（普通の FunctionTool） | OK。応答 event が返る（`None` の応答は pause ではない） |
| (4c) | pause と通常ツールの同居 | 1 応答に `wait_human`（await）+ `quick` | OK。`quick` の応答だけ返り、`wait_human` は long-running として除外 |
| (5a) | function_call に id が無い | `FakeLlm` の既定（id 無し） | OK。ADK が `populate_client_function_call_id` で `adk-<uuid>` を付け、LLM へは `remove_client_function_call_id` で外して送る（LLM 側で観測した id は `None`）。検出は内部 event の id で動く |
| (5b) | 重複 id | 2 つの function_call に同じ `id="dup"` | OK（両方応答が返り、`pending["dup"]` は 1 回の pop で消える） |
| (5c) | ターンをまたいだ id の再利用 | 毎ターン `id="same"` | OK |
| (6) | ループ内で同じツールを複数回 | `LoopAgent(max 3)` の各周で `web_search` | OK（3 周 × call / response） |
| (6b) | 1 ターンに同じツールを 2 回 | `web_search` × 2 | OK（ADK が別 id を付ける） |

## 2. 見逃しの確認（すべて `RunError`）

| # | 入力 | 結果 |
|---|---|---|
| 対照 | `cancel_tool:fn(query)` が `CancelledError`・root = LlmAgent | `RunError: ツール 'fn' が応答を返さずに実行が終了しました（キャンセルされた可能性…）` |
| 対照 | 同・root = workflow（sequence 配下） | `RunError: 実行に失敗しました（CancelledError: ref の関数が asyncio.CancelledError を投げました）`（`cancelling()==0` 経路） |
| 並列 + cancel | 1 応答に `web_search` + `fn`（cancel） | `RunError: ツール 'web_search' / 'fn' が応答を返さず…`。ADK は並列応答を 1 event にまとめるため、cancel で**両方**の応答が失われる。検出は実態どおり 2 つとも名指しする（誤検知ではない） |
| 重複 id + cancel | `web_search`(id=dup) + `fn`(id=dup) / 逆順 | どちらも `RunError`（見逃さない）。ただし名指しされるツール名は後勝ちで上書きされた方（`'fn'` / `'web_search'`）になり、実際に cancel した側と一致しないことがある → F-C-P2-301 |
| 参考 | 引数名違い（`fn(x=…)`）で ADK が呼ばずにエラー応答を返す | 応答 event（`{'error': 'Invoking fn() failed as the following mandatory input parameters are not present…'}`）が返るので検出対象にならない（正しい） |

## 3. F-C-P2-201 → **defect-gone**
- `build._open_for_write` が tmp を開いたあと `os.fchmod(fd, stat.S_IMODE(info.st_mode))`（`build.py:171`・`info` は `lstat` 済み）
- 実測（`exp6` (7)）: `agent.py` を 0600、`.env.example` を 0640 にして `write_project(force=True)` → **0600 / 0640 のまま**。新規ファイル（`__init__.py` を再作成した場合）は 0644 & umask

## 4. 新規 finding

### F-C-P2-301 — 重複 id のとき `RunError` が名指しするツール名が実際に応答しなかった側と一致しないことがある
- confidence: **100**（§2 の「重複 id + cancel」2 件で実測）/ 重要度: 低（ADK と Gemini は id を一意に振る。重複 id は LLM 実装のバグか手製の台本でしか起きない）
- 場所: `packages/jin-adk/src/jin_adk/runtime.py:245-250`（`pending[call.id] = call.name` が後勝ちで上書きし、1 つの pop で両方消える）
- 何が起きるか: 同じ id の 2 呼び出しの片方だけ応答が無い場合、`RunError` にはなる（見逃さない）が、文言のツール名は最後に登録された方
- 修正案: `pending` を `dict[str, list[str]]` にして id ごとに名前を積み、応答で 1 つ pop する。または現状のまま「id 重複時は名前が不正確になりうる」を docstring に 1 行
