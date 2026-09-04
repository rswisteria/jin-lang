"""生成プロジェクトの構造（要件書 §3.1）と `.env.example`。

design.yaml Phase 2 machine 条件 3「生成プロジェクトのディレクトリ構造が §3.1 と一致する
（`<out>/<root_name>/__init__.py` と `agent.py` と `.env.example`）」。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from jin_adk.codegen import generate
from jin_adk.project import project_paths, write_project
from jin_core.model import JinFile

REPO_ROOT = Path(__file__).resolve().parents[3]
REQUIREMENTS = REPO_ROOT / "jin-requirements.md"


def test_directory_structure_matches_the_requirement(
    example_model: JinFile, tmp_path: Path
) -> None:
    """machine 3: **ちょうどこの 3 ファイル**であること。

    「足りない」だけでなく「余計なものがある」も落とす。ADR-009 の対応表を
    `<out>` へ書き出すと `adk web <out>` が読むツリーに知らないファイルが混ざる。
    """
    project = write_project(example_model, tmp_path)
    written = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    assert written == sorted(
        [
            ".env.example",
            f"{project.root_name}/__init__.py",
            f"{project.root_name}/agent.py",
        ]
    )
    assert sorted(project_paths(tmp_path, project.root_name)) == sorted(
        p for p in tmp_path.rglob("*") if p.is_file()
    )


def test_the_structure_is_the_one_written_in_the_requirement() -> None:
    """要件書 §3.1 のツリー図そのものを読んで、テストの期待と突き合わせる。

    期待値をテスト側にだけ書くと、要件書が変わってもテストは緑のまま残る。
    """
    text = REQUIREMENTS.read_text(encoding="utf-8")
    block = re.search(r"### 3\.1 出力形式.*?```\n(.*?)```", text, re.DOTALL)
    assert block is not None, "要件書 §3.1 のツリー図が見つからない"
    tree = block.group(1)
    for name in ("__init__.py", "agent.py", ".env.example"):
        assert name in tree, f"要件書 §3.1 のツリーに {name} が無い"


def test_init_py_reexports_root_agent(example_model: JinFile, tmp_path: Path) -> None:
    """要件書 §3.1 の `__init__.py  # from .agent import root_agent`。"""
    project = write_project(example_model, tmp_path)
    init = (tmp_path / project.root_name / "__init__.py").read_text(encoding="utf-8")
    assert "from .agent import root_agent" in init


def test_generated_files_use_lf_and_end_with_a_newline(
    example_model: JinFile, tmp_path: Path
) -> None:
    """CRLF に化けるとスナップショットとバイト一致しなくなる（正準形と同じ方針）。"""
    project = write_project(example_model, tmp_path)
    for path in project_paths(tmp_path, project.root_name):
        raw = path.read_bytes()
        assert b"\r" not in raw, path
        assert raw.endswith(b"\n"), path


def test_build_is_idempotent(example_model: JinFile, tmp_path: Path) -> None:
    """2 回書いても同じ内容（既存を上書きし、追記しない）。"""
    write_project(example_model, tmp_path)
    first = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    write_project(example_model, tmp_path)
    second = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert first == second


def test_generation_is_stable_across_processes_with_different_hash_seeds(
    example_path: Path,
) -> None:
    """辞書のハッシュ順に依存していないことを**別プロセス**で確かめる。

    同一プロセスで 2 回呼ぶだけでは `PYTHONHASHSEED` が同じなので差が出ない
    （`tests/contract/test_cli_contract.py` の dump と同じ手口）。
    """
    script = (
        "from pathlib import Path;"
        "from jin_core.check import check_file;"
        "from jin_adk.codegen import generate;"
        f"print(generate(check_file(Path({str(example_path)!r})).model).agent_py, end='')"
    )
    outputs = []
    for seed in ("0", "12345"):
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
            check=True,
        )
        outputs.append(result.stdout)
    assert outputs[0] == outputs[1]


# --------------------------------------------------------------------------------------
# .env.example（DP-COMMON-15）
# --------------------------------------------------------------------------------------
#: google-adk 2.8.0 の実測で決めたキー（decision-conformance.md §2.13）。
#: 根拠: `google/adk/cli/cli_create.py` が `adk create` で書き出す `.env` の 4 キーと、
#: `google/genai/_api_client.py` が実際に読む環境変数。**推測で足さない。**
EXPECTED_ENV_KEYS = (
    "GOOGLE_GENAI_USE_ENTERPRISE",
    "GOOGLE_API_KEY",
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_CLOUD_LOCATION",
)


def test_env_example_has_exactly_the_measured_keys(example_model: JinFile, tmp_path: Path) -> None:
    write_project(example_model, tmp_path)
    text = (tmp_path / ".env.example").read_text(encoding="utf-8")
    keys = [
        line.split("=", 1)[0]
        for line in text.splitlines()
        if line and not line.startswith("#") and "=" in line
    ]
    assert keys == list(EXPECTED_ENV_KEYS)


def test_env_example_has_no_values(example_model: JinFile, tmp_path: Path) -> None:
    """雛形に秘密を書かない。`GOOGLE_GENAI_USE_ENTERPRISE` だけは既定の 0 を置く。"""
    write_project(example_model, tmp_path)
    text = (tmp_path / ".env.example").read_text(encoding="utf-8")
    for line in text.splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key == "GOOGLE_GENAI_USE_ENTERPRISE":
            assert value == "0"
        else:
            assert value == "", f"{key} に値が入っている: {value!r}"


@pytest.mark.parametrize("key", EXPECTED_ENV_KEYS)
def test_every_env_key_is_actually_read_by_the_installed_adk(key: str) -> None:
    """**捏造していないこと**を実物のソースで確かめる（DP-COMMON-15 の「実測に委ねる」）。

    キー名は google-adk / google-genai のソースに現れるものだけを使う。
    ADK が名前を変えたらここが赤くなり、`.env.example` と
    `decision-conformance.md` を同時に直すことになる。
    """
    import google.adk
    import google.genai

    roots = [Path(google.adk.__file__).parent, Path(google.genai.__file__).parent]
    found = any(
        key in path.read_text(encoding="utf-8", errors="ignore")
        for root in roots
        for path in root.rglob("*.py")
    )
    assert found, f"{key} が google-adk / google-genai のソースに見つからない（捏造の疑い）"


def test_env_example_warns_about_committing_secrets(example_model: JinFile, tmp_path: Path) -> None:
    write_project(example_model, tmp_path)
    text = (tmp_path / ".env.example").read_text(encoding="utf-8")
    assert "コミットしないでください" in text


def test_env_example_is_not_affected_by_the_model(load_jin: Callable) -> None:
    """`.env.example` は `.jin` の内容に依存しない（キーは ADK 側の都合で決まる）。"""
    contents = {
        generate(load_jin(path)).env_example
        for path in sorted((REPO_ROOT / "examples").rglob("*.jin"))
    }
    assert len(contents) == 1
