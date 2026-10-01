import { expect, test } from "@playwright/test";

import { serveHarness } from "./harness";

/**
 * 音声のコーデックの可否の実測（delivery/…/stage-api-probe.md §G）。Playwright 同梱の Chromium で
 * `aac` / `opus`（48kHz・モノラル）をエンコードできるかを読み、出力に残す。値は環境で変わりうるので
 * 真偽値であることだけを確かめ、書き出しの読み戻しは stage.spec.ts の音の e2e が見る。
 */
test("音声のコーデックの可否（aac / opus）", async ({ page }) => {
	const harness = await serveHarness();
	await page.goto(harness.url);
	const stage = page.frameLocator("#stage");
	await expect(stage.getByTestId("stage-status")).toHaveText("準備完了");
	const frame = page.frames().find((f) => f.url().includes("/stage/"));
	if (frame === undefined) throw new Error("stage の iframe が無い");
	const codecs = await frame.evaluate(() =>
		(
			window as unknown as {
				__jinStage: { audioCodecs(): Promise<{ aac: boolean; opus: boolean }> };
			}
		).__jinStage.audioCodecs(),
	);
	console.log(
		`audio codecs: aac=${String(codecs.aac)} opus=${String(codecs.opus)}`,
	);
	expect(typeof codecs.aac).toBe("boolean");
	expect(typeof codecs.opus).toBe("boolean");
	await harness.close();
});
