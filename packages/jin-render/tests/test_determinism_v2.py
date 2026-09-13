"""v2 の決定性（NFR-DET-001。v1 の `test_determinism.py` と同じ 2 段）。"""

from __future__ import annotations

import subprocess
import sys

import pytest
from jin_render import render

from .conftest import EXAMPLES_V2, TRACE_FIXTURE_V2, load_model_v2
from .test_determinism import _src_path

_SCRIPT = (
    "import json, sys;"
    "from pathlib import Path;"
    "from jin_core.check import check_file;"
    "from jin_render import render;"
    "m = check_file(Path(sys.argv[1])).model;"
    'rows = [json.loads(l) for l in Path(sys.argv[2]).read_text().split("\\n") if l];'
    "sys.stdout.buffer.write(render(m, focus=sys.argv[3], trace=rows, upto=12).encode('utf-8'))"
)


@pytest.mark.parametrize("focus", [None, "Play", "Play/step"])
def test_two_renders_in_one_process_are_byte_identical(focus: str | None) -> None:
    model = load_model_v2(EXAMPLES_V2 / "paddle" / "paddle.jin")
    assert render(model, focus=focus).encode("utf-8") == render(model, focus=focus).encode("utf-8")


@pytest.mark.parametrize("focus", ["Play", "Play/step"])
def test_two_processes_with_different_hash_seeds_agree(focus: str) -> None:
    outputs = []
    for seed in ("0", "4242"):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                _SCRIPT,
                str(EXAMPLES_V2 / "paddle" / "paddle.jin"),
                str(TRACE_FIXTURE_V2),
                focus,
            ],
            capture_output=True,
            env={"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": seed, "PYTHONPATH": _src_path()},
            check=False,
        )
        assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
        outputs.append(result.stdout)
    assert outputs[0] == outputs[1]
    assert b"data-jin-fired" in outputs[0]
