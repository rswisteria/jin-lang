"""パッケージ横断契約: Jin v2 の正準形（式の正準化・v2.1。docs/spec/v2/expr.md §8 / model.md §9）。

v1 の契約（`test_canonical_contract.py`）は v2 のファイルを見ない（fixture の走査が v1 のディレクトリに
閉じている）。v2 では式の欄が AST から書き戻されるので「意味保存」は**式の AST が変わらない**ことで見る
（文字列の一致ではない）。

- 冪等性: examples-v2 / v2-programs / errors/v2（モデルになるもの）について dumps(dumps(x)) == dumps(x)
- 意味保存: 式の欄ごとに parse(before) ≅ parse(after)（位置を除く）。読めない式は文字どおり同じ
- 正の証拠: `tests/fixtures/canonical/v2/messy.jin` → `messy.expected.jin` にバイト一致
- 整形が消す診断は `cast.target` の形（JIN202）だけ
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jin_core.canonical import dumps
from jin_core.check import check_file, check_text
from jin_core.v2.expr import ExprSyntaxError, parse_expr
from jin_core.v2.model import expr_fields
from pydantic import BaseModel

from tests.conftest import REPO_ROOT

V2_DIRS = (
    REPO_ROOT / "examples-v2",
    REPO_ROOT / "tests" / "fixtures" / "v2-programs",
    REPO_ROOT / "tests" / "fixtures" / "errors" / "v2",
)
CANONICAL_DIR = REPO_ROOT / "tests" / "fixtures" / "canonical" / "v2"


def _v2_paths() -> list[Path]:
    paths: list[Path] = []
    for root in V2_DIRS:
        paths.extend(sorted(root.rglob("*.jin")))
    return paths


def _formattable() -> list[Path]:
    return [p for p in _v2_paths() if check_file(p).model is not None]


def _shape(text: str) -> Any:
    """式の意味（構造）。読めない式は字面そのもの。"""
    try:
        node = parse_expr(text)
    except ExprSyntaxError:
        return ("raw", text)
    return _node_shape(node)


def _node_shape(node: Any) -> Any:
    out: list[Any] = [type(node).__name__]
    for slot in type(node).__slots__:
        if slot in ("span", "type", "name_span", "form_span"):
            continue
        value = getattr(node, slot)
        if isinstance(value, list):
            out.append(
                tuple(_node_shape(v) if hasattr(v, "span") else _pair_shape(v) for v in value)
            )
        elif hasattr(value, "span"):
            out.append(_node_shape(value))
        else:
            out.append(value)
    return tuple(out)


def _pair_shape(pair: tuple[str, Any, Any]) -> Any:
    name, _, value = pair
    return (name, _node_shape(value))


def _expression_fields(model: Any) -> list[tuple[str, str]]:
    """モデルの全式の欄を（JSON pointer, テキスト）で列挙する。印（`expr_fields`）で見分ける。"""
    found: list[tuple[str, str]] = []

    def visit(obj: Any, pointer: str) -> None:
        if isinstance(obj, BaseModel):
            exprs = expr_fields(type(obj))
            for name, info in type(obj).model_fields.items():
                key = info.alias or name
                value = getattr(obj, name)
                if key in exprs:
                    if isinstance(value, str):
                        found.append((f"{pointer}/{key}", value))
                    elif isinstance(value, list):
                        for i, item in enumerate(value):
                            found.append((f"{pointer}/{key}/{i}", item))
                else:
                    visit(value, f"{pointer}/{key}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                visit(item, f"{pointer}/{i}")

    visit(model, "")
    return found


def test_the_v2_fixture_set_is_not_empty() -> None:
    paths = _formattable()
    assert len(paths) >= 30
    assert any(p.name == "JIN201_expression_syntax_error.jin" for p in paths)


@pytest.mark.parametrize("path", _formattable(), ids=lambda p: p.name)
def test_dumps_is_idempotent_and_preserves_every_expression(path: Path) -> None:
    before = check_file(path).model
    assert before is not None
    once = dumps(before)
    after = check_text(once, str(path)).model
    assert after is not None
    assert dumps(after) == once, "冪等でない"
    fields_before = _expression_fields(before)
    fields_after = _expression_fields(after)
    assert [p for p, _ in fields_before] == [p for p, _ in fields_after]
    for (pointer, text_before), (_, text_after) in zip(fields_before, fields_after, strict=True):
        assert _shape(text_before) == _shape(text_after), f"{path.name}{pointer}"


def test_the_syntax_error_fixture_keeps_its_broken_expression() -> None:
    path = REPO_ROOT / "tests" / "fixtures" / "errors" / "v2" / "JIN201_expression_syntax_error.jin"
    model = check_file(path).model
    assert model is not None
    raw = json.loads(path.read_text(encoding="utf-8"))
    out = json.loads(dumps(model))
    assert out["circles"][0]["rites"][0]["steps"][0]["expr"] == "1 +"
    assert raw["circles"][0]["rites"][0]["steps"][0]["expr"] == "1 +"


def test_the_messy_fixture_formats_to_the_expected_bytes() -> None:
    messy = CANONICAL_DIR / "messy.jin"
    expected = (CANONICAL_DIR / "messy.expected.jin").read_text(encoding="utf-8")
    model = check_file(messy).model
    assert model is not None
    assert dumps(model) == expected
    # expected 自身が正準（冪等）
    again = check_text(expected, "messy.expected.jin").model
    assert again is not None
    assert dumps(again) == expected
    # 整形の前後で式の意味は同じ
    for (pointer, before), (_, after) in zip(
        _expression_fields(model), _expression_fields(again), strict=True
    ):
        assert _shape(before) == _shape(after), pointer


def test_the_messy_fixture_exercises_every_kind_of_expression_field() -> None:
    """before / after の fixture が印の付いた欄をすべて 1 回以上変えていることを固定する。"""
    messy = check_file(CANONICAL_DIR / "messy.jin").model
    expected = check_file(CANONICAL_DIR / "messy.expected.jin").model
    assert messy is not None and expected is not None
    changed_keys: set[str] = set()
    for (pointer, before), (_, after) in zip(
        _expression_fields(messy), _expression_fields(expected), strict=True
    ):
        if before != after:
            key = pointer.rsplit("/", 1)[-1]
            changed_keys.add(pointer.rsplit("/", 2)[-2] if key.isdigit() else key)
    assert changed_keys == {
        "exit",
        "init",
        "target",
        "expr",
        "args",
        "into",
        "cond",
        "in",
        "times",
        "ticks",
        "until",
        "assert",
    }


def test_formatting_only_removes_the_cast_target_shape_diagnostic() -> None:
    """`cast.target` は名前の欄だが式の印を持つので同じ規則で書き戻す（`canvas . rect` → `canvas.rect`）。

    check は名前の形を要求するので整形前は JIN202、整形後は通る。整形が消す診断はこれだけで、
    他の診断は整形の前後で同じ（expr.md §8）。
    """
    before = check_file(CANONICAL_DIR / "messy.jin")
    after = check_file(CANONICAL_DIR / "messy.expected.jin")
    assert [(d.code, d.pointer) for d in before.diagnostics] == [
        ("JIN202", "/circles/1/rites/0/steps/2/target")
    ]
    assert after.diagnostics == []
