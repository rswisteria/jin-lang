# Phase 3 修正ラウンド 4 指示書（親 → impl-p3・2026-09-06・**最終・文言とテスト 1 本のみ**）

最終確認レビュー（`code-review-raw/*-p3-round3.md`）: ラウンド 2 の新規 26 件は **defect-gone 17 / 部分残存 2 / 残存（低）4 / 記録のみ 5（妥当）**。
fail-open 0。新規は confidence 90 が 3 件（いずれも文言・数字・テスト 1 本）。**コードの挙動は変えない。**

| # | finding | 対応 |
|---|---|---|
| 1 | **F-C-P3-303 / F-W-P3-301**〔90 / 70〕（`jin build … > /dev/full` は 1 行 exit 1 で正しいが、build 側にテストも変異も無く `_echo_or_exit` を `typer.echo` に戻しても緑） | `packages/jin-cli/tests/test_build_run.py` に `/dev/full` へ stdout を向けて exit 1・1 行のテストを 1 本。`mutate_p3.py` の `CLI-success-message-raw-echo` を build 側にも掛ける（または `CLI-build-success-raw-echo` を追加）→ 赤を実測 |
| 2 | **F-C-P3-301 / F-V-P3-302**〔90 / 55〕（`docs/spec/layout.md` §6 の相互参照 2 箇所が「上記 / 下の表」で向きが逆） | 向きを直す |
| 3 | **F-C-P3-302 / F-W-P3-302**〔90 / 35〕（notes の「decision_record 22 件」は実物 23 件） | 実数（`python -c` で数える）に直し、R3.3 の「不変」の主張は「親の record.py 以外は触っていない」に書き直す |
| 4 | **F-V-P3-301**〔60〕（symlink 拒否文言が「理由: path」の並びで、docstring・notes・指示書の「path: 理由」と逆） | 他の `WriteRefused` と同じ **「path: 理由」** に並びをそろえ、テストは並びも見る |
| 5 | **F-V-P3-303**〔50〕（R3.0「C 節 8 件直し・2 件記録のみ」の数え違い。205 / 208 / 209 / 210 が未対応・未記録） | 4 件を直す（cheap）か記録のみの理由を書き、R3.0 の数を実数に |
| 6 | F-V-P3-203 / 204 の部分残存（`packaging:399`「計 7 項目」/ 関数内 import 残り 2） | 直す |

記録: `implementation-notes.md` に **P3-R4**（対応表 6 行 / 8 ゲート実測 / 変異 caught 数）。8 ゲートと `mutate_p3.py` 全件を再実測。git commit はしない。最終応答は 5 行以内。
