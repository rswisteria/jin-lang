# エディタからの実行 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `apps/editor` から `jin run` を起動し、トレースを逐次オーバーレイに反映する。

**Architecture:** `jin editor` の既存の静的 HTTP サーバに `POST /run` を足し、`jin run` を子プロセスで起こして一時ファイルのトレースを tail し、SSE でブラウザへ流す。LSP(ws) は 6 種のまま無改造で、ブラウザは受け取った行から `Replay` を組み立てて既存の `jin/renderSvg` 経路でオーバーレイを描く。

**Tech Stack:** Python 3（`http.server` / `subprocess` / `threading`）、TypeScript + React（`fetch` + `ReadableStream`）、pytest、vitest、Playwright

**Spec:** `docs/superpowers/specs/2026-09-08-editor-run-design.md`

## Global Constraints

- **`jin/…` を増やさない。** `tests/contract/test_editor_contract.py::test_the_debug_mode_does_not_add_a_new_lsp_request` が 6 種（`jin/model` / `jin/renderSvg` / `jin/ops` / `jin/applyOps` / `jin/open` / `jin/save`）で等号固定している。このテストは**変更しない**
- **エディタは 1 本の線も描かない。** SVG は `jin/renderSvg` から受け取る。`createElementNS(ns, "path" / "line" / "text" …)` は禁止
- **エディタは Python パッケージを直接 import しない。** 例外は `schemas/jin.schema.json` のみ（`apps/editor/eslint.config.js` の `no-restricted-imports` が落とす）
- **トークンはカスタムヘッダ `X-Jin-Token` で送る。** body や query に置くと simple request として他オリジンから撃たれる
- **CORS ヘッダを 1 つも返さない。** `OPTIONS` には 403 を返す
- **`jin-requirements.md` は変更しない。** 逸脱は `delivery/20260904-1445-jin/decision-conformance.md` に記録する
- **テストはネットワークと API キーを必要としない。** モデルは `--model fake`（FakeLlm）
- `apps/editor` の依存の版は完全一致で固定する（`^` / `~` を使わない）
- 新しい診断コード（JINxxx）は増やさない

---

### Task 1: トレースを 1 行ごとに flush する

`_LazyTruncateSink` は `os.fdopen(fd, "w")` のブロックバッファで書いており、`flush()` は切り詰めの 1 回だけである。このままでは tail しても実行完了まで 1 バイトも見えず、SSE がストリームにならない（spec §3.5）。

**Files:**
- Modify: `packages/jin-cli/src/jin_cli/main.py`（`_LazyTruncateSink.write`・772 行付近）
- Test: `packages/jin-cli/tests/test_cli.py`

**Interfaces:**
- Consumes: なし
- Produces: `_LazyTruncateSink.write` が書き込みのたびに OS へ渡す（外のプロセスから `close()` 前に読める）

- [ ] **Step 1: Write the failing test**

`packages/jin-cli/tests/test_cli.py` の末尾に足す。

```python
def test_trace_sink_makes_each_line_visible_before_close(tmp_path: Path) -> None:
    """書いた行が `close()` の前に**外から**読めること。

    `jin editor` の実行エンドポイントはこのファイルを tail して SSE に流す
    （`docs/superpowers/specs/2026-09-08-editor-run-design.md` §3.5）。
    バッファに溜まったままだと実行が終わるまで 1 行も出ず「ストリーム」にならない。
    """
    from jin_cli.main import _LazyTruncateSink, _open_trace

    target = tmp_path / "t.jsonl"
    sink = _LazyTruncateSink(_open_trace(target))
    try:
        sink.write('{"seq": 1, "kind": "text"}\n')
        assert target.read_text(encoding="utf-8") == '{"seq": 1, "kind": "text"}\n'
        sink.write('{"seq": 2, "kind": "text"}\n')
        assert target.read_text(encoding="utf-8").count("\n") == 2
    finally:
        sink.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/jin-cli/tests/test_cli.py -v -k trace_sink`

Expected: FAIL — `assert '' == '{"seq": 1, "kind": "text"}\n'`（バッファに溜まっていてファイルが空）

- [ ] **Step 3: Write minimal implementation**

`packages/jin-cli/src/jin_cli/main.py` の `_LazyTruncateSink.write` を差し替える。

```python
    def write(self, text: str) -> int:
        self._truncate()
        written = self._handle.write(text)
        # **1 行ごとに OS へ渡す。** 既定のブロックバッファのままだと `close()` するまで
        # トレースが外から 1 バイトも見えない。`jin editor` の実行エンドポイントは
        # このファイルを tail して SSE に流すので、溜まると「ストリーム」にならない
        # （`docs/superpowers/specs/2026-09-08-editor-run-design.md` §3.5）。
        # 代償は書き込みのたびの syscall だけで、トレースの**内容は変わらない**。
        self._handle.flush()
        return written
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/jin-cli -v`

Expected: PASS（新しいテストが通り、既存のトレース関連テストも緑のまま）

- [ ] **Step 5: Commit**

```
git add packages/jin-cli/src/jin_cli/main.py packages/jin-cli/tests/test_cli.py
git commit -m "fix(cli): トレースを 1 行ごとに flush して途中でも読めるようにする"
```

---

### Task 2: 実行の中身（子プロセスと tail と SSE）

HTTP を通さない純粋なロジックを 1 モジュールに閉じる。`editor.py` を膨らませない。

**Files:**
- Create: `packages/jin-cli/src/jin_cli/runserver.py`
- Create: `packages/jin-cli/tests/test_runserver.py`

**Interfaces:**
- Consumes: Task 1 の flush（tail が行を拾えること）
- Produces:
  - `RunRequest(prompt: str, model: str | None)` — frozen dataclass
  - `RunRejected(Exception)`
  - `parse_request(body: bytes) -> RunRequest`
  - `sse(event: str, payload: object) -> bytes`
  - `sse_row(line: str) -> bytes`
  - `command_for(target: Path, request: RunRequest, trace: Path) -> list[str]`
  - `stream(target: Path, request: RunRequest, *, popen: Callable[..., subprocess.Popen[bytes]] | None = None, slot: RunSlot | None = None) -> Iterator[bytes]`
  - `RunSlot` — `try_acquire() -> bool` / `attach(process) -> None` / `release() -> None` / `terminate() -> None`
  - `POLL_SECONDS: float` / `GRACE_SECONDS: float`

- [ ] **Step 1: 既存の stubs の載せ方を確かめる**

`examples/pipeline` の `ref` はリポジトリに実体が無く、`tests/fixtures/stubs` を `sys.path` / `PYTHONPATH` に載せる必要がある（CLAUDE.md）。**新しい方法を発明せず既存に揃える。**

Run: `grep -rn "stubs" packages/jin-cli/tests/ tests/conftest.py packages/jin-adk/tests/`

