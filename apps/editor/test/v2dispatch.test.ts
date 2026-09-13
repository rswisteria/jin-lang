import { describe as group, expect, test } from "vitest";

import schemaV2 from "../../../schemas/jin-v2.schema.json";
import schemaV1 from "../../../schemas/jin.schema.json";
import {
	fieldsOf,
	isExpr,
	type JsonSchema,
	resolveRef,
} from "../src/form/schemaForm";
import {
	addHostSigil,
	addRite,
	addState,
	addStep,
	extractSelectedStep,
	moveOps,
	removeSelected,
	toggleStateOut,
	wrapSelectedStep,
} from "../src/v2/actions";
import {
	defaultStep,
	fieldsForSelectionV2,
	opsForChangeV2,
	schemaForV2,
} from "../src/v2/dispatch";
import {
	applyCandidate,
	filterCandidates,
	tokenBefore,
} from "../src/v2/ExprEditor";
import { lspPositionOf } from "../src/v2/position";
import type { SelectionV2 } from "../src/v2/selection";

const ROOT = schemaV2 as JsonSchema;
const v2 = true as const;

const MODEL = {
	version: 2,
	root: "Play",
	stage: { width: 320, height: 240, fps: 60, seed: 0, assets: [] },
	forms: [{ name: "Ball", fields: [{ name: "x", type: "num" }] }],
	circles: [
		{
			name: "Game",
			flow: { kind: "sequence", steps: ["Play"], exit: "Play.done" },
		},
		{
			name: "Play",
			description: "説明",
			core: "begin",
			state: [{ name: "score", type: "num", init: "0", out: false }],
			sigils: [{ name: "canvas", kind: "host", host: "canvas" }],
			rites: [
				{
					name: "begin",
					steps: [
						{ do: "set", target: "score", expr: "0" },
						{
							do: "cast",
							target: "canvas.clear",
							args: ['"#000"'],
							into: null,
						},
						{ do: "let", name: "v", expr: "1", type: null },
					],
				},
			],
			boundary: {
				on: [{ event: "tick", rite: "begin" }],
				guards: [{ assert: "true", message: null }],
			},
			delegate: ["Game"],
		},
	],
};

group("式の欄の印（x-jin-expr）だけで式エディタを決める", () => {
	test("v2 schema の式の欄は expr、v1 schema には印が無い", () => {
		const set = fieldsOf(ROOT, resolveRef(ROOT, "#/$defs/SetStep")!);
		expect(set.map((f) => [f.key, f.type, f.expr])).toEqual([
			["do", "string", false],
			["target", "string", true],
			["expr", "string", true],
		]);
		const cast = fieldsOf(ROOT, resolveRef(ROOT, "#/$defs/CastStep")!);
		expect(cast.find((f) => f.key === "args")!.type).toBe("exprList");
		expect(cast.find((f) => f.key === "into")!).toMatchObject({
			expr: true,
			nullable: true,
		});
		const circle = fieldsOf(ROOT, resolveRef(ROOT, "#/$defs/Circle")!);
		expect(circle.every((f) => !f.expr)).toBe(true);
		const v1 = schemaV1 as JsonSchema;
		expect(
			isExpr(v1, resolveRef(v1, "#/$defs/Instruction")!.properties!["rune"]!),
		).toBe(false);
	});

	test("印を消すと式エディタが消える（名前で決めていない証拠）", () => {
		const set = resolveRef(ROOT, "#/$defs/SetStep")!;
		const stripped: JsonSchema = {
			...set,
			properties: {
				...set.properties,
				expr: { type: "string", title: "Expr" },
			},
		};
		expect(fieldsOf(ROOT, stripped).find((f) => f.key === "expr")!.expr).toBe(
			false,
		);
	});
});

