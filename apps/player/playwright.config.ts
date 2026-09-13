import { defineConfig } from "@playwright/test";

/**
 * パリティ層（設計書 §12 Phase 4 の完了条件「パリティ(Playwright)が通る」）。
 *
 * **実際の `jin build` / `jin run` に繋ぐ**。モックしない。ブラウザで録画した `.jinrec` を
 * `jin run --input` で再生し、トレース行が全行一致することを 1 本で押さえる。
 *
 * `webServer` を使わないのは、配る内容（`jin build` の出力 + `dist/`）をテストが
 * 一時ディレクトリに組み立てるためである。静的サーバはテスト側で起こす（`e2e/harness.ts`）。
 */
export default defineConfig({
	testDir: "./e2e",
	fullyParallel: false,
	workers: 1,
	timeout: 120_000,
	expect: { timeout: 15_000 },
	reporter:
		process.env["CI"] === undefined
			? "list"
			: [["list"], ["html", { open: "never" }]],
	use: { trace: "retain-on-failure" },
	projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
