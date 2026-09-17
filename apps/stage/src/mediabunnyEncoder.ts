import {
	BufferTarget,
	CanvasSource,
	canEncodeVideo,
	Mp4OutputFormat,
	Output,
	Quality,
	WebMOutputFormat,
} from "mediabunny";

import type { CodecChoice } from "./codec";
import type { FrameEncoder } from "./exporter";
import { VIDEO_FPS } from "./timeline";

/**
 * Mediabunny の薄いアダプタ（docs/spec/v2/stage.md §5）。単体テストせず e2e が読み戻して見る。
 * 画質は `quality: new Quality("high")`（`bitrate: QUALITY_HIGH` は 1.57.0 で非推奨・stage-api-probe.md §B.3 / §E）。
 */
export function canEncode(
	codec: "avc" | "vp9",
	width: number,
	height: number,
): Promise<boolean> {
	if (typeof VideoEncoder === "undefined") return Promise.resolve(false);
	return canEncodeVideo(codec, { width, height, quality: new Quality("high") });
}

export async function createEncoder(
	canvas: HTMLCanvasElement,
	choice: CodecChoice,
): Promise<FrameEncoder> {
	const target = new BufferTarget();
	const output = new Output({
		format:
			choice.container === "mp4"
				? new Mp4OutputFormat()
				: new WebMOutputFormat(),
		target,
	});
	const source = new CanvasSource(canvas, {
		codec: choice.codec,
		quality: new Quality("high"),
	});
	output.addVideoTrack(source, { frameRate: VIDEO_FPS });
	await output.start();
	return {
		add: (timestamp, duration) => source.add(timestamp, duration),
		finish: async () => {
			await output.finalize();
			if (target.buffer === null)
				throw new Error("書き出したバイト列がありません");
			return new Uint8Array(target.buffer);
		},
		cancel: () => output.cancel(),
	};
}
