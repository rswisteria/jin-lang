# Stage 5 review: conventions — Phase 3 (jin-render) 修正ラウンド 2 の再レビュー（範囲限定）

レビュア: rereview-p3-r2-conventions（Stage 5・観点 conventions・defect-gone 確認）／ 2026-09-06
対象: ブランチ `feat/jin-phase3-render`（worktree `/home/wisteria/jin-lang/.claude/worktrees/jin-phase3-6`・ベース origin/main `32c215e`）の
修正ラウンド 2 後の状態。入力は前回 finding `conventions-p3-round1.md`（F-V-P3-101〜113）と部分残存 5 件（F-V-P3-007 / 008 / 014 / 022 / 010）、
親の指示書 `phase3-fix-round-2-instructions.md`、実装者の対応表 `implementation-notes.md` P3-R2（R2.0〜R2.5）。
本レビューが worktree に書いたのはこのファイル 1 本だけ。

## 実測した環境・コマンド（隔離コピーのパス・件数）

| 項目 | 値 |
|---|---|
| 隔離コピー | `/home/wisteria/.claude/jobs/e2bcfe94/tmp/rereview2-conventions/`（`.venv` / `.git` / `__pycache__` / `.pytest_cache` / `.ruff_cache` を除いて rsync。`diff -rq packages` で worktree と同一を確認）。変異用に同内容の 2 本目 `…/rereview2-conventions-mut/` |
| スクリプト | `/home/wisteria/.claude/jobs/e2bcfe94/tmp/rereview2-conventions-scripts/{drive.py,mut.py,mut2.py,probe104.py}`（変異は書き換え → 実行 → 復元。復元後にバイト一致を assert）。ログは同ディレクトリの `*.log` |
| インタプリタ | worktree の `.venv/bin/python`（Python 3.14.7）。`PYTHONPATH` にコピー側 `packages/*/src` を前置、`PYTHONDONTWRITEBYTECODE=1` / `-p no:cacheprovider` / `__pycache__` 削除 / `TMPDIR` をジョブ tmp に |
| `pytest`（全体・コピー上） | **1190 passed**, 68 warnings（39.59s）。notes R2.0 / R2.3 の 1190 / 68 と一致 |
| `pytest tests/spec` | **62 passed**（`machine-readable` ブロックの突合を含む） |
| `ruff check .` / `ruff format --check .`（cwd=コピー） | All checks passed / 77 files already formatted |
| `lint-imports`（cwd=コピー） | Contracts: 3 kept, 0 broken |
| `mutate_p3.py`（コピー上・`TMPDIR` をジョブ tmp に） | baseline 383 passed・**70/70 mutations caught**（68 RED + 期待 GREEN 2・SKIP 0・`/tmp` とジョブ tmp に残骸 0）。notes R2.0 / R2.3 と一致。`TRACE-splitlines` は **5 failed**（notes A-2 行と一致）、`STAR-pre-fix-visit-order` 7 failed / `STAR-pre-fix-star-shape-stays` 3 passed（notes と一致） |
| `layout.md` の `machine-readable` ブロック | `ring-radii` は origin/main と**バイト一致**。`data-jin-kinds` は `flow-edge` 行の**第 2 セルだけ**が変わり（「flow の弦・矢印と、flow の節（`flow.steps` の参照の紋）」）、第 1 セルは 9 行とも不変（`sed` で切り出して `diff`）。`tests/spec` 62 passed |
| `model.md §3.3` の誤引用（grep 実測） | Phase 3 側 2 箇所（`layout.md:201` / `layout.py:77`）は直っている。**Phase 2 側は 4 箇所**残る: `codegen.py:27` / `codegen.py:73` / `adk-mapping.md:124` / **`adk-mapping.md:168`**（R2.2 項 1 は「3 箇所」と数えている・下の F-V-P3-202）。いずれも `machine-readable` ブロック（14–31 / 96–107 / 127–147）の外で、`tests/spec` の読取対象ではない |
| worktree の不変性 | `git status --short` に本ファイル以外の本レビュー由来の変更なし |

## 前回 finding の判定

判定の語: **defect-gone** / **部分残存** / **残存** / **記録のみ（理由妥当）** / **記録のみ（理由不十分）**

