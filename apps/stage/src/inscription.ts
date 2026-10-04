import type { Glow } from "./effects";
import type { GemId } from "./palette";
import { pathSegments, SceneError, svgFrame, type Vec2 } from "./scene";

/**
 * 銘環の帯（陣書き S7・docs/spec/v2/stage.md §2.2）。three を import しない純関数。
 *
 * 帯の SVG（`jin/renderSvg` の `inscription: true`）は**通常の図と同じ座標系**で、升がプログラムの銘文の順
 * （12 時から時計回り・内の周から外の周へ）に並んでいる。stage は升を置き直さず、`svgFrame` で写すだけ。
 * 升は欄の pointer を持ち、発火した行の pointer の配下の升が灯る（`bandLights`）。
 */
export interface BandCell {
	/** 帯の中の順（銘文を読む順）。 */
	readonly index: number;
	readonly pointer: string;
	readonly kind: string;
	readonly segments: readonly (readonly [Vec2, Vec2])[];
}

export interface Band {
	readonly cells: readonly BandCell[];
	readonly segmentCount: number;
}

/** 帯の面の高さ（層 1 = 外周の環と同じ面・stage.md §2.2）。 */
export const BAND_HEIGHT = 0;
/** 帯が巡る速さ（rad/秒・時計回り）。層の自転（毎秒 0.03 rad）より遅い。 */
export const BAND_SPIN_RAD_PER_SECOND = -0.02;
/** 読み上げ: 光の先頭が灯った升の列を端から端まで渡り切る、演出の進みの位置。 */
export const SWEEP_END = 0.6;
/** 先頭が通り過ぎた升に残る明るさ（演出の強さに対する比）。 */
export const AFTERGLOW = 0.35;
/** 先頭の幅（升の数）。灯った升の列の長さの割合と下限。 */
export const HEAD_RATIO = 0.08;
export const HEAD_MIN = 2;

export function parseInscription(svgText: string): Band {
	const { root, point } = svgFrame(svgText);
	const cells: BandCell[] = [];
	let segmentCount = 0;
	for (const element of root.querySelectorAll("path[data-jin-kind]")) {
		if (element.closest("defs") !== null) continue;
		const segments = pathSegments(element.getAttribute("d") ?? "", point);
		if (segments.length === 0) continue;
		cells.push({
			index: cells.length,
			pointer: element.getAttribute("data-jin") ?? "",
			kind: element.getAttribute("data-jin-kind") ?? "",
			segments,
		});
		segmentCount += segments.length;
	}
	if (cells.length === 0) throw new SceneError("銘環の帯に升がありません");
	return { cells, segmentCount };
}

/** 帯の回転（rad）。時刻だけで決まる。 */
export function bandSpin(seconds: number): number {
	return BAND_SPIN_RAD_PER_SECOND * seconds + 0;
}

/** pointer の配下（同じか `/` の段で下）の升の順。`/circles/2` は `/circles/20/…` を拾わない。 */
export function cellsUnder(band: Band, pointer: string): readonly number[] {
	const prefix = `${pointer}/`;
	return band.cells
		.filter(
			(cell) => cell.pointer === pointer || cell.pointer.startsWith(prefix),
		)
		.map((cell) => cell.index);
}

export interface CellLight {
	readonly level: number;
	readonly gem: GemId;
}

/**
 * 時刻の光（`glowsAt` の出力）→ 升ごとの明るさと宝玉。同じ升に重なれば強い方。
 *
 * 読み上げ: 灯る升の列（帯の順）を、光の先頭が進み `0` から `SWEEP_END` までに端から端へ渡る。先頭の升は演出の強さで、
 * 通り過ぎた升は `AFTERGLOW` 倍で残り、まだ来ていない升は暗い。陣の鼓動（`pulse`）は渡らず一様に灯す。
 */
export function bandLights(
	band: Band,
	glows: readonly Glow[],
	under: (pointer: string) => readonly number[] = (pointer) =>
		cellsUnder(band, pointer),
): ReadonlyMap<number, CellLight> {
	const lights = new Map<number, CellLight>();
	const put = (index: number, level: number, gem: GemId): void => {
		if (!(level > 0)) return;
		const current = lights.get(index);
		if (current === undefined || level > current.level)
			lights.set(index, { level, gem });
	};
	for (const glow of glows) {
		const indices = under(glow.inscribed);
		if (indices.length === 0) continue;
		if (glow.effect === "pulse") {
			for (const index of indices) put(index, glow.intensity, glow.gem);
			continue;
		}
		const head =
			(Math.min(glow.progress, SWEEP_END) / SWEEP_END) * (indices.length - 1);
		const width = Math.max(HEAD_MIN, indices.length * HEAD_RATIO);
		indices.forEach((index, k) => {
			const ahead = k - head;
			const shape =
				ahead > 0
					? Math.max(0, 1 - ahead / width)
					: Math.max(AFTERGLOW, 1 - -ahead / width);
			put(index, glow.intensity * shape, glow.gem);
		});
	}
	return lights;
}
