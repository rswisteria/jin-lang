# ADR-004: DP-COMMON-11 案 B: import-linter で layered contract を宣言 + apps/editor は pnpm 側で別途静的検査

> ⚠️ **AI 仮決定（ai_provisional）** — auto mode の仮判断であり人間確定ではない（DP-AUTOMODE-01）。PR レビュー後、`/decide` で approved / overridden に確定する。

- **ステータス**: proposed (ai_provisional)
- **日付**: 2026-09-04
- **決定者**: auto-decider
- **関連判断ポイント**: DP-COMMON-11

## コンテキスト

_（コンテキストは案件側で追記）_

## 選択肢

| 選択肢 | 採否 |
|---|---|
| 案 B: import-linter で layered contract を宣言 + apps/editor は pnpm 側で別途静的検査 | 採用 |
| 案 A: uv workspace の依存宣言（pyproject.toml の dependencies）だけで担保する | 不採用 |
| 案 C: 自前の AST 走査テスト（tests/contract/test_dependencies.py）を書く | 不採用 |

## 決定

design.yaml fired_decision_points[DP-COMMON-11] の推奨案（案 B）をそのまま採用する。architect の根拠は「import-linter は層の宣言が設定ファイル 1 本で済み、間接依存も追う。TypeScript 側は対象外なのでそこだけ別の仕掛けが要る点を明示的に受け入れる」。要件との適合根拠: FR-ARCH-002 / NFR-DEP-001 が依存の一方向性を要求し、要件書 §1.2 の「jin-core は ADK に依存しない」「apps/editor は LSP にしか依存しない」は本案件の設計思想そのもの。案 A（pyproject.toml の依存宣言のみ）は同一環境にインストールされていれば import が通るため実効性が弱く、案 C（自前 AST 走査）は間接依存の追跡が不完全になりやすい。依存担保の方式は後から変えると全パッケージの CI 構成に波及するため ADR 化する。

## 影響

_（影響は案件側で追記）_
