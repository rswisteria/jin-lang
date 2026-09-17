import { expect, type Page, test } from "@playwright/test";
import { ALL_FORMATS, BufferSource, Input } from "mediabunny";

import { serveHarness } from "./harness";

/**
 * 鑑賞ページの往復（docs/spec/v2/stage.md §5・設計書 §4.4）。360p・1 秒で書き出し、
 * PNG の署名と、動画を Mediabunny で読み戻したコマ数・長さを見る。
 * 読み戻しは Node 側（この spec）の demux で、WebCodecs は要らない（probe §B.5）。
 * Chromium（Playwright）で H.264 を encode できるかは probe §C の結果に従う（できなければ WebM を見る）。
 */
let harness: Awaited<ReturnType<typeof serveHarness>>;

test.beforeEach(async () => {
	harness = await serveHarness();
});
test.afterEach(async () => {
	await harness.close();
});

async function open(page: Page) {
	await page.goto(harness.url);
	const stage = page.frameLocator("#stage");
	await expect(stage.getByTestId("stage-status")).toHaveText("準備完了");
	return stage;
}

type Received = { name: string; mime: string; bytes: number[] };
const files = (page: Page): Promise<Received[]> =>
	page.evaluate(
		() => (window as unknown as { JIN_FILES: Received[] }).JIN_FILES,
	);

test("陣が描かれ、トレースの行数が届く", async ({ page }) => {
	const stage = await open(page);
	await expect(stage.getByTestId("stage-rows")).toHaveText("995");
	const lit = await stage
		.locator("canvas")
		.evaluate((canvas: HTMLCanvasElement) => {
			const probe = document.createElement("canvas");
			probe.width = 64;
			probe.height = 64;
			const context = probe.getContext("2d");
			context?.drawImage(canvas, 0, 0, 64, 64);
			const data =
				context?.getImageData(0, 0, 64, 64).data ?? new Uint8ClampedArray();
			let bright = 0;
			for (let i = 0; i < data.length; i += 4)
				if ((data[i] ?? 0) + (data[i + 1] ?? 0) > 180) bright++;
			return bright;
		});
	expect(lit).toBeGreaterThan(20);
});

test("PNG を書き出す", async ({ page }) => {
	const stage = await open(page);
	await stage.getByTestId("stage-export-png").click();
	await expect.poll(async () => (await files(page)).length).toBe(1);
	const [png] = await files(page);
	expect(png?.name).toMatch(/^paddle-Play-seed7-t\d+-\d+\.png$/);
	expect(png?.mime).toBe("image/png");
	expect(png?.bytes.slice(0, 8)).toEqual([
		0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
	]);
});

test("1 秒の動画を書き出し、読み戻すと 60 コマ・約 1 秒", async ({ page }) => {
	const stage = await open(page);
	const codecLabel = stage.getByTestId("stage-codec");
	await expect(codecLabel).toHaveAttribute("data-codec", /.+/);
	const codec = await codecLabel.getAttribute("data-codec");
	// CI の stage ジョブは JIN_REQUIRE_CODEC=1 で走る。どちらのコーデックも無いときに往復を黙って飛ばさない
	// （CI と同じ Linux の Chromium 151 では avc / vp9 とも通る。probe §C.1）。
	if (process.env["JIN_REQUIRE_CODEC"] === "1")
		expect(codec, "JIN_REQUIRE_CODEC=1 なのに動画を書き出せない").not.toBe("none");
	test.skip(codec === "none", "WebCodecs が無い環境（probe §C）");
	test.info().annotations.push({ type: "codec", description: codec ?? "" });
	await stage.getByTestId("stage-start").fill("0");
	await stage.getByTestId("stage-end").fill("60");
	await stage.getByTestId("stage-export-video").click();
	await expect
		.poll(async () => (await files(page)).length, { timeout: 150_000 })
		.toBe(1);
	const [video] = await files(page);
	expect(video?.name).toMatch(/^paddle-Play-seed7-t0-60\.(mp4|webm)$/);
	expect(video?.mime).toBe(
		codec === "avc" ? "video/mp4" : "video/webm",
	);
	const input = new Input({
		source: new BufferSource(new Uint8Array(video?.bytes ?? [])),
		formats: ALL_FORMATS,
	});
	const track = await input.getPrimaryVideoTrack();
	if (track === null) throw new Error("動画のトラックが読めません");
	const readBack = {
		duration: await input.computeDuration(),
		packets: (await track.computePacketStats()).packetCount,
		width: await track.getDisplayWidth(),
		height: await track.getDisplayHeight(),
	};
	expect(readBack.packets).toBe(60);
	expect(readBack.duration).toBeGreaterThan(0.95);
	expect(readBack.duration).toBeLessThan(1.05);
	expect([readBack.width, readBack.height]).toEqual([360, 360]);
});
