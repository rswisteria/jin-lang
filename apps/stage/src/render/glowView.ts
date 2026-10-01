import * as THREE from "three";
import { LineMaterial } from "three/addons/lines/LineMaterial.js";
import { LineSegments2 } from "three/addons/lines/LineSegments2.js";
import { LineSegmentsGeometry } from "three/addons/lines/LineSegmentsGeometry.js";

import { type Glow, WHOLE_CIRCLE } from "../effects";
import { type LayerIndex, layerHeight } from "../layers";
import {
	arcPoint,
	crackTilt,
	igniteLight,
	layerOffset,
	layerSpin,
	pillarHeight,
	rippleRadius,
	type Vec3,
} from "../motion";
import type { Vec2 } from "../scene";
import { MAX_RIPPLES, type Ripple } from "./floor";
import { circleOf, nearestInScene } from "../names";
import { GEMS, gemColorAt } from "../palette";
import { type BurstPlace, byPriority, collect } from "../particles";
import { mulberry32 } from "../random";
import type { GemHandle } from "./gems";
import {
	BASE_EMISSIVE,
	type GildedModel,
	type ItemHandle,
	NO_CIRCLE,
} from "./gilded";
import { ParticleView } from "./particleView";

/**
 * Glow の列 → 宝玉と金細工の明るさ・層の自転と浮き沈み・光線（弧）・粒子
 * （docs/spec/v2/stage.md §3・仕様書 docs/superpowers/specs/2026-10-01-jin-stage-gem-worldview-design.md §5）。
 * **時刻の関数**: 同じ (glows, tick, fps) なら同じ状態にする（前のフレームの状態を持ち越さない）。
 * 光線と粒子の端点は、層と同じ変換（陣の中心まわりの自転・浮き沈み・傾き）を通してから使う（ずれない）。
 */
const MAX_BEAMS = 24;
/** 光線 1 本の弧の分割数。 */
const ARC_SEGMENTS = 12;
const MAX_SEGMENTS = MAX_BEAMS * ARC_SEGMENTS;
const EMISSIVE_GAIN = 1.6;
const COLOR_GAIN = 1.2;
/** 宝玉が灯ったときの自発光の増分（強さ 1 あたり）。 */
const GEM_EMISSIVE_GAIN = 1.4;
/** cast で核の宝玉が受ける光の割合（核は発動した力の色を映す）。 */
const CORE_ECHO = 0.35;
const BEAM_WIDTH_PX = 3.5;
/** spin の写しの輪の上限。 */
const MAX_GHOSTS = 16;
/** crack の亀裂の本数と 1 本の折れ数。 */
const CRACKS = 6;
const CRACK_SEGMENTS = 4;

/** 宝玉の色を映す種別（核と ◇）。それ以外は自分の宝玉の色で灯る。 */
const MIRROR_KINDS: ReadonlySet<string> = new Set(["core", "on"]);

interface Level {
	level: number;
	color: number | null;
}

export class GlowView {
	private readonly beamPositions = new Float32Array(MAX_SEGMENTS * 6);
	private readonly beamColors = new Float32Array(MAX_SEGMENTS * 6);
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
	private readonly particles = new ParticleView();
	private readonly ghosts: readonly THREE.Mesh<
		THREE.TorusGeometry,
		THREE.MeshBasicMaterial
	>[];
	private readonly ghostGeometry = new THREE.TorusGeometry(1, 0.05, 6, 64);
	private readonly scratch = new THREE.Color();
	/** 床の波紋（`apply` が毎回作り直す・`Floor.setRipples` へ渡す）。 */
	ripples: readonly Ripple[] = [];
	/** 光の柱（`crown`）。無ければ null。 */
	pillar: {
		readonly at: Vec2;
		readonly base: number;
		readonly height: number;
		readonly alpha: number;
	} | null = null;
	/** 灯った宝玉の強さの和（ゴッドレイの濃さ）。 */
	rays = 0;

