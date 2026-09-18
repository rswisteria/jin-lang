import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, type Frame, test } from "@playwright/test";

import {
	expectServerGone,
	REPO_ROOT,
	type RunningEditor,
	startEditor,
} from "../e2e/editor";
import {
	caption,
	glideClick,
	glideHit,
	glideTo,
	installCursor,
	openEditor,
	pause,
	typeInto,
} from "./helpers";

/**
 * チュートリアル動画の台本（`pnpm demo:fib`）: 陣 `Fib` だけの空の `.jin` をビジュアルエディタで開き、
 * 画面操作だけで `examples-v2/fib/fib.jin`（フィボナッチ数列）を組み立て、鑑賞モードで 3D の魔法陣を眺め、
 * 実行して記憶環に答えが出るのを見て、発動の演出を MP4 に書き出す。
 *
 * テストではない（何かを固定する意図は無い）が、`expect` で各段が実際に起きたことは確かめる:
 * 保存した `.jin` が `examples-v2/fib/fib.jin` と**バイト一致**し、`jin run` が 6765 を返す
 * （組み上がらないまま動画だけ出ると嘘のチュートリアルになる）。間の `pause` は見せるための間。
 *
 * fib.jin は起動の 1 tick で計算が終わる（トレース 6 行）ので、一致を確かめた後に loop の本文へ `wait 1` を足し、
 * `stage.fps` を 4 に下げて 1 tick に 1 段ずつ進むようにしてから走らせる（記憶環の値と 3D の発動が目で追える）。
 */

/** 出発点: 陣 `Fib` と、空の手順 `fib`（仮の核）だけ。核は最後に `main` へ切り替える。 */
const START = `${JSON.stringify(
	{
		$schema: "https://xtone.internal/jin/schemas/jin-v2.schema.json",
		version: 2,
		root: "Fib",
		stage: { width: 64, height: 64 },
		circles: [
			{ name: "Fib", core: "fib", rites: [{ name: "fib", steps: [] }] },
		],
	},
	null,
	2,
)}\n`;
const FIB = readFileSync(join(REPO_ROOT, "examples-v2/fib/fib.jin"));

let editor: RunningEditor;

test.beforeEach(async ({ context }) => {
	editor = await startEditor(START, "fib.jin");
	await installCursor(context);
});

test.afterEach(async () => {
	const stopped = await editor?.stop();
	await expectServerGone(editor.url);
	expect(stopped).toBe(true);
});

