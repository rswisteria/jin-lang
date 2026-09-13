import type { JinModel, JinOp } from "../rpc/protocol";
import type { JinTarget } from "../svg/hitTest";
import { defaultStep } from "./dispatch";
import { resolveSelectionV2, type SelectionV2, valueAt } from "./selection";

/**
 * 図の操作 → オペレーション（`docs/spec/v2/ops.md` §5「エディタの操作との対応」）。
 *
 * - 手順の図で空き位置に足す → `addStep`（種別はパレットから）。ドラッグ → `moveStep`
 * - 「包む」→ `wrapSteps`、「抽出」→ `extractRite`（Phase 5 は選択中の 1 ステップを対象にする）
 * - 記憶環の四角をダブルクリック → `setState`（`out` の切り替え）
 * - 道具環のドラッグ → `moveSigil`
 *
 * 新しい要素は**スキーマ上必須の欄だけ**を埋め、参照先を捏造しない（DP-IMPL-JIN-P5-ADD-DEFAULTS-01）。
 * `jin check` が未解決の名前を診断として出し、次に何をすべきかが図に出る。
 */

type Rec = Readonly<Record<string, unknown>>;

function isRecord(value: unknown): value is Rec {
	return value !== null && typeof value === "object" && !Array.isArray(value);
}

function usedNames(list: unknown): ReadonlySet<string> {
	return new Set(
		Array.isArray(list)
			? list.map((item) =>
					typeof item === "string"
						? item
						: isRecord(item)
							? String(item["name"] ?? "")
							: "",
				)
			: [],
	);
}

export function freshName(base: string, used: ReadonlySet<string>): string {
	for (let i = 1; ; i += 1) {
		const candidate = `${base}${i}`;
		if (!used.has(candidate)) return candidate;
	}
}

function circlePointer(model: JinModel, circleName: string): string | null {
	return resolveSelectionV2(model, {
		v2: true,
		kind: "circle",
		circle: circleName,
	});
}

/** 手順を足す（`addRite`）。名前は `rite1` / `rite2` … の空き番。 */
export function addRite(model: JinModel, circleName: string): readonly JinOp[] {
	const pointer = circlePointer(model, circleName);
	if (pointer === null) return [];
	const rites = valueAt(model, `${pointer}/rites`);
	const name = freshName("rite", usedNames(rites));
	return [
		{ op: "addRite", pointer: `${pointer}/rites`, value: { name, steps: [] } },
	];
}

/** 記憶を足す（`addState`）。型は `num`、初期値は `0`（最小の妥当な定数式）。 */
export function addState(
	model: JinModel,
	circleName: string,
): readonly JinOp[] {
	const pointer = circlePointer(model, circleName);
	if (pointer === null) return [];
	const name = freshName(
		"state",
		usedNames(valueAt(model, `${pointer}/state`)),
	);
	return [
		{
			op: "addState",
			pointer: `${pointer}/state`,
			value: { name, type: "num", init: "0" },
		},
	];
}

/** ホスト能力の道具を足す（`addSigil` / `kind: host`）。名前空間は呼び出し側（パレット）が選ぶ。 */
export function addHostSigil(
	model: JinModel,
	circleName: string,
	host: string,
): readonly JinOp[] {
	const pointer = circlePointer(model, circleName);
	if (pointer === null) return [];
	const used = usedNames(valueAt(model, `${pointer}/sigils`));
	const name = used.has(host) ? freshName(host, used) : host;
	return [
		{
			op: "addSigil",
			pointer: `${pointer}/sigils`,
			value: { name, kind: "host", host },
		},
	];
}

/**
 * ステップを足す（`addStep`）。
 *
 * ステップが選ばれていればその**直後**に、手順が選ばれていれば（または手順の図を開いていれば）
 * その手順の末尾に入れる。`kind` はパレットの選択。
 */
