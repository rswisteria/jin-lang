import { describe as group, expect, test } from "vitest";

import {
	extendStepRange,
	followRenameV2,
	rangePointersV2,
	resolveSelectionV2,
	type SelectionV2,
	selectionFromPointerV2,
} from "../src/v2/selection";

/** paddle を縮めたモデル（鍵の種類が全部出る最小）。 */
const MODEL = {
	version: 2,
	root: "Game",
	stage: { width: 320, height: 240 },
	forms: [{ name: "Ball", fields: [{ name: "x", type: "num" }] }],
	circles: [
		{
			name: "Game",
			flow: {
				kind: "sequence",
				steps: ["Play", "Result"],
				exit: "Result.quit",
			},
		},
		{
			name: "Play",
			core: "begin",
			state: [
				{ name: "ball", type: "Ball", init: "Ball{x: 1}" },
				{ name: "score", type: "num", init: "0", out: true },
			],
			sigils: [
				{ name: "canvas", kind: "host", host: "canvas" },
				{ name: "input", kind: "host", host: "input" },
			],
			rites: [
				{ name: "begin", steps: [{ do: "set", target: "score", expr: "0" }] },
				{
					name: "step",
					params: [{ name: "dt", type: "num" }],
					steps: [
						{ do: "if", cond: "true", then: [{ do: "finish" }], else: [] },
						{ do: "cast", target: "canvas.clear", args: ['"#000"'] },
					],
				},
			],
			boundary: {
				on: [{ event: "tick", rite: "step" }],
				guards: [{ assert: "score >= 0" }],
			},
			delegate: ["Result"],
		},
		{ name: "Result", core: "show", rites: [{ name: "show", steps: [] }] },
	],
};

const v2 = true as const;

group("v2 の選択の再解決（DP-COMMON-16 の v2 版）", () => {
	test("種別ごとの鍵から pointer を引ける", () => {
		const cases: [SelectionV2, string][] = [
			[{ v2, kind: "stage" }, "/stage"],
			[{ v2, kind: "form", name: "Ball" }, "/forms/0"],
			[{ v2, kind: "circle", circle: "Play" }, "/circles/1"],
			[{ v2, kind: "core", circle: "Play" }, "/circles/1/core"],
			[
				{ v2, kind: "state", circle: "Play", name: "score" },
				"/circles/1/state/1",
			],
			[
				{ v2, kind: "sigil", circle: "Play", name: "input" },
				"/circles/1/sigils/1",
			],
			[
				{ v2, kind: "rite", circle: "Play", name: "step" },
				"/circles/1/rites/1",
			],
			[
				{ v2, kind: "on", circle: "Play", event: "tick" },
				"/circles/1/boundary/on/0",
			],
			[
				{ v2, kind: "guard", circle: "Play", assert: "score >= 0" },
				"/circles/1/boundary/guards/0",
			],
			[
				{ v2, kind: "delegate", circle: "Play", name: "Result" },
				"/circles/1/delegate/0",
			],
			[
				{ v2, kind: "flow-edge", circle: "Game", name: "Result" },
				"/circles/0/flow/steps/1",
			],
			[
				{
					v2,
					kind: "step",
					circle: "Play",
					rite: "step",
					path: ["steps", "0", "then", "0"],
				},
				"/circles/1/rites/1/steps/0/then/0",
			],
		];
		for (const [selection, pointer] of cases) {
			expect(resolveSelectionV2(MODEL, selection)).toBe(pointer);
			expect(selectionFromPointerV2(MODEL, pointer)).toEqual(selection);
		}
	});

	test("無い要素は null（例外にしない）", () => {
		expect(
			resolveSelectionV2(MODEL, {
				v2,
				kind: "state",
				circle: "Play",
				name: "nope",
			}),
		).toBeNull();
		expect(
			resolveSelectionV2(MODEL, { v2, kind: "circle", circle: "Nope" }),
		).toBeNull();
		expect(
			resolveSelectionV2(MODEL, {
				v2,
				kind: "step",
				circle: "Play",
				rite: "step",
				path: ["steps", "9"],
			}),
		).toBeNull();
		expect(selectionFromPointerV2(MODEL, "/circles/9")).toBeNull();
		expect(selectionFromPointerV2(MODEL, "/nope")).toBeNull();
	});

	test("moveSigil / moveStep で並び替わっても選択が追随する", () => {
		const selection: SelectionV2 = {
			v2,
			kind: "sigil",
			circle: "Play",
			name: "canvas",
		};
		expect(resolveSelectionV2(MODEL, selection)).toBe("/circles/1/sigils/0");
		const moved = {
			...MODEL,
			circles: [
				MODEL.circles[0]!,
				{
					...MODEL.circles[1]!,
					sigils: [...(MODEL.circles[1]!.sigils ?? [])].reverse(),
				},
				MODEL.circles[2]!,
			],
		};
		expect(resolveSelectionV2(moved, selection)).toBe("/circles/1/sigils/1");
	});

	test("手順の図の pointer（外環 = 手順、核 = 手順の name、欄 = ステップ）は要素へ写す", () => {
		expect(selectionFromPointerV2(MODEL, "/circles/1/rites/1/name")).toEqual({
			v2,
			kind: "rite",
			circle: "Play",
			name: "step",
		});
		expect(
			selectionFromPointerV2(MODEL, "/circles/1/rites/1/steps/1/args/0"),
		).toEqual({
			v2,
			kind: "step",
			circle: "Play",
			rite: "step",
			path: ["steps", "1"],
		});
		expect(selectionFromPointerV2(MODEL, "/circles/0/flow")).toEqual({
			v2,
			kind: "circle",
			circle: "Game",
		});
		expect(selectionFromPointerV2(MODEL, "/circles/0/flow/exit")).toEqual({
			v2,
			kind: "circle",
			circle: "Game",
		});
	});

	test("rename の追随（陣 / 手順 / 要素）", () => {
		const state: SelectionV2 = {
			v2,
			kind: "state",
			circle: "Play",
			name: "score",
		};
		// 手順の引数（`…/params/k`）の改名は手順の改名ではない（pointer は手順を指すが要素が違う）。
		// 選択中の手順の名前を引数の新名に書き換えると、選択が「見つかりません」になる（v2.1 で実測）。
		const rite: SelectionV2 = { v2, kind: "rite", circle: "Play", name: "step" };
		expect(
			followRenameV2(
				rite,
				{ op: "rename", pointer: "/circles/1/rites/1/params/0", value: "n" },
				MODEL,
			),
		).toBe(rite);
		expect(
			followRenameV2(
				rite,
				{ op: "rename", pointer: "/circles/1/rites/1", value: "advance" },
				MODEL,
			),
		).toEqual({ ...rite, name: "advance" });
		expect(
			followRenameV2(
				state,
				{ op: "rename", pointer: "/circles/1/state/1", value: "points" },
				MODEL,
			),
		).toEqual({ ...state, name: "points" });
		expect(
			followRenameV2(
				state,
				{ op: "rename", pointer: "/circles/1", value: "Arena" },
				MODEL,
			),
		).toEqual({ ...state, circle: "Arena" });
		const step: SelectionV2 = {
			v2,
			kind: "step",
			circle: "Play",
			rite: "step",
			path: ["steps", "0"],
		};
		expect(
			followRenameV2(
				step,
				{ op: "rename", pointer: "/circles/1/rites/1", value: "update" },
				MODEL,
			),
		).toEqual({ ...step, rite: "update" });
		// 別の要素の rename は触らない。
		expect(
			followRenameV2(
				state,
				{ op: "rename", pointer: "/circles/1/state/0", value: "b" },
				MODEL,
			),
		).toBe(state);
		expect(
			followRenameV2(
				state,
				{ op: "setState", pointer: "/circles/1/state/1" },
				MODEL,
			),
		).toBe(state);
	});
});

