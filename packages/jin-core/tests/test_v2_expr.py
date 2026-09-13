"""Jin v2 の葉の式（docs/spec/v2/expr.md）: 文法・位置・型検査・定数式・位置換算。"""

from __future__ import annotations

import pytest
from jin_core.diagnostics import Position, Range
from jin_core.v2.expr import (
    Binary,
    Call,
    Construct,
    ExprSyntaxError,
    FieldAccess,
    Index,
    ListLiteral,
    Name,
    Number,
    Scope,
    Span,
    String,
    Unary,
    check_expr,
    is_constant,
    is_place,
    parse_expr,
    place_root,
    walk,
)
from jin_core.v2.spans import decode_offsets, span_to_range


def scope() -> Scope:
    return Scope(
        locals={"dt": "num", "xs": "list<num>", "names": "list<str>"},
        state={"ball": "Ball", "score": "num", "paddle": "num", "flag": "bool"},
        sigils={
            "input": ("host", "input"),
            "canvas": ("host", "canvas"),
            "helper": ("summon", "Lib", "clamp"),
        },
        public={"Play": {"score": "num"}, "Result": {"quit": "bool"}},
        forms={
            "Ball": {"x": "num", "y": "num", "vx": "num", "vy": "num"},
            "Pointer": {"x": "num", "y": "num", "down": "bool"},
        },
        circle="Play",
        circles=frozenset({"Play", "Result", "Game"}),
    )


def codes(text: str, expected: str | None = None) -> list[str]:
    return [issue.code for issue in check_expr(parse_expr(text), scope(), expected).issues]


def type_of(text: str, expected: str | None = None) -> str | None:
    result = check_expr(parse_expr(text), scope(), expected)
    assert result.ok, result.issues
    return result.type


# ---------------------------------------------------------------- 文法と位置


def test_precedence_and_associativity() -> None:
    node = parse_expr("1 + 2 * 3 - 4")
    assert isinstance(node, Binary) and node.op == "-"
    assert isinstance(node.left, Binary) and node.left.op == "+"
    assert isinstance(node.left.right, Binary) and node.left.right.op == "*"
    node = parse_expr("not a and b or c")
    assert isinstance(node, Binary) and node.op == "or"
    assert isinstance(node.left, Binary) and node.left.op == "and"
    assert isinstance(node.left.left, Unary) and node.left.left.op == "not"


def test_keywords_do_not_split_identifiers() -> None:
    node = parse_expr("andy + orb - nota")
    names = [n.name for n in walk(node) if isinstance(n, Name)]
    assert names == ["andy", "orb", "nota"]
    assert isinstance(parse_expr("true"), type(parse_expr("false")))


def test_postfix_chain_and_spans() -> None:
    node = parse_expr("xs[i].x")
    assert isinstance(node, FieldAccess)
    assert node.name == "x" and node.name_span == Span(6, 7)
    assert isinstance(node.obj, Index)
    assert node.span == Span(0, 7)
    call = parse_expr('input.key("ArrowLeft")')
    assert isinstance(call, Call) and isinstance(call.callee, FieldAccess)
    assert isinstance(call.args[0], String) and call.args[0].value == "ArrowLeft"
    assert call.args[0].span == Span(10, 21)


def test_construct_and_list_literals() -> None:
    node = parse_expr("Ball{x: 1, y: 2, vx: 3, vy: 4}")
    assert isinstance(node, Construct)
    assert [name for name, _, _ in node.fields] == ["x", "y", "vx", "vy"]
    assert node.form_span == Span(0, 4)
    empty = parse_expr("Ball{}")
    assert isinstance(empty, Construct) and empty.fields == []
    lst = parse_expr("[1, 2.5, 3e2]")
    assert isinstance(lst, ListLiteral) and [i.value for i in lst.items] == [1.0, 2.5, 300.0]
    assert isinstance(parse_expr("[]"), ListLiteral)


