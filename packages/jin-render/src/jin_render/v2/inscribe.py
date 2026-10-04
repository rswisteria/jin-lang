"""銘帯の中身: `.jin`(v2)を銘環・額縁の銘帯に書く升の列にする(glyph 設計書 §1.2 / §1.3、正典 glyph.md §3)。

S3 の構文解析器はこの逆を行う(欄の順は `jin_core.v2.glyph` から引き、名前で書き写さない)。升の列は正準形の JSON から作るので、
升の pointer は「欄が正準形の JSON にあればその欄の pointer、無ければ持ち主の pointer」になり、モデルの pointer 空間に収まる。

- 名前と数はラテン 1 字 1 升。演算子・括弧・区切り・真偽は式紋 1 升
- 文字列(式の文字列リテラル・`description`・guard の `message`・asset の `path`・agent の `file`)は `quote_l` … `quote_r`。
  升に描けない字は `esc` + `ESCAPE_LETTERS`、それ以外の制御文字は `esc` `u` + 16 進 4 桁
- 名前(`Name`)の欄は括らない(`emit` の `message`・`host` の `host` も名前)
- 欄は `sep`、並びの要素は `comma`。省略できる欄は判別の紋(枠 `optional` / `wait`)を頭に置く
- `$schema` は標準の URL なら書かない(モデルに必ずあるので、書かれていなければ標準)
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from jin_core.canonical import dumps
from jin_core.schema_export import SCHEMA_ID_V2
from jin_core.v2.glyph import ESCAPE_LETTERS, EXPR_TOKEN_OF, GLYPHS, STRUCT_MARK_OF
from jin_core.v2.model import JinFileV2

from jin_render.v2.font import readable


@dataclass(frozen=True)
class InkCell:
    """銘帯の 1 升。`t` が latin なら `v` は 1 字、glyph なら紋 id、struct なら構造の印の id(と始まりの印)。"""

    t: Literal["latin", "glyph", "struct"]
    v: str
    pointer: str
    kind: str


#: 式の字句(expr.md §1 の終端記号と同じ集合)。長い記号を先に並べる。`jin_core.v2.expr` の Lark の字句と同じ切り方に
#: なることは `test_inscribe.py::test_the_token_pattern_cuts_like_the_expression_lexer` が全 fixture の式で見る。
#: 最後の `\S` は文法に無い字(JIN201 の式)で、黙って落とさずラテンの升にする(読めない式もそのまま往復させる)。
_TOKEN = re.compile(
    r'"(?:[^"\\]|\\.)*"|[A-Za-z_][A-Za-z0-9_]*|[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?'
    r"|==|!=|<=|>=|\+\+|[-+*/%<>()\[\]{},:.]|\S"
)
_GLYPH_OF_TOKEN = {token: gid for gid, token in EXPR_TOKEN_OF.items()}
_DISC = {(g.slot, g.token): g.id for g in GLYPHS if g.layer == "disc"}
_UNESCAPE = {letter: ch for ch, letter in ESCAPE_LETTERS.items()}
_TYPE_GLYPH = {"num": "t_num", "bool": "t_bool", "str": "t_str"}


class _Band:
    """1 本の銘帯を組み立てる道具(持ち主の pointer / kind と、欄の pointer を解く元の JSON を持つ)。"""

    def __init__(self, data: Any, owner: str, kind: str) -> None:
        self.data, self.owner, self.kind = data, owner, kind
        self.cells: list[InkCell] = []
        self.fields = 0

    def at(self, pointer: str) -> str:
        return pointer if _resolves(self.data, pointer) else self.owner

    def glyph(self, gid: str, pointer: str | None = None) -> None:
        self.cells.append(InkCell("glyph", gid, pointer or self.owner, self.kind))

    def struct(self, sid: str) -> None:
        self.cells.append(InkCell("struct", sid, self.owner, self.kind))

    def field(self) -> None:
        """欄の切れ目(2 つ目以降の欄の前に sep)。"""
        if self.fields:
            self.glyph("sep")
        self.fields += 1

    def name(self, text: str, pointer: str) -> None:
        self.cells += [InkCell("latin", ch, self.at(pointer), self.kind) for ch in text]

    def string(self, text: str, pointer: str) -> None:
        self.cells += _string_cells(text, self.at(pointer), self.kind)

    def expr(self, text: str, pointer: str) -> None:
        self.cells += expr_cells(text, self.at(pointer), self.kind)

    def type_(self, text: str, pointer: str) -> None:
        p = self.at(pointer)
        if text.startswith("list<") and text.endswith(">"):
            self.glyph("t_list_l", p)
            self.type_(text[5:-1], pointer)
            self.glyph("t_list_r", p)
        elif text in _TYPE_GLYPH:
            self.glyph(_TYPE_GLYPH[text], p)
        else:
            self.name(text, pointer)

    def typed(self, name: str, type_text: str, pointer: str) -> None:
        """引数・型紙の欄の 1 つ: `名前 colon 型`(型紙名の型もラテンなので colon が無いと名前との境が切れない)。"""
        self.name(name, f"{pointer}/name")
        self.glyph("colon", self.at(pointer))
        self.type_(type_text, f"{pointer}/type")

    def listed(self, items: Sequence[Any], pointer: str, write: Any) -> None:
        for k, item in enumerate(items):
            if k:
                self.glyph("comma", self.at(pointer))
            write(item, f"{pointer}/{k}")


def _resolves(data: Any, pointer: str) -> bool:
    node = data
    for part in pointer.split("/")[1:]:
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        elif isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return False
    return True


def _string_cells(text: str, pointer: str, kind: str) -> list[InkCell]:
    out = [InkCell("glyph", "quote_l", pointer, kind)]
    for ch in text:
        if ch in ESCAPE_LETTERS:
            out += [
                InkCell("glyph", "esc", pointer, kind),
                InkCell("latin", ESCAPE_LETTERS[ch], pointer, kind),
            ]
        elif not readable(ch):
            # 点から同じ字に読み戻せない字(制御文字・点の無い全角空白・字形が無く □ で描かれる字・同じ点の並びの組の先頭でない字)は
            # 符号位置で書く。BMP の外は UTF-16 のサロゲートの組(JSON の \u エスケープと同じ)
            data = ch.encode("utf-16-be")
            for k in range(0, len(data), 2):
                out.append(InkCell("glyph", "esc", pointer, kind))
                out += [
                    InkCell("latin", c, pointer, kind) for c in f"u{data[k] << 8 | data[k + 1]:04x}"
                ]
        else:
            out.append(InkCell("latin", ch, pointer, kind))
    out.append(InkCell("glyph", "quote_r", pointer, kind))
    return out


def expr_cells(text: str, pointer: str, kind: str) -> list[InkCell]:
    """式 1 本を升の列にする(式の字句ごと。名前と数はラテン 1 字 1 升)。"""
    out: list[InkCell] = []
    for token in _TOKEN.findall(text):
        if token.startswith('"'):
            out += _string_cells(json.loads(token), pointer, kind)
        elif token in _GLYPH_OF_TOKEN:
            out.append(InkCell("glyph", _GLYPH_OF_TOKEN[token], pointer, kind))
        else:
            out += [InkCell("latin", ch, pointer, kind) for ch in token]
    return out


def to_expr(cells: Sequence[InkCell]) -> str:
    """式の升を ASCII の式に戻す(字句の間に空白 1 つ。正準化は `canonical_expr` に任せる)。"""
    out: list[str] = []
    buf = ""
    in_string = escaped = False
    for cell in cells:
        if in_string:
            if escaped:
                buf += "\\u" if cell.v == "u" else json.dumps(_UNESCAPE[cell.v])[1:-1]
                escaped = False
            elif cell.t == "glyph" and cell.v == "esc":
                escaped = True
            elif cell.t == "glyph" and cell.v == "quote_r":
                out.append(buf + '"')
                buf, in_string = "", False
            else:
                buf += cell.v
            continue
        if cell.t == "latin":
            buf += cell.v
            continue
        if buf:
            out.append(buf)
            buf = ""
        if cell.v == "quote_l":
            buf, in_string = '"', True
        else:
            out.append(EXPR_TOKEN_OF[cell.v])
    if buf:
        out.append(buf)
    return " ".join(out)


def _canonical(model: JinFileV2) -> Any:
    return json.loads(dumps(model))


@dataclass(frozen=True)
class Inscription:
    """プログラム全体の銘文(額縁の銘帯・陣の銘環・手順の銘環)。正準 JSON を 1 回だけ作って全部の帯を組む。"""

    frame: list[InkCell]
    circles: dict[int, list[InkCell]]
    rites: dict[tuple[int, int], list[InkCell]]


def inscribe(model: JinFileV2) -> Inscription:
    """全部の銘帯。完全陣・型紙・鑑賞の帯が同じ帯を何度も組まないように使う(環ごとに `dumps` し直すと遅い)。"""
    data = _canonical(model)
    return Inscription(
        frame=frame_band(model, data=data),
        circles={ci: circle_ring(model, ci, data=data) for ci in range(len(model.circles))},
        rites={
            (ci, ri): rite_ring(model, ci, ri, data=data)
            for ci, circle in enumerate(model.circles)
            for ri in range(len(circle.rites))
        },
    )


def frame_band(model: JinFileV2, *, data: Any = None) -> list[InkCell]:
    """額縁の銘帯: (標準でない `$schema`)→ width / height / fps / seed → 型紙 → asset。"""
    data = _canonical(model) if data is None else data
    band = _Band(data, "/stage", "stage")
    if data.get("$schema") != SCHEMA_ID_V2:
        band.field()
        band.string(data["$schema"], "/$schema")
    for key in ("width", "height", "fps", "seed"):
        band.field()
        # 正準形は既定値の欄を落とすので、値はモデルから読む(既定値を写さない)
        band.name(str(getattr(model.stage, key)), f"/stage/{key}")
    names = [c["name"] for c in data["circles"]]
    if data["root"] in names and names.index(data["root"]) > 0:
        # S3: root が circles[0] でないときだけ root の添字(陣の塊の並びからは root の添字が分からない)
        band.field()
        band.name(str(names.index(data["root"])), "/root")
    cells = band.cells
    for i, form in enumerate(data.get("forms", [])):
        sub = _Band(data, f"/forms/{i}", "form")
        sub.struct(STRUCT_MARK_OF["form"])
        sub.field()
        sub.name(form["name"], f"/forms/{i}/name")
        sub.field()
        sub.listed(
            form["fields"],
            f"/forms/{i}/fields",
            lambda f, p, s=sub: s.typed(f["name"], f["type"], p),
        )
        cells += sub.cells
    for i, asset in enumerate(data["stage"].get("assets", [])):
        base = f"/stage/assets/{i}"
        sub = _Band(data, base, "stage")
        sub.struct(STRUCT_MARK_OF["asset"])
        sub.field()
        sub.name(asset["name"], f"{base}/name")
        sub.field()
        sub.glyph(_DISC[("asset", asset["kind"])], sub.at(f"{base}/kind"))
        sub.field()
        sub.string(asset["path"], f"{base}/path")
        cells += sub.cells
    return cells


def circle_ring(model: JinFileV2, ci: int, *, data: Any = None) -> list[InkCell]:
    """陣の銘環: 陣の核 → description → 記憶 → 道具 → on → guard → 委譲(glyph 設計書 §1.3)。"""
    data = _canonical(model) if data is None else data
    circle = data["circles"][ci]
    base = f"/circles/{ci}"
    head = _Band(data, base, "circle")
    head.struct(STRUCT_MARK_OF["circle"])
    head.field()
    head.name(circle["name"], f"{base}/name")
    if "core" in circle:
        head.field()
        head.name(circle["core"], f"{base}/core")
    elif "flow" in circle:
        flow = circle["flow"]
        head.field()
        head.glyph(_DISC[("flow", flow["kind"])], head.at(f"{base}/flow/kind"))
        head.field()
        head.listed(flow["steps"], f"{base}/flow/steps", lambda n, p: head.name(n, p))
        if "exit" in flow:
            head.field()
            head.expr(flow["exit"], f"{base}/flow/exit")
    cells = head.cells
    if "description" in circle:
        sub = _Band(data, base, "circle")
        sub.struct(STRUCT_MARK_OF["description"])
        sub.string(circle["description"], f"{base}/description")
        cells += sub.cells
    for j, state in enumerate(circle.get("state", [])):
        p = f"{base}/state/{j}"
        sub = _Band(data, p, "state")
        sub.struct(STRUCT_MARK_OF["state"])
        sub.field()
        sub.name(state["name"], f"{p}/name")
        sub.field()
        sub.type_(state["type"], f"{p}/type")
        sub.field()
        sub.expr(state["init"], f"{p}/init")
        if state.get("out"):  # 公開は判別の紋だけの欄(図の二重線は画素からは読めない大きさ)
            sub.field()
            sub.glyph(_DISC[("optional", "out")], sub.at(f"{p}/out"))
        cells += sub.cells
    for j, sigil in enumerate(circle.get("sigils", [])):
        p = f"{base}/sigils/{j}"
        sub = _Band(data, p, "sigil")
        sub.struct(STRUCT_MARK_OF["sigil"])
        sub.field()
        sub.name(sigil["name"], f"{p}/name")
        sub.field()
        sub.glyph(_DISC[("sigil", sigil["kind"])], sub.at(f"{p}/kind"))
        if sigil["kind"] == "host":
            sub.field()
            sub.name(sigil["host"], f"{p}/host")
        elif sigil["kind"] == "summon":
            sub.field()
            sub.name(sigil["circle"], f"{p}/circle")
            sub.field()
            sub.name(sigil["rite"], f"{p}/rite")
        else:
            sub.field()
            sub.string(sigil["file"], f"{p}/file")
        cells += sub.cells
    boundary = circle.get("boundary", {})
    for j, on in enumerate(boundary.get("on", [])):
        p = f"{base}/boundary/on/{j}"
        sub = _Band(data, p, "on")
        sub.struct(STRUCT_MARK_OF["on"])
        sub.field()
        sub.glyph(_DISC[("event", on["event"])], sub.at(f"{p}/event"))
        sub.field()
        sub.name(on["rite"], f"{p}/rite")
        cells += sub.cells
    for j, guard in enumerate(boundary.get("guards", [])):
        p = f"{base}/boundary/guards/{j}"
        sub = _Band(data, p, "guard")
        sub.struct(STRUCT_MARK_OF["guard"])
        sub.field()
        sub.expr(guard["assert"], f"{p}/assert")
        if "message" in guard:
            sub.field()
            sub.glyph(_DISC[("optional", "message")])
            sub.string(guard["message"], f"{p}/message")
        cells += sub.cells
    for j, name in enumerate(circle.get("delegate", [])):
        p = f"{base}/delegate/{j}"
        sub = _Band(data, p, "delegate")
        sub.struct(STRUCT_MARK_OF["delegate"])
        sub.field()
        sub.name(name, p)
        cells += sub.cells
    return cells


def rite_ring(model: JinFileV2, ci: int, ri: int, *, data: Any = None) -> list[InkCell]:
    """手順陣の銘環: 手順陣の核(名前・引数・戻り値)→ ステップを前順で(glyph 設計書 §1.3)。"""
    data = _canonical(model) if data is None else data
    rite = data["circles"][ci]["rites"][ri]
    base = f"/circles/{ci}/rites/{ri}"
    head = _Band(data, base, "rite")
    head.struct(STRUCT_MARK_OF["rite"])
    head.field()
    head.name(rite["name"], f"{base}/name")
    head.field()
    head.listed(
        rite.get("params", []),
        f"{base}/params",
        lambda prm, p: head.typed(prm["name"], prm["type"], p),
    )
    if "returns" in rite:
        head.field()
        head.type_(rite["returns"], f"{base}/returns")
    return head.cells + _steps_cells(data, rite["steps"], f"{base}/steps")


def _steps_cells(data: Any, steps: list[Any], prefix: str) -> list[InkCell]:
    """ステップの列を前順に。`if` は then → (else があれば s_else → else)→ s_end、`loop` は本文 → s_end
    (入れ子の境目を銘文に書く・S3・ユーザーの判断 B。s_end は本文が空でも書く)。"""
    cells: list[InkCell] = []
    for k, step in enumerate(steps):
        pointer = f"{prefix}/{k}"
        cells += _step_band(data, pointer, step)
        if step["do"] == "if":
            cells += _steps_cells(data, step["then"], f"{pointer}/then")
            if step.get("else"):
                mark = _Band(data, f"{pointer}/else", "step")
                mark.struct(STRUCT_MARK_OF["else"])
                cells += mark.cells + _steps_cells(data, step["else"], f"{pointer}/else")
        elif step["do"] == "loop":
            cells += _steps_cells(data, step["steps"], f"{pointer}/steps")
        if step["do"] in ("if", "loop"):
            end = _Band(data, pointer, "step")
            end.struct(STRUCT_MARK_OF["end"])
            cells += end.cells
    return cells


def _step_band(data: Any, p: str, step: Any) -> list[InkCell]:
    band = _Band(data, p, "step")
    band.struct(STRUCT_MARK_OF["step." + step["do"]])
    do = step["do"]
    if do == "set":
        band.field()
        band.expr(step["target"], f"{p}/target")
        band.field()
        band.expr(step["expr"], f"{p}/expr")
    elif do == "let":
        band.field()
        band.name(step["name"], f"{p}/name")
        if "type" in step:  # 欄が 3 つなら型あり(型紙名もラテンなので欄の数で見分ける)
            band.field()
            band.type_(step["type"], f"{p}/type")
        band.field()
        band.expr(step["expr"], f"{p}/expr")
    elif do == "cast":
        band.field()
        band.expr(step["target"], f"{p}/target")
        band.field()
        band.listed(step.get("args", []), f"{p}/args", lambda a, q: band.expr(a, q))
        if "into" in step:
            band.field()
            band.glyph(_DISC[("optional", "into")])
            band.expr(step["into"], f"{p}/into")
    elif do == "if":
        band.field()
        band.expr(step["cond"], f"{p}/cond")
    elif do == "loop":
        band.glyph(_DISC[("loop", step["kind"])], band.at(f"{p}/kind"))
        if step["kind"] == "each":
            band.field()
            band.name(step["name"], f"{p}/name")
            band.field()
            band.expr(step["in"], f"{p}/in")
        elif step["kind"] == "while":
            band.field()
            band.expr(step["cond"], f"{p}/cond")
        else:
            band.field()
            band.expr(step["times"], f"{p}/times")
            if "name" in step:
                band.field()
                band.glyph(_DISC[("optional", "name")])
                band.name(step["name"], f"{p}/name")
    elif do == "wait":
        key = "ticks" if "ticks" in step else "until"
        band.glyph(_DISC[("wait", key)])
        band.expr(step[key], f"{p}/{key}")
    elif do == "emit":
        band.field()
        band.name(step["circle"], f"{p}/circle")
        band.field()
        band.name(step["message"], f"{p}/message")
        band.field()
        band.listed(step.get("args", []), f"{p}/args", lambda a, q: band.expr(a, q))
    elif do == "return":
        if "expr" in step:
            band.field()
            band.expr(step["expr"], f"{p}/expr")
    elif do == "transfer":
        band.field()
        band.name(step["circle"], f"{p}/circle")
    return band.cells


__all__ = [
    "InkCell",
    "Inscription",
    "circle_ring",
    "expr_cells",
    "frame_band",
    "inscribe",
    "rite_ring",
    "to_expr",
]
