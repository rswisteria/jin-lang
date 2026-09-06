# Stage 5 review: conventions — Phase 3 (jin-render) 修正ラウンド 1 の再レビュー

レビュア: rereview-p3-conventions（Stage 5・観点 conventions・defect-gone 確認）／ 2026-09-06
対象: ブランチ `feat/jin-phase3-render`（worktree `/home/wisteria/jin-lang/.claude/worktrees/jin-phase3-6`・ベース origin/main `32c215e`）の
修正ラウンド 1 後の状態。入力は前回 finding `conventions-p3.md`（F-V-P3-001〜025）、親の指示書 `phase3-fix-round-1-instructions.md`、
実装者の対応表 `implementation-notes.md` P3-R1（R1.1 / R1.2 / R1.6）。
レビュー中に他エージェント（auto-decider-p3-r1）が worktree に足した `docs/adr/ADR-021-*.md` は対象外。本レビューが worktree に書いたのはこのファイル 1 本だけ。

## 実測した環境・コマンド（隔離コピーのパス・件数）

| 項目 | 値 |
|---|---|
| 隔離コピー | `/home/wisteria/.claude/jobs/e2bcfe94/tmp/rereview-conventions/`（`.venv` / `.git` / `__pycache__` を除いて rsync。`diff -rq packages` で worktree と同一を確認） |
| スクリプト | `/home/wisteria/.claude/jobs/e2bcfe94/tmp/rereview-conventions-scripts/{run.py,probe2.py}`（変異は書き換え → 実行 → 復元。復元後にバイト一致を assert） |
| インタプリタ | worktree の `.venv/bin/python`（Python 3.14.7）。`PYTHONPATH` にコピー側 `packages/*/src` を前置、`PYTHONDONTWRITEBYTECODE=1` / `-p no:cacheprovider` / `__pycache__` 削除 |
| `pytest`（全体・コピー上） | **1100 passed**（0 failed / 0 skipped・36.49s）。notes R1.0 の 1100 と一致 |
| `pytest packages/jin-cli/tests/test_cli.py` | **75 passed**（notes P3-8 項 4 の「75 passed」と一致・F-V-P3-023） |
| `ruff check .` / `ruff format --check .`（cwd=コピー） | All checks passed / 77 files already formatted |
| `lint-imports`（cwd=コピー） | Contracts: 3 kept, 0 broken |
| `mutate_p3.py`（コピー上・`TMPDIR` をジョブ tmp に向けて実行） | baseline 296 passed・**59/59 mutations caught**（58 RED + `CLI-follow-symlink-upfront-only` の期待 GREEN・SKIP 0・`/tmp` とコピー側 `tmp/` に残骸 0）。notes R1.0 / R1.4 と一致 |
| `implementation-plan.json` | schema（bundle 0.5.0）errors 0。origin/main との比較: `skill_plan` 26→28 / `tasks` 47→50 / `milestones` 7→8 / `undecided` 9→10 / `undecided_details` 19→25 / `decision_record` 17→22 / `domain_checks` 15→18 / `evidence` 95→102 で**既存要素はすべて不変**（prefix 一致）。新規 skill_plan 2 / tasks 3 / domain_checks 3 はすべて `jin_phase: 3`、evidence 7 行は `[jin_phase=3]` 接頭。`round` / `layers.pipeline_e2e`（passed → not_run）の書き換えは申し送りどおり |
| `layout.md` の `machine-readable` ブロック | `ring-radii` / `data-jin-kinds` の 2 本とも origin/main と**バイト一致**（`sed` で切り出して `diff`）。`tests/spec/test_spec_consistency.py` は全体 1100 passed の中で緑 |
| worktree の不変性 | `git status --short` に本ファイル以外の本レビュー由来の変更なし |

## 前回 finding 25 件の判定

判定の語: **defect-gone** / **部分残存** / **残存** / **記録のみ（理由妥当）** / **記録のみ（理由不十分）**

