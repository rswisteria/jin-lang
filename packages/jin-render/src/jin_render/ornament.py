"""識別紋章（装飾）の決定的生成（`docs/spec/layout.md` §2.2 / §6）。

装飾は `instruction.rune` の **SHA-256** から作る。`hash()` は `PYTHONHASHSEED` で変わるが
`hashlib.sha256` は変わらないので、別プロセス・別環境でも同じ図になる（machine 条件 7 / 8）。
`rune` を持たない circle には装飾を描かない（layout.md §2.2）。

ハッシュの使い方（要件書に無い実装判断・layout.md §6）:

| バイト | 用途 |
|---|---|
| `digest[0] % 6 + 3` | 点の個数（3〜8 個） |
| `digest[1 + 3i]` | i 番目の点の角度（`360 * b / 256` 度） |
| `digest[2 + 3i]` | i 番目の点の半径（`0.18 + 0.12 * b / 255`） |
| `digest[3 + 3i]` | i 番目の点の大きさ（`0.008 + 0.010 * b / 255`） |

最大で 添字 24（= 25 バイト目）までしか使わない（SHA-256 は 32 バイト）。
"""

from __future__ import annotations

import hashlib

ORNAMENT_MIN_DOTS = 3
ORNAMENT_DOT_SPAN = 6
_BYTES_PER_DOT = 3
#: 点を置く半径の範囲（核 0.12 と指示環 0.35 の間）。
ORNAMENT_RADIUS_MIN = 0.18
ORNAMENT_RADIUS_SPAN = 0.12
ORNAMENT_SIZE_MIN = 0.008
ORNAMENT_SIZE_SPAN = 0.010


def ornament_dots(rune: str) -> list[tuple[float, float, float]]:
    """`(角度, 半径, 点の半径)` の並びを返す。同じ rune なら常に同じ並び。"""
    digest = hashlib.sha256(rune.encode("utf-8")).digest()
    count = ORNAMENT_MIN_DOTS + digest[0] % ORNAMENT_DOT_SPAN
    dots: list[tuple[float, float, float]] = []
    for index in range(count):
        base = 1 + index * _BYTES_PER_DOT
        angle = 360.0 * digest[base] / 256.0
        radius = ORNAMENT_RADIUS_MIN + ORNAMENT_RADIUS_SPAN * digest[base + 1] / 255.0
        size = ORNAMENT_SIZE_MIN + ORNAMENT_SIZE_SPAN * digest[base + 2] / 255.0
        dots.append((angle, radius, size))
    return dots


__all__ = [
    "ORNAMENT_DOT_SPAN",
    "ORNAMENT_MIN_DOTS",
    "ORNAMENT_RADIUS_MIN",
    "ORNAMENT_RADIUS_SPAN",
    "ORNAMENT_SIZE_MIN",
    "ORNAMENT_SIZE_SPAN",
    "ornament_dots",
]
