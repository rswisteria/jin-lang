import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, test } from "vitest";

import { buildStageNames } from "../src/stage/names";

const REPO = join(__dirname, "..", "..", "..");

describe("名前の表（stage.md §6）", () => {
	test("paddle: 陣ごとに sigil / state / delegate の名前 → pointer", () => {
		const model = JSON.parse(
			readFileSync(join(REPO, "examples-v2/paddle/paddle.jin"), "utf8"),
		) as Record<string, unknown>;
		const names = buildStageNames(model);
		expect(names["Play"]).toEqual({
			pointer: "/circles/1",
			sigils: {
				canvas: "/circles/1/sigils/0",
				input: "/circles/1/sigils/1",
				audio: "/circles/1/sigils/2",
			},
			state: {
				ball: "/circles/1/state/0",
				paddle: "/circles/1/state/1",
				score: "/circles/1/state/2",
			},
			delegates: {},
			sigilKinds: { canvas: "canvas", input: "input", audio: "audio" },
			stateTypes: { ball: "Ball", paddle: "num", score: "num" },
		});
		expect(names["Game"]?.pointer).toBe("/circles/0");
		expect(names["Game"]?.isRoot).toBe(true);
	});

	test("tetris: 力の名前空間・記憶の型・root（仕様書 2026-10-01 §4）", () => {
		const model = JSON.parse(
			readFileSync(join(REPO, "examples-v2/tetris/tetris.jin"), "utf8"),
		) as Record<string, unknown>;
		const names = buildStageNames(model);
		expect(names["Play"]?.sigilKinds).toEqual({
			canvas: "canvas",
			input: "input",
			audio: "audio",
			random: "random",
		});
		expect(names["Play"]?.stateTypes?.["board"]).toBe("list<num>");
		expect(names["Play"]?.stateTypes?.["piece"]).toBe("Piece");
		expect(names["Play"]?.stateTypes?.["over"]).toBe("bool");
		expect(names["Game"]?.isRoot).toBe(true);
		expect(names["Play"]?.isRoot).toBeUndefined();
		expect("isRoot" in (names["Play"] ?? {})).toBe(false);
	});

	test("othello: agent と summon の sigil は kind をそのまま", () => {
		const model = JSON.parse(
			readFileSync(join(REPO, "examples-v2/othello/othello.jin"), "utf8"),
		) as Record<string, unknown>;
		const kinds = buildStageNames(model)["Play"]?.sigilKinds;
		expect(kinds?.["rival"]).toBe("agent");
		expect(kinds?.["legal"]).toBe("summon");
		expect(kinds?.["storage"]).toBe("storage");
	});

	test("delegate は陣名の配列から pointer を作る", () => {
		const names = buildStageNames({
			circles: [{ name: "A", delegate: ["B", "C"] }, { name: "B" }],
		});
		expect(names["A"]?.delegates).toEqual({
			B: "/circles/0/delegate/0",
			C: "/circles/0/delegate/1",
		});
	});

	test("形が崩れたモデルでも例外を投げず、読める分だけ返す", () => {
		expect(buildStageNames({})).toEqual({});
		expect(
			buildStageNames({
				circles: [
					null,
					{ name: 3 },
					{ name: "X", sigils: [{}, { name: "s" }] },
				],
			}),
		).toEqual({
			X: {
				pointer: "/circles/2",
				sigils: { s: "/circles/2/sigils/1" },
				state: {},
				delegates: {},
				sigilKinds: {},
				stateTypes: {},
			},
		});
	});
});