	constructor(private readonly model: GildedModel) {
		this.beamGeometry.setPositions(this.beamPositions);
		this.beamGeometry.setColors(this.beamColors);
		this.beamGeometry.instanceCount = 0;
		this.beams = new LineSegments2(this.beamGeometry, this.beamMaterial);
		// 配列を書き換えるので境界球が古くなる。視錐台で間引かない。
		this.beams.frustumCulled = false;
		this.beams.visible = false;
		model.effects.add(this.beams, this.particles.object);
		this.ghosts = Array.from({ length: MAX_GHOSTS }, () => {
			const mesh = new THREE.Mesh(
				this.ghostGeometry,
				new THREE.MeshBasicMaterial({
					color: GEMS.gold.color,
					transparent: true,
					opacity: 0,
					depthWrite: false,
					blending: THREE.AdditiveBlending,
				}),
			);
			mesh.visible = false;
			model.effects.add(mesh);
			return mesh;
		});
	}

	dispose(): void {
		this.beamGeometry.dispose();
		this.beamMaterial.dispose();
		this.particles.dispose();
		this.ghostGeometry.dispose();
		for (const ghost of this.ghosts) ghost.material.dispose();
	}

	get lineMaterials(): readonly LineMaterial[] {
		return [...this.model.lineMaterials, this.beamMaterial];
	}

	/** 粒子の大きさの換算（`ParticleView.setScale`）。 */
	setPointScale(scale: number): void {
		this.particles.setScale(scale);
	}

	/** 要素の今の位置（root の局所座標）。宝玉があれば宝玉、無ければ最初の形の中心。`apply` の後に読む。 */
	endpointOf(pointer: string): THREE.Vector3 | null {
		const gem = this.model.gems.get(pointer);
		if (gem !== undefined)
			return this.toRoot(
				gem.anchor.circle,
				gem.anchor.layer,
				gem.mesh.position,
			);
		const handle = this.model.handles.get(pointer)?.[0];
		if (handle === undefined) return null;
		return this.toRoot(
			handle.item.circle,
			handle.item.layer,
			new THREE.Vector3(handle.center.x, handle.center.y, 0),
		);
	}

	private toRoot(
		circle: string | null,
		layer: LayerIndex,
		local: THREE.Vector3,
	): THREE.Vector3 {
		const group = this.model.circles.get(circle ?? NO_CIRCLE)?.layers[layer];
		return group === undefined
			? local.clone()
			: local.clone().applyMatrix4(group.matrix);
	}

	/** 要素の大きさ（宝玉の置き場所の半径・輪の半径）。 */
	private sizeOf(pointer: string): number {
		const gem = this.model.gems.get(pointer);
		if (gem !== undefined) return gem.anchor.radius;
		const shape = this.model.handles.get(pointer)?.[0]?.item.shape;
		return shape?.type === "ring" || shape?.type === "dot"
			? shape.radius
			: 0.03;
	}

