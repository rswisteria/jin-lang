"""構文解析器: 場面グラフ(`.jinscene.json`)→ モデル(陣書き S3・設計書 §3.5)。`jin_render.v2.inscribe` の逆。

1. 銘帯の升を構造の印で切り、銘帯の頭の印(`FIELD_ORDER` の鍵)ごとに欄(`sep`)・並び(括弧の深さ 0 の `comma`)・
   `名前 colon 型`・文字列(`quote_l` … `quote_r` と `esc`)・式(`to_expr`)に割る
2. 手順陣のステップの列を `s_else` / `s_end` で木に戻す
3. 陣の並び: 図形 `c0` が root、`c1`… が他の陣を `circles[]` の順に。額縁の 6 つ目の欄(root の添字)があれば root をそこへ差し込む
4. 組んだ JSON を `jin_core.check.check_text` に通す(schema と意味の検査)。その診断の pointer はモデルの中なので、
   欄ごとに覚えた対応表で場面グラフの pointer(`/bands/3/cells/2`)に写す

診断は `.jinscene.json` に対して出す(diagnostics.md §5)。絵の文法の誤り(JIN301〜305)が 1 つでもあればモデルは組まない
(`check_text` も呼ばない。fixture が対応コードをちょうど 1 つだけ出す規律)。JIN306(迷いを第一候補で解いた)は warning。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from jin_core.check import check_text
from jin_core.diagnostics import Diagnostic, Position, Range, severity_of
from jin_core.parser import JinSyntaxError, PointerTable, parse_text
from jin_core.pointer import loc_to_pointer
from jin_core.schema_export import SCHEMA_ID_V2
from jin_core.v2.expr import canonical_expr
from jin_core.v2.glyph import (
    ESCAPE_LETTERS,
    EXPR_TOKEN_OF,
    GLYPHS,
    LOOP_FIELDS,
    START_MARK,
    STRUCT_MARKS,
)
from jin_core.v2.model import JinFileV2
from jin_render.v2.inscribe import to_expr
from pydantic import ValidationError

from jin_glyph.scene import JinScene

_OWNER_OF = {m.id: m.owner for m in STRUCT_MARKS}
_DISC = {g.id: (g.slot, g.token) for g in GLYPHS if g.layer == "disc"}
_SLOT_GLYPHS: dict[str, list[str]] = {}
for _g in GLYPHS:
    if _g.layer == "disc" and _g.slot is not None:
        _SLOT_GLYPHS.setdefault(_g.slot, []).append(_g.id)
_TYPE_OF_GLYPH = {"t_num": "num", "t_bool": "bool", "t_str": "str"}
_OPEN = frozenset({"paren_l", "brack_l", "brace_l", "t_list_l"})
_CLOSE = frozenset({"paren_r", "brack_r", "brace_r", "t_list_r"})
_UNESCAPE = frozenset(ESCAPE_LETTERS.values())
_HEX = frozenset("0123456789abcdefABCDEF")
#: 文字列の中でラテンの升に生のまま置けない字(銘文は esc で書く。生のままだと to_expr が組む JSON が壊れる・最終レビュー #1)
_NEEDS_ESCAPE = frozenset(ESCAPE_LETTERS) | {chr(c) for c in range(0x20)}
#: 額縁の数の欄の桁数の上限(stage の値の上限より十分大きく、int() の桁数の上限より十分小さい)
_MAX_DIGITS = 12
#: 型の list の入れ子の上限(手書きの場面グラフで再帰が溢れないように)
_MAX_LIST_DEPTH = 32
#: 陣の銘環・手順陣の銘環・額縁の銘帯に現れてよい銘帯の頭(先頭の 1 本は別に決まっている)
_CIRCLE_PARTS = frozenset({"description", "state", "sigil", "on", "guard", "delegate"})
_FRAME_PARTS = frozenset({"form", "asset"})
_CIRCLE_ID = re.compile(r"c(0|[1-9][0-9]*)")
_RITE_ID = re.compile(r"r(0|[1-9][0-9]*)_(0|[1-9][0-9]*)")
_NO_RANGE = Range(Position(1, 1), Position(1, 1))
_DISC_HINT = "判別の紋は決まった枠(loop / wait / sigil / asset / flow / event の種別の欄と、省略できる欄の頭)にだけ置ける"


@dataclass(frozen=True)
class _C:
    """升 1 つと、場面グラフの中の pointer(`/bands/<b>/cells/<c>`)。`to_expr` が読む `t` / `v` を持つ。"""

    t: str
    v: str
    at: str


Run = list[_C]


class _Bad(Exception):
    def __init__(self, code: str, at: str, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.code, self.at, self.message, self.hint = code, at, message, hint


@dataclass
class _Segment:
    """銘帯の頭の印 1 つと、次の頭の印までの升。"""

    owner: str  # FIELD_ORDER の鍵
    at: str  # 頭の印の升の pointer
    cells: Run


@dataclass
class _Builder:
    problems: list[_Bad] = field(default_factory=list)
    origin: dict[str, str] = field(default_factory=dict)  # モデルの pointer → 場面グラフの pointer

    def note(self, model_pointer: str, at: str) -> None:
        self.origin.setdefault(model_pointer, at)


# ---- 升の列の道具 -------------------------------------------------------------------------------


def _is(cell: _C, gid: str) -> bool:
    return cell.t == "glyph" and cell.v == gid


def _split(cells: Run, gid: str) -> list[Run]:
    """文字列の外・括弧の深さ 0 の gid で切る。"""
    parts: list[Run] = [[]]
    depth = 0
    in_string = escaped = False
    for cell in cells:
        if in_string:
            parts[-1].append(cell)
            if escaped:
                escaped = False
            elif _is(cell, "esc"):
                escaped = True
            elif _is(cell, "quote_r"):
                in_string = False
            continue
        if cell.t == "glyph":
            if cell.v == "quote_l":
                in_string = True
            elif cell.v in _OPEN:
                depth += 1
            elif cell.v in _CLOSE:
                depth -= 1
            elif cell.v == gid and depth == 0:
                parts.append([])
                continue
        parts[-1].append(cell)
    return parts


def _fields(segment: _Segment) -> list[Run]:
    return _split(segment.cells, "sep") if segment.cells else []


def _items(run: Run) -> list[Run]:
    return _split(run, "comma") if run else []


def _need(fields: list[Run], counts: tuple[int, ...], segment: _Segment) -> None:
    if len(fields) not in counts:
        want = " か ".join(str(n) for n in counts)
        raise _Bad(
            "JIN302",
            segment.at,
            f"{segment.owner} の銘帯の欄が {len(fields)} 個です({want} 個のはず)",
            "欄の区切りの紋(sep)の数を確かめてください",
        )


def _first(run: Run, segment: _Segment) -> str:
    return run[0].at if run else segment.at


def _plain(run: Run, what: str, segment: _Segment) -> None:
    """名前の欄に紋が無いこと(判別の紋なら JIN303)。"""
    if not run:
        raise _Bad("JIN302", segment.at, f"{segment.owner} の銘帯の {what} が空です")
    for cell in run:
        if cell.t == "glyph" and cell.v in _DISC:
            raise _Bad("JIN303", cell.at, f"判別の紋 {cell.v} が {what} の中にあります", _DISC_HINT)
        if cell.t != "latin":
            raise _Bad("JIN302", cell.at, f"{what} はラテンの字だけで書きます({cell.v} があります)")


def _name(run: Run, segment: _Segment, what: str = "名前") -> str:
    _plain(run, what, segment)
    return "".join(c.v for c in run)


def _int(run: Run, segment: _Segment, what: str) -> int:
    text = _name(run, segment, what)
    if not (text.isascii() and text.isdigit()) or len(text) > _MAX_DIGITS:
        raise _Bad(
            "JIN302",
            run[0].at,
            f"{what} が数ではありません(0 以上の整数・{_MAX_DIGITS} 桁まで): {text[:20]!r}",
        )
    return int(text)


def _string(run: Run, segment: _Segment, what: str) -> str:
    if len(run) < 2 or not _is(run[0], "quote_l") or not _is(run[-1], "quote_r"):
        raise _Bad("JIN302", _first(run, segment), f"{what} は quote_l … quote_r で括ります")
    _check_string_body(run[1:-1])
    return json.loads(to_expr(run))


def _check_string_body(body: Run) -> None:
    k = 0
    while k < len(body):
        cell = body[k]
        if _is(cell, "esc"):
            letter = body[k + 1] if k + 1 < len(body) else None
            if (
                letter is None
                or letter.t != "latin"
                or (letter.v not in _UNESCAPE and letter.v != "u")
            ):
                raise _Bad("JIN302", cell.at, "esc の後の字が読めません")
            if letter.v == "u":
                digits = body[k + 2 : k + 6]
                if len(digits) != 4 or any(d.t != "latin" or d.v not in _HEX for d in digits):
                    raise _Bad("JIN302", cell.at, "esc u の後は 16 進 4 桁です")
                k += 6
                continue
            k += 2
            continue
        if cell.t != "latin":
            raise _Bad("JIN302", cell.at, f"文字列の中に紋 {cell.v} があります")
        _check_raw(cell)
        k += 1


def _check_raw(cell: _C) -> None:
    if cell.v in _NEEDS_ESCAPE:
        raise _Bad(
            "JIN302",
            cell.at,
            f"文字列の中の {cell.v!r} は esc で書きます",
            "表は glyph.md §3(空白は esc s)",
        )


def _expr(run: Run, segment: _Segment, what: str) -> str:
    if not run:
        raise _Bad("JIN302", segment.at, f"{segment.owner} の銘帯の {what} が空です")
    in_string = escaped = False
    for k, cell in enumerate(run):
        if in_string:
            if escaped:
                escaped = False
            elif _is(cell, "esc"):
                escaped = True
                nxt = run[k + 1] if k + 1 < len(run) else None
                if nxt is None or nxt.t != "latin" or (nxt.v not in _UNESCAPE and nxt.v != "u"):
                    raise _Bad("JIN302", cell.at, "esc の後の字が読めません")
            elif _is(cell, "quote_r"):
                in_string = False
            elif cell.t != "latin":
                raise _Bad("JIN302", cell.at, f"文字列の中に紋 {cell.v} があります")
            else:
                _check_raw(cell)
            continue
        if cell.t == "glyph":
            if cell.v in _DISC:
                raise _Bad("JIN303", cell.at, f"判別の紋 {cell.v} が式の中にあります", _DISC_HINT)
            if cell.v == "quote_l":
                in_string = True
            elif cell.v not in EXPR_TOKEN_OF:
                raise _Bad("JIN302", cell.at, f"紋 {cell.v} は式に現れません")
    return canonical_expr(
        to_expr(run)
    )  # 字句の間の空白を正準に(cast の target は名前の形でないと check が通らない)


def _type(run: Run, segment: _Segment) -> str:
    depth = 0
    # 再帰せずに剥く(手書きの深い入れ子で RecursionError にしない)
    while len(run) >= 3 and _is(run[0], "t_list_l") and _is(run[-1], "t_list_r"):
        run, depth = run[1:-1], depth + 1
        if depth > _MAX_LIST_DEPTH:
            raise _Bad("JIN302", run[0].at, f"list の入れ子が深すぎます({_MAX_LIST_DEPTH} 段まで)")
    if len(run) == 1 and run[0].t == "glyph" and run[0].v in _TYPE_OF_GLYPH:
        inner = _TYPE_OF_GLYPH[run[0].v]
    else:
        inner = _name(run, segment, "型")
    return "list<" * depth + inner + ">" * depth


def _typed(run: Run, segment: _Segment) -> tuple[str, str]:
    for k, cell in enumerate(run):
        if _is(cell, "colon"):
            return _name(run[:k], segment), _type(run[k + 1 :], segment)
    raise _Bad("JIN302", _first(run, segment), "名前 colon 型 の colon がありません")


def _disc(run: Run, slot: str, segment: _Segment) -> str:
    if not run:
        raise _Bad("JIN302", segment.at, f"{segment.owner} の銘帯の {slot} の紋の欄が空です")
    cell = run[0]
    if len(run) == 1 and cell.t == "glyph" and _DISC.get(cell.v, (None, None))[0] == slot:
        return _DISC[cell.v][1]
    raise _Bad(
        "JIN303",
        cell.at,
        f"{slot} の枠に置けない升です({cell.v})",
        "置ける紋: " + " / ".join(_SLOT_GLYPHS[slot]),
    )


def _marked(run: Run, token: str, segment: _Segment) -> Run:
    """省略できる欄: 判別の紋(枠 optional の token)を頭に置いた欄の残り。"""
    if run and run[0].t == "glyph" and _DISC.get(run[0].v) == ("optional", token):
        return run[1:]
    raise _Bad(
        "JIN303",
        _first(run, segment),
        f"{segment.owner} の銘帯のこの欄は {token} の印の紋で始まります",
        "置ける紋: " + " / ".join(g for g in _SLOT_GLYPHS["optional"] if _DISC[g][1] == token),
    )


def _segments(cells: Run, where: str) -> tuple[Run, list[_Segment]]:
    """(最初の頭の印より前の升, 頭の印ごとの切れ目)。"""
    lead: Run = []
    segments: list[_Segment] = []
    for cell in cells:
        if cell.t == "struct":
            if cell.v == START_MARK:
                raise _Bad("JIN302", cell.at, f"始まりの印が{where}の途中にあります")
            segments.append(_Segment(_OWNER_OF[cell.v], cell.at, []))
        elif segments:
            segments[-1].cells.append(cell)
        else:
            lead.append(cell)
    return lead, segments


# ---- 銘帯ごとの読み手 ---------------------------------------------------------------------------


def _frame(cells: Run, b: _Builder) -> tuple[dict[str, Any], int | None]:
    """(文書の骨組み, root の添字)。"""
    lead, segments = _segments(cells, "額縁の銘帯")
    head = _Segment("frame", lead[0].at if lead else "/bands", lead)
    fields = _fields(head)
    doc: dict[str, Any] = {"$schema": SCHEMA_ID_V2, "version": 2}
    if fields and fields[0] and _is(fields[0][0], "quote_l"):
        doc["$schema"] = _string(fields[0], head, "$schema")
        b.note("/$schema", fields[0][0].at)
        fields = fields[1:]
    _need(fields, (4, 5), head)
    stage: dict[str, Any] = {}
    for key, run in zip(("width", "height", "fps", "seed"), fields, strict=False):
        stage[key] = _int(run, head, key)
        b.note(f"/stage/{key}", run[0].at)
    root = None
    if len(fields) == 5:
        root = _int(fields[4], head, "root の添字")
        b.note("/root", fields[4][0].at)
    forms: list[dict[str, Any]] = []
    assets: list[dict[str, Any]] = []
    for seg in segments:
        if seg.owner not in _FRAME_PARTS:
            raise _Bad("JIN302", seg.at, f"額縁の銘帯に {seg.owner} の銘帯は置けません")
        f = _fields(seg)
        if seg.owner == "form":
            _need(f, (2,), seg)
            p = f"/forms/{len(forms)}"
            b.note(p, seg.at)
            items = []
            for k, item in enumerate(_items(f[1])):
                name, type_ = _typed(item, seg)
                items.append({"name": name, "type": type_})
                b.note(f"{p}/fields/{k}", item[0].at if item else seg.at)
            forms.append({"name": _name(f[0], seg), "fields": items})
        else:
            _need(f, (3,), seg)
            p = f"/stage/assets/{len(assets)}"
            b.note(p, seg.at)
            assets.append(
                {
                    "name": _name(f[0], seg),
                    "kind": _disc(f[1], "asset", seg),
                    "path": _string(f[2], seg, "path"),
                }
            )
    stage["assets"] = assets
    doc["stage"] = stage
    doc["forms"] = forms
    return doc, root


def _circle(cells: Run, base: str, b: _Builder) -> dict[str, Any]:
    lead, segments = _segments(cells, "陣の銘環")
    if lead or not segments or segments[0].owner != "circle":
        at = lead[0].at if lead else (segments[0].at if segments else base)
        raise _Bad("JIN302", at, "陣の銘環は陣の核の印(s_circle)で始まります")
    head = segments[0]
    b.note(base, head.at)
    fields = _fields(head)
    _need(fields, (1, 2, 3, 4), head)
    circle: dict[str, Any] = {"name": _name(fields[0], head)}
    b.note(f"{base}/name", fields[0][0].at)
    if len(fields) >= 2 and len(fields[1]) == 1 and fields[1][0].v in _DISC:
        _need(fields, (3, 4), head)
        flow: dict[str, Any] = {"kind": _disc(fields[1], "flow", head)}
        flow["steps"] = [_name(item, head) for item in _items(fields[2])]
        if len(fields) == 4:
            flow["exit"] = _expr(fields[3], head, "exit")
            b.note(f"{base}/flow/exit", fields[3][0].at)
        circle["flow"] = flow
        b.note(f"{base}/flow", fields[1][0].at)
    elif len(fields) >= 2:
        _need(fields, (2,), head)
        circle["core"] = _name(fields[1], head)
        b.note(f"{base}/core", fields[1][0].at)
    state: list[dict[str, Any]] = []
    sigils: list[dict[str, Any]] = []
    ons: list[dict[str, Any]] = []
    guards: list[dict[str, Any]] = []
    delegate: list[str] = []
    for seg in segments[1:]:
        if seg.owner not in _CIRCLE_PARTS:
            raise _Bad("JIN302", seg.at, f"陣の銘環に {seg.owner} の銘帯は置けません")
        f = _fields(seg)
        if seg.owner == "description":
            circle["description"] = _string(seg.cells, seg, "description")
            b.note(f"{base}/description", seg.at)
        elif seg.owner == "state":
            _need(f, (3, 4), seg)
            p = f"{base}/state/{len(state)}"
            b.note(p, seg.at)
            item = {
                "name": _name(f[0], seg),
                "type": _type(f[1], seg),
                "init": _expr(f[2], seg, "init"),
            }
            b.note(f"{p}/init", f[2][0].at)
            if len(f) == 4:
                if _marked(f[3], "out", seg):
                    raise _Bad("JIN302", f[3][1].at, "公開の印の後に升があります")
                item["out"] = True
            state.append(item)
        elif seg.owner == "sigil":
            _need(f, (3, 4), seg)
            b.note(f"{base}/sigils/{len(sigils)}", seg.at)
            kind = _disc(f[1], "sigil", seg)
            sigil: dict[str, Any] = {"name": _name(f[0], seg), "kind": kind}
            if kind == "summon":
                _need(f, (4,), seg)
                sigil["circle"], sigil["rite"] = _name(f[2], seg), _name(f[3], seg)
            else:
                _need(f, (3,), seg)
                if kind == "host":
                    sigil["host"] = _name(f[2], seg)
                else:
                    sigil["file"] = _string(f[2], seg, "file")
            sigils.append(sigil)
        elif seg.owner == "on":
            _need(f, (2,), seg)
            b.note(f"{base}/boundary/on/{len(ons)}", seg.at)
            ons.append({"event": _disc(f[0], "event", seg), "rite": _name(f[1], seg)})
        elif seg.owner == "guard":
            _need(f, (1, 2), seg)
            p = f"{base}/boundary/guards/{len(guards)}"
            b.note(p, seg.at)
            guard = {"assert": _expr(f[0], seg, "assert")}
            b.note(f"{p}/assert", f[0][0].at)
            if len(f) == 2:
                guard["message"] = _string(_marked(f[1], "message", seg), seg, "message")
            guards.append(guard)
        else:
            _need(f, (1,), seg)
            b.note(f"{base}/delegate/{len(delegate)}", seg.at)
            delegate.append(_name(f[0], seg))
    circle.update(state=state, sigils=sigils, rites=[], delegate=delegate)
    if ons or guards:
        circle["boundary"] = {"on": ons, "guards": guards}
    return circle


def _rite(cells: Run, base: str, b: _Builder) -> dict[str, Any]:
    lead, segments = _segments(cells, "手順陣の銘環")
    if lead or not segments or segments[0].owner != "rite":
        at = lead[0].at if lead else (segments[0].at if segments else base)
        raise _Bad("JIN302", at, "手順陣の銘環は手順陣の核の印(s_rite)で始まります")
    head = segments[0]
    b.note(base, head.at)
    fields = _fields(head)
    _need(fields, (2, 3), head)
    params = []
    for k, item in enumerate(_items(fields[1])):
        name, type_ = _typed(item, head)
        params.append({"name": name, "type": type_})
        b.note(f"{base}/params/{k}", item[0].at if item else head.at)
    rite: dict[str, Any] = {"name": _name(fields[0], head), "params": params}
    if len(fields) == 3:
        rite["returns"] = _type(fields[2], head)
    rite["steps"] = _steps(segments[1:], f"{base}/steps", b)
    return rite


def _steps(segments: list[_Segment], prefix: str, b: _Builder) -> list[dict[str, Any]]:
    """ステップの銘帯の列を `s_else` / `s_end` で木に戻す。"""
    top: list[dict[str, Any]] = []
    # (開いている if / loop のステップ, その pointer, いま積んでいる枝の名前, 頭の印の pointer)
    stack: list[tuple[dict[str, Any], str, str, str]] = []
    current, current_prefix = top, prefix
    for seg in segments:
        if seg.owner == "else":
            if seg.cells:
                raise _Bad("JIN302", seg.cells[0].at, "s_else の印に欄はありません")
            if not stack or stack[-1][0]["do"] != "if" or stack[-1][2] != "then":
                raise _Bad("JIN302", seg.at, "s_else の印が if の then の後にありません")
            step, pointer, _, at = stack[-1]
            stack[-1] = (step, pointer, "else", at)
            current, current_prefix = step["else"], f"{pointer}/else"
            b.note(current_prefix, seg.at)
            continue
        if seg.owner == "end":
            if seg.cells:
                raise _Bad("JIN302", seg.cells[0].at, "s_end の印に欄はありません")
            if not stack:
                raise _Bad("JIN302", seg.at, "閉じる if / loop の無い s_end の印です(余り)")
            stack.pop()
            if stack:
                step, pointer, branch, _ = stack[-1]
                current = step[branch]
                current_prefix = f"{pointer}/{branch}"
            else:
                current, current_prefix = top, prefix
            continue
        if not seg.owner.startswith("step."):
            raise _Bad("JIN302", seg.at, f"手順陣の銘環に {seg.owner} の銘帯は置けません")
        pointer = f"{current_prefix}/{len(current)}"
        b.note(pointer, seg.at)
        step = _step(seg, pointer, b)
        current.append(step)
        if step["do"] == "if":
            stack.append((step, pointer, "then", seg.at))
            current, current_prefix = step["then"], f"{pointer}/then"
        elif step["do"] == "loop":
            stack.append((step, pointer, "steps", seg.at))
            current, current_prefix = step["steps"], f"{pointer}/steps"
    if stack:
        raise _Bad(
            "JIN302",
            stack[-1][3],
            f"{stack[-1][0]['do']} のブロックを閉じる s_end の印がありません(欠け)",
            "if / loop のブロックの終わりに s_end の印を書く(本文が空でも書く)",
        )
    return top


def _step(seg: _Segment, p: str, b: _Builder) -> dict[str, Any]:
    do = seg.owner.removeprefix("step.")
    step: dict[str, Any] = {"do": do}

    def expr(run: Run, key: str) -> None:
        step[key] = _expr(run, seg, key)
        b.note(f"{p}/{key}", run[0].at)

    def exprs(run: Run, key: str) -> None:
        step[key] = []
        for k, item in enumerate(_items(run)):
            step[key].append(_expr(item, seg, key))
            b.note(f"{p}/{key}/{k}", item[0].at if item else seg.at)

    if do in ("break", "finish"):
        if seg.cells:
            raise _Bad("JIN302", seg.cells[0].at, f"{do} の銘帯に欄はありません")
        return step
    if do == "loop":
        if not seg.cells:
            raise _Bad("JIN302", seg.at, "loop の銘帯に種別の紋がありません")
        kind = _disc(seg.cells[:1], "loop", seg)
        step["kind"] = kind
        f = _split(seg.cells[1:], "sep") if len(seg.cells) > 1 else []
        names = LOOP_FIELDS[kind]
        optional = 1 if kind == "count" else 0
        _need(f, tuple(range(len(names) - optional, len(names) + 1)), seg)
        for key, run in zip(names, f, strict=False):
            if key == "name" and kind == "count":
                step["name"] = _name(_marked(run, "name", seg), seg)
            elif key == "name":
                step["name"] = _name(run, seg)
            else:
                expr(run, key)
        step["steps"] = []
        return step
    if do == "wait":
        if not seg.cells:
            raise _Bad("JIN302", seg.at, "wait の銘帯に ticks / until の紋がありません")
        key = _disc(seg.cells[:1], "wait", seg)
        expr(seg.cells[1:], key)
        return step
    f = _fields(seg)
    if do == "set":
        _need(f, (2,), seg)
        expr(f[0], "target")
        expr(f[1], "expr")
    elif do == "let":
        _need(f, (2, 3), seg)
        step["name"] = _name(f[0], seg)
        if len(f) == 3:
            step["type"] = _type(f[1], seg)
        expr(f[-1], "expr")
    elif do == "cast":
        _need(f, (2, 3), seg)
        expr(f[0], "target")
        exprs(f[1], "args")
        if len(f) == 3:
            expr(_marked(f[2], "into", seg), "into")
    elif do == "if":
        _need(f, (1,), seg)
        expr(f[0], "cond")
        step["then"], step["else"] = [], []
    elif do == "emit":
        _need(f, (3,), seg)
        step["circle"], step["message"] = _name(f[0], seg), _name(f[1], seg)
        exprs(f[2], "args")
    elif do == "return":
        _need(f, (0, 1), seg)
        if f:
            expr(f[0], "expr")
    else:  # transfer
        _need(f, (1,), seg)
        step["circle"] = _name(f[0], seg)
    return step


# ---- 全体 ---------------------------------------------------------------------------------------


def _assemble(scene: JinScene, b: _Builder) -> dict[str, Any] | None:
    figure_ids = {f.id for f in scene.figures}
    runs: dict[str, Run] = {}
    first_band: dict[str, str] = {}
    for bi, band in enumerate(scene.bands):
        if band.owner not in figure_ids:
            b.problems.append(
                _Bad(
                    "JIN305",
                    f"/bands/{bi}/owner",
                    f"銘帯の持ち主 {band.owner!r} が図形にありません",
                    "図形の id: " + " / ".join(sorted(figure_ids)),
                )
            )
            continue
        first_band.setdefault(band.owner, f"/bands/{bi}")
        runs.setdefault(band.owner, []).extend(
            _C(c.t, c.v, f"/bands/{bi}/cells/{ci}") for ci, c in enumerate(band.cells)
        )
    circles: dict[int, str] = {}
    rites: dict[tuple[int, int], str] = {}
    for fi, figure in enumerate(scene.figures):
        if figure.id == "frame":
            continue
        if m := _CIRCLE_ID.fullmatch(figure.id):
            circles[int(m.group(1))] = figure.id
        elif m := _RITE_ID.fullmatch(figure.id):
            rites[(int(m.group(1)), int(m.group(2)))] = figure.id
        else:
            b.problems.append(
                _Bad(
                    "JIN305",
                    f"/figures/{fi}/id",
                    f"図形 {figure.id!r} はどの陣・環にも帰属しません",
                )
            )
    for (k, j), fid in rites.items():
        if k not in circles:
            at = f"/figures/{[f.id for f in scene.figures].index(fid)}/id"
            b.problems.append(_Bad("JIN305", at, f"手順陣 {fid!r} の陣 c{k} がありません"))
    if b.problems:
        return None

    def ring(fid: str) -> Run:
        """銘環の升(始まりの印と継ぎの紋を除く)。"""
        cells = runs.get(fid, [])
        if not cells or not (cells[0].t == "struct" and cells[0].v == START_MARK):
            at = cells[0].at if cells else first_band.get(fid, "/figures")
            raise _Bad(
                "JIN301",
                at,
                f"環 {fid!r} の先頭に始まりの印がありません",
                "環の 12 時に始まりの印を描く",
            )
        if _is(cells[-1], "cont"):
            raise _Bad(
                "JIN304",
                cells[-1].at,
                f"環 {fid!r} の継ぎの紋の先に銘環がありません",
                "継ぎの紋は周の最後の升に置き、続きを 1 つ外の周の始まりから書く",
            )
        return [c for c in cells[1:] if not _is(c, "cont")]

    try:
        doc, root_index = _frame(runs.get("frame", []), b)
    except _Bad as bad:
        b.problems.append(bad)
        return None
    order = sorted(circles)
    if order != list(range(len(order))) or not order:
        b.problems.append(_Bad("JIN302", "/figures", "陣の図形 c0, c1, … が揃っていません"))
        return None
    root = 0 if root_index is None else root_index
    if root >= len(order):
        b.problems.append(_Bad("JIN302", b.origin["/root"], f"root の添字 {root} に陣がありません"))
        return None
    # c0 は root、c1… は他の陣を circles[] の順に(root を添字の位置へ差し込む)
    model_index = {0: root} | {k: k - 1 if k - 1 < root else k for k in order[1:]}
    circle_docs: list[dict[str, Any] | None] = [None] * len(order)
    for k in order:
        ci = model_index[k]
        try:
            circle = _circle(ring(circles[k]), f"/circles/{ci}", b)
            rite_keys = sorted(j for (kk, j) in rites if kk == k)
            if rite_keys != list(range(len(rite_keys))):
                raise _Bad(
                    "JIN302", "/figures", f"陣 c{k} の手順陣 r{k}_0, r{k}_1, … が揃っていません"
                )
            circle["rites"] = [
                _rite(ring(rites[(k, j)]), f"/circles/{ci}/rites/{j}", b) for j in rite_keys
            ]
            circle_docs[ci] = circle
        except _Bad as bad:
            b.problems.append(bad)
    if b.problems:
        return None
    doc["root"] = circle_docs[root]["name"]  # type: ignore[index]
    doc["circles"] = circle_docs
    return doc


def _range(table: PointerTable | None, pointer: str) -> Range:
    return table.resolve(pointer) if table is not None else _NO_RANGE


def _scene_pointer(origin: dict[str, str], model_pointer: str) -> str:
    current = model_pointer
    while current:
        if current in origin:
            return origin[current]
        current = current.rsplit("/", 1)[0]
    return ""


def parse_scene(
    scene: JinScene, *, file: str, table: PointerTable | None = None
) -> tuple[JinFileV2 | None, list[Diagnostic]]:
    """場面グラフからモデルを組む。診断は `file`(`.jinscene.json`)に対して。`table` があれば range をそこから引く。"""

    def diag(code: str, pointer: str, message: str, hint: str | None = None) -> Diagnostic:
        return Diagnostic(
            file, pointer, _range(table, pointer), code, severity_of(code), message, hint
        )

    diagnostics: list[Diagnostic] = []
    for bi, band in enumerate(scene.bands):
        for ci, cell in enumerate(band.cells):
            if cell.unsure:
                diagnostics.append(
                    diag(
                        "JIN306",
                        f"/bands/{bi}/cells/{ci}",
                        f"迷いを第一候補 {cell.v} で解きました",
                        "他の候補: " + " / ".join(cell.unsure),
                    )
                )
    b = _Builder()
    doc = _assemble(scene, b)
    if doc is None:
        diagnostics += [diag(p.code, p.at, p.message, p.hint) for p in b.problems]
        return None, diagnostics
    result = check_text(json.dumps(doc, ensure_ascii=False, indent=2), file)
    for d in result.diagnostics:
        diagnostics.append(diag(d.code, _scene_pointer(b.origin, d.pointer), d.message, d.hint))
    model = result.model if isinstance(result.model, JinFileV2) else None
    return model, diagnostics


def parse_scene_text(text: str, *, file: str) -> tuple[JinFileV2 | None, list[Diagnostic]]:
    """`.jinscene.json` のテキストから。JSON の誤りは JIN001、場面グラフの schema の誤りは JIN002。"""
    try:
        parsed = parse_text(text)
    except JinSyntaxError as exc:
        return None, [
            Diagnostic(file, "", exc.range, "JIN001", severity_of("JIN001"), exc.message, exc.hint)
        ]
    try:
        scene = JinScene.model_validate(parsed.value)
    except ValidationError as exc:
        out = []
        for error in exc.errors():
            pointer = loc_to_pointer(parsed.value, tuple(error["loc"]))
            out.append(
                Diagnostic(
                    file,
                    pointer,
                    parsed.table.resolve(pointer),
                    "JIN002",
                    severity_of("JIN002"),
                    error["msg"],
                )
            )
        return None, out
    return parse_scene(scene, file=file, table=parsed.table)


__all__ = ["parse_scene", "parse_scene_text"]
