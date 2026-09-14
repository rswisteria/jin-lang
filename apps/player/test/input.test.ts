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
		text: false,
		textSink: null,
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

	test("adopt は押下中のキー / ポインタと溜まりを引き継ぐ（差し替えの間に押したままでも離しが出る）", () => {
		const { canvas, c: before } = collector();
		key("keydown", "ArrowLeft");
		pointer(canvas, "pointerdown", 10 + 66, 20 + 36);
		before.detach();
		const { canvas: canvas2, c: after } = collector();
		after.adopt(before);
		// 溜まりはそのまま渡り、押したままのキーを離すと `down: false` が出る（reset していたら出ない）。
		key("keyup", "ArrowLeft");
		pointer(canvas2, "pointerup", 10 + 70, 20 + 40);
		expect(after.drain()).toEqual([
			{ kind: "key", name: "ArrowLeft", down: true },
			{ kind: "pointer", x: 33, y: 18, down: true },
			{ kind: "key", name: "ArrowLeft", down: false },
			{ kind: "pointer", x: 35, y: 20, down: false },
		]);
		after.detach();
	});
});

group(
	"InputCollector の文字入力（abilities.md §3 の input.text・v2.1）",
	() => {
		function withSink(
			opts: Partial<ConstructorParameters<typeof InputCollector>[1]> = {},
		) {
			const sink = document.createElement("input");
			document.body.append(sink);
			const made = collector({
				keyNames: new Set(["ArrowLeft", "Backspace", "KeyA"]),
				text: true,
				textSink: sink,
				...opts,
			});
			return { ...made, sink };
		}

		/** 入力欄に文字が入ったことにする（ブラウザが値を書き換えてから `input` を送る順）。 */
		function typeInto(
			sink: HTMLInputElement,
			value: string,
			isComposing = false,
		) {
			sink.value += value;
			sink.dispatchEvent(
				new InputEvent("input", { bubbles: true, isComposing }),
			);
		}

		function sinkKey(
			sink: HTMLInputElement,
			code: string,
			isComposing = false,
		) {
			const ev = new KeyboardEvent("keydown", {
				code,
				bubbles: true,
				cancelable: true,
				isComposing,
			});
			sink.dispatchEvent(ev);
			return ev;
		}

		test("確定した文字列は text イベントで届き、入力欄の値は取り出すたびに空にする", () => {
			const { c, sink } = withSink();
			typeInto(sink, "a");
			expect(sink.value).toBe("");
			typeInto(sink, "日本😀");
			expect(c.drain()).toEqual([
				{ kind: "text", text: "a" },
				{ kind: "text", text: "日本😀" },
			]);
			c.detach();
		});

		test("IME の合成中は文字もキーも集めず、compositionend で確定した文字列を 1 つにする", () => {
			const { c, sink } = withSink();
			sink.dispatchEvent(
				new CompositionEvent("compositionstart", { bubbles: true }),
			);
			sinkKey(sink, "KeyA", true);
			typeInto(sink, "に", true);
			sink.value = "日本";
			sink.dispatchEvent(
				new InputEvent("input", { bubbles: true, isComposing: true }),
			);
			sink.dispatchEvent(
				new CompositionEvent("compositionend", { bubbles: true, data: "日本" }),
			);
			// 合成の後に isComposing: false の input が来るブラウザもある（値はもう空なので何も出ない）。
			sink.dispatchEvent(new InputEvent("input", { bubbles: true }));
			expect(c.drain()).toEqual([{ kind: "text", text: "日本" }]);
			c.detach();
		});

		test("入力欄からのキーも集め、既定動作は止めない（止めると文字が入らない）", () => {
			const { canvas, c, sink } = withSink();
			const fromSink = sinkKey(sink, "KeyA");
			expect(fromSink.defaultPrevented).toBe(false);
			const fromCanvas = new KeyboardEvent("keydown", {
				code: "ArrowLeft",
				bubbles: true,
				cancelable: true,
			});
			canvas.dispatchEvent(fromCanvas);
			expect(fromCanvas.defaultPrevented).toBe(true);
			// 入力欄以外のフォーム部品（seed の欄など）からのキーは従来どおり集めない。
			const other = document.createElement("input");
			document.body.append(other);
			other.dispatchEvent(
				new KeyboardEvent("keydown", { code: "Backspace", bubbles: true }),
			);
			expect(c.drain()).toEqual([
				{ kind: "key", name: "KeyA", down: true },
				{ kind: "key", name: "ArrowLeft", down: true },
			]);
			c.detach();
		});

		test("制御文字と対にならないサロゲートは落とし、残りが空なら出さない", () => {
			const { c, sink } = withSink();
			typeInto(sink, `a\tb${String.fromCharCode(7)}`);
			typeInto(sink, String.fromCharCode(0x7f));
			typeInto(sink, `x\uD800`);
			expect(c.drain()).toEqual([
				{ kind: "text", text: "ab" },
				{ kind: "text", text: "x" },
			]);
			c.detach();
		});

		test("text が false なら入力欄を聞かない（input を使わない陣）", () => {
			const { c, sink } = withSink({ text: false });
			typeInto(sink, "a");
			expect(sink.value).toBe("a");
			expect(c.drain()).toEqual([]);
			c.detach();
		});

		test("ポインタの押下でフォーカスは入力欄に移る（文字と IME を受けるため）", () => {
			const { canvas, c, sink } = withSink();
			pointer(canvas, "pointerdown", 10, 20);
			expect(document.activeElement).toBe(sink);
			c.focus();
			expect(document.activeElement).toBe(sink);
			c.detach();
			const { canvas: plain, c: noText } = collector();
			plain.tabIndex = 0; // プレイヤーの canvas と同じく focus できるようにする
			noText.focus();
			expect(document.activeElement).toBe(plain);
			noText.detach();
		});
	},
);
