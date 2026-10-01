import * as THREE from "three";

import { armillary } from "../motion";
import { METALS } from "../palette";

/**
 * 天球儀の輪（仕様書 2026-10-01 §6）: 境界環の外に、意味を持たない飾りの細い輪を 2 本。傾けて回す。
 * 陣の要素は傾けない（光線の端点をずらさない）。地金は root のイエローゴールド。
 */
const RADII = [1.32, 1.38] as const;
const TUBE = 0.0022;
/** 地金を暗くする比（飾りなので陣より目立たせない）。 */
const DIM = 0.45;
/** 輪の中心の高さ（陣の層の真ん中あたり）。 */
const CENTER_Z = 0.1;

export class Armillary {
	readonly object = new THREE.Group();
	private readonly rings: readonly THREE.Mesh<
		THREE.TorusGeometry,
		THREE.MeshStandardMaterial
	>[];

	constructor() {
		const color = new THREE.Color(METALS.yellow.color).multiplyScalar(DIM);
		this.rings = RADII.map((radius) => {
			const mesh = new THREE.Mesh(
				new THREE.TorusGeometry(radius, TUBE, 8, 256),
				new THREE.MeshStandardMaterial({
					color,
					metalness: 1,
					roughness: METALS.yellow.roughness,
					emissive: color,
					emissiveIntensity: 0,
				}),
			);
			mesh.position.z = CENTER_Z;
			this.object.add(mesh);
			return mesh;
		});
	}

	set(seconds: number): void {
		this.rings.forEach((mesh, index) => {
			const { tiltX, tiltY, spin } = armillary(index as 0 | 1, seconds);
			mesh.rotation.set(tiltX, tiltY, spin);
		});
	}

	dispose(): void {
		for (const ring of this.rings) {
			ring.geometry.dispose();
			ring.material.dispose();
		}
	}
}
