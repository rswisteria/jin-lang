import type { RpcClient } from "./jsonrpc";
import {
  JIN_METHOD,
  type JinApplyOpsResult,
  type JinDiagnostic,
  type JinModelResult,
  type JinOp,
  type JinOpenResult,
  type JinOpsResult,
  type JinRenderSvgResult,
  type JinSaveResult,
  type LspCompletionItem,
  type LspPosition,
} from "./protocol";

/**
 * DP-COMMON-17 案 B の「Jin 固有リクエストの型付きラッパ」。
 *
 * **UI はこのインタフェースの関数だけを呼ぶ**。JSON-RPC 層や WebSocket を直接触らない。
 * DP-COMMON-20 が定めるモックの境界もここ 1 本である。
 */
export interface JinApi {
  open(uri: string): Promise<JinOpenResult>;
  save(uri: string, text?: string): Promise<JinSaveResult>;
  model(uri: string): Promise<JinModelResult>;
  renderSvg(uri: string, options?: RenderOptions): Promise<JinRenderSvgResult>;
  ops(): Promise<JinOpsResult>;
  applyOps(uri: string, ops: readonly JinOp[]): Promise<JinApplyOpsResult>;
  /**
   * LSP **標準**の `textDocument/completion`（`jin/…` は 6 種のまま増えない）。
   * v2 の式エディタが候補を得るのに使う（設計書 §8「補完候補は LSP の completion をそのまま使う」）。
   */
  complete(uri: string, position: LspPosition): Promise<readonly LspCompletionItem[]>;
  onDiagnostics(handler: (uri: string, diagnostics: readonly JinDiagnostic[]) => void): void;
  dispose(): void;
}

export interface RenderOptions {
  readonly focus?: string | undefined;
  readonly trace?: readonly Record<string, unknown>[] | undefined;
  readonly upto?: number | undefined;
}

/**
 * LSP の `publishDiagnostics` は LSP 座標（0 始まり・UTF-16）で来るが、
 * `jin/open` / `jin/save` / `jin/applyOps` の応答に載る診断は
 * **`jin_core` の座標のまま**（1 始まり・コードポイント）である。
 * エディタが表示に使うのは後者だけにして、座標系を 1 つに保つ。
 * SVG 上のバッジは pointer で引くので、そもそも行・列を使わない。
 */
export function createJinApi(client: RpcClient, token: string): JinApi {
  return {
    open: (uri) => client.request(JIN_METHOD.open, { uri, token }),
    save: (uri, text) =>
      client.request(JIN_METHOD.save, text === undefined ? { uri, token } : { uri, token, text }),
    model: (uri) => client.request(JIN_METHOD.model, { uri }),
    renderSvg: (uri, options) => client.request(JIN_METHOD.renderSvg, { uri, ...options }),
    ops: () => client.request(JIN_METHOD.ops, {}),
    applyOps: (uri, ops) => client.request(JIN_METHOD.applyOps, { uri, ops }),
    complete: async (uri, position) => {
      const result = await client.request<
        { textDocument: { uri: string }; position: LspPosition },
        readonly LspCompletionItem[] | { items: readonly LspCompletionItem[] } | null
      >("textDocument/completion", { textDocument: { uri }, position });
      if (result === null) return [];
      return Array.isArray(result) ? result : (result as { items: readonly LspCompletionItem[] }).items;
    },
    onDiagnostics: (handler) => {
      client.onNotification<{ uri: string; diagnostics: readonly JinDiagnostic[] }>(
        "textDocument/publishDiagnostics",
        (params) => handler(params.uri, params.diagnostics),
      );
    },
    dispose: () => client.dispose(),
  };
}