| finding | 判定 | 根拠（実測） |
|---|---|---|
| F-V-P3-101（= 010 の残存）A-1 | **defect-gone（Phase 3 の 2 箇所）** | `layout.md:201` は「CLAUDE.md / ADR-012 … `model.md` §3.3 は State の定義であって採番の規律ではない」、`layout.py:77` は「CLAUDE.md / ADR-012」。notes R2.1 A-1 行も実態どおり。Phase 2 側 4 箇所は R2.2 項 1 で意図的に据え置き（数え違い・F-V-P3-202、意見は末尾） |
| F-V-P3-103 A-2 | **defect-gone** | `test_a_trace_written_by_jin_run_is_readable_by_jin_render` が `["core", "output"]` の 2 param。`core` 側は `_jin_with_separator_in_core` で pipeline の `core` に ` x` を足し、`jin check` exit 0 → `jin run --model fake --trace` → 生の U+2028 の存在と `splitlines()` との差を先に assert → `jin render --trace` exit 0。R1.2 項 3 は取り消し線 + 「これは誤りだった」+ 正しい理由（`FakeLlm` の台本）に書き直し済み。`TRACE-splitlines` 変異 5 failed（3 param + 端到端 2） |
| F-V-P3-102 B-2 | **defect-gone** | `test_the_scan_finds_the_modules_that_carry_claims` に `{name.split("/",1)[0] for name in found} == expected_packages`。**M-B2a**（`svg.py` の `guard:` 行を全削除）→ **1 failed**（同テスト）。**M-B2b**（CLAUDE.md の 8 項目目 2 行を削除）→ `test_claude_md_has_the_package_addition_checklist` **1 failed**（期待語「走査が壊れて対象が消えたときに気づく」は CLAUDE.md にその 1 箇所しか無い・`grep -c` = 1）。**M-B2c**（Phase 4 の想定: `jin_core/pointer.py` に本物の `guard: pointer_exists -> resolve_pointer(document,pointer)` を書き、期待集合を更新しない）→ `test_the_scan…` **だけが 1 failed**（`point_at_real_guards[jin-core/…/pointer.py]` は緑 = 主張自体は正しいのに集合の等号で捕まる。これが 8 項目目の自己検出）。CLAUDE.md は「1〜7 の抜けは … 名指しで落とす。8 は … 等号で自己検出する（名指しではない）」に分かれている |
| F-V-P3-105（= 007 の部分残存）B-3 | **defect-gone** | layout.md §7.2 に `/circles/i/flow`（弦）と `/circles/i/flow/steps/j`（節）の 2 行。§3 の `flow-edge` 行は第 2 セルだけ変更。`FLOW_POINTER_KINDS` 2 行 + `test_a_flow_pointer_lands_on_the_kind_the_table_says`（核なし circle の合成モデル）。**M-B3a**（弦の kind を `circle`）→ `[/circles/0/flow-flow-edge]` **1 failed**、**M-B3b**（節の kind を `tool`）→ `[/circles/0/flow/steps/0-flow-edge]` **1 failed**（`test_overlay` + `test_layout` + `test_render_contract` の 233 件中）。mutate_p3 の `KIND-chord-as-circle` / `KIND-flow-node-as-tool` も RED。指示は「`POINTER_KINDS` に同じ 2 行」だったが別リスト `FLOW_POINTER_KINDS` にした（モデルが違うので妥当。ただし R2.2 に書いていない・F-V-P3-210） |
| F-V-P3-106（= 008 の部分残存）B-4 | **defect-gone** | `implementation-plan.json:2322` `undecided_details[ROUNDING-01].phase_impact` が「最大座標 1000 px（キャンバスの縁）の倍精度 1 ULP は約 1.1e-13 px」。`grep 1300` の残りは `decision_record` / `auto-decisions` の「前回の記録」注記（履歴として正しい）だけ |
| F-V-P3-104 | **残存（悪化・F-V-P3-201）** | 二層目のパス二重表示は消えたが、**通常経路（事前判定）でパスが 1 回も出なくなった**。実測: `jin render pipeline.jin -o <symlink> --force` の stderr は `シンボリックリンクなので書き込みを拒みました\n` のみ（`fmt` の同種メッセージとディレクトリ拒否はパス付き）。下の F-V-P3-201 |
| F-V-P3-107（= 014 の部分残存） | **defect-gone** | `grep -n "enumerate\|_ = position" test_layout.py` → 0 件 |
| F-V-P3-108（= 022 の部分残存） | **部分残存（増えている・F-V-P3-204）** | 移したのは `test_a_rune_with_a_noncharacter_still_parses_as_xml` だけ。`test_overlay.py:137`（`import time`）/ `test_determinism.py:120`（`import hashlib`）/ `test_render_contract.py:41`（`ET`）は残り、R2 で足した `test_render.py:383`（`_new_file_mode`）/ `:403-404`（`subprocess` / `sys`）が新規 |
| F-V-P3-109 | **部分残存（F-V-P3-203）** | `test_dependency_direction.py:221` は今も「**7 項目である**」で、列挙が「… 6. / **8.** / 7.」の順。`test_packaging_contract.py:399` の「計 7 項目」も残る。notes C 表「8 項目目を追記」は事実だが、見出しの数と順序が直っていない |
| F-V-P3-110 | **defect-gone** | `test_a_huge_pointer_is_matched_in_linear_time` に改名 |
| F-V-P3-111 | **部分残存（F-V-P3-205）** | 定数直上のコメントは「§7.2 と §3 から人が起こした対応であって写しではない」に直ったが、その 3 行上の節見出しコメント（`test_overlay.py:331`）は「**layout.md §7.2 の表を書き写す**」のまま |
| F-V-P3-112 | **defect-gone** | notes:1110 が「`0.55 + 0.28 * 1.01 + 0.04 = 0.873 < 0.95`（R1 の外枠追加と R2 の兄弟間隔で更新 … §6）」 |
| F-V-P3-113 | **defect-gone** | `guard: _new_file_mode -> os.umask(mask)`（`main.py:345`・実コード `os.umask(mask)` と一致）+ `test_reading_the_umask_restores_it` + 変異 `CLI-umask-not-restored`（70/70 の中で RED） |
| F-V-P3-010 | **defect-gone（Phase 3 側）** | 上の 101 と同じ。Phase 2 側 4 箇所は別扱い |
| F-V-P3-013（記録のみ） | 変更なし（前回「理由は半分」。指示書 C は変更不要と判定） | — |

