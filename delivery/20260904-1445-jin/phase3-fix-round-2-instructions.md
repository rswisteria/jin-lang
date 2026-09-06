# Phase 3 修正ラウンド 2 指示書（親 → impl-p3・2026-09-06）

修正ラウンド 1 の再レビュー（`code-review-raw/{correctness,conventions,wiring,security}-p3-round1.md`）の結果:
前回 62 件は **defect-gone 50 / 部分残存 8 / 残存 1 / 記録のみ 3**。修正が持ち込んだ新規は **30 件**（correctness 5 / conventions 13 / wiring 6 / security 6）、
confidence 90 以上 **5 件**。fail-open は 0。規律はラウンド 1 と同じ（本文は生出力を読む・固定テスト + 変異で赤を実測・仕様とコードを同時に・
指示と違えたら理由を P3-R2.2 に・git commit しない・8 ゲート再実測）。

## A. fix-now（confidence ≥ 90）

| # | finding | 対応 |
|---|---|---|
| A-1 | **F-V-P3-101**〔95〕= F-V-P3-010 の残存（`docs/spec/layout.md` §5 と `layout.py:77` が `model.md §3.3` を引いたまま。`main.py` だけ直った） | 残り 2 箇所を「CLAUDE.md / ADR-012」に直す。3 箇所を grep で確認して notes に列挙 |
| A-2 | **F-V-P3-103 / F-W-P3-105**〔90 / 90〕（R1.2 項 3 の理由「`core` の U+2028 は `name` に載る経路が無い」は偽。`model` 行の `name` は `.jin` の `core` そのもので、実測でトレースに生の U+2028 が載る） | R1.2 項 3 を事実（`core` 経由でも載る。`output` 経路を選んだのは FakeLlm の台本で制御できるため）に書き直し、端到端テスト `test_a_trace_written_by_jin_run_is_readable_by_jin_render` を **`core` 経路と `output` 経路の 2 param** にする（指示 A-1 の文言どおりに） |
| A-3 | **F-W-P3-102**〔90〕= F-W-P3-006 の部分残存（`packages/jin-render/tests/conftest.py` の docstring が今も存在しない網を根拠にしている） | 実物の網 `test_packaging_contract.py::test_package_tests_only_import_the_jin_packages_that_package_depends_on` を名指しする文に直す |
| A-4 | **F-C-P3-104**〔90〕（記録の誤り: 変異 `STAR-slot-identity` の効き方が実物と逆。実物は「星形テスト赤・訪問順テスト緑」。notes P3-R1.1 C-1 行・`mutate_p3.py` の説明・`undecided_details` の note の 3 箇所） | 3 箇所を実測どおりに直す（変異は捕まるので 59/59 は不変）。**ADR-021 と `decision_record` の rationale は親が auto-decider 経由で置換記録する**（あなたは触らない） |

## B. triage（80〜89・親判定で fix-now）

| # | finding | 対応 |
|---|---|---|
| B-1 | **F-C-P3-101**〔85〕（flow の弦が節の外枠より短いと**黙って描かれない**。examples 同型の中身で n ≥ 7、最大の中身では n ≥ 6 で `sequence` の弦が 0 本・loop も n=6 で 0 本。`/circles/i/flow` を指す要素が消える） | **弦は消さない。** 節の描画縮尺を兄弟間隔から導く: 入れ子の縮尺 `NESTED_SCALE`（0.28）を上限とし、節が多いときは「外枠半径 ≤ 隣接節の中心距離の半分 − 弦の最小本体長（矢じり長 + ε）」を満たす縮尺まで**中身ごと**縮める（外枠だけを詰めて中身がはみ出す形にしない）。layout.md §6 に式と根拠を書く（「0.28 は上限。実際の縮尺は n に依存」）。テスト: n=3..12 × 中身 3 種（core のみ / examples 同型 / core+boundary+guards）で `sequence` は n−1 本・`loop` は n 本の弦があり、各弦の本体長 ≥ 矢じり長。変異: 縮尺を 0.28 固定に戻して赤。スナップショット差分があれば要約を notes に |
| B-2 | **F-V-P3-102**〔80〕（CLAUDE.md「1〜8 の抜けは名指しで落とす」は 8 項目目について過大。8 項目目の 2 行を消しても緑） | `test_the_scan_finds_the_modules_that_carry_claims` に「主張を持つモジュールの**パッケージ名集合** == 期待集合のパッケージ名集合」を足して 8 を自己検出にする。`test_claude_md_has_the_package_addition_checklist` の期待語に `test_guard_claims.py` を足す。CLAUDE.md の文を「1〜7 は名指しで落とす。8 は … が自己検出する」に分ける |
| B-3 | **F-V-P3-105**〔80〕+ F-V-P3-007 の部分残存（pointer → kind 表テストと layout.md §7.2 に弦 `/circles/i/flow` と節 `/circles/i/flow/steps/j` の行が無い。kind を入れ替えても 147 passed） | §7.2 の表に 2 行足し、`POINTER_KINDS` に同じ 2 行（flow を持つ合成モデル）。§3 の 9 種表の `flow-edge` 行の対象列に「節」を足す（**`machine-readable` ブロックの第 1 セルは変えない**）。変異: 弦の kind を `circle` に、節の kind を `tool` にして赤 |
| B-4 | **F-V-P3-106**〔85〕（`implementation-plan.json` の `undecided_details[DP-IMPL-JIN-P3-ROUNDING-01].phase_impact` が「1300 px 級・2.3e-13」のまま） | 実装者の記録なので直してよい: 「最大座標 1000 px（キャンバスの縁）の 1 ULP は約 1.1e-13 px」に |
| B-5 | **F-W-P3-104**〔80〕= F-W-P3-008 の半分（`jin build` の成功メッセージが `_safe` を通っていない） | `build` の成功文言も `_safe` に通し、テスト 1 本（`jin build` 側にも制御文字入りの `--out` で） |

