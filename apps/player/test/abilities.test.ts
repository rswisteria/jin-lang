import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe as group, expect, test } from "vitest";

import {
	AUDIO_OPS,
	CANVAS_OPS,
	KEY_NAMES,
	UI_OPS,
	op,
	subscriptions,
} from "../src/abilities";

group("abilities.json から引く（コピーを置かない）", () => {
	test("キー名と op 名はリポジトリの schemas/abilities.json と同じ", () => {
		const schema = JSON.parse(
			readFileSync(join(process.cwd(), "../../schemas/abilities.json"), "utf8"),
		) as {
			keys: string[];
			namespaces: { name: string; members: { name: string }[] }[];
		};
		expect([...KEY_NAMES]).toEqual(schema.keys);
		const members = (name: string) =>
			schema.namespaces
				.find((n) => n.name === name)
				?.members.map((m) => m.name);
		expect(CANVAS_OPS).toEqual(members("canvas"));
		expect(UI_OPS).toEqual(members("ui"));
		expect(AUDIO_OPS).toEqual(members("audio"));
	});

	test("op() はカタログに無い名前を拒む", () => {
		expect(op("rect")).toBe("rect");
		expect(() => op("blit")).toThrow(/abilities\.json/);
	});

	test("購読は namespaces で決まる（runtime.md §9）", () => {
		expect(subscriptions(["canvas"])).toEqual({
			keys: false,
			pointer: false,
			text: false,
		});
		expect(subscriptions(["canvas", "ui"])).toEqual({
			keys: false,
			pointer: true,
			text: false,
		});
		// 文字（input.text）は input の許可で集める（abilities.md §3・v2.1）。
		expect(subscriptions(["canvas", "input"])).toEqual({
			keys: true,
			pointer: true,
			text: true,
		});
	});
});