集計: defect-gone **10**（101 / 103 / 102 / 105 / 106 / 107 / 110 / 112 / 113 / 010）/ 部分残存 **3**（108 / 109 / 111）/ 残存（悪化）**1**（104）/ 記録のみ **1**（013）。
指示書 A（4 件）・B（5 件）のうち conventions 所管の A-1 / A-2 / B-2 / B-3 / B-4 は**全件 defect-gone**。

### B-1（layout.md §6 の縮小規則）と実装の一致（conventions 観点）

- 式: §6 `r <= FLOW_RING * sin(pi/n) - (ARROW_HEAD + ε)` ＝ `_flow_node_limit`（`layout.py:383`）。`FLOW_RING = RING_TOOLS = 0.55` / `ARROW_HEAD = 0.05` / `FLOW_NODE_EPSILON = 0.01` は `geometry.py` にあり `__all__` に載る
- 「外枠・中身・隙間を同じ係数で縮める」: `_reference_size` が `(limit, limit / natural)` を返し `nested = frame.nested(…, NESTED_SCALE * factor)`。外枠 `limit`、中身の到達 `0.28 * extent * factor`、隙間 `0.04 * factor` なので係数は 3 つとも `limit / natural`（**一致**）。**M-B1d**（`(limit, 1.0)` = 外枠だけ詰める）→ `test_a_shrunk_flow_node_shrinks_its_contents_too[6/7/12]` **3 failed**
- 上限 0.28 のまま（**M-B1a** `if True:`）→ **23 failed**（`every_flow_chord…` 17 + `chord_gap_matches` 5 + `crowded…` 1）。点への退避を消す（**M-B1c**）→ `test_a_crowded_flow_falls_back_to_points` **1 failed**
- 境界値の検算: n=20 で `0.55·sin(π/20) − 0.06 = 0.0260 < 0.03`、n=19 で 0.0305 ≥ 0.03（§6「n >= 20 で点」一致）。`2·0.55·sin(π/n) − 0.06 ≥ 0.05` は n ≤ 31（§6「n <= 31」一致）。縮み始める n: core のみ（0.12・natural 0.0736）は n=13、examples 同型（0.80・natural 0.264）は n=5（上限 0.2633）、最大（1.01・natural 0.3228）は n=5（§6 の表と一致）。pipeline n=3 の上限 0.416 > 0.264（notes「スナップショット差分 0」の根拠と一致）
- `count < 2` で `math.inf` を返す分岐は §6 に無い（弦が無いので無害・記述の欠けとしても軽微）
- **ε は機械固定されていない**（下の F-V-P3-207）

