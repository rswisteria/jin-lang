"""SVG のノード表現と文字列化（`docs/spec/layout.md` §3 / §4）。

## 決定性（DP-JIN-SVG-DETERMINISM-01 案 B・ADR-010）

**座標を SVG に書き出す経路は `fmt_coord` 1 本だけ**である。`f"{x}"` / `str(float)` / `repr` を
SVG 生成に混ぜない。桁数は `COORD_DECIMALS`（3 桁・固定小数）。末尾ゼロを落とさないので
「SVG 内の幾何・体裁属性の数値がすべて 3 桁で終わる」ことを正規表現で固定できる。

`-0.0` は `0.0` に正規化する。`cos(90°)` 級の微小値の符号は libm で揺れ、`-0.000` と `0.000` の差が
開発機と CI でスナップショットをずらす。

    guard: fmt_coord -> format(value,_COORD_FORMAT)
    guard: fmt_coord -> float(text)==0.0

## XML エスケープ

**現在 SVG に流れる `.jin` 由来の文字列は `instruction.rune` のテキストノードだけ**である
（F-V-P3-002 の実測）。circle 名 / tool 名 / state 名は描画に出ず、`data-jin` は添字だけの
pointer、`data-jin-seq` は整数。したがって属性値のエスケープを実際に守っているのは
`test_svg.py` の単体テストであって、統合テストではない。

`attr_value` は**将来属性へ流れる値**（Phase 5 の `title` / `aria-label` など）の受け皿として
残す。属性値は `quoteattr` ではなく `escape` + **常に二重引用符**にする。`quoteattr` は値に
`"` があると囲みを単引用符へ切り替えるので、出力の形が入力次第で変わる（スナップショットと
正規表現検査が不揃いになる）。

Phase 5 のエディタはこの SVG を DOM に埋め込むので、XML 1.0 の `Char` に無い文字
（C0 制御文字 / サロゲート / U+FFFE / U+FFFF）は U+FFFD へ置き換える。エスケープしても
`&#1;` は XML 1.0 では不正のままで、パーサが文書ごと拒む（F-S-P3-005）。

    guard: attr_value -> xml_chars(value)
    guard: text_value -> xml_chars(value)
    guard: attr_value -> escape(xml_chars(value),_ATTR_ENTITIES)
    guard: text_value -> escape(xml_chars(value))
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

#: 丸め桁数。根拠は docs/spec/layout.md §4 と decision-conformance.md §2（DP-IMPL-JIN-P3-ROUNDING-01）。
COORD_DECIMALS = 3
_COORD_FORMAT = f".{COORD_DECIMALS}f"

#: 白黒 2 値（要件書 §2.5）。
INK = "#000000"
#: 強調 1 色（トレース時のみ）。要件値ではない（DP-IMPL-JIN-P3-ACCENT-COLOR-01）。
ACCENT = "#cc0000"

STROKE_WIDTH = 1.0
ACCENT_STROKE_WIDTH = 2.0
#: `out: true` の state（ADK の output_key になるもの）を描き分ける線幅。
OUT_STROKE_WIDTH = 2.0
FONT_FAMILY = "sans-serif"

#: `escape` の既定（`&` `<` `>`）に足す属性値専用の置換。改行・タブは属性値の中で
#: 空白に潰されるので実体参照にする（pointer や名前に混ざったときに形が変わらない）。
#: XML 1.0 の `Char` **以外**。サロゲート（U+D800-U+DFFF）は Python の str に単独で
#: 入りうる（`json` が `\\ud800` を通す）ので明示的に含める。
_XML_NON_CHAR = re.compile("[^\u0009\u000a\u000d\u0020-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")

_ATTR_ENTITIES = {
    '"': "&quot;",
    "'": "&apos;",
    "\n": "&#10;",
    "\r": "&#13;",
    "\t": "&#9;",
}


def fmt_coord(value: float) -> str:
    """座標・寸法を SVG へ書き出す**唯一の**関数（DP-JIN-SVG-DETERMINISM-01 案 B）。

    guard: fmt_coord -> format(value,_COORD_FORMAT)
    guard: fmt_coord -> float(text)==0.0
    """
    text = format(value, _COORD_FORMAT)
    if float(text) == 0.0:
        # `-0.000` を `0.000` にそろえる（libm の符号の揺れを SVG に出さない）。
        text = format(0.0, _COORD_FORMAT)
    return text


#: 破線の刻み。`fmt_coord` を通す（数値を書く経路を 1 本に保つ・F-V-P3-001）。
DASH = f"{fmt_coord(6.0)} {fmt_coord(4.0)}"


def xml_chars(value: str) -> str:
    """XML 1.0 の `Char` に無い符号位置を U+FFFD へ置き換える。

    `Char ::= #x9 | #xA | #xD | [#x20-#xD7FF] | [#xE000-#xFFFD] | [#x10000-#x10FFFF]`。
    ここに無い文字は**エスケープしても不正**である（`&#1;` は XML 1.0 の数値文字参照
    として許されない）。1 文字混ざるだけでパーサが SVG 全体を拒むので、
    エスケープの前に落とす（F-S-P3-005）。`jin_core` の検証は変えない
    （診断コードは増やさない）。ここは**描画側の出力契約**を守るための置換である。
    """
    return _XML_NON_CHAR.sub("\ufffd", value)


def attr_value(value: str) -> str:
    """属性値をエスケープする（囲みは常に二重引用符）。

    guard: attr_value -> xml_chars(value)
    guard: attr_value -> escape(xml_chars(value),_ATTR_ENTITIES)
    """
    return escape(xml_chars(value), _ATTR_ENTITIES)


def text_value(value: str) -> str:
    """テキストノードをエスケープする。

    guard: text_value -> xml_chars(value)
    guard: text_value -> escape(xml_chars(value))
    """
    return escape(xml_chars(value))


@dataclass
class Node:
    """SVG の 1 要素。

    `pointer` が `None` の要素（`<defs>` とその配下）は `data-jin` 契約の対象外
    （layout.md §3）。それ以外はすべて `data-jin` / `data-jin-kind` を持つ。

    `accent_attr` は強調のときに `ACCENT` へ置き換える属性名。線で描く要素は `stroke`、
    文字と塗りつぶしの点は `fill`。
    """

    tag: str
    attrs: list[tuple[str, str]] = field(default_factory=list)
    pointer: str | None = None
    kind: str | None = None
    ref: str | None = None
    text: str | None = None
    children: list[Node] = field(default_factory=list)
    accent_attr: str = "stroke"
    fired: bool = False

    def walk(self) -> list[Node]:
        """自分と子孫を描画順で返す。"""
        found = [self]
        for child in self.children:
            found.extend(child.walk())
        return found


def _attrs_of(node: Node) -> list[tuple[str, str]]:
    """出力する属性を決定的な順序で組み立てる。"""
    out: list[tuple[str, str]] = []
    if node.pointer is not None:
        out.append(("data-jin", node.pointer))
        out.append(("data-jin-kind", node.kind or ""))
    if node.ref is not None:
        out.append(("data-jin-ref", node.ref))
    if node.fired:
        out.append(("data-jin-fired", "1"))
    body = list(node.attrs)
    if node.fired:
        dropped = {node.accent_attr}
        if node.accent_attr == "stroke":
            dropped.add("stroke-width")
        body = [(name, value) for name, value in body if name not in dropped]
        body.append((node.accent_attr, ACCENT))
        if node.accent_attr == "stroke":
            body.append(("stroke-width", fmt_coord(ACCENT_STROKE_WIDTH)))
    return out + body


def _serialize(node: Node, depth: int, out: list[str]) -> None:
    pad = "  " * depth
    attrs = "".join(f' {name}="{attr_value(value)}"' for name, value in _attrs_of(node))
    if node.text is not None:
        out.append(f"{pad}<{node.tag}{attrs}>{text_value(node.text)}</{node.tag}>")
        return
    if not node.children:
        out.append(f"{pad}<{node.tag}{attrs}/>")
        return
    out.append(f"{pad}<{node.tag}{attrs}>")
    for child in node.children:
        _serialize(child, depth + 1, out)
    out.append(f"{pad}</{node.tag}>")


def document(defs: list[Node], body: list[Node], size: float) -> str:
    """`<svg>` 文書を組み立てる。

    `<svg>` 要素自身と `<defs>` 配下は `data-jin` 契約の対象外（layout.md §3）。
    背景は塗らない（塗ると `data-jin` を持たない描画要素ができる）。SVG の既定どおり
    透明で、埋め込む側の地色がそのまま出る。
    """
    edge = fmt_coord(size)
    zero = fmt_coord(0.0)
    head = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{edge}" height="{edge}" viewBox="{zero} {zero} {edge} {edge}">'
    )
    lines = [head]
    if defs:
        lines.append("  <defs>")
        for node in defs:
            _serialize(node, 2, lines)
        lines.append("  </defs>")
    for node in body:
        _serialize(node, 1, lines)
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


__all__ = [
    "ACCENT",
    "ACCENT_STROKE_WIDTH",
    "COORD_DECIMALS",
    "DASH",
    "FONT_FAMILY",
    "INK",
    "OUT_STROKE_WIDTH",
    "STROKE_WIDTH",
    "Node",
    "attr_value",
    "document",
    "fmt_coord",
    "text_value",
    "xml_chars",
]