group("ステップの範囲選択（Shift クリック・v2.1）", () => {
	const at = (...path: string[]): Extract<SelectionV2, { kind: "step" }> => ({
		v2,
		kind: "step",
		circle: "Play",
		rite: "step",
		path,
	});

	test("同じ列の添字なら範囲に広げる（path は先頭、count は個数）", () => {
		expect(extendStepRange(at("steps", "0"), at("steps", "1"))).toEqual({
			...at("steps", "0"),
			count: 2,
		});
		// 後ろから前へ広げても先頭が path になる。
		expect(extendStepRange(at("steps", "1"), at("steps", "0"))).toEqual({
			...at("steps", "0"),
			count: 2,
		});
		// 範囲の内側を Shift クリックしても縮めない（起点を持たない）。
		expect(
			extendStepRange({ ...at("steps", "0"), count: 2 }, at("steps", "0")),
		).toEqual({ ...at("steps", "0"), count: 2 });
		// 同じ 1 つを Shift クリックしたら 1 つのまま（count は書かない）。
		expect(extendStepRange(at("steps", "1"), at("steps", "1"))).toEqual(
			at("steps", "1"),
		);
	});

	test("列が違う・手順が違う・ステップでないなら、クリックした要素だけを選ぶ", () => {
		const nested = at("steps", "0", "then", "0");
		expect(extendStepRange(at("steps", "1"), nested)).toBe(nested);
		expect(extendStepRange(nested, at("steps", "1"))).toEqual(at("steps", "1"));
		const other: SelectionV2 = { ...at("steps", "1"), rite: "begin" };
		expect(extendStepRange(other, at("steps", "0"))).toEqual(at("steps", "0"));
		const rite: SelectionV2 = {
			v2,
			kind: "rite",
			circle: "Play",
			name: "step",
		};
		expect(extendStepRange(rite, at("steps", "0"))).toEqual(at("steps", "0"));
		expect(extendStepRange(at("steps", "0"), rite)).toBe(rite);
		expect(extendStepRange(null, at("steps", "0"))).toEqual(at("steps", "0"));
		expect(extendStepRange(at("steps", "0"), null)).toBeNull();
	});

	test("範囲の pointer は先頭。範囲が列からはみ出したら解決しない", () => {
		expect(resolveSelectionV2(MODEL, { ...at("steps", "0"), count: 2 })).toBe(
			"/circles/1/rites/1/steps/0",
		);
		expect(
			resolveSelectionV2(MODEL, { ...at("steps", "1"), count: 2 }),
		).toBeNull();
		expect(
			rangePointersV2("/circles/1/rites/1/steps/0", {
				...at("steps", "0"),
				count: 2,
			}),
		).toEqual(["/circles/1/rites/1/steps/0", "/circles/1/rites/1/steps/1"]);
		expect(
			rangePointersV2("/circles/1/rites/1/steps/0/then/0", at("steps", "0")),
		).toEqual(["/circles/1/rites/1/steps/0/then/0"]);
	});
});