export function addStep(
	model: JinModel,
	selection: SelectionV2 | null,
	focusRite: { readonly circle: string; readonly rite: string } | null,
	kind: string,
): readonly JinOp[] {
	if (selection?.kind === "step") {
		const pointer = resolveSelectionV2(model, selection);
		if (pointer === null) return [];
		const parts = pointer.split("/");
		const index = Number(parts.at(-1)) + 1;
		return [
			{
				op: "addStep",
				pointer: parts.slice(0, -1).join("/"),
				index,
				value: defaultStep(kind, selection.circle),
			},
		];
	}
	const target =
		selection?.kind === "rite"
			? { circle: selection.circle, rite: selection.name }
			: focusRite;
	if (target === null || target === undefined) return [];
	const pointer = resolveSelectionV2(model, {
		v2: true,
		kind: "rite",
		circle: target.circle,
		name: target.rite,
	});
	if (pointer === null) return [];
	return [
		{
			op: "addStep",
			pointer: `${pointer}/steps`,
			value: defaultStep(kind, target.circle),
		},
	];
}

/** 選択中の要素を消す。消せる種別だけ（陣 / stage / core は消さない）。 */
export function removeSelected(
	model: JinModel,
	selection: SelectionV2,
): readonly JinOp[] {
	const pointer = resolveSelectionV2(model, selection);
	if (pointer === null) return [];
	switch (selection.kind) {
		case "form":
			return [{ op: "removeForm", pointer }];
		case "state":
			return [{ op: "removeState", pointer }];
		case "sigil":
			return [{ op: "removeSigil", pointer }];
		case "rite":
			return [{ op: "removeRite", pointer }];
		case "step":
			return [{ op: "removeStep", pointer }];
		case "on":
			return [{ op: "removeOn", pointer }];
		case "guard":
			return [{ op: "removeGuard", pointer }];
		case "delegate":
			return [{ op: "removeDelegate", pointer }];
		case "stage":
		case "circle":
		case "core":
		case "flow-edge":
			return [];
	}
}

/** 選択中の 1 ステップを `if` で包む（`wrapSteps`）。条件は `true`（有効な式の最小）。 */
export function wrapSelectedStep(
	model: JinModel,
	selection: SelectionV2,
): readonly JinOp[] {
	if (selection.kind !== "step") return [];
	const pointer = resolveSelectionV2(model, selection);
	if (pointer === null) return [];
	const parts = pointer.split("/");
	return [
		{
			op: "wrapSteps",
			pointer: parts.slice(0, -1).join("/"),
			from: Number(parts.at(-1)),
			count: 1,
			value: { do: "if", cond: "true" },
		},
	];
}

/** 選択中の 1 ステップを新しい手順へ抽出する（`extractRite`）。 */
export function extractSelectedStep(
	model: JinModel,
	selection: SelectionV2,
): readonly JinOp[] {
	if (selection.kind !== "step") return [];
	const pointer = resolveSelectionV2(model, selection);
	if (pointer === null) return [];
	const circle = circlePointer(model, selection.circle);
	if (circle === null) return [];
	const name = freshName("rite", usedNames(valueAt(model, `${circle}/rites`)));
	const parts = pointer.split("/");
	return [
		{
			op: "extractRite",
			pointer: parts.slice(0, -1).join("/"),
			from: Number(parts.at(-1)),
			count: 1,
			name,
		},
	];
}

/** 記憶の四角をダブルクリック → `out` の切り替え（`setState`）。 */
export function toggleStateOut(
	model: JinModel,
	selection: SelectionV2,
): readonly JinOp[] {
	if (selection.kind !== "state") return [];
	const pointer = resolveSelectionV2(model, selection);
	if (pointer === null) return [];
	const current = valueAt(model, pointer);
	const out = isRecord(current) && current["out"] === true;
	return [{ op: "setState", pointer, value: { out: !out } }];
}

/**
 * ドラッグの落とし先 → 並べ替え。**同じ列の中**だけ（列を跨ぐ移動は ops.md §2 のとおり
 * `removeStep` + `addStep` の合成になるが、Phase 5 のドラッグは同じ列に限る）。
 */
export function moveOps(from: JinTarget, to: JinTarget): readonly JinOp[] {
	const fromParts = from.pointer.split("/");
	const toParts = to.pointer.split("/");
	const index = Number(toParts.at(-1));
	if (!Number.isInteger(index)) return [];
	if (fromParts.slice(0, -1).join("/") !== toParts.slice(0, -1).join("/"))
		return [];
	if (from.kind === "sigil")
		return [{ op: "moveSigil", pointer: from.pointer, to: index }];
	if (from.kind === "step")
		return [{ op: "moveStep", pointer: from.pointer, to: index }];
	return [];
}