	apply(
		glows: readonly Glow[],
		tick: number,
		fps: number,
		pointers: ReadonlySet<string>,
	): void {
		const seconds = tick / fps;
		const metals = new Map<
			ItemHandle,
			{ level: number; tint: number | null }
		>();
		const gems = new Map<GemHandle, Level>();
		const dark = new Map<GemHandle, number>();
		/** 陣ごとの層の足し分（単位を掛ける前）と傾き。 */
		const offsets = new Map<string, number[]>();
		const tilts = new Map<string, number>();

		const raiseMetal = (
			handle: ItemHandle,
			level: number,
			tint: number | null,
		): void => {
			const current = metals.get(handle);
			metals.set(handle, {
				level: Math.max(current?.level ?? 0, level),
				tint: tint ?? current?.tint ?? null,
			});
		};
		const raiseGem = (gem: GemHandle, level: number, color: number): void => {
			const current = gems.get(gem);
			if (current === undefined || level >= current.level)
				gems.set(gem, { level, color });
		};
		const resolve = (target: string, whole: boolean): string | null =>
			nearestInScene(pointers, target) ?? (whole ? target : null);

		for (const glow of glows) {
			const whole = WHOLE_CIRCLE.has(glow.effect);
			const target = resolve(glow.target, whole);
			if (target === null) continue;
			const color = gemColorAt(glow.gem, seconds, glow.seq);
			const tint =
				glow.effect === "warn" || glow.effect === "crack"
					? GEMS[glow.gem].color
					: null;
			const level =
				glow.effect === "warn"
					? glow.intensity *
						(0.6 + 0.4 * Math.sin(2 * Math.PI * 3 * glow.progress))
					: glow.intensity;
			if (whole) {
				const scale = glow.effect === "fade" ? 0.5 : 1;
				/** ignite は層ごとに光が走る（陣全体を同時に灯さない）。ほかの陣全体の演出は一様。 */
				const at = (layer: LayerIndex): number =>
					glow.effect === "ignite" ? igniteLight(glow.progress, layer) : 1;
				for (const [pointer, list] of this.model.handles)
					if (pointer === glow.target || pointer.startsWith(`${glow.target}/`))
						for (const h of list)
							raiseMetal(h, level * scale * at(h.item.layer), tint);
				for (const [pointer, gem] of this.model.gems)
					if (pointer.startsWith(`${glow.target}/`))
						raiseGem(
							gem,
							level *
								scale *
								at(gem.anchor.layer) *
								(glow.effect === "crack" ? 0 : 1),
							MIRROR_KINDS.has(gem.anchor.kind) ? color : GEMS[gem.gem].color,
						);
				const circle = circleOf(glow.target) ?? glow.target;
				const levels = offsets.get(circle) ?? [0, 0, 0, 0, 0, 0];
				for (let i = 1; i < levels.length; i++)
					levels[i] =
						(levels[i] ?? 0) +
						layerOffset(glow.effect, glow.progress, i as LayerIndex);
				offsets.set(circle, levels);
				if (glow.effect === "crack") {
					tilts.set(
						circle,
						(tilts.get(circle) ?? 0) + crackTilt(glow.progress),
					);
					this.darken(circle, glow.progress, dark);
				}
			} else {
				for (const h of this.model.handles.get(target) ?? [])
					raiseMetal(h, level, tint);
				const gem = this.model.gems.get(target);
				if (gem !== undefined)
					raiseGem(
						gem,
						level,
						MIRROR_KINDS.has(gem.anchor.kind) ? color : GEMS[gem.gem].color,
					);
			}
			if (glow.effect === "beam") {
				const core = this.model.gems.get(`${circleOf(target) ?? ""}/core`);
				if (core !== undefined)
					raiseGem(core, glow.intensity * CORE_ECHO, color);
			}
		}

		this.placeLayers(seconds, offsets, tilts);
		this.lightMetals(metals);
		this.lightGems(gems, dark);
		this.drawBeams(glows, pointers, seconds);
		this.drawGhosts(glows, pointers);
		this.floorAndPillar(glows, pointers, seconds);
		this.particles.set(
			collect(
				glows,
				(glow): BurstPlace | null => {
					const target = resolve(glow.target, WHOLE_CIRCLE.has(glow.effect));
					const at = target === null ? null : this.endpointOf(target);
					if (target === null || at === null) return null;
					const source =
						glow.source === null ? null : nearestInScene(pointers, glow.source);
					const from = source === null ? null : this.endpointOf(source);
					return {
						at: vec(at),
						from: from === null ? null : vec(from),
						size: this.sizeOf(target),
					};
				},
				seconds,
			),
		);
		for (const { group, speed } of this.model.tickers)
			group.rotation.z = seconds * speed;
	}

