import { readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, type Frame, type Page, test } from "@playwright/test";

import {
	expectServerGone,
	REPO_ROOT,
	type RunningEditor,
	startEditor,
} from "../e2e/editor";
import {
	caption,
	glideClick,
	glideTo,
	installCursor,
	openEditor,
	pause,
} from "./helpers";

/**
 * README の動画の台本（`pnpm demo`）: Jin v2 のサンプル（tetris）をビジュアルエディタで開き、
 * 核の手順の式（重力）を書き換えて保存し、実行パネルで録画しながら遊び、録画を読み直して
 * トレースをスクラブする。
 *
 * テストではない（何かを固定する意図は無い）が、`expect` で各段が実際に起きたことは確かめる
 * （動かないまま動画だけ出ると嘘の README になる）。間の `pause` は見せるための間で、収録の外では意味が無い。
 * 画面には擬似カーソルと字幕を差し込む（Playwright の動画にはカーソルが写らない）。
 *
 * 遊ぶのは自動操縦（プレイヤーの公開 state `Play.board` / `Play.piece` を読み、置き場所を選んで矢印キーと
 * Space を押す）。走らせている間のトレースは 4000 行で古い行が落ちる（`MAX_LIVE_ROWS`・tetris は 1 tick に
 * 数十〜百行）ので、スクラブは「この録画を再生」で読み直した全行（`MAX_REPLAY_ROWS`）に対して行う。
 */
const TETRIS = join(REPO_ROOT, "examples-v2/tetris/tetris.jin");
const SOURCE = readFileSync(TETRIS, "utf8");

/** ミノの形の表（`Play.shapes` の init と同じ。7 種 × 4 回転 × 4 マスの x, y）。 */
const SHAPES: number[] = (() => {
	const doc = JSON.parse(SOURCE) as {
		circles: { name: string; state?: { name: string; init: string }[] }[];
	};
	const play = doc.circles.find((c) => c.name === "Play");
	const shapes = play?.state?.find((s) => s.name === "shapes");
	if (shapes === undefined) throw new Error("Play.shapes がありません");
	return JSON.parse(shapes.init) as number[];
})();

let editor: RunningEditor;

test.beforeEach(async ({ context }) => {
	editor = await startEditor(SOURCE, "tetris.jin");
	await installCursor(context);
});

test.afterEach(async () => {
	const stopped = await editor?.stop();
	await expectServerGone(editor.url);
	expect(stopped).toBe(true);
});

// ---------------------------------------------------------------- 自動操縦

interface Piece {
	readonly kind: number;
	readonly rot: number;
	readonly x: number;
	readonly y: number;
}

interface PublicState {
	readonly "Play.board"?: number[];
	readonly "Play.piece"?: Piece;
	readonly "Play.placed"?: number;
	readonly "Play.score"?: number;
	readonly "Play.lines"?: number;
}

function cell(kind: number, rot: number, i: number): [number, number] {
	const base = ((kind * 4 + rot) * 4 + i) * 2;
	return [SHAPES[base] ?? 0, SHAPES[base + 1] ?? 0];
}

/** `Play.fits` と同じ判定（盤面の外・埋まったマス）。 */
function fits(
	board: number[],
	kind: number,
	rot: number,
	x: number,
	y: number,
): boolean {
	for (let i = 0; i < 4; i += 1) {
		const [cx, cy] = cell(kind, rot, i);
		const px = x + cx;
		const py = y + cy;
		if (px < 0 || px >= 10 || py >= 20) return false;
		if (py >= 0 && (board[py * 10 + px] ?? 0) !== 0) return false;
	}
	return true;
}

/** 置いた後の盤面の悪さ（高さ・穴・でこぼこ・消える行）。小さいほど良い。 */
function badness(
	board: number[],
	kind: number,
	rot: number,
	x: number,
	y: number,
): number {
	const next = board.slice();
	for (let i = 0; i < 4; i += 1) {
		const [cx, cy] = cell(kind, rot, i);
		if (y + cy >= 0) next[(y + cy) * 10 + x + cx] = 1;
	}
	let cleared = 0;
	for (let r = 0; r < 20; r += 1) {
		if (next.slice(r * 10, r * 10 + 10).every((v) => v !== 0)) cleared += 1;
	}
	const heights: number[] = [];
	let holes = 0;
	for (let c = 0; c < 10; c += 1) {
		let top = 20;
		for (let r = 0; r < 20; r += 1) {
			if ((next[r * 10 + c] ?? 0) !== 0) {
				top = r;
				break;
			}
		}
		heights.push(20 - top);
		for (let r = top + 1; r < 20; r += 1) {
			if ((next[r * 10 + c] ?? 0) === 0) holes += 1;
		}
	}
	let bumpiness = 0;
	for (let c = 0; c + 1 < 10; c += 1) {
		bumpiness += Math.abs((heights[c] ?? 0) - (heights[c + 1] ?? 0));
	}
	const aggregate = heights.reduce((a, b) => a + b, 0);
	return aggregate * 0.5 + holes * 4 + bumpiness * 0.4 - cleared * 6;
}

