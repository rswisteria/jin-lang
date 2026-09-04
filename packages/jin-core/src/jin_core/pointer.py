"""JSON Pointer（RFC 6901）ユーティリティ。

Pointer は「ファイル内の位置・描画要素（data-jin）・診断・トレースイベント」を結ぶ唯一の鍵
（要件書 §10 #11 / docs/spec/model.md §6）。ルート文書は空文字列 `""` で表す。
"""

from __future__ import annotations

from typing import Any


def escape_token(token: str) -> str:
    """RFC 6901 のトークンエスケープ（`~` → `~0`、`/` → `~1`）。順序を守ること。"""
    return token.replace("~", "~0").replace("/", "~1")


def unescape_token(token: str) -> str:
    """RFC 6901 のトークン復号（`~1` → `/` を先に戻す）。"""
    return token.replace("~1", "/").replace("~0", "~")


def join(pointer: str, token: str | int) -> str:
    """親 pointer に 1 段追加する。"""
    return f"{pointer}/{escape_token(str(token))}"


def split_pointer(pointer: str) -> list[str]:
    """pointer をトークン列へ分解する。ルート `""` は空リスト。"""
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise ValueError(f"JSON Pointer は '/' で始まる必要があります: {pointer!r}")
    return [unescape_token(part) for part in pointer[1:].split("/")]


def is_index_token(token: str) -> bool:
    """RFC 6901 の配列添字トークンとして妥当かを判定する。

    `str.isdigit()` は ASCII 以外の数字（`"٣"` = U+0663、`"²"` = U+00B2）にも
    True を返す。`int("٣")` は 3 になるので、そのまま添字に使うと
    **原文に書かれていない要素**を指してしまう。`isascii()` と併せて弾く。
    RFC 6901 は先頭 0（`"01"`）も符号（`"-1"` / `"+1"`）も許さない。
    """
    if not (token.isascii() and token.isdigit()):
        return False
    return token == "0" or not token.startswith("0")


def parent_of(pointer: str) -> str | None:
    """1 段上の pointer。ルートなら None。"""
    if pointer == "":
        return None
    return pointer.rsplit("/", 1)[0]


def resolve_pointer(document: Any, pointer: str) -> Any:
    """素の JSON 値（dict / list / スカラ）から pointer の指す値を取り出す。

    解決できない場合は KeyError / IndexError を投げる（黙って None を返さない・NFR-FAIL-001）。
    """
    node = document
    for token in split_pointer(pointer):
        if isinstance(node, dict):
            if token not in node:
                raise KeyError(pointer)
            node = node[token]
        elif isinstance(node, list):
            if not is_index_token(token):
                raise KeyError(pointer)
            index = int(token)
            if not 0 <= index < len(node):
                raise IndexError(pointer)
            node = node[index]
        else:
            raise KeyError(pointer)
    return node


def pointer_exists(document: Any, pointer: str) -> bool:
    try:
        resolve_pointer(document, pointer)
    except (KeyError, IndexError, ValueError):
        return False
    return True


def loc_to_pointer(document: Any, loc: tuple[Any, ...]) -> str:
    """Pydantic の `ValidationError.loc` を JSON Pointer に変換する。

    `loc` には**実際のキー / 添字ではない要素**が混ざる:

    - 判別共用体のタグ（例: `('circles', 0, 'tools', 1, 'summon', 'circle')` の `'summon'`）
    - バリデータ由来のラベル（`'function-after'` など）

    そこで**解析済みの JSON 値に対して左から順に降りられるかどうか**で判定し、
    降りられない要素はタグとみなして読み飛ばす（ADR-006 の constraints
    「loc → pointer の変換規則を判別共用体・Optional・エイリアスについて網羅的にテストする」）。

    末尾のキーが存在しない場合（必須キー欠落）は、そのキーを 1 段だけ足した pointer を返す。
    その pointer は対応表に無いので `PointerTable.resolve` が親へフォールバックする。
    """
    pointer = ""
    node = document
    for i, element in enumerate(loc):
        if isinstance(node, dict) and isinstance(element, str):
            if element in node:
                pointer = join(pointer, element)
                node = node[element]
                continue
            # 必須キー欠落: 最後の要素なら 1 段足して返す。途中ならタグとして読み飛ばす。
            if i == len(loc) - 1:
                return join(pointer, element)
            continue
        if isinstance(node, list) and isinstance(element, int):
            if 0 <= element < len(node):
                pointer = join(pointer, element)
                node = node[element]
                continue
            if i == len(loc) - 1:
                return join(pointer, element)
            continue
        # ここに来るのはタグ・ラベルの類い。読み飛ばす。
        continue
    return pointer


__all__ = [
    "escape_token",
    "is_index_token",
    "join",
    "loc_to_pointer",
    "parent_of",
    "pointer_exists",
    "resolve_pointer",
    "split_pointer",
    "unescape_token",
]
