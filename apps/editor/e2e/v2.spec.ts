import { execFileSync } from "node:child_process";
import { copyFileSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type Page } from "@playwright/test";

import {
	expectServerGone,
	REPO_ROOT,
	type RunningEditor,
	startEditor,
} from "./editor";

/**
 * Jin v2 のエディタ（設計書 §12 行 5 の完了条件と §10 のスモーク）:
 *
 * 1. 「v2 ファイルを開く → ステップを足す → 保存 → 正準形一致」
 * 2. 「実行パネルで 10 tick 進めてスクラブ」
 *
 * 台本は `examples-v2/paddle/paddle.jin`（設計書 §2.2 と突合される正典。ここでは写しを編集する）。
 * 実行パネルは `jin editor` が `/play/` として配る `apps/player/dist` を使う（要 `pnpm build`）。
 */
const SOURCE = readFileSync(
	join(REPO_ROOT, "examples-v2/paddle/paddle.jin"),
	"utf8",
);

let editor: RunningEditor;

test.beforeEach(async () => {
	editor = await startEditor(SOURCE);
});

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

async function open(page: Page): Promise<void> {
	await page.goto(editor.url);
	await expect(page.getByTestId("jin-status")).toHaveAttribute(
		"data-state",
		"ready",
	);
	// 版は `jin/model` の応答の `version` で決まる（v2 のツールバーが出る）。
	await expect(page.locator("main.jin-app")).toHaveAttribute(
		"data-version",
		"2",
	);
}

test("v2 ファイルを開く → ステップを足す → 保存 → 正準形一致（§12 行 5）", async ({
	page,
}) => {
	await open(page);
	const canvas = page.getByTestId("jin-canvas");
	await expect(
		canvas.locator('[data-jin-kind="stage"]').first(),
	).toBeAttached();

	// 手順環の小陣（`rite`）をクリック → 手順が選ばれ、フォームは jin-v2.schema.json から出る。
	await canvas
		.locator('text[data-jin="/circles/1/rites/0"]')
		.first()
		.click();
	await expect(page.getByTestId("jin-pointer")).toHaveText(
		"/circles/1/rites/0",
	);
	await expect(page.getByTestId("jin-form").locator("label")).toHaveText([
		"Name",
		"Returns",
	]);

	// ダブルクリック → focus が `陣名/手順名` になり、手順の図（step / step-edge）が出る（ops.md §5）。
	await canvas
		.locator('text[data-jin="/circles/1/rites/0"]')
		.first()
		.dblclick();
	await expect(page.getByTestId("jin-focus-clear")).toContainText("Play/begin");
	await expect(canvas.locator('[data-jin-kind="step"]').first()).toBeAttached();
	await expect(
		canvas.locator('[data-jin="/circles/1/rites/0/steps/2"]'),
	).toHaveCount(0);

	// パレットで種別を選んでステップを足す（`addStep`）。
	await page.getByTestId("jin-step-kind").selectOption("finish");
	await page.getByTestId("jin-add-step").click();
	await expect(
		canvas
			.locator('[data-jin="/circles/1/rites/0/steps/2"][data-jin-kind="step"]')
			.first(),
	).toBeAttached();

	// 保存 → `jin fmt` の出力とバイト一致（要件書 成功条件 5・v2 でも同じ）。
	await page.getByTestId("jin-save").click();
	await expect(page.getByTestId("jin-notice")).toContainText("保存しました");
	const saved = readFileSync(editor.file);
	const copy = editor.file.replace(/\.jin$/, "-copy.jin");
	copyFileSync(editor.file, copy);
	execFileSync("uv", ["run", "jin", "fmt", copy], { cwd: REPO_ROOT });
	expect(saved.equals(readFileSync(copy))).toBe(true);
	execFileSync("uv", ["run", "jin", "fmt", "--check", editor.file], {
		cwd: REPO_ROOT,
	});
	execFileSync("uv", ["run", "jin", "check", editor.file], { cwd: REPO_ROOT });

	const model = JSON.parse(saved.toString("utf8")) as {
		circles: { rites: { steps: { do: string }[] }[] }[];
	};
	expect(model.circles[1]!.rites[0]!.steps.map((step) => step.do)).toEqual([
		"set",
		"cast",
		"finish",
	]);
});

