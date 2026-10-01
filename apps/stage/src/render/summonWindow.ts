import * as THREE from "three";

import { GEMS } from "../palette";
import { drawOps } from "../screen/draw";
import type { ScreenFrame, WindowState } from "../screen/frames";

/**
 * 召喚の窓（仕様書 docs/superpowers/specs/2026-10-01-jin-stage-summon-design.md §1）。陣の核の上空に、トレースの
 * `frame` 行の表示リスト（ゲーム画面）をドットのまま映す光の窓。世界座標に置き、常にカメラを向く（ビルボード）。
 * 場面が変わっても作り直さず、`setStage` で舞台の大きさと裏の 2D キャンバスだけを差し替える。
 */
export const WINDOW = {
	/** 板の幅（世界座標）。高さは舞台の縦横比から。 */
	width: 1.0,
	/** 窓の下端の高さ（世界の y）。 */
	base: 0.7,
	/** カメラから見て陣の奥へ寄せる量。 */
	back: 0.35,
	/** 窓があるときに陣を収める半径（camera.ts の FIT_RADIUS 1.45 から広げる）。 */
	fitRadius: 1.9,
	/** 窓が開いたときにカメラの注視点を上げる量（窓と陣の両方を収める）。 */
	lookUp: 0.5,
	/** 縁の光の板の大きさ（画面に対する比）。 */
	glow: 1.14,
	/** 金細工の枠の太さ（世界座標）。 */
	frame: 0.014,
} as const;

const EDGE_VERTEX = /* glsl */ `
varying vec2 vUv;
void main() {
	vUv = uv;
	gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}`;

/** 内側の矩形（画面）の外にだけ、距離で減衰する光（縁の光）。 */
const EDGE_FRAGMENT = /* glsl */ `
uniform vec3 tint;
uniform float strength;
uniform vec2 inner;
varying vec2 vUv;
void main() {
	vec2 d = max(abs(vUv - 0.5) - inner, 0.0);
	float outside = length(d);
	if (outside <= 0.0) discard;
	float a = strength * exp(-outside * 38.0);
	gl_FragColor = vec4(tint * a, a);
}`;

const SAPPHIRE = new THREE.Color(GEMS.sapphire.color);
const AMETHYST = new THREE.Color(GEMS.amethyst.color);
const GARNET = new THREE.Color(GEMS.garnet.color);
const WHITE = new THREE.Color(1, 1, 1);

export class SummonWindow {
	readonly object = new THREE.Group();
	private readonly panel: THREE.Mesh<
		THREE.PlaneGeometry,
		THREE.MeshBasicMaterial
	>;
	private readonly edge: THREE.Mesh<THREE.PlaneGeometry, THREE.ShaderMaterial>;
	private readonly bars: readonly THREE.Mesh<
		THREE.BoxGeometry,
		THREE.MeshStandardMaterial
	>[];
	private readonly barMaterial: THREE.MeshStandardMaterial;
	private readonly beam: THREE.Mesh<
		THREE.CylinderGeometry,
		THREE.MeshBasicMaterial
	>;
	private canvas: HTMLCanvasElement | null = null;
	private texture: THREE.CanvasTexture | null = null;
	private size: { readonly width: number; readonly height: number } | null =
		null;
	private drawn: ScreenFrame | null = null;
	private readonly tint = new THREE.Color();
	private readonly flat = new THREE.Vector3();

