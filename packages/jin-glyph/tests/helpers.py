"""テスト用: 完全陣と同じ描き方で升を SVG に描き、cairosvg で PNG にする(開発時だけの依存)。"""

from __future__ import annotations

import io

import cairosvg
from jin_core.v2.glyph import START_MARK
from jin_core.v2.model import JinFileV2
from jin_glyph.scene import Band, Cell, Figure, ImageInfo, JinScene
from jin_render.v2 import geometry as g2
from jin_render.v2.font import char_d
from jin_render.v2.glyph_paths import glyph_d
from jin_render.v2.inscribe import circle_ring, frame_band, rite_ring
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


def png_data(svg: str, scale: float) -> bytes:
    """白地の PNG のバイト列(完全陣は Pillow の爆弾検査に掛かる大きさになるので、Pillow を通さない)。"""
    return cairosvg.svg2png(bytestring=svg.encode(), scale=scale, background_color="white")


def to_png(svg: str, scale: float) -> Image.Image:
    return Image.open(io.BytesIO(png_data(svg, scale))).convert("L")


def cell_image(t: str, v: str, scale: float) -> tuple[Image.Image, tuple[float, float], float]:
    """(画像, 升の中心の画素, 升の画素数)。"""
    image = to_png(cell_svg(t, v), scale)
    center = 1.5 * CELL * scale
    return image, (center, center), CELL * scale


def inscribed_scene(model: JinFileV2) -> JinScene:
    """画像を通さない理想の場面グラフ(`jin_render.v2.inscribe` の升の列。図形の id はデコーダと同じ付け方)。"""
    names = [c.name for c in model.circles]
    root = names.index(model.root) if model.root in names else 0
    order = [root] + [ci for ci in range(len(model.circles)) if ci != root]
    start = Cell(t="struct", v=START_MARK)
    figures = [Figure(id="frame", kind="frame", at=(0.0, 0.0))]
    bands = [Band(owner="frame", cells=[Cell(t=c.t, v=c.v) for c in frame_band(model)])]
    for k, ci in enumerate(order):
        figures.append(Figure(id=f"c{k}", kind="ring.circle", at=(0.0, 0.0)))
        bands.append(
            Band(
                owner=f"c{k}", cells=[start] + [Cell(t=c.t, v=c.v) for c in circle_ring(model, ci)]
            )
        )
        for j in range(len(model.circles[ci].rites)):
            figures.append(Figure(id=f"r{k}_{j}", kind="ring.rite", at=(0.0, 0.0)))
            cells = [start] + [Cell(t=c.t, v=c.v) for c in rite_ring(model, ci, j)]
            bands.append(Band(owner=f"r{k}_{j}", cells=cells))
    return JinScene(
        jinscene=1,
        sheet="full",
        image=ImageInfo(sha256="0" * 64, width=1, height=1),
        figures=figures,
        bands=bands,
    )
