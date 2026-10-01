import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, test } from "vitest";

import {
	BEAT,
	DURATION_SECONDS,
	EFFECTS,
	foldTrace,
	glowsAt,
	glowTarget,
	HUM,
	tickSpan,
} from "../src/effects";
import type { StageNames, TraceRow } from "../src/names";

const NAMES = JSON.parse(
	readFileSync(join(__dirname, "fixtures", "paddle-names.json"), "utf8"),
) as StageNames;
const TRACE = readFileSync(
	join(__dirname, "fixtures", "paddle-trace.jsonl"),
	"utf8",
)
	.split("\n")
	.filter((line) => line.trim() !== "")
	.map((line) => JSON.parse(line) as TraceRow);

let seq = 0;
const row = (fields: Partial<TraceRow>): TraceRow => ({
	seq: seq++,
	tick: 0,
	circle: "Play",
	kind: "rite",
	pointer: "/circles/1/rites/2",
	...fields,
});

describe("演出の表（stage.md §3）", () => {
	test("13 種、frame は鼓動（pulse / beat・仕様書 2026-10-01 §5.1）", () => {
		expect(Object.keys(EFFECTS).sort()).toEqual([
			"assert",
			"cast",
			"emit",
			"enter",
			"error",
			"event",
			"exit",
			"finish",
			"frame",
			"rite",
			"set",
			"transfer",
			"wait",
		]);
		expect(EFFECTS["frame"]).toEqual({ effect: "pulse", strength: "beat" });
		expect(Object.keys(DURATION_SECONDS)).toHaveLength(13);
	});

	test("長さは仕様書 2026-10-01 §5.4 の値", () => {
		expect(DURATION_SECONDS).toEqual({
			ignite: 2.4,
			fade: 1.6,
			chant: 1.0,
			spin: 0.9,
			beam: 0.8,
			flash: 0.8,
			release: 1.4,
			flow: 1.2,
			breathe: 1.5,
			crown: 3.2,
			warn: 1.4,
			crack: 2.0,
			pulse: 0.5,
		});
	});
});

describe("発火の宝玉（仕様書 2026-10-01 §2）", () => {
	test("cast canvas.rect の発火はサファイア、名前の表で引けない力は金", () => {
		const names = {
			Play: {
				...NAMES["Play"]!,
				sigilKinds: { canvas: "canvas", input: "input", audio: "audio" },
			},
		};
		const firings = foldTrace(
			[
				row({
					kind: "cast",
					name: "canvas.rect",
					pointer: "/circles/1/rites/2/steps/0",
				}),
				row({
					kind: "cast",
					name: "fits",
					pointer: "/circles/1/rites/2/steps/1",
				}),
			],
			names,
		);
		expect(firings.map((f) => f.gem)).toEqual(["sapphire", "gold"]);
		const glows = glowsAt(firings, 0.1, 60);
		expect(glows.map((g) => g.gem)).toEqual(["sapphire", "gold"]);
	});
});

describe("陣全体の演出は陣を光らせる（設計書 §2.3・stage.md §3.1）", () => {
	test("finish（crown）と error（crack）はステップの pointer を持っていても陣が target", () => {
		const firings = foldTrace(
			[
				row({ kind: "finish", pointer: "/circles/1/rites/3/steps/2" }),
				row({ kind: "error", pointer: "/circles/12/rites/0/steps/4/then/1" }),
				row({ kind: "enter", pointer: "/circles/1" }),
				row({ kind: "exit", pointer: "/circles/2" }),
			],
			NAMES,
		);
		expect(firings.map((f) => [f.effect, f.target])).toEqual([
			["crown", "/circles/1"],
			["crack", "/circles/12"],
			["ignite", "/circles/1"],
			["fade", "/circles/2"],
		]);
	});

	test("陣全体でない演出は §3.1 の解決のまま（陣に上げない）", () => {
		expect(glowTarget("spin", "/circles/1/rites/3")).toBe("/circles/1/rites/3");
		expect(glowTarget("warn", "/circles/1/boundary/guards/0")).toBe(
			"/circles/1/boundary/guards/0",
		);
		expect(glowTarget("crown", "/circles/1/rites/3/steps/2")).toBe(
			"/circles/1",
		);
		// 段一致: `/circles/10` を `/circles/1` と読まない。陣の外はそのまま
		expect(glowTarget("crack", "/circles/10/rites/0")).toBe("/circles/10");
		expect(glowTarget("crack", "/stage")).toBe("/stage");
	});
});

