/**
 * `jin run --trace` が書いた JSONL の読み取り（要件書 §7.2 / `docs/spec/layout.md` §7.5）。
 *
 * **ブラウザはファイルシステムを持たない。** トレースは `<input type="file">` で
 * ユーザーが渡し、ここで 1 行ずつ JSON にする（HANDOFF `DP-IMPL-JIN-P6-TRACE-SOURCE-01`）。
 * サーバに読み込みリクエストを足さないのは、要件書 §6.3 の独自リクエスト 4 種
 * （+ ADR-011 の 2 種）への**追加が仕様変更**で人間の承認を要するからであり、
 * また `jin lsp --ws` はトークンで閉じてはいても same-origin 制限の無い口だからである
 * （`docs/spec/ops.md` §5.1）。ファイル入力なら読めるのは**ユーザーが選んだ 1 本**だけになる。
 *
 * ## 検証をどこまでやるか
 *
 * ここでやるのは `jin_cli.main._read_trace_rows` と**同じ範囲**である:
 * 行を JSON にして、オブジェクトであることを見る。それだけ。
 * `seq` / `pointer` の契約（1 始まり・範囲・型）は `jin_render.overlay.read_trace` が
 * 持っており、二重に実装するとレンダラと食い違ったときに気づけない。
 * サーバが拒んだらその文言をそのまま出す（`App` の `notice`）。
 *
 * **黙って読み飛ばさない**（NFR-FAIL-001）。壊れた行に当たったらそこで止め、
 * **実ファイルの行番号**を添えて返す。空行だけは読み飛ばすので、並びの位置と
 * 行番号はずれる（F-V-P3-004 と同じ理由）。
 */

/** サーバへそのまま渡す 1 行。**キーを取捨選択しない**（`input` / `output` も要る）。 */
export type TraceRow = Readonly<Record<string, unknown>>;

export interface TraceEvent {
  /** JSONL の**実ファイル行番号**（1 始まり）。空行を飛ばすので添字とはずれる。 */
  readonly line: number;
  readonly row: TraceRow;
}

export type ParseResult =
  | { readonly ok: true; readonly events: readonly TraceEvent[] }
  | { readonly ok: false; readonly line: number; readonly message: string };

/**
 * JSONL を読む。
 *
 * 行の区切りは **`\n` だけ**である（`jin_adk.trace` の writer が書くのがそれだけ・
 * `docs/spec/layout.md` §7.5）。JavaScript の `String.prototype.split("\n")` は
 * U+2028 / U+2029 で割らないので、モデル出力にそれらを含む**正当なトレース**も読める。
 * Windows で書かれた `\r\n` を通すため、行末の `\r` は 1 つだけ落とす。
 * 先頭の BOM は 1 つだけ落とす（`File.text()` は BOM を残す）。
 */
export function parseTrace(text: string): ParseResult {
  const body = text.startsWith("﻿") ? text.slice(1) : text;
  const events: TraceEvent[] = [];
  const lines = body.split("\n");
  for (let index = 0; index < lines.length; index += 1) {
    const number = index + 1;
    const raw = lines[index] ?? "";
    const line = raw.endsWith("\r") ? raw.slice(0, -1) : raw;
    if (line.trim() === "") continue;
    let value: unknown;
    try {
      value = JSON.parse(line);
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      return {
        ok: false,
        line: number,
        message: `JSON として読めません（${detail}）。--trace は 1 行 1 JSON オブジェクトの JSONL です`,
      };
    }
    if (value === null || typeof value !== "object" || Array.isArray(value)) {
      return {
        ok: false,
        line: number,
        message: `JSON オブジェクトではありません（${describeJson(value)}）。1 行 1 イベントで書いてください`,
      };
    }
    events.push({ line: number, row: value as TraceRow });
  }
  return { ok: true, events };
}

function describeJson(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  return typeof value;
}

/** サーバへ渡す形（`jin/renderSvg` の `trace`）。行番号は落とす。 */
export function rowsOf(events: readonly TraceEvent[]): readonly TraceRow[] {
  return events.map((event) => event.row);
}

/**
 * 行の `seq`。**整数でなければ `null`**（`bool` も除く。`jin_render.overlay` と同じ扱い）。
 *
 * スクラバの上限を決めるためだけに読む。範囲（`1..2^63-1`）の検査はサーバの仕事で、
 * ここでやると片方だけ直したときに食い違う。
 */
export function seqOf(event: TraceEvent): number | null {
  const seq = event.row["seq"];
  return typeof seq === "number" && Number.isInteger(seq) ? seq : null;
}

/** 行の `pointer`。文字列でなければ `null`（`pointer: null` の行も `null`）。 */
export function pointerOf(event: TraceEvent): string | null {
  const pointer = event.row["pointer"];
  return typeof pointer === "string" ? pointer : null;
}

/** 行の文字列欄（`kind` / `name` / `agent`）。無ければ `null`。 */
export function stringOf(event: TraceEvent, key: string): string | null {
  const value = event.row[key];
  return typeof value === "string" ? value : null;
}

/**
 * スクラバの上限。**`seq` の最大値**であって行数ではない。
 *
 * `upto` は「`seq <= upto` のイベントまで発火済み」（`docs/spec/layout.md` §7.4）なので、
 * 連番でないトレース（将来のフィルタ済み出力）でも最後の行まで届く値にする。
 */
export function maxSeq(events: readonly TraceEvent[]): number {
  let max = 0;
  for (const event of events) {
    const seq = seqOf(event);
    if (seq !== null && seq > max) max = seq;
  }
  return max;
}