## Findings（修正が持ち込んだ・見落とした新規欠陥）

### F-V-P3-201 [confidence 90] F-V-P3-104 の修正で、通常経路のシンボリックリンク拒否メッセージから**パスが消えた**（`fmt` / ディレクトリ拒否とも不揃い）
- 場所: `packages/jin-cli/src/jin_cli/main.py:981`（事前判定 `SymlinkWriteRefused("シンボリックリンクなので書き込みを拒みました")`・パス無し）、`main.py:1068-1071`（`render` が `SymlinkWriteRefused` だけ前置せずに出す）、`main.py:418`（二層目・パス有り）、`main.py:315`（`fmt` の同種メッセージ・パス有り）
- 内容: 前回の指摘は「二層目が発火した競合時だけパスが 2 回出る」だった。R2 は `render` 側の前置を外したが、事前判定側のメッセージにパスを足していないので、**事前判定が拒む通常経路ではパスが 0 回**になった。隔離コピーで実測（`probe104.py`・CliRunner）:
  - `jin render pipeline.jin -o <symlink> --force` → exit 1・出力 `'シンボリックリンクなので書き込みを拒みました\n'`（リンク名は**出力に含まれない**）
  - 同じ CLI の `fmt <symlink>` → `'シンボリックリンクなので整形しません: <path>\n'`（パス有り）
  - `jin render … -o <dir>` → `'<path>: ディレクトリです。…'`（パス有り）
  複数ファイルを扱うスクリプトから呼ばれたとき、どの出力先が拒まれたか分からない。競合時だけの体裁を直して通常時の情報を落とした形で、R2.2 項 9「読解で確認した」が不十分だった実例
- 変異検証: 既存 `test_a_symlinked_output_is_refused` は `"シンボリックリンク" in result.output` しか見ないので、この退行では緑のまま（偽 green・下表）
- 提案: 事前判定のメッセージを `f"シンボリックリンクなので書き込みを拒みました: {path}"`（二層目・`fmt` と同形）にし、`test_a_symlinked_output_is_refused` に `str(link) in result.output` を足す。競合時の重複は無くなり通常時のパスも戻る

### F-V-P3-202 [confidence 85] R2.2 項 1「Phase 2 の 3 箇所」は数え違い。`model.md §3.3` の誤引用は Phase 2 側に **4 箇所**残る
- 場所: `packages/jin-adk/src/jin_adk/codegen.py:27` / `:73`、`docs/spec/adk-mapping.md:124`、**`docs/spec/adk-mapping.md:168`**（§3.1 の 2 つ目の表「1 circle に `out: true` の state が 2 件以上」行の末尾「診断コードは増やさない（`docs/spec/model.md` §3.3）」）
- 内容: notes R2.2 項 1 と R2.5 項 5 は「`codegen.py` の 2 行と `adk-mapping.md:124`」の 3 箇所と書く。grep（`model.md.*3\.3`）で 4 箇所。親が R2.5 項 5 を判断するときの母数が違う。4 箇所とも `machine-readable` ブロック（adk-mapping.md 14–31 / 96–107 / 127–147）の外で、`tests/spec` が読む対象ではない
- 変異検証: 該当なし（記録の数え違い）
- 提案: R2.2 項 1 を 4 箇所に直す。意見は末尾（R2.5 項 5）

### F-V-P3-203 [confidence 70] F-V-P3-109 の修正が「8 を差し込んだ」だけで、見出しの「7 項目である」と列挙の順序（6 / 8 / 7）が直っていない
- 場所: `tests/contract/test_dependency_direction.py:221`「`CLAUDE.md` の「パッケージを足すときのチェックリスト」の **7 項目**である」、`:223-228`（列挙が `6. … / 8. test_guard_claims.py の期待集合 / 7. 依存する側 …` の順）、`tests/contract/test_packaging_contract.py:399`「（… 計 **7 項目**）」
- 内容: notes C 表「トリップワイヤ docstring の「7 項目」に 8 項目目を追記」。追記はあるが、この docstring は Phase 4 で `jin_lsp` を足す人が最初に読む誘導文で、「7 項目である」と言いながら 8 項目を並べ、順序も CLAUDE.md（1〜8）と違う。前回 finding の指摘は「7 項目 → 8 項目に」だった
- 提案: 「8 項目である」にし、列挙を 1〜8 の順に並べ替える。`test_packaging_contract.py:399` を「計 8 項目」に

