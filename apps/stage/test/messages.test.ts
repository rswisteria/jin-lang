import { describe, expect, test } from "vitest";

import { fileMessage, parseInbound, STAGE_FILE, STAGE_STATUS, statusMessage } from "../src/messages";

describe("エディタとの 4 語（stage.md §6）", () => {
	test("stage.scene", () => {
		const names = { Play: { pointer: "/circles/1", sigils: {}, state: {}, delegates: {} } };
		expect(parseInbound({ type: "stage.scene", svg: "<svg/>", names, fps: 60, jinName: "paddle.jin", circleName: "Play" })).toEqual({
			type: "scene",
			value: { svg: "<svg/>", names, fps: 60, jinName: "paddle.jin", circleName: "Play" },
		});
	});

	test("stage.trace（行の配列と seed）", () => {
		const rows = [{ seq: 0, tick: -1, circle: "Play", kind: "enter", pointer: "/circles/1" }];
		expect(parseInbound({ type: "stage.trace", rows, seed: 7 })).toEqual({ type: "trace", value: { rows, seed: 7 } });
		expect(parseInbound({ type: "stage.trace", rows, seed: null })).toEqual({ type: "trace", value: { rows, seed: null } });
	});

	test.each([
		[null],
		["stage.scene"],
		[{ type: "stage.scene", svg: 1, names: {}, fps: 60, jinName: "", circleName: "" }],
		[{ type: "stage.scene", svg: "", names: {}, fps: 0, jinName: "", circleName: "" }],
		[{ type: "stage.trace", rows: "x", seed: 1 }],
		[{ type: "stage.trace", rows: [{ seq: "0" }], seed: 1 }],
		[{ type: "jin.load" }],
	])("形の違う message は null: %j", (data) => {
		expect(parseInbound(data)).toBeNull();
	});

	test("stage.status と stage.file", () => {
		expect(statusMessage({ ready: true, rows: 3, codec: "vp9", exporting: null, error: null })).toEqual({
			type: STAGE_STATUS,
			ready: true,
			rows: 3,
			codec: "vp9",
			exporting: null,
			error: null,
		});
		const bytes = new ArrayBuffer(2);
		expect(fileMessage("a.png", "image/png", bytes)).toEqual({ type: STAGE_FILE, name: "a.png", mime: "image/png", bytes });
	});
});
