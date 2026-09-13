/**
 * プレイヤーの入口（runtime.md §9 / §10）。
 *
 * - 通常: `game.manifest.json` と `game.lua` をページからの相対パスで fetch し、`wasmoon.wasm` も相対パスで読む
 * - `--single`: `window.JIN_BUNDLE`（JIL / manifest / wasm の base64）から読む。wasm は `data:` URL で渡す
 * - 最小 UI: 実行 / 一時停止 / 1 tick / seed / 最初から / 録画 / 書き出し
 * - 埋め込み（iframe・Jin v2 のエディタの実行パネル）: **fetch せず**親からの
 *   `{ type: "jin.load", jil, manifest }` を待って読み込む（ライブリロード）。トレース行は親へ
 *   `postMessage({ type: "jin.trace", rows })`。`{ type: "jin.control", action }` で
 *   実行 / 一時停止 / 1 tick / 最初から（seed 付き）/ 録画 / 録画を止める を受ける。
 *   親以外からの message は無視する
 * - 埋め込みのデバッグ（Phase 6）: `{ type: "jin.replay", text }` で `.jinrec` を最初から再生し
 *   （トレースは `jin.trace` で 1 回にまとめて流す）、`{ type: "jin.frame", ops }` でスクラブ中の
 *   画面（トレースの `frame` 行の表示リスト）を描く。状態が変わるたびに `{ type: "jin.status", … }`、
 *   録画を止めたら `{ type: "jin.recording", text, seed, ticks }` を親へ送る
 * - `window.__jinPlayer`: パリティ e2e が使う操作口（UI と同じ関数を呼ぶだけ）
 */
import { KEY_NAMES, subscriptions } from "./abilities";
import { AudioOut } from "./audio";
import { Renderer } from "./canvas";
import { JinHost } from "./host";
import { InputCollector } from "./input";
import { parseJinrec } from "./jinrec";
import { Player, type Clock } from "./player";
import type { Manifest, Op, SingleBundle, TraceRow } from "./types";

/** `.jinrec` の再生の結果（`PlayerApi.replay`）。 */
export interface ReplayOutcome {
	readonly ok: boolean;
	/** 走らせた tick 数（`ok` でなければ 0）。 */
	readonly ticks: number;
	/** 断った理由（`行番号: 理由`）。`ok` なら null。 */
	readonly message: string | null;
}

/** e2e / 埋め込み側が触る口。 */
export interface PlayerApi {
	readonly ready: true;
	start(): void;
	pause(): void;
	step(): void;
	reboot(seed?: number): void;
	startRecording(): void;
	stopRecording(): string | null;
	load(jil: string, manifest: Manifest): Promise<void>;
	/** `.jinrec` のテキストを最初から再生する（止まったまま終わる）。 */
	replay(text: string): ReplayOutcome;
	/** 表示リストを描くだけ（走っている間は false）。 */
	show(ops: readonly Op[]): boolean;
	ticks(): number;
	seed(): number;
	running(): boolean;
	done(): boolean;
	error(): string | null;
	trace(): readonly TraceRow[];
	lastOps(): readonly Op[];
	publicState(): Readonly<Record<string, unknown>>;
	recordedEvents(): number;
}

declare global {
	interface Window {
		JIN_BUNDLE?: SingleBundle;
		__jinPlayer?: PlayerApi;
	}
}

interface Source {
	readonly jil: string;
	readonly manifest: Manifest;
	readonly wasmUri: string;
	/** asset の実体を読む（`--single` では無い）。 */
	readonly assetUrl: ((path: string) => string) | null;
}

function byId<T extends HTMLElement>(id: string): T {
	const el = document.getElementById(id);
	if (el === null) throw new Error(`#${id} がありません`);
	return el as T;
}

/** iframe の中で動いているか（Jin v2 のエディタの実行パネル）。 */
const EMBEDDED = window.parent !== window;

/** `wasmoon.wasm` の場所。`--single` は `data:`、それ以外はページからの相対（fetch は要らない）。 */
function wasmUriOf(): string {
	const bundle = window.JIN_BUNDLE;
	return bundle !== undefined
		? `data:application/wasm;base64,${bundle.wasm}`
		: new URL("wasmoon.wasm", document.baseURI).href;
}

