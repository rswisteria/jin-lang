# Stage 5 再レビュー — conventions（Phase 2 / 修正ラウンド 1）

- 対象: ブランチ `feat/jin-phase2-adk` の作業ツリー（修正ラウンド 1 反映後・A-3-1 の `sys.path.append` 反映済み）
- 判定対象: 親が fix-now に振った F-V-P2-001 / 002 / 003 / 004 / 005 / 006 / 007 / 008 / 009 / 010 / 011 / 012 / 013 / 014 / 019 / 020 / 023 / 024 / 026（19 件）
- 方法: 実ツリーは変更せず、隔離コピー `scratchpad/review-conventions-r1/` を作り直して実行・変異。ラウンド 0 のコピーとの `diff -ru` で修正差分を全件読んだ
- 結論: **DONE_WITH_CONCERNS**（defect-gone 18 / 残存（部分）1 = F-V-P2-003。新規 5 件はすべて低〜中）

## 0. 実測した事実

| 検査 | 結果 | 再現 |
|---|---|---|
| 全テスト | **770 tests / failures 0 / errors 0**（junit）。implementer の申告 770 と一致 | `python -m pytest -p no:cacheprovider --junitxml=junit.xml` |
| ruff / lint-imports | `All checks passed!` / `59 files already formatted` / `Contracts: 3 kept, 0 broken`（契約名「任意コード実行の実装は jin_cli.resolver と jin_adk.runtime に閉じる」） | `ruff check . && ruff format --check . && lint-imports` |
| `tests/contract/test_guard_claims.py`（新設・21 件） | 走査対象は `packages/*/src` の自動検出。変異 6 件すべて赤（下表） | 下表 |
| spec の機械可読表 | `escalate` 2 行目の pointer を `/circles/i/core` に書き換え → `test_trace_kinds_table_matches_the_implementation` 赤。`builtin_name_collision` 行を消す → `test_build_error_table_covers_every_fixture` 赤 | 隔離コピーで sed → pytest |
| CLAUDE.md / README の開発コマンド | `jin build examples/pipeline/pipeline.jin --out …` EXIT 0 / `PYTHONPATH=tests/fixtures/stubs jin run … --model fake --trace …` EXIT 0・11 行・**トレースは 0600**（`stat -c %a` = 600）/ `uv run python delivery/…/phase2-mutations/mutate_p2.py` → `59/59 mutations caught`・`imports from: /tmp/jin-mutate-*/…`（実ツリー不変。`git status --short` の行数は実行前後で同じ） | 本文の各コマンド |
| build-errors fixture | 20 本。`jin check` → error 0 / warning 0、`jin fmt --check` EXIT 0 | 同 |
| `implementation-plan.json` | 修正後は schema（`schemas/v1/implementation-plan.schema.json`）に対して **エラー 0**。HEAD（main）は `scope_labels[1] 'pipeline-verified' is not one of [...]` の **1 エラー**（元から enum 違反だった） | `jsonschema.Draft202012Validator` |

`guard:` / `hazard:` 検査の変異（`pytest tests/contract/test_guard_claims.py`。対象ファイルは実行後に復元を確認）:

| # | 変異 | 実測 |
|---|---|---|
| A | `build.py` の `guard: _open_for_write -> os.O_EXCL` を `-> os`（緩いトークン） | `GuardTokenTooLoose: guard: のトークン 'os' が裸の名前` |
| B | `runtime.py` の `guard: load_generated -> …` を `load_generatedx`（存在しない関数） | `AssertionError: guard: が存在しない関数 load_generatedx を名指ししている` |
| C | `runtime.py` の `hazard: _import_agent_module -> importlib.util.spec_from_file_location` を `guard:` に | `test_hazard_tags_mark_the_dangerous_operations_not_defenses` 赤（`tags[...] == {"hazard"}`） |
| D | `main.py` の `hazard: run -> sys.path.append` を `guard:` に | 同テスト赤（`AssertionError: sys.path.append`） |
| E | `main.py` の `guard: _open_trace -> os.O_NOFOLLOW` を `os.O_APPEND`（嘘の名指し） | `_open_trace に os.O_APPEND が無いのに guard: がそこを名指ししている` |
| F | `main.py` の `sys.path.append(cwd)` を `pass` に（主張は残す） | `test_guard_claims_point_at_real_guards[jin-cli/src/jin_cli/main.py]` 赤 |

