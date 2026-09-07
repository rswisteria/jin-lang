import { readFileSync } from "node:fs";
import { join } from "node:path";

import { ESLint } from "eslint";
import { describe as group, expect, test } from "vitest";

/**
 * DP-COMMON-11 の 2 本目（`apps/editor` → Python パッケージの禁止）。
 *
 * Python 側は import-linter が落とす。ここは TS 側の対応物で、
 * **「規則が存在する」ではなく「規則が落ちる」**ことを確かめる
 * （Phase 0+1 で偽 green を踏んだ規律。`tests/contract/test_dependency_direction.py` の
 * 注入テストと同じ形）。
 */
async function lint(code: string): Promise<readonly ESLint.LintResult[]> {
  const eslint = new ESLint({ cwd: process.cwd() });
  return eslint.lintText(code, { filePath: "src/__probe__.ts" });
}

function messages(results: readonly ESLint.LintResult[]): readonly string[] {
  return results.flatMap((result) => result.messages.map((m) => `${m.ruleId}: ${m.message}`));
}

group("apps/editor は Python パッケージを参照しない", () => {
  test.each([
    ['import { x } from "../../../packages/jin-core/src/jin_core/model";', "packages 配下"],
    ['import { x } from "jin_core";', "パッケージ名そのもの"],
    ['import { x } from "jin_lsp";', "jin_lsp"],
    ['import { x } from "../../../packages/jin-render/src/jin_render/svg.py";', ".py"],
  ])("%s は落ちる（%s）", async (code) => {
    const found = messages(await lint(code));
    expect(found.join("\n")).toMatch(/no-restricted-imports/);
    expect(found.join("\n")).toMatch(/DP-COMMON-11/);
  });

  test("`schemas/jin.schema.json` は**通る**（唯一の例外・フォームを手書きしないため）", async () => {
    const found = messages(await lint('import schema from "../../../schemas/jin.schema.json";'));
    expect(found.join("\n")).not.toMatch(/no-restricted-imports/);
  });

  test("普通の相対 import は通る", async () => {
    const found = messages(await lint('import { App } from "./App";'));
    expect(found.join("\n")).not.toMatch(/no-restricted-imports/);
  });

  test("規則が設定に書かれている（注入テストが素通りしていないことの二層目）", () => {
    // 設定を **import せずテキストで**読む。`eslint.config.js` は型を持たないので、
    // import すると `any` になり型の穴ができる。上の注入テストが本体で、ここは
    // 「規則ごと消えたのに注入テストだけ緑」が起きないための重ね置きである。
    const config = readFileSync(join(process.cwd(), "eslint.config.js"), "utf8");
    expect(config).toContain("no-restricted-imports");
    expect(config).toContain("**/packages/**");
    expect(config).toContain("jin_core");
    expect(config).toContain("jin_lsp");
  });
});
