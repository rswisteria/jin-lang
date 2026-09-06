# ADR-022: loop の星形多角形は節を角位置 (j*k) mod n に置き、辺を訪問順の隣で結ぶ

> ⚠️ **AI 仮決定（ai_provisional）** — auto mode の仮判断であり人間確定ではない（DP-AUTOMODE-01）。PR レビュー後、`/decide` で approved / overridden に確定する。

- **ステータス**: proposed (ai_provisional)
- **日付**: 2026-09-06
- **決定者**: auto-decider
- **関連判断ポイント**: DP-IMPL-JIN-P3-LOOP-STAR-ORDER-01

## コンテキスト

要件書 §2.5 は n >= 5 の loop を星形多角形 {n/k}（k は n/2 未満で n と互いに素な最大の整数）で描き「辺の順を訪問順に一致させる」と定める。Phase 3 の初期実装は節 flow.steps[j] を角位置 j に置き、辺を j → (j+k) mod n に矢じり付きで描いていた。この配置では n=5 のとき辺列が S0→S2→S4→S1→S3 となり、辺の順も矢じりの向きも flow.steps の実行順と一致しない。docs/spec/layout.md §2.1 も同じ節の中で「辺の順は訪問順に一致させる」と「辺は節 j から節 (j+k) mod n」を並べており、文書内でも食い違っていた（Stage 5 レビュー F-C-P3-002・confidence 70）。

## 選択肢

| 選択肢 | 採否 |
|---|---|
| 選択肢 (a): loop の節 flow.steps[j] を角位置 (j*k) mod n に置き、辺は j → (j+1) mod n（訪問順の隣）を矢じり付きで結ぶ。星形多角形 {n/k} の見た目と「辺の順は訪問順」を同時に満たす | 採用 |
| 選択肢 (b): 配置と辺は現状（節 j を角位置 j・辺は j → (j+k) mod n）のまま矢じりを外す。不採用 — 旧配置では辺列自体が S0→S2→S4→S1→S3 で、矢じりの有無に関わらず §2.5 の「辺の順を訪問順に一致させる」を満たさない。向きの主張をやめて食い違いを見えなくするだけであり、implementation-notes P3-7 項 5 の「矢じりが無いと訪問順を目で追えない」も失う | 不採用 |
| 選択肢 (c): 現状のまま（節 j を角位置 j・辺は j → (j+k) mod n・矢じりあり）。不採用 — 要件書 §2.5 と docs/spec/layout.md §2.1 冒頭の文の両方と食い違ったままになる（F-C-P3-002） | 不採用 |
| 角位置は現状のまま辺だけを j → (j+1) mod n にする案。不採用 — 角位置 j と j+1 は隣り合う頂点なので単純な凸多角形になり、星形多角形 {n/k} を描くという要件書 §2.5 の指定を失う | 不採用 |
| 前回の記録（2026-09-06T12:04:02+09:00・auto-decider / ai_provisional）: chosen・選択肢・constraints は同一だが、rationale に変異 STAR-slot-identity の効き方を「角位置を恒等に戻すと星形テストは緑のまま訪問順テストだけが赤 = 2 本が独立に効いている証拠」と書いていた。実物は逆で、恒等に戻すと辺 j → (j+1) mod n が単純多角形になるため星形テスト test_loop_edges_follow_the_star_polygon の [5-2] / [8-3] が赤になり、訪問順テスト test_loop_nodes_are_placed_so_the_arrows_follow_the_visit_order は緑のままである（Stage 5 再レビュー F-C-P3-104・confidence 90）。修正ラウンド 2 で notes P3-R1.1 C-1 行 / mutate_p3.py のコメント / undecided_details の note の 3 箇所が実測に直り、独立性の証拠は新規変異 STAR-pre-fix-visit-order / STAR-pre-fix-star-shape-stays に置き換わった。本記録はその実測に追従させたもので、結論は変えていない | 不採用 |

## 決定

