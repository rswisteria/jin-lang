# ADR-017: トレース kind の final / escalate の判定規則

> ⚠️ **AI 仮決定（ai_provisional）** — auto mode の仮判断であり人間確定ではない（DP-AUTOMODE-01）。PR レビュー後、`/decide` で approved / overridden に確定する。

- **ステータス**: proposed (ai_provisional)
- **日付**: 2026-09-05
- **決定者**: auto-decider
- **関連判断ポイント**: DP-IMPL-JIN-P2-TRACEKIND-01

## コンテキスト

要件書 §3.4 はトレース kind として model / tool / transfer / escalate / final の 5 種を列挙するだけで判定規則を書いていない。ADK の Event には kind に相当する属性が無く（Event.is_final_response は参加 agent ごとに True になりうる・event.py:288）、Jin 側で導出する必要がある。

## 選択肢

| 選択肢 | 採否 |
|---|---|
| 承認する（final = 実行全体の最後の行が model のときだけその行を付け替える / escalate = StateCheckAgent の判定イベントを一致しなかった回も含む + actions.escalate / partial は行にしない） | 採用 |
| final を root agent の is_final_response に限定する | 不採用 |
| 一致しなかった判定は escalate ではなく別扱いにする（enum 追加＝要件書変更） | 不採用 |

## 決定

HANDOFF Q-JIN-P2-05 の推奨（1 つ目）を採用。根拠: (a) 要件書 §3.4 は kind の 5 種を列挙するだけで判定規則を書いていない。決めた規則は docs/spec/adk-mapping.md §2.4 の machine-readable 表 trace-kinds に明文化され、tests/spec の test_trace_kinds_table_matches_the_implementation が表と実装（jin_adk.trace.classify / TraceWriter の 1 行遅延）の集合一致を固定している（decision-conformance.md §2.21）。(b) 案 2（root agent の is_final_response に限定）は成立しない: ADK の Event.is_final_response（google/adk/events/event.py:288）の docstring 自身が「複数 agent が参加する invocation では参加 agent ごとに True になりうる」と言っており root 限定の根拠にならず、examples/pipeline の root は SequentialAgent で model 行を出さないため final が一度も付かない。(c) 案 3（不一致の判定を別 kind にする）は要件書 §3.4 の enum 追加＝要件書変更であり、人間判断が要る性質なので AI 仮判断では選ばない。escalate 行の output.matched で一致・不一致を区別できるので Phase 6 のリプレイで情報は失われない。(d) partial を行にしないのは確定イベントと二重になるため（adk-mapping.md §2.4）。kind の意味論は Phase 6 のトレースリプレイ表示に波及する責務分界なので ADR 化する。ただし「final が無い実行がある」見え方は人間の期待と違いうるため confidence は medium。

## 影響

docs/spec/adk-mapping.md §2.4 の trace-kinds 表が正典。final は TraceWriter が 1 行遅延で最後の model 行を付け替える。escalate は StateCheckAgent の判定イベント（一致・不一致とも・output.matched で区別）と actions.escalate。partial は行にしない。Phase 6 のトレースリプレイは final 行が無い実行を扱える設計にする。
