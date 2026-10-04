"""本に載せる「Jin が描いた図」を、レンダラ(`jin_render.render`)から PNG にして `figures/` に書く。

    uv run python docs/specification-v2/tools/renders.py

作図(D2 / Mermaid)と違い、これはレンダラの出力そのもの。HTML に組むときに埋め込めるよう PNG にする
(`build-html.mjs` は `figures/` の PNG を data URI で埋め込む)。描き方が変わればここを再実行して差分を読む。
"""

from __future__ import annotations

from pathlib import Path

import cairosvg
from jin_core.check import check_text
from jin_render import render

BOOK = Path(__file__).resolve().parents[1]
FIGURES = BOOK / "figures"

#: (出力名, 例のパス, render の引数, PNG の幅 px)
RENDERS = [
    ("render-hello", "examples/hello/hello.jin", {}, 420),
    ("render-score", "examples/score/score.jin", {}, 420),
    ("render-score-rite", "examples/score/score.jin", {"focus": "Play/count"}, 420),
    ("render-score-full", "examples/score/score.jin", {"full": True}, 560),
    ("render-score-panorama", "examples/score/score.jin", {"panorama": True}, 560),
]


def main() -> int:
    FIGURES.mkdir(exist_ok=True)
    for name, source, options, width in RENDERS:
        path = BOOK / source
        model = check_text(path.read_text(encoding="utf-8"), path.name).model
        svg = render(model, **options)
        cairosvg.svg2png(
            bytestring=svg.encode(),
            write_to=str(FIGURES / f"{name}.png"),
            output_width=width,
            background_color="white",
        )
    print(f"描きました: {len(RENDERS)} 枚")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
