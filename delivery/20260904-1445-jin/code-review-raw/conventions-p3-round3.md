# Stage 5 review: conventions — Phase 3 (jin-render) 修正ラウンド 3 の最終確認（範囲限定）

レビュア: rereview-p3-r3-conventions（Stage 5・観点 conventions・defect-gone 確認）／ 2026-09-06
対象: ブランチ `feat/jin-phase3-render`（worktree `/home/wisteria/jin-lang/.claude/worktrees/jin-phase3-6`・ベース origin/main `32c215e`）の
修正ラウンド 3 後の状態。入力は前回 finding `conventions-p3-round2.md`（F-V-P3-201〜210）と部分残存 4 件（F-V-P3-108 / 109 / 111 / 104）、
親の指示書 `phase3-fix-round-3-instructions.md`、実装者の対応表 `implementation-notes.md` P3-R3（R3.0〜R3.4）。
本レビューが worktree に書いたのはこのファイル 1 本だけ。

## 実測した環境・コマンド（隔離コピーのパス・件数）

| 項目 | 値 |
|---|---|
| 隔離コピー | `/home/wisteria/.claude/jobs/e2bcfe94/tmp/rereview3-conventions/`（`.venv` / `.git` / `__pycache__` / `.pytest_cache` / `.ruff_cache` を除いて rsync。`diff -rq packages` で worktree と同一を確認）。R2 時点の比較用に前回のコピー `…/rereview2-conventions/` を残したまま使った |
| スクリプト・ログ | `/home/wisteria/.claude/jobs/e2bcfe94/tmp/rereview3-conventions-scripts/{gates.sh,mut_a1.sh}` と `{pytest-full,gates,mutate_p3,mut_a1}.log`。変異は書き換え → 実行 → 復元し、復元後に worktree とバイト一致（`cmp`）を確認 |
| インタプリタ | worktree の `.venv/bin/python`（Python 3.14.7）。`PYTHONPATH` にコピー側 `packages/*/src` を前置、`PYTHONDONTWRITEBYTECODE=1` / `-p no:cacheprovider` / `__pycache__` 削除 / `TMPDIR` をジョブ tmp に |
| `pytest`（全体・コピー上） | **1201 passed**, 68 warnings, 6 snapshots passed（39.57s）。notes R3.0 / R3.3 の 1201 / 68 と一致。**注**: `pyproject.toml` の `addopts = "-q …"` に `-q` を重ねると summary 行が出ない（1 回目のログに件数が無かった）ので `-o addopts=""` で再計測 |
| `pytest tests/spec` | **62 passed** |
| `ruff check .` / `ruff format --check .`（cwd=コピー） | All checks passed / 77 files already formatted |
| `lint-imports`（cwd=コピー） | Contracts: 3 kept, 0 broken |
| `mutate_p3.py`（コピー上・`TMPDIR` をジョブ tmp に） | baseline 394 passed・**75/75 mutations caught**（期待 GREEN 2・SKIP 行 0・`/tmp` とジョブ tmp に残骸 0）。notes R3.0 / R3.3 と一致。新規 5 本はすべて RED: `FLOW-limit-drops-epsilon` **18 failed**（notes と一致）/ `FLOW-point-fallback-off` 1 failed / `CLI-symlink-message-without-path` 1 failed / `CLI-success-message-raw-echo` 1 failed / `CLI-no-closed-stdout-branch` 1 failed。R3.2 項 4 の 4 本（`CLI-follow-symlink-*` / `CLI-stdout-oserror-traceback` / `CLI-build-success-unsafe`）は SKIP でなく RED / 期待 GREEN |
| 独自変異（`mut_a1.sh`） | **M-A1a**（`render` 側で `SymlinkWriteRefused` にもパスを前置 = 2 回出る）→ `test_a_symlinked_output_is_refused` **1 failed**（`count == 1` が効く）。**M-A1b**（一層目の文言からパスを落とす）→ **1 failed**。**M-A1c**（モジュール docstring の `guard: _write_svg -> _write_atomically(...)` を `_write_in_place(path,text)` に）→ `test_guard_claims_point_at_real_guards[jin-cli/…/main.py]` **1 failed** |
| `model.md §3.3` の誤引用（grep 実測） | `packages` / `docs` / `tests` / `CLAUDE.md` / `README.md` で `model\.md.*3\.3` は **`layout.md:201` の 1 件だけ**（「§3.3 は State の定義であって採番の規律ではない」という否定の文なので正しい）。`codegen.py:27` / `:73`・`adk-mapping.md:124` / `:168` は「`CLAUDE.md` / ADR-012」に直っており、`docs/adr/ADR-012-DP-JIN-DIAGCODE-NUMBERING-01.md` は実在 |
| R2 → R3 のコード差分 | `packages/jin-render/src` は `layout.py` の**コメント 1 箇所**（F-C-P3-102 の残り）だけ。`jin_cli/main.py` は 69 行差分（A-1 / B-3 / B-4 / docstring）。R3.2 項 6「コードは変えていない」と一致 |
| `docs/pending-decisions.md` | 生成器 `pending-decisions-generator/bin/generate.py --check`（プラグインキャッシュの同一スクリプト）をコピー上で実行 → **exit 0**（自動生成ブロックに差分なし）。`DP-REVIEW-JIN-P3-001` は未決リストの 10 行目に載る |
| worktree の不変性 | `git status --short` に本ファイル以外の本レビュー由来の変更なし |

