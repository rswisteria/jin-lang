"""位置 → JSON Pointer の解決。

LSP の各機能（definition / references / hover / rename / codeAction / completion）は
どれも「カーソルがどの要素の上にあるか」から始まる。`jin_core.parser.PointerTable` が
**pointer → range** を持っているので、ここではその逆を引く。

対応表は数百件（examples で 200 前後）なので線形走査で足りる。索引を作らないのは、
索引の更新漏れが「静かに古い位置を返す」形で壊れるからである（打鍵ごとに表ごと作り直す）。
"""

from __future__ import annotations

from jin_core.diagnostics import Position, Range
from jin_core.parser import PointerTable


def contains(range_: Range, position: Position) -> bool:
    """`range_` が `position` を含むか（`end` は排他）。"""
    if position.line < range_.start.line or position.line > range_.end.line:
        return False
    if position.line == range_.start.line and position.col < range_.start.col:
        return False
    return not (position.line == range_.end.line and position.col >= range_.end.col)


def _size(range_: Range) -> tuple[int, int]:
    """範囲の広さ（行差, 列差）。狭いほうを深い要素とみなす。"""
    return (range_.end.line - range_.start.line, range_.end.col - range_.start.col)


def pointer_at(table: PointerTable, position: Position) -> str | None:
    """`position` を含む**最も狭い**値の pointer を返す。無ければ `None`。

    JSON は入れ子なので複数の pointer が同じ位置を含む（`""` ⊃ `/circles` ⊃
    `/circles/0` ⊃ `/circles/0/name`）。一番深い要素を返さないと、
    circle 名の上で rename を求められたときにファイル全体を対象にしてしまう。

    同じ広さの候補が並んだときは **pointer の文字列順**で決める。位置が同じで
    広さも同じ pointer は実際には現れないが、決め方を書いておかないと
    dict の反復順に依存する（決定性を辞書順序に預けない）。
    """
    best: tuple[tuple[int, int], str] | None = None
    for pointer, range_ in table.value_ranges.items():
        if not contains(range_, position):
            continue
        key = (_size(range_), pointer)
        if best is None or key < best:
            best = key
    return best[1] if best is not None else None


def key_pointer_at(table: PointerTable, position: Position) -> str | None:
    """`position` がメンバの**キー**の上にあるならその pointer を返す。

    `"name"` というキーの上と `"Drafter"` という値の上では、completion が出すべき
    候補が違う（前者はキー名、後者は参照名）。
    """
    for pointer, range_ in table.key_ranges.items():
        if contains(range_, position):
            return pointer
    return None


def range_of(table: PointerTable, pointer: str) -> Range | None:
    """pointer が指す**値**の範囲。祖先へ遡らない（`PointerTable.resolve` との違い）。"""
    return table.value_ranges.get(pointer)


__all__ = ["contains", "key_pointer_at", "pointer_at", "range_of"]
