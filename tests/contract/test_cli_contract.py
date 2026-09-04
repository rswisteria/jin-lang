"""パッケージ横断契約: CLI の出力が jin-core の関数と同じものを返すこと。

design.yaml implementation_phases.items[1].verification.machine のうち、
プロセス境界をまたいで初めて意味を持つ条件をここで検証する。
"""

from __future__ import annotations

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


def _run(*args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    assert JIN.exists(), f"jin コマンドが見つからない: {JIN}"
    env = {**os.environ, **(env_extra or {})}
    return subprocess.run(
        [str(JIN), *args], cwd=REPO_ROOT, capture_output=True, text=True, env=env, check=False
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
