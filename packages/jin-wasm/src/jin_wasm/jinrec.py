"""入力ログ / 録画 `.jinrec`（runtime.md §7）の読み書き。

JSONL。1 行目はヘッダ `{"jinrec": 1, "file", "seed", "fps", "ticks", ["storage"]}`、以降は
`{"tick", "kind": "key" | "pointer" | "text", ...}`。`tick` は昇順（同じ tick の複数行は発生順）。
壊れた行は黙って読み飛ばさず、行番号を添えて `JinrecError` にする（`jin_cli.main._read_trace_rows` と同じ規律）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

JINREC_VERSION = 1
#: `text` は v2.1（abilities.md §3）。古い読み手は未知の kind として行番号付きで断るので、版は 1 のまま。
EVENT_KINDS = ("key", "pointer", "text")


class JinrecError(Exception):
    """`.jinrec` の契約違反（`path:line: 理由`）。"""


def is_clean_text(text: str) -> bool:
    """文字入力として運べる文字だけか（制御文字 U+0000〜U+001F / U+007F と対にならないサロゲートを含まない）。

    プレイヤーの集め手は入力欄の値からこれらを落としてから `text` イベントにする（`apps/player/src/input.ts`
    の `cleanText`）。サロゲートが残ると Lua の文字列（UTF-8）へ写せない。
    """
    return not any(ord(c) < 0x20 or ord(c) == 0x7F or 0xD800 <= ord(c) <= 0xDFFF for c in text)


@dataclass(slots=True)
class Recording:
    file: str | None = None
    seed: int | None = None
    fps: int | None = None
    ticks: int | None = None
    #: 録画の boot に渡した記憶の写し（abilities.md §8・v2.1）。無ければ None（= 空）。
    storage: dict[str, str] | None = None
    events: list[dict[str, Any]] = field(default_factory=list)


def read_jinrec(path: Path) -> Recording:
    """`.jinrec` を読む。ヘッダとイベントの形を検査する。"""
    recording = Recording()
    last_tick = -1
    saw_header = False
    try:
        with path.open(encoding="utf-8", newline="\n") as handle:
            for number, raw in enumerate(handle, start=1):
                line = raw.removesuffix("\n").removesuffix("\r")
                if number == 1:
                    line = line.removeprefix("\ufeff")  # BOM（jin_cli の _read_trace_rows と同じ）
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except ValueError as exc:
                    raise JinrecError(
                        f"{path}:{number}: JSON として読めません（{getattr(exc, 'msg', exc)}）"
                    ) from exc
                if not isinstance(value, dict):
                    raise JinrecError(f"{path}:{number}: JSON オブジェクトではありません")
                if not saw_header:
                    _read_header(path, number, value, recording)
                    saw_header = True
                    continue
                last_tick = _read_event(path, number, value, last_tick, recording)
    except OSError as exc:
        raise JinrecError(f"{path}: 読めません（{exc.strerror}）") from exc
    if not saw_header:
        raise JinrecError(f'{path}: ヘッダ行（{{"jinrec": {JINREC_VERSION}, ...}}）がありません')
    return recording


def _read_header(path: Path, number: int, value: dict[str, Any], out: Recording) -> None:
    if value.get("jinrec") != JINREC_VERSION:
        raise JinrecError(
            f'{path}:{number}: 1 行目は {{"jinrec": {JINREC_VERSION}}} のヘッダです'
            f"（実際 {json.dumps(value.get('jinrec'), ensure_ascii=False)}）"
        )
    for key in ("seed", "fps", "ticks"):
        if key in value and not _is_int(value[key]):
            raise JinrecError(f"{path}:{number}: ヘッダの {key} は整数です")
    file = value.get("file")
    if file is not None and not isinstance(file, str):
        raise JinrecError(f"{path}:{number}: ヘッダの file は文字列です")
    out.file = file
    out.seed = value.get("seed")
    out.fps = value.get("fps")
    out.ticks = value.get("ticks")
    if out.ticks is not None and out.ticks < 0:
        raise JinrecError(f"{path}:{number}: ヘッダの ticks は 0 以上です")
    storage = value.get("storage")
    if storage is not None:
        try:
            out.storage = check_storage_copy(storage, where="ヘッダの storage")
        except TypeError as exc:
            raise JinrecError(f"{path}:{number}: {exc}") from exc


def check_storage_copy(value: object, *, where: str) -> dict[str, str]:
    """記憶の写し（abilities.md §8）の形を検査する。JSON の object で、値はすべて文字列。

    録画のヘッダの `storage` と `jin run --storage` のファイル（runtime.md §8）が同じ規則で読む。
    `where` は文言の主語（`ヘッダの storage はオブジェクトです`）。違反は `TypeError`。
    """
    if not isinstance(value, dict):
        raise TypeError(f"{where} はオブジェクトです")
    if not all(isinstance(v, str) for v in value.values()):
        raise TypeError(f"{where} の値は文字列です")
    return dict(value)


def _read_event(
    path: Path, number: int, value: dict[str, Any], last_tick: int, out: Recording
) -> int:
    tick = value.get("tick")
    if not _is_int(tick) or tick < 0:
        raise JinrecError(f"{path}:{number}: tick は 0 以上の整数です")
    if tick < last_tick:
        raise JinrecError(
            f"{path}:{number}: tick が昇順ではありません（{last_tick} の後に {tick}）"
        )
    kind = value.get("kind")
    if kind not in EVENT_KINDS:
        raise JinrecError(f"{path}:{number}: kind は {' / '.join(EVENT_KINDS)} のどれかです")
    event: dict[str, Any] = {"tick": tick, "kind": kind}
    if kind == "key":
        if not isinstance(value.get("name"), str):
            raise JinrecError(f"{path}:{number}: key の name は文字列です")
        if not isinstance(value.get("down"), bool):
            raise JinrecError(f"{path}:{number}: key の down は真偽値です")
        event["name"] = value["name"]
        event["down"] = value["down"]
    elif kind == "text":
        text = value.get("text")
        if not isinstance(text, str) or text == "":
            raise JinrecError(f"{path}:{number}: text の text は空でない文字列です")
        if not is_clean_text(text):
            raise JinrecError(
                f"{path}:{number}: text の text に制御文字や対にならないサロゲートは置けません"
            )
        event["text"] = text
    else:
        for key in ("x", "y"):
            if not _is_num(value.get(key)):
                raise JinrecError(f"{path}:{number}: pointer の {key} は数値です")
            event[key] = float(value[key])
        if not isinstance(value.get("down"), bool):
            raise JinrecError(f"{path}:{number}: pointer の down は真偽値です")
        event["down"] = value["down"]
    out.events.append(event)
    return tick


def dumps_jinrec(header: dict[str, Any], events: list[dict[str, Any]]) -> str:
    """ヘッダとイベントを `.jinrec` の文字列にする（プレイヤーの録画と同じ形）。"""
    lines = [json.dumps({"jinrec": JINREC_VERSION, **header}, ensure_ascii=False)]
    for event in events:
        lines.append(json.dumps(event, ensure_ascii=False))
    return "\n".join(lines) + "\n"


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


__all__ = [
    "EVENT_KINDS",
    "JINREC_VERSION",
    "JinrecError",
    "Recording",
    "dumps_jinrec",
    "is_clean_text",
    "read_jinrec",
]
