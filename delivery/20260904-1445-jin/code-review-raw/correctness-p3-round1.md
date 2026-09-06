# Stage 5 review: correctness — Phase 3 (jin-render) 再レビュー round 1

- 入力: 前回 finding `correctness-p3.md`（F-C-P3-001〜013）、親の指示書 `phase3-fix-round-1-instructions.md`、
  実装者の対応表 `implementation-notes.md` P3-R1（R1.1 / R1.2 / R1.6）
- 判定材料は差分コード・生成 SVG・テスト・仕様だけ。実装者の「直しました」「変異で赤」は根拠にせず、
  隔離コピーで**自分の変異**を入れて赤を実測した
- confidence の基準は前回と同じ: 85 以上 = 隔離コピーで実測して直接確認、60〜80 = 実測で間接確認または解釈の余地、
  60 未満 = 読解のみ / 記述の不一致

## 実測した環境・コマンド（隔離コピーのパス・件数）

- 隔離コピー: `/home/wisteria/.claude/jobs/e2bcfe94/tmp/rereview-correctness/`（`packages` / `tests` / `examples` / `docs` /
  `schemas` / `pyproject.toml` / `jin-requirements.md` / `CLAUDE.md` / `README.md` / `delivery/20260904-1445-jin` を `cp -r`）
- 実行: `run_pytest.sh`（`PYTHONDONTWRITEBYTECODE=1`・`__pycache__` 削除・`PYTHONPATH` にコピー側 4 パッケージの `src`・
  `--import-mode=importlib -p no:cacheprovider`・python は worktree の `.venv`）。コピー側を import している証拠は
  `probe_r1.py` 冒頭の `jin_render.__file__` 表示と、コピー側だけを書き換えた変異で結果が変わったこと
- ベースライン（コピー）: `packages/jin-render/tests` + `packages/jin-cli/tests/test_render.py` → **261 passed・4 snapshots passed**
  （前回 177 → 261。実装者申告の全体 1100 は再実測していない）
- 契約（コピー）: `tests/contract/test_render_contract.py` → **12 passed**（A-1 の端到端 `jin run --model fake --trace` → `jin render` と、
  F-S-P3-010 の別プロセス `PYTHONIOENCODING=ascii` を含む。前回 `delivery/` 不在で落ちた 7 件は今回コピーに含めたので出ない）
- 実測スクリプト（同ディレクトリ）: `probe_r1.py`（loop n=3..12 の配置と矢印 / `_outer_extent` と実描画の最外半径 13 構成 /
  pipeline の弦端 / `is_ancestor_or_same` 境界 11 例 / 50 000 行トレースの時間 / ストリーム読み 15 例 / umask 3 値）、
  `probe_r1b.py`（弦が消える閾値）、`mutate_r1.py`（変異 22 件・非スナップショット と スナップショットのみ の 2 通り）
- 実ツリーは本ファイルの追加以外に変更していない（変異のたびに `cmp` で worktree のソースとバイト一致を確認）。
  `git status --short` に他エージェントによる `docs/adr/ADR-021-*.md` の追加が同時に現れているが、本レビューの操作ではない

## 1. 前回 finding の判定（13 件）

