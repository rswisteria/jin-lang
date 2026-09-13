/**
 * `.jinrec`（runtime.md §7）の読み手。**`jin_wasm.jinrec.read_jinrec` の写し**である。
 *
 * 書き手（`recorder.ts`）と同じ app に置く。エディタ（`apps/editor`）は 1 行目に `"jinrec"` が
 * あるかだけで「録画か trace か」を見分け、生のテキストを `jin.replay` で渡してくる。
 * 検査の範囲と文言は Python 側と同じで、壊れた行は**黙って読み飛ばさず**行番号を添えて断る。
 * 同じ壊れ方を同じ行番号で拒むことは `tests/fixtures/jinrec/broken/`（`broken.expected.json`）を
 * Python と TS の両方が検算して固定する。
 *
 * 既知の差: JSON の `5.0` は Python では float（整数の欄で拒む）だが JS では `5` と区別できない
 * （`JSON.parse` が同じ数になる）。録画の書き手は整数を `5` と書くので実用上は当たらない。
 */
import type { InputEvent } from "./types";

export const JINREC_VERSION = 1;
export const EVENT_KINDS = ["key", "pointer"] as const;
/** ヘッダに `ticks` が無いときの再生の tick 数（runtime.md §8: `jin run --ticks` の既定と同じ）。 */
export const DEFAULT_TICKS = 600;

/** 録画の 1 行（`tick` 付き）。 */
export type RecordedEvent = InputEvent & { readonly tick: number };

export interface Recording {
	readonly file: string | null;
	readonly seed: number | null;
	readonly fps: number | null;
	readonly ticks: number | null;
	/** 録画の `boot` に渡した記憶の写し（abilities.md §8）。無ければ null（= 空）。 */
	readonly storage: Readonly<Record<string, string>> | null;
	readonly events: readonly RecordedEvent[];
}

export type JinrecResult =
	| { readonly ok: true; readonly recording: Recording }
	| { readonly ok: false; readonly line: number; readonly message: string };

function isInt(value: unknown): value is number {
	return typeof value === "number" && Number.isInteger(value);
}

function isNum(value: unknown): value is number {
	return typeof value === "number" && Number.isFinite(value);
}

function fail(line: number, message: string): JinrecResult {
	return { ok: false, line, message };
}

/** `.jinrec` のテキストを読む。ヘッダとイベントの形を検査する（`read_jinrec` と同じ順・同じ文言）。 */
export function parseJinrec(text: string): JinrecResult {
	let header: {
		file: string | null;
		seed: number | null;
		fps: number | null;
		ticks: number | null;
		storage: Readonly<Record<string, string>> | null;
	} | null = null;
	const events: RecordedEvent[] = [];
	let lastTick = -1;
	const lines = text.split("\n");
	for (let index = 0; index < lines.length; index += 1) {
		const number = index + 1;
		let line = lines[index] ?? "";
		if (line.endsWith("\r")) line = line.slice(0, -1);
		if (number === 1 && line.startsWith("﻿")) line = line.slice(1);
		if (line.trim() === "") continue;
		let value: unknown;
		try {
			value = JSON.parse(line);
		} catch (error) {
			const detail = error instanceof Error ? error.message : String(error);
			return fail(number, `JSON として読めません（${detail}）`);
		}
		if (value === null || typeof value !== "object" || Array.isArray(value)) {
			return fail(number, "JSON オブジェクトではありません");
		}
		const row = value as Record<string, unknown>;
		if (header === null) {
			if (row["jinrec"] !== JINREC_VERSION) {
				return fail(
					number,
					`1 行目は {"jinrec": ${String(JINREC_VERSION)}} のヘッダです（実際 ${JSON.stringify(row["jinrec"] ?? null)}）`,
				);
			}
			for (const key of ["seed", "fps", "ticks"] as const) {
				if (key in row && !isInt(row[key])) {
					return fail(number, `ヘッダの ${key} は整数です`);
				}
			}
			const file = row["file"];
			if (file !== undefined && file !== null && typeof file !== "string") {
				return fail(number, "ヘッダの file は文字列です");
			}
			const ticks = isInt(row["ticks"]) ? row["ticks"] : null;
			if (ticks !== null && ticks < 0) {
				return fail(number, "ヘッダの ticks は 0 以上です");
			}
			let storage: Readonly<Record<string, string>> | null = null;
			const rawStorage = row["storage"];
			if (rawStorage !== undefined && rawStorage !== null) {
				if (typeof rawStorage !== "object" || Array.isArray(rawStorage)) {
					return fail(number, "ヘッダの storage はオブジェクトです");
				}
				const entries = Object.entries(rawStorage as Record<string, unknown>);
				if (entries.some(([, v]) => typeof v !== "string")) {
					return fail(number, "ヘッダの storage の値は文字列です");
				}
				storage = Object.fromEntries(entries) as Record<string, string>;
			}
			header = {
				file: typeof file === "string" ? file : null,
				seed: isInt(row["seed"]) ? row["seed"] : null,
				fps: isInt(row["fps"]) ? row["fps"] : null,
				ticks,
				storage,
			};
			continue;
		}
		const tick = row["tick"];
		if (!isInt(tick) || tick < 0) {
			return fail(number, "tick は 0 以上の整数です");
		}
		if (tick < lastTick) {
			return fail(
				number,
				`tick が昇順ではありません（${String(lastTick)} の後に ${String(tick)}）`,
			);
		}
		const kind = row["kind"];
		if (kind === "key") {
			if (typeof row["name"] !== "string") {
				return fail(number, "key の name は文字列です");
			}
			if (typeof row["down"] !== "boolean") {
				return fail(number, "key の down は真偽値です");
			}
			events.push({ tick, kind: "key", name: row["name"], down: row["down"] });
		} else if (kind === "pointer") {
			for (const key of ["x", "y"] as const) {
				if (!isNum(row[key])) {
					return fail(number, `pointer の ${key} は数値です`);
				}
			}
			if (typeof row["down"] !== "boolean") {
				return fail(number, "pointer の down は真偽値です");
			}
			events.push({
				tick,
				kind: "pointer",
				x: row["x"] as number,
				y: row["y"] as number,
				down: row["down"],
			});
		} else {
			return fail(number, `kind は ${EVENT_KINDS.join(" / ")} のどれかです`);
		}
		lastTick = tick;
	}
	if (header === null) {
		return fail(
			0,
			`ヘッダ行（{"jinrec": ${String(JINREC_VERSION)}, ...}）がありません`,
		);
	}
	return { ok: true, recording: { ...header, events } };
}

/** 録画のイベントを tick ごとに分ける（`events` は昇順なので 1 回の走査で済む）。 */
export function eventsByTick(
	events: readonly RecordedEvent[],
	ticks: number,
): readonly (readonly InputEvent[])[] {
	const out: InputEvent[][] = Array.from({ length: ticks }, () => []);
	for (const { tick, ...event } of events) {
		out[tick]?.push(event);
	}
	return out;
}
