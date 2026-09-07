import type { JinModel } from "../rpc/protocol";

/**
 * 選択の保持と再解決（DP-COMMON-16 案 B）。
 *
 * **生の JSON Pointer では保持しない。** `moveTool` は「環上の角度の変更」として日常的に
 * 使われる操作で、配列が並び替わると同じ pointer が別の要素を指す。
 * 要件書 §10 #11 が名前を ID と定めているので、
 * **circle 名 + 種別 + 要素名の 3 つ組**で持ち、`applyOps` の応答のたびに
 * 新しいモデル上で pointer を引き直す。
 *
 * `tools[].name` / `state[].name` は **circle 内で一意**であって全体では一意でないため、
 * circle 名で限定しないと同名の tool を持つ circle 間で選択が飛ぶ。
 */
export type SelectionKind = "circle" | "core" | "rune" | "tool" | "state" | "delegate" | "guard";

export interface Selection {
  readonly circle: string;
  readonly kind: SelectionKind;
  /** `circle` / `core` / `rune` は要素名を持たない。 */
  readonly name?: string;
}

interface CircleLike {
  readonly name?: unknown;
  readonly tools?: unknown;
  readonly state?: unknown;
  readonly delegate?: unknown;
  readonly boundary?: unknown;
}

function circles(model: JinModel): readonly CircleLike[] {
  const value = model["circles"];
  return Array.isArray(value) ? (value as CircleLike[]) : [];
}

/**
 * 要素の「名前」。**guard だけは `name` を持たない**（`on` が circle 内で要素を決める鍵で、
 * `schemas/jin.schema.json` の Guard は `on` / `ref` の 2 欄しか持たない）ので、
 * どのキーで引くかを呼び出し側が渡す。
 */
function nameOf(item: unknown, key: string): string | null {
  if (typeof item === "string") return item;
  if (item !== null && typeof item === "object" && key in item) {
    const name = (item as Record<string, unknown>)[key];
    return typeof name === "string" ? name : null;
  }
  return null;
}

function indexByName(list: unknown, name: string, key: string): number {
  if (!Array.isArray(list)) return -1;
  return list.findIndex((item) => nameOf(item, key) === name);
}

/**
 * 選択 → 現在のモデル上の JSON Pointer。**この関数 1 本だけ**が変換を持つ
 * （DP-COMMON-16 の replaceability）。解決できなければ `null`（例外にしない）。
 */
export function resolveSelection(model: JinModel, selection: Selection): string | null {
  const index = circles(model).findIndex((circle) => nameOf(circle, "name") === selection.circle);
  if (index < 0) return null;
  const circle = circles(model)[index];
  if (circle === undefined) return null;
  const base = `/circles/${index}`;

  switch (selection.kind) {
    case "circle":
      return base;
    case "core":
      return `${base}/core`;
    case "rune":
      return `${base}/instruction/rune`;
    case "tool":
      return childPointer(base, "tools", circle.tools, selection.name);
    case "state":
      return childPointer(base, "state", circle.state, selection.name);
    case "delegate":
      return childPointer(base, "delegate", circle.delegate, selection.name);
    case "guard": {
      const boundary = circle.boundary;
      const guards =
        boundary !== null && typeof boundary === "object" && "guards" in boundary
          ? (boundary as { guards: unknown }).guards
          : undefined;
      return childPointer(`${base}/boundary`, "guards", guards, selection.name, "on");
    }
  }
}

function childPointer(
  base: string,
  key: string,
  list: unknown,
  name: string | undefined,
  matchKey = "name",
): string | null {
  if (name === undefined) return null;
  const index = indexByName(list, name, matchKey);
  return index < 0 ? null : `${base}/${key}/${index}`;
}

/**
 * SVG の `data-jin` が返す pointer から選択を作る（逆向き）。
 *
 * `data-jin` は**参照側**の pointer を持つ（`docs/spec/layout.md` §7）ので、
 * ここでも参照側の要素として解決する。名前が引けない pointer は `null`。
 */
export function selectionFromPointer(model: JinModel, pointer: string): Selection | null {
  const parts = pointer.split("/").slice(1);
  if (parts[0] !== "circles" || parts[1] === undefined) return null;
  const circle = circles(model)[Number(parts[1])];
  if (circle === undefined) return null;
  const circleName = nameOf(circle, "name");
  if (circleName === null) return null;

  if (parts.length === 2) return { circle: circleName, kind: "circle" };
  const kind = parts[2];
  if (kind === "core") return { circle: circleName, kind: "core" };
  if (kind === "instruction" && parts[3] === "rune") return { circle: circleName, kind: "rune" };

  const named = (key: "tools" | "state" | "delegate", list: unknown): Selection | null => {
    const index = Number(parts[3]);
    const name = Array.isArray(list) ? nameOf(list[index], "name") : null;
    if (name === null) return null;
    const selectionKind: SelectionKind =
      key === "tools" ? "tool" : key === "state" ? "state" : "delegate";
    return { circle: circleName, kind: selectionKind, name };
  };

  if (kind === "tools") return named("tools", circle.tools);
  if (kind === "state") return named("state", circle.state);
  if (kind === "delegate") return named("delegate", circle.delegate);
  if (kind === "boundary" && parts[3] === "guards") {
    const boundary = circle.boundary as { guards?: unknown } | undefined;
    const guard = Array.isArray(boundary?.guards) ? boundary.guards[Number(parts[4])] : null;
    const on = guard !== null && typeof guard === "object" && "on" in guard ? guard.on : null;
    if (typeof on !== "string") return null;
    return { circle: circleName, kind: "guard", name: on };
  }
  return null;
}

/**
 * `rename` を当てた直後の選択追随。
 *
 * DP-COMMON-16 の cons が「名前が変わる rename 直後の再解決規則を別途決める必要がある」と
 * 明記していた箇所である（HANDOFF `DP-IMPL-JIN-P5-RENAME-FOLLOW-01`）。
 * **当てたオペレーションが選択中の要素の rename なら、選択の名前を新名へ差し替える。**
 * サーバの `rename` は参照を全て追随させる（`docs/spec/ops.md` §3）ので、
 * 名前だけ差し替えれば新モデル上で同じ要素を指す。
 */
export function followRename(
  selection: Selection | null,
  op: { readonly op: string; readonly pointer?: string; readonly name?: unknown },
  before: JinModel,
): Selection | null {
  if (selection === null || op.op !== "rename" || typeof op.name !== "string") return selection;
  const pointer = op.pointer;
  if (pointer === undefined) return selection;
  const renamed = selectionFromPointer(before, pointer);
  if (renamed === null) return selection;
  if (renamed.circle !== selection.circle) return selection;

  if (renamed.kind === "circle" && renamed.circle === selection.circle) {
    return { ...selection, circle: op.name };
  }
  if (renamed.kind === selection.kind && renamed.name === selection.name) {
    return { ...selection, name: op.name };
  }
  return selection;
}
