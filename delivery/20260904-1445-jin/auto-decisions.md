# AI 判断台帳（auto mode / DP-AUTOMODE-01）

**人間に確認してほしい判断: 3 件**（内訳: ⚠️ prohibition 付き 2 件 + △ confidence が high 以外 1 件）／レビュー待ち 3 件・全 3 件。
承認・上書きは `/decide DP-XXX "<選択>" "<理由>" --decided_by "<氏名>"`（同一選択 = approved / 別選択 = overridden）。

| 要確認 | DP ID | 選択 | rationale | confidence | review_status | model | 起票元 |
|---|---|---|---|---|---|---|---|
| ⚠️ 要人間確認 | DP-JIN-DISTRIBUTION-01 | 現 remote(github.com:rswisteria/jin-lang.git)を配布元とし、社内移管は後日行う | recommended をそのまま採用した(依頼者の明示発話は配布導線に言及しておらず、推奨と矛盾しない)。本リポジトリの実 remote は git@github.com:rswisteria/jin-lang.git であり、jin-… | medium | pending_human_review | claude-opus-5 | requirements.json |
| ⚠️ 要人間確認 | DP-JIN-EDITOR-UX-01 | 機能要件(§7.1 / §7.2)だけを満たす最小 UI を AI 仮判断で作り、デザインは後で差し替える | DP-JIN-PHASE-SCOPE-01 で Phase 5〜6 を本ランに含めたため、recommended の「Phase 5 を本ランのスコープから外し、デザイナー参加後の別ランにする」は依頼者が名指しした「ビジュアルエディタ」を… | medium | pending_human_review | claude-opus-5 | requirements.json |
| △ 要確認（medium） | DP-JIN-PHASE-SCOPE-01 | Phase 0〜6(全フェーズ) | 依頼者(人間)の逐語発話「jin-requirements.md で定義されているビジュアルプログラミング言語処理系とビジュアルエディターを実装したいです。- 言語仕様 - 実行処理系 - ビジュアルエディタ 上記を実装したいです」を最優… | medium | pending_human_review | claude-opus-5 | requirements.json |
