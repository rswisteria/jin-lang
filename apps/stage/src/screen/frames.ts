import { circleOf, type StageNames, type TraceRow } from "../names";
import type { Op } from "./draw";

/**
 * 召喚の窓に映すコマ・窓の開閉・縁の光を、トレースと時刻だけから決める（仕様書
 * docs/superpowers/specs/2026-10-01-jin-stage-summon-design.md §1.2〜§1.4）。three を import しない純関数。
 * 時刻 `t` は tick 単位の実数（`effects.ts` と同じ）。行の時刻は `max(tick, 0)`。
 */
export interface ScreenFrame {
	readonly tick: number;
	readonly ops: readonly Op[];
	readonly audio: readonly Op[];
}

export interface WindowState {
	/** 0（閉）〜 1（開）。 */
	readonly open: number;
	/** `tone` が鳴ったコマの直後の縁の脈（1 → 0）。 */
	readonly tonePulse: number;
	/** `play` のコマの直後の縁の閃き（1 → 0）。 */
	readonly playFlash: number;
	/** 実行時エラーの後の縁の明滅（0〜1）。前は 0。 */
	readonly errorPulse: number;
}

export const OPEN_SECONDS = 0.8;
export const PULSE_SECONDS = 0.25;
export const FLASH_SECONDS = 0.3;
const ERROR_HZ = 2;

function opsOf(value: unknown): readonly Op[] {
	return Array.isArray(value)
		? (value.filter(
				(item) => Array.isArray(item) && typeof item[0] === "string",
			) as Op[])
		: [];
}

/** `frame` 行の `output`（`{ops, audio}`）を tick 順に。 */
export function framesOf(rows: readonly TraceRow[]): readonly ScreenFrame[] {
	const frames: ScreenFrame[] = [];
	for (const row of rows) {
		if (row.kind !== "frame") continue;
		const output =
			row.output !== null && typeof row.output === "object"
				? (row.output as { ops?: unknown; audio?: unknown })
				: {};
		frames.push({
			tick: Math.max(row.tick, 0),
			ops: opsOf(output.ops),
			audio: opsOf(output.audio),
		});
	}
	return frames.sort((a, b) => a.tick - b.tick);
}

/** 二分探索: tick ≤ floor(t) で最後のコマの添字（無ければ −1）。 */
function indexAt(frames: readonly ScreenFrame[], t: number): number {
	const tick = Math.floor(t);
	let lo = 0;
	let hi = frames.length - 1;
	let found = -1;
	while (lo <= hi) {
		const mid = (lo + hi) >> 1;
		if ((frames[mid]?.tick ?? Number.POSITIVE_INFINITY) <= tick) {
			found = mid;
			lo = mid + 1;
		} else hi = mid - 1;
	}
	return found;
}

/** 時刻 `t` に映すコマ（最初のコマより前は null・最後を越えたら最後のコマ）。 */
export function frameAt(
	frames: readonly ScreenFrame[],
	t: number,
): ScreenFrame | null {
	const i = indexAt(frames, t);
	return i < 0 ? null : (frames[i] ?? null);
}

function clamp01(x: number): number {
	return Math.min(1, Math.max(0, x));
}

/** 直近の、`name` の音を含むコマからの経過秒（`windowSeconds` を越えたら null）。 */
function sinceSound(
	frames: readonly ScreenFrame[],
	t: number,
	fps: number,
	name: string,
	windowSeconds: number,
): number | null {
	for (let i = indexAt(frames, t); i >= 0; i--) {
		const frame = frames[i];
		if (frame === undefined) break;
		const age = (t - frame.tick) / fps;
		if (age >= windowSeconds) return null;
		if (frame.audio.some((op) => op[0] === name)) return age;
	}
	return null;
}

function rootPointer(names: StageNames): string | null {
	for (const circle of Object.values(names))
		if (circle.isRoot === true) return circle.pointer;
	return null;
}

export function windowAt(
	rows: readonly TraceRow[],
	frames: readonly ScreenFrame[],
	names: StageNames,
	t: number,
	fps: number,
): WindowState {
	const first = frames[0];
	const closed = { open: 0, tonePulse: 0, playFlash: 0, errorPulse: 0 };
	if (first === undefined || t < first.tick) return closed;
	const root = rootPointer(names);
	let openAt: number | null = root === null ? first.tick : null;
	let closeAt: number | null = null;
	let errorAt: number | null = null;
	for (const row of rows) {
		const time = Math.max(row.tick, 0);
		if (
			root !== null &&
			row.kind === "enter" &&
			row.pointer === root &&
			openAt === null
		)
			openAt = time;
		if (
			root !== null &&
			(row.kind === "exit" || row.kind === "finish") &&
			circleOf(row.pointer) === root &&
			openAt !== null &&
			closeAt === null &&
			time >= openAt
		)
			closeAt = time;
		if (row.kind === "error" && errorAt === null) errorAt = time;
	}
	if (openAt === null) return closed;
	let open = clamp01((t - openAt) / fps / OPEN_SECONDS);
	if (closeAt !== null && t >= closeAt)
		open *= 1 - clamp01((t - closeAt) / fps / OPEN_SECONDS);
	const tone = sinceSound(frames, t, fps, "tone", PULSE_SECONDS);
	const play = sinceSound(frames, t, fps, "play", FLASH_SECONDS);
	return {
		open,
		tonePulse: tone === null ? 0 : 1 - tone / PULSE_SECONDS,
		playFlash: play === null ? 0 : 1 - play / FLASH_SECONDS,
		errorPulse:
			errorAt === null || t < errorAt
				? 0
				: 0.5 + 0.5 * Math.sin(2 * Math.PI * ERROR_HZ * ((t - errorAt) / fps)),
	};
}
