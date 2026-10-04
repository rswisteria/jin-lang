"""陣書き S0 spike: .jin → 手描き用の升目シート(SVG)と正解(JSON)。使い捨て。

1 行 = 1 つの図形の銘帯(spec §1.3 の欄の順)。ラテン層は 1 字 1 升、式紋・判別の紋は 1 紋 1 升。
レイアウトは連環陣ではなく行の並び(spike が測るのは升ごとの認識であって配置ではない)。

    uv run python make_sheet.py --check examples-v2/fib/fib.jin     # 平らにした結果を検算
    uv run python make_sheet.py examples-v2/fib/fib.jin examples-v2/clicker/clicker.jin
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from jin_core.v2.expr import canonical_expr

HERE = Path(__file__).resolve().parent
GLYPHS: dict[str, dict] = json.loads((HERE / "glyphs.json").read_text(encoding="utf-8"))

# ---------------------------------------------------------------- 平らにする

TOKEN = re.compile(
    r'"(?:[^"\\]|\\.)*"|[A-Za-z_][A-Za-z0-9_]*|[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?'
    r"|==|!=|<=|>=|\+\+|[-+*/%<>()\[\]{},:.]"
)
OP_GLYPH = {g["token"]: gid for gid, g in GLYPHS.items() if g["layer"] == "expr" and gid not in
            {"quote_l", "quote_r", "esc", "t_num", "t_bool", "t_str", "t_list_l", "t_list_r", "sep", "cont"}}
DISC = {(g["slot"], g["token"]): gid for gid, g in GLYPHS.items() if g["layer"] == "disc"}
from jin_core.v2.glyph import ESCAPE_LETTERS as ESCAPES  # noqa: E402  空白は esc + s(最終レビュー #1)


def L(text: str) -> list[dict]:
    return [{"t": "latin", "v": ch} for ch in text]


def G(gid: str) -> dict:
    assert gid in GLYPHS, gid
    return {"t": "glyph", "v": gid}


def string_cells(value: str) -> list[dict]:
    out = [G("quote_l")]
    for ch in value:
        if ch in ESCAPES:
            out += [G("esc"), *L(ESCAPES[ch])]
        elif ord(ch) < 0x20:
            out += [G("esc"), *L(f"u{ord(ch):04x}")]
        else:
            out += L(ch)
    return out + [G("quote_r")]


def expr_cells(text: str) -> list[dict]:
    out: list[dict] = []
    tokens = TOKEN.findall(text)
    if TOKEN.sub("", text).strip():  # 字句を除いて空白以外が残る = 知らない字(黙って落とさない・#119)
        raise ValueError(f"式に字句にならない字があります: {text!r}")
    for tok in tokens:
        if tok.startswith('"'):
            out += string_cells(json.loads(tok))
        elif tok in ("true", "false", "and", "or", "not"):
            out.append(G(tok))
        elif tok in OP_GLYPH:
            out.append(G(OP_GLYPH[tok]))
        else:
            out += L(tok)
    return out


def type_cells(t: str) -> list[dict]:
    if t.startswith("list<"):
        return [G("t_list_l"), *type_cells(t[5:-1]), G("t_list_r")]
    return [G({"num": "t_num", "bool": "t_bool", "str": "t_str"}[t])] if t in ("num", "bool", "str") else L(t)


def joined(*fields: list[dict]) -> list[dict]:
    out: list[dict] = []
    for i, f in enumerate(fields):
        if i:
            out.append(G("sep"))
        out += f
    return out


def listed(items: list[list[dict]]) -> list[dict]:
    out: list[dict] = []
    for i, it in enumerate(items):
        if i:
            out.append(G("comma"))
        out += it
    return out


@dataclass
class Row:
    id: str
    label: str
    cells: list[dict]
    exprs: list[str] = field(default_factory=list)  # 検算用: この行に入った式の原文
    strings: list[str] = field(default_factory=list)  # 検算用: この行に入った文字列(host / file / message)


def step_rows(steps: list[dict], base: str, rows: list[Row]) -> None:
    for k, s in enumerate(steps):
        p = f"{base}/{k}"
        do = s["do"]
        ex: list[str] = []

        def e(key: str) -> list[dict]:
            ex.append(s[key])
            return expr_cells(s[key])

        if do == "set":
            cells = joined(e("target"), e("expr"))
        elif do == "let":
            parts = [L(s["name"])]
            if "type" in s:
                parts.append(type_cells(s["type"]))
            cells = joined(*parts, e("expr"))
        elif do == "cast":
            ex += s.get("args", [])
            parts = [e("target"), listed([expr_cells(a) for a in s.get("args", [])])]
            if "into" in s:
                parts.append([G("mark_into"), *e("into")])
            cells = joined(*parts)
        elif do == "if":
            cells = e("cond")
        elif do == "loop":
            kind = s["kind"]
            head = [G(DISC[("loop", kind)])]
            if kind == "each":
                cells = head + joined(L(s["name"]), e("in"))
            elif kind == "while":
                cells = head + e("cond")
            else:
                parts = [e("times")]
                if "name" in s:
                    parts.append([G("mark_name"), *L(s["name"])])
                cells = head + joined(*parts)
        elif do == "wait":
            key = "ticks" if "ticks" in s else "until"
            cells = [G(DISC[("wait", key)]), *e(key)]
        elif do == "emit":
            ex += s.get("args", [])
            cells = joined(L(s["circle"]), string_cells(s["message"]), listed([expr_cells(a) for a in s.get("args", [])]))
        elif do == "return":
            cells = e("expr") if "expr" in s else []
        elif do == "transfer":
            cells = L(s["circle"])
        else:  # break / finish
            cells = []
        if cells:
            rows.append(Row(f"r{len(rows)}", f"{p} {do}", cells, ex))
        for key in ("then", "else", "steps"):
            if key in s:
                step_rows(s[key], f"{p}/{key}", rows)


#: spike の型紙が書けない欄(fib / clicker には無い)。黙って落とすと手描きの答えが元と合わなくなるので断る(#119)
STANDARD_SCHEMA = "https://xtone.internal/jin/schemas/jin-v2.schema.json"


def unsupported(model: dict) -> list[str]:
    found = []
    if model.get("$schema") != STANDARD_SCHEMA:
        found.append("$schema")
    if model["stage"].get("assets"):
        found.append("/stage/assets")
    for i, c in enumerate(model["circles"]):
        for key in ("description", "delegate"):
            if key in c:
                found.append(f"/circles/{i}/{key}")
        if "exit" in c.get("flow", {}):
            found.append(f"/circles/{i}/flow/exit")
    return found


def linearize(model: dict) -> list[Row]:
    if missing := unsupported(model):
        raise ValueError(f"spike の型紙はこの欄を書けません: {', '.join(missing)}")
    rows: list[Row] = []
    st = model["stage"]
    rows.append(Row("r0", "/stage", joined(*(L(str(st.get(k, d))) for k, d in
                                               (("width", 0), ("height", 0), ("fps", 60), ("seed", 0))))))
    for i, form in enumerate(model.get("forms", [])):
        rows.append(Row(f"r{len(rows)}", f"/forms/{i}", joined(L(form["name"]), listed(
            [L(fl["name"]) + type_cells(fl["type"]) for fl in form["fields"]]))))
    for i, c in enumerate(model["circles"]):
        cp = f"/circles/{i}"
        core = L(c["core"]) if "core" in c else [G(DISC[("flow", c["flow"]["kind"])])]
        rows.append(Row(f"r{len(rows)}", cp, joined(L(c["name"]), core)))
        for j, sv in enumerate(c.get("state", [])):
            cells = joined(L(sv["name"]), type_cells(sv["type"]), expr_cells(sv["init"]))
            rows.append(Row(f"r{len(rows)}", f"{cp}/state/{j}", cells, [sv["init"]]))
        for j, sg in enumerate(c.get("sigils", [])):
            extra = {"host": [string_cells(sg.get("host", ""))], "summon": [L(sg.get("circle", "")), L(sg.get("rite", ""))],
                     "agent": [string_cells(sg.get("file", ""))]}[sg["kind"]]
            texts = [sg[k] for k in ("host", "file") if k in sg]
            rows.append(Row(f"r{len(rows)}", f"{cp}/sigils/{j}", joined(L(sg["name"]), [G(DISC[("sigil", sg["kind"])])], *extra), strings=texts))
        for j, r in enumerate(c.get("rites", [])):
            parts = [L(r["name"]), listed([L(pm["name"]) + type_cells(pm["type"]) for pm in r.get("params", [])])]
            if "returns" in r:
                parts.append(type_cells(r["returns"]))
            rows.append(Row(f"r{len(rows)}", f"{cp}/rites/{j}", joined(*parts)))
            step_rows(r["steps"], f"{cp}/rites/{j}/steps", rows)
        b = c.get("boundary", {})
        for j, on in enumerate(b.get("on", [])):
            rows.append(Row(f"r{len(rows)}", f"{cp}/boundary/on/{j}", joined([G(DISC[("event", on["event"])])], L(on["rite"]))))
        for j, gd in enumerate(b.get("guards", [])):
            parts = [expr_cells(gd["assert"])]
            if "message" in gd:
                parts.append([G("mark_message"), *string_cells(gd["message"])])
            texts = [gd["message"]] if "message" in gd else []
            rows.append(Row(f"r{len(rows)}", f"{cp}/boundary/guards/{j}", joined(*parts), [gd["assert"]], texts))
    for row in rows:
        assert row.cells, row.label
    return rows


# ---------------------------------------------------------------- 検算


def to_ascii(cells: list[dict]) -> str:
    """式の升を ASCII の式に戻す(検算用)。名前・数のラテン文字は続けて書く。"""
    out: list[str] = []
    buf = ""
    instr = False
    escaped = False
    unescape = {v: k for k, v in ESCAPES.items()}
    for c in cells:
        if c["t"] == "latin":
            if escaped:  # esc + 字 → JSON の文字列リテラルの中の表記に戻す(u は 16 進 4 桁が続く)
                buf += "\\u" if c["v"] == "u" else json.dumps(unescape[c["v"]])[1:-1]
                escaped = False
            else:
                buf += c["v"]
            continue
        g = c["v"]
        if g == "quote_l":
            out.append(buf)
            buf = '"'
            instr = True
        elif g == "quote_r":
            out.append(buf + '"')
            buf = ""
            instr = False
        elif g == "esc":
            escaped = True
        else:
            if buf:
                out.append(buf)
                buf = ""
            out.append(GLYPHS[g]["token"])
        assert not (instr and g not in ("quote_l", "esc")), "文字列の中に紋"
    if buf:
        out.append(buf)
    return " ".join(out)


def check(rows: list[Row]) -> int:
    bad = 0
    for row in rows:
        for ex in row.exprs:
            got = canonical_expr(to_ascii(expr_cells(ex)))
            if got != canonical_expr(ex):
                print(f"NG {row.label}: {ex!r} -> {got!r}")
                bad += 1
        for text in row.strings:  # 文字列(エスケープ込み)も往復する(#119)
            got = json.loads(to_ascii(string_cells(text)))
            if got != text:
                print(f"NG {row.label}: {text!r} -> {got!r}")
                bad += 1
    total = sum(len(r.cells) for r in rows)
    seps = sum(c == G("sep") for r in rows for c in r.cells)
    print(f"行 {len(rows)} / 升 {total}(うち区切り {seps})/ 式の往復 NG {bad}")
    return 1 if bad else 0


# ---------------------------------------------------------------- シート

MM = 1.0  # SVG の単位は mm
SIDE = 280.0
FID = 15.0
MARGIN = 20.0
LABEL_W = 46.0
CELL = 5.0
LINE_H = 9.0  # 升 5 mm + 行間 4 mm
COLS = int((SIDE - 2 * MARGIN - LABEL_W) // CELL)  # 38
LINES = int((SIDE - 2 * MARGIN - 10) // LINE_H)  # 1 ページの行数


@dataclass
class Placed:
    row: str
    index: int  # 行の中の升の番号
    page: int
    box: tuple[float, float, float, float]  # x0, y0, x1, y1 (mm)


def layout(rows: list[Row]) -> tuple[list[list[tuple[Row, int, float]]], list[Placed]]:
    """行を折り返してページに詰める。戻り値はページごとの (行, 先頭の升番号, y) と、全升の配置。"""
    pages: list[list[tuple[Row, int, float]]] = [[]]
    placed: list[Placed] = []
    line = 0
    for row in rows:
        for start in range(0, len(row.cells), COLS):
            if line == LINES:
                pages.append([])
                line = 0
            y = MARGIN + 10 + line * LINE_H
            pages[-1].append((row, start, y))
            for k in range(start, min(start + COLS, len(row.cells))):
                x = MARGIN + LABEL_W + (k - start) * CELL
                placed.append(Placed(row.id, k, len(pages) - 1, (x, y, x + CELL, y + CELL)))
            line += 1
    return pages, placed


def fiducial(x: float, y: float, top_right: bool) -> str:
    s = FID
    inner = (
        f'<circle cx="{x + s / 2}" cy="{y + s / 2}" r="3.2" fill="#000"/>'
        if top_right
        else f'<rect x="{x + s / 2 - 3}" y="{y + s / 2 - 3}" width="6" height="6" fill="#000"/>'
    )
    return (f'<rect x="{x + 1}" y="{y + 1}" width="{s - 2}" height="{s - 2}" fill="none" stroke="#000" stroke-width="2"/>'
            + inner)


def cell_content(c: dict, x: float, y: float) -> str:
    """手本の升の中身。紋は字形のパス(1 升 = 100 を 5 mm に縮める)、ラテン文字は文字。"""
    if c["t"] == "glyph":
        return (f'<path transform="translate({x + 0.5} {y + 0.5}) scale(0.04)" d="{GLYPHS[c["v"]]["d"]}" '
                'fill="none" stroke="#000" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/>')
    ch = {"&": "&amp;", "<": "&lt;", ">": "&gt;"}.get(c["v"], c["v"])
    return (f'<text x="{x + CELL / 2}" y="{y + 3.9}" font-family="monospace" font-size="4.2" '
            f'text-anchor="middle">{ch}</text>')


def render_page(name: str, page_no: int, n_pages: int, entries: list[tuple[Row, int, float]], guide: bool = False) -> str:
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{SIDE}mm" height="{SIDE}mm" viewBox="0 0 {SIDE} {SIDE}">',
           f'<rect width="{SIDE}" height="{SIDE}" fill="#fff"/>']
    if not guide:  # 手本は撮らないので護符を描かない(手本を撮り違えても位置合わせで気づける)
        for (x, y, tr) in ((0, 0, False), (SIDE - FID, 0, True), (0, SIDE - FID, False), (SIDE - FID, SIDE - FID, False)):
            out.append(fiducial(x, y, tr))
    title = "GUIDE (copy this onto the sheet)" if guide else "sheet"
    out.append(f'<text x="{MARGIN + 2}" y="{MARGIN + 3}" font-family="sans-serif" font-size="4" fill="#888">'
               f'Jin glyph spike - {name} {page_no + 1}/{n_pages} - {title}</text>')
    for row, start, y in entries:
        label = f"{row.id} {row.label}" if start == 0 else f"{row.id} (cont.)"
        out.append(f'<text x="{MARGIN}" y="{y + 3.8}" font-family="monospace" font-size="2.2" fill="#aaa">{label[:30]}</text>')
        n = min(COLS, len(row.cells) - start)
        for k in range(n):
            x = MARGIN + LABEL_W + k * CELL
            out.append(f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" fill="none" stroke="#c8c8c8" stroke-width="0.25"/>')
            if guide:
                out.append(cell_content(row.cells[start + k], x, y))
    out.append("</svg>")
    return "\n".join(out) + "\n"


def extra_rows(name: str, rows: list[Row]) -> list[Row]:
    """合格線(spec §9 #17)の対象外の行。label が "extra" で始まり、採点は別に数える。"""
    if name == "clicker":  # Review Focus 3: 日本語の文字列
        return rows + [Row(f"r{len(rows)}", "extra japanese string", string_cells("まほうじん"))]
    if name == "fib":  # fib に出ない紋も測るため 57 字を 1 回ずつ。空のまま残す行で幻の字を測る(最終レビュー #2)
        return rows + [
            Row(f"r{len(rows)}", "extra all glyphs", [G(gid) for gid in GLYPHS]),
            Row(f"r{len(rows) + 1}", "extra leave empty", [{"t": "empty", "v": ""}] * 6),
        ]
    return rows


def build(path: Path) -> None:
    name = path.stem
    rows = extra_rows(name, linearize(json.loads(path.read_text(encoding="utf-8"))))
    pages, _ = layout(rows)
    (HERE / "sheets").mkdir(exist_ok=True)
    (HERE / "answers").mkdir(exist_ok=True)
    for n, entries in enumerate(pages):
        (HERE / "sheets" / f"{name}-{n + 1}.svg").write_text(render_page(name, n, len(pages), entries), encoding="utf-8")
        (HERE / "sheets" / f"{name}-{n + 1}-guide.svg").write_text(
            render_page(name, n, len(pages), entries, guide=True), encoding="utf-8")
    answers = {"source": str(path), "pages": len(pages),
               "rows": [{"id": r.id, "label": r.label, "cells": r.cells} for r in rows]}
    (HERE / "answers" / f"{name}.json").write_text(json.dumps(answers, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{name}: 行 {len(rows)} / 升 {sum(len(r.cells) for r in rows)} / {len(pages)} ページ")


def rows_for(name: str, source: Path) -> list[Row]:
    return extra_rows(name, linearize(json.loads(source.read_text(encoding="utf-8"))))


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--check":
        return max(check(linearize(json.loads(Path(p).read_text(encoding="utf-8")))) for p in argv[1:])
    for p in argv:
        build(Path(p))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
