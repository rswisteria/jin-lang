# Stage 5 review: correctness — Phase 3 (jin-render) 再レビュー round 2（範囲限定）

- 入力: 前回 finding `correctness-p3-round1.md`（F-C-P3-101〜105）、親の指示書 `phase3-fix-round-2-instructions.md`、
  実装者の対応表 `implementation-notes.md` P3-R2（R2.1 / R2.2 の 12 件 / R2.5 の 5 点）
- 判定材料は差分コード・生成 SVG・テスト・仕様だけ。実装者の「直しました」「変異で赤」は根拠にせず、隔離コピーで
  **自分の probe と変異**を入れて実測した。confidence の基準は前回と同じ（85 以上 = 隔離コピーで実測して直接確認、
  60〜80 = 間接確認または解釈の余地、60 未満 = 読解のみ / 記述の不一致）

## 実測した環境・コマンド（隔離コピーのパス・件数）

- 隔離コピー: `/home/wisteria/.claude/jobs/e2bcfe94/tmp/rereview2-correctness/`（`packages` / `tests` / `examples` / `docs` /
  `schemas` / `pyproject.toml` / `jin-requirements.md` / `CLAUDE.md` / `README.md` / `delivery/20260904-1445-jin` を `cp -r`）
- 実行: `run_pytest.sh`（`PYTHONDONTWRITEBYTECODE=1`・`__pycache__` 削除・`PYTHONPATH` にコピー側 4 パッケージの `src`・
  `--import-mode=importlib -p no:cacheprovider`・python は worktree の `.venv`）。コピー側を import している証拠は
  各 probe 冒頭の `jin_render.__file__` / `jin_cli.__file__` の表示
- ベースライン（コピー）: `packages/jin-render/tests` + `packages/jin-cli/tests/test_render.py` + `tests/contract/test_render_contract.py`
  → **360 passed・4 snapshots passed**（R1 の 261 + 12 から増。全体 1190 は再実測していない）
- 実装者の変異ハーネス `mutate_p3.py` をコピー側から `MUTATE_ONLY` で 8 本（`STAR-slot-identity` / `STAR-pre-fix-visit-order` /
  `STAR-pre-fix-star-shape-stays` / `FLOW-node-scale-fixed` / `FLOW-no-node-limit` / `FLOW-extent-no-limit` / `KIND-chord-as-circle` /
  `KIND-flow-node-as-tool`）→ baseline 383 passed・**8/8 caught**（`imports from:` がハーネスの一時コピーを指すことを確認）
- 実測スクリプト（同ディレクトリ）: `probe_r2.py`（n=3..12 × 中身 4 種〔core のみ / examples 同型 / 最大 / 全要素入り〕× sequence / loop の
  弦の本数・最短本体・節 0 の wrapper 配下**全要素**の最外到達 vs 外枠、n=13..64 の点への切替と弦の消失、縮み始める n）、
  `probe_r2b.py`（道具環の summon 紋の重なり・文字種・`int_max_str_digits`）、`probe_r2c.py`（CLI: BOM / 全角空白 / NBSP だけの行、
  `-o <symlink>` の文言）、`mutate_r2.py`（自前の変異 7 本・layout テストとスナップショットの 2 通り）
- 実ツリーは本ファイルの追加以外に変更していない（変異のたびに `filecmp` で worktree の `layout.py` とバイト一致を確認。`git status` に
  他エージェントによる `docs/adr/ADR-021 → ADR-022` の置換と `implementation-plan.json` の変更が同時に現れているが、本レビューの操作ではない）

## 1. 前回 finding の判定（5 件）

