# Stage 5 review: correctness — Phase 3 (jin-render) 最終確認 round 3（範囲限定）

- 入力: 前回 finding `correctness-p3-round2.md`（F-C-P3-201〜206）、親の指示書 `phase3-fix-round-3-instructions.md`、
  実装者の対応表 `implementation-notes.md` P3-R3（R3.1 の A-1〜B-4 / C 節・R3.2 の 6 件）
- 判定材料は差分コード・生成 SVG・テスト・仕様だけ。実装者の「直した」「変異で赤」「1201 passed」は根拠にせず、隔離コピーで
  **自分の probe と変異**を入れて実測した。confidence の基準は前回と同じ（85 以上 = 隔離コピーで実測して直接確認、
  60〜80 = 間接確認または解釈の余地、60 未満 = 読解のみ / 記述の不一致）

## 実測した環境・コマンド（隔離コピーのパス・件数）

- 隔離コピー: `/home/wisteria/.claude/jobs/e2bcfe94/tmp/rereview3-correctness/`（`packages` / `tests` / `examples` / `docs` / `schemas` /
  `.github` / `.python-version` / `uv.lock` / `pyproject.toml` / `jin-requirements.md` / `CLAUDE.md` / `README.md` / `delivery/20260904-1445-jin` を `cp -r`）
- 実行: `run_pytest.sh`（`PYTHONDONTWRITEBYTECODE=1`・`__pycache__` 削除・`PYTHONPATH` にコピー側 4 パッケージの `src`・
  `--import-mode=importlib -p no:cacheprovider`・python は worktree の `.venv`）。コピー側を import している証拠は probe 冒頭の
  `jin_render.__file__` / `jin_cli.__file__` の表示（assert）
- ベースライン（コピー）: `packages/jin-render/tests` + `packages/jin-cli/tests/test_render.py` + `tests/contract/test_render_contract.py`
  → **371 passed・4 snapshots passed**（R2 の 360 から +11）。**全体は 1201 passed・68 warnings・6 snapshots passed**（R3.0 / R3.3 の主張と一致。
  `.github` / `.python-version` / `uv.lock` を欠いた最初の実行は `test_ci_contract` の 15 件がコピー欠落で落ちた。ツリーの欠陥ではない）
- 実装者の変異ハーネス `mutate_p3.py` をコピー側から **`MUTATE_ONLY` 無しで全 75 本** → baseline 394 passed・**75/75 caught・SKIP 0**
  （RED (expected) 73 + GREEN (expected) 2。`imports from:` がハーネスの一時コピーを指すことを確認。出力は `harness_full.txt`）。
  先に R3 新規 5 本 + R3.2 項 4 の「SKIP になった 4 本」+ `STAR-pre-fix-star-shape-stays` の 10 本を個別にも回した（10/10）
- 実測スクリプト（同ディレクトリ）: `probe_r3.py`（(1) n=19/20/31/32/57/58 の弦の本数・最短本体・節 0 の形、(2) CLI の symlink 拒否文言と
  二層目 `_write_atomically` 直呼びの文言、(3) BOM / U+3000 / NBSP / U+2028 / U+0085 / ASCII 空白だけの行、(4) DP-REVIEW-JIN-P3-001 の数値主張、
  (5) plan の `decision_record` / `undecided[]`）、`mutate_r3.py`（自前の変異 6 本・`filecmp` で worktree とバイト一致を確認しながら復元）、
  `mutate_r3b.py`（`build` 側の成功文言の変異 1 本）
- 記録の差分: `/home/wisteria/.claude/jobs/e2bcfe94/tmp/plan-before-r3.json`（R3 前の plan）と現在の plan を JSON で比較。R2 のコピー
  `rereview2-correctness/packages` と現在の `layout.py` / `geometry.py` / `main.py` を `diff`（R3 がコードに何を変えたかの実物）
- 実ツリーは本ファイルの追加以外に変更していない（変異のたびに `filecmp`。`git status` の `M` / `??` は Phase 3 の実装差分で、本レビューの操作ではない）

## 1. 前回 finding の判定（6 件）

