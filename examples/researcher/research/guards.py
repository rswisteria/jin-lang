"""researcher.jin の boundary.guards[].ref が指すコールバック。

`guards[].on` はそのまま ADK のコールバック引数名に対応する（要件書 §3.3）。
シグネチャは google-adk 2.8.0 の実測（`google/adk/agents/llm_agent.py` の
`_SingleBeforeModelCallback` / `_SingleBeforeToolCallback`）に合わせてある。

`None` を返すと ADK は「差し替えない」と解釈して通常の処理を続ける。
"""

from __future__ import annotations

from typing import Any


def pii_filter(callback_context: Any, llm_request: Any) -> None:
    """before_model。個人情報を落とす想定の雛形（何も書き換えない）。

    暗黙に `None` を返す（= ADK は「差し替えない」と解釈して通常の処理を続ける）。
    """
    _ = (callback_context, llm_request)


def audit_log(tool: Any, args: dict[str, Any], tool_context: Any) -> None:
    """before_tool。呼び出しを記録する想定の雛形（何も書き換えない）。

    暗黙に `None` を返す（= ADK は通常のツール呼び出しを続ける）。
    """
    _ = (tool, args, tool_context)
