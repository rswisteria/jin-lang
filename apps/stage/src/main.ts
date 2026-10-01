import { type CameraOffset, type CameraPreset, NO_OFFSET } from "./camera";
import { chooseCodec } from "./codec";
import { type Firing, foldTrace, glowsAt, tickSpan } from "./effects";
import { runExport } from "./exporter";
import { exportFileName } from "./exportName";
import { drawOps, type Op } from "./screen/draw";
import { frameAt, framesOf, type ScreenFrame, windowAt } from "./screen/frames";
import { synthesize, TONE_GAIN } from "./screen/sound";
import {
	canEncode,
	canEncodeAudioTrack,
	createEncoder,
} from "./mediabunnyEncoder";
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
// e2e の口（GPU の資源が送り直しで増えないことを見る）。window に生やすのは main.ts だけ。
(window as unknown as { __jinStage: { memory(): unknown } }).__jinStage = {
	memory: () => renderer.memory(),
	summon: () => renderer.summonShown(),
	// プレビューで描いた回数（隠れている間は増えない・e2e の口）。
	draws: () => previewDraws,
	// 召喚の窓の描画の写し（screen/draw.ts）で表示リストを描いた PNG（プレイヤーと同じ正解と画素一致を見る e2e の口）。
	renderOps: (ops: readonly Op[], width: number, height: number): string => {
		const surface = document.createElement("canvas");
		surface.width = width;
		surface.height = height;
		const context = surface.getContext("2d");
		if (context === null) throw new Error("2D の描画面が取れません");
		drawOps(context, ops, width, height);
		return surface.toDataURL("image/png");
	},
	// 音声のコーデックの可否（probe §G・e2e の口）。
	audioCodecs: async () => ({
		aac: await canEncodeAudioTrack("aac"),
		opus: await canEncodeAudioTrack("opus"),
	}),
} as { memory(): unknown };
const play = element<HTMLButtonElement>("play");
const mute = element<HTMLButtonElement>("mute");
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
	/** 召喚の窓のコマ（トレースの frame 行・screen/frames.ts）。 */
	frames: [] as readonly ScreenFrame[],
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
	state.frames = framesOf(state.rows);
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

/** プレビューで描いた回数（e2e の口 `__jinStage.draws()`）。 */
let previewDraws = 0;

function drawAt(tick: number): void {
	if (state.scene === null) return;
	previewDraws++;
	renderer.draw({
		tick,
		fps: state.scene.fps,
		glows: glowsAt(state.firings, tick, state.scene.fps),
		preset: preset.value as CameraPreset,
		aspect: viewAspect(),
		offset: state.offset,
		screen: frameAt(state.frames, tick),
		window: windowAt(
			state.rows,
			state.frames,
			state.scene.names,
			tick,
			state.scene.fps,
		),
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
			renderer.setScene(
				parseScene(message.value.svg),
				message.value.names,
				message.value.stageSize,
			);
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
	unlockAudio();
	lastSoundTick = Math.floor(state.tick);
});
mute.addEventListener("click", () => {
	muted = !muted;
	mute.setAttribute("aria-pressed", String(muted));
	mute.textContent = muted ? "音: 切" : "音: 入";
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

/** e2e だけが使う「音声のコーデックが無い」環境（`?noaudio=1`・無音で書き出す分岐を通す）。 */
const NO_AUDIO =
	new URLSearchParams(window.location.search).get("noaudio") === "1";

/**
 * プレビューの音（仕様書 2026-10-01-jin-stage-summon §3.2）: 再生中に tick が進むたびに、その tick のコマの `tone` を
 * プレイヤーと同じ矩形波・音量で鳴らす。スクラブ中と消音中は鳴らさない。`AudioContext` は再生ボタンの操作で作る
 * （実時間の時計を読むのは main.ts だけ）。
 */
let audioContext: AudioContext | null = null;
let muted = false;
let lastSoundTick = Number.NaN;

function unlockAudio(): void {
	if (typeof AudioContext === "undefined") return;
	audioContext ??= new AudioContext();
	if (audioContext.state === "suspended") void audioContext.resume();
}

function soundTick(tick: number): void {
	const ctx = audioContext;
	const whole = Math.floor(tick);
	const previous = lastSoundTick;
	lastSoundTick = whole;
	if (ctx === null || muted || !state.playing || ctx.state !== "running")
		return;
	if (!(whole > previous) || whole - previous > 4) return;
	for (let t = previous + 1; t <= whole; t++) {
		const frame = frameAt(state.frames, t);
		if (frame === null || frame.tick !== t) continue;
		for (const [name, ...args] of frame.audio) {
			const hz = typeof args[0] === "number" ? args[0] : 0;
			const ms = typeof args[1] === "number" ? args[1] : 0;
			if (name !== "tone" || !(hz > 0) || !(ms > 0)) continue;
			const osc = ctx.createOscillator();
			osc.type = "square";
			osc.frequency.value = hz;
			const gain = ctx.createGain();
			gain.gain.value = TONE_GAIN;
			osc.connect(gain).connect(ctx.destination);
			osc.start();
			osc.stop(ctx.currentTime + ms / 1000);
		}
	}
}

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
	// e2e は表示文ではなくこの値で書き出せるかを見る（確かめ終えるまで属性が無い）。
	codecText.dataset["codec"] = choice?.codec ?? "none";
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
	readonly rows: readonly TraceRow[];
	readonly frames: readonly ScreenFrame[];
	readonly preset: CameraPreset;
	readonly offset: CameraOffset;
	readonly caption: string | null;
}

function snapshot(scene: SceneMessage): ExportSnapshot {
	return {
		scene,
		seed: state.seed,
		firings: state.firings,
		rows: state.rows,
		frames: state.frames,
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
		screen: frameAt(shot.frames, tick),
		window: windowAt(
			shot.rows,
			shot.frames,
			shot.scene.names,
			tick,
			shot.scene.fps,
		),
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
			// 音（仕様書 2026-10-01-jin-stage-summon §3）: 範囲の tone を合成して音声トラックに。
			// `?noaudio=1` は e2e の口で、音声のコーデックが無い環境（無音で書き出す分岐）を作る。
			let withAudio = false;
			const bytes = await withExportSize(width, height, async () => {
				const encoder = await createEncoder(
					composer.canvas,
					choice,
					synthesize(shot.frames, range),
					NO_AUDIO ? () => Promise.resolve(false) : undefined,
				);
				withAudio = encoder.audio;
				return runExport({
					range,
					draw: (tick) => drawFor(shot, tick, width, height),
					encoder,
					signal: controller.signal,
					onProgress: (done, total) => report({ exporting: { done, total } }),
				});
			});
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
			if (bytes !== null && !withAudio)
				statusText.textContent =
					"準備完了（音声のコーデックが無いため無音で書き出しました）";
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
	// 隠れている間（エディタが鑑賞パネルの iframe を隠すと描く面が 0 になる）は描かず鳴らさない。重い 3D を描き続けると、
	// ソフトウェア描画ではエディタ全体が応答しなくなる。書き出し中は出力の大きさの canvas をプレビューで上書きしない。
	const visible = host.clientWidth > 0 && host.clientHeight > 0;
	if (exporting === null && visible) {
		drawAt(state.tick);
		soundTick(state.tick);
	}
	requestAnimationFrame(loop);
}
requestAnimationFrame(loop);
report({});
