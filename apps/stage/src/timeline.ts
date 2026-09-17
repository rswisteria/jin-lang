/** tick ↔ 動画のコマ（docs/spec/v2/stage.md §5）。 */
export const VIDEO_FPS = 60;
export const MAX_EXPORT_SECONDS = 60;
export const MAX_PNG_LONG_SIDE = 4096;

export type Speed = 1 | 0.5;
export type Aspect = "1:1" | "16:9" | "9:16";
export type Resolution = 1080 | 1440 | 2160;

export interface ExportRange {
	readonly startTick: number;
	readonly endTick: number;
	/** ゲームの fps（`stage.fps`）。 */
	readonly fps: number;
	readonly speed: Speed;
}

/** 開始 ≤ 終了に並べ、動画の長さを 60 秒で切る。 */
export function clampRange(range: ExportRange): ExportRange {
	const startTick = Math.min(range.startTick, range.endTick);
	const endTick = Math.max(range.startTick, range.endTick);
	const maxTicks = MAX_EXPORT_SECONDS * range.speed * range.fps;
	return {
		...range,
		startTick,
		endTick: Math.min(endTick, startTick + maxTicks),
	};
}

export function frameCount(range: ExportRange): number {
	const seconds = (range.endTick - range.startTick) / range.fps / range.speed;
	return Math.max(1, Math.round(seconds * VIDEO_FPS));
}

export function tickAtFrame(range: ExportRange, n: number): number {
	return range.startTick + (n / VIDEO_FPS) * range.speed * range.fps;
}

const RATIOS: Readonly<Record<Aspect, number>> = {
	"1:1": 1,
	"16:9": 16 / 9,
	"9:16": 9 / 16,
};

/** 長辺を `longSide` にし、短辺は偶数に切り下げる（H.264 は偶数の辺を要る）。 */
export function outputSize(
	aspect: Aspect,
	longSide: number,
): { readonly width: number; readonly height: number } {
	const ratio = RATIOS[aspect];
	const even = (value: number): number => Math.floor(value / 2) * 2;
	if (ratio >= 1) return { width: longSide, height: even(longSide / ratio) };
	return { width: even(longSide * ratio), height: longSide };
}
