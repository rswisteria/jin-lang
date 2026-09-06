# ADR-019: trace overlay の強調規則は祖先一致 + referent 規則とする

> ⚠️ **AI 仮決定（ai_provisional）** — auto mode の仮判断であり人間確定ではない（DP-AUTOMODE-01）。PR レビュー後、`/decide` で approved / overridden に確定する。

- **ステータス**: proposed (ai_provisional)
- **日付**: 2026-09-06
- **決定者**: auto-decider
- **関連判断ポイント**: DP-IMPL-JIN-P3-OVERLAY-REFERENT-01

## コンテキスト

要件書 §4 は trace と upto を渡すと発火した要素を強調色でオーバーレイすることを求める。一方 §2.5 は data-jin をエディタのヒットテストの鍵と定め、jin/model の pointer→range 対応表と一致することを要求する。参照を表す要素（flow.steps の節・summon の紋・delegate の小円）の data-jin は参照側の pointer でなければならないが、トレースの行は参照先の pointer を持つ。pointer を末尾から削る祖先一致だけでは、focus=root のとき下位 circle の model 行に対応する描画要素が無く何も強調されない。

## 選択肢

| 選択肢 | 採否 |
|---|---|
| 選択肢 1: trace overlay の強調規則として「pointer を末尾から 1 セグメントずつ削る祖先一致」+「参照要素の data-jin-ref による referent 規則」を承認する | 採用 |
| 選択肢 2: data-jin を参照先の pointer にする。祖先一致だけで済むが、エディタのヒットテストが参照側を掴めなくなり、要件書 §2.5 の pointer→range 対応表との一致も崩れる | 不採用 |
| 選択肢 3: 参照要素を強調しない。規則は単純になるが focus=root でトレースがほぼ見えず、要件書 §4 の overlay 要件を満たさない | 不採用 |

## 決定

要件書 §2.5 は data-jin を「エディタがヒットテストと選択を行う鍵」と定め、さらに「jin/model が返す pointer→range 対応表と一致すること」を要求している。したがって参照を表す要素（flow.steps の節・summon の紋・delegate の小円）の data-jin は参照側の pointer でなければならない。選択肢 2（data-jin を参照先にする）はこの 2 つの契約を同時に壊す。一方トレースの行は参照先の pointer を持つため、祖先一致だけでは focus=root のとき下位 circle の model 行（/circles/4/core など）が何も強調されず、要件書 §4 の「upto までに発火した要素を強調色でオーバーレイ」が root 焦点でほぼ成立しない。これが選択肢 3 を採れない理由である。よって参照要素に追加属性 data-jin-ref="/circles/<k>" を付け、参照先 circle の配下 pointer でも当たるようにする案 1 を採る。追加属性は契約違反ではない（契約は「2 属性を持つこと」であって「2 属性しか持たないこと」ではない・docs/spec/layout.md §3.1）。規則の正本は docs/spec/layout.md §7.1、根拠は decision-conformance.md §2.24.5。機械固定は tests/contract/test_render_contract.py::test_every_live_pointer_resolves_at_the_root_focus（jin run --model fake を実際に回した 11 行の全 pointer が root 焦点で解決する）で、変異 OVL-exact-only / OVL-no-referent / OVL-no-ref-attribute の 3 本が赤になることを実測している。

## 影響

参照要素は data-jin-ref="/circles/<k>" を持ち、参照先 circle の配下 pointer でも強調対象になる。Phase 5-6 のエディタはこの属性でヒットテストと強調表示を行うため、規則を変えるならエディタ着手前が安い。契約テストは 2 属性の存在と kind 9 種だけを見る形にし、追加属性を禁じない。深さ 1 の入れ子は完全一致で解決するので referent 規則は深さ 2 以降の点にだけ効く。