| ID | 前回の要旨 | 判定 | 根拠（実測） |
|---|---|---|---|
| F-C-P3-001 | `splitlines()` が U+2028 等で割る | **defect-gone** | `main.py:879-881` が `open(newline="\n")` のストリーム読み + `removesuffix("\n").removesuffix("\r")`。probe: U+2028 を値に含む 1 行 → exit 0・点 1。変異 `001-splitlines`（`handle.read().splitlines(keepends=True)` に戻す）で `test_a_row_containing_a_unicode_line_break_is_read[NEL]` ほか **赤** |
| F-C-P3-002 | loop の矢印が j→j+k で訪問順と逆 | **defect-gone** | `layout.py:583`（節 j → 角位置 `(j*k) mod n`）と `:600`（辺 j→j+1）。probe: n=3..12 の全てで「配置 = (j·k) mod n」「矢印 = j→j+1」「角位置差 = k（星形）」が成立・辺数 = n。変異 `002-reversed` で `test_loop_nodes_are_placed_so_the_arrows_follow_the_visit_order` **赤**。layout.md §2.1 / §6 は実装と一致（文書内の食い違いは解消）。ただし変異の効き方についての記録の誤りが 1 件（§4 の F-C-P3-104） |
| F-C-P3-003 | summon の紋（外枠）が描かれず朱が見えない | **defect-gone** | `layout.py:435-447` が wrapper 直下に `<circle data-jin=参照側 data-jin-ref=参照先>` を置く。変異 `003-no-outline` で `test_a_summon_draws_a_visible_outline_*` / `test_the_summon_outline_follows_*` / `test_the_radial_line_stops_*` **赤** |
| F-C-P3-004 | `seq <= 0` を受理 | **defect-gone** | `overlay.py:83`（`1 <= seq <= SEQ_MAX`）。probe: `--upto 0` で点 0・強調なし。変異 `004-no-lower-bound` で `test_a_seq_outside_the_range_is_refused[0/-1]` と `test_a_seq_below_one_exits_two[0/-1]` **赤**（前回は同じ変異で 126 件緑だった） |
| F-C-P3-005 | 弦・放射線の終端が固定 0.266 で実物の環と合わない | **defect-gone（部分的に未固定）** | `layout.py:309-342`。pipeline 実測: Drafter への弦端 = 外枠 r = 105.6 px（= (0.28×0.80+0.04)×400）、Refine への弦端 = 80.96 px（flow のみ 0.58）で外枠に接する。変異 `005-fixed-extent` / `005-gap-zero` / `state`・`boundary`・`instruction` の項を落とす変異は非スナップショットで **赤**。一方 `flow` / `delegate` / `tools` の項を落とす変異は非スナップショットで**緑**（`flow` はスナップショット 2 本だけが赤、`delegate` / `tools` はスナップショットも緑）→ §4 の偽 green 表 |
| F-C-P3-006 | 親ディレクトリ不在の文言が「消えました」 | **defect-gone** | `main.py:953-955`。変異 `006-no-parent-check` で `test_a_missing_parent_directory_is_refused_without_creating_it` **赤** |
| F-C-P3-007 | 到達しない `accent_attr="fill"` | **defect-gone** | `layout.py:746-747` で引数を外しコメント化（読解） |
| F-C-P3-008 | 存在しない規則番号 | **defect-gone** | `test_overlay.py:184`「§7.1 規則 2（`data-jin-ref` 一致）」。「規則 4」「祖先一致」の番号付き表記は消えた（grep） |
| F-C-P3-009 | ダイジェスト末尾バイトの記述が 3 箇所で食い違う | **defect-gone** | layout.md:101 / ornament.py:16 / test_determinism.py:152 の 3 箇所とも「添字 24（= 25 バイト目）」（grep） |
| F-C-P3-010 | 丸め根拠「1300 px 級」 | **defect-gone** | layout.md §4 / decision-conformance §2.24.1 / test_svg.py に `1300` は残っていない（grep 0 件）。「最大座標は 1000 px・1 ULP 約 1.1e-13 px」 |
| F-C-P3-011 | 成功メッセージだけ `_safe` を通さない | **defect-gone** | `main.py:1040`。変異 `011-success-unsafe` で `test_the_success_message_does_not_carry_control_characters` **赤** |
| F-C-P3-012 | 核なし + state / boundary / delegate の描画が未検査 | **defect-gone** | `test_a_flow_circle_with_state_and_delegate_still_draws_them`。前回緑のままだった 2 変異（`012-state-ring-needs-core` / `012-delegate-line-from-core-only`）がどちらも **赤** |
| F-C-P3-013 | `pointer_prefixes("/")` | **defect-gone** | 関数ごと削除（grep 0 件）。後継 `is_ancestor_or_same` の境界は §2 の A-3 で確認 |

defect-gone **13 / 13**（005 は挙動は直っているが、`_outer_extent` の 3 項がテストに固定されていない）。残存 0。

## 2. 重点確認（R1.6 と親の指示）