## 前回 finding の判定

判定の語: **defect-gone** / **部分残存** / **残存** / **記録のみ（理由妥当）** / **記録のみ（理由不十分）**

| finding | 判定 | 根拠（実測） |
|---|---|---|
| F-V-P3-201（= 104 の悪化）A-1 | **defect-gone**（ただし文言の**形**は主張と逆・F-V-P3-301） | `main.py:1006` 一層目 `SymlinkWriteRefused(f"シンボリックリンクなので書き込みを拒みました: {path}")`、`:420` 二層目も同文・`:1093-1097` `render` は前置しない。テスト `test_render.py:112` `str(link) in result.output` + `:114` `count(str(link)) == 1`。変異: `CLI-symlink-message-without-path` RED / 独自 M-A1a・M-A1b とも 1 failed。通常経路でパスが 1 回出る |
| F-V-P3-202 A-3 | **defect-gone** | 4 箇所すべて「`CLAUDE.md` / ADR-012」。grep 残り 0（否定文の `layout.md:201` を除く）。`tests/spec` 62 passed。notes R2.2 項 1 は取り消し線 + 「4 箇所」+ R3.1 A-3 に列挙 |
| F-V-P3-203（= 109 の部分残存） | **部分残存**（軽微） | `test_dependency_direction.py:221` は「**8 項目**である」、列挙は 1〜8 の順に直った。`test_packaging_contract.py:305` に「（全 8 項目）」。**`test_packaging_contract.py:399`「計 7 項目」はそのまま**（前回 finding が名指しした 2 ファイル目）。同テスト `:415-417` は 8 項目目を見ているので docstring の数だけが古い |
| F-V-P3-204（= 108 の部分残存） | **部分残存**（軽微） | `time` / `hashlib` / `subprocess` / `sys` の 4 箇所は先頭へ移った。残り **2 箇所**: `test_render.py:390`（`from jin_cli.main import _new_file_mode`。先頭 `:17` に `from jin_cli.main import app` があるのでそこへ足せる）/ `tests/contract/test_render_contract.py:41`（`import xml.etree.ElementTree as ET`） |
| F-V-P3-205（= 111 の部分残存） | **残存** | `test_overlay.py:326` 節見出し「layout.md §7.2 の表を**書き写す**」のまま。直下 `:329-331` は「写しではない」。notes R3.0 は「F-V-P3-111 は R2 で対応済み」と書くが、205 は R2 後の見出しを指した finding で、R3 で触っていない |
| F-V-P3-206 / F-W-P3-204 | **defect-gone** | `mutate_p3.py:776-785` `EXPECT_GREEN_REASON: dict[str, str]`（`two-layer` = 「二層目が守る」/ 「主張そのもの（星形テストは配置の恒等化では落ちない）」）、`EXPECT_GREEN = set(EXPECT_GREEN_REASON)`、`:939` ラベルに理由を差し込む。実測ログ: `STAR-pre-fix-star-shape-stays GREEN (expected: 主張そのもの（…））` |
| F-V-P3-207 | **defect-gone** | `test_every_flow_chord…` の下限を `2 * (ARROW_HEAD + ε)` に。変異 `FLOW-limit-drops-epsilon`（レビューの M-B1b と同じ置換）**18 failed**（R2 では 220 passed だった） |
| F-V-P3-208 | **残存**（低） | `decision-conformance.md:641` §2.24.3 は「入れ子の縮尺 0.28」のまま（「上限」の語なし）。`layout.md` §7.2 の `/circles/i/flow/steps/j` 行は「参照が解決すれば外枠 + 入れ子の小陣、しなければ点」のまま（n ≥ 20 の点への退避なし）。指示書 C「203〜210 の残り（本文を読む）」の対象だが R3.1 / R3.2 に言及なし |
| F-V-P3-209 | **残存**（低・所管は親） | `implementation-plan.json:2140` `[jin_phase=3][mutation] … 42/42 caught` が変異の最終行。R1 59/59・R2 70/70・R3 75/75 の evidence 行なし。R3.3「plan の変更は `DP-REVIEW-JIN-P3-001` の追加だけ」と整合（実装者は指示どおり触っていない） |
| F-V-P3-210 | **残存**（低） | notes R2.2（1543 行〜）の 12 項目に `FLOW_POINTER_KINDS` を別リストにした判断は無い（R2.1 B-3 行 `:1504` に結果だけ） |
| F-V-P3-104 | **defect-gone** | 二層目・一層目ともパス入り、`render` は前置しないので、どの層が拒んでも 1 回。M-A1a（前置を復活）が `count == 1` で赤 |
| F-V-P3-108 / 109 / 111 | 上の 204 / 203 / 205 に同じ | — |

