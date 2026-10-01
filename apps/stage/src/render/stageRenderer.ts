import * as THREE from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

import { type CameraOffset, type CameraPreset, cameraPose } from "../camera";
import type { Glow } from "../effects";
import { cameraNudge } from "../motion";
import type { StageNames } from "../names";
import type { Scene } from "../scene";
import { Armillary } from "./armillary";
import { Floor } from "./floor";
import { buildGilded, type GildedModel } from "./gilded";
import { GlowView } from "./glowView";
import { Pillar } from "./pillar";
import { buildPost, type PostChain } from "./post";

/** 1 回の描画に要るもの（すべて時刻の関数の入力）。 */
export interface StageFrame {
	readonly tick: number;
	readonly fps: number;
	readonly glows: readonly Glow[];
	readonly preset: CameraPreset;
	readonly aspect: number;
	readonly offset: CameraOffset;
}

/** 宝玉の色が映える深い藍（仕様書 2026-10-01 §1）。霧は藍の薄い霞。 */
const BACKGROUND = 0x05060c;
const FOG = { color: 0x0a0d1c, density: 0.08 } as const;
const ENVIRONMENT_INTENSITY = 0.6;
/** 線の太さの基準にする画面の高さ（CSS px）。 */
const LINE_REFERENCE_HEIGHT = 1080;
/** カメラの注視点（世界座標）。ゴッドレイの中心は陣の核のあたり。 */
const LOOK_AT = new THREE.Vector3(0, 0.1, 0);
const CORE_WORLD = new THREE.Vector3(0, 0.2, 0);

export class StageRenderer {
	private readonly renderer: THREE.WebGLRenderer;
	private readonly scene = new THREE.Scene();
	private readonly camera = new THREE.PerspectiveCamera(35, 1, 0.05, 50);
	private readonly post: PostChain;
	/** 主光源。強さ 8 だと淡い地金（ローズ・ホワイト）が白く飛び、地金の違いが見えなかった（stage.md §7）。 */
	private readonly key = new THREE.PointLight(0xfff2dc, 4.5, 8, 1.3);
	/** 場面が変わっても作り直さない飾り（床・光の柱・天球儀）。金細工と同じく x 軸まわりに −90°。 */
	private readonly decor = new THREE.Group();
	private readonly floor = new Floor();
	private readonly pillar = new Pillar();
	private readonly armillary = new Armillary();
	private model: GildedModel | null = null;
	private view: GlowView | null = null;
	private pointers: ReadonlySet<string> = new Set();
	private width = 1;
	private height = 1;
	private pixelRatio = 1;

	constructor(readonly canvas: HTMLCanvasElement) {
		this.renderer = new THREE.WebGLRenderer({
			canvas,
			antialias: true,
			preserveDrawingBuffer: true,
		});
		this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
		this.scene.background = new THREE.Color(BACKGROUND);
		this.scene.fog = new THREE.FogExp2(FOG.color, FOG.density);
		// 環境マップの映り込みを抑えて、地金の色（彩度）を残す。
		this.scene.environmentIntensity = ENVIRONMENT_INTENSITY;
		this.scene.environment = new THREE.PMREMGenerator(this.renderer).fromScene(
			new RoomEnvironment(),
			0.04,
		).texture;
		this.scene.add(this.key);
		const rim = new THREE.DirectionalLight(0xbfd0ff, 1.2);
		rim.position.set(-1.5, 0.6, -2);
		this.scene.add(rim, new THREE.AmbientLight(0x1a1e30, 0.5));
		this.decor.rotation.x = -Math.PI / 2;
		this.decor.add(
			this.floor.object,
			this.pillar.object,
			this.armillary.object,
		);
		this.scene.add(this.decor);
		this.post = buildPost(this.renderer, this.scene, this.camera);
	}

