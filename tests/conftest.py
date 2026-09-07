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

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: 書き込み権限で「消せない / 書けない」状態を作るテストは root では空虚になる（root は権限を無視する）。
#: `geteuid` の無い OS（Windows）も同じ理由で skip。1 か所に置く（F-W-P2-202 / F-V-P2-205: 2 定義が逆に振る舞っていた）。
requires_non_root = pytest.mark.skipif(
    not hasattr(os, "geteuid") or os.geteuid() == 0,
    reason="root（または geteuid の無い OS）ではパーミッションによる拒否を再現できない",
)

#: モデルにならない（= fmt できない）診断コード。docs/spec/diagnostics.md §6。
UNFORMATTABLE_CODES = frozenset({"JIN001", "JIN002"})

#: examples の `ref`（`research.*`）と異常系ツールのスタブ置き場。
STUBS = REPO_ROOT / "tests" / "fixtures" / "stubs"


def delivery_run(slug: str = "jin", root: Path | None = None) -> Path:
    """`delivery/` から**辞書順で最新**のランディレクトリを返す（DP-REVIEW-JIN-005）。

    ランディレクトリは `<YYYYMMDD-HHmm>-<slug>` という名前で、次のランが走ると
    別のタイムスタンプで切られる。契約テストがこれを直書きしていると、
    **次のランでテストが壊れる**（Issue #9 / DP-REVIEW-JIN-005・2026-09-07 toyota 確定）。
    Issue の指定は「パスをハードコードし直すのではなく、ランディレクトリを解決する形に変える」。

    名前が `YYYYMMDD-HHmm` で始まるので**辞書順 = 時系列順**であり、日付を解釈する必要はない
    （解釈するとタイムゾーンや桁揃えの話が入り込む）。タイムスタンプの無い
    旧形式（`delivery/<slug>/`）は後方互換として、タイムスタンプ付きが 1 つも無いときだけ使う
    （`record.py --slug` の解決規則と同じ扱い）。

    見つからなければ `FileNotFoundError`。**黙って別の場所を指さない**（NFR-FAIL-001）。

    `root` は探索の起点（既定は `delivery/`）。テストが新しいランを置いて
    解決先が切り替わることを確かめるために外から差せるようにしてある。
    """
    root = root if root is not None else REPO_ROOT / "delivery"
    runs = sorted(
        (p for p in root.glob(f"*-{slug}") if p.is_dir() and p.name != slug),
        key=lambda p: p.name,
    )
    if runs:
        return runs[-1]
    flat = root / slug
    if flat.is_dir():
        return flat
    raise FileNotFoundError(f"delivery/ に *-{slug} のランディレクトリがありません: {root}")


#: 現在のラン（`delivery/<最新>-jin/`）。契約テストはこれを起点にする。
DELIVERY_RUN = delivery_run()


def child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """子プロセス用の環境。`extra["PYTHONPATH"]` は既存の値を**捨てずに前置**する。

    開発者の `PYTHONPATH` を上書きしないための唯一の実装（F-W-P2-007 / F-W-P3-004）。
    前置の有無が `test_cli_contract` / `test_render_contract` / `mutate_p3.py` の
    3 箇所で食い違っていたので 1 箇所に寄せた。
    """
    extra = extra or {}
    env = {**os.environ, **extra}
    inherited = os.environ.get("PYTHONPATH")
    if extra.get("PYTHONPATH") and inherited:
        env["PYTHONPATH"] = os.pathsep.join([extra["PYTHONPATH"], inherited])
    return env


def env_with_stubs(extra: dict[str, str] | None = None) -> dict[str, str]:
    """`tests/fixtures/stubs` を `PYTHONPATH` の先頭に置いた子プロセス環境。"""
    return child_env({**(extra or {}), "PYTHONPATH": str(STUBS)})


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
def build_error_fixture_paths() -> list[Path]:
    """`jin check` は通るが `jin build` が落とす構造（Phase 2・全部モデルになる）。"""
    return sorted((REPO_ROOT / "tests" / "fixtures" / "build-errors").glob("*.jin"))


@pytest.fixture(scope="session")
def formattable_paths(
    example_paths: list[Path],
    error_fixture_paths: list[Path],
    build_error_fixture_paths: list[Path],
) -> list[Path]:
    """examples + モデルになる fixture（= JIN001 / JIN002 以外）+ build-errors（wiring review F-W-P2-004）。"""
    return (
        example_paths
        + [p for p in error_fixture_paths if fixture_code(p) not in UNFORMATTABLE_CODES]
        + build_error_fixture_paths
    )
