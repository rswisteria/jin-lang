"""OK/NG の決定的ルール。LLM には判定させず、この関数だけが verdict を決める。

`jin run` はこのモジュールを cwd（または PYTHONPATH）から import する。
関数名 = ADK の FunctionTool 名（`FunctionTool.name == func.__name__`）。
"""

from __future__ import annotations

import json

SEVERITIES = ("Critical", "Major", "Minor", "Suggest")
AXES = ("w5h1", "volume", "terminology", "typo", "grammar", "consistency")

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


def judge(findings_json: str) -> str:
    """検証済み指摘 JSON から OK/NG と総合点を決め、JSON 文字列で返す。

    Args:
        findings_json: Verifier が出した JSON（findings / dropped / scores を持つ）。
    """
    try:
        data = json.loads(findings_json)
    except (json.JSONDecodeError, TypeError):
        return json.dumps(
            {"verdict": "NG", "reasons": ["検証済み指摘を JSON として読めない"], "score": 0},
            ensure_ascii=False,
        )

    findings = data.get("findings") or []
    scores = data.get("scores") or {}
    counts = {s: 0 for s in SEVERITIES}
    for f in findings:
        sev = f.get("severity")
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
        },
        ensure_ascii=False,
    )


def _clamp(value: object) -> int:
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, n))