describe("慣れの規則（stage.md §3.2）", () => {
	test("毎 tick 繰り返す rite は 3 回目からうなり（HUM）に落ちる", () => {
		const rows = [0, 1, 2, 3, 4].map((tick) => row({ tick }));
		expect(foldTrace(rows, NAMES).map((f) => f.strength)).toEqual([
			1,
			1 - (1 - HUM) / 3,
			1 - (2 * (1 - HUM)) / 3,
			HUM,
			HUM,
		]);
	});

	test("同じ tick の中の繰り返しは連続回数を増やさない", () => {
		const rows = [row({ tick: 5 }), row({ tick: 5 }), row({ tick: 5 })];
		expect(foldTrace(rows, NAMES).map((f) => f.strength)).toEqual([1, 1, 1]);
	});

	test("間が空いたら 0 に戻る", () => {
		const rows = [0, 1, 2, 3, 9].map((tick) => row({ tick }));
		expect(foldTrace(rows, NAMES).at(-1)?.strength).toBe(1);
	});

	test("once の kind は常に 1", () => {
		const rows = [0, 1, 2, 3].map((tick) =>
			row({ tick, kind: "emit", pointer: "/circles/1/rites/2/steps/0" }),
		);
		expect(foldTrace(rows, NAMES).map((f) => f.strength)).toEqual([1, 1, 1, 1]);
	});

	test("set は値が変わらなければ HUM、変われば強い", () => {
		const rows = [
			row({ tick: 0, kind: "set", name: "score", output: 0 }),
			row({ tick: 10, kind: "set", name: "score", output: 0 }),
			row({ tick: 20, kind: "set", name: "score", output: 1 }),
		];
		expect(foldTrace(rows, NAMES).map((f) => [f.target, f.strength])).toEqual([
			["/circles/1/state/2", 1],
			["/circles/1/state/2", HUM],
			["/circles/1/state/2", 1],
		]);
	});

	test("boot の行（tick −1）は時刻 0、frame は /stage に強さ BEAT の鼓動", () => {
		const firings = foldTrace(
			[
				row({ tick: -1, kind: "enter", pointer: "/circles/1" }),
				row({ tick: 0, kind: "frame", circle: null, pointer: "/stage" }),
			],
			NAMES,
		);
		expect(firings.map((f) => [f.kind, f.time])).toEqual([
			["enter", 0],
			["frame", 0],
		]);
		expect(firings[1]).toMatchObject({
			effect: "pulse",
			target: "/stage",
			source: null,
			strength: BEAT,
		});
	});

	test("frame の鼓動は慣れの対象外（100 tick 続いても BEAT のまま）", () => {
		const rows = Array.from({ length: 100 }, (_, t) =>
			row({ tick: t, kind: "frame", circle: null, pointer: "/stage" }),
		);
		const firings = foldTrace(rows, NAMES);
		expect(new Set(firings.map((f) => f.strength))).toEqual(new Set([BEAT]));
		expect(BEAT).toBe(0.1);
	});

	// paddle-trace.jsonl は `jin run --ticks 90 --debug` の記録で、score は boot 行（tick −1・output 0）で
	// 1 回だけ set される（入力の無い paddle は 90 tick では得点しない・コントローラの判定）。
	test("paddle の 90 tick: ball の set はうなりに落ち、score は boot の 1 回だけ強い", () => {
		const firings = foldTrace(TRACE, NAMES);
		const ball = firings.filter((f) => f.target === "/circles/1/state/0");
		expect(ball.slice(-10).every((f) => f.strength === HUM)).toBe(true);
		const strongScore = firings.filter(
			(f) => f.target === "/circles/1/state/2" && f.strength === 1,
		);
		expect(strongScore).toHaveLength(1);
		expect(strongScore[0]?.time).toBe(0);
		// 同じ入力なら同じ結果（純関数）
		expect(foldTrace(TRACE, NAMES)).toEqual(firings);
	});
});

describe("時刻ごとの光（stage.md §3.3）", () => {
	const fps = 60;
	const firings = foldTrace(
		[row({ tick: 60, kind: "emit", pointer: "/circles/1/rites/2/steps/0" })],
		NAMES,
	);

	test("発火前と長さを過ぎた後は光らない", () => {
		expect(glowsAt(firings, 59.9, fps)).toEqual([]);
		expect(glowsAt(firings, 60 + DURATION_SECONDS.release * fps, fps)).toEqual(
			[],
		);
	});

	test("包絡は 15% で頂点、その後は線形に消える", () => {
		const peak = glowsAt(
			firings,
			60 + 0.15 * DURATION_SECONDS.release * fps,
			fps,
		)[0];
		expect(peak?.intensity).toBeCloseTo(1, 10);
		const half = glowsAt(
			firings,
			60 + 0.575 * DURATION_SECONDS.release * fps,
			fps,
		)[0];
		expect(half?.intensity).toBeCloseTo(0.5, 10);
		expect(half?.effect).toBe("release");
	});

	test("tickSpan は tick −1 を 0 に置いた範囲", () => {
		expect(tickSpan(TRACE)).toEqual({
			first: 0,
			last: Math.max(...TRACE.map((r) => r.tick)),
		});
		expect(tickSpan([])).toEqual({ first: 0, last: 0 });
	});
});
