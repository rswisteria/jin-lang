# Phase 3 修正ラウンド 3 指示書（親 → impl-p3・2026-09-06）

修正ラウンド 2 の再レビュー（`code-review-raw/*-p3-round2.md`）: 前回の新規 30 件は **defect-gone 25 / 部分残存 3 / 悪化 1 / 記録のみ 5（妥当）**。
新規 **26 件**（correctness 6 / conventions 10 / wiring 5 / security 5）・confidence 90 以上 **4 件**（うち 3 件は同じ退行を 3 観点が独立に指摘）。fail-open 0。
規律はラウンド 1・2 と同じ。**これで最後のラウンドにする**つもりなので、指示に無い変更を増やさない。

## A. fix-now

| # | finding | 対応 |
|---|---|---|
| A-1 | **F-C-P3-202 / F-V-P3-201 / F-S-P3-201**〔95 / 90 / 85〕（R2 の F-V-P3-104 対応で、`jin render -o <symlink>` の**通常経路**の拒否文言からパスが消えた退行。既存テストは部分文字列一致で偽 green） | 文言にパスを戻す（`fmt` / ディレクトリ拒否と同じ `path: 理由` の形）。テストは**パスが含まれること**を assert。二層目が発火したときの二重表示（元の F-V-P3-104）は「事前判定の文言にパスを含め、二層目の `WriteRefused` は render 側で捕まえて 1 行にする」形で両立させる。変異: パスを落として赤 |
| A-2 | **F-C-P3-203**〔90〕（R2.2 項 5 の理由「空行の定義を ASCII に狭めると BOM 付き空行が壊れた行になる」は偽。BOM 行は今すでに exit 2） | R2.2 項 5 を事実に書き直す（判断〔記録のみ〕は変えない）。BOM 付き行が exit 2 になることを固定するテストが無ければ 1 本足す |
| A-3 | **F-C-P3-204 / F-V-P3-202**〔90 / 85〕+ R2.5 項 5（`model.md §3.3` の誤引用は Phase 2 側に **4 箇所**: `packages/jin-adk/src/jin_adk/codegen.py` 2 行・`docs/spec/adk-mapping.md:124` と `:168`） | **親判定: 今このブランチで直す**（コメント・文書の引用先だけ。4 行・`machine-readable` 外・`tests/spec` 対象外）。R2.2 項 1 の「3 箇所」も 4 に直す。grep で残り 0 を確認して notes に列挙 |

## B. triage（80〜89・親判定）

| # | finding | 対応 |
|---|---|---|
| B-1 | **F-C-P3-201**〔85〕（道具環の summon 紋が最大の中身で n ≥ 6、examples 同型で n ≥ 7 のとき隣と重なる。R2.2 項 3 の別件） | **fix-later**: `implementation-plan.json` の `undecided[]` / `undecided_details[]` に **`DP-REVIEW-JIN-P3-001`** として起票（選択肢: 紋の縮尺を兄弟間隔から導く〔B-1 と同じ規則を道具環へ〕/ tools 12 個の上限〔JIN020〕を根拠に定数を詰める / 現状のまま。判断期限は Phase 5 のエディタ着手前）。コードは変えない。layout.md §6 に「道具環の紋は縮尺を詰めない（既知の重なり・DP-REVIEW-JIN-P3-001）」を 1 行 |
| B-2 | **F-C-P3-205 / F-S-P3-2xx**〔85〕（layout.md §6「n ≥ 32 で弦がまた消える」は実測 n ≥ 58。32〜57 は矢じりが本体より長くなる別条件） | §6 の 1 文を実測に直す（「n ≥ 32 で本体が矢じりより短くなり、n ≥ 58 で弦が消える」）。R2.2 項 4 の数字も直す。両方の境界を固定するテスト（n=31/32、57/58）を足す |
| B-3 | **F-W-P3-201**〔70〕（`jin render -o … > /dev/full` で成功文言の `typer.echo` が rich トレースバック + exit 120。`-o` 無し経路の 1 行 exit 1 と揃っていない） | 成功文言の出力を `-o` 無し経路と同じ `OSError` 包み（1 行 stderr・exit 1）に。`build` の成功文言も同じ（同型・1 箇所のヘルパで）。テスト: `/dev/full` に stdout を向けて exit 1 |
| B-4 | **F-W-P3-202 / F-S-P3-202**〔60 / 40〕（`sys.stdout is None` 分岐にテスト無し。`preexec_fn=os.close(1)` で作れる） | テスト 1 本を足す（wiring の実測どおり `preexec_fn` で fd 1 を閉じる）。難しければ理由を書いて記録のみ |

## C. 低（cheap なら直す）

- F-C-P3-102 の残り（`layout.py:481` のコメント 1 行が旧文言）/ F-V-P3-108（関数内 import の残り）/ F-V-P3-109（「7 項目」の残り）/ F-V-P3-111（`POINTER_KINDS` コメント）/ F-V-P3-207（ε=0.01 の項が未固定・害なし・記録でもよい）/ F-V-P3-203〜210 の残り（本文を読む）
- F-W-P3-204（`mutate_p3.py` の期待 GREEN の印字理由が「二層目が守る」のまま → 2 本目は「主張そのもの」と分ける）
- F-W-P3-205（notes 1501 行付近の `ADR-021` → **ADR-022**。親が置換記録で ADR を切り直し ADR-021 を削除した。notes / `undecided_details` の note に ADR-021 が残っていれば ADR-022 に）
- F-S-P3-203〜205 / F-W-P3-203（記録のみで可・判断を 1 行）

## D. 記録

`implementation-notes.md` に **P3-R3**（R3.0 まとめ / R3.1 対応表 / R3.2 指示と違えた判断 / R3.3 8 ゲート / R3.4 verification_status）。`mutate_p3.py` に A-1 / B-2 / B-3 の変異。`decision-conformance.md` P3 行の追従（§6 の数字）。
最終応答は短く（件数 前→後 / 変異 caught 数 / 新 DP ID / 4 状態）。