| finding | 判定 | 根拠（実測） |
|---|---|---|
| F-V-P3-001 `DASH` が `fmt_coord` を通らない | **defect-gone** | `DASH = f"{fmt_coord(6.0)} {fmt_coord(4.0)}"`。M1（`DASH = "6 4"`）→ `test_all_geometry_numbers_are_written_with_three_decimals[dashed]` **1 failed**。`test_every_numeric_attribute_is_covered_by_at_least_one_model` が `stroke-dasharray` の出現を固定（空振り検出） |
| F-V-P3-002 空虚な hostile circle 名テスト / docstring 過大 | **defect-gone** | `test_names_are_not_emitted_into_the_svg` が `name not in svg` を assert。`svg.py` docstring は「rune のテキストノードだけ」「`attr_value` は将来の受け皿」に書き直されている（読解一致） |
| F-V-P3-003 `every_live_pointer_resolves_for_each_focus` の名前 | **defect-gone** | `test_at_least_one_live_pointer_resolves_for_each_focus` に改名・docstring 一致 |
| F-V-P3-004 トレース行エラーの基数・書式 | **defect-gone** | `_read_trace_rows` が `(rows, numbers)` を返し、CLI が `TraceRowError.index` を `numbers[]` で実ファイル行へ写す。M6（`exc.index + 1` に戻す）→ `test_a_bad_row_reports_the_real_file_line_number` **1 failed**（空行 3 本入りで `:6:`）。layout.md §7.5 に「実ファイルの行番号・`path:N:`」を明記 |
| F-V-P3-005 `guard: _write_svg -> path.is_symlink` | **defect-gone（付随事項は残存・F-V-P3-104）** | 主張は `guard: _write_svg -> _write_atomically(path,text,allow_create=True)` の 1 本。M9（`_write_svg` の末尾を `path.write_text` に替える）→ `test_guard_claims_point_at_real_guards[jin-cli/.../main.py]` **1 failed**（主張が実コードを見ている）。事前 5 条件は docstring とモジュール docstring の両方で「文言のための早期判定であって防御ではない」と散文。`mutate_p3.py` の `EXPECT_GREEN` コメントも一致。二層目のメッセージのパス二重表示は残る（低・F-V-P3-104） |
| F-V-P3-006 `guard:` 網羅テストに `svg.py` が無い | **defect-gone（CLAUDE.md 側の主張は過大・F-V-P3-102）** | 期待集合に `jin-render/src/jin_render/svg.py`。M2（`svg.py` の `guard:` 行を全削除）→ `test_the_scan_finds_the_modules_that_carry_claims` **1 failed**。CLAUDE.md チェックリスト 8 項目目は追記済みだが、`test_claude_md_has_the_package_addition_checklist` は 8 項目目を見ていない（M7 で緑・下の F-V-P3-102） |
| F-V-P3-007 `data-jin-kind` の個別値が未固定 | **部分残存** | `POINTER_KINDS` 7 行 + `await` + `flow/exit` の 9 形は固定され、M3（`flow/exit` を `core`）→ **1 failed**。しかし **`/circles/i/flow`（弦）と `/circles/i/flow/steps/j`（節）の kind は誰も固定していない**: M4（弦を `circle`）/ M5（節を `tool`）とも `test_layout.py` + `test_overlay.py` + `test_render_contract.py` **147 passed（緑）**。layout.md §7.2 の表にもこの 2 行が無い（仕様側とテスト側の同じ欠陥）。F-V-P3-105 |
| F-V-P3-008 丸め根拠の「1300 px 級」 | **部分残存（実装者所管の 1 箇所が未追従）** | layout.md §4 / decision-conformance §2.24.1 と P3 行 / notes P3-3 / `test_rounding_step_is_far_above_the_float_noise`（`largest = geo.CANVAS_PX`・`math.ulp(1000.0) = 1.137e-13` を実測）は直っている。**`implementation-plan.json:2284` の `undecided_details[DP-IMPL-JIN-P3-ROUNDING-01].phase_impact`（`raised_by: impl-p3` の HANDOFF 本文）が「1300 px 級 / 2.3e-13」のまま**。これは `decision_record` ではないので B-4 の「decision_record は触らない」の対象外。`decision_record.constraints`（同ファイル 1618 / 1626）と `auto-decisions.{json,md}` は親 / auto-decider 所管（台帳 2026-09-06 行で auto-decider-p3-r1 が置換中）。F-V-P3-106 |
| F-V-P3-009 テストの `__import__` | **defect-gone** | `grep __import__ packages/jin-render/tests` → 0 件 |
| F-V-P3-010 「診断コードは増やさない」の引用先 `model.md §3.3` | **残存（3 箇所のうち 1 箇所だけ直った）** | 直ったのは `main.py:1010`（「CLAUDE.md / ADR-012」）だけ。**`docs/spec/layout.md:201`（§5 末尾）と `layout.py:77`（`RenderError` docstring）は `docs/spec/model.md` §3.3 のまま**。notes R1.1 D 表は「→ CLAUDE.md / ADR-012」と 3 箇所直したかのように書いている。F-V-P3-101 |
| F-V-P3-011 効かない `# noqa: TRY004` | **defect-gone** | `grep noqa packages/jin-render` → 0 件。コメントは「`TypeError` ではなく `ValueError`」の理由だけ |
| F-V-P3-012 「24 バイト目」/「25 バイト目」 | **defect-gone** | `ornament.py` / layout.md §2.2 / `test_determinism.py:190` の 3 箇所が「添字 24（= 25 バイト目）」で一致 |
| F-V-P3-013 plan `$comment` にラウンド 3 の extend が無い | **記録のみ（理由は半分妥当）** | R1.2 項 8 の理由は「他エージェントが `decision_record` を書き込み中で衝突を避けた」。しかし実装者は同じファイルの `undecided[]` / `undecided_details[]` に追記しており、`$comment` 1 文字列の書き換えが衝突リスクを増やす根拠は無い。実効的な理由は指示書 E の「他は触らない」であり、そう書くべき。**親が `$comment` を追記する**のが自然（F-V-P3-109） |
| F-V-P3-014 `radii_or` / `enumerate` / `approx in list` | **部分残存** | `radii_or` は消え、`any(value == pytest.approx(...))` に書き換わった。**`test_layout.py:293-294` の `for position, element in enumerate(...)`: `_ = position` は残っている**（notes D 表は 2 点だけ挙げ、`enumerate` に触れていない）。F-V-P3-107 |
| F-V-P3-015 `_write_svg` docstring「`jin fmt` / `jin build` と同じ規約」 | **defect-gone（C-2 で実装側が build に揃った）** | `_new_file_mode() = 0o644 & ~umask`。M12（`return 0o644`）→ `test_the_output_file_is_created_with_the_generated_file_mode[0o002/0o077]` **2 failed**。`test_the_created_mode_matches_what_jin_build_writes` が `jin build` の実物と突合。notes P3-7 項 9 は取り消し線 + 「レビューで覆された」+ 論拠 (b) の撤回。docstring の「同じ規約」は事実になった |
| F-V-P3-016 成功メッセージだけ `_safe` を通さない | **defect-gone** | `typer.echo(f"書き出しました: {_safe(str(out))}")`。`test_the_success_message_does_not_carry_control_characters` |
| F-V-P3-017 `ARROW_HEAD` の所在 | **defect-gone（1 語の抜け・低）** | `geometry.ARROW_HEAD` に移し `layout.py` は再輸出。layout.md §6 冒頭に「他の値から導く定数（`RUNE_MAX_CHARS` など）だけは `layout.py`」。`RUNE_ELLIPSIS`（導出値ではない・§6 の「+ `…`」）も `layout.py` にあるが「など」で読める範囲 |
| F-V-P3-018 `layout.__all__` の幅 | **defect-gone** | `__init__.py` docstring「契約はこの `__all__` の名前だけ。サブモジュールの `__all__` は契約ではない」 |
| F-V-P3-019 §7.5「1 始まり」が検証ではない | **defect-gone（B-9 と同時）** | `read_trace` が `1 <= seq <= SEQ_MAX` を検査。§7.5 に範囲と根拠（下限 / 上限）を明記。mutate_p3 `OVL-accept-seq-zero` RED（実測） |
| F-V-P3-020 ライブラリコードの `assert` | **defect-gone** | `grep "^\s*assert " packages/jin-render/src` → 0 件。`_await_angles(circle, boundary)` が `Boundary` を引数で受ける |
| F-V-P3-021 楕円弧検査の正規表現が rune に誤反応 | **defect-gone** | `d` 属性だけを対象にし、rune `A tool L 1` を含む合成モデルも回す |
| F-V-P3-022 `test_determinism.py` の関数内 import | **部分残存（同型を B-5 が持ち込んだ）** | 指摘した 2 箇所（`import os` / `check_file`）は先頭へ。`test_determinism.py:119` の `import hashlib` は残り、**B-5 で足した `test_svg.py:168-172`（`ET` / `render` / `model_from` の 3 行）と `test_overlay.py:137`（`import time`）が新たに関数内 import** になった。F-V-P3-108 |
| F-V-P3-023 notes「test_cli.py の既存 42 件」 | **defect-gone** | 「2026-09-06 の実測で 75 passed」。本レビューの実測も 75 passed |
| F-V-P3-024 layout.md 冒頭の Phase 区分 | **defect-gone** | 「§1〜§3 の骨格と §4 の『丸め関数 1 本』は Phase 0。各節の印した部分と §5〜§8 は Phase 3」 |
| F-V-P3-025 `pointers()` が欠落を `""` に潰す | **defect-gone** | `pointers()` は `element.get("data-jin")`（欠落 = `None`）を返し、`test_every_pointer_resolves_in_the_model` が `pointer is not None` を先に assert。M14（核の pointer を `None`）→ **同テスト単独で 2 failed**（修正前は隣の `carries_both_attributes` に依存していた） |

