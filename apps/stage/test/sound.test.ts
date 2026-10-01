import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, test } from "vitest";

import type { TraceRow } from "../src/names";
import { framesOf, type ScreenFrame } from "../src/screen/frames";
import {
	FADE_SECONDS,
	SAMPLE_RATE,
	synthesize,
	TONE_GAIN,
	toneEvents,
} from "../src/screen/sound";
import { type ExportRange, frameCount, VIDEO_FPS } from "../src/timeline";

const frame = (tick: number, audio: ScreenFrame["audio"]): ScreenFrame => ({
	tick,
	ops: [],
	audio,
});
const range = (fields: Partial<ExportRange> = {}): ExportRange => ({
	startTick: 0,
	endTick: 60,
	fps: 30,
	speed: 1,
	...fields,
});
const expectedLength = (r: ExportRange): number =>
	Math.round((frameCount(r) / VIDEO_FPS) * SAMPLE_RATE);

describe("tone の置き場所（仕様書 2026-10-01-jin-stage-summon §3.1）", () => {
	test("tick 30（fps 30・開始 0・速度 1）の tone(440, 100) は 1.0 秒から 0.1 秒", () => {
		expect(toneEvents([frame(30, [["tone", 440, 100]])], range())).toEqual([
			{ startSeconds: 1, hz: 440, seconds: 0.1 },
		]);
	});

	test("0.5 倍速では置き場所が 2 倍、長さと音程はそのまま", () => {
		expect(
			toneEvents([frame(30, [["tone", 440, 100]])], range({ speed: 0.5 })),
		).toEqual([{ startSeconds: 2, hz: 440, seconds: 0.1 }]);
	});

	test("開始より前に鳴り始めて食い込む音は頭が切れ、範囲より前で終わる音と範囲の後の音は捨てる", () => {
		const events = toneEvents(
			[
				frame(9, [["tone", 220, 200]]),
				frame(5, [["tone", 220, 30]]),
				frame(70, [["tone", 220, 30]]),
			],
			range({ startTick: 10 }),
		);
		expect(events).toHaveLength(1);
		expect(events[0]?.startSeconds).toBeCloseTo(0, 12);
		expect(events[0]?.seconds).toBeCloseTo(0.2 - 1 / 30, 12);
	});

	test("hz ≤ 0 と ms ≤ 0 と play は鳴らさない", () => {
		expect(
			toneEvents(
				[
					frame(1, [
						["tone", 0, 100],
						["tone", 440, 0],
						["play", "boom"],
					]),
				],
				range(),
			),
		).toEqual([]);
	});
});

describe("PCM の合成", () => {
	test("長さは映像と同じ。frame の無いトレースでは全部 0", () => {
		const pcm = synthesize([], range());
		expect(pcm.length).toBe(expectedLength(range()));
		expect(pcm.every((v) => v === 0)).toBe(true);
	});

	test("範囲の終わりを越える音は切れる（長さは映像のまま）", () => {
		const pcm = synthesize([frame(59, [["tone", 440, 1000]])], range());
		expect(pcm.length).toBe(expectedLength(range()));
	});

	test("矩形波の振幅は TONE_GAIN、頭の 1 サンプル目はフェードで 0", () => {
		const pcm = synthesize([frame(30, [["tone", 440, 100]])], range());
		const start = Math.round(1 * SAMPLE_RATE);
		expect(pcm[start]).toBe(0);
		const middle = start + Math.round(0.05 * SAMPLE_RATE);
		expect(Math.abs(pcm[middle] ?? 0)).toBeCloseTo(TONE_GAIN, 6);
		expect(
			Math.abs(pcm[start + Math.round((FADE_SECONDS / 2) * SAMPLE_RATE)] ?? 0),
		).toBeLessThan(TONE_GAIN);
	});

	test("同時の音は足し、[−1, 1] に収める", () => {
		const many = Array.from({ length: 30 }, () => ["tone", 440, 100] as const);
		const pcm = synthesize([frame(30, many)], range());
		const middle = Math.round(1.05 * SAMPLE_RATE);
		expect(Math.abs(pcm[middle] ?? 0)).toBeCloseTo(1, 6);
		expect(pcm.every((v) => v >= -1 && v <= 1)).toBe(true);
	});

	test("同じ入力なら同じ PCM（決定性）", () => {
		const frames = [
			frame(3, [["tone", 330, 80]]),
			frame(20, [["tone", 550, 40]]),
		];
		expect(synthesize(frames, range())).toEqual(synthesize(frames, range()));
	});

	test("tetris の録画の fixture（ハードドロップ 3 回）から 3 つの tone を拾う", () => {
		const rows = readFileSync(
			join(__dirname, "fixtures", "tetris-drops-trace.jsonl"),
			"utf8",
		)
			.split("\n")
			.filter((line) => line.trim() !== "")
			.map((line) => JSON.parse(line) as TraceRow);
		expect(
			toneEvents(framesOf(rows), range({ endTick: 120 })).length,
		).toBeGreaterThanOrEqual(3);
	});
});
