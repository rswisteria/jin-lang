"""手順の図（`--focus 陣名/手順名`・`docs/spec/v2/layout.md` §3）。

手順を 1 つの陣として描く。中心の核には手順名。ステップは深さ 0 を環 0.95、深さ 1 を 0.75、
深さ 2 を 0.55、深さ 3 を 0.35 に置き（外から内へ）、深さ 4 以上（JIN211）は最内環に丸める。

## 弧の割り当て（v2 layout.md §3・Phase 3 で確定）

- 深さ 0 のステップ `k`（`n` 個）は角 `theta_k = -90° + 360° * k / n`、幅 `360° / n` の弧を持つ
- 入れ子のブロック（`if.then` / `if.else` / `loop.steps`）は**親の弧**に収める。`if` に `then` と
  `else` の両方があれば前半（反時計回り側）を `then`、後半を `else` に割る。片方だけなら全幅
- ブロックの `m` 個の子は、その弧を `m` 等分した各区画の**中央**に置き、子の弧幅は `弧幅 / m`
- ステップ間は配列順に弦（矢じり付き）。`if` / `loop` の紋から各ブロックの先頭へ線を引き
  （`else` は破線）、ブロックの末尾から親の次のステップへ戻る（`loop` は紋へ戻る）

意味検査を呼ばない。`cast` の分類は名前表だけで決める（summon の sigil 名 → 自陣の手順名 →
`名前空間.member` の名前空間が host の sigil → どれでもなければ破線の点）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from jin_core.v2.model import (
    BreakStep,
    CastStep,
    Circle,
    EmitStep,
    FinishStep,
    IfStep,
    JinFileV2,
    LetStep,
    LoopStep,
    ReturnStep,
    SetStep,
    Step,
    TransferStep,
    WaitStep,
)

from jin_render import geometry as geo
from jin_render import paths
from jin_render.svg import Node
from jin_render.v2 import geometry as g2
from jin_render.v2 import shapes

#: `cast` の分類（v2 layout.md §3 の表）。
CAST_HOST = "host"
CAST_RITE = "rite"
CAST_SUMMON = "summon"


@dataclass
class _Placed:
    """置き場所の決まったステップ。角度は度、幅はこのステップが持つ弧の幅（度）。"""

    step: Step
    pointer: str
    depth: int
    angle: float
    width: float
    then: list[_Placed] = field(default_factory=list)
    else_: list[_Placed] = field(default_factory=list)
    body: list[_Placed] = field(default_factory=list)

    @property
    def ring(self) -> float:
        return g2.DEPTH_RINGS[min(self.depth, len(g2.DEPTH_RINGS) - 1)]

    @property
    def gap(self) -> float:
        """弦がこのステップの図形から空ける隙間（正規化単位）。"""
        if isinstance(self.step, (SetStep, LetStep, CastStep, IfStep, LoopStep)):
            return g2.STEP_GAP
        return g2.LINE_STEP_GAP

    def blocks(self) -> list[tuple[list[_Placed], bool]]:
        """`(子の列, 破線か)`。`if` は then / else、`loop` は steps。"""
        out: list[tuple[list[_Placed], bool]] = []
        if self.then:
            out.append((self.then, False))
        if self.else_:
            out.append((self.else_, True))
        if self.body:
            out.append((self.body, False))
        return out

    def walk(self) -> list[_Placed]:
        found = [self]
        for block, _ in self.blocks():
            for child in block:
                found.extend(child.walk())
        return found


def place_block(
    steps: list[Step], prefix: str, depth: int, start: float, width: float
) -> list[_Placed]:
    """`steps` を弧 `[start, start + width]` に等分配置する（再帰）。"""
    count = len(steps)
    out: list[_Placed] = []
    for position, step in enumerate(steps):
        own = width / count
        angle = start + own * (position + 0.5)
        placed = _Placed(step, f"{prefix}/{position}", depth, angle, own)
        arc_start = angle - own / 2.0
        if isinstance(step, IfStep):
            if step.else_:
                placed.then = place_block(
                    step.then, f"{placed.pointer}/then", depth + 1, arc_start, own / 2.0
                )
                placed.else_ = place_block(
                    step.else_,
                    f"{placed.pointer}/else",
                    depth + 1,
                    arc_start + own / 2.0,
                    own / 2.0,
                )
            else:
                placed.then = place_block(
                    step.then, f"{placed.pointer}/then", depth + 1, arc_start, own
                )
        elif isinstance(step, LoopStep):
            placed.body = place_block(
                step.steps, f"{placed.pointer}/steps", depth + 1, arc_start, own
            )
        out.append(placed)
    return out


def classify_cast(circle: Circle, target: str) -> str | None:
    """`cast` の `target` を host / rite / summon に分類する。解決できなければ `None`。"""
    summons = {sigil.name for sigil in circle.sigils if sigil.kind == "summon"}
    hosts = {sigil.name for sigil in circle.sigils if sigil.kind == "host"}
    rites = {rite.name for rite in circle.rites}
    if target in summons:
        return CAST_SUMMON
    if target in rites:
        return CAST_RITE
    if "." in target and target.split(".", 1)[0] in hosts:
        return CAST_HOST
    return None


@dataclass
class _RiteBuilder:
    model: JinFileV2
    circle: Circle
    frame: geo.Frame
    index_of: dict[str, int]

    def position(self, placed: _Placed) -> tuple[float, float]:
        return geo.point(self.frame, placed.ring, placed.angle)

    # -- 環（深さごと。`wait` の角度に欠け） ------------------------------------------------
    def rings(self, base: str, placed: list[_Placed]) -> list[Node]:
        by_ring: dict[float, list[_Placed]] = {}
        for item in placed:
            by_ring.setdefault(item.ring, []).append(item)
        out: list[Node] = []
        for ring in sorted(by_ring, reverse=True):
            gaps = [
                (
                    item.angle - g2.WAIT_HALF_ANGLE - geo.TOP_ANGLE,
                    item.angle + g2.WAIT_HALF_ANGLE - geo.TOP_ANGLE,
                )
                for item in by_ring[ring]
                if isinstance(item.step, WaitStep)
            ]
            if not gaps:
                out.append(
                    shapes.circle(
                        (self.frame.cx, self.frame.cy), ring * self.frame.scale, base, "circle"
                    )
                )
                continue
            for start, sweep in geo.complement_arcs(gaps):
                out.append(
                    shapes.path(
                        paths.arc_d(self.frame, ring, geo.TOP_ANGLE + start, sweep), base, "circle"
                    )
                )
        return out

    # -- 弦 ------------------------------------------------------------------------------
    def _chord(
        self, source: _Placed, target: _Placed, *, head: bool, dashed: bool = False
    ) -> Node | None:
        d = paths.arrow_d(
            self.position(source),
            self.position(target),
            source.gap * self.frame.scale,
            target.gap * self.frame.scale,
            geo.ARROW_HEAD * self.frame.scale if head else 0.0,
        )
        if d is None:
            return None
        return shapes.path(d, source.pointer, "step-edge", dashed=dashed)

    def edges(self, block: list[_Placed], parent: _Placed | None) -> list[Node]:
        """ブロックの中を配列順に結び、末尾から親の次へ（`loop` は親へ）戻る。再帰。"""
        out: list[Node] = []
        for position, item in enumerate(block):
            if position + 1 < len(block):
                chord = self._chord(item, block[position + 1], head=True)
                if chord is not None:
                    out.append(chord)
            for children, _ in item.blocks():
                out.extend(self.edges(children, item))
                last = children[-1]
                if isinstance(item.step, LoopStep):
                    back = self._chord(last, item, head=True)
                elif position + 1 < len(block):
                    back = self._chord(last, block[position + 1], head=True)
                else:
                    back = None
                if back is not None:
                    out.append(back)
        return out

    def branch_lines(self, item: _Placed) -> list[Node]:
        """`if` / `loop` の紋から各ブロックの両端へ（`else` は破線）。`kind` は `step`。"""
        out: list[Node] = []
        for children, dashed in item.blocks():
            ends = [children[0]] if len(children) == 1 else [children[0], children[-1]]
            for end in ends:
                d = paths.arrow_d(
                    self.position(item),
                    self.position(end),
                    item.gap * self.frame.scale,
                    end.gap * self.frame.scale,
                    0.0,
                )
                if d is not None:
                    out.append(shapes.path(d, item.pointer, "step", dashed=dashed))
        return out

    # -- 図形 ----------------------------------------------------------------------------
    def _radial(self, item: _Placed, inner: float, outer: float, *, dashed: bool = False) -> Node:
        return shapes.line(
            geo.point(self.frame, inner, item.angle),
            geo.point(self.frame, outer, item.angle),
            item.pointer,
            "step",
            dashed=dashed,
        )

    def _bar(self, item: _Placed, radius: float) -> str:
        """角度 `item.angle` の半径 `radius` の点を通る、接線方向の短い横棒。"""
        theta = math.radians(item.angle)
        cx, cy = geo.point(self.frame, radius, item.angle)
        half = g2.STEP_TIP * self.frame.scale
        vx, vy = -math.sin(theta), math.cos(theta)
        return " ".join(
            [
                paths.move((cx - vx * half, cy - vy * half)),
                paths.line_to((cx + vx * half, cy + vy * half)),
            ]
        )

    def glyph(self, item: _Placed) -> list[Node]:
        step = item.step
        ring = item.ring
        frame = self.frame
        center = self.position(item)
        pointer = item.pointer
        radius = g2.STEP_RADIUS * frame.scale
        if isinstance(step, SetStep):
            return [
                shapes.path(paths.square_d(frame, item.angle, ring, g2.STEP_HALF), pointer, "step")
            ]
        if isinstance(step, LetStep):
            return [
                shapes.path(paths.square_d(frame, item.angle, ring, g2.LET_HALF), pointer, "step")
            ]
        if isinstance(step, CastStep):
            kind = classify_cast(self.circle, step.target)
            out = [shapes.circle(center, radius, pointer, "step", dashed=kind is None)]
            if kind == CAST_HOST:
                out.append(
                    self._radial(item, ring + g2.STEP_RADIUS, ring + g2.STEP_RADIUS + g2.STEP_TAIL)
                )
            elif kind == CAST_RITE:
                out.append(
                    self._radial(item, ring - g2.STEP_RADIUS, ring - g2.STEP_RADIUS - g2.STEP_TAIL)
                )
            elif kind == CAST_SUMMON:
                out.append(
                    self._radial(
                        item,
                        ring + g2.STEP_RADIUS,
                        ring + g2.STEP_RADIUS + g2.STEP_TAIL,
                        dashed=True,
                    )
                )
            return out
        if isinstance(step, IfStep):
            return [
                shapes.path(paths.polygon_d(center, radius, 4, 1, geo.TOP_ANGLE), pointer, "step")
            ]
        if isinstance(step, LoopStep):
            count = max(3, len(step.steps))
            star = geo.star_step(count) if step.kind == "each" else 1
            return [
                shapes.path(
                    paths.polygon_d(center, radius, count, star, geo.TOP_ANGLE), pointer, "step"
                )
            ]
        if isinstance(step, BreakStep):
            d = " ".join(
                [
                    paths.move(geo.point(frame, ring, item.angle)),
                    paths.line_to(geo.point(frame, ring + g2.STEP_TAIL, item.angle)),
                    self._bar(item, ring + g2.STEP_TAIL),
                ]
            )
            return [shapes.path(d, pointer, "step")]
        if isinstance(step, ReturnStep):
            return [self._radial(item, ring, ring + g2.STEP_TAIL)]
        if isinstance(step, FinishStep):
            d = " ".join(
                [
                    paths.move(geo.point(frame, ring, item.angle)),
                    paths.line_to(geo.point(frame, ring + g2.STEP_TAIL, item.angle)),
                    self._bar(item, ring + g2.STEP_TAIL),
                    self._bar(item, ring + g2.STEP_TAIL - g2.STEP_TIP),
                ]
            )
            return [shapes.path(d, pointer, "step")]
        if isinstance(step, EmitStep):
            return [
                self._radial(item, ring, ring + g2.STEP_TAIL, dashed=True),
                shapes.circle(
                    geo.point(frame, ring + g2.STEP_TAIL + g2.STEP_TIP, item.angle),
                    g2.STEP_TIP * frame.scale,
                    pointer,
                    "step",
                ),
            ]
        if isinstance(step, TransferStep):
            tip = geo.point(frame, ring + g2.STEP_TAIL + g2.TRANSFER_RADIUS, item.angle)
            target = self.index_of.get(step.circle)
            return [
                self._radial(item, ring, ring + g2.STEP_TAIL, dashed=True),
                shapes.circle(
                    tip,
                    g2.TRANSFER_RADIUS * frame.scale,
                    pointer,
                    "step",
                    dashed=target is None,
                    ref=None if target is None else f"/circles/{target}",
                ),
                shapes.circle(tip, g2.TRANSFER_CORE * frame.scale, pointer, "step", filled=True),
            ]
        if isinstance(step, WaitStep):
            parts: list[str] = []
            for edge in (item.angle - g2.WAIT_HALF_ANGLE, item.angle + g2.WAIT_HALF_ANGLE):
                parts.append(paths.move(geo.point(frame, ring - g2.WAIT_TICK_HALF, edge)))
                parts.append(paths.line_to(geo.point(frame, ring + g2.WAIT_TICK_HALF, edge)))
            return [shapes.path(" ".join(parts), pointer, "step")]
        return []  # pragma: no cover - Step は 11 種で尽きている


def draw_rite(
    model: JinFileV2, circle_index: int, rite_index: int, frame: geo.Frame, index_of: dict[str, int]
) -> Node:
    """手順を 1 つの陣として描く。戻り値は `data-jin="/circles/i/rites/j"` の `<g>`。"""
    circle = model.circles[circle_index]
    rite = circle.rites[rite_index]
    base = f"/circles/{circle_index}/rites/{rite_index}"
    builder = _RiteBuilder(model=model, circle=circle, frame=frame, index_of=index_of)
    count = len(rite.steps)
    top = (
        place_block(rite.steps, f"{base}/steps", 0, geo.TOP_ANGLE - 180.0 / count, 360.0)
        if count
        else []
    )
    placed = [item for root in top for item in root.walk()]

    node = shapes.group(base, "circle")
    body = node.children
    body.extend(builder.rings(base, placed))
    body.extend(builder.edges(top, None))
    for item in placed:
        body.extend(builder.branch_lines(item))
    center = (frame.cx, frame.cy)
    body.append(shapes.circle(center, g2.CORE_RADIUS * frame.scale, f"{base}/name", "core"))
    body.append(
        shapes.text(
            center,
            g2.RITE_CORE_FONT * frame.scale,
            shapes.clip(rite.name, g2.CORE_MAX_CHARS),
            f"{base}/name",
            "core",
        )
    )
    for item in placed:
        body.extend(builder.glyph(item))
    return node


__all__ = ["CAST_HOST", "CAST_RITE", "CAST_SUMMON", "classify_cast", "draw_rite", "place_block"]
