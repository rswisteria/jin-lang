import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, test } from "vitest";

import { parseScene, SceneError } from "../src/scene";

const svg = (body: string, viewBox = "0.000 0.000 1000.000 1000.000"): string =>
	`<svg xmlns="http://www.w3.org/2000/svg" width="1000.000" height="1000.000" viewBox="${viewBox}">${body}</svg>`;

const PLAY = readFileSync(join(__dirname, "fixtures", "play.svg"), "utf8");

describe("座標は SVG から来たものだけ（stage.md §1）", () => {
	test("架空の座標がそのまま正規化されて出る", () => {
		const scene = parseScene(
			svg(`<g data-jin="/circles/0" data-jin-kind="circle">
				<circle data-jin="/circles/0/sigils/3" data-jin-kind="sigil" cx="637.500" cy="412.000" r="21.000"/>
			</g>`),
		);
		const [item] = scene.items;
		expect(item?.shape).toEqual({
			type: "ring",
			center: [0.34375, 0.22],
			radius: 0.0525,
		});
		expect(item?.layer).toBe(3);
		expect(item?.circle).toBe("/circles/0");
	});

	test("viewBox の大きさが違っても同じ正規化になる", () => {
		const small = parseScene(
			svg(
				'<line data-jin="/p" data-jin-kind="sigil" x1="500" y1="500" x2="900" y2="500"/>',
			),
		);
		const large = parseScene(
			svg(
				'<line data-jin="/p" data-jin-kind="sigil" x1="1000" y1="1000" x2="1800" y2="1000"/>',
				"0 0 2000 2000",
			),
		);
		expect(large.items[0]?.shape).toEqual(small.items[0]?.shape);
		expect(small.items[0]?.shape).toEqual({
			type: "segments",
			segments: [
				[
					[0, 0],
					[1, 0],
				],
			],
			spoke: true,
		});
	});

	test("パスは M / L / C / Z を線分にする", () => {
		const scene = parseScene(
			svg(
				'<path data-jin="/s" data-jin-kind="state" d="M 500.000 500.000 L 900.000 500.000 L 900.000 100.000 Z"/>',
			),
		);
		const shape = scene.items[0]?.shape;
		expect(shape?.type).toBe("segments");
		if (shape?.type !== "segments") return;
		expect(shape.segments).toHaveLength(3);
		expect(shape.segments[2]).toEqual([
			[1, 1],
			[0, 0],
		]);
	});

	test("文字と塗りのある点", () => {
		const scene = parseScene(
			svg(`<text data-jin="/c" data-jin-kind="core" x="500" y="500" font-size="18.000">begin</text>
			<circle data-jin="/c" data-jin-kind="core" cx="540" cy="500" r="6" fill="#000000"/>`),
		);
		expect(scene.items.map((i) => i.shape)).toEqual([
			{ type: "text", at: [0, 0], size: 0.045, text: "begin" },
			{ type: "dot", center: [0.1, 0], radius: 0.015 },
		]);
	});
});

describe("環の層は属する陣の核から決める", () => {
	test("入れ子の小陣（縮小された核）でも外周は層 1", () => {
		const scene = parseScene(
			svg(`<g data-jin="/circles/0" data-jin-kind="circle">
				<g data-jin="/circles/0/flow/steps/0" data-jin-kind="flow-edge">
					<g data-jin="/circles/1" data-jin-kind="circle">
						<circle data-jin="/circles/1" data-jin-kind="circle" cx="500" cy="300" r="106.400"/>
						<circle data-jin="/circles/1" data-jin-kind="circle" cx="500" cy="300" r="39.200"/>
						<circle data-jin="/circles/1/core" data-jin-kind="core" cx="500" cy="300" r="13.440"/>
					</g>
				</g>
			</g>`),
		);
		const rings = scene.items.filter((i) => i.kind === "circle");
		expect(rings.map((i) => [i.layer, i.circle])).toEqual([
			[1, "/circles/1"],
			[4, "/circles/1"],
		]);
	});

	test("paddle の Play 陣: 4 本の環が層 1〜4、額縁は層 0、pointer の集合を持つ", () => {
		const scene = parseScene(PLAY);
		const rings = scene.items.filter(
			(i) => i.kind === "circle" && i.shape.type === "ring",
		);
		expect(rings.map((i) => i.layer).sort()).toEqual([1, 2, 3, 4]);
		expect(
			scene.items
				.filter((i) => i.kind === "stage")
				.every((i) => i.layer === 0 && i.circle === null),
		).toBe(true);
		expect(scene.pointers.has("/circles/1/state/2")).toBe(true);
		expect(scene.pointers.has("/circles/1/boundary/on/0")).toBe(true);
	});
});

describe("読めない入力は SceneError", () => {
	test.each([
		["<not-svg/>", "SVG ではない"],
		['<svg xmlns="http://www.w3.org/2000/svg"></svg>', "viewBox が無い"],
		[
			svg(
				'<path data-jin="/x" data-jin-kind="state" d="M 0 0 A 1 1 0 0 1 2 2"/>',
			),
			"弧 A",
		],
		["<svg", "XML が壊れている"],
	])("%s（%s）", (text) => {
		expect(() => parseScene(text)).toThrow(SceneError);
	});
});