## C. 低（cheap なら直す・直さないものは理由を P3-R2.2 に 1 行）

- **F-S-P3-101**〔70〕: `_write_svg` の「事前 5 条件は防御ではない」docstring は入力 `.jin` 上書き拒否（`CLI-overwrite-the-input` が RED になる実効防御）に当てはまらない → その 1 条件を `guard: _write_svg -> <同一性判定のトークン>` として主張し docstring を分ける。**F-V-P3-113**〔50〕: `_new_file_mode` にも `guard:` 主張
- **F-W-P3-101**〔75〕: `child_env` の前置を固定するテスト（既存 `PYTHONPATH` が残ることを assert）
- **F-C-P3-102**〔70〕: `_outer_extent` の四角の角（`hypot`）— 列挙を `hypot` にするか docstring と §6 を「主要素の外接半径（角は隙間で吸収）」に
- **F-V-P3-104**〔60〕: 二層目が発火したときパスが 2 回出る → 事前判定のメッセージを 1 本に
- **F-V-P3-107 / 108 / F-C-P3-105**: `enumerate` + `_ = position` の残り / 関数内 import 3 箇所 / `test_determinism.py:73` の `splitlines`
- **F-V-P3-109**: 「チェックリストは 7 項目」の記述 3 箇所を 8 に
- **F-V-P3-110**: `test_a_huge_pointer_does_not_blow_up_memory_or_time` は時間だけ → 名前を実効検査に合わせるか `resource.getrusage` で maxrss も見る
- **F-V-P3-111 / 112**: `POINTER_KINDS` のコメント / notes P3-3「入れ子の縮尺 0.28」の式（B-1 で書き換わるので同時に）
- **F-W-P3-106**: R1.4 の「1 warning」を実数に
- **F-S-P3-103**〔40〕: `_write_stdout_bytes` の EPIPE 以外の `OSError` / `sys.stdout is None` → 1 行 exit 1。**F-S-P3-105**〔30〕: `os.umask` 復元を固定するテスト
- **F-C-P3-103**〔40〕（Unicode 空白だけの行を空行扱い）/ **F-S-P3-102**〔45〕（1 行長の上限なし）/ **F-S-P3-104**〔35〕（FIFO + `--force`）/ **F-S-P3-106**〔25〕（`--upto` 負数の全桁表示 → 80 文字で切る）/ **F-W-P3-103**〔40〕（tests の動的 import は網を素通り）: 判断を書く（記録のみでよい）
- 前回の記録のみ 3 件（F-C-P3-013 / F-V-P3-013 / F-S-P3-013）と部分残存 F-S-P3-011 の判断は再レビューが「妥当」と判定。変更不要

## D. 記録

`implementation-notes.md` に **P3-R2**（R2.0 まとめ / R2.1 対応表 / R2.2 指示と違えた判断 / R2.3 8 ゲート / R2.4 verification_status / R2.5 再レビュー依頼〔範囲限定〕）。
`mutate_p3.py` に B-1 / B-3 の変異を足し全件再実行。`decision-conformance.md` の P3 行を B-1（縮尺の式）に追従。
