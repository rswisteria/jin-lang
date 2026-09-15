import { readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, type Locator, type Page, test } from "@playwright/test";

import {
	expectServerGone,
	REPO_ROOT,
	type RunningEditor,
	startEditor,
} from "../e2e/editor";

/**
 * README の動画の台本（`pnpm demo`）: Jin v2 のサンプル（paddle）をビジュアルエディタで開き、
 * 手順の式を書き換えて保存し、実行パネルで遊んで、止めてトレースをスクラブする。
 *
 * テストではない（何かを固定する意図は無い）が、`expect` で各段が実際に起きたことは確かめる
 * （動かないまま動画だけ出ると嘘の README になる）。間の `pause` は見せるための間で、収録の外では意味が無い。
 * 画面には擬似カーソルと字幕を差し込む（Playwright の動画にはカーソルが写らない）。
 */
const SOURCE = readFileSync(
	join(REPO_ROOT, "examples-v2/paddle/paddle.jin"),
	"utf8",
);

let editor: RunningEditor;

test.beforeEach(async ({ context }) => {
	editor = await startEditor(SOURCE, "paddle.jin");
	// 擬似カーソル（全フレームに入れる。iframe のプレイヤーにも効く）。
	await context.addInitScript(() => {
		window.addEventListener("DOMContentLoaded", () => {
			const cursor = document.createElement("div");
			cursor.id = "jin-demo-cursor";
			cursor.style.cssText =
				"position:fixed;left:-100px;top:-100px;width:22px;height:22px;pointer-events:none;z-index:2147483647;" +
				"transform:translate(-4px,-2px);";
			cursor.innerHTML =
				'<svg width="22" height="22" viewBox="0 0 22 22"><path d="M3 2 L3 18 L7.5 13.5 L11 20 L13.5 19 L10 12.5 L16 12.5 Z" ' +
				'fill="#fff" stroke="#000" stroke-width="1.5" stroke-linejoin="round"/></svg>';
			document.body.appendChild(cursor);
			window.addEventListener(
				"mousemove",
				(ev) => {
					cursor.style.left = `${String(ev.clientX)}px`;
					cursor.style.top = `${String(ev.clientY)}px`;
				},
				true,
			);
			window.addEventListener(
				"mousedown",
				() => {
					cursor.style.transform = "translate(-4px,-2px) scale(0.85)";
				},
				true,
			);
			window.addEventListener(
				"mouseup",
				() => {
					cursor.style.transform = "translate(-4px,-2px)";
				},
				true,
			);
		});
	});
});

test.afterEach(async () => {
	const stopped = await editor?.stop();
	await expectServerGone(editor.url);
	expect(stopped).toBe(true);
});

const pause = (page: Page, ms: number): Promise<void> =>
	page.waitForTimeout(ms);

/** 画面の下に字幕を出す（`docs/images/` の動画の各段の説明）。 */
async function caption(page: Page, text: string): Promise<void> {
	await page.evaluate((message) => {
		let bar = document.getElementById("jin-demo-caption");
		if (bar === null) {
			bar = document.createElement("div");
			bar.id = "jin-demo-caption";
			bar.style.cssText =
				"position:fixed;left:24px;bottom:18px;max-width:54%;" +
				"padding:10px 18px;border-radius:8px;background:rgba(20,20,24,0.88);color:#fff;" +
				"font:600 20px/1.4 system-ui,sans-serif;letter-spacing:0.02em;z-index:2147483646;" +
				"box-shadow:0 4px 18px rgba(0,0,0,0.35);pointer-events:none;white-space:nowrap;";
			document.body.appendChild(bar);
		}
		bar.textContent = message;
	}, text);
}

/** 要素の中心へ滑らかに動いてからクリック（クリックだけだとカーソルが跳ぶ）。 */
async function glideTo(page: Page, target: Locator): Promise<void> {
	const box = await target.boundingBox();
	if (box === null) throw new Error("要素が見えない");
	await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, {
		steps: 24,
	});
}

async function glideClick(page: Page, target: Locator): Promise<void> {
	await glideTo(page, target);
	await pause(page, 250);
	await target.click();
}

