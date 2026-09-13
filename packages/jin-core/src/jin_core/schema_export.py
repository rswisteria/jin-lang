"""Pydantic 定義から JSON Schema（draft 2020-12）を生成する。

FR-MODEL-001 / NFR-SSOT-001: モデル定義が唯一の真実であり、`schemas/jin.schema.json`（v1）と
`schemas/jin-v2.schema.json`（v2）はここから生成する。CI（`test_committed_schema_has_no_drift`）で
ドリフトを検出する。

**直列化は本モジュールの `serialize` 1 箇所に閉じ込める。**
生成スクリプト（`scripts/generate_schema.py`）と CLI（`jin schema`）が同じ関数を通ることで、
「`jin schema` の標準出力が `schemas/jin.schema.json` とバイト一致」が構造的に保証される。

v2 は**別ファイル**にする（設計書 §11 #16）。`jin.schema.json` のルート `properties` を
`apps/editor` のフォーム生成が直接読むので、ルートを oneOf に変えるとエディタが壊れる。
"""

from __future__ import annotations

import json
from typing import Any

from jin_core.model import JinFile
from jin_core.v2.model import JinFileV2

#: リポジトリルートからの相対パス（v1）。
SCHEMA_PATH = "schemas/jin.schema.json"

#: 同（v2）。
SCHEMA_PATH_V2 = "schemas/jin-v2.schema.json"

#: 生成される JSON Schema 自身の `$id`。`.jin` の `$schema` が指す URL と一致させる。
SCHEMA_ID = "https://xtone.internal/jin/schemas/jin.schema.json"
SCHEMA_ID_V2 = "https://xtone.internal/jin/schemas/jin-v2.schema.json"

#: JSON Schema の方言（要件書 §1.1）。
SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"


def _build(root: type, schema_id: str, title: str) -> dict[str, Any]:
    schema = root.model_json_schema(by_alias=True, mode="validation")
    # Pydantic は方言と $id を付けないので、先頭に来るよう組み直す。
    ordered: dict[str, Any] = {"$schema": SCHEMA_DIALECT, "$id": schema_id}
    ordered.update(schema)
    ordered.setdefault("title", title)
    return ordered


def build_schema() -> dict[str, Any]:
    """`JinFile`（v1）から JSON Schema を作る。キー名は JSON 側（alias）を使う。"""
    return _build(JinFile, SCHEMA_ID, "JinFile")


def build_schema_v2() -> dict[str, Any]:
    """`JinFileV2` から JSON Schema を作る。"""
    return _build(JinFileV2, SCHEMA_ID_V2, "JinFileV2")


def serialize(schema: dict[str, Any]) -> str:
    """JSON Schema を**唯一の書式**でテキストにする。

    `.jin` の正準形とは別物（こちらは機械が読む公開契約なので `json` 標準の直列化で十分）だが、
    バイト一致を担保するため書式は 1 箇所に固定する。
    """
    return json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def render(version: int = 1) -> str:
    """`jin schema` と生成スクリプトが共通で呼ぶ入口。`version` は 1 か 2。"""
    if version == 1:
        return serialize(build_schema())
    if version == 2:
        return serialize(build_schema_v2())
    raise ValueError(f"version は 1 か 2 です: {version}")


__all__ = [
    "SCHEMA_DIALECT",
    "SCHEMA_ID",
    "SCHEMA_ID_V2",
    "SCHEMA_PATH",
    "SCHEMA_PATH_V2",
    "build_schema",
    "build_schema_v2",
    "render",
    "serialize",
]
