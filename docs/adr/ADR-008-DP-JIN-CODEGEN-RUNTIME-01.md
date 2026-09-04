# ADR-008: DP-JIN-CODEGEN-RUNTIME-01 案 A: StateCheckAgent のクラス本体を agent.py に毎回埋め込む（生成物が自己完結）

> ✅ **人間確定済み — 承認（approved）** — 2026-09-04 に toyota が /decide で確定（DP-AUTOMODE-01）。

- **ステータス**: accepted
- **日付**: 2026-09-04
- **決定者**: auto-decider
- **関連判断ポイント**: DP-JIN-CODEGEN-RUNTIME-01

## コンテキスト

_（コンテキストは案件側で追記）_

## 選択肢

| 選択肢 | 採否 |
|---|---|
| 案 A: StateCheckAgent のクラス本体を agent.py に毎回埋め込む（生成物が自己完結） | 採用 |
| 案 B: jin_adk.runtime から import させる（生成物は jin に依存） | 不採用 |
| 案 C: 生成時に別ファイル（_jin_runtime.py）を出力ディレクトリへ一緒に書き出す | 不採用 |

## 決定

design.yaml fired_decision_points[DP-JIN-CODEGEN-RUNTIME-01] の推奨（案 A を主とし FakeLlm のみ案 B 側に置く併用）を採用する。StateCheckAgent のクラス本体は生成物 agent.py に埋め込み、FakeLlm は jin_adk 側に置く。要件との適合根拠: 要件書 §3.1 が「adk run <out>/<root_name> と adk web <out> でそのまま動くこと」を要求するため、§3.3 の flow.exit に対応する StateCheckAgent は生成された agent 木の構成要素として生成物が自己完結している必要がある（案 B は生成プロジェクトの実行に jin のインストールを強い、§3.1 の「そのまま動く」の意味が弱まる）。一方 §3.4 の FakeLlm は jin run --model fake という Jin の CLI が実行時に差し替えるもので生成物の一部ではなく、生成された agent.py に現れる必要がない。本判断により design.yaml architecture.dependency_direction.rules の 8 行目「生成される ADK プロジェクトのjin パッケージへの依存可否は DP-JIN-CODEGEN-RUNTIME-01 で未決」が解消され、「生成物は jin パッケージに依存しない」に確定する。実測 API（BaseAgent._run_async_impl を override し EventActions(escalate=True) を返す）は adk-api-probe.md で確定済み。architect が「生成物の自己完結性と DRY のどちらを優先するかは人間に委ねる」としているため confidence は medium。

## 影響

_（影響は案件側で追記）_
