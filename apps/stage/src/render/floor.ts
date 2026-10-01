import * as THREE from "three";
import { Reflector } from "three/addons/objects/Reflector.js";

import type { Vec2 } from "../scene";

/**
 * 床（仕様書 2026-10-01 §6）: 陣の下の暗い磨いた円盤に陣と光を映し、宝玉の共鳴の波紋を加算の輪で描く。
 * 座標は金細工の root と同じ局所座標（陣は xy 面・z が上）。場面が変わっても作り直さない。
 */
export interface Ripple {
	readonly at: Vec2;
	readonly radius: number;
	readonly color: number;
	readonly alpha: number;
}

/** 床の高さ（台座の層 0 = −0.32 よりさらに下）と半径。stage.md §7。 */
export const FLOOR_Z = -0.45;
const FLOOR_RADIUS = 3;
/** 映り込みに掛ける色（Reflector は overlay で混ぜる。暗いほど映り込みが控えめ）。 */
const FLOOR_COLOR = 0x05060a;
export const MAX_RIPPLES = 32;

export class Floor {
	readonly object = new THREE.Group();
	private readonly reflector: Reflector;
	private readonly ringGeometry = new THREE.RingGeometry(0.92, 1, 96);
	private readonly rings: readonly THREE.Mesh<
		THREE.RingGeometry,
		THREE.MeshBasicMaterial
	>[];

	constructor() {
		this.reflector = new Reflector(new THREE.CircleGeometry(FLOOR_RADIUS, 96), {
			textureWidth: 512,
			textureHeight: 512,
			color: FLOOR_COLOR,
		});
		this.reflector.position.z = FLOOR_Z;
		this.object.add(this.reflector);
		this.rings = Array.from({ length: MAX_RIPPLES }, () => {
			const mesh = new THREE.Mesh(
				this.ringGeometry,
				new THREE.MeshBasicMaterial({
					transparent: true,
					opacity: 0,
					depthWrite: false,
					blending: THREE.AdditiveBlending,
				}),
			);
			mesh.position.z = FLOOR_Z + 0.002;
			mesh.visible = false;
			this.object.add(mesh);
			return mesh;
		});
	}

	setRipples(ripples: readonly Ripple[]): void {
		this.rings.forEach((mesh, k) => {
			const ripple = ripples[k];
			if (ripple === undefined || ripple.radius <= 0 || ripple.alpha <= 0) {
				mesh.visible = false;
				return;
			}
			mesh.visible = true;
			mesh.position.x = ripple.at[0];
			mesh.position.y = ripple.at[1];
			mesh.scale.set(ripple.radius, ripple.radius, 1);
			mesh.material.color.setHex(ripple.color);
			mesh.material.opacity = Math.min(1, ripple.alpha);
		});
	}

	/** 映り込みの描画先の大きさ（描画の大きさの半分・デバイス px）。 */
	setSize(width: number, height: number): void {
		this.reflector
			.getRenderTarget()
			.setSize(
				Math.max(1, Math.round(width / 2)),
				Math.max(1, Math.round(height / 2)),
			);
	}

	dispose(): void {
		this.reflector.dispose();
		this.reflector.geometry.dispose();
		this.ringGeometry.dispose();
		for (const ring of this.rings) ring.material.dispose();
	}
}
