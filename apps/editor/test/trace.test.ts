import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe as group, expect, test } from "vitest";

import { eventsFiredAt, isAncestorOrSame } from "../src/trace/filter";
import { maxSeq, parseTrace, pointerOf, rowsOf, seqOf, stringOf } from "../src/trace/parse";

/** `jin run --model fake` が実際に書いたトレース（11 行）。 */
const FIXTURE = join(process.cwd(), "..", "..", "tests", "fixtures", "traces", "pipeline-fake.jsonl");

function events(text: string) {
  const parsed = parseTrace(text);
  if (!parsed.ok) throw new Error(`読めない: ${parsed.line}: ${parsed.message}`);
  return parsed.events;
}

group("parseTrace", () => {
  test("`jin run --trace` の実出力を読む", () => {
    const rows = events(readFileSync(FIXTURE, "utf8"));
    expect(rows).toHaveLength(11);
    expect(rows.map((row) => seqOf(row))).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]);
    expect(pointerOf(rows[0]!)).toBe("/circles/2/core");
    expect(maxSeq(rows)).toBe(11);
  });

  test("空行は読み飛ばすが、行番号は**実ファイルの位置**のまま", () => {
    const rows = events('\n{"seq": 1, "pointer": null}\n\n{"seq": 2, "pointer": "/circles/0"}\n');
    expect(rows.map((row) => row.line)).toEqual([2, 4]);
  });

  test("壊れた行で止まり、実ファイルの行番号を返す（黙って飛ばさない）", () => {
    const parsed = parseTrace('{"seq": 1, "pointer": null}\nこわれている\n{"seq": 3}\n');
    expect(parsed.ok).toBe(false);
    if (parsed.ok) return;
    // **2 行目**。読み飛ばして 2 件返してはいけない（NFR-FAIL-001）。
    expect(parsed.line).toBe(2);
    expect(parsed.message).toContain("JSON として読めません");
  });

  test("空行を挟んだ先の壊れた行でも行番号がずれない（F-V-P3-004 と同じ理由）", () => {
    const parsed = parseTrace('\n\n{"seq": 1, "pointer": null}\n\nこわれている\n');
    expect(parsed.ok).toBe(false);
    if (parsed.ok) return;
    expect(parsed.line).toBe(5);
  });

  test("オブジェクトでない行は拒む", () => {
    for (const [text, shape] of [
      ["[1, 2]\n", "array"],
      ["42\n", "number"],
      ["null\n", "null"],
      ['"x"\n', "string"],
    ] as const) {
      const parsed = parseTrace(text);
      expect(parsed.ok).toBe(false);
      if (parsed.ok) continue;
      expect(parsed.message).toContain(shape);
    }
  });

  test("行の区切りは `\\n` だけ（U+2028 を含む正当な出力を割らない）", () => {
    const rows = events('{"seq": 1, "pointer": null, "output": "a\\u2028b"}\n');
    expect(rows).toHaveLength(1);
    expect(rows[0]!.row["output"]).toBe("a b");
  });

  test("`\\r\\n` は 1 つだけ落とす / BOM も 1 つだけ落とす", () => {
    const rows = events('﻿{"seq": 1, "pointer": null}\r\n{"seq": 2, "pointer": null}\r\n');
    expect(rows).toHaveLength(2);
  });

  test("空のトレースは正当（`docs/spec/layout.md` §7.4）", () => {
    expect(events("")).toHaveLength(0);
    expect(events("\n\n")).toHaveLength(0);
    expect(maxSeq([])).toBe(0);
  });

  test("キーを取捨選択しない（`input` / `output` をそのままサーバへ渡す）", () => {
    const rows = events('{"seq": 1, "pointer": null, "input": {"k": 1}, "output": [1, 2]}\n');
    expect(rowsOf(rows)).toEqual([
      { seq: 1, pointer: null, input: { k: 1 }, output: [1, 2] },
    ]);
  });

  test("`seq` が整数でない行はここでは拒まない（契約は `jin_render` が持つ）", () => {
    // 二重に実装するとレンダラと食い違ったときに気づけない。読めはするが `seqOf` は null。
    const rows = events('{"seq": "x", "pointer": null}\n{"seq": true, "pointer": null}\n');
    expect(rows).toHaveLength(2);
    expect(rows.map((row) => seqOf(row))).toEqual([null, null]);
  });

  test("文字列欄の読み取り", () => {
    const rows = events('{"seq": 1, "pointer": null, "kind": "model", "name": "m", "agent": 3}\n');
    expect(stringOf(rows[0]!, "kind")).toBe("model");
    expect(stringOf(rows[0]!, "name")).toBe("m");
    expect(stringOf(rows[0]!, "agent")).toBeNull();
    expect(stringOf(rows[0]!, "missing")).toBeNull();
  });
});

group("isAncestorOrSame（overlay の規則 1 と同じ判定）", () => {
  test("完全一致は残る", () => {
    expect(isAncestorOrSame("/circles/2/core", "/circles/2/core")).toBe(true);
  });

  test("配下は残る", () => {
    expect(isAncestorOrSame("/circles/2", "/circles/2/core")).toBe(true);
    expect(isAncestorOrSame("/circles/2", "/circles/2/tools/0")).toBe(true);
  });

  test("**前方一致ではない**（段で区切る）", () => {
    // ここが変異の主対象。`startsWith` だけにすると `/circles/2` が
    // `/circles/20/core` を拾ってしまう。
    expect(isAncestorOrSame("/circles/2", "/circles/20/core")).toBe(false);
    expect(isAncestorOrSame("/circles/2", "/circles/21")).toBe(false);
  });

  test("子は祖先ではない（向きを取り違えない）", () => {
    expect(isAncestorOrSame("/circles/2/core", "/circles/2")).toBe(false);
  });

  test("ルートは祖先に数えない", () => {
    expect(isAncestorOrSame("", "/circles/2/core")).toBe(false);
  });

  test("兄弟は残らない", () => {
    expect(isAncestorOrSame("/circles/2", "/circles/3/core")).toBe(false);
  });
});

group("eventsFiredAt", () => {
  const rows = events(readFileSync(FIXTURE, "utf8"));

  test("選択が無ければ絞り込まない", () => {
    expect(eventsFiredAt(rows, null)).toHaveLength(11);
  });

  test("完全一致した行だけ残る", () => {
    const found = eventsFiredAt(rows, "/circles/4/core");
    expect(found.map((row) => seqOf(row))).toEqual([3, 6, 9]);
  });

  test("配下の行も残る（circle を選ぶと核の行が残る）", () => {
    const found = eventsFiredAt(rows, "/circles/4");
    expect(found.map((row) => seqOf(row))).toEqual([3, 6, 9]);
  });

  test("`pointer: null` の行は残らない", () => {
    const withNull = events('{"seq": 1, "pointer": null}\n{"seq": 2, "pointer": "/circles/0"}\n');
    expect(eventsFiredAt(withNull, "/circles/0").map((row) => seqOf(row))).toEqual([2]);
  });

  test("別の紋の行は残らない", () => {
    expect(eventsFiredAt(rows, "/circles/1/flow/exit").map((row) => seqOf(row))).toEqual([5, 8, 11]);
    expect(eventsFiredAt(rows, "/circles/2/core").map((row) => seqOf(row))).toEqual([1]);
  });
});
