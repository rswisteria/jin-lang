/**
 * Wasmoon で JIL を走らせるホスト（runtime.md §1 / §8 / §10）。
 *
 * ## これは任意コード実行ではない
 *
 * JIL は `require` / `load` / `os` / `io` を持たない Lua の静的サブセット（jil.md §2）で、
 * Lua からホスト（JS）を呼ぶ口も無い。それでも多層防御として、JIL を読む**前**に次を行う
 * （`jin_wasm.runtime` と同じ順序。probe §A.8 / §A.10 の実測に基づく）:
 *
 * - `openStandardLibs: true` で作る（`false` は base ライブラリごと消える）
 * - `JIN_ARM` / `JIN_HOOK`（命令数の上限）を置く。`debug` を消す**前**に `sethook` を捕まえる
 * - `load` / `loadstring` / … / `debug` / `collectgarbage` を **`global.set(name, undefined)`** で消す
 *   （`null` は Wasmoon 1.16.0 で `TypeError` になり消えない）。`string.dump` も消す
 * - JIL を読んだ**後**に `JIN_ARM` / `JIN_HOOK` を消す（グローバルは `boot` / `tick` だけに戻る）
 *
 * ホストが呼ぶ Lua の関数は **`boot` / `tick` の 2 つだけ**で、`tick` の戻り値は JSON 文字列
 * 1 本を `JSON.parse` する。Lua のテーブルは境界を越えない。`Thread.setTimeout`（C の hook）は
 * コルーチンの中で PANIC するので使わない（probe §A.10）。
 *
 * JS → Lua の値は proxy の userdata で渡り、Lua が欄を読んだときに初めて JS の値が積まれる。
 * **JS の `null` は積めない**（`pushValue` が `TypeError` を投げ、Lua の中からだと PANIC で
 * エンジンごと落ちる。probe §A.11）。`manifest` に載る `snapshot`（状態を保った差し替え・
 * runtime.md §1）は核なし陣の `state` / `delegate` が `null` なので、`boot` に渡す前に
 * `null` を欄ごと落として `nil` に見せる（`withoutNulls`）。
 *
 * ## wasm-GC（`WasmGcHost`・jil.md §6.2・v2.1 Issue #53 / #76）
 *
 * `--target wasm-gc` の `game.wasm` は import を持たず（ホストを呼ばない）、export は `memory` / `input(n)` /
 * `boot(n)` / `tick(n) -> (ptr, len)` の 4 つ。引数も戻りも UTF-8 の JSON 1 本を線形メモリで越える:
 * `TextEncoder` で先にバイト列を作り → `input(n)` で入力域をもらい → **その後に** `memory.buffer` を取って書く
 * （`input` が `memory.grow` すると前の `ArrayBuffer` は detach される。probe A.5）→ `boot` / `tick` を呼ぶ →
 * `tick` の `(ptr, len)` を `TextDecoder` で読んで `JSON.parse`。結果は次の呼び出しまでしか有効でないので
 * 読み終えてから次を呼ぶ。実行時のエラーは module の中で `error` 行になって返るので、wasm の trap
 * （`WebAssembly.RuntimeError`）は生成系のバグであり `HostError` で止める。サンドボックスの手続きは無い
 * （消すグローバルも hook も無い。上限は module 内のカウンタ・jil.md §6.6）。
 * `Player` はどちらのホストかを知らない（`Host`）。
 */
import { LuaFactory, type LuaEngine } from "wasmoon";

import type { Inputs, Manifest, TickResult } from "./types";

/** `Player` が呼ぶホストの口（runtime.md §1）。Wasmoon の `JinHost` と wasm-GC の `WasmGcHost` が同じ形を持つ。 */
export interface Host {
	boot(seed: number, manifest: Manifest): void;
	tick(t: number, inputs: Inputs): TickResult;
	close(): void;
}

/** wasm-GC の module がホストに見せる export（jil.md §6.2。`jin_wasmgc.runtime.EXPORTS` と同じ 4 つ）。 */
export const WASMGC_EXPORTS: readonly string[] = [
	"memory",
	"input",
	"boot",
	"tick",
];

/** JIL を読む前に消すグローバル（runtime.md §8 / §10。`jin_wasm.runtime.SANDBOX_REMOVED` と同じ）。 */
export const SANDBOX_REMOVED: readonly string[] = [
	"load",
	"loadstring",
	"dofile",
	"loadfile",
	"require",
	"package",
	"os",
	"io",
	"debug",
	"collectgarbage",
];