| ID | 前回の要旨 | 判定 | 根拠（実測） |
|---|---|---|---|
| F-C-P3-201 | 道具環の `summon` 紋が n ≥ 6 / 7 で重なる・rune 帯を横切る | **記録のみ（妥当・起票内容は事実と一致・コード不変）** | `layout.py` の R2 → R3 差分は `_reference` 内コメント 1 行（481-482）だけ（`diff` 実物）。`_summon_extent` は `limit=None` のまま（`layout.py:343-345`）。plan `undecided[]` / `undecided_details[]` に `DP-REVIEW-JIN-P3-001` が追加され、既存 `undecided_details` 26 件は不変・`decision_record` は JSON 比較で同一。`phase_impact` の数値を再計算: 外枠 0.3228 / 0.2640、重なり始める n = **6 / 7**、内縁 0.2272 / 0.2860、rune 帯 0.35〜0.40 → 全部一致。「(a) でも examples のスナップショットは動かない」も真（researcher の tools は 4 個で limit 0.3789 > 0.3228）。`docs/pending-decisions.md:24` にも載っている。`layout.md` §6 の記述は事実だが**相互参照の向きが 2 箇所とも逆** → F-C-P3-301 |
| F-C-P3-202 | `-o <symlink>` の拒否文言からパスが消えた退行 | **defect-gone** | `main.py:1006`（一層目）が `f"...拒みました: {path}"` に。probe: 通常経路 `シンボリックリンクなので書き込みを拒みました: /…/out_link.svg`・exit 1・**パス 1 回**・リンク先は無傷。二層目 `_write_atomically(link, …)` 直呼び（事前判定を飛ばした競合時の経路）も同じ文言でパス 1 回・一時ファイル残骸 0。`render` 側は前置しないので、どちらの層でも 1 回（F-V-P3-104 との両立）。他の 3 条件は従来どおり `path: 理由`。テスト `test_a_symlinked_output_is_refused:112-114` が `str(link) in output` と `count == 1` を見る。変異: ハーネス `CLI-symlink-message-without-path` **RED**、自前 M6（同じ置換）**RED** |
| F-C-P3-203 | R2.2 項 5 の理由「ASCII に狭めると BOM 付き空行が壊れた行になる」は偽 | **defect-gone（記録の訂正が事実と一致）** | notes:1567-1576 が「BOM だけの行は現状で既に exit 2・`str.strip()` は U+FEFF を落とさない」に書き直され、判断〔記録のみ〕は不変。probe: BOM だけの 2 行目 → exit 2 `…:2: JSON として読めません（Unexpected UTF-8 BOM (decode using utf-8-sig)）`、U+3000 / NBSP / U+2028 / U+0085 だけの行 → exit 0 で読み飛ばし、`"﻿".strip() == ""` は False。新テスト `test_a_bom_only_line_is_refused` / `test_a_unicode_whitespace_only_line_is_skipped[U+3000/U+00A0]` あり。変異 M5（`strip()` → `strip(" \t\r\n")`）→ Unicode 空白の 2 param が **RED**・BOM テストは緑のまま（= BOM は空白の定義に依らない、という訂正後の理由そのものの実証） |
| F-C-P3-204 | `model.md §3.3` の誤引用は 3 箇所ではなく 4 箇所 | **defect-gone** | 4 箇所とも「`CLAUDE.md` / ADR-012」に（`codegen.py:27` / `:73`、`adk-mapping.md:123-124` / `:168`）。`grep -rn "§3.3\|model.md.*3\.3" packages docs tests CLAUDE.md README.md` の残りは `layout.md:201`（「`model.md` §3.3 は State の定義であって採番の規律ではない」= 正しい記述）と要件書 §3.3 への引用だけ → **誤引用の残り 0**。引用先は実在（`CLAUDE.md:101`「診断コードは増やさない」/ `docs/adr/ADR-012-DP-JIN-DIAGCODE-NUMBERING-01.md`）。R2.2 項 1 の数字も 4 に訂正済み（notes:1545-1548） |
| F-C-P3-205 | 「n ≥ 32 で弦が消える」の閾値が実物と違う | **defect-gone** | `layout.md:263-274`・notes R2.2 項 4・conformance §2.24.1c が「n ≤ 31 本体 ≥ 矢じり / 32〜57 描かれるが本体 < 矢じり / n ≥ 58 消える / 点に落ちるのは n ≥ 20」に。probe（core のみ・sequence）: n=19 小陣（本体 48.00 px）/ n=20 点 / n=31 30/30 本・最短 20.51 px / n=32 31/31 本・19.13 px（矢じり 20 px）/ n=57 56/56 本・0.24 px / **n=58 0/57 本**。テスト `test_the_two_crowding_boundaries`（31/32/57/58）と `test_a_crowded_flow_falls_back_to_points`（19/20/40）が境界を**両側から**通る: 自前変異 M1（点の下限 +0.001 → n=19 が点）**RED**、M2（点モードの外枠 0.03 → 0.031 → n=31 の本体 < 矢じり・n=57 の弦が消える）**RED 2 件**、M3（0.03 → 0.028 → n=32 の本体 ≥ 矢じり・n=58 に弦が残る）**RED 2 件**。M4（`_arrow_d` の `<=` → `<`）は**緑**で、n=58 が等号上に無い（0.0596 < 0.06）ことも確認。ハーネス `FLOW-point-fallback-off` RED。旧文言「n ≥ 32 で消える」の残りは grep で 0（残るのは訂正の経緯を書いた文だけ） |
| F-C-P3-206 | ハーネスの GREEN ラベルが `STAR-pre-fix-star-shape-stays` に「二層目が守る」を出す | **defect-gone** | `mutate_p3.py:776-785` が `EXPECT_GREEN_REASON: dict[str, str]`（`two-layer` / `claim` の 2 種）に、`EXPECT_GREEN = set(EXPECT_GREEN_REASON)`。実出力 `STAR-pre-fix-star-shape-stays GREEN (expected: 主張そのもの（星形テストは配置の恒等化では落ちない）)` / `CLI-follow-symlink-upfront-only GREEN (expected: 二層目が守る)` |

