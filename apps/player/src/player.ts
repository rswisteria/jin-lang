/**
 * 実行ループ（runtime.md §10）。
 *
 * `requestAnimationFrame` で時間を積み、`1 / fps` ごとに `tick` を呼ぶ。遅れたら最大
 * `MAX_CATCH_UP` tick まで連続で呼び、それ以上は捨てる（音と絵が乱れるだけで、トレースの
 * 決定性は保たれる。捨てた tick は存在しない）。
 *
 * 1 tick の順序は固定: 入力を集める → （録画中なら）書く → reducer で `inputs` にする →
 * `tick` → 描く → 鳴らす → トレースを流す → `done` なら止まる。録画と `inputs` が同じ
 * イベント列から出ることがパリティの根拠（`input.ts`）。
 */
import type { AudioOut } from "./audio";
import type { Renderer } from "./canvas";
import type { JinHost } from "./host";
import { InputCollector, InputReducer } from "./input";
import { eventsByTick, type Recording } from "./jinrec";
import { Recorder } from "./recorder";
import type { InputEvent, Manifest, Op, TraceRow } from "./types";

/** 1 フレームで追いつくために連続で呼ぶ tick の上限（runtime.md §10）。 */
export const MAX_CATCH_UP = 4;

export interface Clock {
	/** ミリ秒。 */
	now(): number;
	/** 次のフレームで `callback(nowMs)` を呼ぶ。 */
	requestFrame(callback: (nowMs: number) => void): void;
}

export interface PlayerOptions {
	readonly host: JinHost;
	readonly manifest: Manifest;
	readonly renderer: Renderer;
	readonly collector: InputCollector;
	readonly audio: AudioOut;
	readonly clock: Clock;
	readonly onTrace?: (rows: readonly TraceRow[]) => void;
	readonly onChange?: () => void;
}

export class Player {
	private reducer = new InputReducer();
	private recorder: Recorder | null = null;
	private lastRecording: string | null = null;
	private accumulator = 0;
	private lastFrame = 0;
	private frameQueued = false;

	tick = 0;
	seed: number;
	running = false;
	done = false;
	error: string | null = null;
	lastOps: readonly Op[] = [];
	lastPublic: Readonly<Record<string, unknown>> = {};
	/** デバッグビルドのトレース（`boot` から通し）。`reboot` で空になる。 */
	readonly trace: TraceRow[] = [];

	constructor(private readonly o: PlayerOptions) {
		this.seed = o.manifest.stage.seed;
	}

	get recording(): boolean {
		return this.recorder !== null;
	}

	get recordedEvents(): number {
		return this.recorder?.events ?? 0;
	}

	/** `boot` し直して tick 0 から。録画中なら録画も捨てる。 */
	reboot(seed = this.seed): void {
		this.seed = Math.trunc(seed);
		this.tick = 0;
		this.done = false;
		this.error = null;
		this.trace.length = 0;
		this.reducer = new InputReducer();
		this.recorder = null;
		this.o.collector.reset();
		this.accumulator = 0;
		this.o.host.boot(this.seed, this.o.manifest);
		this.o.onChange?.();
	}

	start(): void {
		if (this.running || this.done) return;
		this.running = true;
		this.lastFrame = this.o.clock.now();
		this.accumulator = 0;
		this.queueFrame();
		this.o.onChange?.();
	}

	pause(): void {
		this.running = false;
		this.o.onChange?.();
	}

	/** 1 tick だけ進める（一時停止中の操作）。 */
	step(): void {
		if (this.done) return;
		this.running = false;
		this.advance();
		this.o.onChange?.();
	}

	/** 最初から録画する（`boot` し直す。録画は tick 0 から始まらないと `jin run --input` と揃わない）。 */
	startRecording(): void {
		this.reboot();
		this.recorder = new Recorder({
			file: this.o.manifest.file,
			seed: this.seed,
			fps: this.o.manifest.stage.fps,
		});
		this.o.onChange?.();
	}

