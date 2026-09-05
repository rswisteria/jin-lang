"""`research.guards` のスタブ。ADK のコールバックとして呼ばれても何もしない（None を返す = 素通し）。"""

from __future__ import annotations

from typing import Any


def pii_filter(callback_context: Any, llm_request: Any) -> None:
    """before_model_callback のスタブ。None を返すとモデル呼び出しはそのまま進む。"""
    return


def audit_log(tool: Any, args: Any, tool_context: Any) -> None:
    """before_tool_callback のスタブ。None を返すとツール呼び出しはそのまま進む。"""
    return