集計: defect-gone **6**（201 / 202 / 206 / 207 / 104 と 108〜111 の親 finding の Phase 3 側）/ 部分残存 **2**（203 / 204）/ 残存 **4**（205 / 208 / 209 / 210・いずれも低・文言と記録）。
指示書 A（3 件）・B（4 件）のうち conventions 所管の A-1 / A-3 は **defect-gone**。B-1 / B-2 の文書側（layout.md §6・decision-conformance §2.24.1c・R2.2 項 4）は下で検算した。

### A-2 / B-1 / B-2 の文書側（conventions 観点）

- **A-2**: R2.2 項 5 は「理由は誤りだった / BOM だけの行は現状で既に exit 2 / `str.strip()` は U+FEFF を落とさない」に書き直され、判断〔記録のみ〕は不変。`test_a_bom_only_line_is_refused`（`test_render.py:439`）と `test_a_unicode_whitespace_only_line_is_skipped`（`:456`・U+3000 / U+00A0）が実在
- **B-1**: `DP-REVIEW-JIN-P3-001`（`implementation-plan.json:2370-2377`）の鍵は `id / title / raised_by / decide_by_phase / phase_impact / parent_dp / note` で、`DP-REVIEW-JIN-P2-001` / `P2-002`（`:2302` / `:2311`）と**同一の書式**。`raised_by` は「impl-p3 (Phase 3 修正ラウンド 3・Stage 5 再レビュー F-C-P3-201 による起票)」で P2 の「impl-p2 (Phase 2 修正ラウンド 1・correctness review F-C-P2-016)」と同形。`undecided[]`（`:1841-1843`）に追加済み。`docs/pending-decisions.md:24` に載り、生成器 `--check` が exit 0。`layout.md` §6 の段落（276〜284 行）と `decision-conformance.md` §2.24.1c 末尾の 3 行が同じ数字（n = 6 / n = 7・内縁 0.227〜0.286）。検算: 最大 r = 0.28·1.01 + 0.04 = 0.3228 → 2r = 0.6456 は n=6 の隣接距離 0.55 を超え n=5 の 0.6466 は超えない（n ≥ 6 ✓）。examples 同型 r = 0.264 → 2r = 0.528 は n=7 の 0.4773 を超え n=6 の 0.55 は超えない（n ≥ 7 ✓）
- **B-2**: `layout.md` §6 の 3 段表（n ≤ 31 / 32 ≤ n ≤ 57 / n ≥ 58）と「n >= 20 で点」、`decision-conformance.md:610-613`（n >= 20 / **n >= 32** / **n >= 58**）、notes R2.2 項 4（(a) n >= 32 / (b) n >= 58）の**三者が一致**。検算: n=20 で 0.55·sin(π/20) − 0.06 = 0.0260 < 0.03、n=19 で 0.0305 ≥ 0.03 ✓。n=31 で 1.1·sin(π/31) − 0.06 = 0.0513 ≥ 0.05、n=32 で 0.0478 < 0.05 ✓。n=58 で 1.1·sin(π/58) = 0.05955 ≤ 0.06（`_arrow_d` は `length <= gap_start + gap_end` で `None`・`layout.py:146`）、n=57 で 0.0606 > 0.06 ✓。テスト `test_the_two_crowding_boundaries`（31 / 32 / 57 / 58）と `test_a_crowded_flow_falls_back_to_points`（19 / 20 / 40）が実在し、変異 `FLOW-point-fallback-off` RED

