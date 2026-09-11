"""OK/NG の決定的ルール。LLM には判定させず、この関数だけが verdict を決める。

`jin run` はこのモジュールを cwd（または PYTHONPATH）から import する。
関数名 = ADK の FunctionTool 名（`FunctionTool.name == func.__name__`）。

2 段に分けてある:

- `decide(findings_json)`: 純関数。Verifier の JSON 文字列を受け取り verdict の JSON 文字列を返す。
  モデル無しで単体テストできる
- `judge(tool_context)`: ADK から呼ばれるツール。`Verifier` が `output_key` で書いた
  `session.state["findings"]` を**直接**読んで `decide` に渡す。引数名 `tool_context` は ADK 2.8.0 が
  型注釈なしでも注入し、LLM 向けの関数宣言からは隠す（`google/adk/tools/function_tool.py`）。
  LLM に JSON をツール引数へ転記させると二重エスケープで壊れる（Gemini 3.8 Flash で実測）ので、
  LLM は引数を渡さない
"""

from __future__ import annotations

import json
import re
from typing import Any

SEVERITIES = ("Critical", "Major", "Minor", "Suggest")
AXES = ("w5h1", "volume", "terminology", "typo", "grammar", "consistency")

#: Verifier が `output_key` で書く state key（docreview.jin の Verifier.state[0].name と一致させる）
FINDINGS_STATE_KEY = "findings"

# 総合点への重み（合計 1.0）。読者の行動に直結する観点を重くする
WEIGHTS = {
    "w5h1": 0.30,
    "volume": 0.15,
    "terminology": 0.15,
    "typo": 0.15,
    "grammar": 0.15,
    "consistency": 0.10,
}

# NG になる条件（いずれか 1 つでも該当したら NG）
MAX_CRITICAL = 0
MAX_MAJOR = 2
MIN_TOTAL_SCORE = 70
MIN_AXIS_SCORE = 50

_CODE_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def judge(tool_context) -> str:
    """検証済み指摘（session state の `findings`）から OK/NG と総合点を決め、JSON 文字列で返す。

    引数は取らない。判定に使う指摘は Verifier が書いたセッション状態から読む。
    （`tool_context` は ADK が注入する ToolContext。型注釈を書くと google.adk への依存になるので書かない）
    """
    findings_json = tool_context.state.get(FINDINGS_STATE_KEY)
    if not isinstance(findings_json, str):
        return _ng(f"session state に {FINDINGS_STATE_KEY} が無い（Verifier が出力していない）")
    return decide(findings_json)


def decide(findings_json: str) -> str:
    """Verifier の JSON 文字列から verdict の JSON 文字列を作る純関数。"""
    data = _loads_lenient(findings_json)
    if not isinstance(data, dict):
        return _ng("検証済み指摘を JSON として読めない")

    findings = data.get("findings") or []
    scores = data.get("scores") or {}
    counts = {s: 0 for s in SEVERITIES}
    for f in findings:
        sev = f.get("severity") if isinstance(f, dict) else None
        if sev in counts:
            counts[sev] += 1

    axis_scores = {a: _clamp(scores.get(a, 0)) for a in AXES}
    total = round(sum(axis_scores[a] * WEIGHTS[a] for a in AXES))

    reasons: list[str] = []
    if counts["Critical"] > MAX_CRITICAL:
        reasons.append(f"Critical が {counts['Critical']} 件（上限 {MAX_CRITICAL}）")
    if counts["Major"] > MAX_MAJOR:
        reasons.append(f"Major が {counts['Major']} 件（上限 {MAX_MAJOR}）")
    if total < MIN_TOTAL_SCORE:
        reasons.append(f"総合点 {total}（下限 {MIN_TOTAL_SCORE}）")
    low = [a for a in AXES if axis_scores[a] < MIN_AXIS_SCORE]
    if low:
        reasons.append(f"観点別の点数が下限 {MIN_AXIS_SCORE} 未満: {', '.join(low)}")

    return json.dumps(
        {
            "verdict": "NG" if reasons else "OK",
            "score": total,
            "axis_scores": axis_scores,
            "counts": counts,
            "reasons": reasons,
            "findings": findings,
            "dropped": data.get("dropped") or [],
        },
        ensure_ascii=False,
    )


def _loads_lenient(text: str) -> Any:
    """LLM 出力の JSON を読む。コードフェンス（```json）と、JSON 文字列として二重にエンコードされた
    形（`"{\\n  \\"findings\\"..."` のような転記事故）だけは剥がす。それ以外は素の json.loads と同じ。"""
    if not isinstance(text, str):
        return None
    candidate = text.strip()
    fenced = _CODE_FENCE.match(candidate)
    if fenced:
        candidate = fenced.group(1)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    try:
        inner = json.loads(f'"{candidate}"')  # 二重エスケープを 1 段剥がす
        return json.loads(inner) if isinstance(inner, str) else None
    except json.JSONDecodeError:
        return None


def _ng(reason: str) -> str:
    return json.dumps(
        {
            "verdict": "NG",
            "score": 0,
            "axis_scores": {a: 0 for a in AXES},
            "counts": {s: 0 for s in SEVERITIES},
            "reasons": [reason],
            "findings": [],
            "dropped": [],
        },
        ensure_ascii=False,
    )


def _clamp(value: object) -> int:
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, n))
