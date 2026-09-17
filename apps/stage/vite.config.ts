/// <reference types="vitest/config" />
import { defineConfig } from "vite";

/**
 * 鑑賞ページ（docs/spec/v2/stage.md）。`jin editor` が `/stage/` として配るので、
 * パスの前置きを持たない（`base: "./"`）。リポジトリのファイルは 1 つも読まない。
 */
export default defineConfig({
	base: "./",
	build: {
		outDir: "dist",
		emptyOutDir: true,
		sourcemap: false,
	},
	test: {
		environment: "jsdom",
		globals: true,
		include: ["test/**/*.test.ts"],
	},
});
