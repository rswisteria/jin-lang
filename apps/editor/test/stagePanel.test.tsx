import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";

import {
	rootCircleName,
	StagePanel,
	stageFps,
	stageSizeOf,
} from "../src/stage/StagePanel";

describe("舞台の大きさ（stage.scene の stageSize・仕様書 2026-10-01-jin-stage-summon §2.1）", () => {
	test("モデルの stage の width / height を渡す", () => {
		expect(
			stageSizeOf({ stage: { width: 176, height: 120, fps: 30 } }),
		).toEqual({ width: 176, height: 120 });
	});
	test("無い・数でない・0 以下なら null", () => {
		expect(stageSizeOf(null)).toBeNull();
		expect(stageSizeOf({ stage: { fps: 30 } })).toBeNull();
		expect(stageSizeOf({ stage: { width: "x", height: 120 } })).toBeNull();
		expect(stageSizeOf({ stage: { width: 0, height: 120 } })).toBeNull();
	});
});

afterEach(cleanup);

describe("StagePanel（stage.md §6）", () => {
	test("iframe は ./stage/ を開き、隠すときは hidden", () => {
		render(
			<StagePanel
				svg="<svg/>"
				inscription={null}
				model={{ circles: [] }}
				rows={[]}
				seed={null}
				fileName="paddle.jin"
				circleName="Play"
				hidden
				panorama={false}
				panoramaOn
				onPanoramaChange={() => undefined}
			/>,
		);
		const frame = screen.getByTestId("jin-stage") as HTMLIFrameElement;
		expect(frame.getAttribute("src")).toBe("./stage/");
		expect(screen.getByTestId("jin-stage-panel").hidden).toBe(true);
	});

	test("iframe が読み込まれたら stage.scene と stage.trace を送る", () => {
		const rows = [
			{
				seq: 0,
				tick: -1,
				circle: "Play",
				kind: "enter",
				pointer: "/circles/1",
			},
		];
		render(
			<StagePanel
				svg="<svg/>"
				inscription={null}
				model={{
					stage: { fps: 30 },
					circles: [{ name: "Play", sigils: [{ name: "canvas" }] }],
				}}
				rows={rows}
				seed={7}
				fileName="paddle.jin"
				circleName="Play"
				hidden={false}
				panorama={false}
				panoramaOn
				onPanoramaChange={() => undefined}
			/>,
		);
		const frame = screen.getByTestId("jin-stage") as HTMLIFrameElement;
		const post = vi.fn();
		Object.defineProperty(frame, "contentWindow", {
			value: { postMessage: post },
		});
		// load → setLoaded → effect で送る。state の更新と effect を流し切るため act で包む。
		act(() => {
			frame.dispatchEvent(new Event("load"));
		});
		const types = post.mock.calls.map(
			([message]) => (message as { type: string }).type,
		);
		expect(types).toEqual(["stage.scene", "stage.trace"]);
		expect(post.mock.calls[0]?.[0]).toMatchObject({
			svg: "<svg/>",
			fps: 30,
			jinName: "paddle.jin",
			circleName: "Play",
			// 舞台の大きさの無いモデル → stageSize は null（鑑賞ページは窓を出さない）
			stageSize: null,
			names: {
				Play: {
					pointer: "/circles/0",
					sigils: { canvas: "/circles/0/sigils/0" },
				},
			},
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

describe("StagePanel は同じ内容を送り直さない（stage.md §6）", () => {
	const model = {
		stage: { fps: 30 },
		circles: [{ name: "Play", sigils: [{ name: "canvas" }] }],
	};
	const rows = [
		{ seq: 0, tick: -1, circle: "Play", kind: "enter", pointer: "/circles/1" },
	];

	function panel(
		currentRows: typeof rows,
		currentModel: Record<string, unknown>,
	): React.JSX.Element {
		return (
			<StagePanel
				svg="<svg/>"
				inscription={null}
				model={currentModel}
				rows={currentRows}
				seed={7}
				fileName="paddle.jin"
				circleName="Play"
				hidden={false}
				panorama={false}
				panoramaOn
				onPanoramaChange={() => undefined}
			/>
		);
	}

	function loaded() {
		const view = render(panel(rows, model));
		const frame = screen.getByTestId("jin-stage") as HTMLIFrameElement;
		const post = vi.fn();
		Object.defineProperty(frame, "contentWindow", {
			value: { postMessage: post },
		});
		act(() => {
			frame.dispatchEvent(new Event("load"));
		});
		const types = (): string[] =>
			post.mock.calls.map(([message]) => (message as { type: string }).type);
		return { view, types };
	}

	test("中身が同じ新しい model と同じ svg では stage.scene を送り直さない", () => {
		const { view, types } = loaded();
		expect(types()).toEqual(["stage.scene", "stage.trace"]);
		view.rerender(panel(rows, structuredClone(model)));
		expect(types()).toEqual(["stage.scene", "stage.trace"]);
	});

	test("同じ rows の配列では stage.trace を送り直さず、別の配列なら送る", () => {
		const { view, types } = loaded();
		view.rerender(panel(rows, model));
		expect(types()).toEqual(["stage.scene", "stage.trace"]);
		view.rerender(panel([...rows], model));
		expect(types()).toEqual(["stage.scene", "stage.trace", "stage.trace"]);
	});
});

describe("StagePanel は舞台の大きさを stage.scene の stageSize で送る（仕様書 2026-10-01-jin-stage-summon §2.1）", () => {
	function panel(stage: Record<string, unknown>): React.JSX.Element {
		return (
			<StagePanel
				svg="<svg/>"
				inscription={null}
				model={{ stage, circles: [{ name: "Play", sigils: [] }] }}
				rows={[]}
				seed={7}
				fileName="tetris.jin"
				circleName="Play"
				hidden={false}
				panorama={false}
				panoramaOn
				onPanoramaChange={() => undefined}
			/>
		);
	}

	test("舞台のあるモデルでは stageSize が数の { width, height } で届き、大きさが変われば送り直す", () => {
		const view = render(panel({ width: 176, height: 120, fps: 30 }));
		const frame = screen.getByTestId("jin-stage") as HTMLIFrameElement;
		const post = vi.fn();
		Object.defineProperty(frame, "contentWindow", {
			value: { postMessage: post },
		});
		act(() => {
			frame.dispatchEvent(new Event("load"));
		});
		const scenes = (): unknown[] =>
			post.mock.calls
				.map(([message]) => message as { type: string; stageSize?: unknown })
				.filter((message) => message.type === "stage.scene")
				.map((message) => message.stageSize);
		expect(scenes()).toEqual([{ width: 176, height: 120 }]);
		// 同じ大きさなら送り直さない。
		view.rerender(panel({ width: 176, height: 120, fps: 30 }));
		expect(scenes()).toHaveLength(1);
		view.rerender(panel({ width: 320, height: 240, fps: 30 }));
		expect(scenes()).toEqual([
			{ width: 176, height: 120 },
			{ width: 320, height: 240 },
		]);
	});
});

describe("StagePanel は銘環の帯を stage.scene の inscription で送る（陣書き S7・stage.md §2.2）", () => {
	function panel(inscription: string | null): React.JSX.Element {
		return (
			<StagePanel
				svg="<svg/>"
				inscription={inscription}
				model={{ circles: [{ name: "Play", sigils: [] }] }}
				rows={[]}
				seed={7}
				fileName="fib.jin"
				circleName="Play"
				hidden={false}
				panorama={false}
				panoramaOn
				onPanoramaChange={() => undefined}
			/>
		);
	}

	test("帯が届くと送り直し、同じ帯なら送らない", () => {
		const view = render(panel(null));
		const frame = screen.getByTestId("jin-stage") as HTMLIFrameElement;
		const post = vi.fn();
		Object.defineProperty(frame, "contentWindow", {
			value: { postMessage: post },
		});
		act(() => {
			frame.dispatchEvent(new Event("load"));
		});
		const bands = (): unknown[] =>
			post.mock.calls
				.map(([message]) => message as { type: string; inscription?: unknown })
				.filter((message) => message.type === "stage.scene")
				.map((message) => message.inscription);
		expect(bands()).toEqual([null]);
		view.rerender(panel("<svg>band</svg>"));
		view.rerender(panel("<svg>band</svg>"));
		expect(bands()).toEqual([null, "<svg>band</svg>"]);
	});
});

describe("StagePanel は全景を stage.scene の panorama で知らせる（stage.md §2.3・Issue #132）", () => {
	function panel(
		panorama: boolean,
		onPanoramaChange: (on: boolean) => void = () => undefined,
	): React.JSX.Element {
		return (
			<StagePanel
				svg={panorama ? "<svg>whole</svg>" : "<svg/>"}
				inscription={null}
				model={{ circles: [{ name: "Play", sigils: [] }] }}
				rows={[]}
				seed={7}
				fileName="tetris-plus.jin"
				circleName="Game"
				hidden={false}
				panorama={panorama}
				panoramaOn
				onPanoramaChange={onPanoramaChange}
			/>
		);
	}

	test("全景か否かを欄で送り、切り替えると送り直す", () => {
		const view = render(panel(true));
		const frame = screen.getByTestId("jin-stage") as HTMLIFrameElement;
		const post = vi.fn();
		Object.defineProperty(frame, "contentWindow", {
			value: { postMessage: post },
		});
		act(() => {
			frame.dispatchEvent(new Event("load"));
		});
		const flags = (): unknown[] =>
			post.mock.calls
				.map(([message]) => message as { type: string; panorama?: unknown })
				.filter((message) => message.type === "stage.scene")
				.map((message) => message.panorama);
		expect(flags()).toEqual([true]);
		view.rerender(panel(false));
		expect(flags()).toEqual([true, false]);
	});

	test("「全景」のチェックは既定の状態を映し、外すと知らせる", () => {
		const changes: boolean[] = [];
		render(panel(true, (on) => changes.push(on)));
		const box = screen.getByTestId("jin-stage-panorama") as HTMLInputElement;
		expect(box.checked).toBe(true);
		act(() => {
			box.click();
		});
		expect(changes).toEqual([false]);
	});
});
