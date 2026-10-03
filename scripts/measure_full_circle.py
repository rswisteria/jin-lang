#!/usr/bin/env python3
"""examples-v2 の完全陣の大きさを測り、Markdown の表で出す(陣書き S2・glyph 設計書 §2.4 の見積もりを実測で置き換える)。

    uv run python scripts/measure_full_circle.py

列: 一辺(升)= 額縁の一辺 / 銘環の周回数の最大(陣・手順陣ごとの最大)/ 升の総数(額縁の銘帯 + 全銘環の字)/
A3(280 mm 角)に刷ったときの 1 升(mm)。値はレイアウトの定数(`jin_render.v2.geometry` の FULL_*)から決まる。
"""

from __future__ import annotations

import sys
from pathlib import Path

from jin_core.check import check_text
from jin_render.v2.full_layout import circle_inner, place, ring_cells, rite_inner
from jin_render.v2.inscribe import circle_ring, frame_band, rite_ring

REPO_ROOT = Path(__file__).resolve().parents[1]
A3_MM = 280.0


def measure(path: Path) -> tuple[str, float, int, int, float]:
    model = check_text(path.read_text(encoding="utf-8"), path.name).model
    placement = place(model)
    rings: list[int] = []
    cells = len(frame_band(model))
    for ci in placement.circles:
        band = circle_ring(model, ci)
        cells += len(band)
        rings.append(max(c.ring for c in ring_cells(band, 0.0, 0.0, circle_inner())) + 1)
    for ci, ri in placement.rites:
        band = rite_ring(model, ci, ri)
        cells += len(band)
        rings.append(max(c.ring for c in ring_cells(band, 0.0, 0.0, rite_inner())) + 1)
    side = 2.0 * placement.half
    return path.stem, side, max(rings), cells, A3_MM / side


def main() -> int:
    print("| 例 | 一辺(升) | 銘環の周回数の最大 | 升の総数 | A3 で 1 升(mm) |")
    print("|---|---|---|---|---|")
    for path in sorted((REPO_ROOT / "examples-v2").glob("*/*.jin")):
        name, side, rings, cells, mm = measure(path)
        print(f"| {name} | {side:.1f} | {rings} | {cells} | {mm:.2f} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