集計: defect-gone **18** / 部分残存 **5**（007 / 008 / 014 / 022 と 005・006 の付随） / 残存 **1**（010） / 記録のみ **1**（013・理由は半分妥当）。

## Findings（修正が持ち込んだ・見落とした新規欠陥）

### F-V-P3-101 [confidence 95] F-V-P3-010 の修正が 3 箇所のうち 1 箇所で止まっている（layout.md §5 と `layout.py` は `model.md §3.3` のまま）
- 場所: `docs/spec/layout.md:201`「**診断コード（JINxxx）は増やさない**（`docs/spec/model.md` §3.3）」、`packages/jin-render/src/jin_render/layout.py:77`（`RenderError` docstring・同文）。直ったのは `packages/jin-cli/src/jin_cli/main.py:1010` だけ
- 内容: notes R1.1 D 表「F-V-P3-010 | 「`docs/spec/model.md` §3.3」→「CLAUDE.md / ADR-012」」は 3 箇所を直したように読めるが、仕様（layout.md）とライブラリ側は未修正。仕様側とコード側の同じ欠陥を片方だけ直した形で、しかも直したのは CLI 側 1 箇所。`model.md §3.3` は State の `output_key` 個別ケースの文（前回どおり）
- 変異検証: 該当なし（文書の引用）
- 提案: 2 箇所を「CLAUDE.md『診断コードは増やさない』/ `docs/adr/ADR-012-DP-JIN-DIAGCODE-NUMBERING-01.md`」に向ける。notes D 表を「main.py のみ」→「3 箇所」の実態に合わせる