async function open(page: Page): Promise<void> {
	await page.goto(editor.url);
	// 見せるための調整（製品の CSS は変えない）: 右のパネルを広げ、プレイヤーの iframe を高くして、
	// 320×180 の stage が 2 倍（640×360）で描かれるようにする（プレイヤーの fitCanvas は整数倍）。
	await page.addStyleTag({
		content:
			".jin-side { width: 44rem !important; } .jin-player { height: 36rem !important; }",
	});
	await expect(page.getByTestId("jin-status")).toHaveAttribute(
		"data-state",
		"ready",
	);
	await expect(page.locator("main.jin-app")).toHaveAttribute(
		"data-version",
		"2",
	);
}

test("paddle をエディタで直して、実行パネルで遊び、トレースを追う", async ({
	page,
}) => {
	await open(page);
	const canvas = page.getByTestId("jin-canvas");
	await expect(
		canvas.locator('[data-jin-kind="stage"]').first(),
	).toBeAttached();
	await caption(
		page,
		"Jin v2 のサンプル paddle.jin をビジュアルエディタで開く",
	);
	await page.mouse.move(640, 400);
	await pause(page, 2200);

	// 1. 手順 Play/step を選び、ダブルクリックで手順の図（ステップ）へ。
	await caption(
		page,
		"陣 Play の手順 step をダブルクリックして、ステップの図を開く",
	);
	const stepRite = canvas
		.locator('text[data-jin="/circles/1/rites/2"]')
		.first();
	await glideClick(page, stepRite);
	await expect(page.getByTestId("jin-pointer")).toHaveText(
		"/circles/1/rites/2",
	);
	await pause(page, 900);
	await stepRite.dblclick();
	await expect(page.getByTestId("jin-focus-clear")).toContainText("Play/step");
	await expect(canvas.locator('[data-jin-kind="step"]').first()).toBeAttached();
	await pause(page, 1600);

	// 2. ArrowLeft の枝の set を選び、式を書き換える（パドルの速さを 2 倍に）。
	await caption(
		page,
		"ステップを選んで、式エディタでパドルの速さを 180 → 360 に変える",
	);
	const setStep = canvas
		.locator(
			'[data-jin="/circles/1/rites/2/steps/0/then/0"][data-jin-kind="step"]',
		)
		.first();
	await glideClick(page, setStep);
	const field = page.locator("#jin-field-expr");
	await expect(field).toHaveValue("max(0, paddle - 180 * dt)");
	await glideClick(page, field);
	await pause(page, 500);
	await field.fill("");
	await field.pressSequentially("max(0, paddle - 360 * dt)", { delay: 55 });
	await pause(page, 600);
	await field.press("Tab");
	await expect(page.locator("#jin-field-expr")).toHaveValue(
		"max(0, paddle - 360 * dt)",
	);
	await pause(page, 900);

	// 3. 保存 → `.jin` に正準形で書き戻る。
	await caption(page, "保存すると .jin ファイル（JSON）に正準形で書き戻される");
	await glideClick(page, page.getByTestId("jin-save"));
	await expect(page.getByTestId("jin-notice")).toContainText("保存しました");
	await pause(page, 1200);
	await glideClick(page, page.getByTestId("jin-focus-clear"));
	await pause(page, 800);

	// 4. デバッグモード → 実行パネル（同一オリジンの iframe のプレイヤー）で走る。
	await caption(
		page,
		"デバッグモードに切り替えると、実行パネルでゲームが動き出す",
	);
	await glideClick(page, page.getByTestId("jin-mode-debug"));
	await expect(page.getByTestId("jin-run-panel")).toBeVisible();
	await expect(page.getByTestId("jin-player-missing")).toHaveCount(0);
	await expect(page.getByTestId("jin-jil-error")).toHaveCount(0);
	const frame = page.frameLocator('[data-testid="jin-player"]');
	await expect(frame.locator("#status")).toContainText("tick", {
		timeout: 30_000,
	});
	await pause(page, 1200);

	// 5. 遊ぶ: 止めて最初から（tick 0）に戻し、キャンバスにフォーカスして走らせ、矢印キーでパドルを動かす
	//    （読み込み直後から走っているので、放っておくと球を取り損ねて終わってしまう）。
	await caption(page, "「最初から」で tick 0 に戻し、矢印キーでパドルを動かして遊ぶ");
	await glideClick(page, page.getByTestId("jin-play-pause"));
	await glideClick(page, page.getByTestId("jin-play-reboot"));
	await expect(frame.locator("#status")).toContainText("tick 0");
	const stage = frame.locator("#stage");
	await glideClick(page, stage);
	await glideClick(page, page.getByTestId("jin-play-start"));
	await stage.click();
	// 自動操縦: プレイヤーの表示リスト（`__jinPlayer.lastOps()`）から球（circle）とパドル（rect・幅 40）の x を読み、
	// 矢印キーで球の下へ寄せる（直した式のとおり速く動くので追いつく）。台本の外の入力はこれだけ。
	// 4.2 秒（約 250 tick）で止め、すぐ一時停止するのは、走らせている間のトレースが 4000 行（`MAX_LIVE_ROWS`）を
	// 超えると古い行を落として記憶環の値の積算が途切れるため（paddle は 1 tick に約 12 行）。
	const player = page.frames().find((f) => f.url().includes("/play/"));
	if (player === undefined) throw new Error("プレイヤーの iframe がありません");
	let held: "ArrowLeft" | "ArrowRight" | null = null;
	const hold = async (key: typeof held): Promise<void> => {
		if (key === held) return;
		if (held !== null) await page.keyboard.up(held);
		if (key !== null) await page.keyboard.down(key);
		held = key;
	};
	const started = Date.now();
	while (Date.now() - started < 4_200) {
		const ops = await player.evaluate(
			() =>
				(
					window as unknown as {
						__jinPlayer?: { lastOps(): readonly (readonly unknown[])[] };
					}
				).__jinPlayer?.lastOps() ?? [],
		);
		const ball = ops.find((op) => op[0] === "circle");
		const paddle = ops.find((op) => op[0] === "rect");
		if (ball !== undefined && paddle !== undefined) {
			const target = Number(ball[1]) - 20;
			const x = Number(paddle[1]);
			await hold(x < target - 3 ? "ArrowRight" : x > target + 3 ? "ArrowLeft" : null);
		}
		await pause(page, 40);
	}
	await hold(null);
	const scored = await player.evaluate(
		() =>
			(
				window as unknown as {
					__jinPlayer?: { publicState(): Record<string, unknown> };
				}
			).__jinPlayer?.publicState()["Play.score"] ?? 0,
	);
	expect(Number(scored)).toBeGreaterThanOrEqual(1);

	// 6. 止めて、トレースをスクラブ（発火した要素の強調と記憶環の値が動く）。
	await caption(
		page,
		"一時停止すると、トレースが魔法陣に重なる。スクラブで遡れる",
	);
	await glideClick(page, page.getByTestId("jin-play-pause"));
	await expect(page.getByTestId("jin-player-status")).toContainText("停止");
	await expect(page.getByTestId("jin-trace-name")).toContainText("実行パネル");
	await expect(canvas.locator('[data-jin-fired="1"]').first()).toBeAttached();
	await pause(page, 1500);
	const upto = page.getByTestId("jin-upto");
	const max = Number(await upto.getAttribute("max"));
	expect(max).toBeGreaterThan(20);
	await glideTo(page, upto);
	await pause(page, 400);
	// スライダを段階的に戻す（記憶環の値の表と点の数が変わる）。
	for (const ratio of [0.75, 0.5, 0.3, 0.15, 0.05, 0.3, 0.6, 1]) {
		await upto.fill(String(Math.max(0, Math.round(max * ratio))));
		await pause(page, 550);
	}
	await expect(page.getByTestId("jin-state-value").first()).toBeAttached();
	await page.getByTestId("jin-state-values").scrollIntoViewIfNeeded();
	await caption(page, "魔法陣の中の記憶環に、その時点の値が並ぶ");
	await pause(page, 2200);
	await caption(page, "uv run jin editor examples-v2/paddle/paddle.jin");
	await pause(page, 2200);
});
