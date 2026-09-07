import { describe as group, expect, test } from "vitest";

import { EMPTY_HISTORY, push, redo, undo } from "../src/state/history";

const A = { forward: [{ op: "setCore", pointer: "/circles/0", value: "x" }], inverse: [{ op: "setCore", pointer: "/circles/0", value: null }] };
const B = { forward: [{ op: "setRoot", pointer: "", value: "Sub" }], inverse: [{ op: "setRoot", pointer: "", value: "Main" }] };

group("undo / redo（要件書 §7.1 / §6.3）", () => {
  test("空のときは何も返さない", () => {
    expect(undo(EMPTY_HISTORY)).toBeNull();
    expect(redo(EMPTY_HISTORY)).toBeNull();
  });

  test("undo はサーバが返した逆オペレーション列を返す", () => {
    const history = push(EMPTY_HISTORY, A);
    const step = undo(history);
    expect(step?.ops).toEqual(A.inverse);
    expect(step?.history.undo).toEqual([]);
    expect(step?.history.redo).toEqual([A]);
  });

  test("redo は順オペレーション列を当て直す", () => {
    const step = redo(undo(push(EMPTY_HISTORY, A))!.history);
    expect(step?.ops).toEqual(A.forward);
    expect(step?.history.undo).toEqual([A]);
    expect(step?.history.redo).toEqual([]);
  });

  test("新しい編集で redo は捨てる（分岐した歴史を持たない）", () => {
    const after = undo(push(EMPTY_HISTORY, A))!.history;
    expect(after.redo).toEqual([A]);
    expect(push(after, B).redo).toEqual([]);
  });

  test("**モデルの写しを積まない**（積むのは 2 つのオペレーション列だけ）", () => {
    const entry = push(EMPTY_HISTORY, A).undo[0]!;
    expect(Object.keys(entry).sort()).toEqual(["forward", "inverse"]);
  });
});
