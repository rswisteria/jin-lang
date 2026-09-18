import type { JinModel, JinOp } from "../rpc/protocol";
import type { JinTarget } from "../svg/hitTest";
import { defaultStep } from "./dispatch";
import {
	resolveSelectionV2,
	type SelectionV2,
	selectionFromPointerV2,
	stepCount,
	valueAt,
} from "./selection";

/**
 * 図の操作 → オペレーション（`docs/spec/v2/ops.md` §5「エディタの操作との対応」）。
 *
 * - 手順の図で空き位置に足す → `addStep`（種別はパレットから）
 * - 「包む」→ `wrapSteps`、「抽出」→ `extractRite`（選択中のステップ、または Shift クリックの範囲）
 * - 記憶環の四角をダブルクリック → `setState`（`out` の切り替え）
 * - ドラッグ → `dropOps`（道具 / 同じ列のステップの並べ替え、列を跨ぐステップの移動、陣同士を結ぶ）
 *
 * 新しい要素は**スキーマ上必須の欄だけ**を埋め、参照先を捏造しない（DP-IMPL-JIN-P5-ADD-DEFAULTS-01）。
 * `jin check` が未解決の名前を診断として出し、次に何をすべきかが図に出る。
 */

type Rec = Readonly<Record<string, unknown>>;

function isRecord(value: unknown): value is Rec {
	return value !== null && typeof value === "object" && !Array.isArray(value);
}

/**
 * 図の操作 1 回ぶんの編集。
 *
 * `select` は**適用後のモデル**で選ぶ要素（ステップの選択はパスで持つので、包む / 抽出 / 移動の
 * 後は同じ鍵が別の要素を指す）。書かなければ選択はそのまま。`notice` は送らなかった理由。
 */
export interface EditV2 {
	readonly ops: readonly JinOp[];
	readonly select?: SelectionV2 | null;
	readonly notice?: string;
}

const NOTHING: EditV2 = { ops: [] };

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

