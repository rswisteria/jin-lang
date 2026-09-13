import { describe as group, expect, test } from "vitest";

import type { AudioOut } from "../src/audio";
import type { Renderer } from "../src/canvas";
import type { JinHost } from "../src/host";
import type { InputCollector } from "../src/input";
import { MAX_CATCH_UP, Player, type Clock } from "../src/player";
import type { InputEvent, Inputs, Manifest, TickResult } from "../src/types";

const MANIFEST: Manifest = {
	file: "t.jin",
	stage: { width: 320, height: 180, fps: 60, seed: 7 },
	namespaces: ["input"],
	assets: [],
	debug: true,
	jil: "",
};

/** `boot` / `tick` の呼び出しを記録する偽ホスト。`doneAt` の tick で done を返す。 */
function fakeHost(doneAt = Infinity) {
	const calls: { t: number; inputs: Inputs }[] = [];
	const boots: number[] = [];
	const host = {
		boot: (seed: number) => {
			boots.push(seed);
		},
		tick: (t: number, inputs: Inputs): TickResult => {
			calls.push({ t, inputs });
			return {
				ops: [["rect", t, 0, 1, 1]],
				audio: [],
				trace: [
					{
						seq: t,
						tick: t,
						circle: null,
						kind: "frame",
						name: null,
						pointer: "/stage",
						input: null,
						output: null,
					},
				],
				done: t >= doneAt,
				error: null,
				public: { t },
			};
		},
		close: () => {},
	} as unknown as JinHost;
	return { host, calls, boots };
}

function fakeClock() {
	let now = 0;
	let queued: ((nowMs: number) => void) | null = null;
	const clock: Clock = {
		now: () => now,
		requestFrame: (cb) => {
			queued = cb;
		},
	};
	return {
		clock,
		/** `ms` 進めて 1 フレーム描く。 */
		frame: (ms: number) => {
			now += ms;
			const cb = queued;
			queued = null;
			cb?.(now);
		},
	};
}

function fakeCollector(queue: InputEvent[][]) {
	return {
		drain: () => queue.shift() ?? [],
		reset: () => {},
	} as unknown as InputCollector;
}

const drawn: unknown[] = [];
const renderer = {
	draw: (ops: unknown) => drawn.push(ops),
} as unknown as Renderer;
const audio = { play: () => {} } as unknown as AudioOut;

group("Player（実行ループ・runtime.md §10）", () => {
	test("1 / fps ごとに tick を呼び、1 フレームで追いつくのは最大 4 tick", () => {
		const { host, calls } = fakeHost();
		const { clock, frame } = fakeClock();
		const player = new Player({
			host,
			manifest: MANIFEST,
			renderer,
			collector: fakeCollector([]),
			audio,
			clock,
		});
		player.reboot();
		player.start();
		frame(1000 / 60); // ちょうど 1 tick
		expect(calls.map((c) => c.t)).toEqual([0]);
		frame(8); // 半分 → まだ
		expect(calls.length).toBe(1);
		frame(9); // 合わせて 17 ms → 1 tick
		expect(calls.length).toBe(2);
		frame(1000); // 60 tick 分遅れた → 4 tick だけ呼び、残りは捨てる
		expect(calls.length).toBe(2 + MAX_CATCH_UP);
		frame(1000 / 60);
		expect(calls.length).toBe(3 + MAX_CATCH_UP);
	});

	test("入力は集めた tick に渡り、録画にも同じ tick で載る（reducer は共通）", () => {
		const { host, calls } = fakeHost();
		const { clock, frame } = fakeClock();
		const queue: InputEvent[][] = [
			[],
			[{ kind: "key", name: "ArrowLeft", down: true }],
			[],
			[{ kind: "key", name: "ArrowLeft", down: false }],
		];
		const player = new Player({
			host,
			manifest: MANIFEST,
			renderer,
			collector: fakeCollector(queue),
			audio,
			clock,
		});
		player.startRecording();
		player.start();
		for (let i = 0; i < 4; i++) frame(1000 / 60);
		expect(calls[1]?.inputs).toEqual({
			events: [{ kind: "key", name: "ArrowLeft", down: true }],
			keys: { ArrowLeft: true },
			pointer: { x: 0, y: 0, down: false },
		});
		expect(calls[2]?.inputs.keys).toEqual({ ArrowLeft: true });
		expect(calls[3]?.inputs.keys).toEqual({});
		const rec = player.stopRecording();
		expect(rec?.split("\n")).toEqual([
			'{"jinrec":1,"file":"t.jin","seed":7,"fps":60,"ticks":4}',
			'{"tick":1,"kind":"key","name":"ArrowLeft","down":true}',
			'{"tick":3,"kind":"key","name":"ArrowLeft","down":false}',
			"",
		]);
	});

	test("録画は boot し直して tick 0 から始まり、トレースは boot から通しで溜まる", () => {
		const { host, boots } = fakeHost();
		const { clock, frame } = fakeClock();
		const player = new Player({
			host,
			manifest: MANIFEST,
			renderer,
			collector: fakeCollector([]),
			audio,
			clock,
		});
		player.reboot(5);
		player.start();
		frame(1000 / 60);
		frame(1000 / 60);
		expect(player.tick).toBe(2);
		player.startRecording();
		expect(player.tick).toBe(0);
		expect(boots).toEqual([5, 5]);
		expect(player.trace).toEqual([]);
		player.step();
		expect(player.trace.map((r) => r.tick)).toEqual([0]);
	});

	test("done になったら止まり、以後は進めない", () => {
		const { host, calls } = fakeHost(1);
		const { clock, frame } = fakeClock();
		const player = new Player({
			host,
			manifest: MANIFEST,
			renderer,
			collector: fakeCollector([]),
			audio,
			clock,
		});
		player.reboot();
		player.start();
		frame(100);
		expect(calls.length).toBe(2); // t=0, t=1（done）
		expect(player.done).toBe(true);
		expect(player.running).toBe(false);
		player.start();
		player.step();
		frame(100);
		expect(calls.length).toBe(2);
	});
});
