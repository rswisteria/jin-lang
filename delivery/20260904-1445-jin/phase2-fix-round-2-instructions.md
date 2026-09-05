# Phase 2 修正ラウンド 2 — 親から implementer `impl-p2` への指示

作成: 親 ／ 2026-09-05
根拠: 修正ラウンド 1 の再レビュー生出力 `code-review-raw/{conventions,security,wiring}-p2-round1.md`
（correctness の再レビューは追って追記する。届く前に本書の A〜C に着手してよい）。

再レビューの集計（fix-now の defect-gone）: conventions 18/19 / security 11/12 / wiring 7/8。
**修正ラウンド 1 が新規に持ち込んだ回帰 1 件（High）**と、残存 3 件、新規 12 件（多くは低）。

## A. 回帰（High・最優先）— F-S-P2-102（confidence 97）

`run_model_async` を CLI の `asyncio.run` に出した結果、**ツール実行中の `sys.exit(0)` を誰も捕まえず exit 0** になる
（asyncio は `SystemExit` / `KeyboardInterrupt` をタスクの結果にせずループの外へ再送出する。コルーチン側の
`except BaseException` は `CancelledError` しか見ない）。Phase 1 の S2 と同型の fail-open。

1. CLI `run`: `asyncio.run(...)` を `try` で包み、`except KeyboardInterrupt: raise` / `except SystemExit as exc:` →
   `実行に失敗しました（SystemExit: {exc.code}）` を stderr に出して **exit 1**（トレースバック無し）。同期 `run_model` にも同じ包み
2. `run_model_async` の docstring に「`SystemExit` は asyncio がループの外へ再送出するので、呼び出し側が `asyncio.run` を包むこと」を明記
   （Phase 4 の pygls 側への申し送りとして `phase2-handoff.md` §6 にも 1 行）
3. テスト: `test_build_run.py` に「ツールが `sys.exit(0)` → exit 1・stderr に `SystemExit`・トレースバック無し」
   （台本つき FakeLlm を `monkeypatch.setattr(jin_cli.main, "FakeLlm", ...)`）。`test_runtime.py` に同期 `run_model` → `RunError`
4. 変異 `RUN-swallow-systemexit-at-runtime`（CLI の `except SystemExit` を消す）を `mutate_p2.py` に追加
5. `runtime.py` docstring と `decision-conformance.md` §4.1 の「`sys.exit(0)` で成功扱いにしない」を **import 中と実行中の両方**に

## B. cwd の扱い（`DP-IMPL-JIN-P2-SYSPATH-01` 再々判断・record 済み）— F-S-P2-101（95）

chosen: **cwd を生成モジュール（`agent.py`）の import の間だけ `sys.path` に足し、import が終わったら（例外時も）`finally` で必ず外す。**
Runner 実行中は cwd が `sys.path` に無い状態を保つ。constraints は `implementation-plan.json` の decision_record（prohibition 3 / scope 1 / condition 3）を読むこと。

1. `jin_adk.runtime.load_generated` / `run_model_async` / `run_model` に `extra_sys_path: Sequence[str] = ()` を足し、
   `_import_agent_module` の前に append、`finally` で取り除く（同じ値が元からあったなら触らない）。CLI の `run` はそこへ `[os.getcwd()]` を渡し、
   CLI 自身は `sys.path` を触らない
2. `hazard:` の名指し先を `jin_adk/runtime.py` の当該関数へ移し（`hazard: <関数> -> sys.path.append`）、`guard: <関数> -> sys.path.remove`（finally での取り除き）を主張
3. テスト: `test_run_adds_cwd_to_sys_path` を「import 中は `research.*` を解決でき、**実行後は cwd が `sys.path` に含まれない**」に書き換え。
   契約テスト `test_cwd_cannot_shadow_an_installed_package_in_a_real_process` に **`anthropic/` 版**（未インストール名・Runner 実行中に ADK が毎回 import を試みる）を追加し、
   append 実装に戻すと赤になることを確認
4. `mutate_p2.py` の `CLI-no-cwd` / `CLI-cwd-first` の before を追従（`SKIP (pattern not found)` を出さない）。「Runner 実行中に cwd を残す」変異を 1 件
5. 文書: `decision-conformance.md` §2.19 / §4.1、`CLAUDE.md`「`--resolve` と `jin run` の危険性」、README、`adk-mapping.md` §6 を chosen と残存
   （ref 先関数の実行時の遅延 import は cwd から解決できない＝PYTHONPATH に委ねる / import 中の `google.adk.tools` 遅延 import 窓は残る）に揃える

## C. 残存・新規（小）

