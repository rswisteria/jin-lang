import { describe as group, expect, test } from "vitest";

import { assertNever, describe, hasDrawing, VIEW_STATE_KINDS, type ViewState } from "../src/state/viewState";

/**
 * DP-COMMON-19 の 5 状態（design.yaml machine 7）。
 *
 * **状態数を 3 に固定しない**ことがこの判断の要点なので、
 * 「5 つある」ことと「分岐漏れがコンパイルエラーになる」ことを別々に固定する。
 * 後者は `test/exhaustiveness.fixture.ts` が `@ts-expect-error` で受け持つ
 * （tsc が**落ちないと**赤になる形）。
 */
group("表示状態の集合", () => {
  test("DP-COMMON-19 が確定した 5 つと過不足なく一致する", () => {
    expect([...VIEW_STATE_KINDS]).toEqual([
      "disconnected",
      "loading",
      "ready",
      "stale",
      "unavailable",
    ]);
  });

  test("3 状態に潰れていない（読込中 / 正常 / エラーの 3 つではない）", () => {
    expect(VIEW_STATE_KINDS.length).toBe(5);
  });

  test("ステイルは正常と別の文言で伝わる（古い図を現在の状態と誤認させない）", () => {
    const ready: ViewState = {
      kind: "ready",
      uri: "file:///a.jin",
      model: {},
      pointers: [],
      svg: "<svg/>",
      diagnostics: [],
    };
    const stale: ViewState = { ...ready, kind: "stale" };
    expect(describe(ready)).not.toBe(describe(stale));
    expect(describe(stale)).toContain("直前の正常な版");
  });

  test("図を出せるのは ready と stale だけ", () => {
    const base = { uri: "file:///a.jin", model: {}, pointers: [], svg: "<svg/>", diagnostics: [] };
    expect(hasDrawing({ kind: "ready", ...base })).toBe(true);
    expect(hasDrawing({ kind: "stale", ...base })).toBe(true);
    expect(hasDrawing({ kind: "loading", uri: base.uri })).toBe(false);
    expect(hasDrawing({ kind: "disconnected", reason: null })).toBe(false);
    expect(hasDrawing({ kind: "unavailable", uri: base.uri, message: "x" })).toBe(false);
  });

  test("assertNever は黙って通らない（分岐漏れが実行時にも露見する）", () => {
    expect(() => assertNever({ kind: "zzz" } as never)).toThrow(/分岐漏れ/);
  });
});
