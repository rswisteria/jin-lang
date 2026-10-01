import { type ExportRange, frameCount, VIDEO_FPS } from "../timeline";
import type { ScreenFrame } from "./frames";

/**
 * 書き出しの音（仕様書 docs/superpowers/specs/2026-10-01-jin-stage-summon-design.md §3.1）。`frame` 行の `audio` の
 * `tone(hz, ms)` を、プレイヤー（`apps/player/src/audio.ts`）と同じ矩形波・音量 0.08 で合成する。three を import しない純関数。
 *
 * プレイヤーとの差は頭と終わりの `FADE_SECONDS` の線形フェードだけ（書き出しの雑音を消す。トレースと決定性には影響しない）。
 * `play(name)` は素材が届かないので鳴らさない。
 */
export const SAMPLE_RATE = 48000;
export const TONE_GAIN = 0.08;
export const FADE_SECONDS = 0.005;

export interface ToneEvent {
	/** 動画の頭からの秒。 */
	readonly startSeconds: number;
	readonly hz: number;
	readonly seconds: number;
}

function videoSeconds(range: ExportRange): number {
	return frameCount(range) / VIDEO_FPS;
}

/**
 * 範囲の中で鳴る音。置き場所は `(tick − 開始) / fps / 速度` 秒（0.5 倍速でも音程と長さはそのまま）。
 * 開始より前に鳴り始めて食い込む音は頭を切り、範囲の外の音は捨てる（終わりの切り詰めは `synthesize`）。
 */
export function toneEvents(
	frames: readonly ScreenFrame[],
	range: ExportRange,
): readonly ToneEvent[] {
	const total = videoSeconds(range);
	const events: ToneEvent[] = [];
	for (const frame of frames) {
		for (const [name, ...args] of frame.audio) {
			if (name !== "tone") continue;
			const hz = typeof args[0] === "number" ? args[0] : 0;
			const ms = typeof args[1] === "number" ? args[1] : 0;
			if (!(hz > 0) || !(ms > 0)) continue;
			const start = (frame.tick - range.startTick) / range.fps / range.speed;
			const end = start + ms / 1000;
			if (end <= 0 || start >= total) continue;
			const head = Math.max(0, start);
			// 頭を切らないときは長さを ms / 1000 のまま（end − start は浮動小数の誤差を持つ）。
			events.push({ startSeconds: head, hz, seconds: start >= 0 ? ms / 1000 : end });
		}
	}
	return events;
}

/** 範囲の動画と同じ長さの 48kHz・モノラルの PCM。同時の音は足して [−1, 1] に収める。 */
export function synthesize(
	frames: readonly ScreenFrame[],
	range: ExportRange,
): Float32Array {
	const pcm = new Float32Array(Math.round(videoSeconds(range) * SAMPLE_RATE));
	for (const { startSeconds, hz, seconds } of toneEvents(frames, range)) {
		const first = Math.round(startSeconds * SAMPLE_RATE);
		const count = Math.round(seconds * SAMPLE_RATE);
		for (let k = 0; k < count; k++) {
			const i = first + k;
			if (i >= pcm.length) break;
			const tau = k / SAMPLE_RATE;
			// 矩形波（周期の前半 +・後半 −）。sin の符号だと、ちょうど半周期の位置で 0 になる。
			const square = (hz * tau) % 1 < 0.5 ? 1 : -1;
			const fade = Math.min(
				1,
				tau / FADE_SECONDS,
				(seconds - tau) / FADE_SECONDS,
			);
			pcm[i] = (pcm[i] ?? 0) + square * TONE_GAIN * Math.max(0, fade);
		}
	}
	for (let i = 0; i < pcm.length; i++)
		pcm[i] = Math.min(1, Math.max(-1, pcm[i] ?? 0));
	return pcm;
}
