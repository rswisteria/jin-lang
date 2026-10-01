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
	/** 注視点の床の上のずれ（y は 0）。レンダラは陣の核の高さと召喚の窓の持ち上げをこれに足す。 */
	readonly target: readonly [number, number, number];
	readonly fovDeg: number;
}

/**
 * 手で動かした分（設計書 §2.5・stage.md §4）。書き出しはこの値を初期値にした決まった動きになる。
 * `zoom` は注視点からの距離の倍率（無ければ 1）、`pan` は注視点の床の上のずれ `[x, z]`（無ければ原点）。
 */
export interface CameraOffset {
	readonly azimuthDeg: number;
	readonly elevationDeg: number;
	readonly zoom?: number;
	readonly pan?: readonly [number, number];
}

export const NO_OFFSET: CameraOffset = {
	azimuthDeg: 0,
	elevationDeg: 0,
	zoom: 1,
	pan: [0, 0],
};
export const MIN_ELEVATION_DEG = 5;
export const MAX_ELEVATION_DEG = 89;
/** 寄る・引くの範囲（距離の倍率）。0.25 = 4 倍寄る。 */
export const MIN_ZOOM = 0.25;
export const MAX_ZOOM = 2.5;
/** 注視点をずらせる範囲（中心からの距離）。額縁の内側（場面は [−1.25, 1.25] に写す）。 */
export const PAN_LIMIT = 1.25;
/** ホイール 1 px あたりの距離の倍率の指数（100 px で約 1.16 倍）。 */
export const WHEEL_ZOOM_PER_PX = 0.0015;
/** 縦のドラッグを床の奥行きへ写すときの仰角の下限（低い構図で sin が小さくなり跳ぶのを抑える）。 */
const MIN_PAN_SIN = 0.25;

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
		(fitRadius / Math.sin(Math.min(halfV, halfH))) *
		nudge.distanceScale *
		zoomOf(offset);
	const elevation = elevationOf(preset, offset, nudge.elevationDeg) * RAD;
	const azimuth =
		(ORBIT_DEG_PER_SECOND * seconds + offset.azimuthDeg + nudge.azimuthDeg) *
		RAD;
	const flat = distance * Math.cos(elevation);
	const [panX, panZ] = offset.pan ?? [0, 0];
	return {
		position: [
			panX + flat * Math.sin(azimuth),
			distance * Math.sin(elevation),
			panZ + flat * Math.cos(azimuth),
		],
		target: [panX, 0, panZ],
		fovDeg: FOV_DEG,
	};
}

function zoomOf(offset: CameraOffset): number {
	return offset.zoom ?? 1;
}

function elevationOf(
	preset: CameraPreset,
	offset: CameraOffset,
	nudgeDeg: number,
): number {
	return Math.min(
		MAX_ELEVATION_DEG,
		Math.max(
			MIN_ELEVATION_DEG,
			PRESET_ELEVATION_DEG[preset] + offset.elevationDeg + nudgeDeg,
		),
	);
}

/** 寄る・引く: 距離の倍率に `factor` を掛けて `MIN_ZOOM`〜`MAX_ZOOM` に収める。正の有限でない倍率では変えない。 */
export function zoomBy(offset: CameraOffset, factor: number): CameraOffset {
	if (!(factor > 0) || !Number.isFinite(factor)) return offset;
	const zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoomOf(offset) * factor));
	return { ...offset, zoom };
}

/** ホイールの `deltaY`（px）→ 距離の倍率。下へ回す（正）と引き、上へ回すと寄る。 */
export function wheelZoomFactor(deltaY: number): number {
	return Math.exp(deltaY * WHEEL_ZOOM_PER_PX);
}

/** ずらすときに今の構図を知るための入力（トレースから決まる足し分と窓の半径は含めない近似）。 */
export interface PanView {
	readonly preset: CameraPreset;
	readonly aspect: number;
	readonly seconds: number;
	/** 描画の高さ（CSS px）。 */
	readonly heightPx: number;
}

/**
 * 注視点をずらす: 画面の上で (dx, dy) px ドラッグしたとき、注視点の深さで陣がポインタについてくる量だけ、
 * 注視点を逆向きに床の上で動かす。縦は床の奥行きへ写す（仰角で縮む分を戻す）。中心から `PAN_LIMIT` に収める。
 */
export function panBy(
	offset: CameraOffset,
	dxPx: number,
	dyPx: number,
	view: PanView,
): CameraOffset {
	const pose = cameraPose(view.preset, view.aspect, view.seconds, offset);
	const distance = Math.hypot(
		pose.position[0] - pose.target[0],
		pose.position[1] - pose.target[1],
		pose.position[2] - pose.target[2],
	);
	const perPx =
		(2 * distance * Math.tan((FOV_DEG / 2) * RAD)) / Math.max(1, view.heightPx);
	const azimuth =
		(ORBIT_DEG_PER_SECOND * view.seconds + offset.azimuthDeg) * RAD;
	const sinElevation = Math.max(
		MIN_PAN_SIN,
		Math.sin(elevationOf(view.preset, offset, 0) * RAD),
	);
	// 画面の右は床の (cos a, −sin a)、画面の上（奥）は (−sin a, −cos a)。
	const right = dxPx * perPx;
	const forward = (dyPx * perPx) / sinElevation;
	const [x, z] = offset.pan ?? [0, 0];
	let nextX = x - right * Math.cos(azimuth) - forward * Math.sin(azimuth);
	let nextZ = z + right * Math.sin(azimuth) - forward * Math.cos(azimuth);
	const radius = Math.hypot(nextX, nextZ);
	if (radius > PAN_LIMIT) {
		nextX *= PAN_LIMIT / radius;
		nextZ *= PAN_LIMIT / radius;
	}
	return { ...offset, pan: [nextX, nextZ] };
}
