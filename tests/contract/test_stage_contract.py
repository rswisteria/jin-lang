"""鑑賞ページ `apps/stage` の契約（設計書 docs/superpowers/specs/2026-09-17-jin-stage-design.md §4.2）。

`tests/contract/test_player_contract.py` と同じ型: 版の完全一致、実行時依存の限定、
読んでよいファイル、語彙の等号、CI のジョブ。
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from tests.spec.test_stage_spec_consistency import machine_table, stage_effects, stage_layers

REPO_ROOT = Path(__file__).resolve().parents[2]
STAGE = REPO_ROOT / "apps" / "stage"
EDITOR = REPO_ROOT / "apps" / "editor"
PLAYER = REPO_ROOT / "apps" / "player"
SRC = STAGE / "src"
LAYERS_TS = SRC / "layers.ts"
EFFECTS_TS = SRC / "effects.ts"

STAGE_RUNTIME_DEPENDENCIES = {"three": "0.186.0", "mediabunny": "1.57.0"}
THREE_D_PACKAGES = {"three", "mediabunny", "@types/three"}


def _package(app: Path) -> dict[str, object]:
    return json.loads((app / "package.json").read_text(encoding="utf-8"))


def test_the_stage_exists_with_the_expected_scripts() -> None:
    scripts = _package(STAGE)["scripts"]
    assert isinstance(scripts, dict)
    assert {"build", "lint", "test", "e2e", "typecheck"} <= set(scripts)


def test_the_package_manager_is_pinned_like_the_player() -> None:
    assert _package(STAGE)["packageManager"] == _package(PLAYER)["packageManager"]


def test_every_dependency_is_pinned_to_an_exact_version() -> None:
    package = _package(STAGE)
    for field in ("dependencies", "devDependencies"):
        section = package[field]
        assert isinstance(section, dict)
        loose = {name: v for name, v in section.items() if not re.fullmatch(r"\d+\.\d+\.\d+", v)}
        assert loose == {}, loose


def test_the_only_runtime_dependencies_are_three_and_mediabunny() -> None:
    assert _package(STAGE)["dependencies"] == STAGE_RUNTIME_DEPENDENCIES


def test_the_toolchain_matches_the_player() -> None:
    stage = _package(STAGE)["devDependencies"]
    player = _package(PLAYER)["devDependencies"]
    assert isinstance(stage, dict) and isinstance(player, dict)
    shared = set(stage) & set(player)
    assert shared == set(player), sorted(set(player) - shared)
    assert {name: stage[name] for name in shared} == {name: player[name] for name in shared}
    assert stage["@types/three"] == STAGE_RUNTIME_DEPENDENCIES["three"]


def test_three_d_stays_out_of_the_editor_and_the_player() -> None:
    for app in (EDITOR, PLAYER):
        package = _package(app)
        names = set(package.get("dependencies", {})) | set(package.get("devDependencies", {}))  # type: ignore[arg-type]
        assert not names & THREE_D_PACKAGES, (app.name, sorted(names & THREE_D_PACKAGES))
    for path in sorted((EDITOR / "src").rglob("*.ts*")) + sorted((PLAYER / "src").rglob("*.ts")):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r'from\s+"(three|mediabunny)', text), path


def test_the_stage_ignores_its_build_products() -> None:
    ignored = (STAGE / ".gitignore").read_text(encoding="utf-8").split()
    assert {"node_modules/", "dist/", "test-results/", "playwright-report/"} <= set(ignored)


def test_the_stage_reads_no_repository_file() -> None:
    offenders = [
        f"{path.relative_to(REPO_ROOT)}: {match.group(0)}"
        for path in sorted(SRC.rglob("*.ts"))
        for match in re.finditer(
            r'from\s+"[^"]*\.\./(schemas|packages|examples|examples-v2|tests)/',
            path.read_text(encoding="utf-8"),
        )
    ]
    assert offenders == [], offenders


def test_the_svg_fixture_is_what_the_renderer_draws_today(tmp_path: Path) -> None:
    """単体テストの `play.svg` がレンダラの出力とずれていない（ずれたら fixture を作り直す）。"""
    out = tmp_path / "play.svg"
    subprocess.run(
        [
            "uv",
            "run",
            "jin",
            "render",
            "examples-v2/paddle/paddle.jin",
            "--focus",
            "Play",
            "-o",
            str(out),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    assert out.read_bytes() == (STAGE / "test" / "fixtures" / "play.svg").read_bytes()


def test_the_kind_layers_in_the_code_are_the_table_of_stage_md() -> None:
    body = re.search(
        r"KIND_LAYERS[^=]*=\s*\{(.*?)\};", LAYERS_TS.read_text(encoding="utf-8"), re.DOTALL
    )
    assert body is not None
    code = {
        key.strip('"'): int(value)
        for key, value in re.findall(r'("?[a-z-]+"?):\s*(\d)', body.group(1))
    }
    assert code == {kind: layer for kind, (layer, _) in stage_layers().items()}


def test_the_ring_layers_in_the_code_are_the_table_of_stage_md() -> None:
    body = re.search(
        r"RING_LAYERS[^=]*=\s*\[(.*?)\n\];", LAYERS_TS.read_text(encoding="utf-8"), re.DOTALL
    )
    assert body is not None
    code = [
        (int(layer), float(radius))
        for layer, radius in re.findall(r"\[(\d),\s*([\d.]+)\]", body.group(1))
    ]
    table = [
        (int(layer), float(radius))
        for layer, radius in machine_table(REPO_ROOT / "docs/spec/v2/stage.md", "stage-ring-layers")
    ]
    assert code == table


def test_the_effects_in_the_code_are_the_table_of_stage_md() -> None:
    body = re.search(
        r"export const EFFECTS[^=]*=\s*\{(.*?)\n\};",
        EFFECTS_TS.read_text(encoding="utf-8"),
        re.DOTALL,
    )
    assert body is not None
    code = {
        kind: ("" if effect == "null" else effect.strip('"'), strength)
        for kind, effect, strength in re.findall(
            r'(\w+):\s*\{\s*effect:\s*("?\w+"?),\s*strength:\s*"(\w+)"\s*\}', body.group(1)
        )
    }
    assert code == stage_effects()


def test_the_picture_does_not_read_the_clock_or_math_random() -> None:
    """stage.md §3.4: 絵は時刻の関数。実時間を読むのはプレビューの時計（main.ts）だけ。"""
    offenders = [
        f"{path.relative_to(REPO_ROOT)}: {word}"
        for path in sorted(SRC.rglob("*.ts"))
        if path.name != "main.ts"
        for word in ("Math.random", "Date.now", "performance.now", "new Date(")
        if word in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], offenders
