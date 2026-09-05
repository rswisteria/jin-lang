# AI 判断台帳（auto mode / DP-AUTOMODE-01）

**人間に確認してほしい判断: 13 件**（prohibition 付き・confidence が high 以外）／レビュー待ち 5 件・全 28 件。
承認・上書きは `/decide DP-XXX "<選択>" "<理由>" --decided_by "<氏名>"`（同一選択 = approved / 別選択 = overridden）。

| 要確認 | DP ID | 選択 | rationale | confidence | review_status | model | 起票元 |
|---|---|---|---|---|---|---|---|
| ⚠️ 要人間確認 | DP-IMPL-JIN-P2-SYSPATH-01 | cwd を生成モジュールの import の間だけ sys.path に足し、import が終わったら必ず外す（jin_adk.runtime.load_generated / run_model_async に extra_sys_p… | security レビュー修正ラウンド 1 の F-S-P2-101（delivery/20260904-1445-jin/code-review-raw/security-p2-round1.md・Medium / confidence… | medium | pending_human_review | claude-fable-5-1 | implementation-plan.json |
| ⚠️ 要人間確認 | DP-IMPL-JIN-P2-TRACEKIND-01 | 承認する（final = 実行全体の最後の行が model のときだけその行を付け替える / escalate = StateCheckAgent の判定イベントを一致しなかった回も含む + actions.escalate / part… | HANDOFF Q-JIN-P2-05 の推奨（1 つ目）を採用。根拠: (a) 要件書 §3.4 は kind の 5 種を列挙するだけで判定規則を書いていない。決めた規則は docs/spec/adk-mapping.md §2.4… | medium | pending_human_review | claude-fable-5-1 | implementation-plan.json |
| ⚠️ 要人間確認 | DP-IMPL-JIN-P2-ADKDEPRECATION-01 | google-adk 2.8.0 固定（TARGET_ADK_VERSION）のまま進め、Workflow への移行は別 Issue で扱う | HANDOFF Q-JIN-P2-03 の推奨（1 つ目）を採用。根拠: (a) ADK 自身の deprecation 文言が「Workflow cannot yet be used as an LlmAgent sub-agent」と… | high | pending_human_review | claude-fable-5-1 | implementation-plan.json |
| ⚠️ 要人間確認 | DP-IMPL-JIN-P2-STATESEED-01 | 現状のまま（jin run だけが宣言済み state を None で seed する。adk run 単体で KeyError になることを README / adk-mapping.md §6 に明記済み）を承認する | HANDOFF Q-JIN-P2-01 の推奨（1 つ目）を採用。根拠: (a) google-adk 2.8.0 は instruction の {key} が session.state に無いと KeyError を投げる（goog… | high | pending_human_review | claude-fable-5-1 | implementation-plan.json |
| ⚠️ 要人間確認 | DP-COMMON-15 | 案 B: 実装 Stage 1 の実測に委ね、実測できなければコメントのみで生成する | AI 仮判断（confidence: high）を承認。 |  | approved |  | design.yaml |
| ⚠️ 要人間確認 | DP-COMMON-17 | 案 B: JSON-RPC クライアント 1 層 + Jin 固有 4 リクエストの型付きラッパ | AI 仮判断（confidence: medium）を承認。 |  | approved |  | design.yaml |
| ⚠️ 要人間確認 | DP-JIN-DIAGCODE-NUMBERING-01 | 選択肢 1: JIN012（循環参照）/ JIN013（多重親）を承認し、要件書 §2.4 の表に 2 行追加する | AI 仮判断（confidence: medium）を承認。 |  | approved |  | implementation-plan.json |
| ⚠️ 要人間確認 | DP-JIN-DISTRIBUTION-01 | 現 remote(github.com:rswisteria/jin-lang.git)を配布元とし、社内移管は後日行う | AI 仮判断（confidence: medium）を承認。 |  | approved |  | requirements.json |
| ⚠️ 要人間確認 | DP-JIN-EDITOR-PROTOCOL-01 | 案 C: 独自リクエスト（jin/open と jin/save 仮称）を 2 本追加し、ws モードのエディタだけが使う | AI 仮判断（confidence: medium）を承認。 |  | approved |  | design.yaml |
| ⚠️ 要人間確認 | DP-JIN-EDITOR-UX-01 | 機能要件(§7.1 / §7.2)だけを満たす最小 UI を AI 仮判断で作り、デザインは後で差し替える | AI 仮判断（confidence: medium）を承認。 |  | approved |  | requirements.json |
| ⚠️ 要人間確認 | DP-JIN-JIN050-LOOP-SCOPE-01 | 現仕様を維持する: docs/spec/model.md §5 の loop 行「祖先が loop のとき、すべての兄弟枝の部分木を含める」を変えず、新しい診断コードも警告も追加しない（1 周目に未定義でありうることは仕様上の既知の限界と… | AI 仮判断（confidence: medium）を承認。 |  | approved |  | implementation-plan.json |
| ⚠️ 要人間確認 | DP-JIN-SEMANTIC-GAPS-01 | 案 A: 新しい JIN コードを 2 つ追加し、jin-core の意味検査で検出する | AI 仮判断（confidence: medium）を承認。 |  | approved |  | design.yaml |
| ⚠️ 要人間確認 | DP-JIN-SVG-DETERMINISM-01 | 案 B: 出力直前に固定桁数へ丸める関数を 1 本通す規約にする（桁数は未決） | AI 仮判断（confidence: medium）を承認。 |  | approved |  | design.yaml |
|  | DP-IMPL-JIN-P2-EXITEQ-01 | この規則を承認する（文字列は前後の空白を除き、equals が str なら文字列比較、bool / number なら JSON として読み同じ JSON 型で比較。"True" / "1" は true に不一致、"3.0" = 3） | HANDOFF Q-JIN-P2-02 の推奨（1 つ目）を採用。根拠: (a) 実測で LlmAgent.output_key は LLM の応答テキストを str で session.state に入れる（decision-confo… | high | pending_human_review | claude-fable-5-1 | implementation-plan.json |
|  | DP-COMMON-07 | 案 B: ドキュメント単位で last-good モデル 1 世代のみ保持。SVG はキャッシュしない | AI 仮判断（confidence: high）を承認。 |  | approved |  | design.yaml |
|  | DP-COMMON-09 | 案 C: パッケージ単位の垂直分割 + tests/contract/ の横断契約テスト | AI 仮判断（confidence: medium）を承認。 |  | approved |  | design.yaml |
|  | DP-COMMON-11 | 案 B: import-linter で layered contract を宣言 + apps/editor は pnpm 側で別途静的検査 | AI 仮判断（confidence: high）を承認。 |  | approved |  | design.yaml |
|  | DP-COMMON-14 | 案 B: トレース JSONL（成果物・--trace 指定時のみ）と サーバログ（stderr 固定）を明示的に分離する | AI 仮判断（confidence: high）を承認。 |  | approved |  | design.yaml |
|  | DP-COMMON-16 | 案 B: circle 名 + 種別 + 要素名 の 3 つ組で選択を保持し、applyOps 応答のたびに新モデル上の pointer を引き直す | AI 仮判断（confidence: high）を承認。 |  | approved |  | design.yaml |
|  | DP-COMMON-18 | 案 A: SSR なし単一ページ SPA。モードはページ内切替 | AI 仮判断（confidence: high）を承認。 |  | approved |  | design.yaml |
|  | DP-COMMON-19 | 案 B: 未接続 / 取得中 / 正常 / ステイル / 表示不能 の 5 状態 | AI 仮判断（confidence: high）を承認。 |  | approved |  | design.yaml |
|  | DP-COMMON-20 | 案 B: ユニット層（モック）+ スモーク層（実 LSP プロセス）の 2 層 | AI 仮判断（confidence: medium）を承認。 |  | approved |  | design.yaml |
|  | DP-JIN-CANONICAL-01 | 案 C: jin_core.canonical に独自 writer を書く（Pydantic のフィールド定義順を走査して直列化） | AI 仮判断（confidence: high）を承認。 |  | approved |  | design.yaml |
|  | DP-JIN-CODEGEN-RUNTIME-01 | 案 A: StateCheckAgent のクラス本体を agent.py に毎回埋め込む（生成物が自己完結） | AI 仮判断（confidence: medium）を承認。 |  | approved |  | design.yaml |
|  | DP-JIN-PHASE-SCOPE-01 | Phase 0〜6(全フェーズ) | AI 仮判断（confidence: medium）を承認。 |  | approved |  | requirements.json |
|  | DP-JIN-POINTER-RANGE-01 | 案 B: Lark の木を 1 回走査して pointer→range の完全表を作り、Pydantic の loc を pointer に変換して引く | AI 仮判断（confidence: high）を承認。 |  | approved |  | design.yaml |
|  | DP-JIN-RENAME-SCOPE-01 | 案 (a): 仕様（docs/spec/ops.md §3「可視範囲に絞らない」）が正しい。実装と仕様は変えず、矛盾している packages/jin-core/src/jin_core/ops.py:405 のコメントを実装・仕様に合わ… | AI 仮判断（confidence: high）を承認。 |  | approved |  | implementation-plan.json |
|  | DP-JIN-TRACE-POINTER-01 | 案 B: コード生成時に ADK 識別子 → JSON Pointer の対応表を作り、実行時に引く | AI 仮判断（confidence: medium）を承認。 |  | approved |  | design.yaml |
