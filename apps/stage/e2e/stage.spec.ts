import { expect, type Page, test } from "@playwright/test";
import { ALL_FORMATS, BufferSource, Input } from "mediabunny";

import {
	PADDLE_BAND,
	PADDLE_STEP,
	serveHarness,
	TETRIS,
	TETRIS_DROPS,
} from "./harness";

/**
 * 音（仕様書 2026-10-01-jin-stage-summon §3.3）: ハードドロップ 3 回の tetris（tick 4 / 34 / 64 で tone）の 2 秒（tick 0〜120・
 * harness の fps 60）を書き出し、Node 側で読み戻す。`noaudio` なら iframe を `?noaudio=1` で読み直す（音声のコーデックが無い分岐）。
 */
async function exportDrops(
	page: Page,
	noaudio: boolean,
): Promise<{
	audio: boolean;
	audioSeconds: number | null;
	videoSeconds: number;
	mime: string;
}> {
	const harness = await serveHarness(TETRIS_DROPS);
	await page.goto(harness.url);
	if (noaudio) {
		await page.evaluate(() => {
			(document.getElementById("stage") as HTMLIFrameElement).src =
				"./stage/?export=360&noaudio=1";
		});
	}
	const stage = page.frameLocator("#stage");
	await expect(stage.getByTestId("stage-status")).toHaveText("準備完了");
	const codecLabel = stage.getByTestId("stage-codec");
	await expect(codecLabel).toHaveAttribute("data-codec", /.+/);
	test.skip(
		(await codecLabel.getAttribute("data-codec")) === "none",
		"WebCodecs が無い環境（probe §C）",
	);
	await stage.getByTestId("stage-start").fill("0");
	await stage.getByTestId("stage-end").fill("120");
	await stage.getByTestId("stage-export-video").click();
	await expect
		.poll(async () => (await files(page)).length, { timeout: 170_000 })
		.toBe(1);
	const [video] = await files(page);
	const input = new Input({
		source: new BufferSource(new Uint8Array(video?.bytes ?? [])),
		formats: ALL_FORMATS,
	});
	const audioTrack = await input.getPrimaryAudioTrack();
	const videoTrack = await input.getPrimaryVideoTrack();
	if (videoTrack === null) throw new Error("動画のトラックが読めません");
	const result = {
		audio: audioTrack !== null,
		audioSeconds:
			audioTrack === null ? null : await audioTrack.computeDuration(),
		videoSeconds: await videoTrack.computeDuration(),
		mime: video?.mime ?? "",
	};
	await harness.close();
	return result;
}

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

