"""recognize.py の幾何と採点を API なしで検算する(使い捨て)。

    uv run --with pillow --with cairosvg python selftest.py
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import cairosvg
from PIL import Image, ImageChops, ImageOps

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import make_sheet as ms  # noqa: E402
import recognize as rc  # noqa: E402


def synthetic_sheet(name: str) -> Image.Image:
    rows = ms.rows_for(name, rc.SOURCES[name])
    pages, _ = ms.layout(rows)
    sheet = ms.render_page(name, 0, len(pages), pages[0])
    guide = ms.render_page(name, 0, len(pages), pages[0], guide=True)
    body = guide.split(">", 1)[1].rsplit("</svg>", 1)[0]  # 手本の中身を重ねる
    composite = sheet.replace("</svg>", body + "</svg>")
    side = int(ms.SIDE * rc.PX_PER_MM)
    png = cairosvg.svg2png(bytestring=composite.encode(), output_width=side, output_height=side)
    return Image.open(io.BytesIO(png)).convert("RGB")


def main() -> int:
    flat0 = synthetic_sheet("fib")
    side = flat0.width
    # 90° 時計回りに回し、周りに 300 px の余白を足した「写真」
    photo = ImageOps.expand(flat0.rotate(-90, expand=True), border=300, fill="white")
    c = ms.FID / 2 * rc.PX_PER_MM

    def rot(x: float, y: float) -> list[float]:  # 元の (x, y) → 回した写真の座標
        return [side - y + 300, x + 300]

    corners = {"tl": rot(c, c), "tr": rot(side - c, c), "bl": rot(c, side - c), "br": rot(side - c, side - c)}
    flat = rc.rectify(photo, corners)
    diff = ImageChops.difference(flat.convert("L"), flat0.convert("L"))
    bad = sum(1 for v in diff.getdata() if v > 96) / (side * side)
    print(f"正面化の画素の食い違い(>96): {bad:.4%}")
    rows = ms.rows_for("fib", rc.SOURCES["fib"])
    pages, _ = ms.layout(rows)
    row, start, y = pages[0][12]
    n = min(ms.COLS, len(row.cells) - start)
    rc.strip(flat, ms.MARGIN + ms.LABEL_W, y, n).save(HERE / "selftest-strip.png")
    print(f"行 {row.id} ({row.label}) を selftest-strip.png に切り出した(升 {n})")
    lines = [(r, s, yy, min(ms.COLS, len(r.cells) - s)) for r, s, yy in pages[0]]
    perfect = {(r.id, k): r.cells[k] for r, s, _, n in lines for k in range(s, s + n)}
    print("完全な読みの採点:")
    rc.score(lines, perfect)
    return 0 if bad < 0.005 else 1


if __name__ == "__main__":
    sys.exit(main())
