# ADR-005: DP-JIN-CANONICAL-01 案 C: jin_core.canonical に独自 writer を書く（Pydantic のフィールド定義順を走査して直列化）

> ✅ **人間確定済み — 承認（approved）** — 2026-09-04 に toyota が /decide で確定（DP-AUTOMODE-01）。

- **ステータス**: accepted
- **日付**: 2026-09-04
- **決定者**: auto-decider
- **関連判断ポイント**: DP-JIN-CANONICAL-01

## コンテキスト

_（コンテキストは案件側で追記）_

## 選択肢

| 選択肢 | 採否 |
|---|---|
| 案 C: jin_core.canonical に独自 writer を書く（Pydantic のフィールド定義順を走査して直列化） | 採用 |
| 案 A: json.dumps の引数調整のみ（indent=2, ensure_ascii=False, sort_keys=False） | 不採用 |
| 案 B: Pydantic の model_dump（exclude_defaults / exclude_none）+ json.dumps 後処理 | 不採用 |

## 決定

design.yaml fired_decision_points[DP-JIN-CANONICAL-01] の推奨案（案 C）をそのまま採用する。jin_core.canonical に独自 writer を書き、Pydantic のフィールド定義順を走査して直列化する。要件との適合根拠: 要件書 §2.3 は「キー順はスキーマ定義順」「省略可能なキーは既定値なら出力しない」「非 ASCII をエスケープしない」「2 スペースインデント」「末尾改行」の 5 規則を要求するが、json.dumps で直接制御できるのは indent と ensure_ascii の 2 つだけで、案 A / 案 B では規則がPydantic の設定と後処理の 2 箇所に分散し §2.3 との対応が読みにくくなる。正準形は NFR-DET-002（fmt(fmt(x)) == fmt(x) の冪等性・往復無損失）と成功条件 5 の土台であり、エディタ保存と jin fmt がバイト一致することの唯一の担保であるため、実装がライブラリの既定挙動に依存する状態は担保として弱い。後から差し替えると全スナップショットと決定性テストに波及するため ADR 化する。

## 影響

_（影響は案件側で追記）_