test("式エディタは LSP の completion を候補にする（設計書 §8）", async ({
	page,
}) => {
	await open(page);
	const canvas = page.getByTestId("jin-canvas");
	await canvas
		.locator('text[data-jin="/circles/1/rites/2"]')
		.first()
		.dblclick();
	await expect(page.getByTestId("jin-focus-clear")).toContainText("Play/step");
	// `step` 手順の 1 つ目の `if` の中の `set`（expr: `max(0, paddle - 180 * dt)`）。
	await canvas
		.locator(
			'[data-jin="/circles/1/rites/2/steps/0/then/0"][data-jin-kind="step"]',
		)
		.first()
		.click();
	await expect(page.getByTestId("jin-pointer")).toHaveText(
		"/circles/1/rites/2/steps/0/then/0",
	);
	const expr = page.locator("#jin-field-expr");
	await expect(expr).toHaveValue("max(0, paddle - 180 * dt)");

	// 末尾に ` + pad` と打つと、スコープの識別子（state `paddle`）が候補に出る。
	await expr.click();
	await expr.press("End");
	await expr.pressSequentially(" + pad");
	const candidates = page.getByTestId("jin-expr-candidate");
	await expect(candidates.first()).toContainText("paddle");
	await expr.press("Enter");
	await expect(expr).toHaveValue("max(0, paddle - 180 * dt) + paddle");
	// 欄を離れると `setStep` が飛び、モデルが置き換わる（フォームは新モデルから引き直す）。
	await expr.press("Tab");
	await expect(page.locator("#jin-field-expr")).toHaveValue(
		"max(0, paddle - 180 * dt) + paddle",
	);
	await expect(page.getByTestId("jin-undo")).toBeEnabled();
});

test("実行パネルで 10 tick 進めてスクラブ（§10 のスモーク）", async ({
	page,
}) => {
	await open(page);
	await page.getByTestId("jin-mode-debug").click();
	const panel = page.getByTestId("jin-run-panel");
	await expect(panel).toBeVisible();
	await expect(page.getByTestId("jin-player-missing")).toHaveCount(0);
	await expect(page.getByTestId("jin-jil-error")).toHaveCount(0);

	// プレイヤー（同一オリジンの iframe `/play/`）が JIL を受け取って動き出す。
	const frame = page.frameLocator('[data-testid="jin-player"]');
	await expect(frame.locator("#status")).toContainText("tick", {
		timeout: 30_000,
	});

	// 一時停止 → 最初から（止まったまま tick 0・トレースも空）→ 1 tick × 10。
	await page.getByTestId("jin-play-pause").click();
	await page.getByTestId("jin-play-reboot").click();
	await expect(frame.locator("#status")).toContainText("tick 0");
	for (let i = 0; i < 10; i += 1) {
		await page.getByTestId("jin-play-step").click();
	}
	await expect(frame.locator("#status")).toContainText("tick 10");
	// トレースが親に届き（`jin.trace`）、オーバーレイが図に重なる。
	await expect(page.getByTestId("jin-trace-name")).toContainText("実行パネル");
	const canvas = page.getByTestId("jin-canvas");
	await expect(canvas.locator('[data-jin-fired="1"]').first()).toBeAttached();
	const upto = Number(await page.getByTestId("jin-upto-value").textContent());
	expect(upto).toBeGreaterThan(10);
	// 10 tick ぶんの行（`frame` 行が tick ごとに 1 つ・seq は 0 始まり）。
	await expect(
		page.locator('[data-testid="jin-trace-row"][data-fired="1"]').first(),
	).toBeAttached();

	// スクラブ: `upto` を 3 に戻すと seq 0..3 の点だけになる（seq 0 始まり・layout.md §7.4）。
	const scrub = async (value: number): Promise<void> => {
		await page.getByTestId("jin-upto").fill(String(value));
		await expect(page.getByTestId("jin-upto-value")).toHaveText(String(value));
		await expect(canvas.locator("[data-jin-seq]")).toHaveCount(value + 1);
	};
	await scrub(3);
	const svg = canvas.locator("svg");
	const at3 = await svg.evaluate((node) => node.outerHTML);
	await scrub(7);
	expect(await svg.evaluate((node) => node.outerHTML)).not.toBe(at3);
	await scrub(3);
	expect(await svg.evaluate((node) => node.outerHTML)).toBe(at3);
});
