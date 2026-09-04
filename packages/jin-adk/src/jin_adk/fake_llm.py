"""`jin run --model fake` が差し込む固定応答モデル（要件書 §3.4）。

**生成物には現れない**（ADR-008 / DP-JIN-CODEGEN-RUNTIME-01）。`FakeLlm` は
`jin run` が実行時に差し替えるものであって、`adk run <out>/<root_name>` で動く
生成プロジェクトの一部ではない。だから `jin_adk` 側に置く。

NFR-TEST-001「テストはネットワーク・API キー不要」を満たす唯一の手段でもある。
差し替えは**エージェント木を歩いて `LlmAgent.model` を置き換える**方式にした。
`LLMRegistry` へ登録する方式だと、モデル名（`gemini-2.5-flash` など）が
実物のクラスに解決されるかどうかがグローバル状態に依存し、
同一プロセスで 2 回走らせたときに前の登録が残る。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from google.adk.models import BaseLlm, LlmRequest, LlmResponse
from google.genai import types

#: 差し替え後に返る固定テキスト。**モデル呼び出しをしていないことが読んで分かる**文言にする。
DEFAULT_RESPONSE = "[fake] jin run --model fake なので、モデルは呼び出していません。"


class FakeLlm(BaseLlm):
    """固定応答を 1 回返す `BaseLlm`。

    実測シグネチャ（`adk-api-probe.md`）:
    `BaseLlm.generate_content_async(self, llm_request: LlmRequest, stream: bool = False)
    -> AsyncGenerator[LlmResponse, None]`

    **ツール呼び出しを返さない。** 返すと `.jin` の `ref` が指す関数が実際に走ることになり、
    「fake」という名前が嘘になる（テストがネットワークに出る経路も生む）。
    """

    model: str = "fake"
    response_text: str = DEFAULT_RESPONSE

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        _ = (llm_request, stream)
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text=self.response_text)])
        )


def install_fake_llm(agent: object, response_text: str = DEFAULT_RESPONSE) -> list[str]:
    """エージェント木を歩いて、`model` を持つエージェントを `FakeLlm` に差し替える。

    差し替えたエージェント名を返す（0 件なら呼び出し側が気づけるように）。

    辿るのは `sub_agents` **と `AgentTool.agent`** の 2 つ。`summon`（AgentTool）で
    呼ばれる circle は親子辺を作らないので `sub_agents` には現れず、
    `sub_agents` だけを辿ると**そこだけ実モデルが残る**（= `--model fake` が
    ネットワークに出る）。examples/researcher がまさにその形。
    """
    replaced: list[str] = []
    seen: set[int] = set()
    stack = [agent]
    while stack:
        node = stack.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        if hasattr(node, "model"):
            node.model = FakeLlm(response_text=response_text)  # type: ignore[attr-defined]
            replaced.append(getattr(node, "name", "?"))
        stack.extend(reversed(getattr(node, "sub_agents", None) or []))
        for tool in getattr(node, "tools", None) or []:
            wrapped = getattr(tool, "agent", None)
            if wrapped is not None:
                stack.append(wrapped)
    return sorted(replaced)


__all__ = ["DEFAULT_RESPONSE", "FakeLlm", "install_fake_llm"]
