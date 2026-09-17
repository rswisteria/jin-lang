import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";

import { expect, test } from "@playwright/test";

import {
	expectServerGone,
	REPO_ROOT,
	type RunningEditor,
	startEditor,
} from "./editor";

/**
 * 鑑賞モード（docs/spec/v2/stage.md §6・設計書 §4.4）: `jin editor` で paddle を開き、実行パネルで録画を再生して
 * 鑑賞モードへ切り替えると、stage に `jin run --input` と同じ行数が届き、陣が描かれている。
 * 要 `apps/player` と `apps/stage` の `pnpm build`。
 */
const SOURCE = readFileSync(
	join(REPO_ROOT, "examples-v2/paddle/paddle.jin"),
	"utf8",
);
const RECORDING = join(REPO_ROOT, "tests/fixtures/jinrec/paddle-120.jinrec");

let editor: RunningEditor;
test.beforeEach(async () => {
	editor = await startEditor(SOURCE);
});
test.afterEach(async () => {
	const stopped = await editor.stop();
	await expectServerGone(editor.url);
	expect(stopped).toBe(true);
});

test("録画を再生して鑑賞モードへ → 行数が jin run --input と一致し、陣が準備完了", async ({
	page,
}) => {
	await page.goto(editor.url);
	await expect(page.getByTestId("jin-status")).toHaveAttribute(
		"data-state",
		"ready",
	);
	await page.getByTestId("jin-mode-debug").click();
	// プレイヤーが立ち上がって走り出してから止め、録画を読む（v2.spec.ts の再生と同じ順序）。
	const player = page.frameLocator('[data-testid="jin-player"]');
	await expect(player.locator("#status")).toContainText("tick", {
		timeout: 30_000,
	});
	await page.getByTestId("jin-play-pause").click();
	await page.getByTestId("jin-run-file").setInputFiles(RECORDING);
	await expect(page.getByTestId("jin-player-notice")).toContainText(
		"120 tick 再生しました",
	);

	const tracePath = join(dirname(editor.file), "headless-trace.jsonl");
	execFileSync(
		"uv",
		[
			"run",
			"jin",
			"run",
			join(REPO_ROOT, "examples-v2/paddle/paddle.jin"),
			"--input",
			RECORDING,
			"--trace",
			tracePath,
		],
		{ cwd: REPO_ROOT },
	);
	const expected = readFileSync(tracePath, "utf8")
		.split("\n")
		.filter((line) => line.trim() !== "").length;
	await expect(page.getByTestId("jin-trace-name")).toHaveText(
		`録画: paddle-120.jinrec（${String(expected)} 件）`,
	);

	await page.getByTestId("jin-mode-stage").click();
	await expect(page.getByTestId("jin-stage-panel")).toBeVisible();
	const stage = page.frameLocator('[data-testid="jin-stage"]');
	await expect(stage.getByTestId("stage-status")).toHaveText("準備完了", {
		timeout: 60_000,
	});
	await expect(stage.getByTestId("stage-rows")).toHaveText(String(expected));
	await expect(page.getByTestId("jin-stage-status")).toHaveText(
		`トレース ${String(expected)} 行`,
	);
	// 編集モードへ戻ってもプレイヤーの iframe は残る（鑑賞モードが実行パネルを外していない）
	await page.getByTestId("jin-mode-edit").click();
	await expect(page.getByTestId("jin-player")).toBeAttached();
});
