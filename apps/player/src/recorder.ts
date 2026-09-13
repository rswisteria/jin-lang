/**
 * 録画 `.jinrec`（runtime.md §7）。JSONL。1 行目はヘッダ、以降は `{tick, kind, ...}`。
 *
 * `jin_wasm.jinrec.dumps_jinrec` と同じ形（ヘッダのキー順 `jinrec, file, seed, fps, ticks`）。
 * `ticks` は実行した tick 数（`jin run --ticks` の既定値になる）。
 */
import type { InputEvent } from "./types";

export const JINREC_VERSION = 1;

export interface RecordingHeader {
	readonly file: string;
	readonly seed: number;
	readonly fps: number;
}

export class Recorder {
	private readonly lines: string[] = [];
	private count = 0;

	constructor(private readonly header: RecordingHeader) {}

	/** この tick に渡したイベントを発生順に書く（`inputs.events` と同じ列）。 */
	push(tick: number, events: readonly InputEvent[]): void {
		for (const ev of events) {
			this.lines.push(JSON.stringify({ tick, ...ev }));
			this.count += 1;
		}
	}

	get events(): number {
		return this.count;
	}

	/** ヘッダ + 本文。`ticks` は `tick(0..ticks-1)` を呼んだ数。 */
	finish(ticks: number): string {
		const head = JSON.stringify({
			jinrec: JINREC_VERSION,
			file: this.header.file,
			seed: this.header.seed,
			fps: this.header.fps,
			ticks,
		});
		return [head, ...this.lines].join("\n") + "\n";
	}
}
