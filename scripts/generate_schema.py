#!/usr/bin/env python3
"""schemas/jin.schema.json を Pydantic 定義から再生成する。

CI のドリフト検出（packages/jin-core/tests/test_schema_export.py）が落ちたらこれを実行してコミットする。
"""

from __future__ import annotations

import sys
from pathlib import Path

from jin_core.schema_export import SCHEMA_PATH, render

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    target = REPO_ROOT / SCHEMA_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    text = render()
    before = target.read_text(encoding="utf-8") if target.exists() else None
    target.write_text(text, encoding="utf-8")
    if before == text:
        print(f"unchanged: {SCHEMA_PATH}")
    else:
        print(f"written: {SCHEMA_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
