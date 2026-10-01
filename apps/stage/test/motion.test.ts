import { describe, expect, test } from "vitest";

import type { Glow } from "../src/effects";
import {
	arcPoint,
	armillary,
	cameraNudge,
	crackTilt,
	LAYER_SPIN_RAD_PER_SECOND,
	layerOffset,
	layerSpin,
	pillarHeight,
	rippleRadius,
	rotateAbout,
} from "../src/motion";

const glow = (fields: Partial<Glow>): Glow => ({
	seq: 1,
	target: "/circles/0",
	source: null,
	effect: "ignite",
	gem: "gold",
	intensity: 1,
	progress: 0.5,
	...fields,
});

describe("層の自転（仕様書 2026-10-01 §5.2）", () => {
	test("偶数層と奇数層は逆向きに同じ速さ", () => {
		expect(layerSpin(0, 10)).toBeCloseTo(LAYER_SPIN_RAD_PER_SECOND * 10, 12);
		expect(layerSpin(1, 10)).toBeCloseTo(-layerSpin(0, 10), 12);
		expect(layerSpin(2, 0)).toBe(0);
	});

	test("rotateAbout は中心まわりに回す", () => {
		const [x, y] = rotateAbout([1, 0], [0, 0], Math.PI / 2);
		expect(x).toBeCloseTo(0, 12);
		expect(y).toBeCloseTo(1, 12);
		expect(rotateAbout([2, 3], [2, 3], 1.2)).toEqual([2, 3]);
	});
});

describe("層の浮き沈み（§5.1）", () => {
	test("ignite: 沈んだ位置から下の層ほど先に上がり、元の高さに収まる", () => {
		expect(layerOffset("ignite", 0, 5)).toBeCloseTo(-0.25, 12);
		expect(layerOffset("ignite", 0, 0)).toBe(0);
		expect(layerOffset("ignite", 0.999, 5)).toBeCloseTo(0, 6);
		// 層 2 は層 3 より先に上がり切る
		const p = 0.5;
		const done2 = layerOffset("ignite", p, 2) / -0.1;
		const done3 = layerOffset("ignite", p, 3) / -0.15;
		expect(done2).toBeLessThan(done3);
	});

	test("fade と crack は沈んで戻る（端で 0）", () => {
		for (const effect of ["fade", "crack"] as const) {
			expect(layerOffset(effect, 0, 4)).toBeCloseTo(0, 12);
			expect(layerOffset(effect, 0.5, 4)).toBeLessThan(0);
			expect(layerOffset(effect, 1, 4)).toBeCloseTo(0, 12);
		}
	});

	test("ほかの演出は層を動かさない", () => {
		for (const effect of ["beam", "pulse", "crown", "spin"] as const)
			expect(layerOffset(effect, 0.5, 3)).toBe(0);
	});

	test("crack の傾きは 0 から最大 0.06 rad", () => {
		expect(crackTilt(0)).toBe(0);
		expect(crackTilt(0.5)).toBeCloseTo(0.06, 12);
		expect(crackTilt(1)).toBeCloseTo(0, 12);
	});
});

describe("光の弧・柱・波紋", () => {
	test("弧は両端を通り、中ほどが両端より高い", () => {
		const a = [0, 0, 0.1] as const;
		const b = [1, 0, 0.2] as const;
		expect(arcPoint(a, b, 0)).toEqual(a);
		const end = arcPoint(a, b, 1);
		b.forEach((value, i) => expect(end[i]).toBeCloseTo(value, 12));
		expect(arcPoint(a, b, 0.5)[2]).toBeGreaterThan(0.2);
	});

	test("柱は 0 から 2.4 まで単調に伸びる", () => {
		expect(pillarHeight(0)).toBe(0);
		expect(pillarHeight(1)).toBeCloseTo(2.4, 12);
		let previous = -1;
		for (let p = 0; p <= 1; p += 0.05) {
			expect(pillarHeight(p)).toBeGreaterThanOrEqual(previous);
			previous = pillarHeight(p);
		}
	});

	test("波紋は 0 から 0.25 まで広がる", () => {
		expect(rippleRadius(0)).toBe(0);
		expect(rippleRadius(1)).toBeCloseTo(0.25, 12);
	});
});

describe("カメラの足し分（§5.3）", () => {
	test("光が無ければ何も足さない", () => {
		expect(cameraNudge([])).toEqual({
			distanceScale: 1,
			elevationDeg: 0,
			azimuthDeg: 0,
		});
	});

	test("enter は中ほどで距離 0.9 倍まで寄る", () => {
		expect(
			cameraNudge([glow({ effect: "ignite", progress: 0.5 })]).distanceScale,
		).toBeCloseTo(0.9, 12);
	});

	test("finish は中ほどで仰角 +8°", () => {
		expect(
			cameraNudge([glow({ effect: "crown", progress: 0.5 })]).elevationDeg,
		).toBeCloseTo(8, 12);
	});

	test("error の揺れは同じ seq なら同じ、始めの 0.4 秒だけ", () => {
		const a = cameraNudge([glow({ effect: "crack", progress: 0.05, seq: 7 })]);
		const b = cameraNudge([glow({ effect: "crack", progress: 0.05, seq: 7 })]);
		expect(a).toEqual(b);
		expect(Math.abs(a.azimuthDeg) + Math.abs(a.elevationDeg)).toBeGreaterThan(
			0,
		);
		expect(Math.abs(a.azimuthDeg)).toBeLessThanOrEqual(0.6);
		expect(
			cameraNudge([glow({ effect: "crack", progress: 0.5, seq: 7 })]),
		).toEqual({ distanceScale: 1, elevationDeg: 0, azimuthDeg: 0 });
	});
});

describe("天球儀の輪（§6）", () => {
	test("同じ秒なら同じ、2 本は違う傾き", () => {
		expect(armillary(0, 3)).toEqual(armillary(0, 3));
		expect(armillary(0, 3)).not.toEqual(armillary(1, 3));
		expect(armillary(0, 0).spin).toBe(0);
	});
});
