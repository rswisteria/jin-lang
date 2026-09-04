"""`jin-adk` — 意味モデルを ADK プロジェクトへコンパイルし、実行してトレースを採る。

要件書 §3（ADK コンパイル要件）の実装。対象ランタイムは **google-adk 2.8.0**
（`delivery/20260904-1445-jin/adk-api-probe.md` の実測でピン留め。記憶で書かない）。

**ADK の語彙が現れてよいのはこのパッケージだけ**（`CLAUDE.md`「パッケージ境界」）。
`jin_core` が `google` を import しないことは import-linter の forbidden 契約が落とす。

`google.adk` を import するのは実行系（`fake_llm` / `loader` / `run`）だけで、
コード生成（`codegen` / `project`）は**テキストしか作らない**。`jin build` に
ADK のロード（数秒）を強いないための分割であり、`from jin_adk import codegen` は
ADK が入っていなくても動く。
"""

from __future__ import annotations

from jin_adk.codegen import GeneratedProject, generate
from jin_adk.errors import CompileError, CompileIssue
from jin_adk.pointers import PointerMap
from jin_adk.project import project_paths, write_project

__all__ = [
    "CompileError",
    "CompileIssue",
    "GeneratedProject",
    "PointerMap",
    "generate",
    "project_paths",
    "write_project",
]
