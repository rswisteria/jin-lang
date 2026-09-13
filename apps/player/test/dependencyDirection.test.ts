import { readFileSync } from "node:fs";
import { join } from "node:path";

import { ESLint } from "eslint";
import { describe as group, expect, test } from "vitest";

/**
 * `apps/player` → Python パッケージの禁止（runtime.md §10）。
 *
 * Python 側は import-linter が落とす。ここは TS 側の対応物で、
 * **「規則が存在する」ではなく「規則が落ちる」**ことを確かめる
 * （`apps/editor/test/dependencyDirection.test.ts` と同じ形）。
 */
async function lint(code: string): Promise<readonly ESLint.LintResult[]> {
	const eslint = new ESLint({ cwd: process.cwd() });
	return eslint.lintText(code, { filePath: "src/__probe__.ts" });
}

function messages(results: readonly ESLint.LintResult[]): readonly string[] {
	return results.flatMap((result) =>
		result.messages.map((m) => `${m.ruleId}: ${m.message}`),
	);
}

group("apps/player は Python パッケージを参照しない", () => {
	test.each([
		[
			'import { x } from "../../../packages/jin-wasm/src/jin_wasm/runtime";',
			"packages 配下",
		],
		['import { x } from "jin_wasm";', "パッケージ名そのもの"],
		['import { x } from "jin_core";', "jin_core"],
		[
			'import { x } from "../../../packages/jin-wasm/src/jin_wasm/runtime.py";',
			".py",
		],
		[
			'import prelude from "../../../packages/jin-wasm/src/jin_wasm/prelude.lua?raw";',
			".lua",
		],
	])("%s は落ちる（%s）", async (code) => {
		const found = messages(await lint(code));
		expect(found.join("\n")).toMatch(/no-restricted-imports/);
		expect(found.join("\n")).toMatch(/runtime\.md §10/);
	});

	test("`schemas/abilities.json` は**通る**（唯一の例外・キー名と op 名の一覧）", async () => {
		const found = messages(
			await lint('import abilities from "../../../schemas/abilities.json";'),
		);
		expect(found.join("\n")).not.toMatch(/no-restricted-imports/);
	});

	test("普通の相対 import は通る", async () => {
		const found = messages(await lint('import { JinHost } from "./host";'));
		expect(found.join("\n")).not.toMatch(/no-restricted-imports/);
	});

	test("規則が設定に書かれている（注入テストが素通りしていないことの二層目）", () => {
		const config = readFileSync(
			join(process.cwd(), "eslint.config.js"),
			"utf8",
		);
		expect(config).toContain("no-restricted-imports");
		expect(config).toContain("**/packages/**");
		expect(config).toContain("jin_wasm");
		expect(config).toContain("**/*.lua");
	});
});