	constructor() {
		this.panel = new THREE.Mesh(
			new THREE.PlaneGeometry(1, 1),
			new THREE.MeshBasicMaterial({
				color: 0xffffff,
				toneMapped: false,
				transparent: true,
			}),
		);
		this.edge = new THREE.Mesh(
			new THREE.PlaneGeometry(1, 1),
			new THREE.ShaderMaterial({
				uniforms: {
					tint: { value: new THREE.Color() },
					strength: { value: 0 },
					inner: { value: new THREE.Vector2(0.44, 0.44) },
				},
				vertexShader: EDGE_VERTEX,
				fragmentShader: EDGE_FRAGMENT,
				transparent: true,
				depthWrite: false,
				blending: THREE.AdditiveBlending,
			}),
		);
		this.edge.position.z = -0.002;
		this.barMaterial = new THREE.MeshStandardMaterial({
			metalness: 1,
			roughness: 0.3,
		});
		this.bars = Array.from(
			{ length: 4 },
			() => new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), this.barMaterial),
		);
		this.beam = new THREE.Mesh(
			new THREE.CylinderGeometry(0.006, 0.006, 1, 8, 1, true),
			new THREE.MeshBasicMaterial({
				color: GEMS.sapphire.color,
				transparent: true,
				depthWrite: false,
				blending: THREE.AdditiveBlending,
			}),
		);
		this.object.add(this.edge, this.panel, ...this.bars);
		this.object.visible = false;
		this.beam.visible = false;
	}

	/** 光の柱（核から窓へ）は世界座標の別の物として持つ（窓はカメラを向いて回るので）。 */
	get beamObject(): THREE.Object3D {
		return this.beam;
	}

	/** 舞台の大きさ（論理解像度）と枠の地金。null なら窓を出さない。裏のキャンバスとテクスチャを作り直す（前の分は解放）。 */
	setStage(
		size: { readonly width: number; readonly height: number } | null,
		frameColor: number,
	): void {
		this.texture?.dispose();
		this.texture = null;
		this.canvas = null;
		this.drawn = null;
		this.size = size;
		this.barMaterial.color.setHex(frameColor);
		if (size === null) {
			this.panel.material.map = null;
			this.panel.material.needsUpdate = true;
			return;
		}
		const canvas = document.createElement("canvas");
		canvas.width = size.width;
		canvas.height = size.height;
		const texture = new THREE.CanvasTexture(canvas);
		texture.magFilter = THREE.NearestFilter;
		texture.minFilter = THREE.NearestFilter;
		texture.generateMipmaps = false;
		texture.colorSpace = THREE.SRGBColorSpace;
		this.canvas = canvas;
		this.texture = texture;
		this.panel.material.map = texture;
		this.panel.material.needsUpdate = true;
		const height = (WINDOW.width * size.height) / size.width;
		this.panel.scale.set(WINDOW.width, height, 1);
		this.edge.scale.set(WINDOW.width * WINDOW.glow, height * WINDOW.glow, 1);
		const inner = this.edge.material.uniforms["inner"];
		if (inner !== undefined)
			inner.value = new THREE.Vector2(0.5 / WINDOW.glow, 0.5 / WINDOW.glow);
		const t = WINDOW.frame;
		const [top, bottom, left, right] = this.bars;
		top?.scale.set(WINDOW.width + 2 * t, t, t);
		top?.position.set(0, height / 2 + t / 2, 0);
		bottom?.scale.set(WINDOW.width + 2 * t, t, t);
		bottom?.position.set(0, -height / 2 - t / 2, 0);
		left?.scale.set(t, height, t);
		left?.position.set(-WINDOW.width / 2 - t / 2, 0, 0);
		right?.scale.set(t, height, t);
		right?.position.set(WINDOW.width / 2 + t / 2, 0, 0);
	}

	/** 窓が見えているか・映しているコマの tick（e2e の口・`__jinStage.summon()`）。 */
	shown(): { readonly visible: boolean; readonly tick: number | null } {
		return { visible: this.object.visible, tick: this.drawn?.tick ?? null };
	}

	/** 窓がある（舞台の大きさがあり、開いている）か。カメラの半径を広げるかに使う。 */
	openness(state: WindowState): number {
		return this.size === null ? 0 : state.open;
	}

	update(
		frame: ScreenFrame | null,
		state: WindowState,
		camera: THREE.Camera,
	): void {
		const size = this.size;
		const open = this.openness(state);
		this.object.visible = size !== null && open > 0 && frame !== null;
		if (!this.object.visible || size === null) {
			this.beam.visible = false;
			return;
		}
		if (frame !== this.drawn && this.canvas !== null) {
			const context = this.canvas.getContext("2d");
			if (context !== null) {
				context.fillStyle = "#000";
				context.fillRect(0, 0, size.width, size.height);
				if (frame !== null)
					drawOps(context, frame.ops, size.width, size.height);
			}
			if (this.texture !== null) this.texture.needsUpdate = true;
			this.drawn = frame;
		}
		// 位置: 核の上空、カメラから見て陣の奥。常にカメラを向く。開くと広がる（ease-out）。
		const height = (WINDOW.width * size.height) / size.width;
		this.flat.set(camera.position.x, 0, camera.position.z);
		if (this.flat.lengthSq() > 0) this.flat.normalize();
		this.object.position.set(
			-this.flat.x * WINDOW.back,
			WINDOW.base + height / 2,
			-this.flat.z * WINDOW.back,
		);
		this.object.quaternion.copy(camera.quaternion);
		const eased = 1 - (1 - open) ** 3;
		this.object.scale.setScalar(Math.max(0.0001, eased));
		this.panel.material.opacity = Math.min(1, open * 1.25);
		// 縁: 描く力（サファイア）→ 音（アメジスト）→ 素材の音（白）→ 実行時エラー（ガーネット）。
		this.tint
			.copy(SAPPHIRE)
			.lerp(AMETHYST, state.tonePulse)
			.lerp(WHITE, state.playFlash)
			.lerp(GARNET, state.errorPulse);
		const uniforms = this.edge.material.uniforms;
		if (uniforms["tint"] !== undefined)
			(uniforms["tint"].value as THREE.Color).copy(this.tint);
		if (uniforms["strength"] !== undefined)
			uniforms["strength"].value =
				open *
				(0.8 +
					0.7 * Math.max(state.tonePulse, state.playFlash, state.errorPulse));
		// 開く・閉じるあいだだけ、核から窓へ細い光が立つ。
		const rising = Math.sin(Math.PI * open);
		this.beam.visible = rising > 0.01;
		if (this.beam.visible) {
			const bottom = 0.2;
			const top = this.object.position.y - (height / 2) * eased;
			this.beam.scale.set(1, Math.max(0.0001, top - bottom), 1);
			this.beam.position.set(
				this.object.position.x * eased,
				(top + bottom) / 2,
				this.object.position.z * eased,
			);
			this.beam.material.opacity = rising;
		}
	}

	dispose(): void {
		this.texture?.dispose();
		this.panel.geometry.dispose();
		this.panel.material.dispose();
		this.edge.geometry.dispose();
		this.edge.material.dispose();
		for (const bar of this.bars) bar.geometry.dispose();
		this.barMaterial.dispose();
		this.beam.geometry.dispose();
		this.beam.material.dispose();
	}
}
