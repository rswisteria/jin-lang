"""陣書き(画像を `.jin` の 2 つ目の直列化にする)の紋の語彙と銘帯の欄の順。

正典は `docs/spec/v2/glyph.md`(上位設計は `docs/superpowers/specs/2026-10-03-jin-glyph-design.md`)。
純データで、レンダラ(`jin_render`)が銘帯を描くときと、読み取り(`jin_glyph`)が銘帯を欄に割るときの
**両方**がここを読む(`jin_render` は `jin_glyph` を import できない・層の契約)。字形のパスはここに置かない。

- 式紋(`layer == "expr"`)は銘帯のどこにでも現れる。`EXPR_TOKEN_OF` は式の字句に写るものだけ
- 判別の紋(`layer == "disc"`)は決まった枠(`slot`)にだけ現れ、`token` はその枠の値(モデルの Literal など)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Glyph:
    id: str
    layer: Literal["expr", "disc"]
    token: str
    slot: str | None


def _expr(gid: str, token: str) -> Glyph:
    return Glyph(gid, "expr", token, None)


def _disc(gid: str, slot: str, token: str) -> Glyph:
    return Glyph(gid, "disc", token, slot)


#: spec §1.1 の表の順(= glyph.md の紋の表の順)。式紋 37 字・判別の紋 22 字。
GLYPHS: tuple[Glyph, ...] = (
    _expr("add", "+"),
    _expr("sub", "-"),
    _expr("mul", "*"),
    _expr("div", "/"),
    _expr("mod", "%"),
    _expr("cat", "++"),
    _expr("eq", "=="),
    _expr("ne", "!="),
    _expr("lt", "<"),
    _expr("le", "<="),
    _expr("gt", ">"),
    _expr("ge", ">="),
    _expr("and", "and"),
    _expr("or", "or"),
    _expr("not", "not"),
    _expr("paren_l", "("),
    _expr("paren_r", ")"),
    _expr("brack_l", "["),
    _expr("brack_r", "]"),
    _expr("brace_l", "{"),
    _expr("brace_r", "}"),
    _expr("comma", ","),
    _expr("colon", ":"),
    _expr("dot", "."),
    _expr("quote_l", '"'),
    _expr("quote_r", '"'),
    _expr("esc", "\\"),
    _expr("divider", "<space>"),
    _expr("true", "true"),
    _expr("false", "false"),
    _expr("t_num", "num"),
    _expr("t_bool", "bool"),
    _expr("t_str", "str"),
    _expr("t_list_l", "list<"),
    _expr("t_list_r", ">"),
    _expr("sep", "<sep>"),
    _expr("cont", "<cont>"),
    _disc("loop_each", "loop", "each"),
    _disc("loop_while", "loop", "while"),
    _disc("loop_count", "loop", "count"),
    _disc("wait_ticks", "wait", "ticks"),
    _disc("wait_until", "wait", "until"),
    _disc("sigil_host", "sigil", "host"),
    _disc("sigil_summon", "sigil", "summon"),
    _disc("sigil_agent", "sigil", "agent"),
    _disc("asset_sprite", "asset", "sprite"),
    _disc("asset_sound", "asset", "sound"),
    _disc("flow_sequence", "flow", "sequence"),
    _disc("flow_parallel", "flow", "parallel"),
    _disc("flow_loop", "flow", "loop"),
    _disc("event_tick", "event", "tick"),
    _disc("event_key", "event", "key"),
    _disc("event_pointer", "event", "pointer"),
    _disc("event_message", "event", "message"),
    _disc("event_exit", "event", "exit"),
    _disc("mark_into", "optional", "into"),
    _disc("mark_name", "optional", "name"),
    _disc("mark_message", "optional", "message"),
    _disc("mark_out", "optional", "out"),
)

GLYPH_IDS: frozenset[str] = frozenset(g.id for g in GLYPHS)

#: 式の字句に写る式紋だけ(文字列の括り・エスケープ・型・欄の区切り・継ぎは式の字句ではない)。
_NOT_EXPR_TOKENS = frozenset(
    {
        "quote_l",
        "quote_r",
        "esc",
        "divider",
        "t_num",
        "t_bool",
        "t_str",
        "t_list_l",
        "t_list_r",
        "sep",
        "cont",
    }
)
EXPR_TOKEN_OF: dict[str, str] = {
    g.id: g.token for g in GLYPHS if g.layer == "expr" and g.id not in _NOT_EXPR_TOKENS
}

#: 文字列の中で升に描けない文字 → `esc` の後に書くラテン文字(1 対 1)。式の文字列リテラルの JSON エスケープ
#: (expr.md §1)と同じ。**空白**は空の升と見分けられないので、エスケープではなく語の区切りの紋 `divider` 1 升で書く
#: (`DIVIDER`・glyph.md §3)。これ以外の制御文字は
#: `esc` + `u` + 16 進 4 桁で書く(`u` は予約)。視覚層だけの規則で、読み取りは ASCII の式に写すときに戻す。
ESCAPE_LETTERS: dict[str, str] = {
    '"': '"',
    "\\": "\\",
    "\b": "b",
    "\f": "f",
    "\n": "n",
    "\r": "r",
    "\t": "t",
}

#: 文字列の中の空白を書く紋(碑文の語の区切り)。空白の升は空の升と見分けられないため(Issue #129)。
DIVIDER = "divider"

#: 各環の 12 時に置く「始まりの印」。構造紋なので `GLYPHS` には入れない(spec §1.4)。
START_MARK = "start"

#: 図形の種類 → 銘帯の欄の並び(spec §1.3)。並びは「現れる欄をこの順に書く」の意味で、
#: 種別ごとに現れる欄が違うもの(sigil・wait・陣の核)は現れない欄を飛ばす。省略できる欄の見分けは
#: 判別の紋(`slot == "optional"` / `"wait"`)が担う。`loop` は種別で並びが変わるので `LOOP_FIELDS`。
FIELD_ORDER: dict[str, tuple[str, ...]] = {
    "frame": ("$schema", "width", "height", "fps", "seed"),
    "form": ("name", "fields"),
    "circle": ("name", "core", "flow.kind", "flow.steps", "flow.exit"),
    "state": ("name", "type", "init"),
    "sigil": ("name", "kind", "host", "circle", "rite", "file"),
    "asset": ("name", "kind", "path"),
    "rite": ("name", "params", "returns"),
    "step.set": ("target", "expr"),
    "step.let": ("name", "type", "expr"),
    "step.cast": ("target", "args", "into"),
    "step.if": ("cond",),
    "step.loop": ("kind",),
    "step.break": (),
    "step.wait": ("ticks", "until"),
    "step.emit": ("circle", "message", "args"),
    "step.return": ("expr",),
    "step.finish": (),
    "step.transfer": ("circle",),
    "on": ("event", "rite"),
    "guard": ("assert", "message"),
    "delegate": ("circle",),
    "description": ("description",),
    # S3(入れ子の境目・ユーザーの判断 B): 欄を持たない印だけの銘帯。`if` の `else` の始まりと、`if` / `loop` のブロックの終わり
    "else": (),
    "end": (),
}

#: `loop` の種別の紋の後に続く欄の並び(`count` は `times` が先で、`name` は印の紋付きで後)。
LOOP_FIELDS: dict[str, tuple[str, ...]] = {
    "each": ("name", "in"),
    "while": ("cond",),
    "count": ("times", "name"),
}


@dataclass(frozen=True)
class StructMark:
    """構造の印(spec §1.1 / §1.3・S2)。銘環の中で銘帯 1 本の頭に置き、どの図形の銘文かを示す(区切りを兼ねる)。"""

    id: str
    owner: str  # FIELD_ORDER の鍵(図形の種類)


#: 額縁は銘帯の頭を持たない(額縁の辺そのものが始まり)ので印が無い。並びは FIELD_ORDER と同じ。
STRUCT_MARKS: tuple[StructMark, ...] = tuple(
    StructMark("s_" + owner.removeprefix("step."), owner)
    for owner in FIELD_ORDER
    if owner != "frame"
)

STRUCT_MARK_OF: dict[str, str] = {m.owner: m.id for m in STRUCT_MARKS}

__all__ = [
    "DIVIDER",
    "ESCAPE_LETTERS",
    "EXPR_TOKEN_OF",
    "FIELD_ORDER",
    "GLYPHS",
    "GLYPH_IDS",
    "LOOP_FIELDS",
    "START_MARK",
    "STRUCT_MARKS",
    "STRUCT_MARK_OF",
    "Glyph",
    "StructMark",
]