| ID | 前回の要旨 | 判定 | 根拠（実測） |
|---|---|---|---|
| F-C-P3-101 | flow の弦が節の外枠より短いと黙って描かれない | **defect-gone** | `layout.py:347-383`（`_reference_size` / `_flow_node_limit`）。probe: n=3..12 × 中身 4 種 × sequence / loop の **80 構成すべて**で弦 = n−1 / n 本、最短本体 ≥ 48 px（矢じり 20 px。制限に掛かる構成は全部ちょうど 48.0 px = `2·(0.05+0.01)·400`）。節 0 の wrapper 配下の全要素（核 / 環 / 四角 / 刻印 / 欠け / rune の経路 + 字高 / 紋 / 委譲）の最外到達は外枠の内側（最も外に届くのは刻印と欠けの `path`。n=12 最大で 28.86 px vs 外枠 32.94 px）。縮み始める n は 13 / 5 / 5（§6 の表と一致）。ハーネス 3 本 + 自前 5 本（§4）が赤。**下記 F-C-P3-205（n ≥ 32 の記述）と偽 green 2 件（ε・隙間）は別記** |
| F-C-P3-102 | `_outer_extent` が四角の角を数えていない | **defect-gone（文言 1 箇所が部分残存・低）** | docstring `layout.py:309-320` と layout.md §6 の表は「主要素の外接半径（角は隙間に吸収）」に。ただし `_reference` 内のコメント `layout.py:481`「半径は入れ子の**実際の最外到達半径** + 隙間」が旧文言のまま（grep） |
| F-C-P3-103 | Unicode 空白だけの行を空行扱い | **記録のみ（判断は妥当・理由は偽）** | 現状維持は妥当（害が無い）。ただし R2.2 項 5 の理由が事実でない → F-C-P3-203 |
| F-C-P3-104 | 記録の誤り（`STAR-slot-identity` の効き方が逆） | **defect-gone** | impl 分 3 箇所（notes:1345 / `mutate_p3.py:352-355` / plan `undecided_details` note:2365）と、親の置換記録（`ADR-022`・plan rationale:1799）の両方が実測どおり。旧文言が残るのは ADR-022:22 / plan:1829 の「前回の記録」引用だけ（正しい引用）。ハーネス実測: `STAR-slot-identity` → **2 failed**（星形 [5-2] / [8-3]）、`STAR-pre-fix-visit-order` → **7 failed**、`STAR-pre-fix-star-shape-stays` → **3 passed**（記録と一致）。ただしハーネスの表示ラベルに不一致 → F-C-P3-206 |
| F-C-P3-105 | テスト側に `splitlines()` でトレースを読む箇所が残る | **defect-gone** | `test_determinism.py` に `splitlines` は無い（grep）。残る `splitlines()` は SVG 文字列の先頭 / 末尾行を取る 2 箇所（`test_layout.py:525` / `test_svg.py:127`）と、空虚化防止の assert 1 箇所（`test_render_contract.py:273`・意図的）だけ |

defect-gone **4 / 5**（102 はコメント 1 行が残存）、記録のみ 1（103・理由の差し替えが要る）。残存 0。

## 2. 重点確認（親の指示 B-1 / A-4 と R2.5）

### B-1: `_reference_size` / `_flow_node_limit`（式・中身のはみ出し・境界）

- **式は layout.md §6 / decision-conformance §2.24.1c と一致**: `limit = 0.55·sin(π/n) − (0.05 + 0.01)`、`natural = 0.28·実寸 + 0.04`、
  超えたら `係数 = limit / natural` で外枠・中身・隙間を一括で縮める（`layout.py:359-365` / `:495` の `NESTED_SCALE * factor`）。
  `limit < 0.03` で点（n ≥ 20・実測どおり）
- **中身のはみ出しは無い**（境界環以外も含めて）: probe の「全要素入り」中身（builtin 四角・tool 円・state 四角 ×2・delegate・guard・await・
  長い rune）で n=3..12 の最外到達は刻印 / 欠けの `path` で、外枠に対して n=3: 113.1 / 129.1 px、n=12: 28.9 / 32.9 px。
  rune は defs の経路半径 + 字高で近似（`<text>` に座標が無いため）。隙間も同じ係数で縮むので余白は `0.04·係数`
