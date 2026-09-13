"""JIL の禁止語走査（jil.md §2）。走査が**本物**を落とし、フィールド名を落とさないことを固定する。"""

from __future__ import annotations

import pytest
from jin_wasm.jil import (
    JIL_FORBIDDEN,
    TRACE_FIELDS,
    TRACE_KINDS,
    forbidden_uses,
    strip_comments_and_strings,
)


@pytest.mark.parametrize(
    "snippet",
    [
        "local k = next(t)",
        "for k, v in pairs(t) do end",
        "local t0 = os.time()",
        "io.write('x')",
        "debug.sethook(f)",
        "setmetatable(t, mt)",
        "local f = load('return 1')",
        "require('x')",
        "collectgarbage()",
        "local n = select('#', a)",
        "local function f(...) end",
        "local s = string.dump(f)",
        "local co = coroutine.wrap(f)",
        "local p = package.loaded",
        "rawset(t, 'k', 1)",
    ],
)
def test_the_scan_catches_real_uses(snippet: str) -> None:
    uses = forbidden_uses("local t = {}\n" + snippet + "\n")
    assert uses, snippet
    assert uses[0].line == 2


@pytest.mark.parametrize(
    "snippet",
    [
        "local r = H.random.next()",  # フィールド名
        "local d = manifest.debug",  # フィールド名
        "local H = { random = { next = f, range = g } }",  # テーブルコンストラクタのキー
        "obj:load()",  # メソッド名
        "-- next(t) はコメント",
        'local s = "next(t) pairs(t) ... os.time()"',
        "local s = [[\nnext(t)\n]]",
        "--[[ os.time()\n require('x') ]]",
        "local nexts = 1",  # 前方一致ではない
        "local x = t.next == 1",  # `==` はキーではない",
    ],
)
def test_the_scan_ignores_field_names_comments_and_strings(snippet: str) -> None:
    assert forbidden_uses(snippet + "\n") == []


def test_strip_keeps_line_numbers() -> None:
    text = 'a = "x\\"y" -- c\nb = [[\nz\n]]\nc = 1\n'
    stripped = strip_comments_and_strings(text)
    assert stripped.count("\n") == text.count("\n")
    assert "z" not in stripped
    assert "c = 1" in stripped


def test_forbidden_list_has_no_duplicates_and_trace_kinds_are_unique() -> None:
    assert len(set(JIL_FORBIDDEN)) == len(JIL_FORBIDDEN)
    assert len(set(TRACE_KINDS)) == len(TRACE_KINDS)
    assert TRACE_FIELDS[0] == "seq" and TRACE_FIELDS[-1] == "output"
