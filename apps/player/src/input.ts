/**
 * 入力を集めて `tick(t, inputs)` の `inputs`（runtime.md §1.1）にする。
 *
 * ## パリティは構成で保証する
 *
 * `inputs` と `.jinrec`（§7）の両方を **同じ reducer**（`InputReducer` = `jin_wasm.runtime.InputState.apply`
 * の写し）から出す。プレイヤーが `keys` を独自に追跡すると、blur で押し下げが残る / カタログ外の
 * キーが混ざるだけで `jin run --input` の再生と割れる。写しであることは
 * `tests/fixtures/jinrec/reducer.jinrec` + `reducer.expected.json` を Python と TS の両方が検算して固定する。
 *
 * ## 集める規則（`InputCollector`）
 *
 * - キーは `KeyboardEvent.code` で、`abilities.json` の `keys` にあるものだけ。`event.repeat` は捨てる
 *   （OS の自動リピートで録画が膨らみ、`pressed` の意味も崩れる）。同じキーの二重の押下も捨てる
 * - `blur` では押下中のキーをすべて `down: false` として**記録してから**離す（押しっぱなしを残さない）
 * - ポインタは主ボタンだけ。座標は論理座標（stage の幅 / 高さに写し、整数に切り捨て、枠内に留める）。
 *   移動は tick の中で最後の 1 つに畳むが、down → up の遷移は残す（`ui.button` の離しが見る）
 * - `namespaces` に `input` が無ければキーを集めない。`ui` も無ければポインタも集めない（runtime.md §9）
 */
import type { InputEvent, Inputs } from "./types";

/** `jin_wasm.runtime.InputState.apply` の写し。 */
export class InputReducer {
	private readonly keys = new Map<string, true>();
	private x = 0;
	private y = 0;
	private down = false;

	apply(events: readonly InputEvent[]): Inputs {
		const rows: InputEvent[] = [];
		for (const ev of events) {
			if (ev.kind === "key") {
				if (ev.down) this.keys.set(ev.name, true);
				else this.keys.delete(ev.name);
				rows.push({ kind: "key", name: ev.name, down: ev.down });
			} else {
				this.x = ev.x;
				this.y = ev.y;
				this.down = ev.down;
				rows.push({ kind: "pointer", x: this.x, y: this.y, down: this.down });
			}
		}
		const keys: Record<string, true> = {};
		for (const name of this.keys.keys()) keys[name] = true;
		return {
			events: rows,
			keys,
			pointer: { x: this.x, y: this.y, down: this.down },
		};
	}
}

export interface CollectorOptions {
	readonly width: number;
	readonly height: number;
	readonly keyNames: ReadonlySet<string>;
	readonly keys: boolean;
	readonly pointer: boolean;
}

interface Pending {
	readonly event: InputEvent;
	/** ポインタの移動（畳んでよい）。押下 / 離しの遷移は false。 */
	readonly move: boolean;
}

export class InputCollector {
	private pending: Pending[] = [];
	private readonly held = new Set<string>();
	private pointerDown = false;
	private readonly listeners: (() => void)[] = [];

	constructor(
		private readonly target: HTMLElement,
		private readonly options: CollectorOptions,
	) {}

	attach(): void {
		const on = <K extends keyof WindowEventMap>(
			name: K,
			handler: (ev: WindowEventMap[K]) => void,
		) => {
			window.addEventListener(name, handler);
			this.listeners.push(() => window.removeEventListener(name, handler));
		};
		const onTarget = <K extends keyof HTMLElementEventMap>(
			name: K,
			handler: (ev: HTMLElementEventMap[K]) => void,
		) => {
			this.target.addEventListener(name, handler);
			this.listeners.push(() => this.target.removeEventListener(name, handler));
		};
		if (this.options.keys) {
			on("keydown", (ev) => this.keyDown(ev));
			on("keyup", (ev) => this.keyUp(ev));
		}
		if (this.options.pointer) {
			onTarget("pointerdown", (ev) => this.pointer(ev, "down"));
			onTarget("pointermove", (ev) => this.pointer(ev, "move"));
			onTarget("pointerup", (ev) => this.pointer(ev, "up"));
			onTarget("pointercancel", (ev) => this.pointer(ev, "up"));
		}
		on("blur", () => this.releaseAll());
	}

