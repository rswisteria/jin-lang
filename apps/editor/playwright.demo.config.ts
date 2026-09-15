import { defineConfig } from "@playwright/test";

/**
 * README 用のデモ動画の収録（`pnpm demo`）。テストではなく**台本**を実ブラウザで演じ、Playwright の
 * `recordVideo` で `.webm` に落とす（`demo/encode.mjs` が ffmpeg で GIF / MP4 にして `docs/images/` へ書く）。
 *
 * `playwright.config.ts`（スモーク層）とは別の設定にしてあるので、`pnpm e2e` には混ざらない。
 * 実際の `jin editor` プロセスに繋ぐのはスモーク層と同じ（`e2e/editor.ts` を使う）。
 */
export default defineConfig({
	testDir: "./demo",
	outputDir: "./demo-results",
	fullyParallel: false,
	workers: 1,
	timeout: 600_000,
	expect: { timeout: 30_000 },
	reporter: "list",
	retries: 0,
	use: {
		browserName: "chromium",
		viewport: { width: 1600, height: 900 },
		deviceScaleFactor: 1,
		locale: "ja-JP",
		video: { mode: "on", size: { width: 1600, height: 900 } },
		trace: "off",
	},
	projects: [{ name: "chromium" }],
});
