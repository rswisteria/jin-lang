# Phase 3 修正ラウンド 1 指示書（親 → impl-p3・2026-09-06）

Stage 5 の 4 並列レビュー（`code-review-raw/{correctness,conventions,wiring,security}-p3.md`）の結果:
**correctness 13 / conventions 25 / wiring 11 / security 13 = 62 件**。レビュー開始時点でテスト 1005 件は全緑・変異 42/42 だった。
トリアージ規則は正本どおり（confidence ≥ 90 は fix-now・80〜89 は親が案件文脈で判定・< 80 は記録または cheap なら直す）。
**finding の本文は必ず生出力（`code-review-raw/*-p3.md`）を読むこと。** 本書は対応方針だけを書く。

## 規律（Phase 2 と同じ）

- 「直しました」は defect-gone の根拠にならない。修正ごとに**固定するテスト**を足し（無ければ）、`mutate_p3.py` に対応する変異を足して赤を実測する。
- 仕様側とコード側は同じ欠陥（layout.md とコードを同時に直す）。
- 指示と実物が食い違ったら、指示どおりにせず理由を `implementation-notes.md` P3-R1.2 に書く。
- 実ツリー以外（`/tmp`）に残骸を残さない。`__pycache__` 削除 + `PYTHONDONTWRITEBYTECODE=1` で 8 ゲートを再実測。
- git commit はしない。最終応答は短く（件数・変異数・notes の節名・4 状態）。

## A. fix-now（confidence ≥ 90・11 件。同型は束ねた）

