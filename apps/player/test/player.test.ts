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
			storage: null,
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

	test("ヘッダに ticks が無い録画は jin run と同じ 600 tick 再生する（runtime.md §8）", () => {
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
		expect(
			player.replay({
				file: null,
				seed: null,
				fps: null,
				ticks: null,
				storage: null,
				events: [],
			}),
		).toBe(600);
		expect(calls).toHaveLength(600);
		expect(player.seed).toBe(MANIFEST.stage.seed);
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
				storage: null,
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

/**
 * 差し替え（runtime.md §1 の `manifest.resume`）の偽ホスト: tick 結果に `snapshot` を載せ、
 * `manifest.resume` 付きで boot されたら次の tick に `resume` の知らせを載せる。
 */
function resumableHost(mode: "resumed" | "fresh" = "resumed") {
	const boots: { seed: number; resume: unknown }[] = [];
	const calls: { t: number; inputs: Inputs }[] = [];
	let pendingNote: TickResult["resume"] | undefined;
	let seed = 0;
	const host = {
		boot: (s: number, manifest: Manifest) => {
			seed = s;
			boots.push({ seed: s, resume: manifest.resume ?? null });
			pendingNote =
				manifest.resume === undefined
					? undefined
					: {
							mode,
							tick: mode === "fresh" ? -1 : manifest.resume.tick,
							kept: mode === "fresh" ? [] : ["Only"],
							dropped: [],
						};
		},
		tick: (t: number, inputs: Inputs): TickResult => {
			calls.push({ t, inputs });
			const note = pendingNote;
			pendingNote = undefined;
			return {
				ops: [["rect", t, 0, 1, 1]],
				audio: [],
				trace: [
					{
						seq: t,
						tick: t,
						circle: "Only",
						kind: "event",
						name: "tick",
						pointer: "/circles/0",
						input: null,
						output: null,
					},
				],
				done: false,
				error: null,
				public: { "Only.n": t + 1 },
				snapshot: { tick: t, seed, seq: t, rng: "0x1", circles: [] },
				...(note === undefined ? {} : { resume: note }),
			};
		},
		close: () => {},
	} as unknown as JinHost;
	return { host, boots, calls };
}

group("Player の差し替え（状態を保つ・設計書 §11 #42）", () => {
	function make(host: JinHost, queue: InputEvent[][] = []) {
		const { clock, frame } = fakeClock();
		const notes: unknown[] = [];
		const traced: number[] = [];
		const player = new Player({
			host,
			manifest: MANIFEST,
			renderer,
			collector: fakeCollector(queue),
			audio,
			clock,
			onResume: (note) => notes.push(note),
			onTrace: (rows) => traced.push(...rows.map((r) => r.tick)),
		});
		return { player, frame, notes, traced };
	}

	test("resumeFrom は直近の snapshot を manifest.resume に付けて boot し、tick / seed / reducer / トレース / 世代を引き継ぐ", () => {
		const a = resumableHost();
		const { player: before, frame } = make(a.host, [
			[],
			[{ kind: "key", name: "ArrowLeft", down: true }],
		]);
		before.reboot(5);
		before.start();
		frame(1000 / 60);
		frame(1000 / 60);
		expect(before.tick).toBe(2);
		expect(before.lastSnapshot).toEqual({
			tick: 1,
			seed: 5,
			seq: 1,
			rng: "0x1",
			circles: [],
		});

		const b = resumableHost();
		const { player: after, notes } = make(b.host, [[]]);
		before.pause();
		expect(after.resumeFrom(before)).toBe(true);
		expect(b.boots).toEqual([{ seed: 5, resume: before.lastSnapshot }]);
		expect(after.tick).toBe(2);
		expect(after.seed).toBe(5);
		expect(after.running).toBe(false); // 走らせるかは呼ぶ側
		expect(after.generation).toBe(before.generation);
		expect(after.trace.map((r) => r.tick)).toEqual([0, 1]);
		expect(after.lastPublic).toEqual({ "Only.n": 2 });

		// 次の tick は 2 から。押したままの ArrowLeft は reducer に残っている（作り直していない）。
		after.step();
		expect(b.calls.map((c) => c.t)).toEqual([2]);
		expect(b.calls[0]?.inputs.keys).toEqual({ ArrowLeft: true });
		expect(after.lastResume).toEqual({
			mode: "resumed",
			tick: 1,
			kept: ["Only"],
			dropped: [],
		});
		expect(notes).toHaveLength(1);
		expect(after.trace.map((r) => r.tick)).toEqual([0, 1, 2]);
		expect(after.lastSnapshot?.tick).toBe(2);
		// 知らせは 1 回だけ。
		after.step();
		expect(notes).toHaveLength(1);
	});

	test("root が照合できず fresh に落ちたら、その tick は捨てて tick 0 からやり直す（世代が進む）", () => {
		const a = resumableHost();
		const { player: before, frame } = make(a.host);
		before.reboot(5);
		before.start();
		frame(1000 / 60);
		frame(1000 / 60);
		before.pause();

		const b = resumableHost("fresh");
		const { player: after, notes, traced } = make(b.host);
		expect(after.resumeFrom(before)).toBe(true);
		const generation = after.generation;
		after.step();
		// boot が 2 回（resume 付き → 通常）、捨てた tick 2 の後に tick 0 から。
		expect(b.boots.map((x) => x.resume !== null)).toEqual([true, false]);
		expect(b.calls.map((c) => c.t)).toEqual([2]);
		expect(after.tick).toBe(0);
		expect(after.trace).toEqual([]);
		expect(after.generation).toBe(generation + 1);
		expect(after.lastResume?.mode).toBe("fresh");
		expect(notes).toHaveLength(1);
		after.step();
		expect(b.calls.map((c) => c.t)).toEqual([2, 0]);
		expect(traced).toEqual([0]); // 捨てた tick 2 の行は流れない
	});

	test("snapshot が無い（release / tick 0 / 終わっている）なら resumeFrom は false", () => {
		const { host } = fakeHost(); // snapshot を載せないホスト
		const { player: before, frame } = make(host);
		before.reboot();
		before.start();
		frame(1000 / 60);
		const { player: after } = make(resumableHost().host);
		expect(after.resumeFrom(before)).toBe(false);

		const { player: fresh } = make(resumableHost().host);
		fresh.reboot();
		expect(after.resumeFrom(fresh)).toBe(false); // tick 0

		const { player: finished, frame: f2 } = make(resumableHost().host);
		finished.reboot();
		finished.start();
		f2(1000 / 60);
		finished.done = true;
		expect(after.resumeFrom(finished)).toBe(false);
	});

	test("記憶: boot に写しを渡し、tick の書き込みを store と onStore に反映する。resumeFrom は引き継ぐ", () => {
		const boots: unknown[] = [];
		const written: { writes: unknown; store: Record<string, string> }[] = [];
		const host = {
			boot: (_seed: number, manifest: Manifest) => {
				boots.push(manifest.storage);
			},
			tick: (t: number): TickResult => ({
				ops: [],
				audio: [],
				done: false,
				error: null,
				public: {},
				snapshot: { tick: t, seed: 7, seq: t, rng: "0x1", circles: [] },
				...(t === 1
					? { storage: [["runs", "2"] as const, ["label", "run 2"] as const] }
					: {}),
			}),
			close: () => {},
		} as unknown as JinHost;
		const { clock, frame } = fakeClock();
		const player = new Player({
			host,
			manifest: MANIFEST,
			renderer,
			collector: fakeCollector([]),
			audio,
			clock,
			storage: new Map([["runs", "1"]]),
			onStore: (writes, store) =>
				written.push({ writes, store: Object.fromEntries(store) }),
		});
		player.reboot();
		expect(boots).toEqual([{ runs: "1" }]);
		player.start();
		frame(17);
		expect(written).toEqual([]);
		frame(17); // tick 1 が書く
		expect(Object.fromEntries(player.store)).toEqual({
			runs: "2",
			label: "run 2",
		});
		expect(written).toEqual([
			{
				writes: [
					["runs", "2"],
					["label", "run 2"],
				],
				store: { runs: "2", label: "run 2" },
			},
		]);
		// 次の boot には更新後の写しが渡る。
		player.reboot();
		expect(boots.at(-1)).toEqual({ runs: "2", label: "run 2" });

		// 差し替えで続けるときも前の写しを引き継ぎ、resume と一緒に boot に渡す。
		player.start();
		frame(17);
		player.pause();
		const nextBoots: Manifest[] = [];
		const next = new Player({
			host: {
				boot: (_seed: number, manifest: Manifest) => {
					nextBoots.push(manifest);
				},
				tick: host.tick,
				close: () => {},
			} as unknown as JinHost,
			manifest: MANIFEST,
			renderer,
			collector: fakeCollector([]),
			audio,
			clock,
		});
		expect(next.resumeFrom(player)).toBe(true);
		expect(nextBoots[0]?.storage).toEqual({ runs: "2", label: "run 2" });
		expect(nextBoots[0]?.resume).toBeDefined();
		expect(Object.fromEntries(next.store)).toEqual({
			runs: "2",
			label: "run 2",
		});

		// forget は空にしてホストへ知らせ、空の写しで boot し直す。
		written.length = 0;
		player.forget();
		expect(player.store.size).toBe(0);
		expect(written).toEqual([{ writes: [], store: {} }]);
		expect(boots.at(-1)).toEqual({});
		expect(player.tick).toBe(0);
	});

	test("再生はヘッダの写しで boot し、書き込みをスクラッチに溜めて永続化しない。次の reboot で本物に戻る", () => {
		const boots: unknown[] = [];
		const written: unknown[] = [];
		const host = {
			boot: (_seed: number, manifest: Manifest) => {
				boots.push(manifest.storage);
			},
			tick: (t: number): TickResult => ({
				ops: [],
				audio: [],
				done: false,
				error: null,
				public: {},
				storage: [["runs", String(t + 1)]],
			}),
			close: () => {},
		} as unknown as JinHost;
		const { clock } = fakeClock();
		const player = new Player({
			host,
			manifest: MANIFEST,
			renderer,
			collector: fakeCollector([]),
			audio,
			clock,
			storage: new Map([["runs", "9"]]),
			onStore: (writes) => written.push(writes),
		});
		player.replay({
			file: null,
			seed: 3,
			fps: null,
			ticks: 2,
			storage: { runs: "0", label: "old" },
			events: [],
		});
		expect(boots).toEqual([{ runs: "0", label: "old" }]);
		expect(player.replaying).toBe(true);
		expect(written).toEqual([]); // 永続化しない
		expect(Object.fromEntries(player.store)).toEqual({ runs: "9" }); // 本物はそのまま
		// 再生の後の 1 tick もスクラッチに書く。
		player.step();
		expect(written).toEqual([]);
		expect(Object.fromEntries(player.store)).toEqual({ runs: "9" });
		// reboot で本物に戻る（ヘッダの写しは捨てる）。
		player.reboot();
		expect(player.replaying).toBe(false);
		expect(boots.at(-1)).toEqual({ runs: "9" });
		player.step();
		expect(written).toEqual([[["runs", "1"]]]);
		// 録画のヘッダには録画の boot に渡した写しが載る（seed は再生で 3 になったまま）。
		player.startRecording();
		player.step();
		expect(player.stopRecording()?.split("\n")[0]).toBe(
			'{"jinrec":1,"file":"t.jin","seed":3,"fps":60,"ticks":1,"storage":{"runs":"1"}}',
		);
	});

	test("reboot のたびに世代が進み、プレイヤーを作り直しても戻らない", () => {
		const { player: one } = make(resumableHost().host);
		one.reboot();
		const first = one.generation;
		one.reboot();
		expect(one.generation).toBe(first + 1);
		const { player: two } = make(resumableHost().host);
		two.reboot();
		expect(two.generation).toBe(first + 2);
		one.startRecording();
		expect(one.generation).toBe(first + 3);
	});
});
