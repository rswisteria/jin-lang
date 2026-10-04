"""鑑賞ページの銘環の帯(`jin_render.v2.inscription`・陣書き S7・stage.md §2.2)の規律。

- 升の列は完全陣の銘文(`frame_band` → 陣ごとに `circle_ring` → `rite_ring`)と同じで、置き場所だけが違う
- 通常の図と同じ座標系(1000 px 四方)で、全点が環 `BAND_INNER` 〜 `BAND_OUTER` に収まる(図と重ならない)
- `<text>` 無し・kind は 13 種のまま・pointer はモデルの pointer 空間・決定的
- 入口は `jin_render.render(..., inscription=True)` 1 本で、併用できない引数と v1 を断る
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pytest
from jin_core.canonical import dumps
from jin_core.check import check_text
from jin_core.v2.model import JinFileV2
from jin_render import DATA_JIN_KINDS_V2, RenderError, render
from jin_render.v2.font import char_d
from jin_render.v2.full_layout import ring_cells
from jin_render.v2.inscription import (
    BAND_CELL_MAX,
    BAND_INNER,
    BAND_OUTER,
    band_cell_size,
    band_cells,
    render_inscription,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = sorted((REPO_ROOT / "examples-v2").glob("*/*.jin"))
PROGRAMS = EXAMPLES + sorted((REPO_ROOT / "tests/fixtures/v2-programs").glob("*.jin"))
#: 通常の図の正規化 1.0 あたりの px と中心(`jin_render.geometry.UNIT_PX` / `CANVAS_PX`)。
UNIT_PX = 400.0
CENTER = 500.0


def load(path: Path) -> JinFileV2:
    model = check_text(path.read_text(encoding="utf-8"), path.name).model
    assert isinstance(model, JinFileV2), path
    return model


def resolves(data: object, pointer: str) -> bool:
    node = data
    for part in pointer.split("/")[1:]:
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        elif isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return False
    return True


@pytest.fixture(scope="module")
def rendered() -> dict[str, tuple[JinFileV2, str]]:
    out = {}
    for path in PROGRAMS:
        model = load(path)
        out[path.stem] = (model, render_inscription(model))
    return out


def test_the_band_has_the_same_canvas_as_the_plain_drawing(rendered: dict) -> None:
    for name, (model, svg) in rendered.items():
        head = svg.splitlines()[0]
        plain = render(model).splitlines()[0]
        assert head == plain, name


def test_the_band_has_no_text_and_only_the_v2_kinds(rendered: dict) -> None:
    for name, (_, svg) in rendered.items():
        assert "<text" not in svg, name
        kinds = set(re.findall(r'data-jin-kind="([^"]+)"', svg))
        assert kinds <= set(DATA_JIN_KINDS_V2), (name, kinds - set(DATA_JIN_KINDS_V2))


def test_every_cell_points_into_the_model(rendered: dict) -> None:
    for name, (model, svg) in rendered.items():
        data = json.loads(dumps(model))
        for pointer in re.findall(r'data-jin="([^"]*)"', svg):
            assert resolves(data, pointer), (name, pointer)


def test_every_point_lies_inside_the_band(rendered: dict) -> None:
    for name, (_, svg) in rendered.items():
        radii = []
        for d in re.findall(r' d="([^"]*)"', svg):
            numbers = [float(v) for v in re.findall(r"-?\d+\.\d+", d)]
            for x, y in zip(numbers[::2], numbers[1::2], strict=True):
                radii.append(math.hypot(x - CENTER, y - CENTER) / UNIT_PX)
        assert radii, name
        # 升の角は中心から √2/2 升。内縁は 1 周目の升の中心 − 半升の角まで、外縁は ring_outer が見る
        size = band_cell_size(len(band_cells(rendered[name][0])))
        assert min(radii) >= BAND_INNER - 0.01, (name, min(radii))
        assert max(radii) <= BAND_OUTER + size * 0.5, (name, max(radii), size)


def test_the_band_carries_the_whole_inscription_in_order(rendered: dict) -> None:
    """帯の升は銘文の升(+ 始まりの印と継ぎの紋)を同じ順で並べたもの。点の無い字(空白)は描かない。"""
    for name, (model, svg) in rendered.items():
        cells = band_cells(model)
        size = band_cell_size(len(cells))
        placed = ring_cells(cells, 0.0, 0.0, BAND_INNER / size)
        assert [item.cell for item in placed if item.cell.v != "cont"][1:] == cells, name
        expected = [
            (item.cell.pointer, item.cell.kind)
            for item in placed
            if item.cell.t != "latin" or char_d(item.cell.v, 0.0, 0.0, 1.0)
        ]
        assert re.findall(r'<path data-jin="([^"]*)" data-jin-kind="([^"]*)"', svg) == expected, (
            name
        )


def test_the_cell_size_shrinks_with_the_length_and_has_a_ceiling() -> None:
    assert band_cell_size(10) == BAND_CELL_MAX
    sizes = [band_cell_size(n) for n in (100, 1000, 5000)]
    assert sizes == sorted(sizes, reverse=True)
    assert sizes[-1] < sizes[0]


def test_the_band_is_deterministic(rendered: dict) -> None:
    for name, (model, svg) in rendered.items():
        assert render_inscription(model) == svg, name


def test_render_dispatches_the_band_and_rejects_the_other_arguments() -> None:
    model = load(REPO_ROOT / "examples-v2/fib/fib.jin")
    assert render(model, inscription=True) == render_inscription(model)
    for kwargs in (
        {"full": True},
        {"focus": "Fib"},
        {"trace": []},
        {"trace": [], "upto": 0},
    ):
        with pytest.raises(RenderError, match="inscription"):
            render(model, inscription=True, **kwargs)
    v1 = check_text(
        (REPO_ROOT / "examples/pipeline/pipeline.jin").read_text(encoding="utf-8"), "pipeline.jin"
    ).model
    with pytest.raises(RenderError, match="v2"):
        render(v1, inscription=True)


def test_the_band_does_not_change_the_other_drawings() -> None:
    """帯を足しても通常の図・完全陣の出力は変わらない(既存のスナップショットと往復の契約が別に固定する)。"""
    model = load(REPO_ROOT / "examples-v2/fib/fib.jin")
    assert render(model, inscription=False) == render(model)


@pytest.mark.parametrize("name", ["fib"])
def test_inscription_band_snapshot(name: str, snapshot) -> None:
    model = load(REPO_ROOT / "examples-v2" / name / f"{name}.jin")
    assert render_inscription(model) == snapshot
