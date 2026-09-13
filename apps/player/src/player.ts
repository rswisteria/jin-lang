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
 *
 * 状態を保った差し替え（runtime.md §1 の `manifest.resume`・設計書 §11 #42）: 新しい JIL のホストで
 * 作った `Player` が `resumeFrom(previous)` で前のプレイヤーの直近の `snapshot` / reducer / トレース /
 * tick を引き継ぎ、`manifest.resume` 付きで `boot` する。root が照合できなければ（`resume.mode`
 * が `fresh`）そのまま `reboot` に落ちる。**世代**（`generation`）は boot し直すたびに増え、差し替えで
 * 続けたときは増えない（親はこれでトレースを捨てるかを決める）。
 */
import type { AudioOut } from "./audio";
import type { Renderer } from "./canvas";
import type { JinHost } from "./host";
import { InputCollector, InputReducer } from "./input";
import { DEFAULT_TICKS, eventsByTick, type Recording } from "./jinrec";
import { Recorder } from "./recorder";
import type {
	InputEvent,
	Manifest,
	Op,
	ResumeNote,
	Snapshot,
	StorageWrite,
	TraceRow,
} from "./types";

/** 1 フレームで追いつくために連続で呼ぶ tick の上限（runtime.md §10）。 */
export const MAX_CATCH_UP = 4;

