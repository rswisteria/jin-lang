import {
	cpSync,
	mkdtempSync,
	readFileSync,
	rmSync,
	writeFileSync,
} from "node:fs";
import { createServer, type Server } from "node:http";
import { tmpdir } from "node:os";
import { extname, isAbsolute, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

/**
 * エディタの代わりに postMessage を送る親ページと、ビルド済みの `dist/` を一時ディレクトリに組み立てて配る。
 * 親ページは `stage.file` を `window.JIN_FILES` に積み、`stage.status` を `window.JIN_STATUS` に置く。
 */
const STAGE_ROOT = resolve(fileURLToPath(new URL("..", import.meta.url)));
const FIXTURES = join(STAGE_ROOT, "test", "fixtures");

const PARENT = (
	svg: string,
	names: string,
	rows: string,
	stageSize: string,
): string => `<!doctype html>
<html><body style="margin:0">
<iframe id="stage" src="./stage/?export=360" style="width:960px;height:720px;border:0"></iframe>
<script>
window.JIN_FILES = []; window.JIN_STATUS = null;
const frame = document.getElementById("stage");
window.addEventListener("message", (event) => {
  if (event.source !== frame.contentWindow) return;
  if (event.data.type === "stage.file") window.JIN_FILES.push({ name: event.data.name, mime: event.data.mime, bytes: Array.from(new Uint8Array(event.data.bytes)) });
  if (event.data.type === "stage.status") window.JIN_STATUS = event.data;
});
window.JIN_SCENE = { type: "stage.scene", svg: ${svg}, names: ${names}, fps: 60, jinName: "paddle.jin", circleName: "Play", stageSize: ${stageSize} };
window.JIN_RESEND = () => frame.contentWindow.postMessage(window.JIN_SCENE, location.origin);
frame.addEventListener("load", () => {
  frame.contentWindow.postMessage(window.JIN_SCENE, location.origin);
  frame.contentWindow.postMessage({ type: "stage.trace", rows: ${rows}, seed: 7 }, location.origin);
});
</script></body></html>`;

const TYPES: Readonly<Record<string, string>> = {
	".html": "text/html",
	".js": "text/javascript",
	".css": "text/css",
	".svg": "image/svg+xml",
	".json": "application/json",
	".wasm": "application/wasm",
};

/** `dir` の内側（`dir` 自身を含む）か。`startsWith` だと `/tmp/x` が `/tmp/x-evil` を通すので `relative` で見る。 */
function inside(dir: string, file: string): boolean {
	const rel = relative(dir, file);
	return rel === "" || (!rel.startsWith("..") && !isAbsolute(rel));
}

/** 親ページが送る fixture（`test/fixtures/` のファイル名）。既定は paddle の陣。 */
export interface HarnessFixture {
	readonly svg: string;
	readonly names: string;
	readonly trace: string;
	/** 舞台の大きさ（召喚の窓）。無ければ窓を出さない場面。 */
	readonly stageSize?: { readonly width: number; readonly height: number };
}

export const PADDLE: HarnessFixture = {
	svg: "play.svg",
	names: "paddle-names.json",
	trace: "paddle-trace.jsonl",
};
export const TETRIS: HarnessFixture = {
	svg: "tetris.svg",
	names: "tetris-names.json",
	trace: "tetris-trace.jsonl",
	stageSize: { width: 176, height: 176 },
};
export const PADDLE_STEP: HarnessFixture = { ...PADDLE, svg: "play-step.svg" };
/** 音の fixture: tetris でハードドロップを 3 回する録画（tests/fixtures/jinrec/tetris-drops.jinrec）のトレース。 */
export const TETRIS_DROPS: HarnessFixture = { ...TETRIS, trace: "tetris-drops-trace.jsonl" };

export async function serveHarness(fixture: HarnessFixture = PADDLE): Promise<{
	url: string;
	close(): Promise<void>;
}> {
	const dir = mkdtempSync(join(tmpdir(), "jin-stage-e2e-"));
	cpSync(join(STAGE_ROOT, "dist"), join(dir, "stage"), { recursive: true });
	const rows = readFileSync(join(FIXTURES, fixture.trace), "utf8")
		.split("\n")
		.filter((line) => line.trim() !== "")
		.map((line) => JSON.parse(line) as unknown);
	writeFileSync(
		join(dir, "index.html"),
		PARENT(
			JSON.stringify(readFileSync(join(FIXTURES, fixture.svg), "utf8")),
			readFileSync(join(FIXTURES, fixture.names), "utf8"),
			JSON.stringify(rows),
			JSON.stringify(fixture.stageSize ?? null),
		),
	);
	const server: Server = createServer((request, response) => {
		let path: string;
		try {
			path = decodeURIComponent((request.url ?? "/").split("?")[0] ?? "/");
		} catch {
			response.writeHead(400).end();
			return;
		}
		const file = resolve(
			dir,
			`.${path.endsWith("/") ? `${path}index.html` : path}`,
		);
		if (!inside(dir, file)) {
			response.writeHead(404).end();
			return;
		}
		try {
			const body = readFileSync(file);
			response
				.writeHead(200, {
					"Content-Type": TYPES[extname(file)] ?? "application/octet-stream",
				})
				.end(body);
		} catch {
			response.writeHead(404).end();
		}
	});
	await new Promise<void>((done) => server.listen(0, "127.0.0.1", done));
	const address = server.address();
	if (address === null || typeof address === "string")
		throw new Error("待ち受けのポートが読めません");
	return {
		url: `http://127.0.0.1:${String(address.port)}/`,
		close: () =>
			new Promise((done) => {
				server.closeAllConnections();
				server.close(() => {
					rmSync(dir, { recursive: true, force: true });
					done();
				});
			}),
	};
}