group("選択 → schema 上の定義（フォームの足場）", () => {
	test("種別ごとに schema の定義を引く（判別共用体は値の do / kind で枝を選ぶ）", () => {
		const labels = (selection: SelectionV2, value: unknown): string[] =>
			fieldsForSelectionV2(ROOT, selection, value).map((f) => f.key);
		expect(labels({ v2, kind: "stage" }, MODEL.stage)).toEqual([
			"width",
			"height",
			"fps",
			"seed",
		]);
		expect(
			labels({ v2, kind: "state", circle: "Play", name: "score" }, {}),
		).toEqual(["name", "type", "init", "out"]);
		expect(
			labels(
				{ v2, kind: "sigil", circle: "Play", name: "canvas" },
				{ kind: "host" },
			),
		).toEqual(["name", "kind", "host"]);
		expect(
			labels(
				{ v2, kind: "sigil", circle: "Play", name: "s" },
				{ kind: "summon" },
			),
		).toEqual(["name", "kind", "circle", "rite"]);
		expect(
			labels({ v2, kind: "rite", circle: "Play", name: "begin" }, {}),
		).toEqual(["name", "returns"]);
		expect(
			labels(
				{
					v2,
					kind: "step",
					circle: "Play",
					rite: "begin",
					path: ["steps", "1"],
				},
				{ do: "cast" },
			),
		).toEqual(["do", "target", "args", "into"]);
		expect(
			labels({ v2, kind: "on", circle: "Play", event: "tick" }, {}),
		).toEqual(["event", "rite"]);
		expect(
			labels({ v2, kind: "guard", circle: "Play", assert: "true" }, {}),
		).toEqual(["assert", "message"]);
		// 流れを持つ陣は Flow のスカラ欄（kind / exit）も並ぶ。配列は落ちる。
		expect(
			labels({ v2, kind: "circle", circle: "Game" }, MODEL.circles[0]),
		).toEqual(["name", "description", "core", "kind", "exit"]);
		expect(
			schemaForV2(ROOT, { v2, kind: "core", circle: "Play" }, "begin")
				?.properties,
		).toHaveProperty("core");
	});
});

group("欄の変更 → v2 オペレーション（docs/spec/v2/ops.md §2 の 32 件）", () => {
	const ops = (
		selection: SelectionV2,
		key: string,
		value: string | boolean | number | null | string[],
	) => opsForChangeV2(MODEL, selection, { key, value });

	test("直接のオペレーションがある欄", () => {
		expect(ops({ v2, kind: "stage" }, "width", 640)).toEqual([
			{ op: "setStage", pointer: "/stage", value: { width: 640 } },
		]);
		expect(
			ops({ v2, kind: "circle", circle: "Play" }, "name", "Arena"),
		).toEqual([{ op: "rename", pointer: "/circles/1", value: "Arena" }]);
		expect(
			ops({ v2, kind: "circle", circle: "Play" }, "core", "serve"),
		).toEqual([{ op: "setCore", pointer: "/circles/1", value: "serve" }]);
		expect(
			ops({ v2, kind: "circle", circle: "Game" }, "exit", "Play.done"),
		).toEqual([
			{ op: "setFlow", pointer: "/circles/0", value: { exit: "Play.done" } },
		]);
		expect(
			ops({ v2, kind: "state", circle: "Play", name: "score" }, "out", true),
		).toEqual([
			{ op: "setState", pointer: "/circles/1/state/0", value: { out: true } },
		]);
		expect(
			ops(
				{ v2, kind: "rite", circle: "Play", name: "begin" },
				"returns",
				"num",
			),
		).toEqual([
			{
				op: "setRiteSignature",
				pointer: "/circles/1/rites/0",
				value: { returns: "num" },
			},
		]);
		expect(
			ops({ v2, kind: "on", circle: "Play", event: "tick" }, "rite", "serve"),
		).toEqual([
			{
				op: "setOn",
				pointer: "/circles/1/boundary/on",
				value: { event: "tick", rite: "serve" },
			},
		]);
		expect(
			ops(
				{ v2, kind: "guard", circle: "Play", assert: "true" },
				"message",
				"m",
			),
		).toEqual([
			{
				op: "setGuard",
				pointer: "/circles/1/boundary/guards/0",
				value: { assert: "true", message: "m" },
			},
		]);
		const step: SelectionV2 = {
			v2,
			kind: "step",
			circle: "Play",
			rite: "begin",
			path: ["steps", "0"],
		};
		expect(ops(step, "expr", "score + 1")).toEqual([
			{
				op: "setStep",
				pointer: "/circles/1/rites/0/steps/0",
				value: { expr: "score + 1" },
			},
		]);
		const cast: SelectionV2 = {
			v2,
			kind: "step",
			circle: "Play",
			rite: "begin",
			path: ["steps", "1"],
		};
		expect(ops(cast, "args", ['"#fff"', "1"])).toEqual([
			{
				op: "setStep",
				pointer: "/circles/1/rites/0/steps/1",
				value: { args: ['"#fff"', "1"] },
			},
		]);
		expect(ops(cast, "into", "")).toEqual([
			{
				op: "setStep",
				pointer: "/circles/1/rites/0/steps/1",
				value: { into: null },
			},
		]);
		const let_: SelectionV2 = {
			v2,
			kind: "step",
			circle: "Play",
			rite: "begin",
			path: ["steps", "2"],
		};
		expect(ops(let_, "name", "w")).toEqual([
			{ op: "rename", pointer: "/circles/1/rites/0/steps/2", value: "w" },
		]);
	});

	test("**33 個目を作らず**合成で書く欄（description / sigil の host / on の event / delegate / do）", () => {
		expect(
			ops({ v2, kind: "circle", circle: "Play" }, "description", "新"),
		).toEqual([
			{ op: "removeCircle", pointer: "/circles/1" },
			{
				op: "addCircle",
				pointer: "/circles",
				index: 1,
				value: { ...MODEL.circles[1], description: "新" },
			},
		]);
		expect(
			ops({ v2, kind: "sigil", circle: "Play", name: "canvas" }, "host", "ui"),
		).toEqual([
			{ op: "removeSigil", pointer: "/circles/1/sigils/0" },
			{
				op: "addSigil",
				pointer: "/circles/1/sigils",
				index: 0,
				value: { name: "canvas", kind: "host", host: "ui" },
			},
		]);
		expect(
			ops({ v2, kind: "on", circle: "Play", event: "tick" }, "event", "exit"),
		).toEqual([
			{ op: "removeOn", pointer: "/circles/1/boundary/on/0" },
			{
				op: "setOn",
				pointer: "/circles/1/boundary/on",
				index: 0,
				value: { event: "exit", rite: "begin" },
			},
		]);
		expect(
			ops(
				{ v2, kind: "delegate", circle: "Play", name: "Game" },
				"delegate",
				"Play",
			),
		).toEqual([
			{ op: "removeDelegate", pointer: "/circles/1/delegate/0" },
			{
				op: "addDelegate",
				pointer: "/circles/1/delegate",
				index: 0,
				value: "Play",
			},
		]);
		expect(
			ops(
				{ v2, kind: "flow-edge", circle: "Game", name: "Play" },
				"steps",
				"Result",
			),
		).toEqual([
			{ op: "setFlow", pointer: "/circles/0", value: { steps: ["Result"] } },
		]);
		const step: SelectionV2 = {
			v2,
			kind: "step",
			circle: "Play",
			rite: "begin",
			path: ["steps", "0"],
		};
		expect(ops(step, "do", "finish")).toEqual([
			{ op: "removeStep", pointer: "/circles/1/rites/0/steps/0" },
			{
				op: "addStep",
				pointer: "/circles/1/rites/0/steps",
				index: 0,
				value: { do: "finish" },
			},
		]);
	});

	test("書けない欄は空配列（黙って握り潰さない）", () => {
		expect(ops({ v2, kind: "form", name: "Ball" }, "zzz", "x")).toEqual([]);
		expect(ops({ v2, kind: "circle", circle: "Nope" }, "name", "x")).toEqual(
			[],
		);
	});

	test("ステップの既定値は参照先を捏造しない（陣名は自陣・式は空）", () => {
		expect(defaultStep("emit", "Play")).toEqual({
			do: "emit",
			circle: "Play",
			message: "message",
			args: [],
		});
		expect(defaultStep("transfer", "Play")).toEqual({
			do: "transfer",
			circle: "Play",
		});
		expect(defaultStep("set", "Play")).toEqual({
			do: "set",
			target: "",
			expr: "",
		});
		expect(defaultStep("finish", "Play")).toEqual({ do: "finish" });
	});
});

