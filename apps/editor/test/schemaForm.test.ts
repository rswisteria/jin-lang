import { describe as group, expect, test } from "vitest";

import schema from "../../../schemas/jin.schema.json";
import { fieldsForSelection, opsForChange, schemaFor } from "../src/form/dispatch";
import { fieldsOf, resolveRef, type JsonSchema } from "../src/form/schemaForm";

const ROOT = schema as JsonSchema;

const MODEL = {
  root: "Main",
  circles: [
    {
      name: "Main",
      core: "gemini-2.0-flash",
      instruction: { rune: "hi" },
      tools: [
        { name: "alpha", kind: "tool", ref: "m.a" },
        { name: "web", kind: "builtin", builtin: "google_search" },
      ],
      state: [{ name: "memo", type: "string", out: false }],
      boundary: { guards: [{ on: "before_agent", ref: "g.h" }] },
    },
  ],
};

group("フォームは JSON Schema から生成される（要件書 §7.1）", () => {
  test("**schema にキーを足すと欄が増える**（手書きの欄一覧を持っていない証拠）", () => {
    const state = resolveRef(ROOT, "#/$defs/State")!;
    const before = fieldsOf(ROOT, state).map((field) => field.key);
    const probed: JsonSchema = {
      ...state,
      properties: { ...state.properties, zzz_probe: { type: "string", title: "Zzz Probe" } },
    };
    const after = fieldsOf(ROOT, probed).map((field) => field.key);
    expect(before).not.toContain("zzz_probe");
    expect(after).toEqual([...before, "zzz_probe"]);
  });

  test("欄の型・必須・最大長・選択肢を schema から読む", () => {
    const fields = fieldsOf(ROOT, resolveRef(ROOT, "#/$defs/State")!);
    expect(fields.map((f) => [f.key, f.type, f.required])).toEqual([
      ["name", "string", true],
      ["type", "string", true],
      ["out", "boolean", false],
    ]);
    expect(fields[0]!.maxLength).toBe(128);

    const guard = fieldsOf(ROOT, resolveRef(ROOT, "#/$defs/Guard")!);
    expect(guard[0]!.type).toBe("enum");
    expect(guard[0]!.options).toEqual([
      "before_agent",
      "after_agent",
      "before_model",
      "after_model",
      "before_tool",
      "after_tool",
    ]);
  });

  test("配列・オブジェクトは欄にしない（図の操作で編集する）", () => {
    const circle = fieldsOf(ROOT, resolveRef(ROOT, "#/$defs/Circle")!).map((f) => f.key);
    expect(circle).toEqual(["name", "core", "description"]);
    expect(circle).not.toContain("tools");
    expect(circle).not.toContain("flow");
  });

  test("tools の判別共用体は値の kind で枝を選ぶ", () => {
    const asTool = fieldsForSelection(ROOT, { circle: "Main", kind: "tool", name: "alpha" }, MODEL.circles[0]!.tools[0]).map((f) => f.key);
    const asBuiltin = fieldsForSelection(ROOT, { circle: "Main", kind: "tool", name: "web" }, MODEL.circles[0]!.tools[1]).map((f) => f.key);
    expect(asTool).toEqual(["name", "kind", "ref"]);
    expect(asBuiltin).toEqual(["name", "kind", "builtin"]);
  });

  test("const の欄（kind）は読み取り専用になる", () => {
    const fields = fieldsForSelection(ROOT, { circle: "Main", kind: "tool", name: "alpha" }, MODEL.circles[0]!.tools[0]);
    expect(fields.find((f) => f.key === "kind")?.readOnly).toBe(true);
    expect(fields.find((f) => f.key === "ref")?.readOnly).toBe(false);
  });

  test("core / rune は 1 欄だけの足場を schema から作る", () => {
    expect(fieldsForSelection(ROOT, { circle: "Main", kind: "core" }, null).map((f) => f.key)).toEqual(["core"]);
    expect(fieldsForSelection(ROOT, { circle: "Main", kind: "rune" }, null).map((f) => f.key)).toEqual(["rune"]);
    expect(schemaFor(ROOT, { circle: "Main", kind: "delegate", name: "Sub" }, null)).toBeNull();
  });
});

group("欄の変更 → オペレーション（20 個目を作らない）", () => {
  test("引数のキーは jin_core.ops に合わせて value / index である", () => {
    expect(opsForChange(MODEL, { circle: "Main", kind: "core" }, { key: "core", value: "x" })).toEqual([
      { op: "setCore", pointer: "/circles/0", value: "x" },
    ]);
    expect(opsForChange(MODEL, { circle: "Main", kind: "rune" }, { key: "rune", value: "y" })).toEqual([
      { op: "setRune", pointer: "/circles/0", value: "y" },
    ]);
  });

  test("空欄は null（core を消せる）", () => {
    expect(opsForChange(MODEL, { circle: "Main", kind: "core" }, { key: "core", value: "" })).toEqual([
      { op: "setCore", pointer: "/circles/0", value: null },
    ]);
  });

  test("名前の変更は rename（参照追随はサーバが行う）", () => {
    expect(
      opsForChange(MODEL, { circle: "Main", kind: "tool", name: "alpha" }, { key: "name", value: "zeta" }),
    ).toEqual([{ op: "rename", pointer: "/circles/0/tools/0", value: "zeta" }]);
  });

  test("**tool の ref は removeTool + addTool の合成で書く**（専用オペレーションを増やさない）", () => {
    expect(
      opsForChange(MODEL, { circle: "Main", kind: "tool", name: "alpha" }, { key: "ref", value: "m.z" }),
    ).toEqual([
      { op: "removeTool", pointer: "/circles/0/tools/0" },
      {
        op: "addTool",
        pointer: "/circles/0/tools",
        index: 0,
        value: { name: "alpha", kind: "tool", ref: "m.z" },
      },
    ]);
  });

  test("guard は setGuard で全体を置き換える", () => {
    expect(
      opsForChange(MODEL, { circle: "Main", kind: "guard", name: "before_agent" }, { key: "ref", value: "g.z" }),
    ).toEqual([
      { op: "setGuard", pointer: "/circles/0/boundary/guards/0", value: { on: "before_agent", ref: "g.z" } },
    ]);
  });

  test("書けない欄は空配列（黙って握り潰さない）", () => {
    expect(opsForChange(MODEL, { circle: "Main", kind: "delegate", name: "Sub" }, { key: "x", value: "y" })).toEqual([]);
    expect(opsForChange(MODEL, { circle: "None", kind: "circle" }, { key: "name", value: "y" })).toEqual([]);
  });
});