@pytest.mark.parametrize(
    ("text", "position"),
    [
        ("a < b < c", 6),  # 比較は連鎖しない
        ("1 +", 3),
        ("[1, 2,]", 6),
        ("'x'", 0),  # 文字列は二重引用符だけ
        ("a.1", 2),  # 欄名は識別子
        ("f(,)", 2),
    ],
)
def test_syntax_errors_carry_positions(text: str, position: int) -> None:
    with pytest.raises(ExprSyntaxError) as info:
        parse_expr(text)
    assert info.value.span.start == position
    assert info.value.hint.startswith("期待:")


def test_whitespace_around_dots_is_allowed() -> None:
    assert isinstance(parse_expr("a . b"), FieldAccess)


def test_newline_and_empty_are_syntax_errors() -> None:
    with pytest.raises(ExprSyntaxError) as info:
        parse_expr("a +\nb")
    assert info.value.span == Span(3, 4)
    with pytest.raises(ExprSyntaxError):
        parse_expr("   ")


def test_isolated_number_and_string_are_nodes_with_spans() -> None:
    assert parse_expr("42") == Number(Span(0, 2), 42.0)
    assert isinstance(parse_expr('"a\\"b"'), String)
    assert parse_expr('"a\\"b"').value == 'a"b'


# ---------------------------------------------------------------- 型検査


def test_types_of_well_formed_expressions() -> None:
    assert type_of("ball.x + ball.vx * dt") == "num"
    assert type_of('input.key("ArrowLeft") and ball.y > 170') == "bool"
    assert type_of('"SCORE " ++ str(score)') == "str"
    assert type_of("Result.quit") == "bool"
    assert type_of("input.pointer().down") == "bool"
    assert type_of("max(0, paddle - 180 * dt)") == "num"
    assert type_of("len(xs) + len(names)") == "num"
    assert type_of('contains(names, "a")') == "bool"
    assert type_of("xs[0]") == "num"
    assert type_of("[[1], [2]]") == "list<list<num>>"
    assert type_of("[]", "list<Ball>") == "list<Ball>"
    assert type_of("Ball{x: 1, y: 2, vx: 3, vy: 4}") == "Ball"
    assert type_of("-score % 2 == 0") == "bool"
    assert type_of("flag == false") == "bool"


@pytest.mark.parametrize(
    ("text", "expected_codes"),
    [
        ("score ++ 1", ["JIN202", "JIN202"]),
        ("flag + 1", ["JIN202"]),
        ("ball == ball", ["JIN202"]),
        ("score < flag", ["JIN202"]),
        ("not score", ["JIN202"]),
        ("Play.score", ["JIN203"]),
        ("Game.x", ["JIN203"]),
        ("Result.score", ["JIN203"]),
        ("ball.z", ["JIN203"]),
        ("score.x", ["JIN202"]),
        ("padle", ["JIN203"]),
        ("canvas.rect(1, 2, 3, 4)", ["JIN202"]),
        ("audio.tone(1, 2)", ["JIN204"]),
        ("audio", ["JIN203"]),
        ('input.key("Foo")', ["JIN205"]),
        ('input.kye("Space")', ["JIN205"]),
        ('input.key("Space", 1)', ["JIN205"]),
        ("input.key(1)", ["JIN202"]),
        ("helper(1, 2, 3)", ["JIN203"]),
        ("helper.clamp(1)", ["JIN202"]),
        ("input", ["JIN202"]),
        ("input.key", ["JIN202"]),
        ("Ball{x: 1, y: 2}", ["JIN202"]),
        ("Ball{x: 1, y: 2, vx: 3, vy: 4, w: 5}", ["JIN202"]),
        ("Ball{x: 1, x: 2, y: 2, vx: 3, vy: 4}", ["JIN202"]),
        ("Bal{x: 1}", ["JIN203"]),
        ("Ball", ["JIN203"]),
        ('[1, "a"]', ["JIN202"]),
        ("[]", ["JIN202"]),
        ('xs["a"]', ["JIN202"]),
        ("score[0]", ["JIN202"]),
        ("abs(1, 2)", ["JIN202"]),
        ('abs("a")', ["JIN202"]),
        ("len(1)", ["JIN202"]),
        ("str(ball)", ["JIN202"]),
        ('contains(xs, "a")', ["JIN202"]),
        ("push(xs, 1)", ["JIN202"]),
        ("dt(1)", ["JIN202"]),
        ("foo(1)", ["JIN203"]),
        ("(1)(2)", ["JIN202"]),
    ],
)
def test_type_issues(text: str, expected_codes: list[str]) -> None:
    assert codes(text) == expected_codes


