"""ホスト能力カタログ（docs/spec/v2/abilities.md）の正本。

**ここが唯一の真実**で、`schemas/abilities.json` はここから生成する（`scripts/generate_schema.py`）。
読む側は 4 つ: `jin_core.v2.semantic`（JIN204 / JIN205 / 型検査）、`jin_wasm`（Phase 2 の
Lua プレリュードと codegen）、`apps/player`（TS 型の生成元）、LSP の補完。
純データだけを置き、ADK / Lua / ブラウザの語彙をここに持ち込まない。

abilities.md §7 は当初「`jin_wasm` が生成し `jin_core` が JSON を読む」としていたが、`jin_core` は
`jin_wasm` を import できず、インストール済みパッケージから `schemas/` も見つけられないので、
正本を最下層（ここ）に置く（設計書 §11 #19）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

#: リポジトリルートからの相対パス。
ABILITIES_PATH = "schemas/abilities.json"

MemberKind = Literal["effect", "read", "effect+read", "state"]


@dataclass(frozen=True, slots=True)
class Member:
    name: str
    params: tuple[tuple[str, str], ...]
    returns: str | None
    kind: MemberKind


@dataclass(frozen=True, slots=True)
class Namespace:
    name: str
    members: tuple[Member, ...]

    def member(self, name: str) -> Member | None:
        for member in self.members:
            if member.name == name:
                return member
        return None


def _m(name: str, params: str, returns: str | None, kind: MemberKind) -> Member:
    pairs: list[tuple[str, str]] = []
    for item in params.split(",") if params else []:
        param_name, param_type = item.strip().split(":")
        pairs.append((param_name.strip(), param_type.strip()))
    return Member(name, tuple(pairs), returns, kind)


#: カタログ本体（abilities.md §1 の表と 1:1）。順序は表と同じ。
NAMESPACES: tuple[Namespace, ...] = (
    Namespace(
        "canvas",
        (
            _m("clear", "color: str", None, "effect"),
            _m("ink", "color: str", None, "effect"),
            _m("rect", "x: num, y: num, w: num, h: num", None, "effect"),
            _m("circle", "x: num, y: num, r: num", None, "effect"),
            _m("line", "x1: num, y1: num, x2: num, y2: num", None, "effect"),
            _m("text", "s: str, x: num, y: num", None, "effect"),
            _m("sprite", "name: str, x: num, y: num", None, "effect"),
        ),
    ),
    Namespace(
        "input",
        (
            _m("key", "name: str", "bool", "read"),
            _m("pressed", "name: str", "bool", "read"),
            _m("pointer", "", "Pointer", "read"),
        ),
    ),
    Namespace(
        "ui",
        (
            _m("button", "label: str, x: num, y: num, w: num, h: num", "bool", "effect+read"),
            _m("label", "s: str, x: num, y: num", None, "effect"),
        ),
    ),
    Namespace(
        "audio",
        (
            _m("tone", "hz: num, ms: num", None, "effect"),
            _m("play", "name: str", None, "effect"),
        ),
    ),
    Namespace(
        "random",
        (
            _m("next", "", "num", "state"),
            _m("range", "lo: num, hi: num", "num", "state"),
        ),
    ),
)

#: `input.key` / `input.pressed` に渡せるキー名（`KeyboardEvent.code`。abilities.md §3）。
KEY_NAMES: tuple[str, ...] = (
    "ArrowLeft",
    "ArrowRight",
    "ArrowUp",
    "ArrowDown",
    "Space",
    "Enter",
    "Escape",
    "Backspace",
    "Tab",
    "ShiftLeft",
    "ShiftRight",
    "ControlLeft",
    "ControlRight",
    *(f"Key{chr(c)}" for c in range(ord("A"), ord("Z") + 1)),
    *(f"Digit{d}" for d in range(10)),
)

#: 組み込みの型紙 `Pointer`（model.md §2）。
POINTER_FIELDS: tuple[tuple[str, str], ...] = (("x", "num"), ("y", "num"), ("down", "bool"))


def namespace(name: str) -> Namespace | None:
    for ns in NAMESPACES:
        if ns.name == name:
            return ns
    return None


def to_json_dict() -> dict:
    return {
        "namespaces": [
            {
                "name": ns.name,
                "members": [
                    {
                        "name": m.name,
                        "params": [{"name": p, "type": t} for p, t in m.params],
                        "returns": m.returns,
                        "kind": m.kind,
                    }
                    for m in ns.members
                ],
            }
            for ns in NAMESPACES
        ],
        "keys": list(KEY_NAMES),
        "pointer": [{"name": p, "type": t} for p, t in POINTER_FIELDS],
    }


def render_abilities() -> str:
    """`schemas/abilities.json` の唯一の書式。"""
    return json.dumps(to_json_dict(), indent=2, ensure_ascii=False, sort_keys=False) + "\n"


__all__ = [
    "ABILITIES_PATH",
    "KEY_NAMES",
    "NAMESPACES",
    "POINTER_FIELDS",
    "Member",
    "MemberKind",
    "Namespace",
    "namespace",
    "render_abilities",
    "to_json_dict",
]
