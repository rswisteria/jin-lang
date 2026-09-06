"""CLI（Phase 2: build / run）のテスト。ネットワーク・API キー不要（`--model fake`）。"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from jin_cli.main import app
from jin_core.pointer import resolve_pointer
from typer.testing import CliRunner

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPO_ROOT / "examples"
STUBS = REPO_ROOT / "tests" / "fixtures" / "stubs"
BUILD_ERRORS = REPO_ROOT / "tests" / "fixtures" / "build-errors"

runner = CliRunner()


def run(*args: str):
    return runner.invoke(app, list(args))


@pytest.fixture(autouse=True)
def stubs_on_path(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.syspath_prepend(str(STUBS))
    yield
    for name in [m for m in sys.modules if m == "research" or m.startswith("research.")]:
        sys.modules.pop(name, None)


def test_help_lists_phase2_commands() -> None:
    result = run("--help")
    assert result.exit_code == 0
    for name in ("check", "fmt", "schema", "dump", "build", "run"):
        assert name in result.output


# --------------------------------------------------------------------------------------
# jin build
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["researcher", "pipeline"])
def test_build_writes_the_project_layout(tmp_path: Path, name: str) -> None:
    root = {"researcher": "Researcher", "pipeline": "Pipeline"}[name]
    result = run("build", str(EXAMPLES / name / f"{name}.jin"), "--out", str(tmp_path))
    assert result.exit_code == 0, result.output
    assert (tmp_path / root / "__init__.py").is_file()
    assert (tmp_path / root / "agent.py").is_file()
    assert (tmp_path / ".env.example").is_file()


def test_build_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    source = str(EXAMPLES / "pipeline" / "pipeline.jin")
    assert run("build", source, "--out", str(tmp_path)).exit_code == 0
    (tmp_path / "Pipeline" / "agent.py").write_text("mine\n", encoding="utf-8")
    result = run("build", source, "--out", str(tmp_path))
    assert result.exit_code == 1
    assert "--force" in result.output
    assert (tmp_path / "Pipeline" / "agent.py").read_text(encoding="utf-8") == "mine\n"
    assert run("build", source, "--out", str(tmp_path), "--force").exit_code == 0
    assert "root_agent" in (tmp_path / "Pipeline" / "agent.py").read_text(encoding="utf-8")


def test_build_reports_diagnostics_and_exits_one(tmp_path: Path) -> None:
    bad = tmp_path / "bad.jin"
    bad.write_text(
        '{"$schema": "x", "version": 1, "root": "Nope", "circles": []}\n', encoding="utf-8"
    )
    result = run("build", str(bad), "--out", str(tmp_path / "out"))
    assert result.exit_code == 1
    assert "JIN060" in result.output
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("path", sorted(BUILD_ERRORS.glob("*.jin")), ids=lambda p: p.stem)
def test_build_fails_loudly_on_structures_without_an_adk_counterpart(
    tmp_path: Path, path: Path
) -> None:
    """NFR-FAIL-001 / machine 条件 8: exit 1 + 何が悪いか + hint。ファイルは 1 つも作らない。"""
    result = run("build", str(path), "--out", str(tmp_path / "out"))
    assert result.exit_code == 1, result.output
    assert "hint:" in result.output
    assert "pointer:" in result.output
    assert not (tmp_path / "out").exists()


def test_build_rejects_non_jin_and_missing_files(tmp_path: Path) -> None:
    assert run("build", str(REPO_ROOT / "README.md"), "--out", str(tmp_path)).exit_code == 2
    assert run("build", str(tmp_path / "nope.jin"), "--out", str(tmp_path)).exit_code == 2


@pytest.mark.parametrize(
    ("name", "shown"),
    [
        (
            "x\nimport os; os.system('id')\n#.jin",
            "\\u000a",
        ),  # F-S-P2-001: 改行入りの名前（Linux では合法）
        ("a\x1b[2Kb.jin", "\\u001b"),  # F-S-P2-016: 診断表示を偽装できるエスケープ
        ("bad\udcff.jin", "\\udcff"),  # F-S-P2-005: 不正 UTF-8 バイト（surrogateescape）
    ],
)
def test_unsafe_file_names_are_rejected_at_the_entry(tmp_path: Path, name: str, shown: str) -> None:
    """ファイル名は `.jin` 本文と違って検査を通っていない。入口で exit 2、表示は `_safe` の可視表現（`shown`）を通す。"""
    import shutil

    target = tmp_path / name
    shutil.copy(EXAMPLES / "pipeline" / "pipeline.jin", target)
    for command in (
        ["build", str(target), "--out", str(tmp_path / "out")],
        ["run", str(target), "go", "--model", "fake"],
    ):
        result = run(*command)
        assert result.exit_code == 2, result.output
        assert shown in result.output, result.output
        assert "\x1b" not in result.output  # 生のエスケープは出ない（名前は可視表現に置換される）
        assert result.output.count("\n") == 1  # 1 行の診断（生の改行で行が割れない）
    assert not (tmp_path / "out").exists()
    # 存在しない名前でも同じ（stderr へ生の改行が出ない・F-S-P2-016）
    missing = run("build", str(tmp_path / "gone\nline2.jin"), "--out", str(tmp_path / "out"))
    assert missing.exit_code == 2 and "\\u000a" in missing.output


def test_build_reports_write_failures_without_a_traceback(tmp_path: Path) -> None:
    """F-S-P2-004: `--out` が通常ファイルでもトレースバックにしない（exit 1 + 文）。"""
    regular = tmp_path / "regfile"
    regular.write_text("x", encoding="utf-8")
    result = run("build", str(EXAMPLES / "pipeline" / "pipeline.jin"), "--out", str(regular))
    assert result.exit_code == 1, result.output
    assert "Traceback" not in result.output and "regfile" in result.output


# --------------------------------------------------------------------------------------
# jin run --model fake
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["researcher", "pipeline"])
def test_run_with_fake_model_completes_and_writes_a_valid_trace(tmp_path: Path, name: str) -> None:
    """machine 条件 5 / 6 / 7。"""
    trace = tmp_path / "trace.jsonl"
    source = EXAMPLES / name / f"{name}.jin"
    result = run("run", str(source), "こんにちは", "--model", "fake", "--trace", str(trace))
    assert result.exit_code == 0, result.output
    lines = [line for line in trace.read_text(encoding="utf-8").split("\n") if line]
    assert lines
    from jin_core.check import check_file

    model = check_file(source).model
    document = json.loads(model.model_dump_json(by_alias=True, exclude_defaults=True))
    for i, line in enumerate(lines, start=1):
        record = json.loads(line)
        assert list(record) == ["seq", "ts", "agent", "kind", "name", "pointer", "input", "output"]
        assert record["seq"] == i
        assert record["kind"] in {"model", "tool", "transfer", "escalate", "final"}
        assert record["pointer"] is not None
        resolve_pointer(document, record["pointer"])
    assert "pointer を解決できませんでした" not in result.output


def test_run_streams_events_to_stdout(tmp_path: Path) -> None:
    result = run("run", str(EXAMPLES / "pipeline" / "pipeline.jin"), "go", "--model", "fake")
    assert result.exit_code == 0, result.output
    assert "[1] Drafter model gemini-2.5-flash /circles/2/core" in result.output
    assert "escalate Refine /circles/1/flow/exit" in result.output


def test_run_rejects_other_model_values() -> None:
    result = run(
        "run", str(EXAMPLES / "pipeline" / "pipeline.jin"), "go", "--model", "gemini-2.5-flash"
    )
    assert result.exit_code == 2
    assert "fake" in result.output


def test_run_reports_build_errors_and_exits_one() -> None:
    result = run("run", str(BUILD_ERRORS / "two_out_states.jin"), "go", "--model", "fake")
    assert result.exit_code == 1
    assert "out: true" in result.output


def test_failed_run_does_not_empty_an_existing_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-S-P2-006 / F-C-P2-009: `BuildError` でも `RunError` でも前回のトレースを 0 バイトにしない。"""
    trace = tmp_path / "t.jsonl"
    previous = '{"seq": 1, "previous": "trace"}\n'
    trace.write_text(previous, encoding="utf-8")
    build_error = run(
        "run",
        str(BUILD_ERRORS / "two_out_states.jin"),
        "go",
        "--model",
        "fake",
        "--trace",
        str(trace),
    )
    assert build_error.exit_code == 1
    assert trace.read_text(encoding="utf-8") == previous
    # RunError（ref 先が無い）: 行が 1 つも出ないまま失敗する
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != str(STUBS)])
    for name in [m for m in sys.modules if m == "research" or m.startswith("research.")]:
        sys.modules.pop(name, None)
    monkeypatch.chdir(tmp_path)
    run_error = run(
        "run",
        str(EXAMPLES / "researcher" / "researcher.jin"),
        "go",
        "--model",
        "fake",
        "--trace",
        str(trace),
    )
    assert run_error.exit_code == 1, run_error.output
    assert trace.read_text(encoding="utf-8") == previous