読んだ方法を Step 2 のテストで使う。

- [ ] **Step 2: Write the failing test**

`packages/jin-cli/tests/test_runserver.py` を新規に作る。`PIPELINE` を使うテストには Step 1 で確かめた stubs の載せ方を適用すること。

```python
"""`jin editor` の実行エンドポイントの中身（Issue #34）。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from jin_cli.runserver import (
    RunRejected,
    RunRequest,
    RunSlot,
    parse_request,
    sse,
    sse_row,
    stream,
)

PIPELINE = Path(__file__).resolve().parents[3] / "examples" / "pipeline" / "pipeline.jin"


def test_parse_request_reads_prompt_and_model() -> None:
    assert parse_request(b'{"prompt": "go", "model": "fake"}') == RunRequest(
        prompt="go", model="fake"
    )


def test_parse_request_allows_a_null_model() -> None:
    assert parse_request(b'{"prompt": "go", "model": null}').model is None
    assert parse_request(b'{"prompt": "go"}').model is None


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b'["prompt"]',
        b'{"model": "fake"}',
        b'{"prompt": ""}',
        b'{"prompt": 1}',
        b'{"prompt": "go", "model": "gemini-2.0-flash"}',
    ],
)
def test_parse_request_rejects_bad_bodies(body: bytes) -> None:
    """実モデル名を許さないのは `jin run` と同じ規律（実モデルは `.jin` の core が持つ）。"""
    with pytest.raises(RunRejected):
        parse_request(body)


def test_sse_puts_the_payload_on_one_line() -> None:
    """`data` に生の改行が入ると SSE の書式が壊れる。JSON にすればエスケープされる。"""
    frame = sse("done", {"exit": 0, "stderr": "1 行目\n2 行目\n"}).decode("utf-8")
    assert frame.startswith("event: done\ndata: ")
    assert frame.endswith("\n\n")
    body = frame.split("data: ", 1)[1].rstrip("\n")
    assert "\n" not in body
    assert json.loads(body) == {"exit": 0, "stderr": "1 行目\n2 行目\n"}


def test_sse_row_sends_the_jsonl_line_verbatim() -> None:
    """行は `jin_adk.trace` が `json.dumps` で書いたものなので、そのまま載せる。"""
    line = '{"seq": 1, "agent": "a", "kind": "text"}'
    assert sse_row(line).decode("utf-8") == f"event: row\ndata: {line}\n\n"


def test_stream_runs_the_file_and_emits_rows_then_done() -> None:
    text = b"".join(stream(PIPELINE, RunRequest(prompt="go", model="fake"))).decode("utf-8")
    assert text.count("event: row\n") >= 1, text
    assert text.count("event: done\n") == 1, text
    done = json.loads(text.rsplit("event: done\ndata: ", 1)[1].strip())
    assert done["exit"] == 0, done


def test_stream_reports_a_failure_without_hiding_it() -> None:
    """落ちても `done` は来る（ブラウザ側が図を消さないため）。理由は stderr に載る。"""
    missing = PIPELINE.parent / "does-not-exist.jin"
    text = b"".join(stream(missing, RunRequest(prompt="go", model="fake"))).decode("utf-8")
    assert "event: done\n" in text
    done = json.loads(text.rsplit("event: done\ndata: ", 1)[1].strip())
    assert done["exit"] != 0
    assert done["stderr"] != ""


def test_stream_emits_an_error_when_the_child_cannot_start() -> None:
    def refuse(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        raise OSError("no exec")

    text = b"".join(
        stream(PIPELINE, RunRequest(prompt="go", model="fake"), popen=refuse)
    ).decode("utf-8")
    assert "event: error\n" in text
    assert "event: done\n" not in text


def test_run_slot_admits_one_at_a_time() -> None:
    slot = RunSlot()
    assert slot.try_acquire() is True
    assert slot.try_acquire() is False
    slot.release()
    assert slot.try_acquire() is True
    slot.release()


def test_run_slot_terminates_the_child_it_holds() -> None:
    """`terminate()` が実際に子を終わらせること（Issue #32 と同じ規律の土台）。"""
    slot = RunSlot()
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
    try:
        slot.attach(child)
        slot.terminate()
        assert child.poll() is not None, "terminate() のあとも子が生きている"
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
```

テストの import に `import sys` を足すこと。

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest packages/jin-cli/tests/test_runserver.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'jin_cli.runserver'`

- [ ] **Step 4: Write minimal implementation**

`packages/jin-cli/src/jin_cli/runserver.py` を新規に作る。

```python
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
    """
    command = [
        sys.executable,
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest packages/jin-cli/tests/test_runserver.py -v`

Expected: PASS（9 件）

- [ ] **Step 6: Commit**

```
git add packages/jin-cli/src/jin_cli/runserver.py packages/jin-cli/tests/test_runserver.py
git commit -m "feat(cli): jin run を子プロセスで起こしてトレースを SSE に流す"
```

---

### Task 3: HTTP の口と 5 段の防御

`jin editor` の静的サーバに `POST /run` と `OPTIONS` を足す。

**Files:**
- Modify: `packages/jin-cli/src/jin_cli/editor.py`（`_StaticHandler` / `_handler_for` / `_static_server` / `serve`）
- Test: `packages/jin-cli/tests/test_editor.py`（無ければ新規）

**Interfaces:**
- Consumes: Task 2 の `RunRequest` / `RunRejected` / `RunSlot` / `parse_request` / `stream` / `sse`
- Produces:
  - `RunEndpoint` — `__init__(self, target: Path, token: str)`、属性 `origin: str | None`（`serve` が後から設定する）、`slot: RunSlot`
  - `RunEndpoint.authorize(origin: str | None, token: str | None) -> bool`
  - `_handler_for(root: Path, endpoint: RunEndpoint | None) -> Callable[..., SimpleHTTPRequestHandler]`
  - `_static_server(host: str, root: Path, endpoint: RunEndpoint | None) -> ThreadingHTTPServer`

- [ ] **Step 1: Write the failing test**

`packages/jin-cli/tests/test_editor.py` に足す（既存ファイルがあれば末尾へ）。

```python
"""`jin editor` の実行エンドポイント（Issue #34）。"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from jin_cli.editor import RunEndpoint, _static_server

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "pipeline" / "pipeline.jin"


@pytest.fixture()
def endpoint_server(tmp_path: Path):
    """静的サーバを 1 本立てて、URL と endpoint を返す。"""
    (tmp_path / "index.html").write_text("<p>dist</p>", encoding="utf-8")
    endpoint = RunEndpoint(target=EXAMPLE, token="secret-token")
    httpd = _static_server("127.0.0.1", tmp_path, endpoint)
    port = int(httpd.server_address[1])
    endpoint.origin = f"http://127.0.0.1:{port}"
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", endpoint
    finally:
        httpd.shutdown()
        httpd.server_close()


