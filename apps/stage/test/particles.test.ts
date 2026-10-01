import { describe, expect, test } from "vitest";

import type { Glow } from "../src/effects";
import { arcPoint, type Vec3 } from "../src/motion";
import {
	AMBIENT_COUNT,
	ambient,
	burst,
	collect,
	MAX_PARTICLES,
} from "../src/particles";

const glow = (fields: Partial<Glow>): Glow => ({
	seq: 3,
	target: "/circles/1/sigils/0",
	source: "/circles/1/rites/2",
	effect: "beam",
	gem: "sapphire",
	intensity: 1,
	progress: 0.5,
	...fields,
});

const AT: Vec3 = [0.5, 0.2, 0.14];
const FROM: Vec3 = [-0.2, 0.1, 0.21];
const distance = (a: Vec3, b: Vec3): number =>
	Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);

describe("粒子の 1 系統（仕様書 2026-10-01 §5.1 / §6）", () => {
	test("同じ引数なら同じ粒子（決定性）", () => {
		for (const effect of [
			"chant",
			"release",
			"crown",
			"flow",
			"breathe",
			"beam",
			"flash",
		] as const) {
			const g = glow({ effect });
			expect(burst(g, AT, FROM, 0.03, 2)).toEqual(burst(g, AT, FROM, 0.03, 2));
		}
		expect(ambient(4.5)).toEqual(ambient(4.5));
	});

	test("beam の粒子は出どころと行き先を結ぶ弧の上", () => {
		const particles = burst(
			glow({ effect: "beam", progress: 0.4 }),
			AT,
			FROM,
			0.03,
			0,
		);
		expect(particles.length).toBe(8);
		for (const particle of particles) {
			const nearest = Math.min(
				...Array.from({ length: 201 }, (_, i) =>
					distance(arcPoint(FROM, AT, i / 200), particle.position),
				),
			);
			expect(nearest).toBeLessThan(0.01);
		}
	});

	test("出どころが無ければ beam と flow は粒子を出さない", () => {
		expect(burst(glow({ effect: "beam" }), AT, null, 0.03, 0)).toEqual([]);
		expect(burst(glow({ effect: "flow" }), AT, null, 0.03, 0)).toEqual([]);
	});

	test("chant の粒子は進みとともに行き先へ近づく", () => {
		const mean = (progress: number): number => {
			const particles = burst(
				glow({ effect: "chant", progress }),
				AT,
				null,
				0.03,
				0,
			);
			return (
				particles.reduce((sum, p) => sum + distance(p.position, AT), 0) /
				particles.length
			);
		};
		expect(mean(0.8)).toBeLessThan(mean(0.1));
	});

	test("flash の粒子は記憶の四角の輪郭の上", () => {
		const half = 0.03;
		for (const p of burst(glow({ effect: "flash" }), AT, null, half, 0)) {
			const dx = Math.abs(p.position[0] - AT[0]);
			const dy = Math.abs(p.position[1] - AT[1]);
			expect(Math.max(dx, dy)).toBeCloseTo(half, 9);
		}
	});

	test("色は宝玉の色、明るさは光の強さ", () => {
		const particles = burst(
			glow({ effect: "beam", intensity: 0.4 }),
			AT,
			FROM,
			0.03,
			0,
		);
		for (const p of particles) {
			expect(p.color).toBe(0x2f6bff);
			expect(p.alpha).toBeCloseTo(0.4, 12);
		}
	});

	test("光らない演出は粒子を出さない", () => {
		for (const effect of [
			"ignite",
			"fade",
			"spin",
			"warn",
			"crack",
			"pulse",
		] as const)
			expect(burst(glow({ effect }), AT, FROM, 0.03, 0)).toEqual([]);
	});

	test("発火が無くても漂う粒子は AMBIENT_COUNT 個", () => {
		expect(AMBIENT_COUNT).toBe(460);
		expect(collect([], () => null, 0).length).toBe(AMBIENT_COUNT);
	});

	test("crown を 200 個重ねても MAX_PARTICLES を超えない", () => {
		const glows = Array.from({ length: 200 }, (_, i) =>
			glow({ effect: "crown", seq: i }),
		);
		const particles = collect(
			glows,
			() => ({ at: AT, from: null, size: 0.03 }),
			1,
		);
		expect(particles.length).toBe(MAX_PARTICLES);
	});
});
