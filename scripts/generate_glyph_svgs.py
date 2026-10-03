#!/usr/bin/env python3
"""`docs/spec/v2/glyphs/<id>.svg`(正典 glyph.md の字形の表)を `jin_render.v2.glyph_paths` から生成する。

字形の正本は `glyph_paths.GLYPH_PATHS`(陣書き S2 で S0 の spike の glyphs.json から移した)。SVG は手で編集しない。
1 升 = viewBox `0 0 100 100`、線の太さ 6。表に無い SVG は消す。

使い方:

    uv run python scripts/generate_glyph_svgs.py            # 書き直す(変わらなければ触らない)
    uv run python scripts/generate_glyph_svgs.py --check    # ずれていたら exit 1(pytest が走らせる)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from jin_render.v2.glyph_paths import GLYPH_PATHS, glyph_d

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT = REPO_ROOT / "docs" / "spec" / "v2" / "glyphs"


def render(gid: str) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">\n'
        f'<path d="{glyph_d(gid, 0.0, 0.0, 100.0)}" fill="none" stroke="#000000" stroke-width="6" '
        'stroke-linecap="round" stroke-linejoin="round"/>\n</svg>\n'
    )


def expected() -> dict[str, str]:
    return {f"{gid}.svg": render(gid) for gid in GLYPH_PATHS}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="ずれていたら exit 1(書き換えない)")
    args = parser.parse_args(argv)
    want = expected()
    have = (
        {p.name: p.read_text(encoding="utf-8") for p in OUT.glob("*.svg")} if OUT.is_dir() else {}
    )
    stale = sorted(set(have) - set(want))
    differ = sorted(name for name, text in want.items() if have.get(name) != text)
    if args.check:
        if stale or differ:
            print(
                f"ずれている: 余分 {stale} / 違う {differ[:10]}{' …' if len(differ) > 10 else ''}",
                file=sys.stderr,
            )
            print("uv run python scripts/generate_glyph_svgs.py で書き直す", file=sys.stderr)
            return 1
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    for name in stale:
        (OUT / name).unlink()
    for name in differ:
        (OUT / name).write_text(want[name], encoding="utf-8")
    print(f"字形 {len(want)} 本(書き直し {len(differ)}・削除 {len(stale)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
