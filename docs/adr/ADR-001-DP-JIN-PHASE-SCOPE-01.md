# ADR-001: 本ランの実装範囲を Phase 0〜6 全フェーズとし、Phase 0 承認ゲートを PR レビューで代替する

> ⚠️ **AI 仮決定（ai_provisional）** — auto mode の仮判断であり人間確定ではない（DP-AUTOMODE-01）。PR レビュー後、`/decide` で approved / overridden に確定する。

- **ステータス**: proposed (ai_provisional)
- **日付**: 2026-09-04
- **決定者**: auto-decider
- **関連判断ポイント**: DP-JIN-PHASE-SCOPE-01

## コンテキスト

jin-requirements.md §11 は Phase 0〜7 を独立した発注単位とし、Phase 0 の仕様書承認を Phase 1 着手の前提としている。auto mode(DP-AUTOMODE-01)には承認する人間がおらず、また requirements-analyst は依頼者の逐語発話を判断材料に含めずに Phase 0〜1 を推奨していた。依頼者は 言語仕様 / 実行処理系 / ビジュアルエディタ の 3 点を明示的に名指ししている。

## 選択肢

| 選択肢 | 採否 |
|---|---|
| Phase 0〜6(全フェーズ) | 採用 |
| Phase 0〜1(仕様書 + jin-core + jin-cli の check/fmt/schema/dump) | 不採用 |
| Phase 0〜2(+ jin-adk build/run/trace/FakeLlm) | 不採用 |
| Phase 0〜4(エディタを除く全 Python パッケージ + Claude Code プラグイン) | 不採用 |

## 決定

依頼者(人間)の逐語発話「jin-requirements.md で定義されているビジュアルプログラミング言語処理系とビジュアルエディターを実装したいです。- 言語仕様 - 実行処理系 - ビジュアルエディタ 上記を実装したいです」を最優先の判断根拠とした。requirements-analyst の recommended は「Phase 0〜1(仕様書 + jin-core + jin-cli の check/fmt/schema/dump)」だが、これは当該依頼を判断材料に含めずに付けられた推奨であるため、requirements-analyst の recommended より依頼者の明示発話を優先した。jin-requirements.md §11 の Phase 対応では 言語仕様 = Phase 0〜1 / 実行処理系 = Phase 2(+ Phase 3 レンダラ・Phase 4 LSP は §0「レンダラは 1 つだけ(Python)。エディタは LSP から SVG を受け取って表示し、独自に描画しない」により処理系とエディタ双方の前提) / ビジュアルエディタ = Phase 5〜6 であり、人間が名指しした 3 点すべてを満たす選択肢は Phase 0〜6 のみ。Phase 0〜4 では「ビジュアルエディタ」が、Phase 0〜2 では加えて成功条件 2・4 が落ちる。DP タイトル後半の Phase 0 承認ゲート(§11「Phase 0 の仕様書を先に承認してから Phase 1 に入る」)は auto mode に承認者がいないため、skills/common/auto-decision/DOMAIN-SKILL.md「人間レビュー(PR レビューで代替)」節に従い ai_provisional 記録 + PR レビューで代替する(constraints 参照)。本選択肢の cons「要件書自身が各フェーズを独立した spec → plan → 実装のサイクルにすると指定している方針に反する」に対しては、1 ラン内でも Phase 順に進め前 Phase の §11 完了条件充足を後続 Phase の着手条件とすることで正面から応える(constraints 参照)。confidence は medium — 依頼者の明示発話という強い根拠がある一方、もう 1 つの cons「Python 5 パッケージ + React エディタ + Playwright を 1 ランで作ることになり品質担保が困難」は実在するリスクとして残るため high は付けない。

## 影響

design.yaml のスコープと implementation-plan.json の Stage 構成が Phase 0〜6 相当まで広がる。Python 5 パッケージ(jin-core / jin-cli / jin-adk / jin-render / jin-lsp)+ Claude Code プラグイン + React エディタが本ランの対象になり、成功条件 1〜6 すべてが評価対象になる。Phase 0 仕様書の妥当性判断は PR レビューまで先送りされるため、仕様の誤りが後続 Phase に伝播するリスクを負う。
