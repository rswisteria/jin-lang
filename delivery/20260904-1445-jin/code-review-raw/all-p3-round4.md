# Stage 5 review: all（correctness / conventions / wiring / security まとめ）— Phase 3 (jin-render) 修正ラウンド 4 の最終確認

対象: 修正ラウンド 4（`phase3-fix-round-4-instructions.md`・notes **P3-R4**）。入力はラウンド 3 の新規 8 件
（F-C-P3-301〜303 / F-V-P3-301〜303 / F-W-P3-301〜302）と残存 6 件（F-V-P3-203 / 204 / 205 / 208 / 209 / 210）。
判定はレビュー中に親がコミットした **`8af3df2`** の内容に対して行った（下記）。

## 実測した環境・コマンド（隔離コピーのパス・件数）

- 隔離コピー: `/home/wisteria/.claude/jobs/e2bcfe94/tmp/rereview4/`（rsync・`.git` / `.venv` / キャッシュ除外）。自前変異用に
  `rereview4-mut/` を別に取った。**実ツリーは 1 バイトも変更していない**（`git status --short` は親が後で足した
  `implement-ledger.md` の 1 行だけ。コピーと worktree の `diff -rq` も ledger 以外は同一）。
- レビュー中に親が worktree を **`8af3df2`（feat(jin): Phase 3 …）** としてコミットした。`git diff --stat HEAD` は
  ledger 1 ファイルだけなので、コピー = HEAD（ledger を除く）。以下の判定はこのコミットの内容に対するもの。
- R4 の差分は R3 時点の隔離コピー 2 本（`rereview3-correctness/` と `rereview3-conventions/`・両者で一致）との
  `diff -rq` / `diff -u` で取った。変わったファイル: `main.py`（symlink 文言 3 箇所 + コメント）/ `test_build_run.py`（テスト 1 本追加）/
  `test_render.py`（`startswith` 1 行 + import 移動）/ `test_overlay.py`（コメント 1 行）/ `test_packaging_contract.py`（docstring）/
  `test_render_contract.py`（import 移動）/ `mutate_p3.py`（変異 2 本追加・`before` 追従）/ `layout.md`（3 行）/
  `decision-conformance.md`（1 行）/ `implementation-notes.md` / 親の台帳 3 本（`implementation-plan.json` の `evidence[]` 3 行 +
  `skill_plan`・`implement-ledger.md`・`code-review-report.md`）。**`jin_render` 配下・`jin_core` / `jin_adk`・テンプレート・
  スナップショットに差分なし。** `main.py` の差分は f-string の語順（`理由: {path}` → `{path}: 理由`）とコメントだけで、分岐・
  exit code・書き込み経路は不変（下の probe でも確認）。
- 全スイート（`PYTHONDONTWRITEBYTECODE=1`・`__pycache__` 削除・`-p no:cacheprovider`）: **1202 passed, 68 warnings, 6 snapshots passed**
  （`rereview4-scripts/pytest-full.log`）。`/dev/full` テスト 2 本は skip されず実行された。
- `mutate_p3.py`（`TMPDIR` を job tmp に向けて実行・`rereview4-scripts/mutate_p3.log`）: baseline green（394 passed）・
  **77/77 mutations caught・RED 75 + 期待 GREEN 2・SKIP 0・EXIT 0**。新規 2 本 `CLI-symlink-message-order` / `CLI-build-success-raw-echo`
  はどちらも **RED (expected)・1 failed**。`/tmp` に `jin-mutate-p3-*` 残骸 0・作業コピーも削除済み。
- ゲート（コピー上・`rereview4-scripts/gates.log`）: `uv lock --check` EXIT 0 / `ruff check` All checks passed / `ruff format --check`
  77 files already formatted / `lint-imports` Contracts: 3 kept, 0 broken / `jin schema` 差分なし / `jin check examples` 2 ファイル・error 0・
  warning 0 / `jin fmt --check examples` EXIT 0 / `jin check` / `fmt --check` `tests/fixtures/build-errors` 20 ファイル・EXIT 0。
  import 元がコピーであることを `jin_cli.__file__` / `jin_render.__file__` で確認。`uv sync` はコピーに venv が無いので実行せず
  （`uv lock --check` で lock と pyproject の整合だけ見た。notes R4.3 の「Checked 76 packages」は `uv sync` の出力で、別コマンド）。
- 自前変異（`rereview4-scripts/hand_mutations.py`・`rereview4-mut` 上・実行後に原本へ復元を assert）:

