import { describe as group, expect, test } from "vitest";

import { DRAWABLE_OPS, Renderer, type Surface } from "../src/canvas";
import { CELL_WIDTH, pixels, textWidth } from "../src/font";

/** 呼び出しを記録するだけの Surface（jsdom には 2D コンテキストが無い）。 */
function recording(): { surface: Surface; calls: string[] } {
	const calls: string[] = [];
	const surface: Surface = {
		fillStyle: "",
		strokeStyle: "",
		lineWidth: 0,
		fillRect: (x, y, w, h) =>
			calls.push(`fillRect ${x},${y},${w},${h} ${String(surface.fillStyle)}`),
		strokeRect: (x, y, w, h) => calls.push(`strokeRect ${x},${y},${w},${h}`),
		beginPath: () => calls.push("beginPath"),
		arc: (x, y, r) => calls.push(`arc ${x},${y},${r}`),
		fill: () => calls.push(`fill ${String(surface.fillStyle)}`),
		moveTo: (x, y) => calls.push(`moveTo ${x},${y}`),
		lineTo: (x, y) => calls.push(`lineTo ${x},${y}`),
		stroke: () => calls.push(`stroke ${String(surface.strokeStyle)}`),
		drawImage: (_image, x, y) => calls.push(`drawImage ${x},${y}`),
	};
	return { surface, calls };
}

group("Renderer（表示リスト → canvas）", () => {
	test("clear / ink / rect / circle / line を順に描き、ink は tick の先頭で #fff に戻る", () => {
		const { surface, calls } = recording();
		const r = new Renderer(surface, 320, 180);
		r.draw([
			["clear", "#000"],
			["rect", 1, 2, 3, 4],
			["ink", "#f00"],
			["circle", 10, 20, 5],
			["line", 0, 0, 10, 10],
		]);
		expect(calls).toEqual([
			"fillRect 0,0,320,180 #000",
			"fillRect 1,2,3,4 #fff",
			"beginPath",
			"arc 10,20,5",
			"fill #f00",
			"beginPath",
			"moveTo 0.5,0.5",
			"lineTo 10.5,10.5",
			"stroke #f00",
		]);
		calls.length = 0;
		r.draw([["rect", 0, 0, 1, 1]]);
		expect(calls).toEqual(["fillRect 0,0,1,1 #fff"]);
	});

	test("text は 6×8 の枠のビットマップで、1 文字進むと x が 6 動く", () => {
		const a = [...pixels("A", 0, 0)];
		const b = [...pixels("AA", 0, 0)];
		expect(a.length).toBeGreaterThan(0);
		expect(b.length).toBe(a.length * 2);
		expect(b.slice(a.length)).toEqual(a.map(([x, y]) => [x + CELL_WIDTH, y]));
		expect(textWidth("abc")).toBe(18);
		expect(textWidth("あい")).toBe(12); // コードポイント単位（プレリュードの len と同じ）
		// ASCII の外は □（点が出る）
		expect([...pixels("あ", 0, 0)].length).toBeGreaterThan(0);
		// 空白は何も塗らない
		expect([...pixels(" ", 0, 0)]).toEqual([]);
	});

	test("button は枠を描き、label を中央に置く", () => {
		const { surface, calls } = recording();
		new Renderer(surface, 320, 180).draw([["button", "OK", 10, 10, 40, 16]]);
		expect(calls[0]).toBe("strokeRect 10.5,10.5,39,15");
		const first = calls[1]?.match(/^fillRect (\d+),(\d+),1,1/);
		expect(first).not.toBeNull();
		// "OK" の幅は 12 → x は 10 + (40 - 12) / 2 = 24 から、y は 10 + (16 - 8) / 2 = 14 から
		expect(Number(first?.[1])).toBeGreaterThanOrEqual(24);
		expect(Number(first?.[2])).toBeGreaterThanOrEqual(14);
	});

	test("カタログに無い op は無視する（落ちない）", () => {
		const { surface, calls } = recording();
		new Renderer(surface, 320, 180).draw([
			["nope", 1],
			["rect", 0, 0, 1, 1],
		]);
		expect(calls).toEqual(["fillRect 0,0,1,1 #fff"]);
	});

	test("描ける op の一覧は abilities.json の canvas + ui", () => {
		expect(DRAWABLE_OPS).toEqual([
			"clear",
			"ink",
			"rect",
			"circle",
			"line",
			"text",
			"sprite",
			"button",
			"label",
		]);
	});
});
