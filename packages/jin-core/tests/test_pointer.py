"""JSON Pointer の添字トークン判定（security review S10）。

`str.isdigit()` は ASCII 以外の数字にも True を返すが `int()` の解釈は別物になる。
`"٣"`（U+0663 アラビア数字の 3）は `isdigit()` が True で `int("٣") == 3` なので、
**原文に書かれていない要素**を指す pointer が通ってしまう。`"²"`（U+00B2）は
`isdigit()` が True でも `int()` が `ValueError` を投げ、`OpError` ではなく素の例外になる。
"""

from __future__ import annotations

import pytest
from jin_core.pointer import is_index_token, pointer_exists, resolve_pointer

DOCUMENT = {"circles": [{"name": "A"}, {"name": "B"}, {"name": "C"}, {"name": "D"}]}


@pytest.mark.parametrize("token", ["0", "1", "12", "1234"])
def test_ascii_digits_are_index_tokens(token: str) -> None:
    assert is_index_token(token) is True


@pytest.mark.parametrize(
    "token",
    [
        "٣",  # U+0663 アラビア数字。isdigit() は True で int() は 3 を返す
        "²",  # U+00B2 上付き 2。isdigit() は True で int() は ValueError
        "１",  # U+FF11 全角 1
        "-1",  # 符号つきは RFC 6901 で不正
        "--1",
        "+1",
        "01",  # 先頭 0 は RFC 6901 で不正
        "",
        "name",
        "1.0",
        " 1",
    ],
)
def test_non_ascii_or_malformed_tokens_are_rejected(token: str) -> None:
    assert is_index_token(token) is False


def test_arabic_digit_does_not_resolve_to_a_real_element() -> None:
    """`"٣"` が通ると `/circles/٣` が 4 番目の circle を指してしまう。"""
    assert resolve_pointer(DOCUMENT, "/circles/3") == {"name": "D"}
    with pytest.raises(KeyError):
        resolve_pointer(DOCUMENT, "/circles/٣")
    assert pointer_exists(DOCUMENT, "/circles/٣") is False


def test_superscript_two_raises_key_error_not_value_error() -> None:
    """`int("²")` は ValueError。判定側で弾かないと素の例外が呼び出し元へ抜ける。"""
    with pytest.raises(KeyError):
        resolve_pointer(DOCUMENT, "/circles/²")


def test_leading_zero_is_rejected() -> None:
    with pytest.raises(KeyError):
        resolve_pointer(DOCUMENT, "/circles/01")
