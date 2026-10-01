import { describe, expect, test } from "vitest";

import type { StageNames, TraceRow } from "../src/names";
import {
	frameAt,
	framesOf,
	OPEN_SECONDS,
	PULSE_SECONDS,
	windowAt,
} from "../src/screen/frames";

const FPS = 30;
const NAMES: StageNames = {
	Game: {
		pointer: "/circles/0",
		sigils: {},
		state: {},
		delegates: {},
		isRoot: true,
	},
	Play: { pointer: "/circles/1", sigils: {}, state: {}, delegates: {} },
};
const NO_ROOT: StageNames = {
	Play: { pointer: "/circles/1", sigils: {}, state: {}, delegates: {} },
};

let seq = 0;
const row = (fields: Partial<TraceRow>): TraceRow => ({
	seq: seq++,
	tick: 0,
	circle: "Game",
	kind: "rite",
	pointer: "/circles/0",
	...fields,
});
const frame = (
	tick: number,
	ops: unknown[] = [["clear", "#000"]],
	audio: unknown[] = [],
): TraceRow =>
	row({
		tick,
		circle: null,
		kind: "frame",
		pointer: "/stage",
		output: { ops, audio },
	});

describe("映すコマ（仕様書 2026-10-01-jin-stage-summon §1.2）", () => {
	const rows = [
		row({ tick: -1, kind: "enter" }),
		frame(0),
		frame(1, [["clear", "#111"]]),
		frame(9, [["clear", "#999"]]),
	];
	const frames = framesOf(rows);

	test("frame 行だけを tick 順に、ops と audio を読む", () => {
		expect(frames.map((f) => f.tick)).toEqual([0, 1, 9]);
		expect(frames[1]?.ops).toEqual([["clear", "#111"]]);
	});

	test("時刻 t の tick（floor）以前で最新のコマ。最初の frame より前は null、最後を越えたら最後のコマで止まる", () => {
		expect(frameAt(frames, -0.5)).toBeNull();
		expect(frameAt(frames, 0.99)?.tick).toBe(0);
		expect(frameAt(frames, 8.99)?.tick).toBe(1);
		expect(frameAt(frames, 9)?.tick).toBe(9);
		expect(frameAt(frames, 500)?.tick).toBe(9);
	});

	test("frame 行の無いトレース（release の録画）では常に null", () => {
		expect(frameAt(framesOf([row({ kind: "enter" })]), 10)).toBeNull();
	});
});

describe("窓の開閉と縁の光（§1.3 / §1.4）", () => {
	const rows = [
		row({ tick: -1, kind: "enter", pointer: "/circles/0" }),
		row({ tick: -1, kind: "enter", circle: "Play", pointer: "/circles/1" }),
		frame(0),
		frame(30, [["clear", "#000"]], [["tone", 440, 50]]),
		frame(60),
		row({ tick: 90, kind: "finish", pointer: "/circles/0/rites/0/steps/2" }),
		frame(90),
	];
	const frames = framesOf(rows);
	const at = (t: number, names: StageNames = NAMES) =>
		windowAt(rows, frames, names, t, FPS);

	test("root の enter から OPEN_SECONDS で開き、root の finish から閉じる", () => {
		expect(at(0).open).toBe(0);
		expect(at((OPEN_SECONDS / 2) * FPS).open).toBeCloseTo(0.5, 9);
		expect(at(60).open).toBe(1);
		expect(at(90 + (OPEN_SECONDS / 2) * FPS).open).toBeCloseTo(0.5, 9);
		expect(at(90 + OPEN_SECONDS * FPS + 1).open).toBe(0);
	});

	test("子の陣の enter / finish では開閉しない", () => {
		const child = [
			row({ tick: -1, kind: "enter", circle: "Play", pointer: "/circles/1" }),
			frame(0),
			frame(60),
		];
		expect(windowAt(child, framesOf(child), NAMES, 60, FPS).open).toBe(0);
	});

	test("isRoot の無い表では最初の frame で開き、閉じない", () => {
		expect(at(OPEN_SECONDS * FPS, NO_ROOT).open).toBe(1);
		expect(at(200, NO_ROOT).open).toBe(1);
	});

	test("tone を含むコマの直後に tonePulse が 1、PULSE_SECONDS 後に 0", () => {
		expect(at(30).tonePulse).toBeCloseTo(1, 9);
		expect(at(30 + PULSE_SECONDS * FPS).tonePulse).toBe(0);
		expect(at(29).tonePulse).toBe(0);
	});

	test("error の後は errorPulse が 0〜1 で振れ、前は 0", () => {
		const broken = [
			...rows.slice(0, 4),
			row({ tick: 40, kind: "error", pointer: "/circles/0/rites/0/steps/1" }),
		];
		const f = framesOf(broken);
		expect(windowAt(broken, f, NAMES, 39, FPS).errorPulse).toBe(0);
		const values = [41, 43, 45, 47].map(
			(t) => windowAt(broken, f, NAMES, t, FPS).errorPulse,
		);
		for (const v of values) {
			expect(v).toBeGreaterThanOrEqual(0);
			expect(v).toBeLessThanOrEqual(1);
		}
		expect(new Set(values.map((v) => v.toFixed(3))).size).toBeGreaterThan(1);
	});

	test("frame の無いトレースでは窓を開かない", () => {
		const bare = [row({ tick: -1, kind: "enter" })];
		expect(windowAt(bare, framesOf(bare), NAMES, 100, FPS).open).toBe(0);
	});
});
