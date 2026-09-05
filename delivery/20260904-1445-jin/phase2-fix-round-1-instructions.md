# Phase 2 修正ラウンド 1 — 親から implementer `impl-p2` への指示

作成: 親（`/aid auto-deliver` 実行主体）／ 2026-09-05
根拠: Stage 5 の 4 並列レビュー生出力 `code-review-raw/{correctness,conventions,wiring,security}-p2.md`
（合計 78 件: correctness 24 / conventions 29 / wiring 9 / security 16）。
しきい値は design.yaml `review_policy.confidence_threshold_fix_now = 90`。80〜89 は親が案件文脈で判定した。

**規律**（Phase 0+1 と同じ）:
- 修正の完了は同一観点の reviewer による再レビューで確定する。「直しました」は根拠にしない
- 新しい防御は **実装を壊して赤くなること**を隔離コピー or ハーネスで実測し、`implementation-notes.md` に記録する
- 仕様側（`docs/spec/*.md`）とコード側は同じ欠陥。片方だけ直さない
- `guard:` 記法で主張を固定する。散文だけの安全宣言を増やさない
- 判断ポイントを勝手に決めない。`DP-REVIEW-JIN-002`（ruff select）/ `DP-JIN-RESOLVE-ISOLATION-01` / `DP-REVIEW-JIN-008` は未決のまま
- **git commit / push しない**。台帳（`implement-ledger.md`）には `[R1][<ID>]` 行頭で見解を append してよい

## A. fix-now（confidence ≥ 90 ＋ 親が格上げしたもの）

### A-1. コード生成の名前衝突・重複（NFR-FAIL-001）— F-C-P2-001 / 002 / 003 / F-V-P2-011 / F-S-P2-002

1. `generate` で **builtin 名**を `taken` に入れる（`_plan_imports(model, taken | builtin_names)`）。circle 名 vs builtin 名、
   ref 束縛名 vs builtin 名は `BuildError`（pointer は circle 名側 / 2 つ目の要素側）
2. **ADK 上のツール名**（`kind: tool` → callable 名、`builtin` → その名、`summon` → circle 名）を circle 内で集計し、
   重複したら `BuildError`（hint: 「callable 名が ADK のツール名になる。別名の関数に包むか 1 つにまとめる」）。
   `test_same_callable_name_from_two_modules_gets_aliased` は「BuildError になる」へ書き換える。
   `RuntimeTable.bind_tools` の「同名は None」経路は到達不能になるので、消すか到達不能である旨を書く
3. **NFKC**: `_check_identifier` / `_check_root_name` / `_plan_imports` の `taken` / `bound` は
   `unicodedata.normalize("NFKC", name)` した値で判定し、`normalized != name` は `BuildError`
   （「生成コードの変数名は NFKC 正規形のみ」）。生成物の `Assign` target 集合が circle 数 + checker 数と一致することを AST で固定
4. `docs/spec/adk-mapping.md` §3.1 に行を足し（builtin 衝突 / ADK ツール名重複 / NFKC）、fixture
   `tests/fixtures/build-errors/` を各 1 本（`test_build_error_table_covers_every_fixture` が拾う形）

### A-2. ファイル名経由の注入と書き込み失敗 — F-S-P2-001（High）/ F-S-P2-005 / F-S-P2-004 / F-C-P2-020 / F-S-P2-016

1. `_header` の `source_name` を `py_literal` に通す **かつ** CLI 入口（`_load_model_or_exit`）で `file.name` に
   制御文字（`\n` `\r` 等）か孤立サロゲート（`name.encode("utf-8")` 失敗）があれば exit 2（表示は `_safe`）。
   `test_jin_strings_cannot_inject_statements` に `source_name='x\nimport os\n#.jin'` を足し、AST body の種類が
   `ImportFrom` / `Assign`（+ `has_exit` 時の `Import` / `FunctionDef` / `ClassDef`）だけであることを固定
2. `write_project`: `text.encode("utf-8")` を **open より前**に済ませて bytes を書く。片付けを `except WriteRefused` から
   `except BaseException`（今作ったものだけ消す・既存物は触らない）に広げる。`--force` の `ftruncate` は encode 成功後にしか走らない形にする
3. `write_project` / `_open_package_dir` / `out.mkdir` の `OSError`（`--out` が通常ファイル / dangling symlink / ENAMETOOLONG）を
   `WriteRefused` に包む（Phase 1 の `_describe_oserror` 流用可）。テストは `--out` が通常ファイルのケース 1 本
4. `_load_model_or_exit` の 2 分岐（「ファイルがありません」「'.jin' ではありません」）でファイル名を `_safe` に通す
5. `<out>` 自体も `O_NOFOLLOW` で開く（`--trace` / `<out>/<root>` と規律を揃える・F-S-P2-007）。docstring を実態に合わせる

### A-3. `jin run` の cwd と `--trace` — F-S-P2-003 / F-S-P2-006 / F-C-P2-009 / F-S-P2-008