## 1. finding ごとの判定

| ID | 判定 | 根拠（修正後の実物） |
|---|---|---|
| F-V-P2-001 | **defect-gone** | `tests/contract/test_packaging_contract.py:209` が `test_importlib_is_confined_to_the_cli_resolver_and_jin_run`。旧名は `grep` で 0 件 |
| F-V-P2-002 | **defect-gone** | `packages/jin-cli/tests/test_cli.py:38` が `test_help_lists_phase1_commands`（docstring で Phase 2 分は `test_build_run.py` と明記）。旧名 0 件 |
| F-V-P2-003 | **残存（部分）** | 直った箇所: CLAUDE.md「`--resolve` と `jin run` の危険性」の末尾箇条書きが design.yaml rule 5 と整合する文（「jin-lsp は jin_core / jin_adk / jin_render に依存できる … ws 公開パスから `jin_cli.resolver` と `jin_adk.runtime` を import しないことを Phase 4 の契約で機械化する」）に置き換わり、forbidden 契約は改名 + `forbidden_modules` に `jin_adk.runtime`、`phase2-handoff.md` §6 に Phase 4 の申し送り、`test_dependency_direction.py` の bite テストに `jin_adk.runtime` 注入を追加。**残っている箇所**: `packages/jin-cli/src/jin_cli/resolver.py:10`「Phase 4 の `jin-lsp` は `jin_core` にしか依存しないので、ws で公開されるコードパスからここへ到達できない」と `packages/jin-core/src/jin_core/resolver.py:8`「`jin_core` にしか依存しない Phase 4 の LSP サーバ」。この 2 docstring は契約名だけ差し替えられ、指摘した誤った前提文はそのまま。implementer の P2-R1.1 A-9「契約名を参照する docstring も追従」という申告と実物が食い違う。修正案: 両 docstring の当該行を CLAUDE.md と同じ文（jin-lsp は jin_adk に依存できる。到達不能は Phase 4 で `source_modules` に `jin_lsp` を足して機械化）に直す |
| F-V-P2-004 | **defect-gone** | `tests/contract/test_guard_claims.py` 新設。`packages/*/src/**/*.py` を走査し記法を含む全モジュールを自動対象（`modules_with_claims`）。`test_cli.py` から検査本体を削除し移設コメントを残す。変異 A〜F 全赤（§0）。`test_the_scan_finds_the_modules_that_carry_claims` が 4 モジュールの包含と総数下限（15）を固定 |
| F-V-P2-005 | **defect-gone** | `run` 内の散文「上書きはするが、リンクは辿らない」は消え、`_open_trace`（`O_NOFOLLOW`・`O_TRUNC` 無し・0600）と `_LazyTruncateSink._truncate`（`os.ftruncate`）に分離。`guard: _open_trace -> os.O_NOFOLLOW` / `guard: _truncate -> os.ftruncate` がモジュール docstring と関数 docstring の両方にあり、変異 E で赤。指示書の `guard: run -> os.O_NOFOLLOW` にしなかった判断（P2-R1.2 #5）は記法の規則「トークンが在る関数を名指しする」に照らして正しい |
| F-V-P2-006 | **defect-gone** | `round.jin_phases` = `[0, 1, 2]`（`scope` 末尾に【R1】で理由）。`review_status_note` は旧文を残した追記形。`milestones` は削除された「Phase 2 以降: 別ラウンドの implementer が担当（未着手）」行が復元され、その後ろに 3 行追記。`scope_labels` は `["backend-unit-verified"]` のみ。**implementer の判断は妥当**: schema の `scope_labels.items.enum` は 4 値で、HEAD の `pipeline-verified` も指示書の `pipeline-verified(phase0-1)` も enum 外（HEAD は実際に schema 違反 1 件・§0）。enum にある `pipeline-e2e-verified` を付けないのも本ブランチの `layers.pipeline_e2e = not_run` と整合する。Phase 0+1 の pipeline passed は `note` 末尾と `evidence[]` の `[jin_phase=0,1][post-merge]` 行に残っている。nit: `$comment` の「round は現在のラウンドを指す」と `jin_phases` の累積表記が字面上ずれる（`scope` の【R1】注記で読める） |
| F-V-P2-007 | **defect-gone** | `decision-conformance.md` §1: ラウンド 1 の `out_of_scope` 4 行（DP-COMMON-14 / DP-COMMON-15 / DP-JIN-CODEGEN-RUNTIME-01 / DP-JIN-TRACE-POINTER-01）が HEAD の文言 +「（ラウンド 1 の判定・記録として残す。直下の P2 行が…）」で復元され、直下に `**P2**` 行。判定サマリはラウンド 1 / ラウンド 2 の 2 段。方針文と表が一致した |
| F-V-P2-008 | **defect-gone** | `version-matrix.md` §8.3 #15: 旧文を取り消し線で残し「`result.output` は stdout + stderr の混在。stdout だけは `result.stdout`」に訂正。出典欄に私の実測（`"hint:" in result.output` = True / `stdout` False / `stderr` True）を転記 |
| F-V-P2-009 | **defect-gone** | adk-mapping.md §2.4 の `escalate` が checker 由来（`/circles/i/flow/exit`・loop 名）と `actions.escalate` 由来（`/circles/i`・author）の 2 行。`jin_adk.trace.KIND_POINTERS` を追加し `test_trace_kinds_table_matches_the_implementation` が kind ごとの pointer 列と escalate 2 行を突合（表の pointer 変異で赤・§0）。`trace.py` docstring の表も同じ 2 行。実装 `classify` は tool 行の後に escalate 行を足す形（`test_non_checker_escalate_keeps_the_tool_row_and_adds_an_escalate_row`） |
| F-V-P2-010 | **defect-gone** | fixture `flow_circle_with_instruction` / `flow_circle_with_delegate` を追加（計 20 本・`jin check` 0 error・正準形）。§3.1 の行を 5 fixture に分けて書き、`await` は行から外して表の下に「JIN070 が先に落とすので fixture は無い。枝はライブラリ利用の防御として残す」と注記。`await` 枝を消さなかった判断（P2-R1.2 #3）は私の前回の実測（`model_validate` 直呼びで到達）と一致する |
| F-V-P2-011 | **defect-gone** | `codegen._validate`: `circle.name in _builtin_names(model)` を `BuildError`（pointer `/circles/i/name`・hint「別の名前（例: google_search_agent）」）。fixture `builtin_name_collision`、§3.1 に行、`test_circle_named_like_a_builtin_is_rejected`。あわせて builtin 名を `taken` に入れ ref 束縛名は別名化（`test_ref_named_like_a_builtin_in_another_circle_is_aliased_not_shadowed`） |
| F-V-P2-012 | **defect-gone** | README「生成物と `adk run` の関係」を pipeline（`ref` 無し・fake で完走実測・実モデルは human_only 未実施）と researcher（`adk run` 単体では動かない 2 つの理由・要件書 §3.1「そのまま動く」は researcher で未達 = Q-JIN-P2-01）に分けて書き、「そのまま動く」を落とした。例の出力先は `/tmp/out` / `/tmp/t.jsonl` |
| F-V-P2-013 | **defect-gone** | CLAUDE.md「cwd の追加は CLI（`jin_cli/main.py` の `run`）が行う。`jin_adk.runtime.run_model` は `sys.path` を触らない（ライブラリとして呼ぶ側は cwd 解決を得られない）」。adk-mapping.md §6 手順 3、`runtime.py` モジュール docstring の箇条書き、`main.py` モジュール docstring がすべて同じ内容。実装は `main.py:733` の `sys.path.append(cwd)` のみ（`grep -rn "sys.path" packages/*/src` で確認） |
| F-V-P2-014 | **defect-gone（指示の範囲で）** | `codegen.py` の `# noqa: PLR0124` は `math.isnan` / `math.isinf` に置き換えて消えた。`ruff check --select RUF100 packages` の残りは Phase 1 由来の `jin_cli/resolver.py:43`（`BLE001`）1 件のみで、指示書 A-9「新規コードの死んだ noqa」の範囲外。`DP-REVIEW-JIN-002` は未決のまま（指示どおり） |
| F-V-P2-019 | **defect-gone** | `test_trace.py:52-53` が `assert rows[0].name == "Stranger"` + `assert table.unresolved` |
| F-V-P2-020 | **defect-gone** | CLAUDE.md チェックリスト 4 に「兄弟がまだ存在しない間は単独で書く … `Missing layer` で EXIT 1」を追記。7 項目目（依存する側の `pyproject.toml`）と「1〜7 の抜けは…」も整合。`test_dependency_direction.py` の docstring も 7 項目に更新 |
| F-V-P2-023 | **defect-gone** | `main.py:118` `_require_jin_file` に統合し、`dump` / `_load_model_or_exit`（build / run）の 3 箇所が呼ぶ。「ファイルがありません」「'.jin' ではありません」の文言は `_require_jin_file` と `_collect`（ディレクトリ収集の別経路）の 2 箇所になった |
| F-V-P2-024 | **defect-gone** | CLAUDE.md「`.jin` 由来の文字列**値**は `py_literal` … 識別子として埋め込むもの（circle 名 / `builtin` 名 / `ref` のモジュール）は検査済み（`isidentifier()` + NFKC 正規形 + 予約語 / 予約名 / `check_ref_format`）のものだけ。`.jin` のファイル名も入力であり、ヘッダには `py_literal` を通して載せる」。codegen.py モジュール docstring も同じ区別 |
| F-V-P2-026 | **defect-gone** | `codegen.py:627-628`「await は tools の関数を LongRunningFunctionTool に包む指定で、tools を持てない workflow agent には書けません」 |

