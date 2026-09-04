# ADR-013: rename(state) の参照追随は可視範囲に絞らず全 circle に及ぼす

> ⚠️ **AI 仮決定（ai_provisional）** — auto mode の仮判断であり人間確定ではない（DP-AUTOMODE-01）。PR レビュー後、`/decide` で approved / overridden に確定する。

- **ステータス**: proposed (ai_provisional)
- **日付**: 2026-09-04
- **決定者**: auto-decider
- **関連判断ポイント**: DP-JIN-RENAME-SCOPE-01（aliases: (a) 仕様が正しく、矛盾しているのは ops.py:405 のコメントだけ, 仕様維持・コメント修正）

## コンテキスト

Stage 5 correctness レビュー A-5（confidence 100・挙動は実測済み）が、docs/spec/ops.md §3（可視範囲に絞らないと明記）と実装は一致しているのに、packages/jin-core/src/jin_core/ops.py:405 のコメントだけが『その state が見える circle の rune 内 {key} を追随させる』と書いており両者と矛盾していることを指摘した。あわせて、examples/pipeline/pipeline.jin と同型（複数 circle が同名 state を持つ）で /circles/N/state/M を rename すると無関係に見える circle の rune が静かに書き換わり、rename 後に jin check を通しても診断が 0 件になることを実測した。実装者に『仕様とコードのどちらを直すか』を選ばせると片方を消すだけで矛盾が見かけ上消えてしまうため判断ポイントとして起票された。Phase 5 のエディタは rename をフォームから呼ぶので、この選択でエディタの挙動が変わる。

## 選択肢

| 選択肢 | 採否 |
|---|---|
| 案 (a): 仕様（docs/spec/ops.md §3「可視範囲に絞らない」）が正しい。実装と仕様は変えず、矛盾している packages/jin-core/src/jin_core/ops.py:405 のコメントを実装・仕様に合わせて修正して閉じる | 採用 |
| 案 (b): 仕様が誤りとして rename(state) を可視範囲に絞る（docs/spec/ops.md §3・ops.py・テストを同時変更）。_visible_state_keys が名前の集合しか返さず由来を持たないため指摘された問題を解けず、可視範囲判定が flow 構造に依存するため編集途中のモデルで rename の結果が未定義になる | 不採用 |
| 案 (c): 同名の state 宣言も全 circle で追随させる（同一 session key であることを宣言側にも及ぼす）。A-5 の静かな意味変化を唯一根本的に解けるが、undo の逆オペレーション契約が複数宣言にまたがって壊れ、キーを意図的に分岐させる rename ができなくなり、ops.md §3 と要件書 §6.3 の契約変更になる | 不採用 |

## 決定

(1) 上位要件が可視範囲を要求していない: 要件書 §6.3 は rename を『circle / tool / state。参照を全て追随』とし、§10 #11 は『名前を ID とし、rename は参照追随の意味オペレーション』と決めている。可視範囲という限定はどこにも書かれていない。(2) 決定的な根拠は state 名の実行時の同一性である: state 名は ADK の output_key / session.state のキーそのものである（要件書 l.105『state[](out) → session.state / output_key』、l.294『out: true だけが output_key になる』、docs/spec/adk-mapping.md）。したがって circle が違っても同名の state は同一のセッションキーを指す。examples/pipeline/pipeline.jin の Critic / Rewriter の書き直しループはまさにこの同一性の上に成立している（Rewriter が out: true で書いた draft を、次周の Critic が {draft} で読む）。全 circle への追随は『過剰置換』ではなく実行時の同一性の追跡であり、ops.md §3 の判断は正しい。(3) 案 (b) は指摘された問題を解けないことが実測で分かる: packages/jin-core/src/jin_core/semantic.py の _visible_state_keys は state key の**名前の集合**を返すだけで、どの circle 由来かの情報を持たない（examples/pipeline/pipeline.jin で実測すると Critic / Rewriter はいずれも {'approved', 'draft', 'review'}）。可視範囲に絞る実装を書いても、rune 内の {draft} がどの circle の draft を指すのかを判定できないため、A-5 が挙げた『無関係な circle の rune が書き換わる』事象を防げない。さらに pipeline.jin の構造から導出すると、Drafter の state は sequence 上流として Critic / Rewriter からも可視なので、案 (b) でも同じ rune が書き換わる。(4) 案 (b) は編集途中の壊れたモデルで未定義になる: 可視範囲の判定（docs/spec/model.md §5）は flow の構造に依存するが、エディタは一時的に不正なモデルを編集する。ops が意味解析の結果に依存すると rename の結果が flow の妥当性に左右される。ops.md §3 が挙げている『rename の前後で可視範囲が変わりうる』という根拠と同じ問題である。(5) A-5 が実測した静かな意味変化（rename 後に jin check が 0 件）は残るが、その原因は可視範囲ではなく『rename が指し示した state 宣言だけを改名し、同名の別宣言を残す』ことにある。これは案 (c)（同名の state 宣言まで追随させる）でしか解けず、案 (b) では解けない。案 (c) を今回採らない理由: 逆オペレーションが複数の宣言にまたがるため要件書 §6.3 の『サーバは各オペレーションの逆オペレーションを応答に含める』という undo 契約が壊れる、意図的にキーを分岐させたい rename ができなくなる、ops.md §3 の追随表と §6.3 のオペレーション契約そのものの変更になる。残存リスクは constraints で仕様注記と Phase 5 エディタの可視化に回す。

## 影響

docs/spec/ops.md §3 と ops.py の rename 実装は現状を維持する。修正は ops.py:405 のコメントと ops.md §3 の注記の書き換えのみで、テストと examples に変更はない。Phase 5 のエディタは rename(state) の波及を可視化する責務を負う。A-5 が指摘した静かな意味変化（同名の別宣言が残ることで rune の解決先が移る）は本判断では解消せず、rename 後に jin check を通すという運用と Phase 5 の可視化で受ける。根本解決にあたる案 (c)（同名の state 宣言まで追随）は undo の逆オペレーション契約に触れるため、必要になった時点で別 DP として人間が判断する。
