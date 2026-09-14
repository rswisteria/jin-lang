import { copyFileSync, mkdirSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

import { buildWithPlayer, jin, REPO_ROOT, serveDirectory, type StaticServer } from "./harness";

/**
 * v1 の陣に問う `agent` の sigil（runtime.md §11・設計書 §11 #55・Issue #54 / #69）のパリティ。
 *
 * ブラウザのプレイヤーは v1 の陣に**答えない**（問い `asks` は出るが届かない）。答えを持つのは
 * ヘッドレスの `jin run --model fake --record` が書いた録画（`reply` 行）で、その録画をブラウザで
 * **再生**すると v1 を呼ばずに `jin run --input` とトレースが全行一致する。
 *
 * 台本は `tests/fixtures/v2-programs/agent.jin` の写し + `agents/oracle.jin`（= v1 の pipeline・`ref` 無し）。
 */
const AGENT = join(REPO_ROOT, "tests", "fixtures", "v2-programs", "agent.jin");
const PIPELINE = join(REPO_ROOT, "examples", "pipeline", "pipeline.jin");

let server: StaticServer;
let dir: string;
let world: string;
let recording: string;

test.beforeAll(async () => {
	const home = mkdtempSync(join(tmpdir(), "jin-agent-e2e-"));
	world = join(home, "agent.jin");
	copyFileSync(AGENT, world);
	mkdirSync(join(home, "agents"));
	copyFileSync(PIPELINE, join(home, "agents", "oracle.jin"));
	recording = join(home, "live.jinrec");
	jin(["run", world, "--model", "fake", "--ticks", "5", "--record", recording]);
	const built = buildWithPlayer(world);
	dir = built.dir;
	server = await serveDirectory(built.dist);
});

test.afterAll(async () => {
	await server?.close();
});

test("reply 入りの録画の再生は v1 を呼ばず、jin run --input とトレースが全行一致する", async ({
	page,
}) => {
	const errors: string[] = [];
	page.on("pageerror", (error) => errors.push(error.message));
	await page.goto(server.url);
	await page.waitForFunction(() => window.__jinPlayer?.ready === true);
	// ライブでは答えが来ないので、問いを出したまま待ち続ける（tick は進む・done にならない）。
	await page.waitForFunction(() => (window.__jinPlayer?.ticks() ?? 0) >= 3);
	expect(await page.evaluate(() => window.__jinPlayer?.running())).toBe(true);

	const text = readFileSync(recording, "utf8");
	expect(text).toContain('"kind": "reply"');
	const outcome = await page.evaluate(
		(t) => window.__jinPlayer?.replay(t) ?? null,
		text,
	);
	expect(outcome).toEqual({ ok: true, ticks: 2, message: null });
	expect(await page.evaluate(() => window.__jinPlayer?.running())).toBe(false);
	const browserRows = await page.evaluate(
		() => window.__jinPlayer?.trace() ?? [],
	);

	const tracePath = join(dir, "replay-trace.jsonl");
	jin(["run", world, "--input", recording, "--trace", tracePath]);
	const headlessRows = readFileSync(tracePath, "utf8")
		.split("\n")
		.filter((line) => line.trim() !== "")
		.map((line) => JSON.parse(line) as unknown);
	expect(errors).toEqual([]);
	expect(browserRows.length).toBe(headlessRows.length);
	expect(browserRows).toEqual(headlessRows);
	// 答えが届いた証拠: emit 行（配達された）と公開 state。
	const emit = (headlessRows as { kind: string; output: unknown }[]).find(
		(row) => row.kind === "emit",
	);
	expect(emit?.output).toBe(true);
});
