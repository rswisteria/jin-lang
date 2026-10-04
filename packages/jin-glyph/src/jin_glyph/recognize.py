"""Claude 認識器(モード 2 = 印刷した型紙に手で描いた陣の写真・陣書き S4・設計書 §3.1 / §3.7・正典 glyph.md §10)。

写真 → 場面グラフ(`JinScene`)。プログラムは組まない(構文解析器 `jin_glyph.parse` の仕事。Claude に `.jin` を書かせない)。

1. 位置合わせ: 写真(長辺 `ALIGN_LONG_SIDE` px に縮小)を 1 回送り、四隅の護符の中心・向きの印(右上の丸)・等級の印を返させる。
   座標は**画像の幅・高さに対する比**で受け取る(API 側の縮小に依存しない)。受け取った位置は護符の中の塗りの重心で詰め直す
   (`refine_talisman`。Claude の座標は升の数分の 1 ずれうるので、升を切り出す精度はこちらで出す)
2. 正面化・切り出し: 4 点の射影変換(純 Python で 8 元の連立を解く・`homography`)で型紙の座標へ戻し、
   等級の幾何(`jin_render.v2.sheet_layout`。型紙を描く側と同じ表)から書く升を切り出す。空の升は送らない(`is_blank`)
3. 記号の認識: 字の入った升を `CELLS_PER_REQUEST` 個ずつ、番号付きの画像として 1 要求に並べ、升ごとに
   「ラテン 1 字か紋 id か構造の印か・迷い(他の候補)」を構造化出力で返させる。紋の字形表は画像で最初の user の先頭に置き、
   `cache_control` で使い回す(`system` は text しか受けないため・SDK 1.11.0 の型で実測)
4. 場面グラフ: 持ち主ごとに升を読む順につなぎ、印刷した始まりの印 `start` を頭に積む。銘帯の最後が継ぎの紋なら
   まだ使っていない続きの帯を番号の順につなぐ(`fill_sheet` の逆)。升の `box` は**写真の座標**(EXIF の向きを直した後)

外部送信: この関数は写真と升の画像を Anthropic の API に送る。呼ぶのは `jin check <写真>` / `jin fmt <写真>` を明示したときだけで、
`--offline` では呼ばれない(`jin_cli.main`)。認証は SDK の既定の解決順(`ANTHROPIC_API_KEY` ほか)。
"""

from __future__ import annotations

import base64
import hashlib
import io
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

import anthropic
from jin_core.v2.glyph import GLYPHS, START_MARK, STRUCT_MARKS
from jin_render.v2.sheet_layout import GRADES, Grade, Sheet, Slot, sheet_layout
from PIL import Image, ImageDraw, ImageFont, ImageOps
from pydantic import BaseModel

from jin_glyph import freehand
from jin_glyph.cells import _flatten
from jin_glyph.scene import Band, Cell, Figure, ImageInfo, JinScene

MODEL = "claude-opus-5-5"
#: `fallbacks: "default"` の beta(拒否されたら分類ごとの推奨モデルでサーバ側がやり直す)
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOKENS = 16000
#: 位置合わせに送る写真の長辺(px)。座標は比で受けるので、API 側でさらに縮められても狂わない
ALIGN_LONG_SIDE = 1568
#: 正面化した型紙の 1 升の px
RECTIFIED_CELL_PX = 48
#: 空の升の判定に使う升の内側(升の枠は ±0.45 升。印刷の枠を拾わないよう内側だけを見る)
INK_INSET = 0.38
#: 「地より DARK_DELTA 以上暗い画素」がこの割合を超えたら字が入っている
INK_FRACTION = 0.02
DARK_DELTA = 60
#: Claude に見せる升の画像(升の枠を含めて ±0.6 升を、この px 角に)
CELL_IMAGE_PX = 96
CELLS_PER_REQUEST = 60
#: 護符の中の塗りを探す窓(升)と詰め直しの回数
REFINE_WINDOW = 1.0
REFINE_ROUNDS = 4

_STRUCT_IDS = [m.id for m in STRUCT_MARKS]
_GLYPH_IDS = [g.id for g in GLYPHS]


class RecognizeError(Exception):
    """写真を場面グラフにできない(API の失敗・拒否・型紙が見つからない・応答が契約に合わない)。文はそのまま利用者に見せる。"""


# ---- 射影変換 ------------------------------------------------------------------------------------


