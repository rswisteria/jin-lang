"""生成系が共有する `.jin` の解析（jil.md §3 の名前の写像・§6.1）。

`jin_wasm.codegen`（JIL = Lua）と `jin_wasmgc.codegen`（wasm-GC の WAT・v2.1 Issue #53）の**両方**が
同じ解析を使う。ここにあるのは「型付きの式の AST」「型紙 / 陣 / 手順 / state / sigil の添字」
「`wait` を含む手順の閉包」「manifest の共通部」で、Lua も WAT も出さない。

名前は識別子に**埋め込まない**（jil.md §3）。陣は添字（`index` は 1 始まり = Lua の添字、
`pointer_index` は 0 始まり = JSON Pointer）、state / 型紙の欄は宣言順の添字で引く。
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from jin_core.v2 import expr as ex
from jin_core.v2.model import (
    CastStep,
    Circle,
    IfStep,
    JinFileV2,
    LoopStep,
    SigilHost,
    SigilSummon,
    Step,
    WaitStep,
)
from jin_core.v2.semantic import BUILTIN_FORMS, typed_nodes


class CodegenError(Exception):
    """生成できない（診断に error が残っている、など）。利用者向けの文で伝える。"""


@dataclass(slots=True)
class FormInfo:
    index: int  # JF の添字（Pointer = 0、forms は 1 始まり）
    fields: dict[str, tuple[int, str]]  # 欄名 → (添字, 型)


@dataclass(slots=True)
class CircleInfo:
    index: int  # Lua の添字（1 始まり）
    pointer_index: int  # JSON Pointer の添字（0 始まり）
    circle: Circle
    states: dict[str, tuple[int, str]]  # state 名 → (添字, 型)
    rites: dict[str, int]  # 手順名 → Lua の添字（1 始まり）
    sigils: dict[str, tuple[str, ...]]  # ("host", ns) | ("summon", circle, rite) | ("agent", file)
    waits: dict[str, bool] = field(default_factory=dict)


@dataclass(slots=True)
class Program:
    """解析済みの `.jin`。生成系はここから読むだけで、`typed_nodes` を呼び直さない。"""

    model: JinFileV2
    nodes: dict[str, ex.Node]  # pointer → 型注記付きの式の AST
    forms: dict[str, FormInfo]  # 型紙名 → 添字と欄（`Pointer` を含む）
    circles: dict[str, CircleInfo]  # 陣名 → 添字と state / 手順 / sigil

    def node(self, pointer: str) -> ex.Node:
        node = self.nodes.get(pointer)
        if node is None:
            raise CodegenError(f"式 {pointer} の型注記がありません（jin check を通してください）")
        return node


def analyze(model: JinFileV2) -> Program:
    """`.jin` を解析する。診断に error があれば `CodegenError`。"""
    nodes, diagnostics = typed_nodes(model)
    errors = [d for d in diagnostics if d.severity == "error"]
    if errors:
        first = errors[0]
        raise CodegenError(
            f"診断に error があるため生成できません（{first.code} {first.pointer}: {first.message}）。"
            "先に jin check を通してください"
        )
    forms: dict[str, FormInfo] = {
        "Pointer": FormInfo(
            0, {n: (j, t) for j, (n, t) in enumerate(BUILTIN_FORMS["Pointer"].items())}
        )
    }
    for k, form in enumerate(model.forms, start=1):
        forms[form.name] = FormInfo(k, {f.name: (j, f.type) for j, f in enumerate(form.fields)})
    circles: dict[str, CircleInfo] = {}
    for i, circle in enumerate(model.circles):
        sigils: dict[str, tuple[str, ...]] = {}
        for sigil in circle.sigils:
            if isinstance(sigil, SigilHost):
                sigils[sigil.name] = ("host", sigil.host)
            elif isinstance(sigil, SigilSummon):
                sigils[sigil.name] = ("summon", sigil.circle, sigil.rite)
            else:
                sigils[sigil.name] = ("agent", sigil.file)
        circles[circle.name] = CircleInfo(
            index=i + 1,
            pointer_index=i,
            circle=circle,
            states={s.name: (j, s.type) for j, s in enumerate(circle.state)},
            rites={r.name: j + 1 for j, r in enumerate(circle.rites)},
            sigils=sigils,
        )
    for info in circles.values():
        info.waits = rite_waits(info.circle)
    return Program(model, nodes, forms, circles)


def rite_waits(circle: Circle) -> dict[str, bool]:
    """手順ごとに「wait を含む（自陣の手順への cast を辿って）」か。semantic の JIN212 と同じ閉包。"""
    direct: dict[str, bool] = {}
    casts: dict[str, set[str]] = {}
    names = {r.name for r in circle.rites}
    for rite in circle.rites:
        direct[rite.name] = False
        casts[rite.name] = set()
        for step in walk_steps(rite.steps):
            if isinstance(step, WaitStep):
                direct[rite.name] = True
            elif isinstance(step, CastStep) and step.target in names:
                casts[rite.name].add(step.target)
    changed = True
    while changed:
        changed = False
        for name in names:
            if not direct[name] and any(direct[c] for c in casts[name]):
                direct[name] = True
                changed = True
    return direct


def walk_steps(steps: list[Step]) -> Iterator[Step]:
    """ステップを入れ子ごと前順で辿る。"""
    for step in steps:
        yield step
        if isinstance(step, IfStep):
            yield from walk_steps(step.then)
            yield from walk_steps(step.else_)
        elif isinstance(step, LoopStep):
            yield from walk_steps(step.steps)


def manifest_base(model: JinFileV2, *, source_name: str | None, debug: bool) -> dict[str, Any]:
    """`game.manifest.json` の両経路に共通な部分（runtime.md §9）。

    生成物の digest（Lua は `jil`、wasm-GC は `wasm`）と `target` は生成系が後ろに足す。
    """
    namespaces = sorted(
        {s.host for c in model.circles for s in c.sigils if isinstance(s, SigilHost)}
    )
    return {
        "file": source_name,
        "stage": {
            "width": model.stage.width,
            "height": model.stage.height,
            "fps": model.stage.fps,
            "seed": model.stage.seed,
        },
        "namespaces": namespaces,
        "assets": [{"name": a.name, "kind": a.kind, "path": a.path} for a in model.stage.assets],
        "debug": debug,
    }


__all__ = [
    "CircleInfo",
    "CodegenError",
    "FormInfo",
    "Program",
    "analyze",
    "manifest_base",
    "rite_waits",
    "walk_steps",
]
