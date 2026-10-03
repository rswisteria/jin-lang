"""`jin editor` の取り込みエンドポイント `POST /read` の中身（陣書き S5・設計書 §4.3 / §9 #13 / #21）。

ここがするのは 4 つだけである:

1. 要求（画像の名前とバイト列）を読む
2. 画像を場面グラフにする（写真は Claude 認識器・PNG は完全陣の決定的デコーダ・隣に同じ画像の場面グラフがあればそれ）
3. 構文解析して正準形の `.jin` を組む
4. 写真・`<写真名>.jinscene.json`・`<写真名>.jin` を root（`jin editor` で開いた `.jin` の親ディレクトリ）に書く

**HTTP は知らない。** ヘッダも検査もしない（それは `editor.py` の役目・`runserver.py` と同じ分担）。

【外部送信】写真（`.jpg` / `.jpeg` / `.webp`）は Anthropic の API に送る（`jin check <写真>` と同じ・設計書 §3.7）。
送る前に `notify` へ 1 行出す。API キーはこのプロセス（サーバ側）の `anthropic` SDK だけが読み、ブラウザに渡さない。
PNG は送らない（デコードに失敗しても API へ回さない・§9 #37）。

【書き出し】3 つの規律（ops.md §5.3）: 既にある名前には書かない（`os.link` は在る名前に張れない）・symlink を拒む・
root の外へ出ない（名前は区切りを含まない 1 段だけ）。写真と場面グラフが既に在って、それが同じ画像のもの
（写真はバイト一致・場面グラフは `image.sha256` 一致）なら書かずにそれを使う。場面グラフを手で直して同じ写真を
落とし直せば、API を呼ばずに `.jin` を書ける（`jin check <写真>` の再利用と同じ規則）。
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: 型紙に手で描いた陣の写真（Claude 認識器で読む）。`jin_cli.main._PHOTO_SUFFIXES` と同じ（テストが突き合わせる）
PHOTO_SUFFIXES = (".jpg", ".jpeg", ".webp")
#: 受ける画像の拡張子。PNG は完全陣（決定的デコーダ・API に送らない）
IMAGE_SUFFIXES = (".png", *PHOTO_SUFFIXES)
#: 場面グラフの拡張子。`jin_cli.main._SCENE_SUFFIX` と同じ
SCENE_SUFFIX = ".jinscene.json"

#: `POST /read` の body の上限（バイト）。JSON の中の base64（4/3 倍）なので、写真で 24 MiB まで。
#: スマートフォンの写真（4032 × 3024 の JPEG で数 MB）に余裕を持たせ、`/run` の 64 KiB とは別に置く
MAX_READ_BODY = 32 * 1024 * 1024

#: ファイル名の上限（バイト）。多くのファイルシステムの NAME_MAX。`<名前>.jinscene.json` が収まるように差し引く
_MAX_NAME_BYTES = 255 - len(SCENE_SUFFIX.encode())

#: 名前に入れない字（`jin_cli.main._UNSAFE_CODES` と同じ集合: 制御文字・U+2028 / U+2029・孤立サロゲート）
_UNSAFE_CODES = frozenset(
    [*range(0x20), 0x7F, *range(0x80, 0xA0), 0x2028, 0x2029, *range(0xD800, 0xE000)]
)


class ReadRejected(Exception):
    """要求を受けられない理由。`status` が HTTP の状態番号（400 / 409 / 422）。"""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class ReadRequest:
    """取り込みの要求。**書き先のディレクトリは含まない**（`jin editor` の root に固定する）。"""

    name: str
    data: bytes


def _check_name(name: object) -> str:
    if not isinstance(name, str) or name == "":
        raise ReadRejected(400, "name（画像のファイル名）が要ります")
    if "/" in name or "\\" in name or name.startswith("."):
        raise ReadRejected(
            400, f"ファイル名だけを送ってください（区切りや先頭の . は使えません）: {name!r}"
        )
    if any(ord(ch) in _UNSAFE_CODES for ch in name):
        raise ReadRejected(400, "ファイル名に制御文字は使えません")
    if len(name.encode("utf-8")) > _MAX_NAME_BYTES:
        raise ReadRejected(400, "ファイル名が長すぎます")
    if Path(name).suffix.lower() not in IMAGE_SUFFIXES:
        raise ReadRejected(
            400, "取り込めるのは型紙の写真（.jpg / .jpeg / .webp）か完全陣の画像（.png）だけです"
        )
    return name


def parse_request(body: bytes) -> ReadRequest:
    """POST の body（`{"name": …, "data": <base64>}`）を読む。読めない形は理由を添えて断る。"""
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReadRejected(400, "JSON として読めません") from exc
    if not isinstance(payload, dict):
        raise ReadRejected(400, "JSON オブジェクトを送ってください")
    name = _check_name(payload.get("name"))
    raw = payload.get("data")
    if not isinstance(raw, str) or raw == "":
        raise ReadRejected(400, "data（画像の base64）が要ります")
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ReadRejected(400, "data が base64 として読めません") from exc
    return ReadRequest(name=name, data=data)


def _is_photo(name: str) -> bool:
    return Path(name).suffix.lower() in PHOTO_SUFFIXES


def _existing(path: Path) -> bool:
    """在るか（リンク切れの symlink も「在る」）。symlink は在っても使わずに拒む。"""
    if path.is_symlink():
        raise ReadRejected(409, f"{path.name} はシンボリックリンクなので使いません")
    if path.exists() and not path.is_file():
        raise ReadRejected(409, f"{path.name} は通常のファイルではありません")
    return path.exists()


def _scene_matching(path: Path, sha256: str) -> str | None:
    """在る場面グラフのテキスト（同じ画像のものなら）。別の画像のものは拒む。無ければ None。"""
    if not _existing(path):
        return None
    try:
        text = path.read_text(encoding="utf-8")
        image = json.loads(text).get("image")
    except (OSError, UnicodeDecodeError, ValueError, AttributeError):
        image = None
    if isinstance(image, dict) and image.get("sha256") == sha256:
        return text
    raise ReadRejected(
        409,
        f"{path.name} は別の画像の場面グラフです（上書きしません。消すか写真の名前を変えてください）",
    )


def _create(root: Path, name: str, data: bytes) -> None:
    """`root/name` を**新しく**作る。在れば（symlink を含む）`ReadRejected(409)`。

    同じディレクトリの一時ファイルに書き切ってから `os.link` で名前を張る。`os.link` は在る名前
    （symlink を含む）に張れないので、検査と書き込みの間にすり替えられても上書きしない（`O_EXCL` と同じ効き目）。
    書きかけのファイルがその名前で見えることも無い。一時ファイルは必ず消す。

    guard: _create -> os.link
    """
    handle, temporary = tempfile.mkstemp(dir=root, prefix=".jin-read-", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        umask = os.umask(0)
        os.umask(umask)
        os.chmod(temporary, 0o666 & ~umask)
        try:
            os.link(temporary, root / name, follow_symlinks=False)
        except FileExistsError as exc:
            raise ReadRejected(409, f"{name} が既にあります（上書きしません）") from exc
    finally:
        with contextlib.suppress(OSError):
            os.unlink(temporary)


def _recognize_photo(data: bytes) -> Any:
    from jin_glyph.recognize import recognize_photo

    return recognize_photo(data)


def _decode_png(data: bytes) -> Any:
    from jin_glyph.decode import decode_png

    return decode_png(data)


def _scene_of(
    request: ReadRequest,
    recognize: Callable[[bytes], Any] | None,
    notify: Callable[[str], None] | None,
) -> Any:
    """画像 → 場面グラフ。写真だけを送る（送る前に 1 行）。失敗は 422（何も書いていない）。"""
    from jin_glyph.decode import DecodeError
    from jin_glyph.recognize import RecognizeError

    try:
        if _is_photo(request.name):
            if notify is not None:
                notify(
                    f"{request.name}: 写真を Anthropic の API（Claude）に送って読み取ります"
                    "（エディタの取り込み。結果は隣の .jinscene.json に保存し、次回からは送りません）"
                )
            return (recognize or _recognize_photo)(request.data)
        return _decode_png(request.data)
    except RecognizeError as exc:
        raise ReadRejected(422, f"写真を読み取れません（{exc}）") from exc
    except (DecodeError, OSError, ValueError) as exc:
        raise ReadRejected(
            422,
            f"画像として読めません（{exc}）"
            "（型紙の写真なら .jpg で、Jin が描いた完全陣なら .png で渡してください）",
        ) from exc


def read_image(
    root: Path,
    request: ReadRequest,
    *,
    recognize: Callable[[bytes], Any] | None = None,
    notify: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """画像を取り込んで、写真・場面グラフ・`.jin` を `root` に書く。応答の JSON（dict）を返す。

    書く順は 写真 → 場面グラフ → `.jin`（認識が終わってから書き始める。認識の失敗では何も書かない）。
    `.jin` を書くのは**モデルを組めたとき**（意味の誤り JIN2xx が残っていても書く。図と実行パネルで直せるように・
    `jin fmt <写真> --out` が誤りを残して書かないのとは意図して違う・設計書 §9 #43）。絵の文法の誤り（JIN3xx）で
    モデルを組めなければ写真と場面グラフだけを書き、`jin` を null にして診断を返す。

    hazard: read_image -> _scene_of(request,recognize,notify)
    guard: read_image -> _create(root,name,request.data)
    """
    from jin_core.canonical import dumps
    from jin_glyph.parse import parse_scene_text
    from jin_glyph.scene import JinScene, box_of

    root = root.resolve()
    name = _check_name(request.name)
    stem = name[: -len(Path(name).suffix)]
    photo_path = root / name
    scene_path = root / (stem + SCENE_SUFFIX)
    jin_path = root / (stem + ".jin")
    if photo_path.parent != root or jin_path.parent != root:
        raise ReadRejected(400, "root の外へは書きません")
    if _existing(jin_path):
        raise ReadRejected(409, f"{jin_path.name} が既にあります（上書きしません）")
    photo_present = _existing(photo_path)
    if photo_present and photo_path.read_bytes() != request.data:
        raise ReadRejected(
            409, f"{name} という別の画像が既にあります（上書きしません。名前を変えてください）"
        )
    sha256 = hashlib.sha256(request.data).hexdigest()
    text = _scene_matching(scene_path, sha256)
    scene_present = text is not None
    if text is None:
        scene = _scene_of(request, recognize, notify)
        payload = scene.model_dump(mode="json", by_alias=True, exclude_defaults=True)
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    if not photo_present:
        _create(root, name, request.data)
    if not scene_present:
        _create(root, scene_path.name, text.encode("utf-8"))

    model, diagnostics = parse_scene_text(text, file=str(scene_path))
    try:
        parsed: Any = JinScene.model_validate_json(text)
    except ValueError:
        parsed = None
    jin_uri: str | None = None
    if model is not None:
        _create(root, jin_path.name, dumps(model).encode("utf-8"))
        jin_uri = jin_path.as_uri()

    image = json.loads(text).get("image") if parsed is None else parsed.image.model_dump()
    return {
        "jin": jin_uri,
        "photo": name,
        "scene": scene_path.name,
        "image": {
            "width": image.get("width") if isinstance(image, dict) else None,
            "height": image.get("height") if isinstance(image, dict) else None,
        },
        "diagnostics": [
            {
                "code": d.code,
                "severity": d.severity,
                "message": d.message,
                "hint": d.hint,
                "pointer": d.pointer,
                "box": (
                    list(box)
                    if parsed is not None and (box := box_of(parsed, d.pointer)) is not None
                    else None
                ),
            }
            for d in diagnostics
        ],
    }


__all__ = [
    "IMAGE_SUFFIXES",
    "MAX_READ_BODY",
    "PHOTO_SUFFIXES",
    "SCENE_SUFFIX",
    "ReadRejected",
    "ReadRequest",
    "parse_request",
    "read_image",
]