/** `/a/b/3` → `["/a/b", 3]`。 */
function splitLast(pointer: string): readonly [string, number] {
	const parts = pointer.split("/");
	return [parts.slice(0, -1).join("/"), Number(parts.at(-1))];
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
 * ステップが選ばれていればその**直後**（範囲なら範囲の直後）に、手順が選ばれていれば
 * （または手順の図を開いていれば）その手順の末尾に入れる。`kind` はパレットの選択。
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
		const [list, low] = splitLast(pointer);
		return [
			{
				op: "addStep",
				pointer: list,
				index: low + stepCount(selection),
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

/**
 * 境界のイベントを足す（`setOn`・Issue #95）。
 *
 * 選択中の**手順**を呼ぶ `on` を、その陣でまだ使われていない先頭のイベント（`events` は schema の
 * `OnHandler.event` の enum。名前を書き写さない）で置く。参照先を捏造しない（手順は選択中のもの）。
 * すべてのイベントが使われていれば送らず `notice` で断る。足した `on` を選ぶ。
 */
export function addOn(
	model: JinModel,
	selection: SelectionV2 | null,
	events: readonly string[],
): EditV2 {
	if (selection?.kind !== "rite") return NOTHING;
	const circle = circlePointer(model, selection.circle);
	if (circle === null) return NOTHING;
	const boundary = valueAt(model, `${circle}/boundary`);
	const used = new Set(
		isRecord(boundary) && Array.isArray(boundary["on"])
			? boundary["on"].map((on) =>
					isRecord(on) ? String(on["event"] ?? "") : "",
				)
			: [],
	);
	const event = events.find((candidate) => !used.has(candidate));
	if (event === undefined) {
		return events.length === 0
			? NOTHING
			: {
					ops: [],
					notice: `${selection.circle} はすべてのイベントに既に手順を結んでいます（フォームで rite を変えてください）`,
				};
	}
	return {
		ops: [
			{
				op: "setOn",
				pointer: `${circle}/boundary/on`,
				value: { event, rite: selection.name },
			},
		],
		select: { v2: true, kind: "on", circle: selection.circle, event },
	};
}

/**
 * 選択中の 1 ステップが持つ**本文の列**の pointer（`loop` は `…/steps`、`if` は `…/then`）。
 * 本文を持たないステップ・範囲選択・ステップ以外は null（ボタンの活性の判定にも使う）。
 */
export function insideListOf(
	model: JinModel,
	selection: SelectionV2 | null,
): string | null {
	if (selection?.kind !== "step" || stepCount(selection) !== 1) return null;
	const pointer = resolveSelectionV2(model, selection);
	if (pointer === null) return null;
	const step = valueAt(model, pointer);
	if (!isRecord(step)) return null;
	if (step["do"] === "loop") return `${pointer}/steps`;
	if (step["do"] === "if") return `${pointer}/then`;
	return null;
}

/**
 * 選択中の `loop` / `if` の**本文の末尾**にステップを足す（`addStep`・v2.1）。
 *
 * 「ステップを追加」は選択の直後、ドラッグの落とし先は既にあるステップなので、
 * **空の本文には図に要素が無く、どちらでも入れられない**（ops.md §5）。この操作だけがその列に届く。
 * 足したステップを選ぶ。
 */
export function addStepInside(
	model: JinModel,
	selection: SelectionV2 | null,
	kind: string,
): EditV2 {
	const list = insideListOf(model, selection);
	if (list === null || selection?.kind !== "step") return NOTHING;
	const body = valueAt(model, list);
	const length = Array.isArray(body) ? body.length : 0;
	return {
		ops: [
			{
				op: "addStep",
				pointer: list,
				value: defaultStep(kind, selection.circle),
			},
		],
		select: selectionFromPointerV2(model, `${list}/${String(length)}`),
	};
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
		case "step": {
			// 範囲は**後ろから**消す（前から消すと残りの pointer が 1 つずつずれる）。
			const [list, low] = splitLast(pointer);
			return Array.from({ length: stepCount(selection) }, (_, k) => ({
				op: "removeStep",
				pointer: `${list}/${String(low + stepCount(selection) - 1 - k)}`,
			}));
		}
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

/** 範囲の先頭 1 つの選択（包む / 抽出で置き換わった 1 ステップ）。 */
function firstOfRange(
	selection: Extract<SelectionV2, { kind: "step" }>,
): SelectionV2 {
	const { v2, kind, circle, rite, path } = selection;
	return { v2, kind, circle, rite, path };
}

/** 選択中のステップ（範囲なら範囲全体）を `if` で包む（`wrapSteps`）。条件は `true`（有効な式の最小）。 */
export function wrapSelectedStep(
	model: JinModel,
	selection: SelectionV2,
): EditV2 {
	if (selection.kind !== "step") return NOTHING;
	const pointer = resolveSelectionV2(model, selection);
	if (pointer === null) return NOTHING;
	const [list, from] = splitLast(pointer);
	return {
		ops: [
			{
				op: "wrapSteps",
				pointer: list,
				from,
				count: stepCount(selection),
				value: { do: "if", cond: "true" },
			},
		],
		select: firstOfRange(selection),
	};
}

/** 選択中のステップ（範囲なら範囲全体）を新しい手順へ抽出する（`extractRite`）。 */
export function extractSelectedStep(
	model: JinModel,
	selection: SelectionV2,
): EditV2 {
	if (selection.kind !== "step") return NOTHING;
	const pointer = resolveSelectionV2(model, selection);
	if (pointer === null) return NOTHING;
	const circle = circlePointer(model, selection.circle);
	if (circle === null) return NOTHING;
	const name = freshName("rite", usedNames(valueAt(model, `${circle}/rites`)));
	const [list, from] = splitLast(pointer);
	return {
		ops: [
			{
				op: "extractRite",
				pointer: list,
				from,
				count: stepCount(selection),
				name,
			},
		],
		select: firstOfRange(selection),
	};
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
 * `removed` を消した後のモデルで `target` が指す pointer。
 *
 * `target` が `removed` と同じ列の、後ろの兄弟の中を通っていれば、その段の添字を 1 つ下げる
 * （段の一致であって文字列の前方一致ではない: `steps/1` を消しても `steps/10` は `steps/9`、
 * `steps/10` を消しても `steps/1` は変わらない）。
 */
export function pointerAfterRemoval(target: string, removed: string): string {
	const [list, index] = splitLast(removed);
	const prefix = `${list}/`;
	if (!target.startsWith(prefix)) return target;
	const rest = target.slice(prefix.length).split("/");
	const head = Number(rest[0]);
	if (!Number.isInteger(head) || head <= index) return target;
	return `${prefix}${[String(head - 1), ...rest.slice(1)].join("/")}`;
}

/**
 * ドラッグの落とし先 → オペレーション（ops.md §5）。種別は描かれた要素ではなく、
 * `selectionFromPointerV2` で解決した**モデルの要素**で決める（手順の図の外環は kind `circle`
 * だが手順を指す）。
 *
 * - 道具 → 同じ列の道具: `moveSigil`
 * - ステップ → ステップ / 手順: `moveStep`（同じ列）か `removeStep` + `addStep`（列を跨ぐ・1 回で送る）
 * - 陣 → 陣: `addDelegate`、陣 → 手順: `addSigil`（`summon`）
 */
export function dropOps(
	model: JinModel,
	from: JinTarget,
	to: JinTarget,
): EditV2 {
	if (from.kind === "sigil") {
		const [fromList] = splitLast(from.pointer);
		const [toList, index] = splitLast(to.pointer);
		if (to.kind !== "sigil" || fromList !== toList) return NOTHING;
		if (!Number.isInteger(index)) return NOTHING;
		return { ops: [{ op: "moveSigil", pointer: from.pointer, to: index }] };
	}
	const source = selectionFromPointerV2(model, from.pointer);
	if (source?.kind === "step") return dropStep(model, source, from.pointer, to);
	if (source?.kind === "circle" || source?.kind === "core")
		return connectCircles(model, source.circle, to);
	return NOTHING;
}

function dropStep(
	model: JinModel,
	source: Extract<SelectionV2, { kind: "step" }>,
	pointer: string,
	to: JinTarget,
): EditV2 {
	const target = selectionFromPointerV2(model, to.pointer);
	if (target === null || !("circle" in target)) return NOTHING;
	if (target.circle !== source.circle) return NOTHING;
	let list: string;
	let index: number | null;
	if (target.kind === "step" && target.rite === source.rite) {
		const resolved = resolveSelectionV2(model, target);
		if (resolved === null) return NOTHING;
		[list, index] = splitLast(resolved);
	} else if (target.kind === "rite") {
		const rite = resolveSelectionV2(model, target);
		if (rite === null) return NOTHING;
		list = `${rite}/steps`;
		index = null;
	} else {
		return NOTHING;
	}
	const [sourceList, sourceIndex] = splitLast(pointer);
	const selectAt = (at: string): SelectionV2 | null =>
		selectionFromPointerV2(model, at);
	const steps = valueAt(model, list);
	const length = Array.isArray(steps) ? steps.length : 0;
	if (list === sourceList) {
		const destination = index ?? length - 1;
		if (destination === sourceIndex) return NOTHING;
		return {
			ops: [{ op: "moveStep", pointer, to: destination }],
			select: selectAt(`${list}/${String(destination)}`),
		};
	}
	// 自分の子孫の列へは移せない（消した後に落とし先が無くなる）。
	if (list.startsWith(`${pointer}/`)) return NOTHING;
	const adjusted = pointerAfterRemoval(list, pointer);
	const add: JinOp =
		index === null
			? { op: "addStep", pointer: adjusted, value: valueAt(model, pointer) }
			: {
					op: "addStep",
					pointer: adjusted,
					index,
					value: valueAt(model, pointer),
				};
	return {
		ops: [{ op: "removeStep", pointer }, add],
		// 落とし先の列は消した列と別なので、長さは変わらない（末尾 = 今の長さ）。
		select: selectAt(`${adjusted}/${String(index ?? length)}`),
	};
}

/**
 * 陣を別の陣 / 手順に落とす。**落とした側が呼ぶ側**（`delegate` / `sigils` を持つ）。
 *
 * 核の有無・閉路（JIN011 / JIN012）・流れの陣に置けないこと（JIN002）はサーバの検査に任せる。
 * エディタが断るのは、既にある委譲の重複（サーバは断らず、同じ名前が 2 つ並ぶ）と、
 * 自分自身への落とし（手を滑らせただけのドラッグ）の 2 つだけ。
 */
function connectCircles(
	model: JinModel,
	sourceCircle: string,
	to: JinTarget,
): EditV2 {
	const target = selectionFromPointerV2(model, to.ref ?? to.pointer);
	if (target === null || !("circle" in target)) return NOTHING;
	if (target.circle === sourceCircle) return NOTHING;
	const base = circlePointer(model, sourceCircle);
	if (base === null) return NOTHING;
	if (target.kind === "circle" || target.kind === "core") {
		if (usedNames(valueAt(model, `${base}/delegate`)).has(target.circle)) {
			return {
				ops: [],
				notice: `${sourceCircle} は既に ${target.circle} へ委譲しています`,
			};
		}
		return {
			ops: [
				{
					op: "addDelegate",
					pointer: `${base}/delegate`,
					value: target.circle,
				},
			],
			select: {
				v2: true,
				kind: "delegate",
				circle: sourceCircle,
				name: target.circle,
			},
		};
	}
	if (target.kind === "rite") {
		const used = usedNames(valueAt(model, `${base}/sigils`));
		const name = used.has(target.name)
			? freshName(target.name, used)
			: target.name;
		return {
			ops: [
				{
					op: "addSigil",
					pointer: `${base}/sigils`,
					value: {
						name,
						kind: "summon",
						circle: target.circle,
						rite: target.name,
					},
				},
			],
			select: { v2: true, kind: "sigil", circle: sourceCircle, name },
		};
	}
	return NOTHING;
}
