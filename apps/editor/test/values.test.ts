import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe as group, expect, test } from "vitest";

import {
	assertLabels,
	assertsAt,
	formatValue,
	frameAt,
	LABEL_MAX,
	stateLabels,
	stateValuesAt,
} from "../src/debug/values";
import { parseTrace, type TraceEvent } from "../src/trace/parse";

/** `jin run --ticks 3 --debug --trace` が実際に書いた paddle のトレース（38 行・seq 0 始まり）。 */
const FIXTURE = join(
	process.cwd(),
	"../../tests/fixtures/traces/paddle-v2.jsonl",
);
const PADDLE = join(process.cwd(), "../../examples-v2/paddle/paddle.jin");

function events(): readonly TraceEvent[] {
	const parsed = parseTrace(readFileSync(FIXTURE, "utf8"));
	if (!parsed.ok)
		throw new Error(`読めない: ${parsed.line}: ${parsed.message}`);
	return parsed.events;
}

function row(partial: Record<string, unknown>, line: number): TraceEvent {
	return { line, row: partial };
}

group("stateValuesAt（runtime.md §5 の積算）", () => {
	test("enter 行で init 後の state が全部入り、set 行で 1 つずつ置き換わる", () => {
		const rows = events();
		// seq 0 = enter（ball / paddle / score）、seq 2 = set score 0、seq 4 = set ball
		const at0 = stateValuesAt(rows, 0);
		expect([...at0.keys()]).toEqual(["Play"]);
		expect(at0.get("Play")?.get("paddle")).toBe(140);
		expect(at0.get("Play")?.get("ball")).toEqual({
			x: 160,
			y: 40,
			vx: 90,
			vy: 70,
		});
		// seq 8 = set ball（y が動く）
		const at8 = stateValuesAt(rows, 8);
		expect(at8.get("Play")?.get("ball")).toEqual({
			x: 161.5,
			y: 41.166666666666664,
			vx: 90,
			vy: 70,
		});
		expect(at8.get("Play")?.get("paddle")).toBe(140);
		// upto の外は積算しない（seq 7 までなら y はまだ 40）
		expect(stateValuesAt(rows, 7).get("Play")?.get("ball")).toEqual({
			x: 161.5,
			y: 40,
			vx: 90,
			vy: 70,
		});
	});

	test("seq の順に積算する（配列の順ではない）。seq が無い行と circle の無い行は数えない", () => {
		const values = stateValuesAt(
			[
				row({ seq: 2, circle: "A", kind: "set", name: "n", output: 2 }, 1),
				row({ seq: 1, circle: "A", kind: "set", name: "n", output: 1 }, 2),
				row({ circle: "A", kind: "set", name: "n", output: 99 }, 3),
				row({ seq: 3, kind: "set", name: "n", output: 100 }, 4),
				row(
					{ seq: 0, circle: "A", kind: "enter", output: { n: 0, m: "x" } },
					5,
				),
			],
			3,
		);
		expect(values.get("A")?.get("n")).toBe(2);
		expect(values.get("A")?.get("m")).toBe("x");
	});
});

group("assertsAt / assertLabels", () => {
	test("assert 行だけを seq 順に、guard ごとに 1 枚のバッジ（回数付き）にする", () => {
		const rows = [
			row(
				{
					seq: 9,
					circle: "Only",
					kind: "assert",
					pointer: "/circles/0/boundary/guards/0",
					output: "n は 2 未満",
				},
				1,
			),
			row(
				{
					seq: 10,
					circle: "Only",
					kind: "set",
					pointer: "/circles/0/rites/1/steps/0",
				},
				2,
			),
			row(
				{
					seq: 14,
					circle: "Only",
					kind: "assert",
					pointer: "/circles/0/boundary/guards/0",
					output: "n は 2 未満",
				},
				3,
			),
		];
		expect(assertsAt(rows, 9)).toEqual([
			{
				seq: 9,
				pointer: "/circles/0/boundary/guards/0",
				circle: "Only",
				message: "n は 2 未満",
			},
		]);
		expect(assertsAt(rows, 20)).toHaveLength(2);
		expect(assertLabels(assertsAt(rows, 20))).toEqual([
			{
				pointer: "/circles/0/boundary/guards/0",
				text: "n は 2 未満 ×2",
				tone: "assert",
			},
		]);
		expect(assertLabels(assertsAt(rows, 9))[0]?.text).toBe("n は 2 未満");
		expect(assertsAt(rows, 8)).toEqual([]);
	});
});

group("frameAt", () => {
	test("upto までの最後の frame 行の ops。boot の行の範囲では null", () => {
		const rows = events();
		// frame 行は seq 15 / 26 / 37（tick 0 / 1 / 2 の終わり）
		expect(frameAt(rows, 14)).toBeNull();
		const first = frameAt(rows, 15);
		expect(Array.isArray(first)).toBe(true);
		expect(first?.[0]).toEqual(["clear", "#000"]);
		// 2 tick 目の frame は 1 tick 目と違う（ボールが動く）
		expect(frameAt(rows, 37)).not.toEqual(first);
	});
});

group("stateLabels / formatValue", () => {
	test("モデルの陣名と state 名から `/circles/i/state/j` に写す。トレースに無い陣には付けない", () => {
		const model = JSON.parse(readFileSync(PADDLE, "utf8")) as Record<
			string,
			unknown
		>;
		const labels = stateLabels(model, stateValuesAt(events(), 8));
		expect(labels.map((label) => label.pointer)).toEqual([
			"/circles/1/state/0",
			"/circles/1/state/1",
			"/circles/1/state/2",
		]);
		expect(labels[1]).toEqual({
			pointer: "/circles/1/state/1",
			text: "140",
			tone: "value",
		});
		expect(labels[0]?.text.endsWith("…")).toBe(true);
	});

	test("値は JSON の綴りで、長ければ切って `…`", () => {
		expect(formatValue(3)).toBe("3");
		expect(formatValue("abc")).toBe('"abc"');
		expect(formatValue(true)).toBe("true");
		expect(formatValue(null)).toBe("null");
		expect(formatValue({ x: 1 })).toBe('{"x":1}');
		const long = formatValue("a".repeat(LABEL_MAX * 2));
		expect([...long]).toHaveLength(LABEL_MAX);
		expect(long.endsWith("…")).toBe(true);
	});
});
