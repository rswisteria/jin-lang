import { describe, expect, test } from "vitest";

import type { Glow } from "../src/effects";
import { layerHeight } from "../src/layers";
import { buildGilded, NO_CIRCLE } from "../src/render/gilded";
import { GlowView } from "../src/render/glowView";
import { parseScene } from "../src/scene";

/**
 * 金環の高さ（stage.md §2・設計書 §2.1）。root の陣（核 r = 48 → 単位 1）と、その中の入れ子の小陣
 * （核 r = 13.44 → 単位 0.28）と、陣に属さない額縁。
 */
const SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="1000.000" height="1000.000" viewBox="0.000 0.000 1000.000 1000.000">
<circle data-jin="/stage" data-jin-kind="stage" cx="500" cy="500" r="490"/>
<g data-jin="/circles/0" data-jin-kind="circle">
	<circle data-jin="/circles/0" data-jin-kind="circle" cx="500" cy="500" r="380"/>
	<circle data-jin="/circles/0/core" data-jin-kind="core" cx="500" cy="500" r="48"/>
	<g data-jin="/circles/0/flow/steps/0" data-jin-kind="flow-edge">
		<g data-jin="/circles/1" data-jin-kind="circle">
			<circle data-jin="/circles/1" data-jin-kind="circle" cx="500" cy="300" r="106.400"/>
			<circle data-jin="/circles/1/core" data-jin-kind="core" cx="500" cy="300" r="13.440"/>
			<circle data-jin="/circles/1/rites/0" data-jin-kind="rite" cx="520" cy="300" r="4"/>
		</g>
	</g>
</g>
</svg>`;

const scene = parseScene(SVG);

const heights = (model: ReturnType<typeof buildGilded>, circle: string): number[] =>
	(model.circles.get(circle)?.layers ?? []).map((g) => g.position.z);

describe("層の高さは陣の単位を掛ける（stage.md §2）", () => {
	test("入れ子の小陣は幅に比例して低い（塔にならない）", () => {
		const model = buildGilded(scene);
		expect([...model.circles.keys()].sort()).toEqual([NO_CIRCLE, "/circles/0", "/circles/1"]);
		expect(heights(model, "/circles/0")).toEqual([-0.32, 0, 0.07, 0.14, 0.21, 0.28]);
		const nested = heights(model, "/circles/1");
		expect(nested[5]).toBeCloseTo(0.28 * 0.28, 12);
		expect(nested[0]).toBeCloseTo(-0.32 * 0.28, 12);
		expect(heights(model, NO_CIRCLE)[0]).toBe(-0.32);
		model.dispose();
	});

	test("光線・火花の端点（中心）も同じ高さ", () => {
		const model = buildGilded(scene);
		const rite = model.handles.get("/circles/1/rites/0")?.[0];
		expect(rite?.item.layer).toBe(4);
		expect(rite?.center.z).toBeCloseTo(layerHeight(4, 0.28), 12);
		expect(model.handles.get("/circles/0/core")?.[0]?.center.z).toBe(0.28);
		model.dispose();
	});
});

describe("陣全体の演出（設計書 §2.3）", () => {
	const glow = (fields: Partial<Glow>): Glow => ({
		seq: 1,
		target: "/circles/1",
		source: null,
		effect: "ignite",
		intensity: 1,
		progress: 0.5,
		...fields,
	});

	test("ignite は光った陣の層だけを、その陣の単位で浮かせる", () => {
		const model = buildGilded(scene);
		const view = new GlowView(model);
		view.apply([glow({})], 30, 60, scene.pointers);
		expect(heights(model, "/circles/0")).toEqual([-0.32, 0, 0.07, 0.14, 0.21, 0.28]);
		const nested = heights(model, "/circles/1");
		// 層 i の浮き = 強さ × 0.05 × i × min(1, 進み × 3) × 単位
		expect(nested[5]).toBeCloseTo((0.28 + 1 * 0.05 * 5 * 1) * 0.28, 12);
		// 時刻の関数: 光が無ければ元の高さに戻る
		view.apply([], 30, 60, scene.pointers);
		expect(heights(model, "/circles/1")[5]).toBeCloseTo(0.28 * 0.28, 12);
		view.dispose();
		model.dispose();
	});

	test("crown は陣の配下すべてを光らせ、ほかの陣は光らせない", () => {
		const model = buildGilded(scene);
		const view = new GlowView(model);
		view.apply([glow({ effect: "crown" })], 30, 60, scene.pointers);
		const emissive = (pointer: string): number[] =>
			(model.handles.get(pointer) ?? []).flatMap((h) =>
				h.glowables.map((g) => ("emissiveIntensity" in g.material ? g.material.emissiveIntensity : Number.NaN)),
			);
		for (const pointer of ["/circles/1", "/circles/1/core", "/circles/1/rites/0"])
			for (const value of emissive(pointer)) expect(value).toBeGreaterThan(0.5);
		for (const value of emissive("/circles/0")) expect(value).toBeLessThan(0.5);
		view.dispose();
		model.dispose();
	});
});
