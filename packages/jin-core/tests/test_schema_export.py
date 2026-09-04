"""JSON Schema の生成とコミット済みファイルとのドリフト検出（FR-MODEL-001 / NFR-SSOT-001）。"""

from __future__ import annotations

import json
from pathlib import Path

from jin_core.schema_export import SCHEMA_PATH, build_schema, serialize

REPO_ROOT = Path(__file__).resolve().parents[3]
COMMITTED = REPO_ROOT / SCHEMA_PATH


def test_schema_is_draft_2020_12() -> None:
    schema = build_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_schema_has_id() -> None:
    assert build_schema()["$id"] == "https://xtone.internal/jin/schemas/jin.schema.json"


def test_schema_uses_json_side_key_names() -> None:
    schema = build_schema()
    assert "$schema" in schema["properties"]
    assert "version" in schema["properties"]
    boundary = schema["$defs"]["Boundary"]["properties"]
    assert "await" in boundary
    assert "await_" not in boundary


def test_additional_properties_is_false_everywhere() -> None:
    """未知のキーはスキーマ違反（要件書 §2.2）。"""
    schema = build_schema()
    assert schema["additionalProperties"] is False
    for name, definition in schema["$defs"].items():
        if definition.get("type") == "object":
            assert definition.get("additionalProperties") is False, name


def test_tools_is_a_discriminated_union() -> None:
    tool_items = build_schema()["$defs"]["Circle"]["properties"]["tools"]["items"]
    assert "discriminator" in tool_items or "oneOf" in tool_items or "anyOf" in tool_items


def test_serialize_is_stable_and_ends_with_newline() -> None:
    text = serialize(build_schema())
    assert text.endswith("\n")
    assert text == serialize(build_schema())
    json.loads(text)


def test_committed_schema_has_no_drift() -> None:
    """コミット済み schemas/jin.schema.json が Pydantic 定義から再生成した内容とバイト一致すること。

    失敗したら `uv run python scripts/generate_schema.py` で再生成してコミットする。
    """
    assert COMMITTED.exists(), f"{SCHEMA_PATH} が存在しない"
    assert COMMITTED.read_text(encoding="utf-8") == serialize(build_schema())
