"""構文解析器(`jin_glyph.parse`): 場面グラフ → モデル。画像を通さず、`inscribe` の升の列から組んだ場面グラフで固定する。

- 全プログラムで元の正準形に戻る(root が circles[0] でない並びも)
- 壊れた場面グラフは例外ではなく JIN3xx を出す。fixture(`tests/fixtures/errors/scene/`)は対応コードをちょうど 1 つ出す
"""

from __future__ import annotations

from pathlib import Path

import pytest
from jin_core.canonical import dumps
from jin_core.check import check_text
from jin_core.diagnostics import SCENE_CODES
from jin_core.v2.model import JinFileV2
from jin_glyph.parse import parse_scene, parse_scene_text
from jin_glyph.scene import Cell

from .helpers import inscribed_scene

REPO_ROOT = Path(__file__).resolve().parents[3]
PROGRAMS = sorted((REPO_ROOT / "examples-v2").glob("*/*.jin")) + sorted(
    (REPO_ROOT / "tests/fixtures/v2-programs").glob("*.jin")
)
SCENE_FIXTURES = sorted((REPO_ROOT / "tests/fixtures/errors/scene").glob("*.jinscene.json"))


def load(path: Path) -> JinFileV2:
    model = check_text(path.read_text(encoding="utf-8"), path.name).model
    assert isinstance(model, JinFileV2), path
    return model


@pytest.mark.parametrize("path", PROGRAMS, ids=lambda p: p.stem)
def test_the_inscription_parses_back_to_the_canonical_form(path: Path) -> None:
    model = load(path)
    parsed, diagnostics = parse_scene(inscribed_scene(model), file="x.jinscene.json")
    assert diagnostics == []
    assert parsed is not None
    assert dumps(parsed) == dumps(model)


def test_the_circle_order_survives_when_root_is_not_first() -> None:
    model = load(REPO_ROOT / "examples-v2/paddle/paddle.jin")
    moved = model.model_copy(update={"circles": list(reversed(model.circles))})
    assert moved.circles[0].name != moved.root
    parsed, diagnostics = parse_scene(inscribed_scene(moved), file="x.jinscene.json")
    assert diagnostics == []
    assert parsed is not None
    assert dumps(parsed) == dumps(moved)


@pytest.mark.parametrize("path", SCENE_FIXTURES, ids=lambda p: p.name.split(".")[0])
def test_each_scene_fixture_yields_exactly_its_code(path: Path) -> None:
    code = path.name.split("_")[0]
    _, diagnostics = parse_scene_text(path.read_text(encoding="utf-8"), file=path.name)
    assert [d.code for d in diagnostics] == [code], [
        (d.code, d.pointer, d.message) for d in diagnostics
    ]
    d = diagnostics[0]
    assert d.file == path.name
    assert d.pointer.startswith("/")
    assert (d.range.start.line, d.range.start.col) != (
        1,
        1,
    )  # range は .jinscene.json のテキストの位置


def test_every_scene_code_has_a_fixture() -> None:
    assert {p.name.split("_")[0] for p in SCENE_FIXTURES} == set(SCENE_CODES)


def test_an_unsure_cell_is_a_warning_and_the_model_is_still_built() -> None:
    model = load(REPO_ROOT / "examples-v2/fib/fib.jin")
    scene = inscribed_scene(model)
    first = scene.bands[1].cells[3]
    scene.bands[1].cells[3] = Cell(t=first.t, v=first.v, unsure=["?"])
    parsed, diagnostics = parse_scene(scene, file="x.jinscene.json")
    assert [(d.code, d.severity, d.pointer) for d in diagnostics] == [
        ("JIN306", "warning", "/bands/1/cells/3")
    ]
    assert parsed is not None and dumps(parsed) == dumps(model)


def test_semantic_errors_point_into_the_scene() -> None:
    # 手順の名前を変えると陣の核の参照が解けない(JIN011)。pointer はモデルではなく場面グラフの中
    model = load(REPO_ROOT / "examples-v2/fib/fib.jin")
    scene = inscribed_scene(model)
    rite = next(b for b in scene.bands if b.owner == "r0_0")
    name_cell = 3  # start, s_rite, 名前の 1 字目
    rite.cells[name_cell - 1] = Cell(t="latin", v="Q")
    _, diagnostics = parse_scene(scene, file="x.jinscene.json")
    assert diagnostics, "名前を壊したのに診断が無い"
    for d in diagnostics:
        assert d.pointer.startswith("/bands/"), (d.code, d.pointer)


def test_a_broken_json_or_scene_is_a_diagnostic_not_an_exception() -> None:
    _, syntax = parse_scene_text("{", file="x.jinscene.json")
    assert [d.code for d in syntax] == ["JIN001"]
    _, schema = parse_scene_text('{"jinscene": 1}', file="x.jinscene.json")
    assert schema and {d.code for d in schema} == {"JIN002"}


def _frame_lead_end(cells: list[Cell]) -> int:
    return next((i for i, c in enumerate(cells) if c.t == "struct"), len(cells))


def _hostile(kind: str):
    """手書き・壊れた場面グラフ(最終レビュー #1)。どれも例外ではなく JIN302 になる。"""
    scene = inscribed_scene(load(REPO_ROOT / "examples-v2/fib/fib.jin"))
    frame = scene.bands[0].cells
    if kind in ("quote", "control", "backslash_n"):
        body = {"quote": ['"'], "control": ["\n"], "backslash_n": ["\\", "n"]}[kind]
        head = [Cell(t="glyph", v="quote_l")]
        head += [Cell(t="latin", v=ch) for ch in body] + [Cell(t="glyph", v="quote_r")]
        frame[0:0] = [*head, Cell(t="glyph", v="sep")]
    elif kind == "long_number":
        end = _frame_lead_end(frame)
        frame[end:end] = [Cell(t="glyph", v="sep")] + [Cell(t="latin", v="9")] * 5000
    elif kind == "deep_type":
        ring = scene.bands[1].cells
        at = next(i for i, c in enumerate(ring) if c.t == "struct" and c.v == "s_state")
        sep = next(i for i in range(at, len(ring)) if ring[i].v == "sep")
        nxt = next(i for i in range(sep + 1, len(ring)) if ring[i].v == "sep")
        ring[sep + 1 : nxt] = (
            [Cell(t="glyph", v="t_list_l")] * 3000
            + [Cell(t="glyph", v="t_num")]
            + [Cell(t="glyph", v="t_list_r")] * 3000
        )
    return scene


@pytest.mark.parametrize("kind", ["quote", "control", "backslash_n", "long_number", "deep_type"])
def test_a_hostile_scene_is_a_diagnostic_not_an_exception(kind: str) -> None:
    parsed, diagnostics = parse_scene(_hostile(kind), file="x.jinscene.json")
    assert parsed is None
    assert [d.code for d in diagnostics] == ["JIN302"], [(d.code, d.message) for d in diagnostics]
