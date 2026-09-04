"""位置情報付き JSON パーサ（Lark）。

ADR-006 / DP-JIN-POINTER-RANGE-01（案 B）:
**Lark の木を 1 回走査して JSON Pointer → range の完全な対応表を作る**。
Pydantic の `ValidationError.loc` は `jin_core.pointer.loc_to_pointer` で pointer に変換し、この表を引く。

lark 1.3.1 の実測（`delivery/20260904-1445-jin/lsp-api-probe.md` §3 と本ラウンドの再確認）:

- JSON 文法は同梱されていないので自前で書く（`%import common.ESCAPED_STRING / SIGNED_NUMBER / WS` は使える）
- `propagate_positions=True` で `Tree.meta` に `line` / `column` / `end_line` / `end_column` が入る
- 位置が無い枝では `meta.empty` が True になるので参照前に確認する
- **1 始まりで `end_column` は排他**（実測: `'{"a": "xy"}'` の `"a"` が L1C2-L1C5、`22` が C22-C24）

文字列と数値の**値の解釈は `json.loads` に委ねる**。lark の `ESCAPED_STRING` は `\\x41` のような
不正エスケープや生の制御文字を通してしまうため、自前でアンエスケープを書くとそこがバグの温床になる。
`json.loads` が拒否したものは JIN001（構文エラー）として位置つきで返す。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from lark import Lark, Token, Tree
from lark.exceptions import UnexpectedInput

from jin_core.diagnostics import Position, Range
from jin_core.pointer import join, parent_of

#: `.jin` の JSON 文法。スカラを全て終端にしているのは、
#: `"true" -> true` のような空の別名ツリーだと `meta.empty` になって位置が取れないため。
JIN_JSON_GRAMMAR = r"""
?value: object | array | STRING | NUMBER | TRUE | FALSE | NULL

object: "{" [pair ("," pair)*] "}"
pair: STRING ":" value
array: "[" [value ("," value)*] "]"

TRUE: "true"
FALSE: "false"
NULL: "null"
STRING: ESCAPED_STRING
NUMBER: SIGNED_NUMBER

