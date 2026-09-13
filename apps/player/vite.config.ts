/// <reference types="vitest/config" />
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

import { defineConfig, type Plugin } from "vite";

/** リポジトリのルート。`schemas/abilities.json` を dev server から読ませるために要る。 */
const repoRoot = fileURLToPath(new URL("../..", import.meta.url));

/**
 * Wasmoon の wasm 本体。`player.js` は `wasmoon.wasm` を**ページからの相対パス**で読む
 * （runtime.md §9）。`new LuaFactory()` を引数無しで呼ぶと unpkg へ fetch しに行く
 * （probe §A.10）ので、ビルド物に同梱して常に URL を渡す。
 */
const wasmoonWasm = createRequire(import.meta.url).resolve(
	"wasmoon/dist/glue.wasm",
);

function emitWasmoonWasm(): Plugin {
	return {
		name: "jin-emit-wasmoon-wasm",
		apply: "build",
		generateBundle() {
			this.emitFile({
				type: "asset",
				fileName: "wasmoon.wasm",
				source: readFileSync(wasmoonWasm),
			});
		},
	};
}

export default defineConfig({
	// `jin build` の `<out>/` に置かれ、任意の静的サーバで開ける（パスの前置きを持たない）。
	base: "./",
	plugins: [emitWasmoonWasm()],
	// `public/index.html` はそのまま `dist/index.html` になる（vite は書き換えない）。
	// `jin build --single` はこの `index.html` の `<script src="player.js">` を置き換える
	// ので、IIFE 1 本 + 素の HTML という形を崩さない。
	publicDir: "public",
	server: {
		fs: {
			// `schemas/abilities.json` は `apps/player` の外にある**唯一の**入力である。
			allow: [repoRoot],
		},
	},
	build: {
		outDir: "dist",
		emptyOutDir: true,
		sourcemap: false,
		lib: {
			entry: "src/main.ts",
			name: "JinPlayer",
			formats: ["iife"],
			fileName: () => "player.js",
		},
	},
	test: {
		environment: "jsdom",
		globals: true,
		include: ["test/**/*.test.ts"],
	},
});
