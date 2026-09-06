# 未決の判断ポイント（pending-decisions）— jin-lang

warn_and_document（T-002）の出力先。`pending-decisions-generator` が schema から自動生成する（B-42）。

<!-- AUTO-GENERATED START: pending-decisions-generator (B-42) — 直接編集禁止 -->
<!-- 再生成: python3 xtone-shared-plugin/skills/common/pending-decisions-generator/bin/generate.py --plugin-root <path> -->
> **走査範囲**（Issue #281 / DP-DELIVERY-TIMESTAMP-01 改定）: 未決（undecided）と AI 仮決定は各 slug の**最新ランのみ**（過去ランの stale な項目を偽 pending・偽レビュー待ちにしない）。決定済み（decision_record）は同一 slug の**全ランを累積表示**（決定履歴を索引から消さない）。正本は `delivery/<run>/` の成果物と `docs/adr/`。

## 未決リスト（schema 駆動・自動生成）

`undecided[]` を集約。手書き編集は不可（編集は schema 側の `undecided[]` を更新し再生成）。

| 起票元ファイル | DP ID |
|---|---|
| 20260904-1445-jin/implementation-plan.json | DP-REVIEW-JIN-001 |
| 20260904-1445-jin/implementation-plan.json | DP-REVIEW-JIN-002 |
| 20260904-1445-jin/implementation-plan.json | DP-REVIEW-JIN-003 |
| 20260904-1445-jin/implementation-plan.json | DP-REVIEW-JIN-004 |
| 20260904-1445-jin/implementation-plan.json | DP-REVIEW-JIN-005 |
| 20260904-1445-jin/implementation-plan.json | DP-REVIEW-JIN-006 |
| 20260904-1445-jin/implementation-plan.json | DP-REVIEW-JIN-007 |
| 20260904-1445-jin/implementation-plan.json | DP-REVIEW-JIN-P2-001 |
| 20260904-1445-jin/implementation-plan.json | DP-REVIEW-JIN-P2-002 |
| 20260904-1445-jin/implementation-plan.json | DP-REVIEW-JIN-P3-001 |

## AI 仮決定（auto mode・レビュー待ち・自動生成）

auto mode（DP-AUTOMODE-01）の AI 仮判断。人間確定ではない。`/decide DP-XXX ...` で approved / overridden に確定する。

