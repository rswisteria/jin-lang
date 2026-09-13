import { describe as group, expect, test } from "vitest";

import { JINREC_VERSION, Recorder } from "../src/recorder";

group("Recorder（.jinrec・runtime.md §7）", () => {
	test("1 行目はヘッダ、以降は tick 付きのイベント。ticks は実行した tick 数", () => {
		const r = new Recorder({ file: "paddle.jin", seed: 7, fps: 60 });
		r.push(0, []);
		r.push(3, [{ kind: "key", name: "ArrowLeft", down: true }]);
		r.push(9, [
			{ kind: "key", name: "ArrowLeft", down: false },
			{ kind: "pointer", x: 150, y: 110, down: true },
		]);
		const lines = r.finish(600).split("\n");
		expect(lines).toEqual([
			`{"jinrec":${JINREC_VERSION},"file":"paddle.jin","seed":7,"fps":60,"ticks":600}`,
			'{"tick":3,"kind":"key","name":"ArrowLeft","down":true}',
			'{"tick":9,"kind":"key","name":"ArrowLeft","down":false}',
			'{"tick":9,"kind":"pointer","x":150,"y":110,"down":true}',
			"",
		]);
		expect(r.events).toBe(3);
	});

	test("記憶の写しはヘッダの最後に、非空のときだけ載る（abilities.md §8）", () => {
		const empty = new Recorder({
			file: "s.jin",
			seed: 1,
			fps: 60,
			storage: {},
		});
		expect(empty.finish(2).split("\n")[0]).toBe(
			`{"jinrec":${JINREC_VERSION},"file":"s.jin","seed":1,"fps":60,"ticks":2}`,
		);
		const some = new Recorder({
			file: "s.jin",
			seed: 1,
			fps: 60,
			storage: { runs: "3", label: "run 3" },
		});
		expect(some.finish(2).split("\n")[0]).toBe(
			`{"jinrec":${JINREC_VERSION},"file":"s.jin","seed":1,"fps":60,"ticks":2,"storage":{"runs":"3","label":"run 3"}}`,
		);
	});
});
