# Phase 2 修正ラウンド 3 — 親から implementer `impl-p2` への指示

作成: 親 ／ 2026-09-06
根拠: 修正ラウンド 2 の再レビュー `code-review-raw/{security,conventions,wiring}-p2-round2.md`（correctness は追記予定）。
ラウンド 2 の fix-now は security 5/5・conventions 5/5・wiring 4/4 で **全件 defect-gone**。回帰なし。
本ラウンドは新規 1 件（≥ 90・fix-now 固定）と小さい残件のみ。**大きな設計変更をしない。**

## A. fix-now — F-S-P2-201（Medium / 95）ツール関数の `asyncio.CancelledError` が exit 0 になる

- root が LlmAgent のとき、ツール関数が `CancelledError` を投げると ADK の `_cleanup_root_task` が root の cancel を warning で握って
  正常復帰するため、`run_model_async` の `except CancelledError: raise` の**外側で吸われ**、`jin run` は exit 0・「1 イベント」・エラー行無し
  （`sys.exit(0)` と同じ「失敗を成功に見せる」経路。round 0 から在った穴）
- root が workflow agent のときは逆に `CancelledError` が `asyncio.run` から素通りし、CLI がフルトレースバックで exit 1（F-S-P2-202・Low / 95）
- 修正方針（reviewer の観察に従う・`Task.cancelling()` で「ツール由来の cancel（0）」と「shutdown 由来（1）」を区別できる）:
  1. `run_model_async`: Runner の完走後に「呼び出し行はあるが応答行が無い `tool` 行」があり、かつそのツールが
     `long_running_tool_ids`（`await` の正規 pause）に**含まれない**ものは `RunError`（「ツール '<name>' が応答を返さずに終了しました
     （キャンセルされた可能性）」）にする。`await` の正規 pause（long-running ツールが `None` を返す）はトレース上同じ形（tool 行 1 本・exit 0）なので
     **誤検知しない**ことをテストで固定する（researcher の `publish` を `await` に入れた台本）
  2. CLI `run` / 同期 `run_model`: `asyncio.CancelledError` を `except` で受け、`Task.cancelling()` 相当の判定ができなければ一律
     「実行がキャンセルされました」の 1 行で **exit 1**（トレースバック無し）。`KeyboardInterrupt` は従来どおり素通し（exit 130）
  3. テスト: root=LlmAgent / root=SequentialAgent の両方で「ツールが `CancelledError` → exit 1・1 行・トレースバック無し」、
     `await` の pause は exit 0 のまま。変異 2 件（検出を消す / CLI の except を消す）
  4. `runtime.py` docstring と `decision-conformance.md` §4.1 に「ツール由来の cancel も成功扱いにしない」を追記

## B. 小さい残件（すべて低・回帰なし・まとめて）

| ID | 内容 | 対応 |
|---|---|---|
| F-S-P2-203（Low） | 3 ファイル目の `os.replace` 失敗で部分適用（`agent.py` 新・他 2 つ旧）になり、メッセージが言わない | 部分適用になったファイル名を列挙して「`jin build --force` を再実行してください」を出す（原子性の追求はしない） |
| F-S-P2-204（Info） | `--force` が既存ファイルのモードを引き継がない | `os.replace` 前に既存の mode を `fchmod` で引き継ぐ（Phase 1 の N1 と同じ規律）+ テスト |
| F-S-P2-205 / F-W-P2-203（Low） | `MUTATE_ONLY` の部分実行が `N/N mutations caught` で全件と区別できず、存在しない名前で `0/0`・rc 0 | 部分実行は `N/N (subset of M)` と出し、0 件選択は rc 1 |
| F-W-P2-201（Low） | `anthropic` 版契約テストの `skipif` は将来 lock に `anthropic` が入ると黙って skip | `skipif` を `assert`（「anthropic が入っていたらこのテストの前提を見直す」）に |
| F-W-P2-204（Low） | ツール実行中の `sys.exit` を**実プロセス**で固定するテストが無い（CliRunner 在中のみ） | `tests/contract/test_cli_contract.py` に別プロセス版を 1 本（`exits_tool` スタブ + 台本 FakeLlm は環境変数で切替 or 専用 `.jin`） |
| F-W-P2-202 / F-V-P2-205 | `requires_non_root` の二重定義（geteuid の無い OS で逆に振る舞う） | `tests/conftest.py` に 1 定義へ集約 |
| F-V-P2-203（55） | `codegen.py` の予約名衝突 hint が「一覧参照」になり要件書 §5「hint は具体値」から後退 | `例: {name}_agent` の形に戻す |
| F-V-P2-204（40） | `test_run_adds_cwd_to_sys_path` の名前が守備範囲（実行後は無い）より狭い | `test_cwd_is_on_sys_path_only_while_importing_the_generated_module` 等へ |

（F-V-P2-201 / 202 は親が直した: notes P2-R2.6 の誤記、CLAUDE.md の stubs 説明）

## C. correctness の再レビュー結果（追記・2026-09-06）

`correctness-p2-round2.md`: F-C-P2-101 / 102 / 103 / 002 文言の 4 件 **全 defect-gone**、残存 0、変異 21 件全部赤、P2-R2.2 の 7 件は妥当。新規 1 件 **F-C-P2-201（低・100）** = `--force` の tmp + `os.replace` で既存 `agent.py` の mode（利用者の `chmod 600`）が 0644 に戻る。**B の F-S-P2-204 と同一**（既存 mode を引き継ぐ対応で両方閉じる。テスト名に両 ID を書く）。

## D. 完了条件

- 8 コマンド全緑 / ハーネス全件 caught（A の新規変異を含む）/ 実ツリー不変 / `/tmp` 残骸 0
- `implementation-notes.md` に `P2-R3` 節（対応表）。`implementation-plan.json` は evidence 追記のみ
- 最終応答は件数と変更ファイル一覧を短く
