import type { JinDiagnostic, JinModel, JinPointerRow } from "../rpc/protocol";

/**
 * エディタの表示状態（DP-COMMON-19 案 B・**5 状態**）。
 *
 * 一般的な「読込中 / 正常 / エラー」の 3 状態にしないのが本案件の要点である。
 * NFR-AVAIL-001 が「JSON 構文エラー中も直前の正常なモデルで renderSvg を提供する」を
 * 要求しており、**「エラーだが図は出せる」**という第 4 の状態が実在する。
 * これを `ready` と混ぜると、ユーザーは古い図を現在の状態だと誤認する。
 * 接続断（`disconnected`）とファイル不正（`unavailable`）も別物で、次に取るべき行動が違う。
 *
 * 分岐は `switch` を `default` 無しで書き、最後に `assertNever` を置く。
 * 状態を増やして分岐を足し忘れると **tsc が落ちる**（design.yaml machine 7）。
 */
export type ViewState =
  /** (1) LSP 未接続・接続中。 */
  | { readonly kind: "disconnected"; readonly reason: string | null }
  /** (2) モデル取得中。 */
  | { readonly kind: "loading"; readonly uri: string }
  /** (3) 正常表示。 */
  | {
      readonly kind: "ready";
      readonly uri: string;
      readonly model: JinModel;
      readonly pointers: readonly JinPointerRow[];
      readonly svg: string;
      readonly diagnostics: readonly JinDiagnostic[];
    }
  /** (4) ステイル表示。構文エラー中で、**直前の正常モデル**を出していることを画面に明示する。 */
  | {
      readonly kind: "stale";
      readonly uri: string;
      readonly model: JinModel;
      readonly pointers: readonly JinPointerRow[];
      readonly svg: string;
      readonly diagnostics: readonly JinDiagnostic[];
    }
  /** (5) 表示不能。正常なモデルが 1 度も得られていない。 */
  | { readonly kind: "unavailable"; readonly uri: string; readonly message: string };

/**
 * DP-COMMON-19 で確定した状態名の集合。
 *
 * `test/viewState.test.ts` がこの配列と `ViewState["kind"]` の等号を型と実行時の
 * 両方で固定する。**3 に減らすことも、名前を黙って変えることもできない**。
 */
export const VIEW_STATE_KINDS = [
  "disconnected",
  "loading",
  "ready",
  "stale",
  "unavailable",
] as const satisfies readonly ViewState["kind"][];

/** 網羅性の番人。`switch` に `default` を書かず、末尾でこれを呼ぶ。 */
export function assertNever(value: never): never {
  throw new Error(`分岐漏れ: ${JSON.stringify(value)}`);
}

/** 図（SVG）を出してよい状態か。`ready` と `stale` だけが真。 */
export function hasDrawing(
  state: ViewState,
): state is Extract<ViewState, { kind: "ready" | "stale" }> {
  switch (state.kind) {
    case "ready":
    case "stale":
      return true;
    case "disconnected":
    case "loading":
    case "unavailable":
      return false;
  }
  return assertNever(state);
}

/** 画面上部に出す 1 行。状態を**黙って潰さない**（NFR-FAIL-001）。 */
export function describe(state: ViewState): string {
  switch (state.kind) {
    case "disconnected":
      return state.reason === null
        ? "LSP に接続していません"
        : `LSP に接続していません: ${state.reason}`;
    case "loading":
      return "モデルを取得しています…";
    case "ready":
      return "正常";
    case "stale":
      return "構文エラーのため、直前の正常な版を表示しています（この図は現在のファイルではありません）";
    case "unavailable":
      return `表示できません: ${state.message}`;
  }
  return assertNever(state);
}
