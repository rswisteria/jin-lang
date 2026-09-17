import { defineConfig } from "@playwright/test";

/**
 * 鑑賞ページの e2e（stage.md §5）。ビルド済みの `dist/` と、エディタの代わりに
 * postMessage を送る親ページを一時ディレクトリに組み立てて開く（`e2e/harness.ts`）。
 * WebGL と書き出しは GPU なしでは遅いので、1 本の上限を長く取る。
 */
export default defineConfig({
	testDir: "./e2e",
	fullyParallel: false,
	workers: 1,
	timeout: 180_000,
	expect: { timeout: 60_000 },
	reporter:
		process.env["CI"] === undefined
			? "list"
			: [["list"], ["html", { open: "never" }]],
	use: { trace: "retain-on-failure" },
	projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