group("図の操作 → オペレーション（ops.md §5）", () => {
	test("追加系は空き番の名前で、削除系は選択の pointer で", () => {
		expect(addRite(MODEL, "Play")).toEqual([
			{
				op: "addRite",
				pointer: "/circles/1/rites",
				value: { name: "rite1", steps: [] },
			},
		]);
		expect(addState(MODEL, "Play")).toEqual([
			{
				op: "addState",
				pointer: "/circles/1/state",
				value: { name: "state1", type: "num", init: "0" },
			},
		]);
		// 同じ名前空間の道具が既にあれば名前だけ空き番にする（名前空間は変えない）。
		expect(addHostSigil(MODEL, "Play", "canvas")).toEqual([
			{
				op: "addSigil",
				pointer: "/circles/1/sigils",
				value: { name: "canvas1", kind: "host", host: "canvas" },
			},
		]);
		expect(
			removeSelected(MODEL, {
				v2,
				kind: "state",
				circle: "Play",
				name: "score",
			}),
		).toEqual([{ op: "removeState", pointer: "/circles/1/state/0" }]);
		expect(
			removeSelected(MODEL, { v2, kind: "circle", circle: "Play" }),
		).toEqual([]);
		expect(
			toggleStateOut(MODEL, {
				v2,
				kind: "state",
				circle: "Play",
				name: "score",
			}),
		).toEqual([
			{ op: "setState", pointer: "/circles/1/state/0", value: { out: true } },
		]);
	});

	test("addStep は選択中のステップの直後、手順なら末尾、focus の手順にも足せる", () => {
		const step: SelectionV2 = {
			v2,
			kind: "step",
			circle: "Play",
			rite: "begin",
			path: ["steps", "0"],
		};
		expect(addStep(MODEL, step, null, "finish")).toEqual([
			{
				op: "addStep",
				pointer: "/circles/1/rites/0/steps",
				index: 1,
				value: { do: "finish" },
			},
		]);
		expect(
			addStep(
				MODEL,
				{ v2, kind: "rite", circle: "Play", name: "begin" },
				null,
				"break",
			),
		).toEqual([
			{
				op: "addStep",
				pointer: "/circles/1/rites/0/steps",
				value: { do: "break" },
			},
		]);
		expect(
			addStep(MODEL, null, { circle: "Play", rite: "begin" }, "wait"),
		).toEqual([
			{
				op: "addStep",
				pointer: "/circles/1/rites/0/steps",
				value: { do: "wait", ticks: "1" },
			},
		]);
		expect(addStep(MODEL, null, null, "wait")).toEqual([]);
	});

	test("包む / 抽出 / 並べ替え", () => {
		const step: SelectionV2 = {
			v2,
			kind: "step",
			circle: "Play",
			rite: "begin",
			path: ["steps", "1"],
		};
		expect(wrapSelectedStep(MODEL, step)).toEqual([
			{
				op: "wrapSteps",
				pointer: "/circles/1/rites/0/steps",
				from: 1,
				count: 1,
				value: { do: "if", cond: "true" },
			},
		]);
		expect(extractSelectedStep(MODEL, step)).toEqual([
			{
				op: "extractRite",
				pointer: "/circles/1/rites/0/steps",
				from: 1,
				count: 1,
				name: "rite1",
			},
		]);
		const from = {
			pointer: "/circles/1/rites/0/steps/0",
			kind: "step" as const,
			ref: null,
		};
		expect(
			moveOps(from, {
				pointer: "/circles/1/rites/0/steps/2",
				kind: "step",
				ref: null,
			}),
		).toEqual([
			{ op: "moveStep", pointer: "/circles/1/rites/0/steps/0", to: 2 },
		]);
		// 列を跨ぐ移動はしない（ops.md §2: removeStep + addStep の合成であって moveStep ではない）。
		expect(
			moveOps(from, {
				pointer: "/circles/1/rites/0/steps/0/then/0",
				kind: "step",
				ref: null,
			}),
		).toEqual([]);
		expect(
			moveOps(
				{ pointer: "/circles/1/sigils/0", kind: "sigil", ref: null },
				{ pointer: "/circles/1/sigils/1", kind: "sigil", ref: null },
			),
		).toEqual([{ op: "moveSigil", pointer: "/circles/1/sigils/0", to: 1 }]);
	});
});

