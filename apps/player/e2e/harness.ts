import { execFileSync } from "node:child_process";
import {
	copyFileSync,
	existsSync,
	mkdirSync,
	mkdtempSync,
	readFileSync,
	statSync,
} from "node:fs";
import { createServer, type Server } from "node:http";
import { tmpdir } from "node:os";
import { extname, join, normalize, resolve } from "node:path";

export const REPO_ROOT = resolve(import.meta.dirname, "../../..");
export const PLAYER_DIST = resolve(import.meta.dirname, "../dist");
export const PADDLE = join(REPO_ROOT, "examples-v2", "paddle", "paddle.jin");

/** `jin build` の出力に同梱される 3 ファイル（`jin_wasm.bundle.PLAYER_FILES` と同じ）。 */
export const PLAYER_FILES = [
	"index.html",
	"player.js",
	"wasmoon.wasm",
] as const;

const MIME: Readonly<Record<string, string>> = {
	".html": "text/html; charset=utf-8",
	".js": "text/javascript; charset=utf-8",
	".json": "application/json; charset=utf-8",
	".wasm": "application/wasm",
	".lua": "text/plain; charset=utf-8",
	".png": "image/png",
	".wav": "audio/wav",
};

export interface StaticServer {
	readonly url: string;
	close(): Promise<void>;
}

/**
 * ディレクトリを 127.0.0.1 の空きポートで配る。**ネットワークには出ない**（NFR-TEST-001）。
 * `.wasm` を `application/wasm` で返すのは `WebAssembly.instantiateStreaming` のため。
 */
export async function serveDirectory(root: string): Promise<StaticServer> {
	const server: Server = createServer((request, response) => {
		const pathname = decodeURIComponent(
			new URL(request.url ?? "/", "http://127.0.0.1").pathname,
		);
		const relative = normalize(
			pathname === "/" ? "/index.html" : pathname,
		).replace(/^(\.\.[/\\])+/, "");
		const file = join(root, relative);
		if (
			!file.startsWith(root) ||
			!existsSync(file) ||
			!statSync(file).isFile()
		) {
			response.writeHead(404);
			response.end();
			return;
		}
		response.writeHead(200, {
			"content-type": MIME[extname(file)] ?? "application/octet-stream",
		});
		response.end(readFileSync(file));
	});
	await new Promise<void>((resolvePromise) =>
		server.listen(0, "127.0.0.1", resolvePromise),
	);
	const address = server.address();
	if (address === null || typeof address === "string")
		throw new Error("ポートが取れません");
	return {
		url: `http://127.0.0.1:${address.port}`,
		close: () =>
			new Promise((resolvePromise) => server.close(() => resolvePromise())),
	};
}

/** `uv run jin …` をリポジトリのルートで同期実行する（失敗は stderr 付きで投げる）。 */
export function jin(args: readonly string[]): string {
	return execFileSync("uv", ["run", "jin", ...args], {
		cwd: REPO_ROOT,
		encoding: "utf8",
		stdio: ["ignore", "pipe", "pipe"],
	});
}

/** `uv run python <script>` をリポジトリのルートで同期実行する。 */
export function python(args: readonly string[]): string {
	return execFileSync("uv", ["run", "python", ...args], {
		cwd: REPO_ROOT,
		encoding: "utf8",
		stdio: ["ignore", "pipe", "pipe"],
	});
}

/**
 * paddle を `jin build --debug` して、`apps/player/dist` の 3 ファイルを隣に置く。
 * （`jin build` 自身の同梱は Python 側の `scripts/sync_player.py` に掛かるので、
 *   e2e はビルド物を**自分で**並べて、プレイヤーの契約だけを見る）
 */
export function buildPaddleWithPlayer(): { dir: string; dist: string } {
	return buildWithPlayer(PADDLE);
}

/** 任意の v2 の `.jin` を `jin build --debug` して、プレイヤーの 3 ファイルを隣に置く。 */
export function buildWithPlayer(jinFile: string): {
	dir: string;
	dist: string;
} {
	for (const name of PLAYER_FILES) {
		if (!existsSync(join(PLAYER_DIST, name))) {
			throw new Error(
				`apps/player/dist/${name} がありません。先に \`pnpm build\` を実行してください`,
			);
		}
	}
	const dir = mkdtempSync(join(tmpdir(), "jin-player-e2e-"));
	const dist = join(dir, "dist");
	mkdirSync(dist);
	jin(["build", jinFile, "--out", dist, "--debug"]);
	for (const name of PLAYER_FILES) {
		copyFileSync(join(PLAYER_DIST, name), join(dist, name));
	}
	return { dir, dist };
}
