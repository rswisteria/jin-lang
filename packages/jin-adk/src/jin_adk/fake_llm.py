"""`FakeLlm`: ネットワークに出ない固定応答の `BaseLlm`（要件書 §3.4 / NFR-TEST-001）。

ADR-008: FakeLlm は生成物（`agent.py`）に埋め込まず、`jin_adk` 側にだけ置く。
`jin run --model fake` が import 後の agent 木を走査して `LlmAgent.model` に差し替える
（`jin_adk.runtime.swap_models`）。

応答は**決定的**: `responses` を呼び出し順に返し、尽きたら最後の要素を繰り返す。
`FakeToolCall` を置くと function_call を返すので、ツール経路のトレース（`kind: tool`）を
テストできる。実測 API: `BaseLlm.generate_content_async(llm_request, stream=False)`
→ `AsyncGenerator[LlmResponse, None]`（`delivery/20260904-1445-jin/adk-api-probe.md`）。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from google.adk.models import BaseLlm, LlmRequest, LlmResponse
from google.genai import types
from pydantic import BaseModel, Field, PrivateAttr

#: 既定の固定応答。`output_key` へこの文字列が入る。
DEFAULT_RESPONSE = "fake-response"


class FakeToolCall(BaseModel):
    """FakeLlm に「このツールを呼べ」と言わせる台本の 1 行。"""

    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class FakeLlm(BaseLlm):
    """固定応答の LLM。`model` は常に `"fake"`。

    Pydantic モデルなので状態は `PrivateAttr` に置く（クラス属性を後付けすると
    `AttributeError` になる・実測）。
    """

    model: str = "fake"
    responses: list[str | FakeToolCall] = Field(default_factory=lambda: [DEFAULT_RESPONSE])
    _calls: int = PrivateAttr(default=0)

    @classmethod
    def supported_models(cls) -> list[str]:
        return ["fake"]

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        _ = (llm_request, stream)
        index = min(self._calls, len(self.responses) - 1)
        self._calls += 1
        item = self.responses[index]
        if isinstance(item, FakeToolCall):
            part = types.Part(
                function_call=types.FunctionCall(name=item.name, args=dict(item.args))
            )
        else:
            part = types.Part(text=item)
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


__all__ = ["DEFAULT_RESPONSE", "FakeLlm", "FakeToolCall"]
