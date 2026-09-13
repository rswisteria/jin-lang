"""式の正準形（docs/spec/v2/expr.md §8・v2.1）: 印字器の往復・括弧・数値・文字列・writer の規則 8。"""

from __future__ import annotations

import json
import random

import pytest
from jin_core.canonical import dumps, encode_string
from jin_core.check import check_text
from jin_core.model import JinFile
from jin_core.v2.expr import (
    Binary,
    Boolean,
    Call,
    Construct,
    FieldAccess,
    Index,
    ListLiteral,
    Name,
    Node,
    Number,
    Span,
    String,
    Unary,
    canonical_expr,
    format_number,
    parse_expr,
    unparse,
)
from jin_core.v2.model import JinFileV2

# ---------------------------------------------------------------- 字面の規則（expr.md §8）


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # 空白: 二項演算子の両側に 1 つ、`,` と `:` の後ろに 1 つ。タブと余分な空白は消える
        ("a+1", "a + 1"),
        ("a\t+\tb", "a + b"),
        ("  a  ", "a"),
        ("f(a,b)", "f(a, b)"),
        ("Ball{x:160,y:40}", "Ball{x: 160, y: 40}"),
        ("Ball{}", "Ball{}"),
        ("[ 1 ,2 ]", "[1, 2]"),
        ("[]", "[]"),
        ("f()", "f()"),
        ("xs [ i ] . k ( 1 ) ( 2 )", "xs[i].k(1)(2)"),
        # 括弧: 優先順位と結合で要るときだけ
        ("(a and b) or c", "a and b or c"),
        ("a and (b or c)", "a and (b or c)"),
        ("(a + b) + c", "a + b + c"),
        ("a + (b + c)", "a + (b + c)"),
        ("(a - b) - c", "a - b - c"),
        ("a - (b - c)", "a - (b - c)"),
        ("(a + b) * c", "(a + b) * c"),
        ("a * (b + c)", "a * (b + c)"),
        ("((n))", "n"),
        # cmp は連鎖しないので両側に要る
        ("(a < b) == c", "(a < b) == c"),
        ("a < (b == c)", "a < (b == c)"),
        # not は cmp より弱く and より強い
        ("not (a and b)", "not (a and b)"),
        ("not (a == b)", "not a == b"),
        ("not not a", "not not a"),
        ("(not a) and b", "not a and b"),
        # 単項 -
        ("-(a * b)", "-(a * b)"),
        ("(-a) * b", "-a * b"),
        ("-(-x)", "-(-x)"),
        ("- -x", "-(-x)"),
        ("--x", "-(-x)"),
        ("a - -b", "a - -b"),
        ("a--b", "a - -b"),
        ("(-a).x", "(-a).x"),
        ("(a + b)[0]", "(a + b)[0]"),
        ("-abs(ball.vy) * 1.05", "-abs(ball.vy) * 1.05"),
        # 数値: 整数値は整数、それ以外は repr の配置
        ("1.50", "1.5"),
        ("1e3", "1000"),
        ("1e21", "1e+21"),
        ("1.5e-7", "1.5e-07"),
        ("007", "7"),
        # 文字列: JSON の最小エスケープ
        ('"\\u0041\\/"', '"A/"'),
        ('"日本\\n"', '"日本\\n"'),
        ("true", "true"),
        ("false", "false"),
    ],
)
def test_canonical_form_of_expressions(text: str, expected: str) -> None:
    assert unparse(parse_expr(text)) == expected
    assert unparse(parse_expr(expected)) == expected, "正準形は冪等"


def test_examples_from_the_design_document_are_already_canonical() -> None:
    for text in (
        "Ball{x: 160, y: 40, vx: 90, vy: 70}",
        "ball.y > 170 and ball.x >= paddle and ball.x <= paddle + 40",
        'str(len(items)) ++ "/" ++ sub("hello", 1, 3)',
        'ui.button("UPGRADE", 130, 60, 90, 28) and count >= 10',
        "max(0, paddle - 180 * dt)",
        'num(storage.get("runs")) + 1',
    ):
        assert unparse(parse_expr(text)) == text


# ---------------------------------------------------------------- 数値


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.0, "0"),
        (-0.0, "0"),
        (3.0, "3"),
        (160.0, "160"),
        (0.1, "0.1"),
        (1.05, "1.05"),
        (1e-5, "1e-05"),
        (1.5e-7, "1.5e-07"),
        (1e15 + 0.5, "1000000000000000.5"),
        (2.0**53 - 1, "9007199254740991"),
        (2.0**53, "9007199254740992.0"),
        (1e16, "1e+16"),
        (1e21, "1e+21"),
        (1e300, "1e+300"),
        (5e-324, "5e-324"),
    ],
)
def test_format_number_follows_the_runtime_number_format(value: float, expected: str) -> None:
    """runtime.md §6（`str(x)` の書式）と同じ。どれも文法の NUMBER として読み戻せる。"""
    assert format_number(value) == expected
    node = parse_expr(expected)
    assert isinstance(node, Number) and node.value == value


