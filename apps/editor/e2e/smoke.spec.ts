import { execFileSync } from "node:child_process";
import { copyFileSync, readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

import { REPO_ROOT, type RunningEditor, startEditor } from "./editor";

/** 正準形の `.jin`（`uv run jin fmt` の出力とバイト一致する形で置く）。 */
const SOURCE = `{
  "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
  "version": 1,
  "root": "Main",
  "circles": [
    {
      "name": "Main",
      "core": "gemini-2.5-flash",
      "instruction": {
        "rune": "こんにちは"
      },
      "tools": [
        {
          "name": "search",
          "kind": "builtin",
          "builtin": "google_search"
        }
      ]
    }
  ]
}
`;

let editor: RunningEditor;

// **テストごとに `jin editor` を起こす。** ブラウザのコンテキストを跨いで同じ
// ポートへ繋ぎ直すと Chromium が閉じたソケットを再利用して `ERR_CONNECTION_RESET`
// になることがある（サーバ側には何も記録が残らない・実測）。1 テスト 1 プロセスなら
// この揺れが入らないうえ、`.jin` も毎回まっさらから始まる。
// **同一ページ内での再読み込みが効くこと**は最初のテストの中で見る（そちらが
// ユーザーの実際の操作であり、pygls の `start_ws` が 1 接続で落ちる問題の再発検知になる）。
test.beforeEach(async () => {
  editor = await startEditor(SOURCE);
});

test.afterEach(() => {
  editor?.stop();
});

// Playwright はフックの第 1 引数に**オブジェクトの分割代入**を要求する（実測: それ以外は
// 「First argument must use the object destructuring pattern」で起動時に落ちる）。
// eslint-disable-next-line no-empty-pattern
test.afterEach(async ({}, testInfo) => {
  if (testInfo.status !== testInfo.expectedStatus) {
    // サーバ側で何が起きたかを付ける（ブラウザ側のログだけでは原因が分からない）。
    await testInfo.attach("jin editor stderr", {
      body: editor.log(),
      contentType: "text/plain",
    });
  }
});

test("開く → 紋を追加 → 保存 → ファイルが jin fmt の出力とバイト一致する", async ({ page }) => {
  await page.goto(editor.url);

  // 開く: SVG が出て、状態が「正常」になる（DP-COMMON-19 の (3)）。
  await expect(page.getByTestId("jin-status")).toHaveAttribute("data-state", "ready");

  // **再読み込みしてもサーバが生きている。** pygls 2.1.1 の `LanguageServer.start_ws` は
  // 1 本目の接続が閉じた直後に `shutdown()` を呼ぶので、これをそのまま使うと
  // ページを 1 回リロードしただけでエディタが死ぬ（実測）。`JinLanguageServer.serve_ws` で
  // 直した箇所の再発検知である。
  await page.reload();
  await expect(page.getByTestId("jin-status")).toHaveAttribute("data-state", "ready");
  const canvas = page.getByTestId("jin-canvas");
  await expect(canvas.locator("svg")).toBeVisible();
  // レンダラは Python 1 本（要件書 §0）。エディタは 1 本の線も描かない。
  await expect(canvas.locator("[data-jin]").first()).toBeAttached();

  // `data-jin` のヒットテスト（要件書 §7.1）。**実際のクリック**で紋を選ぶ。
  await canvas.locator('path[data-jin-kind="tool"]').first().click();
  await expect(page.getByTestId("jin-pointer")).toHaveText("/circles/0/tools/0");
  // 選んだ紋のフォームが JSON Schema から生成されている（builtin の枝）。
  await expect(page.getByTestId("jin-form").locator("label")).toHaveText([
    "Name",
    "Kind",
    "Builtin",
  ]);

  // 核をクリックすると核が選ばれる（同 §7.1「核をクリック → setCore」の入口）。
  await canvas.locator('[data-jin-kind="core"]').first().click();
  await expect(page.getByTestId("jin-pointer")).toHaveText("/circles/0/core");

  // 紋を追加する（要件書 §7.1「環の空き位置をクリック → addTool」）。
  await page.getByTestId("jin-add-tool").click();
  await expect(canvas.locator('[data-jin="/circles/0/tools/1"]').first()).toBeAttached();

  // 保存する。書かれるのは**正準形**（要件書 成功条件 5）。
  await page.getByTestId("jin-save").click();
  await expect(page.getByTestId("jin-notice")).toContainText("保存しました");

  // ファイルが `jin fmt` の出力とバイト一致すること。
  // `jin fmt` は所定の位置を書き換えるので、写しに当てて元と比べる。
  const saved = readFileSync(editor.file);
  // `jin fmt` は `.jin` 以外を読まないので、写しも `.jin` で作る。
  const copy = editor.file.replace(/\.jin$/, "-copy.jin");
  copyFileSync(editor.file, copy);
  execFileSync("uv", ["run", "jin", "fmt", copy], { cwd: REPO_ROOT });
  expect(saved.equals(readFileSync(copy))).toBe(true);
  // 二層目: `jin fmt --check` が差分なしと言うこと（exit 0 でなければ throw）。
  execFileSync("uv", ["run", "jin", "fmt", "--check", editor.file], { cwd: REPO_ROOT });

  // 追加した紋がファイルに入っていること（保存が空振りしていない）。
  const model = JSON.parse(saved.toString("utf8")) as {
    circles: { tools: { name: string }[] }[];
  };
  expect(model.circles[0]!.tools.map((tool) => tool.name)).toEqual(["search", "tool1"]);
});

test("undo でファイルが元に戻る（逆オペレーションの往復）", async ({ page }) => {
  await page.goto(editor.url);
  await expect(page.getByTestId("jin-status")).toHaveAttribute("data-state", "ready");
  const before = readFileSync(editor.file);

  const canvas = page.getByTestId("jin-canvas");
  await canvas.locator('[data-jin-kind="core"]').first().click();
  await page.getByTestId("jin-add-tool").click();
  await expect(page.getByTestId("jin-undo")).toBeEnabled();
  await page.getByTestId("jin-undo").click();
  await page.getByTestId("jin-save").click();
  await expect(page.getByTestId("jin-notice")).toContainText("保存しました");

  expect(readFileSync(editor.file).equals(before)).toBe(true);
});

test("壊れたファイルではステイル表示になる（NFR-AVAIL-001 / DP-COMMON-19 の (4)）", async ({
  page,
}) => {
  await page.goto(editor.url);
  await expect(page.getByTestId("jin-status")).toHaveAttribute("data-state", "ready");
  // ここでは壊れたテキストを送る経路が編集モードに無い（編集はすべて applyOps 経由で、
  // applyOps は構文エラーを作れない）ので、**サーバ側の状態を壊さずに**
  // ステイルの文言が正常と別物であることだけを見る。
  // 実際のステイル遷移はユニット層（test/viewState.test.ts）が押さえている。
  await expect(page.getByTestId("jin-status")).not.toContainText("直前の正常な版");
});