%import common.ESCAPED_STRING
%import common.SIGNED_NUMBER
%import common.WS
%ignore WS
"""

_PARSER = Lark(
    JIN_JSON_GRAMMAR,
    start="value",
    parser="lalr",
    propagate_positions=True,
)

#: 値の入れ子の上限。決定根拠は
#: delivery/20260904-1445-jin/decision-conformance.md（DP-JIN-DEPTHLIMIT-01）。
#: 妥当な `.jin` の最大は 7 段（`/circles/N/boundary/guards/M/on`）なので約 9 倍の余裕がある。
MAX_NESTING_DEPTH = 64

#: lark の終端名 → 人間が読める表記。診断の hint に生の終端名を出さないための対応表。
_TERMINAL_LABELS = {
    "LBRACE": "'{'",
    "RBRACE": "'}'",
    "LSQB": "'['",
    "RSQB": "']'",
    "COMMA": "','",
    "COLON": "':'",
    "STRING": "文字列",
    "NUMBER": "数値",
    "TRUE": "true",
    "FALSE": "false",
    "NULL": "null",
    "$END": "入力の終わり",
}


class JinSyntaxError(Exception):
    """JIN001。JSON として読めない。

    位置と「何が来るはずだったか」を持つ。LLM がそのまま直せるよう hint は具体値にする（NFR-LLM-001）。
    """

    def __init__(self, message: str, range_: Range, hint: str) -> None:
        super().__init__(message)
        self.message = message
        self.range = range_
        self.hint = hint


@dataclass(slots=True)
class PointerTable:
    """JSON Pointer → range の対応表。

    - `value_ranges`: その pointer が指す**値**の範囲
    - `key_ranges`: その pointer のメンバの**キー**の範囲（配列要素にはキーが無いので入らない）
    """

    value_ranges: dict[str, Range] = field(default_factory=dict)
    key_ranges: dict[str, Range] = field(default_factory=dict)

    def resolve(self, pointer: str) -> Range:
        """pointer の範囲を返す。無ければ祖先へ遡り、最後はルートへ落ちる。

        必須キー欠落（Pydantic の `missing`）は存在しない pointer を指すため、この遡りが要る。
        """
        current: str | None = pointer
        while current is not None:
            if current in self.value_ranges:
                return self.value_ranges[current]
            current = parent_of(current)
        return self.value_ranges[""]

    def resolve_key_or_value(self, pointer: str) -> Range:
        """キーの範囲を優先して返す（未知キーの診断はキーを指したほうが読みやすい）。"""
        if pointer in self.key_ranges:
            return self.key_ranges[pointer]
        return self.resolve(pointer)


@dataclass(slots=True)
class ParseResult:
    """素の JSON 値と pointer→range 対応表。"""

    value: Any
    table: PointerTable


def _range_of_token(token: Token) -> Range:
    return Range(
        Position(int(token.line), int(token.column)),
        Position(int(token.end_line), int(token.end_column)),
    )


def _range_of_tree(tree: Tree) -> Range:
    meta = tree.meta
    if meta.empty:  # pragma: no cover - 本文法では空の枝が出ない想定だが規約どおり確認する
        return Range(Position(1, 1), Position(1, 1))
    return Range(
        Position(int(meta.line), int(meta.column)),
        Position(int(meta.end_line), int(meta.end_column)),
    )


def _decode_scalar(token: Token) -> Any:
    """スカラの値を `json.loads` に委ねる。失敗は JIN001。"""
    text = str(token)
    try:
        return json.loads(text)
    except ValueError as exc:
        raise JinSyntaxError(
            f"JSON として解釈できないリテラルです: {text[:40]}",
            _range_of_token(token),
            f"期待: JSON の妥当なリテラル（{exc}）",
        ) from exc


def _walk(node: Any, pointer: str, table: PointerTable, depth: int = 0) -> Any:
    if isinstance(node, Token):
        table.value_ranges[pointer] = _range_of_token(node)
        return _decode_scalar(node)

    assert isinstance(node, Tree)
    if depth >= MAX_NESTING_DEPTH:
        # 再帰で降りる前に止める。止めないと Python の再帰上限に当たって
        # RecursionError が診断ではなくトレースバックとして表に出る（fail-open）。
        raise JinSyntaxError(
            f"入れ子が深すぎます（上限 {MAX_NESTING_DEPTH} 段）",
            _range_of_tree(node),
            f"期待: 入れ子は {MAX_NESTING_DEPTH} 段まで。`.jin` の正しい構造は最大 7 段です",
        )
    table.value_ranges[pointer] = _range_of_tree(node)

    if node.data == "object":
        obj: dict[str, Any] = {}
        seen: dict[str, Token] = {}
        for pair in node.children:
            if pair is None:  # 空オブジェクト `{}` は children=[None]
                continue
            key_token, value_node = pair.children
            key = _decode_scalar(key_token)
            if key in seen:
                # RFC 8259 は重複キーの扱いを未定義にしている。黙って後勝ちにすると
                # 「1 つの pointer が 1 つの値を指す」（docs/spec/model.md §6）が破れ、
                # 診断の range が原文の別の場所を指す。段 1 で落とす。
                first = seen[key]
                raise JinSyntaxError(
                    f"キー {key!r} が同じオブジェクト内で 2 回現れています",
                    _range_of_token(key_token),
                    f"期待: キーは 1 回だけ。最初の {key!r} は "
                    f"{first.line} 行 {first.column} 列にあります。どちらかを消すこと",
                )
            seen[key] = key_token
            child_pointer = join(pointer, key)
            table.key_ranges[child_pointer] = _range_of_token(key_token)
            obj[key] = _walk(value_node, child_pointer, table, depth + 1)
        return obj

    if node.data == "array":
        arr: list[Any] = []
        index = 0
        for item in node.children:
            if item is None:  # 空配列 `[]` は children=[None]
                continue
            arr.append(_walk(item, join(pointer, index), table, depth + 1))
            index += 1
        return arr

    raise AssertionError(f"未知の文法ノードです: {node.data}")  # pragma: no cover


def _readable(terminal: str) -> str:
    """lark の終端名を、書いた人がそのまま直せる表記に変換する（NFR-LLM-001）。"""
    return _TERMINAL_LABELS.get(terminal, terminal)


def _syntax_error_from_lark(text: str, exc: UnexpectedInput) -> JinSyntaxError:
    line = getattr(exc, "line", None) or 1
    column = getattr(exc, "column", None) or 1
    expected = sorted(getattr(exc, "expected", None) or getattr(exc, "allowed", None) or [])
    # UnexpectedToken は `.token`、UnexpectedCharacters は `.char` を持つ。
    # `.token` だけを見ると、字句段のエラー（`@` など）が「入力の終わり」と誤表示される。
    token = getattr(exc, "token", None)
    char = getattr(exc, "char", None)
    if token is not None:
        found = "入力の終わり" if token.type == "$END" else repr(str(token))
        width = max(1, len(str(token)))
    elif char is not None:
        found = repr(str(char))
        width = max(1, len(str(char)))
    else:  # pragma: no cover - lark はどちらかを必ず持つ
        found = "入力の終わり"
        width = 1
    labels = [_readable(name) for name in expected]
    hint = f"期待: {', '.join(labels)}" if labels else "期待: JSON の値・','・':' などの区切り"
    end_col = column + width
    return JinSyntaxError(
        f"JSON 構文エラー: {found} はここに置けません",
        Range(Position(int(line), int(column)), Position(int(line), int(end_col))),
        hint,
    )


def parse_text(text: str) -> ParseResult:
    """テキストをパースして値と pointer→range 対応表を返す。

    失敗時は `JinSyntaxError`（JIN001）。
    """
    if text.startswith("\ufeff"):
        # BOM は JSON テキストの一部ではない（RFC 8259 §8.1「実装は BOM を追加してはならない」）。
        # 黙って剥がすと `jin fmt` が頼まれていないバイト列の変更をしたことになるので、
        # 段 1 で落として書き手に直してもらう（correctness review E-5 の残件）。
        raise JinSyntaxError(
            "先頭に BOM（U+FEFF）があります",
            Range(Position(1, 1), Position(1, 2)),
            "期待: BOM なしの UTF-8。エディタの保存設定を「UTF-8（BOM なし）」にしてください",
        )
    if not text.strip():
        raise JinSyntaxError(
            "ファイルが空です",
            Range(Position(1, 1), Position(1, 1)),
            "期待: JSON オブジェクト。最小の .jin は "
            '{"$schema": "...", "version": 1, "root": "...", "circles": []}',
        )
    try:
        tree = _PARSER.parse(text)
    except UnexpectedInput as exc:
        raise _syntax_error_from_lark(text, exc) from exc

    table = PointerTable()
    value = _walk(tree, "", table)
    return ParseResult(value=value, table=table)


__all__ = [
    "JIN_JSON_GRAMMAR",
    "MAX_NESTING_DEPTH",
    "JinSyntaxError",
    "ParseResult",
    "PointerTable",
    "parse_text",
]