1. **cwd**: `DP-IMPL-JIN-P2-SYSPATH-01` は auto-decider に再判断させる（親が回す）。**結果が届くまで着手しない**。
   届いたら chosen どおりに直し（`append` になる見込み）、`guard:` / `mutate_p2.py` の `CLI-no-cwd` / `decision-conformance.md` §2.19 /
   `CLAUDE.md` の文言（「cwd のモジュールも実行される」）を追従させる
2. `--trace`: `generate()` が通ってから開く（CLI 側で `generate` → open → `run_model(project=...)` に分ける、または
   `O_TRUNC` 無しで開き最初の行の直前に `ftruncate`）。`BuildError` / `RunError` で既存トレースが 0 バイトにならないテスト
3. トレース JSONL は **0o600** で作る（ツール引数・state の実値・モデル出力を含む成果物）。根拠を `decision-conformance.md` に

### A-4. トレースの分類と仕様表の整合 — F-C-P2-004 / 005 / 006 / 007 / 018 / 021 / F-V-P2-009

1. `transfer_to_agent` の function_call を `kind: tool / pointer: null` にしない（応答側の `transfer` 行があるので
   **行にしない**。unresolved にも積まない）。`docs/spec/adk-mapping.md` §2.4 の `transfer` 行に「2 event 構造・どちらを行にするか」を書く
2. `escalate` を 2 種に分ける: checker 由来（name = loop 名 / pointer = `/circles/i/flow/exit`）と `actions.escalate` 由来
   （`exit_loop` 等: **tool 行 + escalate 行の両方**を出す。name = author / pointer = `/circles/i`）。表を 2 行に分け、
   `test_trace_kinds_table_matches_the_implementation` で pointer 列の形も照合
3. text と function_call が同居する event: `model` 行も出す（順序 text → tool）。§2.4 に追記
4. `Event.error_code` / `error_message` がある event は `output = {"error_code": ..., "error_message": ...}` にし、
   空応答の正常終了に見せない。§2.4 に追記
5. summon（AgentTool）先の内部イベントは行にならない（ADK 2.8.0 の仕様）ことを §2.4 / §6 に明記し、
   Phase 3 の trace overlay への申し送りとして `phase2-handoff.md` に 1 行
6. `--session <id>` はラベルであり永続化しない旨を help 文と §6 に書く（F-C-P2-017）。
   `tools[].name` が LLM に見える名前ではなく `func.__name__` が見える旨を §2.2 に 1 文（F-C-P2-023）

### A-5. `flow.exit` の比較 — F-C-P2-008 / F-C-P2-012

`equals` 側も strip する（`docs/spec/model.md` §3.4 の表「`"yes"` = `" yes "`」の対称な読みに実装を合わせる。
DP-IMPL-JIN-P2-EXITEQ-01 の chosen「文字列は前後の空白を除き」の範囲内）。`test_state_matches_semantics` に
`(" yes", "yes")` 系と `(1, "true", False)` / `(0, "false", False)` を足す

### A-6. root に親が付く構造 — F-C-P2-016

`generate` で「root circle が別 circle の `flow.steps` / `delegate` / `summon` に現れる」を `BuildError`（pointer は参照側）にし
fixture を足す。`jin check` 側の診断化は**診断コードを増やせない**ため未決として `DP-REVIEW-JIN-P2-001` を
`implementation-plan.json` の `undecided[]` に起票（`docs/pending-decisions.md` は生成器で再生成）

### A-7. テストの穴（変異で緑のまま）— F-C-P2-010 / 011 / 013 / 014 / 015 / 024

- 同種 guard 2 件 → `before_model_callback == [f, g]` を import 後のオブジェクトで固定
- `FakeToolCall(name="publish")` で `/circles/0/tools/3` を確認（添字対応）
- flow circle の `instruction` / `delegate` fixture（F-V-P2-010 と同じ 3 本: instruction / delegate / await。
  `await` 枝が到達不能なら枝を消して §3.1 の行も直す）
- `ts == event.timestamp` を固定 / flow circle の `description` と `delegate` 2 件以上の順序を固定
- `test_unknown_author_gets_a_null_pointer_not_a_dropped_row` の `or` を消す

### A-8. 契約テストと配線 — F-W-P2-003 / 005 / 001 / 004 / 007 / F-V-P2-001 / 002 / 004 / 005

- `test_jin_core_does_not_import_jin_cli` を「`jin_core` 以外の `jin_*` を一切 import しない」に広げる
- importlib 厳密一致テストを AST ベース（`Import` / `ImportFrom` の `importlib*`、`Call` の `__import__` / `exec` / `eval` / `runpy.*`）に
- 「各 `packages/<p>/src` が import する `jin_*` はその `pyproject.toml` の `dependencies` にある」契約テストを 1 本。
  CLAUDE.md チェックリストに 7 項目目
