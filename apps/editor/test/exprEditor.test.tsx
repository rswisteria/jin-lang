import { act, cleanup, fireEvent, render } from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, test } from "vitest";

import { ExprEditor } from "../src/v2/ExprEditor";

/**
 * 式エディタの確定と、サーバが返す**正準形**（expr.md §8）への追随。
 *
 * サーバ（`jin/applyOps`）は確定した式を正準形に揃えて返す（`a+1` → `a + 1`）。Enter で確定しても
 * フォーカスは入力に残るので、欄がそのまま `a+1` を見せ続けると blur でもう一度同じ式を確定して
 * しまう（同値のオペレーションが undo に積まれる）。ここではサーバ役の親を模して、確定回数と
 * 欄の表示を固定する。
 */

afterEach(cleanup);

interface HostProps {
	/** 親（App）の役: 確定した式を「サーバの正準形」に直して value として返す。 */
	readonly canonical: (text: string) => string;
	readonly commits: string[];
	/** undo / redo や別の欄の確定を模して、外から value を変える口。 */
	readonly expose?: (set: (value: string) => void) => void;
}

function Host(props: HostProps): React.JSX.Element {
	const [value, setValue] = useState("a");
	props.expose?.(setValue);
	return (
		<ExprEditor
			id="f"
			value={value}
			complete={null}
			onCommit={(text) => {
				props.commits.push(text);
				setValue(props.canonical(text));
			}}
		/>
	);
}

const canonical = (text: string): string =>
	text.replace(/\s*\+\s*/g, " + ").replace(/[()]/g, "");

function mount(commits: string[]): {
	readonly input: HTMLInputElement;
	readonly set: (value: string) => void;
} {
	let setter: (value: string) => void = () => undefined;
	const { getByTestId } = render(
		<Host
			canonical={canonical}
			commits={commits}
			expose={(set) => {
				setter = set;
			}}
		/>,
	);
	return {
		input: getByTestId("jin-expr-input") as HTMLInputElement,
		set: (value) => setter(value),
	};
}

test("Enter で確定するとサーバの正準形が欄に入り、blur でもう一度確定しない", () => {
	const commits: string[] = [];
	const { input } = mount(commits);
	act(() => {
		input.focus();
	});
	fireEvent.change(input, { target: { value: "a+(1)" } });
	fireEvent.keyDown(input, { key: "Enter" });
	expect(commits).toEqual(["a+(1)"]);
	expect(document.activeElement).toBe(input);
	expect(input.value).toBe("a + 1");
	fireEvent.blur(input);
	expect(commits).toEqual(["a+(1)"]);
});

test("確定後に打ち直した式は、次の確定でそのまま送られる", () => {
	const commits: string[] = [];
	const { input } = mount(commits);
	act(() => {
		input.focus();
	});
	fireEvent.change(input, { target: { value: "a+1" } });
	fireEvent.keyDown(input, { key: "Enter" });
	expect(input.value).toBe("a + 1");
	fireEvent.change(input, { target: { value: "a + 12" } });
	fireEvent.blur(input);
	expect(commits).toEqual(["a+1", "a + 12"]);
	expect(input.value).toBe("a + 12");
});

test("フォーカスが無ければ親の値にそのまま追随し（undo / redo）、入力中は打ちかけを守る", () => {
	const commits: string[] = [];
	const { input, set } = mount(commits);
	expect(input.value).toBe("a");
	act(() => {
		set("b");
	});
	expect(input.value).toBe("b");
	act(() => {
		input.focus();
	});
	fireEvent.change(input, { target: { value: "b+" } });
	act(() => {
		set("c");
	});
	expect(input.value).toBe("b+");
	expect(commits).toEqual([]);
});

test("同じ式のまま離れても確定しない", () => {
	const commits: string[] = [];
	const { input } = mount(commits);
	act(() => {
		input.focus();
	});
	fireEvent.keyDown(input, { key: "Enter" });
	fireEvent.blur(input);
	expect(commits).toEqual([]);
});
