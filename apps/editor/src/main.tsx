import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import schema from "../../../schemas/jin.schema.json";
import type { JsonSchema } from "./form/schemaForm";
import { createJinApi } from "./rpc/jin";
import { connect } from "./rpc/jsonrpc";
import "./style.css";

/**
 * 単一ページ SPA のエントリ（DP-COMMON-18 案 A）。ルーティングは持たない。
 *
 * 接続先とファイルは **URL** から受ける（DP-COMMON-18 の replaceability）:
 *
 * - クエリ `?ws=<url>&uri=<file uri>`
 * - フラグメント `#token=<起動トークン>`
 *
 * **トークンをフラグメントに置くのは、フラグメントが HTTP 要求にも `Referer` にも
 * 載らないからである**（`jin editor` が配る静的サーバのログにも出ない）。
 * 残存: ブラウザの履歴には残り、同じページの JS からは読める。
 *
 * `schemas/jin.schema.json` は**コピーせずに直接読む**（要件書 §7.1 の
 * 「フォームは JSON Schema から生成する」。コピーを置くとドリフトする）。
 */
const params = new URLSearchParams(window.location.search);
const fragment = new URLSearchParams(window.location.hash.replace(/^#/, ""));
const wsUrl = params.get("ws") ?? `ws://${window.location.hostname}:8765`;
const uri = params.get("uri") ?? "";
const token = fragment.get("token") ?? "";

const container = document.getElementById("root");
if (container === null) throw new Error("#root がありません");
const root = createRoot(container);

if (uri === "") {
	root.render(
		<p className="jin-hint">
			開くファイルが指定されていません（?uri=file:///... ）。
		</p>,
	);
} else {
	connect(wsUrl)
		.then((client) => {
			root.render(
				<StrictMode>
					<App
						api={createJinApi(client, token)}
						uri={uri}
						schema={schema as JsonSchema}
						// 実行エンドポイント（Issue #34）は**このページを配っているのと同じ origin**
						// にある（`jin editor` の静的サーバ）。別の場所を指せるようにしない。
						runOrigin={window.location.origin}
						token={token}
					/>
				</StrictMode>,
			);
		})
		.catch((error: unknown) => {
			root.render(
				<p className="jin-hint">
					LSP に接続できません（{wsUrl}）:{" "}
					{error instanceof Error ? error.message : String(error)}
				</p>,
			);
		});
}
