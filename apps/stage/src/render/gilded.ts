import * as THREE from "three";
import { LineMaterial } from "three/addons/lines/LineMaterial.js";
import { LineSegments2 } from "three/addons/lines/LineSegments2.js";
import { LineSegmentsGeometry } from "three/addons/lines/LineSegmentsGeometry.js";

import { LAYER_HEIGHTS, type LayerIndex, layerHeight } from "../layers";
import type { Scene, SceneItem, Vec2 } from "../scene";

/**
 * Scene → 金環（docs/spec/v2/stage.md §2・設計書 §2.1）。**座標は Scene のまま**使い、
 * 決めるのは層の高さ・素材・意味を持たない飾り（輪の外の目盛り）だけ。
 *
 * 陣の面は root の局所 XY。root を x 軸まわりに −90° 回して、世界では y = 0 の床に寝かせる
 * （局所 z = 層の高さ → 世界の +y）。
 *
 * 層の group は**陣ごと**に 6 つ持ち、高さは層の値 × その陣の単位（`layerHeight`）。
 * 入れ子の小陣を root と同じ高さで積むと、幅と同じ高さの塔になる。
 */
export const GOLD = new THREE.Color(0xc8943a);
export const GOLD_LINE = new THREE.Color(0xd9a54f);
export const GOLD_DIM = new THREE.Color(0x5a3c16);
export const GOLD_HOT = new THREE.Color(0xfff0c8);
export const WARN_RED = new THREE.Color(0xff2a2a);
const EMBER = new THREE.Color(0xffb35a);

const RING_TUBE = 0.009;
const SMALL_RING_TUBE = 0.005;
const LINE_WIDTH_PX = 1.4;
/** 光っていないときの自発光。低いほど環境マップの映り込み（金属の陰影）が見える。 */
export const BASE_EMISSIVE = 0.12;

export interface Glowable {
	readonly material: THREE.MeshStandardMaterial | LineMaterial | THREE.SpriteMaterial;
	readonly base: THREE.Color;
}

export interface ItemHandle {
	readonly item: SceneItem;
	readonly glowables: readonly Glowable[];
	/** 層の座標系での中心（光線と火花の端点）。 */
	readonly center: THREE.Vector3;
}

/** 1 つの陣（額縁など陣に属さない要素は key ""）の層。 */
export interface CircleLayers {
	readonly unit: number;
	/** 添字 = 層。`position.z` の基準は `layerHeight(層, unit)`。 */
	readonly layers: readonly THREE.Group[];
}

/** 陣に属さない要素の key。 */
export const NO_CIRCLE = "";

export interface GildedModel {
	readonly root: THREE.Group;
	/** key = 陣の pointer（`SceneItem.circle`）。 */
	readonly circles: ReadonlyMap<string, CircleLayers>;
	readonly handles: ReadonlyMap<string, readonly ItemHandle[]>;
	readonly tickers: readonly { readonly group: THREE.Group; readonly speed: number }[];
	readonly lineMaterials: readonly LineMaterial[];
	/** 光線・火花を載せる、root の局所座標の group。 */
	readonly effects: THREE.Group;
	dispose(): void;
}

