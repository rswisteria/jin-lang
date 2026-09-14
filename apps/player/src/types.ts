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
	/**
	 * 状態を保った差し替え（runtime.md §1）: 直前の `tick` 結果の `snapshot` をそのまま渡すと、`boot` は
	 * 陣を名前で照合して状態を続ける。`game.manifest.json` には無く、プレイヤーが差し替えのときにだけ足す。
	 */
	readonly resume?: Snapshot;
	/**
	 * 記憶（`storage`・abilities.md §8・v2.1）: ホストが持つ内容の写し。`boot` のたびにプレイヤーが足す
	 * （`game.manifest.json` には無い）。鍵も値も文字列。
	 */
	readonly storage?: Readonly<Record<string, string>>;
}

/** 記憶への 1 件の書き込み `[key, val]`（`tick` の戻り値の `storage`・abilities.md §8）。 */
export type StorageWrite = readonly [string, string];

/**
 * DEBUG の `tick` 結果に載る、次の `boot` の `manifest.resume` へ**そのまま**渡す状態（runtime.md §1）。
 * プレイヤーは中を解釈しない（読むのは `tick` と `seed` だけ。形の検査は Lua 側の読み手が行う）。
 */
export interface Snapshot {
	readonly tick: number;
	readonly seed: number;
	readonly seq: number;
	readonly rng: string;
	readonly circles: readonly unknown[];
}

/** 差し替え直後の `tick` 結果に 1 回だけ載る、復元の知らせ（runtime.md §1）。 */
export interface ResumeNote {
	/** `resumed`: 名前で照合して続けた。`fresh`: root が照合できず通常の boot に落ちた。 */
	readonly mode: "resumed" | "fresh";
	readonly tick: number;
	readonly kept: readonly string[];
	readonly dropped: readonly string[];
}

/** 入力イベント（runtime.md §1.1 / §7。`.jinrec` の行から `tick` を除いたもの）。 */
export type InputEvent =
	| { readonly kind: "key"; readonly name: string; readonly down: boolean }
	| {
			readonly kind: "pointer";
			readonly x: number;
			readonly y: number;
			readonly down: boolean;
	  }
	/** 確定した文字列（abilities.md §3 の `input.text`・v2.1）。押下状態には触らない。 */
	| { readonly kind: "text"; readonly text: string };

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
	/** この tick の記憶への書き込み（あった tick だけ。release でも出る。abilities.md §8）。 */
	readonly storage?: readonly StorageWrite[];
	/** DEBUG だけ。次の `boot` に渡せば状態が続く（差し替え）。 */
	readonly snapshot?: Snapshot;
	/** DEBUG だけ。`manifest.resume` 付きで boot した直後の 1 回だけ。 */
	readonly resume?: ResumeNote;
}

/** `--single` が `index.html` に埋める束（runtime.md §9）。 */
export interface SingleBundle {
	readonly jil: string;
	readonly manifest: Manifest;
	/** `wasmoon.wasm` の base64。 */
	readonly wasm: string;
}
