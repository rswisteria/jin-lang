"""陣書き S0 spike: glyphs.json → 字形表 reference.svg(と --png で reference.png)。使い捨て。

認識器のシステムプロンプトに画像として置く表でもある。各字の下に id を小さく添える。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CELL = 120  # 1 字の区画(字形 100 + 余白)
COLS = 8


def render(glyphs: dict[str, dict]) -> str:
    items = list(glyphs.items())
    rows = (len(items) + COLS - 1) // COLS
    w, h = COLS * CELL, rows * (CELL + 24) + 40
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
        f'<rect width="{w}" height="{h}" fill="#ffffff"/>',
        '<text x="8" y="26" font-family="sans-serif" font-size="18">Jin glyph reference (expr: 36 / disc: 21)</text>',
    ]
    for n, (gid, g) in enumerate(items):
        x = (n % COLS) * CELL + 10
        y = (n // COLS) * (CELL + 24) + 40
        frame = "#bbbbbb" if g["layer"] == "expr" else "#d9a000"
        out.append(f'<rect x="{x}" y="{y}" width="100" height="100" fill="none" stroke="{frame}" stroke-width="1"/>')
        out.append(
            f'<path transform="translate({x} {y})" d="{g["d"]}" fill="none" stroke="#111111" '
            'stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>'
        )
        label = gid if g["slot"] is None else f'{gid}'
        out.append(f'<text x="{x + 50}" y="{y + 116}" font-family="monospace" font-size="12" text-anchor="middle">{label}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main() -> None:
    glyphs = json.loads((HERE / "glyphs.json").read_text(encoding="utf-8"))
    svg = render(glyphs)
    (HERE / "reference.svg").write_text(svg, encoding="utf-8")
    print("reference.svg")
    if "--png" in sys.argv:
        import cairosvg

        cairosvg.svg2png(bytestring=svg.encode(), write_to=str(HERE / "reference.png"))
        print("reference.png")


if __name__ == "__main__":
    main()
