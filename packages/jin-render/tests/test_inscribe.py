"""銘帯の中身(`jin_render.v2.inscribe`)。`.jin` の情報が升の列に過不足なく載り、式が往復することを固定する。"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest
from jin_core.canonical import dumps
from jin_core.check import check_text
from jin_core.v2.expr import canonical_expr
from jin_core.v2.glyph import STRUCT_MARK_OF
from jin_core.v2.model import JinFileV2
from jin_render import DATA_JIN_KINDS_V2
from jin_render.v2.inscribe import circle_ring, expr_cells, frame_band, rite_ring, to_expr

REPO_ROOT = Path(__file__).resolve().parents[3]
PROGRAMS = sorted((REPO_ROOT / "examples-v2").glob("*/*.jin")) + sorted(
    (REPO_ROOT / "tests/fixtures/v2-programs").glob("*.jin")
)
EXPR_KEYS = {
    "init",
    "expr",
    "cond",
    "assert",
    "exit",
    "ticks",
    "until",
    "times",
    "in",
    "target",
    "into",
}


def load(path: Path) -> JinFileV2:
    model = check_text(path.read_text(encoding="utf-8"), path.name).model
    assert isinstance(model, JinFileV2), path
    return model


def all_bands(model: JinFileV2) -> list:
    cells = list(frame_band(model))
    for ci, circle in enumerate(model.circles):
        cells += circle_ring(model, ci)
        for ri in range(len(circle.rites)):
            cells += rite_ring(model, ci, ri)
    return cells


def exprs_of(node: object):
    if isinstance(node, dict):
        for key, value in node.items():
            if key in EXPR_KEYS and isinstance(value, str):
                yield value
            elif key == "args" and isinstance(value, list):
                yield from (v for v in value if isinstance(v, str))
            else:
                yield from exprs_of(value)
    elif isinstance(node, list):
        for value in node:
            yield from exprs_of(value)


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


@pytest.mark.parametrize("path", PROGRAMS, ids=lambda p: p.stem)
def test_every_expression_round_trips_through_cells(path: Path) -> None:
    data = json.loads(dumps(load(path)))
    for text in exprs_of(data):
        assert canonical_expr(to_expr(expr_cells(text, "/x", "step"))) == canonical_expr(text), text


def test_a_space_in_a_string_is_escaped() -> None:
    cells = expr_cells('"SCORE " ++ str(score)', "/x", "step")
    assert not any(c.t == "latin" and c.v == " " for c in cells)
    pairs = [(a.v, b.v) for a, b in itertools.pairwise(cells)]
    assert ("esc", "s") in pairs


@pytest.mark.parametrize("path", PROGRAMS, ids=lambda p: p.stem)
def test_bands_start_with_their_struct_mark_in_preorder(path: Path) -> None:
    data = json.loads(dumps(load(path)))

    def preorder(steps: list) -> list[str]:
        out: list[str] = []
        for step in steps:
            out.append(STRUCT_MARK_OF["step." + step["do"]])
            for key in ("then", "else", "steps"):
                out += preorder(step.get(key, []))
        return out

    model = load(path)
    for ci, circle in enumerate(data["circles"]):
        for ri, rite in enumerate(circle.get("rites", [])):
            marks = [c.v for c in rite_ring(model, ci, ri) if c.t == "struct"]
            assert marks == ["s_rite", *preorder(rite["steps"])], (circle["name"], rite["name"])


@pytest.mark.parametrize("path", PROGRAMS, ids=lambda p: p.stem)
def test_cell_pointers_are_in_the_canonical_pointer_space(path: Path) -> None:
    model = load(path)
    data = json.loads(dumps(model))
    for cell in all_bands(model):
        assert resolves(data, cell.pointer), (cell, path.name)


@pytest.mark.parametrize("path", PROGRAMS, ids=lambda p: p.stem)
def test_cell_kinds_are_v2_kinds(path: Path) -> None:
    assert {c.kind for c in all_bands(load(path))} <= set(DATA_JIN_KINDS_V2)


def test_latin_cells_hold_one_code_point() -> None:
    for path in PROGRAMS:
        assert all(len(c.v) == 1 for c in all_bands(load(path)) if c.t == "latin"), path


def test_a_public_state_carries_the_out_mark_and_a_private_one_does_not() -> None:
    # S2 の最終レビュー #3 → ユーザーの判断(b): out を銘帯に載せる(画素から図の二重線は読めない)
    model = load(REPO_ROOT / "examples-v2/paddle/paddle.jin")
    for ci, circle in enumerate(model.circles):
        cells = circle_ring(model, ci)
        for j, state in enumerate(circle.state):
            marks = [
                c
                for c in cells
                if c.v == "mark_out" and c.pointer.startswith(f"/circles/{ci}/state/{j}")
            ]
            assert len(marks) == (1 if state.out else 0), (circle.name, state.name)
    assert any(s.out for c in model.circles for s in c.state)


def test_the_standard_schema_url_is_not_inscribed_but_a_custom_one_is() -> None:
    model = load(REPO_ROOT / "examples-v2/fib/fib.jin")
    assert all(c.pointer != "/$schema" for c in frame_band(model))
    custom = model.model_copy(update={"schema_url": "https://example.com/x.json"})
    assert any(c.pointer == "/$schema" for c in frame_band(custom))


def test_a_param_name_and_a_form_typed_param_are_separated_by_a_colon() -> None:
    # 最終レビュー #1: 型紙名の型もラテンなので、名前との間に colon が無いと `pPointer` を切れない
    model = load(REPO_ROOT / "tests/fixtures/v2-programs/key_pointer.jin")
    for ci, circle in enumerate(model.circles):
        for ri, rite in enumerate(circle.rites):
            if any(p.type == "Pointer" for p in rite.params):
                cells = rite_ring(model, ci, ri)
                text = "".join(c.v if c.t == "latin" else f"<{c.v}>" for c in cells)
                assert "p<colon>Pointer" in text, text
                return
    raise AssertionError("Pointer 型の引数を持つ手順が fixture に無い")


def test_a_form_field_name_and_its_type_are_separated_by_a_colon() -> None:
    model = load(REPO_ROOT / "examples-v2/paddle/paddle.jin")
    text = "".join(c.v if c.t == "latin" else f"<{c.v}>" for c in frame_band(model))
    assert "<colon><t_num>" in text, text[:200]


def test_a_character_without_dots_is_escaped_with_its_code_point() -> None:
    # 最終レビュー #5: 全角空白は点が 1 つも無く、升が空に見えて復号で消える
    cells = expr_cells('"a　b"', "/x", "step")
    text = "".join(c.v if c.t == "latin" else f"<{c.v}>" for c in cells)
    assert "a<esc>u3000b" in text, text
    assert canonical_expr(to_expr(cells)) == canonical_expr('"a　b"')
