# Stage 5 再レビュー（conventions）— Phase 2 修正ラウンド 2

- reviewer: `review-conventions-p2`（general-purpose Subagent・conventions 観点）
- 対象: `feat/jin-phase2-adk` 作業ツリー（修正ラウンド 2 反映後）。`phase2-fix-round-2-instructions.md` A〜D と
  `implementation-notes.md` P2-R2.1 / P2-R2.2 / P2-R2.7
- 前回: `conventions-p2-round1.md`（fix-now 19 件中 18 件 defect-gone・残存 1・新規 F-V-P2-101〜105）
- 方法: 隔離コピー（`git ls-files --cached --others` → scratchpad 配下）で CI 同等コマンドを再実行し、
  `guard:` / `hazard:` 主張は実装を壊す変異で赤を確認した。**実ツリーは変更していない**（`git status` clean・差分なし）
- 日付: 2026-09-05

## 0. 実測（隔離コピー）

| 項目 | 結果 |
|---|---|
| `pytest`（junit で計数） | **787 passed / 0 failed / 0 error**（770 → 787） |
| `ruff check` / `ruff format --check` | clean（RUF100 の残りは既存の `resolver.py:43` BLE001 のみ・R1 と同じ） |
| `lint-imports` | 3 契約 kept（layers / google-adk 禁止 / 「任意コード実行の実装は jin_cli.resolver と jin_adk.runtime に閉じる」） |
| `mutate_p2.py`（コピーから実行） | **66/66 mutations caught**（RED 64・「二層目が守る」期待 GREEN 2）。`/tmp/jin-run-*` の残骸 **0** |
| `jin build` / `jin run --model fake --trace` | 生成 → 実行 → トレース 11 行・`--trace` は 0600・Traceback 無し |
| `jin fmt --check tests/fixtures/{errors,build-errors}` | EXIT 0（20 本） |
| `implementation-plan.json` を schema 検証 | エラー 0 |
| チェックリスト存在テスト | CLAUDE.md の項目 7 を消すと赤（F-V-P2-103 の固定を実証） |

`guard:` / `hazard:` 主張の変異（コピー内・各 1 件ずつ・すべて赤）:

| # | 変異 | 赤になったテスト |
|---|---|---|
| G1 | `guard: _sys_path_window -> sys.path.remove` を `hazard:` に書き換え | `test_guard_claims`（`sys.path.remove` は guard のみ） |
| G2 | `hazard: _sys_path_window -> sys.path.append` を `guard:` に書き換え | `test_guard_claims`（`sys.path.append` は hazard のみ） |
| G3 | `_sys_path_window` の `finally` から `sys.path.remove` を削除 | `test_guard_claims`（主張と AST 不一致）＋ `test_run_adds_cwd_to_sys_path` |
| G4 | `_open_trace` の `os.fchmod` を削除 | `test_guard_claims` ＋ `test_existing_trace_file_is_made_owner_only` |
| G5 | `_move_into_place` の `os.replace` → `os.rename` | `test_guard_claims` |
| G6 | `_open_for_write` の `stat.S_ISLNK` → `stat.S_ISDIR` | `test_guard_claims` ＋ symlink 拒否テスト |

## 1. 前回 finding の判定

