import type { JinModel } from "../rpc/protocol";

/**
 * Jin v2 の選択（DP-COMMON-16 の v2 版・設計書 §8）。
 *
 * v1 と同じく**生の JSON Pointer では保持しない**（`moveSigil` / `moveStep` で配列が並び替わると
 * 同じ pointer が別の要素を指す）。鍵は名前で持ち、`applyOps` の応答のたびに新しいモデル上で
 * pointer を引き直す。名前を持たない要素の鍵は次のとおり:
 *
 * - `on` は `event`（`setOn` が同じ event を置換するので陣内で一意）
 * - `guard` は `assert` の文字列（v1 の `on` に倣う）
 * - `step` は 陣 + 手順名 + **手順内のパス**（`["steps", "0", "then", "1"]`）。ステップは
 *   名前を持たない（`let` の `name` は局所名で、ステップの鍵ではない）ので、パスで持つ。
 *   Shift クリックの範囲選択（v2.1）は同じ鍵に `count` を足す（`path` は範囲の**先頭**。
 *   範囲は同じ列の連続する添字に限る・`extendStepRange`）
 * - `flow-edge` は流れの中の陣名（`flow.steps[j]`）
 *
 * 変換は `resolveSelectionV2` **1 本**だけが行う（v1 の `resolveSelection` と同じ規律）。
 * `v2: true` は v1 の `Selection` と見分けるための印（App が両方を 1 つの state で持つ）。
 */
export type SelectionV2 =
	| { readonly v2: true; readonly kind: "stage" }
	| { readonly v2: true; readonly kind: "form"; readonly name: string }
	| { readonly v2: true; readonly kind: "circle"; readonly circle: string }
	| { readonly v2: true; readonly kind: "core"; readonly circle: string }
	| {
			readonly v2: true;
			readonly kind: "state";
			readonly circle: string;
			readonly name: string;
	  }
	| {
			readonly v2: true;
			readonly kind: "sigil";
			readonly circle: string;
			readonly name: string;
	  }
	| {
			readonly v2: true;
			readonly kind: "rite";
			readonly circle: string;
			readonly name: string;
	  }
	| {
			readonly v2: true;
			readonly kind: "on";
			readonly circle: string;
			readonly event: string;
	  }
	| {
			readonly v2: true;
			readonly kind: "guard";
			readonly circle: string;
			readonly assert: string;
	  }
	| {
			readonly v2: true;
			readonly kind: "delegate";
			readonly circle: string;
			readonly name: string;
	  }
	| {
			readonly v2: true;
			readonly kind: "flow-edge";
			readonly circle: string;
			readonly name: string;
	  }
	| {
			readonly v2: true;
			readonly kind: "step";
			readonly circle: string;
			readonly rite: string;
			/** 手順の中のパス。`["steps", "2"]` / `["steps", "0", "then", "1"]`。範囲なら先頭。 */
			readonly path: readonly string[];
			/** 範囲選択の個数（2 以上）。1 つだけのときは書かない。 */
			readonly count?: number;
	  };

export type SelectionKindV2 = SelectionV2["kind"];

type Rec = Readonly<Record<string, unknown>>;

function isRecord(value: unknown): value is Rec {
	return value !== null && typeof value === "object" && !Array.isArray(value);
}

function listOf(value: unknown): readonly unknown[] {
	return Array.isArray(value) ? value : [];
}

function stringField(item: unknown, key: string): string | null {
	if (typeof item === "string") return item;
	if (isRecord(item) && typeof item[key] === "string")
		return item[key] as string;
	return null;
}

function indexBy(list: unknown, key: string, wanted: string): number {
	return listOf(list).findIndex((item) => stringField(item, key) === wanted);
}

function circleIndex(model: JinModel, name: string): number {
	return indexBy(model["circles"], "name", name);
}

/** 選択 → 現在のモデル上の JSON Pointer。解決できなければ `null`（例外にしない）。 */
export function resolveSelectionV2(
	model: JinModel,
	selection: SelectionV2,
): string | null {
	if (selection.kind === "stage") return "/stage";
	if (selection.kind === "form") {
		const index = indexBy(model["forms"], "name", selection.name);
		return index < 0 ? null : `/forms/${index}`;
	}
	const index = circleIndex(model, selection.circle);
	if (index < 0) return null;
	const circle = listOf(model["circles"])[index];
	if (!isRecord(circle)) return null;
	const base = `/circles/${index}`;
	const child = (
		key: string,
		matchKey: string,
		wanted: string,
	): string | null => {
		const position = indexBy(circle[key], matchKey, wanted);
		return position < 0 ? null : `${base}/${key}/${position}`;
	};
	switch (selection.kind) {
		case "circle":
			return base;
		case "core":
			return `${base}/core`;
		case "state":
			return child("state", "name", selection.name);
		case "sigil":
			return child("sigils", "name", selection.name);
		case "rite":
			return child("rites", "name", selection.name);
		case "delegate":
			return child("delegate", "name", selection.name);
		case "on": {
			const boundary = circle["boundary"];
			const position = isRecord(boundary)
				? indexBy(boundary["on"], "event", selection.event)
				: -1;
			return position < 0 ? null : `${base}/boundary/on/${position}`;
		}
		case "guard": {
			const boundary = circle["boundary"];
			const position = isRecord(boundary)
				? indexBy(boundary["guards"], "assert", selection.assert)
				: -1;
			return position < 0 ? null : `${base}/boundary/guards/${position}`;
		}
		case "flow-edge": {
			const flow = circle["flow"];
			const position = isRecord(flow)
				? indexBy(flow["steps"], "name", selection.name)
				: -1;
			return position < 0 ? null : `${base}/flow/steps/${position}`;
		}
		case "step": {
			const rite = indexBy(circle["rites"], "name", selection.rite);
			if (rite < 0) return null;
			const pointer = `${base}/rites/${rite}/${selection.path.join("/")}`;
			// 範囲なら末尾まで揃っていること（はみ出した範囲は解決しない）。
			const last = rangePointersV2(pointer, selection).at(-1) ?? pointer;
			return valueAt(model, pointer) === null || valueAt(model, last) === null
				? null
				: pointer;
		}
	}
}

