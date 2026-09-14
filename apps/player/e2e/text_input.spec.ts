import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

import {
	buildWithPlayer,
	jin,
	REPO_ROOT,
	serveDirectory,
	type StaticServer,
} from "./harness";

/**
 * 文字入力（abilities.md §3 の `input.text`・v2.1）を**実ブラウザ**で。
 *
 * `tests/fixtures/v2-programs/text_input.jin` は `name = name ++ input.text()` で打った文字をつなぎ、
 * `input.pressed("Backspace")` で 1 文字消し、`canvas.text` で描く。見るのは:
 * 1. canvas を押すとフォーカスが見えない入力欄に移り、打った文字（keydown → input）と貼り付けた非 ASCII
 *    （input だけ）がどちらも `text` イベントとして `input.text()` に届く。Backspace はキーとして届く
 * 2. 録画に `text` の行が載り、`jin run --input` で再生すると**トレースが全行一致**する（決定性）
 *
 * IME の合成（compositionstart → isComposing の input → compositionend）は Playwright で本物を
 * 起こせないので、`apps/player/test/input.test.ts` が合成イベントで固定する。
 */
const PROGRAM = join(
	REPO_ROOT,
	"tests",
	"fixtures",
	"v2-programs",
	"text_input.jin",
);

interface Row {
	readonly seq: number;
	readonly kind: string;
	readonly name?: string | null;
	readonly output?: unknown;
}

let server: StaticServer;
let dir: string;

test.beforeAll(async () => {
	const built = buildWithPlayer(PROGRAM);
	dir = built.dir;
	server = await serveDirectory(built.dist);
});

test.afterAll(async () => {
	await server?.close();
});

async function nameIs(
	page: import("@playwright/test").Page,
	want: string,
): Promise<void> {
	await page.waitForFunction(
		(w) => window.__jinPlayer?.publicState()?.["Only.name"] === w,
		want,
	);
}

test("打った文字と貼り付けた非 ASCII が input.text() に届き、録画を jin run --input で再生するとトレースが全行一致する", async ({
	page,
}) => {
	const errors: string[] = [];
	page.on("pageerror", (error) => errors.push(error.message));
	await page.goto(server.url);
	await page.waitForFunction(() => window.__jinPlayer?.ready === true);

	// 録画は boot し直して tick 0 から（runtime.md §7）。
	await page.evaluate(() => window.__jinPlayer?.startRecording());
	await page.evaluate(() => window.__jinPlayer?.start());

	// canvas を押すと、文字と IME を受ける入力欄にフォーカスが移る（canvas は文字を受けられない）。
	await page.locator("#stage").click();
	await expect(page.locator("#text")).toBeFocused();

	await page.keyboard.type("ab");
	await nameIs(page, "ab");
	await page.keyboard.insertText("日本😀");
	await nameIs(page, "ab日本😀");
	await page.keyboard.press("Backspace");
	await nameIs(page, "ab日本");
	await page.keyboard.type("c");
	await nameIs(page, "ab日本c");
	// 入力欄には何も残らない（確定するたびに取り出して空にする）。
	await expect(page.locator("#text")).toHaveValue("");

	await page.evaluate(() => window.__jinPlayer?.pause());
	const text = await page.evaluate(
		() => window.__jinPlayer?.stopRecording() ?? "",
	);
	const recorded = text
		.split("\n")
		.slice(1)
		.filter((line) => line.trim() !== "")
		.map((line) => JSON.parse(line) as { kind: string; text?: string });
	expect(
		recorded.filter((ev) => ev.kind === "text").map((ev) => ev.text),
	).toEqual(["a", "b", "日本😀", "c"]);
	expect(
		recorded.some(
			(ev) =>
				ev.kind === "key" && (ev as { name?: string }).name === "Backspace",
		),
	).toBe(true);

	const browserRows: readonly Row[] = await page.evaluate(
		() => window.__jinPlayer?.trace() ?? [],
	);
	const recPath = join(dir, "text_input.jinrec");
	writeFileSync(recPath, text);
	const tracePath = join(dir, "headless.jsonl");
	jin(["run", PROGRAM, "--input", recPath, "--trace", tracePath]);
	const headlessRows = readFileSync(tracePath, "utf8")
		.split("\n")
		.filter((line) => line.trim() !== "")
		.map((line) => JSON.parse(line) as Row);
	expect(browserRows).toEqual(headlessRows);
	expect(
		headlessRows
			.filter((row) => row.kind === "set" && row.name === "name")
			.map((row) => row.output)
			.at(-1),
	).toBe("ab日本c");
	expect(errors).toEqual([]);
});
