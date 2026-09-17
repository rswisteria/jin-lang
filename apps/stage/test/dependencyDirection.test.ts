import { readFileSync } from "node:fs";
import { join } from "node:path";

import { ESLint } from "eslint";
import { describe as group, expect, test } from "vitest";

/** `apps/stage` → リポジトリのファイル / Python パッケージの禁止（stage.md §1）。規則が**落ちる**ことを見る。 */
async function lint(code: string): Promise<readonly ESLint.LintResult[]> {
	const eslint = new ESLint({ cwd: process.cwd() });
	return eslint.lintText(code, { filePath: "src/__probe__.ts" });
}

function messages(results: readonly ESLint.LintResult[]): string {
	return results
		.flatMap((r) => r.messages.map((m) => `${m.ruleId}: ${m.message}`))
		.join("\n");
}

group(
	"apps/stage はリポジトリのファイルと Python パッケージを参照しない",
	() => {
		test.each([
			[
				'import { x } from "../../../packages/jin-render/src/jin_render/v2/layout";',
				"packages 配下",
			],
			[
				'import schema from "../../../schemas/jin-v2.schema.json";',
				"schemas（player と違い例外なし）",
			],
			[
				'import svg from "../../../tests/fixtures/traces/paddle-v2.jsonl?raw";',
				"tests 配下",
			],
			['import { x } from "jin_render";', "パッケージ名"],
			[
				'import prelude from "../../../packages/jin-wasm/src/jin_wasm/prelude.lua?raw";',
				".lua",
			],
		])("%s は落ちる（%s）", async (code) => {
			const found = messages(await lint(code));
			expect(found).toMatch(/no-restricted-imports/);
			expect(found).toMatch(/stage\.md §1/);
		});

		test("three と mediabunny と相対 import は通る", async () => {
			const found = messages(
				await lint(
					'import * as THREE from "three";\nimport { Output } from "mediabunny";\nimport { parseScene } from "./scene";\nexport { THREE, Output, parseScene };',
				),
			);
			expect(found).not.toMatch(/no-restricted-imports/);
		});

		test("規則が設定に書かれている", () => {
			const config = readFileSync(
				join(process.cwd(), "eslint.config.js"),
				"utf8",
			);
			expect(config).toContain("no-restricted-imports");
			expect(config).toContain("**/schemas/**");
			expect(config).toContain("jin_render");
		});
	},
);
