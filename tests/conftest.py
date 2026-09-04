"""リポジトリ直下の tests/ で共有する fixture。

ADR-003（DP-COMMON-09）の constraints「横断契約テストの置き場は tests/contract/ とする。
パッケージ横断 fixture の共有方法は実装 Stage で決め、根拠を残す」への回答:

**リポジトリ直下の `tests/conftest.py` に置き、pytest の rootdir を 1 つに保つ。**

根拠:
- 各パッケージのテスト（`packages/*/tests/`）は自分のパッケージだけを見るので共有 fixture を必要としない。
  共有が要るのは `tests/spec/`（要件書との突合）と `tests/contract/`（パッケージ横断契約）だけで、
  どちらもリポジトリ直下の `tests/` の下にある
- pytest プラグインを 1 つ作って配布するより、conftest.py 1 本のほうが依存が増えず追跡しやすい
- `pyproject.toml` の `testpaths` に 3 つのディレクトリを並べ、`uv run pytest` 1 発で全部通す
  （FR-TEST-001「全て uv run pytest で通ること」）
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: モデルにならない（= fmt できない）診断コード。docs/spec/diagnostics.md §6。
UNFORMATTABLE_CODES = frozenset({"JIN001", "JIN002"})


def fixture_code(path: Path) -> str:
    return path.name.split("_", 1)[0]


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


def discover_jin_files(root: Path) -> list[Path]:
    """ディレクトリ配下の `.jin` を**深さを問わず**集める。

    CLI（`jin_cli.main._collect`）と同じ規則にそろえるための 1 箇所。
    `glob("*/*.jin")` は深さちょうど 2 しか拾わないので、`examples/a/b/x.jin` を
    置いた瞬間に静かに検査対象から漏れる（wiring review W-08）。
    """
    return sorted(root.rglob("*.jin"))


@pytest.fixture(scope="session")
def example_paths() -> list[Path]:
    return discover_jin_files(REPO_ROOT / "examples")


@pytest.fixture(scope="session")
def error_fixture_paths() -> list[Path]:
    return sorted((REPO_ROOT / "tests" / "fixtures" / "errors").glob("*.jin"))


@pytest.fixture(scope="session")
def formattable_paths(example_paths: list[Path], error_fixture_paths: list[Path]) -> list[Path]:
    """examples + モデルになる fixture（= JIN001 / JIN002 以外）。"""
    return example_paths + [
        p for p in error_fixture_paths if fixture_code(p) not in UNFORMATTABLE_CODES
    ]
