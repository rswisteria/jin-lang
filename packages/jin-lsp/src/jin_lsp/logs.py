"""ログの出力先（DP-COMMON-14・人間確定）。

決定内容: **トレース JSONL とサーバログを分離し、サーバログは stderr 固定**。
理由は stdio トランスポートでは **stdout が JSON-RPC の通信路そのもの**だからである。
`print()` 1 つ、ライブラリの `logging.StreamHandler()`（既定は stderr だが
`sys.stdout` を渡す実装がある）1 つで、クライアントは「壊れたヘッダ」を受け取り
セッションごと落ちる。しかも**ログの中身が相手に渡る**ので情報漏れにもなる。

そのため:

- `configure()` が root logger に **stderr のハンドラだけ**を付ける
- `jin_lsp` パッケージに `print(...)` を 1 つも置かない
  （`tests/contract/test_guard_claims.py` と `test_lsp_contract.py` が走査して固定する）

guard: configure -> sys.stderr
"""

from __future__ import annotations

import logging
import sys

#: ログの書式。時刻はクライアントのログビューアが付けるので、こちらは付けない
#: （二重の時刻は読みにくいうえ、テストの出力が非決定的になる）。
_FORMAT = "%(levelname)s %(name)s: %(message)s"


def configure(level: int = logging.WARNING) -> None:
    """root logger を **stderr だけ**に向ける（DP-COMMON-14）。

    guard: configure -> sys.stderr

    既に付いているハンドラは**外す**。pygls も lsprotocol も自前でハンドラを足さないが、
    アプリケーション側の設定（`logging.basicConfig` を先に呼ぶ何か）が stdout の
    ハンドラを残していると、そこから JSON-RPC の通信路が汚れる。
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(handler)
    root.setLevel(level)


__all__ = ["configure"]
