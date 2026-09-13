"""JIL の契約（docs/spec/v2/jil.md）: 版・禁止語・トレース kind と、禁止語の走査。

`JIL_FORBIDDEN` は jil.md §2 の machine-readable ブロックと等号で突合する
（`tests/spec/test_v2_spec_consistency.py`）。走査は**生成部とプレリュードの両方**に掛ける
（`tests/contract/test_jil_contract.py`）。

走査の規則（jil.md §2「走査は識別子単位」）:

- コメント（`--` / `--[[ ]]`）と文字列リテラル（`"…"` / `'…'` / `[[…]]`）を先に取り除く
- 自由な識別子（直前が `.` / `:` でないもの）が禁止語なら違反。`random.next()` の `next` や
  `manifest.debug` の `debug` はフィールド名なので違反にしない
- `string.dump` / `coroutine.wrap` は `A.B` の対で照合する
- `...`（可変長引数）はトークンとして照合する
- テーブルコンストラクタのキー（`{ next = … }` のように直後に `=` が続くもの。`==` は除く）は
  自由な識別子ではないので違反にしない。プレリュードのホスト能力テーブルがこの形を使う

走査が**本物の** `next(` / `pairs(` / `os.time()` を落とすことは
`packages/jin-wasm/tests/test_jil.py` が注入で固定する。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: JIL の契約の版（jil.md §1）。プレリュードと生成部の**組**で 1 つの版。
JIL_VERSION = 1

#: 禁止語（jil.md §2 の machine-readable ブロックと等号）。
JIL_FORBIDDEN: tuple[str, ...] = (
    "pairs",
    "next",
    "setmetatable",
    "getmetatable",
    "rawget",
    "rawset",
    "rawequal",
    "rawlen",
    "load",
    "loadstring",
    "loadfile",
    "dofile",
    "require",
    "collectgarbage",
    "os",
    "io",
    "debug",
    "package",
    "string.dump",
    "coroutine.wrap",
    "select",
    "...",
)

#: トレース行の kind（runtime.md §5 の machine-readable ブロックと等号）。
TRACE_KINDS: tuple[str, ...] = (
    "enter",
    "exit",
    "event",
    "rite",
    "cast",
    "set",
    "emit",
    "transfer",
    "wait",
    "finish",
    "assert",
    "error",
    "frame",
)

#: トレース行のキー順（runtime.md §5 / jil.md §5）。
TRACE_FIELDS: tuple[str, ...] = (
    "seq",
    "tick",
    "circle",
    "kind",
    "name",
    "pointer",
    "input",
    "output",
)

#: ホストが Lua を呼ぶ関数（runtime.md §1）。
HOST_ENTRY_POINTS: tuple[str, ...] = ("boot", "tick")


@dataclass(frozen=True, slots=True)
class ForbiddenUse:
    line: int
    token: str
    text: str

    def __str__(self) -> str:
        return f"{self.line}: `{self.token}` ({self.text.strip()})"


_LONG_BRACKET = re.compile(r"\[(=*)\[")


def strip_comments_and_strings(text: str) -> str:
    """コメントと文字列リテラルを空白で置き換える（行番号は保つ）。

    長い括弧（`[[…]]` / `[==[…]==]`）はコメントにも文字列にも使えるので同じ規則で読む。
    改行はそのまま残すので、置き換え後も行番号が変わらない。
    """
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "-" and text.startswith("--", i):
            m = _LONG_BRACKET.match(text, i + 2)
            if m:
                end = _long_bracket_end(text, m.end(), m.group(1))
                out.append(_blank(text[i:end]))
                i = end
                continue
            end = text.find("\n", i)
            end = n if end == -1 else end
            out.append(" " * (end - i))
            i = end
            continue
        if ch in ('"', "'"):
            j = i + 1
            while j < n and text[j] != ch:
                if text[j] == "\\":
                    j += 1
                if j < n and text[j] == "\n":
                    break
                j += 1
            end = min(j + 1, n)
            out.append(_blank(text[i:end]))
            i = end
            continue
        if ch == "[":
            m = _LONG_BRACKET.match(text, i)
            if m:
                end = _long_bracket_end(text, m.end(), m.group(1))
                out.append(_blank(text[i:end]))
                i = end
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def _long_bracket_end(text: str, start: int, level: str) -> int:
    closing = "]" + level + "]"
    end = text.find(closing, start)
    return len(text) if end == -1 else end + len(closing)


def _blank(chunk: str) -> str:
    return "".join("\n" if c == "\n" else " " for c in chunk)


_TOKEN = re.compile(r"\.\.\.|[A-Za-z_][A-Za-z0-9_]*")
_DOTTED = {tuple(t.split(".")) for t in JIL_FORBIDDEN if "." in t}
_FREE = {t for t in JIL_FORBIDDEN if "." not in t and t != "..."}


def forbidden_uses(text: str) -> list[ForbiddenUse]:
    """JIL の本文に禁止語が現れる箇所を行番号付きで返す（空なら契約どおり）。"""
    cleaned = strip_comments_and_strings(text)
    lines = text.split("\n")
    uses: list[ForbiddenUse] = []
    for line_no, line in enumerate(cleaned.split("\n"), start=1):
        for m in _TOKEN.finditer(line):
            token = m.group(0)
            if token == "...":
                uses.append(ForbiddenUse(line_no, token, lines[line_no - 1]))
                continue
            before = line[: m.start()].rstrip()
            after = line[m.end() :].lstrip()
            if before.endswith((".", ":")):
                continue  # フィールド / メソッド名
            if after.startswith("=") and not after.startswith("=="):
                continue  # テーブルコンストラクタのキー
            if token in _FREE:
                uses.append(ForbiddenUse(line_no, token, lines[line_no - 1]))
                continue
            if after.startswith("."):
                rest = after[1:].lstrip()
                m2 = _TOKEN.match(rest)
                if m2 and (token, m2.group(0)) in _DOTTED:
                    uses.append(ForbiddenUse(line_no, f"{token}.{m2.group(0)}", lines[line_no - 1]))
    return uses


__all__ = [
    "HOST_ENTRY_POINTS",
    "JIL_FORBIDDEN",
    "JIL_VERSION",
    "TRACE_FIELDS",
    "TRACE_KINDS",
    "ForbiddenUse",
    "forbidden_uses",
    "strip_comments_and_strings",
]