/** 世代の採番（ページで 1 本。`Player` を作り直しても戻らない）。 */
let nextGeneration = 1;

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
	/** 差し替え直後の tick が返した復元の知らせ（1 回だけ）。 */
	readonly onResume?: (note: ResumeNote) => void;
	/** 記憶（`storage`・abilities.md §8）の初期内容。無ければ空。 */
	readonly storage?: ReadonlyMap<string, string>;
	/**
	 * 記憶が変わった（tick の書き込み / `forget`）。永続化はホストの仕事（`store` を丸ごと書けばよい）。
	 * 録画の再生の間（スクラッチ）は呼ばれない。
	 */
	readonly onStore?: (
		writes: readonly StorageWrite[],
		store: ReadonlyMap<string, string>,
	) => void;
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
	/** デバッグビルドのトレース（`boot` から通し）。`reboot` で空になる。差し替えで続けたときは引き継ぐ。 */
	readonly trace: TraceRow[] = [];
	/** 直近の tick 結果の `snapshot`（DEBUG だけ。差し替えで次の `boot` に渡す）。 */
	lastSnapshot: Snapshot | null = null;
	/** 差し替え直後の tick が返した復元の知らせ。`reboot` で null に戻る。 */
	lastResume: ResumeNote | null = null;
	/** boot し直した回数の通し番号（0 はまだ boot していない）。差し替えで続けたときは変わらない。 */
	generation = 0;
	/**
	 * 記憶（`storage`・abilities.md §8）。ホストが持つ内容の写しで、`boot` のたびに `manifest.storage` へ渡し、
	 * tick の書き込みを順に反映する。`Map` なので `__proto__` のような鍵も普通の鍵。
	 */
	readonly store: Map<string, string>;
	/** 録画の再生の間の書き込み先（ヘッダの写しから始まり、永続化しない）。null なら `store` に書く。 */
	private scratch: Map<string, string> | null = null;

	constructor(private readonly o: PlayerOptions) {
		this.seed = o.manifest.stage.seed;
		this.store = new Map(o.storage ?? []);
	}

	/** 再生の間はスクラッチに書いている（永続化されない）。 */
	get replaying(): boolean {
		return this.scratch !== null;
	}

	/** 今の `boot` に渡す記憶の写し。 */
	private storageCopy(): Record<string, string> {
		return Object.fromEntries(this.scratch ?? this.store);
	}

	get recording(): boolean {
		return this.recorder !== null;
	}

	get recordedEvents(): number {
		return this.recorder?.events ?? 0;
	}

	/** `boot` し直して tick 0 から。録画中なら録画も捨てる。再生のスクラッチも捨てる（記憶は本物に戻る）。 */
	reboot(seed = this.seed): void {
		this.restart(seed, null);
	}

	/** 記憶を空にして（ホストにも知らせて）`boot` し直す。Lua 側の写しも空から始まる。 */
	forget(): void {
		this.store.clear();
		this.o.onStore?.([], this.store);
		this.restart(this.seed, null);
	}

	private restart(seed: number, scratch: Map<string, string> | null): void {
		this.seed = Math.trunc(seed);
		this.tick = 0;
		this.done = false;
		this.error = null;
		this.trace.length = 0;
		this.reducer = new InputReducer();
		this.recorder = null;
		this.lastSnapshot = null;
		this.lastResume = null;
		this.scratch = scratch;
		this.o.collector.reset();
		this.accumulator = 0;
		this.generation = nextGeneration;
		nextGeneration += 1;
		this.o.host.boot(this.seed, {
			...this.o.manifest,
			storage: this.storageCopy(),
		});
		this.o.onChange?.();
	}

	/**
	 * 状態を保った差し替え。前のプレイヤー（別の JIL のホストで動いていた）の直近の `snapshot` を
	 * `manifest.resume` に付けて `boot` し、tick / seed / reducer / トレース / 直近の画面と公開 state /
	 * 世代を引き継ぐ。**走らせるかは呼ぶ側**が決める（引き継いだ直後は止まっている）。
	 * 録画は続けられない（差し替えた瞬間から後は同じ JIL の記録ではない）ので、前の録画は捨てる。
	 * 前のプレイヤーに `snapshot` が無い（release / まだ tick していない）か終わっていれば false
	 * （呼ぶ側は `reboot` に落とす）。
	 */
	resumeFrom(previous: Player): boolean {
		const snapshot = previous.lastSnapshot;
		if (snapshot === null || previous.done || previous.tick === 0) return false;
		this.seed = snapshot.seed;
		this.tick = snapshot.tick + 1;
		this.done = false;
		this.error = null;
		this.trace.length = 0;
		this.trace.push(...previous.trace);
		this.reducer = previous.reducer;
		this.recorder = null;
		this.lastRecording = previous.lastRecording;
		this.lastSnapshot = snapshot;
		this.lastResume = null;
		this.lastOps = previous.lastOps;
		this.lastPublic = previous.lastPublic;
		this.accumulator = 0;
		this.generation = previous.generation;
		// 記憶も引き継ぐ（前のプレイヤーの写しが正。再生の途中ならスクラッチのまま続ける）。
		this.store.clear();
		for (const [key, value] of previous.store) this.store.set(key, value);
		this.scratch = previous.scratch === null ? null : new Map(previous.scratch);
		this.o.host.boot(this.seed, {
			...this.o.manifest,
			resume: snapshot,
			storage: this.storageCopy(),
		});
		this.o.renderer.draw(this.lastOps);
		this.o.onChange?.();
		return true;
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
			// 録画の boot に渡した記憶の写し（`jin run --input` が同じ写しで boot する。abilities.md §8）。
			storage: this.storageCopy(),
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
	 * 記憶はヘッダの写しで `boot` し、書き込みは**スクラッチ**に溜めて永続化しない（履歴の再実行であって、
	 * 利用者の本物の記憶を上書きしない。abilities.md §8）。次の `reboot` で本物に戻る。
	 */
	replay(recording: Recording): number {
		// ヘッダに `ticks` が無ければ `jin run --input` と同じ 600（runtime.md §8）。0 にすると同じ録画から違うトレースになる。
		const ticks = recording.ticks ?? DEFAULT_TICKS;
		this.restart(
			recording.seed ?? this.o.manifest.stage.seed,
			new Map(Object.entries(recording.storage ?? {})),
		);
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
		if (result.resume !== undefined) {
			// 差し替え直後の 1 回。root が照合できず通常の boot に落ちていたら（`fresh`）、この tick は
			// 「tick N+1 で最初から」になっていて数が合わないので、捨てて tick 0 からやり直す。
			this.lastResume = result.resume;
			this.o.onResume?.(result.resume);
			if (result.resume.mode === "fresh") {
				const note = result.resume;
				this.reboot();
				this.lastResume = note;
				return;
			}
		}
		this.tick += 1;
		if (result.snapshot !== undefined) this.lastSnapshot = result.snapshot;
		if (result.storage !== undefined && result.storage.length > 0) {
			// 書き込みを順に写しへ。再生中はスクラッチ（永続化しない）。
			const target = this.scratch ?? this.store;
			for (const [key, value] of result.storage) target.set(key, value);
			if (this.scratch === null) this.o.onStore?.(result.storage, this.store);
		}
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