質問 1（要件書 §2.5「辺の順を訪問順に一致させる」の解釈）: 決め手は矢じりではなく辺列そのものである。旧配置（節 j を角位置 j に置き、辺を j → (j+k) mod n にする）では、n=5 のとき辺を順に辿ると S0→S2→S4→S1→S3 になり、矢じりを外しても「辺の順」は訪問順（S0→S1→S2→S3→S4）にならない。したがって選択肢 (b)（矢じりを外す）は §2.5 を満たす案ではなく、向きの主張をやめて食い違いを見えなくするだけであり、選択肢 (c) は食い違いをそのまま残す。gcd(n,k)=1 により j -> (j*k) mod n は全単射なので、節を角位置 (j*k) mod n へ置き替えて辺を訪問順の隣 j → (j+1) mod n で結ぶと、角位置だけを見た辺集合は s -> (s+k) mod n のまま（星形 {n/k} は不変）で、同時に辺列と矢じりが flow.steps の実行順を指す。{n/k} を保ったまま §2.5 を満たせるのは (a) だけなので (a) を採る。出典は code-review-raw/correctness-p3.md の F-C-P3-002（confidence 70）と docs/spec/layout.md §2.1 / §6。実装は jin_render.layout._Builder._flow_slots（`[(j * step) % count for j in range(count)]`）と _flow_edges（loop は `pairs = [(j, (j + 1) % count)]`）。ADR-010（DP-JIN-SVG-DETERMINISM-01・人間確定）の condition「星形多角形 {n/k} の k の選択規則を一意に定める」には触れていない: k を返す jin_render.geometry.star_step（`max{ j : 1 <= j < n/2 かつ gcd(n, j) == 1 }`）は変更していない。質問 2（Phase 4 着手前に確定させる前提でよいか）: よい。examples 2 本に loop が無いので今回のスナップショット差分は 0 で、変えるなら図の位置に依存する成果物が増える前が最も安い。Phase 5 のエディタが節の位置を記憶する設計なら、その前提が固まる前に確定している必要がある。質問 3（n < 5 は配列順のままでよいか）: よい。ただしこれは分岐ではなく式の帰結である。_flow_slots は (j*k) mod n の 1 本だけで n<5 の特別扱いを持たず、star_step が k=1 を返す n では恒等写像になる。k=1 になるのは n<5 だけでなく n=6（2j<6 かつ gcd(6,j)=1 は j=1 のみ）も同じで、配置が実際に動くのは k>=2 になる n（5, 7 以上の該当 n）である。機械固定は packages/jin-render/tests/test_layout.py::test_loop_nodes_are_placed_so_the_arrows_follow_the_visit_order（n=3〜12 の 10 param・節の名前の側から「どの矢印も flow.steps で隣り合う 2 つを結ぶ」を見る）、::test_a_small_loop_keeps_the_array_order_placement、既存の ::test_loop_edges_follow_the_star_polygon（n=5/6/8・角位置としての辺集合が {n/k} のままであることを別に固定）。変異は STAR-slot-identity と STAR-reversed で赤を実測済み。STAR-slot-identity（_flow_slots を list(range(count)) に戻す）の効き方は実測では「角位置を恒等に戻すと辺 j → (j+1) mod n が単純多角形になるので test_loop_edges_follow_the_star_polygon の [5-2] / [8-3] が赤・test_loop_nodes_are_placed_so_the_arrows_follow_the_visit_order は全 param 緑」である。2 本のテストが独立に効くことは、修正ラウンド 2 で足した変異 2 本が示す: STAR-pre-fix-visit-order（配置を恒等に戻し辺も j → (j+k) mod n に戻す修正前挙動を当て、訪問順テストだけを見て 7 param 赤）と STAR-pre-fix-star-shape-stays（同じ修正前挙動で星形テストだけを見て 3 param 緑・EXPECT_GREEN）。修正ラウンド 2 の実測は 70 本 / 70 caught（うち 2 本は期待 GREEN・SKIP 0）。仕様側は docs/spec/layout.md §2.1（節の置き方と辺の定義・旧記述との違いの説明を含む）と §6 の表 2 行を同時に直してあり、レビューが指摘した「§2.1 の中で文が食い違う」状態は解消している。残存: loop の辺に矢じりを付けること自体は implementation-notes P3-7 項 5 の別判断（要件書 §2.5 は sequence にだけ「（矢印）」と書いている）であり、本判断はその前提の上で向きの正しさだけを決める。図としての見た目の妥当性は human_only で実装者は判定していない。

## 影響

jin_render.layout._Builder._flow_slots が loop の節を角位置 (j*k) mod n へ置き、_flow_edges が loop の辺を j → (j+1) mod n で結ぶ。角位置として見た辺集合は s → (s+k) mod n のままなので星形 {n/k} の見た目は変わらず、矢じりだけが実行順を指すようになる。k の決め方（geometry.star_step）は変えていない。k = 1 になる n（n < 5 および n = 6）は恒等写像なので配置は配列順のまま。docs/spec/layout.md §2.1 / §6 を同時に直した。機械固定は test_layout.py の test_loop_nodes_are_placed_so_the_arrows_follow_the_visit_order（n=3〜12）/ test_a_small_loop_keeps_the_array_order_placement / test_loop_edges_follow_the_star_polygon、変異 STAR-slot-identity と STAR-reversed で赤を実測。examples 2 本に loop が無いためスナップショット差分は 0 だが、n >= 5 で k >= 2 の loop を含む図は角位置が動くので、Phase 5 のエディタが位置を記憶する設計より前に確定させる必要がある。
