"""`research.tools` のスタブ。関数名 = ADK の FunctionTool 名（`FunctionTool.name == func.__name__`）。"""

from __future__ import annotations


def web_search(query: str) -> str:
    """スタブ: 検索したふりをして固定文字列を返す。"""
    return f"stub-search:{query}"


def fetch_page(url: str) -> str:
    """スタブ: ページ本文のふり。"""
    return f"stub-page:{url}"


def publish(text: str) -> str:
    """スタブ: 公開したふり（本物は人の確認を待つ LongRunningFunctionTool になる）。"""
    return f"stub-published:{text}"


# ADK のツール名は func.__name__ なので、この別名で import しても名前は web_search のまま
# （`jin_adk.trace.RuntimeTable.bind_tools` の同名経路が実行時に到達可能であることの実測用）
search_again = web_search
