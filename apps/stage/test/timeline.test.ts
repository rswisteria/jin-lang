import { describe, expect, test } from "vitest";

import {
	clampRange,
	frameCount,
	MAX_EXPORT_SECONDS,
	outputSize,
	tickAtFrame,
	VIDEO_FPS,
} from "../src/timeline";

describe("tick ↔ 動画のコマ（stage.md §5）", () => {
	const range = { startTick: 30, endTick: 150, fps: 60, speed: 1 as const };

	test("1× では 1 秒 = fps tick = 60 コマ", () => {
		expect(frameCount(range)).toBe(120);
		expect(tickAtFrame(range, 0)).toBe(30);
		expect(tickAtFrame(range, 60)).toBe(90);
	});

	test("0.5× では同じ範囲が 2 倍のコマになる", () => {
		const slow = { ...range, speed: 0.5 as const };
		expect(frameCount(slow)).toBe(240);
		expect(tickAtFrame(slow, 120)).toBe(90);
	});

	test("fps 30 のゲームは 1 コマあたり 0.5 tick 進む", () => {
		expect(tickAtFrame({ ...range, fps: 30 }, 1)).toBe(30.5);
	});

	test("最低 1 コマ、長さは 60 秒で切る、逆順は直す", () => {
		expect(frameCount({ ...range, endTick: 30 })).toBe(1);
		const long = clampRange({
			startTick: 0,
			endTick: 60 * 600,
			fps: 60,
			speed: 1,
		});
		expect(frameCount(long)).toBe(MAX_EXPORT_SECONDS * VIDEO_FPS);
		expect(clampRange({ ...range, startTick: 150, endTick: 30 })).toEqual(
			range,
		);
		expect(
			frameCount(
				clampRange({ startTick: 0, endTick: 60 * 600, fps: 60, speed: 0.5 }),
			),
		).toBe(MAX_EXPORT_SECONDS * VIDEO_FPS);
	});
});

describe("出力の大きさ", () => {
	test.each([
		["1:1", 1080, 1080, 1080],
		["16:9", 1080, 1080, 606],
		["9:16", 2160, 1214, 2160],
	] as const)(
		"%s 長辺 %i → %i×%i（短辺は偶数に切り下げ）",
		(aspect, long, width, height) => {
			expect(outputSize(aspect, long)).toEqual({ width, height });
		},
	);
});