## 2. 修正が新たに持ち込んだ規約違反（新規 finding）

**F-V-P2-101** | 70 | `packages/jin-cli/src/jin_cli/resolver.py:10-11` / `packages/jin-core/src/jin_core/resolver.py:8` | CLAUDE.md「パッケージ境界」/ design.yaml rule 5 / 申告（P2-R1.1 A-9）と実物の一致
F-V-P2-003 の残存部分。2 つの docstring が「Phase 4 の jin-lsp は `jin_core` にしか依存しない」という前提を残したまま、契約名だけ新しい名前に差し替えている。前提が偽なので「ここへ到達できない」の論拠が docstring 内で成立していない（CLAUDE.md 側は正しく書き直されている）。
修正案: 両方を「Phase 4 の jin-lsp は jin_adk にも依存できるので、到達不能は forbidden contract の `source_modules` に `jin_lsp` を足して機械化する（`phase2-handoff.md` §6）」に揃える。

**F-V-P2-102** | 55 | `tests/contract/test_packaging_contract.py:209`（`test_importlib_is_confined_to_the_cli_resolver_and_jin_run`） | DP-REVIEW-JIN-007（テスト名と守備範囲）
F-V-P2-001 で名前を直した直後だが、検出器 `dynamic_import_sites` は `importlib*` に加えて `__import__` / `exec` / `eval` / `runpy.*` まで見るようになった（F-W-P2-005）。名前の「importlib」は守備範囲より狭い。CLAUDE.md の「`importlib` を使うモジュールは 2 つだけ」も同じ。
修正案: `test_dynamic_import_is_confined_to_the_cli_resolver_and_jin_run` に改名し、CLAUDE.md を「動的 import（importlib / `__import__` / exec / eval / runpy）を使うモジュールは」に。