- **loop**: k ≥ 2 の弦は隣接より長く（n=7 最短 286 px）、k=1（n=6）は隣接と同じ 48.0 px。「隣接距離だけを見れば足りる」は成立
- **変異（自前・`mutate_r2.py`）**: `B1-contents-not-shrunk`（中身の縮尺を 0.28 固定）→ `shrinks_its_contents_too[6]` **赤**、
  `B1-limit-drops-arrow-head` → `every_flow_chord[sequence-5-largest]` **赤**（本体 8.0 px）、`B1-no-point-fallback` → `crowded_flow_falls_back_to_points` **赤**、
  `B1-limit-off-by-factor-2` → **赤**（本体 0.38 px）、`B1-factor-clamped-to-1`（外枠だけ詰める）→ **赤**。
  **緑のまま**: `B1-limit-drops-epsilon`、`B1-gap-not-shrunk`（§4）
- **スナップショット差分 0 の主張**: 上記 7 変異すべてでスナップショット 4 本は緑（examples の flow は pipeline n=3 だけ・制限に掛からない）。
  B-1 のテストが**スナップショットに全く依存していない**ことの裏返しでもある（合成モデルで固定されているので問題ない）

### A-4: 2 変異の効き方（実測と記録の一致）

ハーネスの出力（コピー側）:

```
STAR-slot-identity            RED   2 failed, 14 passed   ← 星形テスト [5-2] / [8-3]
STAR-pre-fix-visit-order      RED   7 failed,  3 passed   ← 訪問順テスト n=5,7..12
STAR-pre-fix-star-shape-stays GREEN (expected)  3 passed  ← 星形テスト n=5,6,8
```

notes R2.1 / `mutate_p3.py` / plan note / ADR-022 の記述と一致。「独立性の証拠」としては十分:
`slot-identity` が「星形だけ赤・訪問順は緑」、`pre-fix` が「訪問順だけ赤・星形は緑」で、2 本のテストが**双方向に**独立に効くことが
機械で示されている（R2.5-4 の答え）。`EXPECT_GREEN` を 2 本目として使うことも許容できる（主張そのものが GREEN）。ただし
ハーネスが出す状態ラベルは symlink 用の「二層目が守る」がそのまま出る（F-C-P3-206・低）。

### R2.5 への答え

| # | 問い | 答え |
|---|---|---|
| 1 | B-1 の式が §6 と一致するか・中身がはみ出さないか | **一致・はみ出さない**（上記。境界環以外の要素も含めて実測） |
| 2 | n ≥ 32 で弦が消えるのを仕様として許容してよいか | **許容してよい（条件付き）**。`flow.steps` に上限が無い以上、環半径を変えずに解くことはできず、診断コードも増やさない方針と整合する。ただし**閾値の記述が実測と違う**: 弦が 0 本になるのは **n ≥ 58**（`2·0.55·sin(π/n) ≤ 0.06`）で、n = 32〜57 は弦は描かれるが本体が矢じり 20 px より短い（n=32: 19.1 px、n=40: 10.5 px、n=57: 0.2 px。矢じりが尾を突き抜ける）。layout.md §6 と notes R2.2 項 4 を「32〜57 は矢じりが本体より長くなる・58 以上で消える」に直す条件で許容（F-C-P3-205） |
| 3 | 道具環の紋 12 個の重なりを別 finding にすべきか | **起票する**（F-C-P3-201）。実測で最大の中身は **n ≥ 6**、examples 同型でも **n ≥ 7** で隣と重なる。§6 の表「紋 0.06 は 12 個並べても重ならない」は `tool` / `builtin` にしか当てはまらない |
| 4 | A-4 の 2 変異は独立性の証拠として十分か | **十分**（上記） |
| 5 | Phase 2 に残る `model.md §3.3` の誤引用を今直すか | **今直してよい**（文言だけの変更で `tests/spec` の突合対象は見出し・表の構造であって引用先ではない。grep 確認は 1 分で済む）。ただし数は **4 箇所**（F-C-P3-204）。Phase 4 に送るなら handoff に 4 箇所を列挙する |

## 3. R2.2「指示と違えた判断 / 直さなかったもの」12 件の評価

