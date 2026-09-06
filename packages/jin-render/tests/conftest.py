"""jin-render のテストで共有する道具。

**`jin_adk` を import しない**（design.yaml rule 4 / ADR-003）。これを機械で落とすのは
`tests/contract/test_packaging_contract.py::test_package_tests_only_import_the_jin_packages_that_package_depends_on`
である（`test_every_package_declares_the_jin_packages_it_imports` は `src/` しか見ない・F-W-P3-006 / 102）。
トレースを使うテストはコミット済みの `tests/fixtures/traces/pipeline-fake.jsonl` を読む。
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest
from jin_core.check import check_file
from jin_core.model import JinFile

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPO_ROOT / "examples"
ERROR_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "errors"
TRACE_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "traces" / "pipeline-fake.jsonl"

SVG_NS = "http://www.w3.org/2000/svg"

#: `<svg>` 自身と `<defs>` 配下は `data-jin` 契約の対象外（docs/spec/layout.md §3）。
EXCLUDED_TAGS = frozenset({f"{{{SVG_NS}}}svg", f"{{{SVG_NS}}}defs"})


def load_model(path: Path) -> JinFile:
    result = check_file(path)
    assert result.model is not None, path
    return result.model


def parse(svg: str) -> ET.Element:
    return ET.fromstring(svg)


def contract_elements(svg: str) -> list[ET.Element]:
    """`data-jin` 契約の対象となる要素（`<svg>` と `<defs>` 配下を除く全要素）。"""
    root = parse(svg)
    found: list[ET.Element] = []

    def walk(node: ET.Element, inside_defs: bool) -> None:
        for child in node:
            in_defs = inside_defs or child.tag == f"{{{SVG_NS}}}defs"
            if not in_defs:
                found.append(child)
            walk(child, in_defs)

    assert root.tag == f"{{{SVG_NS}}}svg"
    walk(root, False)
    return found


def pointers(svg: str) -> list[str | None]:
    """各要素の `data-jin`。**欠落は `None`** で返す（F-V-P3-025）。

    既定値 `""` へ潰すと、`pointer_exists(document, "")` が真なので
    「属性が無い要素」が pointer 解決テストを素通りしていた。
    """
    return [element.get("data-jin") for element in contract_elements(svg)]


def fired_pointers(svg: str) -> set[str]:
    return {
        element.get("data-jin", "")
        for element in contract_elements(svg)
        if element.get("data-jin-fired") == "1"
    }


def trace_rows() -> list[dict[str, Any]]:
    """コミット済みの `jin run --model fake` のトレース（11 行）。"""
    text = TRACE_FIXTURE.read_text(encoding="utf-8")
    # JSONL の区切りは `\n` だけ（`splitlines()` は U+2028 などでも割る・F-C-P3-001）
    return [json.loads(line) for line in text.split("\n") if line]


@pytest.fixture(scope="session")
def researcher() -> JinFile:
    return load_model(EXAMPLES / "researcher" / "researcher.jin")


@pytest.fixture(scope="session")
def pipeline() -> JinFile:
    return load_model(EXAMPLES / "pipeline" / "pipeline.jin")


def model_from(circles: list[dict[str, Any]], root: str) -> JinFile:
    """テスト用の最小モデル。`$schema` / `version` は正準形と同じ既定値。"""
    return JinFile.model_validate(
        {
            "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
            "version": 1,
            "root": root,
            "circles": circles,
        }
    )
