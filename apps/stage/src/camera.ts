/** カメラ（docs/spec/v2/stage.md §4）。注視点は原点、y が上、陣は y = 0 の面に置く。 */
export type CameraPreset = "overhead" | "oblique" | "low";

export const PRESET_ELEVATION_DEG: Readonly<Record<CameraPreset, number>> = {
	overhead: 80,
	oblique: 45,
	low: 16,
};
export const FOV_DEG = 35;
export const FIT_RADIUS = 1.45;
export const ORBIT_DEG_PER_SECOND = 4;

export interface CameraPose {
	readonly position: readonly [number, number, number];
	readonly fovDeg: number;
}

/** 手で動かした分（設計書 §2.5）。書き出しはこの値を初期値にした決まった動きになる。 */
export interface CameraOffset {
	readonly azimuthDeg: number;
	readonly elevationDeg: number;
}

export const NO_OFFSET: CameraOffset = { azimuthDeg: 0, elevationDeg: 0 };
export const MIN_ELEVATION_DEG = 5;
export const MAX_ELEVATION_DEG = 89;

const RAD = Math.PI / 180;

/** トレースから決まる足し分（`motion.ts` の `cameraNudge`・仕様書 2026-10-01 §5.3）。 */
export interface CameraNudgeInput {
	readonly distanceScale: number;
	readonly elevationDeg: number;
	readonly azimuthDeg: number;
}

const NO_NUDGE: CameraNudgeInput = {
	distanceScale: 1,
	elevationDeg: 0,
	azimuthDeg: 0,
};

export function cameraPose(
	preset: CameraPreset,
	aspect: number,
	seconds: number,
	offset: CameraOffset = NO_OFFSET,
	nudge: CameraNudgeInput = NO_NUDGE,
	/** 陣を収める半径（召喚の窓があるときは広げる・仕様書 2026-10-01-jin-stage-summon §1.1）。 */
	fitRadius: number = FIT_RADIUS,
): CameraPose {
	const halfV = (FOV_DEG / 2) * RAD;
	const halfH = Math.atan(Math.tan(halfV) * aspect);
	const distance =
		(fitRadius / Math.sin(Math.min(halfV, halfH))) * nudge.distanceScale;
	const elevationDeg = Math.min(
		MAX_ELEVATION_DEG,
		Math.max(
			MIN_ELEVATION_DEG,
			PRESET_ELEVATION_DEG[preset] + offset.elevationDeg + nudge.elevationDeg,
		),
	);
	const elevation = elevationDeg * RAD;
	const azimuth =
		(ORBIT_DEG_PER_SECOND * seconds + offset.azimuthDeg + nudge.azimuthDeg) *
		RAD;
	const flat = distance * Math.cos(elevation);
	return {
		position: [
			flat * Math.sin(azimuth),
			distance * Math.sin(elevation),
			flat * Math.cos(azimuth),
		],
		fovDeg: FOV_DEG,
	};
}