/** ステップの選択の個数（範囲でなければ 1）。 */
export function stepCount(selection: SelectionV2): number {
	return selection.kind === "step" ? (selection.count ?? 1) : 1;
}

/**
 * 解決した pointer（範囲の先頭）→ 範囲に入る全ステップの pointer（ハイライト用）。
 * 範囲でなければ `[pointer]`。
 */
export function rangePointersV2(
	pointer: string,
	selection: SelectionV2,
): readonly string[] {
	const count = stepCount(selection);
	if (count <= 1) return [pointer];
	const parts = pointer.split("/");
	const parent = parts.slice(0, -1).join("/");
	const low = Number(parts.at(-1));
	return Array.from(
		{ length: count },
		(_, k) => `${parent}/${String(low + k)}`,
	);
}

/**
 * Shift クリック（v2.1・ops.md §5）: 選択中のステップと、クリックしたステップが**同じ列**なら
 * 両方を含む連続範囲に広げる。それ以外（列 / 手順が違う・どちらかがステップでない）は
 * クリックした要素だけを選ぶ。起点は持たない（範囲の内側をクリックしても縮めない）。
 */
export function extendStepRange(
	current: SelectionV2 | null,
	clicked: SelectionV2 | null,
): SelectionV2 | null {
	if (current?.kind !== "step" || clicked?.kind !== "step") return clicked;
	if (current.circle !== clicked.circle || current.rite !== clicked.rite)
		return clicked;
	const parentOf = (path: readonly string[]): string =>
		path.slice(0, -1).join("/");
	if (parentOf(current.path) !== parentOf(clicked.path)) return clicked;
	const currentLow = Number(current.path.at(-1));
	const at = Number(clicked.path.at(-1));
	const low = Math.min(currentLow, at);
	const high = Math.max(currentLow + stepCount(current) - 1, at);
	const path = [...clicked.path.slice(0, -1), String(low)];
	const { v2, kind, circle, rite } = clicked;
	return high > low
		? { v2, kind, circle, rite, path, count: high - low + 1 }
		: { v2, kind, circle, rite, path };
}

/** pointer の値。無ければ `null`。 */
export function valueAt(model: JinModel, pointer: string): unknown {
	let node: unknown = model;
	for (const segment of pointer.split("/").slice(1)) {
		if (node === null || typeof node !== "object") return null;
		node = Array.isArray(node) ? node[Number(segment)] : (node as Rec)[segment];
	}
	return node ?? null;
}

/**
 * SVG の `data-jin` が返す pointer から選択を作る（逆向き）。
 *
 * v2 の pointer の形は `docs/spec/v2/layout.md` §4。手順の図では外環が `/circles/i/rites/j`
 * （kind `circle`）、核が `/circles/i/rites/j/name`（kind `core`）を持つので、どちらも手順の選択に写す。
 * `/circles/i/flow` と `/circles/i/flow/exit`（kind `flow-edge`）は陣の選択に写す。
 */