/** プレリュードが読むホスト提供のグローバル（`jin_wasm.jil.HOST_HOOK_GLOBALS`）。読んだ後に消す。 */
export const HOST_HOOK_GLOBALS: readonly string[] = ["JIN_ARM", "JIN_HOOK"];

/**
 * JSON 由来の値から `null` を落とした写し（オブジェクトは欄ごと消し、配列は `undefined` で位置を保つ）。
 * Wasmoon は `null` を Lua に積めない（probe §A.11）。Lua 側の読み手は無い欄を `nil` として扱う。
 */
export function withoutNulls<T>(value: T): T {
	if (value === null) return undefined as T;
	if (Array.isArray(value)) return value.map(withoutNulls) as T;
	if (typeof value === "object") {
		const out: Record<string, unknown> = {};
		for (const [key, item] of Object.entries(value as object)) {
			if (item !== null) out[key] = withoutNulls(item);
		}
		return out as T;
	}
	return value;
}

/** 1 回の `boot` / `tick` の命令数の上限（`jin_wasm.runtime.INSTRUCTION_BUDGET` と同じ値）。 */
export const INSTRUCTION_BUDGET = 10_000_000;

/**
 * `JIN_ARM` / `JIN_HOOK` を置くチャンク。**`jin_wasm.runtime._SETUP` と同じ Lua**（文言も同じ。
 * `error` 行の文がホストで変わるとパリティが割れる）。チャンクは installer を返し、上限を渡して呼ぶ。
 */
export const HOOK_SETUP = `
local sethook = debug.sethook
return function(limit)
  local function over()
    error({ code = "budget", message = "命令数の上限 " .. limit .. " を超えました（無限ループ？）" }, 0)
  end
  JIN_ARM = function() sethook(over, "", limit) end
  JIN_HOOK = function(co) sethook(co, over, "", limit) end
end
`;

export class HostError extends Error {
	override readonly name = "HostError";
}

function message(error: unknown): string {
	if (error instanceof Error) return error.message.split("\n", 1)[0] ?? "";
	return String(error);
}

/** 1 本の JIL を読み、`boot` / `tick` だけを呼ぶ。 */
export class JinHost implements Host {
	private constructor(private readonly lua: LuaEngine) {}

	/**
	 * @param jil `game.lua` の中身
	 * @param wasmUri `wasmoon.wasm` の URL（相対パスか `data:` URL）。**省略できない**:
	 *   `new LuaFactory()` を引数無しで呼ぶと unpkg へ fetch しに行く（probe §A.10）
	 */
	static async create(
		jil: string,
		wasmUri: string,
		budget = INSTRUCTION_BUDGET,
	): Promise<JinHost> {
		const lua = await new LuaFactory(wasmUri).createEngine({
			openStandardLibs: true,
		});
		try {
			// installer は Lua の中で呼ぶ（JS に包んだ Lua 関数は別スレッドで走りうる。probe §A.10）。
			lua.doStringSync(
				`(function() ${HOOK_SETUP} end)()(${Math.trunc(budget)})`,
			);
			for (const name of SANDBOX_REMOVED) {
				lua.global.set(name, undefined);
			}
			lua.doStringSync("string.dump = nil");
			try {
				lua.doStringSync(jil);
			} catch (error) {
				throw new HostError(`JIL を読めません: ${message(error)}`);
			} finally {
				for (const name of HOST_HOOK_GLOBALS) {
					lua.global.set(name, undefined);
				}
			}
			const entry: unknown = lua.doStringSync(
				'return type(boot) == "function" and type(tick) == "function"',
			);
			if (entry !== true) {
				throw new HostError("JIL に関数 boot / tick がありません");
			}
			return new JinHost(lua);
		} catch (error) {
			lua.global.close();
			throw error;
		}
	}

	boot(seed: number, manifest: Manifest): void {
		try {
			this.lua.global.call("boot", Math.trunc(seed), withoutNulls(manifest));
		} catch (error) {
			throw new HostError(`boot に失敗しました: ${message(error)}`);
		}
	}

