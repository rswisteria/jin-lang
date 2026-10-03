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
