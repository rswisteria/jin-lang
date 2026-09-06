"""SVG のスナップショット（design.yaml machine 1「examples 2 本について安定」）。

**正規化せず素のバイト列で比較する。** design.yaml の machine 条件は「（正規化後）」と書いているが、
`render` の出力は既にバイト単位で決定的（machine 2 / 7 で別に固定している）ので、正規化を挟むと
「正規化で消える差分」が検出できなくなる。座標の桁揺れ・属性順の入れ替わり・要素順の変化は
どれも意味のある回帰であり、素の比較で落としたい。

スナップショットは `__snapshots__/test_snapshots.ambr`（syrupy）。テンプレートやレイアウト定数を
直したら `uv run pytest packages/jin-render --snapshot-update` で更新し、**差分を読んでから**
コミットすること。
"""

from __future__ import annotations

import pytest
from jin_core.model import JinFile
from jin_render import render

from .conftest import trace_rows


@pytest.mark.parametrize("name", ["researcher", "pipeline"])
def test_example_svg_snapshot(name: str, request: pytest.FixtureRequest, snapshot) -> None:
    model: JinFile = request.getfixturevalue(name)
    assert render(model) == snapshot


def test_focus_switch_snapshot(researcher: JinFile, snapshot) -> None:
    """入れ子の側から見た図（focus を切り替えたときの展開対象の違い）。"""
    assert render(researcher, focus="Summarizer") == snapshot


def test_trace_overlay_snapshot(pipeline: JinFile, snapshot) -> None:
    """`--upto 5` の overlay（強調 + 境界環の外側の点）。"""
    assert render(pipeline, trace=trace_rows(), upto=5) == snapshot
