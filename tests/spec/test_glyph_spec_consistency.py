"""陣書きの正典 `docs/spec/v2/glyph.md` と実装・設計書の突合。

`<!-- machine-readable: … -->` の表を読み、`jin_core.v2.glyph`(紋の語彙・欄の順)・
`jin_core.diagnostics.SCENE_CODES`(JIN3xx)・字形の SVG・設計書の字数と等号で固定する。
表の読み方は `test_v2_spec_consistency.py` と同じ(関数はモジュールごと借りる。名前で import すると
そのテスト関数がここでも収集されるため)。
"""

from __future__ import annotations

import re
from pathlib import Path

from jin_core.diagnostics import SCENE_CODES
from jin_core.v2.glyph import FIELD_ORDER, GLYPH_IDS, GLYPHS, LOOP_FIELDS, START_MARK

from tests.spec import test_v2_spec_consistency as v2spec

REPO_ROOT = Path(__file__).resolve().parents[2]
GLYPH_MD = REPO_ROOT / "docs/spec/v2/glyph.md"
DIAGNOSTICS_MD = REPO_ROOT / "docs/spec/v2/diagnostics.md"
GLYPH_DIR = REPO_ROOT / "docs/spec/v2/glyphs"
DESIGN = REPO_ROOT / "docs/superpowers/specs/2026-10-03-jin-glyph-design.md"


def rows(path: Path, marker: str) -> list[list[str]]:
    return v2spec.table_rows(v2spec.machine_block(path, marker))[1:]  # 見出し行を除く


def code_spans(cell: str) -> list[str]:
    return re.findall(r"`([^`]+)`", cell)


def none_or_span(cell: str) -> str | None:
    spans = code_spans(cell)
    return spans[0] if spans else None


def test_the_glyph_table_matches_the_vocabulary() -> None:
    table = rows(GLYPH_MD, "glyph-table")
    assert [code_spans(r[0])[0] for r in table] == [g.id for g in GLYPHS]
    for r, g in zip(table, GLYPHS, strict=True):
        assert r[1] == g.layer, g.id
        assert code_spans(r[2]) == [g.token], g.id
        assert none_or_span(r[3]) == g.slot, g.id
        assert f"glyphs/{g.id}.svg" in r[4], g.id


def test_every_glyph_has_an_svg_and_nothing_else_does() -> None:
    assert {p.stem for p in GLYPH_DIR.glob("*.svg")} == set(GLYPH_IDS)
    for p in GLYPH_DIR.glob("*.svg"):
        assert 'viewBox="0 0 100 100"' in p.read_text(encoding="utf-8"), p.name


def test_the_field_order_table_matches_the_code() -> None:
    table = {code_spans(r[0])[0]: tuple(code_spans(r[1])) for r in rows(GLYPH_MD, "field-order")}
    assert table == FIELD_ORDER


def test_the_loop_field_table_matches_the_code() -> None:
    table = {code_spans(r[0])[0]: tuple(code_spans(r[1])) for r in rows(GLYPH_MD, "loop-fields")}
    assert table == LOOP_FIELDS


def test_the_struct_mark_table_matches_the_code() -> None:
    from jin_core.v2.glyph import STRUCT_MARKS

    table = [(code_spans(r[0])[0], code_spans(r[1])[0]) for r in rows(GLYPH_MD, "struct-marks")]
    assert table == [(m.id, m.owner) for m in STRUCT_MARKS]


def test_the_start_mark_is_named_in_the_spec() -> None:
    assert f"`{START_MARK}`" in v2spec.read(GLYPH_MD)


def test_the_scene_code_table_matches_the_code() -> None:
    table = {r[0]: r[1] for r in rows(DIAGNOSTICS_MD, "scene-codes")}
    assert table == SCENE_CODES


def test_the_design_document_counts_match_the_vocabulary() -> None:
    text = v2spec.read(DESIGN)
    expr = int(re.search(r"式紋\(新設・(\d+) 字\)", text).group(1))
    disc = int(re.search(r"判別の紋\(新設・(\d+) 字\)", text).group(1))
    assert expr == sum(g.layer == "expr" for g in GLYPHS)
    assert disc == sum(g.layer == "disc" for g in GLYPHS)
