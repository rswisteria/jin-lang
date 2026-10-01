import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

import { serveHarness } from "./harness";

/**
 * 召喚の窓の描画の写し（`src/screen/draw.ts`）がプレイヤーの描画と画素一致する（仕様書 2026-10-01-jin-stage-summon §2.3）。
 * 正解はプレイヤーの e2e（`apps/player/e2e/screen.spec.ts`）が自分の描画で作り、同じ正解と比べる。
 * `sprite` は鑑賞ページだけが印を描くので fixture に入れない（印は `test/draw.test.ts` が見る）。
 */
const REPO_ROOT = resolve(fileURLToPath(new URL("../../..", import.meta.url)));
const SCREEN = join(REPO_ROOT, "tests", "fixtures", "screen");
const FIXTURES = ["all-ops", "tetris-10", "tetris-60"] as const;

for (const name of FIXTURES) {
	test(`召喚の窓の描画の写し: ${name} がプレイヤーの正解の PNG と画素一致`, async ({
		page,
	}) => {
		const harness = await serveHarness();
		await page.goto(harness.url);
		const stage = page.frameLocator("#stage");
		await expect(stage.getByTestId("stage-status")).toHaveText("準備完了");
		const frame = page.frames().find((f) => f.url().includes("/stage/"));
		if (frame === undefined) throw new Error("stage の iframe が無い");
		const fixture = JSON.parse(
			readFileSync(join(SCREEN, `${name}.json`), "utf8"),
		) as {
			width: number;
			height: number;
			ops: [string, ...(string | number)[]][];
		};
		const expected = `data:image/png;base64,${readFileSync(join(SCREEN, `${name}.png`)).toString("base64")}`;
		const differing = await frame.evaluate(
			async ({ fixture: f, expected: e }) => {
				const api = (
					window as unknown as {
						__jinStage: {
							renderOps(ops: unknown, w: number, h: number): string;
						};
					}
				).__jinStage;
				const pixels = async (url: string): Promise<Uint8ClampedArray> => {
					const image = new Image();
					image.src = url;
					await image.decode();
					const canvas = document.createElement("canvas");
					canvas.width = image.width;
					canvas.height = image.height;
					const context = canvas.getContext("2d");
					if (context === null) return new Uint8ClampedArray();
					context.drawImage(image, 0, 0);
					return context.getImageData(0, 0, image.width, image.height).data;
				};
				const [x, y] = [
					await pixels(api.renderOps(f.ops, f.width, f.height)),
					await pixels(e),
				];
				if (x.length !== y.length) return -1;
				let count = 0;
				for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) count++;
				return count;
			},
			{ fixture, expected },
		);
		expect(differing).toBe(0);
		await harness.close();
	});
}