	tick(t: number, inputs: Inputs): TickResult {
		let returned: unknown[];
		try {
			returned = this.lua.global.call("tick", Math.trunc(t), inputs);
		} catch (error) {
			throw new HostError(`tick ${t} に失敗しました: ${message(error)}`);
		}
		const text = returned[0];
		if (typeof text !== "string") {
			throw new HostError(
				`tick ${t} の戻り値が文字列ではありません（${typeof text}）`,
			);
		}
		try {
			return JSON.parse(text) as TickResult;
		} catch (error) {
			throw new HostError(
				`tick ${t} の戻り値を JSON として読めません: ${message(error)}`,
			);
		}
	}

	/** テスト用: Lua の式を評価する（JIL とは無関係の固定文字列だけを渡す）。 */
	evalForTest(expression: string): unknown {
		return this.lua.doStringSync(`return ${expression}`);
	}

	close(): void {
		this.lua.global.close();
	}
}

interface WasmGcExports {
	readonly memory: WebAssembly.Memory;
	input(n: number): number;
	boot(n: number): void;
	tick(n: number): unknown;
}

/** 1 本の `game.wasm` を instantiate し、`boot` / `tick` を JSON の詰め替えで呼ぶ（jil.md §6.2）。 */
export class WasmGcHost implements Host {
	private readonly encoder = new TextEncoder();
	private readonly decoder = new TextDecoder("utf-8", { fatal: true });

	private constructor(private readonly exports: WasmGcExports) {}

	/** @param game `game.wasm` のバイト列（fetch の `arrayBuffer()` か、`--single` の base64 を戻したもの） */
	static async create(game: BufferSource): Promise<WasmGcHost> {
		let instance: WebAssembly.Instance;
		try {
			// import は空（module はホストを呼ばない・jil.md §6.2）。CompileError / LinkError もここで受ける
			({ instance } = await WebAssembly.instantiate(game, {}));
		} catch (error) {
			throw new HostError(`game.wasm を読めません: ${message(error)}`);
		}
		const exports = instance.exports as Record<string, unknown>;
		const missing = WASMGC_EXPORTS.filter((name) => !(name in exports));
		if (missing.length > 0) {
			throw new HostError(
				`game.wasm に export ${missing.join(" / ")} がありません（jil.md §6.2）`,
			);
		}
		if (
			!(exports["memory"] instanceof WebAssembly.Memory) ||
			typeof exports["input"] !== "function" ||
			typeof exports["boot"] !== "function" ||
			typeof exports["tick"] !== "function"
		) {
			throw new HostError(
				"game.wasm の export memory / input / boot / tick の形が違います（jil.md §6.2）",
			);
		}
		return new WasmGcHost(exports as unknown as WasmGcExports);
	}

	/**
	 * JSON を入力域に書いて `fn(n)` を呼ぶ。バイト列を先に作り、`input(n)` の**後**に `memory.buffer` を取る
	 * （`input` が `memory.grow` すると前の buffer は detach される。probe A.5）。
	 */
	private call<T>(fn: (n: number) => T, payload: unknown, label: string): T {
		const bytes = this.encoder.encode(JSON.stringify(payload));
		try {
			const ptr = this.exports.input(bytes.length);
			new Uint8Array(this.exports.memory.buffer, ptr, bytes.length).set(bytes);
			return fn(bytes.length);
		} catch (error) {
			throw new HostError(`${label} に失敗しました: ${message(error)}`);
		}
	}

	boot(seed: number, manifest: Manifest): void {
		this.call(this.exports.boot, { seed: Math.trunc(seed), manifest }, "boot");
	}

	tick(t: number, inputs: Inputs): TickResult {
		const returned = this.call(
			this.exports.tick,
			{ t: Math.trunc(t), inputs },
			`tick ${t}`,
		);
		if (
			!Array.isArray(returned) ||
			returned.length !== 2 ||
			!returned.every((v) => Number.isInteger(v) && v >= 0)
		) {
			throw new HostError(
				`tick ${t} の戻り値が (先頭, 長さ) ではありません（${JSON.stringify(returned)}）`,
			);
		}
		const [ptr, length] = returned as [number, number];
		let text: string;
		try {
			text = this.decoder.decode(
				new Uint8Array(this.exports.memory.buffer, ptr, length),
			);
		} catch (error) {
			throw new HostError(
				`tick ${t} の戻り値を UTF-8 として読めません: ${message(error)}`,
			);
		}
		try {
			return JSON.parse(text) as TickResult;
		} catch (error) {
			throw new HostError(
				`tick ${t} の戻り値を JSON として読めません: ${message(error)}`,
			);
		}
	}

	/** 手放すだけ（instance は GC に任せる）。 */
	close(): void {}
}
