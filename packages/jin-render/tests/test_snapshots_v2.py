"""v2 の SVG スナップショット（設計書 §12 Phase 3「SVG スナップショットが安定」）。

v1 と同じく**正規化せず素のバイト列**で比較する。レイアウト定数（`jin_render.v2.geometry`）や
描き方を直したら `uv run pytest packages/jin-render --snapshot-update` で更新し、差分を読んでからコミット。
"""

from __future__ import annotations

import pytest
from jin_core.v2.model import JinFileV2
from jin_render import render

from .conftest import PROGRAMS_V2, load_model_v2, trace_rows_v2


@pytest.mark.parametrize("name", ["paddle", "clicker", "fib", "tetris", "othello"])
def test_example_svg_snapshot(name: str, request: pytest.FixtureRequest, snapshot) -> None:
    model: JinFileV2 = request.getfixturevalue(name)
    assert render(model) == snapshot


def test_play_circle_snapshot(paddle: JinFileV2, snapshot) -> None:
    """核あり陣の 4 環（手順 / 道具 / 記憶 / 境界）と装飾。"""
    assert render(paddle, focus="Play") == snapshot


def test_rite_view_snapshot(paddle: JinFileV2, snapshot) -> None:
    """手順の図（深さ 0 / 1・if の弧・cast の放射線・finish）。"""
    assert render(paddle, focus="Play/step") == snapshot


def test_transfer_fixture_snapshot(snapshot) -> None:
    """`delegate`（paddle に無い 13 種目）。"""
    assert render(load_model_v2(PROGRAMS_V2 / "transfer.jin")) == snapshot


def test_trace_overlay_snapshot(paddle: JinFileV2, snapshot) -> None:
    """`--upto 12` の overlay（強調 + 境界環の外側の点）。"""
    assert render(paddle, focus="Play", trace=trace_rows_v2(), upto=12) == snapshot