def _post(url: str, *, token: str | None, origin: str | None, body: bytes) -> int:
    """`POST /run` を撃って HTTP の状態番号だけ返す。"""
    request = urllib.request.Request(url + "/run", data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    if token is not None:
        request.add_header("X-Jin-Token", token)
    if origin is not None:
        request.add_header("Origin", origin)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
            return int(response.status)
    except urllib.error.HTTPError as error:
        return int(error.code)


def test_the_static_files_are_still_served(endpoint_server) -> None:
    url, _ = endpoint_server
    with urllib.request.urlopen(url + "/index.html", timeout=10) as response:
        assert b"dist" in response.read()


def test_run_without_the_token_is_refused(endpoint_server) -> None:
    url, _ = endpoint_server
    assert _post(url, token=None, origin=url, body=b'{"prompt": "go"}') == 403


def test_run_with_a_wrong_token_is_refused(endpoint_server) -> None:
    url, _ = endpoint_server
    assert _post(url, token="wrong", origin=url, body=b'{"prompt": "go"}') == 403


def test_run_from_another_origin_is_refused(endpoint_server) -> None:
    """`Origin` 検査。ws と違って HTTP はここを見られる。"""
    url, _ = endpoint_server
    assert (
        _post(url, token="secret-token", origin="http://evil.example", body=b'{"prompt": "go"}')
        == 403
    )


def test_options_is_refused_so_preflight_never_passes(endpoint_server) -> None:
    """CORS ヘッダを 1 つも返さない。preflight が通らなければ本要求は飛ばない。"""
    url, _ = endpoint_server
    request = urllib.request.Request(url + "/run", method="OPTIONS")
    request.add_header("Origin", "http://evil.example")
    request.add_header("Access-Control-Request-Method", "POST")
    request.add_header("Access-Control-Request-Headers", "x-jin-token")
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(request, timeout=10)
    assert caught.value.code == 403
    assert caught.value.headers.get("Access-Control-Allow-Origin") is None


def test_a_broken_body_is_refused(endpoint_server) -> None:
    url, _ = endpoint_server
    assert _post(url, token="secret-token", origin=url, body=b"not json") == 400


def test_a_real_model_name_is_refused(endpoint_server) -> None:
    url, _ = endpoint_server
    body = b'{"prompt": "go", "model": "gemini-2.0-flash"}'
    assert _post(url, token="secret-token", origin=url, body=body) == 400


def test_a_second_run_is_refused_while_one_is_going(endpoint_server) -> None:
    url, endpoint = endpoint_server
    assert endpoint.slot.try_acquire() is True
    try:
        assert _post(url, token="secret-token", origin=url, body=b'{"prompt": "go"}') == 409
    finally:
        endpoint.slot.release()


def test_run_streams_rows_and_finishes(endpoint_server) -> None:
    """正常系。`--model fake` で row が並び、最後に done が来る。"""
    url, _ = endpoint_server
    request = urllib.request.Request(
        url + "/run", data=b'{"prompt": "go", "model": "fake"}', method="POST"
    )
    request.add_header("Content-Type", "application/json")
    request.add_header("X-Jin-Token", "secret-token")
    request.add_header("Origin", url)
    with urllib.request.urlopen(request, timeout=120) as response:
        assert response.headers.get_content_type() == "text/event-stream"
        text = response.read().decode("utf-8")
    assert "event: row\n" in text
    assert text.count("event: done\n") == 1
    done = json.loads(text.rsplit("event: done\ndata: ", 1)[1].strip())
    assert done["exit"] == 0, done
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/jin-cli/tests/test_editor.py -v -k run`

Expected: FAIL — `ImportError: cannot import name 'RunEndpoint' from 'jin_cli.editor'`

- [ ] **Step 3: Write minimal implementation**

`packages/jin-cli/src/jin_cli/editor.py` を編集する。

import に足す:

```python
import secrets
from http import HTTPStatus

from jin_cli import runserver
from jin_cli.runserver import RunRejected, RunSlot
```

`EditorAddress` の下に `RunEndpoint` を足す:

```python
#: `POST /run` の body の上限（バイト）。prompt しか入らないので十分に小さくてよい。
MAX_RUN_BODY = 64 * 1024


class RunEndpoint:
    """`POST /run` が知っておくこと（Issue #34・spec §4）。

    **対象ファイルはここに固定する。** クライアントは実行するパスを指定できない。
    `origin` は待ち受けポートが決まってから `serve` が設定する（起動前は `None`）。
    """

    def __init__(self, target: Path, token: str) -> None:
        self.target = target
        self.token = token
        self.origin: str | None = None
        self.slot = RunSlot()

    def authorize(self, origin: str | None, token: str | None) -> bool:
        """`Origin` とトークンを見る。**どちらも合わなければ実行しない。**

        `Origin` が無い要求（curl など）は**通す**。ブラウザからの他オリジンの
        `fetch` には必ず `Origin` が付くので、ここで見るのは「別のページからの
        なりすまし」だけであり、端末から自分で叩く道を塞ぐ意味は無い。
        なりすましの本命の防御はカスタムヘッダ（トークン）が強制する
        preflight であり、`Origin` 検査はその上乗せである（spec §3.2）。

        guard: authorize -> secrets.compare_digest
        """
        if origin is not None and origin != self.origin:
            return False
        if token is None:
            return False
        return secrets.compare_digest(token.encode("utf-8"), self.token.encode("utf-8"))
```

`_StaticHandler` を差し替える（既存の docstring と `log_message` は残す）:

```python
class _StaticHandler(SimpleHTTPRequestHandler):
    """`HTTP/1.1` で応答する静的ハンドラ。

    （既存の docstring をそのまま残す）
    """

    protocol_version = "HTTP/1.1"

    def __init__(self, *args: object, endpoint: RunEndpoint | None = None, **kwargs: object) -> None:
        # **`super().__init__` の前に設定する。** `BaseHTTPRequestHandler.__init__` は
        # その場でリクエストを処理する（`handle()` を呼ぶ）ので、あとから代入しても間に合わない。
        self._endpoint = endpoint
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]

    def log_message(self, format: str, *args: object) -> None:
        """アクセスログを**捨てる**。（既存の docstring をそのまま残す）"""

    def do_OPTIONS(self) -> None:
        """preflight を**通さない**。

        CORS ヘッダを 1 つも返さないので、他オリジンのページは本要求へ進めない。
        トークンをカスタムヘッダで要求しているのはこのためである（spec §3.2）。
        """
        self.send_error(HTTPStatus.FORBIDDEN, "CORS preflight is not allowed")

    def do_POST(self) -> None:
        """`POST /run` だけを受ける（spec §4）。

        guard: do_POST -> endpoint.authorize
        """
        endpoint = self._endpoint
        if endpoint is None or self.path != "/run":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not endpoint.authorize(self.headers.get("Origin"), self.headers.get("X-Jin-Token")):
            self.send_error(HTTPStatus.FORBIDDEN, "token or origin mismatch")
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self.send_error(HTTPStatus.BAD_REQUEST, "bad Content-Length")
            return
        if length > MAX_RUN_BODY:
            self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        try:
            request = runserver.parse_request(self.rfile.read(length))
        except RunRejected as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        # **同時に走ってよいのは 1 本だけ。** 枠を取れなかったら 409 で断る。
        if not endpoint.slot.try_acquire():
            self.send_error(HTTPStatus.CONFLICT, "a run is already going")
            return
        try:
            self._stream_run(endpoint, request)
        finally:
            endpoint.slot.release()

    def _stream_run(self, endpoint: RunEndpoint, request: runserver.RunRequest) -> None:
        """SSE で流す。`Content-Length` を持てないので接続を閉じて区切る。"""
        self.close_connection = True
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for frame in runserver.stream(endpoint.target, request, slot=endpoint.slot):
                self.wfile.write(frame)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            # ブラウザが離れた。走っている子は道連れにする（残すと孤児になる）。
            endpoint.slot.terminate()
