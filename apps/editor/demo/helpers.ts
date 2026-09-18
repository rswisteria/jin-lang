import {
	type BrowserContext,
	expect,
	type Locator,
	type Page,
} from "@playwright/test";

/**
 * デモ動画の台本（`demo/*.spec.ts`）の共通部: 擬似カーソル・字幕・滑らかなクリック。
 *
 * Playwright の動画にはカーソルが写らないので、全フレームに入れる `<div>` を `addInitScript` で
 * 差し込む（iframe のプレイヤー / 鑑賞ページにも効く）。字幕は画面の左下の HTML 層。
 * テストではないが、各段が実際に起きたことは呼び出し側が `expect` で確かめる（動かないまま動画だけ出ると嘘になる）。
 */

/** 擬似カーソル（`mousemove` / `mousedown` / `mouseup` を追う）。`beforeEach` で context に掛ける。 */
export async function installCursor(context: BrowserContext): Promise<void> {
	await context.addInitScript(() => {
		window.addEventListener("DOMContentLoaded", () => {
			const cursor = document.createElement("div");
			cursor.id = "jin-demo-cursor";
			cursor.style.cssText =
				"position:fixed;left:-100px;top:-100px;width:22px;height:22px;pointer-events:none;z-index:2147483647;" +
				"transform:translate(-4px,-2px);";
			cursor.innerHTML =
				'<svg width="22" height="22" viewBox="0 0 22 22"><path d="M3 2 L3 18 L7.5 13.5 L11 20 L13.5 19 L10 12.5 L16 12.5 Z" ' +
				'fill="#fff" stroke="#000" stroke-width="1.5" stroke-linejoin="round"/></svg>';
			document.body.appendChild(cursor);
			window.addEventListener(
				"mousemove",
				(ev) => {
					cursor.style.left = `${String(ev.clientX)}px`;
					cursor.style.top = `${String(ev.clientY)}px`;
				},
				true,
			);
			window.addEventListener(
				"mousedown",
				() => {
					cursor.style.transform = "translate(-4px,-2px) scale(0.85)";
				},
				true,
			);
			window.addEventListener(
				"mouseup",
				() => {
					cursor.style.transform = "translate(-4px,-2px)";
				},
				true,
			);
		});
	});
}

export const pause = (page: Page, ms: number): Promise<void> =>
	page.waitForTimeout(ms);

/** 画面の左下に字幕を出す（動画の各段の説明）。 */
export async function caption(page: Page, text: string): Promise<void> {
	await page.evaluate((message) => {
		let bar = document.getElementById("jin-demo-caption");
		if (bar === null) {
			bar = document.createElement("div");
			bar.id = "jin-demo-caption";
			bar.style.cssText =
				"position:fixed;left:24px;bottom:18px;max-width:60%;" +
				"padding:10px 18px;border-radius:8px;background:rgba(20,20,24,0.88);color:#fff;" +
				"font:600 20px/1.4 system-ui,sans-serif;letter-spacing:0.02em;z-index:2147483646;" +
				"box-shadow:0 4px 18px rgba(0,0,0,0.35);pointer-events:none;white-space:nowrap;";
			document.body.appendChild(bar);
		}
		bar.textContent = message;
	}, text);
}

/** 要素の中心へ滑らかに動く（クリックだけだとカーソルが跳ぶ）。 */
export async function glideTo(page: Page, target: Locator): Promise<void> {
	const box = await target.boundingBox();
	if (box === null) throw new Error("要素が見えない");
	await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, {
		steps: 24,
	});
}

export async function glideClick(page: Page, target: Locator): Promise<void> {
	await glideTo(page, target);
	await pause(page, 250);
	await target.click();
}

/**
 * 欄へ滑らかに移って、消してから 1 文字ずつ打ち、Tab で確定する。
 * 式の欄は打っている間に補完の候補が出る（Tab / Enter は候補の確定になる）ので、Escape で閉じてから Tab で抜ける。
 */
export async function typeInto(
	page: Page,
	field: Locator,
	text: string,
): Promise<void> {
	await glideClick(page, field);
	await pause(page, 300);
	await field.fill("");
	await field.pressSequentially(text, { delay: 110 });
	await pause(page, 450);
	await field.press("Escape");
	await field.press("Tab");
}

/** エディタが v2 で準備完了になるまで待つ。右のパネルは見せるために広げる（製品の CSS は変えない）。 */
export async function openEditor(page: Page, url: string): Promise<void> {
	await page.goto(url);
	await page.addStyleTag({
		content:
			".jin-side { width: 42rem !important; } .jin-player { height: 42rem !important; }",
	});
	await expect(page.getByTestId("jin-status")).toHaveAttribute(
		"data-state",
		"ready",
	);
	await expect(page.locator("main.jin-app")).toHaveAttribute(
		"data-version",
		"2",
	);
}

/**
 * 塗りの無い SVG 要素（記憶の四角・額縁・環）に**当たる点**を探す（`e2e/v2.spec.ts` の `pointOn` と同じ）:
 * 外接矩形の 9 点と輪郭上の 21 点を `elementFromPoint` で確かめ、最初に当たった点を返す。
 */
export async function hitPoint(
	target: Locator,
): Promise<{ x: number; y: number }> {
	let found: { x: number; y: number } | null = null;
	await expect(async () => {
		found = await hitOnce(target);
		expect(found, "要素に当たる点が見つからない").not.toBeNull();
	}).toPass({ timeout: 20_000 });
	return found!;
}

async function hitOnce(
	target: Locator,
): Promise<{ x: number; y: number } | null> {
	await expect(target.first()).toBeAttached();
	await target.first().scrollIntoViewIfNeeded();
	return target.evaluateAll((elements) => {
		const candidates: { x: number; y: number }[] = [];
		for (const element of elements) {
			const box = element.getBoundingClientRect();
			for (const fx of [0.5, 0.25, 0.75]) {
				for (const fy of [0.5, 0.25, 0.75]) {
					candidates.push({
						x: box.left + box.width * fx,
						y: box.top + box.height * fy,
					});
				}
			}
			if (element instanceof SVGGeometryElement) {
				const matrix = element.getScreenCTM();
				const length = element.getTotalLength();
				for (let k = 0; matrix !== null && k <= 20; k += 1) {
					const at = element
						.getPointAtLength((length * k) / 20)
						.matrixTransform(matrix);
					candidates.push({ x: at.x, y: at.y });
				}
			}
		}
		return (
			candidates.find((candidate) => {
				const found = document.elementFromPoint(candidate.x, candidate.y);
				return found !== null && (elements as Element[]).includes(found);
			}) ?? null
		);
	});
}

/** 当たる点へ滑らかに動いてクリック（塗りの無い SVG 要素向け）。 */
export async function glideHit(
	page: Page,
	target: Locator,
	options?: { readonly dblclick?: boolean },
): Promise<void> {
	const point = await hitPoint(target);
	await page.mouse.move(point.x, point.y, { steps: 24 });
	await pause(page, 250);
	if (options?.dblclick === true) await page.mouse.dblclick(point.x, point.y);
	else await page.mouse.click(point.x, point.y);
}
