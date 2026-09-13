/**
 * トレースから「その位置の記憶環の値」と「偽になった `assert`」と「その tick の画面」を引く
 * （Jin v2 Phase 6・runtime.md §5「エディタのスクラバは `set` 行を積算して記憶環の値を出し、
 * `frame` 行でその tick の画面を出す」）。
 *
 * **オーバーレイ（発火の強調と点）はここでは作らない。** それは `jin_render` 1 本の仕事で、
 * ここで読むのは runtime.md §5 が「エディタの仕事」と書いた積算だけである:
 *
 * - `enter` / `exit` 行の `output` は**その陣の state 全部**（公開・非公開とも）
 * - `set` 行は state 1 つ（`circle` + `name` → `output`。局所変数は記録されない）
 * - `assert` 行は `guards[].assert` が偽（`pointer` は guard、`output` は `message`）
 * - `frame` 行は tick の終わりの表示リスト（`output.ops`）
 *
 * 位置は `seq <= upto`（`docs/spec/v2/layout.md` §6・0 始まり）。`seq` が読めない行は数えない。
 */
import { pointerOf, seqOf, stringOf, type TraceEvent } from "../trace/parse";

/** 陣名 → state 名 → 値。 */
export type StateValues = ReadonlyMap<string, ReadonlyMap<string, unknown>>;

export interface AssertHit {
	readonly seq: number;
	readonly pointer: string;
	readonly circle: string | null;
	readonly message: string;
}

/** 図の上に重ねる 1 枚のラベル（HTML。SVG には描かない）。 */
export interface ValueLabel {
	readonly pointer: string;
	readonly text: string;
	readonly tone: "value" | "assert";
}

/** `seq <= upto` の行を `seq` 順に。 */
function firedInOrder(
	events: readonly TraceEvent[],
	upto: number,
): TraceEvent[] {
	const rows: { seq: number; event: TraceEvent }[] = [];
	for (const event of events) {
		const seq = seqOf(event);
		if (seq !== null && seq <= upto) rows.push({ seq, event });
	}
	rows.sort((a, b) => a.seq - b.seq);
	return rows.map((row) => row.event);
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return value !== null && typeof value === "object" && !Array.isArray(value);
}

/** `upto` の位置での記憶環の値（陣名 → state 名 → 値）。 */
export function stateValuesAt(
	events: readonly TraceEvent[],
	upto: number,
): StateValues {
	const values = new Map<string, Map<string, unknown>>();
	const of = (circle: string): Map<string, unknown> => {
		let found = values.get(circle);
		if (found === undefined) {
			found = new Map();
			values.set(circle, found);
		}
		return found;
	};
	for (const event of firedInOrder(events, upto)) {
		const kind = stringOf(event, "kind");
		const circle = stringOf(event, "circle");
		if (circle === null) continue;
		const output = event.row["output"];
		if (kind === "enter" || kind === "exit") {
			if (!isRecord(output)) continue;
			const target = of(circle);
			for (const [name, value] of Object.entries(output))
				target.set(name, value);
		} else if (kind === "set") {
			const name = stringOf(event, "name");
			if (name === null) continue;
			of(circle).set(name, output);
		}
	}
	return values;
}

/** `upto` までに偽になった `assert`（`seq` 順）。 */
export function assertsAt(
	events: readonly TraceEvent[],
	upto: number,
): readonly AssertHit[] {
	const hits: AssertHit[] = [];
	for (const event of firedInOrder(events, upto)) {
		if (stringOf(event, "kind") !== "assert") continue;
		const pointer = pointerOf(event);
		const seq = seqOf(event);
		if (pointer === null || seq === null) continue;
		const output = event.row["output"];
		hits.push({
			seq,
			pointer,
			circle: stringOf(event, "circle"),
			message: typeof output === "string" ? output : "",
		});
	}
	return hits;
}

/** `upto` の位置で最後に描かれた画面（`frame` 行の `output.ops`）。無ければ null（boot の行の範囲）。 */
export function frameAt(
	events: readonly TraceEvent[],
	upto: number,
): readonly unknown[] | null {
	let ops: readonly unknown[] | null = null;
	for (const event of firedInOrder(events, upto)) {
		if (stringOf(event, "kind") !== "frame") continue;
		const output = event.row["output"];
		if (isRecord(output) && Array.isArray(output["ops"])) ops = output["ops"];
	}
	return ops;
}

/** ラベルの幅の上限（コードポイント）。超えた分は `…`。値そのものは脇の表で全部出す。 */
export const LABEL_MAX = 24;

/** 値を短い 1 行にする（JSON の綴り。文字列は引用符付き）。 */
export function formatValue(value: unknown): string {
	const text =
		value === undefined ? "" : (JSON.stringify(value) ?? String(value));
	const points = [...text];
	return points.length > LABEL_MAX
		? `${points.slice(0, LABEL_MAX - 1).join("")}…`
		: text;
}

/**
 * 記憶環の四角（`/circles/i/state/j`）に貼る値のラベル。pointer への写像はモデル（陣名と state 名）
 * から引く。トレースに無い state（まだ `enter` していない陣）にはラベルを付けない。
 */
export function stateLabels(
	model: Readonly<Record<string, unknown>>,
	values: StateValues,
): readonly ValueLabel[] {
	const labels: ValueLabel[] = [];
	const circles = model["circles"];
	if (!Array.isArray(circles)) return labels;
	circles.forEach((circle: unknown, i: number) => {
		if (!isRecord(circle) || typeof circle["name"] !== "string") return;
		const found = values.get(circle["name"]);
		if (found === undefined || !Array.isArray(circle["state"])) return;
		circle["state"].forEach((state: unknown, j: number) => {
			if (!isRecord(state) || typeof state["name"] !== "string") return;
			if (!found.has(state["name"])) return;
			labels.push({
				pointer: `/circles/${String(i)}/state/${String(j)}`,
				text: formatValue(found.get(state["name"])),
				tone: "value",
			});
		});
	});
	return labels;
}

/** 偽になった `assert` のバッジ（guard ごとに 1 枚。最後のメッセージと回数）。 */
export function assertLabels(
	hits: readonly AssertHit[],
): readonly ValueLabel[] {
	const byPointer = new Map<string, { message: string; count: number }>();
	for (const hit of hits) {
		const found = byPointer.get(hit.pointer);
		byPointer.set(hit.pointer, {
			message: hit.message,
			count: (found?.count ?? 0) + 1,
		});
	}
	return [...byPointer.entries()].map(([pointer, { message, count }]) => ({
		pointer,
		text:
			count > 1
				? `${message || "assert"} ×${String(count)}`
				: message || "assert",
		tone: "assert",
	}));
}