def homography(
    src: Sequence[tuple[float, float]], dst: Sequence[tuple[float, float]]
) -> tuple[float, ...]:
    """4 点の対応 src → dst の射影変換の係数 (a, b, c, d, e, f, g, h)。
    dst = ((a x + b y + c) / (g x + h y + 1), (d x + e y + f) / (g x + h y + 1))。Pillow の PERSPECTIVE と同じ並び。"""
    rows: list[list[float]] = []
    for (x, y), (u, v) in zip(src, dst, strict=True):
        rows.append([x, y, 1.0, 0.0, 0.0, 0.0, -u * x, -u * y, u])
        rows.append([0.0, 0.0, 0.0, x, y, 1.0, -v * x, -v * y, v])
    n = 8
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(rows[r][col]))
        if abs(rows[pivot][col]) < 1e-12:
            raise RecognizeError("四隅の護符の位置が一直線に並んでいて、型紙の向きを決められません")
        rows[col], rows[pivot] = rows[pivot], rows[col]
        for r in range(n):
            if r != col:
                factor = rows[r][col] / rows[col][col]
                rows[r] = [a - factor * b for a, b in zip(rows[r], rows[col], strict=True)]
    return tuple(rows[i][n] / rows[i][i] for i in range(n))


def apply(h: Sequence[float], x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f, g, k = h
    w = g * x + k * y + 1.0
    return ((a * x + b * y + c) / w, (d * x + e * y + f) / w)


# ---- 写真 ---------------------------------------------------------------------------------------


def load_photo(data: bytes) -> Image.Image:
    """写真を開き、EXIF の向きを直す(スマホの写真は画素を回さず向きのタグで持つ)。"""
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (OSError, Image.DecompressionBombError) as exc:
        raise RecognizeError(f"画像として開けません({exc})") from exc
    return ImageOps.exif_transpose(image).convert("RGB")


def _jpeg(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=90)
    return base64.standard_b64encode(buffer.getvalue()).decode("ascii")


def _png(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return base64.standard_b64encode(buffer.getvalue()).decode("ascii")


def order_corners(points: Sequence[tuple[float, float]], circle: int) -> list[tuple[float, float]]:
    """護符 4 点を型紙の 左上・右上・左下・右下 の順に。`circle` は丸の護符(右上)の添字。写真が回っていてもよい(裏返しは無い)。"""
    cx = sum(p[0] for p in points) / 4.0
    cy = sum(p[1] for p in points) / 4.0
    # 画像の座標は y が下向きなので、atan2 の昇順が時計回り
    clockwise = sorted(range(4), key=lambda i: math.atan2(points[i][1] - cy, points[i][0] - cx))
    at = clockwise.index(circle)
    tl, tr, br, bl = (points[clockwise[(at + k) % 4]] for k in (-1, 0, 1, 2))
    return [tl, tr, bl, br]


def refine_talisman(
    gray: Image.Image, at: tuple[float, float], cell_px: float
) -> tuple[float, float]:
    """護符の中の塗り(1.2 升角の黒い四角か丸)の重心へ寄せる。窓は ±REFINE_WINDOW 升で、外枠(±1.3 升)を拾わない。"""
    x, y = at
    reach = REFINE_WINDOW * cell_px
    for _ in range(REFINE_ROUNDS):
        box = (round(x - reach), round(y - reach), round(x + reach), round(y + reach))
        patch = gray.crop(box)
        paper = _paper(patch)
        sx = sy = total = 0.0
        width = patch.width
        for i, value in enumerate(patch.get_flattened_data()):
            if value < paper - DARK_DELTA:
                sx += i % width
                sy += i // width
                total += 1.0
        if total == 0.0:
            break
        x, y = box[0] + sx / total + 0.5, box[1] + sy / total + 0.5
    return (x, y)


def _paper(patch: Image.Image) -> int:
    """地(紙)の明るさ: 明るい側から 25% の画素の値。"""
    histogram = patch.histogram()
    count = sum(histogram)
    seen = 0
    for value in range(255, -1, -1):
        seen += histogram[value]
        if seen >= count * 0.25:
            return value
    return 255


def is_blank(patch: Image.Image) -> bool:
    """升の内側に字が入っていないか(地より DARK_DELTA 以上暗い画素が INK_FRACTION 以下)。"""
    paper = _paper(patch)
    histogram = patch.histogram()
    dark = sum(histogram[: max(0, paper - DARK_DELTA)])
    return dark <= INK_FRACTION * sum(histogram)


# ---- 字形表 -------------------------------------------------------------------------------------


def glyph_table(*, with_start: bool = False) -> Image.Image:
    """紋(式紋・判別の紋・継ぎの紋)と構造の印の字形を id 付きで並べた表(Claude への見本)。決定的。
    `with_start` は始まりの印も載せる(フリーハンドでは描き手が描くので読む対象・型紙では刷ってあるので載せない)。"""
    ids = _GLYPH_IDS + _STRUCT_IDS + ([START_MARK] if with_start else [])
    tile, columns = 120, 10
    rows = math.ceil(len(ids) / columns)
    image = Image.new("L", (tile * columns, tile * rows), 255)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=13)
    scale = 72 / 240  # _flatten は一辺 240 の下書きの座標
    for n, gid in enumerate(ids):
        ox, oy = (n % columns) * tile + 24, (n // columns) * tile + 8
        draw.rectangle((ox - 4, oy - 4, ox + 76, oy + 76), outline=190)
        for line in _flatten(gid):
            draw.line([(ox + px * scale, oy + py * scale) for px, py in line], fill=0, width=3)
        draw.text((ox + 36, oy + 96), gid, fill=0, anchor="mm", font=font)
    return image


SYSTEM = f"""You read a hand-drawn "Jin" magic circle written on a printed template sheet.
Every cell of the sheet holds exactly one symbol, drawn by hand with a pen:
- a single Latin/digit/kana/kanji character (names, numbers and string contents), or
- one of the special glyphs shown in the glyph table image (answer its id, e.g. "add", "sep", "quote_l", "loop_count"), or
- one of the structure marks shown in the same table (ids starting with "s_", e.g. "s_set", "s_rite"); a structure mark is a small
  shape inside a double square frame and starts each inscription.
Printed light-grey square frames, tick marks and numbers belong to the template; ignore them.
Never guess a whole word: read each cell on its own, but you may use the neighbouring cells listed with it to break ties.
Glyph ids: {", ".join(_GLYPH_IDS)}.
Structure mark ids: {", ".join(_STRUCT_IDS)}."""

ALIGN_PROMPT = """This photo shows a printed Jin template sheet (a square frame with four black corner talismans).
Each talisman is a square outline with a filled mark inside; exactly one of them (the top-right one of the sheet) has a filled
circle inside, the other three have filled squares.
Return the centre of each of the four talismans as fractions of the image width (x) and height (y), from 0 to 1, whether its inner
mark is a circle, and the large printed grade letter next to the top-left talisman ("S" or "M"; "none" if there is no sheet)."""

CELLS_PROMPT = """Read each numbered cell image below. For every cell return: n (its number), t ("latin" for one character,
"glyph" for a glyph id, "struct" for a structure mark id, "empty" if the cell has no pen stroke), v (the character or the id;
"" when empty), and unsure (other plausible readings, most likely first; [] when you are sure)."""


class _Corner(BaseModel):
    x: float
    y: float
    circle: bool


class _Alignment(BaseModel):
    grade: Literal["S", "M", "none"]
    corners: list[_Corner]


class _CellRead(BaseModel):
    n: int
    t: Literal["latin", "glyph", "struct", "empty"]
    v: str
    unsure: list[str]


class _CellReads(BaseModel):
    cells: list[_CellRead]


# ---- API 境界 -----------------------------------------------------------------------------------


@dataclass
class Recognizer:
    """Claude への要求の窓口。`client` はテストで生の HTTP 応答を返す transport を持つものに差し替える。"""

    client: Any = None
    model: str = MODEL

    def _client(self) -> Any:
        if self.client is None:
            try:
                self.client = anthropic.Anthropic()
            except anthropic.AnthropicError as exc:
                raise RecognizeError(
                    f"Anthropic の API の認証情報がありません（ANTHROPIC_API_KEY などを設定してください: {exc}）"
                ) from exc
        return self.client

    def ask(
        self, content: list[dict[str, Any]], schema: type[BaseModel], system: str | None = None
    ) -> Any:
        try:
            response = self._client().beta.messages.parse(
                model=self.model,
                max_tokens=MAX_TOKENS,
                betas=[FALLBACK_BETA],
                fallbacks="default",
                output_config={"effort": "medium"},
                system=SYSTEM if system is None else system,
                messages=[{"role": "user", "content": content}],
                output_format=schema,
            )
        except TypeError as exc:
            # SDK 1.11.0 は認証情報が 1 つも無いと、送る前に TypeError("Could not resolve authentication method…")
            # を投げる(2026-10-03 の実測)。それ以外の TypeError は生成系のバグなのでそのまま上げる
            if "authentication" not in str(exc):
                raise
            raise RecognizeError(
                "Anthropic の API の認証情報がありません"
                "（ANTHROPIC_API_KEY を設定するか `ant auth login` をしてください。送る前に止めたので写真は外へ出ていません）"
            ) from exc
        except anthropic.AuthenticationError as exc:
            raise RecognizeError(
                f"Anthropic の API が認証を拒みました（API キーを確かめてください）: {exc}"
            ) from exc
        except anthropic.RateLimitError as exc:
            raise RecognizeError(
                f"Anthropic の API の利用上限に達しました。時間をおいて読み直してください: {exc}"
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise RecognizeError(f"Anthropic の API に繋がりません: {exc}") from exc
        except anthropic.APIStatusError as exc:
            raise RecognizeError(
                f"Anthropic の API がエラーを返しました（{exc.status_code}）: {exc}"
            ) from exc
        except (
            anthropic.AnthropicError
        ) as exc:  # 応答が schema に合わない(SDK の検証)・認証情報なし など
            raise RecognizeError(f"Anthropic の API の応答を読めません: {exc}") from exc
        if response.stop_reason == "refusal":
            details = response.stop_details
            category = getattr(details, "category", None) if details is not None else None
            raise RecognizeError(f"Claude が読み取りを断りました（分類: {category}）")
        if response.stop_reason == "max_tokens":
            raise RecognizeError("Claude の応答が長さの上限で切れました")
        parsed = response.parsed_output
        if parsed is None:
            raise RecognizeError(
                f"Claude の応答に結果がありません（stop_reason: {response.stop_reason}）"
            )
        return parsed


def _image_block(data: str, media_type: str) -> dict[str, Any]:
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}


# ---- 全体 ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Ink:
    slot: Slot
    image: str  # base64 PNG
    box: tuple[float, float, float, float]  # 写真の座標


def _small_jpeg(image: Image.Image) -> dict[str, Any]:
    small = image.copy()
    small.thumbnail((ALIGN_LONG_SIDE, ALIGN_LONG_SIDE))
    return _image_block(_jpeg(small), "image/jpeg")


def _align(
    photo: Image.Image, recognizer: Recognizer
) -> tuple[Grade, list[tuple[float, float]]] | None:
    """型紙の等級と四隅の護符。型紙が写っていなければ None(フリーハンドとして読む・S6)。"""
    reply: _Alignment = recognizer.ask(
        [_small_jpeg(photo), {"type": "text", "text": ALIGN_PROMPT}],
        _Alignment,
    )
    if reply.grade == "none" or reply.grade not in GRADES:
        return None
    circles = [i for i, c in enumerate(reply.corners) if c.circle]
    if len(reply.corners) != 4 or len(circles) != 1:
        raise RecognizeError(
            f"四隅の護符を 4 つ（うち丸の印が 1 つ）見つけられません（護符 {len(reply.corners)} 個・丸 {len(circles)} 個）"
        )
    points = [(c.x * photo.width, c.y * photo.height) for c in reply.corners]
    return reply.grade, order_corners(points, circles[0])


def _locate(
    gray: Image.Image, sheet: Sheet, corners: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    """Claude が返した護符の位置を、護符の中の塗りの重心へ詰め直す。"""
    talismans = sheet.talismans()
    # 1 升の px のおおよそ(上辺の護符どうしの距離から)
    span = math.dist(corners[0], corners[1]) / (talismans[1][0] - talismans[0][0])
    return [refine_talisman(gray, p, span) for p in corners]


def _cells_of(
    gray: Image.Image, sheet: Sheet, refined: list[tuple[float, float]], to_photo: Sequence[float]
) -> list[_Ink]:
    talismans = sheet.talismans()
    p = RECTIFIED_CELL_PX
    side = round(2 * sheet.half * p)

    def out_px(x: float, y: float) -> tuple[float, float]:
        return ((x + sheet.half) * p, (y + sheet.half) * p)

    to_input = homography([out_px(*t) for t in talismans], refined)
    rectified = gray.transform(
        (side, side), Image.Transform.PERSPECTIVE, to_input, Image.Resampling.BICUBIC, fillcolor=255
    )
    inks: list[_Ink] = []
    for slot in sheet.slots:
        if slot.kind != "cell":
            continue
        x, y = out_px(*slot.center)
        inner = INK_INSET * p
        if is_blank(
            rectified.crop((round(x - inner), round(y - inner), round(x + inner), round(y + inner)))
        ):
            continue
        reach = 0.6 * p
        view = rectified.crop(
            (round(x - reach), round(y - reach), round(x + reach), round(y + reach))
        )
        view = view.resize((CELL_IMAGE_PX, CELL_IMAGE_PX), Image.Resampling.LANCZOS)
        inks.append(_Ink(slot, _png(view), _box(to_photo, slot.center)))
    return inks


def _cell_of(
    read: _CellRead | None, structs: Sequence[str] = _STRUCT_IDS
) -> tuple[str, str, list[str]] | None:
    """Claude の読み → (t, v, unsure)。空なら None。契約に合わない読みは「?」と迷いにする(場面グラフは人が直せる)。"""
    if read is None:
        return ("latin", "?", ["(読めませんでした)"])
    if read.t == "empty":
        return None
    valid = (
        (read.t == "latin" and len(read.v) == 1)
        or (read.t == "glyph" and read.v in _GLYPH_IDS)
        or (read.t == "struct" and read.v in structs)
    )
    if not valid:
        return ("latin", "?", [f"{read.t}:{read.v}"] + list(read.unsure))
    return (read.t, read.v, [u for u in read.unsure if u and u != read.v])


def _read_cells(
    inks: list[_Ink], recognizer: Recognizer
) -> list[tuple[str, str, list[str]] | None]:
    table = {
        **_image_block(_png(glyph_table()), "image/png"),
        "cache_control": {"type": "ephemeral"},
    }
    out: list[tuple[str, str, list[str]] | None] = []
    for start in range(0, len(inks), CELLS_PER_REQUEST):
        batch = inks[start : start + CELLS_PER_REQUEST]
        content: list[dict[str, Any]] = [
            table,
            {"type": "text", "text": CELLS_PROMPT},
        ]
        for n, ink in enumerate(batch, start=1):
            content.append(
                {"type": "text", "text": f"#{n} ({ink.slot.owner}, cell {ink.slot.index})"}
            )
            content.append(_image_block(ink.image, "image/png"))
        reply: _CellReads = recognizer.ask(content, _CellReads)
        by_number: dict[int, _CellRead] = {}
        for read in reply.cells:
            by_number.setdefault(read.n, read)
        out += [_cell_of(by_number.get(n)) for n in range(1, len(batch) + 1)]
    return out


def _assemble(
    sheet: Sheet,
    reads: dict[
        tuple[str, int], tuple[tuple[str, str, list[str]], tuple[float, float, float, float]]
    ],
    to_photo: Sequence[float],
) -> tuple[list[Figure], list[Band]]:
    def cells(owner: str) -> list[Cell]:
        found = []
        for slot in sheet.of(owner):
            hit = reads.get((owner, slot.index))
            if hit is not None:
                (t, v, unsure), box = hit
                found.append(Cell(t=t, v=v, unsure=unsure, box=box))  # type: ignore[arg-type]
        return found

    def is_cont(cell: Cell) -> bool:
        return cell.t == "glyph" and cell.v == "cont"

    strips = [o for o in sheet.owners() if o.startswith("strip")]
    strip_cells = {o: cells(o) for o in strips}
    queue = [o for o in strips if strip_cells[o]]
    figures: list[Figure] = []
    bands: list[Band] = []
    rings = {r.owner: r for r in sheet.rings}
    for owner in sheet.owners():
        if owner.startswith("strip"):
            continue
        band = cells(owner)
        if owner != "frame" and not band:
            continue  # 書かれていない環は図形ごと出さない(手順は番号の小さい環から詰めて使う)
        while band and is_cont(band[-1]) and queue:
            band = band[:-1] + strip_cells[queue.pop(0)]
        if owner == "frame":
            at = apply(to_photo, 0.0, 0.0)
            kind = "frame"
        else:
            ring = rings[owner]
            at = apply(to_photo, *ring.center)
            kind = "circle" if owner.startswith("c") else "rite"
            start = sheet.of(owner)[0]
            band = [Cell(t="struct", v=START_MARK, box=_box(to_photo, start.center))] + band
        figures.append(Figure(id=owner, kind=kind, at=(round(at[0], 1), round(at[1], 1))))
        bands.append(Band(owner=owner, cells=band))
    for owner in queue:  # どの銘帯にもつながらなかった続きの帯(構文解析器が JIN305 で知らせる)
        head = sheet.of(owner)[0]
        at = apply(to_photo, *head.center)
        figures.append(Figure(id=owner, kind="strip", at=(round(at[0], 1), round(at[1], 1))))
        bands.append(Band(owner=owner, cells=strip_cells[owner]))
    return figures, bands


def _box(
    to_photo: Sequence[float], center: tuple[float, float]
) -> tuple[float, float, float, float]:
    corners = [
        apply(to_photo, center[0] + dx, center[1] + dy) for dx in (-0.5, 0.5) for dy in (-0.5, 0.5)
    ]
    return (
        round(min(c[0] for c in corners), 1),
        round(min(c[1] for c in corners), 1),
        round(max(c[0] for c in corners), 1),
        round(max(c[1] for c in corners), 1),
    )


def recognize_photo(data: bytes, *, recognizer: Recognizer | None = None) -> JinScene:
    """型紙に手で描いた陣の写真 → 場面グラフ。写真を Anthropic の API に送る(モジュールの docstring)。"""
    recognizer = recognizer or Recognizer()
    photo = load_photo(data)
    aligned = _align(photo, recognizer)
    if aligned is None:
        return _recognize_free(data, photo, recognizer)
    grade, corners = aligned
    sheet = sheet_layout(grade)
    gray = photo.convert("L")
    refined = _locate(gray, sheet, corners)
    to_photo = homography(sheet.talismans(), refined)
    inks = _cells_of(gray, sheet, refined, to_photo)
    reads: dict[
        tuple[str, int], tuple[tuple[str, str, list[str]], tuple[float, float, float, float]]
    ] = {}
    for ink, read in zip(inks, _read_cells(inks, recognizer), strict=True):
        if read is not None:
            reads[(ink.slot.owner, ink.slot.index)] = (read, ink.box)
    figures, bands = _assemble(sheet, reads, to_photo)
    return JinScene(
        jinscene=1,
        sheet=grade,
        image=ImageInfo(
            sha256=hashlib.sha256(data).hexdigest(), width=photo.width, height=photo.height
        ),
        figures=figures,
        bands=bands,
    )


# ---- フリーハンド(モード 1・陣書き S6) -----------------------------------------------------------

#: 正面化した額縁の一辺の px の範囲(写真の中の額縁の大きさに合わせ、この範囲に収める)
FREE_SIDE_MIN = 800
FREE_SIDE_MAX = 3000
#: 塊の画像: 字の大きさの 1.2 倍を CELL_IMAGE_PX にする倍率で縮め、長辺はこの倍数まで
FREE_BLOB_MAX = 4
#: 塊の切り出しの余白(字の大きさに対する比)
FREE_BLOB_PAD = 0.25

FREE_SYSTEM = f"""You read a hand-drawn "Jin" magic circle drawn freehand on blank paper (no printed template).
The drawing is a square frame containing one or more circles. Around each circle runs an inscription: symbols written one by one
along concentric circular lines ("turns"), starting at a start mark at the top of the circle and going clockwise. The frame
itself carries a short inscription written along the inside of its edges, starting at the top-left corner and going clockwise.
Each inscription symbol is drawn by hand with a pen and is exactly one of:
- a single Latin/digit/kana/kanji character (names, numbers and string contents), or
- one of the special glyphs shown in the glyph table image (answer its id, e.g. "add", "sep", "quote_l", "loop_count"), or
- one of the structure marks shown in the same table (ids starting with "s_", e.g. "s_set", "s_rite"; a small shape inside a
  double square frame), or the start mark (id "start", a horizontal bar with a downward-pointing triangle under it,
  shown as "start" in the glyph table) that begins every circle's inscription.
Lines, circles, arrows and small shapes of the diagram inside each circle, and the decorations in the frame corners, are not
inscription symbols.
Never guess a whole word: read each symbol on its own.
Glyph ids: {", ".join(_GLYPH_IDS)}.
Structure mark ids: {", ".join(_STRUCT_IDS + [START_MARK])}."""

FRAME_PROMPT = """This photo shows a magic circle drawn by hand on paper, inside a hand-drawn square frame.
Return found (false if there is no such square frame) and the four corners of the frame as fractions of the image width (x) and
height (y), from 0 to 1, in this order: top-left, top-right, bottom-right, bottom-left of the drawing. Judge "top" from the drawing
itself, not from the photo: the handwriting is upright when the drawing is the right way up, and every circle's start mark sits at
the top of its circle."""

LAYOUT_PROMPT = """This image is the square frame of the drawing, straightened so that its corners are the image corners.
Return, as fractions of the image side (0 to 1):
- cell: the typical height of one handwritten inscription symbol
- frame_rows: for each row of the frame's inscription, the distance from the frame edge to the middle of that row of symbols
  (outermost row first; [] if the frame has no inscription)
- rings: one entry per circle that has an inscription around it: x, y (the circle's centre), radii (the radius of the middle line
  of each turn of its inscription, innermost first) and start (the centre of its start mark; [] if you cannot see one)."""

BLOBS_PROMPT = """Each numbered image below is a piece of an inscription. It usually holds one symbol, but may hold several symbols
(read them in the order given in its label: "left to right", "top to bottom", ...) or none (a stray line or a piece of the
diagram). For every image return n (its number) and symbols: one entry per symbol with t ("latin" for one character, "glyph" for
a glyph id, "struct" for a structure mark id or "start"), v (the character or the id) and unsure (other plausible readings, most
likely first; [] when you are sure). Return symbols [] when the image holds no inscription symbol."""


class _Point(BaseModel):
    x: float
    y: float


class _FreeFrame(BaseModel):
    found: bool
    corners: list[_Point]


class _FreeRing(BaseModel):
    x: float
    y: float
    radii: list[float]
    start: list[_Point]


class _FreeLayout(BaseModel):
    cell: float
    frame_rows: list[float]
    rings: list[_FreeRing]


class _Symbol(BaseModel):
    t: Literal["latin", "glyph", "struct"]
    v: str
    unsure: list[str]


class _BlobRead(BaseModel):
    n: int
    symbols: list[_Symbol]


class _BlobReads(BaseModel):
    blobs: list[_BlobRead]


_FREE_STRUCTS = [*_STRUCT_IDS, START_MARK]

Point = tuple[float, float]


@dataclass(frozen=True)
class FreeRing:
    """正面図の上の環 1 つ(Claude の値を詰め直した後): 中心・周の半径(内から)・始まりの角度(度)。"""

    center: Point
    radii: list[float]
    start: float


@dataclass(frozen=True)
class FreeInk:
    """読みに送る墨の塊 1 つ。owner は環の添字(`int`)か `"frame"`。"""

    owner: int | str
    blob: freehand.Blob
    image: str  # base64 PNG
    box: tuple[float, float, float, float]  # 写真の座標


@dataclass(frozen=True)
class FreeGeometry:
    """フリーハンドの写真から切り出したもの(読みの前まで)。テストの応答の合成もこれを使う。"""

    side: int
    to_photo: tuple[float, ...]  # 正面図の px → 写真の px
    cell: float
    rings: list[FreeRing]
    inks: list[FreeInk]


def _free_corners(photo: Image.Image, recognizer: Recognizer) -> list[Point]:
    reply: _FreeFrame = recognizer.ask(
        [_small_jpeg(photo), {"type": "text", "text": FRAME_PROMPT}], _FreeFrame, FREE_SYSTEM
    )
    if not reply.found:
        raise RecognizeError("写真に型紙も、フリーハンドの陣の額縁（四角い枠）も見つかりません")
    if len(reply.corners) != 4:
        raise RecognizeError(f"額縁の四隅を 4 つ見つけられません（{len(reply.corners)} 個）")
    return [(c.x * photo.width, c.y * photo.height) for c in reply.corners]


def rectify_frame(corners: Sequence[Point]) -> tuple[int, tuple[float, ...]]:
    """額縁の四隅(左上・右上・右下・左下・写真の px)→ (正面図の一辺 px, 正面図 → 写真の射影)。"""
    mean = sum(math.dist(corners[i], corners[(i + 1) % 4]) for i in range(4)) / 4.0
    side = max(FREE_SIDE_MIN, min(FREE_SIDE_MAX, round(mean)))
    return side, homography(_square(side), corners)


def _rectify(
    gray: Image.Image, corners: Sequence[Point]
) -> tuple[int, tuple[float, ...], Image.Image]:
    side, to_photo = rectify_frame(corners)
    rect = gray.transform(
        (side, side), Image.Transform.PERSPECTIVE, to_photo, Image.Resampling.BICUBIC, fillcolor=255
    )
    return side, to_photo, rect


def _upright(layout: _FreeLayout) -> int:
    """正面図の何回 90° 右に回った位置に描き手の上があるか(0〜3)。額縁の中心に最も近い環の始まりの印の向きで決める
    (完全陣の配置では root の陣が中央にあり、始まりの印は 12 時にある)。印が無ければ Claude の向きのまま(0)。"""
    marked = [r for r in layout.rings if r.start]
    if not marked:
        return 0
    ring = min(marked, key=lambda r: math.dist((r.x, r.y), (0.5, 0.5)))
    angle = math.degrees(math.atan2(ring.start[0].y - ring.y, ring.start[0].x - ring.x))
    return round(((angle - freehand.TOP) % 360.0) / 90.0) % 4


def _blob_image(rect: Image.Image, box: tuple[int, int, int, int], cell: float) -> str:
    pad = FREE_BLOB_PAD * cell
    x0, y0, x1, y1 = box
    view = rect.crop((round(x0 - pad), round(y0 - pad), round(x1 + pad), round(y1 + pad)))
    scale = CELL_IMAGE_PX / (1.2 * cell)
    limit = FREE_BLOB_MAX * CELL_IMAGE_PX
    width = max(8, min(limit, round(view.width * scale)))
    height = max(8, min(limit, round(view.height * scale)))
    return _png(view.resize((width, height), Image.Resampling.LANCZOS))


def _photo_box(
    to_photo: Sequence[float], box: tuple[int, int, int, int]
) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = box
    corners = [apply(to_photo, x, y) for x in (x0, x1) for y in (y0, y1)]
    return (
        round(min(c[0] for c in corners), 1),
        round(min(c[1] for c in corners), 1),
        round(max(c[0] for c in corners), 1),
        round(max(c[1] for c in corners), 1),
    )


def free_geometry(photo: Image.Image, recognizer: Recognizer) -> FreeGeometry:
    """額縁の四隅 → 正面化 → 環の形 → 詰め直し → 切り分け(Claude への要求は 2 本)。"""
    gray = photo.convert("L")
    corners = _free_corners(photo, recognizer)
    side, to_photo, rect = _rectify(gray, corners)
    layout: _FreeLayout = recognizer.ask(
        [_small_jpeg(rect), {"type": "text", "text": LAYOUT_PROMPT}], _FreeLayout, FREE_SYSTEM
    )
    turn = _upright(layout)
    if turn:
        # 描き手の上が正面図の右(turn = 1)なら、左上は今の右上。正面図を作り直し、Claude の座標を新しい正面図へ写す
        old = to_photo
        corners = corners[turn:] + corners[:turn]
        side, to_photo, rect = _rectify(gray, corners)
        back = homography(corners, _square(side))

        def move(x: float, y: float) -> Point:
            px, py = apply(back, *apply(old, x * side, y * side))
            return (px / side, py / side)

        for ring in layout.rings:
            ring.x, ring.y = move(ring.x, ring.y)
            for point in ring.start:
                point.x, point.y = move(point.x, point.y)
    cell = max(4.0, layout.cell * side)
    rings: list[FreeRing] = []
    for ring in layout.rings:
        radii = sorted(r * side for r in ring.radii if r > 0.0)
        center, radii = freehand.refine_ring(rect, (ring.x * side, ring.y * side), radii, cell)
        if ring.start:
            sx, sy = ring.start[0].x * side, ring.start[0].y * side
            start = math.degrees(math.atan2(sy - center[1], sx - center[0]))
        else:
            start = freehand.TOP  # 始まりの印が無い環(構文解析器が JIN301 で知らせる)
        rings.append(FreeRing(center, radii, start))
    inks: list[FreeInk] = []
    for index, ring in enumerate(rings):
        for blobs in freehand.ring_turns(rect, ring.center, ring.radii, ring.start, cell):
            for blob in blobs:
                inks.append(
                    FreeInk(
                        index,
                        blob,
                        _blob_image(rect, blob.box, cell),
                        _photo_box(to_photo, blob.box),
                    )
                )
    rows = sorted(r * side for r in layout.frame_rows if r > 0.0)
    for k, row in enumerate(rows):
        insets = freehand.refine_inset(rect, side, row, cell)
        width = freehand.band_half_width(rows, k, cell)
        for blob in freehand.frame_blobs(rect, side, insets, width, cell):
            inks.append(
                FreeInk(
                    "frame", blob, _blob_image(rect, blob.box, cell), _photo_box(to_photo, blob.box)
                )
            )
    return FreeGeometry(side, to_photo, cell, rings, inks)


def _square(side: int) -> list[Point]:
    return [(0.0, 0.0), (float(side), 0.0), (float(side), float(side)), (0.0, float(side))]


def _read_blobs(
    inks: list[FreeInk], recognizer: Recognizer
) -> list[list[tuple[str, str, list[str]]]]:
    table = {
        **_image_block(_png(glyph_table(with_start=True)), "image/png"),
        "cache_control": {"type": "ephemeral"},
    }
    out: list[list[tuple[str, str, list[str]]]] = []
    for begin in range(0, len(inks), CELLS_PER_REQUEST):
        batch = inks[begin : begin + CELLS_PER_REQUEST]
        content: list[dict[str, Any]] = [table, {"type": "text", "text": BLOBS_PROMPT}]
        for n, ink in enumerate(batch, start=1):
            content.append({"type": "text", "text": f"#{n} ({ink.blob.direction})"})
            content.append(_image_block(ink.image, "image/png"))
        reply: _BlobReads = recognizer.ask(content, _BlobReads, FREE_SYSTEM)
        by_number: dict[int, _BlobRead] = {}
        for read in reply.blobs:
            by_number.setdefault(read.n, read)
        for n in range(1, len(batch) + 1):
            read = by_number.get(n)
            if read is None:
                out.append([("latin", "?", ["(読めませんでした)"])])
                continue
            symbols = []
            for symbol in read.symbols:
                cell = _cell_of(
                    _CellRead(n=n, t=symbol.t, v=symbol.v, unsure=symbol.unsure), _FREE_STRUCTS
                )
                if cell is not None:
                    symbols.append(cell)
            out.append(symbols)
    return out


def _recognize_free(data: bytes, photo: Image.Image, recognizer: Recognizer) -> JinScene:
    geometry = free_geometry(photo, recognizer)
    reads = _read_blobs(geometry.inks, recognizer)
    ring_cells: list[list[Cell]] = [[] for _ in geometry.rings]
    frame_cells: list[Cell] = []
    for ink, symbols in zip(geometry.inks, reads, strict=True):
        cells = [Cell(t=t, v=v, unsure=unsure, box=ink.box) for t, v, unsure in symbols]  # type: ignore[arg-type]
        (frame_cells if ink.owner == "frame" else ring_cells[ink.owner]).extend(cells)  # type: ignore[index]
    texts = [
        freehand.RingText(
            ring.center, apply(geometry.to_photo, *ring.center), cells, max(ring.radii, default=0.0)
        )
        for ring, cells in zip(geometry.rings, ring_cells, strict=True)
    ]
    middle = (geometry.side / 2.0, geometry.side / 2.0)
    figures, bands = freehand.assemble(
        texts, frame_cells, middle, apply(geometry.to_photo, *middle)
    )
    return JinScene(
        jinscene=1,
        sheet="free",
        image=ImageInfo(
            sha256=hashlib.sha256(data).hexdigest(), width=photo.width, height=photo.height
        ),
        figures=figures,
        bands=bands,
    )


__all__ = [
    "MODEL",
    "FreeGeometry",
    "RecognizeError",
    "Recognizer",
    "apply",
    "free_geometry",
    "glyph_table",
    "homography",
    "is_blank",
    "load_photo",
    "order_corners",
    "recognize_photo",
    "rectify_frame",
    "refine_talisman",
]
