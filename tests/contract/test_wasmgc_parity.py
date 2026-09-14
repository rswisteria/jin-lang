"""パッケージ横断契約: Lua 経路と wasm-GC 経路のパリティ（jil.md §6.7・Issue #53）。

同じ `.jin` と同じ seed / ticks で `jin run --target lua` と `jin run --target wasm-gc` を**実プロセス**で
走らせ、出力を突き合わせる。Sub-Issue A（#73）は fib の公開 state（標準出力）だけ。B（#74）が release の
`--frames`、C（#75）が debug の `--trace` + `--frames` を、v2-programs 14 本 + examples-v2 3 本に広げる。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: A の対象。B / C で `examples-v2/` 3 本と `tests/fixtures/v2-programs/` 14 本の全部に広げる。
PUBLIC_STATE_PARITY = [REPO_ROOT / "examples-v2" / "fib" / "fib.jin"]


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
