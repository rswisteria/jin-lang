"""生成モジュールの import（要件書 §3.4「生成コードを一時ディレクトリに書き出して import」）。

**`jin_adk` の中で `importlib` を使うのはこのモジュールだけ。**
`tests/contract/test_packaging_contract.py::test_the_only_module_importing_importlib_is_the_cli_resolver`
がその 1 箇所性を機械で固定する（security review S1 の生の網）。

## ここで起きること（利用者に隠さない）

import は**モジュールのトップレベルを実行する**。`jin run` は

1. `.jin` から生成した `agent.py` を実行し、
2. その `agent.py` が `.jin` の `tools[].ref` / `boundary.guards[].ref` が指す
   ユーザのモジュールを import する

ので、`jin run` は `.jin` を書いた相手に**このプロセスの権限で任意のコードを実行させる**。
`jin check --resolve` と同じ危険性であり（`CLAUDE.md`「`--resolve` の危険性」）、
違いは「`jin run` は実行するためのコマンドなので、それが目的である」ことだけ。
CLI の `--help` と docstring に必ず書く。

`jin_core` はこの実装を知らない。`jin_lsp`（Phase 4・ws で外に出る）は `jin_core` にしか
依存しないので、この経路へ到達できない。
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType


class GeneratedModuleError(Exception):
    """生成モジュールを import できなかった / `root_agent` を公開していなかった。"""


@contextmanager
def _sys_path(entries: list[Path]) -> Iterator[None]:
    """`sys.path` の先頭に足して、必ず元へ戻す。

    `finally` で元のリストごと差し戻す（`remove` だと、import されたコードが
    `sys.path` を触っていたときに戻し方が壊れる）。
    """
    original = list(sys.path)
    for entry in reversed(entries):
        sys.path.insert(0, str(entry))
    try:
        yield
    finally:
        sys.path[:] = original


def load_root_agent(
    project_root: Path, root_name: str, extra_paths: list[Path] | None = None
) -> object:
    """`<project_root>/<root_name>/agent.py` を import して `root_agent` を返す。

    `extra_paths` には `.jin` が置かれたディレクトリを渡す。`tools[].ref` が
    `research.tools:web_search` のような**相対的な**参照を指すとき、その `research`
    パッケージは普通 `.jin` の隣にある（examples/researcher がその形）。
    ここを足さないと、生成物としては正しいのに `jin run` だけが import に失敗する。

    同じ `root_name` を 1 プロセスで 2 回読むと `sys.modules` のキャッシュが
    **前回の一時ディレクトリの中身**を返す。毎回キャッシュを落としてから import する。
    """
    entries = [project_root, *(extra_paths or [])]
    module_name = f"{root_name}.agent"
    with _sys_path(entries):
        for cached in [
            name for name in sys.modules if name == root_name or name.startswith(f"{root_name}.")
        ]:
            del sys.modules[cached]
        try:
            module: ModuleType = importlib.import_module(module_name)
        except Exception as exc:
            raise GeneratedModuleError(
                f"生成モジュール {module_name} を import できません（{type(exc).__name__}: {exc}）"
            ) from exc
    root_agent = getattr(module, "root_agent", None)
    if root_agent is None:
        raise GeneratedModuleError(f"生成モジュール {module_name} が root_agent を公開していません")
    return root_agent


__all__ = ["GeneratedModuleError", "load_root_agent"]
