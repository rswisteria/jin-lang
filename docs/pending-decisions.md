# 未決の判断ポイント（pending-decisions）— jin-lang

warn_and_document（T-002）の出力先。`pending-decisions-generator` が schema から自動生成する（B-42）。

<!-- AUTO-GENERATED START: pending-decisions-generator (B-42) — 直接編集禁止 -->
<!-- 再生成: python3 xtone-shared-plugin/skills/common/pending-decisions-generator/bin/generate.py --plugin-root <path> -->
> **走査範囲**（Issue #281 / DP-DELIVERY-TIMESTAMP-01 改定）: 未決（undecided）と AI 仮決定は各 slug の**最新ランのみ**（過去ランの stale な項目を偽 pending・偽レビュー待ちにしない）。決定済み（decision_record）は同一 slug の**全ランを累積表示**（決定履歴を索引から消さない）。正本は `delivery/<run>/` の成果物と `docs/adr/`。

## 未決リスト（schema 駆動・自動生成）

`undecided[]` を集約。手書き編集は不可（編集は schema 側の `undecided[]` を更新し再生成）。

_（schema 側に未決はありません）_

## AI 仮決定（auto mode・レビュー待ち・自動生成）

auto mode（DP-AUTOMODE-01）の AI 仮判断。人間確定ではない。`/decide DP-XXX ...` で approved / overridden に確定する。

| 起票元ファイル | DP ID | 選択 | confidence | review_status | 決定日 |
|---|---|---|---|---|---|
| 20260904-1445-jin/requirements.json | DP-JIN-DISTRIBUTION-01 | 現 remote(github.com:rswisteria/jin-lang.git)を配布元とし、社内移管は後日行う | medium | pending_human_review | 2026-09-04T15:08:58+09:00 |
| 20260904-1445-jin/requirements.json | DP-JIN-EDITOR-UX-01 | 機能要件(§7.1 / §7.2)だけを満たす最小 UI を AI 仮判断で作り、デザインは後で差し替える | medium | pending_human_review | 2026-09-04T15:08:58+09:00 |
| 20260904-1445-jin/requirements.json | DP-JIN-PHASE-SCOPE-01 | Phase 0〜6(全フェーズ) | medium | pending_human_review | 2026-09-04T15:08:58+09:00 |
| 20260904-1445-jin/design.yaml | DP-COMMON-07 | 案 B: ドキュメント単位で last-good モデル 1 世代のみ保持。SVG はキャッシュしない | high | pending_human_review | 2026-09-04T15:44:00+09:00 |
| 20260904-1445-jin/design.yaml | DP-COMMON-09 | 案 C: パッケージ単位の垂直分割 + tests/contract/ の横断契約テスト | medium | pending_human_review | 2026-09-04T15:44:00+09:00 |
| 20260904-1445-jin/design.yaml | DP-COMMON-11 | 案 B: import-linter で layered contract を宣言 + apps/editor は pnpm 側で別途静的検査 | high | pending_human_review | 2026-09-04T15:44:00+09:00 |
| 20260904-1445-jin/design.yaml | DP-COMMON-14 | 案 B: トレース JSONL（成果物・--trace 指定時のみ）と サーバログ（stderr 固定）を明示的に分離する | high | pending_human_review | 2026-09-04T15:44:00+09:00 |
| 20260904-1445-jin/design.yaml | DP-COMMON-15 | 案 B: 実装 Stage 1 の実測に委ね、実測できなければコメントのみで生成する | high | pending_human_review | 2026-09-04T15:44:00+09:00 |
| 20260904-1445-jin/design.yaml | DP-COMMON-16 | 案 B: circle 名 + 種別 + 要素名 の 3 つ組で選択を保持し、applyOps 応答のたびに新モデル上の pointer を引き直す | high | pending_human_review | 2026-09-04T15:44:00+09:00 |
| 20260904-1445-jin/design.yaml | DP-COMMON-17 | 案 B: JSON-RPC クライアント 1 層 + Jin 固有 4 リクエストの型付きラッパ | medium | pending_human_review | 2026-09-04T15:44:00+09:00 |
| 20260904-1445-jin/design.yaml | DP-COMMON-18 | 案 A: SSR なし単一ページ SPA。モードはページ内切替 | high | pending_human_review | 2026-09-04T15:44:00+09:00 |
| 20260904-1445-jin/design.yaml | DP-COMMON-19 | 案 B: 未接続 / 取得中 / 正常 / ステイル / 表示不能 の 5 状態 | high | pending_human_review | 2026-09-04T15:44:00+09:00 |
| 20260904-1445-jin/design.yaml | DP-COMMON-20 | 案 B: ユニット層（モック）+ スモーク層（実 LSP プロセス）の 2 層 | medium | pending_human_review | 2026-09-04T15:44:00+09:00 |
| 20260904-1445-jin/design.yaml | DP-JIN-CANONICAL-01 | 案 C: jin_core.canonical に独自 writer を書く（Pydantic のフィールド定義順を走査して直列化） | high | pending_human_review | 2026-09-04T15:44:00+09:00 |
| 20260904-1445-jin/design.yaml | DP-JIN-CODEGEN-RUNTIME-01 | 案 A: StateCheckAgent のクラス本体を agent.py に毎回埋め込む（生成物が自己完結） | medium | pending_human_review | 2026-09-04T15:44:00+09:00 |
| 20260904-1445-jin/design.yaml | DP-JIN-EDITOR-PROTOCOL-01 | 案 C: 独自リクエスト（jin/open と jin/save 仮称）を 2 本追加し、ws モードのエディタだけが使う | medium | pending_human_review | 2026-09-04T15:44:00+09:00 |
| 20260904-1445-jin/design.yaml | DP-JIN-POINTER-RANGE-01 | 案 B: Lark の木を 1 回走査して pointer→range の完全表を作り、Pydantic の loc を pointer に変換して引く | high | pending_human_review | 2026-09-04T15:44:00+09:00 |
| 20260904-1445-jin/design.yaml | DP-JIN-SEMANTIC-GAPS-01 | 案 A: 新しい JIN コードを 2 つ追加し、jin-core の意味検査で検出する | medium | pending_human_review | 2026-09-04T15:44:00+09:00 |
| 20260904-1445-jin/design.yaml | DP-JIN-SVG-DETERMINISM-01 | 案 B: 出力直前に固定桁数へ丸める関数を 1 本通す規約にする（桁数は未決） | medium | pending_human_review | 2026-09-04T15:44:00+09:00 |
| 20260904-1445-jin/design.yaml | DP-JIN-TRACE-POINTER-01 | 案 B: コード生成時に ADK 識別子 → JSON Pointer の対応表を作り、実行時に引く | medium | pending_human_review | 2026-09-04T15:44:00+09:00 |

