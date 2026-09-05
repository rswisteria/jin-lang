"""パッケージ横断契約: CLI の出力が jin-core の関数と同じものを返すこと。

design.yaml implementation_phases.items[1].verification.machine のうち、
プロセス境界をまたいで初めて意味を持つ条件をここで検証する。
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import UNFORMATTABLE_CODES, fixture_code

REPO_ROOT = Path(__file__).resolve().parents[2]
JIN = Path(sys.executable).parent / "jin"


def _run(
    *args: str, env_extra: dict[str, str] | None = None, cwd: Path = REPO_ROOT
) -> subprocess.CompletedProcess[str]:
    assert JIN.exists(), f"jin コマンドが見つからない: {JIN}"
    env = {**os.environ, **(env_extra or {})}
    if env_extra and "PYTHONPATH" in env_extra and os.environ.get("PYTHONPATH"):
        # 開発者の既存 PYTHONPATH を捨てない（F-W-P2-007）。スタブは前置する
        env["PYTHONPATH"] = os.pathsep.join([env_extra["PYTHONPATH"], os.environ["PYTHONPATH"]])
    return subprocess.run(
        [str(JIN), *args], cwd=cwd, capture_output=True, text=True, env=env, check=False
    )


def test_check_on_examples_exits_zero() -> None:
    """machine 条件「examples 2 本が jin check で error 0 件（exit 0）」。"""
    result = _run("check", "examples")
    assert result.returncode == 0, result.stdout + result.stderr


def test_check_json_on_examples_is_empty() -> None:
    result = _run("check", "--json", "examples")
    assert result.returncode == 0
    assert json.loads(result.stdout) == []


def test_schema_stdout_is_byte_identical_to_committed_file() -> None:
    """machine 条件「jin schema の標準出力が schemas/jin.schema.json とバイト一致」。

    プロセスを分けて実測する（同一プロセス内の比較では、同じオブジェクトを 2 回見ているだけになりうる）。
    """
    result = _run("schema")
    assert result.returncode == 0
    committed = (REPO_ROOT / "schemas" / "jin.schema.json").read_text(encoding="utf-8")
    assert result.stdout == committed


def test_dump_is_stable_across_processes_with_different_hash_seeds() -> None:
    """machine 条件「jin dump の JSON スナップショットが安定」。

    同一プロセス内 2 回の一致は辞書順序依存を検出できないので、
    `PYTHONHASHSEED` を変えた別プロセス 2 回で比べる。
    """
    for target in ["examples/researcher/researcher.jin", "examples/pipeline/pipeline.jin"]:
        first = _run("dump", target, env_extra={"PYTHONHASHSEED": "0"})
        second = _run("dump", target, env_extra={"PYTHONHASHSEED": "12345"})
        assert first.returncode == 0 and second.returncode == 0
        assert first.stdout == second.stdout, target


def test_fmt_check_on_examples_exits_zero() -> None:
    assert _run("fmt", "--check", "examples").returncode == 0


def test_fmt_check_on_every_formattable_fixture_exits_zero(formattable_paths: list[Path]) -> None:
    """F-W-P2-004 / 103: fixture（`tests/fixtures/errors` の整形可能分・`build-errors`）もディスク上で正準形。

    round-trip 契約（`test_canonical_contract.py`）は `dumps` の冪等性しか見ず、ファイルのバイト列を
    読まない。ディスク上の正準形を守るのは `jin fmt --check` だけなので、examples と同じく fixture にも掛ける。
    ディレクトリ単位だと JIN001 / JIN002（モデルにならない）で拒まれるので、ファイルごとに渡す。
    """
    fixtures = [p for p in formattable_paths if "fixtures" in p.parts]
    assert fixtures, "fixture が 1 つも選ばれていない"
    result = _run("fmt", "--check", *[str(p) for p in fixtures])
    assert result.returncode == 0, result.stdout + result.stderr


def test_fmt_refuses_unformattable_fixtures_without_touching_them(tmp_path: Path) -> None:
    """モデルにならない fixture（JIN001 / JIN002）で fmt が **書き換えずに** 落ちること。

    冪等性の machine 条件はこの 2 つに対しては定義できない（fmt(x) が存在しない）。
    黙って飛ばすのではなく「拒否してファイルを触らない」を明示的な契約として固定する。
    """
    source_dir = REPO_ROOT / "tests" / "fixtures" / "errors"
    targets = [
        p for p in sorted(source_dir.glob("*.jin")) if fixture_code(p) in UNFORMATTABLE_CODES
    ]
    assert {fixture_code(p) for p in targets} == set(UNFORMATTABLE_CODES)

    for source in targets:
        target = tmp_path / source.name
        shutil.copy(source, target)
        before = target.read_bytes()
        result = subprocess.run(
            [str(JIN), "fmt", str(target)], capture_output=True, text=True, check=False
        )
        assert result.returncode == 1, source.name
        assert target.read_bytes() == before, f"{source.name} を書き換えてしまった"


def test_check_exit_code_is_one_only_for_errors() -> None:
    fixtures = REPO_ROOT / "tests" / "fixtures" / "errors"
    assert _run("check", str(fixtures / "JIN060_root_not_found.jin")).returncode == 1
    assert _run("check", str(fixtures / "JIN070_await_not_in_tools.jin")).returncode == 0


# --------------------------------------------------------------------------------------
# S19: `--resolve` の危険性がドキュメントに書かれている
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["README.md", "CLAUDE.md"])
def test_resolve_danger_is_documented(name: str) -> None:
    """S19: `--resolve` が任意コードを実行することがどこにも書かれていなかった。

    CLI ヘルプの 1 行だけでは、使う前に読む場所に届かない。
    """
    text = (REPO_ROOT / name).read_text(encoding="utf-8")
    assert "--resolve" in text, f"{name} に --resolve の記述が無い"
    section = text.split("--resolve", 1)[1]
    assert "任意のコード" in section or "任意コード" in section, (
        f"{name} に「任意のコードが走る」ことが書かれていない"
    )


def test_resolve_help_warns_in_the_cli() -> None:
    """S19: `jin check --help` にも警告を出す。"""
    from jin_cli.main import app
    from typer.testing import CliRunner

    output = CliRunner().invoke(app, ["check", "--help"]).output
    assert "危険" in output


# --------------------------------------------------------------------------------------
# Phase 2: build / run（プロセス境界をまたいで初めて意味を持つ条件）
# --------------------------------------------------------------------------------------
def test_build_output_is_byte_identical_across_processes_with_different_hash_seeds(
    tmp_path: Path,
) -> None:
    """machine 条件 1 の別プロセス版: 生成 agent.py が辞書順序・ハッシュシードに依存しない。"""
    outputs: list[bytes] = []
    for seed, sub in (("0", "a"), ("12345", "b")):
        out = tmp_path / sub
        result = _run(
            "build",
            "examples/pipeline/pipeline.jin",
            "--out",
            str(out),
            env_extra={"PYTHONHASHSEED": seed},
        )
        assert result.returncode == 0, result.stdout + result.stderr
        outputs.append((out / "Pipeline" / "agent.py").read_bytes())
    assert outputs[0] == outputs[1]


@pytest.mark.parametrize("name", ["researcher", "pipeline"])
def test_run_with_fake_model_exits_zero_in_a_real_process(tmp_path: Path, name: str) -> None:
    """machine 条件 5: `jin run --model fake` が examples 2 本で最後まで通り exit 0。

    console script は cwd を `sys.path` に含めないので、`research.*` のスタブは
    `PYTHONPATH` で渡す（利用者は cwd か PYTHONPATH に本物の `research` を置く）。
    """
    trace = tmp_path / "trace.jsonl"
    result = _run(
        "run",
        f"examples/{name}/{name}.jin",
        "こんにちは",
        "--model",
        "fake",
        "--trace",
        str(trace),
        env_extra={"PYTHONPATH": str(REPO_ROOT / "tests" / "fixtures" / "stubs")},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    lines = trace.read_text(encoding="utf-8").splitlines()
    assert lines and all(json.loads(line)["pointer"] is not None for line in lines)
    assert "Traceback" not in result.stderr


_SCRIPTED_RUN = """
import sys
import jin_cli.main
from jin_adk.fake_llm import FakeLlm, FakeToolCall
jin_cli.main.FakeLlm = lambda: FakeLlm(responses=[FakeToolCall(name=sys.argv[2], args={"x": "1", "query": "q"}), "done"])
jin_cli.main.app(["run", sys.argv[1], "go", "--model", "fake"])
"""


def _scripted_run(jin: Path, tool: str) -> subprocess.CompletedProcess[str]:
    """`jin run --model fake` にはツールを呼ばせる台本を渡す手段が無いので、`jin_cli.main.FakeLlm` を
    差し替えて `app()` を呼ぶ小スクリプトを**別プロセス**で実行する（CliRunner 在中ではない）。"""
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "tests" / "fixtures" / "stubs")}
    return subprocess.run(
        [sys.executable, "-P", "-c", _SCRIPTED_RUN, str(jin), tool],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _one_tool_jin(tmp_path: Path, ref: str) -> Path:
    jin = tmp_path / "one_tool.jin"
    jin.write_text(
        json.dumps(
            {
                "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
                "version": 1,
                "root": "R",
                "circles": [
                    {"name": "R", "core": "m", "tools": [{"name": "t", "kind": "tool", "ref": ref}]}
                ],
            }
        ),
        encoding="utf-8",
    )
    return jin


@pytest.mark.parametrize(
    ("ref", "tool", "expected"),
    [
        ("exits_tool:boom", "boom", "SystemExit"),  # F-S-P2-102
        ("cancel_tool:fn", "fn", "応答を返さず"),  # F-S-P2-201
    ],
)
def test_tool_failures_are_exit_1_without_a_traceback_in_a_real_process(
    tmp_path: Path, ref: str, tool: str, expected: str
) -> None:
    """F-W-P2-204: ツール実行中の `sys.exit(0)` / `asyncio.CancelledError` を**実プロセス**で固定する。
    CliRunner 在中では pytest の logging プラグインが asyncio ロガーを吸うので、shutdown ログ（トレースバック）が
    stderr に出ないことは実プロセスでしか見えない。"""
    result = _scripted_run(_one_tool_jin(tmp_path, ref), tool)
    assert result.returncode == 1, result.stdout + result.stderr
    assert expected in result.stderr
    assert "Traceback" not in result.stderr and "asyncio.exceptions" not in result.stderr
    assert "イベント（session" not in result.stderr


def test_cwd_cannot_shadow_an_installed_package_in_a_real_process(tmp_path: Path) -> None:
    """security review F-S-P2-003 の再現入力（DP-IMPL-JIN-P2-SYSPATH-01）。

    `ref` を持たない `pipeline.jin` を、`authlib/`（**インストール済み**で、ADK が実行中に遅延 import する
    名前）を置いた cwd で `jin run` する。`insert(0, cwd)` なら cwd 側の `__init__.py` が走って exit 1
    になる（reviewer の実測）。末尾（append）でも import 窓方式でも site-packages の本物が先に解決され
    exit 0。**この検査はインストール済みの名前しか見ない**ので、「Runner 実行中に cwd を残す」変異には
    反応しない。それは下の `anthropic` 版（未インストール名）が担う。
    同一プロセスのテストでは ADK の遅延 import が既に済んでいて再現しないので、**別プロセス**で見る。
    """
    shadow = tmp_path / "authlib"
    shadow.mkdir()
    (shadow / "__init__.py").write_text(
        "raise RuntimeError('SHADOW authlib FROM CWD LOADED')\n", encoding="utf-8"
    )
    result = _run(
        "run",
        str(REPO_ROOT / "examples" / "pipeline" / "pipeline.jin"),
        "go",
        "--model",
        "fake",
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SHADOW" not in result.stdout + result.stderr


def test_cwd_cannot_supply_an_uninstalled_optional_dependency_during_the_run(
    tmp_path: Path,
) -> None:
    """F-S-P2-101: Runner 実行中に cwd が `sys.path` に無いことを**実プロセス**で固定する。

    google-adk 2.8.0 は LLM 要求のたびに `anthropic` を import しようとする
    （`google/adk/models/contents.py` → `anthropic_llm.py`・`ImportError` は握りつぶす）。
    `anthropic` は jin の依存に無い（**未インストール名**）ので、Runner 実行中に cwd が `sys.path` に
    あれば末尾でも cwd の `anthropic/__init__.py` が実行される（append 実装では exit 1 になった・
    reviewer の実測）。import 窓方式なら Runner 実行中は cwd が無いので exit 0。

    **この検査は 2 つの事実に依存する**（F-W-P2-102）: (1) `anthropic` が未インストールであること
    （冒頭の assert・lock が保証）、(2) ADK が実行中に `anthropic` を遅延 import すること（ADK を上げたら再確認）。
    (2) が崩れると、この検査は変異に反応しなくなる（緑のまま）。
    """
    # 前提は uv.lock が保証する（anthropic は依存に無い）。崩れたら skip で黙らず失敗させる（F-W-P2-201）
    assert importlib.util.find_spec("anthropic") is None, (
        "anthropic がインストールされている（lock に入った）。この検査は「未インストール名」が前提なので、"
        "別の未インストール名（ADK が実行中に遅延 import するもの）に差し替えること"
    )
    shadow = tmp_path / "anthropic"
    shadow.mkdir()
    (shadow / "__init__.py").write_text(
        "raise RuntimeError('SHADOW anthropic FROM CWD LOADED')\n", encoding="utf-8"
    )
    result = _run(
        "run",
        str(REPO_ROOT / "examples" / "pipeline" / "pipeline.jin"),
        "go",
        "--model",
        "fake",
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SHADOW" not in result.stdout + result.stderr
