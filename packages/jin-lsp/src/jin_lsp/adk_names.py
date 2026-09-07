"""hover が出す ADK クラス名（要件書 §6.2 の hover 行「要素 → ADK クラス名と生成される引数」）。

正本は `docs/spec/adk-mapping.md` §1 の語彙対応表と §2 の実測 API である。
**ここは `jin_adk` を import しない**。hover のためだけに `google-adk` を LSP プロセスへ
読み込むと、Claude Code がセッションを開くたびに ADK 全体の import を待つことになる
（`jin_lsp` の依存に `jin-adk` を入れない理由でもある）。

そのため対応は**静的な辞書**として持ち、`tests/spec/test_spec_consistency.py` が
`docs/spec/adk-mapping.md` の表と突合して同期のドリフトを落とす（仕様側とコード側は
同じ欠陥・片方だけ直さない）。
"""

from __future__ import annotations

#: `flow.kind` → ADK の workflow agent クラスと主な引数（adk-mapping.md §2.1）。
FLOW_AGENTS: dict[str, tuple[str, str]] = {
    "sequence": ("SequentialAgent", "name / sub_agents / description"),
    "parallel": ("ParallelAgent", "name / sub_agents / description"),
    "loop": ("LoopAgent", "name / sub_agents / description / max_iterations"),
}

#: `tools[].kind` → ADK のツールクラス（adk-mapping.md §2.2）。
TOOL_CLASSES: dict[str, tuple[str, str]] = {
    "tool": ("FunctionTool", "FunctionTool(func, *, require_confirmation=False)"),
    "builtin": (
        "組み込みツールのインスタンス",
        "google.adk.tools の値をそのまま tools=[...] に置く",
    ),
    "summon": (
        "AgentTool",
        (
            "AgentTool(agent, skip_summarization=False, *, include_plugins=True, "
            "propagate_grounding_metadata=False)"
        ),
    ),
}

#: `boundary.await[]` に載った `kind: tool` は `LongRunningFunctionTool` になる（§2.2）。
AWAIT_TOOL_CLASS = ("LongRunningFunctionTool", "LongRunningFunctionTool(func)")

#: `core` を持つ circle の既定（§2.1）。
LLM_AGENT = (
    "LlmAgent",
    (
        "name / model / description / instruction / tools / sub_agents / output_key / "
        "before_agent_callback / after_agent_callback / before_model_callback / "
        "after_model_callback / before_tool_callback / after_tool_callback"
    ),
)

#: `boundary.guards[].on` → コールバック引数名（§2.1「`before_/after_{agent,model,tool}_callback`」）。
GUARD_CALLBACKS = (
    "before_agent_callback / after_agent_callback / before_model_callback / "
    "after_model_callback / before_tool_callback / after_tool_callback"
)

#: `flow.max` の落とし先。**`max` という引数名は ADK に存在しない**（§2.1 の太字）。
LOOP_MAX_ARGUMENT = "max_iterations"

__all__ = [
    "AWAIT_TOOL_CLASS",
    "FLOW_AGENTS",
    "GUARD_CALLBACKS",
    "LLM_AGENT",
    "LOOP_MAX_ARGUMENT",
    "TOOL_CLASSES",
]
