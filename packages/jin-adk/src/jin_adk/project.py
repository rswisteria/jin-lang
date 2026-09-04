"""生成プロジェクトの書き出し（要件書 §3.1）。

```
<out>/
  <root_name>/
    __init__.py         # from .agent import root_agent
    agent.py            # 生成物。root_agent を公開
  .env.example
```

**この 3 ファイルちょうど**を書く。ADR-009 の対応表（pointer map）はここに書き出さない
（「生成物とは別に保持する」が決定内容であり、余計なファイルを置くと上の構造と一致しなくなる）。
"""

from __future__ import annotations

from pathlib import Path

from jin_core.model import JinFile

from jin_adk.codegen import GeneratedProject, generate

#: `<out>/<root_name>/` の下に置くファイル名（要件書 §3.1）。
PACKAGE_FILES = ("__init__.py", "agent.py")
#: `<out>/` の直下に置くファイル名。
ROOT_FILES = (".env.example",)


def project_paths(out: Path, root_name: str) -> list[Path]:
    """`build` が書くファイルの一覧（要件書 §3.1 の構造そのもの）。"""
    return [out / name for name in ROOT_FILES] + [out / root_name / name for name in PACKAGE_FILES]


def write_project(model: JinFile, out: Path) -> GeneratedProject:
    """`jin build <file> --out <dir>` の本体。

    既存ファイルは上書きする。生成物は「編集しない」ものなので
    （`CLAUDE.md`「生成コードは編集しない」）、退避は行わない。
    """
    project = generate(model)
    package = out / project.root_name
    package.mkdir(parents=True, exist_ok=True)
    # 改行を変換しない（`newline=""`）。生成物は LF 固定で、CRLF に化けると
    # スナップショットとバイト一致しなくなる（jin-cli の正準形書き出しと同じ理由）。
    _write(package / "__init__.py", project.init_py)
    _write(package / "agent.py", project.agent_py)
    _write(out / ".env.example", project.env_example)
    return project


def _write(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)


__all__ = ["PACKAGE_FILES", "ROOT_FILES", "project_paths", "write_project"]