group("補完の位置と絞り込み（式エディタは式を再実装しない）", () => {
	test("pointer → LSP の位置（1 始まり・コードポイント → 0 始まり・UTF-16）", () => {
		const text = '{\n  "name": "😀",\n  "expr": "a + b"\n}\n';
		const pointers = [
			{
				pointer: "/name",
				start: { line: 2, col: 11 },
				end: { line: 2, col: 14 },
			},
			{
				pointer: "/expr",
				start: { line: 3, col: 11 },
				end: { line: 3, col: 18 },
			},
		];
		expect(lspPositionOf(pointers, text, "/expr")).toEqual({
			line: 2,
			character: 10,
		});
		// 同じ行にサロゲートペアがあれば UTF-16 の列はコードポイントの列より大きい。
		const surrogate = '{\n  "😀": "a + b"\n}\n';
		const rows = [
			{ pointer: "/😀", start: { line: 2, col: 9 }, end: { line: 2, col: 16 } },
		];
		expect(lspPositionOf(rows, surrogate, "/😀")).toEqual({
			line: 1,
			character: 9,
		});
		expect(lspPositionOf(pointers, text, "/nope")).toBeNull();
	});

	test("カーソル直前のトークンで前方一致、選ぶとトークンを置き換える", () => {
		expect(tokenBefore("ball.x + pad", 12)).toBe("pad");
		expect(tokenBefore("input.", 6)).toBe("input.");
		expect(tokenBefore("a + ", 4)).toBe("");
		const items = [
			{ label: "paddle" },
			{ label: "pad" },
			{ label: "input.key" },
			{ label: "input.pressed" },
			{ label: "abs" },
		];
		expect(filterCandidates(items, "pad").map((i) => i.label)).toEqual([
			"paddle",
		]);
		expect(filterCandidates(items, "input.").map((i) => i.label)).toEqual([
			"input.key",
			"input.pressed",
		]);
		expect(filterCandidates(items, "")).toEqual([]);
		expect(applyCandidate("ball.x + pad", 12, "pad", "paddle")).toEqual({
			text: "ball.x + paddle",
			caret: 15,
		});
	});
});
