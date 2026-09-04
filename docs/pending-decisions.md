# 未決の判断ポイント（pending-decisions）— jin-lang

warn_and_document（T-002）の出力先。`pending-decisions-generator` が schema から自動生成する（B-42）。

<!-- AUTO-GENERATED START: pending-decisions-generator (B-42) — 直接編集禁止 -->
<!-- 再生成: python3 xtone-shared-plugin/skills/common/pending-decisions-generator/bin/generate.py --plugin-root <path> -->
> **走査範囲**（Issue #281 / DP-DELIVERY-TIMESTAMP-01 改定）: 未決（undecided）と AI 仮決定は各 slug の**最新ランのみ**（過去ランの stale な項目を偽 pending・偽レビュー待ちにしない）。決定済み（decision_record）は同一 slug の**全ランを累積表示**（決定履歴を索引から消さない）。正本は `delivery/<run>/` の成果物と `docs/adr/`。

## 未決リスト（schema 駆動・自動生成）

`undecided[]` を集約。手書き編集は不可（編集は schema 側の `undecided[]` を更新し再生成）。

| 起票元ファイル | DP ID |
|---|---|
| 20260904-1445-jin/implementation-plan.json | DP-JIN-RESOLVE-ISOLATION-01 |
| 20260904-1445-jin/implementation-plan.json | DP-REVIEW-JIN-001 |
| 20260904-1445-jin/implementation-plan.json | DP-REVIEW-JIN-002 |
| 20260904-1445-jin/implementation-plan.json | DP-REVIEW-JIN-003 |
| 20260904-1445-jin/implementation-plan.json | DP-REVIEW-JIN-004 |
| 20260904-1445-jin/implementation-plan.json | DP-REVIEW-JIN-005 |
| 20260904-1445-jin/implementation-plan.json | DP-REVIEW-JIN-006 |
| 20260904-1445-jin/implementation-plan.json | DP-REVIEW-JIN-007 |
| 20260904-1445-jin/implementation-plan.json | DP-REVIEW-JIN-008 |

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
| 20260904-1445-jin/implementation-plan.json | DP-JIN-DIAGCODE-NUMBERING-01 | 選択肢 1: JIN012（循環参照）/ JIN013（多重親）を承認し、要件書 §2.4 の表に 2 行追加する | medium | pending_human_review | 2026-09-04T17:13:17+09:00 |
| 20260904-1445-jin/implementation-plan.json | DP-JIN-JIN050-LOOP-SCOPE-01 | 現仕様を維持する: docs/spec/model.md §5 の loop 行「祖先が loop のとき、すべての兄弟枝の部分木を含める」を変えず、新しい診… | medium | pending_human_review | 2026-09-04T17:13:17+09:00 |
| 20260904-1445-jin/implementation-plan.json | DP-JIN-RENAME-SCOPE-01 | 案 (a): 仕様（docs/spec/ops.md §3「可視範囲に絞らない」）が正しい。実装と仕様は変えず、矛盾している packages/jin-cor… | high | pending_human_review | 2026-09-04T17:13:17+09:00 |

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
| 20260904-1445-jin/implementation-plan.json | DP-IMPL-JIN-DIAGCODE-01 | impl-p01 (implementer) | 2026-09-04T07:10:00+00:00 | 要件書 §2.4 のコードは 10 の位で関心事がブロック化されている（00x 入力の妥当性 / 01x 名前と参照 / 02x circle 単体の形 / 03x flow / 04x 外部解決 / 05x rune / 06x root / 07x await）。追加する 2 件はどちらも circle 名で張られた参照グラフ全体の整合性であり 01x の関心事に一致する。03x に採らなか… | docs/adr/ADR-007-DP-JIN-SEMANTIC-GAPS-01.md |
| 20260904-1445-jin/implementation-plan.json | DP-IMPL-JIN-DIAGPREC-01 | impl-p01 (implementer) | 2026-09-04T07:10:00+00:00 | 要件書 §2.4 の JIN011 行は『未解決の参照（summon / delegate / steps / await / {key}）』と 5 種を挙げるが、steps / await / {key} には同じ表に JIN031 / JIN070 / JIN050 という専用コードが存在する。要件書 §9 の『fixture は対応コードを 1 つだけ出す』を成立させるには優先順位を決める… |  |
| 20260904-1445-jin/implementation-plan.json | DP-IMPL-JIN-POSBASE-01 | impl-p01 (implementer) | 2026-09-04T07:10:00+00:00 | (1) 要件書 §5 のフィールド名は col であり LSP の Position は character（lsp-api-probe.md §1 実測）。名前を変えている以上 LSP 座標をそのまま載せる意図ではないと読むのが素直。(2) lark がネイティブに 1 始まり（本ラウンドで再実測: '{"a": "xy"}' の "a" が L1C2-L1C5）。パーサの値をそのまま使えばオ… |  |
| 20260904-1445-jin/implementation-plan.json | DP-IMPL-JIN-TDD-P0-01 | impl-p01 (implementer) | 2026-09-04T06:58:00+00:00 | Phase 0 の成果物は仕様書そのものであり、突合テストは『既に存在する上位要件書と、これから書く仕様書が一致すること』を確かめる検査である。仕様書を書く前にテストを書いても、落ちる理由が『ファイルが無い』だけで設計上の情報を与えない。auto mode なので decided_by_kind = ai_agent の ai_provisional 相当として記録する（AI が実装都合で黙って… |  |
| 20260904-1445-jin/implementation-plan.json | DP-IMPL-JIN-TESTFIXTURE-01 | impl-p01 (implementer) | 2026-09-04T07:10:00+00:00 | 共有 fixture が要るのは tests/spec/ と tests/contract/ だけで、どちらもリポジトリ直下 tests/ の下にある。各パッケージのテストは自分のパッケージしか見ないので共有を必要としない。プラグイン自作は依存が増え追跡しにくい。pyproject.toml の testpaths に 3 ディレクトリを並べれば uv run pytest 1 発で全部通る（F… |  |
| 20260904-1445-jin/implementation-plan.json | DP-IMPL-JIN-TOOLNAME-01 | impl-p01 (implementer) | 2026-09-04T07:10:00+00:00 | name は circle 内一意の ID として boundary.await[]・意味オペレーション moveTool / rename・JSON Pointer の安定性に使われる（要件書 §2.2『名前が ID』/ §6.3）。builtin だけ name を持たないと await に指定できず moveTool の対象も指せない。要件書 §2.2 の builtin の例は説明のため… |  |
| 20260904-1445-jin/implementation-plan.json | DP-IMPL-JIN-UPSTREAM-01 | impl-p01 (implementer) | 2026-09-04T07:10:00+00:00 | 要件書 §2.4 は『自 circle または flow 上流 circle の state』としか書かず実装には厳密な定義が要る。ADK の実行意味論に合わせ「その circle が動く前に確実に動きうるもの」を上流とした。loop で全兄弟を含めるのは 2 周目以降どの兄弟も先に実行されうるため。parallel を含めないのは実行順序の保証が無いため。妥当性の一次証拠は要件書 §2.2 の… |  |

<!-- AUTO-GENERATED END: pending-decisions-generator -->