| # | finding | 対応 |
|---|---|---|
| A-1 | **F-C-P3-001 / F-S-P3-003**（`splitlines()` が U+2028 / U+2029 / U+0085 で割り、`jin run` の出力を exit 2 で拒む） | `_read_trace_rows` を writer（`jin_adk.trace` の `json.dumps(ensure_ascii=False) + "\n"`）の区切りに合わせ `split("\n")`（末尾 `\r` は落とす）にする。U+2028 を `output` に含む 1 行 fixture テストと、**端到端**（`core` に U+2028 を含む `.jin` を `jin run --model fake --trace` → `jin render --trace` が exit 0）のテストを `tests/contract/test_render_contract.py` に足す。変異: `splitlines` に戻して赤 |
| A-2 | **F-S-P3-001**（巨大整数・深い入れ子で未捕捉トレースバック exit 1） | `except ValueError`（`JSONDecodeError` を含む）と `except RecursionError` で exit 2。`seq` に上限（`abs(seq) < 2**63` 等・layout.md §7.5 に明記）。テスト 2 本（5000 桁・10 万段） |
| A-3 | **F-S-P3-002**（`pointer_prefixes` の二次メモリ・100 KB 1 行で 2.4 GB） | 提案 (a): prefix を実体化せず、`by_pointer` の鍵側（要素数で有界）を走査して最長一致を取る線形実装に替える。既存の祖先一致テストを緑に保ち、100 KB の pointer 1 行で `render` が 1 秒以内・メモリが膨らまないテストを足す（計測はセグメント数 50 000 で `resource.getrusage` か時間で）。layout.md §7.1 の規則文は変えない（規則は同じ・実装が変わるだけ） |
| A-4 | **F-V-P3-001**（`DASH` が `fmt_coord` を通らない第 2 経路。examples に破線が出ないので正規表現検査が空振り） | `DASH` を `fmt_coord` で組む。`test_all_geometry_numbers_are_written_with_three_decimals` に破線が出る合成モデル（未解決 summon + delegate）を足し、`NUMERIC_ATTRS` の各属性が**少なくとも 1 回現れた**ことも assert（空振り検出）。変異: `DASH = "6 4"` で赤 |
| A-5 | **F-V-P3-002**（hostile circle 名の属性テストが空虚・docstring の「入力」列挙が過大） | テストを `test_names_are_not_emitted_into_the_svg`（`name not in svg` を assert）に替える。`svg.py` docstring を「SVG に流れる `.jin` 由来の文字列は rune のテキストノードだけ。属性エスケープは将来 `title` 等に名前を出すときの受け皿」に書き直す。`attr_value` は残す（`test_svg.py::test_attribute_escaping_*` が固定） |
| A-6 | **F-V-P3-003**（`test_every_live_pointer_resolves_for_each_focus` の名前と実効検査の不一致） | `test_at_least_one_live_pointer_resolves_for_each_focus` に改名し docstring を合わせる（全件版は `..._at_the_root_focus` が担う） |
| A-7 | **F-W-P3-001**（google-adk 禁止契約の `source_modules` から `jin_render` を外しても 1005 件緑） | `test_packaging_contract.py` に `test_adk_isolation_contract_covers_every_package_but_jin_adk_and_jin_cli`（期待集合 = `root_packages − {jin_adk, jin_cli}`）を足す。契約名の文字列一致に依存しない形で契約を特定する（`forbidden_modules == ["google"]` で引く等）。変異: `source_modules = ["jin_core"]` で赤 |
| A-8 | **F-W-P3-002**（注入テストが `jin_core` にしか無い） | `test_import_linter_actually_bites_on_a_forbidden_import` の parametrize を `(package, target_file, injected, keyword)` に広げ、`jin_render/svg.py` への `import google.adk` / `import jin_adk` / `from jin_cli.resolver import ImportResolver`、`jin_adk/trace.py` への `import jin_render` の 4 件を足す |
| A-9 | **F-W-P3-003 / F-S-P3-012 / F-C-P3-006**（`-o` の親ディレクトリ不在で「書き込む直前にファイルが消えました」） | `_write_svg` で `path.parent.is_dir()` を先に見て `WriteRefused("出力先のディレクトリがありません: <parent>")`（**作らない**）。README の `jin render` 節に「親ディレクトリは作らない」を 1 行。テスト 1 本 |
| A-10 | **F-W-P3-005**（`test_the_help_lists_render` が `render` コマンド無しでも緑） | `runner.invoke(app, ["render", "--help"]).exit_code == 0` に替える。変異: `@app.command()` を外して赤 |
| A-11 | **F-W-P3-006**（jin-render の tests が `jin_adk` を import しても落ちない・conftest docstring が存在しない網を根拠にしている） | `_jin_imports` の走査対象に `package / "tests"` を足し、許可集合を「自パッケージの `dependencies` に宣言した jin-* + 自分自身 + `tests`（共有 conftest）」にする。既存の `packages/jin-adk/tests` / `packages/jin-cli/tests` が現状で通ることを先に確認（通らないなら理由を書いて相談）。conftest docstring を実物に合わせる。変異: `test_svg.py` に `import jin_adk` で赤 |

## B. triage（confidence 80〜89・親が fix-now と判定した 9 件）

