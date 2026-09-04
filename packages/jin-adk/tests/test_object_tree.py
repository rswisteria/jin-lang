"""生成モジュールを import して ADK オブジェクト木を検証する。

design.yaml Phase 2 machine 条件 2「生成モジュールを import して ADK オブジェクト木を
検証する（tools の型 / sub_agents の名前 / callback の同一性）。**モデル呼び出しはしない**」
と条件 4「google-adk 2.8.0 に対する生成モジュールの import テストが通る（NFR-VER-001）」。

**ネットワークにも API キーにも触れない**（NFR-TEST-001）。ここでやるのは
「生成コードが ADK のオブジェクトを組み立てられるか」までで、実行はしない。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from google.adk.agents import LlmAgent, LoopAgent, SequentialAgent
from google.adk.tools import FunctionTool, LongRunningFunctionTool
from google.adk.tools.agent_tool import AgentTool
from jin_adk.loader import load_root_agent
from jin_adk.project import write_project
from jin_core.model import JinFile

REPO_ROOT = Path(__file__).resolve().parents[3]
RESEARCHER = REPO_ROOT / "examples" / "researcher" / "researcher.jin"
PIPELINE = REPO_ROOT / "examples" / "pipeline" / "pipeline.jin"


def build_and_load(model: JinFile, out: Path, extra: list[Path] | None = None) -> object:
    project = write_project(model, out)
    return load_root_agent(out, project.root_name, extra_paths=extra or [])


def test_every_example_imports_under_the_pinned_adk(
    example_model: JinFile, example_path: Path, tmp_path: Path
) -> None:
    """machine 4: 生成モジュールが実物の google-adk 2.8.0 で import できる。"""
    root_agent = build_and_load(example_model, tmp_path, [example_path.parent])
    assert root_agent.name == example_model.root


def test_researcher_object_tree(tmp_path: Path, load_jin: Callable) -> None:
    """machine 2: tools の型 / sub_agents の名前 / callback の同一性。"""
    from research.guards import audit_log, pii_filter  # 生成物と同じ関数を直接読む

    model = load_jin(RESEARCHER)
    root_agent = build_and_load(model, tmp_path, [RESEARCHER.parent])

    assert isinstance(root_agent, LlmAgent)
    assert root_agent.name == "Researcher"
    assert root_agent.model == "gemini-2.5-flash"
    assert root_agent.output_key == "findings"

    # tools の**型**（`await` に載っている publish だけ LongRunningFunctionTool）。
    types_ = [type(tool) for tool in root_agent.tools]
    assert types_ == [FunctionTool, FunctionTool, AgentTool, LongRunningFunctionTool]

    # `summon` は AgentTool で包むだけで親子辺を作らない（docs/spec/model.md §4）。
    summoned = root_agent.tools[2].agent
    assert isinstance(summoned, LlmAgent)
    assert summoned.name == "Summarizer"
    assert root_agent.sub_agents == []

    # callback の**同一性**。名前が合っているだけでは、別の関数を渡していても通る。
    assert root_agent.before_model_callback is pii_filter
    assert root_agent.before_tool_callback is audit_log
    assert root_agent.after_model_callback is None
    assert root_agent.after_tool_callback is None


def test_pipeline_object_tree(tmp_path: Path, load_jin: Callable) -> None:
    """machine 2: workflow agent の種類と `sub_agents` の**並び**。"""
    model = load_jin(PIPELINE)
    root_agent = build_and_load(model, tmp_path)

    assert isinstance(root_agent, SequentialAgent)
    assert [a.name for a in root_agent.sub_agents] == ["Drafter", "Reviewer", "Refine"]

    refine = root_agent.sub_agents[2]
    assert isinstance(refine, LoopAgent)
    assert refine.max_iterations == 3
    # 判定エージェントは**末尾**（要件書 §3.3）。
    assert [a.name for a in refine.sub_agents] == ["Critic", "Rewriter", "Refine__exit"]
    assert refine.sub_agents[2].state_key == "approved"
    assert refine.sub_agents[2].expected is True


def test_the_generated_state_check_agent_escalates_only_when_the_condition_holds(
    tmp_path: Path, load_jin: Callable
) -> None:
    """埋め込んだ `StateCheckAgent` の**中身**を直接動かす（ADR-008 の実体）。

    生成コードにクラス本体を埋めた以上、その本体が正しく動くことまで見る。
    「生成した」だけでは、条件が成立しても escalate しないコードを埋めていても緑になる。
    """
    import asyncio
    from types import SimpleNamespace

    model = load_jin(PIPELINE)
    root_agent = build_and_load(model, tmp_path)
    checker = root_agent.sub_agents[2].sub_agents[2]

    async def events(state: dict[str, object]) -> list[object]:
        ctx = SimpleNamespace(session=SimpleNamespace(state=state))
        return [event async for event in checker._run_async_impl(ctx)]

    assert asyncio.run(events({"approved": False})) == []
    escalated = asyncio.run(events({"approved": True}))
    assert len(escalated) == 1
    assert escalated[0].actions.escalate is True
    assert escalated[0].author == "Refine__exit"


def test_builtin_tool_is_the_adk_instance(
    tmp_path: Path, load_jin: Callable, minimal_jin: Callable, write_jin: Callable
) -> None:
    """`builtin` が ADK の組み込みインスタンスそのものになる。"""
    from google.adk.tools import google_search

    payload = minimal_jin(
        circles=[
            {
                "name": "Root",
                "core": "m",
                "instruction": {"rune": "x"},
                "tools": [{"name": "s", "kind": "builtin", "builtin": "google_search"}],
            }
        ]
    )
    model = load_jin(write_jin(tmp_path, "a.jin", payload))
    root_agent = build_and_load(model, tmp_path / "out")
    assert root_agent.tools == [google_search]


def test_delegate_becomes_sub_agents_with_a_parent_link(
    tmp_path: Path, load_jin: Callable, minimal_jin: Callable, write_jin: Callable
) -> None:
    """`delegate[]` → `sub_agents`。ADK 側で親が張られる（JIN013 が多重親を落とす前提）。"""
    payload = minimal_jin(
        circles=[
            {"name": "Root", "core": "m", "instruction": {"rune": "x"}, "delegate": ["Child"]},
            {"name": "Child", "core": "m", "instruction": {"rune": "y"}},
        ]
    )
    model = load_jin(write_jin(tmp_path, "a.jin", payload))
    root_agent = build_and_load(model, tmp_path / "out")
    assert [a.name for a in root_agent.sub_agents] == ["Child"]
    assert root_agent.sub_agents[0].parent_agent is root_agent


def test_loading_twice_does_not_serve_a_cached_module(
    tmp_path: Path, load_jin: Callable, minimal_jin: Callable, write_jin: Callable
) -> None:
    """一時ディレクトリを使い回すので、`sys.modules` のキャッシュを踏むと**前回の木**が返る。

    同じ `root_name` で中身の違うプロジェクトを 2 回読み、2 回目が新しい内容になることを見る。
    ここが壊れると `jin run` を 2 回呼んだテストが**前回の生成物**を検証してしまう。
    """
    first = minimal_jin(circles=[{"name": "Root", "core": "one", "instruction": {"rune": "x"}}])
    second = minimal_jin(circles=[{"name": "Root", "core": "two", "instruction": {"rune": "x"}}])

    agent_one = build_and_load(load_jin(write_jin(tmp_path, "a.jin", first)), tmp_path / "out1")
    agent_two = build_and_load(load_jin(write_jin(tmp_path, "b.jin", second)), tmp_path / "out2")
    assert agent_one.model == "one"
    assert agent_two.model == "two"


def test_loading_restores_sys_path(tmp_path: Path, load_jin: Callable) -> None:
    """`sys.path` を汚さない（テストの実行順で結果が変わらないように）。"""
    import sys

    before = list(sys.path)
    build_and_load(load_jin(RESEARCHER), tmp_path, [RESEARCHER.parent])
    assert sys.path == before


def test_missing_ref_module_is_reported_as_a_diagnostic(
    tmp_path: Path, load_jin: Callable, minimal_jin: Callable, write_jin: Callable
) -> None:
    """`ref` の import が失敗したらトレースバックではなく `GeneratedModuleError`。"""
    from jin_adk.loader import GeneratedModuleError

    payload = minimal_jin(
        circles=[
            {
                "name": "Root",
                "core": "m",
                "instruction": {"rune": "x"},
                "tools": [{"name": "t", "kind": "tool", "ref": "no_such_module_xyz:fn"}],
            }
        ]
    )
    model = load_jin(write_jin(tmp_path, "a.jin", payload))
    with pytest.raises(GeneratedModuleError, match="import できません"):
        build_and_load(model, tmp_path / "out")
