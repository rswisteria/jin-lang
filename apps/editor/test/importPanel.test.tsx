import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { ImportPanel } from "../src/read/ImportPanel";
import type { ReadResult } from "../src/read/client";

afterEach(cleanup);

const RESULT: ReadResult = {
	jin: "file:///w/fib.jin",
	photo: "fib.jpg",
	scene: "fib.jinscene.json",
	image: { width: 1000, height: 500 },
	diagnostics: [
		{
			code: "JIN306",
			severity: "warning",
			message: "迷いを第一候補 1 で解きました",
			hint: "他の候補: l",
			pointer: "/bands/0/cells/3",
			box: [100, 50, 300, 250],
		},
		{
			code: "JIN301",
			severity: "error",
			message: "始まりの印がありません",
			hint: null,
			pointer: "/figures/0",
			box: null,
		},
	],
};

describe("ImportPanel（写真の下敷きと診断の重ね描き・陣書き S5）", () => {
	test("写真を出し、box のある診断だけを写真の上に % の矩形で重ねる", () => {
		render(
			<ImportPanel result={RESULT} photoUrl="blob:x" onClose={() => {}} />,
		);
		const photo = screen.getByTestId("jin-import-photo") as HTMLImageElement;
		expect(photo.getAttribute("src")).toBe("blob:x");
		const boxes = screen.getAllByTestId("jin-import-box");
		expect(boxes).toHaveLength(1);
		const style = boxes[0]!.style;
		expect(style.left).toBe("10%");
		expect(style.top).toBe("10%");
		expect(style.width).toBe("20%");
		expect(style.height).toBe("40%");
		expect(boxes[0]!.dataset["code"]).toBe("JIN306");
		expect(boxes[0]!.dataset["severity"]).toBe("warning");
		// 診断は位置の無いものも含めて全部並べる
		const items = screen.getAllByTestId("jin-import-diagnostic");
		expect(items.map((item) => item.textContent)).toEqual([
			expect.stringContaining("JIN306"),
			expect.stringContaining("JIN301"),
		]);
	});

	test("モデルを組めなかったら、場面グラフを直して取り込み直すよう伝える", () => {
		render(
			<ImportPanel
				result={{ ...RESULT, jin: null }}
				photoUrl="blob:x"
				onClose={() => {}}
			/>,
		);
		expect(screen.getByTestId("jin-import-summary").textContent).toContain(
			"fib.jinscene.json",
		);
	});

	test("閉じる", () => {
		const onClose = vi.fn();
		render(<ImportPanel result={RESULT} photoUrl="blob:x" onClose={onClose} />);
		screen.getByTestId("jin-import-close").click();
		expect(onClose).toHaveBeenCalledOnce();
	});
});
