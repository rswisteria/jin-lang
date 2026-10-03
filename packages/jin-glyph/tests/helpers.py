"""テスト用: 完全陣と同じ描き方で升を SVG に描き、cairosvg で PNG にする(開発時だけの依存)。"""

from __future__ import annotations

import io

import cairosvg
from jin_render.v2 import geometry as g2
from jin_render.v2.font import char_d
from jin_render.v2.glyph_paths import glyph_d
from PIL import Image

CELL = g2.FULL_CELL_PX


def cell_svg(t: str, v: str, margin: float = 1.0) -> str:
    """升 1 つ(t = latin / glyph / struct)を、上下左右に margin 升の余白を付けて描いた SVG。"""
    side = (1.0 + 2.0 * margin) * CELL
    x0 = y0 = margin * CELL
    if t == "latin":
        d = char_d(v, x0, y0, CELL)
        body = f'<path d="{d}" fill="#000000" stroke="none"/>' if d else ""
    else:
        body = (
            f'<path d="{glyph_d(v, x0, y0, CELL)}" fill="none" stroke="#000000" stroke-width="1.000" '
            'stroke-linecap="round" stroke-linejoin="round"/>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{side}" height="{side}" viewBox="0 0 {side} {side}">'
        f"{body}</svg>"
    )


def to_png(svg: str, scale: float) -> Image.Image:
    data = cairosvg.svg2png(bytestring=svg.encode(), scale=scale, background_color="white")
    return Image.open(io.BytesIO(data)).convert("L")


def cell_image(t: str, v: str, scale: float) -> tuple[Image.Image, tuple[float, float], float]:
    """(画像, 升の中心の画素, 升の画素数)。"""
    image = to_png(cell_svg(t, v), scale)
    center = 1.5 * CELL * scale
    return image, (center, center), CELL * scale
