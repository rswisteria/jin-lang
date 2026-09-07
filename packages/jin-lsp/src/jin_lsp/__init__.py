"""jin-lsp — Jin の Language Server（要件書 §6）。

**言語サービスの唯一の入口**である。CLI・Claude Code・VS Code・視覚エディタの全てが
`jin_core` の同じ関数をこのサーバ経由で使い、LSP 固有のロジックは
**位置変換とプロトコル露出だけ**に限定する（要件書 §6 冒頭）。

依存方向は `jin_core | jin_render ← jin_lsp`（design.yaml rule 5）。
**`jin_adk` には依存しない**。hover で ADK クラス名を出すためだけに `google-adk` を
LSP プロセスへ読み込むと、Claude Code がセッションを開くたびに ADK 全体の import を待つ。
対応表は `docs/spec/adk-mapping.md` 由来の静的な辞書（`jin_lsp.adk_names`）から引く。

`jin_cli.resolver`（`ref` の import）と `jin_adk.runtime`（生成コードの import）へは
**到達してはならない**。`jin lsp --ws` は WebSocket をローカルに開くので、任意コード実行の
実装がそこから届くと外に晒される（import-linter の forbidden 契約が機械で落とす）。
動的 import（`importlib` / `__import__` / `exec` / `eval` / `runpy`）はこのパッケージに 1 箇所も無い。
"""

from __future__ import annotations

#: サーバ名（LSP `initialize` の `serverInfo.name`）。
SERVER_NAME = "jin-lsp"

#: サーバ版（`serverInfo.version`）。パッケージ版と同じ値を持つ。
SERVER_VERSION = "0.1.0"

__all__ = ["SERVER_NAME", "SERVER_VERSION"]