### `main.py` モジュール docstring の安全主張と実装の一致（R3.2 項 1）

`main.py:56-60`「`_write_svg` が先に見る 5 条件のうち 4 つ（シンボリックリンク / ディレクトリ / 親の有無 / 既存）は文言のための早期判定であって防御ではない … 残る 1 つ『`-o` が入力の `.jin` と同じ』だけは二層目が無い実効防御」は `_write_svg`（`:1002-1016`・5 つの `if`）と関数 docstring（`:984-993`「4 条件 + 1 条件」）に一致する。`guard: _write_svg -> _write_atomically(path,text,allow_create=True)` は実コードと一致し、嘘に変えると `test_guard_claims` が赤（M-A1c）。**一致しないのは 1 文**: `:60`「どの条件も文言にパスを含める（`path: 理由`）」— パスを含めるのは事実だが、**並びは symlink だけ `理由: path`**（下の F-V-P3-301）。

## Findings（修正が持ち込んだ・見落とした新規欠陥）

### F-V-P3-301 [confidence 60] A-1 の symlink 文言は `理由: path` の並びで、コメント・docstring・notes が言う「他の条件と同じ `path: 理由` の形」と逆

- 場所: `packages/jin-cli/src/jin_cli/main.py:1006`（一層目 `f"シンボリックリンクなので書き込みを拒みました: {path}"`）、`:1003`（直上コメント「他の 3 条件と同じ `path: 理由` の形」）、`:60`（モジュール docstring「どの条件も文言にパスを含める（`path: 理由`…）」）、`:1098`（`render` が他の `WriteRefused` に `f"{out}: {exc}"` を前置 = `path: 理由`）、notes R3.1 A-1 行（「二層目と同じ `path: 理由` の形」）、指示書 A-1（「`fmt` / ディレクトリ拒否と同じ `path: 理由` の形」）
- 内容: 同じ `jin render -o` の 5 条件で、ディレクトリ / 親なし / 既存 / 入力と同じ は `<path>: <理由>`、symlink だけ `<理由>: <path>` と、**並びが 2 種類**ある。実装側の一貫性（二層目 `:420` と `fmt` の `:590` も `理由: path`）はあるので「symlink 系は `理由: path`」と言えば筋は通るが、コード・docstring・notes・指示書の 4 箇所が全部 `path: 理由` と書いており、**主張と実装の不一致**（このラウンドで潰している型そのもの・R3.2 項 1 の論拠）。CliRunner 実測（M-A1a の前の素の状態）: `シンボリックリンクなので書き込みを拒みました: /…/out.svg`
- 変異検証: `test_a_symlinked_output_is_refused` は `str(link) in output` と `count == 1` しか見ないので、並びをどちらにしても緑（偽 green 表）。M-A1a / M-A1b は「パスの有無・回数」を固定するもので並びは見ていない
- 提案: どちらかに揃える。(a) 一層目・二層目・`fmt` を `f"{path}: シンボリックリンクなので書き込みを拒みました"` にして `path: 理由` を実現する（3 箇所の置換・二層目は `_write_atomically` 経由で `fmt` にも出るので `fmt` のテスト `"シンボリックリンク" in output` は緑のまま）。(b) 実装はそのままにして `:60` / `:1003` / notes R3.1 A-1 を「`理由: path`（`fmt` の同種メッセージ・二層目と同形）」に直す。安いのは (b)。どちらでもテストに `output.startswith(str(link))` か `output.endswith(f": {link}\n")` を 1 行足して並びを固定する

### F-V-P3-302 [confidence 55] `layout.md` §6 の相互参照の向きが逆（表セルの「上記」が指す段落は下・段落の「下の表」が指す表は上）

