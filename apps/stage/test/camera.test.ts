import { describe, expect, test } from "vitest";

import {
	cameraPose,
	FIT_RADIUS,
	FOV_DEG,
	MAX_ELEVATION_DEG,
	MAX_ZOOM,
	MIN_ELEVATION_DEG,
	MIN_ZOOM,
	NO_OFFSET,
	PAN_LIMIT,
	PRESET_ELEVATION_DEG,
	panBy,
	wheelZoomFactor,
	zoomBy,
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

describe("トレースから決まるカメラの足し分（仕様書 2026-10-01 §5.3）", () => {
	const elevation = (p: readonly number[]): number =>
		(Math.asin(p[1]! / length(p)) * 180) / Math.PI;

	test("距離は掛け、仰角と方位角は足す", () => {
		const base = cameraPose("oblique", 1, 0);
		const near = cameraPose("oblique", 1, 0, undefined, {
			distanceScale: 0.9,
			elevationDeg: 0,
			azimuthDeg: 0,
		});
		expect(length(near.position)).toBeCloseTo(length(base.position) * 0.9, 10);
		const up = cameraPose("oblique", 1, 0, undefined, {
			distanceScale: 1,
			elevationDeg: 8,
			azimuthDeg: 0,
		});
		expect(elevation(up.position)).toBeCloseTo(
			PRESET_ELEVATION_DEG.oblique + 8,
			8,
		);
	});

	test("足しても仰角は 5°〜89° に収まる", () => {
		const high = cameraPose(
			"overhead",
			1,
			0,
			{ azimuthDeg: 0, elevationDeg: 8 },
			{ distanceScale: 1, elevationDeg: 8, azimuthDeg: 0 },
		);
		expect(elevation(high.position)).toBeCloseTo(MAX_ELEVATION_DEG, 8);
		const low = cameraPose("low", 1, 0, undefined, {
			distanceScale: 1,
			elevationDeg: -30,
			azimuthDeg: 0,
		});
		expect(elevation(low.position)).toBeCloseTo(MIN_ELEVATION_DEG, 8);
	});
});

describe("召喚の窓を収める半径（仕様書 2026-10-01-jin-stage-summon §1.1）", () => {
	test("fitRadius を渡すと距離がその比で伸びる", () => {
		const base = cameraPose("oblique", 16 / 9, 3);
		const wide = cameraPose(
			"oblique",
			16 / 9,
			3,
			undefined,
			undefined,
			FIT_RADIUS * 1.2,
		);
		expect(length(wide.position)).toBeCloseTo(length(base.position) * 1.2, 10);
	});
});

describe("手で寄る・引く・注視点をずらす（stage.md §4）", () => {
	const minus = (a: readonly number[], b: readonly number[]): number[] =>
		a.map((v, i) => v - (b[i] ?? 0));
	const halfV = ((FOV_DEG / 2) * Math.PI) / 180;

	test("初期の足し分は寄りなし・ずらしなしで、注視点は原点", () => {
		expect(NO_OFFSET.zoom).toBe(1);
		expect(NO_OFFSET.pan).toEqual([0, 0]);
		expect(cameraPose("oblique", 1, 0).target).toEqual([0, 0, 0]);
	});

	test("zoom は注視点からの距離に掛かる（方向は変わらない）", () => {
		const base = cameraPose("oblique", 16 / 9, 2);
		const near = cameraPose("oblique", 16 / 9, 2, { ...NO_OFFSET, zoom: 0.5 });
		expect(length(near.position)).toBeCloseTo(length(base.position) * 0.5, 10);
		for (let i = 0; i < 3; i++)
			expect((near.position[i] ?? 0) / length(near.position)).toBeCloseTo(
				(base.position[i] ?? 0) / length(base.position),
				10,
			);
	});

	test("pan は位置と注視点を床の上で同じだけずらす（周回はずらした注視点のまわり）", () => {
		const base = cameraPose("oblique", 1, 3);
		const moved = cameraPose("oblique", 1, 3, {
			...NO_OFFSET,
			pan: [0.5, -0.3],
		});
		expect(moved.target).toEqual([0.5, 0, -0.3]);
		const shift = minus(moved.position, base.position);
		expect(shift[0]).toBeCloseTo(0.5, 10);
		expect(shift[1]).toBeCloseTo(0, 10);
		expect(shift[2]).toBeCloseTo(-0.3, 10);
	});

	test("zoomBy は倍率を掛けて MIN_ZOOM〜MAX_ZOOM に収め、壊れた倍率では変えない", () => {
		expect(zoomBy(NO_OFFSET, 0.5).zoom).toBeCloseTo(0.5, 12);
		let offset = NO_OFFSET;
		for (let i = 0; i < 50; i++) offset = zoomBy(offset, 0.8);
		expect(offset.zoom).toBe(MIN_ZOOM);
		for (let i = 0; i < 50; i++) offset = zoomBy(offset, 1.25);
		expect(offset.zoom).toBe(MAX_ZOOM);
		for (const broken of [0, -1, Number.NaN, Number.POSITIVE_INFINITY])
			expect(zoomBy(NO_OFFSET, broken)).toEqual(NO_OFFSET);
		expect(MIN_ZOOM).toBe(0.25);
		expect(MAX_ZOOM).toBe(2.5);
	});

	test("ホイールは下へ回すと引き、上へ回すと寄る", () => {
		expect(wheelZoomFactor(100)).toBeGreaterThan(1);
		expect(wheelZoomFactor(-100)).toBeLessThan(1);
		expect(wheelZoomFactor(100) * wheelZoomFactor(-100)).toBeCloseTo(1, 12);
	});

	test("panBy: 横のドラッグは注視点の深さで画面に陣がついてくる量だけ、逆向きに注視点をずらす", () => {
		// 方位角 0（秒 0）のカメラは +z にいて −z を向く。画面の右は +x。
		const view = {
			preset: "oblique" as const,
			aspect: 1,
			seconds: 0,
			heightPx: 800,
		};
		const distance = length(cameraPose("oblique", 1, 0).position);
		const moved = panBy(NO_OFFSET, 100, 0, view);
		expect(moved.pan?.[0]).toBeCloseTo((-distance * Math.tan(halfV)) / 4, 10);
		expect(moved.pan?.[1]).toBeCloseTo(0, 10);
		// 下へのドラッグは注視点を奥（−z）へ。
		expect(panBy(NO_OFFSET, 0, 100, view).pan?.[1]).toBeLessThan(0);
		// 寄っているほど少なく動く。
		const near = panBy({ ...NO_OFFSET, zoom: 0.5 }, 100, 0, view);
		expect(near.pan?.[0]).toBeCloseTo((-distance * 0.5 * Math.tan(halfV)) / 4, 10);
	});

	test("panBy は注視点を PAN_LIMIT（額縁の内側）に収め、他の足し分は変えない", () => {
		const view = {
			preset: "overhead" as const,
			aspect: 1,
			seconds: 0,
			heightPx: 100,
		};
		const start = {
			azimuthDeg: 30,
			elevationDeg: 5,
			zoom: 2,
			pan: [0, 0] as const,
		};
		const far = panBy(start, -100000, 0, view);
		expect(Math.hypot(...(far.pan ?? [0, 0]))).toBeCloseTo(PAN_LIMIT, 10);
		expect(far.azimuthDeg).toBe(30);
		expect(far.elevationDeg).toBe(5);
		expect(far.zoom).toBe(2);
		expect(PAN_LIMIT).toBe(1.25);
	});
});
