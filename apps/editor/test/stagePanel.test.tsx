import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { rootCircleName, StagePanel, stageFps } from "../src/stage/StagePanel";

afterEach(cleanup);

describe("StagePanel（stage.md §6）", () => {
	test("iframe は ./stage/ を開き、隠すときは hidden", () => {
		render(<StagePanel svg="<svg/>" model={{ circles: [] }} rows={[]} seed={null} fileName="paddle.jin" circleName="Play" hidden />);
		const frame = screen.getByTestId("jin-stage") as HTMLIFrameElement;
		expect(frame.getAttribute("src")).toBe("./stage/");
		expect(screen.getByTestId("jin-stage-panel").hidden).toBe(true);
	});

	test("iframe が読み込まれたら stage.scene と stage.trace を送る", () => {
		const rows = [{ seq: 0, tick: -1, circle: "Play", kind: "enter", pointer: "/circles/1" }];
		render(
			<StagePanel
				svg="<svg/>"
				model={{ stage: { fps: 30 }, circles: [{ name: "Play", sigils: [{ name: "canvas" }] }] }}
				rows={rows}
				seed={7}
				fileName="paddle.jin"
				circleName="Play"
				hidden={false}
			/>,
		);
		const frame = screen.getByTestId("jin-stage") as HTMLIFrameElement;
		const post = vi.fn();
		Object.defineProperty(frame, "contentWindow", { value: { postMessage: post } });
		// load → setLoaded → effect で送る。state の更新と effect を流し切るため act で包む。
		act(() => {
			frame.dispatchEvent(new Event("load"));
		});
		const types = post.mock.calls.map(([message]) => (message as { type: string }).type);
		expect(types).toEqual(["stage.scene", "stage.trace"]);
		expect(post.mock.calls[0]?.[0]).toMatchObject({
			svg: "<svg/>",
			fps: 30,
			jinName: "paddle.jin",
			circleName: "Play",
			names: { Play: { pointer: "/circles/0", sigils: { canvas: "/circles/0/sigils/0" } } },
		});
		expect(post.mock.calls[1]?.[0]).toMatchObject({ rows, seed: 7 });
	});

	test("fps の既定は 60、陣名は focus の陣か root", () => {
		expect(stageFps({})).toBe(60);
		expect(stageFps({ stage: { fps: 24 } })).toBe(24);
		expect(rootCircleName({ root: "Game" }, null)).toBe("Game");
		expect(rootCircleName({ root: "Game" }, "Play/step")).toBe("Play");
		expect(rootCircleName({}, null)).toBe("");
	});
});
