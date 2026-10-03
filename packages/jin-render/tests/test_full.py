"""完全陣(`jin_render.v2.full.render_full`)の規律: `<text>` 無し・3 桁固定・pointer と kind の契約・決定性・エラー回復。"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from jin_core.canonical import dumps
from jin_core.check import check_text
from jin_core.v2.model import JinFileV2
from jin_render import DATA_JIN_KINDS_V2
from jin_render.v2.full import render_full

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = sorted((REPO_ROOT / "examples-v2").glob("*/*.jin"))
PROGRAMS = EXAMPLES + sorted((REPO_ROOT / "tests/fixtures/v2-programs").glob("*.jin"))
ERRORS = sorted((REPO_ROOT / "tests/fixtures/errors/v2").glob("*.jin"))


def load(path: Path) -> JinFileV2 | None:
    model = check_text(path.read_text(encoding="utf-8"), path.name).model
    return model if isinstance(model, JinFileV2) else None


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
        assert model is not None, path
        out[path.stem] = (model, render_full(model))
    return out


def test_full_svg_has_no_text_element(rendered: dict) -> None:
    for name, (_, svg) in rendered.items():
        assert "<text" not in svg and "<textPath" not in svg, name


def test_full_svg_uses_no_arc_style_or_transform(rendered: dict) -> None:
    for name, (_, svg) in rendered.items():
        for d in re.findall(r' d="([^"]*)"', svg):
            assert "A" not in d and "a" not in d, name
        assert "<style" not in svg and " style=" not in svg and "transform" not in svg, name


def test_full_svg_numbers_have_three_decimals(rendered: dict) -> None:
    for name, (_, svg) in rendered.items():
        for d in re.findall(r' (?:d|x|y|cx|cy|r|width|height|x1|y1|x2|y2)="([^"]*)"', svg):
            for num in re.findall(r"-?\d+(?:\.\d+)?", d):
                assert re.fullmatch(r"-?\d+\.\d{3}", num), (name, num)


def test_every_full_pointer_is_in_the_model_pointer_space(rendered: dict) -> None:
    for name, (model, svg) in rendered.items():
        data = json.loads(dumps(model))
        for pointer in set(re.findall(r'data-jin="([^"]*)"', svg)):
            assert resolves(data, pointer), (name, pointer)


def test_full_kinds_are_v2_kinds(rendered: dict) -> None:
    for name, (_, svg) in rendered.items():
        assert set(re.findall(r'data-jin-kind="([^"]*)"', svg)) <= set(DATA_JIN_KINDS_V2), name


def test_every_drawn_element_carries_pointer_and_kind(rendered: dict) -> None:
    for name, (_, svg) in rendered.items():
        for tag in re.findall(r"<(?:path|circle|line|rect|polygon|polyline)\b[^>]*>", svg):
            assert "data-jin=" in tag and "data-jin-kind=" in tag, (name, tag[:120])


def test_full_render_is_deterministic(rendered: dict) -> None:
    model, svg = rendered["tetris"]
    assert render_full(model) == svg


def test_full_render_agrees_across_hash_seeds() -> None:
    code = (
        "from pathlib import Path; from jin_core.check import check_text; from jin_render.v2.full import render_full;"
        "import hashlib, sys; p = Path(sys.argv[1]);"
        "print(hashlib.sha256(render_full(check_text(p.read_text(), p.name).model).encode()).hexdigest())"
    )
    target = str(REPO_ROOT / "examples-v2/paddle/paddle.jin")
    digests = {
        subprocess.run(
            [sys.executable, "-c", code, target],
            capture_output=True,
            text=True,
            check=True,
            env=os.environ | {"PYTHONHASHSEED": seed},
        ).stdout
        for seed in ("1", "2")
    }
    assert len(digests) == 1


@pytest.mark.parametrize("path", ERRORS, ids=lambda p: p.stem)
def test_full_render_survives_semantic_errors(path: Path) -> None:
    model = load(path)
    if model is None:
        pytest.skip("schema を通らない fixture")
    assert render_full(model).startswith("<svg")


def test_the_whole_program_is_in_the_picture(rendered: dict) -> None:
    # 銘文の升の data-jin が、式・名前の欄の pointer をすべて覆う(何も落としていない)
    _, svg = rendered["fib"]
    drawn = set(re.findall(r'data-jin="([^"]*)"', svg))
    for pointer in (
        "/circles/0/name",
        "/circles/0/core",
        "/circles/0/state/0/init",
        "/circles/0/rites/0/steps/2/times",
        "/circles/0/rites/0/steps/2/steps/0/expr",
        "/circles/0/rites/1/steps/0/args/0",
        "/circles/0/rites/1/steps/0/into",
        "/stage/width",
    ):
        assert pointer in drawn, pointer


def test_the_single_entry_point_draws_the_full_circle(rendered: dict) -> None:
    from jin_render import render

    model, svg = rendered["fib"]
    assert render(model, full=True) == svg


@pytest.mark.parametrize("kwargs", [{"focus": "Fib"}, {"trace": []}, {"trace": [], "upto": 0}])
def test_full_cannot_be_combined_with_focus_or_trace(rendered: dict, kwargs: dict) -> None:
    from jin_render import RenderError, render

    model, _ = rendered["fib"]
    with pytest.raises(RenderError, match="--full"):
        render(model, full=True, **kwargs)


def test_full_is_only_for_v2() -> None:
    from jin_render import RenderError, render

    path = REPO_ROOT / "examples/pipeline/pipeline.jin"
    model = check_text(path.read_text(encoding="utf-8"), path.name).model
    with pytest.raises(RenderError, match="v2"):
        render(model, full=True)