- 場所: `docs/spec/layout.md:215`（紋（tool）の半径 行「**`summon` の外枠はこの値ではない**（**上記**・DP-REVIEW-JIN-P3-001）」）と `:283`（「**下の表**の『12 個並べても重ならない』は `tool`（円）と `builtin`（四角）の半径 0.06 についての記述」）
- 内容: 表は 210〜240 行、`summon` の重なりの段落は 276〜284 行。表から見て段落は**下**、段落から見て表は**上**。B-1 で両側に注記を足したときに向きを取り違えた。`tests/spec` は `machine-readable` ブロック（`ring-radii` / `data-jin-kinds`）しか読まないので緑
- 提案: `:215` を「（下記・DP-REVIEW-JIN-P3-001）」、`:283` を「上の表の」に

### F-V-P3-303 [confidence 50] R3.0「C 節 10 件・8 件を直し・2 件は記録のみ」は数え違い。205 / 208 / 209 / 210 は直っておらず、記録のみ一覧にも無い

- 場所: notes R3.0（`:1653-1657`）、R3.1 の C 表（`:1670-1683`）、R3.2 項 5（「F-S-P3-203〜205 / F-W-P3-203 は記録のみ」）
- 内容: 指示書 C は「F-V-P3-203〜210 の残り（本文を読む）」と 8 件を名指しする。R3 で直したのは 203（部分）/ 204（部分）/ 206（= F-W-P3-204）/ 207 で、**205 / 208 / 209 / 210 は変更も「直さない」判断の記録も無い**。R3.0 の「F-V-P3-111 は R2 で対応済み」は round2 の判定（部分残存 → 205）と食い違う。209 は所管が親（plan evidence）なのでそう書けばよい
- 提案: R3.2 に 205 / 208 / 210 を直す（各 1〜2 行）か「直さない理由」を書き、209 は親が最終ラウンド後に `[jin_phase=3][fix-round-3][mutation] 75/75` / `[gates] 1201 passed` の 2 行を plan `evidence[]` に足す

## R3.2「指示と違えた判断 / 記録のみ」6 件の評価

| # | 判断 | 評価 |
|---|---|---|
| 1 | 指示に無い変更 2 つ（`main.py` モジュール docstring の 4 + 1 化 / `test_a_crowded_flow_falls_back_to_points` の n=19/20 化 + `FLOW-point-fallback-off`） | **妥当**。docstring は関数 docstring（R2）と一致し `guard:` 主張も実コードにある（M-A1c 赤）。ただし同じ段落の「`path: 理由`」が実装と逆（F-V-P3-301）。n=19/20 は §6「n >= 20 で点」の境界を初めて固定したもので、B-2 の趣旨（境界を機械固定）の内側 |
| 2 | `CLI-symlink-message-without-path` が最初 GREEN（二層目を書き換えていた）→ `before` にコメント行を含めて一意化 | **妥当**。`mutate_p3.py:618-629` の `before` は直前のコメント行込みで一層目にしか一致しない。実測 RED（1 failed）。独自 M-A1b も同じ的で 1 failed |
| 3 | `FLOW-point-fallback-off` が最初 GREEN → n=19/20 を足して RED | **妥当・良い判断**。R2 の `FLOW-no-node-limit` と同じ規律（変異が緑ならテストを足す）。実測 1 failed / 6 passed |
| 4 | B-3 の共通化で 4 本が SKIP → `before` を合わせ直して SKIP 0 | **妥当**。実測ログに SKIP 行 0、当該 4 本は RED（`CLI-follow-symlink-both` / `CLI-stdout-oserror-traceback` / `CLI-build-success-unsafe`）と期待 GREEN（`CLI-follow-symlink-upfront-only`） |
| 5 | F-S-P3-203〜205 / F-W-P3-203 は記録のみ | **妥当**（指示どおり）。ただし conventions 所管の 205 / 208 / 210 が同じ一覧に無い（F-V-P3-303） |
| 6 | `DP-REVIEW-JIN-P3-001` はコードを変えていない | **妥当・実測一致**。R2 コピーとの差分で `jin_render/src` は `layout.py` のコメント 1 箇所のみ。`undecided_details` の書式は P2-00x と同一、`undecided[]` と `pending-decisions.md`（生成器 `--check` exit 0）に載る。判断期限「Phase 5 のエディタ着手前」の理由（hit-test）も note に書いてある |

## 変異で緑のままだったテスト（偽 green の候補）

| 変異 | 対象テスト | 結果 | 意味 |
|---|---|---|---|
| symlink 文言の並びを `path: 理由` ⇄ `理由: path` で入れ替える（現行は `理由: path`） | `test_render.py::test_a_symlinked_output_is_refused` | **緑**（部分文字列 + 回数のみ） | 並びは未固定（F-V-P3-301）。パスの有無・回数は M-A1a / M-A1b で赤を確認済み |
| mutate_p3 `CLI-follow-symlink-upfront-only` / `STAR-pre-fix-star-shape-stays` | 各 1 本 | GREEN（期待どおり・理由がラベルに出る） | 設計どおり（F-V-P3-206 解消） |

