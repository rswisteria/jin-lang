"""v1 の陣に答えるホスト（`jin_cli.agents`・runtime.md §11・Issue #69）。ネットワーク不要（`FakeLlm`）。"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from jin_cli.agents import AgentError, AgentHost, resolve_agent_file
from jin_core.check import check_file
from jin_core.v2.model import JinFileV2
from jin_wasm.codegen import generate
from jin_wasm.runtime import run_headless

REPO_ROOT = Path(__file__).resolve().parents[3]
AGENT = REPO_ROOT / "tests" / "fixtures" / "v2-programs" / "agent.jin"
PIPELINE = REPO_ROOT / "examples" / "pipeline" / "pipeline.jin"


@pytest.fixture
def world(tmp_path: Path) -> Path:
    """`agent.jin` と、その `agents/oracle.jin`（= v1 の pipeline・`ref` 無し）を tmp に並べる。"""
    shutil.copy(AGENT, tmp_path / "agent.jin")
    (tmp_path / "agents").mkdir()
    shutil.copy(PIPELINE, tmp_path / "agents" / "oracle.jin")
    return tmp_path / "agent.jin"


def load(path: Path) -> JinFileV2:
    result = check_file(path)
    assert result.ok, [d.message for d in result.diagnostics]
    assert isinstance(result.model, JinFileV2)
    return result.model


def test_the_host_answers_with_the_final_row_of_the_v1_run(world: Path) -> None:
    host = AgentHost.prepare(world, load(world), fake=True)
    assert host is not None
    assert list(host.agents) == ["Npc.oracle"]
    text = host.answer({"id": 1, "circle": "Npc", "name": "oracle", "prompt": "hi"})
    assert text == "fake-response"


def test_the_answer_reaches_the_next_tick_through_run_headless(world: Path) -> None:
    model = load(world)
    host = AgentHost.prepare(world, model, fake=True)
    assert host is not None
    game = generate(model, source_name=world.name, debug=True)
    result = run_headless(game.lua, game.manifest, seed=7, ticks=5, answer=host.answer)
    assert result.error is None
    assert result.public["Npc.answer"] == "fake-response"
    assert result.public["Npc.summary"] == "got:fake-response"
    assert result.replies == [{"tick": 1, "kind": "reply", "id": 1, "text": "fake-response"}]


def test_no_agent_sigil_means_no_host(tmp_path: Path) -> None:
    paddle = REPO_ROOT / "examples-v2" / "paddle" / "paddle.jin"
    assert AgentHost.prepare(paddle, load(paddle), fake=True) is None


def test_a_missing_or_foreign_or_linked_file_is_refused_before_running(
    world: Path, tmp_path: Path
) -> None:
    model = load(world)
    (tmp_path / "agents" / "oracle.jin").unlink()
    with pytest.raises(AgentError, match="v1 の .jin がありません"):
        AgentHost.prepare(world, model, fake=True)
    # 親の外を指すリンク（形は schema を通るが実体が外）
    outside = tmp_path.parent / f"{tmp_path.name}-outside.jin"
    shutil.copy(PIPELINE, outside)
    os.symlink(outside, tmp_path / "agents" / "oracle.jin")
    with pytest.raises(AgentError, match="シンボリックリンク"):
        AgentHost.prepare(world, model, fake=True)
    (tmp_path / "agents" / "oracle.jin").unlink()
    # ディレクトリのリンクで外へ抜ける
    (tmp_path / "agents").rmdir()
    elsewhere = tmp_path.parent / f"{tmp_path.name}-elsewhere"
    elsewhere.mkdir()
    shutil.copy(PIPELINE, elsewhere / "oracle.jin")
    os.symlink(elsewhere, tmp_path / "agents")
    with pytest.raises(AgentError, match="親ディレクトリの外"):
        resolve_agent_file(world, "agents/oracle.jin")


def test_a_v2_file_or_a_broken_file_is_refused(world: Path, tmp_path: Path) -> None:
    model = load(world)
    shutil.copy(AGENT, tmp_path / "agents" / "oracle.jin")
    with pytest.raises(AgentError, match="version: 1 の .jin ではありません"):
        AgentHost.prepare(world, model, fake=True)
    doc = json.loads(PIPELINE.read_text(encoding="utf-8"))
    doc["root"] = "Nowhere"
    (tmp_path / "agents" / "oracle.jin").write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(AgentError, match="jin check が通りません"):
        AgentHost.prepare(world, model, fake=True)


def test_an_unknown_destination_is_an_error(world: Path) -> None:
    host = AgentHost.prepare(world, load(world), fake=True)
    assert host is not None
    with pytest.raises(AgentError, match="agent の sigil にありません"):
        host.answer({"id": 1, "circle": "Npc", "name": "nope", "prompt": "hi"})
