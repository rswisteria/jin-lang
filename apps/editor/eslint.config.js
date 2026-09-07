// @ts-check
import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";

/**
 * `apps/editor` は **Python パッケージを参照しない**（要件書 §1.2 / DP-COMMON-11 の 2 本目）。
 *
 * Python 側は import-linter が落とす。TS 側に対応物が無いと契約は片肺になるので、
 * ここで静的に落とす。**この配列が契約の実体**であり、
 * `test/dependency-direction.test.ts` が「禁止された import を食わせると実際に落ちる」ことを
 * 確かめる（規則が存在することと、規則が落ちることは別 — Phase 0+1 で偽 green を踏んだ規律）。
 *
 * 例外は `schemas/jin.schema.json` ただ 1 つである。これは Python パッケージではなく
 * Pydantic から生成してリポジトリにコミットされた成果物で、プロパティパネルのフォームを
 * **手書きしない**ために読む（要件書 §7.1）。コピーを置くとドリフトするので直接読む。
 */
export const FORBIDDEN_IMPORT_PATTERNS = [
  {
    group: ["**/packages/**"],
    message:
      "apps/editor は Python パッケージを参照しません（要件書 §1.2 / DP-COMMON-11）。" +
      "モデルも SVG も jin lsp --ws の応答から受け取ってください。",
  },
  {
    group: ["jin_core", "jin_adk", "jin_render", "jin_lsp", "jin_cli", "jin_*/**"],
    message:
      "apps/editor は Python パッケージを参照しません（要件書 §1.2 / DP-COMMON-11）。",
  },
  {
    group: ["**/*.py"],
    message: "apps/editor から Python のソースを読み込まないでください（DP-COMMON-11）。",
  },
];

export default tseslint.config(
  { ignores: ["dist/**", "node_modules/**", "test-results/**", "playwright-report/**"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
    },
    rules: {
      "no-restricted-imports": ["error", { patterns: FORBIDDEN_IMPORT_PATTERNS }],
      // 5 状態の網羅（DP-COMMON-19）は tsc の `switch` 網羅性検査で落とす。
      // `default` で握り潰すと網羅性が消えるので、`default` を書かない形を守る。
      "@typescript-eslint/switch-exhaustiveness-check": "off",
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
    },
  },
);