### F-V-P3-102 [confidence 80] CLAUDE.md「1〜8 の抜けは … `test_guard_claims.py` が名指しで落とす」は 8 項目目について過大。B-7 の「固定するテスト」も 8 項目目を見ていない
- 場所: `CLAUDE.md` パッケージ追加チェックリスト末尾「1〜8 の抜けは `tests/contract/test_packaging_contract.py` と `test_guard_claims.py` が名指しで落とす」、`tests/contract/test_guard_claims.py:96-106`、`tests/contract/test_packaging_contract.py:398-416`、notes R1.1 B-7 行（固定するテスト = `test_the_scan_finds_the_modules_that_carry_claims`, `test_claude_md_has_the_package_addition_checklist`）
- 内容: (1) M2 が示すのは「**期待集合に載っているファイル**の主張を消すと赤」だけ。Phase 4 で `jin_lsp` が `guard:` を書いて期待集合に足し忘れても、`<=` 比較と `MINIMUM_TOTAL_CLAIMS` の両方を通る（= 8 項目目の抜けは何も落とさない）。CLAUDE.md の文は 1〜7 と同じ強さで 8 を主張している。(2) `test_claude_md_has_the_package_addition_checklist` の期待語リストは Phase 2 のまま（`test_guard_claims` の語が無い）。**M7**（CLAUDE.md から 8 項目目の 2 行を削除）→ **1 passed（緑）**。notes B-7 行が「固定するテスト」に挙げた 2 本のうち後者は追記を固定していない
- 変異検証: M7 → 緑（上記）。M2 → 赤（期待集合側は効く）
- 提案: `test_the_scan_finds_the_modules_that_carry_claims` に「主張を持つモジュールのパッケージ名集合 == 期待集合のパッケージ名集合」（`{p.split("/")[0] for p in found} == {... for p in expected}`）を足して 8 を自己検出にする（新パッケージが主張を書いた瞬間に赤くなり、期待集合へ足すまで通らない）。`test_claude_md_has_the_package_addition_checklist` の期待語に `test_guard_claims.py` を足す。CLAUDE.md の文は「1〜7 は名指しで落とす。8 は … が自己検出する」と分けて書く

### F-V-P3-103 [confidence 90] R1.2 項 3 の理由「`core` の U+2028 はトレースの `name` に載る経路が無い」は実測で偽
- 場所: `implementation-notes.md` P3-R1.2 項 3、`tests/contract/test_render_contract.py::test_a_trace_written_by_jin_run_is_readable_by_jin_render`（`FakeLlm` の応答 = `output` に U+2028 を置く）
- 内容: `jin_adk.trace.RuntimeTable.core_pointer` は `(entry.core, entry.model or author)` を返し、`model` 行の `name` は **`.jin` の `core` 文字列そのもの**（コミット済み fixture でも `"name": "gemini-2.5-flash"`）。`Ident` は U+2028 を通す（`check_text` で診断 0 件・実測）。probe2（隔離コピー・`core: "gemini flash"` の pipeline）: `jin run --model fake --trace` → exit 0・**トレースに生の U+2028 が載り `name` が `'gemini flash'`**（`\n` 分割 11 行 / `splitlines()` 19 行）→ `jin render --trace` → exit 0。親も台帳（2026-09-06「親が独立に再現」行）で同じ経路を実測している。指示 A-1 が求めた端到端（`core` 経由）は成立するので、選んだ `output` 経路が「唯一の現実的な経路」という前提は誤り。テスト自体は非空虚（U+2028 の生存在と `splitlines()` との差を先に assert）で問題ない
- 変異検証: 該当なし（記録の主張の真偽）
- 提案: R1.2 項 3 の文を「`core` 経由でも載る（`model` 行の `name`）。`output` 経路を選んだのは `FakeLlm` の差し替えで台本を制御できるため」に直す。または端到端テストの parametrize に `core` 経路を 1 本足す（指示 A-1 の文言どおりになる）

### F-V-P3-104 [confidence 60] `_write_svg` の事前判定を残したことで、二層目が発火したときの CLI 出力はパスが 2 回出る（F-V-P3-005 の付随事項が未対応）
- 場所: `packages/jin-cli/src/jin_cli/main.py:948`（`SymlinkWriteRefused("シンボリックリンクなので書き込みを拒みました")`・パス無し）、`main.py:413`（`SymlinkWriteRefused(f"…: {path}")`・パス有り）、`main.py:1038`（CLI が `{out}: {exc}` で包む）
- 内容: 事前判定を通過して `os.replace` 直前の判定だけが拒んだとき（競合時）の出力は `out.svg: シンボリックリンクなので書き込みを拒みました: out.svg`。前回 finding の「付随して」段落に書いたが、B-6 の指示に含まれず未対応。到達は競合時だけ
- 変異検証: 該当なし
- 提案: 二層目の例外からパスを外す（`fmt` も同じ `{path}: {exc}` 形式で包んでいるなら `fmt` の出力も同時に整う）か、事前判定を消して二層目 1 本にする（前回提案 (2)）

