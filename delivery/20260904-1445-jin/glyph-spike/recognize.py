"""陣書き S0 spike: 撮影した升目シート → Claude で升ごとに読む → 正解と突き合わせて採点。使い捨て。

    uv run --with anthropic --with pillow python recognize.py <写真> --sheet fib [--page 1] [--dry-run]

写真を Anthropic の API に送る。`--dry-run` は送らずに要求数とトークンの目安だけ出す。
SDK の呼び方は claude-api スキル(python/claude-api/tool-use.md の Structured Outputs と
shared/model-migration.md の fallbacks: "default")に従う。実測は glyph-recognition-probe.md に残す。
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import sys
from collections import Counter
from pathlib import Path

from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_sheet as ms  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SOURCES = {"fib": REPO / "examples-v2/fib/fib.jin", "clicker": REPO / "examples-v2/clicker/clicker.jin"}
MODEL = "claude-opus-5-5"
BETAS = ["server-side-fallback-2026-07-01"]
MAX_EDGE = 2576
PX_PER_MM = 10
LINES_PER_REQUEST = 10
TOKENS_PER_PX = 1 / 784  # 28×28 の区画あたり 1 トークンの目安(claude-api スキル cost-optimization.md)

# ---------------------------------------------------------------- Claude

CORNER_SCHEMA = {
    "type": "object",
    "properties": {k: {"type": "array", "items": {"type": "number"}} for k in ("tl", "tr", "bl", "br")},
    "required": ["tl", "tr", "bl", "br"],
    "additionalProperties": False,
}


def cells_schema(glyph_ids: list[str]) -> dict:
    cell = {
        "type": "object",
        "properties": {
            "t": {"type": "string", "enum": ["latin", "glyph", "empty"]},
            "v": {"type": "string"},
            "unsure": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["t", "v", "unsure"],
        "additionalProperties": False,
    }
    line = {
        "type": "object",
        "properties": {"id": {"type": "string"}, "cells": {"type": "array", "items": cell}},
        "required": ["id", "cells"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"lines": {"type": "array", "items": line}},
        "required": ["lines"],
        "additionalProperties": False,
    }


def png_block(img: Image.Image) -> dict:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                        "data": base64.standard_b64encode(buf.getvalue()).decode()}}


def call(client, content: list[dict], schema: dict, max_tokens: int) -> tuple[dict, dict]:
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        betas=BETAS,
        fallbacks="default",
        output_config={"format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": content}],
    )
    if response.stop_reason == "refusal":
        raise SystemExit(f"refusal: {response.stop_details}")
    text = next(b.text for b in response.content if b.type == "text")
    usage = {"input": response.usage.input_tokens, "output": response.usage.output_tokens,
             "cache_read": getattr(response.usage, "cache_read_input_tokens", 0) or 0,
             "model": response.model, "request_id": response._request_id}
    return json.loads(text), usage


# ---------------------------------------------------------------- 幾何


def solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c:
                k = m[r][c] / m[c][c]
                m[r] = [x - k * y for x, y in zip(m[r], m[c])]
    return [m[i][n] / m[i][i] for i in range(n)]


def perspective_coeffs(dst: list[tuple[float, float]], src: list[tuple[float, float]]) -> list[float]:
    """Pillow の PERSPECTIVE 用: 出力の点 dst → 入力の点 src へ写す 8 係数。"""
    a, b = [], []
    for (x, y), (u, v) in zip(dst, src):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.append(u)
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y]); b.append(v)
    return solve(a, b)


def rectify(photo: Image.Image, corners: dict) -> Image.Image:
    side = int(ms.SIDE * PX_PER_MM)
    c = ms.FID / 2 * PX_PER_MM
    dst = [(c, c), (side - c, c), (c, side - c), (side - c, side - c)]
    src = [tuple(corners[k]) for k in ("tl", "tr", "bl", "br")]
    return photo.transform((side, side), Image.Transform.PERSPECTIVE, perspective_coeffs(dst, src),
                           Image.Resampling.BICUBIC, fillcolor="white")


def strip(img: Image.Image, start_x: float, y: float, n: int) -> Image.Image:
    pad = 1.5
    box = ((start_x - pad) * PX_PER_MM, (y - pad) * PX_PER_MM,
           (start_x + n * ms.CELL + pad) * PX_PER_MM, (y + ms.CELL + pad) * PX_PER_MM)
    return img.crop(tuple(int(v) for v in box))


# ---------------------------------------------------------------- 本体

INSTRUCTIONS = """You are reading hand-written cells from a "Jin" magic-circle worksheet.
The first image is the glyph reference table: each box shows one glyph and its id below it.
Then each line image is a horizontal strip of square cells (light grey boxes), left to right.
For each line, return exactly as many cells as its stated count, in order, and echo the line id. Each cell holds ONE of:
- a Latin letter, digit, underscore or other single character (t="latin", v = that character; Japanese characters are allowed),
- a glyph from the reference table (t="glyph", v = its id exactly as printed),
- nothing (t="empty", v="").
Never invent a character for an empty cell. If unsure, put your best answer in v and up to 3 alternatives in "unsure"
(alternatives use the same notation: a character, or a glyph id)."""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("photo", type=Path)
    ap.add_argument("--sheet", required=True, choices=sorted(SOURCES))
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = ms.rows_for(args.sheet, SOURCES[args.sheet])
    pages, _ = ms.layout(rows)
    entries = pages[args.page - 1]
    lines = [(row, start, y, min(ms.COLS, len(row.cells) - start)) for row, start, y in entries]

    photo = ImageOps.exif_transpose(Image.open(args.photo)).convert("RGB")
    scale = min(1.0, MAX_EDGE / max(photo.size))
    small = photo.resize((round(photo.width * scale), round(photo.height * scale)))
    ref = Image.open(HERE / "reference.png").convert("RGB")
    n_req = 1 + (len(lines) + LINES_PER_REQUEST - 1) // LINES_PER_REQUEST
    strip_px = sum((n * ms.CELL + 3) * (ms.CELL + 3) * PX_PER_MM**2 for *_, n in lines)
    est = small.width * small.height * TOKENS_PER_PX + (n_req - 1) * ref.width * ref.height * TOKENS_PER_PX + strip_px * TOKENS_PER_PX
    print(f"要求 {n_req} 回 / 入力画像トークンの目安 {est:,.0f}(字形表は 2 回目以降キャッシュ)/ 行 {len(lines)}")
    if args.dry_run:
        return 0

    import anthropic

    client = anthropic.Anthropic()
    log: dict = {"photo": str(args.photo), "sheet": args.sheet, "page": args.page, "usage": []}

    corners, usage = call(client, [
        png_block(small),
        {"type": "text", "text": "This photo shows a square worksheet with four square fiducial markers at its corners. "
         "Three markers have a filled square in the middle; the TOP-RIGHT marker of the worksheet has a filled circle instead. "
         "The photo may be rotated. Return the pixel coordinates [x, y] of the centre of each marker, named by its position "
         "on the worksheet (tl, tr, bl, br; tr = the circle marker), in this image's pixel space."},
    ], CORNER_SCHEMA, 2000)
    log["usage"].append(usage)
    log["corners"] = corners
    flat = rectify(photo, {k: [v / scale for v in corners[k]] for k in corners})
    (HERE / "results").mkdir(exist_ok=True)
    flat.save(HERE / "results" / f"{args.photo.stem}-flat.png")

    glyph_ids = list(ms.GLYPHS)
    got: dict[tuple[str, int], dict] = {}
    for i in range(0, len(lines), LINES_PER_REQUEST):
        chunk = lines[i:i + LINES_PER_REQUEST]
        ref_block = png_block(ref) | {"cache_control": {"type": "ephemeral"}}
        content: list[dict] = [ref_block, {"type": "text", "text": INSTRUCTIONS}]
        for row, start, y, n in chunk:
            content.append({"type": "text", "text": f"line id={row.id}@{start} cells={n}"})
            content.append(png_block(strip(flat, ms.MARGIN + ms.LABEL_W, y, n)))
        data, usage = call(client, content, cells_schema(glyph_ids), 16000)
        log["usage"].append(usage)
        for line in data["lines"]:
            rid, start = line["id"].split("@")
            for k, cell in enumerate(line["cells"]):
                got[(rid, int(start) + k)] = cell
    log["cells"] = {f"{r}:{k}": c for (r, k), c in got.items()}
    (HERE / "results" / f"{args.photo.stem}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1) + "\n")
    return score(lines, got)


def norm(cell: dict) -> str:
    if cell.get("t") == "empty" or cell.get("v", "") == "":
        return "∅"
    return ("#" + cell["v"]) if cell["t"] == "glyph" else cell["v"]


def score(lines, got) -> int:
    stats = {"program": Counter(), "extra": Counter()}
    confusion: Counter = Counter()
    expected_keys = set()
    for row, start, _, n in lines:
        kind = "extra" if row.label.startswith("extra") else "program"
        for k in range(start, start + n):
            expected_keys.add((row.id, k))
            want = norm(row.cells[k])
            have = norm(got.get((row.id, k), {"t": "empty", "v": ""}))
            stats[kind]["cells"] += 1
            if want != have:
                stats[kind]["errors"] += 1
                stats[kind]["missing" if have == "∅" else "wrong"] += 1
                confusion[(want, have)] += 1
    phantom = sum(1 for key, c in got.items() if key not in expected_keys and norm(c) != "∅")
    for kind, s in stats.items():
        if s["cells"]:
            print(f"{kind}: 升 {s['cells']} / 誤り {s['errors']}(違う字 {s['wrong']}・欠落 {s['missing']})"
                  f" / 誤り率 {s['errors'] / s['cells']:.1%}")
    print(f"幻の字(升の外に返した字): {phantom}")
    for (want, have), n in confusion.most_common(10):
        print(f"  {want} → {have} ×{n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