def test_format_number_refuses_non_finite_values() -> None:
    for value in (float("inf"), float("-inf"), float("nan")):
        with pytest.raises(ValueError):
            format_number(value)


def test_an_overflowing_literal_is_left_as_written() -> None:
    """`1e999` は文法を通るが値は inf。書き戻せないので元の字面のまま。"""
    assert canonical_expr("1e999") == "1e999"
    assert canonical_expr("1e999 + 1") == "1e999 + 1"


def test_a_syntax_error_is_left_as_written() -> None:
    for text in ("1 +", "a < b < c", "[1, 2,]", "", "  ", "a\nb"):
        assert canonical_expr(text) == text


# ---------------------------------------------------------------- 文字列


def test_strings_use_the_canonical_json_escapes() -> None:
    values = ['"', "\\", "\n", "\t", "\x01", "\x7f", "日本", "🎮", "a/b", " "]
    for value in values:
        text = unparse(String(Span(0, 0), value))
        assert text == encode_string(value)
        assert json.loads(text) == value
        node = parse_expr(text)
        assert isinstance(node, String) and node.value == value


# ---------------------------------------------------------------- ランダムな AST の往復


def _shape(node: Node) -> tuple:
    """位置と型を捨てた構造（比較用）。"""
    if isinstance(node, Number):
        return ("num", node.value)
    if isinstance(node, String):
        return ("str", node.value)
    if isinstance(node, Boolean):
        return ("bool", node.value)
    if isinstance(node, Name):
        return ("name", node.name)
    if isinstance(node, Unary):
        return ("unary", node.op, _shape(node.operand))
    if isinstance(node, Binary):
        return ("binary", node.op, _shape(node.left), _shape(node.right))
    if isinstance(node, FieldAccess):
        return ("field", _shape(node.obj), node.name)
    if isinstance(node, Index):
        return ("index", _shape(node.obj), _shape(node.index))
    if isinstance(node, Call):
        return ("call", _shape(node.callee), tuple(_shape(a) for a in node.args))
    if isinstance(node, Construct):
        return ("construct", node.form, tuple((n, _shape(v)) for n, _, v in node.fields))
    if isinstance(node, ListLiteral):
        return ("list", tuple(_shape(i) for i in node.items))
    raise TypeError(type(node))


_NAMES = ["a", "b", "ball", "x_1", "andy", "orb", "notes", "trueish", "_", "Play"]
_STRINGS = ["", "a", '"', "\\", "\n", "\x00", "日本語", "🎮", "a b", "\\u0041"]
_NUMBERS = [0.0, 1.0, 7.0, 0.5, 0.1, 1.05, 1e-7, 1e21, 2.0**53, 2.0**53 - 1, 123456.789]
_BINARY_OPS = ["or", "and", "==", "!=", "<", "<=", ">", ">=", "+", "-", "++", "*", "/", "%"]
_ZERO = Span(0, 0)


def _random_node(rng: random.Random, depth: int) -> Node:
    if depth <= 0:
        kind = rng.choice(["num", "str", "bool", "name"])
    else:
        kind = rng.choice(
            ["num", "str", "bool", "name", "unary", "binary", "binary", "binary"]
            + ["field", "index", "call", "construct", "list"]
        )
    sub = depth - 1
    if kind == "num":
        return Number(_ZERO, rng.choice(_NUMBERS))
    if kind == "str":
        return String(_ZERO, rng.choice(_STRINGS))
    if kind == "bool":
        return Boolean(_ZERO, rng.random() < 0.5)
    if kind == "name":
        return Name(_ZERO, rng.choice(_NAMES))
    if kind == "unary":
        return Unary(_ZERO, rng.choice(["not", "-"]), _random_node(rng, sub))
    if kind == "binary":
        return Binary(
            _ZERO, rng.choice(_BINARY_OPS), _random_node(rng, sub), _random_node(rng, sub)
        )
    if kind == "field":
        return FieldAccess(_ZERO, _random_node(rng, sub), rng.choice(_NAMES), _ZERO)
    if kind == "index":
        return Index(_ZERO, _random_node(rng, sub), _random_node(rng, sub))
    if kind == "call":
        return Call(
            _ZERO,
            _random_node(rng, sub),
            [_random_node(rng, sub) for _ in range(rng.randint(0, 3))],
        )
    if kind == "construct":
        return Construct(
            _ZERO,
            rng.choice(["Ball", "Pointer", "F"]),
            _ZERO,
            [(rng.choice(_NAMES), _ZERO, _random_node(rng, sub)) for _ in range(rng.randint(0, 3))],
        )
    return ListLiteral(_ZERO, [_random_node(rng, sub) for _ in range(rng.randint(0, 3))])