export function selectionFromPointerV2(
	model: JinModel,
	pointer: string,
): SelectionV2 | null {
	const parts = pointer.split("/").slice(1);
	if (parts[0] === "stage") return { v2: true, kind: "stage" };
	if (parts[0] === "forms" && parts[1] !== undefined) {
		const name = stringField(listOf(model["forms"])[Number(parts[1])], "name");
		return name === null ? null : { v2: true, kind: "form", name };
	}
	if (parts[0] !== "circles" || parts[1] === undefined) return null;
	const circle = listOf(model["circles"])[Number(parts[1])];
	if (!isRecord(circle)) return null;
	const circleName = stringField(circle, "name");
	if (circleName === null) return null;
	const rest = parts.slice(2);
	if (rest.length === 0)
		return { v2: true, kind: "circle", circle: circleName };
	const [head, second, third] = rest;
	if (head === "core") return { v2: true, kind: "core", circle: circleName };
	if (head === "flow") {
		if (second === "steps" && third !== undefined) {
			const flow = circle["flow"];
			const name = isRecord(flow)
				? stringField(listOf(flow["steps"])[Number(third)], "name")
				: null;
			return name === null
				? null
				: { v2: true, kind: "flow-edge", circle: circleName, name };
		}
		return { v2: true, kind: "circle", circle: circleName };
	}
	if (head === "state" || head === "sigils" || head === "delegate") {
		const name = stringField(listOf(circle[head])[Number(second)], "name");
		if (name === null) return null;
		const kind =
			head === "state" ? "state" : head === "sigils" ? "sigil" : "delegate";
		return { v2: true, kind, circle: circleName, name };
	}
	if (head === "rites" && second !== undefined) {
		const rite = stringField(listOf(circle["rites"])[Number(second)], "name");
		if (rite === null) return null;
		const path = rest.slice(2);
		if (
			path.length === 0 ||
			path[0] === "name" ||
			path[0] === "params" ||
			path[0] === "returns"
		) {
			return { v2: true, kind: "rite", circle: circleName, name: rite };
		}
		if (path[0] === "steps") {
			// ステップの pointer は `steps/k(/then/m | /else/m | /steps/m)*`。欄（`/expr` など）を
			// 指していたらステップまで切り詰める（偶数個目までが列と添字の対）。
			const trimmed = trimToStep(path);
			return trimmed === null
				? { v2: true, kind: "rite", circle: circleName, name: rite }
				: { v2: true, kind: "step", circle: circleName, rite, path: trimmed };
		}
		return { v2: true, kind: "rite", circle: circleName, name: rite };
	}
	if (head === "boundary" && second === "on" && third !== undefined) {
		const boundary = circle["boundary"];
		const event = isRecord(boundary)
			? stringField(listOf(boundary["on"])[Number(third)], "event")
			: null;
		return event === null
			? null
			: { v2: true, kind: "on", circle: circleName, event };
	}
	if (head === "boundary" && second === "guards" && third !== undefined) {
		const boundary = circle["boundary"];
		const assert = isRecord(boundary)
			? stringField(listOf(boundary["guards"])[Number(third)], "assert")
			: null;
		return assert === null
			? null
			: { v2: true, kind: "guard", circle: circleName, assert };
	}
	return null;
}

const STEP_LIST_KEYS = new Set(["steps", "then", "else"]);

/** `["steps","0","expr"]` → `["steps","0"]`。列名と添字の対が続く限り取り、途中で崩れたら `null`。 */
function trimToStep(path: readonly string[]): readonly string[] | null {
	const kept: string[] = [];
	for (let i = 0; i + 1 < path.length; i += 2) {
		const list = path[i];
		const index = path[i + 1];
		if (list === undefined || index === undefined) break;
		if (!STEP_LIST_KEYS.has(list) || !/^\d+$/.test(index)) break;
		kept.push(list, index);
	}
	return kept.length === 0 ? null : kept;
}

/**
 * `rename` を当てた直後の選択追随（v1 の `followRename` の v2 版）。
 *
 * v2 の `rename` は `value` に新名を持つ（`jin_core.v2.ops`）。当てたオペレーションが
 * 選択中の要素そのもの（または選択の陣 / 手順）の rename なら、名前を新名へ差し替える。
 */
export function followRenameV2(
	selection: SelectionV2 | null,
	op: {
		readonly op: string;
		readonly pointer?: string;
		readonly value?: unknown;
	},
	before: JinModel,
): SelectionV2 | null {
	if (selection === null || op.op !== "rename" || typeof op.value !== "string")
		return selection;
	if (op.pointer === undefined) return selection;
	const renamed = selectionFromPointerV2(before, op.pointer);
	if (renamed === null) return selection;
	// 手順の引数（`…/rites/j/params/k`）や `loop.name` のように、pointer が選択の要素**の中**を指す改名は
	// その要素の改名ではない（選択の名前を書き換えると要素が見つからなくなる）。要素そのものの pointer のときだけ追随する。
	if (resolveSelectionV2(before, renamed) !== op.pointer) return selection;
	const name = op.value;
	if (
		renamed.kind === "circle" &&
		"circle" in selection &&
		selection.circle === renamed.circle
	) {
		return { ...selection, circle: name };
	}
	if (renamed.kind === "rite" && selection.kind === "step") {
		return renamed.circle === selection.circle &&
			renamed.name === selection.rite
			? { ...selection, rite: name }
			: selection;
	}
	if (
		renamed.kind === selection.kind &&
		"name" in renamed &&
		"name" in selection
	) {
		const sameCircle =
			!("circle" in renamed) ||
			!("circle" in selection) ||
			renamed.circle === selection.circle;
		return sameCircle && renamed.name === selection.name
			? { ...selection, name }
			: selection;
	}
	return selection;
}

/** 選択が属する陣の名前（stage / form は無い）。 */
export function circleOfSelection(
	selection: SelectionV2 | null,
): string | null {
	return selection !== null && "circle" in selection ? selection.circle : null;
}