/** 今のミノの置き場所（回転と x）を選ぶ。回転は出現位置で、横移動は 1 列ずつ `fits` を通る経路だけ。 */
function plan(board: number[], piece: Piece): { rot: number; x: number } {
	let best: { rot: number; x: number; score: number } | null = null;
	for (let rot = 0; rot < 4; rot += 1) {
		if (!fits(board, piece.kind, rot, piece.x, piece.y)) continue;
		for (const dir of [-1, 1]) {
			for (let x = piece.x; x >= -3 && x <= 9; x += dir) {
				if (!fits(board, piece.kind, rot, x, piece.y)) break;
				let y = piece.y;
				while (fits(board, piece.kind, rot, x, y + 1)) y += 1;
				const score = badness(board, piece.kind, rot, x, y);
				if (best === null || score < best.score) best = { rot, x, score };
			}
		}
	}
	return best === null
		? { rot: piece.rot, x: piece.x }
		: { rot: best.rot, x: best.x };
}

function publicStateOf(player: Frame): Promise<PublicState> {
	return player.evaluate(
		() =>
			(
				window as unknown as {
					__jinPlayer?: { publicState(): PublicState };
				}
			).__jinPlayer?.publicState() ?? {},
	);
}

/** キーを 1 回押す（押下の遷移が別々の tick に入るよう 70 ms 空ける。30 fps = 33 ms / tick）。 */
async function tap(page: Page, key: string): Promise<void> {
	await page.keyboard.press(key);
	await pause(page, 70);
}

/**
 * 自動操縦: 新しいミノが出るたびに置き場所を選び、回転 → 横移動 → Space で落とす。
 * `untilPlaced` 個置くか `ms` 経つまで。
 */
async function autoplay(
	page: Page,
	player: Frame,
	ms: number,
	untilPlaced: number,
): Promise<void> {
	const started = Date.now();
	let handled = -1;
	while (Date.now() - started < ms) {
		const state = await publicStateOf(player);
		const board = state["Play.board"];
		const piece = state["Play.piece"];
		const placed = state["Play.placed"] ?? 0;
		if (board === undefined || piece === undefined || placed === handled) {
			await pause(page, 30);
			continue;
		}
		if (placed >= untilPlaced) break;
		handled = placed;
		const target = plan(board, piece);
		for (let r = piece.rot; r !== target.rot; r = (r + 1) % 4)
			await tap(page, "ArrowUp");
		const key = target.x < piece.x ? "ArrowLeft" : "ArrowRight";
		for (let i = 0; i < Math.abs(target.x - piece.x); i += 1)
			await tap(page, key);
		await tap(page, "Space");
	}
}

