import * as THREE from "three";
import { BokehPass } from "three/addons/postprocessing/BokehPass.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { ShaderPass } from "three/addons/postprocessing/ShaderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";

import type { Vec2 } from "../scene";

/**
 * 後処理（仕様書 2026-10-01 §6）。順は 描画 → 被写界深度 → ゴッドレイ → ブルーム → 色収差・ビネット・グレイン → 出力。
 * ゴッドレイとグレインは自前の ShaderPass で、グレインの乱れは時刻 `seconds` から作る（乱数を使わない・決定性）。
 * 値は初期値。目視で変えたら stage.md §7。
 */
export const BOKEH = { aperture: 0.0015, maxblur: 0.005 } as const;
/** しきい値は灯った要素だけが滲む高さ（0.82 だと地金の反射まで滲んで輪が白く飛んだ）。 */
export const BLOOM = { strength: 0.7, radius: 0.45, threshold: 0.9 } as const;
/** 濃さ = min(maxStrength, 灯った宝玉の強さの和) × gain（和をそのまま使うと、陣全体が灯る演出で白く飛ぶ）。 */
export const RAYS = {
	samples: 48,
	threshold: 0.55,
	decay: 0.95,
	gain: 0.35,
	maxStrength: 1,
} as const;
export const FINISH = {
	aberration: 0.0015,
	vignette: 0.35,
	/** sRGB の値に足す量（出力の後にかけるので、線形でかけていたときより小さくてよい）。 */
	grain: 0.025,
} as const;

const PASS_VERTEX = /* glsl */ `
varying vec2 vUv;
void main() {
	vUv = uv;
	gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}`;

const RAYS_FRAGMENT = /* glsl */ `
uniform sampler2D tDiffuse;
uniform vec2 center;
uniform float strength;
uniform float threshold;
uniform float decay;
varying vec2 vUv;
const int SAMPLES = ${String(RAYS.samples)};
void main() {
	vec4 base = texture2D(tDiffuse, vUv);
	vec2 step = (center - vUv) / float(SAMPLES);
	vec2 uv = vUv;
	vec3 sum = vec3(0.0);
	float weight = 1.0;
	for (int i = 0; i < SAMPLES; i++) {
		uv += step;
		vec3 s = texture2D(tDiffuse, uv).rgb;
		sum += max(s - threshold, 0.0) * weight;
		weight *= decay;
	}
	gl_FragColor = vec4(base.rgb + sum * strength / float(SAMPLES), base.a);
}`;

const FINISH_FRAGMENT = /* glsl */ `
uniform sampler2D tDiffuse;
uniform float aberration;
uniform float vignette;
uniform float grain;
uniform float time;
uniform vec2 resolution;
varying vec2 vUv;
// sin を使わないハッシュ（大きな画素座標で sin の精度が落ちると、同心円状の縞が出る）。
float hash(vec2 p) {
	vec3 p3 = fract(vec3(p.xyx + fract(time * 0.618) * 113.0) * 0.1031);
	p3 += dot(p3, p3.yzx + 33.33);
	return fract((p3.x + p3.y) * p3.z);
}
void main() {
	vec2 offset = (vUv - 0.5) * aberration;
	float r = texture2D(tDiffuse, vUv + offset).r;
	vec4 g = texture2D(tDiffuse, vUv);
	float b = texture2D(tDiffuse, vUv - offset).b;
	vec3 color = vec3(r, g.g, b);
	float d = length(vUv - 0.5) * 1.4142;
	color *= 1.0 - vignette * d * d;
	color += (hash(floor(vUv * resolution)) - 0.5) * grain;
	gl_FragColor = vec4(color, g.a);
}`;

export interface PostFrame {
	readonly seconds: number;
	/** 核の画面上の位置（0〜1 の uv）。 */
	readonly coreScreen: Vec2;
	/** 灯った宝玉の強さの和（ゴッドレイの濃さ）。 */
	readonly rays: number;
	/** 焦点までの距離（カメラから陣の中心）。 */
	readonly focus: number;
}

export interface PostChain {
	readonly composer: EffectComposer;
	setSize(width: number, height: number, pixelRatio: number): void;
	update(frame: PostFrame): void;
	dispose(): void;
}

function uniform(
	pass: ShaderPass | BokehPass,
	name: string,
): { value: unknown } {
	const found = (
		pass.uniforms as Record<string, { value: unknown } | undefined>
	)[name];
	if (found === undefined) throw new Error(`uniform ${name} が無い`);
	return found;
}

export function buildPost(
	renderer: THREE.WebGLRenderer,
	scene: THREE.Scene,
	camera: THREE.PerspectiveCamera,
): PostChain {
	const composer = new EffectComposer(renderer);
	composer.addPass(new RenderPass(scene, camera));
	const bokeh = new BokehPass(scene, camera, {
		focus: 4,
		aperture: BOKEH.aperture,
		maxblur: BOKEH.maxblur,
	});
	composer.addPass(bokeh);
	const rays = new ShaderPass({
		uniforms: {
			tDiffuse: { value: null },
			center: { value: new THREE.Vector2(0.5, 0.5) },
			strength: { value: 0 },
			threshold: { value: RAYS.threshold },
			decay: { value: RAYS.decay },
		},
		vertexShader: PASS_VERTEX,
		fragmentShader: RAYS_FRAGMENT,
	});
	composer.addPass(rays);
	const bloom = new UnrealBloomPass(
		new THREE.Vector2(1, 1),
		BLOOM.strength,
		BLOOM.radius,
		BLOOM.threshold,
	);
	composer.addPass(bloom);
	const finish = new ShaderPass({
		uniforms: {
			tDiffuse: { value: null },
			aberration: { value: FINISH.aberration },
			vignette: { value: FINISH.vignette },
			grain: { value: FINISH.grain },
			time: { value: 0 },
			resolution: { value: new THREE.Vector2(1, 1) },
		},
		vertexShader: PASS_VERTEX,
		fragmentShader: FINISH_FRAGMENT,
	});
	// 仕上げは出力（トーンマップ・sRGB）の後: グレインを最終の色にかけないと、暗いグラデーション（床の映り込み・霧）の
	// 段差（同心円の縞）をならせない（目視で確認・stage.md §7）。
	composer.addPass(new OutputPass());
	composer.addPass(finish);

	return {
		composer,
		setSize(width, height, pixelRatio) {
			composer.setPixelRatio(pixelRatio);
			composer.setSize(width, height);
			const px = new THREE.Vector2(width * pixelRatio, height * pixelRatio);
			bloom.resolution.copy(px);
			(uniform(finish, "resolution").value as THREE.Vector2).copy(px);
		},
		update({ seconds, coreScreen, rays: level, focus }) {
			uniform(bokeh, "focus").value = focus;
			(uniform(rays, "center").value as THREE.Vector2).set(
				coreScreen[0],
				coreScreen[1],
			);
			uniform(rays, "strength").value =
				Math.min(RAYS.maxStrength, level) * RAYS.gain;
			uniform(finish, "time").value = seconds;
		},
		dispose() {
			bokeh.dispose();
			rays.dispose();
			bloom.dispose();
			finish.dispose();
			composer.dispose();
		},
	};
}
