/**
 * 音リスト（abilities.md §5）を WebAudio で鳴らす。
 *
 * - `tone(hz, ms)`: 矩形波を `ms` ミリ秒。同 tick の複数の `tone` は同時に鳴る
 * - `play(name)`: `stage.assets[]` の `kind: sound` を頭から再生
 *
 * `AudioContext` はユーザー操作の後でないと動かないので、最初のクリック / キー入力で `unlock()` する。
 * 無い環境（テスト / ヘッドレス）では何もしない。音はトレースに載らないので決定性に影響しない。
 */
import { AUDIO_OPS, op } from "./abilities";
import type { Op } from "./types";

const TONE = op("tone");
const PLAY = op("play");

export class AudioOut {
	private context: AudioContext | null = null;
	private readonly sounds = new Map<string, AudioBuffer>();
	private readonly pendingSounds = new Map<string, ArrayBuffer>();

	/** 起動時に読んだ音源（デコードは `unlock()` 後）。 */
	addSound(name: string, bytes: ArrayBuffer): void {
		this.pendingSounds.set(name, bytes);
	}

	/** ユーザー操作の中で呼ぶ。 */
	unlock(): void {
		if (typeof AudioContext === "undefined") return;
		if (this.context === null) {
			this.context = new AudioContext();
			for (const [name, bytes] of this.pendingSounds) {
				void this.context
					.decodeAudioData(bytes.slice(0))
					.then((buffer) => this.sounds.set(name, buffer));
			}
			this.pendingSounds.clear();
		}
		if (this.context.state === "suspended") void this.context.resume();
	}

	play(ops: readonly Op[]): void {
		const ctx = this.context;
		if (ctx === null || ctx.state !== "running") return;
		for (const [name, ...args] of ops) {
			if (name === TONE) {
				const hz = typeof args[0] === "number" ? args[0] : 440;
				const ms = typeof args[1] === "number" ? args[1] : 0;
				if (hz <= 0 || ms <= 0) continue;
				const osc = ctx.createOscillator();
				osc.type = "square";
				osc.frequency.value = hz;
				const gain = ctx.createGain();
				gain.gain.value = 0.08;
				osc.connect(gain).connect(ctx.destination);
				osc.start();
				osc.stop(ctx.currentTime + ms / 1000);
			} else if (name === PLAY) {
				const buffer = this.sounds.get(
					typeof args[0] === "string" ? args[0] : "",
				);
				if (buffer === undefined) continue;
				const source = ctx.createBufferSource();
				source.buffer = buffer;
				source.connect(ctx.destination);
				source.start();
			}
			// AUDIO_OPS の外は無視する
		}
	}
}

export { AUDIO_OPS };
