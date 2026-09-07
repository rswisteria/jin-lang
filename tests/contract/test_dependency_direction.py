"""パッケージ横断契約: 依存の一方向性（ADR-004 / DP-COMMON-11 / FR-ARCH-002 / NFR-DEP-001）。

契約の正本は design.yaml `architecture.dependency_direction.rules` の 8 行。
検査ツール（import-linter）を差し替えても契約は動かさない。

DP-COMMON-11 の constraints:
「CI は jin-core → google-adk と apps/editor → Python パッケージの 2 本を必ず落とすこと」

1 本目（`jin_core` → `google-adk`）は import-linter が落とす。
**2 本目（`apps/editor` → Python パッケージ）は Phase 5 で pnpm 側（eslint の
`no-restricted-imports`）に足した。** Python のツールでは TS を検査できないので道具が違う。
下の `test_the_editor_contract_is_enforced_on_the_pnpm_side` がその仕掛けの所在を、
`apps/editor/test/dependencyDirection.test.ts` が**規則が実際に落ちること**を見る。
"""

from __future__ import annotations

import ast
import json
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
    # security review S1: 任意コード実行の実装（jin_cli.resolver / jin_adk.runtime）を閉じる契約（コメントでの約束は不可）。
    assert any("jin_cli.resolver" in n and "jin_adk.runtime" in n for n in names)


