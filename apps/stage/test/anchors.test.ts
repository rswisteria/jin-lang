import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, test } from "vitest";

import { anchorsOf, GEM_KINDS } from "../src/anchors";
import { parseScene, type SceneItem } from "../src/scene";

const svg = (name: string): string =>
	readFileSync(join(__dirname, "fixtures", name), "utf8");

function bounds(items: readonly SceneItem[]): {
	minX: number;
	minY: number;
	maxX: number;
	maxY: number;
} {
	const xs: number[] = [];
	const ys: number[] = [];
	for (const { shape } of items) {
		if (shape.type === "ring" || shape.type === "dot") {
			xs.push(shape.center[0] - shape.radius, shape.center[0] + shape.radius);
			ys.push(shape.center[1] - shape.radius, shape.center[1] + shape.radius);
		} else if (shape.type === "segments") {
			for (const [a, b] of shape.segments) {
				xs.push(a[0], b[0]);
				ys.push(a[1], b[1]);
			}
		}
	}
	return {
		minX: Math.min(...xs),
		minY: Math.min(...ys),
		maxX: Math.max(...xs),
		maxY: Math.max(...ys),
	};
}

describe("宝玉の置き場所（仕様書 2026-10-01 §3.1）", () => {
	test("陣の図: 宝玉をはめる種別だけを pointer ごとに 1 つ", () => {
		const scene = parseScene(svg("play.svg"));
		const anchors = anchorsOf(scene);
		const kinds = new Set(anchors.map((a) => a.kind));
		for (const kind of ["sigil", "state", "core", "on", "guard"])
			expect(kinds.has(kind)).toBe(true);
		for (const kind of kinds) expect(GEM_KINDS.has(kind)).toBe(true);
		const pointers = anchors.map((a) => a.pointer);
		expect(new Set(pointers).size).toBe(pointers.length);
	});

	test("中心はその pointer の要素の外接矩形の中、半径は正", () => {
		const scene = parseScene(svg("play.svg"));
		for (const anchor of anchorsOf(scene)) {
			const box = bounds(
				scene.items.filter((item) => item.pointer === anchor.pointer),
			);
			expect(anchor.radius).toBeGreaterThan(0);
			expect(anchor.center[0]).toBeGreaterThanOrEqual(box.minX - 1e-9);
			expect(anchor.center[0]).toBeLessThanOrEqual(box.maxX + 1e-9);
			expect(anchor.center[1]).toBeGreaterThanOrEqual(box.minY - 1e-9);
			expect(anchor.center[1]).toBeLessThanOrEqual(box.maxY + 1e-9);
		}
	});

	test("輪を持つ要素（核）は最大の輪の中心と半径", () => {
		const scene = parseScene(svg("play.svg"));
		const core = anchorsOf(scene).find((a) => a.pointer === "/circles/1/core");
		const rings = scene.items
			.filter((item) => item.pointer === "/circles/1/core")
			.flatMap((item) => (item.shape.type === "ring" ? [item.shape] : []));
		const largest = rings.reduce((a, b) => (b.radius > a.radius ? b : a));
		expect(core?.center).toEqual(largest.center);
		expect(core?.radius).toBe(largest.radius);
	});

	test("手順の図: 紋と記憶は無く、核の宝玉だけ", () => {
		const anchors = anchorsOf(parseScene(svg("play-step.svg")));
		expect(anchors.length).toBeGreaterThan(0);
		expect(new Set(anchors.map((a) => a.kind))).toEqual(new Set(["core"]));
	});
});
