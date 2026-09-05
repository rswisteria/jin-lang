"""`jin_adk.fake_llm.FakeLlm`: ネットワークに出ない固定応答（要件書 §3.4）。

テストが決定的になるよう、応答は呼び出し順に `responses` から取り、尽きたら最後の要素を繰り返す。
"""

from __future__ import annotations

import asyncio

from google.adk.models import BaseLlm, LlmRequest
from jin_adk.fake_llm import DEFAULT_RESPONSE, FakeLlm, FakeToolCall


def _collect(llm: FakeLlm, n: int) -> list:
    async def go():
        out = []
        for _ in range(n):
            async for response in llm.generate_content_async(LlmRequest(), stream=False):
                out.append(response)
        return out

    return asyncio.run(go())


def test_fake_llm_is_a_base_llm_named_fake() -> None:
    llm = FakeLlm()
    assert isinstance(llm, BaseLlm)
    assert llm.model == "fake"
    assert "fake" in FakeLlm.supported_models()


def test_default_response_is_a_fixed_string() -> None:
    responses = _collect(FakeLlm(), 3)
    texts = [r.content.parts[0].text for r in responses]
    assert texts == [DEFAULT_RESPONSE] * 3


def test_scripted_responses_are_consumed_in_order_and_last_one_repeats() -> None:
    llm = FakeLlm(responses=["one", "two"])
    texts = [r.content.parts[0].text for r in _collect(llm, 4)]
    assert texts == ["one", "two", "two", "two"]


def test_tool_call_script_yields_a_function_call_part() -> None:
    llm = FakeLlm(responses=[FakeToolCall(name="web_search", args={"query": "q"}), "done"])
    first, second = _collect(llm, 2)
    call = first.content.parts[0].function_call
    assert call is not None and call.name == "web_search" and dict(call.args) == {"query": "q"}
    assert second.content.parts[0].text == "done"


def test_two_instances_do_not_share_state() -> None:
    a, b = FakeLlm(responses=["a1", "a2"]), FakeLlm(responses=["b1", "b2"])
    assert _collect(a, 1)[0].content.parts[0].text == "a1"
    assert _collect(b, 1)[0].content.parts[0].text == "b1"
    assert _collect(a, 1)[0].content.parts[0].text == "a2"


def test_fake_llm_never_imports_a_network_client() -> None:
    """NFR-TEST-001: FakeLlm のモジュールは HTTP クライアントを import しない。"""
    import ast
    from pathlib import Path

    import jin_adk.fake_llm as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imported = {
        (node.module or "") if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in (node.names if isinstance(node, ast.Import) else [None])
    }
    for banned in ("httpx", "requests", "aiohttp", "urllib", "google.genai.client"):
        assert not any(name.startswith(banned) for name in imported), imported
