# ADR-012: JIN012（循環参照）/ JIN013（多重親）の採番と要件書 §2.4 への追加を承認する

> ⚠️ **AI 仮決定（ai_provisional）** — auto mode の仮判断であり人間確定ではない（DP-AUTOMODE-01）。PR レビュー後、`/decide` で approved / overridden に確定する。

- **ステータス**: proposed (ai_provisional)
- **日付**: 2026-09-04
- **決定者**: auto-decider
- **関連判断ポイント**: DP-JIN-DIAGCODE-NUMBERING-01（aliases: JIN012 / JIN013 を承認し要件書 §2.4 の表に 2 行追加する）

## コンテキスト

ADR-007（DP-JIN-SEMANTIC-GAPS-01）が案 A『新しい JIN コードを 2 つ追加して jin-core の意味検査で検出する』を採択したが、その constraints は『採番値は Phase 0 の docs/spec/diagnostics.md 執筆時に決定し根拠を残す』『要件書 §2.4 への追加であり仕様変更として人間の承認を要する』としていた。実装ラウンド 1 で採番値が JIN012 / JIN013 として提案され、docs/spec/diagnostics.md §3 に承認待ちの別表として実装された。診断コードは LLM 向けの公開契約であり、番号を後から変えると定数・fixture・仕様書・生成済み .jin の修正ループがすべて追随する。本 ADR はその採番値と §2.4 への追加そのものの承認を記録する。

## 選択肢

| 選択肢 | 採否 |
|---|---|
| 選択肢 1: JIN012（循環参照）/ JIN013（多重親）を承認し、要件書 §2.4 の表に 2 行追加する | 採用 |
| 選択肢 2: 03x ブロックの JIN032 / JIN033 に採り直す（リネーム影響は定数 2 個とファイル名 2 本で軽微だが、多重親が delegate でも起きるため flow ブロックへの配置は関心事の対応を崩す） | 不採用 |
| 選択肢 3-B: 追加を却下し ADR-007 を案 B（jin-adk のコード生成時エラーに委ねる）へ切り替える（jin check が通ってしまい成功条件 3 が成立せず、レンダラ経路では検出されず無限再帰する） | 不採用 |
| 選択肢 3-C: 追加を却下し ADR-007 を案 C（JIN011 / JIN031 に寄せる）へ切り替える（『未解決の参照』と『解決できる参照が循環している』は意味が違い、要件書 §9『fixture は対応コードを 1 つだけ出す』の意図から外れる） | 不採用 |

## 決定

(1) ADR-007（DP-JIN-SEMANTIC-GAPS-01）は既に案 A『新しい JIN コードを 2 つ追加し jin-core の意味検査で検出する』を採択済みであり、本 DP はその採番値と §2.4 への追加そのものの承認を問うている。案 A を覆すに足る新事実は本ラウンドで得られていないため、案 B / 案 C への切り替え（選択肢 3）は採らない。(2) 採番根拠は docs/spec/diagnostics.md §3.1 に既に書かれており検証可能である。要件書 §2.4 のコードは 10 の位で関心事がブロック化されており（00x 入力の妥当性 / 01x 名前と参照の整合性 / 02x circle 単体の形 / 03x flow / 04x 外部解決 / 05x rune / 06x root / 07x await）、循環参照と多重親はいずれも『circle 名で張られた参照グラフ全体の整合性』であって 01x（JIN010 名前の重複 / JIN011 未解決の参照）と同じ関心事に属する。01x は JIN012〜JIN019 が空いており若い順に JIN012 / JIN013 を採るのは既存の採番規律と一致する。(3) 選択肢 2（03x ブロックの JIN032 / JIN033）は採らない。多重親は delegate（flow ではない）でも、循環参照は summon でも起きるため、03x（flow 自身の妥当性）に置くと 10 の位のブロック対応が崩れ、採番規律そのものが失われる。リネームコストが軽微であることは、規律を崩す理由にはならない。(4) 実害の大きさが追加を正当化する: 循環参照は Phase 3 レンダラの入れ子展開が無限再帰し、多重親は ADK の BaseAgent.parent_agent が単一値であるため Phase 2 のコード生成が破綻する。どちらも jin check で検出できなければ要件書 §0 成功条件 3（LLM が診断だけで直しきる）が成立しない。(5) 本判断は ai_provisional であり、ADR-007 constraints (b) が求める人間承認を代替しない。したがって要件書 §2.4 の実際の編集は人間承認後にのみ行う（constraints 参照）。confidence は ADR-007 自身の判断（『§2.4 の確定した 12 件の表への追加であり仕様変更の人間承認を要するため medium』）に合わせて medium とする。

## 影響

docs/spec/diagnostics.md §3 の 2 件が（人間承認後に）§2 の正典表へ統合され、要件書 §2.4 の表が 12 件から 14 件になる。統合時は diagnostics.md §0 / tests/spec/test_spec_consistency.py / design.yaml:541-543（Phase 0 の verification.machine）にある『12 件』の 3 つの表明を同時に更新する必要がある。承認されるまでは実装（packages/jin-core/src/jin_core/semantic.py の JIN012 / JIN013 検査と diagnostics.py の PROPOSED_CODES）と fixture 2 本は現状のまま据え置く。schemas/jin.schema.json への影響はない。