### F-V-P3-105 [confidence 80] pointer → kind の表テストは `/circles/i/flow`（弦）と `/circles/i/flow/steps/j`（節）を固定していない。layout.md §7.2 の表にも同じ 2 行が無い
- 場所: `packages/jin-render/tests/test_overlay.py:262-336`（`POINTER_KINDS` 7 行 + `await` + `flow/exit`）、`docs/spec/layout.md` §7.2 の表（5 行）、`layout.py:615`（弦 `kind="flow-edge"`）/ `layout.py:640`（節 `"flow-edge"`）
- 内容: F-V-P3-007 の B-8 対応は「§7.2 の表をそのまま写す」だったが、§7.2 の表は `core` / `tools/j` / `delegate/k` / `flow/exit` / `circles/i` の 5 行で、弦と節の行が無い。テストは表より広い 7 行（state / guards / rune を追加）を持つ一方、**弦と節は落ちている**。`flow.steps` の節が `flow-edge` であることは §3 の 9 種表（`flow-edge` = 「flow の弦・矢印」）からも読めず、仕様に書かれていない値になっている。Phase 5 のエディタは kind で hit-test の種別を分けるので、節の kind は特に固定したい
- 変異検証: **M4** 弦の kind を `circle` に → `test_layout.py` + `test_overlay.py` + `test_render_contract.py` **147 passed（緑）**。**M5** 節の kind を `tool` に → 同 **147 passed（緑）**（`test_the_nine_kinds_are_all_drawn` は他要素で 9 種が出続けるので通る）
- 提案: §7.2 の表に `/circles/i/flow` → 弦（`flow-edge`）と `/circles/i/flow/steps/j` → 節（`flow-edge`・参照要素）の 2 行を足し、`POINTER_KINDS` に同じ 2 行を足す（flow を持つ合成モデルを 1 本増やす）。§3 の 9 種表の `flow-edge` 行に「flow の弦・矢印・節」と 1 語足す（`machine-readable` ブロック内なので `first_code_span` の第 1 セルは変えないこと）

### F-V-P3-106 [confidence 85] F-V-P3-008 の追従が `implementation-plan.json` の `undecided_details`（実装者が書いた HANDOFF 本文）に及んでいない
- 場所: `delivery/20260904-1445-jin/implementation-plan.json:2284`（`undecided_details[DP-IMPL-JIN-P3-ROUNDING-01].phase_impact`「(b) 1300 px 級の倍精度 1 ULP は約 2.3e-13 px」・`raised_by: impl-p3`）
- 内容: B-4 は「auto-decider の constraint 文の追従は親がやる（`decision_record` を編集しない）」と線を引いたが、この文は `decision_record` ではなく実装者自身が書いた HANDOFF の質問文。layout.md §4 / conformance / notes / テストが「最大 1000 px・約 1.1e-13」に揃った後も、人間に判断を求める文だけが旧値で残っている。`decision_record.constraints`（1618 / 1626）と `auto-decisions.{json,md}` の旧値は auto-decider 所管（台帳に置換予定と記録あり）なので別扱い
- 変異検証: 該当なし
- 提案: `phase_impact` の (b) を「最大座標 1000 px（キャンバスの縁）の 1 ULP は約 1.1e-13 px」に直す（`undecided_details` は実装者の記録）。親は auto-decider 側の置換完了後に 4 箇所（1618 / 1626 / auto-decisions.json:264,276）を grep で確認する

### F-V-P3-107 [confidence 60] F-V-P3-014 の 3 点のうち `enumerate` + `_ = position` が残っている
- 場所: `packages/jin-render/tests/test_layout.py:293-294`
- 内容: notes D 表「恒等関数 `radii_or` を消し、`approx in list` を `any(...)` に」は 2 点だけを挙げ、前回 finding の 3 点目（添字を捨てるための `enumerate`）を落としている。動作に影響なし
- 提案: `for element in _by_pointer(svg, "/circles/0/tools/0"):` にする

### F-V-P3-108 [confidence 50] B-5 のテストが関数内 import を持ち込んだ（F-V-P3-022 と同型）。ほか 2 箇所も残存
- 場所: `packages/jin-render/tests/test_svg.py:168-172`（`import xml.etree.ElementTree as ET` / `from jin_render import render` / `from .conftest import model_from`・新規）、`test_overlay.py:137`（`import time`・新規）、`test_determinism.py:119`（`import hashlib`・既存）、`tests/contract/test_render_contract.py:41`（`import xml.etree.ElementTree as ET`・Phase 3 初回から）
- 内容: `test_svg.py` は「`jin_render.svg` の単体」を謳うモジュールに `render` を使う統合テストを 1 本足し、その依存を関数内 import で隠している。ruff 既定規則では出ない。読みやすさだけの問題
- 提案: `test_a_rune_with_a_noncharacter_still_parses_as_xml` は `test_layout.py`（`render` を使う統合テスト群・`ET` と `model_from` は既に先頭 import 済み）へ移す。残りは先頭へ寄せる

