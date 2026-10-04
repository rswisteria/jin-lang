import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, test } from "vitest";

import { foldTrace, type Glow, glowsAt } from "../src/effects";
import {
	AFTERGLOW,
	BAND_SPIN_RAD_PER_SECOND,
	bandLights,
	bandSpin,
	cellsUnder,
	parseInscription,
	SWEEP_END,
} from "../src/inscription";
import type { StageNames, TraceRow } from "../src/names";
import { parseScene, pathSegments, SceneError } from "../src/scene";

/** `jin render examples-v2/paddle/paddle.jin --inscription`（契約テストがレンダラの出力と突き合わせる）。 */
const BAND = readFileSync(
	join(__dirname, "fixtures", "paddle-band.svg"),
	"utf8",
);
const PLAY = readFileSync(join(__dirname, "fixtures", "play.svg"), "utf8");
const NAMES = JSON.parse(
	readFileSync(join(__dirname, "fixtures", "paddle-names.json"), "utf8"),
) as StageNames;
const TRACE = readFileSync(
	join(__dirname, "fixtures", "paddle-trace.jsonl"),
	"utf8",
)
	.split("\n")
	.filter((line) => line.trim() !== "")
	.map((line) => JSON.parse(line) as TraceRow);

const band = parseInscription(BAND);

const glow = (fields: Partial<Glow>): Glow => ({
	seq: 1,
	target: "/circles/1/rites/2",
	source: null,
	inscribed: "/circles/1/rites/2",
	effect: "spin",
	gem: "gold",
	intensity: 1,
	progress: 0.3,
	...fields,
});

describe("銘環の帯を読む（陣書き S7・stage.md §2.2）", () => {
	test("升は帯の順に並び、欄の pointer と 13 種の kind を持つ", () => {
		expect(band.cells.length).toBeGreaterThan(900);
		expect(band.cells.map((cell) => cell.index)).toEqual(
			band.cells.map((_, i) => i),
		);
		const KINDS = ["stage", "form", "circle", "core", "rite", "sigil", "state", "on", "guard", "delegate", "flow-edge", "step", "step-edge"];
		for (const cell of band.cells) expect(KINDS).toContain(cell.kind);
		expect(band.segmentCount).toBe(
			band.cells.reduce((sum, cell) => sum + cell.segments.length, 0),
		);
	});

	test("升を置き直さない: 全点が環 1.10〜1.30 に収まり、図（play.svg）の外にある", () => {
		const radii = band.cells.flatMap((cell) =>
			cell.segments.flatMap(([a, b]) => [
				Math.hypot(a[0], a[1]),
				Math.hypot(b[0], b[1]),
			]),
		);
		expect(Math.min(...radii)).toBeGreaterThanOrEqual(1.09);
		expect(Math.max(...radii)).toBeLessThanOrEqual(1.32);
		const drawing = parseScene(PLAY).items.filter(
			(item) => item.kind !== "stage" && item.kind !== "form",
		);
		for (const item of drawing) {
			if (item.shape.type === "ring")
				expect(
					Math.hypot(...item.shape.center) + item.shape.radius,
				).toBeLessThan(1.09);
		}
	});

	test("字形の d（命令の直後に空白が無い）も図の d（空白がある）も同じ線分になる", () => {
		const point = (x: string | null, y: string | null) =>
			[Number(x), Number(y)] as const;
		expect(pathSegments("M1.000 2.000 L3.000 4.000 Z", point)).toEqual(
			pathSegments("M 1.000 2.000 L 3.000 4.000 Z", point),
		);
		expect(pathSegments("M1.000 2.000 L3.000 4.000 Z", point)).toEqual([
			[
				[1, 2],
				[3, 4],
			],
			[
				[3, 4],
				[1, 2],
			],
		]);
	});

	test("升の無い SVG・SVG でないものは SceneError", () => {
		expect(() =>
			parseInscription(
				'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"></svg>',
			),
		).toThrow(SceneError);
		expect(() => parseInscription("band")).toThrow(SceneError);
	});
});

describe("灯る升（stage.md §2.2）", () => {
	test("pointer の配下は / の段で一致し、前方一致ではない", () => {
		const step = cellsUnder(band, "/circles/1/rites/2/steps/2");
		expect(step.length).toBeGreaterThan(0);
		for (const index of step)
			expect(band.cells[index]?.pointer).toMatch(
				/^\/circles\/1\/rites\/2\/steps\/2(\/|$)/,
			);
		const one = cellsUnder(band, "/circles/1");
		const all = band.cells.filter((cell) =>
			cell.pointer.startsWith("/circles/1"),
		);
		expect(one.length).toBeGreaterThan(0);
		expect(one.length).toBeLessThanOrEqual(all.length);
		expect(cellsUnder(band, "/circles/9")).toEqual([]);
	});

	test("読み上げ: 先頭は進みとともに帯の順に渡り、通り過ぎた升は AFTERGLOW で残る", () => {
		const indices = cellsUnder(band, "/circles/1/rites/2");
		const first = indices[0] ?? -1;
		const last = indices.at(-1) ?? -1;
		const start = bandLights(band, [glow({ progress: 0 })]);
		expect(start.get(first)?.level).toBeCloseTo(1);
		expect(start.has(last)).toBe(false);
		const end = bandLights(band, [glow({ progress: SWEEP_END })]);
		expect(end.get(last)?.level).toBeCloseTo(1);
		expect(end.get(first)?.level).toBeCloseTo(AFTERGLOW);
		// 強さを掛ける
		const half = bandLights(band, [glow({ progress: 0, intensity: 0.5 })]);
		expect(half.get(first)?.level).toBeCloseTo(0.5);
	});

	test("陣の鼓動（pulse）は渡らず一様に灯し、重なった升は強い方の宝玉", () => {
		const pulse = bandLights(band, [
			glow({ effect: "pulse", inscribed: "/stage", intensity: 0.1 }),
		]);
		const frame = cellsUnder(band, "/stage");
		expect(frame.length).toBeGreaterThan(0);
		for (const index of frame) expect(pulse.get(index)?.level).toBeCloseTo(0.1);
		const both = bandLights(band, [
			glow({
				inscribed: "/circles/1",
				gem: "sapphire",
				intensity: 0.2,
				progress: 0.59,
			}),
			glow({ progress: 0, gem: "ruby" }),
		]);
		const head = cellsUnder(band, "/circles/1/rites/2")[0] ?? -1;
		expect(both.get(head)?.gem).toBe("ruby");
	});

	test("トレースの行の pointer が帯を灯す（cast は sigil ではなく実行したステップ・enter は陣全体）", () => {
		const firings = foldTrace(TRACE, NAMES);
		const cast = firings.find((firing) => firing.kind === "cast");
		expect(cast?.target).toMatch(/\/sigils\//);
		expect(cast?.inscribed).toMatch(/\/rites\/\d+\/steps\/\d+$/);
		const enter = firings.find((firing) => firing.kind === "enter");
		expect(enter?.inscribed).toBe("/circles/1");
		const lit = bandLights(band, glowsAt(firings, 30, 60));
		expect(lit.size).toBeGreaterThan(0);
		// 時刻の関数: 同じ入力なら同じ結果
		expect([...bandLights(band, glowsAt(firings, 30, 60))]).toEqual([...lit]);
	});

	test("帯は時刻だけで巡る", () => {
		expect(bandSpin(0)).toBe(0);
		expect(bandSpin(10)).toBeCloseTo(BAND_SPIN_RAD_PER_SECOND * 10);
	});
});
