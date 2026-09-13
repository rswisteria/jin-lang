import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type Page } from "@playwright/test";

import {
	buildPaddleWithPlayer,
	jin,
	PADDLE,
	serveDirectory,
	type StaticServer,
} from "./harness";

/**
 * パリティ（設計書 §12 Phase 4 の完了条件・runtime.md §7 / §8）。
 *
 * ブラウザで paddle を録画し（キーとポインタを実際に入れる）、書き出した `.jinrec` を
 * `jin run --input` で再生して、**トレース行が boot から全行一致**することを見る。
 * 両側とも JSON として読んでから比べる（2^53 超の整数は JS で丸まるので、片方だけ
 * 生テキストだと非対称になる）。
 */

let server: StaticServer;
let dir: string;

test.beforeAll(async () => {
	const built = buildPaddleWithPlayer();
	dir = built.dir;
	server = await serveDirectory(built.dist);
});

test.afterAll(async () => {
	await server?.close();
});

async function ticks(page: Page): Promise<number> {
	return page.evaluate(() => window.__jinPlayer?.ticks() ?? -1);
}

test("録画した .jinrec を jin run --input で再生するとトレースが全行一致する", async ({
	page,
}) => {
	const errors: string[] = [];
	page.on("pageerror", (error) => errors.push(String(error)));
	await page.goto(`${server.url}/index.html`);
	await page.waitForFunction(() => window.__jinPlayer?.ready === true);
	// 読み込み直後から動いている（"dist/ をブラウザで開いて paddle が遊べる"）
	await page.waitForFunction(() => (window.__jinPlayer?.ticks() ?? 0) >= 5);
	expect(
		await page.evaluate(() => window.__jinPlayer?.error() ?? null),
	).toBeNull();

	// 録画（boot し直して tick 0 から）。キーとポインタを実際に入れる
	await page.getByRole("button", { name: "録画" }).click();
	await page.waitForFunction(() => (window.__jinPlayer?.ticks() ?? 0) >= 10);
	await page.keyboard.down("ArrowLeft");
	await page.waitForFunction(() => (window.__jinPlayer?.ticks() ?? 0) >= 40);
	await page.keyboard.up("ArrowLeft");
	await page.keyboard.down("ArrowRight");
	await page.waitForFunction(() => (window.__jinPlayer?.ticks() ?? 0) >= 70);
	await page.keyboard.up("ArrowRight");
	const stage = page.locator("#stage");
	const box = await stage.boundingBox();
	if (box === null) throw new Error("#stage が見えない");
	await page.mouse.move(box.x + box.width * 0.3, box.y + box.height * 0.6);
	await page.mouse.down();
	await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.5, {
		steps: 5,
	});
	await page.mouse.up();
	await page.waitForFunction(() => (window.__jinPlayer?.ticks() ?? 0) >= 120);
	await page.getByRole("button", { name: "一時停止" }).click();
	const recorded = await page.evaluate(
		() => window.__jinPlayer?.stopRecording() ?? null,
	);
	const executed = await ticks(page);
	const browserRows = await page.evaluate(
		() => window.__jinPlayer?.trace() ?? [],
	);
	expect(errors).toEqual([]);
	expect(recorded).not.toBeNull();
	if (recorded === null) return;

	// 録画の中身: ヘッダの ticks は実行した tick 数、キーとポインタの両方が入っている
	const lines = recorded.trim().split("\n");
	const header = JSON.parse(lines[0] ?? "{}") as {
		jinrec: number;
		seed: number;
		ticks: number;
	};
	expect(header.jinrec).toBe(1);
	expect(header.ticks).toBe(executed);
	const kinds = lines
		.slice(1)
		.map((line) => (JSON.parse(line) as { kind: string }).kind);
	expect(kinds).toContain("key");
	expect(kinds).toContain("pointer");

	// ヘッドレスで再生
	const recPath = join(dir, "rec.jinrec");
	const tracePath = join(dir, "trace.jsonl");
	writeFileSync(recPath, recorded, "utf8");
	jin(["run", PADDLE, "--input", recPath, "--trace", tracePath]);
	const headlessRows = readFileSync(tracePath, "utf8")
		.split("\n")
		.filter((line) => line.trim() !== "")
		.map((line) => JSON.parse(line) as unknown);

	expect(browserRows.length).toBeGreaterThan(executed); // boot の行 + 毎 tick の frame 行
	expect(browserRows.length).toBe(headlessRows.length);
	expect(browserRows).toEqual(headlessRows);
});
