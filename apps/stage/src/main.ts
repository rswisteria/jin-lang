import { type CameraOffset, type CameraPreset, NO_OFFSET } from "./camera";
import { type Firing, foldTrace, glowsAt, tickSpan } from "./effects";
import {
	parseInbound,
	type SceneMessage,
	type StageStatus,
	statusMessage,
} from "./messages";
import type { TraceRow } from "./names";
import { StageRenderer } from "./render/stageRenderer";
import { parseScene, SceneError } from "./scene";

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

export const state = {
	scene: null as SceneMessage | null,
	rows: [] as readonly TraceRow[],
	seed: null as number | null,
	firings: [] as readonly Firing[],
	tick: 0,
	playing: false,
	offset: NO_OFFSET as CameraOffset,
	status: {
		ready: false,
		rows: 0,
		codec: null,
		exporting: null,
		error: null,
	} as StageStatus,
};

function report(patch: Partial<StageStatus>): void {
	state.status = { ...state.status, ...patch };
	statusText.textContent =
		state.status.error ??
		(state.status.ready ? "準備完了" : "SVG を待っています");
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

window.addEventListener("message", (event: MessageEvent<unknown>) => {
	if (event.source !== window.parent || event.origin !== window.location.origin)
		return;
	const message = parseInbound(event.data);
	if (message === null) return;
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
});

new ResizeObserver(() =>
	renderer.resize(
		host.clientWidth,
		host.clientHeight,
		Math.min(window.devicePixelRatio, 2),
	),
).observe(host);

play.addEventListener("click", () => {
	state.playing = !state.playing;
	play.textContent = state.playing ? "一時停止" : "再生";
});
scrub.addEventListener("input", () => {
	state.tick = Number(scrub.value);
	state.playing = false;
	play.textContent = "再生";
});

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
	drawAt(state.tick);
	requestAnimationFrame(loop);
}
requestAnimationFrame(loop);
report({});