### R1.6-1 / C-1: loop の星形と訪問順（n=5..12 の実測）

`probe_r1.py` で SVG から節の中心角と弦の両端角を自分で計算した（テストの `_nearest` に頼らない）:

```
n= 5 k=2 配置=(j*k)%n:True 矢印=j->j+1:True 角位置差=k:True 辺数=5
n= 6 k=1 … True True True 6 / n= 7 k=3 … 7 / n= 8 k=3 … 8 / n= 9 k=4 … 9
n=10 k=3 … 10 / n=11 k=5 … 11 / n=12 k=5 … 12   （n=3, 4 は k=1 で配列順のまま・True）
```

要件書 §2.5 の読みとして: 「星形多角形 {n/k} で描き、辺の順を訪問順に一致させる」の素直な読みは「辺列を順に辿ると
`flow.steps` の実行順になる」であり、(a) はこれを {n/k} を崩さずに満たす唯一の配置（gcd(n,k)=1 で全単射）。
§2 の「配列順、等角配置」の箇条は紋（tools）についての文で、節の配置とは矛盾しない。**読みは妥当**。
examples に loop が無いのでスナップショットに 1 px も出ない点は実装者の申告どおり（`002-slot-identity` はスナップショット 4 本緑）。

### R1.6-5 / B-1: `_outer_extent` の列挙と実描画の最外半径

入れ子 `<g data-jin="/circles/1">` 配下の全要素（円は中心距離 + r、線は端点、path は M/L の点と C の**終点**。ベジェの制御点は
弧の外に出るので除外）から中心までの最大距離を、13 構成で `_outer_extent` と突き合わせた:

| 構成 | 列挙 | 実描画 | 差 |
|---|---|---|---|
| core のみ / +instruction / +tool(円) / +boundary(guards) / +boundary(空) / +tool+await / +delegate / flow のみ / +exit / parallel | 一致 | 一致 | 0 |
| core+builtin（四角） | 0.6100 | **0.6129** | 列挙が 0.0029 小さい（四角の角 `hypot(0.61, 0.06)`） |
| core+state（四角） | 0.8000 | **0.8016** | 列挙が 0.0016 小さい（`hypot(0.80, 0.05)`） |
| core+summon(A)（深さ 2 は点） | 0.6100 | 0.5800 | 列挙が 0.03 大きい（安全側） |

四角 2 種の角は列挙を超えるが、入れ子縮尺で 0.33 px / 0.18 px。`SUMMON_GAP` 0.04（16 px）に吸収されるので外枠が中身に
食い込むことは無い。docstring「**実際に**届く最大半径」の厳密な意味では不一致（F-C-P3-102・低）。

### A-3: `is_ancestor_or_same` の境界

```
('/circles/1', '/circles/10')=False  ('/circles/1', '/circles/10/core')=False  ('/circles/1', '/circles/1x')=False
('/circles/1', '/circles/1/')=True   ('/circles/1/', '/circles/1')=False      ('/circles/1', '/circles/1')=True
('', '')=True  ('', '/circles/1')=False  ('/circles/1', '')=False  ('/', '/circles/1')=False  ('/', '/')=True
('/circles/1', '/circles/1//core')=True
```

いずれも JSON Pointer の祖先関係として正しい（末尾 `/` は空キーの子・`''` は描画要素に無いので何も強調しない）。
行 pointer `''` / `'/'` → 強調 0、`'/circles/10/core'` → 0、`'/circles/1/'` → `/circles/1` と参照要素、`'/circles/0/flow/max'` →
`/circles/0/flow`（§7.2 の記述どおり）。旧「末尾から削って最初の段」と新「最長一致の鍵」は等価（同じ長さの候補は同一文字列なので tie は無い）。
変異 `A3-first-match`（最長でなく最初の一致）と `A3-not-segment-wise`（`/` 境界を見ない）はどちらも **赤**。
性能: 50 000 行 × `/circles/2/core` の render 0.44 s、5 000 行 × 5 000 段 0.04 s（rows × 鍵数 の二重ループは実用上問題なし）。

