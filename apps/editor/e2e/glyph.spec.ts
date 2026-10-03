import { execFileSync } from "node:child_process";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { dirname, join } from "node:path";

import { expect, test } from "@playwright/test";

import {
	expectServerGone,
	REPO_ROOT,
	type RunningEditor,
	startEditor,
} from "./editor";

/**
 * 陣書き S5: 写真を取り込む → 図に陣 → 写真の下敷き → 実行パネルで動く（設計書 §6 の S5 の完了条件）。
 *
 * 写真は `tests/glyph_photo.py` の `synthetic_photo`（fib の写し書きの手本を斜めから撮ったことにした JPEG）。
 * Claude の応答は `tests/fixtures/recognize/fib-S.synthetic/`（**本物の録画ではなく正解から合成したもの**・
 * その README）を、`ANTHROPIC_BASE_URL` で向けたローカルのモック API が順に返す。ネットワークと API キーは使わない
 * （`ANTHROPIC_API_KEY` はモックに届くだけのダミー）。実行パネルには `apps/player` の dist が要る（v2.spec と同じ）。
 */

const PAGE_SOURCE = readFileSync(
	join(REPO_ROOT, "examples-v2/paddle/paddle.jin"),
	"utf8",
);
const FIB = readFileSync(join(REPO_ROOT, "examples-v2/fib/fib.jin"), "utf8");
const RESPONSES_DIR = join(
	REPO_ROOT,
	"tests/fixtures/recognize/fib-S.synthetic",
);

/** fixture の応答を順に返すモックの Messages API。受けた要求の数を数える。 */
async function startMockApi(): Promise<{
	server: Server;
	url: string;
	paths: string[];
}> {
	const responses = readdirSync(RESPONSES_DIR)
		.filter((name) => name.endsWith(".json"))
		.sort()
		.map((name) => readFileSync(join(RESPONSES_DIR, name), "utf8"));
	const paths: string[] = [];
	const server = createServer((request, response) => {
		request.resume();
		request.on("end", () => {
			paths.push(`${request.method ?? ""} ${request.url ?? ""}`);
			const next = responses.shift();
			if (next === undefined) {
				response.writeHead(500, { "Content-Type": "application/json" });
				response.end(
					'{"type":"error","error":{"type":"api_error","message":"余分な要求"}}',
				);
				return;
			}
			response.writeHead(200, {
				"Content-Type": "application/json",
				"request-id": "req_synthetic",
			});
			response.end(next);
		});
	});
	await new Promise<void>((resolvePromise) => {
		server.listen(0, "127.0.0.1", resolvePromise);
	});
	const { port } = server.address() as AddressInfo;
	return { server, url: `http://127.0.0.1:${String(port)}`, paths };
}

function synthesizePhoto(out: string): void {
	const code = [
		"import sys",
		"from pathlib import Path",
		"from jin_core.check import check_text",
		"from tests.glyph_photo import synthetic_photo",
		'fib = Path("examples-v2/fib/fib.jin")',
		'model = check_text(fib.read_text(encoding="utf-8"), fib.name).model',
		"Path(sys.argv[1]).write_bytes(synthetic_photo(model))",
	].join("\n");
	execFileSync("uv", ["run", "python", "-c", code, out], { cwd: REPO_ROOT });
}

let editor: RunningEditor;
let api: Awaited<ReturnType<typeof startMockApi>>;

test.beforeEach(async () => {
	api = await startMockApi();
	editor = await startEditor(PAGE_SOURCE, "smoke.jin", {
		ANTHROPIC_BASE_URL: api.url,
		ANTHROPIC_API_KEY: "test-key-for-the-mock",
	});
});

test.afterEach(async () => {
	const stopped = await editor?.stop();
	await expectServerGone(editor.url);
	expect(stopped).toBe(true);
	await new Promise<void>((resolvePromise) => {
		api.server.close(() => resolvePromise());
	});
});

// eslint-disable-next-line no-empty-pattern
test.afterEach(async ({}, testInfo) => {
	if (testInfo.status !== testInfo.expectedStatus) {
		await testInfo.attach("jin editor stderr", {
			body: editor.log(),
			contentType: "text/plain",
		});
	}
});

test("写真を取り込む → 図に陣 → 写真の下敷き → 実行パネルで動く（陣書き S5）", async ({
	page,
}) => {
	test.setTimeout(180_000);
	const dir = dirname(editor.file);
	const photo = join(dir, "..", `${String(Date.now())}-fib-photo.jpg`);
	synthesizePhoto(photo);

	await page.goto(editor.url);
	await expect(page.getByTestId("jin-status")).toHaveAttribute(
		"data-state",
		"ready",
	);
	await page.getByTestId("jin-import-file").setInputFiles({
		name: "fib-photo.jpg",
		mimeType: "image/jpeg",
		buffer: readFileSync(photo),
	});

	// 取り込んだ `.jin` を開き直す（URL の uri も差し替わる）。図は fib の陣。
	const panel = page.getByTestId("jin-import-panel");
	await expect(panel).toBeVisible({ timeout: 120_000 });
	await expect(page.getByTestId("jin-import-summary")).toContainText(
		"fib-photo.jin",
	);
	await expect(page).toHaveURL(/fib-photo\.jin/);
	await expect(page.getByTestId("jin-status")).toHaveAttribute(
		"data-state",
		"ready",
	);
	await expect(
		page.getByTestId("jin-canvas").locator('[data-jin-kind="stage"]').first(),
	).toBeAttached();
	// 写真は下敷きとして脇に出る（ブラウザの手元の写真。サーバから配り直さない）
	const image = page.getByTestId("jin-import-photo");
	await expect(image).toBeVisible();
	expect(
		await image.evaluate((node) => (node as HTMLImageElement).naturalWidth),
	).toBeGreaterThan(0);
	await expect(page.getByTestId("jin-import-diagnostic")).toHaveCount(0);

	// 写真・場面グラフ・正準形の `.jin` が開いている `.jin` の隣に書かれている
	expect(readFileSync(join(dir, "fib-photo.jin"), "utf8")).toBe(FIB);
	expect(existsSync(join(dir, "fib-photo.jpg"))).toBe(true);
	const scene = JSON.parse(
		readFileSync(join(dir, "fib-photo.jinscene.json"), "utf8"),
	) as { sheet: string };
	expect(scene.sheet).toBe("S");
	// 認識はサーバ側だけで行い、外へ送る前に 1 行出す（設計書 §3.7）
	expect(api.paths.length).toBe(
		readdirSync(RESPONSES_DIR).filter((n) => n.endsWith(".json")).length,
	);
	expect(api.paths.every((p) => p.startsWith("POST /v1/messages"))).toBe(true);
	expect(editor.log()).toContain("Anthropic の API");

	// 実行パネルで動く
	await page.getByTestId("jin-mode-debug").click();
	const frame = page.frameLocator('[data-testid="jin-player"]');
	await expect(frame.locator("#status")).toContainText("tick", {
		timeout: 30_000,
	});

	// 同じ写真をもう一度落とすと、在る `.jin` に書かずに断る（理由はツールバーに出る）
	const sent = api.paths.length;
	await page.getByTestId("jin-import-file").setInputFiles({
		name: "fib-photo.jpg",
		mimeType: "image/jpeg",
		buffer: readFileSync(photo),
	});
	await expect(page.getByTestId("jin-import-error")).toContainText(
		"上書きしません",
	);
	expect(api.paths.length).toBe(sent);
});
