/**
 * ホスト境界の型（runtime.md §1 / §2 / §5 / §7 / §9）。
 *
 * ここに書く形はすべて **JSON を跨ぐ**（`tick` の戻り値は JSON 文字列、`.jinrec` は JSONL、
 * `game.manifest.json` はファイル）。Lua のテーブルは境界を越えない。
 */

/** 表示リスト / 音リストの 1 要素 `[op, ...args]`（abilities.md §2 / §5）。 */
export type Op = readonly [string, ...(string | number)[]];

/** `game.manifest.json`（`jin_wasm.codegen` が書く）。 */
export interface Manifest {
	readonly file: string;
	readonly stage: {
		readonly width: number;
		readonly height: number;
		readonly fps: number;
		readonly seed: number;
	};
	readonly namespaces: readonly string[];
	readonly assets: readonly {
		readonly name: string;
		readonly kind: string;
		readonly path: string;
	}[];
	readonly debug: boolean;
	readonly jil: string;
}

/** 入力イベント（runtime.md §1.1 / §7。`.jinrec` の行から `tick` を除いたもの）。 */
export type InputEvent =
	| { readonly kind: "key"; readonly name: string; readonly down: boolean }
	| {
			readonly kind: "pointer";
			readonly x: number;
			readonly y: number;
			readonly down: boolean;
	  };

/** `tick(t, inputs)` の `inputs`（runtime.md §1.1）。 */
export interface Inputs {
	readonly events: readonly InputEvent[];
	readonly keys: Readonly<Record<string, true>>;
	readonly pointer: {
		readonly x: number;
		readonly y: number;
		readonly down: boolean;
	};
}

/** トレース行（runtime.md §5）。プレイヤーは中を解釈せず親へ流すだけ。 */
export interface TraceRow {
	readonly seq: number;
	readonly tick: number;
	readonly circle: string | null;
	readonly kind: string;
	readonly name: string | null;
	readonly pointer: string;
	readonly input: unknown;
	readonly output: unknown;
}

/** `tick` の戻り値（runtime.md §2 / 設計書 §11 #22）。 */
export interface TickResult {
	readonly ops: readonly Op[];
	readonly audio: readonly Op[];
	readonly trace?: readonly TraceRow[];
	readonly done: boolean;
	readonly error: string | null;
	readonly public: Readonly<Record<string, unknown>>;
}

/** `--single` が `index.html` に埋める束（runtime.md §9）。 */
export interface SingleBundle {
	readonly jil: string;
	readonly manifest: Manifest;
	/** `wasmoon.wasm` の base64。 */
	readonly wasm: string;
}
