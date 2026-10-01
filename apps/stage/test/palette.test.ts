import { describe, expect, test } from "vitest";

import type { StageNames, TraceRow } from "../src/names";
import {
	GEMS,
	gemColorAt,
	gemOfElement,
	gemOfRow,
	metalOf,
	stateGem,
} from "../src/palette";

const NAMES: StageNames = {
	Game: {
		pointer: "/circles/0",
		sigils: {},
		state: {},
		delegates: {},
		isRoot: true,
	},
	Play: {
		pointer: "/circles/1",
		sigils: { canvas: "/circles/1/sigils/0", input: "/circles/1/sigils/1" },
		state: {
			board: "/circles/1/state/0",
			piece: "/circles/1/state/1",
			score: "/circles/1/state/3",
			over: "/circles/1/state/8",
		},
		delegates: {},
		sigilKinds: { canvas: "canvas", input: "input" },
		stateTypes: {
			score: "num",
			board: "list<num>",
			over: "bool",
			piece: "Piece",
		},
	},
};

/** 3 欄の無い、古いエディタの表。 */
const OLD_NAMES: StageNames = {
	Play: {
		pointer: "/circles/1",
		sigils: { canvas: "/circles/1/sigils/0" },
		state: { score: "/circles/1/state/3" },
		delegates: {},
	},
};

let seq = 0;
const row = (fields: Partial<TraceRow>): TraceRow => ({
	seq: seq++,
	tick: 0,
	circle: "Play",
	kind: "rite",
	pointer: "/circles/1/rites/2",
	...fields,
});

describe("行 → 力の宝玉（仕様書 ① §2.1）", () => {
	test("cast は名前空間の宝玉", () => {
		expect(gemOfRow(row({ kind: "cast", name: "canvas.rect" }), NAMES)).toBe(
			"sapphire",
		);
		expect(gemOfRow(row({ kind: "cast", name: "input.pressed" }), NAMES)).toBe(
			"emerald",
		);
	});
	test("自陣の手順の呼び出しと未知の名前空間は金", () => {
		expect(gemOfRow(row({ kind: "cast", name: "fits" }), NAMES)).toBe("gold");
		expect(gemOfRow(row({ kind: "cast", name: "nope.x" }), NAMES)).toBe("gold");
	});
	test("set は記憶の型の宝玉、bool は値で真珠かオニキス", () => {
		expect(
			gemOfRow(row({ kind: "set", name: "score", output: 3 }), NAMES),
		).toBe("citrine");
		expect(
			gemOfRow(row({ kind: "set", name: "board", output: [] }), NAMES),
		).toBe("tourmaline");
		expect(
			gemOfRow(row({ kind: "set", name: "piece", output: {} }), NAMES),
		).toBe("spinel");
		expect(
			gemOfRow(row({ kind: "set", name: "over", output: true }), NAMES),
		).toBe("pearl");
		expect(
			gemOfRow(row({ kind: "set", name: "over", output: false }), NAMES),
		).toBe("onyx");
	});
	test("一度きりの kind の宝玉", () => {
		expect(gemOfRow(row({ kind: "transfer", name: "Result" }), NAMES)).toBe(
			"topaz",
		);
		expect(gemOfRow(row({ kind: "emit", name: "hit" }), NAMES)).toBe("diamond");
		expect(gemOfRow(row({ kind: "assert", name: "g" }), NAMES)).toBe("ruby");
		expect(gemOfRow(row({ kind: "error" }), NAMES)).toBe("garnet");
	});
	test("event はイベントの種類で染める", () => {
		expect(gemOfRow(row({ kind: "event", name: "key" }), NAMES)).toBe(
			"emerald",
		);
		expect(gemOfRow(row({ kind: "event", name: "pointer" }), NAMES)).toBe(
			"emerald",
		);
		expect(gemOfRow(row({ kind: "event", name: "message" }), NAMES)).toBe(
			"diamond",
		);
		expect(gemOfRow(row({ kind: "event", name: "tick" }), NAMES)).toBe("gold");
		expect(gemOfRow(row({ kind: "event", name: "exit" }), NAMES)).toBe("gold");
	});
	test("それ以外は金", () => {
		for (const kind of ["enter", "exit", "rite", "wait", "finish"]) {
			expect(gemOfRow(row({ kind }), NAMES)).toBe("gold");
		}
	});
	test("欄の無い古い表でも例外を投げず金", () => {
		expect(
			gemOfRow(row({ kind: "cast", name: "canvas.rect" }), OLD_NAMES),
		).toBe("gold");
		expect(
			gemOfRow(row({ kind: "set", name: "score", output: 1 }), OLD_NAMES),
		).toBe("gold");
		expect(
			gemOfRow(
				row({ kind: "cast", name: "canvas.rect", circle: null }),
				OLD_NAMES,
			),
		).toBe("gold");
	});
});

