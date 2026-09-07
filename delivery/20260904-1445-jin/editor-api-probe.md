# エディタ側 API の実測（editor-api-probe.md）

> Phase 5（`apps/editor`）で**記憶で書かずに実測した**もの。
> `adk-api-probe.md` / `lsp-api-probe.md` と同じ役割の一次証拠である。
> 測定日は 2026-09-07、macOS 15（arm64）/ Node v22.12.0 / pnpm 10.15.1。

## 1. 版の選定（`npm view` で実測）

| パッケージ | 入れた版 | 最新 | 選んだ理由 |
|---|---|---|---|
| `typescript` | **5.9.3** | 7.0.2 | `typescript-eslint@8.69.0` の `peerDependencies.typescript` が **`>=4.8.4 <6.1.0`**。TS 7 系は linter が対応していない（実測）。6.0.3 も範囲内だが、vite 8 / vitest 5 と組み合わせた実績のある 5 系の最終版を採った |
| `typescript-eslint` | 8.69.0 | 8.69.0 | `dist-tags` に 9 系は無い（`latest` が 8.69.0） |
| `eslint` | 10.10.0 | 10.10.0 | 上の peer が `^10.0.0` を含む |
| `vite` | 8.2.2 | 8.2.2 | `@vitejs/plugin-react@6.1.1` の peer が `vite ^8.0.0` |
| `vitest` | 5.0.0 | 5.0.0 | peer が `vite ^6.4.0 \|\| ^7 \|\| ^8` |
| `react` / `react-dom` | 19.2.8 | 19.2.8 | |
| `vscode-jsonrpc` | **8.2.1** | 9.0.2 | `vscode-ws-jsonrpc@3.5.0` が `vscode-jsonrpc ~8.2.1` に**固定**している。9 系を別に入れると 2 版が同居する |
| `@playwright/test` | **1.62.0** | 1.63.0 | 1.63.0 が要求する chromium 1243 を、この環境では CDN から取得できなかった（`playwright install` が 30 秒で 8 回連続タイムアウト。実体 URL への直接 `curl` は 5 MB を 1.2 秒で取れるので回線ではなく downloader 側）。`playwright-core@1.62.0` の `browsers.json` が指す chromium 1234 は取得済みだったので 1.62.0 に固定した。CI は自前で `playwright install` するのでこの制約は掛からない |

依存は**すべて完全一致**で書く（`^` / `~` を使わない）。レンダラの出力や LSP の応答と
バイト比較するテストがあるので、ツールチェーンが黙って動くと切り分けができない。
`tests/contract/test_editor_contract.py::test_every_dependency_is_pinned_to_an_exact_version` が固定する。

## 2. pygls 2.1.1 の ws は **binary フレーム**で JSON を送る

`pygls.io_.run_websocket` は

```python
protocol.set_writer(WebSocketWriter(websocket), include_headers=False)
```

を呼ぶ。つまり **1 WebSocket メッセージ = 1 JSON オブジェクト**で、
`Content-Length` ヘッダは付かない（stdio と違う）。ここまでは `vscode-ws-jsonrpc` の
前提と一致する。

**問題は本文の型である。** `WebSocketWriter` は `bytes` を送るので、フレームは binary になる。
ブラウザの `WebSocket` は既定（`binaryType = "blob"`）でそれを `Blob` として渡すため、
`WebSocketMessageReader.readMessage` の `JSON.parse(message)` が
**`"[object Blob]"` を食って失敗する**。失敗は `fireError` に落ちるだけなので、

- コンソールにエラーが出ない
- `sendRequest` の Promise が**永久に pending** のまま
- 画面が白いまま、何も起こらない

という形になる（実測で 30 分溶かした）。対策は `socket.binaryType = "arraybuffer"` にして
`TextDecoder` で復号すること。`apps/editor/src/rpc/jsonrpc.ts` の `toIWebSocket` が行う。
あわせて `initialize` に **15 秒のタイムアウト**を付けた（NFR-FAIL-001「黙って落とさない」）。

## 3. pygls 2.1.1 の `start_ws` は **1 接続で終わる**

```python
async def lsp_connection(websocket):
    await run_websocket(...)
    self.shutdown()          # ← 接続が閉じた直後
```

`shutdown()` は `self._server.close()` を呼ぶので、**クライアントが 1 回切断すると
待ち受けごと消える**。ブラウザのエディタでは「ページを再読み込みしたら死ぬ」ことになる
（Playwright の 2 本目のページ読み込みが `ERR_CONNECTION_REFUSED` になって発覚）。

`JinLanguageServer.serve_ws` は `websockets.asyncio.server.serve` を直接使い、
接続ごとに `pygls.io_.run_websocket` を回して `shutdown()` を呼ばない。
**`stop_event` は接続ごとに作り直す**（使い回すと 1 本目の切断で set されたまま残り、
2 本目が受信ループに入らずに即座に抜ける）。

`jin lsp --ws` もこちらを使う。再発検知は
`packages/jin-lsp/tests/test_ws_roundtrip.py::test_the_server_survives_a_client_reconnect`
（生の `websockets` で 3 回張り直す。**LSP の `shutdown` / `exit` は送らない** —
それを受けたサーバが終了するのは正しい挙動であって、直したい欠陥ではない）。

## 4. `SimpleHTTPRequestHandler` の既定は HTTP/1.0

`BaseHTTPRequestHandler.protocol_version` の既定は `"HTTP/1.0"` で、応答ごとに接続を閉じる。
ブラウザが張りっぱなしのソケットを再利用しようとすると `ERR_CONNECTION_RESET` になる
（Playwright の 2 本目のページ読み込みで実測）。`SimpleHTTPRequestHandler` は
`Content-Length` を必ず付けるので `HTTP/1.1` に上げてよい。

`directory=` を渡さないと **cwd を配る**。`jin editor` は `dist` に固定する。

## 5. レンダラの SVG は全部 `fill="none"` の線画である

`docs/spec/layout.md` のとおり、`jin render` の出力は塗りを持たない。
既定の `pointer-events: visiblePainted` では **1 px の線の上しか当たらない**ので、
環をクリックしても `<svg>` に抜ける（Playwright が
「`<svg …> intercepts pointer events`」で click を拒む形で実測）。

エディタ側の CSS で `[data-jin] { pointer-events: all; }` にして図形の内側も当たるようにした。
**これは描画の変更ではない**（塗りは足していない。当たり判定だけを広げている）。
重なりは SVG の規則どおり後から描かれた要素が勝つので、紋は環より優先される
（核と紋は実クリックで選べる。環そのものは中身に覆われるので、
ユーザーは線の上をクリックすることになる）。

## 6. Playwright のフックは第 1 引数にオブジェクトの分割代入を要求する

`test.afterEach((fixtures, testInfo) => …)` と書くと**起動時に**
`First argument must use the object destructuring pattern: fixtures` で落ちる。
`({}, testInfo)` と書く必要があり、そちらは eslint の `no-empty-pattern` に当たるので
`eslint-disable-next-line` を 1 行入れている。
