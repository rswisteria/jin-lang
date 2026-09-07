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

/** モデルは `schemas/jin.schema.json` が定める JSON。エディタは**中身を解釈しない**。 */
export type JinModel = Readonly<Record<string, unknown>>;

export interface JinModelResult {
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
  | {
      readonly ok: true;
      readonly model: JinModel;
      readonly inverses: readonly JinOp[];
      readonly text: string;
      readonly applied: boolean;
      readonly diagnostics: readonly JinDiagnostic[];
    }
  | { readonly ok: false; readonly error: JinOpError };

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