赤くなった（非空虚を確認した）もの: M-A1a（前置復活 → `count == 1` で 1 failed）/ M-A1b（パス削除 → 1 failed）/ M-A1c（docstring の guard を嘘に → `test_guard_claims` 1 failed）/ mutate_p3 の 73 RED（新規 5 本を含む・`FLOW-limit-drops-epsilon` 18 failed）。

## 実装者の記録（notes / conformance / plan / layout.md）と実物の不一致

| 記録 | 記述 | 実物 | finding |
|---|---|---|---|
| notes R3.1 A-1 / `main.py:60` / `:1003` / 指示書 A-1 | symlink 文言は「`path: 理由` の形」 | `理由: path`（`シンボリックリンクなので書き込みを拒みました: <path>`） | F-V-P3-301 |
| `layout.md:215` / `:283` | 「上記」/「下の表」 | 段落は下・表は上 | F-V-P3-302 |
| notes R3.0 | 「C 節 10 件・8 件を直し・2 件は記録のみ」「F-V-P3-111 は R2 で対応済み」 | 205 / 208 / 209 / 210 は未対応・未記録。111 は round2 で部分残存（205） | F-V-P3-303 |
| notes R3.1 C 表 F-V-P3-109 行 | 「`test_packaging_contract.py:305` に（全 8 項目）」 | `:399`「計 7 項目」は残る | 203 部分残存 |
| notes R3.1 C 表 F-V-P3-108 / 204 行 | 4 箇所を先頭へ | 残り 2 箇所（`test_render.py:390` / `test_render_contract.py:41`） | 204 部分残存 |
| `decision-conformance.md:641` §2.24.3 | 「入れ子の縮尺 0.28」 | §2.24.1c と §6 は「上限」 | 208 残存 |
| plan `evidence[]` | 変異 42/42 が最終行 | R3 実測 75/75 | 209 残存（所管は親） |

一致を確認できた記録: 1201 passed / 68 warnings / 6 snapshots / 変異 75/75（期待 GREEN 2・SKIP 0・残骸 0）/ `FLOW-limit-drops-epsilon` 18 failed / ruff 2 ゲート / lint-imports 3 kept / `tests/spec` 62 passed / `model.md §3.3` 誤引用 4 箇所 → 0 / R2.2 項 1・4・5 の書き直し / `EXPECT_GREEN_REASON` のラベル出力 / `DP-REVIEW-JIN-P3-001` の書式・`undecided[]`・`pending-decisions.md`（生成器 `--check` exit 0）/ layout.md §6 ⇄ decision-conformance §2.24.1c ⇄ notes R2.2 項 4 の数字（20 / 32 / 58・n = 6 / 7・0.227〜0.286）と検算 / `_arrow_d` の `<=` と n = 58 / モジュール docstring の 4 + 1 と `_write_svg` の 5 分岐 / `guard:` 2 本が実コードに一致（M-A1c 赤）/ R2 → R3 で `jin_render` はコメント 1 箇所だけ / notes R2.1 の ADR-021 → 「ADR-022（起票時は ADR-021）」（`ADR-021` の残りは grep で notes 2 行の履歴注記のみ・plan / conformance / layout.md / pending-decisions に無し・`docs/adr/ADR-022-…` 実在）。

## 補記

- 全体 pytest の 1 回目は `pyproject.toml` の `addopts = "-q --import-mode=importlib"` に `-q` を重ねて `-qq` になり summary 行が消えた。`-o addopts=""` で再計測して 1201 を得た（テスト自体は同じ・exit 0）
- `docs/pending-decisions.md` は「直接編集禁止・自動生成」だが、生成器（`~/.claude/plugins/marketplaces/xtone-ai-delivery/plugins/*/skills/common/pending-decisions-generator/bin/generate.py`）を `--plugin-root <コピー> --check` で回して exit 0。手書きか再生成かに関わらず内容は生成物と一致している
- ログ: `/home/wisteria/.claude/jobs/e2bcfe94/tmp/rereview3-conventions-scripts/{pytest-full,gates,mutate_p3,mut_a1}.log`
