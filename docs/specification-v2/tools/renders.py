"""本に載せる「Jin が描いた絵」を PNG にして `figures/` に書く。

    uv run python docs/specification-v2/tools/renders.py

2 種類ある。作図(D2 / Mermaid)と違い、どちらも Jin の出力そのもの。

- 魔法陣の図: レンダラ(`jin_render.render`)の SVG を PNG にする
- 画面: `jin run --frames` の表示リスト(`rect` / `clear` / `ink` / `text`)を、プレイヤーと同じ論理座標で塗った PNG。
  ブラウザのプレイヤーの描き方の簡易な写し(色・四角・ドットの文字)で、ピクセル一致はしない

HTML に組むときに埋め込めるよう PNG にする(`build-html.mjs` は `figures/` の PNG を data URI で埋め込む)。
描き方が変わればここを再実行して差分を読む。
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import cairosvg
from jin_core.check import check_text
from jin_render import render
from jin_render.v2.font import pixels
from PIL import Image, ImageDraw

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

#: (出力名, 例のパス, 並べる tick, 拡大率)
SCREENS = [
    ("screen-hello", "examples/hello/hello.jin", [0, 20, 40], 4),
]
GAP = 12  # 画面を並べる間隔(px)


def screen_strip(source: str, ticks: list[int], scale: int) -> Image.Image:
    path = BOOK / source
    model = check_text(path.read_text(encoding="utf-8"), path.name).model
    width, height = model.stage.width, model.stage.height
    with tempfile.TemporaryDirectory() as tmp:
        frames_path = Path(tmp) / "frames.jsonl"
        subprocess.run(
            [
                sys.executable,
                "-P",
                "-m",
                "jin_cli.main",
                "run",
                str(path),
                "--ticks",
                str(max(ticks) + 1),
                "--frames",
                str(frames_path),
            ],
            check=True,
            capture_output=True,
        )
        frames = {
            f["tick"]: f
            for f in map(json.loads, frames_path.read_text(encoding="utf-8").splitlines())
        }
    strip = Image.new("RGB", (len(ticks) * (width * scale + GAP) - GAP, height * scale), "white")
    for k, tick in enumerate(ticks):
        screen = Image.new("RGB", (width * scale, height * scale), "#000")
        draw = ImageDraw.Draw(screen)
        ink = "#fff"
        for op, *args in frames[tick]["ops"]:
            if op == "clear":
                draw.rectangle((0, 0, width * scale, height * scale), fill=args[0])
            elif op == "ink":
                ink = args[0]
            elif op == "rect":
                x, y, w, h = args
                draw.rectangle(
                    (x * scale, y * scale, (x + w) * scale - 1, (y + h) * scale - 1), fill=ink
                )
            elif op == "text":
                text, x, y = args
                for i, ch in enumerate(text):
                    for col, row in pixels(ch):
                        px, py = (x + i * 6 + col) * scale, (y + row) * scale
                        draw.rectangle((px, py, px + scale - 1, py + scale - 1), fill=ink)
        strip.paste(screen, (k * (width * scale + GAP), 0))
    return strip


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
    for name, source, ticks, scale in SCREENS:
        screen_strip(source, ticks, scale).save(FIGURES / f"{name}.png")
    print(f"描きました: {len(RENDERS) + len(SCREENS)} 枚")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
