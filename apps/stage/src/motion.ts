import { DURATION_SECONDS, type EffectName, type Glow } from "./effects";
import type { LayerIndex } from "./layers";
import { mulberry32 } from "./random";
import type { Vec2 } from "./scene";

/**
 * 時刻から決まる形の変化（仕様書 docs/superpowers/specs/2026-10-01-jin-stage-gem-worldview-design.md §5）。
 * three を import しない純関数。長さは陣の単位を掛ける前の値（外周 1 に対する値）。
 */
export type Vec3 = readonly [number, number, number];

/** 層の金細工のごく遅い自転（rad / 秒）。偶数層は +、奇数層は −。 */
export const LAYER_SPIN_RAD_PER_SECOND = 0.03;

export function layerSpin(layer: LayerIndex, seconds: number): number {
	return (layer % 2 === 0 ? 1 : -1) * LAYER_SPIN_RAD_PER_SECOND * seconds;
}

export function rotateAbout(p: Vec2, pivot: Vec2, angle: number): Vec2 {
	if (angle === 0) return p;
	const c = Math.cos(angle);
	const s = Math.sin(angle);
	const dx = p[0] - pivot[0];
	const dy = p[1] - pivot[1];
	return [pivot[0] + dx * c - dy * s, pivot[1] + dx * s + dy * c];
}

function clamp01(x: number): number {
	return Math.min(1, Math.max(0, x));
}

function smoothstep(x: number): number {
	const t = clamp01(x);
	return t * t * (3 - 2 * t);
}

/** 沈みと戻りの山（端で 0・中ほどで 1）。 */
function bump(progress: number): number {
	return Math.sin(Math.PI * clamp01(progress));
}

/** `ignite` で層が沈む深さ（層 i は i × この値）。 */
const IGNITE_DEPTH = 0.05;
/** 層 i が上がり始める進み = i × この値。上がるのにかかる進み = `IGNITE_RISE`。 */
const IGNITE_STAGGER = 0.12;
const IGNITE_RISE = 0.3;
/** `fade` / `crack` で層 i が沈む深さ（i × この値）・`crack` は全層一様。 */
const FADE_DEPTH = 0.04;
const CRACK_DEPTH = 0.04;

/**
 * 演出による層の高さの足し分（陣の単位を掛ける前）。
 * `ignite`: 沈んだ位置（層 i は −0.05 × i）から、下の層ほど先に上がって元の高さに収まる。
 * `fade`: 外側（層 1）から順に沈んで戻る。`crack`: 全層が沈んで戻る。ほかは 0。
 */
export function layerOffset(
	effect: EffectName,
	progress: number,
	layer: LayerIndex,
): number {
	// 台座（層 0）は動かさない（掛け算で −0 を返さない）。
	if (layer === 0) return 0;
	if (effect === "ignite") {
		const rise = smoothstep((progress - layer * IGNITE_STAGGER) / IGNITE_RISE);
		return -IGNITE_DEPTH * layer * (1 - rise);
	}
	if (effect === "fade") return -FADE_DEPTH * layer * bump(progress);
	if (effect === "crack") return -CRACK_DEPTH * bump(progress);
	return 0;
}

/** `crack` で陣が傾く角（rad）。 */
export function crackTilt(progress: number): number {
	return 0.06 * bump(progress);
}

/** 光の粒が走る 2 次ベジェの弧。制御点は中点の真上（距離 × 0.35）。 */
export function arcPoint(from: Vec3, to: Vec3, t: number): Vec3 {
	const distance = Math.hypot(
		to[0] - from[0],
		to[1] - from[1],
		to[2] - from[2],
	);
	const control: Vec3 = [
		(from[0] + to[0]) / 2,
		(from[1] + to[1]) / 2,
		(from[2] + to[2]) / 2 + distance * 0.35,
	];
	const u = 1 - t;
	return [
		u * u * from[0] + 2 * u * t * control[0] + t * t * to[0],
		u * u * from[1] + 2 * u * t * control[1] + t * t * to[1],
		u * u * from[2] + 2 * u * t * control[2] + t * t * to[2],
	];
}

const PILLAR_HEIGHT = 2.4;
const RIPPLE_RADIUS = 0.25;

/** `crown` の光の柱の高さ（ease-out で 0 → 2.4）。 */
export function pillarHeight(progress: number): number {
	return PILLAR_HEIGHT * (1 - (1 - clamp01(progress)) ** 3);
}

/** 宝玉の共鳴の波紋の半径（ease-out で 0 → 0.25）。 */
export function rippleRadius(progress: number): number {
	return RIPPLE_RADIUS * (1 - (1 - clamp01(progress)) ** 2);
}

export interface CameraNudge {
	readonly distanceScale: number;
	readonly elevationDeg: number;
	readonly azimuthDeg: number;
}

const ENTER_PULL = 0.1;
const FINISH_RISE_DEG = 8;
const SHAKE_SECONDS = 0.4;
const SHAKE_AMPLITUDE_DEG = 0.6;
const SHAKE_HZ = 18;

/** トレースから決まるカメラの足し分（仕様書 §5.3）。同じ時刻の複数の光は足し合わせる。 */
export function cameraNudge(glows: readonly Glow[]): CameraNudge {
	let distanceScale = 1;
	let elevationDeg = 0;
	let azimuthDeg = 0;
	for (const glow of glows) {
		if (glow.effect === "ignite")
			distanceScale -= ENTER_PULL * bump(glow.progress);
		else if (glow.effect === "crown")
			elevationDeg += FINISH_RISE_DEG * bump(glow.progress);
		else if (glow.effect === "crack") {
			const t = glow.progress * DURATION_SECONDS.crack;
			if (t >= SHAKE_SECONDS) continue;
			const random = mulberry32(glow.seq);
			const amplitude = SHAKE_AMPLITUDE_DEG * (1 - t / SHAKE_SECONDS);
			const phase = 2 * Math.PI * SHAKE_HZ * t;
			azimuthDeg += amplitude * Math.sin(phase + random() * 2 * Math.PI);
			elevationDeg += amplitude * Math.sin(phase + random() * 2 * Math.PI);
		}
	}
	return { distanceScale, elevationDeg, azimuthDeg };
}

/** 天球儀の飾りの輪 2 本の傾きと自転（意味を持たない・仕様書 §6）。 */
export function armillary(
	index: 0 | 1,
	seconds: number,
): { readonly tiltX: number; readonly tiltY: number; readonly spin: number } {
	return index === 0
		? {
				tiltX: 0.42 + 0.05 * Math.sin(seconds * 0.11),
				tiltY: 0.12,
				spin: seconds * 0.05,
			}
		: {
				tiltX: -0.3,
				tiltY: 0.38 + 0.05 * Math.cos(seconds * 0.09),
				spin: -seconds * 0.07,
			};
}
