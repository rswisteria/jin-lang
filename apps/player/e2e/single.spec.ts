import { mkdtempSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

import {
	jin,
	PADDLE,
	python,
	serveDirectory,
	type StaticServer,
} from "./harness";

/**
 * `jin build --single`（runtime.md §9）: `scripts/sync_player.py` で同梱してから 1 ファイルの
 * `index.html` を書き、ブラウザで開いて動くことを見る。wasm は `data:` URL で Wasmoon に渡る
 * （fetch しない）。これは実際の `jin build` と実際のブラウザで確かめる以外に方法が無い。
 */

let server: StaticServer;
let dist: string;

test.beforeAll(async () => {
	python(["scripts/sync_player.py"]);
	dist = join(mkdtempSync(join(tmpdir(), "jin-player-single-")), "dist");
	jin(["build", PADDLE, "--out", dist, "--single", "--debug"]);
	server = await serveDirectory(dist);
});

test.afterAll(async () => {
	await server?.close();
});

test("--single の index.html 1 本だけで paddle が動く（wasm は data: URL）", async ({
	page,
}) => {
	expect(readdirSync(dist)).toEqual(["index.html"]);
	const errors: string[] = [];
	page.on("pageerror", (error) => errors.push(String(error)));
	const requests: string[] = [];
	page.on("request", (request) => requests.push(request.url()));
	await page.goto(`${server.url}/index.html`);
	await page.waitForFunction(() => window.__jinPlayer?.ready === true);
	await page.waitForFunction(() => (window.__jinPlayer?.ticks() ?? 0) >= 10);
	expect(errors).toEqual([]);
	expect(
		await page.evaluate(() => window.__jinPlayer?.error() ?? null),
	).toBeNull();
	expect(
		await page.evaluate(() => window.__jinPlayer?.lastOps().length ?? 0),
	).toBeGreaterThan(0);
	expect(
		await page.evaluate(() => window.__jinPlayer?.trace().length ?? 0),
	).toBeGreaterThan(10);
	// 取りに行ったのはページ自身だけ（player.js / wasmoon.wasm / game.lua / manifest は埋め込み）
	expect(requests.filter((url) => url.startsWith("http"))).toEqual([
		`${server.url}/index.html`,
	]);
});
