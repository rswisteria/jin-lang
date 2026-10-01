import * as THREE from "three";

import { MAX_PARTICLES, type Particle } from "../particles";

/**
 * 粒子の 1 系統（仕様書 2026-10-01 §6）を 1 回の描画で流す。`Points` + 自前のシェーダで、粒子ごとに
 * 位置・色・大きさ・明るさを持ち、常にカメラを向く（加算・深度を書かない）。枠は `MAX_PARTICLES` で
 * 固定し、毎フレーム配列を書き換えて `setDrawRange` で数を絞る（GPU のバッファを作り直さない）。
 */
const VERTEX = /* glsl */ `
attribute vec3 tint;
attribute float size;
attribute float alpha;
uniform float scale;
varying vec3 vTint;
varying float vAlpha;
void main() {
	vTint = tint;
	vAlpha = alpha;
	vec4 mv = modelViewMatrix * vec4(position, 1.0);
	gl_PointSize = size * scale / max(-mv.z, 0.05);
	gl_Position = projectionMatrix * mv;
}`;

const FRAGMENT = /* glsl */ `
varying vec3 vTint;
varying float vAlpha;
void main() {
	float d = length(gl_PointCoord - 0.5) * 2.0;
	float a = vAlpha * pow(max(0.0, 1.0 - d), 2.0);
	if (a <= 0.003) discard;
	gl_FragColor = vec4(vTint * a, a);
}`;

export class ParticleView {
	readonly object: THREE.Points;
	private readonly positions = new Float32Array(MAX_PARTICLES * 3);
	private readonly tints = new Float32Array(MAX_PARTICLES * 3);
	private readonly sizes = new Float32Array(MAX_PARTICLES);
	private readonly alphas = new Float32Array(MAX_PARTICLES);
	private readonly material: THREE.ShaderMaterial;
	private readonly color = new THREE.Color();

	constructor() {
		const geometry = new THREE.BufferGeometry();
		geometry.setAttribute(
			"position",
			new THREE.BufferAttribute(this.positions, 3),
		);
		geometry.setAttribute("tint", new THREE.BufferAttribute(this.tints, 3));
		geometry.setAttribute("size", new THREE.BufferAttribute(this.sizes, 1));
		geometry.setAttribute("alpha", new THREE.BufferAttribute(this.alphas, 1));
		geometry.setDrawRange(0, 0);
		this.material = new THREE.ShaderMaterial({
			uniforms: { scale: { value: 500 } },
			vertexShader: VERTEX,
			fragmentShader: FRAGMENT,
			transparent: true,
			depthWrite: false,
			blending: THREE.AdditiveBlending,
		});
		this.object = new THREE.Points(geometry, this.material);
		// 配列を書き換えるので境界球が古くなる。視錐台で間引かない。
		this.object.frustumCulled = false;
	}

	/** 世界の 1 単位が画面の何 px か（描画の高さ（デバイス px）/ (2 tan(縦の半視野))）。 */
	setScale(scale: number): void {
		const uniform = this.material.uniforms["scale"];
		if (uniform !== undefined) uniform.value = scale;
	}

	set(particles: readonly Particle[]): void {
		const count = Math.min(particles.length, MAX_PARTICLES);
		for (let k = 0; k < count; k++) {
			const particle = particles[k];
			if (particle === undefined) continue;
			this.positions.set(particle.position, k * 3);
			this.color.setHex(particle.color);
			this.tints[k * 3] = this.color.r;
			this.tints[k * 3 + 1] = this.color.g;
			this.tints[k * 3 + 2] = this.color.b;
			this.sizes[k] = particle.size;
			this.alphas[k] = particle.alpha;
		}
		const geometry = this.object.geometry;
		geometry.setDrawRange(0, count);
		for (const name of ["position", "tint", "size", "alpha"]) {
			const attribute = geometry.getAttribute(name);
			attribute.needsUpdate = true;
		}
	}

	dispose(): void {
		this.object.geometry.dispose();
		this.material.dispose();
	}
}
