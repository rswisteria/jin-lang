import * as THREE from "three";

import type { Anchor } from "../anchors";
import { GEMS, type GemId } from "../palette";

/**
 * 宝玉の形と素材（仕様書 docs/superpowers/specs/2026-10-01-jin-stage-gem-worldview-design.md §3）。
 * 座標は層の group の中（陣は xy 面・z が上）。宝玉は要素の中心の上に置く。
 */
export type Cut = "cabochon" | "step" | "brilliant" | "rhombus" | "trillion";

export const CUT_OF_KIND: Readonly<Record<string, Cut>> = {
	sigil: "cabochon",
	state: "step",
	core: "brilliant",
	on: "rhombus",
	guard: "trillion",
	delegate: "cabochon",
};

/** 宝玉の大きさ = 置き場所の半径 × この比（核は `CORE_GEM_SCALE`）。stage.md §7。 */
export const GEM_SCALE = 0.55;
export const CORE_GEM_SCALE = 0.5;

/** 透けない・半ば透ける宝玉の透過（それ以外は 0.9）。 */
const TRANSMISSION: Partial<Record<GemId, number>> = {
	pearl: 0.1,
	onyx: 0,
	moonstone: 0.5,
	opal: 0.4,
	amber: 0.7,
	gold: 0,
};

export interface GemHandle {
	readonly anchor: Anchor;
	readonly gem: GemId;
	readonly mesh: THREE.Mesh;
	readonly material: THREE.MeshPhysicalMaterial;
	/** 内側から光るための加算のスプライト（灯るまで不透明度 0）。 */
	readonly glow: THREE.Sprite;
}

const UP = new THREE.Euler(Math.PI / 2, 0, 0);

function shapeOf(cut: Cut, r: number): THREE.BufferGeometry {
	switch (cut) {
		case "cabochon": {
			const geometry = new THREE.SphereGeometry(
				r,
				24,
				12,
				0,
				Math.PI * 2,
				0,
				Math.PI / 2,
			);
			geometry.applyMatrix4(new THREE.Matrix4().makeRotationFromEuler(UP));
			geometry.scale(1, 1, 0.6);
			return geometry;
		}
		case "step": {
			const side = r * 1.4;
			const square = new THREE.Shape();
			square.moveTo(-side / 2, -side / 2);
			square.lineTo(side / 2, -side / 2);
			square.lineTo(side / 2, side / 2);
			square.lineTo(-side / 2, side / 2);
			square.closePath();
			return new THREE.ExtrudeGeometry(square, {
				depth: r * 0.35,
				bevelEnabled: true,
				bevelThickness: r * 0.15,
				bevelSize: r * 0.15,
				bevelSegments: 1,
			});
		}
		case "brilliant":
			return lathe(
				[
					[0, -r * 0.9],
					[r, 0],
					[r * 0.6, r * 0.35],
					[0, r * 0.35],
				],
				8,
			);
		case "rhombus":
			return lathe(
				[
					[0, -r * 0.6],
					[r, 0],
					[0, r * 0.6],
				],
				4,
			);
		case "trillion":
			return lathe(
				[
					[0, -r * 0.5],
					[r, 0],
					[0, r * 0.5],
				],
				3,
			);
	}
}

/** 輪郭（半径, 高さ）を z 軸まわりに回した立体（面の数が少ないほどカットの面が立つ）。 */
function lathe(
	profile: readonly (readonly [number, number])[],
	segments: number,
): THREE.BufferGeometry {
	const geometry = new THREE.LatheGeometry(
		profile.map(([x, y]) => new THREE.Vector2(x, y)),
		segments,
	);
	geometry.applyMatrix4(new THREE.Matrix4().makeRotationFromEuler(UP));
	return geometry.toNonIndexed();
}

/** 放射状に明るさが落ちる光のテクスチャ（canvas を使わない。jsdom でも作れる）。 */
export function glowTexture(): THREE.DataTexture {
	const size = 64;
	const data = new Uint8Array(size * size * 4);
	for (let y = 0; y < size; y++) {
		for (let x = 0; x < size; x++) {
			const d = Math.hypot(x - size / 2 + 0.5, y - size / 2 + 0.5) / (size / 2);
			const a = Math.max(0, 1 - d) ** 2;
			const i = (y * size + x) * 4;
			data[i] = 255;
			data[i + 1] = 255;
			data[i + 2] = 255;
			data[i + 3] = Math.round(a * 255);
		}
	}
	const texture = new THREE.DataTexture(data, size, size);
	texture.needsUpdate = true;
	return texture;
}

export function buildGem(
	anchor: Anchor,
	gem: GemId,
	glowMap: THREE.Texture,
	disposables: { dispose(): void }[],
): GemHandle {
	const spec = GEMS[gem];
	const r =
		anchor.radius * (anchor.kind === "core" ? CORE_GEM_SCALE : GEM_SCALE);
	const geometry = shapeOf(CUT_OF_KIND[anchor.kind] ?? "cabochon", r);
	const color = new THREE.Color(spec.color);
	const metal = gem === "gold";
	const material = new THREE.MeshPhysicalMaterial({
		color,
		metalness: metal ? 1 : 0,
		roughness: metal ? 0.25 : 0.05,
		transmission: TRANSMISSION[gem] ?? 0.9,
		ior: spec.ior,
		dispersion: metal ? 0 : 0.25,
		thickness: r * 2,
		attenuationColor: color,
		attenuationDistance: r * 3,
		clearcoat: 1,
		emissive: color,
		emissiveIntensity: 0,
	});
	const mesh = new THREE.Mesh(geometry, material);
	mesh.position.set(anchor.center[0], anchor.center[1], r * 0.3);
	const glowMaterial = new THREE.SpriteMaterial({
		map: glowMap,
		color,
		transparent: true,
		opacity: 0,
		depthWrite: false,
		blending: THREE.AdditiveBlending,
	});
	const glow = new THREE.Sprite(glowMaterial);
	glow.scale.set(r * 4, r * 4, 1);
	glow.position.set(anchor.center[0], anchor.center[1], r * 0.5);
	disposables.push(geometry, material, glowMaterial);
	return { anchor, gem, mesh, material, glow };
}
