import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

import {
	PLAYER_DIST,
	REPO_ROOT,
	serveDirectory,
	type StaticServer,
} from "./harness";

/**
 * 召喚の窓の描画の写しの正解（仕様書 2026-10-01-jin-stage-summon §2.3）。プレイヤーの描画で表示リストを描き、
 * `tests/fixtures/screen/*.png` と画素一致を見る。鑑賞ページの e2e も同じ正解と比べるので、片方だけが変わると落ちる。
 * 正解を作り直すときは `UPDATE_SCREEN_GOLDEN=1 pnpm e2e -g 召喚の窓` で書いてから差分を読む。
 */
const SCREEN = join(REPO_ROOT, "tests", "fixtures", "screen");
const FIXTURES = ["all-ops", "tetris-10", "tetris-60"] as const;

let server: StaticServer;
test.beforeAll(async () => {
	server = await serveDirectory(PLAYER_DIST);
});
test.afterAll(async () => {
	await server.close();
});

for (const name of FIXTURES) {
	test(`召喚の窓の正解: ${name} をプレイヤーの描画で描くと正解の PNG と画素一致`, async ({
		page,
	}) => {
		await page.goto(server.url);
		await page.waitForFunction(() => window.__jinPlayer !== undefined);
		const fixture = JSON.parse(
			readFileSync(join(SCREEN, `${name}.json`), "utf8"),
		) as {
			width: number;
			height: number;
			ops: [string, ...(string | number)[]][];
		};
		const rendered = await page.evaluate(
			({ ops, width, height }) =>
				window.__jinPlayer?.renderOps(ops, width, height) ?? "",
			fixture,
		);
		const golden = join(SCREEN, `${name}.png`);
		if (process.env["UPDATE_SCREEN_GOLDEN"] === "1") {
			writeFileSync(
				golden,
				Buffer.from(rendered.replace(/^data:image\/png;base64,/, ""), "base64"),
			);
		}
		const expected = `data:image/png;base64,${readFileSync(golden).toString("base64")}`;
		const differing = await page.evaluate(
			async ([a, b]) => {
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
				const [x, y] = [await pixels(a), await pixels(b)];
				if (x.length !== y.length) return -1;
				let count = 0;
				for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) count++;
				return count;
			},
			[rendered, expected] as const,
		);
		expect(differing).toBe(0);
	});
}