defect-gone **5 / 6**、記録のみ 1（201・起票内容は事実と一致・コード不変）。残存 0。悪化 0。

## 2. 重点確認（親の指示 A-1 / A-2 / A-3 / B-1 / B-2 と R3.2）

### A-1: symlink 文言のパス復帰と二層目との両立

- 一層目 `_write_svg:1006`・二層目 `_write_atomically:420` が同じ文言（パス付き）。`render:1093-1097` は `SymlinkWriteRefused` を捕まえて `str(exc)` だけを出す。
  どちらが発火してもパスは 1 回（probe で両層とも実測）。`WriteRefused`（他の 3 条件）は `render` が `{out}: {exc}` に前置するので形が揃う。
- R3.2 項 2「`before` が両層に一致して二層目を書き換えていた」は妥当: 8 スペースの raise 行は 12 スペースの二層目の行の**部分文字列**で、
  ファイル上で先に現れる二層目（420 行）が `replace(…, 1)` の的になる。コメント行を含めた現在の `before` は一意（自前 M6 でも count == 1）。
- `fmt` 側で二層目が発火したときのパス二重表示（`{path}: 書き込めません（…: {path}）`）は R2 以前からあり `_write_svg` を通らない。R3 の範囲外なので起票しない。

### A-2 / A-3: 記録の訂正

- 上表 203 / 204。訂正後の理由 (a)(b)(c)（notes:1572-1576）は事実（(b)「狭めると今受理しているファイルが exit 2 になる」は M5 の赤がそのまま実証）。

### B-1: `DP-REVIEW-JIN-P3-001` の起票

- 選択肢 (a)(b)(c)・判断期限（Phase 5 のエディタ着手前）・`parent_dp`・`raised_by` が指示どおり。`decide_by_phase: "implementation"` は同型の
  `DP-IMPL-JIN-P3-LOOP-STAR-ORDER-01` と同じ値。数値は上表のとおり全部再現。コードは 1 バイトも変わっていない（`layout.py` の差分はコメント 1 行）。
- plan の R3 前後で変わった鍵は `undecided` / `undecided_details` と **`skill_plan`**（`parallel-code-review` の行 1 件追加）。後者の note は
  「親が called を書き戻した」とあり、実装者の編集範囲としては R3.3 の「追加だけ」の主張どおり。

### B-2: 閾値と境界テスト

- 上表 205。式の確認: `2·0.55·sin(π/32) − 0.06 = 0.0478 < 0.05`、`2·0.55·sin(π/31) − 0.06 = 0.0513 ≥ 0.05`、`2·0.55·sin(π/58) = 0.0595 ≤ 0.06`、
  `2·0.55·sin(π/57) = 0.0606 > 0.06`、`0.55·sin(π/20) − 0.06 = 0.0260 < 0.03`、`0.55·sin(π/19) − 0.06 = 0.0305 ≥ 0.03`。すべて描画の実測と一致。
