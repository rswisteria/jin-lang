import { readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

import {
	buildPaddleWithPlayer,
	jin,
	PADDLE,
	REPO_ROOT,
	serveDirectory,
	type StaticServer,
} from "./harness";

/**
 * 録画の再生（設計書 §10 パリティ行「録画済み `.jinrec` を再生させてトレースを取り出し、
 * `jin run --input` の出力と一致」・Phase 6）。
 *
 * `parity.spec.ts` はブラウザで**録画する**側、ここはブラウザで**再生する**側。同じ `.jinrec`
 * （`tests/fixtures/jinrec/paddle-120.jinrec`）を `__jinPlayer.replay` と `jin run --input` に渡し、
 * トレースを JSON として読んでから全行一致で比べる。再生が止まった状態で終わることも見る。
 */
const RECORDING = join(
	REPO_ROOT,
	"tests",
	"fixtures",
	"jinrec",
	"paddle-120.jinrec",
);

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

test("`.jinrec` の再生は jin run --input とトレースが全行一致し、止まったまま終わる", async ({
	page,
}) => {
	const errors: string[] = [];
	page.on("pageerror", (error) => errors.push(error.message));
	await page.goto(server.url);
	await page.waitForFunction(() => window.__jinPlayer?.ready === true);
	await page.waitForFunction(() => (window.__jinPlayer?.ticks() ?? 0) >= 5);

	const text = readFileSync(RECORDING, "utf8");
	const outcome = await page.evaluate(
		(t) => window.__jinPlayer?.replay(t) ?? null,
		text,
	);
	expect(outcome).toEqual({ ok: true, ticks: 120, message: null });
	expect(await page.evaluate(() => window.__jinPlayer?.running())).toBe(false);
	expect(await page.evaluate(() => window.__jinPlayer?.ticks())).toBe(120);
	expect(await page.evaluate(() => window.__jinPlayer?.seed())).toBe(7);
	const browserRows = await page.evaluate(
		() => window.__jinPlayer?.trace() ?? [],
	);

	const tracePath = join(dir, "replay-trace.jsonl");
	jin(["run", PADDLE, "--input", RECORDING, "--trace", tracePath]);
	const headlessRows = readFileSync(tracePath, "utf8")
		.split("\n")
		.filter((line) => line.trim() !== "")
		.map((line) => JSON.parse(line) as unknown);
	expect(errors).toEqual([]);
	expect(browserRows.length).toBe(headlessRows.length);
	expect(browserRows).toEqual(headlessRows);

	// 壊れた録画は行番号付きで断り、走らない。
	const broken = await page.evaluate(
		() =>
			window.__jinPlayer?.replay(
				'{"jinrec": 1}\n{"tick": 1, "kind": "mouse"}\n',
			) ?? null,
	);
	expect(broken?.ok).toBe(false);
	expect(broken?.message).toContain("2: ");
	expect(broken?.message).toContain("kind");
});
