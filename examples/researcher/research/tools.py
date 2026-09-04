"""researcher.jin の tools[].ref が指す関数。

ADK は型注釈と docstring から関数呼び出しスキーマを作るので、注釈を必ず付ける
（`FunctionTool(func)` / `LongRunningFunctionTool(func)` の実測シグネチャは
`docs/spec/adk-mapping.md` §2.2）。
"""

from __future__ import annotations


def web_search(query: str) -> dict[str, str]:
    """与えられた語で検索する（雛形。ネットワークには出ない）。

    Args:
        query: 検索語。

    Returns:
        `status` と `result` を持つ辞書。
    """
    return {"status": "stub", "result": f"'{query}' の検索結果はこの雛形にはありません"}


def fetch_page(url: str) -> dict[str, str]:
    """URL の本文を取得する（雛形。ネットワークには出ない）。

    Args:
        url: 取得先。

    Returns:
        `status` と `body` を持つ辞書。
    """
    return {"status": "stub", "body": f"{url} の本文はこの雛形にはありません"}


def publish(title: str, body: str) -> dict[str, str]:
    """公開する。boundary.await に載っているので LongRunningFunctionTool になる。

    Args:
        title: 見出し。
        body: 本文。

    Returns:
        `status` を持つ辞書。人間の承認を待つ前提の long running ツール。
    """
    return {"status": "pending_human_approval", "title": title, "body": body}
