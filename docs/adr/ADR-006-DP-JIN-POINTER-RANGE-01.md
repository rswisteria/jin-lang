# ADR-006: DP-JIN-POINTER-RANGE-01 案 B: Lark の木を 1 回走査して pointer→range の完全表を作り、Pydantic の loc を pointer に変換して引く

> ✅ **人間確定済み — 承認（approved）** — 2026-09-04 に toyota が /decide で確定（DP-AUTOMODE-01）。

- **ステータス**: accepted
- **日付**: 2026-09-04
- **決定者**: auto-decider
- **関連判断ポイント**: DP-JIN-POINTER-RANGE-01

## コンテキスト

_（コンテキストは案件側で追記）_

## 選択肢

| 選択肢 | 採否 |
|---|---|
| 案 B: Lark の木を 1 回走査して pointer→range の完全表を作り、Pydantic の loc を pointer に変換して引く | 採用 |
| 案 A: Lark の木にモデルを重ねず、行・列は構文エラー（JIN001）のみに付ける | 不採用 |
| 案 C: Lark のカスタム Transformer で Pydantic モデルを直接構築し、位置をモデルに埋め込む | 不採用 |

## 決定

design.yaml fired_decision_points[DP-JIN-POINTER-RANGE-01] の推奨案（案 B + JIN002 検出器の Pydantic 一本化）をそのまま採用する。Lark の木を 1 回走査して JSON Pointer → range の完全な対応表を作り、Pydantic の ValidationError.loc を JSON Pointer 文字列に変換してその表を引く。要件との適合根拠: 要件書 §5 の jin dump、§2.5 の data-jin 契約、§6.3 の独自リクエスト jin/model が共通して pointer→range 対応表を要求する。案 A は JIN002 に range が付かず §5 の診断 JSON 形式（range 必須）を満たせない要件違反。案 C（Lark の Transformer でモデルへ位置を埋め込む）は NFR-SSOT-001 の「モデル定義が唯一の真実」を濁し、往復無損失テストの等価比較に位置が影響する。検出器を Pydantic に一本化するのは、jsonschema ライブラリを併用すると同じ違反に 2 種類のメッセージ形式が生まれNFR-LLM-001（hint は具体値）が破れるため。位置表現の接続方式は全診断・エディタ・レンダラに波及するため ADR 化する。

## 影響

_（影響は案件側で追記）_
