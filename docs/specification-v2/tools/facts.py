"""本の図の事実シート(`figures/<name>.facts.json`)を、リポジトリの正本から作る。

    uv run python docs/specification-v2/tools/facts.py           # 書き出す
    uv run python docs/specification-v2/tools/facts.py --check   # コミット済みのものとずれていれば exit 1

図は事実シートと `figure-check.mjs` で照合する(explainer の手順)。事実シートを手で書かず、ここで正本から引く:

- circle-rings: 陣の欄は `schemas/jin-v2.schema.json` の `Circle` / `Boundary`。辺は model.md §4 の参照の表
  (`core` → 自陣の手順、`boundary.on[].rite` → 自陣の手順)と、手順が記憶・道具を使うこと(model.md §3.3 / §3.4)
- tick-stages: tick の段は runtime.md §2 の番号付きの太字
- tetris-plus: 陣のつながりは `examples-v2/tetris-plus/tetris-plus.jin` の `flow.steps` / summon の道具 / 式の中の `陣名.key`
- views: `jin render` の見え方は CLI のオプション(`--focus` / `--full` / `--panorama`)
"""

from __future__ import annotations

import itertools
import json
import re
import sys
from pathlib import Path

BOOK = Path(__file__).resolve().parents[1]
REPO = BOOK.parents[1]
FIGURES = BOOK / "figures"


def circle_rings() -> dict:
    schema = json.loads((REPO / "schemas" / "jin-v2.schema.json").read_text(encoding="utf-8"))
    defs = schema["$defs"]
    circle = defs["Circle"]["properties"]
    boundary = defs["Boundary"]["properties"]
    names = {
        "core": "核（core）",
        "state": "記憶環（state）",
        "sigils": "道具環（sigils）",
        "rites": "手順環（rites）",
        "boundary": "境界環（boundary）",
    }
    missing = [key for key in names if key not in circle] + [
        k for k in ("on", "guards") if k not in boundary
    ]
    if missing:
        raise SystemExit(f"スキーマに無い欄: {missing}")
    labels = ["陣（circle）", *names.values(), "on", "guards"]
    edges = [
        "circle.core->circle.rites",  # model.md §4: core → 自陣の rite
        "circle.boundary.on->circle.rites",  # model.md §4: boundary.on[].rite → 自陣の rite
        "circle.rites->circle.state",  # model.md §3.4: set / let で記憶を読み書きする
        "circle.rites->circle.sigils",  # model.md §3.4: cast の target は道具の名前
    ]
    return {"labels": labels, "edges": edges}


def tick_stages() -> dict:
    text = (REPO / "docs" / "spec" / "v2" / "runtime.md").read_text(encoding="utf-8")
    section = text.split("## 2. tick の手順", 1)[1].split("\n## ", 1)[0]
    stages = re.findall(r"^\d\. \*\*(.+?)\*\*", section, flags=re.MULTILINE)
    if len(stages) != 7:
        raise SystemExit(f"runtime.md §2 の段が 7 つではない: {stages}")
    ids = [f"s{i + 1}" for i in range(len(stages))]
    return {
        "labels": [f"{i + 1}. {name}" for i, name in enumerate(stages)],
        "edges": [f"{a}->{b}" for a, b in itertools.pairwise(ids)],
    }


def tetris_plus() -> dict:
    model = json.loads(
        (REPO / "examples-v2" / "tetris-plus" / "tetris-plus.jin").read_text(encoding="utf-8")
    )
    names = [c["name"] for c in model["circles"]]
    edges: set[str] = set()
    for circle in model["circles"]:
        me = circle["name"]
        for child in circle.get("flow", {}).get("steps", []):
            edges.add(f"{me}->{child}")
        for sigil in circle.get("sigils", []):
            if sigil["kind"] == "summon":
                edges.add(f"{me}->{sigil['circle']}")
        exprs = json.dumps(circle.get("rites", []), ensure_ascii=False)
        for other in names:
            if other != me and re.search(rf"\b{other}\.[a-z]", exprs):
                edges.add(f"{me}->{other}")
    return {"labels": names, "edges": sorted(edges)}


FACTS = {
    "circle-rings": circle_rings,
    "tick-stages": tick_stages,
    "tetris-plus": tetris_plus,
}


def main() -> int:
    check = "--check" in sys.argv[1:]
    stale = []
    for name, build in FACTS.items():
        path = FIGURES / f"{name}.facts.json"
        text = json.dumps(build(), ensure_ascii=False, indent=2) + "\n"
        if check:
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                stale.append(path.name)
        else:
            FIGURES.mkdir(exist_ok=True)
            path.write_text(text, encoding="utf-8")
    if stale:
        print("事実シートが正本とずれています: " + ", ".join(stale))
        return 1
    print(
        f"事実シート {len(FACTS)} 枚: 正本と一致"
        if check
        else f"事実シート {len(FACTS)} 枚を書きました"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