| ID | 内容 | 対応 |
|---|---|---|
| F-V-P2-101（70） | `packages/jin-cli/src/jin_cli/resolver.py:10` / `packages/jin-core/src/jin_core/resolver.py:8` の docstring に「Phase 4 の jin-lsp は jin_core にしか依存しない」の旧前提文が残る | 契約名の差し替えだけでなく前提文を design.yaml rule 5 と整合する文に |
| F-V-P2-102（55） | `test_importlib_is_confined_to_the_cli_resolver_and_jin_run` の名前が検出範囲（`__import__` / `exec` / `eval` / `runpy`）より狭い | `test_dynamic_imports_are_confined_to_the_cli_resolver_and_jin_run` 等へ |
| F-V-P2-104（50） | `trace_sink: IO[str]` 注釈に duck-typed の `_LazyTruncateSink` を渡している | `Protocol`（`write` / `close`）に注釈を変える |
| F-S-P2-103（90） | テンプレート `_state_matches` / `StateCheckAgent` が使う組み込み名（`str` / `isinstance` / `ValueError` / `json` 等）が `RESERVED_NAMES` に無く、circle 名にすると実行時 `TypeError` | テンプレートが参照する名前を `RESERVED_NAMES` に列挙し、テンプレートの AST から集めた名前と一致することをテストで固定（列挙の漏れを機械で落とす） |
| F-S-P2-104（92） | `--force` で `ftruncate` 後の `os.write` が ENOSPC で失敗すると既存 `agent.py` が 0 バイトで、文言も喪失を言わない | Phase 1 の V-1 と同じ扱い: 失われた側の文言（「既存の内容は失われました。`jin build --force` を再実行してください」）を出す。書き込みを `agent.py.tmp` → rename にできるならそれでもよい（`dir_fd` 相対で） |
| F-W-P2-004 / 103（85 / 90） | fixture の正準形は `jin fmt --check` でしか検査されない。`test_text_roundtrip_is_byte_identical` の docstring が実態と違う | `tests/contract/test_cli_contract.py` の `jin fmt --check` を `tests/fixtures/errors` / `build-errors` にも掛ける。docstring を実態に |
| F-W-P2-101（95） | `mutate_p2.py` が 1 回で `/tmp/jin-run-*` を 3 個残す | `TMPDIR` をコピー内へ向ける（終了時に消える） |
| F-W-P2-102（60） | cwd シャドウ検査が ADK の遅延 import に依存 | B-3 の `anthropic` 版で「未インストール名」に依存させ、依存している事実をテストの docstring に書く |
| F-V-P2-103 / 105（50 / 45） | チェックリスト存在テストの assert が 6 トークン / root skip がマーカーでない | 7 項目目のトークンを足す / `pytest.mark.skipif` に |

## D. correctness の再レビュー結果（追記・2026-09-05）

`code-review-raw/correctness-p2-round1.md`: fix-now 22 件 defect-gone / 残存 2 件は記録のみで妥当（022 / 023）/ P2-R1.2 の 7 件は「正しい」。新規 3 件:

| ID | 内容 | 対応 |
|---|---|---|
| F-C-P2-101（100） | `classify` の `if actions.transfer_to_agent:` が function_response 走査より先に `return` するため、LLM が 1 ターンで `web_search` と `transfer_to_agent` を並列に呼ぶと `web_search` の**応答行**が消える（呼び出し行と対にならない）。ラウンド 1 の F-C-P2-004 修正が持ち込んだもの | transfer 分岐を早期 return にせず、`TRANSFER_TOOL_NAME` 以外の応答を `tool` 行にしてから `transfer` 行を足す（行順 tool → transfer）。§2.4 の `transfer` 行に「同居する他ツールの応答行は残す」。テストは reviewer の `exp4` 4a の event（function_response 2 つ + `actions.transfer_to_agent`）を `classify` に通す形。変異を 1 件 |
| F-C-P2-102（80） | `run_model_async` が `asyncio.CancelledError` を `RunError` に化かす | ラウンド 2 の A で `except (KeyboardInterrupt, asyncio.CancelledError): raise` を入れたはず。defect-gone であることをテストで固定（`test_cancelled_error_propagates_from_run_model_async`） |
| F-C-P2-103（100） | `_open_trace` は `O_CREAT` の mode に 0600 を渡すだけで、**既存**の 0644 ファイルを `--trace` に指定すると world-readable のまま書く。§6 手順 7「0600 で作る」は新規作成のときしか成り立たない | 既存ファイルでも `os.fchmod(fd, 0o600)` する（利用者が名指しした先でも中身はツール引数・state・モデル出力なので安全側）。§6 / `decision-conformance.md` §2.22 を「作成時も既存時も 0600」に。テスト + 変異 |
| F-C-P2-002 文言（低） | `jin run` の unresolved 文言「pointer が決められない」が、実行時の `func.__name__` 衝突の実態（片方が呼べない）を言っていない。§3.1 `adk_tool_name_duplicate` 行にも実行時の別名束縛の残存が無い | 文言を「ADK 上で同名になり片方が呼べません」に。§3.1 に注記 |

## E. 完了条件

- CI 同等 8 コマンド全緑 / 変異ハーネス全件 caught（A・B の新規変異を含む）/ 実ツリー不変の確認
- `implementation-notes.md` に `P2-R2` 節（対応表・指示と違う判断があれば理由）
- 最終応答に「Stage 5 再レビュー依頼」（変更ファイル一覧）