| 変異 | 回したテスト | 結果 |
|---|---|---|
| M-A `build` の `_echo_or_exit(f"書き出しました: …")` → `typer.echo` | `test_build_run.py` + `test_render.py` 全体 | **1 failed, 99 passed**（新テストだけが落ちる） |
| M-B `_write_svg` 一層目の並びを `理由: {path}` に戻す | `test_render.py -k symlinked` | **1 failed** |
| M-C `_write_atomically` 二層目の並びを戻す | `test_render.py` + `test_cli.py -k symlink` | 7 passed（緑・下の「偽 green 候補」） |
| M-D `_write_in_place` ELOOP 退避路の並びを戻す | 同上 | 7 passed（緑・同上） |

- probe（`rereview4-scripts/probe_symlink.py`・CliRunner・コピーの `jin_cli` を import していることを assert）:
  `render -o <symlink> --force` → exit 1・`<path>: シンボリックリンクなので書き込みを拒みました`・パス 1 回。
  `fmt <symlink.jin>` → exit 0・`シンボリックリンクなので整形しません: <path>`（`fmt` 自身のスキップ文言・R4 で不変）。

## 前回 finding の判定

判定の語: **defect-gone** / **部分残存** / **残存** / **記録のみ（妥当）**

| finding | 判定 | 根拠（実測） |
|---|---|---|
| F-C-P3-303 / F-W-P3-301（build 側の `/dev/full` が未固定） | **defect-gone** | `test_build_run.py::test_a_full_stdout_on_the_build_success_message_is_one_line_not_a_traceback`（`/dev/full`・rc 1・`標準出力に書けません`・`Traceback` 無し・stderr ちょうど 1 行・`out/Pipeline/agent.py` 生成済み）。M-A で **1 failed**、ハーネス `CLI-build-success-raw-echo` RED。コード側は R3 のまま（差分なし・notes の主張どおり） |
| F-C-P3-301 / F-V-P3-302（`layout.md` §6 の相互参照の向き） | **defect-gone** | `layout.md:215` 表セル「（**下記**・DP-REVIEW-JIN-P3-001）」、`:282` 段落「**上の表**の『12 個並べても重ならない』」。表 209〜237 行・段落 276〜283 行なので向きは正しい。§6 は 203〜288 行、§7.2 の `/circles/i/flow/steps/j` 行が指す「（§6）」の n >= 20 の記述は `:263` で §6 内 |
| F-C-P3-302 / F-W-P3-302（notes「`decision_record` 22 件」） | **defect-gone** | notes R2.3 / R3.3 とも **23 件** に訂正し「私は触っていない」の主張に書き換え（旧 2 行は `-` 側で消えた）。実物 `len(plan["decision_record"])` = **23**・`undecided` 10 |
| F-V-P3-301（symlink 文言の並び） | **defect-gone** | `main.py:318` / `:420` / `:1007` の 3 箇所が `f"{path}: シンボリックリンクなので書き込みを拒みました"`（grep で旧並び 0）。`test_render.py:117` `result.output.startswith(f"{link}: シンボリックリンク")` が**並び**を見る。M-B 1 failed・ハーネス `CLI-symlink-message-order` RED。`main.py:60` / `:1003` の「`path: 理由`」主張と実装が一致した。`test_cli.py:840`（`fmt` 退避路）は部分一致なので緑のまま。二層目 / 退避路の並びはテスト未固定（下の観察） |
| F-V-P3-303（R3.0 の数え違い・205 / 208 / 209 / 210 が未対応・未記録） | **部分残存（低・記録の文言）** | 4 件は R4.1 項 5 の表で **205 / 208 / 210 を修正・209 を記録のみ** として全件記録された（下 4 行）。しかし指示書 #5 の後半「**R3.0 の数を実数に**」は未実施: notes `:1660-1662` の「C 節が名指しする finding は 10 件で、8 件を直し … 2 件は記録のみ … F-V-P3-111 は R2 で対応済み」は R3 のまま（R3 → R4 差分の `-` 側に無い）。R4.1 項 5 は「数に入れていなかった」と認めるだけで原文を直していない。判定への影響は無い（数字を読む人が R4.1 を併読すれば分かる）が、指示の要求そのもの |
| F-V-P3-203（`packaging:399`「計 7 項目」） | **defect-gone** | docstring を「5 箇所 + `tests/__init__.py` + 依存する側の pyproject + `test_guard_claims.py` の期待集合（計 8 項目）」に。`CLAUDE.md:58-72` のチェックリストは 1〜8 の **8 項目**、`test_dependency_direction.py:221`「8 項目」と一致。`ruff check` / `format --check` 緑（長い 1 行だが docstring） |
| F-V-P3-204（関数内 import 残り 2） | **defect-gone** | `test_render.py:17` `from jin_cli.main import _new_file_mode, app`、`test_render_contract.py:18` `import xml.etree.ElementTree as ET`。関数内 import は両ファイルとも 0 |
| F-V-P3-205（`test_overlay.py` 見出し「書き写す」） | **defect-gone** | `:326`「layout.md §7.2 と §3 から起こした対応」。直下 `:328-331` の「写しではない」と整合 |
| F-V-P3-208（conformance §2.24.3「縮尺 0.28」） | **defect-gone** | `decision-conformance.md:641`「入れ子の縮尺 **上限** 0.28（flow の節は §2.24.1c で兄弟間隔まで縮む・n >= 20 なら点）」。`layout.md:319` §7.2 の節の行に「**節が多い（n >= 20）ときは解決しても点**（§6）」を追加。§6 `:263`「n >= 20 では … 点を描く」と三者一致 |
| F-V-P3-209（plan `evidence[]` に変異の最終行が無い） | **記録のみ（妥当）→ 親が解消** | 実装者は「親の台帳なので触らない」と R4.1 項 5 に記録（理由は妥当・R2 / R3 の指示どおり）。親が `implementation-plan.json:2158-2160` に `[jin_phase=3][review]` / `[gates] 1202 passed` / `[mutation] 77/77 … 42 → 59 → 70 → 75 → 77` の 3 行を追加済み。実測（1202 / 77/77 / 3 kept / 77 files）と一致 |
| F-V-P3-210（`FLOW_POINTER_KINDS` を別リストにした判断が未記録） | **defect-gone** | notes R2.1 B-3 行に「別に立てた（理由は R2.2 項 13）」、R2.2 に項 13（核あり / 核なしでモデルが分岐するため）を追記 |

