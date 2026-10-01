import * as THREE from "three";
import { describe, expect, test } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

import type { Glow } from "../src/effects";
import { layerHeight } from "../src/layers";
import { layerOffset, layerSpin, rotateAbout } from "../src/motion";
import type { StageNames } from "../src/names";
import { GEMS, METALS } from "../src/palette";
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

const heights = (
	model: ReturnType<typeof buildGilded>,
	circle: string,
): number[] =>
	(model.circles.get(circle)?.layers ?? []).map((g) => g.position.z);

describe("層の高さは陣の単位を掛ける（stage.md §2）", () => {
	test("入れ子の小陣は幅に比例して低い（塔にならない）", () => {
		const model = buildGilded(scene);
		expect([...model.circles.keys()].sort()).toEqual([
			NO_CIRCLE,
			"/circles/0",
			"/circles/1",
		]);
		expect(heights(model, "/circles/0")).toEqual([
			-0.32, 0, 0.07, 0.14, 0.21, 0.28,
		]);
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
		gem: "gold",
		effect: "ignite",
		intensity: 1,
		progress: 0.5,
		...fields,
	});

	test("ignite は光った陣の層だけを、沈んだ位置からその陣の単位で上げる（仕様書 2026-10-01 §5.1）", () => {
		const model = buildGilded(scene);
		const view = new GlowView(model);
		view.apply([glow({ progress: 0.5 })], 0, 60, scene.pointers);
		expect(heights(model, "/circles/0")).toEqual([
			-0.32, 0, 0.07, 0.14, 0.21, 0.28,
		]);
		const nested = heights(model, "/circles/1");
		// 層の高さ = (層の値 + layerOffset) × 単位
		expect(nested[5]).toBeCloseTo(
			(0.28 + layerOffset("ignite", 0.5, 5)) * 0.28,
			12,
		);
		expect(nested[5]).toBeLessThan(0.28 * 0.28);
		// 時刻の関数: 光が無ければ元の高さに戻る
		view.apply([], 0, 60, scene.pointers);
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
				h.glowables.map((g) =>
					"emissiveIntensity" in g.material
						? g.material.emissiveIntensity
						: Number.NaN,
				),
			);
		for (const pointer of [
			"/circles/1",
			"/circles/1/core",
			"/circles/1/rites/0",
		])
			for (const value of emissive(pointer)) expect(value).toBeGreaterThan(0.5);
		for (const value of emissive("/circles/0")) expect(value).toBeLessThan(0.5);
		view.dispose();
		model.dispose();
	});
});

describe("宝玉と地金（仕様書 2026-10-01 §2.3 / §3）", () => {
	const names: StageNames = {
		Game: {
			pointer: "/circles/0",
			sigils: {},
			state: {},
			delegates: {},
			isRoot: true,
		},
		Play: { pointer: "/circles/1", sigils: {}, state: {}, delegates: {} },
	};

	test("核にはダイヤの宝玉をはめ、屈折率は宝玉の値", () => {
		const model = buildGilded(scene, names);
		const core = model.gems.get("/circles/0/core");
		expect(core?.gem).toBe("diamond");
		expect(core?.material.ior).toBeCloseTo(GEMS.diamond.ior, 6);
		expect(core?.material.transmission).toBeGreaterThan(0.5);
		expect(model.gems.has("/circles/1/rites/0")).toBe(false);
		model.dispose();
	});

	test("金細工の色は陣の地金（root はイエロー、次はローズ）", () => {
		const model = buildGilded(scene, names);
		const ringColor = (pointer: string): number | undefined => {
			const material = model.handles.get(pointer)?.[0]?.glowables[0]?.material;
			return material instanceof THREE.MeshStandardMaterial
				? material.color.getHex()
				: undefined;
		};
		expect(ringColor("/circles/0")).toBe(
			new THREE.Color(METALS.yellow.color).getHex(),
		);
		expect(ringColor("/circles/1")).toBe(
			new THREE.Color(METALS.rose.color).getHex(),
		);
		model.dispose();
	});

	test("名前の表が無くても組み立てられ、核の宝玉は置かれる", () => {
		const model = buildGilded(scene);
		expect(model.gems.get("/circles/1/core")?.gem).toBe("diamond");
		model.dispose();
	});

	test("自転の中心は陣の輪の中心（額縁は原点）", () => {
		const model = buildGilded(scene, names);
		const ring = (pointer: string): readonly [number, number] | undefined => {
			const shape = scene.items.find(
				(i) => i.pointer === pointer && i.kind === "circle",
			)?.shape;
			return shape?.type === "ring" ? shape.center : undefined;
		};
		expect(model.pivots.get("/circles/0")).toEqual(ring("/circles/0"));
		expect(model.pivots.get("/circles/1")).toEqual(ring("/circles/1"));
		expect(model.pivots.get(NO_CIRCLE)).toEqual([0, 0]);
		model.dispose();
	});
});

