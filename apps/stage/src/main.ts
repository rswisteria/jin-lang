import { type CameraOffset, type CameraPreset, NO_OFFSET } from "./camera";
import { chooseCodec } from "./codec";
import { type Firing, foldTrace, glowsAt, tickSpan } from "./effects";
import { runExport } from "./exporter";
import { exportFileName } from "./exportName";
import { canEncode, createEncoder } from "./mediabunnyEncoder";
import {
	fileMessage,
	type Inbound,
	parseInbound,
	type SceneMessage,
	type StageStatus,
	statusMessage,
} from "./messages";
import type { TraceRow } from "./names";
import { captionText, Composer2D } from "./render/compose";
import { StageRenderer } from "./render/stageRenderer";
import { parseScene, SceneError } from "./scene";
import {
	type Aspect,
	clampRange,
	MAX_PNG_LONG_SIDE,
	outputSize,
	type Speed,
} from "./timeline";

/**
 * 鑑賞ページの入口（docs/spec/v2/stage.md）。エディタ（親）から `stage.scene` / `stage.trace` を受け、
 * プレビューを描く。**message の受け取り元は `window.parent` に限る**（プレイヤーと同じ規律）。
 */
const element = <T extends HTMLElement>(id: string): T => {
	const found = document.getElementById(id);
	if (found === null) throw new Error(`#${id} がありません`);
	return found as T;
};

const host = element<HTMLDivElement>("stage");
const canvas = document.createElement("canvas");
host.appendChild(canvas);
const renderer = new StageRenderer(canvas);
const play = element<HTMLButtonElement>("play");
const scrub = element<HTMLInputElement>("scrub");
const tickOut = element<HTMLOutputElement>("tick");
const preset = element<HTMLSelectElement>("preset");
const statusText = element<HTMLSpanElement>("status");
const rowsText = element<HTMLSpanElement>("rows");
const start = element<HTMLInputElement>("start");
const end = element<HTMLInputElement>("end");

export const state = {
	scene: null as SceneMessage | null,
	rows: [] as readonly TraceRow[],
	seed: null as number | null,
	firings: [] as readonly Firing[],
	tick: 0,
	playing: false,
	offset: NO_OFFSET as CameraOffset,
	/** 書き出しの範囲を人が打ち直したか。打ち直していなければトレースが来るたびに全体へ広げる。 */
	rangeEdited: false,
	status: {
		ready: false,
		rows: 0,
		codec: null,
		exporting: null,
		error: null,
	} as StageStatus,
};

/** 書き出し中の中止口。動画と PNG の両方がここを立てる（重ねて走らせない・プレビューが canvas を上書きしない）。 */
let exporting: AbortController | null = null;

function report(patch: Partial<StageStatus>): void {
	state.status = { ...state.status, ...patch };
	const progress = state.status.exporting;
	statusText.textContent =
		state.status.error ??
		(progress !== null
			? `書き出し中 ${String(progress.done)} / ${String(progress.total)}`
			: state.status.ready
				? "準備完了"
				: "SVG を待っています");
	rowsText.textContent = String(state.status.rows);
	window.parent.postMessage(
		statusMessage(state.status),
		window.location.origin,
	);
}

function refire(): void {
	state.firings =
		state.scene === null ? [] : foldTrace(state.rows, state.scene.names);
	const span = tickSpan(state.rows);
	scrub.min = String(span.first);
	scrub.max = String(span.last);
	// 書き出しの範囲の既定は全体。走らせている間は 1 秒ごとにトレースが届くので、人が打った範囲は上書きしない。
	if (!state.rangeEdited) {
		start.value = String(span.first);
		end.value = String(span.last);
	}
}

function viewAspect(): number {
	return Math.max(1, host.clientWidth) / Math.max(1, host.clientHeight);
}

function drawAt(tick: number): void {
	if (state.scene === null) return;
	renderer.draw({
		tick,
		fps: state.scene.fps,
		glows: glowsAt(state.firings, tick, state.scene.fps),
		preset: preset.value as CameraPreset,
		aspect: viewAspect(),
		offset: state.offset,
	});
}

// 手で動かす（設計書 §2.5・stage.md §4）: 横 1 px = 0.3°、縦 1 px = 0.2°。仰角の範囲は cameraPose が収める。
let dragging: { x: number; y: number } | null = null;
canvas.addEventListener("pointerdown", (event) => {
	// 書き出し中は構図を動かさない（書き出しは押した瞬間の構図で描く）。
	if (exporting !== null) return;
	dragging = { x: event.clientX, y: event.clientY };
	canvas.setPointerCapture(event.pointerId);
});
canvas.addEventListener("pointermove", (event) => {
	if (dragging === null) return;
	state.offset = {
		azimuthDeg: state.offset.azimuthDeg - (event.clientX - dragging.x) * 0.3,
		elevationDeg: Math.max(
			-90,
			Math.min(
				90,
				state.offset.elevationDeg + (event.clientY - dragging.y) * 0.2,
			),
		),
	};
	dragging = { x: event.clientX, y: event.clientY };
});
canvas.addEventListener("pointerup", () => {
	dragging = null;
});
preset.addEventListener("change", () => {
	state.offset = NO_OFFSET;
});

