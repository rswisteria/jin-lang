# ADR-018: --resolve の参照解決を ref ごとの子プロセス + タイムアウト（30 秒）で隔離する

- **ステータス**: accepted
- **日付**: 2026-09-06
- **決定者**: toyota
- **関連判断ポイント**: DP-JIN-RESOLVE-ISOLATION-01

## コンテキスト

`jin check --resolve` は `.jin` の `tools[].ref` / `boundary.guards[].ref` を解決するために同一プロセスで任意モジュールを import する。その結果、1 ファイル目の `ref` が `jin_core.semantic.analyze` を差し替えると 2 ファイル目の本物の JIN060 が消え「2 ファイル / error 0 件」exit 0 になる（親が実測・DP-JIN-RESOLVE-ISOLATION-01）。プロセスが死なずもっともらしい正常レポートを出す点で SystemExit 経路（S2）より実害が大きく、タイムアウトも無いのでハングしうる。Phase 4 の `jin lsp` は長寿命プロセスになり、要件書 §6.2 の hover は「Python 参照の docstring（--resolve 相当）」を要求するので、同一プロセスで参照解決を再利用する設計にすると汚染がサーバ寿命全体に及ぶ。security reviewer は S1 の代替案として「別プロセス + タイムアウト」を提案していた。

## 選択肢

| 選択肢 | 採否 |
|---|---|
| (a) 別プロセス + タイムアウト: ref 1 件ごとに子プロセス（sys.executable -P -m jin_cli.resolver）で import し、親は解決可否と理由だけを受け取る。タイムアウトは ref 1 件あたり 30 秒（既定・CLI オプションは増やさない） | 採用 |
| (b) --resolve を単一ファイルのみに制限し、複数ファイル / ディレクトリ指定では拒否する | 不採用 |
| (c) 現状を受け入れ、--resolve は信頼できる .jin にのみ使う旨を README / CLAUDE.md と CLI 警告に明記する（既に明記済みで実質は現状維持） | 不採用 |

## 決定

Issue #8 の人間判断（2026-09-06 toyota）。決め手は要件書 §6.2 の hover が「Python 参照の docstring（--resolve 相当）」を要求している点で、Phase 4 の長寿命 LSP プロセスは必ず参照解決を行う。(b) は LSP の問題に答えず、(c) は README / CLAUDE.md / --help に既にある警告の再掲で汚染とハングが残るため、Phase 4 の要件と両立するのは (a) だけ。(a) は汚染を子プロセスに閉じ、ハングをタイムアウトで検出する。ただし S1（任意コード実行そのもの）は消えない: 子は親と同じ権限で走るので「中身を確認した .jin にだけ使う」警告は残す。タイムアウト 30 秒の根拠: google-adk 程度（1〜2 秒）だけでなく tensorflow 級の重い依存を持つツールモジュールの cold import（10〜20 秒）を正当に通しつつ、ハングを 30 秒で検出する。要件書に値が無いので docs/spec/diagnostics.md の JIN040 節に根拠を残す。

## 影響

`jin_cli.resolver` に子プロセス起動側（`SubprocessResolver`）と子側のエントリ（`python -P -m jin_cli.resolver <ref>`）を置き、CLI の `--resolve` は子プロセス経路だけを使う。同一プロセスで import する `ImportResolver` は子の中でだけ動く。任意コード実行の実装は引き続き `jin_cli.resolver` と `jin_adk.runtime` に閉じる（import-linter の forbidden contract / test_packaging_contract の厳密一致）。`ref` 1 件ごとに Python 起動コスト（数十 ms）と、同じ重いモジュールを複数の ref が指すときの重複 import が乗る。`--resolve` は明示的で稀な操作なので正しさを優先する。S1 は残る: 子は同じ権限で走るので、信頼できる `.jin` にだけ使う警告は README / CLAUDE.md / --help に残す。テストの stub 供給は `sys.path` 注入では子に届かないため `PYTHONPATH` 環境変数に切り替える。Phase 4 の hover は同じ子プロセス経路を拡張し、`jin_lsp` から `jin_cli.resolver` を import しない。