```

`_handler_for` と `_static_server` を差し替える:

```python
def _handler_for(root: Path, endpoint: RunEndpoint | None) -> Callable[..., SimpleHTTPRequestHandler]:
    """配信の根を `root` に固定したハンドラ。

    （既存の docstring をそのまま残す）
    """
    return partial(_StaticHandler, directory=str(root), endpoint=endpoint)


def _static_server(host: str, root: Path, endpoint: RunEndpoint | None = None) -> ThreadingHTTPServer:
    """`root` の中だけを配る HTTP サーバ。ポートは OS に選ばせて実値を読む。

    guard: _static_server -> _handler_for(root, endpoint)
    """
    return ThreadingHTTPServer((host, 0), _handler_for(root, endpoint))
```

**`guard:` のトークンを呼び出しに合わせて直すこと。** 既存は `guard: _static_server -> _handler_for(root)`
だが、引数が増えるので AST が一致しなくなり `tests/contract/test_guard_claims.py` が赤くなる
（トークンは名指しした関数の実コードに**式として**在る必要がある）。

`__all__` に `"MAX_RUN_BODY"` と `"RunEndpoint"` を足す。

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/jin-cli/tests/test_editor.py -v`

Expected: PASS（9 件）

- [ ] **Step 5: Commit**

```
git add packages/jin-cli/src/jin_cli/editor.py packages/jin-cli/tests/test_editor.py
git commit -m "feat(cli): jin editor に POST /run を足し 5 段の防御で閉じる"
```

---

### Task 4: `serve` に配線して終了時に子を残さない

Task 3 の `RunEndpoint` を `serve` から実際に使う。Issue #32 と同じ後始末を入れる。

**Files:**
- Modify: `packages/jin-cli/src/jin_cli/editor.py`（`serve`）
- Test: `packages/jin-cli/tests/test_editor.py`

**Interfaces:**
- Consumes: Task 3 の `RunEndpoint`、`_static_server(host, root, endpoint)`
- Produces: `serve` が `RunEndpoint` を組み立て、`finally` で `endpoint.slot.terminate()` を呼ぶ

- [ ] **Step 1: Write the failing test**

`packages/jin-cli/tests/test_editor.py` に足す。**`serve` の `finally` から `terminate()` を消すと赤くなる**形にする。

```python
def test_serve_terminates_the_run_slot_when_it_stops(tmp_path: Path, monkeypatch) -> None:
    """`serve` が終わるとき、走っている実行を残さない（Issue #32 と同じ規律）。"""
    from jin_cli import editor as editor_module

    (tmp_path / "index.html").write_text("<p>dist</p>", encoding="utf-8")
    target = tmp_path / "x.jin"
    # `create_server` を差し替えるので中身は読まれない（`prepare` は suffix と存在だけ見る）。
    target.write_text("{}", encoding="utf-8")

    terminated: list[bool] = []

    class _Stub:
        """`create_server` の代わり。`serve_ws` はすぐ返る（本物はブロックする）。"""

        def serve_ws(self, host: str, port: int) -> None:
            return None

    monkeypatch.setattr(editor_module, "create_server", lambda files: _Stub())
    monkeypatch.setattr(
        editor_module.RunSlot, "terminate", lambda self: terminated.append(True)
    )

    editor_module.serve(target, dist=tmp_path, open_browser=False)

    assert terminated == [True], "serve の finally が走っている実行を終わらせていない"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/jin-cli/tests/test_editor.py -v -k terminates`

Expected: FAIL — `AttributeError: module 'jin_cli.editor' has no attribute 'RunSlot'`（Task 3 の import がまだ入っていなければ）、または `assert [] == [True]`（`serve` が `terminate` を呼んでいない）

- [ ] **Step 3: Write minimal implementation**

`packages/jin-cli/src/jin_cli/editor.py` の `serve` を差し替える（既存の docstring と `hazard:` / `guard:` 行はそのまま残す）。

```python
    target, root = prepare(file, dist)

    # `jin/open` / `jin/save` が触れてよいのは**対象ファイルの親ディレクトリ**だけ。
    files = fileio.FileAccess.create(editor_root(target))
    server = create_server(files=files)

    # 実行の口（Issue #34）。**トークンは `jin/open` / `jin/save` と同じものを使う。**
    # 別に発行しても守るものは変わらず、URL のフラグメントに 2 つ載せる分だけ漏れ口が増える。
    endpoint = RunEndpoint(target=target, token=files.token)
    httpd = _static_server(host, root, endpoint)
    http_port = int(httpd.server_address[1])
    # `Origin` の期待値はポートが決まってからでないと書けない。
    endpoint.origin = f"http://{host}:{http_port}"
    ws_port = free_port(host)
    address = EditorAddress(
        http_port=http_port,
        ws_port=ws_port,
        url=build_url(http_port, ws_port, target, files.token, host),
    )
    thread = threading.Thread(target=httpd.serve_forever, name="jin-editor-http", daemon=True)
    thread.start()

    if announce is not None:
        announce(f"{TOKEN_PREFIX}{files.token}")
        announce(f"{URL_PREFIX}{address.url}")
    if open_browser:
        webbrowser.open(address.url)
    try:
        server.serve_ws(host, address.ws_port)
    finally:
        # **走っている実行を残さない**（Issue #32 と同じ規律）。静的サーバを止める前に
        # 子を終わらせる。順序が逆だと、SSE を書いているスレッドが閉じた socket へ
        # 書き込んで例外を出す。
        endpoint.slot.terminate()
        httpd.shutdown()
        httpd.server_close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/jin-cli -v`