### F-V-P3-204 [confidence 55] F-V-P3-108（関数内 import）は 1 件を移しただけで、残り 3 箇所は残り、R2 のテストがさらに 3 箇所足した
- 場所: 残存 `packages/jin-render/tests/test_overlay.py:137`（`import time`）/ `test_determinism.py:120`（`import hashlib`）/ `tests/contract/test_render_contract.py:41`（`ET`）。新規 `packages/jin-cli/tests/test_render.py:383`（`from jin_cli.main import _new_file_mode`・F-S-P3-105 のテスト）/ `:403-404`（`import subprocess` / `import sys`・F-S-P3-103 のテスト）
- 内容: 指示書 C は「関数内 import 3 箇所」。notes C 表の F-V-P3-108 行は移動 1 件だけを書き、残りに触れていない。同じラウンドで足したテストが同型を持ち込んでいる（`test_render.py` は先頭で `os` / `Path` / `pytest` を import 済み）。動作に影響なし・読みやすさだけ
- 提案: 6 箇所を先頭へ。`_new_file_mode` は既に先頭で `from jin_cli.main import …` があるならそこへ足す

### F-V-P3-205 [confidence 50] F-V-P3-111 の修正が定数直上のコメントだけで、3 行上の節見出しは「§7.2 の表を書き写す」のまま
- 場所: `packages/jin-render/tests/test_overlay.py:331`（`# pointer の末尾 → 当たる要素の data-jin-kind（layout.md §7.2 の表を書き写す）`）と `:334-337`（「写しではない」）
- 内容: 同じ画面に「書き写す」と「写しではない」が並ぶ
- 提案: 見出しを「（layout.md §7.2 と §3 から起こした対応）」に

### F-V-P3-206 [confidence 45] `mutate_p3.py` の期待 GREEN の表示ラベルと見出しコメントが 1 本目（symlink 二層）専用のまま。2 本目（`STAR-pre-fix-star-shape-stays`）に「二層目が守る」と出る
- 場所: `delivery/20260904-1445-jin/phase3-mutations/mutate_p3.py:880`（`status = "GREEN (expected: 二層目が守る)"` / `"RED (!! 二層目が効いていない)"`）、`:717-720`（`EXPECT_GREEN` の見出しコメントは symlink の話だけ）
- 内容: 実測ログ（`mutate_p3.log:67`）: `STAR-pre-fix-star-shape-stays GREEN (expected: 二層目が守る)`。エントリ横のコメント（`:723-725`）は正しいが、実行結果を読む人が見るのはラベルのほう。R2.2 項 12 が「理由をエントリのコメントに書いてある」と言う理由が出力に出ない
- 提案: `EXPECT_GREEN: dict[str, str]`（名前 → 理由）にしてラベルに理由を差し込む。見出しコメントを「期待 GREEN は 2 種類」に

### F-V-P3-207 [confidence 40] 弦の余裕 `ε`（`FLOW_NODE_EPSILON = 0.01`）は機械固定されていない。layout.md §6 の「縮み始める n」表と n ≥ 20 / n ≤ 31 の境界も同様
- 場所: `packages/jin-render/src/jin_render/geometry.py:63`、`layout.py:383`、`docs/spec/layout.md` §6「弦の余裕 ε」行・「境界（実測値）」表・「n >= 20」「n <= 31」
- 内容: **M-B1b**（`- (ARROW_HEAD + ε)` → `- ARROW_HEAD`）→ `test_layout` + `test_overlay` **220 passed（緑）**。`test_every_flow_chord…` は `min(bodies) >= head` しか見ないので ε を消しても通る。§6 の表（13 / 5 / 5）と n=20 / n=31 の境界は本文に「実測値」と書いてあるだけで、どのテストも参照しない。値そのものは「実装が決めた」で妥当（要件書に無い値の扱いは他の定数と同じ）
- 提案: `test_every_flow_chord…` の下限を `2 * (ARROW_HEAD + FLOW_NODE_EPSILON) * scale - tol` にする（§6「本体長は `2 * (ARROW_HEAD + ε)` 以上」の文言どおり）。§6 の表は `test_shrink_starts_at_the_documented_n`（3 種 × 境界の前後 1）で固定する

