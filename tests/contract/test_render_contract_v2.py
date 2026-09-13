"""パッケージ横断契約（Jin v2）: `jin_wasm` のトレースの pointer 空間と `jin_render.v2` の `data-jin` 空間。

v1 の `test_render_contract.py` と同じ位置づけ。`jin_render` のパッケージテストは `jin_wasm` を
import できない（兄弟・design.yaml rule 4 の v2 版・設計書 §11 #21）ので、**両方を実際に動かして
突き合わせる**のはここにしか置けない。
"""

from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from jin_core.check import check_file
from jin_core.pointer import pointer_exists
from jin_core.v2.model import JinFileV2
from jin_render import DATA_JIN_KINDS_V2, render

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_V2 = REPO_ROOT / "examples-v2"
PROGRAMS_V2 = REPO_ROOT / "tests" / "fixtures" / "v2-programs"
COMMITTED_TRACE = REPO_ROOT / "tests" / "fixtures" / "traces" / "paddle-v2.jsonl"
PADDLE = EXAMPLES_V2 / "paddle" / "paddle.jin"
JIN = Path(sys.executable).parent / "jin"


def _model(path: Path) -> JinFileV2:
    result = check_file(path)
    assert isinstance(result.model, JinFileV2), path
    return result.model


def _elements(svg: str) -> list[dict[str, str]]:
    namespace = "{http://www.w3.org/2000/svg}"
    found: list[dict[str, str]] = []

    def walk(node: ET.Element, inside_defs: bool) -> None:
        for child in node:
            in_defs = inside_defs or child.tag == f"{namespace}defs"
            if not in_defs:
                found.append(dict(child.attrib))
            walk(child, in_defs)

    walk(ET.fromstring(svg), False)
    return found


def _keys(svg: str) -> set[str]:
    keys: set[str] = set()
    for attributes in _elements(svg):
        for name in ("data-jin", "data-jin-ref"):
            if attributes.get(name) is not None:
                keys.add(attributes[name])
    return keys


def _resolves(keys: set[str], pointer: str) -> bool:
    tokens = pointer.lstrip("/").split("/")
    for length in range(len(tokens), 0, -1):
        if "/" + "/".join(tokens[:length]) in keys:
            return True
    return False


@pytest.fixture(scope="module")
def live_trace(tmp_path_factory: pytest.TempPathFactory) -> list[dict]:
    """`jin run --debug --trace` を**実際に回して**得たトレース（lupa・seed 固定）。"""
    assert JIN.exists(), f"jin コマンドが見つからない: {JIN}"
    target = tmp_path_factory.mktemp("trace") / "live.jsonl"
    result = subprocess.run(
        [str(JIN), "run", str(PADDLE), "--ticks", "3", "--debug", "--trace", str(target)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return [json.loads(line) for line in target.read_text(encoding="utf-8").split("\n") if line]


def test_the_committed_fixture_matches_a_live_run(live_trace: list[dict]) -> None:
    """`tests/fixtures/traces/paddle-v2.jsonl` が実行結果と**全行一致**する（seed 固定・`ts` 無し）。"""
    committed = [
        json.loads(line) for line in COMMITTED_TRACE.read_text(encoding="utf-8").split("\n") if line
    ]
    assert committed == live_trace


def test_every_live_pointer_resolves_at_the_root_focus(live_trace: list[dict]) -> None:
    """root（Game）の図で全行が何かの要素に解決する（入れ子の Play は referent 規則で当たる）。"""
    keys = _keys(render(_model(PADDLE)))
    for row in live_trace:
        assert _resolves(keys, row["pointer"]), f"seq={row['seq']} {row['pointer']} が解決しない"


@pytest.mark.parametrize("focus", ["Play", "Play/step", "Play/begin"])
def test_at_least_one_live_pointer_resolves_for_each_focus(
    live_trace: list[dict], focus: str
) -> None:
    keys = _keys(render(_model(PADDLE), focus=focus))
    assert any(_resolves(keys, row["pointer"]) for row in live_trace if row["kind"] != "frame")


def test_every_live_pointer_exists_in_the_model(live_trace: list[dict]) -> None:
    document = _model(PADDLE).model_dump(mode="json", by_alias=True)
    for row in live_trace:
        assert pointer_exists(document, row["pointer"]), row


@pytest.mark.parametrize("focus", [None, "Play/step"])
def test_the_cli_and_the_library_produce_the_same_svg(focus: str | None) -> None:
    """要件書 §4 最終項（v2 でも入口は 1 本）。"""
    args = [str(JIN), "render", str(PADDLE)] + (["--focus", focus] if focus else [])
    result = subprocess.run(args, cwd=REPO_ROOT, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert result.stdout.decode("utf-8") == render(_model(PADDLE), focus=focus)


def test_the_cli_reads_a_seq_zero_trace(tmp_path: Path) -> None:
    """`jin run --trace`（seq 0 始まり）→ `jin render --trace --upto 0` が繋がる。"""
    trace = tmp_path / "t.jsonl"
    run = subprocess.run(
        [str(JIN), "run", str(PADDLE), "--ticks", "1", "--debug", "--trace", str(trace)],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    assert run.returncode == 0, run.stderr.decode("utf-8", "replace")
    rendered = subprocess.run(
        [str(JIN), "render", str(PADDLE), "--focus", "Play", "--trace", str(trace), "--upto", "0"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert rendered.returncode == 0, rendered.stderr
    assert 'data-jin-fired="1"' in rendered.stdout


@pytest.mark.parametrize(
    "path",
    sorted(EXAMPLES_V2.glob("*/*.jin")) + sorted(PROGRAMS_V2.glob("*.jin")),
    ids=lambda p: p.name,
)
def test_every_rendered_pointer_is_in_the_model_pointer_space(path: Path) -> None:
    model = _model(path)
    document = model.model_dump(mode="json", by_alias=True)
    focuses = [circle.name for circle in model.circles]
    focuses += [f"{c.name}/{r.name}" for c in model.circles for r in c.rites]
    for focus in focuses:
        for attributes in _elements(render(model, focus=focus)):
            assert attributes["data-jin-kind"] in DATA_JIN_KINDS_V2
            assert pointer_exists(document, attributes["data-jin"]), (focus, attributes)
            ref = attributes.get("data-jin-ref")
            if ref is not None:
                assert pointer_exists(document, ref), (focus, attributes)


def test_the_thirteen_kinds_are_all_drawn() -> None:
    """設計書 §12 Phase 3 の完了条件。paddle の 3 視点 + `transfer.jin`（`delegate`・§11 #30）。"""
    paddle = _model(PADDLE)
    drawn: set[str] = set()
    for focus in (None, "Play", "Play/step"):
        drawn |= {a["data-jin-kind"] for a in _elements(render(paddle, focus=focus))}
    assert set(DATA_JIN_KINDS_V2) - drawn == {"delegate"}, sorted(drawn)
    drawn |= {a["data-jin-kind"] for a in _elements(render(_model(PROGRAMS_V2 / "transfer.jin")))}
    assert drawn == set(DATA_JIN_KINDS_V2)
