"""DP-REVIEW-JIN-008: 1000 行以下の .jin に対する check_text の実測（要件書 §6.4「1000 行以下で診断 1 秒以内」）。

使い方（リポジトリルートで）:

    uv run python delivery/20260904-1445-jin/bench/bench_check_text.py

結果と環境は check-text-benchmark.md に記録する。ケースは 5 つ:

- A / B: 現実的な 1000 行（正準形・circle 1 つ約 17 行）。B は flow.steps の半数を未解決名にして
  編集距離の hint 計算を走らせる
- C1〜C3: 敵対的。名前を model.py の上限（MAX_IDENT_LENGTH = 128）いっぱいにし、未解決参照を
  1 行 1 件で詰めて `MAX_DISTANCE_COMPUTATIONS`（20000 回）を使い切らせる。
  行数は 1000 行以下に保つ
"""

import statistics
import sys
import time

from jin_core.canonical import dumps as canonical_dumps
from jin_core.check import check_text
from jin_core.model import JinFile


def circle_llm(name, state_names, tool_refs=()):
    c = {
        "name": name,
        "core": "gemini-2.5-flash",
        "instruction": {"rune": "処理する " + " ".join("{%s}" % s for s in state_names)},
        "state": [{"name": s, "type": "str", "out": True} for s in state_names],
    }
    if tool_refs:
        c["tools"] = [{"name": f"t{i}", "ref": r} for i, r in enumerate(tool_refs)]
    return c


def build(n_circles, name_len=8, unresolved_ratio=0.0, extra_step_refs=0, step_name_len=None):
    step_name_len = step_name_len or name_len
    names = [("C%d" % i).ljust(name_len, "x") for i in range(n_circles)]
    circles = [{"name": "Root", "flow": {"kind": "sequence", "steps": list(names)}}]
    for i, nm in enumerate(names):
        circles.append(circle_llm(nm, [f"s{i}"]))
    # 未解決参照: steps に存在しない名前を混ぜる（JIN031 → 編集距離の hint 計算が走る）
    bad = int(n_circles * unresolved_ratio) + extra_step_refs
    circles[0]["flow"]["steps"] += [("Z%d" % k).ljust(step_name_len, "y") for k in range(bad)]
    doc = {
        "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
        "version": 1,
        "root": "Root",
        "circles": circles,
    }
    return canonical_dumps(JinFile.model_validate(doc))


def measure(label, text, reps=5):
    lines = text.count("\n") + 1
    ts = []
    for _ in range(reps):
        t0 = time.perf_counter()
        r = check_text(text, "bench.jin")
        ts.append(time.perf_counter() - t0)
    print(
        f"{label:48s} lines={lines:5d} bytes={len(text.encode()):7d} diags={len(r.diagnostics):4d} "
        f"median={statistics.median(ts) * 1000:8.1f} ms  max={max(ts) * 1000:8.1f} ms"
    )
    return lines


CASES = [
    ("A: 現実的・有効（1000 行）", dict(n_circles=58)),
    ("B: 現実的・未解決 50%（1000 行）", dict(n_circles=55, unresolved_ratio=0.5)),
    (
        "C1: 敵対的 名前 128 字・未解決 200 件（≤1000 行）",
        dict(n_circles=45, name_len=128, extra_step_refs=200),
    ),
    (
        "C2: 敵対的 名前 128 字・未解決 400 件（≤1000 行）",
        dict(n_circles=35, name_len=128, extra_step_refs=400),
    ),
    (
        "C3: 敵対的 名前 128 字・未解決 900 件（≤1000 行）",
        dict(n_circles=5, name_len=128, extra_step_refs=900),
    ),
]

if __name__ == "__main__":
    print(sys.version)
    for label, kw in CASES:
        measure(label, build(**kw))
