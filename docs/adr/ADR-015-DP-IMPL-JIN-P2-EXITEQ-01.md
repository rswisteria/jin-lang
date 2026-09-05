# ADR-015: flow.exit の等値比較は文字列を JSON として読み同じ JSON 型で比較する

> ⚠️ **AI 仮決定（ai_provisional）** — auto mode の仮判断であり人間確定ではない（DP-AUTOMODE-01）。PR レビュー後、`/decide` で approved / overridden に確定する。

- **ステータス**: proposed (ai_provisional)
- **日付**: 2026-09-05
- **決定者**: auto-decider
- **関連判断ポイント**: DP-IMPL-JIN-P2-EXITEQ-01

## コンテキスト

google-adk 2.8.0 の LlmAgent.output_key は LLM の応答テキストを str で session.state に入れる（実測 {'approved': 'true'}・decision-conformance.md §2.14）。要件書 §3.3 / §2.2 は flow.exit を { key, equals } の等値比較と定めるが、str と bool / number の突き合わせ規則を規定していない。

## 選択肢

| 選択肢 | 採否 |
|---|---|
| この規則を承認する（文字列は前後の空白を除き、equals が str なら文字列比較、bool / number なら JSON として読み同じ JSON 型で比較。"True" / "1" は true に不一致、"3.0" = 3） | 採用 |
| 大文字小文字を無視する（"True" = true）など緩める | 不採用 |
| 文字列比較のみにする（equals: true は "true" とだけ一致） | 不採用 |

## 決定

HANDOFF Q-JIN-P2-02 の推奨（1 つ目）を採用。根拠: (a) 実測で LlmAgent.output_key は LLM の応答テキストを str で session.state に入れる（decision-conformance.md §2.14・google/adk/agents/llm_agent.py の実測 {'approved': 'true'}）ため、equals: true を型を保ったまま比べる手段は「文字列を JSON として読む」しか無い。(b) 規則は docs/spec/model.md §3.4 の machine-readable 表 flow-exit-equality に明文化され、実装は生成物内 _state_matches（packages/jin-adk/src/jin_adk/templates/agent.py.j2）1 箇所、packages/jin-adk/tests/test_runtime.py::test_state_matches_semantics の 16 ケースが一致・不一致の両方を固定している。(c) 案 2（大文字小文字を無視するなど緩める）は「LLM が何を返せば loop が終わるか」を曖昧にし、.jin の equals が持つ型の意味を失わせる。案 3（文字列比較のみ）は equals の bool / number 型（要件書 §2.2 の例 "equals": true）を実質 string と同じにし、スキーマの 4 型が意味を失う。(d) 要件書に規定が無い意味論を Phase 2 で新たに定めたものであり、Phase 6 のリプレイや将来の比較演算子拡張に効く責務分界なので ADR 化する。

## 影響

docs/spec/model.md §3.4 の flow-exit-equality 表が正典。実装は生成物 agent.py 内の _state_matches 1 箇所（ADR-008 の埋め込みコピー）。"True" / "1" / "yes" は true に一致しないため、.jin の instruction は LLM に JSON リテラル（true / false / 数値）を返させる必要がある。Phase 6 のトレースリプレイでは escalate 行の output.matched がこの規則で決まる。