Expected: PASS（既存の editor テストも緑のまま）

- [ ] **Step 5: Commit**

```
git add packages/jin-cli/src/jin_cli/editor.py packages/jin-cli/tests/test_editor.py
git commit -m "feat(cli): serve に実行の口を配線し終了時に子を残さない"
```

---

### Task 5: SSE を読むクライアント（TypeScript）

`EventSource` はカスタムヘッダを付けられないので、`fetch` + `ReadableStream` で自分で読む（spec §3.3）。

**Files:**
- Create: `apps/editor/src/run/client.ts`
- Create: `apps/editor/test/runClient.test.ts`

**Interfaces:**
- Consumes: Task 2 の SSE の書式（`event: row|done|error` + `data: <JSON 1 行>` + 空行）
- Produces:
  - `type RunEvent = { kind: "row"; row: TraceRow } | { kind: "done"; exit: number; stderr: string } | { kind: "error"; message: string }`
  - `class SseDecoder` — `push(chunk: string): RunEvent[]`
  - `async function* runAgent(options: RunOptions): AsyncGenerator<RunEvent>`
  - `interface RunOptions { origin: string; token: string; prompt: string; model: string | null; signal?: AbortSignal }`

- [ ] **Step 1: Write the failing test**

`apps/editor/test/runClient.test.ts` を新規に作る。

```ts
import { describe, expect, it } from "vitest";

import { SseDecoder } from "../src/run/client";

describe("SseDecoder", () => {
  it("1 つのフレームを読む", () => {
    const decoder = new SseDecoder();
    const events = decoder.push('event: row\ndata: {"seq":1,"kind":"text"}\n\n');
    expect(events).toEqual([{ kind: "row", row: { seq: 1, kind: "text" } }]);
  });

  it("chunk をまたいだフレームを落とさない", () => {
    // **ネットワークは行の途中で切れる。** 貯めずに捨てると行が消える。
    const decoder = new SseDecoder();
    expect(decoder.push("event: row\ndata: {\"seq\"")).toEqual([]);
    expect(decoder.push(":1}\n\n")).toEqual([{ kind: "row", row: { seq: 1 } }]);
  });

  it("1 つの chunk に複数フレームが入っていても全部返す", () => {
    const decoder = new SseDecoder();
    const events = decoder.push(
      'event: row\ndata: {"seq":1}\n\nevent: row\ndata: {"seq":2}\n\n',
    );
    expect(events).toHaveLength(2);
  });

  it("done は exit と stderr を持つ", () => {
    const decoder = new SseDecoder();
    const events = decoder.push('event: done\ndata: {"exit":1,"stderr":"だめでした\\n"}\n\n');
    expect(events).toEqual([{ kind: "done", exit: 1, stderr: "だめでした\n" }]);
  });

  it("error はメッセージを持つ", () => {
    const decoder = new SseDecoder();
    const events = decoder.push('event: error\ndata: {"message":"起こせません"}\n\n');
    expect(events).toEqual([{ kind: "error", message: "起こせません" }]);
  });

  it("行が JSON オブジェクトでないフレームは捨てる", () => {
    // `parse.ts` と同じ規律（オブジェクトでない行は行として扱わない）。
    const decoder = new SseDecoder();
    expect(decoder.push("event: row\ndata: 42\n\n")).toEqual([]);
    expect(decoder.push("event: row\ndata: not json\n\n")).toEqual([]);
  });

  it("CRLF で区切られていても読む", () => {
    const decoder = new SseDecoder();
    const events = decoder.push('event: row\r\ndata: {"seq":1}\r\n\r\n');
    expect(events).toEqual([{ kind: "row", row: { seq: 1 } }]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/editor && pnpm test -- runClient`

Expected: FAIL — `Failed to resolve import "../src/run/client"`

- [ ] **Step 3: Write minimal implementation**

`apps/editor/src/run/client.ts` を新規に作る。

```ts
import type { TraceRow } from "../trace/parse";

/**
 * `jin editor` の実行エンドポイント（Issue #34）を読む口。
 *
 * **`EventSource` は使わない。** カスタムヘッダを付けられないからである。トークンを
 * `X-Jin-Token` ヘッダで送るのは、それが CORS の preflight を強制して他オリジンの
 * ページからの実行を封じる唯一の手だてだからで（body や query だと simple request
 * として撃たれる）、受信方法はそれに従う
 * （`docs/superpowers/specs/2026-09-08-editor-run-design.md` §3.2 / §3.3）。
 *
 * **行の契約は書かない。** ここが見るのは SSE の枠（`event:` / `data:` / 空行）だけで、
 * `seq` と `pointer` の意味は `jin_render.overlay` が持つ（`trace/parse.ts` と同じ分担）。
 */
export type RunEvent =
  | { readonly kind: "row"; readonly row: TraceRow }
  | { readonly kind: "done"; readonly exit: number; readonly stderr: string }
  | { readonly kind: "error"; readonly message: string };

export interface RunOptions {
  /** 実行エンドポイントの origin。静的ページを配っているのと同じところ。 */
  readonly origin: string;
  readonly token: string;
  readonly prompt: string;
  /** `"fake"` か `null` だけ。実モデルは `.jin` の core が持つ（サーバが 400 で断る）。 */
  readonly model: string | null;
  readonly signal?: AbortSignal;
}

/**
 * SSE のフレームを組み立てる。**chunk をまたいだ分は貯める。**
 *
 * ネットワークは行の途中で切れる。貯めずに捨てるとトレースの行が黙って消える。
 */
export class SseDecoder {
  private pending = "";

  push(chunk: string): RunEvent[] {
    this.pending += chunk;
    const events: RunEvent[] = [];
    // フレームの区切りは空行。`\r\n` で書かれていても読めるようにする。
    const frames = this.pending.split(/\r?\n\r?\n/);
    this.pending = frames.pop() ?? "";
    for (const frame of frames) {
      const event = decodeFrame(frame);
      if (event !== null) events.push(event);
    }
    return events;
  }
}

function decodeFrame(frame: string): RunEvent | null {
  let name = "";
  let data = "";
  for (const line of frame.split(/\r?\n/)) {
    if (line.startsWith("event: ")) name = line.slice("event: ".length);
    else if (line.startsWith("data: ")) data = line.slice("data: ".length);
  }
  if (name === "" || data === "") return null;
  let payload: unknown;
  try {
    payload = JSON.parse(data);
  } catch {
    return null;
  }
  if (typeof payload !== "object" || payload === null || Array.isArray(payload)) return null;
  const record = payload as Record<string, unknown>;
  if (name === "row") return { kind: "row", row: record };
  if (name === "done") {
    return {
      kind: "done",
      exit: typeof record["exit"] === "number" ? record["exit"] : -1,
      stderr: typeof record["stderr"] === "string" ? record["stderr"] : "",
    };
  }
  if (name === "error") {
    return {
      kind: "error",
      message: typeof record["message"] === "string" ? record["message"] : "理由が分かりません",
    };
  }
  return null;
}

/**
 * 実行を頼み、届いた順にイベントを返す。
 *
 * **トークンはヘッダに置く**（`X-Jin-Token`）。body や query に置いてはいけない。
 */
export async function* runAgent(options: RunOptions): AsyncGenerator<RunEvent> {
  const response = await fetch(`${options.origin}/run`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Jin-Token": options.token,
    },
    body: JSON.stringify({ prompt: options.prompt, model: options.model }),
    signal: options.signal,
  });
  if (!response.ok || response.body === null) {
    yield { kind: "error", message: `実行を頼めません（HTTP ${response.status}）` };
    return;
  }
  const decoder = new SseDecoder();
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) return;
      for (const event of decoder.push(value)) yield event;
    }
  } finally {
    reader.releaseLock();
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/editor && pnpm test -- runClient`