| # | finding | 判定と対応 |
|---|---|---|
| B-1 | **F-C-P3-003**〔85〕（layout.md §7.2 / §7.3「summon の紋（入れ子の小陣の外枠）が強調」が実物と不一致。朱は放射線だけ） | **fix-now・描画側を直す**: summon の紋として見える外枠（入れ子の最外環の少し外側の円・pointer は参照側 `/circles/i/tools/j`・kind `tool`・`data-jin-ref` は参照先）を wrapper 直下に描き、tool 行で朱くなることをテストで固定。F-C-P3-005〔80〕（放射線・弦の終端が入れ子の実際の最外環と一致しない）も同じ箇所なので extent を入れ子の実際の最外環から導く形に直す。スナップショット更新は差分を読んで notes に要約 |
| B-2 | **F-W-P3-004**〔85〕（`live_trace` が `PYTHONPATH` を上書き・F-W-P2-007 の再発・mutate_p3 の 5 変異が実ツリーの `jin_cli` / `jin_adk` を読む） | **fix-now**: `tests/conftest.py` に「STUBS を前置した env を返す」共通ヘルパを 1 つ置き、`test_cli_contract._run` と `test_render_contract.live_trace` の両方から使う。`mutate_p3.py` の `_env` も前置に |
| B-3 | **F-V-P3-004**〔85〕（トレース行エラーが 0 始まり「N 行目」・同一コマンドの JSON エラーと書式が違う・空行でずれる） | **fix-now**: `_read_trace_rows` が `(line_number, row)` を持ち回り、`overlay.read_trace` の例外に添字を載せて CLI 側で `path:N:`（1 始まり・ファイルの実行番号）にそろえる。メッセージを assert するテスト 1 本 |
| B-4 | **F-V-P3-008 / F-C-P3-010**〔85 / 45〕（丸め根拠の「最大座標 1300 px 級」が 1000 px 角キャンバスと矛盾） | **fix-now**: layout.md §4・`decision-conformance.md` §2.24.1・notes P3-3 を「最大座標は 1000 px（キャンバスの縁）。1 ULP は約 1.1e-13 px」に直し、`test_rounding_step_is_far_above_the_float_noise` の `largest` を `geo.CANVAS_PX` から導く。**auto-decider の constraint 文の追従は親がやる**（あなたは `decision_record` を編集しない） |
| B-5 | **F-S-P3-005**〔80〕（rune の U+FFFE / U+FFFF で SVG が well-formed でなくなる） | **fix-now**: `text_value` / `attr_value` で XML 1.0 の Char 生成規則に無い文字（制御文字・サロゲート・U+FFFE / U+FFFF）を U+FFFD に置換し、`guard:` 主張とテスト（`xml.etree` で parse できる）を足す。layout.md §3 に 1 行。`jin_core` のモデル検証は**変えない**（診断を増やさない） |
| B-6 | **F-V-P3-005**〔80〕（`guard: _write_svg -> path.is_symlink` は実効ガードでない） | **fix-now**: `_write_svg` の `guard:` は `_write_atomically(path,text,allow_create=True)` の 1 本にし、事前判定は散文で「文言のための早期判定（防御ではない）」と書く。`mutate_p3.py` の `EXPECT_GREEN` の説明も合わせる |
| B-7 | **F-V-P3-006**〔80〕（`guard:` 網羅テストの期待集合に `svg.py` が無く、主張を全削除しても緑） | **fix-now**: 期待集合に `jin-render/src/jin_render/svg.py` を足す。CLAUDE.md のパッケージ追加チェックリストに 8 点目「`test_guard_claims.py` の期待集合に新パッケージの `guard:` ファイルを足す」を追記（`test_claude_md_has_the_package_addition_checklist` が壊れないことを確認） |
| B-8 | **F-V-P3-007**〔80〕（`data-jin-kind` の個別値が未固定。kind の入れ替え変異が緑） | **fix-now**: layout.md §7.2 の表をそのまま写した「pointer の末尾セグメント → 期待 kind」テストを examples + 合成モデルで回す。変異: `flow.exit` の印を `core` にして赤 |
| B-9 | **F-C-P3-004 / F-S-P3-007 / F-V-P3-019**〔75 / 65 / 55〕（`seq <= 0` を受理し `--upto 0` で発火） | **fix-now**（3 観点が独立に指摘）: `read_trace` で `seq < 1` を `ValueError`（黙って捨てない側）。上限は A-2 と同時に。テスト 1 本・変異 1 件 |

## C. 判断が要るもの（HANDOFF に登録して推奨案で実装）

