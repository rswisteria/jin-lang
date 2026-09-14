"""`apps/player/src/glyphs.ts` を k6x8ゴシックの BDF から生成する（abilities.md §2・設計書 §11 #49）。

`canvas.text` の書体は、ASCII（U+0020〜U+007E）がプレイヤー内蔵の 5×7（`apps/player/src/font.ts`）で、
それ以外のコードポイントがこのスクリプトの出力（k6x8ゴシックの字形 7001 字）である。

- 原本は `apps/player/fonts/k6x8/k6x8_gothic.bdf`（配布 zip の中身を改変せずに置いたもの）。
  digest を `BDF_SHA256` に固定し、違えば生成しない（原本が黙って差し替わるのを防ぐ）
- 字形は 6×8 の枠（BDF の `FONT_ASCENT` 7 / `FONT_DESCENT` 1）に置き、1 字 6 バイト
  （列ごと・bit0 が最上段。`font.ts` の ASCII の表と同じ向き）にする。枠からはみ出す点があれば生成しない
- 出力はコードポイント（2 バイト big-endian・昇順）と字形を別々に base64 にした 2 本の文字列

使い方:

    uv run python scripts/generate_glyphs.py            # glyphs.ts を書き直す（変わらなければ触らない）
    uv run python scripts/generate_glyphs.py --check    # ずれていたら exit 1（pytest が走らせる）
    uv run python scripts/generate_glyphs.py --stdout   # 標準出力へ（CI が diff で比べる。ツリーを書き換えない）
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FONT_DIR = REPO_ROOT / "apps" / "player" / "fonts" / "k6x8"
BDF = FONT_DIR / "k6x8_gothic.bdf"
LICENSE = FONT_DIR / "k6x8.txt"
OUTPUT = REPO_ROOT / "apps" / "player" / "src" / "glyphs.ts"

BDF_SHA256 = "b9029fa0dd93738c23e55b79ffb1f4445f51a57d09f2f9436b2c4d5ee6fe0590"
CELL_WIDTH = 6
CELL_HEIGHT = 8
ASCII_LAST = 0x7E
LICENSE_MARKERS = (
    "These fonts are free software.",
    "Unlimited permission is granted",
    'THESE FONTS ARE PROVIDED "AS IS" WITHOUT WARRANTY.',
)


def read_cells(text: str) -> dict[int, bytes]:
    """BDF の全字形を 6×8 の枠の 6 バイトにする。"""
    ascent = None
    cells: dict[int, bytes] = {}
    codepoint = width = height = x_off = y_off = None
    lines = iter(text.splitlines())
    for line in lines:
        head, _, rest = line.partition(" ")
        if head == "FONT_ASCENT":
            ascent = int(rest)
        elif head == "ENCODING":
            codepoint = int(rest)
        elif head == "BBX":
            width, height, x_off, y_off = map(int, rest.split())
        elif head == "BITMAP":
            if ascent is None or None in (codepoint, width, height, x_off, y_off):
                raise ValueError(
                    f"BITMAP の前に FONT_ASCENT / ENCODING / BBX がありません（U+{codepoint}）"
                )
            columns = [0] * CELL_WIDTH
            span = (width + 7) // 8 * 8
            for row in range(height):
                bits = int(next(lines), 16)
                for col in range(width):
                    if not bits >> (span - 1 - col) & 1:
                        continue
                    x = x_off + col
                    y = ascent - (y_off + height) + row
                    if not (0 <= x < CELL_WIDTH and 0 <= y < CELL_HEIGHT):
                        raise ValueError(f"U+{codepoint:04X} の点 ({x}, {y}) が 6×8 の枠の外です")
                    columns[x] |= 1 << y
            cells[codepoint] = bytes(columns)
            codepoint = width = height = x_off = y_off = None
    return cells


def license_lines(text: str) -> list[str]:
    """`k6x8.txt` のライセンス節の英文 3 行をそのまま抜く。"""
    found = []
    for marker in LICENSE_MARKERS:
        matches = [line.strip("　 ") for line in text.splitlines() if marker in line]
        if len(matches) != 1:
            raise ValueError(f"k6x8.txt にライセンスの行 {marker!r} がちょうど 1 つありません")
        found.append(matches[0])
    return found


def render(bdf: bytes, license_text: str) -> str:
    digest = hashlib.sha256(bdf).hexdigest()
    if digest != BDF_SHA256:
        raise ValueError(f"{BDF.name} の sha256 が {digest} です（期待は {BDF_SHA256}）")
    cells = {cp: cell for cp, cell in read_cells(bdf.decode("ascii")).items() if cp > ASCII_LAST}
    codepoints = sorted(cells)
    if codepoints and codepoints[-1] > 0xFFFF:
        raise ValueError(f"U+{codepoints[-1]:X} は 2 バイトに収まりません")
    packed = b"".join(cp.to_bytes(2, "big") for cp in codepoints)
    bitmaps = b"".join(cells[cp] for cp in codepoints)
    license_block = "\n".join(f" * {line}" for line in license_lines(license_text))
    return (
        "/**\n"
        " * 生成物: `uv run python scripts/generate_glyphs.py` が\n"
        " * `apps/player/fonts/k6x8/k6x8_gothic.bdf` から書く。手で編集しない。\n"
        " *\n"
        " * `canvas.text` の ASCII 以外の字形（abilities.md §2・設計書 §11 #49）。ASCII は `font.ts` の 5×7。\n"
        f" * 字数 {len(codepoints)}。`CODEPOINTS` は 2 バイト big-endian の昇順、`BITMAPS` は 1 字 6 バイト\n"
        " * （6×8 の枠・列ごと・bit0 が最上段）を同じ順に並べ、それぞれ base64 にしたもの。\n"
        " *\n"
        " * k6x8ゴシック 2023-10-19 版（https://littlelimit.net/k6x8.htm）\n"
        " * Copyright (C) 2000-2023 Num Kadoma\n"
        f" * BDF sha256: {digest}\n"
        " *\n"
        f"{license_block}\n"
        " */\n"
        f"export const GLYPH_COUNT = {len(codepoints)};\n"
        f'export const CODEPOINTS = "{base64.b64encode(packed).decode("ascii")}";\n'
        f'export const BITMAPS = "{base64.b64encode(bitmaps).decode("ascii")}";\n'
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="ずれていたら exit 1（書き換えない）")
    mode.add_argument("--stdout", action="store_true", help="標準出力へ書く（書き換えない）")
    args = parser.parse_args(argv)

    try:
        text = render(BDF.read_bytes(), LICENSE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"generate_glyphs: {error}", file=sys.stderr)
        return 1

    if args.stdout:
        sys.stdout.write(text)
        return 0
    current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.is_file() else None
    if args.check:
        if current != text:
            print(
                f"{OUTPUT.relative_to(REPO_ROOT)} が原本とずれています。"
                "`uv run python scripts/generate_glyphs.py` で再生成してください。",
                file=sys.stderr,
            )
            return 1
        return 0
    if current != text:
        OUTPUT.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
