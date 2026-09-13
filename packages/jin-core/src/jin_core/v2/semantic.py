"""Jin v2 の意味検査（段 3）。正典は docs/spec/v2/diagnostics.md。

里程標 1 の時点では空。里程標 3 で共有番号（JIN010 …）→ JIN2xx の順に埋める。
"""

from __future__ import annotations

from jin_core.diagnostics import Diagnostic
from jin_core.parser import PointerTable
from jin_core.v2.model import JinFileV2


def analyze(model: JinFileV2, table: PointerTable, file: str) -> list[Diagnostic]:
    del model, table, file
    return []


__all__ = ["analyze"]