| # | 判断 | 評価 |
|---|---|---|
| 1 | `model.md §3.3` は Phase 3 の 2 箇所だけ直した（Phase 2 に 3 箇所残る） | 判断は**妥当**（範囲を広げない）。ただし残る数は **4**（`codegen.py:27` / `:73` / `adk-mapping.md:124` / **`:168`**）。数え落とし → F-C-P3-204 |
| 2 | `FLOW-no-node-limit` が最初 GREEN → テストを足した | **妥当**。「半径を決める場所が 2 つある」穴を `test_the_chord_gap_matches_the_drawn_node` で閉じた。ハーネスで 8 failed を実測 |
| 3 | B-1 を道具環の紋には適用しない | **妥当**（弦が無いので 101 の直接の対象外）。ただし重なりは実在する（F-C-P3-201） |
| 4 | n ≥ 32 で弦が消えるのは幾何の限界 | 結論は**妥当**、閾値の記述が**不正確**（消えるのは n ≥ 58）→ F-C-P3-205 |
| 5 | F-C-P3-103 は記録のみ。「ASCII に狭めると BOM 付き空行を壊れた行にしてしまう」 | 判断は妥当、**理由が偽**。`"﻿".strip()` は空にならず（`isspace()` も False）、BOM だけの行は**今すでに exit 2**（probe: `bom_only_line.jsonl:1: JSON として読めません`）。ASCII に狭めても BOM の扱いは 1 つも変わらない → F-C-P3-203 |
| 6 | F-S-P3-102（1 行長の上限）は記録のみ | **妥当**（R1.2 項 6 と同じ。根拠の無い閾値を置かない） |
| 7 | F-S-P3-104（FIFO + `--force`）は記録のみ | **妥当**（境界を越えない。security 観点） |
| 8 | F-W-P3-103（tests の動的 import）は記録のみ | **妥当**（契約の対象は配布物。wiring 観点） |
| 9 | F-V-P3-104 の変更は「読解で確認した」・テスト無し | **読解が誤っていた。退行あり** → F-C-P3-202。一層目（`_write_svg:980`）の `SymlinkWriteRefused` はパスを含まない文言なので、`render` 側で前置をやめた結果、**普通に symlink を指定したときの出力からパスが消えた**。既存テストは部分文字列しか見ておらず緑 |
| 10 | `--upto` に届く桁数は 4300 未満 | **正しい**（`sys.int_info.default_max_str_digits == 4300` を実測） |
| 11 | 「道具環の紋の重なり」を記録のみ 5 件に数える | 数え方は整合。内容は F-C-P3-201 |
| 12 | `STAR-pre-fix-star-shape-stays` を `EXPECT_GREEN` に | **許容**（主張そのものが GREEN）。ラベル文言の不一致だけ直す（F-C-P3-206） |

## 4. Findings（修正が持ち込んだ・または今回見つけた新規）

### F-C-P3-201 [confidence 85] 道具環の `summon` 紋は n ≥ 6（最大の中身）/ n ≥ 7（examples 同型）で隣と重なり、内縁は常に rune 帯を横切る
- 場所: `packages/jin-render/src/jin_render/layout.py:343-345`（`_summon_extent`・`limit=None` 固定）、`:387-390`（`_tool_extent`）、
  `docs/spec/layout.md` §6「紋（tool）の半径 0.06 | 道具環 0.55 上で 12 個並べても重ならない」「道具環の紋（`summon`）にはこの縮小を適用しない」
- 内容: `summon` の外枠は `0.28·実寸 + 0.04`（最大 0.3228・examples 同型 0.2640）で、道具環の隣接中心距離 `2·0.55·sin(π/n)` と比べると
  最大の中身で n=6（0.5500 < 0.6456）、examples 同型で n=7 から重なる（`probe_r2b.py`）。n=12（JIN020 の上限）では隣接 0.2847 に対し
  外枠の直径 0.6456 で 2 つ以上先の紋とも重なる。さらに外枠の内縁 `0.55 − r` は 0.227 / 0.286 で、**n に関係なく**指示環の rune 帯
  （0.35〜0.40）を横切る（rune の文字の上に外枠の円が乗る）。§6 の「12 個並べても重ならない」は `tool` / `builtin`（0.06）にしか当てはまらない
