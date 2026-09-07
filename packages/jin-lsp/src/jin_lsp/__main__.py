"""`python -m jin_lsp` — stdio の LSP サーバ。

CLI の `jin lsp` と**同じサーバ**を起動する（要件書 §6.1「同一サーバ実装」）。
この入口があるのは、pytest-lsp が `server_command` でサブプロセスを起動するときに
`jin` コマンドのインストール状態に依存させないためである。

**stdout は JSON-RPC の通信路**なので、ここから先で何も印字しない（DP-COMMON-14）。
"""

from __future__ import annotations

from jin_lsp.server import main

if __name__ == "__main__":
    main()
