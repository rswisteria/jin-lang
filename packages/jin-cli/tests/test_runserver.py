"""`jin editor` の実行エンドポイントの中身（Issue #34）。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from jin_cli.runserver import (
    RunRejected,
    RunRequest,
    RunSlot,
    command_for,
    parse_request,
    sse,
    sse_row,
    stream,
)

#: `ref` も `builtin` も持たない最小の陣。**子プロセスで実行する**ので、
#: `conftest.py` の `sys.path` 細工は届かない（届くのは `PYTHONPATH` だけ）。
#: `examples/pipeline` を使うとその env の細工がテストに要る。
SOLO = """{
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
"""


@pytest.fixture
def solo(tmp_path: Path) -> Path:
    target = tmp_path / "solo.jin"
    target.write_text(SOLO, encoding="utf-8")
    return target


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


def test_stream_runs_the_file_and_emits_rows_then_done(solo: Path) -> None:
    text = b"".join(stream(solo, RunRequest(prompt="go", model="fake"))).decode("utf-8")
    assert text.count("event: row\n") >= 1, text
    assert text.count("event: done\n") == 1, text
    done = json.loads(text.rsplit("event: done\ndata: ", 1)[1].strip())
    assert done["exit"] == 0, done


def test_stream_reports_a_failure_without_hiding_it(solo: Path) -> None:
    """落ちても `done` は来る（ブラウザ側が図を消さないため）。理由は stderr に載る。"""
    missing = solo.parent / "does-not-exist.jin"
    text = b"".join(stream(missing, RunRequest(prompt="go", model="fake"))).decode("utf-8")
    assert "event: done\n" in text
    done = json.loads(text.rsplit("event: done\ndata: ", 1)[1].strip())
    assert done["exit"] != 0
    assert done["stderr"] != ""


def test_stream_emits_an_error_when_the_child_cannot_start(solo: Path) -> None:
    def refuse(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        raise OSError("no exec")

    text = b"".join(stream(solo, RunRequest(prompt="go", model="fake"), popen=refuse)).decode(
        "utf-8"
    )
    assert "event: error\n" in text
    assert "event: done\n" not in text


def test_the_child_does_not_get_cwd_on_its_path() -> None:
    """`-P` を落とさない（F-S-P2-101 の再発防止）。

    `python -m` は既定で cwd を `sys.path[0]` に置き、それが**子の一生の間**続く。
    CLAUDE.md の「Runner 実行中は cwd が `sys.path` に無い」が崩れ、ADK が遅延 import する
    未インストールの任意依存を cwd から解決させる経路が復活する。
    """
    command = command_for(Path("x.jin"), RunRequest(prompt="go", model="fake"), Path("t.jsonl"))
    assert "-P" in command
    assert command.index("-P") < command.index("-m")


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
