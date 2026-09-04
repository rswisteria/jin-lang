# ADR-009: DP-JIN-TRACE-POINTER-01 案 B: コード生成時に ADK 識別子 → JSON Pointer の対応表を作り、実行時に引く

> ⚠️ **AI 仮決定（ai_provisional）** — auto mode の仮判断であり人間確定ではない（DP-AUTOMODE-01）。PR レビュー後、`/decide` で approved / overridden に確定する。

- **ステータス**: proposed (ai_provisional)
- **日付**: 2026-09-04
- **決定者**: auto-decider
- **関連判断ポイント**: DP-JIN-TRACE-POINTER-01

## コンテキスト

_（コンテキストは案件側で追記）_

## 選択肢

| 選択肢 | 採否 |
|---|---|
| 案 B: コード生成時に ADK 識別子 → JSON Pointer の対応表を作り、実行時に引く | 採用 |
| 案 A: 実行時に Event の内容から jin-core のモデルを検索して逆引きする | 不採用 |
| 案 C: 生成コード自体に pointer をコメントや属性として埋め込む | 不採用 |

## 決定

design.yaml fired_decision_points[DP-JIN-TRACE-POINTER-01] の推奨案（案 B）をそのまま採用する。jin-adk がコード生成時に「ADK 上の識別子（agent 名 + tool 名 + callback 名）→ JSON Pointer」の対応表を生成物とは別に保持し、実行時に Event.author と tool 名からその表を引いて pointer を埋める。要件との適合根拠: 要件書 §3.4 はトレース行に pointer（レンダラの data-jin と同じ鍵）を要求するが、adk-api-probe.md の実測どおり ADK の Event は pointer を持たない（author / content / actions / branch / invocation_id 等）。案 A（実行時の逆引き）は tools[].name が circle 内一意であって全体一意ではないため同名 tool を一意に引けない。案 C（生成コードへの埋め込み）は「そのまま動く ADK プロジェクト」の純粋さを落とし、ADK 側にコメントを実行時イベントへ伝える機構がないため結局実行時の対応付けが別に要る。対応付けの責務配置は jin-adk の構造と Phase 6 のトレースリプレイに波及するため ADR 化する。

## 影響

_（影響は案件側で追記）_
