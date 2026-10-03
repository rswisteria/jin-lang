"""陣書きの紋の語彙と欄の順(`jin_core.v2.glyph`)。

正典は `docs/spec/v2/glyph.md`(文書との等号は `tests/spec/test_glyph_spec_consistency.py`)。
ここは語彙がモデルと式の文法に対して過不足ないことを固定する: 判別の紋はモデルの Literal と、
式紋は expr.md §1 の終端記号(名前・数・文字列を除く)と等号。
"""

from __future__ import annotations

import re
from typing import get_args

from jin_core.v2.glyph import EXPR_TOKEN_OF, FIELD_ORDER, GLYPH_IDS, GLYPHS, START_MARK
from jin_core.v2.model import STEP_KINDS, AssetKind, EventKind, FlowKind, LoopKind, SigilKind


def by_slot(slot: str) -> set[str]:
    return {g.token for g in GLYPHS if g.slot == slot}


def test_glyph_counts_match_the_spec() -> None:
    assert sum(g.layer == "expr" for g in GLYPHS) == 36
    assert sum(g.layer == "disc" for g in GLYPHS) == 22
    assert len(GLYPH_IDS) == len(GLYPHS) == 58


def test_glyph_ids_are_lowercase_identifiers() -> None:
    assert all(re.fullmatch(r"[a-z][a-z_]*", g.id) for g in GLYPHS)
    assert START_MARK not in GLYPH_IDS


def test_only_discriminators_have_a_slot() -> None:
    assert all((g.slot is None) == (g.layer == "expr") for g in GLYPHS)


def test_discriminators_cover_the_model_literals_exactly() -> None:
    assert by_slot("loop") == set(get_args(LoopKind))
    assert by_slot("sigil") == set(get_args(SigilKind))
    assert by_slot("event") == set(get_args(EventKind))
    assert by_slot("flow") == set(get_args(FlowKind))
    assert by_slot("asset") == set(get_args(AssetKind))
    assert by_slot("wait") == {"ticks", "until"}
    assert by_slot("optional") == {"into", "name", "message", "out"}
    assert {g.slot for g in GLYPHS if g.slot} == {
        "loop",
        "sigil",
        "event",
        "flow",
        "asset",
        "wait",
        "optional",
    }


def test_expr_glyphs_cover_every_operator_and_bracket_of_the_grammar() -> None:
    # expr.md §1 の終端記号のうち NAME / NUMBER / STRING 以外と等号(1 対 1)
    assert sorted(EXPR_TOKEN_OF.values()) == sorted(
        [
            "or",
            "and",
            "not",
            "==",
            "!=",
            "<",
            "<=",
            ">",
            ">=",
            "+",
            "-",
            "++",
            "*",
            "/",
            "%",
            ".",
            "[",
            "]",
            "(",
            ")",
            ",",
            "{",
            "}",
            ":",
            "true",
            "false",
        ]
    )
    assert set(EXPR_TOKEN_OF) <= GLYPH_IDS


def test_every_step_kind_has_a_field_order() -> None:
    assert {k.removeprefix("step.") for k in FIELD_ORDER if k.startswith("step.")} == set(
        STEP_KINDS
    )


def test_field_order_covers_every_figure_of_the_spec() -> None:
    figures = {k for k in FIELD_ORDER if not k.startswith("step.")}
    assert figures == {
        "frame",
        "form",
        "circle",
        "state",
        "sigil",
        "asset",
        "rite",
        "on",
        "guard",
        "delegate",
        "description",
        "else",
        "end",
    }


def test_loop_fields_cover_every_loop_kind() -> None:
    from jin_core.v2.glyph import LOOP_FIELDS

    assert set(LOOP_FIELDS) == set(get_args(LoopKind))
    assert LOOP_FIELDS["count"] == ("times", "name")  # spec §1.3: count は times が先


def test_struct_marks_cover_every_figure_but_the_frame() -> None:
    # spec §1.1 / §1.3: 銘環の銘帯の頭に置く構造の印。額縁は辺が始まりなので印を持たない
    from jin_core.v2.glyph import STRUCT_MARK_OF, STRUCT_MARKS

    assert len(STRUCT_MARKS) == 23
    assert {m.owner for m in STRUCT_MARKS} == set(FIELD_ORDER) - {"frame"}
    ids = {m.id for m in STRUCT_MARKS}
    assert len(ids) == 23
    assert not ids & GLYPH_IDS
    assert START_MARK not in ids
    assert all(m.id == "s_" + m.owner.replace("step.", "") for m in STRUCT_MARKS)
    assert STRUCT_MARK_OF == {m.owner: m.id for m in STRUCT_MARKS}


def test_escape_letters_cover_every_undrawable_character_including_space() -> None:
    # 最終レビュー #1: 文字列の中の空白は空の升と区別できないので esc + 字で書く
    from jin_core.v2.glyph import ESCAPE_LETTERS

    assert ESCAPE_LETTERS[" "] == "s"
    assert {'"', "\\", "\n", "\t", "\r", "\b", "\f"} <= set(ESCAPE_LETTERS)
    letters = list(ESCAPE_LETTERS.values())
    assert len(letters) == len(set(letters)), "読み戻せるよう 1 対 1"
    assert "u" not in letters, "u は 16 進 4 桁の前置き(その他の制御文字)に予約"
