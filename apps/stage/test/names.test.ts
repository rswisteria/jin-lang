import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, test } from "vitest";

import {
	nearestInScene,
	resolveTargets,
	riteOf,
	type StageNames,
	type TraceRow,
} from "../src/names";

const NAMES = JSON.parse(
	readFileSync(join(__dirname, "fixtures", "paddle-names.json"), "utf8"),
) as StageNames;
const row = (fields: Partial<TraceRow>): TraceRow => ({
	seq: 0,
	tick: 0,
	circle: "Play",
	kind: "rite",
	pointer: "/circles/1",
	...fields,
});

describe("光らせる要素（stage.md §3.1）", () => {
	test("cast は sigil 名で紋を引き、出どころは手順", () => {
		expect(
			resolveTargets(
				row({
					kind: "cast",
					name: "canvas.rect",
					pointer: "/circles/1/rites/3/steps/2",
				}),
				NAMES,
			),
		).toEqual({
			primary: "/circles/1/sigils/0",
			source: "/circles/1/rites/3",
		});
	});

	test("set は state 名で四角を引く", () => {
		expect(
			resolveTargets(
				row({
					kind: "set",
					name: "score",
					pointer: "/circles/1/rites/2/steps/9",
				}),
				NAMES,
			),
		).toEqual({
			primary: "/circles/1/state/2",
			source: null,
		});
	});

	test("引けない名前は行の pointer に落ちる", () => {
		expect(
			resolveTargets(
				row({
					kind: "cast",
					name: "nope.x",
					pointer: "/circles/1/rites/3/steps/2",
				}),
				NAMES,
			),
		).toEqual({
			primary: "/circles/1/rites/3/steps/2",
			source: null,
		});
		expect(
			resolveTargets(
				row({
					kind: "set",
					name: "ghost",
					circle: "Nowhere",
					pointer: "/circles/9/rites/0/steps/0",
				}),
				NAMES,
			),
		).toEqual({
			primary: "/circles/9/rites/0/steps/0",
			source: null,
		});
	});

	test("frame と resume の wait は光らせない", () => {
		expect(
			resolveTargets(row({ kind: "frame", pointer: "/stage" }), NAMES),
		).toBeNull();
		expect(
			resolveTargets(
				row({
					kind: "wait",
					pointer: "/circles/1/rites/0/steps/1",
					output: "resume",
				}),
				NAMES,
			),
		).toBeNull();
		expect(
			resolveTargets(
				row({
					kind: "wait",
					pointer: "/circles/1/rites/0/steps/1",
					output: "suspend",
				}),
				NAMES,
			),
		).toEqual({
			primary: "/circles/1/rites/0/steps/1",
			source: null,
		});
	});

	test("event / enter / assert は行の pointer", () => {
		expect(
			resolveTargets(
				row({ kind: "event", pointer: "/circles/1/boundary/on/0" }),
				NAMES,
			)?.primary,
		).toBe("/circles/1/boundary/on/0");
	});
});

describe("段一致で祖先へ遡る", () => {
	const pointers = new Set([
		"/circles/1",
		"/circles/1/rites/2",
		"/circles/1/rites/20",
	]);
	test("ステップは手順に落ちる", () => {
		expect(nearestInScene(pointers, "/circles/1/rites/2/steps/7/then/1")).toBe(
			"/circles/1/rites/2",
		);
	});
	test("前方一致ではない（/rites/2 は /rites/20 を拾わない）", () => {
		expect(
			nearestInScene(
				new Set(["/circles/1/rites/20"]),
				"/circles/1/rites/2/steps/0",
			),
		).toBeNull();
	});
	test("riteOf", () => {
		expect(riteOf("/circles/1/rites/3/steps/2/then/0")).toBe(
			"/circles/1/rites/3",
		);
		expect(riteOf("/circles/1/boundary/on/0")).toBeNull();
	});
});