集計: 新規 8 件は **defect-gone 7 / 部分残存 1（F-V-P3-303・記録の文言）**。残存 6 件は **defect-gone 5 / 記録のみ（妥当・親が解消）1**。
fail-open 0・退行 0。

## 挙動が変わっていないことの確認（指示「コードの挙動は変えない」）

- `main.py` の差分は **3 つの f-string の語順と 2 行のコメント**だけ（`diff -u` 全文を読んだ）。`if` / `raise` の型 / `from exc` / 経路は同一。
- `packages/jin-render/`・`jin_core`・`jin_adk`・`templates/`・`__snapshots__/` に差分なし。全スイートで **6 snapshots passed**（R3 と同数）。
- ハーネスの baseline は R3 と同じ **394 passed**。期待 GREEN も R3 と同じ 2 本（`CLI-follow-symlink-upfront-only` / `STAR-pre-fix-star-shape-stays`）。
- probe: `render -o <symlink>` は R3 と同じく exit 1・パス 1 回。並びだけが変わった。

## Findings（修正が持ち込んだ・見つけた新規。いずれも低）

### F-V-P3-401 [confidence 25] `fmt` の symlink スキップ文言（`main.py:590`）は `理由: path` のままで、R4.2 項 1「レビューの提案 (a)『一層目・二層目・`fmt` を `path: 理由` に』に合わせた」と対応が読めない
- 場所: `packages/jin-cli/src/jin_cli/main.py:590`（`typer.echo(f"シンボリックリンクなので整形しません: {path}", err=True)`）、notes R4.2 項 1、R4.1 項 4「`fmt` の表示と同じ形」
- 内容: R3 の F-V-P3-301 本文が「`fmt` の `:590` も `理由: path`」と名指しした行は R4 で触られていない（probe: `fmt <symlink.jin>` → `シンボリックリンクなので整形しません: <path>`）。
  ただしこの行は `WriteRefused` ではなく `fmt` の per-file 出力（`整形しました: {path}` / `差分あり: {path}`）と同じ **`結果: path` 様式**に従っており、
  こちらを `path: 理由` にすると今度は `fmt` 内の並びが割れる。実装の選択は妥当。ずれているのは**記録の側**: R4.2 項 1 の「`fmt` にも `理由: path` が残る … (a) に合わせた」が
  `:590` を指すなら残ったまま、`_write_atomically` 経由の表示（`{path}: 書き込めません（…: {path}: シンボリック…）`）を指すならそう書くべき
