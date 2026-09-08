import { describe, expect, it } from "vitest";

import { SseDecoder } from "../src/run/client";

describe("SseDecoder", () => {
	it("1 つのフレームを読む", () => {
		const decoder = new SseDecoder();
		const events = decoder.push(
			'event: row\ndata: {"seq":1,"kind":"text"}\n\n',
		);
		expect(events).toEqual([{ kind: "row", row: { seq: 1, kind: "text" } }]);
	});

	it("chunk をまたいだフレームを落とさない", () => {
		// **ネットワークは行の途中で切れる。** 貯めずに捨てると行が消える。
		const decoder = new SseDecoder();
		expect(decoder.push('event: row\ndata: {"seq"')).toEqual([]);
		expect(decoder.push(":1}\n\n")).toEqual([{ kind: "row", row: { seq: 1 } }]);
	});

	it("1 つの chunk に複数フレームが入っていても全部返す", () => {
		const decoder = new SseDecoder();
		const events = decoder.push(
			'event: row\ndata: {"seq":1}\n\nevent: row\ndata: {"seq":2}\n\n',
		);
		expect(events).toHaveLength(2);
	});

	it("done は exit と stderr を持つ", () => {
		const decoder = new SseDecoder();
		const events = decoder.push(
			'event: done\ndata: {"exit":1,"stderr":"だめでした\\n"}\n\n',
		);
		expect(events).toEqual([{ kind: "done", exit: 1, stderr: "だめでした\n" }]);
	});

	it("error はメッセージを持つ", () => {
		const decoder = new SseDecoder();
		const events = decoder.push(
			'event: error\ndata: {"message":"起こせません"}\n\n',
		);
		expect(events).toEqual([{ kind: "error", message: "起こせません" }]);
	});

	it("行が JSON オブジェクトでないフレームは捨てる", () => {
		// `parse.ts` と同じ規律（オブジェクトでない行は行として扱わない）。
		const decoder = new SseDecoder();
		expect(decoder.push("event: row\ndata: 42\n\n")).toEqual([]);
		expect(decoder.push("event: row\ndata: not json\n\n")).toEqual([]);
	});

	it("CRLF で区切られていても読む", () => {
		const decoder = new SseDecoder();
		const events = decoder.push('event: row\r\ndata: {"seq":1}\r\n\r\n');
		expect(events).toEqual([{ kind: "row", row: { seq: 1 } }]);
	});
});