- 期待との差: layout.md §2「配列順、等角配置」は紋が互いに読める前提。R1 が外枠を実寸化したことで、最大の中身では重なり始める n が 7 → 6 に
  下がった（F-C-P3-101 と同じ構造。ただし紋は弦を持たないので「消える」ことは無い）。101 の修正（兄弟間隔から縮める）を紋には当てていないので、
  同じモデルでも flow の節としては収まり、道具環の紋としては重なる
- 変異検証: 該当なし（幾何の実測）。重なりを固定するテストは無い
- 提案: (a) `_summon_extent` にも `limit = 0.55·sin(π/n) − ε'`（弦が無いので矢じり分は不要）を渡して同じ規則で縮める、または (b) 現状を仕様と
  して §6 に「`summon` の紋は重なりうる」と書き、表の「重ならない」行を `tool` / `builtin` に限定する。どちらでも仕様とコードを同時に。
  rune 帯との交差は `RING_TOOLS` 上に半径 0.3 級の円を置く設計自体の帰結で、直すなら環半径か縮尺の話（要件書に戻る）

### F-C-P3-202 [confidence 95] `jin render -o <symlink>` の拒否文言から**パスが消えた**（R2 の F-V-P3-104 対応が持ち込んだ退行・既存テストは偽 green）
- 場所: `packages/jin-cli/src/jin_cli/main.py:980-981`（一層目 `raise SymlinkWriteRefused("シンボリックリンクなので書き込みを拒みました")`・パス無し）、
  `:1069-1073`（`except SymlinkWriteRefused` で `_safe(str(exc))` をそのまま出し、前置しない）、`:417`（二層目だけ `: {path}` を含む）、
  `packages/jin-cli/tests/test_render.py:99-108`（`test_a_symlinked_output_is_refused` は `"シンボリックリンク" in result.output` しか見ない）
- 再現（隔離コピー・`probe_r2c.py`）:

```
$ jin render pipeline.jin -o out_link.svg --force      # out_link.svg はシンボリックリンク
シンボリックリンクなので書き込みを拒みました            # exit 1・どのパスか分からない
$ jin render pipeline.jin -o out_dir
/…/out_dir: ディレクトリです。ファイル名まで指定してください
$ jin render pipeline.jin -o existing.svg
/…/existing.svg: 既にあります。上書きするなら --force を付けてください
```

- 期待との差: 同じ `_write_svg` の他の 3 条件（ディレクトリ / 親無し / 既存）はパス付き。R2 が直そうとした F-V-P3-104 は「二層目が発火した
  **競合時だけ**パスが 2 回出る」だったが、修正は一層目（通常経路）からパスを落とした。`-o` を複数回打つスクリプトや CI ログでは、どの出力先が
  拒まれたか分からない。R2.2 項 9「読解で確認した」の読解が誤り
- 変異検証: 既存テストは文言の部分一致だけなので、この退行を通した（偽 green）。パスを含める assert を足せば現状で赤になる
- 提案: 一層目の raise を二層目と同じ形 `SymlinkWriteRefused(f"シンボリックリンクなので書き込みを拒みました: {path}")` にする（1 行）。
  `render` 側の「前置しない」はそのままで、一層目・二層目とも 1 回だけパスが出る。`test_a_symlinked_output_is_refused` に
  `str(link) in result.output` を足す。`mutate_p3.py` に「一層目からパスを落とす」変異を 1 本

### F-C-P3-203 [confidence 90] 記録の誤り: R2.2 項 5 の理由「ASCII に狭めると BOM 付き空行を壊れた行にしてしまう」は事実でない
- 場所: `delivery/20260904-1445-jin/implementation-notes.md:1563-1567`（R2.2 項 5）
- 内容: `str.strip()` は U+FEFF を落とさない（`"﻿".strip() == ""` は False・`isspace()` も False）。BOM だけの行は**現状で既に** exit 2
  （probe: `bom_only_line.jsonl:1: JSON として読めません（Unexpected UTF-8 BOM）`。先頭が空行で 2 行目が BOM でも `:2:` で exit 2）。
  したがって「空行」の定義を ASCII 空白に狭めても BOM の扱いは変わらず、理由として成立しない。実際に読み飛ばされるのは全角空白 U+3000 /
  NBSP U+00A0 / U+2028 などの**Unicode 空白だけ**の行（probe: exit 0）
