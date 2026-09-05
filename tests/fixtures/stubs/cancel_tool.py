"""`ref: cancel_tool:fn` 用のスタブ: ツール関数の中で `asyncio.CancelledError` を投げる。

F-S-P2-201 / 202: root が LlmAgent なら ADK が root の cancel を握って正常復帰し（exit 0 に見える）、
workflow agent 配下なら `CancelledError` が Runner から素通りする。どちらも失敗扱いにすることの実測用。
"""

from __future__ import annotations

import asyncio


def fn(query: str) -> str:
    """呼ばれたら asyncio.CancelledError を投げる。"""
    raise asyncio.CancelledError()