export function buildGilded(scene: Scene): GildedModel {
	const root = new THREE.Group();
	root.rotation.x = -Math.PI / 2;
	const circles = new Map<string, CircleLayers>();
	const layersOf = (item: SceneItem): readonly THREE.Group[] => {
		const key = item.circle ?? NO_CIRCLE;
		const existing = circles.get(key);
		if (existing !== undefined) return existing.layers;
		const layers = LAYER_HEIGHTS.map((_, i) => {
			const group = new THREE.Group();
			group.position.z = layerHeight(i as LayerIndex, item.unit);
			root.add(group);
			return group;
		});
		circles.set(key, { unit: item.unit, layers });
		return layers;
	};
	const effects = new THREE.Group();
	root.add(effects);
	const handles = new Map<string, ItemHandle[]>();
	const tickers: { group: THREE.Group; speed: number }[] = [];
	const lineMaterials: LineMaterial[] = [];
	const disposables: { dispose(): void }[] = [];

	const lineMaterial = (color: THREE.Color): LineMaterial => {
		const material = new LineMaterial({ color: color.getHex(), linewidth: LINE_WIDTH_PX });
		lineMaterials.push(material);
		disposables.push(material);
		return material;
	};
	const metal = (color: THREE.Color): THREE.MeshStandardMaterial => {
		const material = new THREE.MeshStandardMaterial({
			color,
			metalness: 1,
			roughness: 0.3,
			emissive: color,
			emissiveIntensity: BASE_EMISSIVE,
		});
		disposables.push(material);
		return material;
	};
	const segmentsObject = (segments: readonly (readonly [Vec2, Vec2])[], material: LineMaterial): LineSegments2 => {
		const geometry = new LineSegmentsGeometry();
		geometry.setPositions(segments.flatMap(([a, b]) => [a[0], a[1], 0, b[0], b[1], 0]));
		disposables.push(geometry);
		return new LineSegments2(geometry, material);
	};

	for (const item of scene.items) {
		const layer = layersOf(item)[item.layer];
		if (layer === undefined) continue;
		const z = layerHeight(item.layer, item.unit);
		const dim = item.layer === 0;
		const glowables: Glowable[] = [];
		let center: THREE.Vector3;
		const shape = item.shape;
		if (shape.type === "ring") {
			const tube = item.kind === "circle" ? RING_TUBE : SMALL_RING_TUBE;
			const material = metal(dim ? GOLD_DIM : GOLD);
			const geometry = new THREE.TorusGeometry(shape.radius, tube, 12, Math.max(48, Math.round(shape.radius * 320)));
			disposables.push(geometry);
			const mesh = new THREE.Mesh(geometry, material);
			mesh.position.set(shape.center[0], shape.center[1], 0);
			layer.add(mesh);
			glowables.push({ material, base: material.color.clone() });
			center = new THREE.Vector3(shape.center[0], shape.center[1], z);
			if (item.kind === "circle") tickers.push(ticker(layer, shape.center, shape.radius, item.layer, lineMaterial, disposables));
		} else if (shape.type === "segments") {
			const color = dim ? GOLD_DIM : shape.spoke ? GOLD_DIM.clone().lerp(GOLD_LINE, 0.6) : GOLD_LINE;
			const material = lineMaterial(color);
			layer.add(segmentsObject(shape.segments, material));
			glowables.push({ material, base: color.clone() });
			center = midpoint(shape.segments, z);
		} else if (shape.type === "dot") {
			const material = metal(GOLD);
			const geometry = new THREE.SphereGeometry(shape.radius, 16, 12);
			disposables.push(geometry);
			const mesh = new THREE.Mesh(geometry, material);
			mesh.position.set(shape.center[0], shape.center[1], shape.radius);
			layer.add(mesh);
			glowables.push({ material, base: material.color.clone() });
			center = new THREE.Vector3(shape.center[0], shape.center[1], z);
		} else {
			const texture = glyph(shape.text, dim ? GOLD_DIM : GOLD_HOT);
			const material = new THREE.SpriteMaterial({ map: texture, transparent: true, depthWrite: false });
			// `Material.dispose()` は `map` を解放しないので、テクスチャも自分で解放する（stage.scene は編集のたびに届く）。
			disposables.push(texture, material);
			const sprite = new THREE.Sprite(material);
			const aspect = shape.text.length > 1 ? 4 : 1;
			sprite.scale.set(shape.size * 1.6 * aspect, shape.size * 1.6, 1);
			sprite.position.set(shape.at[0], shape.at[1], 0.01);
			layer.add(sprite);
			glowables.push({ material, base: new THREE.Color(1, 1, 1) });
			center = new THREE.Vector3(shape.at[0], shape.at[1], z);
		}
		const list = handles.get(item.pointer) ?? [];
		list.push({ item, glowables, center });
		handles.set(item.pointer, list);
	}

	return {
		root,
		circles,
		handles,
		tickers,
		lineMaterials,
		effects,
		dispose: () => {
			for (const d of disposables) d.dispose();
		},
	};
}

function midpoint(segments: readonly (readonly [Vec2, Vec2])[], z: number): THREE.Vector3 {
	const sum = new THREE.Vector3();
	for (const [a, b] of segments) sum.add(new THREE.Vector3((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, 0));
	return sum.multiplyScalar(1 / Math.max(segments.length, 1)).setZ(z);
}

/** 意味を持たない飾り: 輪の外側の目盛り（輪の半径だけから作る・設計書 §2.1）。 */
function ticker(
	layer: THREE.Group,
	center: Vec2,
	radius: number,
	layerIndex: number,
	lineMaterial: (color: THREE.Color) => LineMaterial,
	disposables: { dispose(): void }[],
): { group: THREE.Group; speed: number } {
	const count = Math.max(24, Math.round(radius * 72));
	const segments: number[] = [];
	for (let k = 0; k < count; k++) {
		const angle = (k / count) * Math.PI * 2;
		const inner = radius + 0.014;
		const outer = inner + (k % 6 === 0 ? 0.03 : 0.012);
		segments.push(Math.cos(angle) * inner, Math.sin(angle) * inner, 0, Math.cos(angle) * outer, Math.sin(angle) * outer, 0);
	}
	const geometry = new LineSegmentsGeometry();
	geometry.setPositions(segments);
	disposables.push(geometry);
	const group = new THREE.Group();
	group.position.set(center[0], center[1], 0);
	group.add(new LineSegments2(geometry, lineMaterial(GOLD_DIM)));
	layer.add(group);
	return { group, speed: ((layerIndex % 2 === 0 ? 1 : -1) * 0.05) / Math.max(radius, 0.3) };
}

/** SVG の文字をそのままテクスチャにする（ルーン文字のグリフフォントは別件・設計書 §2.1）。 */
function glyph(text: string, color: THREE.Color): THREE.CanvasTexture {
	const wide = text.length > 1;
	const canvas = document.createElement("canvas");
	canvas.width = wide ? 512 : 128;
	canvas.height = 128;
	const context = canvas.getContext("2d");
	if (context !== null) {
		context.fillStyle = `#${color.getHexString()}`;
		context.font = `600 ${wide ? 72 : 84}px "Times New Roman", serif`;
		context.textAlign = "center";
		context.textBaseline = "middle";
		context.fillText(text, canvas.width / 2, 70);
	}
	const texture = new THREE.CanvasTexture(canvas);
	texture.colorSpace = THREE.SRGBColorSpace;
	return texture;
}

export { EMBER };
