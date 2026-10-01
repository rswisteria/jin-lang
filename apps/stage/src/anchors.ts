import type { LayerIndex } from "./layers";
import type { Scene, SceneItem, Vec2 } from "./scene";

/**
 * 宝玉の置き場所（仕様書 docs/superpowers/specs/2026-10-01-jin-stage-gem-worldview-design.md §3.1）。
 *
 * **配置を計算しない。** 場面の要素（SVG に描かれた形）から、pointer ごとに中心と大きさを読むだけ。
 * 輪を持つ要素（核など）は最大の輪の中心と半径、輪の無い要素は線と点の外接矩形の中心と長辺の半分。文字は見ない。
 */
export interface Anchor {
	readonly pointer: string;
	readonly kind: string;
	readonly center: Vec2;
	readonly radius: number;
	readonly layer: LayerIndex;
	readonly unit: number;
	readonly circle: string | null;
}

/** 宝玉をはめる種別。 */
export const GEM_KINDS: ReadonlySet<string> = new Set([
	"sigil",
	"state",
	"core",
	"on",
	"guard",
	"delegate",
]);

function anchorOf(items: readonly SceneItem[]): Anchor | null {
	const first = items[0];
	if (first === undefined) return null;
	let ring: { center: Vec2; radius: number } | null = null;
	let minX = Number.POSITIVE_INFINITY;
	let minY = Number.POSITIVE_INFINITY;
	let maxX = Number.NEGATIVE_INFINITY;
	let maxY = Number.NEGATIVE_INFINITY;
	const extend = (x: number, y: number): void => {
		minX = Math.min(minX, x);
		minY = Math.min(minY, y);
		maxX = Math.max(maxX, x);
		maxY = Math.max(maxY, y);
	};
	for (const { shape } of items) {
		if (shape.type === "ring") {
			if (ring === null || shape.radius > ring.radius)
				ring = { center: shape.center, radius: shape.radius };
		} else if (shape.type === "dot") {
			extend(shape.center[0] - shape.radius, shape.center[1] - shape.radius);
			extend(shape.center[0] + shape.radius, shape.center[1] + shape.radius);
		} else if (shape.type === "segments") {
			for (const [a, b] of shape.segments) {
				extend(a[0], a[1]);
				extend(b[0], b[1]);
			}
		}
	}
	const base = {
		pointer: first.pointer,
		kind: first.kind,
		layer: first.layer,
		unit: first.unit,
		circle: first.circle,
	};
	if (ring !== null)
		return { ...base, center: ring.center, radius: ring.radius };
	if (!Number.isFinite(minX)) return null;
	const radius = Math.max(maxX - minX, maxY - minY) / 2;
	if (!(radius > 0)) return null;
	return { ...base, center: [(minX + maxX) / 2, (minY + maxY) / 2], radius };
}

/** 場面の中の宝玉の置き場所（pointer ごとに 1 つ・場面の並び順）。 */
export function anchorsOf(scene: Scene): readonly Anchor[] {
	const groups = new Map<string, SceneItem[]>();
	for (const item of scene.items) {
		if (!GEM_KINDS.has(item.kind)) continue;
		const list = groups.get(item.pointer) ?? [];
		list.push(item);
		groups.set(item.pointer, list);
	}
	const anchors: Anchor[] = [];
	for (const items of groups.values()) {
		const anchor = anchorOf(items);
		if (anchor !== null) anchors.push(anchor);
	}
	return anchors;
}
