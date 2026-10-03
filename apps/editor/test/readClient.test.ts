import { afterEach, describe, expect, test, vi } from "vitest";

import {
	isImageName,
	parseReadResult,
	readImage,
	uriInLocation,
} from "../src/read/client";

const OK = {
	jin: "file:///work/fib.jin",
	photo: "fib.jpg",
	scene: "fib.jinscene.json",
	image: { width: 4032, height: 3024 },
	diagnostics: [
		{
			code: "JIN306",
			severity: "warning",
			message: "迷いを第一候補 1 で解きました",
			hint: "他の候補: l",
			pointer: "/bands/0/cells/3",
			box: [10, 20, 30, 40],
		},
	],
};

afterEach(() => {
	vi.unstubAllGlobals();
});

describe("parseReadResult（POST /read の応答・ops.md §5.3）", () => {
	test("形が合えばそのまま読む", () => {
		expect(parseReadResult(OK)).toEqual(OK);
	});
	test("jin が null（絵の文法の誤りでモデルを組めない）でも読む", () => {
		expect(parseReadResult({ ...OK, jin: null })?.jin).toBeNull();
	});
	test("box の無い診断は null", () => {
		const result = parseReadResult({
			...OK,
			diagnostics: [{ ...OK.diagnostics[0], box: null, hint: null }],
		});
		expect(result?.diagnostics[0]?.box).toBeNull();
		expect(result?.diagnostics[0]?.hint).toBeNull();
	});
	test("形が違えば null（推測で埋めない）", () => {
		expect(parseReadResult(null)).toBeNull();
		expect(parseReadResult({ ...OK, jin: 3 })).toBeNull();
		expect(parseReadResult({ ...OK, image: { width: "x" } })).toBeNull();
		expect(
			parseReadResult({ ...OK, diagnostics: [{ code: "JIN306" }] }),
		).toBeNull();
		expect(
			parseReadResult({
				...OK,
				diagnostics: [{ ...OK.diagnostics[0], box: [1, 2, 3] }],
			}),
		).toBeNull();
	});
});

describe("isImageName", () => {
	test("写真と完全陣の拡張子だけ（大文字も）", () => {
		for (const name of ["a.jpg", "a.JPEG", "a.webp", "a.png"])
			expect(isImageName(name)).toBe(true);
		for (const name of ["a.jin", "a.gif", "jpg", "a.jinrec"])
			expect(isImageName(name)).toBe(false);
	});
});

describe("uriInLocation", () => {
	test("uri だけを差し替え、ws とフラグメント（トークン）を保つ", () => {
		const next = uriInLocation(
			"http://127.0.0.1:5000/?ws=ws%3A%2F%2F127.0.0.1%3A6000&uri=file%3A%2F%2F%2Fw%2Fa.jin#token=abc",
			"file:///w/fib.jin",
		);
		const url = new URL(next);
		expect(url.searchParams.get("uri")).toBe("file:///w/fib.jin");
		expect(url.searchParams.get("ws")).toBe("ws://127.0.0.1:6000");
		expect(url.hash).toBe("#token=abc");
	});
});

describe("readImage", () => {
	test("トークンはヘッダに置き、画像は base64 で JSON の body に載せる", async () => {
		const fetchMock = vi.fn(
			async () =>
				new Response(JSON.stringify(OK), {
					status: 200,
					headers: { "Content-Type": "application/json" },
				}),
		);
		vi.stubGlobal("fetch", fetchMock);
		const file = new File(
			[new Uint8Array([0xff, 0xd8, 0x00, 0xd9])],
			"fib.jpg",
		);
		const outcome = await readImage({
			origin: "http://127.0.0.1:5000",
			token: "secret",
			file,
		});
		expect(outcome).toEqual({ kind: "ok", result: OK });
		const [url, init] = fetchMock.mock.calls[0] as unknown as [
			string,
			RequestInit,
		];
		expect(url).toBe("http://127.0.0.1:5000/read");
		expect(init.method).toBe("POST");
		expect((init.headers as Record<string, string>)["X-Jin-Token"]).toBe(
			"secret",
		);
		expect(url).not.toContain("secret");
		const body = JSON.parse(String(init.body)) as Record<string, string>;
		expect(body).toEqual({ name: "fib.jpg", data: "/9gA2Q==" });
		expect(JSON.stringify(body)).not.toContain("secret");
	});

	test("断られたら body の理由を返す", async () => {
		vi.stubGlobal(
			"fetch",
			vi.fn(
				async () =>
					new Response(JSON.stringify({ error: "fib.jin が既にあります" }), {
						status: 409,
					}),
			),
		);
		const outcome = await readImage({
			origin: "http://x",
			token: "t",
			file: new File(["x"], "fib.jpg"),
		});
		expect(outcome).toEqual({
			kind: "error",
			status: 409,
			message: "fib.jin が既にあります",
		});
	});

	test("body が JSON でなければ状態番号だけで断る", async () => {
		vi.stubGlobal(
			"fetch",
			vi.fn(async () => new Response("Forbidden", { status: 403 })),
		);
		const outcome = await readImage({
			origin: "http://x",
			token: "t",
			file: new File(["x"], "fib.jpg"),
		});
		expect(outcome.kind).toBe("error");
		if (outcome.kind === "error") expect(outcome.message).toContain("403");
	});
});