/** 書き出し中に届いた語（種類ごとに最後の 1 つ）。書き出しが終わってから当てる（1 本の書き出しの中で場面を変えない）。 */
const pending: { scene: Inbound | null; trace: Inbound | null } = {
	scene: null,
	trace: null,
};

window.addEventListener("message", (event: MessageEvent<unknown>) => {
	if (event.source !== window.parent || event.origin !== window.location.origin)
		return;
	const message = parseInbound(event.data);
	if (message === null) return;
	if (exporting !== null) {
		pending[message.type] = message;
		return;
	}
	applyInbound(message);
});

function applyInbound(message: Inbound): void {
	if (message.type === "scene") {
		try {
			renderer.setScene(parseScene(message.value.svg));
			state.scene = message.value;
			refire();
			report({ ready: true, error: null });
		} catch (error) {
			report({
				ready: false,
				error:
					error instanceof SceneError
						? `陣を読めません: ${error.message}`
						: String(error),
			});
		}
	} else {
		state.rows = message.value.rows;
		state.seed = message.value.seed;
		refire();
		// 巻き戻さない: 走らせている間は行が 1 秒ごとに足されて届くので、今の位置を新しい範囲に収めるだけ。
		state.tick = Math.min(
			Math.max(state.tick, Number(scrub.min)),
			Number(scrub.max),
		);
		scrub.value = String(state.tick);
		report({ rows: state.rows.length });
	}
}

function resizeToView(): void {
	renderer.resize(
		host.clientWidth,
		host.clientHeight,
		Math.min(window.devicePixelRatio, 2),
	);
}

// 書き出し中は出力の大きさで描いているので、表示の大きさに戻さない（終わったら withExportSize が戻す）。
new ResizeObserver(() => {
	if (exporting === null) resizeToView();
}).observe(host);

play.addEventListener("click", () => {
	state.playing = !state.playing;
	play.textContent = state.playing ? "一時停止" : "再生";
});
scrub.addEventListener("input", () => {
	state.tick = Number(scrub.value);
	state.playing = false;
	play.textContent = "再生";
});

// ---- 書き出し（stage.md §5）: 1 コマずつ描いて WebCodecs に渡す。実時間の録画はしない ----

const aspect = element<HTMLSelectElement>("aspect");
const resolution = element<HTMLSelectElement>("resolution");
const speed = element<HTMLSelectElement>("speed");
const caption = element<HTMLInputElement>("caption");
const exportVideo = element<HTMLButtonElement>("export-video");
const exportPng = element<HTMLButtonElement>("export-png");
const cancel = element<HTMLButtonElement>("cancel");
const codecText = element<HTMLSpanElement>("codec");
const composer = new Composer2D();

/** e2e だけが使う長辺の上書き（`?export=360`）。UI の選択肢には出さない。 */
const overrideLongSide =
	Number(new URLSearchParams(window.location.search).get("export") ?? "") ||
	null;

function exportSize(longSideCap: number): { width: number; height: number } {
	const longSide = Math.min(
		overrideLongSide ?? Number(resolution.value),
		longSideCap,
	);
	return outputSize(aspect.value as Aspect, longSide);
}

async function refreshCodec(): Promise<void> {
	const { width, height } = exportSize(Number.POSITIVE_INFINITY);
	const choice = await chooseCodec(canEncode, width, height);
	codecText.textContent =
		choice === null
			? "この環境では動画を書き出せません"
			: choice.container === "mp4"
				? "MP4（H.264）"
				: "WebM（VP9）";
	exportVideo.disabled = choice === null;
	report({ codec: choice?.codec ?? null });
}

function withExportSize<T>(
	width: number,
	height: number,
	body: () => Promise<T>,
): Promise<T> {
	renderer.resize(width, height, 1);
	composer.resize(width, height);
	return body().finally(resizeToView);
}

/**
 * 書き出しの入力の写し（押した瞬間に取る）。1 本の書き出しの中でトレース・構図・銘が途中で変わらないようにする
 * （設計書 §3.1「同じトレース + 設定 → 同じ場面の列」）。
 */
interface ExportSnapshot {
	readonly scene: SceneMessage;
	readonly seed: number | null;
	readonly firings: readonly Firing[];
	readonly preset: CameraPreset;
	readonly offset: CameraOffset;
	readonly caption: string | null;
}

function snapshot(scene: SceneMessage): ExportSnapshot {
	return {
		scene,
		seed: state.seed,
		firings: state.firings,
		preset: preset.value as CameraPreset,
		offset: state.offset,
		caption: caption.checked ? captionText(scene.circleName) : null,
	};
}

