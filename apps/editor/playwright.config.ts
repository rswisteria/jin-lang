import { defineConfig } from "@playwright/test";

/**
 * スモーク層（DP-COMMON-20 案 B の 2 層目）。
 *
 * **実際の `jin editor` プロセスに繋ぐ**。モックしない。
 * ユニット層（`pnpm test`）がロジックの分岐を見るのに対し、ここは
 * 「静的配信 → ws 接続 → トークン → jin/open → applyOps → jin/save → ファイル」の
 * 通しを 1 本で押さえる（要件書 §9 の必須 1 本）。
 *
 * `webServer` を使わないのは、URL に**起動ごとに変わるトークン**が入るためである
 * （固定 URL を書けない）。プロセスの起動と URL の読み取りはテスト側で行う。
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: process.env["CI"] === undefined ? "list" : [["list"], ["html", { open: "never" }]],
  use: { trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
