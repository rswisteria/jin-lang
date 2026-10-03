"""Claude 認識器(`jin_glyph.recognize`・陣書き S4)。ネットワークと API キーは使わない。

Claude の応答は `tests/fixtures/recognize/` の生の Messages API の JSON を `httpx2.MockTransport` で返す
(SDK の `beta.messages.parse` の経路をそのまま通す)。fixture は**本物の録画ではなく正解から合成したもの**で
(`glyph_photo.synthetic_responses`・2026-10-03 の実装時に API キーが無かった)、ずれたら `UPDATE_RECORDINGS=1` で書き直す。
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import pytest
from jin_core.canonical import dumps
from jin_core.check import check_text
from jin_core.v2.model import JinFileV2
from jin_glyph.parse import parse_scene
from jin_glyph.recognize import (
    FALLBACK_BETA,
    MODEL,
    RecognizeError,
    Recognizer,
    _assemble,
    _cell_of,
    _CellRead,
    apply,
    glyph_table,
    homography,
    is_blank,
    order_corners,
    recognize_photo,
)
from jin_render.v2.sheet_layout import sheet_layout
from PIL import Image, ImageDraw

from tests.glyph_photo import (
    _message,
    refusing_transport_client,
    replay_client,
    synthetic_photo,
    synthetic_responses,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
RECORDINGS = REPO_ROOT / "tests" / "fixtures" / "recognize" / "fib-S.synthetic"


def load(name: str) -> JinFileV2:
    path = REPO_ROOT / "examples-v2" / name / f"{name}.jin"
    model = check_text(path.read_text(encoding="utf-8"), path.name).model
    assert isinstance(model, JinFileV2)
    return model


def source(name: str) -> str:
    return (REPO_ROOT / "examples-v2" / name / f"{name}.jin").read_text(encoding="utf-8")


def recordings() -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(RECORDINGS.glob("*.json"))]


@pytest.fixture(scope="module")
def fib_photo() -> bytes:
    return synthetic_photo(load("fib"))


# ---- 純関数 -------------------------------------------------------------------------------------


def test_homography_maps_the_four_points_and_inverts() -> None:
    src = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    dst = [(103.0, 51.0), (980.0, 120.0), (930.0, 1004.0), (61.0, 950.0)]
    forward = homography(src, dst)
    for a, b in zip(src, dst, strict=True):
        assert apply(forward, *a) == pytest.approx(b, abs=1e-6)
    back = homography(dst, src)
    assert apply(back, *apply(forward, 3.0, 7.0)) == pytest.approx((3.0, 7.0), abs=1e-6)


def test_collinear_corners_are_refused() -> None:
    with pytest.raises(RecognizeError):
        homography([(0, 0), (1, 1), (2, 2), (3, 3)], [(0, 0), (1, 0), (1, 1), (0, 1)])


@pytest.mark.parametrize("turn", [0, 1, 2, 3])
def test_corners_are_ordered_from_the_circle_whatever_the_photo_rotation(turn: int) -> None:
    """型紙の 左上・右上・左下・右下 に並べ直す。写真が 90° ずつ回っていても丸の護符が右上。"""
    sheet = [(0.0, 0.0), (100.0, 0.0), (0.0, 100.0), (100.0, 100.0)]  # TL TR BL BR

    def rotate(p: tuple[float, float]) -> tuple[float, float]:
        x, y = p
        for _ in range(turn):
            x, y = 100.0 - y, x  # 90° 時計回り
        return (x, y)

    photo = [rotate(p) for p in sheet]
    scrambled = [photo[3], photo[0], photo[1], photo[2]]
    assert order_corners(scrambled, circle=2) == photo


def test_a_blank_cell_and_an_inked_cell() -> None:
    blank = Image.new("L", (40, 40), 230)
    assert is_blank(blank)
    inked = blank.copy()
    ImageDraw.Draw(inked).line((8, 8, 32, 32), fill=20, width=3)
    assert not is_blank(inked)


def test_the_glyph_table_is_deterministic() -> None:
    assert glyph_table().tobytes() == glyph_table().tobytes()


def test_a_reading_outside_the_contract_becomes_a_question_mark_with_the_reading_kept() -> None:
    assert _cell_of(None) == ("latin", "?", ["(読めませんでした)"])
    assert _cell_of(_CellRead(n=1, t="empty", v="", unsure=[])) is None
    assert _cell_of(_CellRead(n=1, t="glyph", v="plus", unsure=["add"])) == (
        "latin",
        "?",
        ["glyph:plus", "add"],
    )
    assert _cell_of(_CellRead(n=1, t="latin", v="ab", unsure=[]))[1] == "?"
    assert _cell_of(_CellRead(n=1, t="latin", v="1", unsure=["l", "1", ""])) == (
        "latin",
        "1",
        ["l"],
    )


# ---- 写真 → 場面グラフ(録画の再生) ------------------------------------------------------------


def test_the_recorded_responses_match_their_generator() -> None:
    """fixture は正解から合成した応答。ずれたら UPDATE_RECORDINGS=1 で書き直す。"""
    expected = synthetic_responses(load("fib"))
    if os.environ.get("UPDATE_RECORDINGS"):
        RECORDINGS.mkdir(parents=True, exist_ok=True)
        for old in RECORDINGS.glob("*.json"):
            old.unlink()
        for n, body in enumerate(expected):
            name = "align" if n == 0 else "cells"
            text = json.dumps(body, ensure_ascii=False, indent=2) + "\n"
            (RECORDINGS / f"{n:02d}-{name}.json").write_text(text, encoding="utf-8")
    assert recordings() == expected


def test_a_photo_of_the_hand_written_fib_sheet_reads_back_to_fib(fib_photo: bytes) -> None:
    """完了の条件(設計書 §6 S4)の機械の側: 型紙の fib を撮った写真 → 場面グラフ → 構文解析で元の .jin とバイト一致。"""
    requests: list[dict] = []
    scene = recognize_photo(
        fib_photo, recognizer=Recognizer(client=replay_client(recordings(), requests))
    )
    model, diagnostics = parse_scene(scene, file="fib.jinscene.json")
    assert diagnostics == []
    assert model is not None and dumps(model) == source("fib")
    assert len(requests) == len(recordings())
    # 書かれていない環(手順 3 / 4)は図形ごと出さない
    assert [f.id for f in scene.figures] == ["frame", "c0", "r0_0", "r0_1"]
    assert scene.sheet == "S"


def test_the_requests_use_opus_with_default_fallbacks_and_structured_output(
    fib_photo: bytes,
) -> None:
    requests: list[dict] = []
    recognize_photo(fib_photo, recognizer=Recognizer(client=replay_client(recordings(), requests)))
    for request in requests:
        body = request["body"]
        assert body["model"] == MODEL == "claude-opus-5-5"
        assert body["fallbacks"] == "default"
        assert FALLBACK_BETA in request["headers"]["anthropic-beta"]
        assert body["output_config"]["format"]["type"] == "json_schema"
        assert body["output_config"]["effort"] == "medium"
        assert isinstance(body["system"], str)
    align = requests[0]["body"]["messages"][0]["content"]
    assert [b["type"] for b in align] == ["image", "text"]
    for request in requests[1:]:
        content = request["body"]["messages"][0]["content"]
        # 字形表(画像)が先頭で cache_control 付き。番号の text と升の画像が交互
        assert content[0]["type"] == "image" and content[0]["cache_control"] == {
            "type": "ephemeral"
        }
        assert content[0] == requests[1]["body"]["messages"][0]["content"][0]
        labels = [b["text"] for b in content[2:] if b["type"] == "text"]
        images = [b for b in content[2:] if b["type"] == "image"]
        assert len(labels) == len(images) >= 1
        assert labels[0].startswith("#1 (")


def test_only_the_written_cells_are_sent(fib_photo: bytes) -> None:
    """空の升は手元で落とす。送る升は手本に書いた升とちょうど同じ(番号の text に持ち主と升の順番が載る)。"""
    from jin_render.v2.sheet_layout import fill_sheet

    requests: list[dict] = []
    recognize_photo(fib_photo, recognizer=Recognizer(client=replay_client(recordings(), requests)))
    sent = [
        b["text"].split(" ", 1)[1]
        for r in requests[1:]
        for b in r["body"]["messages"][0]["content"][2:]
        if b["type"] == "text"
    ]
    sheet = sheet_layout("S")
    filled = fill_sheet(sheet, load("fib"))
    expected = [f"({s.owner}, cell {s.index})" for s in sheet.slots if (s.owner, s.index) in filled]
    assert sent == expected


def test_the_boxes_are_in_photo_coordinates(fib_photo: bytes) -> None:
    scene = recognize_photo(
        fib_photo, recognizer=Recognizer(client=replay_client(recordings(), []))
    )
    width, height = scene.image.width, scene.image.height
    for band in scene.bands:
        for cell in band.cells:
            assert cell.box is not None
            x0, y0, x1, y1 = cell.box
            assert 0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height
            assert 40 < x1 - x0 < 90  # 1 升 ≈ 60 px(手本の倍率 5)


def test_a_photo_of_the_hand_written_clicker_sheet_uses_the_strips_and_reads_back() -> None:
    """継ぎの紋 → 続きの帯(clicker の手順陣 272 升は 110 升の環に入らない)。"""
    model = load("clicker")
    scene = recognize_photo(
        synthetic_photo(model),
        recognizer=Recognizer(client=replay_client(synthetic_responses(model), [])),
    )
    parsed, diagnostics = parse_scene(scene, file="clicker.jinscene.json")
    assert diagnostics == []
    assert parsed is not None and dumps(parsed) == source("clicker")


def test_a_rotated_photo_reads_back_too(fib_photo: bytes) -> None:
    """写真が 90° 回っていても(スマホを横に構えた)丸の護符から向きを決める。"""
    import io

    image = Image.open(io.BytesIO(fib_photo)).rotate(-90, expand=True)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=88)
    responses = recordings()
    align = json.loads(responses[0]["content"][1]["text"])
    for corner in align["corners"]:  # 90° 時計回り: (x, y) → (1 - y, x)
        corner["x"], corner["y"] = 1.0 - corner["y"], corner["x"]
    responses = [_message(align, 0)] + responses[1:]
    scene = recognize_photo(
        buffer.getvalue(), recognizer=Recognizer(client=replay_client(responses, []))
    )
    model, diagnostics = parse_scene(scene, file="fib.jinscene.json")
    assert diagnostics == [] and model is not None and dumps(model) == source("fib")


# ---- 失敗の扱い ---------------------------------------------------------------------------------


def _with_stop(reason: str, details: dict | None = None) -> dict:
    body = _message({"grade": "S", "corners": []}, 0)
    body["stop_reason"] = reason
    body["stop_details"] = details
    return body


def test_a_refusal_is_a_recognize_error_naming_the_category(fib_photo: bytes) -> None:
    body = _with_stop("refusal", {"type": "refusal", "category": "cyber", "explanation": "x"})
    body["content"] = []
    with pytest.raises(RecognizeError, match="断りました.*cyber"):
        recognize_photo(fib_photo, recognizer=Recognizer(client=replay_client([body], [])))


def test_a_truncated_reply_is_a_recognize_error(fib_photo: bytes) -> None:
    with pytest.raises(RecognizeError, match="長さの上限"):
        recognize_photo(
            fib_photo,
            recognizer=Recognizer(client=replay_client([_with_stop("max_tokens")], [])),
        )


def test_a_photo_without_a_sheet_is_refused(fib_photo: bytes) -> None:
    body = _message({"grade": "none", "corners": []}, 0)
    with pytest.raises(RecognizeError, match="型紙"):
        recognize_photo(fib_photo, recognizer=Recognizer(client=replay_client([body], [])))


def test_corners_without_exactly_one_circle_are_refused(fib_photo: bytes) -> None:
    align = json.loads(recordings()[0]["content"][1]["text"])
    for corner in align["corners"]:
        corner["circle"] = True
    with pytest.raises(RecognizeError, match="丸の印"):
        recognize_photo(
            fib_photo, recognizer=Recognizer(client=replay_client([_message(align, 0)], []))
        )


def test_an_http_error_is_a_recognize_error(fib_photo: bytes) -> None:
    import anthropic
    import httpx2

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            401, json={"type": "error", "error": {"type": "authentication_error", "message": "no"}}
        )

    client = anthropic.Anthropic(
        api_key="bad",
        max_retries=0,
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    with pytest.raises(RecognizeError, match="認証を拒みました"):
        recognize_photo(fib_photo, recognizer=Recognizer(client=client))


def test_an_unreadable_image_is_refused_before_sending() -> None:
    with pytest.raises(RecognizeError, match="画像として開けません"):
        recognize_photo(b"not an image", recognizer=Recognizer(client=refusing_transport_client()))


def test_a_strip_that_continues_nothing_is_kept_for_the_parser_to_report() -> None:
    """どの銘帯にもつながらない続きの帯は図形 strip<n> として残し、構文解析器が JIN305 で知らせる。"""
    sheet = sheet_layout("S")
    strip = next(o for o in sheet.owners() if o.startswith("strip"))
    reads = {(strip, 1): (("latin", "x", []), (0.0, 0.0, 1.0, 1.0))}
    identity = homography(
        sheet.talismans(), [(x * 10 + 500, y * 10 + 500) for x, y in sheet.talismans()]
    )
    figures, bands = _assemble(sheet, reads, identity)
    assert [f.id for f in figures] == ["frame", strip]
    assert bands[-1].owner == strip and bands[-1].cells[0].v == "x"
    assert math.isclose(figures[0].at[0], 500.0)