| ID | 判定 | 根拠 |
|---|---|---|
| F-V-P2-101 | **defect-gone** | `packages/jin-cli/src/jin_cli/resolver.py:10-13` / `packages/jin-core/src/jin_core/resolver.py:8-12` とも「jin-lsp は jin_core にしか依存しない」の旧前提が消え、design.yaml rule 5（jin-lsp は jin_core / jin_adk / jin_render に依存し jin_cli には依存しない。`jin_adk.runtime` へは到達できるので Phase 4 で forbidden の `source_modules` に `jin_lsp` を足す）に揃った。契約名も現行の「…jin_cli.resolver と jin_adk.runtime に閉じる」を引く |
| F-V-P2-102 | **defect-gone** | `tests/contract/test_packaging_contract.py:209` が `test_dynamic_imports_are_confined_to_the_cli_resolver_and_jin_run` になり、検出範囲（`importlib` / `__import__` / `exec` / `eval` / `runpy`）と名前が一致。CLAUDE.md の「動的 import（importlib / `__import__` / exec / eval / runpy）」・`runtime.py` docstring・handoff §6 の呼称も追従 |
| F-V-P2-103 | **defect-gone** | チェックリスト存在テストに `"依存する側"` と `"test_every_package_declares_the_jin_packages_it_imports"` のトークンが足され 7 項目を全部見る。コピーで CLAUDE.md の項目 7 を消して赤を確認 |
| F-V-P2-104 | **defect-gone** | `packages/jin-adk/src/jin_adk/trace.py:289` に `class TraceSink(Protocol)`（`write(self, text: str, /) -> int`）。`TraceWriter(sink: TraceSink | None)` と `run_model_async(trace_sink: TraceSink | None)` の注釈が `IO[str]` から差し替わり、`_LazyTruncateSink` は duck-typed のままでも注釈に嘘が無い。置き場は sink を消費する `trace.py` で妥当（`runtime.py` は `trace` に依存する側） |
| F-V-P2-105 | **defect-gone**（nit 1 件） | root skip が `pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() == 0, reason=...)` のマーカー（`requires_non_root`）になった。ただし `packages/jin-cli/tests/test_cli.py:431` と `packages/jin-adk/tests/test_runtime.py:125` に同じ定義が 2 回ある（→ F-V-P2-205） |

残存していた F-V-P2-003（R1 で部分）は本ラウンドの対象外・記録のみのまま（変更なし）。

## 2. ラウンド 2 の変更に対する観点別の確認

### 2.1 `guard:` / `hazard:` 記法の規則変更（意味が保たれているか）

- 規則: `sys.path.append` は **hazard のみ**、`sys.path.remove` は **guard のみ**、他の `sys.path.*` は hazard のみ（`tests/contract/test_guard_claims.py:145-148`）。
  「危険の所在」と「防御の所在」が同じ関数 `_sys_path_window`（`runtime.py:124`）に在ることを 2 行で固定しており、
  ラウンド 1 の「`hazard: run -> sys.path.append`（CLI 側）」から意味が縮んでいない。cwd を触るのは CLI ではなく runtime になったので名指し先の移動は正しい
- 各主張と実装の突合（AST 一致はテストが見る。ここでは「主張が守りの実体を指しているか」）:
  - `hazard: _sys_path_window -> sys.path.append`（`runtime.py:32,134`）: 元から無い項目だけ append（`if entry not in sys.path`）。OK
  - `guard: _sys_path_window -> sys.path.remove`（`runtime.py:33,135`）: `finally` 内・`contextlib.suppress(ValueError)`。例外時も外れる。OK
  - `guard: _open_trace -> os.fchmod`（`main.py:45,660`）: `os.open(..., O_CREAT|O_NOFOLLOW, 0o600)` の直後に `os.fchmod(fd, 0o600)`（`main.py:663`）。既存ファイルも 0600 になることを `test_existing_trace_file_is_made_owner_only` が実測。OK
  - `guard: _move_into_place -> os.replace`（`build.py:36,172,175`）: `src_dir_fd` / `dst_dir_fd` 付き。OK
  - `guard: _open_for_write -> stat.S_ISLNK`（`build.py:35,140,155`）: `lstat` の結果を判定して symlink を拒む。OK
  - `write_project -> text.encode("utf-8")`: encode → open → write → replace の順で、書き込み失敗時に既存 `agent.py` が壊れない設計と一致
- 散文だけの新しい安全主張は増えていない。`os.replace` がリンクを辿らない旨の記述は事実の説明で、判定側は `S_ISLNK` の guard が固定している。
  `ftruncate` の guard が消えたのは実装から `ftruncate` が消えたためで、主張の取り下げとして正しい
- `except SystemExit`（`main.py:782` / `runtime.py:311`）は裸の名前なので `guard:` で書けない。`main.py:31-32` に「`guard:` では主張できない。固定は `test_build_run.py` の
  `test_tool_sys_exit_at_runtime_is_a_failure` と変異 `RUN-swallow-systemexit-at-runtime`」と書いてあり、R1 の U-1（裸の名前を `GuardTokenTooLoose` で拒む）の規則どおり。
  `except (KeyboardInterrupt, asyncio.CancelledError): raise`（`runtime.py:284`）も同じ扱い（`test_cancelled_error_propagates_from_run_model_async` で固定）

### 2.2 文書と実装の再突合