	/** 層の自転（陣の中心まわり）・浮き沈み・傾き。行列まで更新して、端点の変換に使えるようにする。 */
	private placeLayers(
		seconds: number,
		offsets: ReadonlyMap<string, number[]>,
		tilts: ReadonlyMap<string, number>,
	): void {
		const spin = new THREE.Quaternion();
		const tilt = new THREE.Quaternion();
		const turn = new THREE.Matrix4();
		const toPivot = new THREE.Matrix4();
		const fromPivot = new THREE.Matrix4();
		const lift = new THREE.Matrix4();
		const scale = new THREE.Vector3();
		/** 陣ごと・層ごとの「高さを除いた」変換（入れ子の子がこれを公転として受け継ぐ）。 */
		const orbits = new Map<string, THREE.Matrix4[]>();
		// 親を子より先に置く（単位の大きい順）。
		const order = [...this.model.circles.entries()].sort(
			(a, b) => b[1].unit - a[1].unit,
		);
		for (const [circle, { unit, layers }] of order) {
			const [px, py] = this.model.pivots.get(circle) ?? [0, 0];
			toPivot.makeTranslation(px, py, 0);
			fromPivot.makeTranslation(-px, -py, 0);
			const levels = offsets.get(circle);
			tilt.setFromAxisAngle(new THREE.Vector3(1, 0, 0), tilts.get(circle) ?? 0);
			const nest = this.model.nesting.get(circle);
			const inherited =
				nest === undefined ? undefined : orbits.get(nest.parent)?.[nest.layer];
			const own: THREE.Matrix4[] = [];
			layers.forEach((layer, i) => {
				spin.setFromAxisAngle(
					new THREE.Vector3(0, 0, 1),
					layerSpin(i as LayerIndex, seconds),
				);
				// 陣の中心まわりの自転と傾き → 親の層の公転（あれば）→ 高さ（root の z・傾けない）。
				turn.makeRotationFromQuaternion(tilt.clone().multiply(spin));
				const orbit = new THREE.Matrix4()
					.multiplyMatrices(toPivot, turn)
					.multiply(fromPivot);
				if (inherited !== undefined) orbit.premultiply(inherited);
				own.push(orbit);
				lift.makeTranslation(
					0,
					0,
					layerHeight(i as LayerIndex, unit) + (levels?.[i] ?? 0) * unit,
				);
				layer.matrix.multiplyMatrices(lift, orbit);
				layer.matrix.decompose(layer.position, layer.quaternion, scale);
				layer.updateMatrix();
			});
			orbits.set(circle, own);
		}
	}

	private lightMetals(
		metals: ReadonlyMap<ItemHandle, { level: number; tint: number | null }>,
	): void {
		for (const list of this.model.handles.values()) {
			for (const handle of list) {
				const state = metals.get(handle);
				const level = state?.level ?? 0;
				const tint = state?.tint ?? null;
				for (const { material, base } of handle.glowables) {
					const color = tint === null ? base : this.scratch.setHex(tint);
					if (material instanceof THREE.MeshStandardMaterial) {
						material.emissive.copy(color);
						material.emissiveIntensity = BASE_EMISSIVE + level * EMISSIVE_GAIN;
					} else {
						material.color.copy(color).multiplyScalar(1 + level * COLOR_GAIN);
					}
				}
			}
		}
	}

	/**
	 * 床の波紋（cast の共鳴は宝玉の色・warn は陣の外周まで広がるルビーの環）と光の柱（crown）。
	 * 位置は端点と同じ変換を通した値の xy。
	 */
	private floorAndPillar(
		glows: readonly Glow[],
		pointers: ReadonlySet<string>,
		seconds: number,
	): void {
		const ripples: Ripple[] = [];
		let pillar: GlowView["pillar"] = null;
		for (const glow of byPriority(glows)) {
			if (glow.effect === "beam") {
				const target = nearestInScene(pointers, glow.target);
				const at = target === null ? null : this.endpointOf(target);
				if (target === null || at === null) continue;
				const unit = this.model.handles.get(target)?.[0]?.item.unit ?? 1;
				ripples.push({
					at: [at.x, at.y],
					radius: rippleRadius(glow.progress) * unit,
					color: gemColorAt(glow.gem, seconds, glow.seq),
					alpha: glow.intensity * (1 - glow.progress) * 0.6,
				});
			} else if (glow.effect === "warn") {
				const circle = circleOf(glow.target) ?? glow.target;
				const ring = this.model.handles.get(circle)?.[0]?.item.shape;
				const pivot = this.model.pivots.get(circle) ?? [0, 0];
				const outer = ring?.type === "ring" ? ring.radius : 0.95;
				ripples.push({
					at: pivot,
					radius: outer * 1.1 * glow.progress,
					color: GEMS.ruby.color,
					alpha: glow.intensity * (1 - glow.progress),
				});
			} else if (glow.effect === "crown" && pillar === null) {
				const circle = circleOf(glow.target) ?? glow.target;
				const core =
					this.endpointOf(`${circle}/core`) ?? this.endpointOf(circle);
				if (core === null) continue;
				const unit = this.model.circles.get(circle)?.unit ?? 1;
				pillar = {
					at: [core.x, core.y],
					base: core.z,
					height: pillarHeight(glow.progress) * unit,
					alpha: glow.intensity * (1 - glow.progress * 0.7),
				};
			}
		}
		this.ripples = ripples.slice(0, MAX_RIPPLES);
		this.pillar = pillar;
	}