def test_random_asts_survive_the_round_trip_and_the_printer_is_idempotent() -> None:
    """`parse(unparse(ast)) == ast`（位置を除く）と `unparse(parse(unparse(ast))) == unparse(ast)`。

    最小括弧の規則（左結合・cmp の非連鎖・単項の被演算子）が壊れると、ここで構造が変わる。
    """
    rng = random.Random(20260914)
    for _ in range(3000):
        node = _random_node(rng, rng.randint(0, 5))
        text = unparse(node)
        parsed = parse_expr(text)
        assert _shape(parsed) == _shape(node), text
        assert unparse(parsed) == text, text


# ---------------------------------------------------------------- writer の規則 8


def _v2_doc() -> dict:
    return {
        "$schema": "https://xtone.internal/jin/schemas/jin-v2.schema.json",
        "version": 2,
        "root": "Only",
        "stage": {"width": 64, "height": 64},
        "circles": [
            {
                "name": "Only",
                "core": "start",
                "state": [
                    {"name": "n", "type": "num", "init": " 1e3 ", "out": True},
                    {"name": "xs", "type": "list<num>", "init": "[ ]"},
                ],
                "rites": [
                    {
                        "name": "start",
                        "steps": [
                            {"do": "set", "target": "n", "expr": "(n+1)"},
                            {"do": "cast", "target": "helper", "args": ["n*2", "(n)"], "into": "n"},
                            {"do": "if", "cond": "1 +", "then": []},
                        ],
                    },
                    {
                        "name": "helper",
                        "params": [{"name": "a", "type": "num"}, {"name": "b", "type": "num"}],
                        "returns": "num",
                        "steps": [{"do": "return", "expr": "a+b"}],
                    },
                ],
                "boundary": {"guards": [{"assert": "n>=0", "message": "n  >=  0"}]},
            }
        ],
    }


def test_dumps_writes_every_expression_field_in_canonical_form() -> None:
    doc = _v2_doc()
    result = check_text(json.dumps(doc), "m.jin")
    assert result.model is not None
    out = json.loads(dumps(result.model))
    circle = out["circles"][0]
    assert circle["state"][0]["init"] == "1000"
    assert circle["state"][1]["init"] == "[]"
    steps = circle["rites"][0]["steps"]
    assert steps[0]["expr"] == "n + 1"
    assert steps[1]["args"] == ["n * 2", "n"], "list[Expr] も 1 つずつ"
    assert steps[2]["cond"] == "1 +", "構文エラーの式は元のまま（JIN201 が残る）"
    assert circle["rites"][1]["steps"][0]["expr"] == "a + b"
    assert circle["boundary"]["guards"][0]["assert"] == "n >= 0"
    assert circle["boundary"]["guards"][0]["message"] == "n  >=  0", "式でない Text は触らない"
    # 入力のモデルは書き換えない
    assert result.model.circles[0].state[0].init == " 1e3 "
    # 冪等
    assert dumps(check_text(dumps(result.model), "m.jin").model) == dumps(result.model)


def test_dumps_leaves_v1_documents_alone() -> None:
    """v1 の `Text` に印は無い。式のように見える文字列も触らない。"""
    doc = {
        "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
        "version": 1,
        "root": "A",
        "circles": [
            {
                "name": "A",
                "core": "gemini-2.5-flash",
                "description": "(a+1)  *  2",
                "state": [{"name": "s", "type": "str", "out": True}],
            }
        ],
    }
    model = JinFile.model_validate(doc)
    assert json.loads(dumps(model))["circles"][0]["description"] == "(a+1)  *  2"


def test_the_expression_fields_are_found_by_the_schema_mark() -> None:
    """規則 8 が名前でなく印で欄を見分けることの証拠: 印の付いた欄の集合はモデルから引ける。"""
    from jin_core.v2.model import CastStep, Guard, expr_fields

    assert expr_fields(CastStep) == frozenset({"target", "args", "into"})
    assert expr_fields(Guard) == frozenset({"assert"})
    assert expr_fields(JinFileV2) == frozenset()
