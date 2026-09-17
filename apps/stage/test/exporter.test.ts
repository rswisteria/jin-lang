import { describe, expect, test } from "vitest";

import { type FrameEncoder, runExport } from "../src/exporter";

function fakeEncoder(): FrameEncoder & {
	added: [number, number][];
	finished: boolean;
	cancelled: boolean;
} {
	const encoder = {
		added: [] as [number, number][],
		finished: false,
		cancelled: false,
		add: (t: number, d: number) => {
			encoder.added.push([t, d]);
			return Promise.resolve();
		},
		finish: () => {
			encoder.finished = true;
			return Promise.resolve(new Uint8Array([1, 2, 3]));
		},
		cancel: () => {
			encoder.cancelled = true;
			return Promise.resolve();
		},
	};
	return encoder;
}

const range = { startTick: 0, endTick: 3, fps: 60, speed: 1 as const };

describe("1 コマずつの書き出し（stage.md §5）", () => {
	test("各コマを描いてから (n/60, 1/60) を渡し、最後にバイト列を返す", async () => {
		const encoder = fakeEncoder();
		const drawn: number[] = [];
		const progress: [number, number][] = [];
		const bytes = await runExport({
			range,
			draw: (tick) => drawn.push(tick),
			encoder,
			signal: new AbortController().signal,
			onProgress: (done, total) => progress.push([done, total]),
		});
		expect(bytes).toEqual(new Uint8Array([1, 2, 3]));
		expect(drawn).toEqual([0, 1, 2]);
		expect(encoder.added).toEqual([
			[0, 1 / 60],
			[1 / 60, 1 / 60],
			[2 / 60, 1 / 60],
		]);
		expect(progress.at(-1)).toEqual([3, 3]);
		expect(encoder.cancelled).toBe(false);
	});

	test("中止したら cancel して null（何も渡さない）", async () => {
		const encoder = fakeEncoder();
		const controller = new AbortController();
		const drawn: number[] = [];
		const bytes = await runExport({
			range: { ...range, endTick: 600 },
			draw: (tick) => {
				drawn.push(tick);
				if (tick >= 5) controller.abort();
			},
			encoder,
			signal: controller.signal,
			onProgress: () => undefined,
		});
		expect(bytes).toBeNull();
		// 中止した次のコマで止まる（600 コマを描き切ってから捨てない）
		expect(drawn).toEqual([0, 1, 2, 3, 4, 5]);
		expect(encoder.cancelled).toBe(true);
		expect(encoder.finished).toBe(false);
	});

	test("仕上げ（finish）の最中に中止したら、仕上がっても null（何も渡さない）", async () => {
		const encoder = fakeEncoder();
		const controller = new AbortController();
		encoder.finish = () => {
			encoder.finished = true;
			controller.abort();
			return Promise.resolve(new Uint8Array([1, 2, 3]));
		};
		const bytes = await runExport({
			range,
			draw: () => undefined,
			encoder,
			signal: controller.signal,
			onProgress: () => undefined,
		});
		expect(encoder.finished).toBe(true);
		expect(bytes).toBeNull();
	});

	test("エンコーダが失敗したら cancel してから投げ直す", async () => {
		const encoder = fakeEncoder();
		encoder.add = () => Promise.reject(new Error("encode failed"));
		await expect(
			runExport({
				range,
				draw: () => undefined,
				encoder,
				signal: new AbortController().signal,
				onProgress: () => undefined,
			}),
		).rejects.toThrow("encode failed");
		expect(encoder.cancelled).toBe(true);
	});
});
