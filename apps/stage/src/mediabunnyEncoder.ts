import {
	AudioSample,
	AudioSampleSource,
	BufferTarget,
	CanvasSource,
	canEncodeAudio,
	canEncodeVideo,
	Mp4OutputFormat,
	Output,
	Quality,
	WebMOutputFormat,
} from "mediabunny";

import type { CodecChoice } from "./codec";
import { SAMPLE_RATE as AUDIO_SAMPLE_RATE } from "./screen/sound";
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

/** 書き出しの音声（48kHz・モノラル・仕様書 2026-10-01 summon §3）を `codec` でエンコードできるか。WebCodecs が無ければ false。 */
export function canEncodeAudioTrack(codec: "aac" | "opus"): Promise<boolean> {
	if (typeof AudioEncoder === "undefined") return Promise.resolve(false);
	return canEncodeAudio(codec, { numberOfChannels: 1, sampleRate: 48000 });
}

/** 音声を 1 回に足す長さ（秒）。エンコーダの背圧に従うため 1 本で足さず、この長さに分ける。 */
const AUDIO_CHUNK_SECONDS = 1;

/**
 * 音声のコーデック（probe §G）: MP4 は `aac`、使えなければ `opus`（Mediabunny の MP4 は opus を受ける。同梱 Chromium は
 * AAC を持たない）。WebM は `opus`。どちらも使えなければ null（無音で書き出す）。
 */
async function audioCodecFor(
	container: CodecChoice["container"],
	can: (codec: "aac" | "opus") => Promise<boolean>,
): Promise<"aac" | "opus" | null> {
	if (container === "mp4" && (await can("aac"))) return "aac";
	return (await can("opus")) ? "opus" : null;
}

/**
 * 映像（canvas）と、あれば音声（48kHz・モノラルの PCM・`screen/sound.ts`）を書き出すエンコーダ。
 * 音声のコーデックが無ければ映像だけにして `audio: false` を返す（書き出しは止めない・仕様書 2026-10-01-jin-stage-summon §3.3）。
 */
export async function createEncoder(
	canvas: HTMLCanvasElement,
	choice: CodecChoice,
	audio: Float32Array | null,
	canEncodeAudioCodec: (
		codec: "aac" | "opus",
	) => Promise<boolean> = canEncodeAudioTrack,
): Promise<FrameEncoder & { readonly audio: boolean }> {
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
	const audioCodec =
		audio === null
			? null
			: await audioCodecFor(choice.container, canEncodeAudioCodec);
	const audioSource =
		audioCodec === null
			? null
			: new AudioSampleSource({
					codec: audioCodec,
					quality: new Quality("high"),
				});
	if (audioSource !== null) output.addAudioTrack(audioSource);
	await output.start();
	if (audioSource !== null && audio !== null) {
		const step = AUDIO_CHUNK_SECONDS * AUDIO_SAMPLE_RATE;
		for (let i = 0; i < audio.length; i += step) {
			const sample = new AudioSample({
				data: audio.subarray(i, Math.min(audio.length, i + step)),
				format: "f32",
				numberOfChannels: 1,
				sampleRate: AUDIO_SAMPLE_RATE,
				timestamp: i / AUDIO_SAMPLE_RATE,
			});
			await audioSource.add(sample);
			sample.close();
		}
		audioSource.close();
	}
	return {
		audio: audioSource !== null,
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
