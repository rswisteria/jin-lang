"""完全陣の SVG スナップショット(fib。paddle 以上はファイルが 1 MB 近くになるので規律の検査 test_full.py に任せる)。

描き方を直したら `uv run pytest packages/jin-render/tests/test_snapshots_full.py --snapshot-update` で更新し、差分を読んでからコミット。
既存の描画のスナップショット(`test_snapshots_v2.ambr`)は完全陣を足しても変わらない(`test_full.py` と合わせて固定)。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from jin_core.check import check_text
from jin_render.v2.full import render_full

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("name", ["fib"])
def test_full_circle_snapshot(name: str, snapshot) -> None:
    path = REPO_ROOT / "examples-v2" / name / f"{name}.jin"
    model = check_text(path.read_text(encoding="utf-8"), path.name).model
    assert render_full(model) == snapshot
