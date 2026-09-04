"""位置付きパーサと pointer→range 対応表（ADR-006 / DP-JIN-POINTER-RANGE-01）のテスト。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jin_core.parser import MAX_NESTING_DEPTH, JinSyntaxError, parse_text
from jin_core.pointer import escape_token, join, resolve_pointer, split_pointer

REPO_ROOT = Path(__file__).resolve().parents[3]


# --------------------------------------------------------------------------------------
# JSON Pointer（RFC 6901）
# --------------------------------------------------------------------------------------
def test_root_pointer_is_empty_string() -> None:
    assert join("", "circles") == "/circles"
    assert split_pointer("") == []


def test_escape_token() -> None:
    assert escape_token("a/b") == "a~1b"
    assert escape_token("a~b") == "a~0b"


def test_split_unescapes() -> None:
    assert split_pointer("/a~1b/c~0d") == ["a/b", "c~d"]


def test_resolve_pointer() -> None:
    doc = {"circles": [{"name": "A"}]}
    assert resolve_pointer(doc, "") is doc
    assert resolve_pointer(doc, "/circles/0/name") == "A"


def test_resolve_pointer_missing_raises() -> None:
    with pytest.raises(KeyError):
        resolve_pointer({"a": 1}, "/b")


# --------------------------------------------------------------------------------------
# パース結果の値
# --------------------------------------------------------------------------------------
def test_parses_scalars_like_json() -> None:
    text = '{"s": "x", "i": 1, "f": 1.5, "t": true, "f2": false, "n": null, "a": [], "o": {}}'
    result = parse_text(text)
    assert result.value == json.loads(text)


def test_parses_escapes_like_json() -> None:
    text = r'{"s": "a\nb\t\"c\\dあ🐉"}'
    assert parse_text(text).value == json.loads(text)


def test_parses_non_ascii_literally() -> None:
    text = '{"s": "調査 \U00020bb7"}'
    assert parse_text(text).value == json.loads(text)


# --------------------------------------------------------------------------------------
# 位置（1 始まり / end 排他 / コードポイント単位）
# --------------------------------------------------------------------------------------
def test_range_is_one_based_and_end_exclusive() -> None:
    text = '{"a": "xy"}'
    table = parse_text(text).table
    rng = table.value_ranges["/a"]
    assert (rng.start.line, rng.start.col) == (1, 7)
    assert (rng.end.line, rng.end.col) == (1, 11)


def test_key_range_is_recorded_separately() -> None:
    text = '{"a": "xy"}'
    table = parse_text(text).table
    key = table.key_ranges["/a"]
    assert (key.start.col, key.end.col) == (2, 5)


def test_columns_count_code_points_not_bytes() -> None:
    """`{"あ": 1}` の `1` は 7 **文字**目。UTF-8 バイト数で数えるなら 9 になる。"""
    text = '{"あ": 1}'
    table = parse_text(text).table
    rng = table.value_ranges["/あ"]
    assert rng.start.col == 7
    assert rng.end.col == 8


def test_multiline_positions() -> None:
    text = '{\n  "a": [\n    1,\n    2\n  ]\n}\n'
    table = parse_text(text).table
    assert table.value_ranges["/a/1"].start.line == 4
    assert table.value_ranges["/a"].start.line == 2
    assert table.value_ranges["/a"].end.line == 5


def test_root_pointer_is_in_table() -> None:
    table = parse_text('{"a": 1}').table
    assert "" in table.value_ranges


# --------------------------------------------------------------------------------------
# 対応表の網羅性
# --------------------------------------------------------------------------------------
def test_table_covers_every_source_pointer() -> None:
    text = '{"a": [{"b": 1}, 2], "c": {"d": null}}'
    result = parse_text(text)
    expected = {"", "/a", "/a/0", "/a/0/b", "/a/1", "/c", "/c/d"}
    assert set(result.table.value_ranges) == expected


def test_table_pointers_resolve_in_parsed_value() -> None:
    result = parse_text('{"a": [{"b": 1}], "c": {}}')
    for pointer in result.table.value_ranges:
        resolve_pointer(result.value, pointer)


def test_escaped_key_becomes_escaped_pointer() -> None:
    table = parse_text('{"a/b": 1}').table
    assert "/a~1b" in table.value_ranges


def test_resolve_walks_up_for_unknown_pointer() -> None:
    """missing key の診断は存在しない pointer を指す。親の範囲へフォールバックする。"""
    table = parse_text('{"a": {"b": 1}}').table
    rng = table.resolve("/a/zzz")
    assert rng == table.value_ranges["/a"]


def test_resolve_falls_back_to_root() -> None:
    table = parse_text('{"a": 1}').table
    assert table.resolve("/nope") == table.value_ranges[""]


# --------------------------------------------------------------------------------------
# JIN001（構文エラー）
# --------------------------------------------------------------------------------------
def test_syntax_error_has_position_and_hint() -> None:
    with pytest.raises(JinSyntaxError) as excinfo:
        parse_text('{"a": }')
    error = excinfo.value
    assert error.range.start.line == 1
    assert error.range.start.col == 7
    assert "期待" in error.hint


def test_trailing_comma_is_a_syntax_error() -> None:
    with pytest.raises(JinSyntaxError):
        parse_text('{"a": 1,}')


def test_unterminated_string_is_a_syntax_error() -> None:
    with pytest.raises(JinSyntaxError):
        parse_text('{"a": "x}')


def test_invalid_escape_is_a_syntax_error() -> None:
    """lark の ESCAPED_STRING は \\x を通してしまうので、json.loads で弾いて JIN001 にする。"""
    with pytest.raises(JinSyntaxError):
        parse_text(r'{"a": "\x41"}')


def test_raw_control_character_in_string_is_a_syntax_error() -> None:
    with pytest.raises(JinSyntaxError):
        parse_text('{"a": "x\ty"}')


def test_empty_input_is_a_syntax_error() -> None:
    with pytest.raises(JinSyntaxError):
        parse_text("")


def test_top_level_non_object_is_parsed() -> None:
    """JSON としては妥当なので JIN001 にはしない（スキーマ違反 JIN002 として後段が扱う）。"""
    assert parse_text("[1]").value == [1]


# --------------------------------------------------------------------------------------
# examples
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "path", sorted((REPO_ROOT / "examples").glob("*/*.jin")), ids=lambda p: p.name
)
def test_examples_parse_and_match_stdlib_json(path: Path) -> None:
    raw = path.read_text(encoding="utf-8")
    result = parse_text(raw)
    assert result.value == json.loads(raw)
    for pointer in result.table.value_ranges:
        resolve_pointer(result.value, pointer)


# --------------------------------------------------------------------------------------
# 修正ラウンド 1 の回帰テスト
# --------------------------------------------------------------------------------------
def test_unexpected_characters_reports_the_actual_character() -> None:
    """C-1: 字句段のエラーで「入力の終わり」と誤報しない。

    `UnexpectedCharacters` は `.token` を持たず `.char` を持つ。`.token` だけを見ると
    どんな不正文字でも「入力の終わり」と表示され、range も幅 1 で固定される。
    修正前はこの経路のテストが 1 件も無かった。
    """
    with pytest.raises(JinSyntaxError) as caught:
        parse_text('{"a": @}')
    error = caught.value
    assert "入力の終わり" not in error.message
    assert "'@'" in error.message
    assert error.range.start.line == 1
    assert error.range.start.col == 7


def test_unexpected_token_still_reports_end_of_input() -> None:
    """C-1: 本当に入力が尽きたときだけ「入力の終わり」と言う。"""
    with pytest.raises(JinSyntaxError) as caught:
        parse_text('{"a": 1')
    assert "入力の終わり" in caught.value.message


@pytest.mark.parametrize("source", ['{"a": @}', '{"a" 1}', '{"a": 1', '{"a": 1,}'])
def test_syntax_hint_has_no_raw_lark_terminal_names(source: str) -> None:
    """C-1: hint に lark の終端名（LBRACE / RSQB / $END …）を出さない。

    要件書 §5「hint は LLM がそのまま編集に使うので具体的な値にする」。
    """
    with pytest.raises(JinSyntaxError) as caught:
        parse_text(source)
    hint = caught.value.hint
    for terminal in ("LBRACE", "RBRACE", "LSQB", "RSQB", "COMMA", "COLON", "$END"):
        assert terminal not in hint, hint


def test_duplicate_key_is_a_syntax_error() -> None:
    """C-2: 同じオブジェクト内の重複キーを黙って後勝ちにしない。

    後勝ちにすると 1 つの pointer が 2 つの値を持ちうることになり、
    docs/spec/model.md §6「pointer は 1 つの値を一意に指す」が破れる。
    """
    with pytest.raises(JinSyntaxError) as caught:
        parse_text('{\n  "a": 1,\n  "a": 2\n}')
    error = caught.value
    assert "'a'" in error.message
    # range は **2 回目**のキーを指す（直せる場所を指す）。
    assert (error.range.start.line, error.range.start.col) == (3, 3)
    # hint は最初の出現位置を教える。
    assert "2 行" in error.hint


def test_duplicate_key_in_a_nested_object_is_detected() -> None:
    with pytest.raises(JinSyntaxError):
        parse_text('{"outer": {"k": 1, "k": 2}}')


def test_same_key_in_sibling_objects_is_fine() -> None:
    """重複検査はオブジェクト単位。兄弟オブジェクトで同じキーが出るのは正当。"""
    result = parse_text('[{"k": 1}, {"k": 2}]')
    assert result.value == [{"k": 1}, {"k": 2}]


def test_deep_nesting_becomes_a_diagnostic_not_a_recursion_error() -> None:
    """S4: 深い入れ子で `RecursionError` を素通しさせない。

    修正前は `_walk` が無制限に再帰し、1000 段で `RecursionError` の
    トレースバックがそのまま表に出ていた（fail-open）。
    """
    source = "[" * (MAX_NESTING_DEPTH + 5) + "]" * (MAX_NESTING_DEPTH + 5)
    with pytest.raises(JinSyntaxError) as caught:
        parse_text(source)
    assert "入れ子" in caught.value.message


def test_nesting_just_below_the_limit_is_accepted() -> None:
    source = "[" * MAX_NESTING_DEPTH + "]" * MAX_NESTING_DEPTH
    parse_text(source)  # 例外が出ないこと


def test_crlf_is_preserved_in_the_parsed_text() -> None:
    """D-2: CRLF を LF に畳まずに解析できる（畳むのは読み手の責務ではない）。"""
    result = parse_text('{\r\n  "a": 1\r\n}')
    assert result.value == {"a": 1}
    assert result.table.value_ranges["/a"].start.line == 2


# --------------------------------------------------------------------------------------
# 修正ラウンド 2: BOM（correctness review E-5 の残件）
# --------------------------------------------------------------------------------------
def test_utf8_bom_is_reported_with_a_specific_message() -> None:
    """E-5: BOM は JSON テキストの一部ではない（RFC 8259 §8.1）。

    黙って剥がすと `jin fmt` が頼まれていないバイト列の変更をしたことになるので、
    段 1 の JIN001 として落とす。修正前は BOM のテストが 1 件も無く、
    メッセージも `'\\ufeff' はここに置けません` という読み手に伝わらないものだった。
    """
    with pytest.raises(JinSyntaxError) as caught:
        parse_text('﻿{"a": 1}')
    error = caught.value
    assert "BOM" in error.message
    assert "U+FEFF" in error.message
    assert "BOM なし" in error.hint
    assert (error.range.start.line, error.range.start.col) == (1, 1)


def test_bom_in_the_middle_is_not_treated_as_a_bom() -> None:
    """E-5: BOM 扱いにするのは**先頭**だけ。文字列の中の U+FEFF は普通の文字として通す。"""
    result = parse_text('{"a": "x﻿y"}')
    assert result.value == {"a": "x﻿y"}