### F-V-P3-208 [confidence 35] B-1 後も「0.28」を固定値のように書く記述が 2 箇所
- 場所: `delivery/20260904-1445-jin/decision-conformance.md:635`（§2.24.3「入れ子の縮尺 0.28」・「上限」の語が無い）、`docs/spec/layout.md` §7.2 の `/circles/i/flow/steps/j` 行「参照が解決すれば外枠 + 入れ子の小陣、しなければ点」（n ≥ 20 の点への退避が無い。§6 にはある）
- 内容: §2.24.1c と §6 の表は「上限」と書き直されているが、§2.24.3 の一覧と §7.2 の行が追従していない。読み手が §2.24.3 だけを見ると固定値に読める
- 提案: §2.24.3 を「入れ子の縮尺 上限 0.28（flow の節は §2.24.1c）」、§7.2 の行に「または n ≥ 20 なら点（§6）」を足す

### F-V-P3-209 [confidence 30] `implementation-plan.json` の `evidence[]` の変異件数が 42/42（Phase 3 初回）のまま。R1（59/59）も R2（70/70）も行を足していない
- 場所: `implementation-plan.json:2139`（`[jin_phase=3][mutation] … 42/42 caught`）
- 内容: evidence は追記ログなので既存行は正しい。ただし Phase 2 では修正ラウンドごとに `[fix-round-N]` 行を足していた（`:2133` など）のに対し、Phase 3 は R1 / R2 とも足していない（notes R2.3「plan は `undecided_details` の 2 件だけ変更」）。plan だけ読む人には 42/42 が最終値に見える
- 提案: 親が最終ラウンド後に `[jin_phase=3][fix-round-2][mutation] 70/70` と `[gates] 1190 passed` の 2 行を足す（実装者は「他は触らない」指示に従っただけなので、記録の所管の話）

### F-V-P3-210 [confidence 30] B-3 の「`POINTER_KINDS` に同じ 2 行」を別リスト `FLOW_POINTER_KINDS` にしたことが R2.2 に無い
- 場所: `packages/jin-render/tests/test_overlay.py:346-349`、notes R2.1 B-3 行（「`FLOW_POINTER_KINDS` を追加」と結果だけ）
- 内容: 核なし circle の別モデルが要るので別リスト + 別テストにしたのは妥当（1 つの parametrize に混ぜるとモデル分岐が要る）。ただし指示と違えた判断は R2.2 に書く規律で、ここは R2.1 に結果だけ
- 提案: R2.2 に 1 行（「同じリストに入れると核あり / 核なしでモデルを分岐させる必要があるため別リストにした」）

## R2.2「指示と違えた判断 / 直さなかったもの」12 件の評価

