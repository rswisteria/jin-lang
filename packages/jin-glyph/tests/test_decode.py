"""デコーダ(`jin_glyph.decode.decode_png`): Jin が描いた完全陣の PNG を場面グラフに読む。

銘帯の升の列(始まりの印と継ぎを除く)が `jin_render.v2.inscribe` の升の列と升ごとに等しいことを固定する。
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest
from jin_core.check import check_text
from jin_core.v2.glyph import START_MARK
from jin_core.v2.model import JinFileV2
from jin_glyph.decode import DecodeError, decode_png
from jin_render.v2.full import render_full
from jin_render.v2.full_layout import place
from jin_render.v2.inscribe import circle_ring, frame_band, rite_ring

from .helpers import png_data

REPO_ROOT = Path(__file__).resolve().parents[3]


def load(name: str) -> JinFileV2:
    path = REPO_ROOT / "examples-v2" / name / f"{name}.jin"
    model = check_text(path.read_text(encoding="utf-8"), path.name).model
    assert isinstance(model, JinFileV2)
    return model


def png_bytes(model: JinFileV2, scale: float) -> bytes:
    return png_data(render_full(model), scale)


def payload(cells) -> list[tuple[str, str]]:
    return [
        (c.t, c.v) for c in cells if not (c.t == "struct" and c.v == START_MARK) and c.v != "cont"
    ]


def expected(model: JinFileV2) -> dict[str, list[tuple[str, str]]]:
    placement = place(model)
    names = [c.name for c in model.circles]
    root = names.index(model.root) if model.root in names else 0
    order = [root] + [ci for ci in range(len(model.circles)) if ci != root]
    out = {"frame": [(c.t, c.v) for c in frame_band(model)]}
    for k, ci in enumerate(order):
        out[f"c{k}"] = [(c.t, c.v) for c in circle_ring(model, ci)]
        for ri in range(len(model.circles[ci].rites)):
            assert (ci, ri) in placement.rites
            out[f"r{k}_{ri}"] = [(c.t, c.v) for c in rite_ring(model, ci, ri)]
    return out


@pytest.mark.parametrize("name", ["fib", "paddle", "tetris"])
def test_the_decoded_bands_equal_the_inscription(name: str) -> None:
    model = load(name)
    scene = decode_png(png_bytes(model, 2))
    assert scene.sheet == "full"
    bands = {band.owner: payload(band.cells) for band in scene.bands}
    assert bands == expected(model)


def test_the_scale_does_not_change_the_scene() -> None:
    model = load("fib")
    two = decode_png(png_bytes(model, 2))
    three = decode_png(png_bytes(model, 3))
    strip = lambda scene: [(b.owner, [(c.t, c.v) for c in b.cells]) for b in scene.bands]
    assert strip(two) == strip(three)
    assert [f.id for f in two.figures] == [f.id for f in three.figures]


def test_rings_keep_their_start_mark_and_cont() -> None:
    scene = decode_png(png_bytes(load("paddle"), 2))
    for band in scene.bands:
        if band.owner != "frame":
            assert (band.cells[0].t, band.cells[0].v) == ("struct", START_MARK), band.owner


def test_a_non_png_is_refused() -> None:
    with pytest.raises(DecodeError, match="PNG"):
        decode_png(b"GIF89a" + bytes(40))


def test_an_oversized_png_is_refused_before_decoding() -> None:
    # IHDR だけ(本体なし)。大きさで断るので Pillow に渡らない
    header = (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", 30000, 30000)
        + bytes(5)
    )
    with pytest.raises(DecodeError, match="大きすぎます"):
        decode_png(header)


def test_a_png_without_the_talisman_is_refused() -> None:
    from .helpers import cell_svg

    with pytest.raises(DecodeError, match="護符"):
        decode_png(png_data(cell_svg("glyph", "add"), 2))


def test_more_than_twelve_circles_on_the_first_orbit_are_all_found() -> None:
    # 最終レビュー #3: 陣の数に上限は無い(衛星 = 手順は JIN020 で 12 まで)。12 で頭打ちにすると 13 陣が 1 陣に化けた
    circles = [
        {"name": f"C{k}", "core": "go", "rites": [{"name": "go", "steps": [{"do": "finish"}]}]}
        for k in range(14)
    ]
    model = JinFileV2.model_validate(
        {
            "$schema": "https://xtone.internal/jin/schemas/jin-v2.schema.json",
            "version": 2,
            "root": "C0",
            "stage": {"width": 64, "height": 64},
            "circles": circles,
        }
    )
    scene = decode_png(png_bytes(model, 2))
    assert sorted(f.id for f in scene.figures if f.id.startswith("c")) == sorted(
        f"c{k}" for k in range(14)
    )


@pytest.mark.parametrize("cut", [16, 20, 23])
def test_a_png_cut_inside_its_header_is_refused(cut: int) -> None:
    # 最終レビュー #1: 署名と IHDR の名前は通るが大きさの 8 バイトが欠けている(struct.error を漏らさない)
    header = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 10, 10)
    with pytest.raises(DecodeError, match="PNG"):
        decode_png(header[:cut])


def test_a_frame_band_longer_than_three_rows_widens_the_frame_and_reads_back() -> None:
    """#119: 額縁の銘帯が 3 周を超えたら余白を広げる(4 周目が陣に食い込まない・位置が尽きて黙って切らない)。"""
    from jin_core.canonical import dumps
    from jin_glyph.parse import parse_scene
    from jin_render.v2 import geometry as g2
    from jin_render.v2.full_layout import FRAME_ROWS, frame_margin, frame_rows

    forms = [
        {"name": f"Form{k:02d}", "fields": [{"name": f"field{j}", "type": "num"} for j in range(6)]}
        for k in range(24)
    ]
    model = JinFileV2.model_validate(
        {
            "$schema": "https://xtone.internal/jin/schemas/jin-v2.schema.json",
            "version": 2,
            "root": "Main",
            "stage": {"width": 64, "height": 64},
            "forms": forms,
            "circles": [
                {
                    "name": "Main",
                    "core": "go",
                    "rites": [{"name": "go", "steps": [{"do": "finish"}]}],
                }
            ],
        }
    )
    placement = place(model)
    frame = placement.inscription.frame
    # 銘帯と次の 1 升が FRAME_ROWS 周を超えるので余白を広げ、銘帯の全部と次の 1 升が余白に収まる
    rows = frame_rows(len(frame) + 1, placement.half)
    assert rows > FRAME_ROWS
    margin = frame_margin(len(frame), placement.half)
    assert margin > g2.FULL_FRAME_MARGIN
    assert 1.5 + (rows - 1) * g2.FULL_RING_PITCH + 0.5 <= margin
    scene = decode_png(png_bytes(model, 2))
    bands = {band.owner: payload(band.cells) for band in scene.bands}
    assert bands["frame"] == [(c.t, c.v) for c in frame]
    parsed, diagnostics = parse_scene(scene, file="forms.jinscene.json")
    assert not [d for d in diagnostics if d.severity == "error"], diagnostics
    assert dumps(parsed) == dumps(model)
