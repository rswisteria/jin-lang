"""テスト用(jin-glyph と jin-cli のテストが共有する): 型紙の手本(`jin render x.jin --sheet S`)を斜めから撮った写真に見立てた JPEG と、Claude の応答の再生。

- `synthetic_photo`: 手本の SVG → cairosvg の PNG → 射影変換で台形に歪め(右上が奥・少し回る)、灰色の机に置いた JPEG
- `synthetic_responses`: その写真に対する Claude の応答(Messages API の生の JSON)を、正解(`fill_sheet`)から組む。
  護符の位置は正解から 0.25 升ずらし、順番も入れ替える(認識器の詰め直しと並べ替えを通すため)
- `replay_client`: 生の HTTP 応答を順に返す `httpx2.MockTransport` を持つ `anthropic.Anthropic`(SDK の parse の経路を通す)

**ここの応答は本物の API の録画ではない**(2026-10-03 の実装時に API キーが無かった)。形は Messages API の応答
(thinking ブロック + text ブロックの JSON・`stop_reason`・`usage`)に合わせてあり、本物の録画は
`scripts/glyph_recognize_eval.py --record` で取れる(手動・CI では回さない)。
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from typing import Any

import anthropic
import cairosvg
import httpx2
from jin_core.v2.model import JinFileV2
from jin_glyph.recognize import apply, homography
from jin_render.v2 import geometry as g2
from jin_render.v2.sheet import render_sheet
from jin_render.v2.sheet_layout import fill_sheet, sheet_layout
from PIL import Image

_ANTHROPIC = anthropic.Anthropic

#: 手本を PNG にする倍率(1 升 60 px。スマホで A3 を撮ると 1 升 60〜70 px)
SCALE = 5.0
#: 写真(机)の大きさ(手本の一辺に対する比)と、型紙の四隅(左上・右上・右下・左下)の置き場所(写真の幅・高さに対する比)
CANVAS = (1.25, 1.2)
PLACE = ((0.08, 0.07), (0.93, 0.10), (0.90, 0.94), (0.06, 0.90))
DESK = 150
#: Claude が返す護符の位置のずれ(升)
ALIGN_ERROR = 0.25


def _sheet_to_photo(grade: str) -> tuple[tuple[float, ...], int, tuple[int, int]]:
    """(手本の画素 → 写真の画素の射影, 手本の一辺 px, 写真の大きさ)。"""
    side = round(2 * sheet_layout(grade).half * g2.FULL_CELL_PX * SCALE)  # type: ignore[arg-type]
    size = (round(side * CANVAS[0]), round(side * CANVAS[1]))
    src = [(0.0, 0.0), (side, 0.0), (side, side), (0.0, side)]
    dst = [(fx * size[0], fy * size[1]) for fx, fy in PLACE]
    return homography(src, dst), side, size


def synthetic_photo(model: JinFileV2, grade: str = "S") -> bytes:
    svg = render_sheet(grade, model)  # type: ignore[arg-type]
    png = cairosvg.svg2png(bytestring=svg.encode(), scale=SCALE, background_color="white")
    sheet_image = Image.open(io.BytesIO(png)).convert("L")
    _, side, size = _sheet_to_photo(grade)
    src = [(fx * size[0], fy * size[1]) for fx, fy in PLACE]
    dst = [(0.0, 0.0), (side, 0.0), (side, side), (0.0, side)]
    photo = sheet_image.transform(
        size,
        Image.Transform.PERSPECTIVE,
        homography(src, dst),
        Image.Resampling.BICUBIC,
        fillcolor=DESK,
    )
    buffer = io.BytesIO()
    photo.convert("RGB").save(buffer, "JPEG", quality=88)
    return buffer.getvalue()


def talisman_truth(grade: str = "S") -> list[tuple[float, float]]:
    """護符の中心の写真の座標(左上・右上・左下・右下)。"""
    to_photo, _, _ = _sheet_to_photo(grade)
    sheet = sheet_layout(grade)  # type: ignore[arg-type]
    unit = g2.FULL_CELL_PX * SCALE
    return [
        apply(to_photo, (x + sheet.half) * unit, (y + sheet.half) * unit)
        for x, y in sheet.talismans()
    ]


def _message(payload: dict[str, Any], n: int) -> dict[str, Any]:
    return {
        "id": f"msg_synthetic_{n:02d}",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": [
            {"type": "thinking", "thinking": "", "signature": "synthetic"},
            {"type": "text", "text": json.dumps(payload, ensure_ascii=False)},
        ],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "stop_details": None,
        "usage": {"input_tokens": 1000, "output_tokens": 200},
    }


def synthetic_responses(
    model: JinFileV2, grade: str = "S", per_request: int = 60
) -> list[dict[str, Any]]:
    """位置合わせ 1 本 + 升の読み(per_request 升ずつ)の応答。"""
    _, _, size = _sheet_to_photo(grade)
    sheet = sheet_layout(grade)  # type: ignore[arg-type]
    unit = g2.FULL_CELL_PX * SCALE
    shift = ALIGN_ERROR * unit
    truth = talisman_truth(grade)
    # 右下・左上・右上・左下 の順で返す(認識器が丸の印から並べ直す)
    corners = [
        {
            "x": (truth[i][0] + shift) / size[0],
            "y": (truth[i][1] - shift) / size[1],
            "circle": i == 1,
        }
        for i in (3, 0, 1, 2)
    ]
    out = [_message({"grade": grade, "corners": corners}, 0)]
    filled = fill_sheet(sheet, model)
    reads = [filled[(s.owner, s.index)] for s in sheet.slots if (s.owner, s.index) in filled]
    for start in range(0, len(reads), per_request):
        batch = reads[start : start + per_request]
        cells = [{"n": n, "t": c.t, "v": c.v, "unsure": []} for n, c in enumerate(batch, start=1)]
        out.append(_message({"cells": cells}, len(out)))
    return out


def replay_client(
    responses: list[dict[str, Any]], requests: list[dict[str, Any]]
) -> anthropic.Anthropic:
    """responses を順に返し、受けた要求の本文を requests に積む client。要求が余れば落ちる(送信の数を固定する)。"""
    queue = list(responses)

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/messages"
        requests.append({"headers": dict(request.headers), "body": json.loads(request.content)})
        assert queue, "録画した応答より多くの要求が出ました"
        return httpx2.Response(200, json=queue.pop(0), headers={"request-id": "req_synthetic"})

    return _client(handler)


def refusing_transport_client() -> anthropic.Anthropic:
    """要求が 1 つでも出たら落ちる client(`--offline` が何も送らないことの検査)。"""

    def handler(request: httpx2.Request) -> httpx2.Response:
        raise AssertionError(f"送信してはいけない要求です: {request.url}")

    return _client(handler)


def _client(handler: Callable[[httpx2.Request], httpx2.Response]) -> anthropic.Anthropic:
    # CLI のテストは `anthropic.Anthropic` を差し替えるので、import した時点の本物のクラスで作る
    return _ANTHROPIC(
        api_key="test-key",
        max_retries=0,
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
    )


# ---- フリーハンド(陣書き S6) -------------------------------------------------------------------
#
# 白紙に描いた陣の写真の代わりに、完全陣(`jin render --full`・手描きの手本と同じ視覚文法)を斜めから撮った JPEG を使う。
# 応答は正解(完全陣の配置 `full_layout` と銘文 `inscribe`)から組み、Claude の座標には FREE_ERROR 升のずれを入れる
# (認識器が墨で詰め直すことを通すため・設計書 §9 #38 と同じ)。升の読みは、認識器と同じ切り分け(`free_geometry`)で
# 出た塊ごとに、その中にある正解の升を並べて返す。正解の升が 2 つの塊に割れたら(字を割る切り分け)ここで落とす。

#: 完全陣を PNG にする倍率(1 升 36 px)
FREE_SCALE = 3.0
#: 写真(机)の大きさ(完全陣の一辺に対する比)と、額縁の四隅(描き手の左上・右上・右下・左下)の置き場所
FREE_CANVAS = (1.2, 1.25)
FREE_PLACE = ((0.09, 0.08), (0.92, 0.05), (0.95, 0.92), (0.06, 0.94))
#: Claude が返す座標のずれ(升)
FREE_ERROR = 0.3


def _free_frame(model: JinFileV2) -> tuple[float, int, tuple[int, int]]:
    """(完全陣の半辺(升), 完全陣の一辺 px, 写真の大きさ)。"""
    from jin_render.v2.full_layout import place

    half = place(model).half
    side = round(2 * half * g2.FULL_CELL_PX * FREE_SCALE)
    return half, side, (round(side * FREE_CANVAS[0]), round(side * FREE_CANVAS[1]))


def _free_place(size: tuple[int, int], turn: int) -> list[tuple[float, float]]:
    """額縁の四隅の写真の px。turn = 1 なら写真の中で陣が 90° 右に回っている(描き手の左上が写真の右上の位置)。"""
    place = [(fx * size[0], fy * size[1]) for fx, fy in FREE_PLACE]
    return place[-turn:] + place[:-turn] if turn else place


def synthetic_free_photo(model: JinFileV2, turn: int = 0) -> bytes:
    from jin_render.v2.full import render_full

    png = cairosvg.svg2png(
        bytestring=render_full(model).encode(), scale=FREE_SCALE, background_color="white"
    )
    drawing = Image.open(io.BytesIO(png)).convert("L")
    _, side, size = _free_frame(model)
    square = [(0.0, 0.0), (side, 0.0), (side, side), (0.0, side)]
    photo = drawing.transform(
        size,
        Image.Transform.PERSPECTIVE,
        homography(_free_place(size, turn), square),
        Image.Resampling.BICUBIC,
        fillcolor=DESK,
    )
    buffer = io.BytesIO()
    photo.convert("RGB").save(buffer, "JPEG", quality=88)
    return buffer.getvalue()


def _free_truth(
    model: JinFileV2,
) -> tuple[list[dict[str, Any]], list[tuple[Any, tuple[float, float]]]]:
    """正解: 環ごとの {center, cells: [(InkCell, 周, 中心)]}(升の単位・完全陣の座標)と、額縁の升 [(InkCell, 中心)]。"""
    from jin_render.v2.full import frame_positions
    from jin_render.v2.full_layout import circle_inner, place, ring_cells, rite_inner
    from jin_render.v2.inscribe import circle_ring, frame_band, rite_ring

    placement = place(model)
    rings = []
    for ci, (x, y) in placement.circles.items():
        placed = ring_cells(circle_ring(model, ci), x, y, circle_inner())
        rings.append({"center": (x, y), "inner": circle_inner(), "cells": placed})
    for (ci, ri), (x, y) in placement.rites.items():
        placed = ring_cells(rite_ring(model, ci, ri), x, y, rite_inner())
        rings.append({"center": (x, y), "inner": rite_inner(), "cells": placed})
    cells = frame_band(model)
    frame = list(zip(cells, frame_positions(len(cells), placement.half), strict=True))
    return rings, frame


class _Scripted:
    """`Recognizer` の代わりに、組んだ応答の Pydantic を順に返す(`free_geometry` を API 無しで回す)。"""

    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = list(payloads)

    def ask(self, content: Any, schema: Any, system: str | None = None) -> Any:
        return schema.model_validate(self.payloads.pop(0))


def synthetic_free_responses(
    model: JinFileV2, turn: int = 0, misjudge: int = 0, per_request: int = 60
) -> list[dict[str, Any]]:
    """型紙の位置合わせ(型紙なし)+ 額縁の四隅 + 環の形 + 塊の読み(per_request 個ずつ)の応答。

    `misjudge` は Claude が描き手の上を取り違えた数(額縁の四隅をその数だけずらして返す。認識器が始まりの印で直す)。
    """
    from jin_glyph.recognize import free_geometry, rectify_frame

    half, side, size = _free_frame(model)
    unit = side / (2.0 * half)  # 完全陣の 1 升の px
    square = [(0.0, 0.0), (side, 0.0), (side, side), (0.0, side)]
    to_photo = homography(square, _free_place(size, turn))

    def photo_of(x: float, y: float) -> tuple[float, float]:
        return apply(to_photo, (x + half) * unit, (y + half) * unit)

    shift = FREE_ERROR * unit
    corners_photo = _free_place(size, turn)
    claimed = corners_photo[misjudge:] + corners_photo[:misjudge]
    frame_reply = {
        "found": True,
        "corners": [{"x": (x + shift) / size[0], "y": (y - shift) / size[1]} for x, y in claimed],
    }
    rect_side, rect_to_photo = rectify_frame(claimed)
    to_rect = homography([apply(rect_to_photo, *p) for p in _square(rect_side)], _square(rect_side))
    cell = unit * rect_side / side  # 正面図の 1 升の px(遠近の歪みはここでは無視する)

    def rect_of(x: float, y: float) -> tuple[float, float]:
        return apply(to_rect, *photo_of(x, y))

    def frac(point: tuple[float, float], error: float = FREE_ERROR) -> dict[str, float]:
        return {
            "x": (point[0] + error * cell) / rect_side,
            "y": (point[1] + error * cell) / rect_side,
        }

    rings, frame = _free_truth(model)
    layout_rings = []
    for ring in rings:
        turns = max(rc.ring for rc in ring["cells"]) + 1
        radii = [
            ((ring["inner"] + 0.5 + k * g2.FULL_RING_PITCH) * cell + 0.25 * cell) / rect_side
            for k in range(turns)
        ]
        start = ring["cells"][0].center
        layout_rings.append(
            {"radii": radii, "start": [frac(rect_of(*start))], **frac(rect_of(*ring["center"]))}
        )
    layout_reply = {
        "cell": 1.1 * cell / rect_side,
        "frame_rows": [(1.5 + FREE_ERROR) * cell / rect_side] if frame else [],
        "rings": layout_rings,
    }
    photo = load_free(synthetic_free_photo(model, turn))
    geometry = free_geometry(photo, _Scripted([frame_reply, layout_reply]))  # type: ignore[arg-type]

    # 正解の升(写真の中の中心)を、同じ持ち主の塊に割り当てる
    from_photo = homography(
        [apply(geometry.to_photo, *p) for p in _square(geometry.side)], _square(geometry.side)
    )
    reach = 0.5 * geometry.cell
    truth: list[tuple[Any, list[tuple[Any, tuple[float, float]]]]] = [
        (k, [(rc.cell, apply(from_photo, *photo_of(*rc.center))) for rc in ring["cells"]])
        for k, ring in enumerate(rings)
    ]
    truth.append(("frame", [(c, apply(from_photo, *photo_of(*at))) for c, at in frame]))
    reads: list[list[Any]] = [[] for _ in geometry.inks]
    for owner, cells in truth:
        mine = [i for i, ink in enumerate(geometry.inks) if ink.owner == owner]
        for order, (ink_cell, (x, y)) in enumerate(cells):
            hits = [
                i
                for i in mine
                if geometry.inks[i].blob.box[0] - reach <= x <= geometry.inks[i].blob.box[2] + reach
                and geometry.inks[i].blob.box[1] - reach
                <= y
                <= geometry.inks[i].blob.box[3] + reach
            ]
            inside = [
                i
                for i in hits
                if geometry.inks[i].blob.box[0] <= x <= geometry.inks[i].blob.box[2]
                and geometry.inks[i].blob.box[1] <= y <= geometry.inks[i].blob.box[3]
            ]
            chosen = inside or hits
            if len(chosen) != 1:
                raise AssertionError(
                    f"正解の升 {ink_cell.t}:{ink_cell.v}({owner})が切り分けの塊 {len(chosen)} 個に当たりました"
                )
            reads[chosen[0]].append((order, ink_cell))
    for i, ink in enumerate(geometry.inks):
        if reads[i]:
            continue
        x0, y0, x1, y1 = ink.blob.box
        mid = ((x0 + x1) / 2, (y0 + y1) / 2)
        for owner, cells in truth:
            if owner != ink.owner:
                continue
            for ink_cell, (x, y) in cells:
                if (
                    abs(mid[0] - x) < 0.35 * geometry.cell
                    and abs(mid[1] - y) < 0.35 * geometry.cell
                ):
                    raise AssertionError(
                        f"正解の升 {ink_cell.t}:{ink_cell.v} が切り分けで割れました"
                    )
    out = [
        _message({"grade": "none", "corners": []}, 0),
        _message(frame_reply, 1),
        _message(layout_reply, 2),
    ]
    blobs = [
        {
            "n": 0,
            "symbols": [
                {"t": c.t, "v": c.v, "unsure": []} for _, c in sorted(read, key=lambda r: r[0])
            ],
        }
        for read in reads
    ]
    for begin in range(0, len(blobs), per_request):
        batch = blobs[begin : begin + per_request]
        for n, blob in enumerate(batch, start=1):
            blob["n"] = n
        out.append(_message({"blobs": batch}, len(out)))
    return out


def _square(side: float) -> list[tuple[float, float]]:
    return [(0.0, 0.0), (float(side), 0.0), (float(side), float(side)), (0.0, float(side))]


def load_free(data: bytes) -> Image.Image:
    from jin_glyph.recognize import load_photo

    return load_photo(data)
