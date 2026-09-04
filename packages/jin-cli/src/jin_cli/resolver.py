"""`--resolve` 用の実解決器（**任意コード実行を伴う**）。

`jin check --resolve` は `ref` の指すモジュールを `importlib.import_module` する。
import は**モジュールのトップレベルを実行する**ので、`.jin` を渡した相手に
このプロセスの権限で任意のコードを走らせる力を与える（security review S1）。

そのため、この実装は **`jin_cli` にしか置かない**:

- `jin_core` は `RefResolver` プロトコルしか知らない（`jin_core.resolver`）
- Phase 4 の `jin-lsp` は `jin_core` にしか依存しないので、ws で公開されるコードパスから
  ここへ到達できない
- その到達不能性は import-linter の forbidden contract
  「resolver の実装は jin_cli に閉じる」で機械的に落とす（`pyproject.toml`）

CLI から明示的に `--resolve` を渡したときだけ使われる。
"""

from __future__ import annotations

import importlib

from jin_core.resolver import check_ref_format


class ImportResolver:
    """`ref` を実際に import して解決可否を判定する。

    **`BaseException` まで捕まえる**。`except Exception` だけでは、import 先の
    トップレベルにある `sys.exit(0)` が投げる `SystemExit` が素通りし、
    `jin check --resolve` が**診断ゼロ・exit 0** で終わる（security review S2 / fail-open）。
    利用者の Ctrl-C だけは通す。
    """

    def resolve(self, ref: str) -> str | None:
        reason = check_ref_format(ref)
        if reason is not None:
            return reason
        module_name, _, attribute = ref.partition(":")
        try:
            module = importlib.import_module(module_name)
        except KeyboardInterrupt:
            raise
        except BaseException as exc:  # noqa: BLE001 - import は SystemExit も投げうる（S2）
            return f"モジュール {module_name} を import できません（{type(exc).__name__}: {exc}）"
        if not hasattr(module, attribute):
            return f"モジュール {module_name} に {attribute} がありません"
        return None


__all__ = ["ImportResolver"]