### F-V-P3-109 [confidence 55] 「チェックリストは 7 項目」の記述が 3 箇所で古びた（8 項目目の追記に追従していない）
- 場所: `tests/contract/test_dependency_direction.py:221`「チェックリスト」の **7 項目**である」（`jin_lsp` を足す人が最初に読むトリップワイヤの docstring）、`tests/contract/test_packaging_contract.py:305`「CLAUDE.md のチェックリスト 7 項目目」（これは 7 番目の項目を指すので正しい）、`:399`「計 7 項目」
- 内容: B-7 で CLAUDE.md を 8 項目にしたのに、トリップワイヤの docstring は「7 項目である」と列挙まで 7 で止まっている（8 番目の `test_guard_claims.py` 期待集合が列挙に無い）。`test_later_packages_do_not_exist_yet` は「そのとき直すのはこの 1 行ではなくチェックリストの N 項目」と読み手を誘導する文なので、ここが古いと Phase 4 で 8 番目を落とす（= F-V-P3-102 の抜けを誘発する）
- 提案: `test_dependency_direction.py:221-226` を 8 項目に更新（8. `test_guard_claims.py` の期待集合）。`test_packaging_contract.py:399` を「計 8 項目」に

### F-V-P3-110 [confidence 55] `test_a_huge_pointer_does_not_blow_up_memory_or_time` はメモリを計測していない（名前と実効検査の不一致）
- 場所: `packages/jin-render/tests/test_overlay.py:126-146`
- 内容: assert は `time.monotonic()` の差 < 1.0 と `fired_pointers == {"/circles/0"}` だけ。名前は memory を主張する。指示 A-3 は「`resource.getrusage` か時間で」と時間を許したが、名前に memory を残すと「メモリの上限が固定されている」と誤読される（DP-REVIEW-JIN-007 型）。`is_ancestor_or_same` の実装は prefix を実体化しないので実態は問題ない
- 提案: `test_a_huge_pointer_is_matched_in_linear_time` に改名するか、`tracemalloc` で peak を上限つきで assert する（後者なら名前どおり）

### F-V-P3-111 [confidence 50] `POINTER_KINDS` のコメント「layout.md §7.2 の表を書き写す」は実物と合わない（表 5 行 vs テスト 7 行 + 別関数 2 本）
- 場所: `packages/jin-render/tests/test_overlay.py:259-270`
- 内容: 「表の値をコードから作らない」という意図は正しいが、書き写しではなく「表 + state / guards / rune の追加、`flow/exit` は別関数、弦と節は無し」。読み手が §7.2 と突合すると食い違う。F-V-P3-105 を直すときに一緒に整える
- 提案: コメントを「§7.2 の表と §3 の 9 種表から起こした pointer → kind の対応。§7.2 に無い行（state / guards / rune / 弦 / 節）も含む」にし、§7.2 側にも同じ行を足す（F-V-P3-105）

### F-V-P3-112 [confidence 45] notes P3-3 の表「入れ子の縮尺 0.28」の式が B-1 後の layout.md §6 と食い違う
- 場所: `implementation-notes.md:1110`「`0.55 + 0.28 * 0.95 = 0.816 < 0.95`」 vs `docs/spec/layout.md:223`「`0.55 + 0.28 * 1.01 + 0.04 = 0.873 < 0.95`」（`geometry.py` のコメントも 0.873）
- 内容: B-1 で外枠（到達半径 1.01 + 隙間 0.04）を足したので、仕様と実装コメントは式を更新したが、notes P3-3（「全件が layout.md §6 と decision-conformance §2.24 の両方に書いてある」と主張する表）だけ旧式。数値の結論（< 0.95）は変わらない
- 提案: notes P3-3 の行を §6 の式に合わせる（または「R1 で 0.873 に更新・§6 参照」と 1 語）

### F-V-P3-113 [confidence 50] `_new_file_mode`（umask 尊重の防御）に `guard:` 主張が無い
- 場所: `packages/jin-cli/src/jin_cli/main.py:332-348`（`_new_file_mode`）、`:410`（`os.chmod(temporary, _new_file_mode())`）
- 内容: CLAUDE.md は「安全主張は `guard: <関数名> -> <トークン>` 記法で書き、`test_guard_claims.py` が固定する」と定める。C-2 の防御（F-S-P3-004: umask を無視して 0644 にしない）は docstring で散文説明され、機械固定は変異 `CLI-ignore-umask` と `test_render.py` の 2 本だけ。`guard: _write_atomically -> os.chmod(temporary,_new_file_mode())` / `guard: _new_file_mode -> os.umask(0)` の形で主張できる（`_guard_satisfied` は呼び出し式を受ける・M9 で `_write_atomically(...)` 形が効くことを確認）。記法の運用の一貫性の問題で、実装は正しい
- 提案: 上の 2 主張を `_write_atomically` / `_new_file_mode` の docstring に足す（`MINIMUM_TOTAL_CLAIMS` は変えない）