	detach(): void {
		for (const off of this.listeners) off();
		this.listeners.length = 0;
	}

	/** この tick のイベントを発生順に返し、溜まりを空にする。押下状態は次の tick へ持ち越す。 */
	drain(): InputEvent[] {
		const out = this.pending.map((p) => p.event);
		this.pending = [];
		return out;
	}

	/** 実行をやり直すとき（`boot` し直し）に押下状態も捨てる。 */
	reset(): void {
		this.pending = [];
		this.held.clear();
		this.pointerDown = false;
	}

	/** 押下中のキーとポインタを、すべて離したことにする（blur）。 */
	releaseAll(): void {
		for (const name of [...this.held]) {
			this.held.delete(name);
			this.push({ kind: "key", name, down: false }, false);
		}
		if (this.pointerDown) {
			this.pointerDown = false;
			this.push(
				{ kind: "pointer", x: this.lastX, y: this.lastY, down: false },
				false,
			);
		}
	}

	private lastX = 0;
	private lastY = 0;

	private keyDown(ev: KeyboardEvent): void {
		if (
			ev.repeat ||
			!this.options.keyNames.has(ev.code) ||
			this.isFormControl(ev.target)
		)
			return;
		ev.preventDefault();
		if (this.held.has(ev.code)) return;
		this.held.add(ev.code);
		this.push({ kind: "key", name: ev.code, down: true }, false);
	}

	private keyUp(ev: KeyboardEvent): void {
		if (!this.held.has(ev.code)) return;
		ev.preventDefault();
		this.held.delete(ev.code);
		this.push({ kind: "key", name: ev.code, down: false }, false);
	}

	private pointer(ev: PointerEvent, phase: "down" | "move" | "up"): void {
		if (phase === "down" && ev.button !== 0) return;
		if (phase === "up" && !this.pointerDown) return;
		const [x, y] = this.toLogical(ev.clientX, ev.clientY);
		this.lastX = x;
		this.lastY = y;
		if (phase === "down") {
			this.pointerDown = true;
			this.target.focus();
			ev.preventDefault();
			this.push({ kind: "pointer", x, y, down: true }, false);
		} else if (phase === "up") {
			this.pointerDown = false;
			this.push({ kind: "pointer", x, y, down: false }, false);
		} else {
			this.push({ kind: "pointer", x, y, down: this.pointerDown }, true);
		}
	}

	private push(event: InputEvent, move: boolean): void {
		const last = this.pending[this.pending.length - 1];
		if (move && last !== undefined && last.move) {
			this.pending[this.pending.length - 1] = { event, move };
		} else {
			this.pending.push({ event, move });
		}
	}

	/** 画面座標 → 論理座標（整数・枠内）。 */
	private toLogical(clientX: number, clientY: number): [number, number] {
		const rect = this.target.getBoundingClientRect();
		const sx = rect.width > 0 ? this.options.width / rect.width : 1;
		const sy = rect.height > 0 ? this.options.height / rect.height : 1;
		const x = Math.floor((clientX - rect.left) * sx);
		const y = Math.floor((clientY - rect.top) * sy);
		return [
			Math.min(Math.max(x, 0), Math.max(0, this.options.width - 1)),
			Math.min(Math.max(y, 0), Math.max(0, this.options.height - 1)),
		];
	}

	private isFormControl(target: EventTarget | null): boolean {
		return (
			target instanceof HTMLInputElement ||
			target instanceof HTMLTextAreaElement
		);
	}
}