## 決定済み（schema 駆動・自動生成）

`decision_record[]` を集約（同一 slug の**全ラン累積**・過去ランの決定履歴を含む・Issue #281）。手書き編集は不可（決定追加は `/decide` 経由で schema を更新し再生成）。

| 起票元ファイル | DP ID | 決定者 | 決定日 | rationale | adr_ref |
|---|---|---|---|---|---|
| 20260904-1445-jin/requirements.json | DP-JIN-ADK-VERSION-01 | 要件書 §1.1（人間確定）+ 親セッション実測 delivery/20260904-1445-jin/adk-api-probe.md | 2026-09-04 | 要件書 §1.1 が「google-adk 2.x 系（メジャーを固定）」と人間確定済みで、未確定だったのは 2.x が実在するかの事実確認のみだった。親セッションが uv venv 隔離環境への実インストールと inspect / Pydantic model_fields 走査で 2.8.0 の実在と API 形状を確認したため、人間判断の余地は残らない。要件定義フェーズでの起票候補から d… |  |
| 20260904-1445-jin/requirements.json | DP-JIN-ADKYAML-01 | 要件書 §10 #7(人間確定済み) | 2026-09-04 | callback を表現できない |  |
| 20260904-1445-jin/requirements.json | DP-JIN-DELIVERYMODE-01 | 親エージェント(team-lead)による確定 | 2026-09-04 | リポジトリには jin-requirements.md 1 ファイルとコミット 1 本しか無く既存コードベースが存在しない |  |
| 20260904-1445-jin/requirements.json | DP-JIN-DIST-01 | 要件書 §10 #8(人間確定済み) | 2026-09-04 | 社内配布の既存導線に乗せる |  |
| 20260904-1445-jin/requirements.json | DP-JIN-EDITORSTATE-01 | 要件書 §10 #10(人間確定済み) | 2026-09-04 | エディタが独自モデル状態を持たないことで往復無損失を担保する |  |
| 20260904-1445-jin/requirements.json | DP-JIN-IDENTITY-01 | 要件書 §10 #11(人間確定済み) | 2026-09-04 | data-jin 属性・診断・trace pointer の鍵を JSON Pointer に統一する |  |
| 20260904-1445-jin/requirements.json | DP-JIN-LOOPEXIT-01 | 要件書 §10 #5(人間確定済み) | 2026-09-04 | 決定性と静的検証可能性を優先 |  |
| 20260904-1445-jin/requirements.json | DP-JIN-MODELREF-01 | 要件書 §10 #4(人間確定済み) | 2026-09-04 | v1 のスコープを絞る |  |
| 20260904-1445-jin/requirements.json | DP-JIN-MULTIFILE-01 | 要件書 §10 #6(人間確定済み) | 2026-09-04 | 名前解決とスコープの複雑化を v1 では避ける |  |
| 20260904-1445-jin/requirements.json | DP-JIN-NAMING-01 | 要件書 §10 #1(人間確定済み) | 2026-09-04 | 要件書 v0.2 §10 決定事項で確定。Claude Code の LSP ルーティングが拡張子単位のため .json を奪わない |  |
| 20260904-1445-jin/requirements.json | DP-JIN-RENDERER-01 | 要件書 §10 #9 / §0 設計前提(人間確定済み) | 2026-09-04 | 描画のズレをゼロにするため |  |
| 20260904-1445-jin/requirements.json | DP-JIN-STACK-01 | 要件書 §1.1 技術選定表(人間確定済み) | 2026-09-04 | 要件書に選定理由が併記されている確定済みの技術スタック指定。design フェーズで比較をやり直さない |  |
| 20260904-1445-jin/requirements.json | DP-JIN-TEXTREPR-01 | 要件書 §10 #2(人間確定済み) | 2026-09-04 | LLM が最も安定して書ける。既存 JSON ツールが使える。エディタとの往復が無損失(コメント・整形の保存問題がない) |  |
| 20260904-1445-jin/requirements.json | DP-JIN-TOOLDEF-01 | 要件書 §10 #3(人間確定済み) | 2026-09-04 | 汎用計算は非目標。ツール実装は Python 側に置き Jin からは参照するだけ |  |

<!-- AUTO-GENERATED END: pending-decisions-generator -->
