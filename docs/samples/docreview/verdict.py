"""`jin run --trace` の JSONL から OK/NG の判定を取り出す。

判定の**正本は `judge` ツールの応答行**（`kind: tool`・`output` がツールの戻り値そのもの）で、
`Judge` 陣の最終テキスト（`final` 行）は LLM が転記したものにすぎない。

使い方:
    uv run python docs/samples/docreview/verdict.py trace.jsonl

終了コード: 0 = OK / 1 = NG / 2 = 判定行が無い（実行が途中で落ちた・ツールが呼ばれなかった）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

JUDGE_TOOL = "judge"


def find_verdict(trace_path: Path) -> dict | None:
    """トレースから最後の `judge` 応答行を探し、戻り値の JSON を辞書で返す。無ければ None。"""
    verdict: dict | None = None
    for raw in trace_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line:
            continue
        row = json.loads(line)
        if row.get("kind") != "tool" or row.get("name") != JUDGE_TOOL:
            continue
        output = row.get("output")
        if output is None:
            continue  # 呼び出し行（input 側）
        # ADK の FunctionTool は dict でない戻り値を {"result": ...} に包む
        if isinstance(output, dict) and "result" in output:
            output = output["result"]
        if isinstance(output, str):
            output = json.loads(output)
        if isinstance(output, dict):
            verdict = output
    return verdict


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: verdict.py <trace.jsonl>", file=sys.stderr)
        return 2
    verdict = find_verdict(Path(argv[1]))
    if verdict is None:
        print("判定行（judge ツールの応答）がトレースにありません", file=sys.stderr)
        return 2
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return 0 if verdict.get("verdict") == "OK" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