def test_successful_run_replaces_the_previous_trace(tmp_path: Path) -> None:
    trace = tmp_path / "t.jsonl"
    trace.write_text('{"previous": true}\n' * 50, encoding="utf-8")
    result = run(
        "run",
        str(EXAMPLES / "pipeline" / "pipeline.jin"),
        "go",
        "--model",
        "fake",
        "--trace",
        str(trace),
    )
    assert result.exit_code == 0, result.output
    lines = [line for line in trace.read_text(encoding="utf-8").split("\n") if line]
    assert lines and all('"previous"' not in line for line in lines)
    assert json.loads(lines[0])["seq"] == 1


def test_trace_file_is_created_owner_only(tmp_path: Path) -> None:
    """F-S-P2-008: トレースはツール引数・state の実値・モデル出力を含むので 0600 で作る（§2.22）。"""
    trace = tmp_path / "t.jsonl"
    result = run(
        "run",
        str(EXAMPLES / "pipeline" / "pipeline.jin"),
        "go",
        "--model",
        "fake",
        "--trace",
        str(trace),
    )
    assert result.exit_code == 0, result.output
    current_umask = os.umask(0)
    os.umask(current_umask)
    assert stat.S_IMODE(trace.stat().st_mode) == 0o600 & ~current_umask


def test_existing_trace_file_is_made_owner_only(tmp_path: Path) -> None:
    """F-C-P2-103: `O_CREAT` の mode は新規作成時にしか効かない。前回 0644 で作った既存のトレースを
    `--trace` に指定し直しても、今回の内容（ツール引数・state・モデル出力）が world-readable のまま
    書かれないよう `os.fchmod` で 0600 にする（§6 手順 7 / §2.22: 新規でも既存でも 0600）。"""
    trace = tmp_path / "t.jsonl"
    trace.write_text("old\n", encoding="utf-8")
    trace.chmod(0o644)
    assert stat.S_IMODE(trace.stat().st_mode) == 0o644
    result = run(
        "run",
        str(EXAMPLES / "pipeline" / "pipeline.jin"),
        "go",
        "--model",
        "fake",
        "--trace",
        str(trace),
    )
    assert result.exit_code == 0, result.output
    assert stat.S_IMODE(trace.stat().st_mode) == 0o600
    assert "old" not in trace.read_text(encoding="utf-8")


