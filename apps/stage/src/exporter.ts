import {
	clampRange,
	type ExportRange,
	frameCount,
	tickAtFrame,
	VIDEO_FPS,
} from "./timeline";

/**
 * 1 コマずつの書き出し（docs/spec/v2/stage.md §5）。**実時間の録画はしない**。
 * エンコーダは注入する（実物は `mediabunnyEncoder.ts`）。
 */
export interface FrameEncoder {
	add(timestampSeconds: number, durationSeconds: number): Promise<void>;
	finish(): Promise<Uint8Array>;
	cancel(): Promise<void>;
}

export interface ExportJob {
	readonly range: ExportRange;
	/** tick（実数）の場面を、エンコーダが読む canvas に描く。 */
	draw(tick: number): void;
	readonly encoder: FrameEncoder;
	readonly signal: AbortSignal;
	onProgress(done: number, total: number): void;
}

export async function runExport(job: ExportJob): Promise<Uint8Array | null> {
	const range = clampRange(job.range);
	const total = frameCount(range);
	try {
		for (let n = 0; n < total; n++) {
			if (job.signal.aborted) {
				await job.encoder.cancel();
				return null;
			}
			job.draw(tickAtFrame(range, n));
			await job.encoder.add(n / VIDEO_FPS, 1 / VIDEO_FPS);
			job.onProgress(n + 1, total);
		}
		if (job.signal.aborted) {
			await job.encoder.cancel();
			return null;
		}
		return await job.encoder.finish();
	} catch (error) {
		await job.encoder.cancel().catch(() => undefined);
		throw error;
	}
}
