"""`jin editor` の実行エンドポイントの中身（Issue #34・要件書 §7.2 のライブ実行）。

ここがするのは 3 つだけである:

1. `jin run` を**子プロセス**として起こす
2. `--trace` の JSONL を tail して 1 行ずつ SSE のフレームにする
3. 子の終了を `done` として 1 回だけ流す

**HTTP は知らない。** ヘッダも検査もしない（それは `editor.py` の役目）。

【危険】`jin run` は `.jin` の `ref` が指すモジュールを import する。これは
**この計算機の権限で任意のコードを実行する**ことと同じである（`--model fake` は
モデル呼び出しをネットワークに出さないだけで、import は行う）。子プロセスに分けているのは
`jin editor` が LSP を抱えた長命プロセスだからで（`sys.modules` の汚染や、ツール関数の
`sys.exit()` がサーバごと巻き込むのを避ける・ADR-018 と同じ理由）、**権限は分かれていない**。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

#: トレースを見に行く間隔（秒）。短くすると反応が良くなり syscall が増える。
POLL_SECONDS = 0.05

#: `terminate()` から `kill()` へ上げるまでの猶予（秒）。
GRACE_SECONDS = 5.0

_TRACE_NAME = "trace.jsonl"
_STDERR_NAME = "stderr.txt"


class RunRejected(Exception):
    """要求が受け取れない理由。HTTP では 400 になる。"""


@dataclass(frozen=True, slots=True)
class RunRequest:
    """実行の要求。**対象ファイルは含まない**（`jin editor` に渡されたものに固定する）。"""

    prompt: str
    model: str | None


def parse_request(body: bytes) -> RunRequest:
    """POST の body を読む。読めない形は理由を添えて断る。"""
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RunRejected("JSON として読めません") from exc
    if not isinstance(payload, dict):
        raise RunRejected("JSON オブジェクトを送ってください")
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or prompt == "":
        raise RunRejected("prompt が要ります")
    model = payload.get("model")
    if model is not None and model != "fake":
        # `jin run` と同じ規律。実モデルは `.jin` の core が持つ。
        raise RunRejected("model に指定できるのは fake だけです")
    return RunRequest(prompt=prompt, model=model)


def sse(event: str, payload: object) -> bytes:
    """SSE の 1 フレーム。`data` は**必ず JSON にする**（生の改行が入ると書式が壊れる）。"""
    data = json.dumps(payload, ensure_ascii=False)
    return f"event: {event}\ndata: {data}\n\n".encode()


def sse_row(line: str) -> bytes:
    """トレースの 1 行を**そのまま**載せる。

    行は `jin_adk.trace` が `json.dumps` で書いたものなので改行を含まない。
    ブラウザ側は `apps/editor/src/trace/parse.ts` の契約をそのまま使う（二重に実装しない）。
    """
    return f"event: row\ndata: {line}\n\n".encode()


class RunSlot:
    """同時に走ってよいのは 1 本だけ、を保つ枠。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._busy = False
        self._process: subprocess.Popen[bytes] | None = None

    def try_acquire(self) -> bool:
        with self._lock:
            if self._busy:
                return False
            self._busy = True
            return True

    def attach(self, process: subprocess.Popen[bytes]) -> None:
        with self._lock:
            self._process = process

    def release(self) -> None:
        with self._lock:
            self._busy = False
            self._process = None

    def terminate(self) -> None:
        """走っている子を終わらせる。**サーバの終了時に必ず呼ぶ**（Issue #32 の教訓）。"""
        with self._lock:
            process = self._process
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def command_for(target: Path, request: RunRequest, trace: Path) -> list[str]:
    """子プロセスのコマンド。

    `jin_cli` に `__main__.py` は無いが `main.py` に `if __name__ == "__main__": app()` がある。
    `sys.executable` を使うのは `jin` コンソールスクリプトが PATH にあるとは限らないため。

    **`-P` を必ず付ける。** これが無いと `python -m` は cwd を `sys.path[0]` に置き、
    それが**子の一生の間**続く。CLAUDE.md が明示している「Runner 実行中は cwd が
    `sys.path` に無い」が崩れ、ADK が LLM 要求のたびに遅延 import する未インストールの
    任意依存（`anthropic` / `openai` / `a2a` …）を cwd から解決させる経路が復活する
    （security review F-S-P2-101。「この経路を再び作らない」）。`--resolve` の子も
    同じ理由で `python -P -m jin_cli.resolver` である。`-P` を付けても `jin run` 自身の
    `extra_sys_path` の窓は効くので、`ref` は従来どおり cwd から解決される。
    """
    command = [
        sys.executable,
        "-P",
        "-m",
        "jin_cli.main",
        "run",
        str(target),
        request.prompt,
        "--trace",
        str(trace),
    ]
    if request.model is not None:
        command += ["--model", request.model]
    return command