def test_run_reports_import_failure_without_a_traceback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """ref 先が無い（スタブを外す）と RunError → exit 1。トレースバックを表に出さない。"""
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != str(STUBS)])
    for name in [m for m in sys.modules if m == "research" or m.startswith("research.")]:
        sys.modules.pop(name, None)
    monkeypatch.chdir(tmp_path)
    result = run("run", str(EXAMPLES / "researcher" / "researcher.jin"), "go", "--model", "fake")
    assert result.exit_code == 1, result.output
    assert "research" in result.output
    assert "Traceback" not in result.output


def test_run_cleans_up_the_temporary_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    original = tempfile.mkdtemp

    def spy(*args, **kwargs):
        path = original(*args, **kwargs)
        seen.append(path)
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o700
        return path

    monkeypatch.setattr(tempfile, "mkdtemp", spy)
    result = run("run", str(EXAMPLES / "pipeline" / "pipeline.jin"), "go", "--model", "fake")
    assert result.exit_code == 0, result.output
    assert len(seen) == 1 and not os.path.exists(seen[0])


def test_run_does_not_follow_a_symlinked_trace_target(tmp_path: Path) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_text("keep\n", encoding="utf-8")
    link = tmp_path / "trace.jsonl"
    link.symlink_to(victim)
    result = run(
        "run",
        str(EXAMPLES / "pipeline" / "pipeline.jin"),
        "go",
        "--model",
        "fake",
        "--trace",
        str(link),
    )
    assert result.exit_code == 1
    assert victim.read_text(encoding="utf-8") == "keep\n"