test("ホイールで寄り、右ドラッグで注視点をずらし、ダブルクリックで戻す（stage.md §4）", async ({
	page,
}) => {
	// CI のソフトウェア描画では 1 コマが重く、実入力 1 つごとに描画の合間を待つ。入力の数を最小にし、制限を延ばす。
	test.setTimeout(300_000);
	const stage = await open(page);
	const canvas = stage.locator("canvas");
	type Offset = {
		azimuthDeg: number;
		elevationDeg: number;
		zoom?: number;
		pan?: [number, number];
	};
	const camera = (): Promise<Offset> =>
		canvas.evaluate(() =>
			(
				window as unknown as { __jinStage: { camera(): Offset } }
			).__jinStage.camera(),
		);
	const box = await canvas.boundingBox();
	if (box === null) throw new Error("canvas が描かれていません");
	const cx = box.x + box.width / 2;
	const cy = box.y + box.height / 2;

	await page.mouse.move(cx, cy);
	await page.mouse.wheel(0, -400);
	await expect.poll(async () => (await camera()).zoom ?? 1).toBeLessThan(0.9);

	await page.mouse.down({ button: "right" });
	await page.mouse.move(cx + 120, cy + 40);
	await page.mouse.up({ button: "right" });
	const panned = await camera();
	expect(Math.hypot(...(panned.pan ?? [0, 0]))).toBeGreaterThan(0.05);
	// 右ドラッグは回さない。
	expect(panned.azimuthDeg).toBe(0);
	expect(panned.elevationDeg).toBe(0);

	// 要素への dblclick は「止まっているか」を描画 2 回分待つので、座標に直接打つ。
	await page.mouse.dblclick(cx, cy);
	expect(await camera()).toEqual({
		azimuthDeg: 0,
		elevationDeg: 0,
		zoom: 1,
		pan: [0, 0],
	});
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

/**
 * 隠れている間は描かない: エディタは鑑賞パネルの iframe を v2 のファイルでは常に載せ、鑑賞モード以外では隠すだけ。
 * 隠れた iframe で重い 3D（床の映り込み・宝玉の透過・被写界深度…）を描き続けると、ソフトウェア描画の CI でエディタ全体が
 * 応答しなくなった（PR #100 の editor ジョブ）。iframe を隠すと描画の回数が止まり、見せると再開する。
 */
test("iframe が隠れている間は描かない（見せると再開する）", async ({
	page,
}) => {
	await open(page);
	const stageFrame = page
		.frames()
		.find((frame) => frame.url().includes("/stage/"));
	if (stageFrame === undefined) throw new Error("stage の iframe が無い");
	const draws = (): Promise<number> =>
		stageFrame.evaluate(() =>
			(
				window as unknown as { __jinStage: { draws(): number } }
			).__jinStage.draws(),
		);
	await expect.poll(draws).toBeGreaterThan(0);
	await page.evaluate(() => {
		(document.getElementById("stage") as HTMLIFrameElement).hidden = true;
	});
	await page.waitForTimeout(300);
	const hidden = await draws();
	await page.waitForTimeout(1000);
	expect(await draws()).toBe(hidden);
	await page.evaluate(() => {
		(document.getElementById("stage") as HTMLIFrameElement).hidden = false;
	});
	await expect.poll(draws).toBeGreaterThan(hidden);
});

test("音: 書き出した動画に音声トラックがあり、長さは映像とほぼ同じ", async ({
	page,
}) => {
	test.setTimeout(240_000);
	const result = await exportDrops(page, false);
	test.info().annotations.push({ type: "mime", description: result.mime });
	expect(result.audio).toBe(true);
	expect(
		Math.abs((result.audioSeconds ?? 0) - result.videoSeconds),
	).toBeLessThanOrEqual(0.1);
});

test("音: 音声のコーデックが無い環境（?noaudio=1）でも、無音の動画を書き出してファイルを渡す", async ({
	page,
}) => {
	test.setTimeout(240_000);
	const result = await exportDrops(page, true);
	expect(result.audio).toBe(false);
	expect(result.videoSeconds).toBeGreaterThan(1.9);
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
	test.setTimeout(300_000);
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
	type Shown = { visible: boolean; tick: number | null };
	const shown = (): Promise<Shown> =>
		stageFrame.evaluate(() =>
			(
				window as unknown as { __jinStage: { summon(): Shown } }
			).__jinStage.summon(),
		);
	// 送り直すたびに、窓が開いている tick（60）で描かせる。窓が描かれて初めてテクスチャが GPU に載るので、
	// t = 0（窓は閉じている）のままでは、前の場面のテクスチャを解放しなくてもこのテストは緑になる（最終レビュー Important 1）。
	const resend = async (): Promise<void> => {
		await page.evaluate(() =>
			(window as unknown as { JIN_RESEND(): void }).JIN_RESEND(),
		);
		await page.waitForTimeout(300);
		await stage.getByTestId("stage-scrub").fill("60");
		await expect.poll(shown).toEqual({ visible: true, tick: 60 });
		await page.waitForTimeout(200);
	};
	await resend();
	const first = await memory();
	expect(first.textures).toBeGreaterThan(0);
	// 3 回で足りる（解放しなければ送り直すたびにテクスチャが 1 つ増える）。窓を毎回描かせるので、ソフトウェア描画の CI では 1 回が重い。
	for (let k = 0; k < 3; k++) await resend();
	const last = await memory();
	expect(last.geometries).toBeLessThanOrEqual(first.geometries);
	expect(last.textures).toBeLessThanOrEqual(first.textures);
	await tetris.close();
});

/**
 * 銘環の帯（陣書き S7・stage.md §2.2）: 帯つきの場面で帯が描かれ、発火の直後（tick 30）に升が灯り、
 * 灯った升の数は時刻だけで決まる（同じ tick へ戻すと同じ数）。帯を外して送り直すと消え、エラーにならない。
 * 送り直しても GPU の資源は増え続けない。
 */
test("銘環の帯が描かれ、発火した行の升が灯る（外すと消える）", async ({
	page,
}) => {
	const band = await serveHarness(PADDLE_BAND);
	await page.goto(band.url);
	const stage = page.frameLocator("#stage");
	await expect(stage.getByTestId("stage-status")).toHaveText("準備完了");
	const stageFrame = page
		.frames()
		.find((frame) => frame.url().includes("/stage/"));
	if (stageFrame === undefined) throw new Error("stage の iframe が無い");
	type Shown = { band: boolean; lit: number };
	type Memory = { geometries: number; textures: number };
	const shown = (): Promise<Shown> =>
		stageFrame.evaluate(() =>
			(
				window as unknown as { __jinStage: { inscription(): Shown } }
			).__jinStage.inscription(),
		);
	const memory = (): Promise<Memory> =>
		stageFrame.evaluate(() =>
			(
				window as unknown as { __jinStage: { memory(): Memory } }
			).__jinStage.memory(),
		);
	await stage.getByTestId("stage-scrub").fill("30");
	await page.waitForTimeout(500);
	const at30 = await shown();
	expect(at30.band).toBe(true);
	expect(at30.lit).toBeGreaterThan(0);
	await stage.getByTestId("stage-scrub").fill("80");
	await page.waitForTimeout(300);
	await stage.getByTestId("stage-scrub").fill("30");
	await page.waitForTimeout(300);
	expect((await shown()).lit).toBe(at30.lit);

	const resend = async (): Promise<void> => {
		await page.evaluate(() =>
			(window as unknown as { JIN_RESEND(): void }).JIN_RESEND(),
		);
		await page.waitForTimeout(400);
	};
	await resend();
	const first = await memory();
	for (let k = 0; k < 3; k++) await resend();
	const last = await memory();
	expect(last.geometries).toBeLessThanOrEqual(first.geometries);

	await page.evaluate(() => {
		const w = window as unknown as {
			JIN_SCENE: Record<string, unknown>;
			JIN_RESEND(): void;
		};
		w.JIN_SCENE["inscription"] = null;
		w.JIN_RESEND();
	});
	await page.waitForTimeout(400);
	expect((await shown()).band).toBe(false);
	await expect(stage.getByTestId("stage-status")).toHaveText("準備完了");
	await band.close();
});