/**
 * 起動時の読み込み元。埋め込みなら `null`（親の `jin.load` を待つ。`game.lua` を fetch しに
 * 行くと `/play/game.lua` の 404 を親のサーバに投げることになる）。
 */
async function loadSource(): Promise<Source | null> {
	const bundle = window.JIN_BUNDLE;
	if (bundle !== undefined) {
		return {
			jil: bundle.jil,
			manifest: bundle.manifest,
			wasmUri: wasmUriOf(),
			assetUrl: null,
		};
	}
	if (EMBEDDED) return null;
	const manifestResponse = await fetch("game.manifest.json");
	if (!manifestResponse.ok)
		throw new Error(
			`game.manifest.json を読めません（${manifestResponse.status}）`,
		);
	const manifest = (await manifestResponse.json()) as Manifest;
	const jilResponse = await fetch("game.lua");
	if (!jilResponse.ok)
		throw new Error(`game.lua を読めません（${jilResponse.status}）`);
	return {
		jil: await jilResponse.text(),
		manifest,
		wasmUri: wasmUriOf(),
		assetUrl: (path) => new URL(path, document.baseURI).href,
	};
}

async function loadSprites(
	source: Source,
): Promise<Map<string, CanvasImageSource>> {
	const sprites = new Map<string, CanvasImageSource>();
	if (source.assetUrl === null) return sprites;
	for (const asset of source.manifest.assets) {
		if (asset.kind !== "sprite") continue;
		const image = new Image();
		image.src = source.assetUrl(asset.path);
		try {
			await image.decode();
			sprites.set(asset.name, image);
		} catch {
			// 読めない画像は描かない（落とさない）
		}
	}
	return sprites;
}

async function loadSounds(source: Source, audio: AudioOut): Promise<void> {
	if (source.assetUrl === null) return;
	for (const asset of source.manifest.assets) {
		if (asset.kind !== "sound") continue;
		try {
			const response = await fetch(source.assetUrl(asset.path));
			if (response.ok) audio.addSound(asset.name, await response.arrayBuffer());
		} catch {
			// 読めない音は鳴らさない
		}
	}
}

const clock: Clock = {
	now: () => performance.now(),
	requestFrame: (callback) => {
		requestAnimationFrame(callback);
	},
};

function fitCanvas(
	canvas: HTMLCanvasElement,
	width: number,
	height: number,
): void {
	const maxW = Math.max(1, window.innerWidth - 32);
	const maxH = Math.max(1, window.innerHeight - 120);
	const scale = Math.max(1, Math.floor(Math.min(maxW / width, maxH / height)));
	canvas.style.width = `${width * scale}px`;
	canvas.style.height = `${height * scale}px`;
}

