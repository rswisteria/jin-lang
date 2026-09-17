import { expect, test } from "vitest";

import { exportFileName } from "../src/exportName";

test("<jin 名>-<陣名>-seed<seed>-t<開始>-<終了>.<拡張子>", () => {
	expect(
		exportFileName({
			jinName: "paddle.jin",
			circleName: "Play",
			seed: 7,
			startTick: 0,
			endTick: 120,
			extension: "mp4",
		}),
	).toBe("paddle-Play-seed7-t0-120.mp4");
});

test("seed が無ければ seed0、tick は整数に丸め、名前の / は _ に", () => {
	expect(
		exportFileName({
			jinName: "",
			circleName: "Play/step",
			seed: null,
			startTick: 10.4,
			endTick: 20.6,
			extension: "png",
		}),
	).toBe("game-Play_step-seed0-t10-21.png");
});