Expected: PASS（7 件）

- [ ] **Step 5: Commit**

```
git add apps/editor/src/run/client.ts apps/editor/test/runClient.test.ts
git commit -m "feat(editor): 実行エンドポイントの SSE を読むクライアントを足す"
```

---

### Task 6: 実行 UI と配線

`DebugPanel` に prompt 入力と実行ボタンを足し、`App` が届いた行で `Replay` を伸ばす。

**Files:**
- Modify: `apps/editor/src/debug/DebugPanel.tsx`
- Modify: `apps/editor/src/App.tsx`
- Modify: `apps/editor/src/main.tsx`
- Modify: `apps/editor/src/style.css`
- Test: `apps/editor/test/trace.test.ts`

**Interfaces:**
- Consumes: Task 5 の `runAgent` / `RunEvent`、既存の `Replay`（`{ name, events, upto }`）と `TraceEvent`（`{ line, row }`）
- Produces:
  - `DebugPanelProps` に `running: boolean`、`runError: string | null`、`runSummary: string | null`、`onRun: (prompt: string, model: string | null) => void` を足す
  - `apps/editor/src/debug/replay.ts` に `appendRow(replay: Replay | null, row: TraceRow, name: string): Replay`

- [ ] **Step 1: Write the failing test**

`apps/editor/test/trace.test.ts` に足す。

```ts
import { appendRow } from "../src/debug/replay";

describe("appendRow", () => {
  it("行を足すと upto が最大まで伸びる", () => {
    // **実行中は常に最後まで見せる。** 伸ばさないと、届いているのに図が止まって見える。
    let replay = appendRow(null, { seq: 1, kind: "text" }, "実行");
    expect(replay.events).toHaveLength(1);
    expect(replay.upto).toBe(1);
    replay = appendRow(replay, { seq: 2, kind: "text" }, "実行");
    expect(replay.upto).toBe(2);
  });

  it("行番号は 1 から連番で振る", () => {
    // SSE には実ファイル行番号が無い。届いた順が JSONL の行順である。
    const first = appendRow(null, { seq: 1 }, "実行");
    const second = appendRow(first, { seq: 2 }, "実行");
    expect(second.events.map((event) => event.line)).toEqual([1, 2]);
  });

  it("seq が読めない行でも落とさない", () => {
    // `parse.ts` の規律と同じ。読めない行も一覧には出す（黙って消さない）。
    const replay = appendRow(null, { kind: "text" }, "実行");
    expect(replay.events).toHaveLength(1);
    expect(replay.upto).toBe(0);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/editor && pnpm test -- trace`

Expected: FAIL — `appendRow is not exported`

- [ ] **Step 3: Write minimal implementation（replay.ts）**

`apps/editor/src/debug/replay.ts` の末尾に足す。import に `TraceRow` を加える。

```ts
/**
 * 実行中に届いた 1 行を足す。**`upto` は常に最大に保つ**（届いた分まで図を進める）。
 *
 * SSE には実ファイル行番号が無いので、届いた順に 1 から振る。JSONL の行順と一致する。
 */
export function appendRow(current: Replay | null, row: TraceRow, name: string): Replay {
  const events = [...(current?.events ?? []), { line: (current?.events.length ?? 0) + 1, row }];
  return { name, events, upto: maxSeq(events) };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/editor && pnpm test -- trace`

Expected: PASS（3 件）

- [ ] **Step 5: DebugPanel に実行の面を足す**

`apps/editor/src/debug/DebugPanel.tsx` の `DebugPanelProps` に足す:

```ts
  /** 実行中か。ボタンを二度押しさせない（サーバも 409 で断るが、押せる見た目にしない）。 */
  readonly running: boolean;
  /** 実行を頼めなかった / 落ちた理由。**黙って捨てない**（NFR-FAIL-001）。 */
  readonly runError: string | null;
  /** 終わったときの一言（`jin run` の stderr の最後の行）。 */
  readonly runSummary: string | null;
  readonly onRun: (prompt: string, model: string | null) => void;
```

`useState` に prompt を足し、`<h2>` の直後（トレース読み込みの `<label>` の**上**）に置く:

```tsx
  const [prompt, setPrompt] = useState("");
```

```tsx
      <form
        className="jin-run"
        data-testid="jin-run-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (!props.running && prompt !== "") props.onRun(prompt, "fake");
        }}
      >
        <label className="jin-field">
          <span>実行（最初の利用者メッセージ）</span>
          <input
            type="text"
            data-testid="jin-run-prompt"
            value={prompt}
            disabled={props.running}
            onChange={(event) => setPrompt(event.target.value)}
          />
        </label>
        <button type="submit" data-testid="jin-run" disabled={props.running || prompt === ""}>
          {props.running ? "実行中…" : "fake モデルで実行"}
        </button>
      </form>

      {props.runError === null ? null : (
        <p className="jin-trace-error" data-testid="jin-run-error">
          {props.runError}
        </p>
      )}
      {props.runSummary === null ? null : (
        <p className="jin-hint" data-testid="jin-run-summary">
          {props.runSummary}
        </p>
      )}
```

`{replay === null ? (` の分岐の文言を、実行中は「実行中…」に見えるようにする必要はない（`running` はボタンに出ている）。

- [ ] **Step 6: App.tsx に配線する**

`App` の props に `runOrigin: string` と `token: string` を足す（`main.tsx` が渡す）。
`import { runAgent } from "./run/client";` と `import { appendRow, loadTrace, type Replay } from "./debug/replay";` にする。

状態を足す（**`ViewState` に混ぜない**・spec §7）:

