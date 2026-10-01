import { describe, expect, test } from "vitest";

import {
	DRAWABLE_OPS,
	drawOps,
	type Op,
	SPRITE_MARK,
	type Surface,
} from "../src/screen/draw";
import { CELL_HEIGHT, pixels, textWidth } from "../src/screen/font";

/** 呼び出しを記録する偽の Surface（プレイヤーの canvas.test.ts と同じ流儀）。 */
function recorder(): { surface: Surface; calls: string[] } {
	const calls: string[] = [];
	const surface: Surface = {
		fillStyle: "",
		strokeStyle: "",
		lineWidth: 0,
		fillRect: (x, y, w, h) =>
			calls.push(`fillRect ${String(surface.fillStyle)} ${x} ${y} ${w} ${h}`),
		strokeRect: (x, y, w, h) =>
			calls.push(
				`strokeRect ${String(surface.strokeStyle)} ${x} ${y} ${w} ${h}`,
			),
		beginPath: () => calls.push("beginPath"),
		arc: (x, y, r) => calls.push(`arc ${x} ${y} ${r}`),
		fill: () => calls.push(`fill ${String(surface.fillStyle)}`),
		moveTo: (x, y) => calls.push(`moveTo ${x} ${y}`),
		lineTo: (x, y) => calls.push(`lineTo ${x} ${y}`),
		stroke: () => calls.push(`stroke ${String(surface.strokeStyle)}`),
		drawImage: () => calls.push("drawImage"),
	};
	return { surface, calls };
}

const draw = (ops: readonly Op[]): string[] => {
	const { surface, calls } = recorder();
	drawOps(surface, ops, 64, 48);
	return calls;
};

describe("表示リストの描画の写し（仕様書 2026-10-01-jin-stage-summon §2.2）", () => {
	test("描く命令は canvas と ui の 9 つ", () => {
		expect([...DRAWABLE_OPS].sort()).toEqual([
			"button",
			"circle",
			"clear",
			"ink",
			"label",
			"line",
			"rect",
			"sprite",
			"text",
		]);
	});

	test("clear は全面を塗り、描画色を #fff に戻す", () => {
		expect(
			draw([
				["clear", "#123"],
				["rect", 1, 2, 3, 4],
			]),
		).toEqual(["fillRect #123 0 0 64 48", "fillRect #fff 1 2 3 4"]);
	});

	test("ink は次の rect と line の色を変える。tick の先頭の色は #fff", () => {
		expect(
			draw([
				["rect", 0, 0, 1, 1],
				["ink", "#f00"],
				["rect", 0, 0, 1, 1],
			]),
		).toEqual(["fillRect #fff 0 0 1 1", "fillRect #f00 0 0 1 1"]);
		expect(
			draw([
				["ink", "#0f0"],
				["line", 1, 2, 5, 6],
			]),
		).toEqual(["beginPath", "moveTo 1.5 2.5", "lineTo 5.5 6.5", "stroke #0f0"]);
	});

	test("circle は負の半径を 0 にして塗る", () => {
		expect(draw([["circle", 10, 10, -3]])).toEqual([
			"beginPath",
			"arc 10 10 0",
			"fill #fff",
		]);
	});

	test("text と label は字形の画素を 1 つずつ塗る（ASCII と日本語）", () => {
		for (const name of ["text", "label"]) {
			const calls = draw([[name, "Aあ", 2, 3]]);
			expect(calls.length).toBe([...pixels("Aあ", 2, 3)].length);
			expect(calls.every((c) => c.endsWith(" 1 1"))).toBe(true);
		}
	});

	test("button は枠と、中央に置いた文字", () => {
		const calls = draw([["button", "OK", 4, 4, 30, 12]]);
		expect(calls[0]).toBe("strokeRect #fff 4.5 4.5 29 11");
		const x = 4 + Math.floor((30 - textWidth("OK")) / 2);
		const y = 4 + Math.floor((12 - CELL_HEIGHT) / 2);
		expect(calls.length - 1).toBe([...pixels("OK", x, y)].length);
	});

	test("sprite は素材の代わりにサファイアの菱形の印を描き、描画色を元に戻す", () => {
		const calls = draw([
			["ink", "#0f0"],
			["sprite", "hero", 10, 20],
			["rect", 0, 0, 1, 1],
		]);
		const marks = calls.filter((c) => c.startsWith("fillRect #2f6bff"));
		expect(marks.length).toBeGreaterThan(0);
		for (const mark of marks) {
			const [, , x, y] = mark.split(" ").map(Number);
			expect(x).toBeGreaterThanOrEqual(10);
			expect(x).toBeLessThan(10 + SPRITE_MARK);
			expect(y).toBeGreaterThanOrEqual(20);
			expect(y).toBeLessThan(20 + SPRITE_MARK);
		}
		expect(calls.at(-1)).toBe("fillRect #0f0 0 0 1 1");
	});

	test("未知の op は無視する", () => {
		expect(
			draw([
				["warp", 1],
				["rect", 0, 0, 1, 1],
			]),
		).toEqual(["fillRect #fff 0 0 1 1"]);
	});
});
