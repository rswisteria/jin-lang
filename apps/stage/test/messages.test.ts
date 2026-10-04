import { describe, expect, test } from "vitest";

import {
	fileMessage,
	MAX_STAGE_SIZE,
	MIN_STAGE_SIZE,
	parseInbound,
	STAGE_FILE,
	STAGE_STATUS,
	statusMessage,
} from "../src/messages";

describe("エディタとの 4 語（stage.md §6）", () => {
	test("stage.scene", () => {
		const names = {
			Play: { pointer: "/circles/1", sigils: {}, state: {}, delegates: {} },
		};
		expect(
			parseInbound({
				type: "stage.scene",
				svg: "<svg/>",
				names,
				fps: 60,
				jinName: "paddle.jin",
				circleName: "Play",
			}),
		).toEqual({
			type: "scene",
			value: {
				svg: "<svg/>",
				inscription: null,
				names,
				fps: 60,
				jinName: "paddle.jin",
				circleName: "Play",
				stageSize: null,
				panorama: false,
			},
		});
	});

	test("stage.scene の panorama（全景・stage.md §2.3）: true だけが全景で、無い・別の型は false で場面は受ける", () => {
		const flagOf = (panorama: unknown) => {
			const parsed = parseInbound({
				type: "stage.scene",
				svg: "<svg/>",
				names: {},
				fps: 30,
				jinName: "t.jin",
				circleName: "Game",
				panorama,
			});
			return parsed?.type === "scene" ? parsed.value.panorama : "rejected";
		};
		expect(flagOf(true)).toBe(true);
		for (const other of [undefined, null, false, 1, "true"])
			expect(flagOf(other)).toBe(false);
	});

	test("stage.scene の inscription（陣書き S7・stage.md §2.2）: 文字列ならそのまま、無い・別の型なら null で場面は受ける", () => {
		const bandOf = (inscription: unknown) => {
			const parsed = parseInbound({
				type: "stage.scene",
				svg: "<svg/>",
				names: {},
				fps: 30,
				jinName: "t.jin",
				circleName: "Play",
				inscription,
			});
			return parsed?.type === "scene" ? parsed.value.inscription : "rejected";
		};
		expect(bandOf("<svg>band</svg>")).toBe("<svg>band</svg>");
		for (const other of [undefined, null, 1, true, { svg: "x" }])
			expect(bandOf(other)).toBeNull();
	});

	test("stage.scene の stageSize（仕様書 2026-10-01-jin-stage-summon §2.1）: 正しければそのまま、壊れていれば null で場面は受ける", () => {
		const scene = (stageSize: unknown) =>
			parseInbound({
				type: "stage.scene",
				svg: "<svg/>",
				names: {},
				fps: 30,
				jinName: "t.jin",
				circleName: "Play",
				stageSize,
			});
		const sizeOf = (stageSize: unknown) => {
			const parsed = scene(stageSize);
			return parsed?.type === "scene" ? parsed.value.stageSize : "rejected";
		};
		expect(sizeOf({ width: 176, height: 176 })).toEqual({
			width: 176,
			height: 176,
		});
		for (const broken of [
			undefined,
			null,
			"x",
			{ width: 0, height: 10 },
			{ width: -1, height: 10 },
			{ width: "1", height: 10 },
			{ width: 10 },
		])
			expect(sizeOf(broken)).toBeNull();
	});

	test("stageSize はモデルと同じ範囲（整数・MIN_STAGE_SIZE〜MAX_STAGE_SIZE）だけ受ける。外れたら丸めずに null（巨大な窓のテクスチャを作らない）", () => {
		const sizeOf = (stageSize: unknown) => {
			const parsed = parseInbound({
				type: "stage.scene",
				svg: "<svg/>",
				names: {},
				fps: 30,
				jinName: "t.jin",
				circleName: "Play",
				stageSize,
			});
			return parsed?.type === "scene" ? parsed.value.stageSize : "rejected";
		};
		expect(MIN_STAGE_SIZE).toBe(16);
		expect(MAX_STAGE_SIZE).toBe(1024);
		for (const ok of [
			{ width: MIN_STAGE_SIZE, height: MIN_STAGE_SIZE },
			{ width: MAX_STAGE_SIZE, height: MAX_STAGE_SIZE },
			{ width: MIN_STAGE_SIZE, height: MAX_STAGE_SIZE },
		])
			expect(sizeOf(ok)).toEqual(ok);
		for (const broken of [
			{ width: MAX_STAGE_SIZE + 1, height: 100 },
			{ width: 100, height: 1e9 },
			{ width: Number.POSITIVE_INFINITY, height: 100 },
			{ width: MIN_STAGE_SIZE - 1, height: 100 },
			{ width: 100.5, height: 100 },
			{ width: 100, height: Number.NaN },
		])
			expect(sizeOf(broken)).toBeNull();
	});

	test("stage.scene は宝玉の 3 欄（sigilKinds / stateTypes / isRoot）があってもそのまま受ける", () => {
		const names = {
			Game: {
				pointer: "/circles/0",
				sigils: {},
				state: {},
				delegates: {},
				sigilKinds: {},
				stateTypes: {},
				isRoot: true,
			},
			Play: {
				pointer: "/circles/1",
				sigils: { canvas: "/circles/1/sigils/0" },
				state: {},
				delegates: {},
				sigilKinds: { canvas: "canvas" },
				stateTypes: { score: "num" },
			},
		};
		const parsed = parseInbound({
			type: "stage.scene",
			svg: "<svg/>",
			names,
			fps: 30,
			jinName: "t.jin",
			circleName: "Play",
		});
		expect(parsed?.type).toBe("scene");
		expect(parsed?.type === "scene" ? parsed.value.names : null).toEqual(names);
	});

	test("stage.trace（行の配列と seed）", () => {
		const rows = [
			{
				seq: 0,
				tick: -1,
				circle: "Play",
				kind: "enter",
				pointer: "/circles/1",
			},
		];
		expect(parseInbound({ type: "stage.trace", rows, seed: 7 })).toEqual({
			type: "trace",
			value: { rows, seed: 7 },
		});
		expect(parseInbound({ type: "stage.trace", rows, seed: null })).toEqual({
			type: "trace",
			value: { rows, seed: null },
		});
	});

	test("stage.trace は frame 行（circle が null・runtime.md §5）を含む実物の列を受ける", () => {
		const rows = [
			{
				seq: 0,
				tick: -1,
				circle: "Play",
				kind: "enter",
				pointer: "/circles/1",
			},
			{
				seq: 1,
				tick: 0,
				circle: null,
				kind: "frame",
				name: null,
				pointer: "/stage",
				output: { ops: [] },
			},
		];
		expect(parseInbound({ type: "stage.trace", rows, seed: 7 })).toEqual({
			type: "trace",
			value: { rows, seed: 7 },
		});
	});

	test.each([
		[null],
		["stage.scene"],
		[
			{
				type: "stage.scene",
				svg: 1,
				names: {},
				fps: 60,
				jinName: "",
				circleName: "",
			},
		],
		[
			{
				type: "stage.scene",
				svg: "",
				names: {},
				fps: 0,
				jinName: "",
				circleName: "",
			},
		],
		[{ type: "stage.trace", rows: "x", seed: 1 }],
		[{ type: "stage.trace", rows: [{ seq: "0" }], seed: 1 }],
		[
			{
				type: "stage.trace",
				rows: [
					{ seq: 0, tick: 0, circle: 1, kind: "frame", pointer: "/stage" },
				],
				seed: 1,
			},
		],
		[{ type: "jin.load" }],
	])("形の違う message は null: %j", (data) => {
		expect(parseInbound(data)).toBeNull();
	});

	test("stage.status と stage.file", () => {
		expect(
			statusMessage({
				ready: true,
				rows: 3,
				codec: "vp9",
				exporting: null,
				error: null,
			}),
		).toEqual({
			type: STAGE_STATUS,
			ready: true,
			rows: 3,
			codec: "vp9",
			exporting: null,
			error: null,
		});
		const bytes = new ArrayBuffer(2);
		expect(fileMessage("a.png", "image/png", bytes)).toEqual({
			type: STAGE_FILE,
			name: "a.png",
			mime: "image/png",
			bytes,
		});
	});
});
