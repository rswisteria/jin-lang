import { assertNever, type ViewState } from "../src/state/viewState";

/**
 * **分岐漏れがコンパイルエラーになること**の証拠（design.yaml machine 7）。
 *
 * 下の関数は `unavailable` の分岐を**わざと欠いている**。網羅性が効いていれば
 * `assertNever` の引数が `never` にならず tsc が落ちるので、`@ts-expect-error` が
 * 「エラーが出る」ことを主張できる。網羅性検査を緩めると
 * **`@ts-expect-error` が「使われていない」ことで tsc が赤になる**
 * （`pnpm typecheck` / `pnpm build` の両方で落ちる）。
 */
export function missingBranch(state: ViewState): string {
  switch (state.kind) {
    case "disconnected":
      return "1";
    case "loading":
      return "2";
    case "ready":
      return "3";
    case "stale":
      return "4";
    // `unavailable` を書かない。
  }
  // @ts-expect-error 分岐が 1 つ欠けているので state は never にならない
  return assertNever(state);
}
