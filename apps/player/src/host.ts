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
 */
import { LuaFactory, type LuaEngine } from "wasmoon";

import type { Inputs, Manifest, TickResult } from "./types";

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
export class JinHost {
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
			this.lua.global.call("boot", Math.trunc(seed), manifest);
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