- 変異検証: 該当なし（文言）
- 提案: R4.2 項 1 に「`fmt` 自身のスキップ文言 `:590` は `fmt` の `結果: path` 様式に従うので触らない」を 1 文。コードは変えない

## 変異で緑のままだったテスト（偽 green の候補）

| 変異 | 内容 | 結果 | 評価 |
|---|---|---|---|
| M-C | `_write_atomically` 二層目の symlink 文言の並びを `理由: path` に戻す | 緑（7 passed） | 二層目は一層目の判定と `os.replace` の間にリンクが差し込まれた競合窓でしか到達しないので、通常経路のテストでは固定できない。`CLI-follow-symlink-upfront-only` が「二層目が拒むこと」自体は固定している（期待 GREEN の理由）。並びまで固定するには一層目を monkeypatch する必要があり、費用対効果が合わない。**欠陥ではない** |
| M-D | `_write_in_place` ELOOP 退避路の並びを戻す | 緑（7 passed） | `test_cli.py:840` は `fmt` が包んだ文言 `{path}: 書き込めません（…: {exc}）` の中の部分一致しか見ない。R4.2 項 2 が記録するとおりここではパスが 2 回出るので、並びを固定するなら `f": {swapped}: シンボリックリンク" in result.output` の 1 行。**低**。次のラウンドがあれば |

R3 で緑だった M7（build 側 `typer.echo`）は M-A / ハーネスで **赤**に転じた。

## 実装者の記録（notes / conformance / plan / layout.md）と実物の不一致

| 記録 | 記述 | 実物 | 判定 |
|---|---|---|---|
| notes R3.0 `:1660-1662` | 「C 節 10 件・8 件を直し・2 件は記録のみ・F-V-P3-111 は R2 で対応済み」 | R4.1 項 5 が数え違いを認めたが原文は未修正 | F-V-P3-303 部分残存 |
| notes R4.2 項 1 | 「`fmt` にも `理由: path` が残る … (a) に合わせた」 | `fmt:590` のスキップ文言は `理由: path` のまま（`fmt` 様式としては整合） | F-V-P3-401（記録の曖昧さ） |
| notes R4.0 / R4.3 | 1202 passed・68 warnings・6 snapshots・77/77・SKIP 0・期待 GREEN 2・ruff 77 files・3 kept・schema 無ドリフト・examples 2 ファイル | すべて一致（コピーで実測） | 一致 |
| notes R4.1 項 4 | 「3 箇所」（一層目 / 二層目 / ELOOP 退避路） | `main.py:318` / `:420` / `:1007` の 3 箇所・旧並び grep 0 | 一致 |
| notes R4.1 項 1 | 「コードは変えていない・テストと変異が無かっただけ」 | `main.py` の R3 → R4 差分に `build` 側の行は無い | 一致 |
| notes R4.3 | 「`implementation-plan.json` は触っていない・差は親の `skill_plan` 追加」 | R3 → R4 差分は `evidence[]` 3 行 + `skill_plan` 1 要素（いずれも親の記述・ledger と整合）。`decision_record` 23 件で同一 | 一致 |
| plan `evidence[]` `[jin_phase=3][review]` | 「初回 62 件 … R3: 新規 8」 | round3 の新規は C3 + V3 + W2 = 8 | 一致 |
| `code-review-report.md` 最終確認欄 | 1202 passed / 77/77 / 8 ゲート | 一致 | 一致 |
| `implement-ledger.md` 最終行 | 「本行以降はコミット・PR」 | `8af3df2` が実在（worktree で `git log`） | 一致 |

## 総合

R4 の差分は文言・テスト 1 本・変異 2 本・記録に限られ、`jin_render` と生成物は不変（スナップショット 6 本・baseline 394・probe で確認）。
新規 8 件は defect-gone 7・部分残存 1（notes R3.0 の数字の原文が未修正・記録の文言のみ）。残存 6 件は defect-gone 5・記録のみ 1（親が plan に追記済み）。
新規欠陥は F-V-P3-401（confidence 25・記録の曖昧さ）のみ。fail-open 0。**DONE**（Phase 3 のコードは閉じてよい。F-V-P3-303 の原文と F-V-P3-401 は
次に notes を触るときに 2 文で直せる）。

ログ: `/home/wisteria/.claude/jobs/e2bcfe94/tmp/rereview4-scripts/{pytest-full,mutate_p3,gates}.log`、
スクリプト: 同ディレクトリの `run_pytest.sh` / `hand_mutations.py` / `probe_symlink.py` / `gates.sh`。
