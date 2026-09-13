// @vitest-environment node
import { createRequire } from "node:module";

import { describe as group, expect, test } from "vitest";

import {
	HOST_HOOK_GLOBALS,
	HostError,
	JinHost,
	SANDBOX_REMOVED,
	withoutNulls,
} from "../src/host";
import type { Manifest } from "../src/types";

/**
 * 実際の Wasmoon で `JinHost` を通す（モックしない）。JIL の代わりに、プレリュードと同じ規約
 * （`JIN_ARM` / `JIN_HOOK` を `local` に捕まえ、`boot` / `tick` を置き、JSON 文字列を返す）で書いた
 * 小さな Lua を使う。**プレリュードそのものは読まない**（apps/player は Python 側の生成物を読まない）。
 */
const WASM = createRequire(import.meta.url).resolve("wasmoon/dist/glue.wasm");

const MANIFEST: Manifest = {
	file: "t.jin",
	stage: { width: 32, height: 16, fps: 60, seed: 3 },
	namespaces: ["canvas"],
	assets: [],
	debug: false,
	jil: "",
};

/** `busy` を真にすると tick の中のコルーチンが無限ループする。 */
function game(busy: boolean): string {
	return `
local ARM = JIN_ARM
local HOOK = JIN_HOOK
local SEED = 0
local N = 0
function boot(seed, manifest)
  if ARM then ARM() end
  SEED = seed
  N = manifest.stage.width
end
function tick(t, inputs)
  if ARM then ARM() end
  local co = coroutine.create(function()
    ${busy ? "local i = 0 while true do i = i + 1 end" : ""}
    return #inputs.events
  end)
  if HOOK then HOOK(co) end
  local ok, e = pcall(function()
    local ok2, v = coroutine.resume(co)
    if not ok2 then error(v, 0) end
    return v
  end)
  if not ok then
    return '{"ops":[],"audio":[],"done":true,"error":"' .. tostring(e.message) .. '","public":{}}'
  end
  local px = inputs.pointer.x
  return '{"ops":[["rect",' .. tostring(t) .. ',' .. tostring(SEED) .. ',' .. tostring(N) .. ',' .. tostring(px) .. ']],"audio":[],"done":false,"error":null,"public":{"n":' .. tostring(e) .. '}}'
end
`;
}

const INPUTS = {
	events: [{ kind: "key" as const, name: "ArrowLeft", down: true }],
	keys: { ArrowLeft: true as const },
	pointer: { x: 5, y: 6, down: false },
};

/** `manifest.resume` の欄の型を tick の JSON に載せる（`null` が Lua に nil として見えることを見る）。 */
const RESUME_PROBE = `
local ARM = JIN_ARM
local SEEN = "-"
function boot(seed, manifest)
  if ARM then ARM() end
  local r = manifest.resume
  if r ~= nil then
    local c = r.circles[1]
    SEEN = type(c.state) .. "/" .. tostring(c.name) .. "/" .. tostring(#r.circles)
      .. "/" .. type(c.list[1]) .. "/" .. tostring(c.list[2]) .. "/" .. type(r.rng)
  end
end
function tick(t, inputs)
  if ARM then ARM() end
  return '{"ops":[],"audio":[],"done":false,"error":null,"public":{"seen":"' .. SEEN .. '"}}'
end
`;

group("JinHost（実際の Wasmoon）", () => {
	test("manifest の null は Lua に nil として見え、配列は 1 始まりで読める（Wasmoon は null を積めない・probe §A.11）", async () => {
		const host = await JinHost.create(RESUME_PROBE, WASM);
		try {
			const resume = {
				tick: 1,
				seed: 3,
				seq: 0,
				rng: "0x1",
				circles: [{ name: "G", state: null, delegate: null, list: [null, 2] }],
			};
			host.boot(3, { ...MANIFEST, resume });
			expect(host.tick(0, INPUTS).public).toEqual({
				seen: "nil/G/1/nil/2/string",
			});
			// 写しなので渡した snapshot はそのまま（`null` が消えていない）。
			expect(resume.circles[0]?.state).toBeNull();
			expect(withoutNulls(resume).circles[0]).toEqual({
				name: "G",
				list: [undefined, 2],
			});
		} finally {
			host.close();
		}
	});

	test("boot / tick を通し、tick の JSON 文字列を parse して返す", async () => {
		const host = await JinHost.create(game(false), WASM);
		try {
			host.boot(3, MANIFEST);
			const result = host.tick(0, INPUTS);
			expect(result.ops).toEqual([["rect", 0, 3, 32, 5]]);
			expect(result.done).toBe(false);
			expect(result.public).toEqual({ n: 1 });
		} finally {
			host.close();
		}
	});

	test("危険なグローバルは JIL を読む前に消えている", async () => {
		const host = await JinHost.create(game(false), WASM);
		try {
			for (const name of SANDBOX_REMOVED) {
				expect(host.evalForTest(`type(${name})`), name).toBe("nil");
			}
			expect(host.evalForTest("type(string.dump)")).toBe("nil");
		} finally {
			host.close();
		}
	});

	test("JIN_ARM / JIN_HOOK は JIL を読んだ後に消え、グローバルは boot / tick だけ", async () => {
		const host = await JinHost.create(game(false), WASM);
		try {
			for (const name of HOST_HOOK_GLOBALS) {
				expect(host.evalForTest(`type(${name})`), name).toBe("nil");
			}
			expect(host.evalForTest("type(boot) .. type(tick)")).toBe(
				"functionfunction",
			);
		} finally {
			host.close();
		}
	});

	test("命令数の上限はコルーチンの中の無限ループも止める（error 行の文は lupa 側と同じ）", async () => {
		const host = await JinHost.create(game(true), WASM, 100_000);
		try {
			host.boot(3, MANIFEST);
			const result = host.tick(0, INPUTS);
			expect(result.done).toBe(true);
			expect(result.error).toBe(
				"命令数の上限 100000 を超えました（無限ループ？）",
			);
		} finally {
			host.close();
		}
	});

	test("boot / tick が無い JIL は HostError", async () => {
		await expect(
			JinHost.create("function boot() end", WASM),
		).rejects.toBeInstanceOf(HostError);
		await expect(
			JinHost.create("this is not lua", WASM),
		).rejects.toBeInstanceOf(HostError);
	});

	test("tick の戻り値が文字列でなければ HostError", async () => {
		const host = await JinHost.create(
			"function boot() end function tick() return 1 end",
			WASM,
		);
		try {
			expect(() => host.tick(0, INPUTS)).toThrow(HostError);
		} finally {
			host.close();
		}
	});
});