- 境界が等号に乗っていない（M4 緑）ので、浮動小数の丸めで表の n が動くことは無い。

### R3.2「指示と違えた判断 / 記録のみ」6 件の評価

| # | 判断 | 評価 |
|---|---|---|
| 1 | 指示に無い変更 2 つ（`main.py` モジュール docstring の安全主張 / n=19/20 のテストと `FLOW-point-fallback-off`） | **妥当**。docstring:56-60 は `_write_svg` の実装（4 条件 + 実効防御 1 条件・全条件にパス）と一致（probe の 4 文言）。n=19/20 は §6 の「n ≥ 20 で点」を初めて固定したテストで、無ければ M1 が緑のままだった |
| 2 | `CLI-symlink-message-without-path` は最初 GREEN（二層目を書き換えていた） | **妥当**（上記 A-1。部分文字列一致の説明は実物と合う）。現在は RED を実測 |
| 3 | `FLOW-point-fallback-off` も最初 GREEN → n=19/20 を足した | **妥当**。「変異が緑ならテストを足す側に倒す」は R2 項 2 と同じ規律。RED を実測 |
| 4 | B-3 の共通化で 4 本が SKIP → `before` を合わせ直して SKIP 0 | **事実**。全 75 本で SKIP 0・75/75 caught を実測（`harness_full.txt`）。ただし `build` 側の成功文言に固定するテストが無い → F-C-P3-303 |
| 5 | F-S-P3-203〜205 / F-W-P3-203 は記録のみ | **妥当**（指示 C 節が「記録のみで可」。correctness の対象外） |
| 6 | `DP-REVIEW-JIN-P3-001` はコードを変えていない | **事実**（`layout.py` / `geometry.py` の差分で確認）。理由「(a)(b) は Phase 5 の hit-test に影響 / rune 帯は環半径の話」も §6 の数値と整合 |

## 3. Findings（修正が持ち込んだ・または今回見つけた新規。いずれも低）

### F-C-P3-301 [confidence 90] `layout.md` §6 の `summon` 紋に関する相互参照が 2 箇所とも**向きが逆**
- 場所: `docs/spec/layout.md:215`（表の「紋（tool）の半径」行「**`summon` の外枠はこの値ではない**（**上記**・DP-REVIEW-JIN-P3-001）」）、
  `:282`（「**下の表**の『12 個並べても重ならない』は `tool`（円）と `builtin`（四角）の…」）
- 内容: 表は 209-237 行、`summon` 紋の段落は 276-283 行。表から見て段落は**下**、段落から見て表は**上**。R3 の B-1 で足した 2 文がどちらも逆向きに指している。
  内容自体（0.06 は `tool` / `builtin` だけ・`summon` は 0.28·実寸 + 0.04）は事実
- 変異検証: 該当なし（文書）
- 提案: 215 行を「下記『flow の節と弦』の末尾」、282 行を「上の表」に（2 語）

### F-C-P3-302 [confidence 95] 記録の誤り: 「`decision_record` は 22 件のまま」は実物 **23 件**（R2 の記述を R3 が再記載）
- 場所: `implementation-notes.md:1733`（R3.3）、`:1619`（R2.3・同じ数字）
- 内容: `implementation-plan.json` の `decision_record` は R3 前（`plan-before-r3.json`）も現在も **23 件**（`DP-IMPL-JIN-DIAGCODE-01` … `DP-IMPL-JIN-P3-LOOP-STAR-ORDER-01`）。
  「バイト単位で不変」は真（JSON 比較で同一）だが件数が違う。`design.yaml` の `decision_record` は 17 件で、どちらとも 22 にならない
- 提案: 2 箇所を 23 に。件数は `len(plan["decision_record"])` を印字して転記する

### F-C-P3-303 [confidence 90] `build` の成功文言の `_echo_or_exit` はテストに固定されていない（変異で緑・偽 green）
- 場所: `packages/jin-cli/src/jin_cli/main.py:691`（`build` の `_echo_or_exit(f"書き出しました: …")`）、`packages/jin-cli/tests/test_build_run.py`
  （`/dev/full` / `_echo_or_exit` に触れるテストが無い。`:502` は文言の部分一致だけ）、`mutate_p3.py` の `CLI-success-message-raw-echo`（`render` 側の行だけを狙う）
