"""`--resolve` 用の実解決器（**任意コード実行を伴う**）。

`jin check --resolve` は `ref` の指すモジュールを `importlib.import_module` する。
import は**モジュールのトップレベルを実行する**ので、`.jin` を渡した相手に
このプロセスの権限で任意のコードを走らせる力を与える（security review S1）。

そのため、この実装は **`jin_cli` にしか置かない**:

- `jin_core` は `RefResolver` プロトコルしか知らない（`jin_core.resolver`）
- Phase 4 の `jin-lsp` は design.yaml rule 5 で `jin_core` / `jin_adk` / `jin_render` に依存できるが
  **`jin_cli` には依存しない**ので、ws で公開されるコードパスからここ（`jin_cli.resolver`）へは到達できない。
  `jin_adk.runtime`（`jin run` の import）へは到達できるため、Phase 4 で forbidden contract の
  `source_modules` に `jin_lsp` を足して機械化する（`phase2-handoff.md` §6）
- 任意コード実行の実装がこの 2 箇所に閉じていることは import-linter の forbidden contract
  「任意コード実行の実装は jin_cli.resolver と jin_adk.runtime に閉じる」で機械的に落とす（`pyproject.toml`）

## 親子 2 段構え（ADR-018 / DP-JIN-RESOLVE-ISOLATION-01）

同一プロセスで import すると、1 ファイル目の `ref` が `jin_core.semantic.analyze` を差し替えたとき
2 ファイル目の本物の JIN060 が消えて「2 ファイル / error 0 件」exit 0 になる（親が実測）。
プロセスが死なずもっともらしい正常レポートを出すので S2（`SystemExit`）より実害が大きく、
タイムアウトも無いのでハングしうる。そこで **CLI は `SubprocessResolver` だけを使い**、
`ref` 1 件ごとに子プロセス

    python -P -m jin_cli.resolver <module.path:callable>

を起動して、その中でだけ `ImportResolver`（同一プロセス import）を動かす。親が受け取るのは
stdout 最終行の JSON 1 行（解決できたか・理由）だけなので、import 先が何を差し替えても親には及ばない。

- `-P` は cwd を子の `sys.path` に足さない（`python -m` は既定で足す）。CLI の `jin` コンソールスクリプトも
  cwd を載せないので、子プロセス化で cwd 解決の経路を**新設しない**（F-S-P2-101 と同じ原則）。
  `PYTHONPATH` は子に引き継ぐ（`ref` の供給手段はこれまでどおり）
- タイムアウトは ref 1 件あたり `RESOLVE_TIMEOUT_SECONDS`（30 秒）。根拠は `docs/spec/diagnostics.md` の JIN040 節
- タイムアウト・子の異常終了（`os._exit` / シグナル）・結果行の欠落はすべて **JIN040 として報告**する
  （fail-closed・S2 と同じ原則）。診断ゼロ・exit 0 で終わらない
- **S1 は消えない。** 子は親と同じ権限で走る。「中身を確認した `.jin` にだけ使う」警告は README / CLAUDE.md /
  `--help` に残す

    hazard: _import_module -> importlib.import_module
    hazard: _spawn_child -> subprocess.run
    guard: _spawn_child -> subprocess.TimeoutExpired

CLI から明示的に `--resolve` を渡したときだけ使われる。
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from types import ModuleType

from jin_core.resolver import check_ref_format

#: 子プロセスが `ref` 1 件の import に使ってよい秒数（ADR-018）。CLI オプションでは変えない。
RESOLVE_TIMEOUT_SECONDS = 30.0

#: 子が stdout の最終行に書く JSON のキー。import 先が stdout に何か書いても、この鍵と `ref` の一致で見分ける。
RESULT_KEY = "jin_resolve"


def _import_module(module_name: str) -> ModuleType:
    """**任意コード実行の所在**。`ImportResolver` からだけ呼ぶ。"""
    return importlib.import_module(module_name)


class ImportResolver:
    """`ref` を**このプロセスで**実際に import して解決可否を判定する。

    CLI からは直接使わず、`SubprocessResolver` が起動した子プロセスの中でだけ動く（ADR-018）。
    ライブラリとして同一プロセスで使うと、import 先がこのプロセスを汚染しうる。

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
            module = _import_module(module_name)
        except KeyboardInterrupt:
            raise
        except BaseException as exc:  # noqa: BLE001 - import は SystemExit も投げうる（S2）
            return f"モジュール {module_name} を import できません（{type(exc).__name__}: {exc}）"
        if not hasattr(module, attribute):
            return f"モジュール {module_name} に {attribute} がありません"
        return None