- 提案: 判断（記録のみ・現状維持）は妥当なので結論は変えず、理由を「`jin_adk.trace` はそういう行を書かず、読み飛ばしてもデータは失われない。
  BOM は空白でないので今も拒まれる」に差し替える

### F-C-P3-204 [confidence 90] 記録の誤り: Phase 2 に残る `model.md §3.3` の誤引用は 3 箇所ではなく **4 箇所**
- 場所: `implementation-notes.md:1547-1551`（R2.2 項 1「Phase 2 の 3 箇所（`codegen.py` の 2 行と `adk-mapping.md:124`）」）
- 内容: grep の実物は `packages/jin-adk/src/jin_adk/codegen.py:27` / `:73`、`docs/spec/adk-mapping.md:124` / **`:168`**（§3.1 の表
  「1 circle に `out: true` の state が 2 件以上」行の「診断コードは増やさない（`docs/spec/model.md` §3.3）」）。`model.md` §3.3 は State の定義
- 提案: 数を 4 に直し、Phase 4 に送るなら handoff に 4 箇所を列挙する。今直すなら 4 箇所とも「CLAUDE.md / ADR-012」に（R2.5-5 への答え）

### F-C-P3-205 [confidence 85] 記録の精度: 「n ≥ 32 で弦がまた消えうる」は閾値が実物と違う（消えるのは n ≥ 58。32〜57 は矢じりが本体より長い）
- 場所: `docs/spec/layout.md:264-266`、`implementation-notes.md:1559-1562`（R2.2 項 4）、`:1624`（R2.5-2）
- 内容（`probe_r2.py` (2)・core のみ・sequence）: n=31 最短本体 20.5 px（矢じり 20 px）、**n=32 で 19.1 px**（本体 < 矢じり。矢じりの後端が
  弦の尾を越える）、n=40 10.5 px、n=57 0.2 px、**n=58 で 0 本**（`2·0.55·sin(π/58) = 0.0596 < 0.06` で `_arrow_d` が `None`）。
  「n ≤ 31 まで本体 ≥ 矢じり」は正しいが、その先の「消えうる」は 58 以上の話で、32〜57 は「描かれるが矢じりがはみ出す」別の状態
- 提案: §6 と notes を「n = 32〜57 は弦は描かれるが本体が矢じりより短くなる（矢じりが尾を越える）。n ≥ 58 で弦が 0 本になる」に。
  `test_a_crowded_flow_falls_back_to_points`（n=40）に「弦は n−1 本ある」を 1 行足すと 32〜57 の状態が固定される

### F-C-P3-206 [confidence 80] 変異ハーネスの GREEN ラベルが `STAR-pre-fix-star-shape-stays` に symlink 用の文言「二層目が守る」を出す
- 場所: `delivery/20260904-1445-jin/phase3-mutations/mutate_p3.py:879-880`（`status = "GREEN (expected: 二層目が守る)"` が `EXPECT_GREEN` 共通）
- 内容: 実出力 `STAR-pre-fix-star-shape-stays GREEN (expected: 二層目が守る)`。この変異の GREEN は「星形テストは配置の恒等化では落ちない」
  という主張であって二層防御ではない。読んだ人が symlink の話と誤読する
- 提案: `EXPECT_GREEN` を `dict[str, str]`（名前 → 理由）にしてラベルに理由を出す（数行）

## 5. 変異で緑のままだったテスト（偽 green の候補）

隔離コピーで 1 箇所ずつ壊し、`test_layout.py` と `test_snapshots.py` の 2 通りで回した（`mutate_r2.py`）。

