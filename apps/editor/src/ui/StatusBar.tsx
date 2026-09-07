import { describe, type ViewState } from "../state/viewState";

/**
 * 表示状態を 1 行で伝える（DP-COMMON-19）。
 *
 * **ステイルを正常と同じ見た目にしない。** 古い図を現在の状態だと誤認させないための
 * 唯一の手掛かりがここである（NFR-AVAIL-001 / NFR-FAIL-001）。
 */
export function StatusBar({ state }: { readonly state: ViewState }): React.JSX.Element {
  return (
    <p className={`jin-status jin-status-${state.kind}`} data-testid="jin-status" data-state={state.kind}>
      {describe(state)}
    </p>
  );
}
