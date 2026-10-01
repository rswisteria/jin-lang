import * as THREE from "three";

import type { Vec2 } from "../scene";

/**
 * 光の柱（仕様書 2026-10-01 §5.1 `finish` / §6）: 核から天へ伸びる加算の円柱。上へ流れる帯をシェーダで描く。
 * 座標は金細工の root と同じ局所座標（z が上）。高さと明るさは `motion.ts` の `pillarHeight` と光の強さ。
 */
const VERTEX = /* glsl */ `
varying vec2 vUv;
void main() {
	vUv = uv;
	gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}`;

const FRAGMENT = /* glsl */ `
uniform float time;
uniform float alpha;
uniform vec3 tint;
varying vec2 vUv;
void main() {
	float band = 0.55 + 0.45 * sin(vUv.y * 28.0 - time * 7.0);
	float rim = pow(abs(sin(vUv.x * 3.14159265)), 0.6);
	float a = alpha * band * rim * (1.0 - vUv.y) * (1.0 - vUv.y);
	gl_FragColor = vec4(tint * a, a);
}`;

const RADIUS = 0.08;

export class Pillar {
	readonly object: THREE.Mesh<THREE.CylinderGeometry, THREE.ShaderMaterial>;

	constructor() {
		const geometry = new THREE.CylinderGeometry(
			RADIUS,
			RADIUS * 1.4,
			1,
			48,
			1,
			true,
		);
		// 円柱の軸（y）を z に向け、根元を原点に置く。
		geometry.translate(0, 0.5, 0);
		geometry.rotateX(Math.PI / 2);
		const material = new THREE.ShaderMaterial({
			uniforms: {
				time: { value: 0 },
				alpha: { value: 0 },
				tint: { value: new THREE.Color(0xfff0c8) },
			},
			vertexShader: VERTEX,
			fragmentShader: FRAGMENT,
			transparent: true,
			depthWrite: false,
			side: THREE.DoubleSide,
			blending: THREE.AdditiveBlending,
		});
		this.object = new THREE.Mesh(geometry, material);
		this.object.visible = false;
	}

	/** `height` が 0 か `alpha` が 0 なら隠す。 */
	set(
		at: Vec2,
		base: number,
		height: number,
		alpha: number,
		seconds: number,
	): void {
		const visible = height > 0 && alpha > 0;
		this.object.visible = visible;
		if (!visible) return;
		this.object.position.set(at[0], at[1], base);
		this.object.scale.set(1, 1, height);
		const uniforms = this.object.material.uniforms;
		if (uniforms["time"] !== undefined) uniforms["time"].value = seconds;
		if (uniforms["alpha"] !== undefined)
			uniforms["alpha"].value = Math.min(1, alpha);
	}

	dispose(): void {
		this.object.geometry.dispose();
		this.object.material.dispose();
	}
}