test("tetris をエディタで直して、実行パネルで遊び、録画を読み直してトレースを追う", async ({
	page,
}) => {
	await openEditor(page, editor.url);
	const canvas = page.getByTestId("jin-canvas");
	await expect(
		canvas.locator('[data-jin-kind="stage"]').first(),
	).toBeAttached();
	await caption(
		page,
		"Jin v2 のサンプル tetris.jin をビジュアルエディタで開く",
	);
	await page.mouse.move(640, 400);
	await pause(page, 2200);

	// 1. 陣 Play の核の手順 begin をダブルクリックして、ステップの図へ。
	await caption(
		page,
		"陣 Play の核の手順 begin をダブルクリックして、ステップの図を開く",
	);
	const beginRite = canvas
		.locator('text[data-jin="/circles/1/rites/0"]')
		.first();
	await glideClick(page, beginRite);
	await expect(page.getByTestId("jin-pointer")).toHaveText(
		"/circles/1/rites/0",
	);
	await pause(page, 900);
	await beginRite.dblclick();
	await expect(page.getByTestId("jin-focus-clear")).toContainText("Play/begin");
	await expect(canvas.locator('[data-jin-kind="step"]').first()).toBeAttached();
	await pause(page, 1600);

	// 2. `set speed = 15` を選び、重力を速くする。
	await caption(
		page,
		"ステップを選んで、式エディタで重力（1 段落ちるまでの tick 数）を 15 → 5 に変える",
	);
	const speedStep = canvas
		.locator('[data-jin="/circles/1/rites/0/steps/3"][data-jin-kind="step"]')
		.first();
	await glideClick(page, speedStep);
	const field = page.locator("#jin-field-expr");
	await expect(field).toHaveValue("15");
	await glideClick(page, field);
	await pause(page, 500);
	await field.fill("");
	await field.pressSequentially("5", { delay: 120 });
	await pause(page, 600);
	await field.press("Tab");
	await expect(page.locator("#jin-field-expr")).toHaveValue("5");
	await pause(page, 900);

	// 3. 保存 → `.jin` に正準形で書き戻る。
	await caption(page, "保存すると .jin ファイル（JSON）に正準形で書き戻される");
	await glideClick(page, page.getByTestId("jin-save"));
	await expect(page.getByTestId("jin-notice")).toContainText("保存しました");
	expect(readFileSync(editor.file, "utf8")).toContain('"expr": "5"');
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
	const player = page.frames().find((f) => f.url().includes("/play/"));
	if (player === undefined) throw new Error("プレイヤーの iframe がありません");
	await pause(page, 2500);

	// 5. 録画を始めて（boot し直して tick 0 から）遊ぶ。最初のミノは直した重力で落ちるのを見せ、あとは自動操縦。
	await caption(
		page,
		"録画を始めて遊ぶ。直した重力のとおり、放っておいても速く落ちる",
	);
	await glideClick(page, page.getByTestId("jin-play-pause"));
	await glideClick(page, page.getByTestId("jin-play-record"));
	await expect(page.getByTestId("jin-player-status")).toContainText("録画中");
	const stage = frame.locator("#stage");
	await glideClick(page, stage);
	await expect
		.poll(async () => (await publicStateOf(player))["Play.placed"] ?? 0)
		.toBeGreaterThanOrEqual(1);
	await caption(
		page,
		"矢印キーで動かして回し、Space で落とす（行がそろうと消える）",
	);
	await autoplay(page, player, 9_000, 60);
	const played = await publicStateOf(player);
	expect(played["Play.placed"] ?? 0).toBeGreaterThan(8);
	await pause(page, 400);

	// 6. 録画を止めて（親がダウンロードとして渡す）、「この録画を再生」で読み直す → トレース全体が載る。
	await caption(
		page,
		"録画を止めて「この録画を再生」で読み直すと、トレースが最初からそろう",
	);
	const downloaded = page.waitForEvent("download");
	await glideClick(page, page.getByTestId("jin-play-stop"));
	await downloaded;
	await expect(page.getByTestId("jin-player-status")).toContainText("停止");
	await pause(page, 900);
	await glideClick(page, page.getByTestId("jin-replay-last"));
	await expect(page.getByTestId("jin-trace-name")).toContainText("録画:", {
		timeout: 60_000,
	});
	await expect(page.getByTestId("jin-player-notice")).toContainText(
		"再生しました",
	);
	await expect(page.getByTestId("jin-trace-error")).toHaveCount(0);
	await expect(canvas.locator('[data-jin-fired="1"]').first()).toBeAttached();
	await pause(page, 1500);

	// 7. スクラブ（発火した要素の強調と記憶環の値がその時点に戻る）。
	await caption(
		page,
		"スクラブで遡ると、発火した要素と記憶環の値がその時点に戻る",
	);
	const upto = page.getByTestId("jin-upto");
	const max = Number(await upto.getAttribute("max"));
	expect(max).toBeGreaterThan(1000);
	await glideTo(page, upto);
	await pause(page, 400);
	for (const ratio of [0.75, 0.5, 0.3, 0.15, 0.05, 0.3, 0.6, 1]) {
		await upto.fill(String(Math.max(0, Math.round(max * ratio))));
		await pause(page, 550);
	}
	await expect(page.getByTestId("jin-state-value").first()).toBeAttached();
	await page.getByTestId("jin-state-values").scrollIntoViewIfNeeded();
	await caption(page, "魔法陣の中の記憶環に、その時点の値が並ぶ");
	await pause(page, 2200);
	await caption(page, "uv run jin editor examples-v2/tetris/tetris.jin");
	await pause(page, 2200);
});
