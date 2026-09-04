"""`FakeLlm` と差し替え（要件書 §3.4「`--model fake` は `BaseLlm` を継承した FakeLlm
（固定応答）に差し替える。テストではネットワークに出ない」）。

NFR-TEST-001 の要になるので、「差し替えたつもりで実モデルが残る」経路を潰す。
特に `summon`（`AgentTool`）で呼ばれる circle は親子辺を作らないので
`sub_agents` を辿るだけでは**届かない**。examples/researcher がその形。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from google.adk.models import BaseLlm
from jin_adk.fake_llm import DEFAULT_RESPONSE, FakeLlm, install_fake_llm
from jin_adk.loader import load_root_agent
from jin_adk.project import write_project
from jin_core.model import JinFile

REPO_ROOT = Path(__file__).resolve().parents[3]
RESEARCHER = REPO_ROOT / "examples" / "researcher" / "researcher.jin"


def test_fake_llm_is_a_base_llm() -> None:
    """ADK の差し替え口は `BaseLlm`。別の基底だと `LlmAgent.model` に入らない。"""
    assert issubclass(FakeLlm, BaseLlm)


def test_fake_llm_returns_text_and_never_a_tool_call() -> None:
    """ツール呼び出しを返すと `.jin` の `ref` が指す関数が**実際に走る**。

    「fake」という名前が嘘になるし、そこからネットワークに出る経路が生まれる。
    """

    async def collect() -> list:
        return [
            response
            async for response in FakeLlm().generate_content_async(llm_request=None, stream=False)
        ]

    responses = asyncio.run(collect())
    assert len(responses) == 1
    parts = responses[0].content.parts
    assert [part.text for part in parts] == [DEFAULT_RESPONSE]
    assert all(part.function_call is None for part in parts)


def test_the_response_text_is_configurable() -> None:
    async def collect(text: str) -> str:
        async for response in FakeLlm(response_text=text).generate_content_async(llm_request=None):
            return response.content.parts[0].text
        raise AssertionError("応答が 1 つも出ていない")

    assert asyncio.run(collect("ok")) == "ok"


def test_install_reaches_agents_behind_a_summon(tmp_path: Path, load_jin: Callable) -> None:
    """`summon`（AgentTool）の先まで差し替える。

    ここが `sub_agents` だけを辿る実装だと、Summarizer に実モデルが残り
    `jin run --model fake` が**そこだけ**ネットワークに出る。
    """
    model = load_jin(RESEARCHER)
    project = write_project(model, tmp_path)
    root_agent = load_root_agent(tmp_path, project.root_name, extra_paths=[RESEARCHER.parent])

    summarizer = root_agent.tools[2].agent
    assert summarizer.name == "Summarizer"
    assert isinstance(summarizer.model, str), "前提: 差し替え前は文字列のモデル ID"

    replaced = install_fake_llm(root_agent)
    assert replaced == ["Researcher", "Summarizer"]
    assert isinstance(summarizer.model, FakeLlm)


def test_install_reaches_agents_behind_sub_agents(
    tmp_path: Path, load_jin: Callable, minimal_jin: Callable, write_jin: Callable
) -> None:
    payload = minimal_jin(
        root="Flow",
        circles=[
            {"name": "Flow", "flow": {"kind": "sequence", "steps": ["A", "B"]}},
            {"name": "A", "core": "m", "instruction": {"rune": "x"}},
            {"name": "B", "core": "m", "instruction": {"rune": "y"}},
        ],
    )
    model = load_jin(write_jin(tmp_path, "a.jin", payload))
    project = write_project(model, tmp_path / "out")
    root_agent = load_root_agent(tmp_path / "out", project.root_name)
    assert install_fake_llm(root_agent) == ["A", "B"]


def test_install_does_not_touch_workflow_agents(
    tmp_path: Path, load_jin: Callable, minimal_jin: Callable, write_jin: Callable
) -> None:
    """workflow agent に `model` は無い（実測）。無理に生やさない。"""
    payload = minimal_jin(
        root="Flow",
        circles=[
            {"name": "Flow", "flow": {"kind": "sequence", "steps": ["A"]}},
            {"name": "A", "core": "m", "instruction": {"rune": "x"}},
        ],
    )
    model = load_jin(write_jin(tmp_path, "a.jin", payload))
    project = write_project(model, tmp_path / "out")
    root_agent = load_root_agent(tmp_path / "out", project.root_name)
    install_fake_llm(root_agent)
    assert not hasattr(root_agent, "model")


def test_no_real_model_remains_after_install(
    example_model: JinFile, example_path: Path, tmp_path: Path
) -> None:
    """examples 2 本について、木のどこにも文字列のモデル ID が残らないこと。

    「差し替えた件数が 0 でない」だけでは、1 つでも残っていれば実モデルを呼ぶ。
    """
    project = write_project(example_model, tmp_path)
    root_agent = load_root_agent(tmp_path, project.root_name, extra_paths=[example_path.parent])
    install_fake_llm(root_agent)

    remaining: list[str] = []
    seen: set[int] = set()
    stack = [root_agent]
    while stack:
        node = stack.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        if hasattr(node, "model") and not isinstance(node.model, FakeLlm):
            remaining.append(node.name)
        stack.extend(getattr(node, "sub_agents", None) or [])
        for tool in getattr(node, "tools", None) or []:
            wrapped = getattr(tool, "agent", None)
            if wrapped is not None:
                stack.append(wrapped)
    assert remaining == [], f"実モデルが残っている: {remaining}"