### A-1: ストリーム読み（`_read_trace_rows`）

| 入力 | 結果 |
|---|---|
| 空ファイル | exit 0・点 0 |
| 最終行に改行無し / CRLF + 最終行改行無し / `\r\r\n` | exit 0・全行受理 |
| 孤立 `\r`（旧 Mac） | exit 2・`:1: JSON として読めません（Extra data）`（writer は書かない区切りなので妥当） |
| UTF-8 BOM 付き | exit 2・`Unexpected UTF-8 BOM`（`jin run` は書かない。修正前と同じ挙動・非退行） |
| 3 行目が壊れ（空行を挟む） | exit 2・`:3:`（実ファイル行番号・B-3 のとおり） |
| U+2028 だけ / NBSP だけ / FF だけ / ASCII 空白だけ の行 | **exit 0・黙って読み飛ばす**（F-C-P3-103・低） |
| 10 MB の 1 行 | exit 0・0.89 s |

### C-2: umask

`_new_file_mode()`（`main.py:332-346`）は `mkstemp` の後に呼ばれるので umask 0 の窓でファイルは作られない。実測
umask 022 → 0644、077 → 0600、002 → 0644（= `0o644 & ~umask`）。変異 `C2-ignore-umask` で 2 テスト **赤**。
`jin build` の `os.open(..., 0o644)` の実効モードと一致する（指示書の `0o666` は `jin build` と矛盾していたので、実物に揃えた判断が正しい）。

### R1.6-2: 外枠の kind

`DATA_JIN_KINDS` は 9 種のまま（`layout.py:50-60`）。外枠は `tool` / `flow-edge` の使い回し。1 pointer に wrapper `<g>` と
外枠 `<circle>` の 2 要素が付くのは Phase 5 の hit-test への申し送りで、欠陥ではない（layout.md §3.1「同じ pointer を持つ要素が
複数あってよい」）。ただし外枠の kind を `circle` に変える変異は**スナップショットしか捕まえない**（§4）。

## 3. R1.2「指示書と違えた判断」9 件の評価

| # | 判断 | 評価 |
|---|---|---|
| 1 | C-2 の期待値を `0o644 & ~umask` に | **妥当**。指示書自身が「`jin build` に合わせる」と `0o666` で矛盾。`jin_adk/build.py` の実物 `0o644` に揃え、`jin build` の出力と突き合わせるテストを置いた（umask 027 で実測一致） |
| 2 | F-S-P3-010 を `sys.stdout.buffer` への UTF-8 書き出しに | **妥当**。包むだけでは日本語 rune が `PYTHONIOENCODING=ascii` で描けない。別プロセスのテストで実測している |
| 3 | A-1 の端到端を `core` ではなく `output` の U+2028 で | **妥当**。`core` は Ident で `name` に載る経路が無く、実際に生で載るのは `output`。空虚化防止の assert 2 本（`" " in raw`・`splitlines` と `split("\n")` の数が違う）がある |
| 4 | U+000B / U+000C を対象から外す | **正しい**。`json.dumps` は 0x20 未満を必ずエスケープする。probe でも FF 単独行は JSON 不正 |
| 5 | B-5 の実効範囲は U+FFFE / U+FFFF だけ | **正確**。`jin_core.model._reject_bad_chars` が C0 / C1 / DEL / 孤立サロゲートを拒む。多層防御として単体 7 param は残している |
| 6 | F-S-P3-011 に上限を付けない | **妥当**。閾値の根拠が無い値を置かない（CLAUDE.md）。ストリーム読みで 2 重コピーは消えた（10 MB 1 行 0.89 s） |
| 7 | F-C-P3-013 は関数削除で消滅 | **事実**（grep 0 件） |
| 8 | F-V-P3-013（plan `$comment`）を見送り | **妥当**。指示書 E「`undecided[]` 以外は触らない」に従った |
| 9 | F-W-P3-010 / F-S-P3-013 は記録のみ | **妥当**。TOCTOU で負けても `os.replace` がリンクの実体を置き換えるだけで境界は越えない（前回レビューと同じ結論） |

