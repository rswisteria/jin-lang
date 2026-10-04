import * as THREE from "three";

import type { Glow } from "../effects";
import {
	BAND_HEIGHT,
	type Band,
	bandLights,
	bandSpin,
	cellsUnder,
} from "../inscription";
import { gemColorAt, METALS } from "../palette";

/**
 * 銘環の帯の描画（陣書き S7・docs/spec/v2/stage.md §2.2）。
 *
 * - 刻まれた銘: 帯のすべての升の線を、root の地金（イエロー）を暗くした色の 1 本の `LineSegments` で描く
 * - 灯った銘: 時刻の光（`bandLights`）で灯った升だけを、宝玉の色 × 明るさの加算の `LineSegments` に書く。
 *   枠は `MAX_LIT_SEGMENTS` に固定し `setDrawRange` で絞る（毎フレーム geometry を作り直さない・`glowView.ts` の
 *   光線と同じ型）。枠を超えたら帯の順で先の升から描き、残りは落とす
 * - 帯は陣の中心まわりに `bandSpin` で巡る。どちらも**時刻の関数**（前のフレームの状態を持ち越さない）
 *
 * 太い線（`LineSegments2`）にしない: 帯は数万〜十数万区間あり、インスタンス描画の太い線は被写界深度の深度のパス
 * （`MeshDepthMaterial` で上書きして描き直す）で区間の数だけ素の四角を重ね描きし、ソフトウェア GL で 1 コマに
 * 数分かかった（stage.md §7）。素の線は深度のパスでも線のまま描かれ、正しい深度を書く。光は加算とブルームで太らせる。
 */
const MAX_LIT_SEGMENTS = 40000;
/** 刻まれた銘の色（地金に対する比・stage.md §7）。 */
const ENGRAVED_DIM = 0.3;
/** 灯った銘の色の増分（明るさ 1 あたり）。 */
const LIT_GAIN = 3;

export class InscriptionView {
	/** 陣の面（root と同じ x 軸まわり −90°）。 */
	readonly object = new THREE.Group();
	private readonly spinner = new THREE.Group();
	private readonly engravedGeometry = new THREE.BufferGeometry();
	private readonly engravedMaterial = new THREE.LineBasicMaterial({
		color: new THREE.Color(METALS.yellow.color).multiplyScalar(ENGRAVED_DIM),
	});
	private readonly litPositions = new Float32Array(MAX_LIT_SEGMENTS * 6);
	private readonly litColors = new Float32Array(MAX_LIT_SEGMENTS * 6);
	private readonly litGeometry = new THREE.BufferGeometry();
	private readonly litMaterial = new THREE.LineBasicMaterial({
		vertexColors: true,
		transparent: true,
		depthWrite: false,
		blending: THREE.AdditiveBlending,
	});
	private readonly lit: THREE.LineSegments;
	private readonly under = new Map<string, readonly number[]>();
	private readonly scratch = new THREE.Color();
	/** 灯った升の数（e2e の口）。 */
	litCells = 0;

	/**
	 * `spinning` が偽なら帯を回さない（全景・stage.md §2.3。銘環が陣ごとの中心にあり、原点まわりに回すと陣からずれる）。
	 */
	constructor(
		private readonly band: Band,
		private readonly spinning = true,
	) {
		this.object.rotation.x = -Math.PI / 2;
		this.spinner.position.z = BAND_HEIGHT;
		this.object.add(this.spinner);

		const positions = new Float32Array(band.segmentCount * 6);
		let at = 0;
		for (const cell of band.cells)
			for (const [a, b] of cell.segments) {
				positions.set([a[0], a[1], 0, b[0], b[1], 0], at);
				at += 6;
			}
		this.engravedGeometry.setAttribute(
			"position",
			new THREE.BufferAttribute(positions, 3),
		);
		const engraved = new THREE.LineSegments(
			this.engravedGeometry,
			this.engravedMaterial,
		);
		this.litGeometry.setAttribute(
			"position",
			new THREE.BufferAttribute(this.litPositions, 3).setUsage(
				THREE.DynamicDrawUsage,
			),
		);
		this.litGeometry.setAttribute(
			"color",
			new THREE.BufferAttribute(this.litColors, 3).setUsage(
				THREE.DynamicDrawUsage,
			),
		);
		this.litGeometry.setDrawRange(0, 0);
		this.lit = new THREE.LineSegments(this.litGeometry, this.litMaterial);
		// 配列を書き換えるので境界球が古くなる。視錐台で間引かない。
		this.lit.frustumCulled = false;
		this.lit.visible = false;
		this.spinner.add(engraved, this.lit);
	}

	apply(glows: readonly Glow[], seconds: number): void {
		this.spinner.rotation.z = this.spinning ? bandSpin(seconds) : 0;
		const lights = bandLights(this.band, glows, (pointer) => {
			let found = this.under.get(pointer);
			if (found === undefined) {
				found = cellsUnder(this.band, pointer);
				this.under.set(pointer, found);
			}
			return found;
		});
		const order = [...lights.keys()].sort((a, b) => a - b);
		let used = 0;
		for (const index of order) {
			const light = lights.get(index);
			const cell = this.band.cells[index];
			if (light === undefined || cell === undefined) continue;
			if (used + cell.segments.length > MAX_LIT_SEGMENTS) break;
			const color = this.scratch
				.set(gemColorAt(light.gem, seconds, index))
				.multiplyScalar(light.level * LIT_GAIN);
			for (const [a, b] of cell.segments) {
				const o = used * 6;
				this.litPositions[o] = a[0];
				this.litPositions[o + 1] = a[1];
				this.litPositions[o + 2] = 0;
				this.litPositions[o + 3] = b[0];
				this.litPositions[o + 4] = b[1];
				this.litPositions[o + 5] = 0;
				for (const k of [o, o + 3]) {
					this.litColors[k] = color.r;
					this.litColors[k + 1] = color.g;
					this.litColors[k + 2] = color.b;
				}
				used += 1;
			}
		}
		this.litCells = order.length;
		this.litGeometry.setDrawRange(0, used * 2);
		this.lit.visible = used > 0;
		if (used > 0) {
			for (const name of ["position", "color"] as const) {
				const attribute = this.litGeometry.getAttribute(
					name,
				) as THREE.BufferAttribute;
				attribute.clearUpdateRanges();
				attribute.addUpdateRange(0, used * 6);
				attribute.needsUpdate = true;
			}
		}
	}

	dispose(): void {
		this.engravedGeometry.dispose();
		this.engravedMaterial.dispose();
		this.litGeometry.dispose();
		this.litMaterial.dispose();
	}
}
