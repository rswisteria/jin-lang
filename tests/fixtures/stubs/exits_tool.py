"""`ref: exits_tool:boom` 用のスタブ: **ツール関数の実行中**に `sys.exit(0)` を呼ぶ。

import 時ではなく Runner の中で呼ぶので、asyncio が `SystemExit` をループの外へ再送出する
（F-S-P2-102）。`jin run` / 同期 `run_model` がこれを成功扱いにしないことの実測用。
"""

from __future__ import annotations

import sys


def boom(x: str) -> str:
    """呼ばれたらプロセスを exit 0 で終わらせようとする。"""
    sys.exit(0)
