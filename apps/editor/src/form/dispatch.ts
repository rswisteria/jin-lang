import type { JinModel, JinOp } from "../rpc/protocol";
import type { Selection } from "../state/selection";
import { resolveSelection } from "../state/selection";
import type { JsonSchema } from "./schemaForm";
import { branchFor, fieldsOf, resolveRef, unwrap } from "./schemaForm";

/**
 * 「どの欄をどのオペレーションで書くか」の対応表。
 *
 * **これはフォーム定義ではない**（欄の一覧は `schemaForm.ts` が schema から作る）。
 * ここにあるのは *書き込み経路*、つまり `docs/spec/ops.md` §2 の 19 件のうち
 * どれを呼ぶかであり、オペレーション一覧は schema には書かれていない情報である。
 *
 * **20 個目のオペレーションを作らない**（要件書 §6.3）。schema にあってもオペレーションで
 * 到達できない欄は、既存オペレーションの合成で書く（tool の `ref` / `builtin` / `circle` は
 * `removeTool` + `addTool`）。
 */

/** 選択の種類 → schema 上の定義（フォームを作る足場）。 */
export function schemaFor(
  root: JsonSchema,
  selection: Selection,
  value: unknown,
): JsonSchema | null {
  const circle = resolveRef(root, "#/$defs/Circle");
  if (circle === null) return null;
  switch (selection.kind) {
    case "circle":
      return circle;
    case "rune":
      // Instruction は `rune` 1 欄だけを持つ定義である。
      return resolveRef(root, "#/$defs/Instruction");
    case "core": {
      // Circle 全体ではなく `core` の 1 欄だけを出す。**欄の定義は schema から取る**
      // （ここで型や最大長を書き写すと手書きのフォーム定義になる）。
      const core = circle.properties?.["core"];
      return core === undefined ? null : { type: "object", properties: { core }, required: [] };
    }
    case "tool": {
      const tools = circle.properties?.["tools"];
      return tools === undefined ? null : branchFor(root, tools, value);
    }
    case "state":
      return resolveRef(root, "#/$defs/State");
    case "guard":
      return resolveRef(root, "#/$defs/Guard");
    case "delegate":
      // delegate は circle 名の**文字列**の配列であって、オブジェクトの欄を持たない。
      return null;
  }
}

export interface FieldChange {
  readonly key: string;
  /** 空欄は `null`（`nullable` な欄でのみ意味を持つ）。 */
  readonly value: string | boolean | number | null;
}

/**
 * 欄の変更 → オペレーション列。書けない欄には**空配列**を返す（黙って握り潰さない）。
 *
 * 引数のキーは `jin_core.ops` の実装に合わせて **`value`（と配列操作の `index`）**である
 * （`_require_value` / `_require_index` を実測）。`core:` `name:` のような欄名では届かない。
 */
export function opsForChange(
  model: JinModel,
  selection: Selection,
  change: FieldChange,
): readonly JinOp[] {
  const pointer = resolveSelection(model, selection);
  if (pointer === null) return [];
  const circlePointer = circlePointerOf(pointer);
  const value = emptyToNull(change.value);

  switch (selection.kind) {
    case "circle":
      if (change.key === "name") {
        return typeof change.value === "string"
          ? [{ op: "rename", pointer, value: change.value }]
          : [];
      }
      if (change.key === "core") return [{ op: "setCore", pointer, value }];
      if (change.key === "description") return [{ op: "setDescription", pointer, value }];
      return [];
    case "core":
      return [{ op: "setCore", pointer: circlePointer, value }];
    case "rune":
      return [{ op: "setRune", pointer: circlePointer, value }];
    case "state":
      if (change.key === "name") {
        return typeof change.value === "string"
          ? [{ op: "rename", pointer, value: change.value }]
          : [];
      }
      return [{ op: "setState", pointer, value: { [change.key]: change.value } }];
    case "tool":
      if (change.key === "name") {
        return typeof change.value === "string"
          ? [{ op: "rename", pointer, value: change.value }]
          : [];
      }
      // `ref` / `builtin` / `circle` を書き換えるオペレーションは v1 に無い。
      // **20 個目を作らず**、削除と再追加の合成で書く（`apply_ops` は
      // 「1 つでも失敗したら何も適用しない」ので、2 件を 1 回で送れば原子性が保たれる）。
      return replaceTool(model, pointer, change);
    case "guard": {
      const current = at(model, pointer);
      if (current === null || typeof current !== "object") return [];
      return [
        {
          op: "setGuard",
          pointer,
          value: { ...(current as Record<string, unknown>), [change.key]: change.value },
        },
      ];
    }
    case "delegate":
      return [];
  }
}

function circlePointerOf(pointer: string): string {
  return pointer.split("/").slice(0, 3).join("/");
}

function emptyToNull(value: string | boolean | number | null): string | boolean | number | null {
  return value === "" ? null : value;
}

function replaceTool(model: JinModel, pointer: string, change: FieldChange): readonly JinOp[] {
  const current = at(model, pointer);
  if (current === null || typeof current !== "object") return [];
  const index = Number(pointer.split("/").at(-1));
  if (!Number.isInteger(index)) return [];
  const next = { ...(current as Record<string, unknown>), [change.key]: change.value };
  return [
    { op: "removeTool", pointer },
    { op: "addTool", pointer: pointer.split("/").slice(0, -1).join("/"), index, value: next },
  ];
}

function at(model: JinModel, pointer: string): unknown {
  let node: unknown = model;
  for (const segment of pointer.split("/").slice(1)) {
    if (node === null || typeof node !== "object") return null;
    node = Array.isArray(node)
      ? node[Number(segment)]
      : (node as Record<string, unknown>)[segment];
  }
  return node ?? null;
}

/** 選択に対応するフォームの欄。schema が引けなければ空。 */
export function fieldsForSelection(
  root: JsonSchema,
  selection: Selection,
  value: unknown,
): ReturnType<typeof fieldsOf> {
  const schema = schemaFor(root, selection, value);
  if (schema === null) return [];
  return fieldsOf(root, unwrap(root, schema).schema);
}
