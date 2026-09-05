"""jin-adk: Jin の意味モデルを Google ADK のコードへ変換し、実行し、トレースする。

依存方向は `jin_core ← jin_adk`（`jin_cli` / `jin_render` / `jin_lsp` には依存しない。
import-linter の layers 契約・ADR-004）。ADK の語彙（LlmAgent / SequentialAgent / LoopAgent /
FunctionTool / AgentTool / Runner / BaseLlm …）がリポジトリ内で現れてよい唯一の Python パッケージ。

モジュール構成:

- `codegen`  — 意味モデル → 生成コード（`agent.py` / `__init__.py` / `.env.example`）と pointer 対応表
- `build`    — 生成物を `<out>/<root_name>/` へ安全に書き出す
- `fake_llm` — ネットワークに出ない固定応答の `BaseLlm`
- `runtime`  — 生成コードを一時ディレクトリへ書いて import し、`Runner` で実行する（**任意コード実行**）
- `trace`    — ADK Event → 要件書 §3.4 のトレース行（pointer 付き）
"""

from __future__ import annotations

#: 生成コードが前提にする google-adk の版。`delivery/20260904-1445-jin/adk-api-probe.md` の実測に固定する。
#: インストールされている版がこれと違うときは `tests/contract/test_adk_version_contract.py` が赤くなる
#: （版を上げるなら probe を取り直してテンプレートを見直し、この定数を更新する）。
TARGET_ADK_VERSION = "2.8.0"

__all__ = ["TARGET_ADK_VERSION"]
