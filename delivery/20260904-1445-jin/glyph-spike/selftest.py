"""recognize.py の幾何と採点を API なしで検算する(使い捨て)。

    uv run --with pillow --with cairosvg python selftest.py
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import cairosvg
from PIL import Image, ImageChops, ImageOps

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import make_sheet as ms  # noqa: E402
import recognize as rc  # noqa: E402


def synthetic_sheet(name: str) -> Image.Image:
    rows = ms.rows_for(name, rc.SOURCES[name])
    pages, _ = ms.layout(rows)
    sheet = ms.render_page(name, 0, len(pages), pages[0])
    guide = ms.render_page(name, 0, len(pages), pages[0], guide=True)
    body = guide.split(">", 1)[1].rsplit("</svg>", 1)[0]  # 手本の中身を重ねる
    composite = sheet.replace("</svg>", body + "</svg>")
    side = int(ms.SIDE * rc.PX_PER_MM)
    png = cairosvg.svg2png(bytestring=composite.encode(), output_width=side, output_height=side)
    return Image.open(io.BytesIO(png)).convert("RGB")


def main() -> int:
    flat0 = synthetic_sheet("fib")
    side = flat0.width
    # 90° 時計回りに回し、周りに 300 px の余白を足した「写真」
    photo = ImageOps.expand(flat0.rotate(-90, expand=True), border=300, fill="white")
    c = ms.FID / 2 * rc.PX_PER_MM

    def rot(x: float, y: float) -> list[float]:  # 元の (x, y) → 回した写真の座標
        return [side - y + 300, x + 300]

    corners = {"tl": rot(c, c), "tr": rot(side - c, c), "bl": rot(c, side - c), "br": rot(side - c, side - c)}
    flat = rc.rectify(photo, corners)
    diff = ImageChops.difference(flat.convert("L"), flat0.convert("L"))
    bad = sum(1 for v in diff.getdata() if v > 96) / (side * side)
    print(f"正面化の画素の食い違い(>96): {bad:.4%}")
    rows = ms.rows_for("fib", rc.SOURCES["fib"])
    pages, _ = ms.layout(rows)
    row, start, y = pages[0][12]
    n = min(ms.COLS, len(row.cells) - start)
    rc.strip(flat, ms.MARGIN + ms.LABEL_W, y, n).save(HERE / "selftest-strip.png")
    print(f"行 {row.id} ({row.label}) を selftest-strip.png に切り出した(升 {n})")
    lines = [(r, s, yy, min(ms.COLS, len(r.cells) - s)) for r, s, yy in pages[0]]
    perfect = {(r.id, k): r.cells[k] for r, s, _, n in lines for k in range(s, s + n)}
    print("完全な読みの採点:")
    ok_perfect = rc.score(lines, perfect)["extra"]["errors"] == 0
    # 最終レビュー #2: 空であるべき升に字を読んだら「幻の字」として数える
    empty_keys = [(r.id, k) for r, s, _, n in lines for k in range(s, s + n) if r.cells[k]["t"] == "empty"]
    assert empty_keys, "空の升の行が無い"
    phantom_read = dict(perfect) | {empty_keys[0]: {"t": "latin", "v": "x"}}
    print("空の升に x を読んだときの採点:")
    ok_phantom = rc.score(lines, phantom_read)["extra"]["phantom"] == 1
    print(f"検査: 完全な読み {'OK' if ok_perfect else 'NG'} / 幻の字 {'OK' if ok_phantom else 'NG'}")
    ok_truncated = check_truncated_response()
    print(f"検査: max_tokens で切れた応答を名指しで止める {'OK' if ok_truncated else 'NG'}")
    return 0 if bad < 0.005 and ok_perfect and ok_phantom and ok_truncated else 1


class _FakeResponse:
    def __init__(self, stop_reason: str, text: str) -> None:
        self.stop_reason = stop_reason
        self.stop_details = None
        self.content = [type("B", (), {"type": "text", "text": text})()]
        self.usage = type("U", (), {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0})()
        self.model = rc.MODEL
        self._request_id = "req_fake"


class _FakeClient:
    """`client.beta.messages.create` だけを持つ偽物(最終レビュー #4)。"""

    def __init__(self, response: _FakeResponse) -> None:
        self.beta = type("Beta", (), {"messages": type("M", (), {"create": staticmethod(lambda **_: response)})()})()


def check_truncated_response() -> bool:
    try:
        rc.call(_FakeClient(_FakeResponse("max_tokens", '{"lines": [')), [], {}, 10)
    except rc.TruncatedResponse as e:
        return "max_tokens" in str(e)
    except Exception as e:  # noqa: BLE001 - 名指しでない失敗は NG
        print(f"  名指しでない失敗: {type(e).__name__}: {e}")
        return False
    return False


if __name__ == "__main__":
    sys.exit(main())
