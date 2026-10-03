/**
 * `jin editor` の取り込みエンドポイント `POST /read`（陣書き S5・`docs/spec/ops.md` §5.3）を読む口。
 *
 * 写真（型紙に手で描いた陣）か完全陣の PNG をサーバへ送ると、サーバが場面グラフにして
 * 写真・`<写真名>.jinscene.json`・`<写真名>.jin` を開いている `.jin` の隣に書き、
 * 診断を写真の座標（`box`）付きで返す。**認識（Anthropic の API）はサーバ側だけ**で行い、
 * API キーはブラウザに来ない。
 *
 * **トークンはヘッダに置く**（`X-Jin-Token`。`POST /run` と同じ理由: カスタムヘッダが
 * CORS の preflight を強制し、他オリジンのページから撃てなくする）。body や query に置かない。
 *
 * **`"/read"` の文字列はこのファイルにだけ書く**（`tests/contract/test_editor_contract.py`）。
 */

/** サーバが受ける拡張子（`jin_cli.readserver.IMAGE_SUFFIXES` と同じ）。 */
export const IMAGE_SUFFIXES = [".png", ".jpg", ".jpeg", ".webp"] as const;

export interface ReadDiagnostic {
	readonly code: string;
	readonly severity: string;
	readonly message: string;
	readonly hint: string | null;
	/** 場面グラフ（`.jinscene.json`）の中の位置。 */
	readonly pointer: string;
	/** 写真の上の矩形（画素・`[x0, y0, x1, y1]`）。位置の分からない診断は null。 */
	readonly box: readonly [number, number, number, number] | null;
}

export interface ReadResult {
	/** 書いた `.jin` の `file://` URI。絵の文法の誤りでモデルを組めなければ null（写真と場面グラフだけ書く）。 */
	readonly jin: string | null;
	readonly photo: string;
	readonly scene: string;
	readonly image: { readonly width: number; readonly height: number };
	readonly diagnostics: readonly ReadDiagnostic[];
}

export type ReadOutcome =
	| { readonly kind: "ok"; readonly result: ReadResult }
	| {
			readonly kind: "error";
			readonly status: number;
			readonly message: string;
	  };

export interface ReadOptions {
	/** 取り込みエンドポイントの origin。**このページを配っているのと同じところ**。 */
	readonly origin: string;
	readonly token: string;
	readonly file: File;
}

export function isImageName(name: string): boolean {
	const lower = name.toLowerCase();
	const dot = lower.lastIndexOf(".");
	if (dot <= 0) return false;
	return (IMAGE_SUFFIXES as readonly string[]).includes(lower.slice(dot));
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseBox(value: unknown): ReadDiagnostic["box"] | undefined {
	if (value === null) return null;
	if (
		Array.isArray(value) &&
		value.length === 4 &&
		value.every((n) => typeof n === "number" && Number.isFinite(n))
	) {
		return [value[0], value[1], value[2], value[3]] as const;
	}
	return undefined;
}

function parseDiagnostic(value: unknown): ReadDiagnostic | null {
	if (!isRecord(value)) return null;
	const { code, severity, message, hint, pointer } = value;
	const box = parseBox(value["box"]);
	if (
		typeof code !== "string" ||
		typeof severity !== "string" ||
		typeof message !== "string" ||
		typeof pointer !== "string" ||
		(hint !== null && hint !== undefined && typeof hint !== "string") ||
		box === undefined
	)
		return null;
	return { code, severity, message, hint: hint ?? null, pointer, box };
}

/** 応答の形を検める。合わなければ null（推測で埋めない）。 */
export function parseReadResult(value: unknown): ReadResult | null {
	if (!isRecord(value)) return null;
	const { jin, photo, scene, image, diagnostics } = value;
	if (jin !== null && typeof jin !== "string") return null;
	if (typeof photo !== "string" || typeof scene !== "string") return null;
	if (
		!isRecord(image) ||
		typeof image["width"] !== "number" ||
		typeof image["height"] !== "number"
	)
		return null;
	if (!Array.isArray(diagnostics)) return null;
	const parsed: ReadDiagnostic[] = [];
	for (const item of diagnostics) {
		const diagnostic = parseDiagnostic(item);
		if (diagnostic === null) return null;
		parsed.push(diagnostic);
	}
	return {
		jin,
		photo,
		scene,
		image: { width: image["width"], height: image["height"] },
		diagnostics: parsed,
	};
}

/**
 * 取り込んだ `.jin` を開き直したあとの URL。`uri` だけを差し替え、`ws` とフラグメント（トークン）を保つ
 * （再読み込みしても取り込んだ `.jin` が開くように `history.replaceState` に渡す）。
 */
export function uriInLocation(href: string, uri: string): string {
	const url = new URL(href);
	url.searchParams.set("uri", uri);
	return url.toString();
}

async function base64Of(file: File): Promise<string> {
	const bytes = new Uint8Array(await file.arrayBuffer());
	let binary = "";
	// `String.fromCharCode(...bytes)` は大きな写真で引数の上限を超えるので区切って積む。
	const CHUNK = 0x8000;
	for (let i = 0; i < bytes.length; i += CHUNK) {
		binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
	}
	return btoa(binary);
}

/**
 * 画像を送って取り込みを頼む。成否とも応答の body は JSON（断られた理由は `error`）。
 */
export async function readImage(options: ReadOptions): Promise<ReadOutcome> {
	const response = await fetch(`${options.origin}/read`, {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			"X-Jin-Token": options.token,
		},
		body: JSON.stringify({
			name: options.file.name,
			data: await base64Of(options.file),
		}),
	});
	let payload: unknown;
	try {
		payload = await response.json();
	} catch {
		payload = null;
	}
	if (!response.ok) {
		const message =
			isRecord(payload) && typeof payload["error"] === "string"
				? payload["error"]
				: `取り込みを頼めません（HTTP ${String(response.status)}）`;
		return { kind: "error", status: response.status, message };
	}
	const result = parseReadResult(payload);
	if (result === null) {
		return {
			kind: "error",
			status: response.status,
			message: "取り込みの応答を読めません",
		};
	}
	return { kind: "ok", result };
}
