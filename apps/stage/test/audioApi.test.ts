import {
	AudioSample,
	AudioSampleSource,
	canEncodeAudio,
	Output,
	Quality,
} from "mediabunny";
import { describe, expect, it } from "vitest";

/**
 * Mediabunny 1.57.0 の音声の部品の実測（delivery/…/stage-api-probe.md §G）。エンコードはしない（jsdom に WebCodecs は無い）。
 * ブラウザでの可否と書き出しの読み戻しは `e2e/audioProbe.spec.ts`。
 */
describe("Mediabunny 1.57.0 の音声トラックの部品", () => {
	it("AudioSample は f32・モノラル・48kHz の PCM と秒の timestamp で作れ、長さは秒", () => {
		const sample = new AudioSample({
			data: new Float32Array(480),
			format: "f32",
			numberOfChannels: 1,
			sampleRate: 48000,
			timestamp: 0.5,
		});
		expect(sample.duration).toBeCloseTo(0.01, 9);
		expect(sample.timestamp).toBe(0.5);
		expect(sample.numberOfFrames).toBe(480);
		sample.close();
	});

	it("AudioSampleSource はエンコードの設定（codec）で作り、Output.addAudioTrack に渡す", () => {
		expect(typeof AudioSampleSource).toBe("function");
		expect(typeof Output.prototype.addAudioTrack).toBe("function");
		const source = new AudioSampleSource({ codec: "aac", quality: new Quality("high") });
		expect(typeof source.add).toBe("function");
	});

	it("canEncodeAudio は codec と（チャンネル数・サンプルレート）を受ける関数", () => {
		expect(typeof canEncodeAudio).toBe("function");
	});
});
