import * as THREE from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";

import { type CameraOffset, type CameraPreset, cameraPose } from "../camera";
import type { Glow } from "../effects";
import type { Scene } from "../scene";
import { buildGilded, type GildedModel } from "./gilded";
import { GlowView } from "./glowView";

/** 1 回の描画に要るもの（すべて時刻の関数の入力）。 */
export interface StageFrame {
	readonly tick: number;
	readonly fps: number;
	readonly glows: readonly Glow[];
	readonly preset: CameraPreset;
	readonly aspect: number;
	readonly offset: CameraOffset;
}

const BACKGROUND = 0x080503;
/** ブルームは発動の瞬間だけ滲むよう、しきい値を高くする（設計書 §2.1）。 */
const BLOOM = { strength: 0.7, radius: 0.45, threshold: 0.82 } as const;

export class StageRenderer {
	private readonly renderer: THREE.WebGLRenderer;
	private readonly scene = new THREE.Scene();
	private readonly camera = new THREE.PerspectiveCamera(35, 1, 0.05, 50);
	private readonly composer: EffectComposer;
	private readonly bloom: UnrealBloomPass;
	private readonly key = new THREE.PointLight(0xffd8a0, 8, 8, 1.3);
	private model: GildedModel | null = null;
	private view: GlowView | null = null;
	private pointers: ReadonlySet<string> = new Set();
	private width = 1;
	private height = 1;

	constructor(readonly canvas: HTMLCanvasElement) {
		this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
		this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
		this.scene.background = new THREE.Color(BACKGROUND);
		this.scene.fog = new THREE.FogExp2(BACKGROUND, 0.1);
		this.scene.environment = new THREE.PMREMGenerator(this.renderer).fromScene(new RoomEnvironment(), 0.04).texture;
		this.scene.add(this.key);
		const rim = new THREE.DirectionalLight(0xffc27a, 1.2);
		rim.position.set(-1.5, 0.6, -2);
		this.scene.add(rim, new THREE.AmbientLight(0x3a2a18, 0.6));
		this.composer = new EffectComposer(this.renderer);
		this.composer.addPass(new RenderPass(this.scene, this.camera));
		this.bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), BLOOM.strength, BLOOM.radius, BLOOM.threshold);
		this.composer.addPass(this.bloom);
		this.composer.addPass(new OutputPass());
	}

	setScene(scene: Scene): void {
		if (this.model !== null) {
			this.scene.remove(this.model.root);
			this.view?.dispose();
			this.model.dispose();
		}
		this.model = buildGilded(scene);
		this.view = new GlowView(this.model);
		this.pointers = scene.pointers;
		this.scene.add(this.model.root);
		this.resize(this.width, this.height, this.renderer.getPixelRatio());
	}

	/** 描画の大きさ（CSS px）と倍率。書き出しでは出力の大きさ・倍率 1 で呼ぶ。 */
	resize(width: number, height: number, pixelRatio: number): void {
		this.width = Math.max(1, Math.round(width));
		this.height = Math.max(1, Math.round(height));
		this.renderer.setPixelRatio(pixelRatio);
		this.renderer.setSize(this.width, this.height, false);
		this.composer.setPixelRatio(pixelRatio);
		this.composer.setSize(this.width, this.height);
		const px = new THREE.Vector2(this.width * pixelRatio, this.height * pixelRatio);
		this.bloom.resolution.copy(px);
		// 線の太さは画面の高さ 1080 px を基準に比例させ、プレビューと書き出しで見え方を揃える。
		for (const material of this.view?.lineMaterials ?? []) {
			material.resolution.copy(px);
			material.linewidth = (material.userData["baseWidth"] ??= material.linewidth) * Math.max(1, px.y / 1080);
		}
	}

	draw(frame: StageFrame): void {
		const seconds = frame.tick / frame.fps;
		const pose = cameraPose(frame.preset, frame.aspect, seconds, frame.offset);
		this.camera.fov = pose.fovDeg;
		this.camera.aspect = frame.aspect;
		this.camera.position.set(...pose.position);
		this.camera.lookAt(0, 0.1, 0);
		this.camera.updateProjectionMatrix();
		this.key.position.set(Math.cos(seconds * 0.5) * 1.4, 1.1, Math.sin(seconds * 0.5) * 1.4);
		this.view?.apply(frame.glows, frame.tick, frame.fps, this.pointers);
		this.composer.render();
	}

	dispose(): void {
		this.view?.dispose();
		this.model?.dispose();
		this.composer.dispose();
		this.renderer.dispose();
	}
}
