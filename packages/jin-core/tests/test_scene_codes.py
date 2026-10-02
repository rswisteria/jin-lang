"""絵の文法の診断 JIN3xx(陣書き・`docs/spec/v2/diagnostics.md` の JIN3xx の節)。

`jin_core` は番号と重さだけを知り、画像を知らない。fixture と「コードごとに fixture がある」の検査は
構文解析器(S3)と一緒に足す。
"""

from __future__ import annotations

from jin_core.diagnostics import CANONICAL_CODES, SCENE_CODES, V2_CODES, severity_of


def test_scene_codes_are_the_six_of_the_plan() -> None:
    assert SCENE_CODES == {
        "JIN301": "error",
        "JIN302": "error",
        "JIN303": "error",
        "JIN304": "error",
        "JIN305": "error",
        "JIN306": "warning",
    }


def test_severity_of_knows_scene_codes() -> None:
    assert severity_of("JIN301") == "error"
    assert severity_of("JIN306") == "warning"


def test_scene_codes_do_not_overlap_other_tables() -> None:
    assert not set(SCENE_CODES) & set(CANONICAL_CODES)
    assert not set(SCENE_CODES) & set(V2_CODES)
