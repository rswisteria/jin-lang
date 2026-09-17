// @ts-check
import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";

/**
 * `apps/stage` は **Python パッケージもリポジトリのファイルも参照しない**
 * （docs/spec/v2/stage.md §1・設計書 §1.1）。SVG・名前の表・トレースはエディタから postMessage で受け取る。
 * **この配列が契約の実体**で、`test/dependencyDirection.test.ts` が「実際に落ちる」ことを確かめる。
 * `apps/player` と違い、`schemas/` の例外も無い。
 */
export const FORBIDDEN_IMPORT_PATTERNS = [
	{
		group: [
			"**/packages/**",
			"**/schemas/**",
			"**/examples-v2/**",
			"**/tests/**",
		],
		message:
			"apps/stage はリポジトリのファイルを読みません（stage.md §1）。エディタから stage.scene / stage.trace で受け取ってください。",
	},
	{
		group: [
			"jin_core",
			"jin_adk",
			"jin_render",
			"jin_lsp",
			"jin_cli",
			"jin_wasm",
			"jin_*/**",
		],
		message: "apps/stage は Python パッケージを参照しません（stage.md §1）。",
	},
	{
		group: ["**/*.py", "**/*.lua"],
		message:
			"apps/stage から Python のソースやプレリュードを読み込まないでください（stage.md §1）。",
	},
];

export default tseslint.config(
	{
		ignores: [
			"dist/**",
			"node_modules/**",
			"test-results/**",
			"playwright-report/**",
		],
	},
	js.configs.recommended,
	...tseslint.configs.recommended,
	{
		languageOptions: {
			globals: { ...globals.browser, ...globals.node },
		},
		rules: {
			"no-restricted-imports": [
				"error",
				{ patterns: FORBIDDEN_IMPORT_PATTERNS },
			],
			"@typescript-eslint/no-unused-vars": [
				"error",
				{ argsIgnorePattern: "^_" },
			],
		},
	},
);
