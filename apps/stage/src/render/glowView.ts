import * as THREE from "three";
import { LineMaterial } from "three/addons/lines/LineMaterial.js";
import { LineSegments2 } from "three/addons/lines/LineSegments2.js";
import { LineSegmentsGeometry } from "three/addons/lines/LineSegmentsGeometry.js";

import { type Glow, WHOLE_CIRCLE } from "../effects";
import { LAYER_HEIGHTS, type LayerIndex, layerHeight } from "../layers";
import { nearestInScene } from "../names";
import { mulberry32 } from "../random";
import { BASE_EMISSIVE, EMBER, GOLD_HOT, type GildedModel, type ItemHandle, WARN_RED } from "./gilded";

/**
 * Glow の列 → 素材の明るさ・層の浮き上がり・光線・火花（docs/spec/v2/stage.md §3・設計書 §2.3）。
 * **時刻の関数**: 同じ (glows, tick, fps) なら同じ状態にする（前のフレームの状態を持ち越さない）。
 */
const MAX_BEAMS = 24;
const SPARKS_PER_BURST = 18;
const MAX_SPARKS = 540;
const AMBIENT_EMBERS = 260;
const EMISSIVE_GAIN = 1.6;
const COLOR_GAIN = 1.2;
const BEAM_WIDTH_PX = 2.5;

export class GlowView {
	/**
	 * 光線は 1 本の LineSegments2 に MAX_BEAMS 本ぶんの枠を持ち、配列を書き換えて `instanceCount` で本数を絞る
	 * （毎フレーム `setPositions` すると GPU のバッファを作り直し続ける）。明るさは頂点色に強さを掛けて表す。
	 */
	private readonly beamPositions = new Float32Array(MAX_BEAMS * 6);
	private readonly beamColors = new Float32Array(MAX_BEAMS * 6);
	private readonly beamGeometry = new LineSegmentsGeometry();
	private readonly beams: LineSegments2;
	private readonly beamMaterial = new LineMaterial({
		color: 0xffffff,
		linewidth: BEAM_WIDTH_PX,
		vertexColors: true,
		transparent: true,
		depthWrite: false,
		blending: THREE.AdditiveBlending,
	});
	private readonly sparkPositions = new Float32Array(MAX_SPARKS * 3);
	private readonly sparkColors = new Float32Array(MAX_SPARKS * 3);
	private readonly sparks: THREE.Points;
	private readonly emberPositions = new Float32Array(AMBIENT_EMBERS * 3);
	private readonly embers: THREE.Points;
	private readonly emberSeeds: readonly (readonly [number, number, number, number])[];