def test_cwd_is_on_sys_path_only_while_importing_the_generated_module(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`research.*` を cwd から解決できる（スタブを cwd にコピーして sys.path からは外す）。

    DP-IMPL-JIN-P2-SYSPATH-01（再々判断）: cwd は生成モジュールの **import の間だけ** `sys.path` の
    末尾にあり（`research.*` が解決できる）、**実行後は含まれない**。Runner 実行中に ADK が遅延 import
    する未インストールの名前を cwd から解決させない（F-S-P2-101）。
    import 中の状態は `_import_agent_module` を包んで観測する（import が成功した事実だけでは
    「窓の外でも残っている」実装と区別できないため、両方を見る）。
    """
    import shutil

    import jin_adk.runtime

    shutil.copytree(STUBS / "research", tmp_path / "research")
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != str(STUBS)])
    for name in [m for m in sys.modules if m == "research" or m.startswith("research.")]:
        sys.modules.pop(name, None)
    monkeypatch.chdir(tmp_path)
    during: list[list[str]] = []
    original = jin_adk.runtime._import_agent_module

    def spy(path: Path):
        during.append(list(sys.path))
        return original(path)

    monkeypatch.setattr(jin_adk.runtime, "_import_agent_module", spy)
    result = run("run", str(EXAMPLES / "researcher" / "researcher.jin"), "go", "--model", "fake")
    assert result.exit_code == 0, result.output
    assert len(during) == 1 and str(tmp_path) in during[0], "import 中に cwd が sys.path に無い"
    assert during[0][0] != str(tmp_path), "cwd が先頭にある（site-packages の名前を差し替えられる）"
    assert str(tmp_path) not in sys.path, "実行後も cwd が sys.path に残っている（Runner 中も残る）"


def _write_cancel_jin(tmp_path: Path, root_kind: str) -> Path:
    tool = {"name": "t", "kind": "tool", "ref": "cancel_tool:fn"}
    if root_kind == "llm":
        circles, root = [{"name": "R", "core": "m", "tools": [tool]}], "R"
    else:
        circles, root = (
            [
                {"name": "Seq", "flow": {"kind": "sequence", "steps": ["A", "B"]}},
                {"name": "A", "core": "m", "tools": [tool]},
                {"name": "B", "core": "m"},
            ],
            "Seq",
        )
    jin = tmp_path / f"cancel_{root_kind}.jin"
    jin.write_text(
        json.dumps(
            {
                "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
                "version": 1,
                "root": root,
                "circles": circles,
            }
        ),
        encoding="utf-8",
    )
    return jin


@pytest.mark.parametrize("root_kind", ["llm", "sequence"])
def test_tool_cancelled_error_is_a_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, root_kind: str
) -> None:
    """F-S-P2-201 / 202: ツール関数の `asyncio.CancelledError` → exit 1・stderr 1 行・トレースバック無し。
    root=LlmAgent（修正前 exit 0・「1 イベント」= fail-open）と root=sequence（修正前フルトレースバック）の両方。"""
    import jin_cli.main
    from jin_adk.fake_llm import FakeLlm, FakeToolCall

    monkeypatch.setattr(
        jin_cli.main,
        "FakeLlm",
        lambda: FakeLlm(responses=[FakeToolCall(name="fn", args={"query": "q"}), "done"]),
    )
    result = run("run", str(_write_cancel_jin(tmp_path, root_kind)), "go", "--model", "fake")
    assert result.exit_code == 1, result.output
    assert "CancelledError" in result.output or "応答を返さず" in result.output
    assert "Traceback" not in result.output
    assert "イベント（session" not in result.output, "失敗なのに成功時の件数行が出ている"


def test_await_pause_still_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """F-S-P2-201 の誤検知防止（CLI）: `await` の正規 pause（long-running ツールが None を返す）は exit 0 のまま。"""
    import jin_cli.main
    import research.tools
    from jin_adk.fake_llm import FakeLlm, FakeToolCall

    def publish(text: str) -> None:
        return None

    monkeypatch.setattr(research.tools, "publish", publish)
    monkeypatch.setattr(
        jin_cli.main,
        "FakeLlm",
        lambda: FakeLlm(responses=[FakeToolCall(name="publish", args={"text": "d"}), "done"]),
    )
    result = run("run", str(EXAMPLES / "researcher" / "researcher.jin"), "go", "--model", "fake")
    assert result.exit_code == 0, result.output
    assert "1 イベント" in result.output


def test_cli_turns_a_stray_cancelled_error_into_one_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """F-S-P2-202 の保険: runtime が区別できずに `CancelledError` を素通りさせても、CLI は 1 行・exit 1 にする
    （トレースバックにしない）。runtime を差し替えて直接 `CancelledError` を出す。"""
    import asyncio

    import jin_cli.main

    async def cancelled(*_args, **_kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(jin_cli.main, "run_model_async", cancelled)
    result = run("run", str(EXAMPLES / "pipeline" / "pipeline.jin"), "go", "--model", "fake")
    assert result.exit_code == 1, result.output
    assert "実行がキャンセルされました" in result.output
    assert "Traceback" not in result.output


def test_tool_sys_exit_at_runtime_is_a_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """F-S-P2-102（修正ラウンド 1 の回帰）: **ツール実行中**の `sys.exit(0)` を exit 0 にしない。

    asyncio は `SystemExit` をタスクの結果にせずループの外へ再送出するので、`run_model_async` の
    `except BaseException` では捕まらない。CLI が `asyncio.run` を包んで exit 1・stderr に
    `SystemExit`・トレースバック無し（asyncio の shutdown ログも出さない）。
    """
    import jin_cli.main
    from jin_adk.fake_llm import FakeLlm, FakeToolCall

    monkeypatch.setattr(
        jin_cli.main,
        "FakeLlm",
        lambda: FakeLlm(responses=[FakeToolCall(name="boom", args={"x": "1"}), "done"]),
    )
    jin = tmp_path / "exits.jin"
    jin.write_text(
        json.dumps(
            {
                "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
                "version": 1,
                "root": "R",
                "circles": [
                    {
                        "name": "R",
                        "core": "m",
                        "tools": [{"name": "t", "kind": "tool", "ref": "exits_tool:boom"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = run("run", str(jin), "go", "--model", "fake")
    assert result.exit_code == 1, result.output
    assert "SystemExit" in result.output
    assert "Traceback" not in result.output
    assert "asyncio" not in result.output, "asyncio の shutdown ログが漏れている"


def test_the_build_success_message_does_not_carry_control_characters(tmp_path: Path) -> None:
    """`jin build` の成功文言も `_safe` を通す（F-W-P3-008 / 104）。

    `--out` は利用者が渡すパスで、端末に出す前に制御文字を落とさないと
    ANSI エスケープで表示を偽装できる。`jin render` 側は R1 で直したが
    `jin build` 側は残っていた。
    """
    out = tmp_path / "o\u0007ut"
    result = run("build", "examples/pipeline/pipeline.jin", "--out", str(out))
    assert result.exit_code == 0, result.output
    assert "書き出しました" in result.output
    assert "\u0007" not in result.output


@pytest.mark.skipif(not Path("/dev/full").exists(), reason="/dev/full が無い")
def test_a_full_stdout_on_the_build_success_message_is_one_line_not_a_traceback(
    tmp_path: Path,
) -> None:
    """`jin build` の成功文言も、書けなければ 1 行 + exit 1（F-C-P3-303 / F-W-P3-301）。

    R3 の B-3 で `render` と `build` の両方を `_echo_or_exit` に通したが、テストは
    `render` 側にしか無く、`build` 側だけ `typer.echo` に戻しても緑だった。
    `build` は 1 ファイルにつき 1 行出すので、**最初の 1 行で落ちる**ことも見る
    （残りの行を出し続けて何十行も溢れさせない）。生成物は出来ていること。
    """
    jin = Path(sys.executable).parent / "jin"
    out = tmp_path / "out"
    with Path("/dev/full").open("wb") as full:
        result = subprocess.run(
            [str(jin), "build", str(EXAMPLES / "pipeline" / "pipeline.jin"), "--out", str(out)],
            cwd=REPO_ROOT,
            stdout=full,
            stderr=subprocess.PIPE,
            check=False,
        )
    message = result.stderr.decode("utf-8", "replace")
    assert result.returncode == 1, (result.returncode, message)
    assert "標準出力に書けません" in message, message
    assert "Traceback" not in message, message
    assert len(message.splitlines()) == 1, message
    assert (out / "Pipeline" / "agent.py").exists(), "生成そのものは終わっているはず"
