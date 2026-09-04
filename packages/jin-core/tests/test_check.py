"""診断パイプライン（構文 → スキーマ → 意味）と fixture の 1 コード検証。

design.yaml implementation_phases.items[1].verification.machine の第 1 条件:
「§2.4 の 12 コードそれぞれに tests/fixtures/errors/JINxxx_*.jin が 1 つ以上存在し、
  そのファイルが対応コードをちょうど 1 つだけ出す」
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jin_core.check import JinReadError, check_file, check_text, read_source
from jin_core.diagnostics import CANONICAL_CODES, PROPOSED_CODES
from jin_core.resolver import check_ref_format

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "errors"
EXAMPLES = sorted((REPO_ROOT / "examples").glob("*/*.jin"))

#: JIN040 は --resolve を付けたときだけ出る（docs/spec/diagnostics.md §6）。
RESOLVE_ONLY_CODES = {"JIN040"}

#: このスタブが import できたことにするモジュール。
IMPORTABLE_FOR_TEST = {"json", "pathlib"}


class StubResolver:
    """テスト用の `RefResolver`。**import は一切しない**。

    `jin_core` に実 import を置かないのが S1 の修正そのものなので、jin-core 側の
    テストは決まった答えを返すスタブを注入して JIN040 の**診断経路**だけを確かめる。
    実際に import する `ImportResolver` は `packages/jin-cli/tests/test_cli.py` で検証する。
    """

    def resolve(self, ref: str) -> str | None:
        reason = check_ref_format(ref)
        if reason is not None:
            return reason
        module_name = ref.partition(":")[0]
        if module_name in IMPORTABLE_FOR_TEST:
            return None
        return f"モジュール {module_name} を import できません（ModuleNotFoundError）"


def resolver_for(code: str) -> StubResolver | None:
    return StubResolver() if code in RESOLVE_ONLY_CODES else None


ALL_FIXTURES = sorted(FIXTURE_DIR.glob("*.jin"))


def code_of(path: Path) -> str:
    return path.name.split("_", 1)[0]


# --------------------------------------------------------------------------------------
# fixture の網羅と 1 コード性
# --------------------------------------------------------------------------------------
def test_every_documented_code_has_a_fixture() -> None:
    expected = set(CANONICAL_CODES) | set(PROPOSED_CODES)
    found = {code_of(p) for p in ALL_FIXTURES}
    assert found == expected, f"不足: {expected - found} / 余分: {found - expected}"


@pytest.mark.parametrize("path", ALL_FIXTURES, ids=lambda p: p.name)
def test_fixture_emits_exactly_its_own_code(path: Path) -> None:
    code = code_of(path)
    result = check_file(path, resolver=resolver_for(code))
    codes = [d.code for d in result.diagnostics]
    assert codes == [code], f"{path.name}: {codes}"


@pytest.mark.parametrize(
    "path", [p for p in ALL_FIXTURES if code_of(p) in RESOLVE_ONLY_CODES], ids=lambda p: p.name
)
def test_resolve_only_fixture_is_clean_without_resolve(path: Path) -> None:
    assert check_file(path, resolver=None).diagnostics == []


@pytest.mark.parametrize("path", ALL_FIXTURES, ids=lambda p: p.name)
def test_every_diagnostic_has_position_pointer_and_hint(path: Path) -> None:
    result = check_file(path, resolver=resolver_for(code_of(path)))
    for diagnostic in result.diagnostics:
        assert diagnostic.range.start.line >= 1
        assert diagnostic.range.start.col >= 1
        assert diagnostic.file == str(path)
        assert diagnostic.message
        assert diagnostic.hint, f"{diagnostic.code} に hint が無い（NFR-LLM-001）"


# --------------------------------------------------------------------------------------
# examples はクリーン
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_examples_have_no_diagnostics(path: Path) -> None:
    assert check_file(path).diagnostics == []


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_examples_produce_a_model(path: Path) -> None:
    assert check_file(path).model is not None


# --------------------------------------------------------------------------------------
# パイプラインの段階制御（docs/spec/diagnostics.md §1）
# --------------------------------------------------------------------------------------
def test_schema_stage_does_not_run_when_syntax_fails() -> None:
    result = check_text('{"a": 1,}', "x.jin")
    assert [d.code for d in result.diagnostics] == ["JIN001"]
    assert result.model is None


def test_semantic_stage_does_not_run_when_schema_fails() -> None:
    doc = {
        "$schema": "u",
        "version": 1,
        "root": "Nope",  # 単独なら JIN060 になるが、スキーマ違反があるので出ない
        "circles": [{"name": "A", "core": "m", "zzz": 1}],
    }
    result = check_text(json.dumps(doc), "x.jin")
    assert [d.code for d in result.diagnostics] == ["JIN002"]


def test_schema_stage_reports_every_violation() -> None:
    doc = {"$schema": "u", "version": 1, "root": "A", "circles": [{"name": 1, "zzz": 2}]}
    result = check_text(json.dumps(doc), "x.jin")
    assert len(result.diagnostics) == 2
    assert {d.code for d in result.diagnostics} == {"JIN002"}


def test_semantic_stage_reports_every_violation() -> None:
    doc = {
        "$schema": "u",
        "version": 1,
        "root": "Nope",
        "circles": [{"name": "A"}],
    }
    result = check_text(json.dumps(doc), "x.jin")
    assert sorted(d.code for d in result.diagnostics) == ["JIN022", "JIN060"]


# --------------------------------------------------------------------------------------
# hint の具体性（NFR-LLM-001）
# --------------------------------------------------------------------------------------
def test_jin011_hint_suggests_close_name() -> None:
    result = check_file(FIXTURE_DIR / "JIN011_unresolved_summon.jin")
    assert "Summarizer" in (result.diagnostics[0].hint or "")


def test_jin031_hint_suggests_close_name() -> None:
    result = check_file(FIXTURE_DIR / "JIN031_step_is_not_a_circle.jin")
    assert "Drafter" in (result.diagnostics[0].hint or "")


def test_jin060_hint_suggests_close_name() -> None:
    result = check_file(FIXTURE_DIR / "JIN060_root_not_found.jin")
    assert "Researcher" in (result.diagnostics[0].hint or "")


def test_jin050_hint_lists_visible_state_keys() -> None:
    result = check_file(FIXTURE_DIR / "JIN050_rune_key_not_in_state.jin")
    assert "query" in (result.diagnostics[0].hint or "")


def test_jin002_unknown_key_hint_lists_allowed_keys() -> None:
    result = check_file(FIXTURE_DIR / "JIN002_unknown_key.jin")
    hint = result.diagnostics[0].hint or ""
    assert "instruction" in hint and "boundary" in hint


def test_jin002_missing_key_points_at_parent_range() -> None:
    doc = {"version": 1, "root": "A", "circles": [{"name": "A", "core": "m"}]}
    result = check_text(json.dumps(doc, indent=2), "x.jin")
    assert result.diagnostics[0].code == "JIN002"
    assert result.diagnostics[0].pointer == "/$schema"
    assert result.diagnostics[0].range.start.line == 1  # ルートへフォールバック


# --------------------------------------------------------------------------------------
# 診断 JSON の形（要件書 §5 / FR-CLI-002）
# --------------------------------------------------------------------------------------
def test_diagnostic_json_shape() -> None:
    result = check_file(FIXTURE_DIR / "JIN060_root_not_found.jin")
    payload = result.diagnostics[0].to_json_dict()
    assert set(payload) == {"file", "pointer", "range", "code", "severity", "message", "hint"}
    assert set(payload["range"]) == {"start", "end"}
    assert set(payload["range"]["start"]) == {"line", "col"}
    json.dumps(payload, ensure_ascii=False)


def test_pointer_resolves_in_source_document() -> None:
    from jin_core.pointer import resolve_pointer

    for path in ALL_FIXTURES:
        code = code_of(path)
        if code in {"JIN001"}:
            continue
        result = check_file(path, resolver=resolver_for(code))
        raw = json.loads(path.read_text(encoding="utf-8"))
        for diagnostic in result.diagnostics:
            resolve_pointer(raw, diagnostic.pointer)


# --------------------------------------------------------------------------------------
# 修正ラウンド 1 の回帰テスト
# --------------------------------------------------------------------------------------
def test_check_file_on_a_directory_raises_jin_read_error(tmp_path: Path) -> None:
    """S5: 読めないパスは素の `IsADirectoryError` ではなく `JinReadError` にする。"""
    directory = tmp_path / "a.jin"
    directory.mkdir()
    with pytest.raises(JinReadError):
        check_file(directory)


def test_check_file_on_a_missing_file_raises_jin_read_error(tmp_path: Path) -> None:
    with pytest.raises(JinReadError):
        check_file(tmp_path / "nope.jin")


def test_check_file_on_a_non_utf8_file_returns_jin001(tmp_path: Path) -> None:
    """S5: 符号化の失敗は診断（段 1）にする。例外を外へ出さない。"""
    path = tmp_path / "sjis.jin"
    path.write_bytes('{"root": "あ"}'.encode("shift_jis"))
    result = check_file(path)
    assert [d.code for d in result.diagnostics] == ["JIN001"]
    assert "UTF-8" in result.diagnostics[0].message


def test_read_source_does_not_translate_newlines(tmp_path: Path) -> None:
    """D-2: CRLF を LF に畳まない。畳むと `fmt --check` が嘘をつく。"""
    path = tmp_path / "crlf.jin"
    path.write_bytes(b'{\r\n  "a": 1\r\n}\r\n')
    assert read_source(path) == '{\r\n  "a": 1\r\n}\r\n'
