"""ADK に対応物のない Jin 構造がコンパイル時エラーになる（NFR-FAIL-001）。

design.yaml Phase 2 machine 条件 8「ADK に対応物のない Jin 構造がコンパイル時エラーに
なる（NFR-FAIL-001・**黙って落とさないこと**の fixture テスト）」。

## fixture の性質（ここが肝）

`tests/fixtures/adk-gaps/*.jin` は **`jin check` を診断 0 件で通る**。
意味検査で拾えるものはそもそも診断コードを持っているので、ここに置くのは
「Jin としては正しいが ADK に写せない」ものだけである。
`test_every_fixture_is_clean_for_jin_check` がその性質自体を固定する
（診断で落ちる fixture を混ぜると、コンパイル時エラーの網が効いているかどうか分からなくなる）。

## 「黙って落とさない」の意味

`CompileError` を投げること**だけ**では足りない。落とした箇所の pointer が
モデルに解決できて、hint に直し方が書いてあるところまで見る。
pointer が空だとエディタが該当箇所へ飛べず、結局「どこが悪いか分からない」に戻る。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from jin_adk.codegen import generate
from jin_adk.errors import CompileError
from jin_core.canonical import dumps
from jin_core.check import check_file
from jin_core.pointer import pointer_exists

FIXTURES = Path(__file__).parent / "fixtures" / "adk-gaps"
FIXTURE_PATHS = sorted(FIXTURES.glob("*.jin"))
FIXTURE_IDS = [path.stem for path in FIXTURE_PATHS]

#: fixture 名 → エラーメッセージに必ず含まれる語。
#: **どの理由で落ちたか**まで見る。別の理由で落ちているだけだと、狙った検査が
#: 効いていなくても緑になる（Phase 0+1 で 5 件あった偽 green と同じ形）。
EXPECTED_REASON = {
    "await_on_a_summon": "LongRunningFunctionTool にできません",
    "bad_guard_ref_format": "import 文を作れません",
    "bad_ref_format": "import 文を作れません",
    "circle_named_root_agent": "エントリポイント名と衝突します",
    "exit_agent_name_collision": "判定エージェント名と衝突します",
    "flow_circle_with_delegate": "delegate は写せません",
    "flow_circle_with_instruction": "instruction は写せません",
    "flow_circle_with_model_guard": "コールバックは写せません",
    "flow_circle_with_out_state": "out: true は写せません",
    "flow_circle_with_tools": "tools は写せません",
    "name_is_a_python_keyword": "Python の識別子である必要があります",
    "name_not_identifier": "Python の識別子である必要があります",
    "name_reserved_by_adk": "ADK が予約しています",
    "two_out_states": "output_key は 1 つしか取れません",
    "unknown_builtin": "google-adk 2.8.0 にありません",
}


def test_there_is_at_least_one_fixture() -> None:
    """glob が空でも全テストが素通りしてしまわないようにする。"""
    assert len(FIXTURE_PATHS) >= 10


def test_every_fixture_has_an_expected_reason() -> None:
    """fixture を足したら期待する理由も足させる（黙って「どれかで落ちた」で済ませない）。"""
    assert sorted(EXPECTED_REASON) == FIXTURE_IDS


@pytest.mark.parametrize("path", FIXTURE_PATHS, ids=FIXTURE_IDS)
def test_every_fixture_is_clean_for_jin_check(path: Path) -> None:
    """fixture は**診断を 1 件も出さない**（意味検査では拾えない穴であることの固定）。"""
    result = check_file(path)
    assert result.diagnostics == [], (
        f"{path.name} は jin check で診断が出る。ここに置くのは"
        "「Jin としては正しいが ADK に写せない」ものだけ"
    )


@pytest.mark.parametrize("path", FIXTURE_PATHS, ids=FIXTURE_IDS)
def test_every_fixture_fails_to_compile(path: Path, load_jin: Callable) -> None:
    """黙って落とさない: 必ず `CompileError` になる。"""
    with pytest.raises(CompileError):
        generate(load_jin(path))


@pytest.mark.parametrize("path", FIXTURE_PATHS, ids=FIXTURE_IDS)
def test_every_fixture_fails_for_the_expected_reason(path: Path, load_jin: Callable) -> None:
    """**狙った理由で**落ちていること。"""
    expected = EXPECTED_REASON[path.stem]
    with pytest.raises(CompileError) as raised:
        generate(load_jin(path))
    messages = [issue.message for issue in raised.value.issues]
    assert any(expected in message for message in messages), (
        f"{path.name} が期待した理由で落ちていない。期待: {expected!r} / 実際: {messages}"
    )


@pytest.mark.parametrize("path", FIXTURE_PATHS, ids=FIXTURE_IDS)
def test_every_issue_points_at_a_place_in_the_model(path: Path, load_jin: Callable) -> None:
    """pointer がモデルに解決できること（エディタが該当箇所へ飛べる・要件書 §10 #11）。"""
    import json

    model = load_jin(path)
    document = json.loads(dumps(model))
    with pytest.raises(CompileError) as raised:
        generate(model)
    for issue in raised.value.issues:
        assert issue.pointer, f"pointer が空: {issue.message}"
        assert pointer_exists(document, issue.pointer), (
            f"pointer {issue.pointer} がモデルに解決できない: {issue.message}"
        )


