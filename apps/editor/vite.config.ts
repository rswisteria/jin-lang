/// <reference types="vitest/config" />
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

/** リポジトリのルート。`schemas/jin.schema.json` を dev server から読ませるために要る。 */
const repoRoot = fileURLToPath(new URL("../..", import.meta.url));

export default defineConfig({
  // `jin editor` は生成物を静的配信するだけで、パスの前置きを持たない。
  base: "./",
  plugins: [react()],
  server: {
    fs: {
      // `schemas/jin.schema.json` は `apps/editor` の外にある**唯一の**入力である。
      // コピーを置かないための許可であって、リポジトリ全体を配るためではない。
      allow: [repoRoot],
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    // `jin editor` が配る 1 ファイル群。ハッシュ付きの既定のままにする。
    sourcemap: false,
  },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["test/**/*.test.ts", "test/**/*.test.tsx"],
    setupFiles: ["./test/setup.ts"],
  },
});