```tsx
  // **実行状態は `ViewState` の外**（DP-COMMON-19 の 5 状態を増やさない）。
  // トレースと同じ理由で、実行の有無は「LSP との関係」と直交する。
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [runSummary, setRunSummary] = useState<string | null>(null);
```

実行のハンドラ:

```tsx
  const startRun = useCallback(
    async (prompt: string, model: string | null) => {
      setRunning(true);
      setRunError(null);
      setRunSummary(null);
      const name = `実行: ${prompt}`;
      let live: Replay | null = null;
      try {
        for await (const event of runAgent({ origin: runOrigin, token, prompt, model })) {
          if (event.kind === "row") {
            live = appendRow(live, event.row, name);
            setReplay(live);
            setTraceError(null);
            await refresh(focus, diagnostics, live);
          } else if (event.kind === "done") {
            // **exit が 0 でなくても図は消さない。** `.jin` は壊れていないので、
            // 理由だけ出して、届いた分のオーバーレイはそのまま残す。
            if (event.exit === 0) setRunSummary(lastLine(event.stderr));
            else setRunError(`実行が失敗しました（exit ${event.exit}）: ${lastLine(event.stderr)}`);
          } else {
            setRunError(event.message);
          }
        }
      } catch (error) {
        setRunError(`実行できません: ${messageOf(error)}`);
      } finally {
        setRunning(false);
      }
    },
    [runOrigin, token, focus, diagnostics, refresh],
  );
```

`DebugPanel` の呼び出しに props を足す:

```tsx
                  running={running}
                  runError={runError}
                  runSummary={runSummary}
                  onRun={(prompt, model) => void startRun(prompt, model)}
```

ファイル末尾に足す:

```tsx
/** stderr の**最後の中身のある行**。`jin run` は最後に「N イベント（session: …）」を出す。 */
function lastLine(text: string): string {
  const lines = text.split("\n").filter((line) => line.trim() !== "");
  return lines.length === 0 ? "" : lines[lines.length - 1];
}
```

`messageOf` は既に App.tsx にある（無ければ `replay.ts` と同じものを足す）。

- [ ] **Step 7: main.tsx で origin とトークンを渡す**

```tsx
        <App
          api={createJinApi(client, token)}
          uri={uri}
          schema={schema as JsonSchema}
          runOrigin={window.location.origin}
          token={token}
        />
```

実行エンドポイントは**このページを配っているのと同じ origin** である（`jin editor` の
静的サーバ）。別の場所を指せるようにしない。

- [ ] **Step 8: style.css に最小限の見た目を足す**

```css
.jin-run {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  margin-bottom: 0.75rem;
}
```

- [ ] **Step 9: 型検査とテストとリント**

Run: `cd apps/editor && pnpm build && pnpm lint && pnpm test`

Expected: すべて PASS。`pnpm build` は `tsc` を通す（`assertNever` の網羅性が壊れていないこと）。

- [ ] **Step 10: Commit**

```
git add apps/editor/src apps/editor/test
git commit -m "feat(editor): デバッグパネルから実行し届いた行でオーバーレイを進める"
```

---

### Task 7: e2e（実行してオーバーレイが出るまで）

**Files:**
- Create: `apps/editor/e2e/run.spec.ts`

**Interfaces:**
- Consumes: Task 3・4 の HTTP の口、Task 6 の `data-testid`（`jin-run-prompt` / `jin-run` / `jin-run-summary` / `jin-run-error`）、既存の `startEditor` / `expectServerGone` / `RunningEditor`（`apps/editor/e2e/editor.ts`）
- Produces: なし（最後のタスク）

**既存ヘルパの実物**（`apps/editor/e2e/editor.ts`。憶測で書かないこと）:

```ts
export interface RunningEditor {
  readonly url: string;
  readonly file: string;
  log(): string;
  stop(): Promise<boolean>;   // SIGTERM を送って終了を待ち、時間内に終わらなければ false
}
export async function startEditor(source: string): Promise<RunningEditor>;
export async function expectServerGone(url: string): Promise<void>;
```

**なぜ新しいファイルにするか**: 既存の `debug.spec.ts` は `beforeEach` で
`examples/pipeline/pipeline.jin` を起動する。あの陣は `ref`（`research.tools` など）を持ち、
実体がリポジトリに無いので**実行**には `PYTHONPATH=tests/fixtures/stubs` が要る（CLAUDE.md）。
e2e にその依存を持ち込まないため、`ref` を持たない陣で別ファイルを立てる。

- [ ] **Step 1: Write the failing test**

`apps/editor/e2e/run.spec.ts` を新規に作る。

```ts
import { expect, test } from "@playwright/test";

import { expectServerGone, type RunningEditor, startEditor } from "./editor";

/**
 * エディタからの実行（Issue #34 / 要件書 §7.2 のライブ実行）。
 *
 * **`ref` も `builtin` も持たない陣**を使う。`ref` は実体がリポジトリに無いので
 * `PYTHONPATH=tests/fixtures/stubs` が要り、`google_search` は Gemini 以外のモデルを
 * 拒んで `--model fake` が `ValueError` で落ちる（CLAUDE.md）。ここで見たいのは
 * 「実行してオーバーレイが出る」ことだけなので、余計な依存を持ち込まない。
 */
const SOURCE = `{
  "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
  "version": 1,
  "root": "Main",
  "circles": [
    {
      "name": "Main",
      "core": "gemini-2.5-flash",
      "instruction": {
        "rune": "こんにちは"
      }
    }
  ]
}
`;

let editor: RunningEditor;

test.beforeEach(async () => {
  editor = await startEditor(SOURCE);
});

// **取り残しをここで赤くする**（Issue #32）。実行の子プロセスが残る形もここで出る。
test.afterEach(async () => {
  const stopped = await editor?.stop();
  await expectServerGone(editor.url);
  expect(stopped).toBe(true);
});

// eslint-disable-next-line no-empty-pattern
test.afterEach(async ({}, testInfo) => {
  if (testInfo.status !== testInfo.expectedStatus) {
    await testInfo.attach("jin editor stderr", { body: editor.log(), contentType: "text/plain" });
  }
});

test("エディタから実行するとオーバーレイが出る", async ({ page }) => {
  await page.goto(editor.url);

  await page.getByTestId("jin-run-prompt").fill("go");
  await page.getByTestId("jin-run").click();

  // `jin run` は最後に「N イベント（session: …）」を stderr に出す。
  await expect(page.getByTestId("jin-run-summary")).toContainText("イベント", {
    timeout: 120_000,
  });
  await expect(page.getByTestId("jin-run-error")).toHaveCount(0);

  // **オーバーレイが実際に出ていること。** `data-jin-fired` を書くのは `jin_render` 1 本で、
  // エディタは 1 つも書かない（`tests/contract/test_editor_contract.py`）。
  await expect(page.locator("[data-jin-fired]").first()).toBeVisible();

  // 行の一覧にも届いていること。
  await expect(page.getByTestId("jin-trace-row").first()).toBeVisible();
});

test("実行中は二度押しできない", async ({ page }) => {
  await page.goto(editor.url);
  await page.getByTestId("jin-run-prompt").fill("go");
  await page.getByTestId("jin-run").click();

  // サーバも 409 で断るが、押せる見た目にしない。
  await expect(page.getByTestId("jin-run")).toBeDisabled();

  // この回は実行中に `afterEach` の `stop()` が走る。走っている子ごと終わること
  // （`expectServerGone` がポートの解放を見る）が Issue #32 と同じ規律の検査になる。
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/editor && pnpm build && pnpm e2e -- --grep "エディタから実行"`