@pytest.mark.parametrize("path", FIXTURE_PATHS, ids=FIXTURE_IDS)
def test_every_issue_has_a_hint_telling_the_reader_what_to_do(
    path: Path, load_jin: Callable
) -> None:
    """要件書 §5「メッセージは『何が悪いか + どう直すか』を必ず含める」。"""
    with pytest.raises(CompileError) as raised:
        generate(load_jin(path))
    for issue in raised.value.issues:
        assert issue.hint.strip(), f"hint が空: {issue.message}"
        assert "ください" in issue.hint, f"hint が指示になっていない: {issue.hint}"


def test_all_issues_are_reported_at_once(
    tmp_path: Path, load_jin: Callable, minimal_jin: Callable, write_jin: Callable
) -> None:
    """1 件目で止めない（`jin check` が全診断を返すのと同じ）。"""
    payload = minimal_jin(
        root="Flow",
        circles=[
            {
                "name": "Flow",
                "instruction": {"rune": "x"},
                "tools": [{"name": "t", "kind": "tool", "ref": "m:t"}],
                "flow": {"kind": "sequence", "steps": ["Step"]},
            },
            {"name": "Step", "core": "m", "instruction": {"rune": "y"}},
        ],
    )
    with pytest.raises(CompileError) as raised:
        generate(load_jin(write_jin(tmp_path, "a.jin", payload)))
    assert len(raised.value.issues) == 2


def test_the_cli_reports_compile_errors_as_diagnostics(tmp_path: Path) -> None:
    """`jin build` がトレースバックではなく診断の体裁で落ちる（exit 1）。"""
    from jin_cli.main import app
    from typer.testing import CliRunner

    result = CliRunner().invoke(
        app,
        ["build", str(FIXTURES / "two_out_states.jin"), "--out", str(tmp_path)],
    )
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "ADK に写せません" in result.output
    assert "hint:" in result.output


def test_a_failed_build_writes_nothing(tmp_path: Path) -> None:
    """コンパイルできないときに**中途半端な生成物を残さない**。

    残すと `adk run` が古い生成物を拾って、直したつもりの `.jin` と食い違う。
    """
    from jin_cli.main import app
    from typer.testing import CliRunner

    out = tmp_path / "out"
    result = CliRunner().invoke(
        app, ["build", str(FIXTURES / "two_out_states.jin"), "--out", str(out)]
    )
    assert result.exit_code == 1
    assert not out.exists() or list(out.rglob("*")) == []
