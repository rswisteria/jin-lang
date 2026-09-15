"""パッケージ横断契約: Lua 経路と wasm-GC 経路のパリティ（jil.md §6.7・Issue #53）。

同じ `.jin` と同じ seed / ticks / 入力ログで `jin run --target lua` と `jin run --target wasm-gc` を**実プロセス**で
走らせ、出力を突き合わせる。Sub-Issue A（#73）は fib の公開 state（標準出力）、B（#74）は release の
`--frames`、C（#75）は `examples-v2/` 3 本と `tests/fixtures/v2-programs/` 14 本の全部について debug の
`--trace` + `--frames` のバイト一致（Issue #53 の完了条件）と、`tests/fixtures/traces/paddle-v2.jsonl` の全行一致。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from jin_wasm.jinrec import dumps_jinrec

REPO_ROOT = Path(__file__).resolve().parents[2]
PROGRAMS = REPO_ROOT / "tests" / "fixtures" / "v2-programs"
EXAMPLES = REPO_ROOT / "examples-v2"
COMMITTED_TRACE = REPO_ROOT / "tests" / "fixtures" / "traces" / "paddle-v2.jsonl"

#: A の対象（公開 state の標準出力）。
PUBLIC_STATE_PARITY = [EXAMPLES / "fib" / "fib.jin"]

#: 入力ログ（`.jinrec` を書いて `--input` で渡す）。無いものは空。
EVENTS: dict[str, list[dict]] = {
    "key_pointer": [
        {"tick": 1, "kind": "key", "name": "ArrowLeft", "down": True},
        {"tick": 1, "kind": "key", "name": "Space", "down": True},
        {"tick": 2, "kind": "pointer", "x": 50, "y": 9, "down": True},
        {"tick": 2, "kind": "key", "name": "Space", "down": False},
        {"tick": 3, "kind": "key", "name": "ArrowLeft", "down": False},
    ],
    "text_input": [
        {"tick": 0, "kind": "text", "text": "ab"},
        {"tick": 0, "kind": "key", "name": "Backspace", "down": True},
        {"tick": 0, "kind": "text", "text": "c"},
        {"tick": 1, "kind": "key", "name": "Backspace", "down": False},
        {"tick": 2, "kind": "text", "text": "日本😀"},
    ],
    # v1 の陣の答えは録画の reply 行が正（両経路とも v1 を呼ばない・runtime.md §11）
    "agent": [{"tick": 2, "kind": "reply", "id": 1, "text": "canned answer"}],
    "paddle": [
        {"tick": 3, "kind": "key", "name": "ArrowLeft", "down": True},
        {"tick": 20, "kind": "key", "name": "ArrowLeft", "down": False},
        {"tick": 35, "kind": "key", "name": "ArrowRight", "down": True},
    ],
    "clicker": [
        {"tick": 5, "kind": "pointer", "x": 30, "y": 70, "down": True},
        {"tick": 6, "kind": "pointer", "x": 30, "y": 70, "down": False},
        {"tick": 70, "kind": "pointer", "x": 140, "y": 70, "down": True},
        {"tick": 71, "kind": "pointer", "x": 140, "y": 70, "down": False},
    ],
}

#: 走らせる tick 数（既定 5。核が wait で待つものは長め）
TICKS = {"paddle": 40, "clicker": 80, "wait_until": 6, "transfer": 6}

#: 両経路とも実行時エラー（exit 1・stderr の「実行時エラー」の行が同じ）
RUNTIME_ERRORS = {"bad_color", "runtime_error_index"}

ALL_PROGRAMS = sorted(p.stem for p in PROGRAMS.glob("*.jin")) + ["fib", "paddle", "clicker"]


def fixture_path(name: str) -> Path:
    return (
        (EXAMPLES / name / f"{name}.jin")
        if (EXAMPLES / name).is_dir()
        else PROGRAMS / f"{name}.jin"
    )


def run(target: str, path: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-P", "-m", "jin_cli.main", "run", str(path), "--target", target, *extra],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )


@pytest.mark.parametrize("path", PUBLIC_STATE_PARITY, ids=lambda p: p.stem)
def test_the_public_state_matches_between_lua_and_wasm_gc(path: Path) -> None:
    lua = run("lua", path, "--ticks", "60")
    wasm = run("wasm-gc", path, "--ticks", "60")
    assert lua.returncode == 0, lua.stderr
    assert wasm.returncode == 0, wasm.stderr
    assert wasm.stdout == lua.stdout
    # stderr は注記（agent / --storage）で増え得るので、走らせた tick の行だけを見る
    assert "tick 走らせました" in lua.stderr and "tick 走らせました" in wasm.stderr


def both_targets(name: str, tmp_path: Path, *, debug: bool) -> dict[str, tuple]:
    """両経路を同じ seed / ticks / 入力ログ / 記憶で走らせ、(結果, frames, trace, memory) を返す。"""
    path = fixture_path(name)
    events = EVENTS.get(name, [])
    ticks = TICKS.get(name, 5)
    outputs: dict[str, tuple] = {}
    for target in ("lua", "wasm-gc"):
        frames = tmp_path / f"{target}.frames.jsonl"
        trace = tmp_path / f"{target}.trace.jsonl"
        memory = tmp_path / f"{target}.memory.json"
        extra = ["--ticks", str(ticks), "--seed", "7", "--frames", str(frames)]
        if debug:
            extra += ["--trace", str(trace)]
        if events:
            recording = tmp_path / f"{target}.jinrec"
            header = {"file": path.name, "seed": 7, "fps": 60, "ticks": ticks}
            recording.write_text(dumps_jinrec(header, events), encoding="utf-8")
            extra += ["--input", str(recording)]
        if name == "storage":
            memory.write_text(json.dumps({"runs": "2", "label": "old"}), encoding="utf-8")
            extra += ["--storage", str(memory)]
        result = run(target, path, *extra)
        outputs[target] = (
            result,
            frames.read_bytes(),
            trace.read_bytes() if debug else b"",
            memory.read_bytes() if name == "storage" else b"",
        )
    return outputs


@pytest.mark.parametrize("name", ALL_PROGRAMS)
@pytest.mark.parametrize("debug", [False, True], ids=["release", "debug"])
def test_the_frames_and_traces_match_byte_for_byte(name: str, debug: bool, tmp_path: Path) -> None:
    """B（release の frames）と C（debug の trace + frames）の完了条件。"""
    outputs = both_targets(name, tmp_path, debug=debug)
    lua, wasm = outputs["lua"], outputs["wasm-gc"]
    expected_code = 1 if name in RUNTIME_ERRORS else 0
    assert lua[0].returncode == expected_code, lua[0].stderr
    assert wasm[0].returncode == expected_code, wasm[0].stderr
    assert wasm[1] == lua[1], "frames がバイト一致しない"
    assert wasm[1].count(b"\n") >= 1
    if debug:
        assert wasm[2] == lua[2], "trace がバイト一致しない"
        assert wasm[2].count(b"\n") >= 2
    assert wasm[0].stdout == lua[0].stdout
    errors_lua = [line for line in lua[0].stderr.splitlines() if "実行時エラー" in line]
    errors_wasm = [line for line in wasm[0].stderr.splitlines() if "実行時エラー" in line]
    assert errors_wasm == errors_lua
    assert bool(errors_lua) == (name in RUNTIME_ERRORS)
    if name == "storage":
        assert wasm[3] == lua[3]
        assert json.loads(lua[3]) == {"runs": "3", "best": "3", "label": "run 3"}


def test_the_committed_paddle_trace_matches_the_wasm_gc_run(tmp_path: Path) -> None:
    """`tests/fixtures/traces/paddle-v2.jsonl`（38 行・Lua 経路の実行結果）が wasm-GC 経路の出力と全行一致する。"""
    trace = tmp_path / "wasm.jsonl"
    result = run(
        "wasm-gc",
        EXAMPLES / "paddle" / "paddle.jin",
        "--ticks",
        "3",
        "--debug",
        "--trace",
        str(trace),
    )
    assert result.returncode == 0, result.stderr
    committed = COMMITTED_TRACE.read_text(encoding="utf-8")
    assert trace.read_text(encoding="utf-8") == committed
    assert committed.count("\n") == 38
