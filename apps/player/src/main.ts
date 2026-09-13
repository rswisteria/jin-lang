/**
 * プレイヤーの入口（runtime.md §9 / §10）。
 *
 * - 通常: `game.manifest.json` と `game.lua` をページからの相対パスで fetch し、`wasmoon.wasm` も相対パスで読む
 * - `--single`: `window.JIN_BUNDLE`（JIL / manifest / wasm の base64）から読む。wasm は `data:` URL で渡す
 * - 最小 UI: 実行 / 一時停止 / 1 tick / seed / 最初から / 録画 / 書き出し
 * - 埋め込み（iframe）: トレース行を親へ `postMessage({ type: "jin.trace", rows })`。親からの
 *   `{ type: "jin.load", jil, manifest }` で差し替える（ライブリロード）。親以外からの message は無視する
 * - `window.__jinPlayer`: パリティ e2e が使う操作口（UI と同じ関数を呼ぶだけ）
 */
import { KEY_NAMES, subscriptions } from "./abilities";
import { AudioOut } from "./audio";
import { Renderer } from "./canvas";
import { JinHost } from "./host";
import { InputCollector } from "./input";
import { Player, type Clock } from "./player";
import type { Manifest, Op, SingleBundle, TraceRow } from "./types";

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

async function loadSource(): Promise<Source> {
	const bundle = window.JIN_BUNDLE;
	if (bundle !== undefined) {
		return {
			jil: bundle.jil,
			manifest: bundle.manifest,
			wasmUri: `data:application/wasm;base64,${bundle.wasm}`,
			assetUrl: null,
		};
	}
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
		wasmUri: new URL("wasmoon.wasm", document.baseURI).href,
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
	const embedded = window.parent !== window;

	const render = (): void => {
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
		} | null;
		if (data === null || typeof data !== "object" || data.type !== "jin.load")
			return;
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
			const previous = await loadSource().catch(() => null);
			await setUp({
				jil,
				manifest,
				wasmUri:
					previous?.wasmUri ??
					`data:application/wasm;base64,${window.JIN_BUNDLE?.wasm ?? ""}`,
				assetUrl: previous?.assetUrl ?? null,
			});
		},
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
		await setUp(await loadSource());
	} catch (error) {
		showError(error);
	}
	window.__jinPlayer = api;
}

void main();