Expected: FAIL — `getByTestId("jin-run-prompt")` が見つからない（Task 6 が入っていない場合）。
**`pnpm build` を先に走らせること**。`jin editor` は `apps/editor/dist` を配るので、
ビルドしないと古い画面が出て、直したはずの UI が出てこない。

- [ ] **Step 3: 通す**

Run: `cd apps/editor && pnpm build && pnpm e2e`

Expected: 既存の `smoke.spec.ts` / `debug.spec.ts` も含めて全部 PASS

- [ ] **Step 4: Commit**

```
git add apps/editor/e2e/run.spec.ts
git commit -m "test(editor): 実行してオーバーレイが出るまでを e2e で押さえる"
```

---

### Task 8: 仕様書と逸脱の記録

**Files:**
- Modify: `docs/spec/ops.md`（§5.1）
- Modify: `delivery/20260904-1445-jin/decision-conformance.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: Task 1〜7 で実装した防御
- Produces: なし

- [ ] **Step 1: `docs/spec/ops.md` §5.1 に実行の口を書く**

既存の 4 段（`jin/open` / `jin/save`）の記述の**後ろ**に節を足す。既存の書き方に合わせること。

内容:

- `jin editor` は `POST /run` を開く。**`jin lsp --ws` は開かない**（実行の口は LSP に無い）
- 防御は 5 段:
  1. `Origin` 検査（自分以外を拒む。`Origin` の無い要求は通す — 端末から自分で叩く道は塞がない）
  2. カスタムヘッダ `X-Jin-Token` のトークン一致（`secrets.compare_digest`）。**カスタムヘッダは CORS の preflight を強制する**ので、他オリジンのページからは撃てない。body や query に置くと simple request として撃たれる
  3. 実行対象は `jin editor` に渡されたファイルに固定（クライアントはパスを指定できない）
  4. 同時 1 本（2 本目は 409）
  5. 終了時に走っている子を必ず終わらせる
- **残存**:
  - **S1（任意コード実行）は残る。** 子は同じ権限で走り `ref` を import する。`--model fake` でも import は行う
  - トークンを握った攻撃者は、これまで `jin/save` で悪意ある `ref` を**書き込む**ところまでだったが、実行の口が開くことで**連鎖が攻撃者だけで完結する**。それでも常時有効にしているのは「`jin editor` に `.jin` を渡す時点でそのディレクトリを信頼している」という前提に立つ判断である（人間確定）
  - キャンセルを持たないので、実モデルでの長い実行はハンドラのスレッドを 1 本占有し続ける

- [ ] **Step 2: `decision-conformance.md` に逸脱を 1 節書く**

§2.25.6（hover）と同じ形式で、要件書 §7.2 からの逸脱を 2 点書く。

1. **v1.1 と書かれたものを v1 で実装した。** 要件書 §7.2 の最終行は「ライブ実行(WebSocket で `jin run` からストリーム)は v1.1」、§11 の Phase 7 も「任意」としている。Issue #34 として起票し人間が着手を判断した
2. **機構が WebSocket ではなく HTTP である。** ws には same-origin 制限が無く、防御がトークン一致だけになる。HTTP ならカスタムヘッダが CORS の preflight を強制するので他オリジンから撃てない。`jin run` は `ref` の import で任意コード実行なので、ここは一段強い防御を取った。あわせて `jin/…` を増やさずに済み、`test_the_debug_mode_does_not_add_a_new_lsp_request` の 6 種の等号が無傷のまま残る

**要件書本文は変更しない**（`tests/spec/test_spec_consistency.py` が写しとの一致を担保しており、上位要件書の変更は人間の承認領域である）。

- [ ] **Step 3: `CLAUDE.md` を直す**

2 か所:

1. Phase 表の Phase 6 が「未着手」のままなので「実装済み」に直す（実装は `main` に入っている）
2. 「`apps/editor` は LSP プロトコルにのみ依存し、Python パッケージを直接 import しない」に例外を明記する。**import の禁止は変わらない**が、実行だけは**同一オリジンの HTTP**（`jin editor` が配るのと同じサーバの `POST /run`）を使う。`jin lsp --ws` にこの口は無い
3. 「`--resolve` と `jin run` の危険性」の節に、`jin editor` の実行の口を 1 段落足す

- [ ] **Step 4: 全ゲートを通す**

Run:

```
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run lint-imports
cd apps/editor && pnpm build && pnpm lint && pnpm test && pnpm e2e
```

Expected: すべて緑。とくに:

- `tests/contract/test_editor_contract.py::test_the_debug_mode_does_not_add_a_new_lsp_request`（6 種の等号が無傷）
- `tests/contract/test_guard_claims.py`。**期待集合は直さなくてよい**（ファイルは部分集合、パッケージ名は等号で見ており `jin-cli` は既にある）。落ちるとすれば主張の**照合**の方である: トークンは名指しした関数の実コードに**式として**在る必要があり、デフォルト引数や docstring は body ではないので当たらない。裸の名前（`os` / `path`）もトークンにできない
- `uv run lint-imports`（`jin_cli` から `jin_adk` を新たに import していないこと。`runserver.py` は子プロセスを起こすだけで `jin_adk` を import しない）

- [ ] **Step 5: Commit**

```
git add docs/spec/ops.md delivery CLAUDE.md
git commit -m "docs: エディタからの実行の防御と要件書 §7.2 からの逸脱を記録する"
```

---

## 完了の確認

- [ ] `uv run pytest` が緑
- [ ] `cd apps/editor && pnpm build && pnpm lint && pnpm test && pnpm e2e` が緑
- [ ] `uv run lint-imports` が緑
- [ ] `uv run ruff check . && uv run ruff format --check .` が緑
- [ ] `jin/…` が 6 種のまま（契約テストを**変更していない**こと）
- [ ] `jin-requirements.md` を変更していないこと
- [ ] 手で 1 回動かす: `cd apps/editor && pnpm build` のあと `uv run jin editor examples/showcase/showcase.jin --no-browser` → 出た URL を開く → prompt を入れて実行 → オーバーレイが進む
