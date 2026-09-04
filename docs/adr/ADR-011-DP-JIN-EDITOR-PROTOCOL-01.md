# ADR-011: DP-JIN-EDITOR-PROTOCOL-01 案 C: 独自リクエスト（jin/open と jin/save 仮称）を 2 本追加し、ws モードのエディタだけが使う

> ⚠️ **AI 仮決定（ai_provisional）** — auto mode の仮判断であり人間確定ではない（DP-AUTOMODE-01）。PR レビュー後、`/decide` で approved / overridden に確定する。

- **ステータス**: proposed (ai_provisional)
- **日付**: 2026-09-04
- **決定者**: auto-decider
- **関連判断ポイント**: DP-JIN-EDITOR-PROTOCOL-01

## コンテキスト

_（コンテキストは案件側で追記）_

## 選択肢

| 選択肢 | 採否 |
|---|---|
| 案 C: 独自リクエスト（jin/open と jin/save 仮称）を 2 本追加し、ws モードのエディタだけが使う | 採用 |
| 案 A: サーバが暗黙にディスクを読み書きする（open は pygls の遅延読込に任せ、save は applyEdit 適用後に常に書く） | 不採用 |
| 案 B: 標準 LSP メッセージに寄せる（エディタが didOpen でテキストを送り、didSave を書き込み契機にする） | 不採用 |

## 決定

design.yaml fired_decision_points[DP-JIN-EDITOR-PROTOCOL-01] の推奨案（案 C）をそのまま採用する。jin editor が起動する Python プロセス側に ws クライアント向けのファイル I/O 責務を置き、独自リクエスト jin/open と jin/save（仮称）の対でエディタが読み込みと保存を要求する形にする。要件との適合根拠: 要件書 §6.3 の jin/applyOps は「クライアントがファイルを読んでテキストを送り保存も行う」というLSP の前提に立つが、ブラウザのエディタはファイルシステムを持たない。案 A（サーバが暗黙にディスクを読み書き）は stdio モードの未保存バッファを無視して書き換え、モードで挙動を分ければ FR-LSP-002 の「同一サーバ実装」が実質崩れる。また pygls の Workspace の遅延読込に黙って依存することは NFR-FAIL-001「黙って落とさない」と噛み合わない。案 B（didOpen / didSave に寄せる）はエディタがファイルを読めないため didOpen に載せるテキストを取得できず、didSave は保存完了通知であって書き込み依頼ではないためプロトコルの意味を曲げる。案 C なら差分がリクエスト 2 本に閉じ、stdio モードは従来どおりで同一サーバ実装を保てる。要件書 §6.3 の独自リクエスト 4 種への追加であり仕様変更の人間承認を要するため confidence は medium とする。

## 影響

_（影響は案件側で追記）_
