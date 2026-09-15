"""パッケージ横断契約: Lua 経路と wasm-GC 経路のパリティ（jil.md §6.7・Issue #53）。

同じ `.jin` と同じ seed / ticks / 入力ログで `jin run --target lua` と `jin run --target wasm-gc` を**実プロセス**で
走らせ、出力を突き合わせる。Sub-Issue A（#73）は fib の公開 state（標準出力）、B（#74）は release の
`--frames`（`key_pointer` / `storage` / `text_input` / `each_list` / `bad_color` / `runtime_error_index`）、
C（#75）が debug の `--trace` + `--frames` を v2-programs 14 本 + examples-v2 3 本に広げる。
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

#: A の対象。C で `examples-v2/` 3 本と `tests/fixtures/v2-programs/` 14 本の全部に広げる。
PUBLIC_STATE_PARITY = [REPO_ROOT / "examples-v2" / "fib" / "fib.jin"]

#: B の対象（release の `--frames`）。入力ログが要るものは `.jinrec` を書いて `--input` で渡す。
RELEASE_FRAMES_PARITY = {
    "key_pointer": [
        {"tick": 1, "kind": "key", "name": "ArrowLeft", "down": True},
        {"tick": 1, "kind": "key", "name": "Space", "down": True},
        {"tick": 2, "kind": "pointer", "x": 50, "y": 9, "down": True},
        {"tick": 2, "kind": "key", "name": "Space", "down": False},
        {"tick": 3, "kind": "key", "name": "ArrowLeft", "down": False},
    ],
    "storage": [],
    "text_input": [
        {"tick": 0, "kind": "text", "text": "ab"},
        {"tick": 0, "kind": "key", "name": "Backspace", "down": True},
        {"tick": 0, "kind": "text", "text": "c"},
        {"tick": 1, "kind": "key", "name": "Backspace", "down": False},
        {"tick": 2, "kind": "text", "text": "日本😀"},
    ],
    "each_list": [],
    "bad_color": [],
    "runtime_error_index": [],
}

#: 両経路とも実行時エラー（exit 1・stderr の「実行時エラー」の行が同じ）
RUNTIME_ERRORS = {"bad_color", "runtime_error_index"}


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


@pytest.mark.parametrize("name", sorted(RELEASE_FRAMES_PARITY))
def test_the_release_frames_match_byte_for_byte(name: str, tmp_path: Path) -> None:
    path = PROGRAMS / f"{name}.jin"
    events = RELEASE_FRAMES_PARITY[name]
    outputs: dict[str, tuple[subprocess.CompletedProcess[str], bytes]] = {}
    for target in ("lua", "wasm-gc"):
        frames = tmp_path / f"{target}.frames.jsonl"
        extra = ["--ticks", "5", "--seed", "7", "--frames", str(frames)]
        if events:
            recording = tmp_path / f"{target}.jinrec"
            header = {"file": path.name, "seed": 7, "fps": 60, "ticks": 5}
            recording.write_text(dumps_jinrec(header, events), encoding="utf-8")
            extra += ["--input", str(recording)]
        if name == "storage":
            memory = tmp_path / f"{target}.memory.json"
            memory.write_text(json.dumps({"runs": "2", "label": "old"}), encoding="utf-8")
            extra += ["--storage", str(memory)]
        result = run(target, path, *extra)
        outputs[target] = (result, frames.read_bytes())
        if name == "storage":
            outputs[target + ".memory"] = (result, memory.read_bytes())
    lua, wasm = outputs["lua"], outputs["wasm-gc"]
    expected_code = 1 if name in RUNTIME_ERRORS else 0
    assert lua[0].returncode == expected_code, lua[0].stderr
    assert wasm[0].returncode == expected_code, wasm[0].stderr
    assert wasm[1] == lua[1], "frames がバイト一致しない"
    assert wasm[1].count(b"\n") >= 1
    assert wasm[0].stdout == lua[0].stdout
    errors_lua = [line for line in lua[0].stderr.splitlines() if "実行時エラー" in line]
    errors_wasm = [line for line in wasm[0].stderr.splitlines() if "実行時エラー" in line]
    assert errors_wasm == errors_lua
    assert bool(errors_lua) == (name in RUNTIME_ERRORS)
    if name == "storage":
        assert outputs["wasm-gc.memory"][1] == outputs["lua.memory"][1]
        assert json.loads(outputs["lua.memory"][1]) == {"runs": "3", "best": "3", "label": "run 3"}
