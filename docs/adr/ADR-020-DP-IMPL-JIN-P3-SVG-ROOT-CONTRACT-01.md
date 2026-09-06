# ADR-020: data-jin 契約の対象は svg 要素と defs 配下を除く描画要素とする

> ⚠️ **AI 仮決定（ai_provisional）** — auto mode の仮判断であり人間確定ではない（DP-AUTOMODE-01）。PR レビュー後、`/decide` で approved / overridden に確定する。

- **ステータス**: proposed (ai_provisional)
- **日付**: 2026-09-06
- **決定者**: auto-decider
- **関連判断ポイント**: DP-IMPL-JIN-P3-SVG-ROOT-CONTRACT-01

## コンテキスト

要件書 §2.5 は「描画された全ての要素」に data-jin と data-jin-kind を要求し、kind を 9 種の閉じた列挙で定める。svg 要素は文書そのもので 9 種のどれにも当たらず、defs の中身は描かれない。両者を契約に含めると 10 種目の kind が必要になり、要件書 §2.5 の列挙を変えることになる。

## 選択肢

| 選択肢 | 採否 |
|---|---|
| 選択肢 1: svg 要素自身と defs 配下を data-jin 契約の対象外とする解釈を承認する | 採用 |
| 選択肢 2: svg 要素に data-jin="" を付け、ルート文書を表す 10 種目の data-jin-kind を足す。契約の文言どおりになるが要件書 §2.5 の 9 種の列挙を変えることになり、tests/spec の要件書突合と Phase 5 エディタのヒットテスト分岐に波及する | 不採用 |

## 決定

要件書 §2.5 は「描画された全ての要素は data-jin と data-jin-kind を持つ」と書き、data-jin-kind を circle|core|rune|tool|state|flow-edge|guard|await|delegate の 9 種の閉じた列挙で定めている。svg 要素は文書そのものであって描画された要素ではなく、9 種のどれにも当たらない。defs の中身（textPath が参照する経路の定義）はそれ自体が描かれない。選択肢 2（svg に data-jin="" を付ける）は 10 種目の kind を足すことになり、要件書 §2.5 の列挙そのものの変更を伴う（T-002: 要件書に無い値・種別を勝手に増やさない）。したがって両者を契約の対象外とし、テストは svg と defs 配下を除く全要素で回す。同じ解釈から背景の塗り（rect）も置かず SVG は透明背景にした。置くと data-jin を持たない描画要素が 1 つ増え、契約の例外がもう 1 つ必要になるからである。9 種に無い描画要素（境界環の外側に並ぶトレースの点）は 10 種目を作らず既存の circle として描き、pointer は焦点の circle・何番目のイベントかは data-jin-seq に入れている。出典は docs/spec/layout.md §3.1 と decision-conformance.md §2.24.4、申し送り phase3-handoff.md §7 の指示とも一致する。機械固定は packages/jin-render/tests/test_layout.py::test_every_element_carries_both_attributes と ::test_every_kind_is_one_of_the_nine で、変異 CONTRACT-core-no-pointer / CONTRACT-ring-no-pointer が赤になることを実測している。

## 影響

契約テストは svg と defs 配下を除く全要素で回す。背景の塗り（rect）を置かないため SVG は透明背景で、埋め込む側の地色を使う（強調色のコントラスト前提に影響する）。9 種に無い描画要素であるトレースの点は kind=circle として描き、pointer は焦点の circle・順序は data-jin-seq で表す。Phase 5 のエディタは svg 要素と defs を選択対象から除外してよい。
