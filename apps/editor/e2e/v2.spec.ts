import { execFileSync } from "node:child_process";
import { copyFileSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";

import { expect, type Locator, type Page, test } from "@playwright/test";

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
	await canvas.locator('text[data-jin="/circles/1/rites/0"]').first().click();
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

test("式は確定すると正準形に揃い（a+(1) → a + 1）、保存は jin fmt とバイト一致（v2.1・expr.md §8）", async ({
	page,
}) => {
	await open(page);
	const canvas = page.getByTestId("jin-canvas");
	await canvas
		.locator('text[data-jin="/circles/1/rites/0"]')
		.first()
		.dblclick();
	await expect(page.getByTestId("jin-focus-clear")).toContainText("Play/begin");
	// `begin` の 1 つ目の `set`（expr: `0`）。
	await canvas
		.locator('[data-jin="/circles/1/rites/0/steps/0"][data-jin-kind="step"]')
		.first()
		.click();
	await expect(page.getByTestId("jin-pointer")).toHaveText(
		"/circles/1/rites/0/steps/0",
	);
	const expr = page.locator("#jin-field-expr");
	await expect(expr).toHaveValue("0");

	// 空白と冗長な括弧を含む式を **Enter** で確定 → `jin/applyOps` が正準形で返し、欄がそれに揃う
	// （フォーカスは欄に残ったまま）。
	await expr.fill("score+ (1)");
	await expr.press("Enter");
	await expect(expr).toHaveValue("score + 1");
	await expect(expr).toBeFocused();
	// 離れても同じ式をもう一度確定しない（undo は 1 段だけ: 1 回戻すと `0` に戻り、undo が空になる）。
	await expr.press("Tab");
	await expect(page.locator("#jin-field-expr")).toHaveValue("score + 1");
	await page.getByTestId("jin-undo").click();
	await expect(page.locator("#jin-field-expr")).toHaveValue("0");
	await expect(page.getByTestId("jin-undo")).toBeDisabled();
	await page.getByTestId("jin-redo").click();
	await expect(page.locator("#jin-field-expr")).toHaveValue("score + 1");

	// 保存 → `jin fmt` の出力とバイト一致し、ファイルには正準形の式が入る。
	await page.getByTestId("jin-save").click();
	await expect(page.getByTestId("jin-notice")).toContainText("保存しました");
	const saved = readFileSync(editor.file);
	execFileSync("uv", ["run", "jin", "fmt", "--check", editor.file], {
		cwd: REPO_ROOT,
	});
	execFileSync("uv", ["run", "jin", "check", editor.file], { cwd: REPO_ROOT });
	const model = JSON.parse(saved.toString("utf8")) as {
		circles: { rites: { steps: { expr?: string }[] }[] }[];
	};
	expect(model.circles[1]!.rites[0]!.steps[0]!.expr).toBe("score + 1");
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

/** 録画の fixture（`apps/player/e2e/replay.spec.ts` と同じ。`jin run --input` と全行一致する）。 */
const RECORDING = join(REPO_ROOT, "tests/fixtures/jinrec/paddle-120.jinrec");

interface Row {
	readonly seq: number;
	readonly kind: string;
	readonly output: unknown;
}

function headlessTrace(dir: string): readonly Row[] {
	const tracePath = join(dir, "headless-trace.jsonl");
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
	return readFileSync(tracePath, "utf8")
		.split("\n")
		.filter((line) => line.trim() !== "")
		.map((line) => JSON.parse(line) as Row);
}

test(".jinrec を読んでスクラブするとオーバーレイと記憶環の値が動く（§12 行 6）", async ({
	page,
}) => {
	await open(page);
	await page.getByTestId("jin-mode-debug").click();
	const frame = page.frameLocator('[data-testid="jin-player"]');
	await expect(frame.locator("#status")).toContainText("tick", {
		timeout: 30_000,
	});
	await page.getByTestId("jin-play-pause").click();

	// 録画を読む → プレイヤーがヘッダの seed で tick 0 から再生し、止まったまま終わる。
	await page.getByTestId("jin-run-file").setInputFiles(RECORDING);
	await expect(page.getByTestId("jin-player-notice")).toContainText(
		"120 tick 再生しました",
	);
	await expect(page.getByTestId("jin-player-status")).toContainText(
		"tick 120 · seed 7 · 停止",
	);
	// 届いた行数はヘッドレス（`jin run --input`）と同じ。
	const headless = headlessTrace(dirname(editor.file));
	await expect(page.getByTestId("jin-trace-name")).toHaveText(
		`録画: paddle-120.jinrec（${String(headless.length)} 件）`,
	);
	const last = headless.at(-1);
	if (last === undefined) throw new Error("トレースが空");
	await expect(page.getByTestId("jin-upto-value")).toHaveText(String(last.seq));

	// 記憶環の値: 表と図のラベルが同じ値を出す。ArrowLeft を押した録画なので paddle は 140 から動いている。
	const canvas = page.getByTestId("jin-canvas");
	const paddleCell = page.locator(
		'[data-testid="jin-state-value"][data-name="paddle"] td',
	);
	const paddleLabel = canvas.locator('[data-jin-label="/circles/1/state/1"]');
	const atEnd = await paddleCell.textContent();
	expect(atEnd).not.toBeNull();
	expect(atEnd).not.toBe("140");
	await expect(paddleLabel).toHaveText(atEnd ?? "");
	await expect(paddleLabel).toHaveAttribute("data-tone", "value");
	// 最後の set 行の値と一致する（積算の正しさをヘッドレスのトレースで裏取り）。
	const lastPaddle = [...headless]
		.reverse()
		.find(
			(row) =>
				row.kind === "set" && (row as { name?: unknown }).name === "paddle",
		);
	expect(atEnd).toBe(JSON.stringify(lastPaddle?.output));
	// 図のオーバーレイ（発火の強調）はレンダラが描く。
	await expect(canvas.locator('[data-jin-fired="1"]').first()).toBeAttached();

	// スクラブ: upto 0（enter 行だけ）→ 初期値 140 に戻り、点は 1 つ。
	await page.getByTestId("jin-upto").fill("0");
	await expect(page.getByTestId("jin-upto-value")).toHaveText("0");
	await expect(paddleCell).toHaveText("140");
	await expect(paddleLabel).toHaveText("140");
	await expect(canvas.locator("[data-jin-seq]")).toHaveCount(1);

	// スクラブ: 最初の frame 行 → プレイヤーの画面がその tick の表示リストになる（`jin.frame`）。
	const firstFrame = headless.find((row) => row.kind === "frame");
	if (firstFrame === undefined) throw new Error("frame 行が無い");
	await page.getByTestId("jin-upto").fill(String(firstFrame.seq));
	await expect(page.getByTestId("jin-upto-value")).toHaveText(
		String(firstFrame.seq),
	);
	const playerFrame = page
		.frames()
		.find((candidate) => candidate.url().includes("/play/"));
	if (playerFrame === undefined) throw new Error("プレイヤーの frame が無い");
	await expect
		.poll(() =>
			playerFrame.evaluate(() =>
				JSON.stringify(
					(
						window as unknown as {
							__jinPlayer?: { lastOps(): unknown };
						}
					).__jinPlayer?.lastOps(),
				),
			),
		)
		.toBe(JSON.stringify((firstFrame.output as { ops: unknown }).ops));
	// tick 10 あたり（ArrowLeft を押している最中）は 140 より小さい。
	const midFrame = headless.filter((row) => row.kind === "frame")[10];
	if (midFrame === undefined) throw new Error("frame 行が足りない");
	await page.getByTestId("jin-upto").fill(String(midFrame.seq));
	await expect(page.getByTestId("jin-upto-value")).toHaveText(
		String(midFrame.seq),
	);
	await expect
		.poll(async () => Number(await paddleCell.textContent()))
		.toBeLessThan(140);

	// focus を手順の図に変えると（state の四角が無い）値のラベルは消え、戻すと出る。
	await canvas
		.locator('text[data-jin="/circles/1/rites/2"]')
		.first()
		.dblclick();
	await expect(page.getByTestId("jin-focus-clear")).toContainText("Play/step");
	await expect(canvas.locator("[data-jin-label]")).toHaveCount(0);
	await page.getByTestId("jin-focus-clear").click();
	await expect(paddleLabel).toBeVisible();
});

test("偽になった assert はバッジと一覧に出て、スクラブで消える", async ({
	page,
}) => {
	// 台本を assert が偽になる fixture に差し替える（paddle の guard は偽にならない）。
	await editor.stop();
	editor = await startEditor(
		readFileSync(
			join(REPO_ROOT, "tests/fixtures/v2-programs/assert_guard.jin"),
			"utf8",
		),
	);
	await open(page);
	await page.getByTestId("jin-mode-debug").click();
	const frame = page.frameLocator('[data-testid="jin-player"]');
	await expect(frame.locator("#status")).toContainText("tick", {
		timeout: 30_000,
	});
	await page.getByTestId("jin-play-pause").click();
	await page.getByTestId("jin-play-reboot").click();
	await expect(page.getByTestId("jin-player-status")).toContainText("tick 0");
	for (let i = 0; i < 3; i += 1) {
		await page.getByTestId("jin-play-step").click();
	}
	await expect(page.getByTestId("jin-player-status")).toContainText("tick 3");

	// `n < 2` は tick 1 と 2 で偽 → 一覧に 2 件、guard のバッジは「×2」。
	await expect(page.getByTestId("jin-assert")).toHaveCount(2);
	await expect(page.getByTestId("jin-assert").first()).toContainText(
		"n は 2 未満",
	);
	const canvas = page.getByTestId("jin-canvas");
	const badge = canvas.locator(
		'[data-jin-label="/circles/0/boundary/guards/0"]',
	);
	await expect(badge).toHaveAttribute("data-tone", "assert");
	await expect(badge).toHaveText("n は 2 未満 ×2");
	// 記憶環の値も出る（n は 3）。
	await expect(
		page.locator('[data-testid="jin-state-value"][data-name="n"] td'),
	).toHaveText("3");
	await expect(
		canvas.locator('[data-jin-label="/circles/0/state/0"]'),
	).toHaveText("3");

	// スクラブで最初の assert より前に戻すとバッジも一覧も消える。
	const firstSeq = Number(
		await page.getByTestId("jin-assert").first().getAttribute("data-seq"),
	);
	await page.getByTestId("jin-upto").fill(String(firstSeq - 1));
	await expect(page.getByTestId("jin-upto-value")).toHaveText(
		String(firstSeq - 1),
	);
	await expect(badge).toHaveCount(0);
	await expect(page.getByTestId("jin-asserts")).toHaveCount(0);
	await page.getByTestId("jin-upto").fill(String(firstSeq));
	await expect(page.getByTestId("jin-assert")).toHaveCount(1);
	await expect(badge).toHaveText("n は 2 未満");
});

test("実行パネルで録画して書き出した .jinrec は jin run --input で同じ行数になり、読み直せる", async ({
	page,
}) => {
	await open(page);
	await page.getByTestId("jin-mode-debug").click();
	const frame = page.frameLocator('[data-testid="jin-player"]');
	await expect(frame.locator("#status")).toContainText("tick", {
		timeout: 30_000,
	});
	// seed を決めて録画（`boot` し直して tick 0 から走る）。キーを 1 つ入れる。
	await page.getByTestId("jin-play-pause").click();
	await page.getByTestId("jin-seed").fill("11");
	await page.getByTestId("jin-play-record").click();
	await expect(page.getByTestId("jin-player-status")).toContainText("録画中");
	await frame.locator("#stage").click();
	await page.keyboard.down("ArrowLeft");
	await expect
		.poll(async () => {
			const text = await page.getByTestId("jin-player-status").textContent();
			return Number(/tick (\d+)/.exec(text ?? "")?.[1] ?? 0);
		})
		.toBeGreaterThan(20);
	await page.keyboard.up("ArrowLeft");
	// 止めて書き出す → 親がダウンロードとして渡す。
	const downloaded = page.waitForEvent("download");
	await page.getByTestId("jin-play-stop").click();
	const download = await downloaded;
	expect(download.suggestedFilename()).toMatch(/^smoke-seed11-\d+t\.jinrec$/);
	const recPath = join(dirname(editor.file), "recorded.jinrec");
	await download.saveAs(recPath);
	const lines = readFileSync(recPath, "utf8").trim().split("\n");
	const header = JSON.parse(lines[0] ?? "{}") as {
		seed: number;
		ticks: number;
	};
	expect(header.seed).toBe(11);
	expect(lines.slice(1).some((line) => line.includes('"ArrowLeft"'))).toBe(
		true,
	);
	await expect(page.getByTestId("jin-player-status")).toContainText(
		`tick ${String(header.ticks)} · seed 11 · 停止`,
	);
	// 走らせている間に溜めた行数 = ヘッドレスで同じ録画を再生した行数。
	const tracePath = join(dirname(editor.file), "recorded-trace.jsonl");
	execFileSync(
		"uv",
		[
			"run",
			"jin",
			"run",
			editor.file,
			"--input",
			recPath,
			"--trace",
			tracePath,
		],
		{ cwd: REPO_ROOT },
	);
	const rows = readFileSync(tracePath, "utf8")
		.split("\n")
		.filter((line) => line.trim() !== "").length;
	await expect(page.getByTestId("jin-trace-name")).toHaveText(
		`実行パネル（${String(rows)} 件）`,
	);
	// 「この録画を再生」で読み直すと、同じ行数が録画の名前で載る。
	await page.getByTestId("jin-replay-last").click();
	await expect(page.getByTestId("jin-trace-name")).toHaveText(
		`録画: ${download.suggestedFilename()}（${String(rows)} 件）`,
	);
	await expect(page.getByTestId("jin-player-notice")).toContainText(
		`${String(header.ticks)} tick 再生しました`,
	);
});
/** iframe の中のプレイヤー（`window.__jinPlayer`）を叩く（`generation` / `lastResume` は UI に出ないので）。 */
function playerFrame(page: Page) {
	const frame = page.frames().find((f) => f.url().includes("/play/"));
	if (frame === undefined) throw new Error("プレイヤーの iframe がありません");
	return frame;
}

function tickOf(statusText: string | null): number {
	const m = /tick (\d+)/.exec(statusText ?? "");
	if (m === null) throw new Error(`tick が読めません: ${String(statusText)}`);
	return Number(m[1]);
}

test("式を編集しても状態を保って続き（tick / 記憶環の値 / トレースが続く）、外せば最初から（v2.1）", async ({
	page,
}) => {
	await open(page);
	await page.getByTestId("jin-mode-debug").click();
	const frame = page.frameLocator('[data-testid="jin-player"]');
	await expect(frame.locator("#status")).toContainText("tick", {
		timeout: 30_000,
	});
	await expect(page.getByTestId("jin-keep-state")).toBeChecked();
	// 少し走らせてから止める（tick が進んでいないと「保つ」は効かない）。
	await expect
		.poll(async () =>
			tickOf(await page.getByTestId("jin-player-status").textContent()),
		)
		.toBeGreaterThanOrEqual(20);
	await page.getByTestId("jin-play-pause").click();
	await expect(page.getByTestId("jin-player-status")).toContainText("停止");
	const status = await page.getByTestId("jin-player-status").textContent();
	const tick = tickOf(status);
	await expect(page.getByTestId("jin-trace-name")).toContainText("実行パネル");
	const upto = Number(await page.getByTestId("jin-upto-value").textContent());
	const ballCell = page.locator(
		'[data-testid="jin-state-value"][data-name="ball"] td',
	);
	const ball = await ballCell.textContent();
	expect(ball).not.toBeNull();
	const player = playerFrame(page);
	const generation = await player.evaluate(
		() =>
			(
				window as unknown as { __jinPlayer?: { generation(): number } }
			).__jinPlayer?.generation() ?? -1,
	);
	expect(generation).toBeGreaterThan(0);

	// 式を書き換える（Play/step の ArrowLeft の枝）→ `jin/applyOps` → 新しい JIL が `jin.load`（keep）で届く。
	// 式の欄は**編集モード**にしか無い。切り替えても実行パネル（iframe）は外れず、隠れているだけ。
	const editExpr = async (expr: string): Promise<void> => {
		await page.getByTestId("jin-mode-edit").click();
		await expect(page.getByTestId("jin-run-panel")).toBeHidden();
		const canvas = page.getByTestId("jin-canvas");
		await canvas
			.locator('text[data-jin="/circles/1/rites/2"]')
			.first()
			.dblclick();
		await expect(page.getByTestId("jin-focus-clear")).toContainText(
			"Play/step",
		);
		await canvas
			.locator(
				'[data-jin="/circles/1/rites/2/steps/0/then/0"][data-jin-kind="step"]',
			)
			.first()
			.click();
		const field = page.locator("#jin-field-expr");
		await field.fill(expr);
		await field.press("Tab");
		await expect(page.locator("#jin-field-expr")).toHaveValue(expr);
		await page.getByTestId("jin-focus-clear").click();
		await page.getByTestId("jin-mode-debug").click();
		await expect(page.getByTestId("jin-run-panel")).toBeVisible();
	};
	await editExpr("max(0, paddle - 360 * dt)");

	// 止まったまま、tick / 記憶環の値 / トレース（upto）はそのまま。知らせが出る。
	await expect(page.getByTestId("jin-player-notice")).toContainText(
		`状態を保って差し替えました（tick ${String(tick)} から続けます）`,
	);
	await expect(page.getByTestId("jin-player-status")).toContainText(
		`tick ${String(tick)} · seed 7 · 停止`,
	);
	await expect(page.getByTestId("jin-upto-value")).toHaveText(String(upto));
	await expect(ballCell).toHaveText(ball ?? "");
	expect(
		await player.evaluate(
			() =>
				(
					window as unknown as { __jinPlayer?: { generation(): number } }
				).__jinPlayer?.generation() ?? -1,
		),
	).toBe(generation);

	// 1 tick 進めると tick N+1、行は続き（upto が増える）、ball が動く。復元の知らせは「続けた」。
	await page.getByTestId("jin-play-step").click();
	await expect(page.getByTestId("jin-player-status")).toContainText(
		`tick ${String(tick + 1)} · seed 7 · 停止`,
	);
	await expect
		.poll(async () =>
			Number(await page.getByTestId("jin-upto-value").textContent()),
		)
		.toBeGreaterThan(upto);
	await expect(ballCell).not.toHaveText(ball ?? "");
	expect(
		await player.evaluate(
			() =>
				(
					window as unknown as { __jinPlayer?: { lastResume(): unknown } }
				).__jinPlayer?.lastResume() ?? null,
		),
	).toEqual({
		mode: "resumed",
		tick: tick - 1,
		kept: ["Game", "Play", "Result"],
		dropped: [],
	});
	await expect(page.getByTestId("jin-trace-name")).toContainText("実行パネル");

	// 「編集しても状態を保つ」を外して編集すると最初から（世代が進み、知らせは消え、トレースは捨てられる）。
	await page.getByTestId("jin-keep-state").uncheck();
	await editExpr("max(0, paddle - 300 * dt)");
	await expect
		.poll(() =>
			player.evaluate(
				() =>
					(
						window as unknown as { __jinPlayer?: { generation(): number } }
					).__jinPlayer?.generation() ?? -1,
			),
		)
		.toBe(generation + 1);
	await expect(page.getByTestId("jin-player-notice")).toHaveCount(0);
	expect(
		await player.evaluate(
			() =>
				(
					window as unknown as { __jinPlayer?: { lastResume(): unknown } }
				).__jinPlayer?.lastResume() ?? null,
		),
	).toBeNull();
	await page.getByTestId("jin-play-pause").click();
	await expect(page.getByTestId("jin-player-status")).toContainText("停止");
	// 捨てた後に届いた行だけなので、upto は「走った tick 数 × 1 tick の行数」に収まる（前の行が残っていれば超える）。
	const afterTick = tickOf(
		await page.getByTestId("jin-player-status").textContent(),
	);
	const afterUpto = Number(
		await page.getByTestId("jin-upto-value").textContent(),
	);
	expect(afterUpto).toBeLessThan((afterTick + 1) * 30);
});
test("storage: 「最初から」でも記憶は続き（runs が 2）、「記憶を消す」で空になって 1 に戻る（v2.1）", async ({
	page,
}) => {
	// 台本を storage を使う fixture に差し替える（paddle は storage を使わない）。
	await editor.stop();
	editor = await startEditor(
		readFileSync(
			join(REPO_ROOT, "tests/fixtures/v2-programs/storage.jin"),
			"utf8",
		),
	);
	await open(page);
	await page.getByTestId("jin-mode-debug").click();
	const frame = page.frameLocator('[data-testid="jin-player"]');
	await expect(frame.locator("#status")).toContainText("tick", {
		timeout: 30_000,
	});
	await page.getByTestId("jin-play-pause").click();
	const runs = page.locator(
		'[data-testid="jin-state-value"][data-name="runs"] td',
	);
	await expect(runs).toHaveText("1");
	// 「最初から」は boot し直すが、記憶（localStorage）は残るので runs は 2 に増える。
	await page.getByTestId("jin-play-reboot").click();
	await expect(page.getByTestId("jin-player-status")).toContainText("tick 0");
	await page.getByTestId("jin-play-step").click();
	await expect(page.getByTestId("jin-player-status")).toContainText("tick 1");
	await expect(runs).toHaveText("2");
	// 「記憶を消す」は空にして boot し直す（止めたまま）。runs は 1 から。
	await page.getByTestId("jin-forget").click();
	await expect(page.getByTestId("jin-player-notice")).toContainText(
		"記憶を消しました",
	);
	await expect(page.getByTestId("jin-player-status")).toContainText("tick 0");
	await page.getByTestId("jin-play-step").click();
	await expect(runs).toHaveText("1");
	// プレイヤーの記憶（localStorage の写し。鍵は開いた .jin の名前で決まるので推測しない）。
	const stored = await page
		.frames()
		.find((f) => f.url().includes("/play/"))
		?.evaluate(
			() =>
				(
					window as unknown as {
						__jinPlayer?: { storage(): Record<string, string> };
					}
				).__jinPlayer?.storage() ?? null,
		);
	expect(stored).toEqual({ runs: "1", best: "1", label: "run 1" });
});

// ======================================================================================
// 図の操作（ops.md §5・v2.1）: 範囲選択 / 列を跨ぐドラッグ / 陣を結ぶ
// ======================================================================================

interface SavedStep {
	readonly do: string;
	readonly target?: string;
	readonly then?: readonly SavedStep[];
}

interface SavedModel {
	readonly circles: readonly {
		readonly name: string;
		readonly delegate?: readonly string[];
		readonly sigils?: readonly Record<string, unknown>[];
		readonly rites?: readonly {
			readonly name: string;
			readonly steps: readonly SavedStep[];
		}[];
	}[];
}

test("Shift クリックの範囲で抽出・包む（count > 1）", async ({ page }) => {
	await open(page);
	const canvas = page.getByTestId("jin-canvas");
	await canvas
		.locator('text[data-jin="/circles/1/rites/3"]')
		.first()
		.dblclick();
	await expect(page.getByTestId("jin-focus-clear")).toContainText("Play/paint");
	const step = (index: string) =>
		canvas.locator(
			`[data-jin="/circles/1/rites/3/steps/${index}"][data-jin-kind="step"]`,
		);

	// 0 をクリック → 1 を Shift クリックで 2 つの範囲。範囲にはフォームを出さず、全部をハイライトする。
	await clickOn(page, step("0"));
	await clickOn(page, step("1"), { shift: true });
	await expect(page.getByTestId("jin-range")).toContainText("2 ステップ");
	await expect(
		step("1").and(canvas.locator("[data-jin-selected]")),
	).not.toHaveCount(0);
	await expect(page.getByTestId("jin-extract-step")).toHaveText(
		"2 ステップを手順に抽出",
	);
	await page.getByTestId("jin-extract-step").click();
	// 抽出の後は、範囲と置き換わった cast（範囲の先頭）を選ぶ。
	await expect(page.getByTestId("jin-pointer")).toHaveText(
		"/circles/1/rites/3/steps/0",
	);
	await expect(step("4")).toHaveCount(0);

	await clickOn(page, step("1"));
	await clickOn(page, step("2"), { shift: true });
	await expect(page.getByTestId("jin-range")).toContainText("2 ステップ");
	await page.getByTestId("jin-wrap-step").click();
	await expect(page.getByTestId("jin-pointer")).toHaveText(
		"/circles/1/rites/3/steps/1",
	);
	await expect(step("1/then/1")).not.toHaveCount(0);

	const model = await saveAndCheck(page);
	const play = model.circles[1]!;
	const paint = play.rites![3]!.steps;
	expect(paint.map((s) => s.do)).toEqual(["cast", "if", "cast"]);
	expect(paint[0]!.target).toBe("rite1");
	expect(paint[1]!.then!.map((s) => s.target)).toEqual([
		"canvas.rect",
		"canvas.circle",
	]);
	expect(play.rites![4]!.name).toBe("rite1");
	expect(play.rites![4]!.steps.map((s) => s.target)).toEqual([
		"canvas.clear",
		"canvas.ink",
	]);
});

test("列を跨ぐドラッグは removeStep + addStep の 1 回の合成", async ({
	page,
}) => {
	await open(page);
	const canvas = page.getByTestId("jin-canvas");
	await canvas
		.locator('text[data-jin="/circles/1/rites/2"]')
		.first()
		.dblclick();
	await expect(page.getByTestId("jin-focus-clear")).toContainText("Play/step");
	const step = (path: string) =>
		canvas.locator(
			`[data-jin="/circles/1/rites/2/steps/${path}"][data-jin-kind="step"]`,
		);

	// steps/2（ball.x）を steps/4 の then の先頭へ。前の兄弟が消えるので、移った先は steps/3/then/0。
	await dragOnto(page, step("2"), step("4/then/0"));
	await expect(page.getByTestId("jin-pointer")).toHaveText(
		"/circles/1/rites/2/steps/3/then/0",
	);
	await expect(step("8")).toHaveCount(0);
	// 1 回の applyOps なので、元に戻すも 1 回（途中の「消えただけ」の状態を通らない）。
	await page.getByTestId("jin-undo").click();
	await expect(step("8")).not.toHaveCount(0);
	await expect(step("4/then/1")).toHaveCount(0);
	await page.getByTestId("jin-redo").click();
	await expect(step("8")).toHaveCount(0);

	const model = await saveAndCheck(page);
	const steps = model.circles[1]!.rites![2]!.steps;
	expect(steps).toHaveLength(8);
	expect(steps[2]!.target).toBe("ball.y");
	expect(steps[3]!.then!.map((s) => s.target)).toEqual(["ball.x", "ball.vx"]);
});

test("陣を陣 / 手順に落として結ぶ（addDelegate / addSigil summon）", async ({
	page,
}) => {
	// 根の図は流れの陣（Game）の中に Play と Result を並べて描くので、既定の画面ではスクロールしないと
	// 両方が同時に入らない。ドラッグは押した点と離す点が同時に画面に要る。
	await page.setViewportSize({ width: 1920, height: 1600 });
	await open(page);
	const canvas = page.getByTestId("jin-canvas");
	const play = canvas.locator('text[data-jin="/circles/1/core"]');
	const result = canvas.locator('text[data-jin="/circles/2/core"]');

	// 陣（核）を陣に落とす → 落とした側（Play）の delegate に足し、足した委譲を選ぶ。
	await dragOnto(page, play, result);
	await expect(page.getByTestId("jin-pointer")).toHaveText(
		"/circles/1/delegate/0",
	);
	// 同じ委譲はもう一度送らない（サーバは重複を断らず、同じ名前が 2 つ並ぶ）。
	await dragOnto(page, play, result);
	await expect(page.getByTestId("jin-notice")).toContainText(
		"Play は既に Result へ委譲しています",
	);
	// 陣を手順の小陣に落とす → summon の道具（名前は手順名）。
	await dragOnto(
		page,
		play,
		canvas.locator('text[data-jin="/circles/2/rites/1"]'),
	);
	await expect(page.getByTestId("jin-pointer")).toHaveText(
		"/circles/1/sigils/3",
	);

	const model = await saveAndCheck(page);
	const circle = model.circles[1]!;
	expect(circle.delegate).toEqual(["Result"]);
	expect(circle.sigils!.at(-1)).toEqual({
		name: "menu",
		kind: "summon",
		circle: "Result",
		rite: "menu",
	});
});

/**
 * 描かれた要素の上で、**その要素自身に当たる**画面上の点（ビューポートの CSS px）。
 *
 * 手順の図のステップは弧（`path`）で描かれ、外接矩形の中心が線の上に無い。レイアウトを知らずに
 * 当てるため、外接矩形の格子点と線の長さに沿った点を順に試し、`elementFromPoint` が
 * locator の要素のどれかを返す最初の点を使う。
 */
async function pointOn(
	target: Locator,
	scroll = true,
): Promise<{ x: number; y: number }> {
	// 実行パネルのプレイヤーが走っている間、図は 1 秒ごとに描き直される（`LIVE_REFRESH_MS`）。
	// 掴んだ要素がスクロールの途中で差し替わることがあるので、点が取れるまで取り直す
	// （座標は描き直しの前後で変わらない）。
	let found: { x: number; y: number } | null = null;
	await expect(async () => {
		found = await pointOnce(target, scroll);
		expect(found, "要素に当たる点が見つからない").not.toBeNull();
	}).toPass();
	return found!;
}

async function pointOnce(
	target: Locator,
	scroll: boolean,
): Promise<{ x: number; y: number } | null> {
	await expect(target.first()).toBeAttached();
	if (scroll) await target.first().scrollIntoViewIfNeeded();
	return target.evaluateAll((elements) => {
		const candidates: { x: number; y: number }[] = [];
		for (const element of elements) {
			const box = element.getBoundingClientRect();
			for (const fx of [0.5, 0.25, 0.75]) {
				for (const fy of [0.5, 0.25, 0.75]) {
					candidates.push({
						x: box.left + box.width * fx,
						y: box.top + box.height * fy,
					});
				}
			}
			if (element instanceof SVGGeometryElement) {
				const matrix = element.getScreenCTM();
				const length = element.getTotalLength();
				for (let k = 0; matrix !== null && k <= 20; k += 1) {
					const at = element
						.getPointAtLength((length * k) / 20)
						.matrixTransform(matrix);
					candidates.push({ x: at.x, y: at.y });
				}
			}
		}
		return (
			candidates.find((candidate) => {
				const found = document.elementFromPoint(candidate.x, candidate.y);
				return found !== null && (elements as Element[]).includes(found);
			}) ?? null
		);
	});
}

async function clickOn(
	page: Page,
	target: Locator,
	options?: { readonly shift?: boolean },
): Promise<void> {
	const point = await pointOn(target);
	if (options?.shift === true) await page.keyboard.down("Shift");
	await page.mouse.click(point.x, point.y);
	if (options?.shift === true) await page.keyboard.up("Shift");
}

/** 押して、動かして、離す（`SvgCanvas` の onPointerDown / onPointerUp を通す）。 */
async function dragOnto(page: Page, from: Locator, to: Locator): Promise<void> {
	// 先に両方を画面に入れてから、**スクロールせずに**点を取り直す（落とし先へのスクロールで
	// 起点の座標がずれると、押す位置が要素を外れてドラッグが始まらない）。
	await pointOn(from);
	await pointOn(to);
	const start = await pointOn(from, false);
	const end = await pointOn(to, false);
	await page.mouse.move(start.x, start.y);
	await page.mouse.down();
	await page.mouse.move(end.x, end.y, { steps: 5 });
	await page.mouse.up();
}

/** 保存 → `jin fmt` の出力とバイト一致 → `jin check` が通る。保存したモデルを返す。 */
async function saveAndCheck(page: Page): Promise<SavedModel> {
	await page.getByTestId("jin-save").click();
	await expect(page.getByTestId("jin-notice")).toContainText("保存しました");
	const saved = readFileSync(editor.file);
	const copy = editor.file.replace(/\.jin$/, "-copy.jin");
	copyFileSync(editor.file, copy);
	execFileSync("uv", ["run", "jin", "fmt", copy], { cwd: REPO_ROOT });
	expect(saved.equals(readFileSync(copy))).toBe(true);
	execFileSync("uv", ["run", "jin", "check", editor.file], { cwd: REPO_ROOT });
	return JSON.parse(saved.toString("utf8")) as SavedModel;
}