**F-V-P2-103** | 50 | `tests/contract/test_packaging_contract.py::test_claude_md_has_the_package_addition_checklist` | テストの守備範囲と docstring の一致
docstring は「計 7 項目」に更新されたが、assert するトークンは 6 個のまま（7 項目目に固有の語が無い）。CLAUDE.md から 7 項目目を消しても緑。
修正案: トークンに `test_every_package_declares_the_jin_packages_it_imports`（または「依存する側」）を足す。

**F-V-P2-104** | 50 | `packages/jin-adk/src/jin_adk/runtime.py:206`（`trace_sink: IO[str] | None`）と `packages/jin-cli/src/jin_cli/main.py:652`（`_LazyTruncateSink`） | 型注釈と実装の一致
CLI は `IO[str]` ではない `_LazyTruncateSink`（`write` / `finish` / `close` だけ）を `trace_sink` に渡す。duck typing で動くが注釈は嘘で、`TraceWriter.sink` も同じ。
修正案: `jin_adk.trace` に `class TraceSink(Protocol): def write(self, text: str) -> int` を置き、`run_model_async` / `TraceWriter` の注釈をそれにする。

**F-V-P2-105** | 45 | `packages/jin-adk/tests/test_runtime.py:129`（`if os.geteuid() == 0: pytest.skip(...)`） | Phase 1 の書き方との一貫性
`test_cli.py:431` は `requires_non_root = pytest.mark.skipif(...)` マーカーで同じ条件を書いている。関数内 skip は `-rs` の集計で理由が揃わず、`hasattr(os, "geteuid")` の防御も無い。
修正案: jin-adk の `tests/conftest.py`（または同ファイル先頭）に同名マーカーを置いて `@requires_non_root` に揃える。

