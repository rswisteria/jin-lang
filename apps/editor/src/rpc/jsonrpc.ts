import {
  type Logger,
  type MessageConnection,
  NotificationType,
  RequestType,
} from "vscode-jsonrpc";
import { createWebSocketConnection, type IWebSocket } from "vscode-ws-jsonrpc";

/**
 * DP-COMMON-17 案 B の「JSON-RPC クライアント 1 層」。
 *
 * pygls 2.1.1 の ws は **1 WebSocket フレーム = 1 JSON オブジェクト**で話す
 * （`pygls.io_.run_websocket` が `protocol.set_writer(..., include_headers=False)` を
 * 呼んでいることを実測。`Content-Length` ヘッダは付かない）。
 * `vscode-ws-jsonrpc` の `createWebSocketConnection` はこの形をそのまま扱う。
 *
 * この層より上（`./jin.ts`）だけがアプリから見える。**モックの境界は `./jin.ts` 1 本**で、
 * ここと WebSocket はモックしない（DP-COMMON-20 の replaceability）。
 */

/**
 * ブラウザの `WebSocket` を `vscode-ws-jsonrpc` の `IWebSocket` に合わせる。
 *
 * **pygls 2.1.1 は JSON を binary フレームで送る**（`pygls.io_.WebSocketWriter` が
 * `body.encode()` した bytes を `websockets` に渡す・2026-09-07 実測）。ブラウザの
 * `WebSocket` は既定でそれを `Blob` として渡すので、そのまま
 * `vscode-ws-jsonrpc` の `WebSocketMessageReader` に流すと `JSON.parse(Blob)` が
 * `"[object Blob]"` を食って失敗する。失敗は `fireError` に落ちるだけで
 * **リクエストの Promise は永久に pending のまま**になり、画面が白いまま何も出ない
 * （実測で踏んだ）。`binaryType` を `arraybuffer` にして自分で復号する。
 */
export function toIWebSocket(socket: WebSocket): IWebSocket {
  socket.binaryType = "arraybuffer";
  const decoder = new TextDecoder();
  return {
    send: (content) => socket.send(content),
    onMessage: (cb) => {
      socket.onmessage = (event: MessageEvent<string | ArrayBuffer>) => {
        const data = event.data;
        cb(typeof data === "string" ? data : decoder.decode(data));
      };
    },
    onError: (cb) => {
      socket.onerror = (event) => cb(event);
    },
    onClose: (cb) => {
      socket.onclose = (event) => cb(event.code, event.reason);
    },
    dispose: () => socket.close(),
  };
}

/** `console` を `vscode-jsonrpc` の `Logger` に合わせる。 */
const consoleLogger: Logger = {
  error: (message) => console.error(message),
  warn: (message) => console.warn(message),
  info: (message) => console.info(message),
  log: (message) => console.log(message),
};

export interface RpcClient {
  request<P, R>(method: string, params: P): Promise<R>;
  onNotification<P>(method: string, handler: (params: P) => void): void;
  dispose(): void;
}

class ConnectionClient implements RpcClient {
  constructor(private readonly connection: MessageConnection) {}

  request<P, R>(method: string, params: P): Promise<R> {
    return this.connection.sendRequest(new RequestType<P, R, void>(method), params);
  }

  onNotification<P>(method: string, handler: (params: P) => void): void {
    this.connection.onNotification(new NotificationType<P>(method), handler);
  }

  dispose(): void {
    this.connection.dispose();
  }
}

/** 接続を張り、LSP の `initialize` → `initialized` まで済ませて返す。 */
export async function connect(url: string): Promise<RpcClient> {
  const socket = await openSocket(url);
  const connection = createWebSocketConnection(toIWebSocket(socket), consoleLogger);
  connection.listen();
  const client = new ConnectionClient(connection);

  // `workspace/applyEdit` を**宣言しない**。宣言しないとサーバは
  // `jin/applyOps` の応答を `applied: false` + `text` で返し、こちらへ要求を送らない
  // （`jin_lsp.server._client_applies_edits` を実測）。
  // サーバは応答を返す前に `analyze_now` で自分の記憶を新テキストへ更新するので、
  // エディタが `didChange` を送り返す必要は無い。
  // **握手にはタイムアウトを付ける**（NFR-FAIL-001「黙って落とさない」）。
  // 応答が来ない形の不具合は画面が白いまま何も起きないので、原因が分からない。
  await withTimeout(
    client.request("initialize", {
      processId: null,
      clientInfo: { name: "jin-editor", version: "0.1.0" },
      rootUri: null,
      capabilities: { workspace: {}, textDocument: { publishDiagnostics: {} } },
    }),
    HANDSHAKE_TIMEOUT_MS,
    "LSP の initialize に応答がありません",
  );
  connection.sendNotification(new NotificationType("initialized"), {});
  return client;
}

/** 握手の待ち時間。`jin_core.check` の最悪ケース（敵対的な入力で 5.1 秒）に余裕を見た値。 */
export const HANDSHAKE_TIMEOUT_MS = 15_000;

function withTimeout<T>(promise: Promise<T>, ms: number, message: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`${message}（${ms} ms）`)), ms);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error: unknown) => {
        clearTimeout(timer);
        reject(error instanceof Error ? error : new Error(String(error)));
      },
    );
  });
}

function openSocket(url: string): Promise<WebSocket> {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(url);
    socket.onopen = () => resolve(socket);
    socket.onerror = () => reject(new Error(`WebSocket に接続できません: ${url}`));
  });
}
