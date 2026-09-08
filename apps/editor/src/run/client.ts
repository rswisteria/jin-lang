import type { TraceRow } from "../trace/parse";

/**
 * `jin editor` の実行エンドポイント（Issue #34）を読む口。
 *
 * **`EventSource` は使わない。** カスタムヘッダを付けられないからである。トークンを
 * `X-Jin-Token` ヘッダで送るのは、それが CORS の preflight を強制して他オリジンの
 * ページからの実行を封じる唯一の手だてだからで（body や query だと `Content-Type` 次第で
 * simple request として撃たれる）、受信方法はそれに従う
 * （`docs/superpowers/specs/2026-09-08-editor-run-design.md` §3.2 / §3.3）。
 *
 * **行の契約は書かない。** ここが見るのは SSE の枠（`event:` / `data:` / 空行）だけで、
 * `seq` と `pointer` の意味は `jin_render.overlay` が持つ（`trace/parse.ts` と同じ分担）。
 */
export type RunEvent =
	| { readonly kind: "row"; readonly row: TraceRow }
	| { readonly kind: "done"; readonly exit: number; readonly stderr: string }
	| { readonly kind: "error"; readonly message: string };

export interface RunOptions {
	/** 実行エンドポイントの origin。**このページを配っているのと同じところ**である。 */
	readonly origin: string;
	readonly token: string;
	readonly prompt: string;
	/** `"fake"` か `null` だけ。実モデルは `.jin` の core が持つ（サーバが 400 で断る）。 */
	readonly model: string | null;
	readonly signal?: AbortSignal;
}

/**
 * SSE のフレームを組み立てる。**chunk をまたいだ分は貯める。**
 *
 * ネットワークは行の途中で切れる。貯めずに捨てるとトレースの行が黙って消える。
 */
export class SseDecoder {
	private pending = "";

	push(chunk: string): RunEvent[] {
		this.pending += chunk;
		const events: RunEvent[] = [];
		// フレームの区切りは空行。`\r\n` で書かれていても読めるようにする。
		const frames = this.pending.split(/\r?\n\r?\n/);
		this.pending = frames.pop() ?? "";
		for (const frame of frames) {
			const event = decodeFrame(frame);
			if (event !== null) events.push(event);
		}
		return events;
	}
}

function decodeFrame(frame: string): RunEvent | null {
	let name = "";
	let data = "";
	for (const line of frame.split(/\r?\n/)) {
		if (line.startsWith("event: ")) name = line.slice("event: ".length);
		else if (line.startsWith("data: ")) data = line.slice("data: ".length);
	}
	if (name === "" || data === "") return null;
	let payload: unknown;
	try {
		payload = JSON.parse(data);
	} catch {
		return null;
	}
	if (typeof payload !== "object" || payload === null || Array.isArray(payload))
		return null;
	const record = payload as Record<string, unknown>;
	if (name === "row") return { kind: "row", row: record };
	if (name === "done") {
		return {
			kind: "done",
			exit: typeof record["exit"] === "number" ? record["exit"] : -1,
			stderr: typeof record["stderr"] === "string" ? record["stderr"] : "",
		};
	}
	if (name === "error") {
		return {
			kind: "error",
			message:
				typeof record["message"] === "string"
					? record["message"]
					: "理由が分かりません",
		};
	}
	return null;
}

/**
 * 実行を頼み、届いた順にイベントを返す。
 *
 * **トークンはヘッダに置く**（`X-Jin-Token`）。body や query に置いてはいけない。
 */
export async function* runAgent(options: RunOptions): AsyncGenerator<RunEvent> {
	const response = await fetch(`${options.origin}/run`, {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			"X-Jin-Token": options.token,
		},
		body: JSON.stringify({ prompt: options.prompt, model: options.model }),
		// `exactOptionalPropertyTypes` のもとでは `signal?: AbortSignal` をそのまま渡せない
		// （`RequestInit.signal` は `AbortSignal | null` で `undefined` を受けない）。
		signal: options.signal ?? null,
	});
	if (!response.ok || response.body === null) {
		yield {
			kind: "error",
			message: `実行を頼めません（HTTP ${String(response.status)}）`,
		};
		return;
	}
	const decoder = new SseDecoder();
	const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
	try {
		for (;;) {
			const { done, value } = await reader.read();
			if (done) return;
			for (const event of decoder.push(value)) yield event;
		}
	} finally {
		reader.releaseLock();
	}
}