記録のみ（finding にしない）: `decision-conformance.md` §2.19 は元段落が現在形で `sys.path.insert(0, …)`（`guard: run -> sys.path.insert`）と書き、直下の注記で撤回・決定を述べる形。extend 規律には従っているので指摘しない。forbidden 契約に `jin_adk/__init__.py` から `jin_adk.runtime` を import する注入をしても `KEPT` だったが、runtime は `jin_adk` の内側なので契約の対象外で正しい（`test_import_linter_actually_bites_on_a_forbidden_import` の注入先が `jin_core/canonical.py` だけで `jin_adk` 側の source は bite テストされていない点は低で記す）。

## 3. 再突合の結果（指定された文書）

- CLAUDE.md Phase 2 追記全体 / 「`--resolve` と `jin run` の危険性」節 / チェックリスト 7 項目目: 実装（`main.py` の `run` / `_require_jin_file` / `_open_trace`、`runtime.py`、`codegen.py`、`test_guard_claims.py`、`test_packaging_contract.py`）と一致。CLAUDE.md の開発コマンド 3 本は実行して確認（§0）
- README: 「そのまま動く」の自己矛盾は解消。cwd の説明（末尾に足す・未インストール名の残存・信頼しない cwd で実行しない）は `main.py` / adk-mapping.md §6 と同じ内容
- adk-mapping.md §2.2（ADK 上のツール名は `tools[].name` ではない）/ §2.4（trace-kinds 7 行・summon 先の内部イベント）/ §3.1（20 fixture と `await` の注記・`source_name` の段落）/ §6（手順 3 の append・手順 6 の `--session` ラベル・手順 7 の trace 0600・手順 8）: すべて修正後の実装と一致。機械可読 2 表は変異で赤になることを確認
- model.md §3.4: 「両辺の前後の空白を除く」が `agent.py.j2` の `expected.strip()` と `test_state_matches_semantics` の追加行 5 件に対応

## 4. 上位

1. F-V-P2-003 の残存（F-V-P2-101）: 2 つの resolver docstring の前提文。申告「docstring も追従」と実物の食い違い
2. F-V-P2-102: 直したばかりのテスト名が、同時に広げた検出範囲より狭い
3. F-V-P2-103 / 104 / 105: 低。次の修正ラウンドか Phase 3 の着手時にまとめて直せる

DONE_WITH_CONCERNS