| 起票元ファイル | DP ID | 選択 | confidence | review_status | 決定日 |
|---|---|---|---|---|---|
| 20260904-1445-jin/implementation-plan.json | DP-IMPL-JIN-P2-ADKDEPRECATION-01 | google-adk 2.8.0 固定（TARGET_ADK_VERSION）のまま進め、Workflow への移行は別 Issue で扱う | high | pending_human_review | 2026-09-05T19:56:01+09:00 |
| 20260904-1445-jin/implementation-plan.json | DP-IMPL-JIN-P2-EXITEQ-01 | この規則を承認する（文字列は前後の空白を除き、equals が str なら文字列比較、bool / number なら JSON として読み同じ JSON… | high | pending_human_review | 2026-09-05T19:56:01+09:00 |
| 20260904-1445-jin/implementation-plan.json | DP-IMPL-JIN-P2-STATESEED-01 | 現状のまま（jin run だけが宣言済み state を None で seed する。adk run 単体で KeyError になることを README… | high | pending_human_review | 2026-09-05T19:56:01+09:00 |
| 20260904-1445-jin/implementation-plan.json | DP-IMPL-JIN-P2-SYSPATH-01 | cwd を生成モジュールの import の間だけ sys.path に足し、import が終わったら必ず外す（jin_adk.runtime.load_g… | medium | pending_human_review | 2026-09-05T21:25:37+09:00 |
| 20260904-1445-jin/implementation-plan.json | DP-IMPL-JIN-P2-TRACEKIND-01 | 承認する（final = 実行全体の最後の行が model のときだけその行を付け替える / escalate = StateCheckAgent の判定イベ… | medium | pending_human_review | 2026-09-05T19:56:01+09:00 |
| 20260904-1445-jin/implementation-plan.json | DP-IMPL-JIN-P3-ACCENT-COLOR-01 | 選択肢 1: trace overlay の強調 1 色を #cc0000（朱）のまま承認する | medium | pending_human_review | 2026-09-06T10:37:47+09:00 |
| 20260904-1445-jin/implementation-plan.json | DP-IMPL-JIN-P3-LOOP-STAR-ORDER-01 | 選択肢 (a): loop の節 flow.steps[j] を角位置 (j*k) mod n に置き、辺は j → (j+1) mod n（訪問順の隣）を矢… | high | pending_human_review | 2026-09-06T13:05:05+09:00 |
| 20260904-1445-jin/implementation-plan.json | DP-IMPL-JIN-P3-OVERLAY-REFERENT-01 | 選択肢 1: trace overlay の強調規則として「pointer を末尾から 1 セグメントずつ削る祖先一致」+「参照要素の data-jin-re… | high | pending_human_review | 2026-09-06T10:37:47+09:00 |
| 20260904-1445-jin/implementation-plan.json | DP-IMPL-JIN-P3-RENDER-ON-ERROR-01 | 選択肢 1: error 診断があるファイルは jin render も既定で拒む（exit 1）。図を出すためのオプションは Phase 3 では足さない | high | pending_human_review | 2026-09-06T10:37:47+09:00 |
| 20260904-1445-jin/implementation-plan.json | DP-IMPL-JIN-P3-ROUNDING-01 | 選択肢 1: SVG 座標の丸めを 3 桁固定小数（format(x, ".3f")）のまま承認する | high | pending_human_review | 2026-09-06T12:04:02+09:00 |
| 20260904-1445-jin/implementation-plan.json | DP-IMPL-JIN-P3-SVG-ROOT-CONTRACT-01 | 選択肢 1: svg 要素自身と defs 配下を data-jin 契約の対象外とする解釈を承認する | high | pending_human_review | 2026-09-06T10:37:47+09:00 |

## 決定済み（schema 駆動・自動生成）

`decision_record[]` を集約（同一 slug の**全ラン累積**・過去ランの決定履歴を含む・Issue #281）。手書き編集は不可（決定追加は `/decide` 経由で schema を更新し再生成）。