## R1.2「指示書と違えた判断」9 件の評価

| # | 判断 | 評価 |
|---|---|---|
| 1 | テスト期待値を `0o666 & ~umask` ではなく `0o644 & ~umask` に | **妥当**。指示書内で「build に合わせる」と「0o666」が矛盾しており、`jin_adk/build.py` の `os.open(..., 0o644)` の実物に合わせるのが正しい。`test_the_created_mode_matches_what_jin_build_writes` が実物突合で固定（M12 で 2 failed を実測） |
| 2 | stdout を「exit 1 に包む」ではなく `sys.stdout.buffer` へ UTF-8 で書く | **妥当・指示より良い**。`-o` とのバイト同一がロケールに依らず成立し、別プロセス `PYTHONIOENCODING=ascii` テストで固定（mutate_p3 `CLI-stdout-locale` RED を実測）。`buffer` 無しの退避路（`sys.stdout.write`）は CliRunner 系のみ |
| 3 | 端到端テストで U+2028 を `core` ではなく `output` に置く | **結論は妥当・理由は偽**（F-V-P3-103）。`core` は `model` 行の `name` にそのまま載る（probe2 で実測）。テストは非空虚なので直すのは文か、`core` 経路の param 追加 |
| 4 | U+000B / U+000C を対象外に | **妥当**。`json.dumps` は 0x20 未満を必ず `\uXXXX` に逃がすので生では現れない（実装者の実測 `Invalid control character` と整合） |
| 5 | B-5 の実効範囲は U+FFFE / U+FFFF のみ | **妥当**。`jin_core.model._reject_bad_chars` が C0 / C1 / DEL / 孤立サロゲートを拒む。単体 7 param で全クラス・端到端で非文字 2 つ、`jin_core` は不変（診断を増やさない） |
| 6 | `--trace` のバイト上限を置かない | **妥当**。ストリーム読みで常駐が「行 1 本 + 受理 dict」になり、閾値の根拠が無い値を置かないのは CLAUDE.md「具体値を推測で置かない」どおり。指示書 D も「記録のみでもよいが判断を書く」 |
| 7 | F-C-P3-013 は A-3 で関数ごと消えた | **妥当**。`grep pointer_prefixes packages tests docs` → 0 件 |
| 8 | plan `$comment` の追記を見送り | **理由は半分**（F-V-P3-013 判定）。実効的な理由は指示書 E「他は触らない」。衝突回避を理由にするなら `undecided[]` への追記も同じリスク。親が追記すればよい |
| 9 | F-W-P3-010 / F-S-P3-013 は記録のみ | **妥当・指示どおり**。TOCTOU で負けても `os.replace` がリンクの実体を置き換えるだけで境界は越えない、という説明は `_write_atomically` docstring と一致 |

## 変異で緑のままだったテスト（偽 green の候補）

| 変異 | 対象テスト | 結果 | 意味 |
|---|---|---|---|
| M4: 弦（`/circles/i/flow`）の kind を `circle` に | `test_layout.py` / `test_overlay.py` / `test_render_contract.py` | **147 passed** | 弦の kind は未固定（F-V-P3-105） |
| M5: 節（`/circles/i/flow/steps/j`）の kind を `tool` に | 同上 | **147 passed** | 節の kind は未固定・仕様にも無い（F-V-P3-105） |
| M7: CLAUDE.md からチェックリスト 8 項目目を削除 | `test_packaging_contract.py::test_claude_md_has_the_package_addition_checklist` | **1 passed** | B-7 の「固定するテスト」は追記を見ていない（F-V-P3-102） |
| M8: `_write_svg` の `guard:` 主張 1 行を削除 | `test_guard_claims.py` | 23 passed | 個別の主張の有無は固定されない（設計どおり・finding にしない） |
| mutate_p3 `CLI-follow-symlink-upfront-only` | `test_render.py::test_a_symlinked_output_is_refused` | GREEN（期待どおり） | 二層目が守る。`CLI-follow-symlink-both` は RED |

赤くなった（非空虚を確認した）もの: M1（DASH）/ M2（svg.py の guard 全削除）/ M3（`flow/exit` の kind）/ M6（行番号を添字に戻す）/ M9（`_write_svg` が `_write_atomically` を呼ばない）/ M12（umask 無視）/ M13（`xml_chars` 素通し: `test_svg.py` 7 param + 端到端 2 + `guard:` 主張で **9 failed**）/ M14（核の pointer を `None` → `pointer_resolves_in_the_model` 単独で 2 failed）/ mutate_p3 の 58 RED。

## 実装者の記録（notes / conformance / plan / layout.md）と実物の不一致

