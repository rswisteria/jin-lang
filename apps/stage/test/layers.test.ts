import { describe, expect, test } from "vitest";

import {
	KIND_LAYERS,
	LAYER_HEIGHTS,
	layerHeight,
	ringLayer,
	stepLayer,
} from "../src/layers";

describe("層（stage.md §2）", () => {
	test("高さは 6 段", () => {
		expect(LAYER_HEIGHTS).toEqual([-0.32, 0, 0.07, 0.14, 0.21, 0.28]);
	});

	test("実際の高さは層の値 × 陣の単位（入れ子の小陣は幅に比例して低い）", () => {
		expect(layerHeight(5, 1)).toBe(0.28);
		expect(layerHeight(5, 0.25)).toBeCloseTo(0.07, 12);
		expect(layerHeight(0, 0.5)).toBeCloseTo(-0.16, 12);
		expect(layerHeight(1, 0.25)).toBe(0);
	});

	test("種別の表は形から決める 3 種を含まない", () => {
		for (const kind of ["circle", "step", "step-edge"])
			expect(KIND_LAYERS[kind]).toBeUndefined();
		expect(KIND_LAYERS["core"]).toBe(5);
		expect(KIND_LAYERS["stage"]).toBe(0);
	});

	test.each([
		[0.95, 1],
		[0.75, 2],
		[0.55, 3],
		[0.35, 4],
		[0.9, 1],
		[0.4, 4],
	])("環の半径 %f は層 %i", (ratio, layer) => {
		expect(ringLayer(ratio)).toBe(layer);
	});

	test.each([
		["/circles/1/rites/2/steps/7", 1],
		["/circles/1/rites/2/steps/7/then/1", 2],
		["/circles/1/rites/2/steps/7/then/1/steps/0", 3],
		["/circles/1/rites/2/steps/7/then/1/steps/0/else/2", 4],
		["/circles/1/rites/2/steps/7/then/1/steps/0/else/2/steps/0", 4],
	])("ステップ %s は層 %i", (pointer, layer) => {
		expect(stepLayer(pointer)).toBe(layer);
	});
});