def test_expected_type_mismatch_is_reported_once_at_the_root() -> None:
    result = check_expr(parse_expr("score + 1"), scope(), "bool")
    assert [i.code for i in result.issues] == ["JIN202"]
    assert result.issues[0].span == Span(0, 9)


def test_short_circuit_rhs_is_still_type_checked() -> None:
    assert codes("flag or score") == ["JIN202"]


def test_checker_annotates_node_types_for_rename() -> None:
    node = parse_expr("ball.x + xs[0]")
    check_expr(node, scope())
    assert isinstance(node, Binary)
    assert node.left.type == "num"
    assert isinstance(node.left, FieldAccess) and node.left.obj.type == "Ball"


# ---------------------------------------------------------------- 定数式・代入先


def test_constant_expressions() -> None:
    assert is_constant(parse_expr("Ball{x: 160, y: -40, vx: 90, vy: 70}"))
    assert is_constant(parse_expr("[1, 2, max(3, 4)]"))
    assert is_constant(parse_expr('"a" ++ "b"')) is False  # 演算子は定数式に含めない
    assert is_constant(parse_expr("score")) is False
    assert is_constant(parse_expr("random.next()")) is False


def test_constant_scope_rejects_identifiers_and_abilities() -> None:
    constant = scope()
    constant.constant = True
    assert [i.code for i in check_expr(parse_expr("score + 1"), constant).issues] == ["JIN250"]
    assert [i.code for i in check_expr(parse_expr('input.key("Space")'), constant).issues] == [
        "JIN250"
    ]
    assert check_expr(parse_expr("Ball{x: 1, y: 2, vx: 3, vy: 4}"), constant).ok


def test_place_expressions() -> None:
    assert is_place(parse_expr("ball.x"))
    assert is_place(parse_expr("xs[i].y"))
    assert is_place(parse_expr("score"))
    assert is_place(parse_expr("Play.score"))  # 形としては place（陣名は段 3 が弾く）
    assert not is_place(parse_expr("f(x)"))
    assert not is_place(parse_expr("1"))
    root = place_root(parse_expr("xs[0].pos.x"))
    assert isinstance(root, Name) and root.name == "xs"


# ---------------------------------------------------------------- 位置換算（spans.py）


def test_decode_offsets_follow_escapes() -> None:
    literal = '"a\\"b\\u3042c\\ud83d\\ude00d"'
    # 復号: a " b あ c 😀 d  → 7 文字
    offsets = decode_offsets(literal)
    assert offsets == [1, 2, 4, 5, 11, 12, 24, 25]


def test_decode_offsets_rejects_non_literals() -> None:
    with pytest.raises(ValueError):
        decode_offsets("abc")
    with pytest.raises(ValueError):
        decode_offsets('"abc\\"')


def test_span_to_range_maps_into_the_literal() -> None:
    literal = '"ball.x + \\"s\\""'
    offsets = decode_offsets(literal)
    literal_range = Range(Position(12, 20), Position(12, 20 + len(literal)))
    # 復号後 "ball.x + \"s\"" の 5..6 は 'x'
    assert span_to_range(literal_range, offsets, 5, 6) == Range(Position(12, 26), Position(12, 27))
    # 末尾を超える区間はリテラルの終端に丸める
    assert span_to_range(literal_range, offsets, 100, 200).end.col == 20 + len(literal) - 1