| # | 判断 | 評価 |
|---|---|---|
| 1 | Phase 2 の `model.md §3.3` 誤引用を据え置き | **判断は理解できるが数が違う**（3 → 4・F-V-P3-202）。意見は R2.5 項 5 |
| 2 | `FLOW-no-node-limit` が最初 GREEN → テストを足して `FLOW-extent-no-limit` も追加 | **妥当・良い判断**。実測 `FLOW-no-node-limit` 8 failed / `FLOW-extent-no-limit` 25 failed。「変異が悪い」で片付けなかったのが正しい |
| 3 | `summon` の紋（道具環）には縮小を適用しない | **妥当**（弦が無い）。§6 に明記済み。「12 個で最大の紋 0.32 が重なりうる」は §6 の「紋 0.06 は 12 個で重ならない」が summon の紋（最大 0.32）を含んでいないので、別 finding（correctness・低）として起票する価値あり（R2.5 項 3 = はい） |
| 4 | n ≥ 32 で弦が消えうるのを幾何の限界として許容 | **妥当**。`flow.steps` に個数上限が無く、環半径は §1 の固定値（要件書 §2.5）。§6 に境界と理由を書き、診断を増やしていない。要件書に戻す必要は無い（R2.5 項 2 = 許容してよい）。Phase 4 の LSP が hint を出すかは別判断 |
| 5 | F-C-P3-103（Unicode 空白だけの行）記録のみ | **妥当**。writer が書かない・BOM 付き空行を壊さない、の 2 点は実装の説明と一致 |
| 6 | F-S-P3-102（1 行長の上限）記録のみ | **妥当**。R1.2 項 6 と同じ論拠・CLAUDE.md「具体値を推測で置かない」 |
| 7 | F-S-P3-104（FIFO + `--force`）記録のみ | **妥当**。境界を越えない・明示 `--force` |
| 8 | F-W-P3-103（tests の動的 import は網の外）記録のみ | **妥当**。契約の対象は配布物 |
| 9 | F-V-P3-104 にテストを足さず読解で確認 | **不十分**。読解で確認した変更が通常経路のパスを落とした（F-V-P3-201）。競合の窓は再現できなくても、「事前判定のメッセージにパスが含まれる」は CliRunner で固定できた |
| 10 | `--upto` の桁数は 4300 未満（`int()` の上限） | **妥当**（事実の記録） |
| 11 | 「道具環の紋の重なり」を C の記録のみ 5 件に数える | **妥当**（帳簿の整合） |
| 12 | `STAR-pre-fix-star-shape-stays` を `EXPECT_GREEN` の 2 本目に | **原理は妥当**（GREEN が主張そのもの）。ただし出力ラベルと見出しコメントが 1 本目専用（F-V-P3-206）。理由をラベルに出せば「GREEN は原則捕まえ損ね」の規律と両立する |

### R2.5 項 5（Phase 2 の `model.md §3.3` 誤引用を今直すか）への意見

**今このブランチで直すのがよい**（4 箇所・各 1 行・`machine-readable` の外・`tests/spec` の読取対象外）。理由:

1. 木の中で**矛盾している**: `layout.md:201` は「`model.md` §3.3 は State の定義であって採番の規律ではない」と書き、同じ木の `adk-mapping.md:124` / `:168` と `codegen.py` は §3.3 を規律として引く。Phase 4 の実装者は両方を読む
2. 変更は文字列の置換だけで、テスト・生成物・スナップショットに影響しない（`adk-mapping.md` の機械可読ブロック 3 本は 14–31 / 96–107 / 127–147 で、4 箇所はすべて外）
3. 「レビュー範囲が広がる」は 4 行のコメント修正には当たらない。分けたいなら PR 内の独立コミット 1 個で足りる

直す先は Phase 3 側と同じ「CLAUDE.md『診断コードは増やさない』/ `docs/adr/ADR-012-DP-JIN-DIAGCODE-NUMBERING-01.md`」。

## 変異で緑のままだったテスト（偽 green の候補）

| 変異 | 対象テスト | 結果 | 意味 |
|---|---|---|---|
| F-V-P3-201 の退行そのもの（事前判定メッセージからパスが消えた状態 = 現行コード） | `test_render.py::test_a_symlinked_output_is_refused` | **緑**（現行 1190 passed の中） | 部分文字列「シンボリックリンク」しか見ておらず、パスの有無を固定していない |
| M-B1b: `_flow_node_limit` から ε を落とす | `test_layout.py` + `test_overlay.py` | **220 passed** | ε と §6 の境界表は未固定（F-V-P3-207） |
| mutate_p3 `CLI-follow-symlink-upfront-only` / `STAR-pre-fix-star-shape-stays` | 各 1 本 | GREEN（期待どおり） | 設計どおり。ラベルの問題は F-V-P3-206 |

赤くなった（非空虚を確認した）もの: M-B2a（svg.py の guard 全削除 → 1 failed）/ M-B2b（CLAUDE.md 8 項目目削除 → 1 failed）/ M-B2c（jin_core に本物の主張・期待集合未更新 → `test_the_scan…` だけ 1 failed）/ M-B3a・M-B3b（弦・節の kind → 各 1 failed）/ M-B1a（0.28 固定 → 23 failed）/ M-B1c（点への退避を消す → 1 failed）/ M-B1d（外枠だけ詰める → 3 failed）/ mutate_p3 の 68 RED。

## 実装者の記録（notes / conformance / plan / layout.md）と実物の不一致

