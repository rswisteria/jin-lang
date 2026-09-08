import { spawn } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

/** `jin_cli.editor.URL_PREFIX` と同じ文字列。ずれたら起動が読めなくなる。 */
const URL_PREFIX = "jin editor url: ";

const REPO_ROOT = resolve(import.meta.dirname, "../../..");

/**
 * `stop()` が終了を待つ上限。
 *
 * 実測（macOS・3 回）は SIGTERM から `uv` の `exit` まで **4 / 4 / 5 ms**、
 * 孫（Python）まで含めて全プロセスが消えるまで **35 / 37 / 42 ms**。
 * CI（共有ランナー）の遅さを見込んで 2 桁以上の余裕を取る。
 * **超えたら取り残しである**ので、待ち続けたり SIGKILL に落としたりせず `false` を返す
 * （SIGKILL は `uv` を即死させるだけで孫へ伝わらないため、静かな取り残しに戻る）。
 */
const EXIT_TIMEOUT_MS = 10_000;

export interface RunningEditor {
	readonly url: string;
	readonly file: string;
	/** サーバ側の stderr。失敗したときに原因を見るために貯めておく。 */
	log(): string;
	/**
	 * 既定のシグナル（SIGTERM）を送って終了を待つ。時間内に終われば `true`。
	 *
	 * **割り込みのシグナルではない。** `spawn` の直接の子は `uv` で、実体の
	 * `jin editor`（Python）はその孫である。割り込みは孫へ伝わらず `uv` 自身も
	 * 終わらないので、`uv run` と Python の 2 プロセスがポートを掴んだまま残る
	 * （Issue #32・実測）。SIGTERM は `uv` が孫へ中継する。
	 */
	stop(): Promise<boolean>;
}

/** 一時ディレクトリに `.jin` を置き、`jin editor --no-browser` を起動して URL を読む。 */
export async function startEditor(source: string): Promise<RunningEditor> {
	const dir = mkdtempSync(join(tmpdir(), "jin-editor-e2e-"));
	const file = join(dir, "smoke.jin");
	writeFileSync(file, source, "utf8");

	const child = spawn("uv", ["run", "jin", "editor", file, "--no-browser"], {
		cwd: REPO_ROOT,
		stdio: ["ignore", "pipe", "pipe"],
	});

	let buffered = "";
	let url: string;
	try {
		url = await new Promise<string>((resolvePromise, rejectPromise) => {
			const timer = setTimeout(() => {
				rejectPromise(
					new Error(`jin editor が URL を出しません:\n${buffered}`),
				);
			}, 60_000);
			child.stderr.setEncoding("utf8");
			child.stderr.on("data", (chunk: string) => {
				buffered += chunk;
				for (const line of buffered.split("\n")) {
					if (line.startsWith(URL_PREFIX)) {
						clearTimeout(timer);
						resolvePromise(line.slice(URL_PREFIX.length).trim());
						return;
					}
				}
			});
			child.on("exit", (code) => {
				clearTimeout(timer);
				rejectPromise(
					new Error(`jin editor が exit ${code} で終わりました:\n${buffered}`),
				);
			});
		});
	} catch (error) {
		// **URL を読めなかった経路でも子を落とす。** ここで殺さないと呼び出し元は
		// `RunningEditor` を受け取れず、`stop()` を呼ぶ手段そのものが無い（Issue #32）。
		child.kill();
		throw error;
	}

	return {
		url,
		file,
		log: () => buffered,
		stop: async () => {
			// 既に終わっている子に `once("exit")` を張ると誰も解決しない（タイムアウトまで待つ）。
			if (child.exitCode !== null || child.signalCode !== null) return true;
			child.kill();
			return await new Promise<boolean>((resolvePromise) => {
				const timer = setTimeout(() => {
					resolvePromise(false);
				}, EXIT_TIMEOUT_MS);
				child.once("exit", () => {
					clearTimeout(timer);
					resolvePromise(true);
				});
			});
		},
	};
}

/**
 * `jin editor` が掴んでいたポートが閉じたこと。
 *
 * **プロセスの生死ではなくポートで見る**のは、(1) `pgrep` に依存せず macOS でも Linux CI でも
 * 同じことを見られる、(2) ポートを握っているのは `uv` ではなく**孫**（Python）なので、
 * 中継されないシグナルを送る実装ならここが必ず落ちる、の 2 つのため。
 * `stop()` の中ではなく呼び出し側に置く（`stop()` が待たずに `true` を返す実装も赤くする）。
 */
export async function expectServerGone(url: string): Promise<void> {
	const origin = new URL(url).origin;
	let rejected = false;
	try {
		await fetch(origin, { signal: AbortSignal.timeout(2_000) });
	} catch {
		rejected = true;
	}
	if (!rejected) {
		throw new Error(
			`${origin} がまだ応答する（jin editor のプロセスが残っている）`,
		);
	}
}

export { REPO_ROOT };
