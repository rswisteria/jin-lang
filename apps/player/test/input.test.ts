import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe as group, expect, test } from "vitest";

import { InputCollector, InputReducer } from "../src/input";
import type { InputEvent, Inputs } from "../src/types";

const FIXTURES = join(process.cwd(), "../../tests/fixtures/jinrec");

/** `.jinrec` の本文を tick ごとに分ける（ヘッダは飛ばす）。 */
function eventsByTick(text: string, ticks: number): InputEvent[][] {
	const out: InputEvent[][] = Array.from({ length: ticks }, () => []);
	for (const line of text.split("\n").slice(1)) {
		if (line.trim() === "") continue;
		const { tick, ...event } = JSON.parse(line) as {
			tick: number;
		} & InputEvent;
		out[tick]?.push(event);
	}
	return out;
}

group("InputReducer は jin_wasm.runtime.InputState.apply の写し", () => {
	test("共有 fixture（Python 側も同じ期待値で検算する）", () => {
		const rec = readFileSync(join(FIXTURES, "reducer.jinrec"), "utf8");
		const expected = JSON.parse(
			readFileSync(join(FIXTURES, "reducer.expected.json"), "utf8"),
		) as Inputs[];
		const reducer = new InputReducer();
		const actual = eventsByTick(rec, expected.length).map((events) =>
			reducer.apply(events),
		);
		expect(actual).toEqual(expected);
	});

	test("keys は押下中のものだけを持ち、離すと消える", () => {
		const reducer = new InputReducer();
		reducer.apply([{ kind: "key", name: "KeyA", down: true }]);
		expect(reducer.apply([]).keys).toEqual({ KeyA: true });
		expect(
			reducer.apply([{ kind: "key", name: "KeyA", down: false }]).keys,
		).toEqual({});
	});
});

function collector(
	opts: Partial<ConstructorParameters<typeof InputCollector>[1]> = {},
) {
	const canvas = document.createElement("canvas");
	canvas.getBoundingClientRect = () =>
		({
			left: 10,
			top: 20,
			width: 640,
			height: 360,
			right: 650,
			bottom: 380,
			x: 10,
			y: 20,
			toJSON: () => ({}),
		}) as DOMRect;
	document.body.append(canvas);
	const c = new InputCollector(canvas, {
		width: 320,
		height: 180,
		keyNames: new Set(["ArrowLeft", "ArrowRight", "Space"]),
		keys: true,
		pointer: true,
		...opts,
	});
	c.attach();
	return { canvas, c };
}

function key(
	type: "keydown" | "keyup",
	code: string,
	extra: KeyboardEventInit = {},
) {
	window.dispatchEvent(
		new KeyboardEvent(type, { code, bubbles: true, ...extra }),
	);
}

function pointer(
	canvas: HTMLElement,
	type: string,
	x: number,
	y: number,
	button = 0,
) {
	// jsdom には PointerEvent が無いので MouseEvent に `button` を載せて代用する
	const ev = new MouseEvent(type, {
		clientX: x,
		clientY: y,
		button,
		bubbles: true,
	});
	canvas.dispatchEvent(ev);
}

group("InputCollector", () => {
	test("カタログにあるキーだけを、押下 / 離しの 1 回ずつ集める（repeat と二重押下は捨てる）", () => {
		const { c } = collector();
		key("keydown", "ArrowLeft");
		key("keydown", "ArrowLeft", { repeat: true });
		key("keydown", "ArrowLeft");
		key("keydown", "KeyQ");
		key("keyup", "ArrowLeft");
		key("keyup", "KeyQ");
		expect(c.drain()).toEqual([
			{ kind: "key", name: "ArrowLeft", down: true },
			{ kind: "key", name: "ArrowLeft", down: false },
		]);
		expect(c.drain()).toEqual([]);
		c.detach();
	});

	test("blur で押下中のキーを down:false として記録してから離す", () => {
		const { c } = collector();
		key("keydown", "ArrowLeft");
		key("keydown", "Space");
		c.drain();
		window.dispatchEvent(new Event("blur"));
		expect(c.drain()).toEqual([
			{ kind: "key", name: "ArrowLeft", down: false },
			{ kind: "key", name: "Space", down: false },
		]);
		key("keyup", "ArrowLeft"); // もう押されていないので何も出ない
		expect(c.drain()).toEqual([]);
		c.detach();
	});

	test("ポインタは論理座標（整数・枠内）で、移動は最後の 1 つに畳み、down → up の遷移は残す", () => {
		const { canvas, c } = collector();
		pointer(canvas, "pointermove", 10 + 64, 20 + 36); // (32, 18)
		pointer(canvas, "pointermove", 10 + 66, 20 + 36); // (33, 18) ← 畳まれてこれだけ残る
		pointer(canvas, "pointerdown", 10 + 66, 20 + 36);
		pointer(canvas, "pointermove", 10 + 70, 20 + 40);
		pointer(canvas, "pointerup", 10 + 70, 20 + 40);
		pointer(canvas, "pointermove", 10 + 2000, 20 - 50); // 枠の外は端に留める
		expect(c.drain()).toEqual([
			{ kind: "pointer", x: 33, y: 18, down: false },
			{ kind: "pointer", x: 33, y: 18, down: true },
			{ kind: "pointer", x: 35, y: 20, down: true },
			{ kind: "pointer", x: 35, y: 20, down: false },
			{ kind: "pointer", x: 319, y: 0, down: false },
		]);
		c.detach();
	});

	test("主ボタン以外の押下は集めない", () => {
		const { canvas, c } = collector();
		pointer(canvas, "pointerdown", 100, 100, 2);
		pointer(canvas, "pointerup", 100, 100, 2);
		expect(c.drain()).toEqual([]);
		c.detach();
	});

	test("namespaces に input が無ければキーを集めない（ポインタは ui のために集める）", () => {
		const { canvas, c } = collector({ keys: false, pointer: true });
		key("keydown", "ArrowLeft");
		pointer(canvas, "pointerdown", 10, 20);
		expect(c.drain()).toEqual([{ kind: "pointer", x: 0, y: 0, down: true }]);
		c.detach();
	});
});