| 記録 | 記述 | 実物 | finding |
|---|---|---|---|
| notes R1.1 D 表 F-V-P3-010 | 「`model.md` §3.3 → CLAUDE.md / ADR-012」 | 直ったのは `main.py` の 1 箇所。`layout.md:201` / `layout.py:77` は §3.3 のまま | F-V-P3-101 |
| notes R1.1 B-7 行 | 固定するテスト = `test_claude_md_has_the_package_addition_checklist` | 8 項目目を消しても緑（M7） | F-V-P3-102 |
| notes R1.2 項 3 | 「`core` の U+2028 は `name` に載る経路が無い」 | `core` は `model` 行の `name` に生で載る（probe2・親の台帳も同じ） | F-V-P3-103 |
| notes R1.1 D 表 F-V-P3-014 | 「`radii_or` を消し、`approx in list` を `any` に」 | `enumerate` + `_ = position` が残る | F-V-P3-107 |
| notes R1.1 D 表 F-V-P3-022 | 「関数内 import を先頭へ」 | `test_svg.py:168-172`（B-5 で新規）/ `test_overlay.py:137` / `test_determinism.py:119` に関数内 import | F-V-P3-108 |
| plan `undecided_details[ROUNDING-01].phase_impact` | 「1300 px 級 / 2.3e-13」 | layout.md §4 / conformance / notes / テストは「1000 px / 1.1e-13」 | F-V-P3-106 |
| notes P3-3 表（入れ子の縮尺） | `0.55 + 0.28 * 0.95 = 0.816` | layout.md §6 / `geometry.py` は `0.55 + 0.28 * 1.01 + 0.04 = 0.873` | F-V-P3-112 |
| `test_dependency_direction.py:221` / `test_packaging_contract.py:399` | チェックリスト「7 項目」 | CLAUDE.md は 8 項目 | F-V-P3-109 |
| CLAUDE.md チェックリスト末尾 | 「1〜8 の抜けは … 名指しで落とす」 | 8 の抜け（新パッケージの期待集合追加漏れ）は落ちない | F-V-P3-102 |
| `test_overlay.py` コメント | 「§7.2 の表を書き写す」 | 表 5 行 vs テスト 7 行 + 2 関数、弦・節は無し | F-V-P3-111 / 105 |
| notes R1.2 項 8 | 「他エージェントの `decision_record` 書き込みと衝突するので `$comment` を見送り」 | 同ファイルの `undecided[]` / `undecided_details[]` には追記している | F-V-P3-013 の判定 |

一致を確認できた記録: 1100 passed / 変異 59/59（SKIP 0・残骸 0）/ ruff 2 ゲート / lint-imports 3 kept / `test_cli.py` 75 passed / plan schema errors 0・extend 規律（既存要素不変・新規要素 `jin_phase: 3`・`undecided[]` に `DP-IMPL-JIN-P3-LOOP-STAR-ORDER-01`・`undecided_details` に同 ID の HANDOFF 本文が `raised_by: impl-p3` で登録・`decision_record` は実装者が触っていない）/ conformance の P3 行 7 件（`grep -c "^| \*\*P3\*\*"` = 7）と §2.24 の 7 小節 + §2.24.1a（覆した判断 4 行が実装と一致: `_new_file_mode` / `(j*k) mod n` / 外枠 / `_outer_extent`）+ §2.24.1b / §2.24.6 の「モデルになる 14 本（19 本中）」（実測 19 / 14）/ layout.md §2.1 の節配置と `_flow_slots` / `_flow_edges` の一致・「n=5 / 6 / 8」「n=3〜12」がテストの parametrize と一致 / §3 の XML Char 段落（`Char` 生成規則の 5 区間が `_XML_NON_CHAR` の補集合と一致・`machine-readable` ブロックの外）/ §4「1000 px・約 1.1e-13」（`math.ulp(1000.0) = 1.137e-13`）/ §6 の `summon` 外枠行（`NESTED_SCALE * _outer_extent + SUMMON_GAP`）と 0.873 の式（到達最大 = `RING_BOUNDARY + GUARD_TICK_HALF = 1.01`）/ §6 冒頭の所在記述（`ARROW_HEAD` は `geometry.py`・`RUNE_MAX_CHARS` は導出値で `layout.py`）/ §7.5 の範囲・区切り・行番号の 3 段落 / `mutate_p3.py` の `EXPECT_GREEN` コメントと `_write_svg` docstring / `guard: _write_svg -> _write_atomically(path,text,allow_create=True)` と `xml_chars` の 4 主張（`_guard_satisfied` が式として照合・M9 / M13 で赤）/ `layout.md` の `machine-readable` 2 ブロックが origin/main とバイト一致。

## 補記

- `.venv/bin/lint-imports` はコピー側 `pyproject.toml` を読み、3 契約 kept。google-adk 契約の `source_modules` は `["jin_core", "jin_render"]`、layers は `"jin_adk | jin_render"` の 1 要素で Phase 3 初回レビューから不変
- ruff を最初に走らせたときは pytest の `TMPDIR`（コピー側 `tmp/`）に残った `jin build` の生成物を拾って 26 files would be reformatted と出た。`tmp/` を消して再実行すると 77 files already formatted（CI と同じ cwd=ルート・`.`）。実ツリーの CI 設定（`extend-exclude`）の問題ではない
- ログ: `/home/wisteria/.claude/jobs/e2bcfe94/tmp/rereview-conventions-scripts/{pytest-full.log,mutate_p3.log}`
