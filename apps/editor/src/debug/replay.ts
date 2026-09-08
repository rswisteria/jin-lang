import {
	maxSeq,
	parseTrace,
	type TraceEvent,
	type TraceRow,
} from "../trace/parse";

/**
 * 読み込み済みトレースと再生位置（要件書 §7.2）。
 *
 * **`ViewState` に混ぜない。** DP-COMMON-19 の 5 状態は「LSP との関係」を表しており、
 * トレースの有無はそれと直交する（構文エラー中でもトレースは読めるし、
 * 正常表示でもトレースが無いことはある）。混ぜると状態が 10 通りに増える。
 */
export interface Replay {
	/** 読み込んだファイル名。表示にだけ使う。 */
	readonly name: string;
	readonly events: readonly TraceEvent[];
	/** `seq <= upto` のイベントまで発火済み（`docs/spec/layout.md` §7.4）。0 は「まだ何も」。 */
	readonly upto: number;
}

export type LoadResult =
	| { readonly ok: true; readonly replay: Replay }
	| { readonly ok: false; readonly message: string };

/**
 * `<input type="file">` で選ばれた JSONL を読む。
 *
 * 壊れた行は**実ファイル行番号を添えて**断る（`jin render --trace` の `path:N:` と同じ形）。
 * 既定の再生位置は**最後まで**（`upto` = `seq` の最大値）。読み込んだ直後に
 * 全部灰色だと「読めていない」と見分けが付かない。
 */
export async function loadTrace(file: File): Promise<LoadResult> {
	let text: string;
	try {
		text = await file.text();
	} catch (error) {
		return {
			ok: false,
			message: `${file.name}: 読めません（${messageOf(error)}）`,
		};
	}
	const parsed = parseTrace(text);
	if (!parsed.ok) {
		return {
			ok: false,
			message: `${file.name}:${parsed.line}: ${parsed.message}`,
		};
	}
	if (parsed.events.length === 0) {
		// 空のトレースは**正当**である（`docs/spec/layout.md` §7.4「空トレースは点 0 個」）。
		return { ok: true, replay: { name: file.name, events: [], upto: 0 } };
	}
	return {
		ok: true,
		replay: {
			name: file.name,
			events: parsed.events,
			upto: maxSeq(parsed.events),
		},
	};
}

/**
 * 実行中に届いた 1 行を足す（Issue #34）。**`upto` は常に最大に保つ**。
 *
 * 伸ばさないと、行は届いているのに図が止まって見える。
 * SSE には実ファイル行番号が無いので、届いた順に 1 から振る（JSONL の行順と一致する）。
 */
export function appendRow(
	current: Replay | null,
	row: TraceRow,
	name: string,
): Replay {
	const events: TraceEvent[] = [
		...(current?.events ?? []),
		{ line: (current?.events.length ?? 0) + 1, row },
	];
	return { name, events, upto: maxSeq(events) };
}

function messageOf(error: unknown): string {
	return error instanceof Error ? error.message : String(error);
}
