/**
 * 層（docs/spec/v2/stage.md §2）。**表の値は stage.md と等号**（`tests/contract/test_stage_contract.py`）。
 * ここは「どの層に置くか」だけを決め、座標は決めない。
 */
export type LayerIndex = 0 | 1 | 2 | 3 | 4 | 5;

/** 添字 = 層。外周 1 に対する高さ。 */
export const LAYER_HEIGHTS: readonly number[] = [
	-0.32, 0, 0.07, 0.14, 0.21, 0.28,
];

/** stage.md の `stage-layers`。`circle` / `step` / `step-edge` は形から決めるので載せない。 */
export const KIND_LAYERS: Readonly<Record<string, LayerIndex>> = {
	stage: 0,
	form: 0,
	on: 1,
	guard: 1,
	delegate: 1,
	state: 2,
	sigil: 3,
	"flow-edge": 3,
	rite: 4,
	core: 5,
};

/** stage.md の `stage-ring-layers`（半径は v2 layout.md の `ring-radii` と同じ値）。 */
export const RING_LAYERS: readonly (readonly [LayerIndex, number])[] = [
	[4, 0.35],
	[3, 0.55],
	[2, 0.75],
	[1, 0.95],
];

/** v2 layout.md §8 が v1 から継承する核の半径。陣の単位を核の描かれた半径から逆算するのに使う。 */
export const CORE_RADIUS = 0.12;

/** 陣の単位で測った輪の半径に、最も近い環の層。 */
export function ringLayer(ratio: number): LayerIndex {
	let best: readonly [LayerIndex, number] = RING_LAYERS[0] ?? [1, 0.95];
	for (const entry of RING_LAYERS) {
		if (Math.abs(entry[1] - ratio) < Math.abs(best[1] - ratio)) best = entry;
	}
	return best[0];
}

/** 手順の図のステップ: `steps` / `then` / `else` の段数 − 1 が深さ、層 = min(深さ, 3) + 1。 */
export function stepLayer(pointer: string): LayerIndex {
	const blocks = pointer.match(/\/(steps|then|else)\/\d+/g)?.length ?? 1;
	const depth = Math.min(Math.max(blocks - 1, 0), 3);
	return (depth + 1) as LayerIndex;
}
