import * as THREE from "three";
import { Reflector } from "three/addons/objects/Reflector.js";
import { BokehPass } from "three/addons/postprocessing/BokehPass.js";
import { ShaderPass } from "three/addons/postprocessing/ShaderPass.js";
import { describe, expect, it } from "vitest";

/**
 * three 0.186.0 の部品の実測（delivery/…/stage-api-probe.md §E）。描画はせず、
 * import パス・コンストラクタの引数・欄の名前だけを固定する（API を記憶で書かない）。
 */
describe("three 0.186.0 の宝玉と後処理の部品", () => {
	it("Reflector は描画先を持ち、解放できる", () => {
		const reflector = new Reflector(new THREE.PlaneGeometry(1, 1), {
			textureWidth: 64,
			textureHeight: 64,
			color: 0x101018,
		});
		expect(reflector.getRenderTarget()).toBeInstanceOf(THREE.WebGLRenderTarget);
		expect(typeof reflector.dispose).toBe("function");
		reflector.dispose();
	});

	it("BokehPass は focus / aperture / maxblur を uniforms に持つ", () => {
		const pass = new BokehPass(
			new THREE.Scene(),
			new THREE.PerspectiveCamera(),
			{
				focus: 3,
				aperture: 0.002,
				maxblur: 0.006,
			},
		);
		const uniforms = pass.uniforms as Record<string, { value: unknown }>;
		expect(uniforms["focus"]?.value).toBe(3);
		expect(uniforms["aperture"]?.value).toBe(0.002);
		expect(uniforms["maxblur"]?.value).toBe(0.006);
		expect(typeof pass.setSize).toBe("function");
		pass.dispose();
	});

	it("ShaderPass は uniforms / vertexShader / fragmentShader の組を受ける", () => {
		const pass = new ShaderPass({
			uniforms: { tDiffuse: { value: null }, amount: { value: 0.5 } },
			vertexShader: "void main() { gl_Position = vec4(position, 1.0); }",
			fragmentShader:
				"uniform float amount; void main() { gl_FragColor = vec4(amount); }",
		});
		expect(pass.uniforms["amount"]?.value).toBe(0.5);
		expect(typeof pass.setSize).toBe("function");
		pass.dispose();
	});

	it("MeshPhysicalMaterial は dispersion を持つ（r163 以降の欄）", () => {
		const material = new THREE.MeshPhysicalMaterial({
			transmission: 1,
			ior: 2.42,
			dispersion: 0.3,
			thickness: 0.05,
			attenuationColor: 0x2f6bff,
			clearcoat: 1,
		});
		expect(material.dispersion).toBe(0.3);
		expect(material.ior).toBeCloseTo(2.42);
		expect(material.attenuationColor.getHex()).toBe(0x2f6bff);
		material.dispose();
	});

	it("InstancedMesh は行列と色を個別に書け、count で数を絞れる", () => {
		const mesh = new THREE.InstancedMesh(
			new THREE.PlaneGeometry(1, 1),
			new THREE.MeshBasicMaterial(),
			4096,
		);
		mesh.setMatrixAt(4095, new THREE.Matrix4().makeTranslation(1, 2, 3));
		mesh.setColorAt(4095, new THREE.Color(0x2f6bff));
		mesh.count = 10;
		expect(mesh.instanceColor).not.toBeNull();
		expect(mesh.count).toBe(10);
		mesh.dispose();
	});
});
