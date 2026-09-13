"""Jin v2 のモデル・schema 生成・振り分け（Phase 1 里程標 1）。

- `schemas/jin-v2.schema.json` / `schemas/abilities.json` が Pydantic 定義とバイト一致（ドリフト検出）
- `version: 2` が v2 のルートモデルへ振り分けられ、`version: 1` の経路は 1 バイトも変わらない
- `examples-v2/` の 3 本が段 2 を通り、正準形である
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jin_core.canonical import dumps
from jin_core.check import check_file, check_text, models_at, root_model_for
from jin_core.diagnostics import CANONICAL_CODES, V2_CODES, V2_SHARED_CODES
from jin_core.model import JinFile
from jin_core.schema_export import (
    SCHEMA_ID_V2,
    SCHEMA_PATH,
    SCHEMA_PATH_V2,
    build_schema,
    build_schema_v2,
    render,
    serialize,
)
from jin_core.v2.abilities import ABILITIES_PATH, NAMESPACES, render_abilities
from jin_core.v2.model import STEP_KINDS, JinFileV2, parse_type

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_V2 = sorted((REPO_ROOT / "examples-v2").glob("*/*.jin"))

MINIMAL_V2 = {
    "$schema": "https://xtone.internal/jin/schemas/jin-v2.schema.json",
    "version": 2,
    "root": "Main",
    "stage": {"width": 64, "height": 64},
    "circles": [{"name": "Main", "core": "main", "rites": [{"name": "main", "steps": []}]}],
}


# ---------------------------------------------------------------- schema のドリフト


def test_committed_v2_schema_has_no_drift() -> None:
    committed = (REPO_ROOT / SCHEMA_PATH_V2).read_text(encoding="utf-8")
    assert committed == serialize(build_schema_v2()) == render(2)


def test_committed_abilities_has_no_drift() -> None:
    committed = (REPO_ROOT / ABILITIES_PATH).read_text(encoding="utf-8")
    assert committed == render_abilities()


def test_v1_schema_is_untouched_by_v2() -> None:
    """v1 の `jin.schema.json` は 1 バイトも変わらない（エディタがルート properties を読む）。"""
    committed = (REPO_ROOT / SCHEMA_PATH).read_text(encoding="utf-8")
    assert committed == render(1) == render()
    schema = build_schema()
    assert schema["properties"]["version"] == {"const": 1, "title": "Version", "type": "integer"}
    assert "oneOf" not in schema


def test_v2_schema_shape() -> None:
    schema = build_schema_v2()
    assert schema["$id"] == SCHEMA_ID_V2
    assert schema["properties"]["version"] == {"const": 2, "title": "Version", "type": "integer"}
    assert schema["additionalProperties"] is False
    for name, definition in schema["$defs"].items():
        if definition.get("type") == "object":
            assert definition.get("additionalProperties") is False, name
    steps = schema["$defs"]["Rite"]["properties"]["steps"]["items"]
    assert steps["discriminator"]["propertyName"] == "do"
    assert set(steps["discriminator"]["mapping"]) == set(STEP_KINDS)


def test_render_rejects_unknown_version() -> None:
    with pytest.raises(ValueError):
        render(3)


# ---------------------------------------------------------------- 振り分け


def test_root_model_dispatches_on_version() -> None:
    assert root_model_for({"version": 2}) is JinFileV2
    assert root_model_for({"version": 1}) is JinFile
    assert root_model_for({}) is JinFile
    assert root_model_for({"version": "2"}) is JinFile
    assert root_model_for([]) is JinFile


def test_version_2_document_validates_against_v2() -> None:
    result = check_text(json.dumps(MINIMAL_V2), "m.jin")
    assert isinstance(result.model, JinFileV2)
    assert result.diagnostics == []


def test_version_3_is_a_v1_schema_error_with_hint() -> None:
    text = json.dumps({**MINIMAL_V2, "version": 3})
    result = check_text(text, "m.jin")
    # v1 の経路に落ちるので、/version（許容値 1）に加えて v1 に無いキー（stage / rites）も JIN002 になる。
    assert result.model is None
    assert {d.code for d in result.diagnostics} == {"JIN002"}
    version_diag = next(d for d in result.diagnostics if d.pointer == "/version")
    assert version_diag.hint == "許容値: 1"


def test_models_at_follows_the_v2_root_and_the_do_tag() -> None:
    document = {
        **MINIMAL_V2,
        "circles": [
            {
                "name": "Main",
                "core": "main",
                "rites": [{"name": "main", "steps": [{"do": "wait", "ticks": "1"}]}],
            }
        ],
    }
    assert models_at("", document) == [JinFileV2]
    (cls,) = models_at("/circles/0/rites/0/steps/0", document)
    assert cls.__name__ == "WaitStep"


def test_unknown_key_hint_lists_v2_keys() -> None:
    text = json.dumps({**MINIMAL_V2, "tools": []})
    result = check_text(text, "m.jin")
    (diag,) = result.diagnostics
    assert diag.code == "JIN002"
    assert diag.hint is not None
    assert "stage" in diag.hint and "forms" in diag.hint


def test_unknown_step_kind_hint_names_the_do_tag() -> None:
    document = {
        **MINIMAL_V2,
        "circles": [
            {"name": "Main", "core": "main", "rites": [{"name": "main", "steps": [{"do": "jump"}]}]}
        ],
    }
    result = check_text(json.dumps(document), "m.jin")
    (diag,) = result.diagnostics
    assert diag.code == "JIN002"
    assert diag.hint is not None
    assert diag.hint.startswith("do は")


# ---------------------------------------------------------------- モデルの段 2 規則


@pytest.mark.parametrize(
    "patch",
    [
        {"stage": {"width": 64.0, "height": 64}},  # 整数値でない
        {"stage": {"width": 8, "height": 64}},  # 下限
        {"root": "1abc"},  # 名前の文法
    ],
    ids=["float-size", "too-small", "bad-name"],
)
def test_stage_and_name_rules_are_schema_errors(patch: dict) -> None:
    result = check_text(json.dumps({**MINIMAL_V2, **patch}), "m.jin")
    assert [d.code for d in result.diagnostics] == ["JIN002"]


@pytest.mark.parametrize(
    "step",
    [
        {"do": "loop", "kind": "each", "steps": []},  # name / in が無い
        {"do": "loop", "kind": "while", "cond": "true", "times": "3", "steps": []},  # 余分
        {"do": "wait"},  # ticks も until も無い
        {"do": "wait", "ticks": "1", "until": "true"},  # 両方
    ],
    ids=["each-missing", "while-extra", "wait-none", "wait-both"],
)
def test_step_key_rules_are_schema_errors(step: dict) -> None:
    document = {
        **MINIMAL_V2,
        "circles": [{"name": "Main", "core": "main", "rites": [{"name": "main", "steps": [step]}]}],
    }
    result = check_text(json.dumps(document), "m.jin")
    assert [d.code for d in result.diagnostics] == ["JIN002"]


def test_flow_circle_cannot_carry_state_and_loop_needs_exit() -> None:
    flow_with_state = {
        **MINIMAL_V2,
        "circles": [
            {
                "name": "Main",
                "flow": {"kind": "sequence", "steps": ["Main"]},
                "state": [{"name": "x", "type": "num", "init": "0"}],
            }
        ],
    }
    result = check_text(json.dumps(flow_with_state), "m.jin")
    assert [d.code for d in result.diagnostics] == ["JIN002"]
    assert result.diagnostics[0].pointer == "/circles/0"
    loop_without_exit = {
        **MINIMAL_V2,
        "circles": [{"name": "Main", "flow": {"kind": "loop", "steps": ["Main"]}}],
    }
    result = check_text(json.dumps(loop_without_exit), "m.jin")
    assert [d.code for d in result.diagnostics] == ["JIN002"]


def test_parse_type_accepts_nesting_and_rejects_garbage() -> None:
    assert parse_type("list<list<Ball>>") == ("list", "list<Ball>")
    assert parse_type("num") == ("num", None)
    with pytest.raises(ValueError):
        parse_type("list<num")
    with pytest.raises(ValueError):
        parse_type("list<>")


# ---------------------------------------------------------------- 診断コード表


def test_v2_codes_do_not_overlap_v1_and_shared_codes_exist_in_v1() -> None:
    assert not set(V2_CODES) & set(CANONICAL_CODES)
    assert set(V2_SHARED_CODES) <= set(CANONICAL_CODES)
    assert len(CANONICAL_CODES) == 14, "v1 の表を増やしてはいけない"


def test_abilities_catalog_namespaces() -> None:
    assert [ns.name for ns in NAMESPACES] == ["canvas", "input", "ui", "audio", "random"]


# ---------------------------------------------------------------- examples-v2


def test_there_are_three_v2_examples() -> None:
    assert [p.stem for p in EXAMPLES_V2] == ["clicker", "fib", "paddle"]


@pytest.mark.parametrize("path", EXAMPLES_V2, ids=[p.stem for p in EXAMPLES_V2])
def test_example_v2_passes_the_pipeline_and_is_canonical(path: Path) -> None:
    result = check_file(path)
    assert isinstance(result.model, JinFileV2)
    assert result.diagnostics == []
    assert path.read_text(encoding="utf-8") == dumps(result.model)


# ---------------------------------------------------------------- 式の欄の印（Phase 5）


def test_expression_fields_carry_the_editor_mark_in_the_schema() -> None:
    """設計書 §8: エディタは schema の `x-jin-expr` だけを見て式エディタを出す。

    `Expr` そのもの・`list[Expr]`（`cast.args`）・`Expr | None`（`into` / `in` / `exit`）・
    alias 付き（`assert`）のどれにも載る。v1 の `jin.schema.json` には現れない。
    """
    from jin_core.v2.model import EXPR_SCHEMA_MARK

    defs = build_schema_v2()["$defs"]
    assert defs["SetStep"]["properties"]["expr"][EXPR_SCHEMA_MARK] is True
    assert defs["CastStep"]["properties"]["args"]["items"][EXPR_SCHEMA_MARK] is True
    assert defs["CastStep"]["properties"]["into"]["anyOf"][0][EXPR_SCHEMA_MARK] is True
    assert defs["LoopStep"]["properties"]["in"]["anyOf"][0][EXPR_SCHEMA_MARK] is True
    assert defs["Guard"]["properties"]["assert"][EXPR_SCHEMA_MARK] is True
    assert defs["Flow"]["properties"]["exit"]["anyOf"][0][EXPR_SCHEMA_MARK] is True
    description = defs["Circle"]["properties"]["description"]
    assert EXPR_SCHEMA_MARK not in description.get("anyOf", [{}])[0]
    assert EXPR_SCHEMA_MARK not in serialize(build_schema())


def test_expr_fields_follow_the_mark_without_naming_the_fields() -> None:
    from jin_core.v2.model import CastStep, Circle, Guard, LoopStep, State, expr_fields

    assert expr_fields(CastStep) == {"target", "args", "into"}
    assert expr_fields(LoopStep) == {"cond", "in", "times"}
    assert expr_fields(Guard) == {"assert"}
    assert expr_fields(State) == {"init"}
    assert expr_fields(Circle) == frozenset()