| 文書 | 結果 |
|---|---|
| CLAUDE.md「`--resolve` と `jin run` の危険性」 | import 窓（import の間だけ cwd・終了後は外す・例外時も）／残存（ref 先の遅延 import は cwd から解決できず PYTHONPATH に委ねる・`google.adk.tools` の遅延 import 窓は残る）／`sys.exit()` を import 中も実行中も失敗扱い、が実装と一致。ただし `CLAUDE.md:118` の stubs 説明は古い（→ F-V-P2-202） |
| README | import 窓と `PYTHONPATH` の注記が CLAUDE.md と同じ内容。実行例 `PYTHONPATH=tests/fixtures/stubs uv run jin run …` はコピーで動作 |
| `docs/spec/adk-mapping.md` §2.4 `transfer` 行 | 「同居する他ツールの応答行は残す・行順 tool → transfer」が `classify`（transfer を早期 return しない）と一致。`trace.py:10-20` の docstring 表は正典ではない写しで、`transfer` 行に「同居」の文言が無いが、pointer 列は spec テストで突合されており意味の差は無い（記録のみ） |
| §3.1 | `reserved_name_collision` に組み込み名を含む旨、`adk_tool_name_duplicate` に実行時の `func.__name__` 別名束縛の残存が入った。`RESERVED_NAMES` は AST から集めた名前との一致テストで固定 |
| §6 手順 3 / 7 / 8 | 3: cwd は import の間だけ。7: `--trace` は作成時も既存時も 0600（`fchmod`）。8: `--force` は `.<name>.jin-tmp` → `os.replace`（`TMP_SUFFIX` を `__all__` で公開）。いずれも実装と一致 |
| `decision-conformance.md` §2.19 | 見出し末尾に「→ **修正ラウンド 2 で import 窓へ**」を追記し、本文は残したまま 483 行目以降に注記。経緯（`insert(0)` → `append` → import 窓）が 487 行目に 1 行で追える |
| §2.22 | 旧文を打ち消し線で残し「修正ラウンド 2（F-C-P2-103）で変更: 既存ファイルでも `os.fchmod`」を追記（533 行目） |
| §4.1 | 既存 2 行（596 build 行・604 cwd 行）は旧セルを全部保持し、末尾に「→ 修正ラウンド 2（F-S-P2-104）で `ftruncate` をやめた（次の行）」／「→ 修正ラウンド 2 で差し替え（次の行）」を追記。新行 597 / 598 / 605 を直下に追加。マーカー文言は 2 行で揃っていないが追記形は満たす（記録のみ） |
| `phase2-handoff.md` §6 | 146-151 行目に「pygls が自前ループで `run_model_async` を回すなら `SystemExit` を自分で包む」「`extra_sys_path` に何を渡すかは Phase 4 の判断」の 2 項目。実装の申し送りと一致 |

### 2.3 テストの名前・範囲・配置

- `test_tool_sys_exit_at_runtime_is_a_failure`（`test_build_run.py:360`）／`test_existing_trace_file_is_made_owner_only`（同 257）／
  `test_cwd_cannot_supply_an_uninstalled_optional_dependency_during_the_run`（`test_cli_contract.py`・anthropic インストール時 skip）は名前と守備範囲が一致
- `test_run_adds_cwd_to_sys_path`（`test_build_run.py:327`）は「import 中は在り・先頭ではない・実行後は無い」まで見るのに名前が「足す」だけ（→ F-V-P2-204）
- `requires_non_root` はマーカー化されたが 2 ファイルで二重定義（→ F-V-P2-205）
- `TraceSink` の Protocol は `trace.py` に置かれ、`runtime.py` から import される。依存方向（runtime → trace）と一致
- `tests/fixtures/stubs/exits_tool.py` は `research/` と同じ「`ref` から import されるスタブ」の集合として stubs 直下で妥当。README / CLAUDE.md が stubs を `PYTHONPATH` に載せる前提とも合う。CLAUDE.md の説明文だけ古い（F-V-P2-202）

### 2.4 `implementation-plan.json` の extend 規律

- schema エラー 0。`T-P2-R2` を追加、`milestones` は末尾追記（「D 反映後 787 passed・変異 66 件」）、`evidence` に `[fix-round-2]` 6 行（`[correctness]` を含む）を追記
- `review_status_note` / `scope_labels`（`['backend-unit-verified']`）/ `jin_phases` / `overall`（`verified`・HEAD から不変）は R2 で触られていない
- `DP-IMPL-JIN-P2-SYSPATH-01` の decision_record は auto-decider が `record.py` 経由で置換したもの（指示書 B「record 済み」）で implementer の作業ではない。
  `compared` に 1 回目（`insert(0)`）・2 回目（`append`）の chosen が残っているので履歴は追える。観察として記録し finding にはしない

