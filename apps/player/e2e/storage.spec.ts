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
 * `storage`（abilities.md §8・v2.1）を**実ブラウザ**で。
 *
 * `tests/fixtures/v2-programs/storage.jin` は boot のたびに `runs` を 1 増やして書き、最高記録 `best` と
 * `label` を保つ。見るのは:
 * 1. 書き込みが `localStorage`（`jin.storage:<file>`）に残り、ページを読み直すと続く（runs が 1 → 2）
 * 2. 録画のヘッダに録画の boot に渡した写しが載り、`jin run --input` が同じ写しで boot して
 *    **トレースが全行一致**する（storage のパリティ）
 * 3. 再生はヘッダの写しで boot し、本物の記憶を上書きしない
 * 4. 「記憶を消す」で空になり、次の boot は runs = 1 から
 */
const PROGRAM = join(
	REPO_ROOT,
	"tests",
	"fixtures",
	"v2-programs",
	"storage.jin",
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

test("記憶は localStorage に残って次の起動で続き、録画のヘッダの写しで jin run --input と全行一致し、再生は上書きしない", async ({
	page,
}) => {
	const errors: string[] = [];
	page.on("pageerror", (error) => errors.push(error.message));
	await page.goto(server.url);
	await page.waitForFunction(() => window.__jinPlayer?.ready === true);
	await page.waitForFunction(() => (window.__jinPlayer?.ticks() ?? 0) >= 2);
	await page.evaluate(() => window.__jinPlayer?.pause());
	// 1 回目: runs = 1、best = 1、label = "run 1" が localStorage に書かれている。
	expect(await page.evaluate(() => window.__jinPlayer?.storage())).toEqual({
		runs: "1",
		best: "1",
		label: "run 1",
	});
	expect(await page.evaluate(() => window.__jinPlayer?.publicState())).toEqual({
		"Only.runs": 1,
		"Only.best": 1,
		"Only.label": "",
	});
	const stored = await page.evaluate(() =>
		window.localStorage.getItem("jin.storage:storage.jin"),
	);
	expect(JSON.parse(stored ?? "null")).toEqual({
		runs: "1",
		best: "1",
		label: "run 1",
	});

	// ページを読み直す（= 次の起動）: boot に写しが渡り runs = 2。
	await page.reload();
	await page.waitForFunction(() => window.__jinPlayer?.ready === true);
	await page.waitForFunction(() => (window.__jinPlayer?.ticks() ?? 0) >= 2);
	await page.evaluate(() => window.__jinPlayer?.pause());
	expect(await page.evaluate(() => window.__jinPlayer?.publicState())).toEqual({
		"Only.runs": 2,
		"Only.best": 2,
		"Only.label": "run 1",
	});
	expect(await page.evaluate(() => window.__jinPlayer?.storage())).toEqual({
		runs: "2",
		best: "2",
		label: "run 2",
	});

	// 録画: boot に渡した写し（runs 2 …）がヘッダに載り、`jin run --input` が同じ写しで boot する。
	await page.evaluate(() => window.__jinPlayer?.startRecording());
	await page.evaluate(() => window.__jinPlayer?.start());
	await page.waitForFunction(() => (window.__jinPlayer?.ticks() ?? 0) >= 5);
	await page.evaluate(() => window.__jinPlayer?.pause());
	const text = await page.evaluate(
		() => window.__jinPlayer?.stopRecording() ?? "",
	);
	const header = JSON.parse(text.split("\n")[0] ?? "{}") as {
		storage?: Record<string, string>;
		ticks?: number;
	};
	expect(header.storage).toEqual({ runs: "2", best: "2", label: "run 2" });
	const browserRows: readonly Row[] = await page.evaluate(
		() => window.__jinPlayer?.trace() ?? [],
	);
	const recPath = join(dir, "storage.jinrec");
	writeFileSync(recPath, text);
	const tracePath = join(dir, "headless.jsonl");
	jin(["run", PROGRAM, "--input", recPath, "--trace", tracePath]);
	const headlessRows = readFileSync(tracePath, "utf8")
		.split("\n")
		.filter((line) => line.trim() !== "")
		.map((line) => JSON.parse(line) as Row);
	expect(browserRows).toEqual(headlessRows);
	// 核の `order = cmp("B", "a") + cmp("ｱ", "😀") * 2`（expr.md §4.1・v2.1）。Wasmoon でもコードポイント順で
	// -3（ロケールの照合順なら 1 つ目が、UTF-16 のコード単位順なら 2 つ目が逆になる）。
	expect(
		browserRows
			.filter((row) => row.kind === "set" && row.name === "order")
			.map((row) => row.output),
	).toEqual([-3]);
	// 録画の間に runs は 3 になっている（本物の記憶）。
	expect(await page.evaluate(() => window.__jinPlayer?.storage())).toEqual({
		runs: "3",
		best: "3",
		label: "run 3",
	});

	// 再生: ヘッダの写し（runs 2）で boot し直すので公開 state は runs 3 だが、本物の記憶は上書きしない。
	const outcome = await page.evaluate(
		(t) => window.__jinPlayer?.replay(t) ?? null,
		text,
	);
	expect(outcome?.ok).toBe(true);
	expect(await page.evaluate(() => window.__jinPlayer?.publicState())).toEqual({
		"Only.runs": 3,
		"Only.best": 3,
		"Only.label": "run 2",
	});
	expect(await page.evaluate(() => window.__jinPlayer?.storage())).toEqual({
		runs: "3",
		best: "3",
		label: "run 3",
	});

	// 記憶を消す: 空になり、boot し直して runs = 1 から。
	await page.evaluate(() => window.__jinPlayer?.forget());
	expect(await page.evaluate(() => window.__jinPlayer?.storage())).toEqual({});
	expect(
		JSON.parse(
			(await page.evaluate(() =>
				window.localStorage.getItem("jin.storage:storage.jin"),
			)) ?? "null",
		),
	).toEqual({});
	await page.evaluate(() => window.__jinPlayer?.step());
	expect(await page.evaluate(() => window.__jinPlayer?.publicState())).toEqual({
		"Only.runs": 1,
		"Only.best": 1,
		"Only.label": "",
	});
	expect(errors).toEqual([]);
});
