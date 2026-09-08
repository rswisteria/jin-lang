import { expect, test, type Page } from "@playwright/test";

import { expectServerGone, type RunningEditor, startEditor } from "./editor";

/**
 * エディタからの実行（Issue #34 / 要件書 §7.2 のライブ実行）。
 *
 * **`ref` も `builtin` も持たない陣**を使う。`ref` は実体がリポジトリに無いので
 * `PYTHONPATH=tests/fixtures/stubs` が要り、`google_search` は Gemini 以外のモデルを
 * 拒んで `--model fake` が `ValueError` で落ちる（CLAUDE.md）。ここで見たいのは
 * 「実行してオーバーレイが出る」ことだけなので、余計な依存を持ち込まない。
 */
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
      }
    }
  ]
}
`;

let editor: RunningEditor;

test.beforeEach(async () => {
	editor = await startEditor(SOURCE);
});

// **取り残しをここで赤くする**（Issue #32）。実行の子プロセスが残る形もここで出る。
test.afterEach(async () => {
	const stopped = await editor?.stop();
	await expectServerGone(editor.url);
	expect(stopped).toBe(true);
});

// eslint-disable-next-line no-empty-pattern
test.afterEach(async ({}, testInfo) => {
	if (testInfo.status !== testInfo.expectedStatus) {
		await testInfo.attach("jin editor stderr", {
			body: editor.log(),
			contentType: "text/plain",
		});
	}
});

/** デバッグモードに入る。編集モードから切り替えるところは `debug.spec.ts` と同じ。 */
async function openDebug(page: Page): Promise<void> {
	await page.goto(editor.url);
	// **接続が済むまで待つ**（`debug.spec.ts` と同じ）。待たずに押すと、
	// まだ描かれていないパネルを掴んで遅い環境で揺れる。
	await expect(page.getByTestId("jin-status")).toHaveAttribute(
		"data-state",
		"ready",
	);
	await page.getByTestId("jin-mode-debug").click();
	await expect(page.getByTestId("jin-debug")).toBeVisible();
}

test("エディタから実行するとオーバーレイが出る", async ({ page }) => {
	await openDebug(page);

	await page.getByTestId("jin-run-prompt").fill("go");
	await page.getByTestId("jin-run").click();

	// `jin run` は最後に「N イベント（session: …）」を stderr に出す。
	await expect(page.getByTestId("jin-run-summary")).toContainText("イベント", {
		timeout: 120_000,
	});
	await expect(page.getByTestId("jin-run-error")).toHaveCount(0);

	// **オーバーレイが実際に出ていること。** `data-jin-fired` を書くのは `jin_render` 1 本で、
	// エディタは 1 つも書かない（`tests/contract/test_editor_contract.py`）。
	// 見方は `debug.spec.ts` と同じ形に揃える（`toHaveCount` で数える）。
	// この陣は `--model fake` で 1 イベント（`/circles/0/core` の `final`）を出す（実測）。
	await expect(
		page.getByTestId("jin-canvas").locator('[data-jin-fired="1"]'),
	).toHaveCount(1);

	// 行の一覧にも届いていること。
	await expect(page.getByTestId("jin-trace-row")).toHaveCount(1);
});

test("実行中は二度押しできない", async ({ page }) => {
	await openDebug(page);
	await page.getByTestId("jin-run-prompt").fill("go");
	await page.getByTestId("jin-run").click();

	// サーバも 409 で断るが、押せる見た目にしない。
	await expect(page.getByTestId("jin-run")).toBeDisabled();

	// この回は実行中に `afterEach` の `stop()` が走ることがある。走っている子ごと
	// 終わること（`expectServerGone` がポートの解放を見る）が Issue #32 と同じ規律の検査になる。
});