def test_import_linter_passes_on_the_real_tree() -> None:
    result = _run_lint_imports(REPO_ROOT)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    ("package", "target_file", "injected", "contract_keyword"),
    [
        ("jin_core", "canonical.py", "import google.adk", "google-adk"),
        (
            "jin_core",
            "canonical.py",
            "from jin_cli.resolver import ImportResolver",
            "jin_cli.resolver",
        ),
        ("jin_core", "canonical.py", "from jin_adk.runtime import run_model", "jin_adk.runtime"),
        # F-W-P3-002: Phase 3 で足した `jin_render` からの経路も実測する。
        # `jin_core` だけを注入点にしていると、契約の `source_modules` から
        # `jin_render` が抜けても全部緑のままになる
        ("jin_render", "svg.py", "import google.adk", "google-adk"),
        ("jin_render", "svg.py", "import jin_adk", "一方向"),
        (
            "jin_render",
            "svg.py",
            "from jin_cli.resolver import ImportResolver",
            "jin_cli.resolver",
        ),
        # 兄弟の逆向き（`jin_adk` → `jin_render`）も layers 契約が落とす
        ("jin_adk", "trace.py", "import jin_render", "一方向"),
    ],
)
def test_import_linter_actually_bites_on_a_forbidden_import(
    tmp_path: Path, package: str, target_file: str, injected: str, contract_keyword: str
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
    target = tmp_path / package / target_file
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


def test_jin_core_imports_no_other_jin_package() -> None:
    """design.yaml rule 1「jin-core は他の jin-* に依存しない」の生の網（import-linter を差し替えても残る）。

    wiring review F-W-P2-003: `jin_cli` だけを見ていたので `import jin_adk` を注入しても素通りした。
    ワイルドカードそのもの（`jin_*` のうち `jin_core` 以外）を見る。
    """
    for path in sorted(CORE_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for name in names:
                top = name.split(".", 1)[0]
                assert not (top.startswith("jin_") and top != "jin_core"), f"{path}: {name}"


#: design.yaml `architecture.dependency_direction.rules` が名指しする Python パッケージの全集合。
#: **Phase 4（`jin_lsp`）で最後の 1 つが埋まった。** v1 のスコープではこれ以上増えない
#: （要件書 §1.2 のリポジトリ構成。`apps/editor` は Python パッケージではない）。
PLANNED_PACKAGES = ("jin_core", "jin_adk", "jin_render", "jin_lsp", "jin_cli")


@pytest.mark.parametrize("planned_package", PLANNED_PACKAGES)
def test_every_planned_package_exists(planned_package: str) -> None:
    """design.yaml が名指しする 5 パッケージが全て実在する（Phase 4 で最後の 1 つが埋まった）。

    Phase 3 まではこれが `test_later_packages_do_not_exist_yet`（未実装パッケージが**無い**ことを
    固定するトリップワイヤ）だった。`jin_adk` は Phase 2、`jin_render` は Phase 3、
    `jin_lsp` は Phase 4 で追加され、parametrize から順に外れて空になったため、
    **同じ 5 つの名前を「全部ある」側から固定する形に反転させた**（削除ではない。
    この docstring が持つチェックリストの所在ごと消える）。

    パッケージを足すときに直すのは**この 1 行ではなく** `CLAUDE.md` の
    「パッケージを足すときのチェックリスト」の 8 項目である
    （conventions review A-3・Phase 3 修正ラウンド 3 で 8 項目に）:

    1. `[project].dependencies` / 2. `[tool.uv.sources]` / 3. `root_packages` /
    4. layers 契約（**兄弟だけ**が `"jin_adk | jin_render"` と `|` 区切り。`jin_lsp` は
       `jin_cli` と `jin_adk | jin_render` の間の単独レイヤ）/
    5. forbidden 契約の `source_modules` / 6. `packages/<name>/tests/__init__.py` /
    7. 依存する側の `packages/<x>/pyproject.toml`（Phase 2 修正ラウンド 1・F-W-P2-001）/
    8. `test_guard_claims.py` の期待集合（Phase 3 修正ラウンド 1・F-V-P3-006）

    6 を落とすと**同名テストファイル 1 個で collection 全体が止まり**、
    「トリップワイヤが赤い」ではなく「テストが 1 件も走らない」状態から始めることになる。
    1〜7 の抜けは `tests/contract/test_packaging_contract.py` が名指しで落とす。
    8 は `test_guard_claims.py` がパッケージ名の等号で自己検出する。
    """
    assert (REPO_ROOT / "packages" / planned_package.replace("_", "-")).is_dir()


def test_the_planned_package_set_matches_the_workspace() -> None:
    """`PLANNED_PACKAGES` が `packages/` の実体と**過不足なく**一致する。

    上のテストは「列挙した名前が実在する」しか見ないので、`PLANNED_PACKAGES` から名前を
    1 つ削れば黙って緑になる（`packages/jin-lsp/` を作ったのに列挙を忘れる、が通ってしまう）。
    等号で固定して、**列挙側が縮んだこと自体**を検出する。
    """
    on_disk = {
        path.name.replace("-", "_")
        for path in (REPO_ROOT / "packages").iterdir()
        if path.is_dir() and (path / "pyproject.toml").is_file()
    }
    assert on_disk == set(PLANNED_PACKAGES)


EDITOR = REPO_ROOT / "apps" / "editor"


def test_the_editor_contract_is_enforced_on_the_pnpm_side() -> None:
    """DP-COMMON-11 の 2 本目（`apps/editor` → Python パッケージ）を pnpm 側が落とす。

    Phase 4 まではこれが `test_editor_contract_is_not_yet_enforced`（`apps/editor` が
    **無い**ことを固定するトリップワイヤ）だった。Phase 5 で `apps/editor` を作ったので
    赤くなったが、**テストを差し替えるだけで済ませない**（Issue #9 / `DP-REVIEW-JIN-003`）。
    先に pnpm 側の静的検査（eslint の `no-restricted-imports`）を足し、
    その検査が**実際に落ちる**ことを `apps/editor/test/dependencyDirection.test.ts` が
    禁止 import を食わせて確かめている。ここではその仕掛けが所定の位置にあることを見る。

    Python 側（import-linter）と TS 側（eslint）で道具が違うので、
    契約が 2 本とも生きていることは**両方のテスト**で担保する。
    """
    config = (EDITOR / "eslint.config.js").read_text(encoding="utf-8")
    assert "no-restricted-imports" in config, "禁止 import の規則が無い"
    assert "**/packages/**" in config, "packages 配下の import が禁止されていない"
    assert "jin_core" in config and "jin_lsp" in config, "Python パッケージ名が禁止されていない"

    probe = (EDITOR / "test" / "dependencyDirection.test.ts").read_text(encoding="utf-8")
    assert "eslint.lintText" in probe or "lintText" in probe, (
        "規則が**落ちる**ことを確かめる注入テストが無い"
        "（規則が存在することと、規則が落ちることは別 — Phase 0+1 の偽 green）"
    )

    package_json = json.loads((EDITOR / "package.json").read_text(encoding="utf-8"))
    assert "lint" in package_json["scripts"], "pnpm lint が無い"
    assert "test" in package_json["scripts"], "pnpm test が無い"


def test_the_editor_does_not_import_python_packages_in_its_sources() -> None:
    """念のための二層目: `apps/editor/src` の import 文を直接読む。

    eslint が設定ごと外されたときに気づくための独立な網である
    （検査ツールを差し替えても契約は動かない・本モジュールの冒頭）。
    `schemas/jin.schema.json` だけは例外で、これは Python パッケージではなく
    Pydantic から生成してコミットされた成果物である（要件書 §7.1）。
    """
    forbidden = re.compile(
        r"""from\s+['"]([^'"]*(?:packages/|jin_core|jin_adk|jin_render|jin_lsp|jin_cli)[^'"]*)['"]"""
    )
    offenders: list[str] = []
    for path in sorted((EDITOR / "src").rglob("*.ts*")):
        for match in forbidden.finditer(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.relative_to(REPO_ROOT)}: {match.group(1)}")
    assert offenders == [], offenders