- `tests/conftest.py` の `formattable_paths` に `fixtures/build-errors` を加える（F-W-P2-004）
- `test_cli_contract._run` の `PYTHONPATH` は前置（既存値を捨てない）
- `guard:` 検査（`GUARD_CLAIM` / `_guard_satisfied` / `guarded_modules`）を `tests/contract/test_guard_claims.py` へ移し、
  `packages/*/src` を走査して `guard:` を含む全モジュールを自動対象に。`run` に `guard: run -> os.O_NOFOLLOW` を足す。
  「危険の所在」を示す 2 件（`spec_from_file_location` / `sys.path.*`）は `guard:` から **`hazard:`** タグへ分け、
  検査は両タグを同じ規則で照合しつつ意味を docstring で区別（F-S-P2-010）
- テスト名の嘘 2 件を改名（`test_importlib_is_confined_to_the_cli_resolver_and_jin_run` / `test_help_lists_phase1_commands`）

### A-9. 文書・成果物の整合 — F-V-P2-003 / 006 / 007 / 008 / 012 / 013 / 014 / F-W-P2-002 / 009

- `CLAUDE.md` 142-143 行の「Phase 4 の jin-lsp は jin_core にしか依存しない」を design.yaml rule 5 と整合する形に直す
  （「`jin_cli.resolver` と `jin_adk.runtime` を ws 公開パスから import しない。Phase 4 の契約で機械化する」）。
  forbidden 契約名を「任意コード実行の実装は `jin_cli.resolver` と `jin_adk.runtime` に閉じる」に改め、
  `phase2-handoff.md` §6 に **Phase 4 で `jin_lsp` → `jin_adk.runtime` を forbidden に加える**申し送りを書く
- `CLAUDE.md` の cwd 記述を「cwd の追加は CLI（`jin_cli/main.py` の `run`）。`run_model` は `sys.path` を触らない」に分ける
- `implementation-plan.json`: `review_status_note` を追記形に戻す / `round.jin_phases` を `[0, 1, 2]` の累積に /
  `scope_labels` に `pipeline-verified(phase0-1)` を残す / milestones の削除行を復元。**置換ではなく extend**
- `decision-conformance.md`: ラウンド 1 の `out_of_scope` 4 行を復元し直下に P2 行を並べる（方針文どおりに）。
  §4.1 の表を本ラウンドの修正に合わせて更新（`source_name` / NFKC / cwd / trace 0600 / encode-before-open）
- `version-matrix.md` §8.3 #15（CliRunner の `result.output` は stdout+stderr）を実測どおりに直す
- README の「そのまま動く」自己矛盾を直す（pipeline は動く / researcher は `{findings}` で落ちる・Q-JIN-P2-01）。
  README の `out/` `t.jsonl` の例を `/tmp` に揃える
- 新規コードの死んだ `# noqa: PLR0124` を消す（`DP-REVIEW-JIN-002` 自体は未決のまま触らない）
- `mutate_p2.py` は **コピー上で**変異する形に変える（実ツリーを書き換えない）。`status` 判定を
  `returncode == 1 and "failed" in summary` にする（F-S-P2-011）。`RUN-plain-mkdir` を本来の形（`mkdtemp` → `os.mkdir(mktemp())`）に

### A-10. 小さいもの（親が格上げ）

- `rmtree(ignore_errors=True)` の失敗を stderr に 1 行（F-W-P2-008）
- `_safe` に `py_literal` と同じ U+2028 / U+2029 の表を使う（F-S-P2-014）
- `run_model_async` を公開し CLI だけが `asyncio.run` する（F-C-P2-019・Phase 4 の pygls から呼べるように）

## B. fix-later（`undecided[]` に起票・人間判断）

| 仮 DP ID | 内容 | 由来 |
|---|---|---|
| DP-REVIEW-JIN-P2-001 | root circle に親が付く構造を `jin check` の診断にするか（診断コードの追加＝要件書 §2.4 変更） | F-C-P2-016 |
| DP-REVIEW-JIN-P2-002 | `ref` 先から `jin_adk` を差し替えると「0 イベント」exit 0 になる経路（`DP-JIN-RESOLVE-ISOLATION-01` の同型）。空トレースを「正常」と区別する印 | F-S-P2-009 |

`DP-REVIEW-JIN-002`（ruff select）は Phase 2 でも未解決（F-V-P2-014）。既存の未決に留める。

## C. 対応不要（記録のみ）

F-C-P2-022（toolset は 2.8.0 に無い）/ F-S-P2-012（`USE_ENTERPRISE=0` は `adk create` の写し）/ F-S-P2-013 / 015 /
F-W-P2-006（PR の Actions で確認）/ conventions の confidence < 70 の項目（F-V-P2-015〜029。うち 019 は A-7 で対応）

## D. 完了条件

- CI 同等 8 コマンド全緑 / 新規防御ごとの変異が赤 / `mutate_p2.py` がコピー上で全件 caught
- `implementation-notes.md` に `P2-R1` 節（対応表: finding ID → 変更箇所 → 固定するテスト → 変異結果）
- 最終応答に「Stage 5 再レビュー依頼」（変更ファイル一覧 / 未対応と判断したものとその理由）
