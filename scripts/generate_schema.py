#!/usr/bin/env python3
"""schemas/ の生成物（jin.schema.json / jin-v2.schema.json / abilities.json）を Pydantic 定義から再生成する。

CI のドリフト検出（packages/jin-core/tests/test_schema_export.py など）が落ちたらこれを実行してコミットする。
"""

from __future__ import annotations

import sys
from pathlib import Path

from jin_core.schema_export import SCHEMA_PATH, SCHEMA_PATH_V2, render
from jin_core.v2.abilities import ABILITIES_PATH, render_abilities

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write(relative: str, text: str) -> None:
    target = REPO_ROOT / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    before = target.read_text(encoding="utf-8") if target.exists() else None
    target.write_text(text, encoding="utf-8")
    print(f"{'unchanged' if before == text else 'written'}: {relative}")


def main() -> int:
    _write(SCHEMA_PATH, render(1))
    _write(SCHEMA_PATH_V2, render(2))
    _write(ABILITIES_PATH, render_abilities())
    return 0


if __name__ == "__main__":
    sys.exit(main())
