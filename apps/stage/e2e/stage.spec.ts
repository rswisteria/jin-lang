import { expect, type Page, test } from "@playwright/test";
import { ALL_FORMATS, BufferSource, Input } from "mediabunny";

import { PADDLE_STEP, serveHarness, TETRIS } from "./harness";

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

/** 画面のうち、色相が [lo, hi]°・彩度と明度がしきい値以上の画素の割合。 */
async function hueShare(
	page: Page,
	stage: ReturnType<Page["frameLocator"]>,
	lo: number,
	hi: number,
): Promise<number> {
	void page;
	return stage.locator("canvas").evaluate(
		(canvas: HTMLCanvasElement, [from, to]) => {
			const probe = document.createElement("canvas");
			probe.width = canvas.width;
			probe.height = canvas.height;
			const context = probe.getContext("2d");
			if (context === null) return 0;
			context.drawImage(canvas, 0, 0);
			const data = context.getImageData(0, 0, probe.width, probe.height).data;
			let hit = 0;
			for (let i = 0; i < data.length; i += 4) {
				const r = (data[i] ?? 0) / 255;
				const g = (data[i + 1] ?? 0) / 255;
				const b = (data[i + 2] ?? 0) / 255;
				const max = Math.max(r, g, b);
				const min = Math.min(r, g, b);
				const d = max - min;
				if (max < 0.35 || d / max < 0.45) continue;
				const h =
					(max === r
						? ((g - b) / d) % 6
						: max === g
							? (b - r) / d + 2
							: (r - g) / d + 4) * 60;
				const hue = (h + 360) % 360;
				if (hue >= (from ?? 0) && hue <= (to ?? 0)) hit++;
			}
			return hit / (data.length / 4);
		},
		[lo, hi] as const,
	);
}

/**
 * 色の意味（仕様書 2026-10-01 §2.1）: tetris の場面で、最初の `cast canvas.*`（tick 0・強さ 1）が進み 0.2 ほどで
 * 光っている tick 10 に、サファイアの色相の画素が画面の 0.02% 以上ある（宝玉の色が実際に出ている）。
 * 基準は実測（0.045%・960×624）の半分弱。金一色ならほぼ 0% なので区別できる（光線は細く、面積の比は小さい）。
 */
test("cast canvas.* の直後、画面にサファイアの色が出ている", async ({
	page,
}) => {
	const tetris = await serveHarness(TETRIS);
	await page.goto(tetris.url);
	const stage = page.frameLocator("#stage");
	await expect(stage.getByTestId("stage-status")).toHaveText("準備完了");
	await stage.getByTestId("stage-scrub").fill("10");
	await page.waitForTimeout(500);
	const share = await hueShare(page, stage, 210, 235);
	expect(share).toBeGreaterThanOrEqual(0.0002);
	await tetris.close();
});

/** 手順の図（紋と記憶が無く、核と手順のステップだけ）を送っても、例外を出さずに描ける（Review Focus）。 */
test("手順の図の場面でも描け、PNG を書き出せる", async ({ page }) => {
	const step = await serveHarness(PADDLE_STEP);
	await page.goto(step.url);
	const stage = page.frameLocator("#stage");
	await expect(stage.getByTestId("stage-status")).toHaveText("準備完了");
	await stage.getByTestId("stage-export-png").click();
	await expect.poll(async () => (await files(page)).length).toBe(1);
	const status = await page.evaluate(
		() =>
			(window as unknown as { JIN_STATUS: { error: string | null } })
				.JIN_STATUS,
	);
	expect(status.error).toBeNull();
	await step.close();
});

