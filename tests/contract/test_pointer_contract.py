"""パッケージ横断契約: JSON Pointer 空間の一致（ADR-006 / boundary_contracts「JSON Pointer」）。

pointer はファイル内の位置・描画要素（data-jin）・診断・トレースを結ぶ唯一の鍵であり、
それらが同一の Pointer 空間を共有することをここで固定する。

Phase 1 時点で存在するのは「ソース位置」「モデル」「診断」の 3 者。
data-jin（Phase 3）とトレース（Phase 2）は、このテストに行を足す形で接続する。
"""

from __future__ import annotations

import json
from pathlib import Path

from jin_cli.resolver import ImportResolver
from jin_core.canonical import dumps
from jin_core.check import check_file
from jin_core.parser import parse_text
from jin_core.pointer import (
    escape_token,
    join,
    loc_to_pointer,
    pointer_exists,
    resolve_pointer,
    split_pointer,
)

from tests.conftest import fixture_code


def _model_pointers(node, prefix: str = "") -> set[str]:
    """素の JSON 値に現れる全 pointer を集める。"""
    found = {prefix}
    if isinstance(node, dict):
        for key, value in node.items():
            found |= _model_pointers(value, join(prefix, key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found |= _model_pointers(value, join(prefix, index))
    return found


def test_source_table_covers_every_model_pointer(formattable_paths: list[Path]) -> None:
    """モデルの pointer 集合は、ソース由来の対応表の**部分集合**である（docs/spec/model.md §6）。"""
    for path in formattable_paths:
        result = check_file(path)
        assert result.model is not None and result.table is not None
        model_pointers = _model_pointers(json.loads(dumps(result.model)))
        missing = model_pointers - set(result.table.value_ranges)
        assert not missing, f"{path}: 対応表に無いモデル pointer {sorted(missing)[:5]}"


def test_every_table_pointer_resolves_in_the_model_for_canonical_files(
    example_paths: list[Path],
) -> None:
    """正準形のファイルでは、対応表の全 pointer がモデルに解決できる。

    design.yaml implementation_phases.items[1].verification.machine
    「pointer→range 対応表の全 pointer がモデルに解決できる」に対応する。
    examples は正準形であることを別テストで担保済み。
    """
    for path in example_paths:
        result = check_file(path)
        model_json = json.loads(dumps(result.model))
        for pointer in result.table.value_ranges:
            assert pointer_exists(model_json, pointer), f"{path}: {pointer}"


def test_every_diagnostic_pointer_resolves_in_the_source(
    error_fixture_paths: list[Path],
) -> None:
    for path in error_fixture_paths:
        code = fixture_code(path)
        if code == "JIN001":
            continue  # 構文エラーはルート pointer のみ
        result = check_file(path, resolver=ImportResolver() if code == "JIN040" else None)
        source = json.loads(path.read_text(encoding="utf-8"))
        for diagnostic in result.diagnostics:
            assert pointer_exists(source, diagnostic.pointer), f"{path}: {diagnostic.pointer}"


def test_every_diagnostic_range_is_inside_the_file(error_fixture_paths: list[Path]) -> None:
    for path in error_fixture_paths:
        code = fixture_code(path)
        lines = path.read_text(encoding="utf-8").splitlines()
        result = check_file(path, resolver=ImportResolver() if code == "JIN040" else None)
        for diagnostic in result.diagnostics:
            start, end = diagnostic.range.start, diagnostic.range.end
            assert 1 <= start.line <= len(lines), f"{path}: {diagnostic.code} の行が範囲外"
            assert 1 <= end.line <= len(lines)
            assert start.col >= 1 and end.col >= 1
            assert (start.line, start.col) <= (end.line, end.col)


def test_pointer_escaping_roundtrips() -> None:
    for token in ["a", "a/b", "a~b", "~1", "/", "", "あ"]:
        assert split_pointer(join("", token)) == [token]
        assert escape_token(token).count("/") == 0


def test_loc_to_pointer_handles_union_tag_optional_and_alias() -> None:
    """ADR-006 の constraints「loc → pointer の変換規則を判別共用体・Optional・エイリアスについて
    網羅的にテストする」への対応。"""
    document = {
        "$schema": "u",
        "version": 1,
        "root": "A",
        "circles": [
            {
                "name": "A",
                "core": "m",
                "tools": [{"name": "t", "kind": "summon", "circle": "B"}],
                "boundary": {"await": ["t"], "guards": [{"on": "before_tool", "ref": "m:g"}]},
                "flow": {"kind": "loop", "steps": [], "max": 1},
            }
        ],
    }
    cases = {
        ("$schema",): "/$schema",  # エイリアス
        ("circles", 0, "boundary", "await", 0): "/circles/0/boundary/await/0",  # 予約語エイリアス
        ("circles", 0, "tools", 0, "summon", "circle"): "/circles/0/tools/0/circle",  # 判別タグ
        ("circles", 0, "flow", "max"): "/circles/0/flow/max",  # Optional
        ("circles", 0, "tools", 0): "/circles/0/tools/0",
        (): "",
    }
    for loc, expected in cases.items():
        assert loc_to_pointer(document, loc) == expected, loc


def test_loc_to_pointer_for_missing_key_points_at_the_missing_child() -> None:
    document = {"version": 1, "root": "A", "circles": []}
    assert loc_to_pointer(document, ("$schema",)) == "/$schema"
    assert not pointer_exists(document, "/$schema")


def test_table_resolve_walks_up_to_an_existing_ancestor() -> None:
    table = parse_text('{"circles": [{"name": "A"}]}').table
    assert table.resolve("/circles/0/missing") == table.value_ranges["/circles/0"]
    assert table.resolve("/circles/9/missing") == table.value_ranges["/circles"]


def test_resolve_pointer_matches_manual_navigation(example_paths: list[Path]) -> None:
    for path in example_paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        assert resolve_pointer(document, "/circles/0/name") == document["circles"][0]["name"]
