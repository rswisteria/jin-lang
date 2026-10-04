"""全景(`jin_render.v2.panorama`・鑑賞ページの全景・stage.md §2.3・Issue #132)。

既定の図は深さ 1 まで展開して以下を点にするので、手順の中身・孫の陣・`summon` だけで使う陣が描かれない。全景は
完全陣と同じ配置にすべての陣と手順の図を並べ、全景の銘は同じ座標系に銘文を並べる。重ねると完全陣になる
(`<text>` と四隅の護符を除く)ことで、配置を完全陣から流用していることを固定する。
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from jin_core.check import check_text
from jin_core.v2.model import JinFileV2
from jin_render import RenderError, render
from jin_render.v2.full import render_full
from jin_render.v2.panorama import render_panorama, render_panorama_inscription

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = sorted((REPO_ROOT / "examples-v2").glob("*/*.jin"))
NS = "{http://www.w3.org/2000/svg}"


def load(path: Path) -> JinFileV2:
    model = check_text(path.read_text(encoding="utf-8"), path.name).model
    assert isinstance(model, JinFileV2)
    return model


def leaves(svg: str) -> list[str]:
    """図形の要素(`<g>` と `<text>` を除く)を、属性込みの文字列の列にする。"""
    out = []
    for element in ET.fromstring(svg).iter():
        tag = element.tag.removeprefix(NS)
        if tag in {"svg", "g", "text", "defs", "style", "title"}:
            continue
        out.append(tag + repr(sorted(element.attrib.items())))
    return out


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_every_circle_and_every_rite_is_drawn(path: Path) -> None:
    model = load(path)
    svg = render_panorama(model)
    drawn = set(re.findall(r'data-jin="(/circles/\d+(?:/rites/\d+)?)"', svg))
    for ci, circle in enumerate(model.circles):
        assert f"/circles/{ci}" in drawn
        for ri in range(len(circle.rites)):
            assert f"/circles/{ci}/rites/{ri}" in drawn


@pytest.mark.parametrize("name", ["fib", "tetris-plus", "othello"])
def test_the_panorama_and_its_inscription_overlay_into_the_full_circle(name: str) -> None:
    model = load(REPO_ROOT / "examples-v2" / name / f"{name}.jin")
    full = leaves(render_full(model))
    drawing = leaves(render_panorama(model))
    band = leaves(render_panorama_inscription(model))
    assert set(drawing) | set(band) <= set(full)
    rest = set(full) - set(drawing) - set(band)
    # 残るのは四隅の護符(額縁の `/stage`)だけ
    assert rest
    assert all("'/stage'" in item for item in rest), sorted(rest)[:3]


def test_the_panorama_keeps_the_names_but_the_inscription_has_no_text() -> None:
    model = load(REPO_ROOT / "examples-v2" / "tetris-plus" / "tetris-plus.jin")
    assert "<text" in render_panorama(model)
    assert "<text" not in render_panorama_inscription(model)


def test_render_dispatches_and_guards_the_panorama() -> None:
    model = load(REPO_ROOT / "examples-v2" / "fib" / "fib.jin")
    assert render(model, panorama=True) == render_panorama(model)
    assert render(model, panorama=True, inscription=True) == render_panorama_inscription(model)
    for kwargs in ({"focus": "Fib"}, {"full": True}, {"trace": []}, {"upto": 0}):
        with pytest.raises(RenderError):
            render(model, panorama=True, **kwargs)
