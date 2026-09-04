"""意味モデル（Pydantic v2）の契約テスト。"""

from __future__ import annotations

import json

import pytest
from jin_core.check import check_text
from jin_core.model import (
    DEFAULT_SCHEMA_URL,
    MAX_IDENT_LENGTH,
    MAX_TEXT_LENGTH,
    JinFile,
)
from pydantic import ValidationError


def minimal() -> dict:
    return {
        "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
        "version": 1,
        "root": "A",
        "circles": [{"name": "A", "core": "m", "instruction": {"rune": "hi"}}],
    }


def test_minimal_document_validates() -> None:
    model = JinFile.model_validate(minimal())
    assert model.root == "A"
    assert model.circles[0].name == "A"
    assert model.circles[0].tools == []


def test_schema_alias_is_dollar_schema() -> None:
    model = JinFile.model_validate(minimal())
    assert model.schema_url.endswith("jin.schema.json")


def test_await_alias_is_await_keyword() -> None:
    doc = minimal()
    doc["circles"][0]["tools"] = [{"name": "t", "kind": "tool", "ref": "m:f"}]
    doc["circles"][0]["boundary"] = {"await": ["t"]}
    model = JinFile.model_validate(doc)
    assert model.circles[0].boundary is not None
    assert model.circles[0].boundary.await_ == ["t"]


def test_unknown_key_is_rejected() -> None:
    doc = minimal()
    doc["circles"][0]["nope"] = 1
    with pytest.raises(ValidationError):
        JinFile.model_validate(doc)


def test_strict_mode_rejects_string_for_int() -> None:
    """ "max": "3" が黙って 3 に変換されると fmt が値を書き換えてしまう。"""
    doc = minimal()
    doc["circles"] = [{"name": "A", "flow": {"kind": "loop", "steps": [], "max": "3"}}]
    with pytest.raises(ValidationError):
        JinFile.model_validate(doc)


def test_tools_discriminated_union() -> None:
    doc = minimal()
    doc["circles"][0]["tools"] = [
        {"name": "a", "kind": "tool", "ref": "m:f"},
        {"name": "b", "kind": "builtin", "builtin": "google_search"},
        {"name": "c", "kind": "summon", "circle": "A"},
    ]
    model = JinFile.model_validate(doc)
    kinds = [t.kind for t in model.circles[0].tools]
    assert kinds == ["tool", "builtin", "summon"]


def test_tool_kind_mismatch_is_rejected() -> None:
    doc = minimal()
    doc["circles"][0]["tools"] = [{"name": "a", "kind": "tool", "circle": "A"}]
    with pytest.raises(ValidationError):
        JinFile.model_validate(doc)


def test_version_must_be_one() -> None:
    doc = minimal()
    doc["version"] = 2
    with pytest.raises(ValidationError):
        JinFile.model_validate(doc)


def test_field_order_matches_spec() -> None:
    """正準形のキー順はスキーマ定義順。docs/spec/model.md §3 の表の順であること。"""
    from jin_core.model import Circle

    assert list(Circle.model_fields) == [
        "name",
        "core",
        "description",
        "instruction",
        "tools",
        "delegate",
        "state",
        "flow",
        "boundary",
    ]
    assert list(JinFile.model_fields) == ["schema_url", "version", "root", "circles"]


def test_examples_validate() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    for path in sorted(root.glob("examples/*/*.jin")):
        JinFile.model_validate(json.loads(path.read_text(encoding="utf-8")))


# --------------------------------------------------------------------------------------
# 修正ラウンド 1 の回帰テスト
# --------------------------------------------------------------------------------------
def _flow(kind: str, **extra) -> dict:
    return {
        "$schema": DEFAULT_SCHEMA_URL,
        "version": 1,
        "root": "A",
        "circles": [
            {"name": "A", "flow": {"kind": kind, "steps": ["B"], **extra}},
            {"name": "B", "core": "m"},
        ],
    }


@pytest.mark.parametrize("kind", ["sequence", "parallel"])
@pytest.mark.parametrize("extra", [{"max": 3}, {"exit": {"key": "k", "equals": True}}])
def test_max_and_exit_are_rejected_outside_loop(kind: str, extra: dict) -> None:
    """B-3: `max` / `exit` は kind: loop でだけ意味を持つ（docs/spec/model.md §3.4）。

    黙って通すと ADK 生成側で捨てられる。要件書 §3.3「ADK に対応物のない Jin 構造は
    コンパイル時エラー。黙って落とさない」に従い、段 2（スキーマ）で落とす。
    """
    with pytest.raises(ValidationError):
        JinFile.model_validate(_flow(kind, **extra))


@pytest.mark.parametrize("extra", [{"max": 3}, {"exit": {"key": "k", "equals": True}}])
def test_max_and_exit_are_accepted_on_loop(extra: dict) -> None:
    JinFile.model_validate(_flow("loop", **extra))


def test_max_and_exit_on_sequence_is_reported_as_jin002() -> None:
    """B-3 の診断側。JIN030（loop に max も exit も無い）と混同しない。"""
    result = check_text(json.dumps(_flow("sequence", max=3)), "t.jin")
    assert [d.code for d in result.diagnostics] == ["JIN002"]
    assert result.diagnostics[0].pointer == "/circles/0/flow"


# ---- S13: 文字列の長さ上限 -------------------------------------------------------------
def _with_name(name: str) -> dict:
    return {
        "$schema": DEFAULT_SCHEMA_URL,
        "version": 1,
        "root": name,
        "circles": [{"name": name, "core": "m"}],
    }


def test_identifier_at_the_limit_is_accepted() -> None:
    JinFile.model_validate(_with_name("a" * MAX_IDENT_LENGTH))


def test_identifier_over_the_limit_is_rejected() -> None:
    """S13: 名前の長さに上限を置く（編集距離の計算量と診断出力の大きさの根）。"""
    with pytest.raises(ValidationError):
        JinFile.model_validate(_with_name("a" * (MAX_IDENT_LENGTH + 1)))


def test_free_text_over_the_limit_is_rejected() -> None:
    document = {
        "$schema": DEFAULT_SCHEMA_URL,
        "version": 1,
        "root": "A",
        "circles": [{"name": "A", "core": "m", "description": "x" * (MAX_TEXT_LENGTH + 1)}],
    }
    with pytest.raises(ValidationError):
        JinFile.model_validate(document)


def test_free_text_allows_newlines_and_tabs() -> None:
    document = {
        "$schema": DEFAULT_SCHEMA_URL,
        "version": 1,
        "root": "A",
        "circles": [{"name": "A", "core": "m", "instruction": {"rune": "1 行目\n2 行目\tタブ"}}],
    }
    JinFile.model_validate(document)


@pytest.mark.parametrize("bad", ["a\nb", "a\tb", "a\x1bb"])
def test_identifiers_reject_every_control_character(bad: str) -> None:
    """S13 / S6: 名前は改行もタブも許さない（診断 1 行を偽装できるため）。"""
    with pytest.raises(ValidationError):
        JinFile.model_validate(_with_name(bad))
