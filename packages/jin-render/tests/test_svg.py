"""`jin_render.svg`: 丸め関数 1 本と XML エスケープ（docs/spec/layout.md §3 / §4）。"""

from __future__ import annotations

import math
import re

import pytest
from jin_render import geometry as geo
from jin_render.svg import (
    ACCENT,
    ACCENT_STROKE_WIDTH,
    COORD_DECIMALS,
    INK,
    Node,
    attr_value,
    document,
    fmt_coord,
    text_value,
    xml_chars,
)

FIXED = re.compile(r"^-?\d+\.\d{3}$")


@pytest.mark.parametrize("value", [0.0, 1.0, -1.0, 123.456789, -0.5, 1e-9, 1e9, math.pi, 1.0 / 3.0])
def test_every_coordinate_has_exactly_three_decimals(value: float) -> None:
    """固定小数（末尾ゼロを落とさない）。桁数を落とすと SVG 全体の正規表現検査が成立しない。"""
    assert FIXED.match(fmt_coord(value)), fmt_coord(value)
    assert COORD_DECIMALS == 3


@pytest.mark.parametrize("value", [-0.0, -1e-9, -0.0004, -0.00049999])
def test_negative_zero_is_normalised(value: float) -> None:
    """`cos(90°)` 級の微小値の符号は libm で揺れる。`-0.000` を出さない（layout.md §4）。

    素の `format(x, ".3f")` は `-0.000` を返すので、この検査は正規化が消えると赤くなる。
    """
    assert format(value, ".3f") == "-0.000"
    assert fmt_coord(value) == "0.000"


def test_rounding_step_is_far_above_the_float_noise() -> None:
    """丸め桁数の根拠（layout.md §4 / decision-conformance.md §2）を機械で固定する。

    最大座標は 1000 px（キャンバスの縁）。倍精度の 1 ULP は約 1.1e-13 px で、
    丸めの刻み 1e-3 px より 10 桁小さい。libm の三角関数が 1 ULP 揺れても
    丸めの境界をまたがない。値は `geometry.CANVAS_PX` から導く（ハードコードすると
    キャンバスを広げたときに根拠だけが古びる・F-V-P3-008 / F-C-P3-010）。
    """
    largest = geo.CANVAS_PX
    ulp = math.ulp(largest)
    assert ulp < 1e-12
    assert ulp * 1000 < 10.0 ** (-COORD_DECIMALS) / 1000.0


def test_attribute_escaping_closes_the_tag_injection() -> None:
    """rune / circle 名は `.jin` 由来の入力。Phase 5 のエディタは SVG を DOM に埋め込む。"""
    hostile = "</svg><script>alert(1)</script>"
    escaped = attr_value(hostile)
    assert "<" not in escaped
    assert ">" not in escaped
    assert "&lt;/svg&gt;" in escaped


def test_attribute_escaping_keeps_double_quotes_as_the_delimiter() -> None:
    """`quoteattr` は値に `"` があると単引用符へ切り替える。それをしないこと。"""
    assert attr_value('a"b') == "a&quot;b"
    assert attr_value("a'b") == "a&apos;b"
    assert attr_value("a\nb") == "a&#10;b"


def test_text_escaping_closes_the_tag_injection() -> None:
    assert text_value("<b>&</b>") == "&lt;b&gt;&amp;&lt;/b&gt;"


def test_ampersand_is_escaped_before_the_other_entities() -> None:
    """`&` を後から置換すると `&lt;` が `&amp;lt;` に化ける。"""
    assert attr_value("&<") == "&amp;&lt;"


def test_a_node_without_a_pointer_carries_no_data_jin() -> None:
    svg = document([Node("path", [("id", "p"), ("d", "M 0.000 0.000")])], [], 10.0)
    assert "data-jin" not in svg
    assert "<defs>" in svg


def test_a_node_with_a_pointer_carries_both_attributes() -> None:
    node = Node("circle", [("r", fmt_coord(1.0))], pointer="/circles/0", kind="core")
    svg = document([], [node], 10.0)
    assert 'data-jin="/circles/0"' in svg
    assert 'data-jin-kind="core"' in svg


def test_a_fired_node_swaps_the_accent_attribute() -> None:
    node = Node(
        "circle",
        [("r", fmt_coord(1.0)), ("stroke", INK), ("stroke-width", fmt_coord(1.0))],
        pointer="/circles/0",
        kind="core",
        fired=True,
    )
    svg = document([], [node], 10.0)
    assert f'stroke="{ACCENT}"' in svg
    assert f'stroke="{INK}"' not in svg
    assert f'stroke-width="{fmt_coord(ACCENT_STROKE_WIDTH)}"' in svg
    assert 'data-jin-fired="1"' in svg


def test_a_fired_text_node_swaps_the_fill_not_the_stroke() -> None:
    node = Node(
        "text",
        [("stroke", "none"), ("fill", INK)],
        pointer="/circles/0/instruction/rune",
        kind="rune",
        accent_attr="fill",
        fired=True,
    )
    svg = document([], [node], 10.0)
    assert f'fill="{ACCENT}"' in svg
    assert 'stroke="none"' in svg


def test_the_svg_root_is_not_a_contract_element() -> None:
    """layout.md §3: `<svg>` 自身と `<defs>` 配下は契約の対象外。背景も塗らない。"""
    svg = document([], [], 1000.0)
    head = svg.splitlines()[0]
    assert "data-jin" not in head
    assert "<rect" not in svg


# --------------------------------------------------------------------------------------
# XML 1.0 の `Char` に無い文字は U+FFFD にする（F-S-P3-005）
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "bad",
    [
        pytest.param("\x01", id="C0-SOH"),
        pytest.param("\x0c", id="FF"),
        pytest.param("\x1f", id="US"),
        pytest.param("\ud800", id="lone-surrogate"),
        pytest.param("\udfff", id="lone-low-surrogate"),
        pytest.param("\ufffe", id="U+FFFE"),
        pytest.param("\uffff", id="U+FFFF"),
    ],
)
def test_a_character_outside_xml_char_becomes_the_replacement_character(bad: str) -> None:
    """エスケープしても `&#1;` は XML 1.0 では不正で、パーサが文書ごと拒む。"""
    assert xml_chars(f"a{bad}b") == "a\ufffdb"
    assert bad not in text_value(f"a{bad}b")
    assert bad not in attr_value(f"a{bad}b")


@pytest.mark.parametrize("keep", ["\t", "\n", "\r", " ", "あ", "\U0001f600", "\ud7ff", "\ue000"])
def test_valid_characters_are_kept(keep: str) -> None:
    assert xml_chars(keep) == keep
