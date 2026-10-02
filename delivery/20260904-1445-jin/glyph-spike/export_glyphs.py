"""glyphs.json の字形を正典の置き場 docs/spec/v2/glyphs/<id>.svg に書き出す(1 升 = viewBox 0 0 100 100)。

S0 で字形を描き直したら再実行して上書きする。S2 で字形のデータが jin_render に移ったら、この SVG は
そこからの生成物に切り替える(手で編集しない)。
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[2] / "docs/spec/v2/glyphs"


def main() -> None:
    glyphs = json.loads((HERE / "glyphs.json").read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.svg"):
        if old.stem not in glyphs:
            old.unlink()
    for gid, g in glyphs.items():
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">\n'
            f'<path d="{g["d"]}" fill="none" stroke="#000000" stroke-width="6" '
            'stroke-linecap="round" stroke-linejoin="round"/>\n</svg>\n'
        )
        (OUT / f"{gid}.svg").write_text(svg, encoding="utf-8")
    print(f"{len(glyphs)} 字を {OUT} に書いた")


if __name__ == "__main__":
    main()