async function main(): Promise<void> {
	const runButton = byId<HTMLButtonElement>("run");
	const stepButton = byId<HTMLButtonElement>("step");
	const seedInput = byId<HTMLInputElement>("seed");
	const rebootButton = byId<HTMLButtonElement>("reboot");
	const recordButton = byId<HTMLButtonElement>("record");
	const exportButton = byId<HTMLButtonElement>("export");
	const status = byId<HTMLSpanElement>("status");
	const errorBox = byId<HTMLPreElement>("error");
	const canvas = byId<HTMLCanvasElement>("stage");

	let player: Player | null = null;
	let host: JinHost | null = null;
	let collector: InputCollector | null = null;
	const audio = new AudioOut();
	const embedded = EMBEDDED;
	/** 直近の再生 / 読み込みの一言（`jin.status` の `notice`）。 */
	let notice: string | null = null;

	/** 親（エディタ）へ状態を知らせる。埋め込みでなければ何もしない。 */
	const postStatus = (): void => {
		if (!embedded) return;
		window.parent.postMessage(
			{
				type: "jin.status",
				loaded: player !== null,
				tick: player?.tick ?? 0,
				seed: player?.seed ?? null,
				running: player?.running ?? false,
				done: player?.done ?? false,
				error: player?.error ?? null,
				recording: player?.recording ?? false,
				recordedEvents: player?.recordedEvents ?? 0,
				notice,
			},
			"*",
		);
	};

	const render = (): void => {
		postStatus();
		if (player === null) return;
		runButton.textContent = player.running ? "一時停止" : "実行";
		runButton.disabled = player.done;
		stepButton.disabled = player.done;
		recordButton.textContent = player.recording ? "録画を止める" : "録画";
		recordButton.setAttribute(
			"aria-pressed",
			player.recording ? "true" : "false",
		);
		exportButton.disabled = player.recordingText === null;
		const parts = [`tick ${player.tick}`, `seed ${player.seed}`];
		if (player.recording) parts.push(`録画中 ${player.recordedEvents} events`);
		if (player.done)
			parts.push(player.error === null ? "終了" : "エラーで終了");
		status.textContent = parts.join(" · ");
		errorBox.textContent = player.error ?? "";
	};

	const setUp = async (source: Source): Promise<void> => {
		player?.pause();
		collector?.detach();
		host?.close();
		const { width, height } = source.manifest.stage;
		canvas.width = width;
		canvas.height = height;
		fitCanvas(canvas, width, height);
		const context = canvas.getContext("2d");
		if (context === null)
			throw new Error("canvas の 2D コンテキストが取れません");
		context.imageSmoothingEnabled = false;
		host = await JinHost.create(source.jil, source.wasmUri);
		const sprites = await loadSprites(source);
		await loadSounds(source, audio);
		collector = new InputCollector(canvas, {
			width,
			height,
			keyNames: KEY_NAMES,
			...subscriptions(source.manifest.namespaces),
		});
		collector.attach();
		const current = new Player({
			host,
			manifest: source.manifest,
			renderer: new Renderer(context, width, height, sprites),
			collector,
			audio,
			clock,
			onChange: render,
			onTrace: (rows) => {
				if (embedded)
					window.parent.postMessage({ type: "jin.trace", rows }, "*");
			},
		});
		player = current;
		seedInput.value = String(current.seed);
		current.reboot();
		current.start();
		render();
	};

	const unlock = (): void => audio.unlock();
	window.addEventListener("pointerdown", unlock);
	window.addEventListener("keydown", unlock);

	runButton.addEventListener("click", () => {
		if (player === null) return;
		if (player.running) player.pause();
		else player.start();
		canvas.focus();
	});
	stepButton.addEventListener("click", () => player?.step());
	rebootButton.addEventListener("click", () => {
		if (player === null) return;
		const seed = Number.parseInt(seedInput.value, 10);
		player.reboot(Number.isFinite(seed) ? seed : player.seed);
		player.start();
		canvas.focus();
	});
	recordButton.addEventListener("click", () => {
		if (player === null) return;
		if (player.recording) {
			player.stopRecording();
		} else {
			const seed = Number.parseInt(seedInput.value, 10);
			if (Number.isFinite(seed)) player.seed = seed;
			player.startRecording();
			player.start();
		}
		canvas.focus();
	});
	exportButton.addEventListener("click", () => {
		const text = player?.recordingText;
		if (text === null || text === undefined || player === null) return;
		const blob = new Blob([text], { type: "application/x-ndjson" });
		const url = URL.createObjectURL(blob);
		const a = document.createElement("a");
		a.href = url;
		a.download = `${player.seed}.jinrec`;
		a.click();
		setTimeout(() => URL.revokeObjectURL(url), 1000);
	});
	window.addEventListener("resize", () => {
		if (player !== null) fitCanvas(canvas, canvas.width, canvas.height);
	});

	window.addEventListener("message", (ev: MessageEvent<unknown>) => {
		if (!embedded || ev.source !== window.parent) return;
		const data = ev.data as {
			type?: unknown;
			jil?: unknown;
			manifest?: unknown;
			action?: unknown;
			seed?: unknown;
			text?: unknown;
			ops?: unknown;
		} | null;
		if (data === null || typeof data !== "object") return;
		if (data.type === "jin.control") {
			// 親（エディタ）の操作。iframe の中のボタンと同じ関数を呼ぶだけ。
			if (player === null) return;
			if (data.action === "start") player.start();
			else if (data.action === "pause") player.pause();
			else if (data.action === "step") player.step();
			// 親の「最初から」は**止めた状態で** tick 0 に戻す（そこから 1 tick ずつ進められる）。
			// seed が付いていればそれで boot する。
			else if (data.action === "reboot") {
				player.reboot(
					typeof data.seed === "number" && Number.isFinite(data.seed)
						? data.seed
						: player.seed,
				);
				seedInput.value = String(player.seed);
			}
			// 録画は `boot` し直して tick 0 から走り出す（iframe の中の「録画」ボタンと同じ）。
			else if (data.action === "record") {
				if (typeof data.seed === "number" && Number.isFinite(data.seed))
					player.seed = data.seed;
				player.startRecording();
				player.start();
			}
			// 録画を止めて `.jinrec` の文字列を親へ返す（書き出しは親が行う）。
			else if (data.action === "stop") {
				const ticks = player.tick;
				const text = player.stopRecording();
				player.pause();
				if (text !== null)
					window.parent.postMessage(
						{ type: "jin.recording", text, seed: player.seed, ticks },
						"*",
					);
			}
			render();
			return;
		}
		if (data.type === "jin.replay") {
			if (typeof data.text !== "string") return;
			const outcome = api.replay(data.text);
			notice = outcome.ok
				? `録画を tick 0 から ${String(outcome.ticks)} tick 再生しました`
				: `録画を読めません: ${outcome.message ?? ""}`;
			render();
			return;
		}
		if (data.type === "jin.frame") {
			if (Array.isArray(data.ops)) api.show(data.ops as readonly Op[]);
			return;
		}
		if (data.type !== "jin.load") return;
		if (
			typeof data.jil !== "string" ||
			typeof data.manifest !== "object" ||
			data.manifest === null
		)
			return;
		void api.load(data.jil, data.manifest as Manifest).catch(showError);
	});

	const showError = (error: unknown): void => {
		status.textContent = "読み込めません";
		errorBox.textContent =
			error instanceof Error ? error.message : String(error);
	};

	const api: PlayerApi = {
		ready: true,
		start: () => player?.start(),
		pause: () => player?.pause(),
		step: () => player?.step(),
		reboot: (seed) => player?.reboot(seed),
		startRecording: () => player?.startRecording(),
		stopRecording: () => player?.stopRecording() ?? null,
		load: async (jil, manifest) => {
			// **fetch しない。** wasm の場所はページから決まる。asset の実体は埋め込みでは
			// 読めない（`.jin` の隣にあり、エディタのサーバは配らない）ので、絵と音は出ない。
			await setUp({
				jil,
				manifest,
				wasmUri: wasmUriOf(),
				assetUrl:
					embedded || window.JIN_BUNDLE !== undefined
						? null
						: (path) => new URL(path, document.baseURI).href,
			});
		},
		replay: (text) => {
			if (player === null)
				return { ok: false, ticks: 0, message: "まだ読み込んでいません" };
			const parsed = parseJinrec(text);
			if (!parsed.ok) {
				return {
					ok: false,
					ticks: 0,
					message: `${String(parsed.line)}: ${parsed.message}`,
				};
			}
			return {
				ok: true,
				ticks: player.replay(parsed.recording),
				message: null,
			};
		},
		show: (ops) => player?.show(ops) ?? false,
		ticks: () => player?.tick ?? 0,
		seed: () => player?.seed ?? 0,
		running: () => player?.running ?? false,
		done: () => player?.done ?? false,
		error: () => player?.error ?? null,
		trace: () => player?.trace ?? [],
		lastOps: () => player?.lastOps ?? [],
		publicState: () => player?.lastPublic ?? {},
		recordedEvents: () => player?.recordedEvents ?? 0,
	};

	try {
		const source = await loadSource();
		if (source === null)
			status.textContent = "エディタからの読み込みを待っています";
		else await setUp(source);
	} catch (error) {
		showError(error);
	}
	window.__jinPlayer = api;
}

void main();