	private lightGems(
		gems: ReadonlyMap<GemHandle, Level>,
		dark: ReadonlyMap<GemHandle, number>,
	): void {
		let rays = 0;
		for (const level of gems.values()) rays += level.level;
		this.rays = rays;
		for (const gem of this.model.gems.values()) {
			const state = gems.get(gem);
			const level = state?.level ?? 0;
			const color = state?.color ?? GEMS[gem.gem].color;
			gem.material.emissive.setHex(color);
			gem.material.emissiveIntensity = level * GEM_EMISSIVE_GAIN;
			gem.material.color
				.setHex(GEMS[gem.gem].color)
				.multiplyScalar(1 - 0.7 * (dark.get(gem) ?? 0));
			gem.glow.material.color.setHex(color);
			gem.glow.material.opacity = Math.min(1, level);
		}
	}

	/** crack: 陣の宝玉を外側から順に暗くする（中心からの距離の降順に進みで追いつく）。 */
	private darken(
		circle: string,
		progress: number,
		dark: Map<GemHandle, number>,
	): void {
		const [px, py] = this.model.pivots.get(circle) ?? [0, 0];
		const inside = [...this.model.gems.entries()]
			.filter(([pointer]) => pointer.startsWith(`${circle}/`))
			.map(([, gem]) => gem);
		const far = Math.max(
			1e-9,
			...inside.map((g) =>
				Math.hypot(g.anchor.center[0] - px, g.anchor.center[1] - py),
			),
		);
		for (const gem of inside) {
			const rank =
				1 -
				Math.hypot(gem.anchor.center[0] - px, gem.anchor.center[1] - py) / far;
			const amount =
				Math.min(1, Math.max(0, progress * 2 - rank)) *
				Math.sin(Math.PI * Math.min(1, progress));
			dark.set(gem, Math.max(dark.get(gem) ?? 0, amount));
		}
	}

