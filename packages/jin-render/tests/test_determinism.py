"""決定性（NFR-DET-001 / DP-JIN-SVG-DETERMINISM-01 / ADR-010）。

design.yaml `implementation_phases.items[3].verification.machine` の 2 / 7 / 8。

machine 2（同一入力を 2 回レンダリングしてバイト一致）と machine 7（異なる `PYTHONHASHSEED` の
別プロセス 2 回でバイト一致）は**別のテスト**として両方置く。同一プロセス内の 2 回一致は
辞書順序依存を検出できず偽 green になりうる（layout.md §4）。
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
from jin_core.model import JinFile
from jin_render import render
from jin_render.ornament import ornament_dots

from .conftest import EXAMPLES, SVG_NS, contract_elements, load_model, model_from, trace_rows

#: 別プロセスで 1 本レンダリングして stdout に出す小さな走り書き。
#: `jin_cli` を使わない（jin-render のテストは jin-render だけを見る・ADR-003）。
_SCRIPT = (
    "import sys;"
    "from pathlib import Path;"
    "from jin_core.check import check_file;"
    "from jin_render import render;"
    "m = check_file(Path(sys.argv[1])).model;"
    "sys.stdout.buffer.write(render(m).encode('utf-8'))"
)


@pytest.mark.parametrize("name", ["researcher/researcher.jin", "pipeline/pipeline.jin"])
def test_two_renders_in_one_process_are_byte_identical(name: str) -> None:
    """machine 2。"""
    model = load_model(EXAMPLES / name)
    assert render(model).encode("utf-8") == render(model).encode("utf-8")


@pytest.mark.parametrize("name", ["researcher/researcher.jin", "pipeline/pipeline.jin"])
@pytest.mark.parametrize("seeds", [("0", "4242")])
def test_two_processes_with_different_hash_seeds_agree(name: str, seeds: tuple[str, str]) -> None:
    """machine 7。`PYTHONHASHSEED` を変えた**別プロセス** 2 回でバイト一致。

    同一プロセス内の 2 回一致では、辞書順序（`set` の反復・`hash()`）への依存を検出できない。
    """
    outputs = []
    for seed in seeds:
        result = subprocess.run(
            [sys.executable, "-c", _SCRIPT, str(EXAMPLES / name)],
            capture_output=True,
            env={"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": seed, "PYTHONPATH": _src_path()},
            check=False,
        )
        assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
        outputs.append(result.stdout)
    assert outputs[0] == outputs[1]
    assert outputs[0], "空の SVG では決定性の検査が空虚になる"


@pytest.mark.parametrize("seeds", [("0", "4242")])
def test_a_trace_overlay_is_also_hash_seed_independent(seeds: tuple[str, str]) -> None:
    """overlay は pointer→要素の辞書を引くので、seed 非依存を別に固定する。"""
    script = (
        "import json, sys;"
        "from pathlib import Path;"
        "from jin_core.check import check_file;"
        "from jin_render import render;"
        "m = check_file(Path(sys.argv[1])).model;"
        # JSONL の区切りは `\n` だけ（reader と同じ割り方にする・F-C-P3-105）
        'rows = [json.loads(l) for l in Path(sys.argv[2]).read_text().split("\\n") if l];'
        "sys.stdout.buffer.write(render(m, trace=rows, upto=7).encode('utf-8'))"
    )
    trace = (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "traces"
        / "pipeline-fake.jsonl"
    )
    outputs = []
    for seed in seeds:
        result = subprocess.run(
            [sys.executable, "-c", script, str(EXAMPLES / "pipeline" / "pipeline.jin"), str(trace)],
            capture_output=True,
            env={"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": seed, "PYTHONPATH": _src_path()},
            check=False,
        )
        assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
        outputs.append(result.stdout)
    assert outputs[0] == outputs[1]
    assert b"data-jin-fired" in outputs[0]


def _src_path() -> str:
    """`packages/*/src` を並べた `PYTHONPATH`（子プロセスは venv の site-packages も見る）。"""
    packages = Path(__file__).resolve().parents[3] / "packages"
    return os.pathsep.join(
        [str(path) for path in sorted(packages.glob("*/src"))]
        + [p for p in sys.path if "site-packages" in p]
    )


# --------------------------------------------------------------------------------------
# machine 8: 装飾は rune の SHA-256 で決まる
# --------------------------------------------------------------------------------------
def test_the_ornament_changes_when_the_rune_changes() -> None:
    assert ornament_dots("a") != ornament_dots("b")


def test_the_ornament_does_not_change_when_the_rune_stays() -> None:
    assert ornament_dots("同じ") == ornament_dots("同じ")


def test_the_ornament_uses_sha256_not_the_builtin_hash() -> None:
    """`hash()` は `PYTHONHASHSEED` で変わる。実測値でハッシュ由来であることを固定する。"""
    digest = hashlib.sha256("下書きを書く".encode()).digest()
    dots = ornament_dots("下書きを書く")
    assert len(dots) == 3 + digest[0] % 6
    assert dots[0][0] == pytest.approx(360.0 * digest[1] / 256.0)


def test_a_circle_without_a_rune_has_no_ornament() -> None:
    """layout.md §2.2: `rune` を持たない circle には装飾を描かない。"""
    bare = model_from([{"name": "A", "core": "m"}], "A")
    assert 'data-jin-kind="rune"' not in render(bare)


def test_the_svg_changes_when_only_the_rune_changes() -> None:
    """装飾が固定値になる変異を捕まえる側。"""
    one = model_from([{"name": "A", "core": "m", "instruction": {"rune": "aaa"}}], "A")
    other = model_from([{"name": "A", "core": "m", "instruction": {"rune": "bbb"}}], "A")
    first = _ornament_circles(render(one))
    second = _ornament_circles(render(other))
    assert first != second


def _ornament_circles(svg: str) -> list[str]:

    return [
        f"{element.get('cx')},{element.get('cy')},{element.get('r')}"
        for element in contract_elements(svg)
        if element.tag == f"{{{SVG_NS}}}circle" and element.get("data-jin-kind") == "rune"
    ]


def test_the_ornament_never_reads_past_the_digest() -> None:
    """点は最大 8 個で 添字 24（= 25 バイト目）までしか使わない（SHA-256 は 32 バイト）。"""
    for text in [str(value) for value in range(500)]:
        dots = ornament_dots(text)
        assert 3 <= len(dots) <= 8


def test_a_trace_overlay_is_stable_across_repeated_renders(pipeline: JinFile) -> None:
    rows = trace_rows()
    first = render(pipeline, trace=rows, upto=5)
    assert first == render(pipeline, trace=rows, upto=5)
