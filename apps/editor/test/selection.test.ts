import { describe as group, expect, test } from "vitest";

import {
  followRename,
  resolveSelection,
  selectionFromPointer,
  type Selection,
} from "../src/state/selection";

const MODEL = {
  root: "Main",
  circles: [
    {
      name: "Main",
      core: "gemini-2.0-flash",
      instruction: { rune: "hello" },
      tools: [
        { name: "alpha", kind: "tool", ref: "m.a" },
        { name: "beta", kind: "tool", ref: "m.b" },
      ],
      state: [{ name: "memo", type: "string" }],
      delegate: ["Sub"],
      boundary: { guards: [{ on: "before_agent", ref: "g.h" }] },
    },
    { name: "Sub", core: "gemini-2.0-flash", tools: [{ name: "alpha", kind: "tool", ref: "s.a" }] },
  ],
};

group("選択の再解決（DP-COMMON-16）", () => {
  test("circle 名 + 種別 + 要素名から pointer を引ける", () => {
    expect(resolveSelection(MODEL, { circle: "Main", kind: "circle" })).toBe("/circles/0");
    expect(resolveSelection(MODEL, { circle: "Main", kind: "core" })).toBe("/circles/0/core");
    expect(resolveSelection(MODEL, { circle: "Main", kind: "rune" })).toBe(
      "/circles/0/instruction/rune",
    );
    expect(resolveSelection(MODEL, { circle: "Main", kind: "tool", name: "beta" })).toBe(
      "/circles/0/tools/1",
    );
    expect(resolveSelection(MODEL, { circle: "Main", kind: "state", name: "memo" })).toBe(
      "/circles/0/state/0",
    );
    expect(resolveSelection(MODEL, { circle: "Main", kind: "guard", name: "before_agent" })).toBe(
      "/circles/0/boundary/guards/0",
    );
  });

  test("**moveTool で並び替えても選択が追随する**（案 A の生 pointer 保持が壊れる場面）", () => {
    const selection: Selection = { circle: "Main", kind: "tool", name: "alpha" };
    expect(resolveSelection(MODEL, selection)).toBe("/circles/0/tools/0");
    const moved = {
      ...MODEL,
      circles: [
        { ...MODEL.circles[0], tools: [...MODEL.circles[0]!.tools!].reverse() },
        MODEL.circles[1],
      ],
    };
    expect(resolveSelection(moved, selection)).toBe("/circles/0/tools/1");
  });

  test("**同名 tool を持つ別 circle へ飛ばない**（tools[].name は circle 内でのみ一意）", () => {
    expect(resolveSelection(MODEL, { circle: "Sub", kind: "tool", name: "alpha" })).toBe(
      "/circles/1/tools/0",
    );
    expect(resolveSelection(MODEL, { circle: "Main", kind: "tool", name: "alpha" })).toBe(
      "/circles/0/tools/0",
    );
  });

  test("消えた要素は null（例外にしない）", () => {
    expect(resolveSelection(MODEL, { circle: "Main", kind: "tool", name: "none" })).toBeNull();
    expect(resolveSelection(MODEL, { circle: "None", kind: "circle" })).toBeNull();
  });

  test("pointer → 選択 → pointer で元に戻る", () => {
    for (const pointer of [
      "/circles/0",
      "/circles/0/core",
      "/circles/0/instruction/rune",
      "/circles/0/tools/1",
      "/circles/0/state/0",
      "/circles/0/delegate/0",
      "/circles/0/boundary/guards/0",
    ]) {
      const selection = selectionFromPointer(MODEL, pointer);
      expect(selection, pointer).not.toBeNull();
      expect(resolveSelection(MODEL, selection!)).toBe(pointer);
    }
  });
});

group("rename 直後の追随（DP-IMPL-JIN-P5-RENAME-FOLLOW-01）", () => {
  test("選択中の tool を rename すると新名へ追随する", () => {
    const selection: Selection = { circle: "Main", kind: "tool", name: "alpha" };
    const next = followRename(
      selection,
      { op: "rename", pointer: "/circles/0/tools/0", name: "gamma" },
      MODEL,
    );
    expect(next).toEqual({ circle: "Main", kind: "tool", name: "gamma" });
  });

  test("選択中の circle を rename すると circle 名が変わる", () => {
    const next = followRename(
      { circle: "Main", kind: "core" },
      { op: "rename", pointer: "/circles/0", name: "Root" },
      MODEL,
    );
    expect(next).toEqual({ circle: "Root", kind: "core" });
  });

  test("別の要素の rename では動かない", () => {
    const selection: Selection = { circle: "Main", kind: "tool", name: "alpha" };
    expect(
      followRename(selection, { op: "rename", pointer: "/circles/0/tools/1", name: "z" }, MODEL),
    ).toEqual(selection);
    expect(
      followRename(selection, { op: "rename", pointer: "/circles/1/tools/0", name: "z" }, MODEL),
    ).toEqual(selection);
  });

  test("rename 以外のオペレーションでは選択を触らない", () => {
    const selection: Selection = { circle: "Main", kind: "tool", name: "alpha" };
    expect(followRename(selection, { op: "moveTool", pointer: "/circles/0/tools/0" }, MODEL)).toBe(
      selection,
    );
  });
});
