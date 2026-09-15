// @vitest-environment node
import { createRequire } from "node:module";

import { describe as group, expect, test } from "vitest";

import {
	HOST_HOOK_GLOBALS,
	HostError,
	JinHost,
	SANDBOX_REMOVED,
	WASMGC_EXPORTS,
	WasmGcHost,
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

/**
 * `WasmGcHost`（jil.md §6.2）を実際の `WebAssembly` で通す（Python の生成物は読まない）。module は
 * `wasmtime.wat2wasm` で 1 回だけ作ったバイト列を貼ってある（WAT はコメント）。
 *
 * ECHO: `input(n)` が**毎回** `memory.grow 1` して新しいページの先頭を返す（前の `memory.buffer` は毎回
 * detach される）。`tick(n)` は入力域 `(ptr, n)` をそのまま返す（echo）ので、書いた JSON が読み戻せれば
 * 「書く直前に buffer を取り直す」ことまで含めて配管全体が確かめられる。
 *
 *   (module
 *     (memory (export "memory") 1)
 *     (global $ptr (mut i32) (i32.const 0))
 *     (func (export "input") (param $n i32) (result i32)
 *       (global.set $ptr (i32.mul (memory.grow (i32.const 1)) (i32.const 65536)))
 *       (global.get $ptr))
 *     (func (export "boot") (param $n i32))
 *     (func (export "tick") (param $n i32) (result i32 i32)
 *       (global.get $ptr) (local.get $n)))
 */
const ECHO = new Uint8Array([
	0x00, 0x61, 0x73, 0x6d, 0x01, 0x00, 0x00, 0x00, 0x01, 0x10, 0x03, 0x60, 0x01,
	0x7f, 0x01, 0x7f, 0x60, 0x01, 0x7f, 0x00, 0x60, 0x01, 0x7f, 0x02, 0x7f, 0x7f,
	0x03, 0x04, 0x03, 0x00, 0x01, 0x02, 0x05, 0x03, 0x01, 0x00, 0x01, 0x06, 0x06,
	0x01, 0x7f, 0x01, 0x41, 0x00, 0x0b, 0x07, 0x20, 0x04, 0x06, 0x6d, 0x65, 0x6d,
	0x6f, 0x72, 0x79, 0x02, 0x00, 0x05, 0x69, 0x6e, 0x70, 0x75, 0x74, 0x00, 0x00,
	0x04, 0x62, 0x6f, 0x6f, 0x74, 0x00, 0x01, 0x04, 0x74, 0x69, 0x63, 0x6b, 0x00,
	0x02, 0x0a, 0x1b, 0x03, 0x0f, 0x00, 0x41, 0x01, 0x40, 0x00, 0x41, 0x80, 0x80,
	0x04, 0x6c, 0x24, 0x00, 0x23, 0x00, 0x0b, 0x02, 0x00, 0x0b, 0x06, 0x00, 0x23,
	0x00, 0x20, 0x00, 0x0b,
]);

/**
 * TRAP: `tick` が `unreachable`（生成系のバグの形）。
 *
 *   (module
 *     (memory (export "memory") 1)
 *     (func (export "input") (param $n i32) (result i32) (i32.const 0))
 *     (func (export "boot") (param $n i32))
 *     (func (export "tick") (param $n i32) (result i32 i32) (unreachable)))
 */
const TRAP = new Uint8Array([
	0x00, 0x61, 0x73, 0x6d, 0x01, 0x00, 0x00, 0x00, 0x01, 0x10, 0x03, 0x60, 0x01,
	0x7f, 0x01, 0x7f, 0x60, 0x01, 0x7f, 0x00, 0x60, 0x01, 0x7f, 0x02, 0x7f, 0x7f,
	0x03, 0x04, 0x03, 0x00, 0x01, 0x02, 0x05, 0x03, 0x01, 0x00, 0x01, 0x07, 0x20,
	0x04, 0x06, 0x6d, 0x65, 0x6d, 0x6f, 0x72, 0x79, 0x02, 0x00, 0x05, 0x69, 0x6e,
	0x70, 0x75, 0x74, 0x00, 0x00, 0x04, 0x62, 0x6f, 0x6f, 0x74, 0x00, 0x01, 0x04,
	0x74, 0x69, 0x63, 0x6b, 0x00, 0x02, 0x0a, 0x0d, 0x03, 0x04, 0x00, 0x41, 0x00,
	0x0b, 0x02, 0x00, 0x0b, 0x03, 0x00, 0x00, 0x0b,
]);

group("WasmGcHost（実際の WebAssembly）", () => {
	test("export は jil.md §6.2 の 4 つ", () => {
		expect(WASMGC_EXPORTS).toEqual(["memory", "input", "boot", "tick"]);
	});

	test("JSON を線形メモリで往復し、memory.grow で detach した buffer に書かない", async () => {
		const host = await WasmGcHost.create(ECHO);
		try {
			host.boot(7, { ...MANIFEST, target: "wasm-gc" });
			// tick は入力域をそのまま返すので、結果 = 書いた JSON（毎回 grow する module で 3 回）
			for (let t = 0; t < 3; t += 1) {
				const echoed = host.tick(t, INPUTS) as unknown as {
					t: number;
					inputs: typeof INPUTS;
				};
				expect(echoed).toEqual({ t, inputs: INPUTS });
			}
			// 非 ASCII も UTF-8 のバイト数で書いて読み戻す
			const text = { ...INPUTS, events: [{ kind: "text" as const, text: "日本😀" }] };
			expect(host.tick(3, text)).toEqual({ t: 3, inputs: text });
		} finally {
			host.close();
		}
	});

	test("trap は HostError（生成系のバグとして止める・パリティの対象外）", async () => {
		const host = await WasmGcHost.create(TRAP);
		try {
			host.boot(1, MANIFEST);
			expect(() => host.tick(0, INPUTS)).toThrow(HostError);
			expect(() => host.tick(0, INPUTS)).toThrow(/tick 0 に失敗しました/);
		} finally {
			host.close();
		}
	});

	test("読めない / export の欠けた module は HostError", async () => {
		await expect(
			WasmGcHost.create(new Uint8Array([0, 1, 2, 3])),
		).rejects.toBeInstanceOf(HostError);
		// export を持たない module（magic + version + 空）
		const empty = new Uint8Array([0x00, 0x61, 0x73, 0x6d, 0x01, 0x00, 0x00, 0x00]);
		await expect(WasmGcHost.create(empty)).rejects.toThrow(/memory \/ input \/ boot \/ tick/);
	});
});
