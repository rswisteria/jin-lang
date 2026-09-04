# ADR-003: DP-COMMON-09 案 C: パッケージ単位の垂直分割 + tests/contract/ の横断契約テスト

> ✅ **人間確定済み — 承認（approved）** — 2026-09-04 に toyota が /decide で確定（DP-AUTOMODE-01）。

- **ステータス**: accepted
- **日付**: 2026-09-04
- **決定者**: auto-decider
- **関連判断ポイント**: DP-COMMON-09

## コンテキスト

_（コンテキストは案件側で追記）_

## 選択肢

| 選択肢 | 採否 |
|---|---|
| 案 C: パッケージ単位の垂直分割 + tests/contract/ の横断契約テスト | 採用 |
| 案 A: 単一の tests/ に §9 の 11 対象をフラットに並べる | 不採用 |
| 案 B: テストピラミッド（unit / integration / e2e）で切る | 不採用 |

## 決定

design.yaml fired_decision_points[DP-COMMON-09] の推奨案（案 C）を採用する。要件との適合根拠: 要件書 §9 のテストマトリクス 11 行と FR-TEST-001 / NFR-TEST-001（全て uv run pytest、エディタは pnpm test、ネットワーク・API キー不要）を満たしつつ、5 パッケージの垂直分割に沿ってテストを配置することで失敗時の原因箇所が特定しやすくなる。パッケージ横断の契約（依存方向・正準形の往復無損失・pointer→range の一致）はどの単一パッケージにも属さないため tests/contract/ に横断契約テストとして置く。後戻りコストが高い（テスト配置は全 Phase の作業単位を規定する）ため ADR 化する。

## 影響

_（影響は案件側で追記）_