test("1 秒の動画を書き出し、読み戻すと 60 コマ・約 1 秒", async ({ page }) => {
	const stage = await open(page);
	const codecLabel = stage.getByTestId("stage-codec");
	await expect(codecLabel).toHaveAttribute("data-codec", /.+/);
	const codec = await codecLabel.getAttribute("data-codec");
	// CI の stage ジョブは JIN_REQUIRE_CODEC=1 で走る。どちらのコーデックも無いときに往復を黙って飛ばさない
	// （CI と同じ Linux の Chromium 151 では avc / vp9 とも通る。probe §C.1）。
	if (process.env["JIN_REQUIRE_CODEC"] === "1")
		expect(codec, "JIN_REQUIRE_CODEC=1 なのに動画を書き出せない").not.toBe(
			"none",
		);
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
	expect(video?.mime).toBe(codec === "avc" ? "video/mp4" : "video/webm");
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

/**
 * 編集のたびに `stage.scene` が届く（仕様書 2026-10-01 Review Focus）。床の映り込みの描画先・後処理・宝玉の素材を
 * 前の場面の分まで解放し、GPU の資源（geometry / texture）が送り直すたびに増えないこと。
 */
test("stage.scene を送り直しても GPU の資源が増え続けない", async ({
	page,
}) => {
	await open(page);
	const stageFrame = page
		.frames()
		.find((frame) => frame.url().includes("/stage/"));
	if (stageFrame === undefined) throw new Error("stage の iframe が無い");
	type Memory = { geometries: number; textures: number };
	const memory = (): Promise<Memory> =>
		stageFrame.evaluate(() =>
			(
				window as unknown as { __jinStage: { memory(): Memory } }
			).__jinStage.memory(),
		);
	const resend = async (): Promise<void> => {
		await page.evaluate(() =>
			(window as unknown as { JIN_RESEND(): void }).JIN_RESEND(),
		);
		await page.waitForTimeout(400);
	};
	await resend();
	const first = await memory();
	for (let k = 0; k < 5; k++) await resend();
	const last = await memory();
	expect(first.geometries).toBeGreaterThan(0);
	expect(last.geometries).toBeLessThanOrEqual(first.geometries);
	expect(last.textures).toBeLessThanOrEqual(first.textures);
});

/**
 * 召喚の窓（仕様書 2026-10-01-jin-stage-summon §1）: tetris の場面（stageSize あり）の tick 60 で窓が見え、tick 60 のコマを映す。
 * stageSize を外して送り直すと窓は消え、エラーにならない。描いた中身が正しいことは screen.spec.ts の画素一致が見る
 * （画面の色の割合では、宝玉の色とゲームの色が重なって窓の有無を見分けられなかった）。
 */
test("tetris の場面で、召喚の窓にゲーム画面が映る（stageSize を外すと消え、エラーにならない）", async ({
	page,
}) => {
	const tetris = await serveHarness(TETRIS);
	await page.goto(tetris.url);
	const stage = page.frameLocator("#stage");
	await expect(stage.getByTestId("stage-status")).toHaveText("準備完了");
	const stageFrame = page
		.frames()
		.find((frame) => frame.url().includes("/stage/"));
	if (stageFrame === undefined) throw new Error("stage の iframe が無い");
	type Shown = { visible: boolean; tick: number | null };
	const shown = (): Promise<Shown> =>
		stageFrame.evaluate(() =>
			(
				window as unknown as { __jinStage: { summon(): Shown } }
			).__jinStage.summon(),
		);
	await stage.getByTestId("stage-scrub").fill("60");
	await expect.poll(shown).toEqual({ visible: true, tick: 60 });
	await page.evaluate(() => {
		const w = window as unknown as {
			JIN_SCENE: { stageSize: unknown };
			JIN_RESEND(): void;
		};
		w.JIN_SCENE.stageSize = null;
		w.JIN_RESEND();
	});
	await stage.getByTestId("stage-scrub").fill("61");
	await expect.poll(async () => (await shown()).visible).toBe(false);
	const status = await page.evaluate(
		() =>
			(window as unknown as { JIN_STATUS: { error: string | null } })
				.JIN_STATUS,
	);
	expect(status.error).toBeNull();
	await tetris.close();
});
test("召喚の窓のある場面でも、stage.scene を送り直して GPU の資源が増え続けない", async ({
	page,
}) => {
	const tetris = await serveHarness(TETRIS);
	await page.goto(tetris.url);
	const stage = page.frameLocator("#stage");
	await expect(stage.getByTestId("stage-status")).toHaveText("準備完了");
	const stageFrame = page
		.frames()
		.find((frame) => frame.url().includes("/stage/"));
	if (stageFrame === undefined) throw new Error("stage の iframe が無い");
	type Memory = { geometries: number; textures: number };
	const memory = (): Promise<Memory> =>
		stageFrame.evaluate(() =>
			(
				window as unknown as { __jinStage: { memory(): Memory } }
			).__jinStage.memory(),
		);
	const resend = async (): Promise<void> => {
		await page.evaluate(() =>
			(window as unknown as { JIN_RESEND(): void }).JIN_RESEND(),
		);
		await page.waitForTimeout(400);
	};
	await resend();
	const first = await memory();
	for (let k = 0; k < 5; k++) await resend();
	const last = await memory();
	expect(last.geometries).toBeLessThanOrEqual(first.geometries);
	expect(last.textures).toBeLessThanOrEqual(first.textures);
	await tetris.close();
});
