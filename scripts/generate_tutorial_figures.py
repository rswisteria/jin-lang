"""`docs/tetris-tutorial.md` の図（`<!-- figure: … -->` … `<!-- /figure -->`）を段階サンプルから生成する。

    uv run python scripts/generate_tutorial_figures.py           # docs/images/tutorial/*.svg と本文のブロックを書く
    uv run python scripts/generate_tutorial_figures.py --check   # ずれていたら exit 1（pytest と CI が呼ぶ）

教材は「ビジュアル言語なのでコード例は図で見せる」を約束している。ただし `jin render` の手順の図は
記号だけで式の文字を持たない（式はエディタのプロパティパネルに出る）ので、1 つの図は

- `jin_render.render(model, focus="陣/手順")` の SVG に、**番号のラベル**（生成器が足す。位置は
  レンダラの `place_block` / `geo.point` で求め、レイアウトを再実装しない）
- 番号 → 記号 → Do → 内容（式）の表（エディタでそのステップを選ぶとパネルに出る内容）

の組にする。ブロックの書き方は本文のマーカー `<!-- figure: <段階> <指定> -->` で、`<指定>` は
`陣/手順`（手順の図）・`陣`（陣全体の図 + 記憶環の表）・`form 名前`（型紙の欄）・`flow 陣`（核なし陣）・
`guards 陣`（境界環の検査）。マーカーの間は生成物で、手で編集しない。

番号の付け方: 手順直下は `1`, `2`, …（図では上から時計回り）。`loop` の中は `2.1`, `2.2`、`if` の then は
`4t1`, `4t2`、else は `4e1`（図では then が親の弧の前半 = 反時計回り側、else が後半）。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from jin_core.check import check_file
from jin_core.v2.model import (
    BreakStep,
    CastStep,
    Circle,
    EmitStep,
    FinishStep,
    IfStep,
    JinFileV2,
    LetStep,
    LoopStep,
    ReturnStep,
    SetStep,
    Step,
    TransferStep,
    WaitStep,
)
from jin_render import geometry as geo
from jin_render import render
from jin_render.svg import fmt_coord
from jin_render.v2.rite import CAST_HOST, CAST_RITE, classify_cast, place_block

REPO_ROOT = Path(__file__).resolve().parents[1]
GUIDE = REPO_ROOT / "docs" / "tetris-tutorial.md"
SAMPLES = REPO_ROOT / "docs" / "samples" / "tetris"
OUT_DIR = REPO_ROOT / "docs" / "images" / "tutorial"
IMG_REL = "images/tutorial"  # 本文（docs/）からの相対

BLOCK = re.compile(r"<!-- figure: ([\w-]+) ([^\n]+?) -->\n(.*?)<!-- /figure -->", re.DOTALL)

#: 番号ラベル（正規化単位）。深さ 0 / 1 は記号（半径 0.05）の外側、深さ 2 以上は内側に置く
#: （深い環ほど弧が狭く、外側に出すと 1 つ上の環のラベルと重なる）
LABEL_OFFSET = 0.085
LABEL_FONT = 0.055
INWARD_FROM_DEPTH = 2
IMG_WIDTH = 360

GLYPHS = {
    "set": "四角",
    "let": "小さな四角",
    "if": "弦（分岐）",
    "break": "外へ抜ける線（横棒）",
    "wait": "環の欠け",
    "emit": "外へ向かう破線（小円）",
    "return": "外へ抜ける線",
    "finish": "外へ抜ける線（二重横棒）",
    "transfer": "外へ向かう破線（小さな陣）",
}


def code(text: str) -> str:
    """表のセルに入れるコード（`|` はセルを壊すので実体参照にする）。"""
    return "`" + text.replace("|", "&#124;") + "`"


def glyph_of(circle: Circle, step: Step) -> str:
    if isinstance(step, CastStep):
        kind = classify_cast(circle, step.target)
        if kind == CAST_HOST:
            return "円（外へ線 = 道具）"
        if kind == CAST_RITE:
            return "円（内へ線 = 自陣の手順）"
        return "破線の円（組み込みの効果）"
    if isinstance(step, LoopStep):
        if step.kind == "each":
            return "星形"
        return f"多角形（{max(3, len(step.steps))} 角）"
    return GLYPHS[step.do]


def describe(step: Step) -> str:
    if isinstance(step, SetStep):
        return code(f"{step.target} ← {step.expr}")
    if isinstance(step, LetStep):
        typed = f"{step.name}: {step.type}" if step.type else step.name
        return code(f"{typed} = {step.expr}")
    if isinstance(step, CastStep):
        call = f"{step.target}({', '.join(step.args)})"
        return code(f"{step.into} ← {call}") if step.into else code(call)
    if isinstance(step, IfStep):
        if step.else_:
            return f"{code(step.cond)} が真なら t の列、偽なら e の列へ"
        return f"{code(step.cond)} が真なら t の列へ"
    if isinstance(step, LoopStep):
        if step.kind == "while":
            return f"{code(step.cond or '')} の間、中を繰り返す"
        if step.kind == "count":
            name = f"（{code(step.name)} に 0, 1, … が入る）" if step.name else ""
            return f"{code(step.times or '')} 回、中を繰り返す{name}"
        return f"{code(step.in_ or '')} の要素を順に {code(step.name or '')} へ入れて繰り返す"
    if isinstance(step, WaitStep):
        if step.until is not None:
            return f"{code(step.until)} が真になるまで待つ"
        return f"{code(step.ticks or '')} tick 待つ"
    if isinstance(step, ReturnStep):
        if step.expr is not None:
            return f"手順を抜けて {code(step.expr)} を返す"
        return "手順を抜ける"
    if isinstance(step, BreakStep):
        return "いちばん近い繰り返しを抜ける"
    if isinstance(step, FinishStep):
        return "陣を終える"
    if isinstance(step, EmitStep):
        return f"{code(step.circle)} へ {code(step.message)} を送る"
    if isinstance(step, TransferStep):
        return f"{code(step.circle)} へ制御を渡す"
    raise TypeError(step)


def _labels(steps: list[Step], prefix: str) -> list[tuple[str, Step]]:
    out: list[tuple[str, Step]] = []
    for position, step in enumerate(steps, start=1):
        label = f"{prefix}{position}"
        out.append((label, step))
        if isinstance(step, IfStep):
            out.extend(_labels(step.then, f"{label}t"))
            out.extend(_labels(step.else_, f"{label}e"))
        elif isinstance(step, LoopStep):
            out.extend(_labels(step.steps, f"{label}."))
    return out


def rite_table(circle: Circle, steps: list[Step]) -> str:
    rows = ["| 番号 | 記号 | Do | 内容 |", "|---|---|---|---|"]
    for label, step in _labels(steps, ""):
        rows.append(f"| {label} | {glyph_of(circle, step)} | `{step.do}` | {describe(step)} |")
    return "\n".join(rows)


def _placed_labels(steps: list[Step]) -> list[tuple[str, float, float, int]]:
    """(番号, 環, 角度) を、レンダラと同じ `place_block` で求める。"""
    count = len(steps)
    top = place_block(steps, "/steps", 0, geo.TOP_ANGLE - 180.0 / count, 360.0) if count else []
    flat = [item for root in top for item in root.walk()]
    labels = _labels(steps, "")
    if len(flat) != len(labels):
        raise RuntimeError("place_block の並びと番号の並びが違う")
    return [
        (label, item.ring, item.angle, item.depth)
        for (label, _), item in zip(labels, flat, strict=True)
    ]


def with_labels(svg: str, steps: list[Step]) -> str:
    """手順の図の SVG に番号ラベルを重ねる（レンダラの出力には触れず、末尾に `<g>` を足す）。"""
    frame = geo.root_frame()
    size = fmt_coord(LABEL_FONT * frame.scale)
    halo = fmt_coord(LABEL_FONT * frame.scale * 0.35)
    texts = []
    inner = (
        0  # 内側に置くラベルの通し番号（互い違いの半径にして、狭い弧に並ぶ同士の重なりを減らす）
    )
    for label, ring, angle, depth in _placed_labels(steps):
        if depth >= INWARD_FROM_DEPTH:
            # 深さ 3（最内環 0.35）はさらに内側へ。核（0.15）との間に収まる
            inward = LABEL_OFFSET * (1.0 + 0.7 * (inner % 2)) + (0.05 if depth >= 3 else 0.0)
            inner += 1
            offset = -inward
        else:
            offset = LABEL_OFFSET
        x, y = geo.point(frame, ring + offset, angle)
        texts.append(
            f'<text x="{fmt_coord(x)}" y="{fmt_coord(y)}" font-size="{size}" '
            f'font-family="sans-serif" font-weight="bold" text-anchor="middle" '
            f'dominant-baseline="central" fill="#c0392b" stroke="#fff" stroke-width="{halo}" '
            f'paint-order="stroke">{label}</text>'
        )
    group = '<g data-tutorial="labels">' + "".join(texts) + "</g>"
    end = svg.rstrip().rfind("</svg>")
    if end < 0:
        raise RuntimeError("</svg> が無い")
    return svg[:end] + group + "\n" + svg[end:]


def img(path_rel: str, alt: str) -> str:
    return f'<img src="{IMG_REL}/{path_rel}" width="{IMG_WIDTH}" alt="{alt}">'


def circle_named(model: JinFileV2, name: str) -> Circle:
    for circle in model.circles:
        if circle.name == name:
            return circle
    raise KeyError(name)


def build(stage: str, spec: str, model: JinFileV2) -> tuple[str, dict[str, str]]:
    """ブロックの本文と、書く SVG（ファイル名 → 中身）を返す。"""
    files: dict[str, str] = {}
    if "/" in spec and not spec.startswith(("form ", "flow ", "guards ")):
        circle_name, rite_name = spec.split("/", 1)
        circle = circle_named(model, circle_name)
        rite = next(r for r in circle.rites if r.name == rite_name)
        file = f"{stage}-{circle_name}-{rite_name}.svg"
        files[file] = with_labels(render(model, focus=spec), rite.steps)
        head = ""
        if rite.params or rite.returns:
            params = ", ".join(f"{p.name}: {p.type}" for p in rite.params)
            returns = f" -> {rite.returns}" if rite.returns else ""
            head = f"手順 `{rite_name}({params}){returns}`\n\n"
        body = f"{img(file, f'手順 {rite_name} の図')}\n\n{head}{rite_table(circle, rite.steps)}"
        return body, files

    file = f"{stage}.svg"
    files[file] = render(model)
    if spec.startswith("form "):
        name = spec.split(" ", 1)[1]
        form = next(f for f in model.forms if f.name == name)
        rows = ["| 欄 | 型 |", "|---|---|"] + [f"| `{f.name}` | `{f.type}` |" for f in form.fields]
        body = f"{img(file, '陣全体の図')}\n\n型紙 `{name}`\n\n" + "\n".join(rows)
        return body, files
    if spec.startswith("flow "):
        name = spec.split(" ", 1)[1]
        circle = circle_named(model, name)
        assert circle.flow is not None
        rows = [
            "| 欄 | 値 |",
            "|---|---|",
            f"| `kind` | `{circle.flow.kind}` |",
            f"| `steps` | {', '.join(code(s) for s in circle.flow.steps)} |",
            f"| `exit` | {code(circle.flow.exit) if circle.flow.exit else '—'} |",
        ]
        body = f"{img(file, '陣全体の図')}\n\n核なし陣 `{name}` の `flow`\n\n" + "\n".join(rows)
        return body, files
    if spec.startswith("guards "):
        name = spec.split(" ", 1)[1]
        circle = circle_named(model, name)
        rows = ["| assert | message |", "|---|---|"] + [
            f"| {code(g.assert_)} | {g.message or ''} |"
            for g in (circle.boundary.guards if circle.boundary else [])
        ]
        body = f"{img(file, '陣全体の図')}\n\n陣 `{name}` の境界環の検査\n\n" + "\n".join(rows)
        return body, files
    circle = circle_named(model, spec)
    rows = ["| 名前 | 型 | 最初の値 | out |", "|---|---|---|---|"] + [
        f"| `{s.name}` | `{s.type}` | {code(s.init)} | {'✓' if s.out else ''} |"
        for s in circle.state
    ]
    sigils = ", ".join(code(s.name) for s in circle.sigils) or "なし"
    core = code(circle.core) if circle.core else "なし"
    on = (
        ", ".join(
            f"{code(h.event)} → {code(h.rite)}"
            for h in (circle.boundary.on if circle.boundary else [])
        )
        or "なし"
    )
    body = (
        f"{img(file, '陣全体の図')}\n\n陣 `{spec}`: 核 {core}・道具環 {sigils}・"
        f"`on` {on}\n\n記憶環（`state`）\n\n" + "\n".join(rows)
    )
    return body, files


def generate(guide_text: str) -> tuple[str, dict[str, str]]:
    models: dict[str, JinFileV2] = {}
    files: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        stage, spec = match.group(1), match.group(2)
        if stage not in models:
            result = check_file(SAMPLES / f"{stage}.jin")
            if result.model is None or not isinstance(result.model, JinFileV2):
                raise RuntimeError(f"{stage}.jin が読めない")
            models[stage] = result.model
        body, new_files = build(stage, spec, models[stage])
        for name, content in new_files.items():
            if name in files and files[name] != content:
                raise RuntimeError(f"{name} が 2 通りに生成された")
            files[name] = content
        return (
            f"<!-- figure: {stage} {spec} -->\n"
            f"<!-- 生成物（scripts/generate_tutorial_figures.py）。手で編集しない -->\n"
            f"{body}\n<!-- /figure -->"
        )

    text, count = BLOCK.subn(replace, guide_text)
    if count == 0:
        raise RuntimeError("figure のマーカーが 1 つも無い")
    return text, files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="ずれを報告して exit 1")
    args = parser.parse_args(argv)
    guide = GUIDE.read_text(encoding="utf-8")
    text, files = generate(guide)
    if args.check:
        drift = []
        if text != guide:
            drift.append(str(GUIDE.relative_to(REPO_ROOT)))
        for name, content in files.items():
            path = OUT_DIR / name
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                drift.append(str(path.relative_to(REPO_ROOT)))
        stale = sorted(p.name for p in OUT_DIR.glob("*.svg") if p.name not in files)
        drift.extend(f"{IMG_REL}/{name}（参照されていない）" for name in stale)
        if drift:
            print("生成物がずれている:", *drift, sep="\n  ", file=sys.stderr)
            return 1
        print(f"{len(files)} 個の図と本文は生成物と一致")
        return 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (OUT_DIR / name).write_text(content, encoding="utf-8")
    for path in OUT_DIR.glob("*.svg"):
        if path.name not in files:
            path.unlink()
    GUIDE.write_text(text, encoding="utf-8")
    print(f"wrote {len(files)} svg + {GUIDE.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
