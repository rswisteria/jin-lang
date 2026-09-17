import { expect, test } from "vitest";

import { chooseCodec } from "../src/codec";

const only =
	(...ok: string[]): ((codec: string) => Promise<boolean>) =>
	(codec: string): Promise<boolean> =>
		Promise.resolve(ok.includes(codec));

test("H.264 が使えれば MP4", async () => {
	expect(await chooseCodec(only("avc", "vp9"), 1080, 1080)).toEqual({
		codec: "avc",
		container: "mp4",
		mime: "video/mp4",
	});
});

test("H.264 が無ければ WebM（VP9）", async () => {
	expect(await chooseCodec(only("vp9"), 1080, 1080)).toEqual({
		codec: "vp9",
		container: "webm",
		mime: "video/webm",
	});
});

test("どちらも無理なら null、判定が例外を投げても null", async () => {
	expect(await chooseCodec(only(), 1080, 1080)).toBeNull();
	expect(
		await chooseCodec(
			() => Promise.reject(new Error("no WebCodecs")),
			1080,
			1080,
		),
	).toBeNull();
});