	constructor(private readonly model: GildedModel) {
		this.beamGeometry.setPositions(this.beamPositions);
		this.beamGeometry.setColors(this.beamColors);
		this.beamGeometry.instanceCount = 0;
		this.beams = new LineSegments2(this.beamGeometry, this.beamMaterial);
		// 配列を書き換えるので境界球が古くなる。視錐台で間引かない。
		this.beams.frustumCulled = false;
		this.beams.visible = false;
		model.effects.add(this.beams);
		const sparkGeometry = new THREE.BufferGeometry();
		sparkGeometry.setAttribute("position", new THREE.BufferAttribute(this.sparkPositions, 3));
		sparkGeometry.setAttribute("color", new THREE.BufferAttribute(this.sparkColors, 3));
		this.sparks = new THREE.Points(sparkGeometry, new THREE.PointsMaterial({ size: 0.014, vertexColors: true, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
		this.sparks.frustumCulled = false;
		model.effects.add(this.sparks);
		const random = mulberry32(1);
		this.emberSeeds = Array.from({ length: AMBIENT_EMBERS }, () => [random(), random(), random(), random()] as const);
		const emberGeometry = new THREE.BufferGeometry();
		emberGeometry.setAttribute("position", new THREE.BufferAttribute(this.emberPositions, 3));
		this.embers = new THREE.Points(emberGeometry, new THREE.PointsMaterial({ color: EMBER, size: 0.012, transparent: true, opacity: 0.8, depthWrite: false, blending: THREE.AdditiveBlending }));
		this.embers.frustumCulled = false;
		model.effects.add(this.embers);
	}

	dispose(): void {
		this.beamGeometry.dispose();
		this.beamMaterial.dispose();
		for (const points of [this.sparks, this.embers]) {
			points.geometry.dispose();
			(points.material as THREE.Material).dispose();
		}
	}

	get lineMaterials(): readonly LineMaterial[] {
		return [...this.model.lineMaterials, this.beamMaterial];
	}

	apply(glows: readonly Glow[], tick: number, fps: number, pointers: ReadonlySet<string>): void {
		const seconds = tick / fps;
		const levels = new Map<ItemHandle, { level: number; warn: boolean }>();
		/** 陣ごとの層の浮き上がり（陣の単位を掛ける前の値）。`ignite` は光った陣だけを浮かせる。 */
		const lift = new Map<string, number[]>();
		/** 同じ出どころ → 行き先の光線は 1 本に畳み、強い方を採る（毎 tick の cast が重なって白く飛ばないように）。 */
		const beams = new Map<string, { from: THREE.Vector3; to: THREE.Vector3; intensity: number }>();
		let sparkCount = 0;

		const raise = (handle: ItemHandle, level: number, warn: boolean): void => {
			const current = levels.get(handle);
			levels.set(handle, { level: Math.max(current?.level ?? 0, level), warn: (current?.warn ?? false) || warn });
		};

		for (const glow of glows) {
			const whole = WHOLE_CIRCLE.has(glow.effect);
			// 陣全体の演出の target は陣（effects.ts の `glowTarget`）。手順の図のように陣そのものが場面に無くても、配下は光らせる。
			const target = nearestInScene(pointers, glow.target) ?? (whole ? glow.target : null);
			if (target === null) continue;
			const warn = glow.effect === "warn";
			if (whole) {
				for (const [pointer, list] of this.model.handles) {
					if (pointer === glow.target || pointer.startsWith(`${glow.target}/`)) for (const h of list) raise(h, glow.intensity * (glow.effect === "fade" ? 0.5 : 1), false);
				}
				if (glow.effect === "ignite") {
					const levels = lift.get(glow.target) ?? new Array<number>(LAYER_HEIGHTS.length).fill(0);
					for (let i = 1; i < levels.length; i++) levels[i] = Math.max(levels[i] ?? 0, glow.intensity * 0.05 * i * Math.min(1, glow.progress * 3));
					lift.set(glow.target, levels);
				}
			} else {
				for (const h of this.model.handles.get(target) ?? []) raise(h, glow.intensity, warn);
			}
			const to = this.model.handles.get(target)?.[0]?.center;
			const from = glow.source === null ? null : this.model.handles.get(nearestInScene(pointers, glow.source) ?? "")?.[0]?.center;
			if (glow.effect === "beam" && from !== undefined && from !== null && to !== undefined) {
				const key = `${glow.source ?? ""}|${target}`;
				const current = beams.get(key);
				if (current === undefined) {
					if (beams.size < MAX_BEAMS) beams.set(key, { from, to, intensity: glow.intensity });
				} else current.intensity = Math.max(current.intensity, glow.intensity);
			}
			if ((glow.effect === "chant" || glow.effect === "release" || glow.effect === "crown" || glow.effect === "flow") && to !== undefined) {
				const random = mulberry32(glow.seq);
				for (let k = 0; k < SPARKS_PER_BURST && sparkCount < MAX_SPARKS; k++, sparkCount++) {
					const angle = random() * Math.PI * 2;
					const reach = 0.1 + random() * 0.35;
					const inward = glow.effect === "chant";
					const travel = inward ? 1 - glow.progress : glow.progress;
					const i = sparkCount * 3;
					this.sparkPositions[i] = to.x + Math.cos(angle) * reach * travel;
					this.sparkPositions[i + 1] = to.y + Math.sin(angle) * reach * travel;
					this.sparkPositions[i + 2] = to.z + (glow.effect === "crown" ? glow.progress * 0.6 * random() : 0.02);
					this.sparkColors[i] = GOLD_HOT.r * glow.intensity;
					this.sparkColors[i + 1] = GOLD_HOT.g * glow.intensity;
					this.sparkColors[i + 2] = GOLD_HOT.b * glow.intensity;
				}
			}
		}

		for (const list of this.model.handles.values()) {
			for (const handle of list) {
				const state = levels.get(handle);
				const level = state?.level ?? 0;
				for (const { material, base } of handle.glowables) {
					if (material instanceof THREE.MeshStandardMaterial) {
						material.emissive.copy(state?.warn === true ? WARN_RED : base);
						material.emissiveIntensity = BASE_EMISSIVE + level * EMISSIVE_GAIN;
					} else {
						material.color.copy(state?.warn === true ? WARN_RED : base).multiplyScalar(1 + level * COLOR_GAIN);
					}
				}
			}
		}
		for (const [circle, { unit, layers }] of this.model.circles) {
			const levels = lift.get(circle);
			layers.forEach((layer, i) => {
				layer.position.z = layerHeight(i as LayerIndex, unit) + (levels?.[i] ?? 0) * unit;
			});
		}
		let beamCount = 0;
		for (const { from, to, intensity } of beams.values()) {
			const i = beamCount * 6;
			this.beamPositions.set([from.x, from.y, from.z, to.x, to.y, to.z], i);
			for (let k = 0; k < 6; k += 3) {
				this.beamColors[i + k] = GOLD_HOT.r * intensity;
				this.beamColors[i + k + 1] = GOLD_HOT.g * intensity;
				this.beamColors[i + k + 2] = GOLD_HOT.b * intensity;
			}
			beamCount++;
		}
		this.beamGeometry.instanceCount = beamCount;
		this.beams.visible = beamCount > 0;
		(this.beamGeometry.attributes["instanceStart"] as THREE.InterleavedBufferAttribute).data.needsUpdate = true;
		(this.beamGeometry.attributes["instanceColorStart"] as THREE.InterleavedBufferAttribute).data.needsUpdate = true;
		this.sparks.geometry.setDrawRange(0, sparkCount);
		this.sparks.geometry.attributes["position"]!.needsUpdate = true;
		this.sparks.geometry.attributes["color"]!.needsUpdate = true;

		this.emberSeeds.forEach(([a, r, rise, phase], k) => {
			const angle = a * Math.PI * 2;
			const radius = Math.sqrt(r) * 1.1;
			const i = k * 3;
			this.emberPositions[i] = Math.cos(angle) * radius;
			this.emberPositions[i + 1] = Math.sin(angle) * radius;
			this.emberPositions[i + 2] = (phase + seconds * (0.04 + rise * 0.08)) % 1.2;
		});
		this.embers.geometry.attributes["position"]!.needsUpdate = true;
		for (const { group, speed } of this.model.tickers) group.rotation.z = seconds * speed;
	}
}
