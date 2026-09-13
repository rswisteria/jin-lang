"""Jin v2 の診断（docs/spec/v2/diagnostics.md）: fixture の網羅と 1 コード性、位置、hint。

v1 の `test_check.py` と同じ規律を v2 の fixture ディレクトリ（`tests/fixtures/errors/v2/`）に張る:

- コード集合 == `V2_CODES` ∪ 共有番号（JIN001 を除く。段 1 は version を知らない）
- 各 fixture は**ちょうど 1 つ**のコードを出す
- すべての診断が位置・pointer・hint を持つ
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jin_core.check import check_file, check_text
from jin_core.diagnostics import V2_CODES, V2_SHARED_CODES

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "errors" / "v2"
PADDLE = REPO_ROOT / "examples-v2" / "paddle" / "paddle.jin"
FIB = REPO_ROOT / "examples-v2" / "fib" / "fib.jin"
ALL_FIXTURES = sorted(FIXTURE_DIR.glob("*.jin"))


def code_of(path: Path) -> str:
    return path.name.split("_", 1)[0]


def test_every_v2_code_has_a_fixture() -> None:
    expected = set(V2_CODES) | (set(V2_SHARED_CODES) - {"JIN001"})
    found = {code_of(p) for p in ALL_FIXTURES}
    assert found == expected, f"不足: {expected - found} / 余分: {found - expected}"


@pytest.mark.parametrize("path", ALL_FIXTURES, ids=lambda p: p.name)
def test_fixture_emits_exactly_its_own_code(path: Path) -> None:
    result = check_file(path)
    codes = [d.code for d in result.diagnostics]
    assert codes == [code_of(path)], f"{path.name}: {[d.message for d in result.diagnostics]}"


@pytest.mark.parametrize("path", ALL_FIXTURES, ids=lambda p: p.name)
def test_every_diagnostic_has_position_pointer_and_hint(path: Path) -> None:
    for diagnostic in check_file(path).diagnostics:
        assert diagnostic.range.start.line >= 1 and diagnostic.range.start.col >= 1
        start, end = diagnostic.range.start, diagnostic.range.end
        assert (end.line, end.col) >= (start.line, start.col)
        assert diagnostic.pointer == "" or diagnostic.pointer.startswith("/")
        assert diagnostic.hint, diagnostic


def test_expression_diagnostics_point_inside_the_literal() -> None:
    """式内の位置が JSON 文字列リテラルの中の列へ写る（expr.md §6 / spans.py）。"""
    text = (
        '{"$schema": "x", "version": 2, "root": "M", "stage": {"width": 64, "height": 64},\n'
        ' "circles": [{"name": "M", "core": "m",\n'
        '   "state": [{"name": "n", "type": "num", "init": "0"}],\n'
        '   "rites": [{"name": "m", "steps": [{"do": "set", "target": "n", "expr": "n + \\"a\\" + cnt"}]}]}]}\n'
    )
    result = check_text(text, "m.jin")
    codes = sorted(d.code for d in result.diagnostics)
    assert codes == ["JIN202", "JIN203"]
    unknown = next(d for d in result.diagnostics if d.code == "JIN203")
    line = text.split("\n")[3]
    # 列は 1 始まりコードポイント。原文の `cnt` を指す
    assert line[unknown.range.start.col - 1 : unknown.range.end.col - 1] == "cnt"
    assert unknown.pointer == "/circles/0/rites/0/steps/0/expr"


def test_semantic_diagnostics_are_deterministically_ordered() -> None:
    doc = {
        "$schema": "x",
        "version": 2,
        "root": "Nope",
        "stage": {"width": 64, "height": 64},
        "circles": [
            {"name": "M", "core": "zzz", "rites": [{"name": "m", "steps": [{"do": "break"}]}]}
        ],
    }
    text = json.dumps(doc, indent=1)
    first = [(d.code, d.pointer) for d in check_text(text, "a.jin").diagnostics]
    second = [(d.code, d.pointer) for d in check_text(text, "a.jin").diagnostics]
    assert first == second
    assert sorted(first) == [
        ("JIN011", "/circles/0/core"),
        ("JIN060", "/root"),
        ("JIN213", "/circles/0/rites/0/steps/0"),
    ]


# ---------------------------------------------------------------- analyze_model（Phase 5・LSP が読む）


def test_analyze_model_records_types_and_scopes_per_pointer() -> None:
    from jin_core.v2.semantic import analyze_model

    model = check_file(PADDLE).model
    assert model is not None
    analysis = analyze_model(model)
    assert analysis.diagnostics == []
    assert analysis.types["/circles/1/state/0/init"] == "Ball"
    assert analysis.types["/circles/0/flow/exit"] == "bool"
    # 手順の中の式: 局所（params）と state と道具環が見える
    scope = analysis.scope_at("/circles/1/rites/2/steps/0/expr")
    assert scope is not None and scope.circle == "Play"
    assert set(scope.locals) == {"dt"} and "ball" in scope.state and "canvas" in scope.sigils
    # 式そのものが記録されていない pointer でも、ステップ / 手順 / 陣へ遡る
    assert analysis.scope_at("/circles/1/rites/2/steps/0/nope") is scope
    assert analysis.scope_at("/circles/1/rites/2") is not None
    assert analysis.scope_at("/stage") is None
    # state.init は定数式のスコープ（識別子は見えない）
    constant = analysis.scope_at("/circles/1/state/0/init")
    assert constant is not None and constant.constant and constant.locals == {}


def test_analyze_model_scope_is_a_snapshot_at_that_step() -> None:
    """`let` で増えた局所は、その後のステップにだけ見える。"""
    from jin_core.v2.semantic import analyze_model

    model = check_file(FIB).model
    assert model is not None
    analysis = analyze_model(model)
    steps = model.circles[0].rites[0].steps
    first = analysis.scope_at("/circles/0/rites/0/steps/0")
    last = analysis.scope_at(f"/circles/0/rites/0/steps/{len(steps) - 1}")
    assert first is not None and last is not None
    assert set(first.locals) < set(last.locals)