describe("記憶の型の宝玉（§2.2）", () => {
	test("型の文字列 → 宝玉", () => {
		expect(stateGem("num")).toBe("citrine");
		expect(stateGem("str")).toBe("aquamarine");
		expect(stateGem("bool")).toBe("pearl");
		expect(stateGem("list<str>")).toBe("tourmaline");
		expect(stateGem("Piece")).toBe("spinel");
		expect(stateGem(undefined)).toBe("gold");
		expect(stateGem("")).toBe("gold");
	});
});

describe("陣の地金（§2.3）", () => {
	test("root はイエローゴールド、他は並び順にローズから", () => {
		expect(metalOf("/circles/0", NAMES)).toBe("yellow");
		expect(metalOf("/circles/1", NAMES)).toBe("rose");
		expect(metalOf(null, NAMES)).toBe("yellow");
	});
	test("root が途中にあれば root を数えずに巡る", () => {
		const names: StageNames = {
			A: { pointer: "/circles/0", sigils: {}, state: {}, delegates: {} },
			R: {
				pointer: "/circles/2",
				sigils: {},
				state: {},
				delegates: {},
				isRoot: true,
			},
		};
		expect(metalOf("/circles/0", names)).toBe("rose");
		expect(metalOf("/circles/1", names)).toBe("white");
		expect(metalOf("/circles/2", names)).toBe("yellow");
		expect(metalOf("/circles/3", names)).toBe("platinum");
		expect(metalOf("/circles/4", names)).toBe("rose");
	});
	test("isRoot がどこにも無ければ全部を並び順で巡る", () => {
		expect(metalOf("/circles/0", OLD_NAMES)).toBe("rose");
		expect(metalOf("/circles/1", OLD_NAMES)).toBe("white");
	});
});

describe("要素 → はめる宝玉（§3.1）", () => {
	test("種別ごとの宝玉", () => {
		expect(gemOfElement("sigil", "/circles/1/sigils/0", NAMES)).toBe(
			"sapphire",
		);
		expect(gemOfElement("state", "/circles/1/state/3", NAMES)).toBe("citrine");
		expect(gemOfElement("state", "/circles/1/state/8", NAMES)).toBe("pearl");
		expect(gemOfElement("core", "/circles/1/core", NAMES)).toBe("diamond");
		expect(gemOfElement("on", "/circles/1/boundary/on/0", NAMES)).toBe(
			"crystal",
		);
		expect(gemOfElement("guard", "/circles/1/boundary/guards/0", NAMES)).toBe(
			"ruby",
		);
		expect(gemOfElement("delegate", "/circles/0/delegate/0", NAMES)).toBe(
			"topaz",
		);
		expect(gemOfElement("rite", "/circles/1/rites/0", NAMES)).toBeNull();
	});
	test("引けない紋と記憶は金", () => {
		expect(gemOfElement("sigil", "/circles/1/sigils/9", NAMES)).toBe("gold");
		expect(gemOfElement("sigil", "/circles/1/sigils/0", OLD_NAMES)).toBe(
			"gold",
		);
	});
});

describe("宝玉の色", () => {
	test("固定の色はその値", () => {
		expect(gemColorAt("sapphire", 0, 0)).toBe(0x2f6bff);
		expect(gemColorAt("ruby", 5, 9)).toBe(GEMS.ruby.color);
	});
	test("オパールは時刻と seq で巡り、同じ引数なら同じ色", () => {
		expect(gemColorAt("opal", 1, 3)).toBe(gemColorAt("opal", 1, 3));
		expect(gemColorAt("opal", 1, 3)).not.toBe(gemColorAt("opal", 3, 3));
		expect(gemColorAt("opal", 1, 3)).not.toBe(gemColorAt("opal", 1, 4));
	});
});