## 4. Findings（修正が持ち込んだ・または今回見つけた新規）

### F-C-P3-101 [confidence 85] flow の弦が節の外枠より短いと**黙って描かれない**。R1 の extent 実寸化で閾値が動いた（悪化側と改善側の両方・修正前後を実測）
- 場所: `packages/jin-render/src/jin_render/layout.py:146-147`（`_arrow_d` が `length <= gap_start + gap_end` で `None`）、
  `:613-614`（`None` なら `continue`）、`docs/spec/layout.md` §2「`sequence` = 開いた弦列(矢印)」（例外を書いていない）
- 内容: 節の外枠半径（= 弦の gap）は R1 で固定 0.266 から「0.28 × 実寸 + 0.04」（最大 0.3228）になった。隣り合う節の中心距離
  `2·0.55·sin(180°/n)` が gap の和より短いと弦が 1 本も出ない。`probe_r1b.py` の実測（全節が同型）。「修正前」は隔離コピーに
  `_summon_extent` を `NESTED_SCALE * RING_BOUNDARY` 固定へ戻す変異を当てて同じ probe を回した実測値:

| 節の中身 | `sequence`（期待 n−1 本） | `loop`（期待 n 本） |
|---|---|---|
| core のみ（0.12） | 修正後: n=3..12 すべて n−1 本。修正前: n≥7 で **0 本**（**改善**） | 修正前後とも全数 |
| core+instruction+state（0.80・examples と同型） | 修正後: n≤6 は n−1 本（n=6 の最短本体 8.8 px）、**n≥7 は 0 本**。修正前: n=6 は 5 本（7.2 px）、n≥7 は 0 本（**同じ**） | 修正前後とも全数 |
| core+boundary+guards（1.01・最大） | 修正後: n=5 は 4 本だが最短本体 **0.4 px**（矢じり 20 px が本体より長い）、**n≥6 は 0 本**。修正前: n=6 は 5 本、n≥7 は 0 本（**悪化**: 消える n が 7 → 6） | 修正後: **n=6 で 0 本**。修正前: 全数（**悪化**） |

- 期待との差: 要件書 §2.5 の `sequence` は「開いた弦列(矢印)」で、訪問順を示す弦が**モデルの大きさによって消える**ことも、消えたことを示す印も無い。
  `/circles/i/flow` を指す要素が 1 つも無くなるので、トレースの `/circles/i/flow/max` 行は `/circles/i`（陣全体）に落ちる。
  根本原因は R1 ではなく既存の `NESTED_SCALE` 0.28 の根拠（layout.md §6「境界環の内側に収まる」= 兄弟の数を見ていない）だが、
  R1 が gap を実寸にしたことで、最大の小陣では消える n が 7 → 6 に下がり、loop でも n=6 で消えるようになった（修正前は消えなかった）
- 変異検証: 修正前挙動への変異（`005-fixed-extent` と同じ置換）を当てた probe で上表の「修正前」列を実測。弦の本数を固定するテストは無い
  （`test_sequence_*` は pipeline の 3 節だけ）
- 提案: (a) 節が多いときは外枠を兄弟間隔から上限で詰める（`min(実寸, 0.55·sin(180°/n) − ε)`）か、(b) 弦が消える代わりに節の外枠上に
  矢じりだけを置く、または (c) 現状を仕様として layout.md §6 に「弦が節の外枠より短いときは描かない」と 1 行書き、
  「n 節の `sequence` の弦は n−1 本」を固定するテストで境界（examples 同型で n=6）を明示する。どれでも仕様とコードを同時に

### F-C-P3-102 [confidence 70] `_outer_extent` の「実際に届く最大半径」は四角（builtin 紋・state）の角を数えていない
- 場所: `packages/jin-render/src/jin_render/layout.py:322-323`（`RING_TOOLS + TOOL_GLYPH_RADIUS`）、`:328-329`（`RING_STATE + STATE_HALF`）、
  docstring `:310`「**実際に**届く最大半径」、layout.md §6「入れ子が**実際に届く**半径」
