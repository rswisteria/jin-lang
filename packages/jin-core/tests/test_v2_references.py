"""名前を持つ要素への参照の位置（`jin_core.v2.references`）と、式の中の位置の換算（`spans`）。

参照の表は `rename` の追随（ops.md §3）と LSP の definition / references / rename が共有する。
ここでは 3 つを固定する:

- 表の具体値（paddle）: 構造の参照は値の全体、式・型・`cast.target` の頭は区間
- 一貫性（examples-v2 + v2-programs の全部）: 定義の名前と各参照の位置から `symbol_at` が
  同じ要素に戻る（2 つの要素が同じ位置を取り合わない）
- `rename` が書き換えるのは表の位置と定義の名前**だけ**（表と追随がずれない）
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jin_core.check import check_text
from jin_core.diagnostics import Position, Range
from jin_core.pointer import resolve_pointer
from jin_core.v2 import references
from jin_core.v2.expr import Span
from jin_core.v2.model import JinFileV2
from jin_core.v2.ops import apply_op
from jin_core.v2.spans import offset_in_literal, range_in_literal

REPO_ROOT = Path(__file__).resolve().parents[3]
PADDLE = REPO_ROOT / "examples-v2" / "paddle" / "paddle.jin"
PROGRAMS = sorted((REPO_ROOT / "examples-v2").glob("*/*.jin")) + sorted(
    (REPO_ROOT / "tests" / "fixtures" / "v2-programs").glob("*.jin")
)


def load(path: Path) -> JinFileV2:
    model = check_text(path.read_text(encoding="utf-8"), path.name).model
    assert isinstance(model, JinFileV2)
    return model


def by_target(model: JinFileV2) -> dict[str, references.Symbol]:
    return {symbol.target: symbol for symbol in references.index(model)}


def shown(doc: dict[str, Any], occurrence: references.Occurrence) -> str:
    value = resolve_pointer(doc, occurrence.pointer)
    span = occurrence.span
    return value if span is None else value[span.start : span.end]


# ---------------------------------------------------------------- spans


@pytest.mark.parametrize(
    "decoded", ["score + 1", 'input.key("A")', "a\nb\\c", "名前 + é", "x 😀 y", " z"]
)
def test_offset_in_literal_inverts_range_in_literal(decoded: str) -> None:
    """復号後の添字 → 原文の列 → 復号後の添字 が元に戻る（エスケープ・非 ASCII・サロゲートペア込み）。"""
    literal = json.dumps(decoded)  # `\n` / `\\` / `\"` / `\uXXXX` のエスケープを含む原文
    line = f'    "expr": {literal},\n'
    col = line.index(literal) + 1
    literal_range = Range(Position(3, col), Position(3, col + len(literal)))
    lines = ["\n", "\n", line]
    for index in range(len(decoded)):
        found = range_in_literal(lines, literal_range, index, index + 1)
        assert found.start.line == 3
        assert offset_in_literal(lines, literal_range, found.start) == index
        # エスケープの途中の列も同じ 1 文字に寄る
        for column in range(found.start.col, found.end.col):
            assert offset_in_literal(lines, literal_range, Position(3, column)) == index


def test_offset_in_literal_clamps_the_quotes_and_rejects_the_outside() -> None:
    line = '"abc"'
    literal_range = Range(Position(1, 1), Position(1, 6))
    assert offset_in_literal([line], literal_range, Position(1, 1)) == 0  # 開き引用符
    assert offset_in_literal([line], literal_range, Position(1, 5)) == 3  # 閉じ引用符 = 末尾の end
    assert offset_in_literal([line], literal_range, Position(1, 7)) is None
    assert offset_in_literal([line], literal_range, Position(2, 1)) is None


def test_range_in_literal_falls_back_to_the_whole_literal_when_it_cannot_read_it() -> None:
    literal_range = Range(Position(1, 1), Position(2, 3))  # 2 行に跨がる（JSON の文字列ではない）
    assert range_in_literal(["ab\n", "cd"], literal_range, 0, 1) == literal_range


# ---------------------------------------------------------------- 表の具体値


def test_paddle_references_cover_structure_types_expressions_and_cast_heads() -> None:
    model = load(PADDLE)
    doc = model.model_dump(by_alias=True, mode="json")
    table = by_target(model)

    play = table["/circles/1"]
    assert (play.kind, play.name, play.name_pointer) == ("circle", "Play", "/circles/1/name")
    assert [(o.pointer, shown(doc, o)) for o in play.occurrences] == [
        ("/circles/0/flow/steps/0", "Play"),
        ("/circles/2/rites/1/steps/1/args/0", "Play"),  # `str(Play.score)`
    ]
    assert play.occurrences[0].span is None

    score = table["/circles/1/state/2"]
    pointers = [o.pointer for o in score.occurrences]
    assert "/circles/1/rites/0/steps/0/target" in pointers  # set.target
    assert "/circles/1/boundary/guards/0/assert" in pointers
    assert "/circles/2/rites/1/steps/1/args/0" in pointers  # 他陣の `Play.score`
    assert {shown(doc, o) for o in score.occurrences} == {"score"}

    ball = table["/forms/0"]
    assert ("/circles/1/state/0/type", Span(0, 4)) in [
        (o.pointer, o.span) for o in ball.occurrences
    ]

    canvas = table["/circles/1/sigils/0"]
    assert {o.span for o in canvas.occurrences} == {Span(0, 6)}  # `canvas.clear` などの頭

    paint = table["/circles/1/rites/3"]
    assert [(o.pointer, o.span) for o in paint.occurrences] == [
        ("/circles/1/rites/2/steps/8/target", None)
    ]

    dt = table["/circles/1/rites/2/params/0"]
    assert dt.kind == "local" and len(dt.occurrences) == 4


def test_symbol_at_prefers_the_reference_that_contains_the_offset() -> None:
    """`Play.score` の `.` の上は `Play` の直後で、中にある区間が無ければ直後の `Play` を選ぶ。"""
    symbols = references.index(load(PADDLE))
    pointer = "/circles/2/rites/1/steps/1/args/0"  # "SCORE " ++ str(Play.score)
    assert references.symbol_at(symbols, pointer, 16).name == "Play"
    assert references.symbol_at(symbols, pointer, 20).name == "Play"  # 直後（他に中の区間が無い）
    assert references.symbol_at(symbols, pointer, 21).name == "score"
    assert references.symbol_at(symbols, pointer, 2) is None  # 文字列リテラルの中
    assert references.symbol_at(symbols, "/circles/1/core", None).name == "begin"
    assert references.symbol_at(symbols, "/circles/1/rites/3/name", None).name == "paint"
    assert references.symbol_at(symbols, "/stage/width", None) is None


def test_find_rejects_a_pointer_that_does_not_name_anything() -> None:
    doc = load(PADDLE).model_dump(by_alias=True, mode="json")
    with pytest.raises(ValueError):
        references.find(doc, "/stage")
    assert references.target_kind(["circles", "1", "rites", "2", "params", "0"]) == (
        "local",
        "param",
    )


# ---------------------------------------------------------------- 全プログラムの一貫性


@pytest.mark.parametrize("path", PROGRAMS, ids=lambda p: p.stem)
def test_every_position_in_the_table_resolves_back_to_its_symbol(path: Path) -> None:
    symbols = references.index(load(path))
    assert symbols, "名前を持つ要素が 1 つも無い"
    for symbol in symbols:
        assert references.symbol_at(symbols, symbol.name_pointer, None) is symbol
        for occurrence in symbol.occurrences:
            offset = occurrence.span.start if occurrence.span is not None else None
            assert references.symbol_at(symbols, occurrence.pointer, offset) is symbol, (
                symbol.target,
                occurrence,
            )


def _leaves(value: Any, pointer: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        found: dict[str, Any] = {}
        for key, item in value.items():
            found.update(_leaves(item, f"{pointer}/{key}"))
        return found
    if isinstance(value, list):
        found = {}
        for index, item in enumerate(value):
            found.update(_leaves(item, f"{pointer}/{index}"))
        return found
    return {pointer: value}


@pytest.mark.parametrize("path", PROGRAMS, ids=lambda p: p.stem)
def test_rename_rewrites_exactly_the_positions_in_the_table(path: Path) -> None:
    model = load(path)
    before = _leaves(model.model_dump(by_alias=True, mode="json"))
    for symbol in references.index(model):
        result = apply_op(model, {"op": "rename", "pointer": symbol.target, "value": "zz_renamed"})
        after = _leaves(result.model.model_dump(by_alias=True, mode="json"))
        changed = {p for p in before.keys() | after.keys() if before.get(p) != after.get(p)}
        expected = {symbol.name_pointer} | {o.pointer for o in symbol.occurrences}
        assert changed == expected, symbol.target
        assert result.warnings == symbol.unresolved
