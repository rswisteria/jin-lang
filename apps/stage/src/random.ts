/**
 * 決まった乱数（docs/spec/v2/stage.md §3.4）。演出の散り方は `seq` を種にしてここから作る。
 * 実行のたびに変わる標準の乱数（`Math` の `random`）は使わない（同じ入力から同じ場面の列を出すため・契約テストが禁止を見る）。
 */
export function mulberry32(seed: number): () => number {
	let state = seed >>> 0;
	return () => {
		state = (state + 0x6d2b79f5) >>> 0;
		let z = state;
		z = Math.imul(z ^ (z >>> 15), z | 1);
		z ^= z + Math.imul(z ^ (z >>> 7), z | 61);
		return ((z ^ (z >>> 14)) >>> 0) / 4294967296;
	};
}