- 内容: `_square_d` は半径方向 ±half・接線方向 ±half の正方形なので、角は `hypot(RING + half, half)` = 0.6129 / 0.8016 に届く
  （列挙 0.61 / 0.80）。差は入れ子で 0.33 px / 0.18 px、`SUMMON_GAP` 16 px に吸収され、外枠が中身に接することは無い
- 変異検証: 該当なし（列挙と実描画の突合）
- 提案: 列挙を `hypot` にするか、docstring と §6 を「主要素の外接半径（四角の角は隙間 0.04 で吸収）」と正確に書く。害は無い

### F-C-P3-103 [confidence 40] `_read_trace_rows` の `line.strip()` が Unicode 空白だけの行も「空行」として黙って読み飛ばす
- 場所: `packages/jin-cli/src/jin_cli/main.py:882`
- 内容: `str.strip()` は U+2028 / U+00A0 / U+000C / U+3000 などの Unicode 空白も落とす。これらだけの行は JSON として不正なのに
  exit 0 で通る（probe: U+2028 のみ / NBSP のみ / FF のみ の行 → exit 0・点 1）。データは失われないので害は小さいが、
  docstring「空行（末尾の余分な改行など）だけは読み飛ばす」と「壊れた行は黙って読み飛ばさない」の境界が ASCII 空白でなく Unicode 空白になっている
- 提案: `line.strip(" \t")` か `not line.strip()` を `line in ("", "\r")` 相当に絞る。テスト 1 本

### F-C-P3-104 [confidence 90] 記録の誤り: 変異 `STAR-slot-identity` の効き方が実物と逆（notes・mutate_p3.py・ADR-021・plan rationale の 4 箇所）
- 場所: `delivery/20260904-1445-jin/phase3-mutations/mutate_p3.py:225-226`（「星形テスト（角位置だけを見る）は緑のまま、訪問順テストだけが赤になる」）、
  `implementation-notes.md:1345`（R1.1 C-1 行「星形テストは緑のまま訪問順テストだけが赤」）、
  `docs/adr/ADR-021-DP-IMPL-JIN-P3-LOOP-STAR-ORDER-01.md` と `implementation-plan.json:1799` の rationale（「= 2 本が独立に効いている証拠」）
- 内容: `_flow_slots` を恒等（`list(range(count))`）にすると辺は j→j+1 のまま**配列順の隣**を結ぶので、出来るのは星形ではなく
  単純多角形である。隔離コピーで実測: **`test_loop_edges_follow_the_star_polygon[5-2]` / `[8-3]` が赤、
  `test_loop_nodes_are_placed_so_the_arrows_follow_the_visit_order` は全 param 緑**（記録と逆）。変異が捕まること自体は正しいので
  「59/59 caught」の数は変わらないが、「2 本が独立に効いている証拠」の論拠が事実でない。独立性の証拠になるのは
  「恒等配置 + 辺 j→j+k（修正前の挙動）」で、これは訪問順テストだけが赤（n=5,7..12 の 7 param）・星形テスト緑（実測）
- 提案: 4 箇所の文を実測に合わせる（「恒等配置は星形テストが赤・修正前挙動（恒等 + j→j+k）は訪問順テストだけが赤」）。
  `mutate_p3.py` に修正前挙動の変異を 1 本足すと、2 本のテストが独立に効くことが機械的に示せる。
  **直す所有者**: `implementation-notes.md` と `mutate_p3.py` は impl。`implementation-plan.json` の rationale と ADR-021 は
  auto-decider が書いた `decision_record` なので親／auto-decider（指示書 E は impl に `decision_record` を触らせていない）

### F-C-P3-105 [confidence 35] テスト側に `splitlines()` でトレースを読む箇所が 1 つ残っている
- 場所: `packages/jin-render/tests/test_determinism.py:73`（サブプロセス script 内 `Path(sys.argv[2]).read_text().splitlines()`）
- 内容: R1.1 A-1 は「テスト側 7 箇所の `splitlines()` も `split("\n")` に」と書くが、この 1 箇所は残る。fixture `pipeline-fake.jsonl`
  に U+2028 は無いので現状は無害。fixture を差し替えたときに reader 側と割れ方が違う
