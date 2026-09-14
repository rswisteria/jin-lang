import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe as group, expect, test } from "vitest";

import {
	EVENT_KINDS,
	eventsByTick,
	JINREC_VERSION,
	parseJinrec,
} from "../src/jinrec";
import { Recorder } from "../src/recorder";

const FIXTURES = join(process.cwd(), "../../tests/fixtures/jinrec");
const BROKEN = join(FIXTURES, "broken");

group("parseJinrec は jin_wasm.jinrec.read_jinrec の写し", () => {
	test("共有 fixture（reducer.jinrec）をヘッダとイベントに分ける", () => {
		const parsed = parseJinrec(
			readFileSync(join(FIXTURES, "reducer.jinrec"), "utf8"),
		);
		expect(parsed.ok).toBe(true);
		if (!parsed.ok) return;
		expect(parsed.recording.seed).toBe(1);
		expect(parsed.recording.fps).toBe(60);
		expect(parsed.recording.ticks).toBe(5);
		expect(parsed.recording.file).toBe("reducer.jin");
		expect(parsed.recording.events.map((e) => e.tick)).toEqual([
			0, 1, 1, 2, 2, 2, 3, 4,
		]);
		const byTick = eventsByTick(parsed.recording.events, 5);
		expect(byTick.map((events) => events.length)).toEqual([1, 2, 3, 1, 1]);
		expect(byTick[1]).toEqual([
			{ kind: "pointer", x: 10, y: 20, down: false },
			{ kind: "pointer", x: 12, y: 20, down: true },
		]);
		// 確定した文字列（v2.1）は key の間に発生順のまま並ぶ。
		expect(byTick[2]?.[1]).toEqual({ kind: "text", text: "aｱ😀" });
	});

	test("Recorder が書いたものをそのまま読める（往復）", () => {
		const r = new Recorder({ file: "paddle.jin", seed: 7, fps: 60 });
		r.push(3, [{ kind: "key", name: "ArrowLeft", down: true }]);
		r.push(9, [{ kind: "pointer", x: 150, y: 110, down: true }]);
		const parsed = parseJinrec(r.finish(600));
		expect(parsed.ok).toBe(true);
		if (!parsed.ok) return;
		expect(parsed.recording).toEqual({
			file: "paddle.jin",
			seed: 7,
			fps: 60,
			ticks: 600,
			storage: null,
			events: [
				{ tick: 3, kind: "key", name: "ArrowLeft", down: true },
				{ tick: 9, kind: "pointer", x: 150, y: 110, down: true },
			],
		});
	});

	test("先頭 BOM / CRLF / 空行を通す（Python 側と同じ）", () => {
		const parsed = parseJinrec('﻿{"jinrec": 1}\r\n\n');
		expect(parsed.ok).toBe(true);
		if (!parsed.ok) return;
		expect(parsed.recording.events).toEqual([]);
		expect(parsed.recording.ticks).toBeNull();
	});

	test("ヘッダの storage（記憶の写し）を読む。無ければ null（abilities.md §8）", () => {
		const withStorage = parseJinrec(
			'{"jinrec":1,"seed":7,"ticks":2,"storage":{"runs":"3"}}\n',
		);
		expect(withStorage.ok).toBe(true);
		if (!withStorage.ok) return;
		expect(withStorage.recording.storage).toEqual({ runs: "3" });
		const without = parseJinrec('{"jinrec":1,"seed":7,"storage":null}\n');
		expect(without.ok).toBe(true);
		if (!without.ok) return;
		expect(without.recording.storage).toBeNull();
		// 往復: Recorder のヘッダをそのまま読める。
		const r = new Recorder({
			file: "s.jin",
			seed: 1,
			fps: 60,
			storage: { a: "b" },
		});
		const parsed = parseJinrec(r.finish(1));
		expect(parsed.ok && parsed.recording.storage).toEqual({ a: "b" });
	});

	test("版と kind の語彙は Python 側と同じ", () => {
		expect(JINREC_VERSION).toBe(1);
		expect([...EVENT_KINDS]).toEqual(["key", "pointer", "text"]);
	});

	/**
	 * 壊れた fixture を**同じ行番号**で拒む。期待値は `broken.expected.json` で、Python 側
	 * （`packages/jin-wasm/tests/test_jinrec_bundle.py`）も同じファイルを読む。
	 */
	const expected = JSON.parse(
		readFileSync(join(BROKEN, "broken.expected.json"), "utf8"),
	) as Record<string, { line: number | null; fragment: string }>;
	const names = readdirSync(BROKEN).filter((name) => name.endsWith(".jinrec"));
	test("壊れ fixture の一覧と期待値が一致する", () => {
		expect([...names].sort()).toEqual(Object.keys(expected).sort());
	});
	for (const name of names) {
		test(`壊れ fixture ${name} を行番号付きで拒む`, () => {
			const parsed = parseJinrec(readFileSync(join(BROKEN, name), "utf8"));
			expect(parsed.ok).toBe(false);
			if (parsed.ok) return;
			const want = expected[name];
			expect(want).toBeDefined();
			expect(parsed.line).toBe(want?.line ?? 0);
			expect(parsed.message).toContain(want?.fragment ?? "");
		});
	}
});