	setScene(scene: Scene, names: StageNames): void {
		if (this.model !== null) {
			this.scene.remove(this.model.root);
			this.view?.dispose();
			this.model.dispose();
		}
		this.model = buildGilded(scene, names);
		this.view = new GlowView(this.model);
		this.pointers = scene.pointers;
		this.scene.add(this.model.root);
		this.resize(this.width, this.height, this.pixelRatio);
	}

	/** 描画の大きさ（CSS px）と倍率。書き出しでは出力の大きさ・倍率 1 で呼ぶ。 */
	resize(width: number, height: number, pixelRatio: number): void {
		this.width = Math.max(1, Math.round(width));
		this.height = Math.max(1, Math.round(height));
		this.pixelRatio = pixelRatio;
		this.renderer.setPixelRatio(pixelRatio);
		this.renderer.setSize(this.width, this.height, false);
		this.post.setSize(this.width, this.height, pixelRatio);
		this.floor.setSize(this.width * pixelRatio, this.height * pixelRatio);
		// 線の太さ: three 0.186 の LineSegments2 は描くたびに `resolution` を `renderer.getViewport()`（CSS px・倍率を掛けない）で
		// 上書きするので、`linewidth` は CSS px で、画面の高さに占める割合は `linewidth / height` になる。
		// 高さ 1080 CSS px のときに基準の太さになるよう `height / 1080` を掛け（頭打ちにしない）、
		// プレビュー（倍率 2 など）と書き出し（出力の大きさ・倍率 1）で画面の高さに対する太さを揃える。
		for (const material of this.view?.lineMaterials ?? []) {
			material.linewidth =
				(material.userData["baseWidth"] ??= material.linewidth) *
				(this.height / LINE_REFERENCE_HEIGHT);
		}
		// 粒子の大きさ（世界の単位）→ デバイス px: 描画の高さ / (2 tan(縦の半視野))。
		this.view?.setPointScale(
			(this.height * pixelRatio) /
				(2 * Math.tan(((this.camera.fov / 2) * Math.PI) / 180)),
		);
	}

	draw(frame: StageFrame): void {
		const seconds = frame.tick / frame.fps;
		const pose = cameraPose(
			frame.preset,
			frame.aspect,
			seconds,
			frame.offset,
			cameraNudge(frame.glows),
		);
		this.camera.fov = pose.fovDeg;
		this.camera.aspect = frame.aspect;
		this.camera.position.set(...pose.position);
		this.camera.lookAt(LOOK_AT);
		this.camera.updateProjectionMatrix();
		this.key.position.set(
			Math.cos(seconds * 0.5) * 1.4,
			1.1,
			Math.sin(seconds * 0.5) * 1.4,
		);
		this.view?.apply(frame.glows, frame.tick, frame.fps, this.pointers);
		this.floor.setRipples(this.view?.ripples ?? []);
		const pillar = this.view?.pillar ?? null;
		if (pillar === null) this.pillar.set([0, 0], 0, 0, 0, seconds);
		else
			this.pillar.set(
				pillar.at,
				pillar.base,
				pillar.height,
				pillar.alpha,
				seconds,
			);
		this.armillary.set(seconds);
		const core = CORE_WORLD.clone().project(this.camera);
		this.post.update({
			seconds,
			coreScreen: [(core.x + 1) / 2, (core.y + 1) / 2],
			rays: this.view?.rays ?? 0,
			focus: this.camera.position.distanceTo(LOOK_AT),
		});
		this.post.composer.render();
	}

	/** GPU に載っている geometry と texture の数（e2e が「送り直しても増えない」を見る）。 */
	memory(): { readonly geometries: number; readonly textures: number } {
		const { geometries, textures } = this.renderer.info.memory;
		return { geometries, textures };
	}

	dispose(): void {
		this.view?.dispose();
		this.model?.dispose();
		this.floor.dispose();
		this.pillar.dispose();
		this.armillary.dispose();
		this.post.dispose();
		this.renderer.dispose();
	}
}
