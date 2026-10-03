"""紋 57 字・構造の印 21 字・始まりの印の線の字形(`jin_render.v2.glyph_paths`)。

字形の正本はこのデータで、`docs/spec/v2/glyphs/*.svg` は `scripts/generate_glyph_svgs.py` の生成物。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from jin_core.v2.glyph import GLYPH_IDS, START_MARK, STRUCT_MARKS
from jin_render.v2.glyph_paths import GLYPH_PATHS, glyph_d

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_every_glyph_struct_mark_and_the_start_mark_has_a_path() -> None:
    assert set(GLYPH_PATHS) == GLYPH_IDS | {m.id for m in STRUCT_MARKS} | {START_MARK}


def test_paths_use_only_move_line_curve_and_close_within_the_cell() -> None:
    for gid, commands in GLYPH_PATHS.items():
        assert commands, gid
        assert commands[0][0] == "M", gid
        for op, nums in commands:
            assert op in "MLCZ", (gid, op)
            assert len(nums) == {"M": 2, "L": 2, "C": 6, "Z": 0}[op], (gid, op)
            assert all(0.0 <= v <= 100.0 for v in nums), (gid, nums)


def test_glyph_d_writes_three_decimals_through_fmt_coord() -> None:
    d = glyph_d("eq", 0.0, 0.0, 100.0)
    assert "M18.000 38.000 L82.000 38.000 M18.000 62.000 L82.000 62.000" in d
    for gid in GLYPH_PATHS:
        for num in re.findall(r"-?\d+(?:\.\d+)?", glyph_d(gid, 1.5, 2.25, 12.0)):
            assert re.fullmatch(r"-?\d+\.\d{3}", num), (gid, num)


def test_glyph_d_scales_into_the_cell() -> None:
    assert glyph_d("eq", 10.0, 20.0, 10.0).startswith("M11.800 23.800 L18.200 23.800")


def test_struct_marks_have_the_double_frame_no_other_glyph_has() -> None:
    # spec §1.1: 構造の印は二重の正方形の枠の中に記号。式紋・判別の紋と形で見分けられる
    outer = [
        ("M", (8.0, 8.0)),
        ("L", (92.0, 8.0)),
        ("L", (92.0, 92.0)),
        ("L", (8.0, 92.0)),
        ("Z", ()),
    ]
    for m in STRUCT_MARKS:
        assert list(GLYPH_PATHS[m.id][:5]) == outer, m.id
    for gid in GLYPH_IDS:
        assert list(GLYPH_PATHS[gid][:5]) != outer, gid


def test_the_svg_files_are_generated_from_the_data() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts/generate_glyph_svgs.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