	/** 録画を閉じて `.jinrec` の文字列を返す（録画していなければ null）。 */
	stopRecording(): string | null {
		if (this.recorder === null) return null;
		this.lastRecording = this.recorder.finish(this.tick);
		this.recorder = null;
		this.o.onChange?.();
		return this.lastRecording;
	}

	/** 直近に閉じた録画。 */
	get recordingText(): string | null {
		return this.lastRecording;
	}

	/**
	 * 録画を最初から再生する（runtime.md §7 / Phase 6 のスクラブ）。
	 *
	 * ヘッダの seed で `boot` し直し、tick 0 からヘッダの `ticks` まで、録画の `tick == t` の行を
	 * **同じ reducer** に通して `tick` を呼ぶ（`jin run --input` と同じ）。root が `done` になったら
	 * そこで止まる。終わったら**止まったまま**（tick = 走らせた数。そこからスクラブ / 1 tick）。
	 * 同期で回し（paddle 600 tick で 1 秒未満）、トレースは最後にまとめて 1 回流す
	 * （tick ごとに `postMessage` すると親が数百回描き直す）。再生の間に届いた実入力は捨てる。
	 */
	replay(recording: Recording): number {
		const ticks = recording.ticks ?? 0;
		this.reboot(recording.seed ?? this.o.manifest.stage.seed);
		const perTick = eventsByTick(recording.events, ticks);
		for (let t = 0; t < ticks && !this.done; t += 1) {
			this.advance(perTick[t] ?? [], false);
		}
		this.running = false;
		this.o.collector.reset();
		if (this.trace.length > 0) this.o.onTrace?.(this.trace.slice());
		this.o.onChange?.();
		return this.tick;
	}

	/**
	 * スクラブ中の画面（トレースの `frame` 行の表示リスト）。**描くだけで Lua は呼ばない。**
	 * 走っている間は無視する（次の tick が上書きするだけで、止まっていないと意味が無い）。
	 */
	show(ops: readonly Op[]): boolean {
		if (this.running) return false;
		this.o.renderer.draw(ops);
		this.lastOps = ops;
		return true;
	}

	private queueFrame(): void {
		if (this.frameQueued) return;
		this.frameQueued = true;
		this.o.clock.requestFrame((now) => {
			this.frameQueued = false;
			this.frame(now);
		});
	}

	private frame(now: number): void {
		if (!this.running) return;
		const period = 1000 / this.o.manifest.stage.fps;
		this.accumulator += now - this.lastFrame;
		this.lastFrame = now;
		let n = 0;
		while (this.accumulator >= period && n < MAX_CATCH_UP && this.running) {
			this.advance();
			this.accumulator -= period;
			n += 1;
		}
		if (this.accumulator >= period) this.accumulator = 0; // 追いつけない分は捨てる
		// 進んだフレームでは状態（tick 数・録画の件数）を知らせる（親の `jin.status` もこれで動く）。
		if (n > 0) this.o.onChange?.();
		if (this.running) this.queueFrame();
	}

	/**
	 * 1 tick。`events` は既定で集めた実入力、再生では録画の行（`emit` は行ごとのトレース通知）。
	 */
	private advance(
		events: readonly InputEvent[] = this.o.collector.drain(),
		emit = true,
	): void {
		this.recorder?.push(this.tick, events);
		const inputs = this.reducer.apply(events);
		const result = this.o.host.tick(this.tick, inputs);
		this.tick += 1;
		this.lastOps = result.ops;
		this.lastPublic = result.public;
		this.o.renderer.draw(result.ops);
		this.o.audio.play(result.audio);
		if (result.trace !== undefined && result.trace.length > 0) {
			this.trace.push(...result.trace);
			if (emit) this.o.onTrace?.(result.trace);
		}
		if (result.done) {
			this.running = false;
			this.done = true;
			this.error = result.error;
			this.o.onChange?.();
		}
	}
}
