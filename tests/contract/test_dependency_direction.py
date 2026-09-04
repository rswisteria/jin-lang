"""パッケージ横断契約: 依存の一方向性（ADR-004 / DP-COMMON-11 / FR-ARCH-002 / NFR-DEP-001）。

契約の正本は design.yaml `architecture.dependency_direction.rules` の 8 行。
検査ツール（import-linter）を差し替えても契約は動かさない。

DP-COMMON-11 の constraints:
「CI は jin-core → google-adk と apps/editor → Python パッケージの 2 本を必ず落とすこと」

本ラウンドで実在するのは Python 側（jin_core / jin_cli）だけなので、ここで担保するのは 1 本目である。
2 本目（apps/editor → Python パッケージ）は apps/editor が存在する Phase 5 で pnpm 側に足す。
その未対応を隠さないよう、下の `test_editor_contract_is_not_yet_enforced` が「まだ無い」ことを明示的に固定する。
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_SRC = REPO_ROOT / "packages" / "jin-core" / "src" / "jin_core"


#: `importlinter.cli` は `python -m` の入口を持たない（実測: 何も出さず exit 0）。
#: 必ず venv の console script を叩く。
LINT_IMPORTS = Path(sys.executable).parent / "lint-imports"


def real_importlinter_section() -> dict:
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return config["tool"]["importlinter"]


def setup_cfg_from(section: dict) -> str:
    """`[tool.importlinter]` を setup.cfg 形式へ**機械的に**写す。

    契約を手書きで複製すると、実契約が typo で常に KEPT になっても注入テストは
    緑のままになる（wiring review W-02 / 偽 green の温床）。実物から生成することで、
    契約を壊したときに「実契約が通る」と「注入が落ちない」の両方が同時に赤くなる。

    setup.cfg 形式では複数値フィールドを改行区切りで書く。1 行に書くと
    import-linter が 1 文字ずつに割る（実測: "Could not find package 'j'"）。
    """
    lines = ["[importlinter]", "root_packages ="]
    lines += [f"    {name}" for name in section["root_packages"]]
    lines.append(f"include_external_packages = {section['include_external_packages']}")
    for i, contract in enumerate(section["contracts"], start=1):
        lines += ["", f"[importlinter:contract:{i}]"]
        for key, value in contract.items():
            if isinstance(value, list):
                lines.append(f"{key} =")
                lines += [f"    {item}" for item in value]
            else:
                lines.append(f"{key} = {value}")
    return "\n".join(lines) + "\n"


def copy_sources(destination: Path) -> None:
    """実物のパッケージソースを一時ツリーへ複製する（実物は触らない）。"""
    for package in sorted((REPO_ROOT / "packages").iterdir()):
        module = package.name.replace("-", "_")
        shutil.copytree(package / "src" / module, destination / module)


def _run_lint_imports(cwd: Path, config: Path | None = None, extra_path: Path | None = None):
    assert LINT_IMPORTS.exists(), f"lint-imports が見つからない: {LINT_IMPORTS}"
    command = [str(LINT_IMPORTS)]
    if config is not None:
        command += ["--config", str(config)]
    env = None
    if extra_path is not None:
        import os

        env = {**os.environ, "PYTHONPATH": str(extra_path)}
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, env=env, check=False)


def test_import_linter_contracts_are_declared() -> None:
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    section = config["tool"]["importlinter"]
    assert section["include_external_packages"] is True
    names = [c["name"] for c in section["contracts"]]
    assert any("一方向" in n for n in names)
    assert any("google-adk" in n for n in names)
    # security review S1: resolver の実装を jin_cli に閉じる契約（コメントでの約束は不可）。
    assert any("jin_cli に閉じる" in n for n in names)


def test_import_linter_passes_on_the_real_tree() -> None:
    result = _run_lint_imports(REPO_ROOT)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    ("target_file", "injected", "contract_keyword"),
    [
        ("canonical.py", "import google.adk", "google-adk"),
        ("canonical.py", "from jin_cli.resolver import ImportResolver", "jin_cli に閉じる"),
    ],
)
def test_import_linter_actually_bites_on_a_forbidden_import(
    tmp_path: Path, target_file: str, injected: str, contract_keyword: str
) -> None:
    """契約が「宣言してあるだけ」でないことを、違反を注入して確認する。

    設定は**実物の `[tool.importlinter]` から生成**する（W-02）。
    2 本目の注入は security review S1 の contract（resolver の実装は jin_cli に閉じる）が
    実際に落ちることを確かめる。実物のツリーは触らない。
    """
    section = real_importlinter_section()
    assert any(contract_keyword in c["name"] for c in section["contracts"]), (
        f"実物の契約に {contract_keyword!r} が見つからない。契約を消したか名前を変えた"
    )

    copy_sources(tmp_path)
    target = tmp_path / "jin_core" / target_file
    target.write_text(
        f"{injected}  # 契約違反の注入\n" + target.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    config = tmp_path / "setup.cfg"
    config.write_text(setup_cfg_from(section), encoding="utf-8")

    result = _run_lint_imports(tmp_path, config=config, extra_path=tmp_path)
    assert result.returncode != 0, (
        "違反を注入したのに import-linter が通ってしまった。契約が効いていない\n"
        + result.stdout
        + result.stderr
    )
    # **どの契約が落ちたか**まで見る。別の契約が代わりに落ちているだけだと、
    # 対象の契約が typo で無効になっていても赤くならない（偽 green）。
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
    broken = [
        line.rsplit(" ", 1)[0].strip()
        for line in plain.splitlines()
        if line.strip().endswith("BROKEN")
    ]
    assert any(contract_keyword in name for name in broken), (
        f"{contract_keyword!r} の契約が BROKEN になっていない。BROKEN: {broken}\n" + plain
    )


def test_injected_config_is_generated_from_the_real_contracts(tmp_path: Path) -> None:
    """W-02: 注入テストが使う設定が実物由来であることを固定する。

    実物と同じ設定で、違反を注入していないツリーは KEPT になるはず。
    ここが落ちたら生成器が実契約を写せていない。
    """
    section = real_importlinter_section()
    copy_sources(tmp_path)
    config = tmp_path / "setup.cfg"
    config.write_text(setup_cfg_from(section), encoding="utf-8")
    result = _run_lint_imports(tmp_path, config=config, extra_path=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"{len(section['contracts'])} kept" in result.stdout


def test_jin_core_source_does_not_mention_adk() -> None:
    """import-linter とは独立した二重の網（ツール差し替えに耐える生の検査）。"""
    for path in sorted(CORE_SRC.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                assert "google" not in stripped, f"{path}: {stripped}"


def test_jin_core_does_not_import_jin_cli() -> None:
    for path in sorted(CORE_SRC.rglob("*.py")):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                assert "jin_cli" not in stripped, f"{path}: {stripped}"


@pytest.mark.parametrize("later_package", ["jin_adk", "jin_render", "jin_lsp"])
def test_later_packages_do_not_exist_yet(later_package: str) -> None:
    """本ラウンドのスコープは Phase 0 / 1。後続 Phase のパッケージはまだ無い。

    存在するようになったらこのテストが赤くなる。そのとき直すのは**この 1 行ではなく**
    `CLAUDE.md` の「パッケージを足すときのチェックリスト」の 6 項目である
    （conventions review A-3）:

    1. `[project].dependencies` / 2. `[tool.uv.sources]` / 3. `root_packages` /
    4. layers 契約（兄弟は `"jin_adk | jin_render"` と `|` 区切り）/
    5. forbidden 契約の `source_modules` / 6. `packages/<name>/tests/__init__.py`

    6 を落とすと**同名テストファイル 1 個で collection 全体が止まり**、
    「トリップワイヤが赤い」ではなく「テストが 1 件も走らない」状態から始めることになる。
    抜けは `tests/contract/test_packaging_contract.py` が名指しで落とす。
    """
    assert not (REPO_ROOT / "packages" / later_package.replace("_", "-")).exists()


def test_editor_contract_is_not_yet_enforced() -> None:
    """DP-COMMON-11 の 2 本目（apps/editor → Python パッケージ）は未対応であることを明示する。

    apps/editor がまだ無いので検査対象が存在しない。Phase 5 で apps/editor を作るときに
    pnpm 側の静的検査を足し、このテストを置き換えること。
    """
    assert not (REPO_ROOT / "apps" / "editor").exists(), (
        "apps/editor ができた。DP-COMMON-11 の constraints に従い "
        "pnpm 側の静的検査（Python パッケージを import しない）を足してからこのテストを差し替えること"
    )