| 変異 | 内容 | layout テスト | スナップショット | 評価 |
|---|---|---|---|---|
| `B1-limit-drops-epsilon` | `_flow_node_limit` から `FLOW_NODE_EPSILON` の項を落とす | **緑** | 緑 | §6「本体 ≥ 2·(矢じり + ε)」の ε はどのテストにも固定されていない（テストは本体 ≥ 矢じりしか見ない。ε 無しでも 40 px ≥ 20 px）。害は無いが、§6 に書いた値が動いても気づかない。`test_every_flow_chord…` の下限を `2·(ARROW_HEAD + FLOW_NODE_EPSILON)·400 − 許容` にすれば閉じる |
| `B1-gap-not-shrunk` | 隙間 0.04 を縮めず、外枠と中身だけ縮める（係数 `(limit−0.04)/(natural−0.04)`） | **緑** | 緑 | 「外枠・中身・隙間を**同じ係数**で縮める」（§6 / docstring）は固定されていない。中身は収まるので欠陥ではないが、仕様の文と実装の一致を見るテストが無い |
| 既存 `test_a_symlinked_output_is_refused` | 一層目の文言からパスを落とす（現状） | 緑（現状が既にそう） | — | F-C-P3-202 |

赤になった自前変異 5 本（`B1-contents-not-shrunk` / `B1-limit-drops-arrow-head` / `B1-no-point-fallback` / `B1-limit-off-by-factor-2` /
`B1-factor-clamped-to-1`）とハーネス 8 本はいずれもスナップショットは緑のまま（examples に制限に掛かる flow が無い・期待どおり）。

## 6. 実装者の記録（notes / conformance / plan / layout.md）と実物の不一致

| 記録 | 実物 | 参照 |
|---|---|---|
| notes R2.2 項 5「ASCII に狭めると BOM 付き空行を壊れた行にしてしまう」 | BOM だけの行は今すでに exit 2。`strip()` は U+FEFF を落とさない | F-C-P3-203 |
| notes R2.2 項 1「Phase 2 の 3 箇所」 | 4 箇所（`adk-mapping.md:168` が抜け） | F-C-P3-204 |
| layout.md §6:264-266 / notes R2.2 項 4「n ≥ 32 では弦がまた消えうる」 | 消えるのは n ≥ 58。32〜57 は矢じりが本体より長い | F-C-P3-205 |
| notes R2.2 項 9「変更は読解で確認した」 | 一層目の symlink 拒否文言からパスが消えている | F-C-P3-202 |
| layout.md §6「紋 0.06 は 12 個並べても重ならない」 | `summon` の紋（0.26〜0.32）は n ≥ 6 / 7 で重なる | F-C-P3-201 |
| `layout.py:481`「入れ子の実際の最外到達半径 + 隙間」 | `_outer_extent` は主要素の外接半径（角は数えない）に改めた | F-C-P3-102 の部分残存 |
| `mutate_p3.py` の GREEN ラベル「二層目が守る」 | `STAR-pre-fix-star-shape-stays` には当てはまらない | F-C-P3-206 |
| notes R2.1 A-4「ADR-021 と `decision_record` は触っていない（親が置換記録）」 | 親の置換は済んでいる（`ADR-022` が実測どおりの文言・plan:1799 も訂正済み。旧文言は「前回の記録」引用にだけ残る） | 一致（104 は完全に解消） |
| notes R2.0「1190 passed」「70/70 caught」 | 全体は再実測していない。jin-render + test_render.py + test_render_contract で 360 passed、ハーネス 8 本を 8/8 caught で実測（矛盾なし） | — |
| layout.md §6「縮み始める n = 13 / 5 / 5」 | 実測 13 / 5 / 5（全要素入りの中身でも 5） | 一致 |
| layout.md §6 / conformance §2.24.1c の式 | `_flow_node_limit` / `_reference_size` と一致 | 一致 |
| notes R2.1 B-1「スナップショット差分 0」 | 4 本緑・自前 7 変異でも動かない | 一致 |
| notes R2.1 A-2「`core` / `output` の 2 param・U+2028 が生で載ることを先に assert」 | `test_render_contract.py:220-274` に 2 param と空虚化防止 assert 2 本（一致） | 一致 |