## 3. 新規 finding（F-V-P2-2NN）

| ID | conf | 内容 | 出典 | 修正案 |
|---|---|---|---|---|
| **F-V-P2-201** | 70 | `implementation-notes.md:960`（P2-R2.6）が「`overall` は触らない（partially_verified のまま…）」と書くが、`implementation-plan.json` の `overall` は HEAD でも作業ツリーでも `verified`。同 notes の P2-R1.5（840 行目）は「`overall` は変えない（`verified`）」と正しく書いており、R1 の記述とも plan の実値とも食い違う。plan が正で notes が誤り。親が最終値を再導出するときに読む文書なので実値に直す | 納品物の一貫性（DP-CONFORMANCE-01・記録の正確さ） | 「`overall` は触らない（`verified` のまま・最終値は再レビュー後に親が再導出）」に。plan.json は変更不要 |
| **F-V-P2-202** | 50 | `CLAUDE.md:118`「`tests/fixtures/stubs/` — examples の `ref` が指す `research.*` のテスト用スタブ」が、`exits_tool.py`（`sys.exit(0)` を呼ぶ `boom`）の追加で実態と違う | CLAUDE.md の記述と実態の一致 | 「examples の `ref` が指す `research.*` と、異常系テストが `ref` から import するスタブ（`exits_tool`）」に |
| **F-V-P2-203** | 55 | `codegen.py:365-366` の予約名衝突 hint が「別の名前にしてください（生成コードが使う名前と組み込み名: `jin_adk.codegen.RESERVED_NAMES`）」になり、要件書 §5「hint は具体的な値にする」から後退。同じ関数の他分岐（347 / 353 / 359 行目）は `例: {name}_agent` を出している。R2 の `RESERVED_NAMES` 拡張（F-S-P2-103 対応）が持ち込んだ後退 | 要件書 §5（診断の hint は具体値） | `f"別の名前にしてください（例: {name}_circle）。{name!r} は生成コードが使う名前です"` のように具体例を出し、一覧参照は末尾に残す |
| **F-V-P2-204** | 40 | `test_build_run.py:327` `test_run_adds_cwd_to_sys_path` は「import 中は在り・先頭でない・実行後は無い」まで assert するのに、名前が「足す」だけで守備範囲より狭い（F-V-P2-102 と同型） | テスト名は守備範囲を言う（R1 の同型 finding と同じ根拠） | `test_run_adds_cwd_to_sys_path_only_during_import` 等に |
| **F-V-P2-205** | 35 | `requires_non_root` マーカーが `test_cli.py:431` と `test_runtime.py:125` に同じ定義で二重にある（F-V-P2-105 の修正で導入）。R1 の修正案が「同ファイル先頭」を許しているので nit | 重複定義の排除 | ルート `tests/conftest.py` か各パッケージ `tests/conftest.py` に 1 か所置いて import する |

記録のみ（finding にしない）:

- `trace.py:10-20` の docstring 表の `transfer` 行に §2.4 の「同居する他ツールの応答行は残す」が無い（正典は §2.4・pointer 列は spec テストで突合済み）
- `decision-conformance.md` §4.1 の追記マーカー文言が build 行と cwd 行で揃っていない（追記形は満たす）
- `DP-IMPL-JIN-P2-SYSPATH-01` の decision_record が置換されている（auto-decider 経由・`compared` に履歴あり）

## 4. 結論

- 対象 5 件（F-V-P2-101〜105）は **すべて defect-gone**。105 は nit 1 件（二重定義）を新規 205 として分離
- `guard:` / `hazard:` の規則変更は意味を保っており、列挙された 5 主張は実装の守りの実体を指す。散文だけの安全主張は増えていない
- ラウンド 2 は新しい回帰を持ち込んでいない（787/0・変異 66/66・`/tmp` 残骸 0）
- 新規 5 件は低〜中。201（notes の `overall` 記述）だけは親の最終集計が読む文書なので次ラウンドで直すのが安い。他は Phase 3 着手時でもよい

**ステータス: DONE**
