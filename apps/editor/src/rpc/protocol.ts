/**
 * `jin lsp --ws` が話す独自リクエストの型（要件書 §6.3 / `docs/spec/ops.md` §5）。
 *
 * **サーバ側 Python との二重管理**であることは DP-COMMON-17 の案 B が受け入れた
 * コストである。ドリフトの監視点を 1 箇所にするため、
 * `tests/fixtures/lsp-responses/*.json`（実サーバの応答を pytest が書き出したもの）を
 * `test/protocol.test.ts` が**この型で読む**。型を変えて実応答とずれれば赤くなる。
 */

/** 診断の位置。**1 始まり・コードポイント単位・end 排他**（`docs/spec/diagnostics.md` §5.1）。 */
export interface JinPosition {
	readonly line: number;
	readonly col: number;
}

export interface JinRange {
	readonly start: JinPosition;
	readonly end: JinPosition;
}

export type JinSeverity = "error" | "warning" | "info";

/** 要件書 §5 の診断 JSON に 1:1 対応する。 */
export interface JinDiagnostic {
	readonly file: string;
	readonly pointer: string;
	readonly range: JinRange;
	readonly code: string;
	readonly severity: JinSeverity;
	readonly message: string;
	readonly hint?: string;
}

/**
 * pointer → range の対応表の 1 行。
 *
 * **配列であって辞書ではない**（DP-IMPL-JIN-P4-POINTER-SHAPE-01）。JSON Pointer は
 * `/` を含むので、クライアントによってはオブジェクトのキーとして往復しない。
 */
export interface JinPointerRow extends JinRange {
	readonly pointer: string;
}

/**
 * モデルは `schemas/jin.schema.json`（v1）/ `schemas/jin-v2.schema.json`（v2）が定める JSON。
 * エディタは**中身を解釈しない**（版の判定は `version` の値だけを見る）。
 */
export type JinModel = Readonly<Record<string, unknown>>;

/** `jin build` が書く `game.manifest.json` と同じ形（`docs/spec/v2/runtime.md` §9）。 */
export interface JinManifest {
	readonly file: string | null;
	readonly stage: {
		readonly width: number;
		readonly height: number;
		readonly fps: number;
		readonly seed: number;
	};
	readonly namespaces: readonly string[];
	readonly assets: readonly {
		readonly name: string;
		readonly kind: string;
		readonly path: string;
	}[];
	readonly debug: boolean;
	readonly jil: string;
}

/**
 * Jin v2（`version: 2`）のときだけ応答に加わる **JIL（`game.lua`）と manifest**
 * （設計書 §8「ライブリロード」・Phase 5）。実行パネルはこれを `/play/` の iframe へ
 * `postMessage`（`jin.load`）して、保存せずに動かす。
 *
 * **best-effort** である: `applyOps` は通ったが式の構文 / 型エラーが残っている
 * （`docs/spec/v2/ops.md` §1）と `jil` は `null` になり、理由が `jilError` に載る。
 */
export interface JinGenerated {
	readonly jil?: string | null;
	readonly manifest?: JinManifest | null;
	readonly jilError?: string | null;
}

export interface JinModelResult extends JinGenerated {
	readonly model: JinModel;
	readonly pointers: readonly JinPointerRow[];
	/** 真なら「現在のテキストが壊れていて直前の正常なモデルで答えた」（NFR-AVAIL-001）。 */
	readonly stale: boolean;
}

export interface JinRenderSvgResult {
	readonly svg: string;
	readonly stale: boolean;
}

export interface JinOperationSpec {
	readonly name: string;
	readonly target: string;
	readonly inverse: string;
}

export interface JinOpsResult {
	readonly operations: readonly JinOperationSpec[];
}

/** 意味編集オペレーション 1 件（`docs/spec/ops.md` §2）。**19 件を 20 件にしない**。 */
export interface JinOp {
	readonly op: string;
	readonly pointer?: string;
	readonly [key: string]: unknown;
}

export interface JinOpError {
	readonly code: string;
	readonly message: string;
	readonly hint?: string | null;
	readonly pointer?: string | null;
}

export type JinApplyOpsResult =
	| ({
			readonly ok: true;
			readonly model: JinModel;
			readonly inverses: readonly JinOp[];
			readonly text: string;
			readonly applied: boolean;
			readonly diagnostics: readonly JinDiagnostic[];
			/** v2 だけ: `rename` が追随できなかった式の pointer（`docs/spec/v2/ops.md` §3）。 */
			readonly warnings?: readonly string[];
	  } & JinGenerated)
	| { readonly ok: false; readonly error: JinOpError };

/** LSP 標準の位置（0 始まり・UTF-16）。`jin_lsp.positions` と同じ向きの換算を `v2/position.ts` が行う。 */
export interface LspPosition {
	readonly line: number;
	readonly character: number;
}

/** `textDocument/completion` の 1 候補。使うのは `label` / `kind` / `detail` だけ。 */
export interface LspCompletionItem {
	readonly label: string;
	readonly kind?: number;
	readonly detail?: string;
}

export interface JinOpenResult {
	readonly uri: string;
	readonly text: string;
	readonly diagnostics: readonly JinDiagnostic[];
}

export interface JinSaveResult {
	readonly uri: string;
	readonly path: string;
	readonly text: string;
	readonly diagnostics: readonly JinDiagnostic[];
}

/** メソッド名は 1 箇所にだけ書く（綴り間違いを型で拾う）。 */
export const JIN_METHOD = {
	model: "jin/model",
	renderSvg: "jin/renderSvg",
	ops: "jin/ops",
	applyOps: "jin/applyOps",
	open: "jin/open",
	save: "jin/save",
} as const;