describe("宝玉の色の光と層の自転（仕様書 2026-10-01 §5）", () => {
	const play = parseScene(
		readFileSync(join(__dirname, "fixtures", "play.svg"), "utf8"),
	);
	const names: StageNames = {
		Game: {
			pointer: "/circles/0",
			sigils: {},
			state: {},
			delegates: {},
			isRoot: true,
		},
		Play: {
			pointer: "/circles/1",
			sigils: {
				canvas: "/circles/1/sigils/0",
				input: "/circles/1/sigils/1",
				audio: "/circles/1/sigils/2",
			},
			state: {},
			delegates: {},
			sigilKinds: { canvas: "canvas", input: "input", audio: "audio" },
		},
	};
	const beam = (fields: Partial<Glow>): Glow => ({
		seq: 5,
		target: "/circles/1/sigils/0",
		source: "/circles/1/rites/2",
		effect: "beam",
		gem: "sapphire",
		intensity: 1,
		progress: 0.3,
		...fields,
	});

	test("cast canvas.* でサファイアの宝玉が灯り、核の宝玉がその色に染まる", () => {
		const model = buildGilded(play, names);
		const view = new GlowView(model);
		view.apply([beam({})], 0, 60, play.pointers);
		const sigil = model.gems.get("/circles/1/sigils/0");
		expect(sigil?.material.emissiveIntensity).toBeGreaterThan(0.5);
		expect(sigil?.glow.material.opacity).toBeGreaterThan(0.5);
		const core = model.gems.get("/circles/1/core");
		expect(core?.material.emissive.getHex()).toBe(
			new THREE.Color(GEMS.sapphire.color).getHex(),
		);
		expect(core?.material.emissiveIntensity).toBeGreaterThan(0);
		view.apply([], 0, 60, play.pointers);
		expect(
			model.gems.get("/circles/1/sigils/0")?.material.emissiveIntensity,
		).toBe(0);
		view.dispose();
		model.dispose();
	});

	test("層の自転で光線の端点も同じ角だけ陣の中心まわりに回る", () => {
		const model = buildGilded(play, names);
		const view = new GlowView(model);
		const seconds = 7;
		view.apply([], seconds * 60, 60, play.pointers);
		const rite = model.handles.get("/circles/1/rites/2")?.[0];
		const pivot = model.pivots.get("/circles/1");
		expect(rite?.item.layer).toBe(4);
		const shape = rite?.item.shape;
		const center = shape?.type === "ring" ? shape.center : null;
		expect(center).not.toBeNull();
		if (center === null || pivot === undefined || rite === undefined) return;
		const [x, y] = rotateAbout(center, pivot, layerSpin(4, seconds));
		const end = view.endpointOf("/circles/1/rites/2");
		expect(end?.x).toBeCloseTo(x, 9);
		expect(end?.y).toBeCloseTo(y, 9);
		expect(end?.z).toBeCloseTo(layerHeight(4, rite.item.unit), 9);
		view.dispose();
		model.dispose();
	});
});
