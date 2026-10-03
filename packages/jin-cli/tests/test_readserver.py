"""陣書き S5: `jin editor` の `POST /read` の中身(`jin_cli.readserver`・HTTP を知らない部分)。

写真の認識は差し替える(`recognize=`)。場面グラフは fib の完全陣 PNG をデコードしたものを、写真の sha256 に
付け替えて返す(ネットワークと API キーを使わない)。書き出しの 3 規律(既存の名前に書かない・symlink を拒む・
root の外へ出ない)と、隣の場面グラフの再利用(`jin check <写真>` と同じ規則)を固定する。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path

import cairosvg
import pytest
from jin_cli import readserver
from jin_cli.readserver import ReadRejected, ReadRequest, parse_request, read_image
from jin_core.check import check_text
from jin_glyph.decode import decode_png
from jin_glyph.scene import JinScene
from jin_render.v2.full import render_full

REPO_ROOT = Path(__file__).resolve().parents[3]
FIB = REPO_ROOT / "examples-v2/fib/fib.jin"
JIN301 = REPO_ROOT / "tests/fixtures/errors/scene/JIN301_missing_start_mark.jinscene.json"

PHOTO = b"\xff\xd8 a photo of a hand-drawn fib \xff\xd9"


@pytest.fixture(scope="module")
def fib_png() -> bytes:
    model = check_text(FIB.read_text(encoding="utf-8"), FIB.name).model
    return cairosvg.svg2png(
        bytestring=render_full(model).encode(), scale=2, background_color="white"
    )


@pytest.fixture(scope="module")
def fib_scene(fib_png: bytes) -> JinScene:
    return decode_png(fib_png)


def for_photo(scene: JinScene, data: bytes = PHOTO) -> JinScene:
    """認識器が返すのと同じく、場面グラフの image を写真のものにする。"""
    image = scene.image.model_copy(update={"sha256": hashlib.sha256(data).hexdigest()})
    return scene.model_copy(update={"image": image})


def recognizer(scene: JinScene, calls: list[bytes] | None = None) -> Callable[[bytes], JinScene]:
    def recognize(data: bytes) -> JinScene:
        if calls is not None:
            calls.append(data)
        return for_photo(scene, data)

    return recognize


def refuse(data: bytes) -> JinScene:
    raise AssertionError("送らないはずの写真を認識器に渡した")


def scene_text(scene: JinScene) -> str:
    payload = scene.model_dump(mode="json", by_alias=True, exclude_defaults=True)
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


# ---- 要求の形 ---------------------------------------------------------------------------------


def body(name: object, data: object) -> bytes:
    return json.dumps({"name": name, "data": data}).encode("utf-8")


def test_a_request_carries_a_plain_image_name_and_base64_bytes() -> None:
    request = parse_request(body("fib.jpg", base64.b64encode(PHOTO).decode()))
    assert request == ReadRequest(name="fib.jpg", data=PHOTO)


@pytest.mark.parametrize(
    "name",
    [
        "../fib.jpg",
        "sub/fib.jpg",
        "sub\\fib.jpg",
        ".fib.jpg",
        ".jpg",
        "fib.jin",
        "fib.jinscene.json",
        "fib.gif",
        "fi\nb.jpg",
        "fi b.jpg",
        "",
        "x" * 300 + ".jpg",
        3,
    ],
)
def test_names_that_are_not_a_plain_image_name_are_refused(name: object) -> None:
    with pytest.raises(ReadRejected) as caught:
        parse_request(body(name, base64.b64encode(PHOTO).decode()))
    assert caught.value.status == 400


@pytest.mark.parametrize(
    "raw",
    [b"not json", b"[]", body("fib.jpg", "***"), body("fib.jpg", ""), body("fib.jpg", None)],
)
def test_broken_bodies_are_refused(raw: bytes) -> None:
    with pytest.raises(ReadRejected) as caught:
        parse_request(raw)
    assert caught.value.status == 400


def test_upper_case_suffixes_are_images_too() -> None:
    assert parse_request(body("FIB.JPG", base64.b64encode(PHOTO).decode())).name == "FIB.JPG"


# ---- 取り込み ---------------------------------------------------------------------------------


def test_a_photo_is_read_and_the_photo_scene_and_jin_are_written(
    tmp_path: Path, fib_scene: JinScene
) -> None:
    calls: list[bytes] = []
    notes: list[str] = []
    result = read_image(
        tmp_path,
        ReadRequest("fib.jpg", PHOTO),
        recognize=recognizer(fib_scene, calls),
        notify=notes.append,
    )
    assert calls == [PHOTO]
    assert any("Anthropic の API" in n for n in notes)
    assert (tmp_path / "fib.jpg").read_bytes() == PHOTO
    scene = json.loads((tmp_path / "fib.jinscene.json").read_text(encoding="utf-8"))
    assert scene["image"]["sha256"] == hashlib.sha256(PHOTO).hexdigest()
    # 取り込み後の正本は `.jin`(正準形・`jin fmt <写真> --out` と同じ中身)
    written = (tmp_path / "fib.jin").read_text(encoding="utf-8")
    assert written == FIB.read_text(encoding="utf-8")
    assert result["jin"] == (tmp_path / "fib.jin").resolve().as_uri()
    assert result["photo"] == "fib.jpg"
    assert result["scene"] == "fib.jinscene.json"
    assert result["image"] == {"width": fib_scene.image.width, "height": fib_scene.image.height}
    assert result["diagnostics"] == []


def test_a_png_is_decoded_and_never_sent(tmp_path: Path, fib_png: bytes) -> None:
    notes: list[str] = []
    result = read_image(
        tmp_path, ReadRequest("fib.png", fib_png), recognize=refuse, notify=notes.append
    )
    assert notes == []
    assert result["jin"] is not None
    assert (tmp_path / "fib.jin").read_text(encoding="utf-8") == FIB.read_text(encoding="utf-8")


def test_an_existing_jin_is_never_overwritten(tmp_path: Path, fib_scene: JinScene) -> None:
    (tmp_path / "fib.jin").write_text("mine", encoding="utf-8")
    with pytest.raises(ReadRejected) as caught:
        read_image(tmp_path, ReadRequest("fib.jpg", PHOTO), recognize=refuse)
    assert caught.value.status == 409
    assert (tmp_path / "fib.jin").read_text(encoding="utf-8") == "mine"
    # 拒んだときは何も書かない(認識も呼ばない)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["fib.jin"]


def test_a_different_photo_under_the_same_name_is_refused(
    tmp_path: Path, fib_scene: JinScene
) -> None:
    (tmp_path / "fib.jpg").write_bytes(b"another photo")
    with pytest.raises(ReadRejected) as caught:
        read_image(tmp_path, ReadRequest("fib.jpg", PHOTO), recognize=refuse)
    assert caught.value.status == 409
    assert (tmp_path / "fib.jpg").read_bytes() == b"another photo"


def test_a_scene_graph_of_another_image_is_refused(tmp_path: Path, fib_scene: JinScene) -> None:
    (tmp_path / "fib.jinscene.json").write_text(
        scene_text(for_photo(fib_scene, b"other")), encoding="utf-8"
    )
    with pytest.raises(ReadRejected) as caught:
        read_image(tmp_path, ReadRequest("fib.jpg", PHOTO), recognize=refuse)
    assert caught.value.status == 409


@pytest.mark.parametrize("which", ["fib.jpg", "fib.jinscene.json", "fib.jin"])
def test_symlinks_are_refused(tmp_path: Path, fib_scene: JinScene, which: str) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "target"
    target.write_bytes(PHOTO)
    root = tmp_path / "root"
    root.mkdir()
    (root / which).symlink_to(target)
    with pytest.raises(ReadRejected) as caught:
        read_image(root, ReadRequest("fib.jpg", PHOTO), recognize=recognizer(fib_scene))
    assert caught.value.status == 409
    assert target.read_bytes() == PHOTO


def test_the_same_photo_with_a_hand_fixed_scene_is_read_again_without_sending(
    tmp_path: Path, fib_scene: JinScene
) -> None:
    """場面グラフを手で直して同じ写真を落とし直すと、API を呼ばずにその場面グラフで `.jin` を書く。

    `jin check <写真>` の再利用と同じ規則(sha256 が一致する隣の場面グラフを読む・設計書 §3.2)。
    """
    (tmp_path / "fib.jpg").write_bytes(PHOTO)
    (tmp_path / "fib.jinscene.json").write_text(scene_text(for_photo(fib_scene)), encoding="utf-8")
    notes: list[str] = []
    result = read_image(
        tmp_path, ReadRequest("fib.jpg", PHOTO), recognize=refuse, notify=notes.append
    )
    assert notes == []
    assert result["jin"] is not None
    assert (tmp_path / "fib.jin").is_file()


def test_a_broken_drawing_writes_the_photo_and_scene_but_no_jin(tmp_path: Path) -> None:
    """絵の文法の誤り(JIN3xx)ではモデルを組めない。写真と場面グラフは残し、診断を返す。"""
    scene = for_photo(JinScene.model_validate_json(JIN301.read_text(encoding="utf-8")))
    result = read_image(tmp_path, ReadRequest("fib.jpg", PHOTO), recognize=lambda _: scene)
    assert result["jin"] is None
    assert not (tmp_path / "fib.jin").exists()
    assert (tmp_path / "fib.jpg").is_file() and (tmp_path / "fib.jinscene.json").is_file()
    codes = [d["code"] for d in result["diagnostics"]]
    assert codes == ["JIN301"]
    first = result["diagnostics"][0]
    assert set(first) == {"code", "severity", "message", "hint", "pointer", "box"}


def test_diagnostics_carry_the_box_of_their_cell(tmp_path: Path, fib_scene: JinScene) -> None:
    """迷い(JIN306・警告)はその升の `box` を添える。警告だけならモデルを組めるので `.jin` も書く。"""
    data = json.loads(scene_text(for_photo(fib_scene)))
    cell = data["bands"][0]["cells"][0]
    cell["unsure"] = ["x"]
    cell["box"] = [1.0, 2.0, 3.0, 4.0]
    scene = JinScene.model_validate(data)
    result = read_image(tmp_path, ReadRequest("fib.jpg", PHOTO), recognize=lambda _: scene)
    assert result["jin"] is not None
    [diagnostic] = result["diagnostics"]
    assert diagnostic["code"] == "JIN306"
    assert diagnostic["pointer"] == "/bands/0/cells/0"
    assert diagnostic["box"] == [1.0, 2.0, 3.0, 4.0]


def test_a_recognition_failure_writes_nothing(tmp_path: Path) -> None:
    from jin_glyph.recognize import RecognizeError

    def fail(data: bytes) -> JinScene:
        raise RecognizeError("認証情報がありません")

    with pytest.raises(ReadRejected) as caught:
        read_image(tmp_path, ReadRequest("fib.jpg", PHOTO), recognize=fail)
    assert caught.value.status == 422
    assert "認証情報" in str(caught.value)
    assert list(tmp_path.iterdir()) == []


def test_an_unreadable_png_is_refused_without_sending(tmp_path: Path) -> None:
    with pytest.raises(ReadRejected) as caught:
        read_image(tmp_path, ReadRequest("fib.png", b"not a png"), recognize=refuse)
    assert caught.value.status == 422
    assert list(tmp_path.iterdir()) == []


def test_written_files_follow_the_umask_and_leave_no_temporaries(
    tmp_path: Path, fib_scene: JinScene
) -> None:
    read_image(tmp_path, ReadRequest("fib.jpg", PHOTO), recognize=recognizer(fib_scene))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["fib.jin", "fib.jinscene.json", "fib.jpg"]
    umask = os.umask(0)
    os.umask(umask)
    assert (tmp_path / "fib.jin").stat().st_mode & 0o777 == 0o666 & ~umask


def test_the_suffixes_match_the_cli() -> None:
    """`jin check` / `jin fmt` が写真として送る拡張子と、`POST /read` が送る拡張子は同じ。"""
    from jin_cli import main

    assert main._PHOTO_SUFFIXES == readserver.PHOTO_SUFFIXES
    assert main._SCENE_SUFFIX == readserver.SCENE_SUFFIX
