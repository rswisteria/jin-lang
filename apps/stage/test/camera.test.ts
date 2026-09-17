import { describe, expect, test } from "vitest";

import {
	cameraPose,
	FIT_RADIUS,
	FOV_DEG,
	MAX_ELEVATION_DEG,
	MIN_ELEVATION_DEG,
	PRESET_ELEVATION_DEG,
} from "../src/camera";

const length = (p: readonly number[]): number => Math.hypot(...p);

describe("カメラ（stage.md §4）", () => {
	test("仰角は構図のとおり", () => {
		for (const preset of ["overhead", "oblique", "low"] as const) {
			const { position } = cameraPose(preset, 1, 0);
			expect(
				Math.asin(position[1] / length(position)) * (180 / Math.PI),
			).toBeCloseTo(PRESET_ELEVATION_DEG[preset], 10);
		}
	});

	test("正方形では縦の半視野で半径 1.45 が収まる距離", () => {
		const { position, fovDeg } = cameraPose("oblique", 1, 0);
		expect(fovDeg).toBe(FOV_DEG);
		expect(length(position)).toBeCloseTo(
			FIT_RADIUS / Math.sin(((FOV_DEG / 2) * Math.PI) / 180),
			10,
		);
	});

	test("縦長は横の半視野が狭いので遠くなり、横長は正方形と同じ", () => {
		const square = length(cameraPose("oblique", 1, 0).position);
		expect(length(cameraPose("oblique", 9 / 16, 0).position)).toBeGreaterThan(
			square,
		);
		expect(length(cameraPose("oblique", 16 / 9, 0).position)).toBeCloseTo(
			square,
			10,
		);
	});

	test("手で動かした分は構図に足され、仰角は 5°〜89° に収まる", () => {
		const base = cameraPose("oblique", 1, 0);
		const turned = cameraPose("oblique", 1, 0, {
			azimuthDeg: 90,
			elevationDeg: 10,
		});
		expect(
			Math.asin(turned.position[1] / length(turned.position)) * (180 / Math.PI),
		).toBeCloseTo(55, 10);
		expect(turned.position[0]).toBeGreaterThan(0);
		expect(length(turned.position)).toBeCloseTo(length(base.position), 10);
		const flat = cameraPose("low", 1, 0, { azimuthDeg: 0, elevationDeg: -40 });
		expect(
			Math.asin(flat.position[1] / length(flat.position)) * (180 / Math.PI),
		).toBeCloseTo(MIN_ELEVATION_DEG, 10);
		const top = cameraPose("overhead", 1, 0, {
			azimuthDeg: 0,
			elevationDeg: 40,
		});
		expect(
			Math.asin(top.position[1] / length(top.position)) * (180 / Math.PI),
		).toBeCloseTo(MAX_ELEVATION_DEG, 10);
	});

	test("周回は秒の関数（同じ秒なら同じ位置、距離は変わらない）", () => {
		expect(cameraPose("low", 1, 12.5)).toEqual(cameraPose("low", 1, 12.5));
		expect(cameraPose("low", 1, 10).position).not.toEqual(
			cameraPose("low", 1, 0).position,
		);
		expect(length(cameraPose("low", 1, 10).position)).toBeCloseTo(
			length(cameraPose("low", 1, 0).position),
			10,
		);
	});
});
