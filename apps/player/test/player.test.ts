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

	test("録画の再生: ヘッダの seed で boot し、録画の tick にだけイベントが渡り、止まったまま終わる", () => {
		const { host, calls, boots } = fakeHost();
		const { clock, frame } = fakeClock();
		const traced: unknown[][] = [];
		const drained: number[] = [];
		const collector = {
			drain: () => {
				drained.push(1);
				return [{ kind: "key", name: "ArrowRight", down: true }];
			},
			reset: () => {},
		} as unknown as InputCollector;
		const player = new Player({
			host,
			manifest: MANIFEST,
			renderer,
			collector,
			audio,
			clock,
			onTrace: (rows) => traced.push([...rows]),
		});
		player.reboot(1);
		player.start();
		frame(1000 / 60);
		expect(player.tick).toBe(1);
		calls.length = 0;
		traced.length = 0;
		drained.length = 0;

		const ticks = player.replay({
			file: "t.jin",
			seed: 9,
			fps: 60,
			ticks: 4,
			events: [
				{ tick: 1, kind: "key", name: "ArrowLeft", down: true },
				{ tick: 3, kind: "key", name: "ArrowLeft", down: false },
				{ tick: 3, kind: "pointer", x: 5, y: 6, down: true },
				{ tick: 40, kind: "key", name: "Space", down: true }, // ticks の外は捨てる
			],
		});
		expect(ticks).toBe(4);
		expect(boots.at(-1)).toBe(9);
		expect(player.seed).toBe(9);
		expect(player.tick).toBe(4);
		expect(player.running).toBe(false);
		// 実入力は読まない（録画の行だけを同じ reducer に通す）。
		expect(drained).toEqual([]);
		expect(calls.map((c) => c.t)).toEqual([0, 1, 2, 3]);
		expect(calls[0]?.inputs.events).toEqual([]);
		expect(calls[1]?.inputs).toEqual({
			events: [{ kind: "key", name: "ArrowLeft", down: true }],
			keys: { ArrowLeft: true },
			pointer: { x: 0, y: 0, down: false },
		});
		expect(calls[2]?.inputs.keys).toEqual({ ArrowLeft: true });
		expect(calls[3]?.inputs).toEqual({
			events: [
				{ kind: "key", name: "ArrowLeft", down: false },
				{ kind: "pointer", x: 5, y: 6, down: true },
			],
			keys: {},
			pointer: { x: 5, y: 6, down: true },
		});
		// トレースは boot から通しで溜まり、親へは**最後に 1 回**流す。
		expect(player.trace.map((r) => r.tick)).toEqual([0, 1, 2, 3]);
		expect(traced).toHaveLength(1);
		expect(traced[0]).toHaveLength(4);
		// 止まったままなので、そこから 1 tick 進められる。
		player.step();
		expect(player.tick).toBe(5);
	});

	test("再生は root が done になったらそこで止まる", () => {
		const { host, calls } = fakeHost(1);
		const { clock } = fakeClock();
		const player = new Player({
			host,
			manifest: MANIFEST,
			renderer,
			collector: fakeCollector([]),
			audio,
			clock,
		});
		expect(
			player.replay({
				file: null,
				seed: null,
				fps: null,
				ticks: 10,
				events: [],
			}),
		).toBe(2);
		expect(calls.map((c) => c.t)).toEqual([0, 1]);
		expect(player.done).toBe(true);
	});

	test("show は表示リストを描くだけで tick を呼ばず、走っている間は無視する", () => {
		const { host, calls } = fakeHost();
		const { clock } = fakeClock();
		const player = new Player({
			host,
			manifest: MANIFEST,
			renderer,
			collector: fakeCollector([]),
			audio,
			clock,
		});
		player.reboot();
		drawn.length = 0;
		const ops = [["rect", 1, 2, 3, 4]] as const;
		expect(player.show(ops)).toBe(true);
		expect(drawn).toEqual([ops]);
		expect(player.lastOps).toBe(ops);
		expect(calls).toEqual([]);
		player.start();
		expect(player.show(ops)).toBe(false);
		expect(drawn).toHaveLength(1);
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
