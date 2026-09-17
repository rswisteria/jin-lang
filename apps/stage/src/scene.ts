import {
	CORE_RADIUS,
	KIND_LAYERS,
	type LayerIndex,
	ringLayer,
	stepLayer,
} from "./layers";

/**
 * SVG（`jin_render` の出力）→ 場面の記述（docs/spec/v2/stage.md §1 / §2）。
 *
 * **配置を計算しない。** `viewBox` の中心を原点、半幅を `HALF_EXTENT` に写すだけで、
 * 座標・半径・文字の大きさは SVG に書かれた値から来る（y は上向きに反転）。
 */
export type Vec2 = readonly [number, number];

export type Shape =
	| { readonly type: "ring"; readonly center: Vec2; readonly radius: number }
	| {
			readonly type: "segments";
			readonly segments: readonly (readonly [Vec2, Vec2])[];
			readonly spoke: boolean;
	  }
	| { readonly type: "dot"; readonly center: Vec2; readonly radius: number }
	| {
			readonly type: "text";
			readonly at: Vec2;
			readonly size: number;
			readonly text: string;
	  };

export interface SceneItem {
	readonly pointer: string;
	readonly kind: string;
	readonly layer: LayerIndex;
	/** 属する陣の `<g data-jin-kind="circle">` の pointer。額縁と型紙の印章は null。 */
	readonly circle: string | null;
	/**
	 * 属する陣の単位（核の描かれた半径 / 0.12・stage.md §2）。高さはこれを掛ける。
	 * 陣に属さない要素（額縁）と核の無い陣は 1。
	 */
	readonly unit: number;
	readonly shape: Shape;
}

export interface Scene {
	readonly items: readonly SceneItem[];
	/** 場面にある pointer の集合（光らせる要素を祖先へ遡って探すのに使う・stage.md §3.1）。 */
	readonly pointers: ReadonlySet<string>;
}

export class SceneError extends Error {}

/** v2 layout.md §8 のキャンバス半幅。`viewBox` の半幅をこの値に写す。 */
export const HALF_EXTENT = 1.25;

const CIRCLE_GROUP = 'g[data-jin-kind="circle"]';

export function parseScene(svgText: string): Scene {
	const doc = new DOMParser().parseFromString(svgText, "image/svg+xml");
	const root = doc.documentElement;
	if (
		doc.getElementsByTagName("parsererror").length > 0 ||
		root.localName !== "svg"
	) {
		throw new SceneError("SVG として読めません");
	}
	const box = (root.getAttribute("viewBox") ?? "")
		.trim()
		.split(/[\s,]+/)
		.map(Number);
	const [minX, minY, width, height] = box;
	if (
		box.length !== 4 ||
		minX === undefined ||
		minY === undefined ||
		width === undefined ||
		height === undefined ||
		!box.every(Number.isFinite) ||
		width <= 0
	) {
		throw new SceneError("viewBox がありません");
	}
	const cx = minX + width / 2;
	const cy = minY + height / 2;
	const scale = width / 2 / HALF_EXTENT;
	// `+ 0` で `-0` を `0` に揃える（`jin_render` が `-0.0` を正規化しているのと同じ規律）。
	const point = (x: string | null, y: string | null): Vec2 => [
		(Number(x) - cx) / scale + 0,
		-(Number(y) - cy) / scale + 0,
	];
	const length = (value: string | null): number => Number(value) / scale;

	const units = new Map<Element, number>();
	const unitOf = (group: Element | null): number => {
		if (group === null) return 1;
		const cached = units.get(group);
		if (cached !== undefined) return cached;
		const core = [...group.children].find(
			(child) =>
				child.localName === "circle" &&
				child.getAttribute("data-jin-kind") === "core" &&
				!hasFill(child),
		);
		const unit =
			core === undefined ? 1 : length(core.getAttribute("r")) / CORE_RADIUS;
		units.set(group, unit);
		return unit;
	};

	const items: SceneItem[] = [];
	for (const element of root.querySelectorAll("[data-jin-kind]")) {
		if (element.localName === "g" || element.closest("defs") !== null) continue;
		const pointer = element.getAttribute("data-jin") ?? "";
		const kind = element.getAttribute("data-jin-kind") ?? "";
		const group = element.closest(CIRCLE_GROUP);
		const circle = group?.getAttribute("data-jin") ?? null;
		const shape = shapeOf(element, point, length);
		const unit = unitOf(group);
		const layer = layerOf(kind, pointer, shape, unit);
		items.push({ pointer, kind, layer, circle, unit, shape });
	}
	return { items, pointers: new Set(items.map((item) => item.pointer)) };
}

