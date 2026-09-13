"""式の中の位置 → JSON 文字列リテラルの中の位置（docs/spec/v2/expr.md §6）。

式は `.jin` の JSON 文字列の**中**にある。式文法が返す位置は「復号後の文字列のコードポイント添字」
なので、診断の `range` にするには原文のリテラル（`"…"`、エスケープ込み）の何列目かへ写す必要がある。
**その換算はこのモジュール 1 か所だけ**が行う（v1 の `jin_lsp.positions` が UTF-16 換算を
1 か所に閉じるのと同じ理由: 2 か所で書くと片方が古くなる）。

列は 1 始まり・コードポイント単位・end 排他（`jin_core.diagnostics` と同じ）。
"""

from __future__ import annotations

from jin_core.diagnostics import Position, Range

#: JSON の 1 文字エスケープ（`\"` など）。`\u` は別扱い。
_SIMPLE_ESCAPES = frozenset('"\\/bfnrt')


def decode_offsets(literal: str) -> list[int]:
    """JSON 文字列リテラル（引用符込み）について、復号後の i 文字目が原文の何文字目から始まるかを返す。

    戻り値の長さは「復号後の文字数 + 1」で、最後の要素は閉じ引用符の位置（= 末尾の文字の end）。
    サロゲートペア（`\\uD83D\\uDE00`）は復号後 1 文字なので 12 文字ぶんを 1 つに畳む。
    リテラルの形が壊れていれば ValueError（段 1 を通った文字列には起きない）。
    """
    if len(literal) < 2 or literal[0] != '"' or literal[-1] != '"':
        raise ValueError("JSON 文字列リテラルではありません")
    offsets: list[int] = []
    i = 1
    end = len(literal) - 1
    while i < end:
        offsets.append(i)
        ch = literal[i]
        if ch != "\\":
            i += 1
            continue
        if i + 1 >= end:
            raise ValueError("エスケープが途中で終わっています")
        nxt = literal[i + 1]
        if nxt in _SIMPLE_ESCAPES:
            i += 2
            continue
        if nxt == "u":
            i += 6
            code = int(literal[i - 4 : i], 16)
            if 0xD800 <= code <= 0xDBFF and literal[i : i + 2] == "\\u":
                low = int(literal[i + 2 : i + 6], 16)
                if 0xDC00 <= low <= 0xDFFF:
                    i += 6
            continue
        raise ValueError(f"未知のエスケープ \\{nxt}")
    offsets.append(end)
    return offsets


def span_to_range(literal_range: Range, offsets: list[int], start: int, end: int) -> Range:
    """復号後の区間 [start, end) を、リテラルの `Range`（原文の位置）へ写す。

    区間が復号後の長さを超えるときはリテラル全体に丸める（構文エラーの位置が末尾を指すことがある）。
    リテラルは 1 行に収まる（JSON 文字列に生の改行は無い）ので行は変わらない。
    """
    last = len(offsets) - 1
    start = max(0, min(start, last))
    end = max(start, min(end, last))
    line = literal_range.start.line
    base = literal_range.start.col
    return Range(Position(line, base + offsets[start]), Position(line, base + offsets[end]))


__all__ = ["decode_offsets", "span_to_range"]