| 起票元ファイル | DP ID | 決定者 | 決定日 | rationale | adr_ref |
|---|---|---|---|---|---|
| 20260904-1445-jin/requirements.json | DP-JIN-ADK-VERSION-01 | 要件書 §1.1（人間確定）+ 親セッション実測 delivery/20260904-1445-jin/adk-api-probe.md | 2026-09-04 | 要件書 §1.1 が「google-adk 2.x 系（メジャーを固定）」と人間確定済みで、未確定だったのは 2.x が実在するかの事実確認のみだった。親セッションが uv venv 隔離環境への実インストールと inspect / Pydantic model_fields 走査で 2.8.0 の実在と API 形状を確認したため、人間判断の余地は残らない。要件定義フェーズでの起票候補から d… |  |
| 20260904-1445-jin/requirements.json | DP-JIN-ADKYAML-01 | 要件書 §10 #7(人間確定済み) | 2026-09-04 | callback を表現できない |  |
| 20260904-1445-jin/requirements.json | DP-JIN-DELIVERYMODE-01 | 親エージェント(team-lead)による確定 | 2026-09-04 | リポジトリには jin-requirements.md 1 ファイルとコミット 1 本しか無く既存コードベースが存在しない |  |
| 20260904-1445-jin/requirements.json | DP-JIN-DIST-01 | 要件書 §10 #8(人間確定済み) | 2026-09-04 | 社内配布の既存導線に乗せる |  |
| 20260904-1445-jin/requirements.json | DP-JIN-DISTRIBUTION-01 | toyota | 2026-09-04T21:20:07+09:00 | AI 仮判断（confidence: medium）を承認。 |  |
| 20260904-1445-jin/requirements.json | DP-JIN-EDITOR-UX-01 | toyota | 2026-09-04T21:12:47+09:00 | AI 仮判断（confidence: medium）を承認。 | docs/adr/ADR-002-DP-JIN-EDITOR-UX-01.md |
| 20260904-1445-jin/requirements.json | DP-JIN-EDITORSTATE-01 | 要件書 §10 #10(人間確定済み) | 2026-09-04 | エディタが独自モデル状態を持たないことで往復無損失を担保する |  |
| 20260904-1445-jin/requirements.json | DP-JIN-IDENTITY-01 | 要件書 §10 #11(人間確定済み) | 2026-09-04 | data-jin 属性・診断・trace pointer の鍵を JSON Pointer に統一する |  |
| 20260904-1445-jin/requirements.json | DP-JIN-LOOPEXIT-01 | 要件書 §10 #5(人間確定済み) | 2026-09-04 | 決定性と静的検証可能性を優先 |  |
| 20260904-1445-jin/requirements.json | DP-JIN-MODELREF-01 | 要件書 §10 #4(人間確定済み) | 2026-09-04 | v1 のスコープを絞る |  |
| 20260904-1445-jin/requirements.json | DP-JIN-MULTIFILE-01 | 要件書 §10 #6(人間確定済み) | 2026-09-04 | 名前解決とスコープの複雑化を v1 では避ける |  |
| 20260904-1445-jin/requirements.json | DP-JIN-NAMING-01 | 要件書 §10 #1(人間確定済み) | 2026-09-04 | 要件書 v0.2 §10 決定事項で確定。Claude Code の LSP ルーティングが拡張子単位のため .json を奪わない |  |
| 20260904-1445-jin/requirements.json | DP-JIN-PHASE-SCOPE-01 | toyota | 2026-09-04T21:12:46+09:00 | AI 仮判断（confidence: medium）を承認。 | docs/adr/ADR-001-DP-JIN-PHASE-SCOPE-01.md |
| 20260904-1445-jin/requirements.json | DP-JIN-RENDERER-01 | 要件書 §10 #9 / §0 設計前提(人間確定済み) | 2026-09-04 | 描画のズレをゼロにするため |  |
| 20260904-1445-jin/requirements.json | DP-JIN-STACK-01 | 要件書 §1.1 技術選定表(人間確定済み) | 2026-09-04 | 要件書に選定理由が併記されている確定済みの技術スタック指定。design フェーズで比較をやり直さない |  |
| 20260904-1445-jin/requirements.json | DP-JIN-TEXTREPR-01 | 要件書 §10 #2(人間確定済み) | 2026-09-04 | LLM が最も安定して書ける。既存 JSON ツールが使える。エディタとの往復が無損失(コメント・整形の保存問題がない) |  |
| 20260904-1445-jin/requirements.json | DP-JIN-TOOLDEF-01 | 要件書 §10 #3(人間確定済み) | 2026-09-04 | 汎用計算は非目標。ツール実装は Python 側に置き Jin からは参照するだけ |  |
| 20260904-1445-jin/design.yaml | DP-COMMON-07 | toyota | 2026-09-04T21:20:09+09:00 | AI 仮判断（confidence: high）を承認。 |  |
| 20260904-1445-jin/design.yaml | DP-COMMON-09 | toyota | 2026-09-04T21:20:08+09:00 | AI 仮判断（confidence: medium）を承認。 | docs/adr/ADR-003-DP-COMMON-09.md |
| 20260904-1445-jin/design.yaml | DP-COMMON-11 | toyota | 2026-09-04T21:20:09+09:00 | AI 仮判断（confidence: high）を承認。 | docs/adr/ADR-004-DP-COMMON-11.md |
| 20260904-1445-jin/design.yaml | DP-COMMON-14 | toyota | 2026-09-04T21:20:09+09:00 | AI 仮判断（confidence: high）を承認。 |  |
| 20260904-1445-jin/design.yaml | DP-COMMON-15 | toyota | 2026-09-04T21:20:08+09:00 | AI 仮判断（confidence: high）を承認。 |  |
| 20260904-1445-jin/design.yaml | DP-COMMON-16 | toyota | 2026-09-04T21:20:09+09:00 | AI 仮判断（confidence: high）を承認。 |  |
| 20260904-1445-jin/design.yaml | DP-COMMON-17 | toyota | 2026-09-04T21:20:07+09:00 | AI 仮判断（confidence: medium）を承認。 |  |
| 20260904-1445-jin/design.yaml | DP-COMMON-18 | toyota | 2026-09-04T21:20:10+09:00 | AI 仮判断（confidence: high）を承認。 |  |
| 20260904-1445-jin/design.yaml | DP-COMMON-19 | toyota | 2026-09-04T21:20:10+09:00 | AI 仮判断（confidence: high）を承認。 |  |
| 20260904-1445-jin/design.yaml | DP-COMMON-20 | toyota | 2026-09-04T21:20:08+09:00 | AI 仮判断（confidence: medium）を承認。 |  |
| 20260904-1445-jin/design.yaml | DP-JIN-CANONICAL-01 | toyota | 2026-09-04T21:20:10+09:00 | AI 仮判断（confidence: high）を承認。 | docs/adr/ADR-005-DP-JIN-CANONICAL-01.md |
| 20260904-1445-jin/design.yaml | DP-JIN-CODEGEN-RUNTIME-01 | toyota | 2026-09-04T21:20:09+09:00 | AI 仮判断（confidence: medium）を承認。 | docs/adr/ADR-008-DP-JIN-CODEGEN-RUNTIME-01.md |
| 20260904-1445-jin/design.yaml | DP-JIN-EDITOR-PROTOCOL-01 | toyota | 2026-09-04T21:20:07+09:00 | AI 仮判断（confidence: medium）を承認。 | docs/adr/ADR-011-DP-JIN-EDITOR-PROTOCOL-01.md |
| 20260904-1445-jin/design.yaml | DP-JIN-POINTER-RANGE-01 | toyota | 2026-09-04T21:20:10+09:00 | AI 仮判断（confidence: high）を承認。 | docs/adr/ADR-006-DP-JIN-POINTER-RANGE-01.md |
| 20260904-1445-jin/design.yaml | DP-JIN-SEMANTIC-GAPS-01 | toyota | 2026-09-04T21:20:07+09:00 | AI 仮判断（confidence: medium）を承認。 | docs/adr/ADR-007-DP-JIN-SEMANTIC-GAPS-01.md |
| 20260904-1445-jin/design.yaml | DP-JIN-SVG-DETERMINISM-01 | toyota | 2026-09-04T21:20:07+09:00 | AI 仮判断（confidence: medium）を承認。 | docs/adr/ADR-010-DP-JIN-SVG-DETERMINISM-01.md |
| 20260904-1445-jin/design.yaml | DP-JIN-TRACE-POINTER-01 | toyota | 2026-09-04T21:20:09+09:00 | AI 仮判断（confidence: medium）を承認。 | docs/adr/ADR-009-DP-JIN-TRACE-POINTER-01.md |
| 20260904-1445-jin/implementation-plan.json | DP-IMPL-JIN-DIAGCODE-01 | toyota | 2026-09-04T21:20:59+09:00 | 人間レビューで承認（2026-09-04 toyota）。実装ラウンド 1 で impl-p01 が根拠付きで確定した値を、内容を変えずに人間確定へ昇格させる。根拠は delivery/20260904-1445-jin/decision-conformance.md §2 を参照。 |  |
| 20260904-1445-jin/implementation-plan.json | DP-IMPL-JIN-DIAGPREC-01 | toyota | 2026-09-04T21:20:59+09:00 | 人間レビューで承認（2026-09-04 toyota）。実装ラウンド 1 で impl-p01 が根拠付きで確定した値を、内容を変えずに人間確定へ昇格させる。根拠は delivery/20260904-1445-jin/decision-conformance.md §2 を参照。 |  |
| 20260904-1445-jin/implementation-plan.json | DP-IMPL-JIN-POSBASE-01 | toyota | 2026-09-04T21:20:59+09:00 | 人間レビューで承認（2026-09-04 toyota）。実装ラウンド 1 で impl-p01 が根拠付きで確定した値を、内容を変えずに人間確定へ昇格させる。根拠は delivery/20260904-1445-jin/decision-conformance.md §2 を参照。 |  |
| 20260904-1445-jin/implementation-plan.json | DP-IMPL-JIN-TDD-P0-01 | toyota | 2026-09-04T21:20:59+09:00 | 人間レビューで承認（2026-09-04 toyota）。実装ラウンド 1 で impl-p01 が根拠付きで確定した値を、内容を変えずに人間確定へ昇格させる。根拠は delivery/20260904-1445-jin/decision-conformance.md §2 を参照。 |  |
| 20260904-1445-jin/implementation-plan.json | DP-IMPL-JIN-TESTFIXTURE-01 | toyota | 2026-09-04T21:20:59+09:00 | 人間レビューで承認（2026-09-04 toyota）。実装ラウンド 1 で impl-p01 が根拠付きで確定した値を、内容を変えずに人間確定へ昇格させる。根拠は delivery/20260904-1445-jin/decision-conformance.md §2 を参照。 |  |
| 20260904-1445-jin/implementation-plan.json | DP-IMPL-JIN-TOOLNAME-01 | toyota | 2026-09-04T21:20:59+09:00 | 人間レビューで承認（2026-09-04 toyota）。実装ラウンド 1 で impl-p01 が根拠付きで確定した値を、内容を変えずに人間確定へ昇格させる。根拠は delivery/20260904-1445-jin/decision-conformance.md §2 を参照。 |  |
| 20260904-1445-jin/implementation-plan.json | DP-IMPL-JIN-UPSTREAM-01 | toyota | 2026-09-04T21:20:59+09:00 | 人間レビューで承認（2026-09-04 toyota）。実装ラウンド 1 で impl-p01 が根拠付きで確定した値を、内容を変えずに人間確定へ昇格させる。根拠は delivery/20260904-1445-jin/decision-conformance.md §2 を参照。 |  |
| 20260904-1445-jin/implementation-plan.json | DP-JIN-DIAGCODE-NUMBERING-01 | toyota | 2026-09-04T21:12:47+09:00 | AI 仮判断（confidence: medium）を承認。 | docs/adr/ADR-012-DP-JIN-DIAGCODE-NUMBERING-01.md |
| 20260904-1445-jin/implementation-plan.json | DP-JIN-JIN050-LOOP-SCOPE-01 | toyota | 2026-09-04T21:20:07+09:00 | AI 仮判断（confidence: medium）を承認。 | docs/adr/ADR-014-DP-JIN-JIN050-LOOP-SCOPE-01.md |
| 20260904-1445-jin/implementation-plan.json | DP-JIN-RENAME-SCOPE-01 | toyota | 2026-09-04T21:12:47+09:00 | AI 仮判断（confidence: high）を承認。 | docs/adr/ADR-013-DP-JIN-RENAME-SCOPE-01.md |
| 20260904-1445-jin/implementation-plan.json | DP-JIN-RESOLVE-ISOLATION-01 | toyota | 2026-09-06T01:20:41+09:00 | Issue #8 の人間判断（2026-09-06 toyota）。決め手は要件書 §6.2 の hover が「Python 参照の docstring（--resolve 相当）」を要求している点で、Phase 4 の長寿命 LSP プロセスは必ず参照解決を行う。(b) は LSP の問題に答えず、(c) は README / CLAUDE.md / --help に既にある警告の再掲で汚染… | docs/adr/ADR-018-DP-JIN-RESOLVE-ISOLATION-01.md |
| 20260904-1445-jin/implementation-plan.json | DP-REVIEW-JIN-008 | toyota | 2026-09-06T01:20:41+09:00 | Issue #8 の人間判断（2026-09-06 toyota）。Issue の指示「まず 1000 行の実ファイルで実測し、満たしていれば『実測して満たした』と記録して閉じてよい（過剰最適化しない）」に従う。実測は delivery/20260904-1445-jin/check-text-benchmark.md（スクリプト: 同 bench/bench_check_text.py・Pyt… |  |

<!-- AUTO-GENERATED END: pending-decisions-generator -->