interface PublicState {
	readonly "Fib.answer"?: number;
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

const CIRCLE = "/circles/0";
const FIB_RITE = `${CIRCLE}/rites/0`;
const MAIN_RITE = `${CIRCLE}/rites/1`;

test("空の陣から fib.jin を組み立て、3D で眺め、実行し、発動の演出を書き出す", async ({
	page,
}) => {
	await openEditor(page, editor.url);
	const canvas = page.getByTestId("jin-canvas");
	const circle = canvas.locator(
		`[data-jin="${CIRCLE}"][data-jin-kind="circle"]`,
	);
	const field = (key: string) => page.locator(`#jin-field-${key}`);
	// ステップは複数の要素（枠 / 辺 / 文字）で描かれ、先頭が幅 0 の `<line>` のことがあるので、当たる点を探して押す。
	const stepAt = (path: string) =>
		canvas.locator(`[data-jin="${path}"][data-jin-kind="step"]`);
	const riteText = (pointer: string) =>
		canvas.locator(`text[data-jin="${pointer}"]`).first();

	await caption(
		page,
		"陣 Fib と空の手順 fib だけの .jin をビジュアルエディタで開く",
	);
	await page.mouse.move(640, 400);
	await pause(page, 2400);

	// ---------------------------------------------------------------- 1. 記憶 answer
	await caption(
		page,
		"陣を選んで「記憶を追加」→ 名前を answer にして、公開（out）にする",
	);
	await glideHit(page, circle);
	await expect(page.getByTestId("jin-pointer")).toHaveText(CIRCLE);
	await glideClick(page, page.getByTestId("jin-add-state"));
	const answer = canvas.locator(
		`[data-jin="${CIRCLE}/state/0"][data-jin-kind="state"]`,
	);
	await expect(answer.first()).toBeAttached();
	await pause(page, 600);
	await glideHit(page, answer);
	await expect(page.getByTestId("jin-pointer")).toHaveText(`${CIRCLE}/state/0`);
	await typeInto(page, field("name"), "answer");
	await expect(field("name")).toHaveValue("answer");
	await glideClick(page, field("out"));
	await expect(field("out")).toBeChecked();
	await pause(page, 900);

	// ---------------------------------------------------------------- 2. 手順 fib(n) -> num
	await caption(
		page,
		"手順 fib を選び、引数の表に n: num を足して、戻り値の型を num に",
	);
	await glideClick(page, riteText(FIB_RITE));
	await expect(page.getByTestId("jin-pointer")).toHaveText(FIB_RITE);
	await expect(field("name")).toHaveValue("fib");
	await glideClick(page, page.getByTestId("jin-row-add"));
	await expect(page.getByTestId("jin-row")).toHaveCount(1);
	await typeInto(page, field("params-0-name"), "n");
	await expect(field("params-0-name")).toHaveValue("n");
	await typeInto(page, field("returns"), "num");
	await expect(field("returns")).toHaveValue("num");
	await pause(page, 900);

	// ---------------------------------------------------------------- 3. fib の中身
	await caption(
		page,
		"手順をダブルクリックしてステップの図を開き、let a = 0 / let b = 1 を足す",
	);
	await glideHit(page, riteText(FIB_RITE), { dblclick: true });
	await expect(page.getByTestId("jin-focus-clear")).toContainText("Fib/fib");
	await pause(page, 800);
	const kind = page.getByTestId("jin-step-kind");
	const addStep = page.getByTestId("jin-add-step");
	const addInside = page.getByTestId("jin-add-step-inside");

	await kind.selectOption("let");
	await glideClick(page, addStep);
	await expect(stepAt(`${FIB_RITE}/steps/0`).first()).toBeAttached();
	await glideHit(page, stepAt(`${FIB_RITE}/steps/0`));
	await expect(page.getByTestId("jin-pointer")).toHaveText(
		`${FIB_RITE}/steps/0`,
	);
	await typeInto(page, field("name"), "a");
	await typeInto(page, field("expr"), "0");
	await expect(field("expr")).toHaveValue("0");

	await glideClick(page, addStep);
	await expect(stepAt(`${FIB_RITE}/steps/1`).first()).toBeAttached();
	await glideHit(page, stepAt(`${FIB_RITE}/steps/1`));
	await expect(page.getByTestId("jin-pointer")).toHaveText(`${FIB_RITE}/steps/1`);
	await typeInto(page, field("name"), "b");
	await typeInto(page, field("expr"), "1");
	await expect(field("expr")).toHaveValue("1");
	await pause(page, 600);

	await caption(
		page,
		"loop を足して回数を n に。本文は空なので「本文に追加」で中へ入れる",
	);
	await kind.selectOption("loop");
	await glideClick(page, addStep);
	await expect(stepAt(`${FIB_RITE}/steps/2`).first()).toBeAttached();
	await glideHit(page, stepAt(`${FIB_RITE}/steps/2`));
	await expect(page.getByTestId("jin-pointer")).toHaveText(`${FIB_RITE}/steps/2`);
	await typeInto(page, field("times"), "n");
	await expect(field("times")).toHaveValue("n");
	await pause(page, 500);

	await kind.selectOption("let");
	await glideClick(page, addInside);
	await expect(page.getByTestId("jin-pointer")).toHaveText(
		`${FIB_RITE}/steps/2/steps/0`,
	);
	await typeInto(page, field("name"), "t");
	await typeInto(page, field("expr"), "a + b");
	await expect(field("expr")).toHaveValue("a + b");

	await caption(
		page,
		"続けて set a = b / set b = t（選んだステップの直後に入る）",
	);
	await kind.selectOption("set");
	await glideClick(page, addStep);
	await expect(stepAt(`${FIB_RITE}/steps/2/steps/1`).first()).toBeAttached();
	await glideHit(page, stepAt(`${FIB_RITE}/steps/2/steps/1`));
	await expect(page.getByTestId("jin-pointer")).toHaveText(`${FIB_RITE}/steps/2/steps/1`);
	await typeInto(page, field("target"), "a");
	await typeInto(page, field("expr"), "b");
	await glideClick(page, addStep);
	await expect(stepAt(`${FIB_RITE}/steps/2/steps/2`).first()).toBeAttached();
	await glideHit(page, stepAt(`${FIB_RITE}/steps/2/steps/2`));
	await expect(page.getByTestId("jin-pointer")).toHaveText(`${FIB_RITE}/steps/2/steps/2`);
	await typeInto(page, field("target"), "b");
	await typeInto(page, field("expr"), "t");
	await expect(field("expr")).toHaveValue("t");
	await pause(page, 600);

	await caption(page, "loop の後ろに return a");
	await glideHit(page, stepAt(`${FIB_RITE}/steps/2`));
	await expect(page.getByTestId("jin-pointer")).toHaveText(
		`${FIB_RITE}/steps/2`,
	);
	await kind.selectOption("return");
	await glideClick(page, addStep);
	await expect(stepAt(`${FIB_RITE}/steps/3`).first()).toBeAttached();
	await glideHit(page, stepAt(`${FIB_RITE}/steps/3`));
	await expect(page.getByTestId("jin-pointer")).toHaveText(`${FIB_RITE}/steps/3`);
	await typeInto(page, field("expr"), "a");
	await expect(field("expr")).toHaveValue("a");
	await pause(page, 1200);

	// ---------------------------------------------------------------- 4. 核の手順 main
	await caption(
		page,
		"「手順を追加」→ 名前を main にして、核（中心）をクリックし core を main に切り替える",
	);
	await glideClick(page, page.getByTestId("jin-focus-clear"));
	await glideHit(page, circle);
	await glideClick(page, page.getByTestId("jin-add-rite"));
	await expect(riteText(MAIN_RITE)).toBeAttached();
	await glideClick(page, riteText(MAIN_RITE));
	await expect(page.getByTestId("jin-pointer")).toHaveText(MAIN_RITE);
	await typeInto(page, field("name"), "main");
	await expect(field("name")).toHaveValue("main");
	await glideClick(page, riteText(`${CIRCLE}/core`));
	await expect(page.getByTestId("jin-pointer")).toHaveText(`${CIRCLE}/core`);
	await typeInto(page, field("core"), "main");
	await expect(field("core")).toHaveValue("main");
	await pause(page, 600);
	await caption(
		page,
		"main の中身: fib(20) の結果を answer に入れて finish",
	);
	await glideHit(page, riteText(MAIN_RITE), { dblclick: true });
	await expect(page.getByTestId("jin-focus-clear")).toContainText("Fib/main");
	await kind.selectOption("cast");
	await glideClick(page, addStep);
	await expect(stepAt(`${MAIN_RITE}/steps/0`).first()).toBeAttached();
	await glideHit(page, stepAt(`${MAIN_RITE}/steps/0`));
	await expect(page.getByTestId("jin-pointer")).toHaveText(`${MAIN_RITE}/steps/0`);
	await typeInto(page, field("target"), "fib");
	await glideClick(page, page.getByTestId("jin-expr-add"));
	await typeInto(page, field("args-0"), "20");
	await expect(field("args-0")).toHaveValue("20");
	await typeInto(page, field("into"), "answer");
	await expect(field("into")).toHaveValue("answer");
	await kind.selectOption("finish");
	await glideClick(page, addStep);
	await expect(stepAt(`${MAIN_RITE}/steps/1`).first()).toBeAttached();
	await glideHit(page, stepAt(`${MAIN_RITE}/steps/1`));
	await expect(page.getByTestId("jin-pointer")).toHaveText(`${MAIN_RITE}/steps/1`);
	await pause(page, 900);

	// ---------------------------------------------------------------- 5. 保存 → fib.jin と一致
	await caption(
		page,
		"保存すると .jin に正準形で書き戻る（examples-v2/fib/fib.jin と 1 バイトも違わない）",
	);
	await glideClick(page, page.getByTestId("jin-save"));
	await expect(page.getByTestId("jin-notice")).toContainText("保存しました");
	expect(readFileSync(editor.file).equals(FIB)).toBe(true);
	const headless = execFileSync(
		"uv",
		["run", "jin", "run", editor.file, "--ticks", "3"],
		{ cwd: REPO_ROOT, encoding: "utf8" },
	);
	expect(headless.trim().split("\n")[0]).toBe('{"Fib.answer": 6765}');
	await pause(page, 1400);
	await glideClick(page, page.getByTestId("jin-focus-clear"));
	await pause(page, 800);

	// ---------------------------------------------------------------- 6. 鑑賞モード（3D）
	await caption(page, "鑑賞モードに切り替えると、魔法陣が金環の 3D になる");
	await glideClick(page, page.getByTestId("jin-mode-stage"));
	await expect(page.getByTestId("jin-stage-panel")).toBeVisible();
	await expect(page.getByTestId("jin-stage-missing")).toHaveCount(0);
	const stage = page.frameLocator('[data-testid="jin-stage"]');
	await expect(stage.getByTestId("stage-status")).toHaveText("準備完了", {
		timeout: 60_000,
	});
	await pause(page, 2600);
	await caption(
		page,
		"構図は 3 種（俯瞰 / 斜め 45° / 低い煽り）。ドラッグで回せる",
	);
	const preset = stage.getByTestId("stage-preset");
	for (const value of ["overhead", "low", "oblique"]) {
		await glideTo(page, preset);
		await preset.selectOption(value);
		await pause(page, 1800);
	}
	const view = stage.getByTestId("stage-view");
	const box = await view.boundingBox();
	if (box === null) throw new Error("鑑賞ページの canvas が見えない");
	const cx = box.x + box.width / 2;
	const cy = box.y + box.height / 2;
	await page.mouse.move(cx, cy, { steps: 20 });
	await page.mouse.down();
	await page.mouse.move(cx + 260, cy - 40, { steps: 60 });
	await page.mouse.move(cx - 120, cy + 30, { steps: 60 });
	await page.mouse.up();
	await pause(page, 1600);

	// ---------------------------------------------------------------- 7. wait 1 と fps
	await caption(
		page,
		"起動の 1 tick で計算が終わるので、loop の本文に wait 1 を足して 1 tick に 1 段ずつ進める",
	);
	await glideClick(page, page.getByTestId("jin-mode-edit"));
	await glideHit(page, riteText(FIB_RITE), { dblclick: true });
	await expect(page.getByTestId("jin-focus-clear")).toContainText("Fib/fib");
	await glideHit(page, stepAt(`${FIB_RITE}/steps/2`));
	await expect(page.getByTestId("jin-pointer")).toHaveText(
		`${FIB_RITE}/steps/2`,
	);
	await kind.selectOption("wait");
	await glideClick(page, addInside);
	await expect(page.getByTestId("jin-pointer")).toHaveText(
		`${FIB_RITE}/steps/2/steps/3`,
	);
	await expect(field("ticks")).toHaveValue("1");
	await pause(page, 900);
	await caption(
		page,
		"額縁（stage）を選んで fps を 4 に下げる（20 tick = 5 秒）",
	);
	await glideClick(page, page.getByTestId("jin-focus-clear"));
	await glideHit(page, canvas.locator('[data-jin-kind="stage"]'));
	await expect(page.getByTestId("jin-pointer")).toHaveText("/stage");
	await typeInto(page, field("fps"), "4");
	await expect(field("fps")).toHaveValue("4");
	await glideClick(page, page.getByTestId("jin-save"));
	await expect(page.getByTestId("jin-notice")).toContainText("保存しました");
	await pause(page, 900);

	// ---------------------------------------------------------------- 8. 実行
	await caption(
		page,
		"実行モードで走らせる。1 tick ごとに fib が進み、20 tick で answer = 6765",
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
	await expect
		.poll(async () => (await publicStateOf(player))["Fib.answer"] ?? 0, {
			timeout: 30_000,
		})
		.toBe(6765);
	await expect(page.getByTestId("jin-state-value").first()).toContainText(
		"6765",
		{ timeout: 15_000 },
	);
	await caption(page, "止まると図が描き直され、記憶環の answer に 6765 が並ぶ");
	await pause(page, 2600);

	// ---------------------------------------------------------------- 9. 発動の演出と書き出し
	await caption(
		page,
		"鑑賞モードに戻ると、走らせたトレースで発動の演出が再生できる",
	);
	await glideClick(page, page.getByTestId("jin-mode-stage"));
	await expect(stage.getByTestId("stage-status")).toHaveText("準備完了", {
		timeout: 60_000,
	});
	await expect
		.poll(async () =>
			Number(await stage.getByTestId("stage-rows").textContent()),
		)
		.toBeGreaterThan(20);
	await glideClick(page, stage.getByTestId("stage-play"));
	await pause(page, 7000);
	await caption(
		page,
		"「動画を書き出す」で MP4 に（1 コマずつ WebCodecs で符号化してダウンロード）",
	);
	const codec = await stage
		.getByTestId("stage-codec")
		.getAttribute("data-codec");
	if (codec === "none") {
		await caption(
			page,
			"この環境では WebCodecs が無いので動画の書き出しは省略",
		);
		await pause(page, 2000);
	} else {
		const downloaded = page.waitForEvent("download", { timeout: 600_000 });
		await glideClick(page, stage.getByTestId("stage-export-video"));
		await expect(page.getByTestId("jin-stage-status")).toContainText(
			"書き出し中",
		);
		const file = await downloaded;
		expect(file.suggestedFilename()).toMatch(
			/^fib-Fib-seed0-t-?\d+-\d+\.(mp4|webm)$/,
		);
		await caption(page, `書き出した: ${file.suggestedFilename()}`);
		await pause(page, 2400);
	}
	await caption(page, "uv run jin editor fib.jin");
	await pause(page, 2400);
});