- 内容: 指示 B-3 は「`build` の成功文言も同じ（同型・1 箇所のヘルパで）。テスト: `/dev/full` に stdout を向けて exit 1」。ヘルパへの置き換えは済んでいるが、
  `build` 側を `typer.echo` に戻す変異（`mutate_r3b.py` M7）で `test_build_run.py` + `test_render.py -k "full_stdout or build or success"` は **53 passed・緑**。
  `render` 側は `test_a_full_stdout_on_the_success_message_is_one_line_not_a_traceback` で赤になる（ハーネス RED）が、`build` 側は誰かが `typer.echo` に
  戻しても気づかない
- 変異検証: M7（`main.py:691` を `typer.echo` に）→ **緑**（偽 green）
- 提案: `test_build_run.py` に `jin build … --out <tmp> > /dev/full` の 1 本（exit 1・`標準出力に書けません`・`Traceback` 無し・`agent.py` は書けている）。
  `mutate_p3.py` に `CLI-build-success-raw-echo` を 1 本（`before` は `_safe(str(path))` の行で一意）。数分で閉じる

## 4. 変異で緑のままだったテスト（偽 green の候補）

| 変異 | 内容 | 結果 | 評価 |
|---|---|---|---|
| M7 `build-success-raw-echo`（自前） | `main.py:691` の `_echo_or_exit` → `typer.echo` | **緑**（53 passed） | F-C-P3-303 |
| M4 `arrow-none-strict`（自前） | `_arrow_d` の `length <= gap` → `<` | 緑（**期待どおり**） | 欠陥ではない。n=58 が等号上に無いことの確認（§6 の閾値が丸めで動かない根拠） |

赤になった自前変異 5 本（M1 / M2 / M3 / M5 / M6）とハーネス全 75 本（73 RED + 期待 GREEN 2）は上記のとおり。

## 5. 実装者の記録（notes / conformance / plan / layout.md）と実物の不一致

| 記録 | 実物 | 参照 |
|---|---|---|
| notes R3.3:1733 / R2.3:1619「`decision_record` は 22 件のまま」 | 23 件（R3 前後で同一） | F-C-P3-302 |
| `layout.md:215`「上記」/ `:282`「下の表」 | 段落は表の下・表は段落の上 | F-C-P3-301 |
| notes R3.1 B-3「`build` の成功文言も同じヘルパ」/ R3.3「75/75 caught」 | ヘルパは通っているがテスト・変異は `render` 側だけ（75 本に `build` 側の成功文言は無い） | F-C-P3-303 |
| notes R3.0 / R3.3「1201 passed・68 warnings・6 snapshots」 | 1201 passed・68 warnings・6 snapshots passed（コピーで実測） | 一致 |
| notes R3.0 / R3.2 項 4「75 本 / 75 caught・SKIP 0・うち 2 本は期待 GREEN」 | 75/75・SKIP 0・GREEN (expected) 2（コピーで実測） | 一致 |
| notes R3.3「plan の変更は `undecided[]` / `undecided_details[]` への追加だけ・既存 `undecided_details` も不変・`decision_record` バイト不変」 | 実装者分は一致（`skill_plan` の 1 行は親の書き戻し）。件数だけ 22 ≠ 23 | F-C-P3-302 以外は一致 |
| notes R3.1 B-1「コードは変えていない」/ R3.2 項 6 | `layout.py` の差分はコメント 1 行・`geometry.py` 差分 0 | 一致 |
| notes R3.1 A-3「4 箇所」「grep で残り 0」 | 4 箇所とも訂正・誤引用の残り 0 | 一致 |
| notes R2.2 項 5（訂正後）「BOM だけの行は現状で既に exit 2（`bom.jsonl:2: JSON として読めません（Unexpected UTF-8 BOM）`）」 | exit 2・`:2: JSON として読めません（Unexpected UTF-8 BOM (decode using utf-8-sig)）。--trace は …`（要約として一致） | 一致 |
| layout.md §6:263-274 / conformance §2.24.1c / notes R2.2 項 4 の閾値（20 / 31-32 / 57-58） | 描画の実測と一致・境界は等号上に無い | 一致 |
| plan `DP-REVIEW-JIN-P3-001.phase_impact` の数値（0.3228 / 0.2640 / n=6 / n=7 / 0.227 / 0.286 / rune 帯 0.35〜0.40 / 「(a) でもスナップショット不変」） | 再計算で全部一致 | 一致 |
| `mutate_p3.py` の GREEN ラベル | 2 種類に分かれて実出力に出る | 一致（206 解消） |
