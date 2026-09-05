"""外部参照（JIN040）の解決口。

**このモジュールは import を一切行わない**。`jin_core` は「参照を解決する能力」を
プロトコルとして宣言するだけで、実際に `importlib.import_module` を呼ぶ実装は
`jin_cli.resolver.ImportResolver` にしか置かない（security review S1）。

理由: `ref` の import は**任意の Python コードをこのプロセスで実行する**。
`jin_core` は全パッケージが依存する最下層なので、ここに実装を置くと Phase 4 の LSP サーバ
（ws で外に出る。design.yaml rule 5 で `jin_core` / `jin_adk` / `jin_render` に依存する）から
無条件に到達可能になり、`.jin` を送りつけるだけで任意コード実行になる。
実装を `jin_cli.resolver`（LSP は `jin_cli` に依存しない）と `jin_adk.runtime`（`jin run`・Phase 4 で
forbidden contract の `source_modules` に `jin_lsp` を足す）に閉じ、import-linter の forbidden contract
「任意コード実行の実装は jin_cli.resolver と jin_adk.runtime に閉じる」で機械的に落とす（pyproject.toml）。
"""

from __future__ import annotations

import re
from typing import Protocol, runtime_checkable

#: Python 参照の形式（要件書 §2.2「module.path:callable 形式のみ」）。
#: 形式検査は import を伴わないので `jin_core` 側に置いてよい。
PYTHON_REF = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*$"
)


def check_ref_format(ref: str) -> str | None:
    """形式だけを検査する。問題なければ None、あれば理由を返す。"""
    if not PYTHON_REF.match(ref):
        return "形式が module.path:callable ではありません"
    return None


@runtime_checkable
class RefResolver(Protocol):
    """`ref` を解決できるかを判定する口。

    `resolve` は**診断を出さないとき None**、出すときは人間が読める理由を返す。
    例外を外へ出してはならない（`jin check` が診断ではなくトレースバックで落ちる）。
    """

    def resolve(self, ref: str) -> str | None: ...


class NullResolver:
    """既定の解決器。**解決を試みない**（JIN040 を出さない）。

    `--resolve` を指定しないときの挙動。`jin_core` 単体ではこれしか使えない。
    """

    def resolve(self, ref: str) -> str | None:
        """プロトコル適合のためのシグネチャ。`ref` は見ない。"""
        _ = ref
        return None


__all__ = ["PYTHON_REF", "NullResolver", "RefResolver", "check_ref_format"]