def _child_argv(ref: str) -> list[str]:
    """子プロセスの起動列。`-P` で cwd を `sys.path` に足さない（F-S-P2-101 と同じ原則）。"""
    return [sys.executable, "-P", "-m", "jin_cli.resolver", ref]


def _parse_child_output(stdout: bytes, ref: str) -> str | None:
    """子の stdout から結果行を取り出す。**最終行**だけを見る。

    import 先が stdout に何か書いても、その後に `_child_main` が結果行を書くので最終行が結果になる。
    結果行が無い（`os._exit` などで import の途中で終わった）ときは理由を返す（fail-closed）。
    """
    for line in reversed(stdout.decode("utf-8", errors="replace").splitlines()):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            break
        if isinstance(payload, dict) and payload.get(RESULT_KEY) == ref:
            reason = payload.get("reason")
            return None if reason is None else str(reason)
        break
    return "解決用の子プロセスが結果を返しませんでした（import の途中で終了した可能性があります）"


def _spawn_child(ref: str, timeout: float) -> str | None:
    """`ref` 1 件を子プロセスで import し、解決できなければ理由を返す。

    タイムアウトしたら子を止めて理由を返す（`subprocess.run` が kill する）。
    子が 0 以外で終わったら（`os._exit(3)` / シグナル / 結果行の書き込み失敗）理由を返す。
    """
    try:
        # argv は固定列 + 形式検査済みの ref（識別子と `.` `:` だけ）。shell は通さない
        completed = subprocess.run(
            _child_argv(ref), capture_output=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired:
        return f"{timeout:g} 秒以内に import が終わりませんでした（タイムアウト・子プロセスを止めました）"
    except (OSError, ValueError) as exc:
        return f"解決用の子プロセスを起動できません（{type(exc).__name__}: {exc}）"
    if completed.returncode != 0:
        return f"解決用の子プロセスが異常終了しました（exit {completed.returncode}）"
    return _parse_child_output(completed.stdout, ref)


class SubprocessResolver:
    """`ref` 1 件ごとに子プロセスで import する解決器（ADR-018）。CLI の `--resolve` はこれだけを使う。

    形式が不正な `ref` は子を起動せずに理由を返す（`check_ref_format`）。
    """

    def __init__(self, timeout: float = RESOLVE_TIMEOUT_SECONDS) -> None:
        self.timeout = timeout

    def resolve(self, ref: str) -> str | None:
        reason = check_ref_format(ref)
        if reason is not None:
            return reason
        return _spawn_child(ref, self.timeout)


def _child_main(argv: list[str]) -> int:
    """子プロセス側。`python -P -m jin_cli.resolver <ref>` で入る。

    結果は stdout の**最終行**に JSON 1 行で書く。import 先が stdout に書いた分は先に flush し、
    改行を 1 つ前置して結果行を独立させる。stdout を差し替えられて書けなければ例外で 0 以外になり、
    親が「異常終了」として JIN040 にする（fail-closed）。
    """
    if len(argv) != 1:
        sys.stderr.write("usage: python -P -m jin_cli.resolver <module.path:callable>\n")
        return 2
    ref = argv[0]
    reason = ImportResolver().resolve(ref)
    line = json.dumps({RESULT_KEY: ref, "reason": reason}, ensure_ascii=False)
    sys.stdout.flush()
    sys.stdout.buffer.write(f"\n{line}\n".encode())
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":  # pragma: no cover - 子プロセスとして実行される
    sys.exit(_child_main(sys.argv[1:]))


__all__ = ["RESOLVE_TIMEOUT_SECONDS", "RESULT_KEY", "ImportResolver", "SubprocessResolver"]