- 提案: `split("\n")` に揃える（1 行）

## 5. 変異で緑のままだったテスト（偽 green の候補）

隔離コピーで 1 箇所ずつ壊し、**スナップショットを除いた**テスト（test_layout / test_overlay / test_render.py / test_determinism / test_svg）と
**スナップショットのみ**の 2 通りで回した。

| 変異 | 内容 | 非スナップショット | スナップショットのみ |
|---|---|---|---|
| `005-extent-drops-flow` | `_outer_extent` の flow の項を落とす | **緑** | 赤（2 failed・pipeline / trace overlay） |
| `005-extent-drops-delegate` | 同 delegate の項 | **緑** | **緑**（examples に delegate 付きの入れ子が無い） |
| `005-extent-drops-tools` | 同 tools の項 | **緑** | **緑**（researcher の Summarizer は tools を持たない） |
| `B1-outline-kind-circle` | 外枠の `data-jin-kind` を `circle` に | **緑**（`test_a_pointer_lands_on_the_kind_the_table_says` は summon を持たないモデル） | 赤（3 failed） |
| `002-slot-identity` | 節を配列順に置く | 赤（星形テスト） | 緑（examples に loop が無い・期待どおり） |

`test_the_summon_outline_follows_the_inner_circles_actual_reach` の 4 param は core / instruction / state / boundary だけを持つので、
`_outer_extent` の flow / delegate / tools の項は**どのテストにも固定されていない**（delegate / tools はスナップショットにも出ない）。
param を 3 つ足せば閉じる（安い）。`B-8` の kind 表テストに summon を 1 つ足せば外枠の kind も固定できる。

前回の表で偽 green だった `SEQ-zero-accepted-is-untested` / `STATE-ring-needs-core` / `DELEGATE-line-from-core-only` / `DOT-accent-fill-dead`
は、今回の `004-no-lower-bound` / `012-state-ring-needs-core` / `012-delegate-line-from-core-only` が**赤**になり、`accent_attr` は削除された。

## 6. 実装者の記録（notes / conformance / plan / layout.md）と実物の不一致

| 記録 | 実物 | 参照 |
|---|---|---|
| notes R1.1 C-1 / mutate_p3.py:224 / ADR-021 / plan rationale「`STAR-slot-identity` は星形テストが緑のまま訪問順テストだけ赤」 | 逆。星形テスト [5-2] [8-3] が赤・訪問順テストは全 param 緑 | F-C-P3-104 |
| notes R1.1 A-1「テスト側 7 箇所の `splitlines()` も `split("\n")` に」 | `test_determinism.py:73` にトレースを `splitlines()` で読む箇所が残る | F-C-P3-105 |
| layout.py:310 / layout.md §6「入れ子が**実際に**届く半径」 | 四角の角（builtin 紋・state）は列挙を 0.0029 / 0.0016 超える（隙間に吸収） | F-C-P3-102 |
| layout.md §2「`sequence` = 開いた弦列(矢印)」 | 節が外枠より近いと弦を描かない（`_arrow_d` → `None`）。仕様に例外の記述が無い | F-C-P3-101 |
| main.py:869-870「空行（末尾の余分な改行など）だけは読み飛ばす」 | Unicode 空白だけの行も読み飛ばす | F-C-P3-103 |
| notes R1.0「1100 passed」 | 全体は再実測していない。jin-render + test_render.py 分を 261 passed・4 snapshots、`test_render_contract.py` を 12 passed で実測（矛盾なし） | — |
| notes R1.1 の各 finding → 固定テスト | 13 件すべて、対応する固定テストが自前の変異で赤になることを実測（一致） | §1 |
| layout.md §2.1 / §6 / §7.2 / §7.5 の R1 追記 | `_flow_slots` / `_reference` / `read_trace` / `_read_trace_rows` と一致（一致） | — |
| decision-conformance §2.24.1 / 2.24.1b / umask 行 | 「最大座標 1000 px」「`0o644 & ~umask`」「XML 1.0 Char」がコードと一致（一致） | — |
