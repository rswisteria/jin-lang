import type { JinPointerRow, LspPosition } from "../rpc/protocol";

/**
 * pointer → LSP の位置（`textDocument/completion` に渡す）。
 *
 * `jin/model` の `pointers` は **`jin_core` の座標系**（1 始まり・コードポイント・end 排他）である。
 * LSP は 0 始まり・UTF-16 なので、その行のテキストで換算する（`jin_lsp.positions` と逆向きの
 * 同じ規則）。換算に要るのは**その行の先頭からリテラルの直前まで**の文字列だけである。
 *
 * 返すのは**リテラルの先頭（開き引用符）の位置**。`jin_lsp.locate.pointer_at` は「位置を含む
 * 最も狭い pointer」（start 込み）を選ぶので、この位置はその式の pointer に解決する。カーソル位置に
 * 応じた絞り込みはクライアント側の前置きで行う（`ExprEditor`）。
 */
export function lspPositionOf(
	pointers: readonly JinPointerRow[],
	text: string,
	pointer: string,
): LspPosition | null {
	const row = pointers.find((entry) => entry.pointer === pointer);
	if (row === undefined) return null;
	const line = text.split("\n")[row.start.line - 1];
	if (line === undefined) return null;
	// コードポイントで数えた列 → その手前の文字列の UTF-16 長。
	const before = [...line].slice(0, row.start.col - 1).join("");
	return { line: row.start.line - 1, character: before.length };
}
