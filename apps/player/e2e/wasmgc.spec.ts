import {
	existsSync,
	mkdtempSync,
	readdirSync,
	readFileSync,
	writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, test, type Page } from "@playwright/test";

import {
	buildWithPlayer,
	jin,
	PADDLE,
	python,
	serveDirectory,
	type StaticServer,
} from "./harness";

/**
 * `--target wasm-gc` のプレイヤー（jil.md §6.8・§6.9 の Sub-Issue D・Issue #76）。
 *
 * `jin build --target wasm-gc --debug` の `game.wasm` を共通のプレイヤー（`manifest.target` で `WasmGcHost`
 * を選ぶ）で実ブラウザで走らせ、録画した `.jinrec` を **Lua 経路と wasm-GC 経路の両方**の `jin run --input`
 * で再生して、トレースが boot から全行一致することを見る（`parity.spec.ts` と同じ比べ方: JSON として
 * 読んでから比べる）。2 本目は `--single` の wasm-gc 版（`game.wasm` を base64 で埋めた `index.html` 1 本）。
 */

async function ticks(page: Page): Promise<number> {
	return page.evaluate(() => window.__jinPlayer?.ticks() ?? -1);
}

function rows(path: string): unknown[] {
	return readFileSync(path, "utf8")
		.split("\n")
		.filter((line) => line.trim() !== "")
		.map((line) => JSON.parse(line) as unknown);
}

test.describe("game.wasm をブラウザで", () => {
	let server: StaticServer;
	let dir: string;

	test.beforeAll(async () => {
		const built = buildWithPlayer(PADDLE, ["--target", "wasm-gc"]);
		dir = built.dir;
		server = await serveDirectory(built.dist);
	});

	test.afterAll(async () => {
		await server?.close();
	});

	test("録画した .jinrec を両経路の jin run --input で再生するとトレースが全行一致する", async ({
		page,
	}) => {
		// バンドルは game.wasm で、game.lua は無い
		expect(existsSync(join(dir, "dist", "game.wasm"))).toBe(true);
		expect(existsSync(join(dir, "dist", "game.lua"))).toBe(false);
		const manifest = JSON.parse(
			readFileSync(join(dir, "dist", "game.manifest.json"), "utf8"),
		) as { target?: string; jil?: string; wasm?: string };
		expect(manifest.target).toBe("wasm-gc");
		expect(manifest.jil).toBeUndefined();

		const errors: string[] = [];
		page.on("pageerror", (error) => errors.push(String(error)));
		const requests: string[] = [];
		page.on("request", (request) => requests.push(request.url()));
		await page.goto(`${server.url}/index.html`);
		await page.waitForFunction(() => window.__jinPlayer?.ready === true);
		await page.waitForFunction(() => (window.__jinPlayer?.ticks() ?? 0) >= 5);
		expect(
			await page.evaluate(() => window.__jinPlayer?.error() ?? null),
		).toBeNull();
		// 取りに行ったのは game.wasm であって game.lua / wasmoon.wasm ではない
		expect(requests.some((url) => url.endsWith("/game.wasm"))).toBe(true);
		expect(requests.some((url) => url.endsWith("/game.lua"))).toBe(false);
		expect(requests.some((url) => url.endsWith("/wasmoon.wasm"))).toBe(false);

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
		const kinds = recorded
			.trim()
			.split("\n")
			.slice(1)
			.map((line) => (JSON.parse(line) as { kind: string }).kind);
		expect(kinds).toContain("key");
		expect(kinds).toContain("pointer");

		// ヘッドレスで再生: Lua 経路と wasm-GC 経路の両方
		const recPath = join(dir, "rec.jinrec");
		writeFileSync(recPath, recorded, "utf8");
		const luaTrace = join(dir, "lua.jsonl");
		const wasmTrace = join(dir, "wasm.jsonl");
		jin(["run", PADDLE, "--input", recPath, "--trace", luaTrace]);
		jin([
			"run",
			PADDLE,
			"--target",
			"wasm-gc",
			"--input",
			recPath,
			"--trace",
			wasmTrace,
		]);
		const luaRows = rows(luaTrace);
		const wasmRows = rows(wasmTrace);
		expect(browserRows.length).toBeGreaterThan(executed); // boot の行 + 毎 tick の frame 行
		expect(browserRows.length).toBe(luaRows.length);
		expect(browserRows).toEqual(luaRows);
		expect(browserRows).toEqual(wasmRows);
	});
});

test.describe("--single の wasm-gc 版", () => {
	let server: StaticServer;
	let dist: string;

	test.beforeAll(async () => {
		python(["scripts/sync_player.py"]);
		dist = join(mkdtempSync(join(tmpdir(), "jin-player-wasmgc-single-")), "dist");
		jin([
			"build",
			PADDLE,
			"--out",
			dist,
			"--single",
			"--debug",
			"--target",
			"wasm-gc",
		]);
		server = await serveDirectory(dist);
	});

	test.afterAll(async () => {
		await server?.close();
	});

	test("index.html 1 本だけで paddle が動く（game.wasm は base64 で埋め込み・何も fetch しない）", async ({
		page,
	}) => {
		expect(readdirSync(dist)).toEqual(["index.html"]);
		const html = readFileSync(join(dist, "index.html"), "utf8");
		expect(html).toContain("window.JIN_BUNDLE");
		expect(html).toContain('"game"');
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
		// 取りに行ったのはページ自身だけ（player.js / game.wasm / manifest は埋め込み。wasmoon.wasm は要らない）
		expect(requests.filter((url) => url.startsWith("http"))).toEqual([
			`${server.url}/index.html`,
		]);
	});
});