	/** 光線（cast の弧・transfer の太い流れの芯）と crack の亀裂を、線の枠に詰める。 */
	private drawBeams(
		glows: readonly Glow[],
		pointers: ReadonlySet<string>,
		seconds: number,
	): void {
		const color = new THREE.Color();
		let count = 0;
		const segment = (
			a: Vec3,
			b: Vec3,
			c: THREE.Color,
			intensity: number,
		): void => {
			if (count >= MAX_SEGMENTS) return;
			const i = count * 6;
			this.beamPositions.set([a[0], a[1], a[2], b[0], b[1], b[2]], i);
			for (let k = 0; k < 6; k += 3) {
				this.beamColors[i + k] = c.r * intensity;
				this.beamColors[i + k + 1] = c.g * intensity;
				this.beamColors[i + k + 2] = c.b * intensity;
			}
			count++;
		};
		/** 同じ出どころ → 行き先の光線は 1 本に畳み、強い方を採る（毎 tick の cast が重なって白く飛ばないように）。 */
		const arcs = new Map<
			string,
			{ from: Vec3; to: Vec3; intensity: number; color: number }
		>();
		for (const glow of byPriority(glows)) {
			if (
				(glow.effect !== "beam" && glow.effect !== "flow") ||
				glow.source === null
			)
				continue;
			const target = nearestInScene(pointers, glow.target);
			const source = nearestInScene(pointers, glow.source);
			if (target === null || source === null) continue;
			const to = this.endpointOf(target);
			const from = this.endpointOf(source);
			if (to === null || from === null) continue;
			const key = `${source}|${target}`;
			const current = arcs.get(key);
			if (current === undefined) {
				if (arcs.size < MAX_BEAMS)
					arcs.set(key, {
						from: vec(from),
						to: vec(to),
						intensity: glow.intensity,
						color: gemColorAt(glow.gem, seconds, glow.seq),
					});
			} else current.intensity = Math.max(current.intensity, glow.intensity);
		}
		for (const { from, to, intensity, color: hex } of arcs.values()) {
			color.setHex(hex);
			for (let k = 0; k < ARC_SEGMENTS; k++)
				segment(
					arcPoint(from, to, k / ARC_SEGMENTS),
					arcPoint(from, to, (k + 1) / ARC_SEGMENTS),
					color,
					intensity,
				);
		}
		for (const glow of glows) {
			if (glow.effect !== "crack") continue;
			const circle = circleOf(glow.target) ?? glow.target;
			const ring = this.model.handles.get(circle)?.[0];
			if (ring === undefined || ring.item.shape.type !== "ring") continue;
			const { center, radius } = ring.item.shape;
			const random = mulberry32(glow.seq);
			const reach = Math.min(1, glow.progress * 2.5);
			color.setHex(GEMS.garnet.color);
			for (let n = 0; n < CRACKS; n++) {
				const angle = random() * Math.PI * 2;
				let previous = this.toRoot(
					ring.item.circle,
					1,
					new THREE.Vector3(
						center[0] + Math.cos(angle) * radius,
						center[1] + Math.sin(angle) * radius,
						0,
					),
				);
				for (let k = 1; k <= CRACK_SEGMENTS; k++) {
					const r = radius * (1 - 0.45 * reach * (k / CRACK_SEGMENTS));
					const a = angle + (random() - 0.5) * 0.25;
					const next = this.toRoot(
						ring.item.circle,
						1,
						new THREE.Vector3(
							center[0] + Math.cos(a) * r,
							center[1] + Math.sin(a) * r,
							0,
						),
					);
					segment(vec(previous), vec(next), color, glow.intensity);
					previous = next;
				}
			}
		}
		this.beamGeometry.instanceCount = count;
		this.beams.visible = count > 0;
		(
			this.beamGeometry.attributes[
				"instanceStart"
			] as THREE.InterleavedBufferAttribute
		).data.needsUpdate = true;
		(
			this.beamGeometry.attributes[
				"instanceColorStart"
			] as THREE.InterleavedBufferAttribute
		).data.needsUpdate = true;
	}

	/** spin: 手順の小円の写しの輪が、浮きながら広がって消える。 */
	private drawGhosts(
		glows: readonly Glow[],
		pointers: ReadonlySet<string>,
	): void {
		let used = 0;
		for (const glow of byPriority(glows)) {
			if (glow.effect !== "spin" || used >= MAX_GHOSTS) continue;
			const target = nearestInScene(pointers, glow.target);
			const handle =
				target === null ? undefined : this.model.handles.get(target)?.[0];
			if (
				target === null ||
				handle === undefined ||
				handle.item.shape.type !== "ring"
			)
				continue;
			const at = this.endpointOf(target);
			const ghost = this.ghosts[used];
			if (at === null || ghost === undefined) continue;
			const radius = handle.item.shape.radius * (1 + 0.3 * glow.progress);
			ghost.position.set(
				at.x,
				at.y,
				at.z + 0.08 * glow.progress * handle.item.unit,
			);
			ghost.scale.set(radius, radius, radius);
			ghost.rotation.set(0, 0, glow.progress * Math.PI * 2);
			ghost.material.opacity = glow.intensity * (1 - glow.progress) * 0.8;
			ghost.visible = true;
			used++;
		}
		for (let k = used; k < MAX_GHOSTS; k++) {
			const ghost = this.ghosts[k];
			if (ghost !== undefined) ghost.visible = false;
		}
	}
}

function vec(v: THREE.Vector3): Vec3 {
	return [v.x, v.y, v.z];
}