function hasFill(element: Element): boolean {
	const fill = element.getAttribute("fill");
	return fill !== null && fill !== "none";
}

function layerOf(
	kind: string,
	pointer: string,
	shape: Shape,
	unit: number,
): LayerIndex {
	if (kind === "circle" && shape.type === "ring")
		return ringLayer(shape.radius / unit);
	if (kind === "step" || kind === "step-edge") return stepLayer(pointer);
	return KIND_LAYERS[kind] ?? 1;
}

function shapeOf(
	element: Element,
	point: (x: string | null, y: string | null) => Vec2,
	length: (value: string | null) => number,
): Shape {
	switch (element.localName) {
		case "circle": {
			const center = point(
				element.getAttribute("cx"),
				element.getAttribute("cy"),
			);
			const radius = length(element.getAttribute("r"));
			return hasFill(element)
				? { type: "dot", center, radius }
				: { type: "ring", center, radius };
		}
		case "line":
			return {
				type: "segments",
				spoke: true,
				segments: [
					[
						point(element.getAttribute("x1"), element.getAttribute("y1")),
						point(element.getAttribute("x2"), element.getAttribute("y2")),
					],
				],
			};
		case "path":
			return {
				type: "segments",
				spoke: false,
				segments: pathSegments(element.getAttribute("d") ?? "", point),
			};
		case "text":
			return {
				type: "text",
				at: point(element.getAttribute("x"), element.getAttribute("y")),
				size: length(element.getAttribute("font-size")),
				text: element.textContent ?? "",
			};
		default:
			throw new SceneError(`未対応の要素: ${element.localName}`);
	}
}

/** 3 次ベジェは 12 本の線分に分ける（`jin_render` は円弧を 3 次ベジェで描き、`A` を使わない）。 */
const BEZIER_STEPS = 12;

function pathSegments(
	d: string,
	point: (x: string | null, y: string | null) => Vec2,
): (readonly [Vec2, Vec2])[] {
	const tokens = d.trim().split(/\s+/);
	const segments: (readonly [Vec2, Vec2])[] = [];
	let current: Vec2 | null = null;
	let start: Vec2 | null = null;
	let i = 0;
	const take = (): Vec2 => {
		const p = point(tokens[i] ?? null, tokens[i + 1] ?? null);
		i += 2;
		return p;
	};
	while (i < tokens.length) {
		const command = tokens[i++];
		if (command === "M") {
			current = take();
			start = current;
		} else if (command === "L" && current !== null) {
			const next = take();
			segments.push([current, next]);
			current = next;
		} else if (command === "C" && current !== null) {
			const [p1, p2, p3] = [take(), take(), take()];
			const from = current;
			let previous: Vec2 = from;
			for (let k = 1; k <= BEZIER_STEPS; k++) {
				const s = k / BEZIER_STEPS;
				const u = 1 - s;
				const at = (j: 0 | 1): number =>
					u * u * u * from[j] +
					3 * u * u * s * p1[j] +
					3 * u * s * s * p2[j] +
					s * s * s * p3[j];
				const next: Vec2 = [at(0), at(1)];
				segments.push([previous, next]);
				previous = next;
			}
			current = p3;
		} else if (command === "Z" && current !== null && start !== null) {
			segments.push([current, start]);
			current = start;
		} else {
			throw new SceneError(`未対応のパス命令: ${String(command)}`);
		}
	}
	return segments;
}
