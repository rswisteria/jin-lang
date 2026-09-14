"""Jin v2 の意味モデル → SVG（`docs/spec/v2/layout.md`）。

入口は `jin_render.render`（version で振り分ける）。ここは v2 の陣の図と、手順の図
（`jin_render.v2.rite`）への振り分け、トレースのオーバーレイを持つ。

## 純関数であること（v1 と同じ）

- 入力は意味モデル。ファイルを読まない。モジュールレベルの可変状態を持たない
- 乱数・時刻・`hash()`・`id()`・辞書順序に依存しない。装飾は `hashlib.sha256`
- 意味検査（`jin_core.v2.semantic`）を呼ばない。`cast` の分類は名前表だけで決める

## 壊れたモデルでも落ちない（v2 layout.md §7）

schema を通る `JinFileV2` なら例外を投げない。未解決の参照は破線、型紙の無い state は `?`、
`core` が手順に無ければ核を破線にする。例外を投げるのは引数が壊れているとき
（未定義の `focus` = `RenderError` / トレース行の型違い = `ValueError`）だけ。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from jin_core import canonical
from jin_core.v2.model import PRIMITIVE_TYPES, Circle, Flow, JinFileV2, parse_type

from jin_render import geometry as geo
from jin_render import paths
from jin_render.layout import RenderError, fired_indices, trace_dots
from jin_render.ornament import ornament_dots
from jin_render.overlay import read_trace
from jin_render.svg import DASH, Node, document
from jin_render.v2 import geometry as g2
from jin_render.v2 import shapes
from jin_render.v2.rite import draw_rite

#: `data-jin-kind` の 13 種（v2 layout.md §4・設計書 §7）。v1 の 9 種とは別集合。
DATA_JIN_KINDS_V2: tuple[str, ...] = (
    "stage",
    "form",
    "circle",
    "core",
    "rite",
    "sigil",
    "state",
    "on",
    "guard",
    "delegate",
    "flow-edge",
    "step",
    "step-edge",
)

#: 組み込みの型紙（`abilities.md`）。state の型の解決に使う。
BUILTIN_FORMS = ("Pointer",)

#: v2 のトレースの `seq` は `boot` から通しの 0 始まり（runtime.md §5）。
TRACE_MIN_SEQ = 0


def split_focus(focus: str) -> tuple[str, str | None]:
    """`--focus` を `(陣名, 手順名 | None)` にする。`/` は 1 つまで。"""
    if "/" not in focus:
        return focus, None
    circle, rite = focus.split("/", 1)
    if not circle or not rite or "/" in rite:
        raise RenderError(f"focus '{focus}' の形が違います（陣名 または 陣名/手順名）")
    return circle, rite


def type_resolves(type_text: str, form_names: frozenset[str]) -> bool:
    """state / 欄の型が解決できるか（`num` / `bool` / `str` / 型紙名 / それらの `list<…>`）。"""
    try:
        head, inner = parse_type(type_text)
        while head == "list" and inner is not None:
            head, inner = parse_type(inner)
    except ValueError:
        return False
    return head in PRIMITIVE_TYPES or head in form_names


# --------------------------------------------------------------------------------------
# 陣の図
# --------------------------------------------------------------------------------------
@dataclass
class _Builder:
    """1 回の `render_v2` の中だけで生きる組み立て器。"""

    model: JinFileV2
    index_of: dict[str, int]
    form_names: frozenset[str]

    # -- 額縁と型紙（v2 layout.md §1） ----------------------------------------------------
    def stage(self, frame: geo.Frame) -> Node:
        """額縁と型紙の印章。線の既定を持つ `<g>`（`/stage`）に包む（塗りの既定を効かせない）。"""
        stage = self.model.stage
        half = g2.STAGE_HALF * frame.scale
        node = shapes.group("/stage", "stage")
        out = node.children
        out += [
            shapes.path(shapes.square_d_at((frame.cx, frame.cy), half), "/stage", "stage"),
            shapes.text(
                (
                    frame.cx,
                    frame.cy
                    - (g2.STAGE_HALF + g2.STAGE_LABEL_GAP + g2.STAGE_FONT / 2.0) * frame.scale,
                ),
                g2.STAGE_FONT * frame.scale,
                f"{stage.width}×{stage.height} @{stage.fps}",
                "/stage",
                "stage",
            ),
        ]
        origin_x = frame.cx - (g2.STAGE_HALF - g2.FORM_SEAL_INSET) * frame.scale
        origin_y = frame.cy - (g2.STAGE_HALF - g2.FORM_SEAL_INSET) * frame.scale
        for position, form in enumerate(self.model.forms):
            center = (origin_x + position * g2.FORM_SEAL_PITCH * frame.scale, origin_y)
            pointer = f"/forms/{position}"
            out.append(
                shapes.path(
                    shapes.square_d_at(center, g2.FORM_SEAL_HALF * frame.scale), pointer, "form"
                )
            )
            out.append(
                shapes.text(
                    center, g2.FORM_FONT * frame.scale, shapes.initial(form.name), pointer, "form"
                )
            )
        return node

    # -- 陣 ------------------------------------------------------------------------------
    def draw_circle(self, index: int, frame: geo.Frame, depth: int) -> Node:
        circle = self.model.circles[index]
        base = f"/circles/{index}"
        node = shapes.group(base, "circle")
        body = node.children
        body.extend(self._rings(circle, base, frame))
        body.extend(self._flow_edges(circle, base, frame, depth))
        body.extend(self._radials(circle, base, frame, depth))
        body.extend(self._core_line(circle, base, frame))
        body.extend(self._delegate_lines(circle, base, frame))
        body.extend(self._core(circle, base, frame))
        body.extend(self._sigils(circle, base, frame, depth))
        body.extend(self._flow_nodes(circle, base, frame, depth))
        body.extend(self._rites(circle, base, frame))
        body.extend(self._states(circle, base, frame))
        body.extend(self._delegates(circle, base, frame))
        body.extend(self._marks(circle, base, frame))
        body.extend(self._ornament(circle, base, frame))
        return node

    @staticmethod
    def _core_rite_index(circle: Circle) -> int | None:
        """`core` が指す手順の添字（先に宣言されたほう）。無ければ `None`（JIN011）。"""
        if circle.core is None:
            return None
        for position, rite in enumerate(circle.rites):
            if rite.name == circle.core:
                return position
        return None

    @staticmethod
    def _has_boundary_ring(circle: Circle) -> bool:
        return circle.boundary is not None or bool(circle.delegate)

    def _ring(self, base: str, frame: geo.Frame, radius: float) -> Node:
        return shapes.circle((frame.cx, frame.cy), radius * frame.scale, base, "circle")

    def _rings(self, circle: Circle, base: str, frame: geo.Frame) -> list[Node]:
        """存在する環だけを描く。半径は詰めない（v2 layout.md §2）。核なし陣は 1 本も描かない。"""
        if circle.core is None:
            return []
        out: list[Node] = []
        if circle.rites:
            out.append(self._ring(base, frame, g2.RING_RITES))
        if circle.sigils:
            out.append(self._ring(base, frame, g2.RING_SIGILS))
        if circle.state:
            out.append(self._ring(base, frame, g2.RING_STATE))
        if self._has_boundary_ring(circle):
            out.append(self._ring(base, frame, g2.RING_BOUNDARY))
        return out

    # -- 核 ------------------------------------------------------------------------------
    def _core(self, circle: Circle, base: str, frame: geo.Frame) -> list[Node]:
        if circle.core is None:
            return []
        pointer = f"{base}/core"
        center = (frame.cx, frame.cy)
        unresolved = self._core_rite_index(circle) is None
        return [
            shapes.circle(center, g2.CORE_RADIUS * frame.scale, pointer, "core", dashed=unresolved),
            shapes.text(
                center,
                g2.CORE_FONT * frame.scale,
                shapes.clip(circle.core, g2.CORE_MAX_CHARS),
                pointer,
                "core",
            ),
        ]

    def _core_line(self, circle: Circle, base: str, frame: geo.Frame) -> list[Node]:
        """核から `core` の手順の小陣へ実線（v2 layout.md §2）。"""
        target = self._core_rite_index(circle)
        if target is None:
            return []
        angle = geo.angle_at(target, len(circle.rites))
        return [
            shapes.line(
                geo.point(frame, g2.CORE_RADIUS, angle),
                geo.point(frame, g2.RING_RITES - g2.RITE_GLYPH_RADIUS, angle),
                f"{base}/core",
                "core",
            )
        ]

    def _ornament(self, circle: Circle, base: str, frame: geo.Frame) -> list[Node]:
        """装飾は `core` の手順の正準 JSON の SHA-256 から（v2 layout.md §5）。"""
        target = self._core_rite_index(circle)
        if target is None:
            return []
        out: list[Node] = []
        for angle, radius, size in ornament_dots(canonical.dumps(circle.rites[target])):
            out.append(
                shapes.circle(
                    geo.point(frame, radius, angle),
                    size * frame.scale,
                    f"{base}/core",
                    "core",
                    filled=True,
                )
            )
        return out

    # -- 手順環 --------------------------------------------------------------------------
    def _rites(self, circle: Circle, base: str, frame: geo.Frame) -> list[Node]:
        count = len(circle.rites)
        out: list[Node] = []
        for position, rite in enumerate(circle.rites):
            angle = geo.angle_at(position, count)
            center = geo.point(frame, g2.RING_RITES, angle)
            pointer = f"{base}/rites/{position}"
            out.append(shapes.circle(center, g2.RITE_GLYPH_RADIUS * frame.scale, pointer, "rite"))
            out.append(
                shapes.text(
                    center, g2.RITE_FONT * frame.scale, shapes.initial(rite.name), pointer, "rite"
                )
            )
        return out

    # -- 道具環 --------------------------------------------------------------------------
    def _sigil_extent(self, circle: Circle, position: int, depth: int) -> float:
        sigil = circle.sigils[position]
        if sigil.kind != "summon":
            return g2.SIGIL_GLYPH_RADIUS
        return self._reference_size(sigil.circle, depth)[0]

    def _radials(self, circle: Circle, base: str, frame: geo.Frame, depth: int) -> list[Node]:
        if circle.core is None or not circle.sigils:
            return []
        count = len(circle.sigils)
        out: list[Node] = []
        for position in range(count):
            angle = geo.angle_at(position, count)
            out.append(
                shapes.line(
                    geo.point(frame, g2.CORE_RADIUS, angle),
                    geo.point(
                        frame, g2.RING_SIGILS - self._sigil_extent(circle, position, depth), angle
                    ),
                    f"{base}/sigils/{position}",
                    "sigil",
                )
            )
        return out

    def _sigils(self, circle: Circle, base: str, frame: geo.Frame, depth: int) -> list[Node]:
        count = len(circle.sigils)
        out: list[Node] = []
        for position, sigil in enumerate(circle.sigils):
            angle = geo.angle_at(position, count)
            center = geo.point(frame, g2.RING_SIGILS, angle)
            pointer = f"{base}/sigils/{position}"
            if sigil.kind == "summon":
                out.append(self._reference(sigil.circle, pointer, "sigil", center, frame, depth))
                continue
            out.append(shapes.circle(center, g2.SIGIL_GLYPH_RADIUS * frame.scale, pointer, "sigil"))
            out.append(
                shapes.text(
                    center,
                    g2.SIGIL_FONT * frame.scale,
                    # host は名前空間名、agent（v2.1）は sigil 名の頭文字（v1 の陣は入れ子に描かない）
                    shapes.initial(sigil.host if sigil.kind == "host" else sigil.name),
                    pointer,
                    "sigil",
                )
            )
        return out

    # -- 参照（入れ子の小陣。v1 と同じ規則） -------------------------------------------------
    def _outer_extent(self, index: int) -> float:
        """circle `index` の主要素の外接半径（その circle 自身の単位）。存在する要素だけから求める。"""
        circle = self.model.circles[index]
        reach = [geo.POINT_RADIUS]
        if circle.core is not None:
            reach.append(g2.CORE_RADIUS)
        if circle.rites:
            reach.append(g2.RING_RITES + g2.RITE_GLYPH_RADIUS)
        if circle.sigils:
            reach.append(g2.RING_SIGILS + g2.SIGIL_GLYPH_RADIUS)
        if circle.flow is not None:
            reach.append(geo.FLOW_RING + geo.POINT_RADIUS)
            if circle.flow.exit is not None:
                reach.append(geo.EXIT_MARK)
        if circle.state:
            reach.append(g2.RING_STATE + g2.STATE_HALF)
        if circle.delegate:
            reach.append(g2.DELEGATE_RING + g2.DELEGATE_RADIUS)
        if self._has_boundary_ring(circle):
            has_mark = circle.boundary is not None and bool(
                circle.boundary.on or circle.boundary.guards
            )
            reach.append(g2.RING_BOUNDARY + (g2.MARK_RADIUS if has_mark else 0.0))
        return max(reach)

    def _reference_size(
        self, name: str, depth: int, limit: float | None = None
    ) -> tuple[float, float | None]:
        """`(外枠の半径, 中身の縮尺係数)`。係数 `None` は「小陣ではなく点」（v1 layout.md §6 と同じ）。"""
        target = self.index_of.get(name)
        if target is None or depth >= 1:
            return (geo.POINT_RADIUS, None)
        natural = geo.NESTED_SCALE * self._outer_extent(target) + geo.SUMMON_GAP
        if limit is None or natural <= limit:
            return (natural, 1.0)
        if limit < geo.POINT_RADIUS:
            return (geo.POINT_RADIUS, None)
        return (limit, limit / natural)

    def _reference(
        self,
        name: str,
        pointer: str,
        kind: str,
        center: tuple[float, float],
        frame: geo.Frame,
        depth: int,
        limit: float | None = None,
    ) -> Node:
        """circle への参照。深さ 1 までは入れ子の小陣、それ以下は点（v2 layout.md §1）。"""
        target = self.index_of.get(name)
        if target is None:
            return paths.dot(center, geo.POINT_RADIUS * frame.scale, pointer, kind, ref=None)
        ref = f"/circles/{target}"
        radius, factor = self._reference_size(name, depth, limit)
        if factor is None:
            return paths.dot(center, radius * frame.scale, pointer, kind, ref=ref)
        wrapper = Node("g", [], pointer=pointer, kind=kind, ref=ref)
        wrapper.children.append(shapes.circle(center, radius * frame.scale, pointer, kind, ref=ref))
        nested = frame.nested(center[0], center[1], geo.NESTED_SCALE * factor)
        wrapper.children.append(self.draw_circle(target, nested, depth + 1))
        return wrapper

    # -- 記憶環 --------------------------------------------------------------------------
    def _states(self, circle: Circle, base: str, frame: geo.Frame) -> list[Node]:
        count = len(circle.state)
        out: list[Node] = []
        for position, state in enumerate(circle.state):
            angle = geo.angle_at(position, count)
            pointer = f"{base}/state/{position}"
            out.append(
                shapes.path(
                    paths.square_d(frame, angle, g2.RING_STATE, g2.STATE_HALF), pointer, "state"
                )
            )
            if state.out:
                # `out: true` は二重線（v2 layout.md §2）。
                out.append(
                    shapes.path(
                        paths.square_d(frame, angle, g2.RING_STATE, g2.STATE_OUT_INNER_HALF),
                        pointer,
                        "state",
                    )
                )
            if not type_resolves(state.type, self.form_names):
                # 型紙の無い state（JIN011）は四角の中に `?`（v2 layout.md §7）。
                out.append(
                    shapes.text(
                        geo.point(frame, g2.RING_STATE, angle),
                        g2.STATE_UNKNOWN_FONT * frame.scale,
                        "?",
                        pointer,
                        "state",
                    )
                )
        return out

    # -- 委譲 ----------------------------------------------------------------------------
    def _delegate_lines(self, circle: Circle, base: str, frame: geo.Frame) -> list[Node]:
        count = len(circle.delegate)
        out: list[Node] = []
        for position in range(count):
            angle = geo.angle_at(position, count)
            out.append(
                shapes.line(
                    geo.point(frame, g2.CORE_RADIUS, angle),
                    geo.point(frame, g2.DELEGATE_RING - g2.DELEGATE_RADIUS, angle),
                    f"{base}/delegate/{position}",
                    "delegate",
                    dashed=True,
                )
            )
        return out

    def _delegates(self, circle: Circle, base: str, frame: geo.Frame) -> list[Node]:
        count = len(circle.delegate)
        out: list[Node] = []
        for position, name in enumerate(circle.delegate):
            angle = geo.angle_at(position, count)
            target = self.index_of.get(name)
            out.append(
                paths.dot(
                    geo.point(frame, g2.DELEGATE_RING, angle),
                    g2.DELEGATE_RADIUS * frame.scale,
                    f"{base}/delegate/{position}",
                    "delegate",
                    ref=None if target is None else f"/circles/{target}",
                )
            )
        return out

    # -- 境界環の刻印 ---------------------------------------------------------------------
    def _marks(self, circle: Circle, base: str, frame: geo.Frame) -> list[Node]:
        """`on`（◇ + イベント名の頭文字）を先に、`guards`（△）を後に、1 つの列として等角配置。"""
        if circle.boundary is None:
            return []
        items: list[tuple[str, int]] = [("on", j) for j in range(len(circle.boundary.on))]
        items += [("guard", j) for j in range(len(circle.boundary.guards))]
        count = len(items)
        out: list[Node] = []
        for position, (kind, index) in enumerate(items):
            angle = geo.angle_at(position, count)
            center = geo.point(frame, g2.RING_BOUNDARY, angle)
            radius = g2.MARK_RADIUS * frame.scale
            if kind == "on":
                pointer = f"{base}/boundary/on/{index}"
                out.append(
                    shapes.path(paths.polygon_d(center, radius, 4, 1, geo.TOP_ANGLE), pointer, "on")
                )
                out.append(
                    shapes.text(
                        center,
                        g2.ON_FONT * frame.scale,
                        shapes.initial(circle.boundary.on[index].event),
                        pointer,
                        "on",
                    )
                )
            else:
                pointer = f"{base}/boundary/guards/{index}"
                out.append(
                    shapes.path(
                        paths.polygon_d(center, radius, 3, 1, geo.TOP_ANGLE), pointer, "guard"
                    )
                )
        return out

    # -- flow（v1 と同じ規則。v2 layout.md §1） ----------------------------------------------
    def _flow_node_limit(self, count: int) -> float:
        if count < 2:
            return math.inf
        return geo.FLOW_RING * math.sin(math.pi / count) - (geo.ARROW_HEAD + geo.FLOW_NODE_EPSILON)

    def _flow_extent(self, flow: Flow, position: int, depth: int) -> float:
        return self._reference_size(
            flow.steps[position], depth, self._flow_node_limit(len(flow.steps))
        )[0]

    @staticmethod
    def _flow_slots(flow: Flow) -> list[int]:
        count = len(flow.steps)
        step = geo.star_step(count) if flow.kind == "loop" else 1
        return [(j * step) % count for j in range(count)]

    def _flow_edges(self, circle: Circle, base: str, frame: geo.Frame, depth: int) -> list[Node]:
        if circle.flow is None:
            return []
        steps = circle.flow.steps
        count = len(steps)
        out: list[Node] = []
        if count:
            slots = self._flow_slots(circle.flow)
            positions = [
                geo.point(frame, geo.FLOW_RING, geo.angle_at(slots[j], count)) for j in range(count)
            ]
            if circle.flow.kind == "sequence":
                pairs = [(j, j + 1) for j in range(count - 1)]
            elif circle.flow.kind == "loop":
                pairs = [(j, (j + 1) % count) for j in range(count)]
            else:
                pairs = []
            for source, target in pairs:
                if source == target:
                    continue
                d = paths.arrow_d(
                    positions[source],
                    positions[target],
                    self._flow_extent(circle.flow, source, depth) * frame.scale,
                    self._flow_extent(circle.flow, target, depth) * frame.scale,
                    geo.ARROW_HEAD * frame.scale,
                )
                if d is None:
                    continue
                out.append(shapes.path(d, f"{base}/flow", "flow-edge"))
        if circle.flow.exit is not None:
            out.append(
                shapes.path(paths.diamond_d(frame, geo.EXIT_MARK), f"{base}/flow/exit", "flow-edge")
            )
        return out

    def _flow_nodes(self, circle: Circle, base: str, frame: geo.Frame, depth: int) -> list[Node]:
        if circle.flow is None:
            return []
        steps = circle.flow.steps
        count = len(steps)
        slots = self._flow_slots(circle.flow)
        limit = self._flow_node_limit(count)
        out: list[Node] = []
        for position, name in enumerate(steps):
            center = geo.point(frame, geo.FLOW_RING, geo.angle_at(slots[position], count))
            out.append(
                self._reference(
                    name, f"{base}/flow/steps/{position}", "flow-edge", center, frame, depth, limit
                )
            )
        return out


# --------------------------------------------------------------------------------------
# 公開 API（`jin_render.render` から呼ばれる）
# --------------------------------------------------------------------------------------
def render_v2(
    model: JinFileV2,
    *,
    focus: str | None = None,
    trace: Sequence[Mapping[str, Any]] | None = None,
    upto: int | None = None,
) -> str:
    """v2 の意味モデルを SVG 文字列にする。同じ入力なら常にバイト単位で同じ。

    - `focus`: `陣名`（陣の図）または `陣名/手順名`（手順の図）。省略時は `root` の陣
    - `trace`: `seq`（0 始まり）と `pointer` を持つ行の並び（`jin run --trace` の JSONL）
    - `upto`: `seq <= upto` の行まで発火済みとみなす。省略時は全行
    """
    if upto is not None and trace is None:
        raise ValueError(
            "upto は trace と一緒にしか使えません（trace が無いと seq を数えられません）"
        )
    if upto is not None and upto < 0:
        raise ValueError(f"upto は 0 以上でなければなりません: {upto}")

    all_rows = read_trace(trace, min_seq=TRACE_MIN_SEQ) if trace is not None else []
    fired_rows = [row for row in all_rows if upto is None or row.seq <= upto]

    index_of: dict[str, int] = {}
    for position, circle in enumerate(model.circles):
        index_of.setdefault(circle.name, position)

    root_unresolved = False
    rite_index: int | None = None
    if focus is not None:
        circle_name, rite_name = split_focus(focus)
        if circle_name not in index_of:
            names = "、".join(circle.name for circle in model.circles)
            raise RenderError(f"focus '{circle_name}' という陣はありません。定義済みの陣: {names}")
        focus_index = index_of[circle_name]
        if rite_name is not None:
            rites = model.circles[focus_index].rites
            found = [j for j, rite in enumerate(rites) if rite.name == rite_name]
            if not found:
                names = "、".join(rite.name for rite in rites) or "（手順がありません）"
                raise RenderError(
                    f"focus '{focus}' という手順はありません。陣 {circle_name} の手順: {names}"
                )
            rite_index = found[0]
    elif model.root in index_of:
        focus_index = index_of[model.root]
    else:
        # JIN060（root が未定義）。落ちずに circles[0] を描き、印を付ける（v1 layout.md §5 と同じ）。
        focus_index = 0
        root_unresolved = True

    form_names = frozenset(form.name for form in model.forms) | frozenset(BUILTIN_FORMS)
    builder = _Builder(model=model, index_of=index_of, form_names=form_names)
    frame = geo.root_frame()
    body: list[Node] = [builder.stage(frame)]
    if rite_index is None:
        group = builder.draw_circle(focus_index, frame, 0)
        focus_pointer = f"/circles/{focus_index}"
    else:
        group = draw_rite(model, focus_index, rite_index, frame, index_of)
        focus_pointer = f"/circles/{focus_index}/rites/{rite_index}"
    if root_unresolved:
        group.attrs.append(("stroke-dasharray", DASH))
        group.attrs.append(("data-jin-root", "unresolved"))
    body.append(group)
    if trace is not None:
        # 額縁と型紙は強調の対象にしない（`frame` 行の `/stage` は点にだけ数える・v2 layout.md §6）。
        elements = group.walk()
        for position in sorted(fired_indices(elements, fired_rows)):
            elements[position].fired = True
        group.children.extend(trace_dots(frame, focus_pointer, len(all_rows), fired_rows))
    return document([], body, geo.CANVAS_PX)


__all__ = [
    "BUILTIN_FORMS",
    "DATA_JIN_KINDS_V2",
    "TRACE_MIN_SEQ",
    "render_v2",
    "split_focus",
    "type_resolves",
]