function drawFor(
	shot: ExportSnapshot,
	tick: number,
	width: number,
	height: number,
): void {
	renderer.draw({
		tick,
		fps: shot.scene.fps,
		glows: glowsAt(shot.firings, tick, shot.scene.fps),
		preset: shot.preset,
		aspect: width / height,
		offset: shot.offset,
	});
	composer.compose(canvas, shot.caption);
}

/** 書き出し中に動かせる欄を止める（再開時はコーデックを判定し直して動画ボタンを戻す）。 */
const exportControls = [
	preset,
	aspect,
	resolution,
	speed,
	start,
	end,
	caption,
	exportVideo,
	exportPng,
];

function beginExport(controller: AbortController): void {
	exporting = controller;
	for (const control of exportControls) control.disabled = true;
}

function endExport(): void {
	exporting = null;
	cancel.hidden = true;
	for (const control of exportControls) control.disabled = false;
	void refreshCodec();
	const { scene, trace } = pending;
	pending.scene = null;
	pending.trace = null;
	if (scene !== null) applyInbound(scene);
	if (trace !== null) applyInbound(trace);
}

/** 親へバイト列を渡す（転送するので、渡す ArrayBuffer はちょうどの長さの単独のものに限る）。 */
function send(name: string, mime: string, bytes: ArrayBuffer): void {
	window.parent.postMessage(
		fileMessage(name, mime, bytes),
		window.location.origin,
		[bytes],
	);
}

function pause(): void {
	state.playing = false;
	play.textContent = "再生";
}

exportVideo.addEventListener("click", () => {
	const scene = state.scene;
	if (scene === null || exporting !== null) return;
	const controller = new AbortController();
	const shot = snapshot(scene);
	beginExport(controller);
	cancel.hidden = false;
	pause();
	void (async () => {
		// 名前と中身の範囲を揃える（runExport も同じ clampRange をかけるが、名前には並べ替え・60 秒で切った値を使う）。
		const range = clampRange({
			startTick: Number(start.value),
			endTick: Number(end.value),
			fps: scene.fps,
			speed: Number(speed.value) as Speed,
		});
		try {
			const { width, height } = exportSize(Number.POSITIVE_INFINITY);
			const choice = await chooseCodec(canEncode, width, height);
			if (choice === null) {
				report({ exporting: null, error: "この環境では動画を書き出せません" });
				return;
			}
			const bytes = await withExportSize(width, height, async () =>
				runExport({
					range,
					draw: (tick) => drawFor(shot, tick, width, height),
					encoder: await createEncoder(composer.canvas, choice),
					signal: controller.signal,
					onProgress: (done, total) => report({ exporting: { done, total } }),
				}),
			);
			if (bytes !== null) {
				const name = exportFileName({
					jinName: scene.jinName,
					circleName: scene.circleName,
					seed: shot.seed,
					startTick: range.startTick,
					endTick: range.endTick,
					extension: choice.container,
				});
				// slice() でちょうどの長さの単独の ArrayBuffer にしてから転送する。
				send(name, choice.mime, bytes.slice().buffer);
			}
			report({ exporting: null, error: null });
		} catch (error) {
			report({
				exporting: null,
				error: `書き出しに失敗しました: ${error instanceof Error ? error.message : String(error)}`,
			});
		} finally {
			endExport();
		}
	})();
});

exportPng.addEventListener("click", () => {
	const scene = state.scene;
	if (scene === null || exporting !== null) return;
	const shot = snapshot(scene);
	const tick = state.tick;
	beginExport(new AbortController());
	const { width, height } = exportSize(MAX_PNG_LONG_SIDE);
	void withExportSize(width, height, async () => {
		drawFor(shot, tick, width, height);
		const bytes = await composer.toPng();
		const rounded = Math.round(tick);
		send(
			exportFileName({
				jinName: scene.jinName,
				circleName: scene.circleName,
				seed: shot.seed,
				startTick: rounded,
				endTick: rounded,
				extension: "png",
			}),
			"image/png",
			bytes,
		);
	})
		.catch((error: unknown) =>
			report({ error: `PNG を作れません: ${String(error)}` }),
		)
		.finally(endExport);
});

cancel.addEventListener("click", () => exporting?.abort());
start.addEventListener("input", () => {
	state.rangeEdited = true;
});
end.addEventListener("input", () => {
	state.rangeEdited = true;
});
aspect.addEventListener("change", () => void refreshCodec());
resolution.addEventListener("change", () => void refreshCodec());
void refreshCodec();

let last = performance.now();
function loop(now: number): void {
	const dt = (now - last) / 1000;
	last = now;
	if (state.playing && state.scene !== null) {
		state.tick += dt * state.scene.fps;
		if (state.tick > Number(scrub.max)) state.tick = Number(scrub.min);
		scrub.value = String(state.tick);
	}
	tickOut.textContent = String(Math.floor(state.tick));
	// 書き出し中は出力の大きさの canvas をプレビューで上書きしない。
	if (exporting === null) drawAt(state.tick);
	requestAnimationFrame(loop);
}
requestAnimationFrame(loop);
report({});
