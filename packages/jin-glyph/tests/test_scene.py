"""場面グラフ(`.jinscene.json`)の型。spec §3.2 の形と schema の生成物を固定する。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jin_glyph.scene import SCENE_SCHEMA_PATH, JinScene, render_scene_schema
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[3]

#: spec §3.2 の例(コメントを外し、座標を数にしたもの)
EXAMPLE = {
    "jinscene": 1,
    "sheet": "S",
    "image": {"sha256": "0" * 64, "width": 4032, "height": 3024},
    "figures": [
        {"id": "f3", "kind": "ring.rites", "at": [100.0, 100.0]},
        {"id": "f12", "kind": "step.set", "at": [120.5, 80.0], "ring": "f3", "angle": 41.5},
        {"id": "f30", "kind": "rite", "at": [300.0, 80.0]},
    ],
    "bands": [
        {
            "owner": "f12",
            "cells": [
                {"t": "latin", "v": "s", "box": [10.0, 20.0, 30.0, 40.0]},
                {"t": "latin", "v": "c"},
                {"t": "glyph", "v": "sep"},
                {"t": "glyph", "v": "add"},
                {"t": "latin", "v": "1", "unsure": ["l", "I"]},
            ],
        }
    ],
    "lines": [{"from": "f12", "to": "f30", "style": "dashed"}],
}


def test_the_spec_example_validates_and_round_trips() -> None:
    scene = JinScene.model_validate_json(json.dumps(EXAMPLE))
    assert scene.bands[0].cells[4].unsure == ["l", "I"]
    dumped = json.loads(scene.model_dump_json(by_alias=True, exclude_defaults=True))
    assert dumped["lines"] == [{"from": "f12", "to": "f30", "style": "dashed"}]
    assert JinScene.model_validate(dumped) == scene


def test_struct_cells_and_the_full_sheet_are_accepted() -> None:
    # S3: デコーダは銘環の始まりの印・構造の印もそのまま升に残す(JIN301 / JIN302 を構文解析器が見るため)
    scene = json.loads(json.dumps(EXAMPLE))
    scene["sheet"] = "full"
    scene["bands"][0]["cells"] = [{"t": "struct", "v": "start"}, {"t": "struct", "v": "s_set"}]
    assert JinScene.model_validate(scene).bands[0].cells[1].v == "s_set"
    scene["bands"][0]["cells"] = [{"t": "struct", "v": "add"}]
    with pytest.raises(ValidationError, match="add"):
        JinScene.model_validate(scene)


def test_an_unknown_glyph_id_is_rejected() -> None:
    bad = json.loads(json.dumps(EXAMPLE))
    bad["bands"][0]["cells"][1] = {"t": "glyph", "v": "nope"}
    with pytest.raises(ValidationError, match="nope"):
        JinScene.model_validate(bad)


@pytest.mark.parametrize("value", ["score", "", "まほ"])
def test_a_latin_cell_holds_exactly_one_code_point(value: str) -> None:
    # 最終レビュー #3: 1 升 = 1 字(コードポイント)。認識器と構文解析器で規約を割らない
    bad = json.loads(json.dumps(EXAMPLE))
    bad["bands"][0]["cells"][0] = {"t": "latin", "v": value}
    with pytest.raises(ValidationError, match="1 字"):
        JinScene.model_validate(bad)


def test_a_latin_cell_accepts_a_japanese_character() -> None:
    ok = json.loads(json.dumps(EXAMPLE))
    ok["bands"][0]["cells"][0] = {"t": "latin", "v": "ま"}
    assert JinScene.model_validate(ok).bands[0].cells[0].v == "ま"


def test_duplicate_figure_ids_are_rejected() -> None:
    bad = json.loads(json.dumps(EXAMPLE))
    bad["figures"].append({"id": "f12", "kind": "step.let", "at": [0.0, 0.0]})
    with pytest.raises(ValidationError, match="f12"):
        JinScene.model_validate(bad)


def test_unknown_keys_are_rejected() -> None:
    bad = json.loads(json.dumps(EXAMPLE))
    bad["extra"] = 1
    with pytest.raises(ValidationError):
        JinScene.model_validate(bad)


def test_the_committed_schema_matches_the_model() -> None:
    committed = (REPO_ROOT / SCENE_SCHEMA_PATH).read_text(encoding="utf-8")
    assert committed == render_scene_schema(), (
        "schemas/jin-scene.schema.json がずれている。uv run python scripts/generate_schema.py を実行してコミットする"
    )
