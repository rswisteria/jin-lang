"""入力ログ / 録画 `.jinrec`（runtime.md §7）の読み書き。

JSONL。1 行目はヘッダ `{"jinrec": 1, "file", "seed", "fps", "ticks", ["storage"]}`、以降は
`{"tick", "kind": "key" | "pointer", ...}`。`tick` は昇順（同じ tick の複数行は発生順）。
壊れた行は黙って読み飛ばさず、行番号を添えて `JinrecError` にする（`jin_cli.main._read_trace_rows` と同じ規律）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

JINREC_VERSION = 1
EVENT_KINDS = ("key", "pointer")


class JinrecError(Exception):
    """`.jinrec` の契約違反（`path:line: 理由`）。"""


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
        if not isinstance(storage, dict):
            raise JinrecError(f"{path}:{number}: ヘッダの storage はオブジェクトです")
        if not all(isinstance(v, str) for v in storage.values()):
            raise JinrecError(f"{path}:{number}: ヘッダの storage の値は文字列です")
        out.storage = dict(storage)


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
    "read_jinrec",
]