| 記録 | 記述 | 実物 | finding |
|---|---|---|---|
| notes R2.2 項 1 / R2.5 項 5 | Phase 2 の誤引用は「3 箇所（`codegen.py` 2 行 + `adk-mapping.md:124`）」 | 4 箇所（+ `adk-mapping.md:168`） | F-V-P3-202 |
| notes R2.1 C 表 F-V-P3-104 行 | 「競合時にパスが 2 回出るのをやめた」 | 通常時にパスが 0 回になった | F-V-P3-201 |
| notes R2.2 項 9 | 「変更は読解で確認した」 | 読解が退行を見落とした | F-V-P3-201 |
| notes R2.1 C 表 F-V-P3-109 行 | 「「7 項目」に 8 項目目を追記」 | 見出しは「7 項目である」のまま・列挙順 6 / 8 / 7・packaging:399 も「計 7 項目」 | F-V-P3-203 |
| notes R2.1 C 表 F-V-P3-108 行 | 移動 1 件 | 残存 3 + 新規 3 | F-V-P3-204 |
| `test_overlay.py:331` | 「§7.2 の表を書き写す」 | 直下のコメントは「写しではない」 | F-V-P3-205 |
| `mutate_p3.py` の出力 | `STAR-pre-fix-star-shape-stays GREEN (expected: 二層目が守る)` | 2 本目の理由は「星形テストは配置の恒等化で落ちない」 | F-V-P3-206 |
| decision-conformance §2.24.3 | 「入れ子の縮尺 0.28」 | B-1 後は上限 | F-V-P3-208 |
| plan `evidence[]` | 変異 42/42 が最後の行 | R2 実測 70/70 | F-V-P3-209 |
| notes R2.1 B-3 行 | `FLOW_POINTER_KINDS` を追加（結果のみ） | 指示は `POINTER_KINDS` に 2 行。判断は R2.2 に無い | F-V-P3-210 |

一致を確認できた記録: 1190 passed / 68 warnings / 変異 70/70（期待 GREEN 2・SKIP 0・残骸 0）/ ruff 2 ゲート / lint-imports 3 kept / `tests/spec` 62 passed / `TRACE-splitlines` 5 failed / `STAR-pre-fix-visit-order` 7 failed・`STAR-pre-fix-star-shape-stays` 3 passed / `FLOW-*` 3 本 RED / `KIND-*` 2 本 RED / スナップショット差分 0 の根拠（pipeline n=3 の上限 0.416 > natural 0.264）/ 縮み始める n（13 / 5 / 5）と n ≥ 20 / n ≤ 31 の検算 / §6 の式と `_flow_node_limit` / 同一係数の縮小と `_reference_size` / notes P3-3 表の 0.873 / decision-conformance §2.24.1c（式・境界・機械固定・変異名）/ plan `undecided_details` ROUNDING-01 の 1000 px・1.1e-13 / `decision_record` 22 件（実装者は触っていない・R2.3 の主張どおり `grep 1300` は「前回の記録」注記のみ）/ CLAUDE.md の「1〜7 名指し / 8 自己検出」/ layout.md `machine-readable` 2 本（`ring-radii` バイト一致・`data-jin-kinds` 第 1 セル不変）/ `guard: _new_file_mode -> os.umask(mask)` と `guard: _write_svg -> path.resolve()==source.resolve()` が実コードと一致（`test_guard_claims` 24 passed）。

## 補記

- M-B2c の初回は単行 docstring（`"""guard: … -> resolve_pointer(document,pointer)"""`）で書いたため `CLAIM` の `\S+` が閉じ引用符まで拾い `point_at_real_guards` も赤になった。複数行 docstring で再実行（`mut2.py`）し、`test_the_scan…` だけが赤であることを確認した（`mut-B2c-rerun.log`）
- `mutate_p3.py` は `ROOT` をスクリプト位置から解くので、コピー側のスクリプトを worktree の `.venv/bin/python` で実行すると対象はコピーになる。`TMPDIR` をジョブ tmp に向けた（`/tmp` に `jin-mutate-p3-*` の残骸 0）
- ログ: `/home/wisteria/.claude/jobs/e2bcfe94/tmp/rereview2-conventions-scripts/{pytest-full,pytest-spec,ruff-check,ruff-format,lint-imports,mutate_p3,mut-*}.log`
