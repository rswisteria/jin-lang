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

export function cameraPose(
	preset: CameraPreset,
	aspect: number,
	seconds: number,
	offset: CameraOffset = NO_OFFSET,
): CameraPose {
	const halfV = (FOV_DEG / 2) * RAD;
	const halfH = Math.atan(Math.tan(halfV) * aspect);
	const distance = FIT_RADIUS / Math.sin(Math.min(halfV, halfH));
	const elevationDeg = Math.min(
		MAX_ELEVATION_DEG,
		Math.max(
			MIN_ELEVATION_DEG,
			PRESET_ELEVATION_DEG[preset] + offset.elevationDeg,
		),
	);
	const elevation = elevationDeg * RAD;
	const azimuth = (ORBIT_DEG_PER_SECOND * seconds + offset.azimuthDeg) * RAD;
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