| # | finding | 対応 |
|---|---|---|
| C-1 | **F-C-P3-002**〔70〕（loop の矢印が j → j+k を指し、要件書 §2.5「辺の順を訪問順に一致させる」と逆。layout.md §2.1 も文書内で食い違っている） | HANDOFF **`DP-IMPL-JIN-P3-LOOP-STAR-ORDER-01`** を `undecided[]` / `undecided_details[]` に登録（選択肢: (a) 節 i を角位置 `(i·k) mod n` に置き辺を i → i+1 にする＝星形を保ちつつ矢じりが実行順を指す / (b) 現状（節は配列順の等角配置・辺は j → j+k）を保ち矢じりを外す / (c) 現状のまま）。**推奨 (a)** で実装し、layout.md §2.1 の最終段と §6 の loop 行・`test_loop_edges_follow_the_star_polygon` の期待値・スナップショットを同時に直す。gcd(n,k)=1 で角位置が全単射になること・`n < 5`（k=1）では配置が変わらないことをテストで固定。notes P3-6 に質問セットを追記 |
| C-2 | **F-S-P3-004 / F-V-P3-015**〔75 / 55〕（`jin render -o` の新規ファイルが umask を無視して 0644・`jin build` は umask が効く・notes P3-7 の 9 の論拠 (b) は不成立） | **親の判定: `jin build` に合わせる（umask を尊重）。** 実装は `_write_atomically(allow_create=True)` の新規作成経路で `os.open(..., O_CREAT|O_EXCL, 0o644)` 相当の umask が効く作り方に統一する（`mkstemp` 0600 → `chmod` の代わりに、build の `write_project` と同じ手順を再利用できるならそれを使う）。`test_the_output_file_is_created_with_the_generated_file_mode` は「`0o666 & ~umask`（実行時の umask を `os.umask` の往復で 1 回だけ読む）に一致」に書き換える。notes P3-7 の 9 を「レビューで覆った」と更新し、論拠 (b) を撤回する |

## D. 低（confidence < 80・cheap なら直す。直さないものは理由を notes に 1 行）

correctness: F-C-P3-007（到達しない `accent_attr="fill"`）/ 008（存在しない規則番号）/ 009・F-V-P3-012（ダイジェスト末尾バイトの記述が 3 箇所で食い違う → 1 箇所に統一）/ 011・F-S-P3-009・F-W-P3-008・F-V-P3-016（成功メッセージも `_safe` を通す）/ 012（核なし circle に state / boundary / delegate があるケースのテスト 1 本）/ 013（`pointer_prefixes("/")`・A-3 で消えるなら記録のみ）。
conventions: F-V-P3-009（テストの `__import__` を通常 import に）/ 010（model.md §3.3 の引用先を正す）/ 011（`noqa: TRY004` の削除）/ 013（plan `$comment` に Phase 3 の extend を追記）/ 014・020・021・022（可読性・`assert`・正規表現の誤反応・関数内 import）/ 017・018（layout.md §6 の所在記述と `__all__` の整理）/ 023（notes の「42 件」を実数に）/ 024（layout.md 冒頭の節番号）/ 025（`data-jin` 欠落を `""` に潰さない）。
security: F-S-P3-006（`except UnicodeDecodeError` 枝のテスト）/ 008（型違いの `!r` 出力を長さ制限）/ 010（stdout のエンコーディング失敗を 1 行 exit 1 に。`jin dump` の流儀に合わせる）/ 011（`--trace` の全読み上限・記録のみでもよいが判断を書く）/ 013（`exists()` の二重判定の窓・記録のみ）。
wiring: F-W-P3-007（`-o` が入力 `.jin` と同一パスなら拒む・1 行）/ 009（`MUTATE_ONLY` typo 検査を先に）/ 010（記録のみ）/ 011（`-o` がディレクトリのときの文言）。

## E. 記録

- `implementation-notes.md` に **P3-R1**（R1.0 要約 / R1.1 対応表 finding → 変更箇所 → 固定テスト → 変異 / R1.2 指示と違う判断 / R1.3 Red 証跡 / R1.4 8 ゲート実測 / R1.5 verification_status / R1.6 再レビュー依頼）を追記。
- `decision-conformance.md` の P3 行を修正内容に追従（丸め根拠・umask・XML Char）。
- `mutate_p3.py` に新しい変異を足し、全件を再実行して caught 数を書く。
- `implementation-plan.json` の `undecided[]` に `DP-IMPL-JIN-P3-LOOP-STAR-ORDER-01` を登録（他は触らない）。