def stream(
    target: Path,
    request: RunRequest,
    *,
    popen: Callable[..., subprocess.Popen[bytes]] | None = None,
    slot: RunSlot | None = None,
) -> Iterator[bytes]:
    """子を起こし、トレースを tail して SSE のフレームを次々に返す。

    **cwd と env は親から継承する**（この関数は何も渡さない）。`jin editor` を起動した人の
    `jin run` と `ref` の解決を一致させるためで、cwd を移すと解決先が CLI と変わる。

    hazard: stream -> subprocess.Popen
    """
    # **既定値を引数に書かない。** `tests/contract/test_guard_claims.py` は主張の
    # トークンが関数の**実コード**に式として在ることを AST で見る。デフォルト引数は
    # body ではないので、`popen=subprocess.Popen` と書くと `hazard:` が当たらない。
    spawn = subprocess.Popen if popen is None else popen
    workdir = Path(tempfile.mkdtemp(prefix="jin-editor-run-"))
    os.chmod(workdir, 0o700)
    trace = workdir / _TRACE_NAME
    stderr_path = workdir / _STDERR_NAME
    try:
        # stdout は捨てる（`jin run` が出すのは `_format_row` の人間向け行で、
        # トレースと同じ情報である）。stderr は**ファイル**へ出す。パイプにすると
        # 誰も読まない間に埋まって子がブロックする。
        with stderr_path.open("wb") as errors:
            try:
                process = spawn(
                    command_for(target, request, trace),
                    stdout=subprocess.DEVNULL,
                    stderr=errors,
                )
            except OSError as exc:
                yield sse("error", {"message": f"実行を起こせません: {exc}"})
                return
        if slot is not None:
            slot.attach(process)
        yield from _tail(trace, process)
        stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace")
        yield sse("done", {"exit": process.returncode, "stderr": stderr_text})
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _tail(trace: Path, process: subprocess.Popen[bytes]) -> Iterator[bytes]:
    """トレースが増えるたびに行を出す。子が終わるまで続ける。

    **終了の判定を読み取りより先に置く。** 逆にすると「読んだあと・終了を見る前」に
    書かれた行を取りこぼす。この順序なら、終了を見た回でもう一度読んでから抜ける。
    """
    handle = None
    pending = b""
    try:
        while True:
            finished = process.poll() is not None
            if handle is None and trace.exists():
                handle = trace.open("rb")
            if handle is not None:
                pending += handle.read()
                *complete, pending = pending.split(b"\n")
                for raw in complete:
                    text = raw.decode("utf-8", errors="replace").rstrip("\r")
                    if text != "":
                        yield sse_row(text)
            if finished:
                return
            time.sleep(POLL_SECONDS)
    finally:
        if handle is not None:
            handle.close()


__all__ = [
    "GRACE_SECONDS",
    "POLL_SECONDS",
    "RunRejected",
    "RunRequest",
    "RunSlot",
    "command_for",
    "parse_request",
    "sse",
    "sse_row",
    "stream",
]
