// @ts-check
import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";

/**
 * `apps/player` は **Python パッケージを参照しない**（runtime.md §10 / 設計書 §1.2）。
 *
 * Python 側は import-linter が落とす。TS 側に対応物が無いと契約は片肺になるので、
 * ここで静的に落とす。**この配列が契約の実体**であり、
 * `test/dependencyDirection.test.ts` が「禁止された import を食わせると実際に落ちる」ことを
 * 確かめる（`apps/editor` と同じ規律）。
 *
 * 例外は `schemas/abilities.json` ただ 1 つである（キー名と op 名の一覧。正本は
 * `jin_core.v2.abilities` で、生成してコミットされた成果物を直接読む。コピーを置かない）。
 */
export const FORBIDDEN_IMPORT_PATTERNS = [
	{
		group: ["**/packages/**"],
		message:
			"apps/player は Python パッケージを参照しません（runtime.md §10）。" +
			"JIL と manifest は jin build の出力（game.lua / game.manifest.json）から受け取ってください。",
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
		message:
			"apps/player は Python パッケージを参照しません（runtime.md §10）。",
	},
	{
		group: ["**/*.py", "**/*.lua"],
		message:
			"apps/player から Python のソースやプレリュードを読み込まないでください（runtime.md §10）。",
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
