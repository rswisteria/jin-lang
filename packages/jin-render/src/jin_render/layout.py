"""意味モデル → SVG（`docs/spec/layout.md`）。

`jin_render.render` が唯一の入口である（要件書 §4 最終項「CLI の `jin render` と LSP の
`jin/renderSvg` は同じ関数を呼び、同じ出力を返す」）。

## 純関数であること

- 入力は意味モデル。**ファイルを読まない**（要件書 §4）。`open` も `Path` も使わない
- モジュールレベルの可変状態を持たない。キャッシュの存在を知らない（DP-COMMON-07 の constraint）
- 乱数・時刻・`hash()`・`id()`・辞書順序に依存しない。装飾は `hashlib.sha256`

## 壊れたモデルでも落ちない

Phase 4 の `jin/renderSvg` は JSON 構文エラー中に**直前の正常モデル**で応答する（NFR-AVAIL-001）。
その「正常」は「パースでき schema を通った」までなので、意味エラー（未定義 circle への `summon` /
`delegate` / `steps`、JIN012 の循環、JIN013 の多重親、JIN022 の core と flow の両立 …）を含みうる。
したがって **schema を通る `JinFile` なら例外を投げない**。例外を投げるのは引数が壊れているとき
（未定義の `focus` = `RenderError` / トレース行の型違い = `ValueError`）だけである。

- 解決できない参照は破線の点で描き、`data-jin` にはその**参照側**の pointer を付ける
- 循環しても無限展開しない: 展開は深さ 1 まで（layout.md §2）で構造的に止まる
- `root` が未定義なら `circles[0]` に落とし、陣全体を破線 + `data-jin-root="unresolved"` にする
- `circles` が空なら空のキャンバスだけを返す
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from jin_core.model import Boundary, Circle, Flow, JinFile

from jin_render import geometry as geo
from jin_render.ornament import ornament_dots
from jin_render.overlay import TraceRow, is_ancestor_or_same, read_trace
from jin_render.svg import (
    DASH,
    FONT_FAMILY,
    INK,
    OUT_STROKE_WIDTH,
    STROKE_WIDTH,
    Node,
    document,
    fmt_coord,
)

#: `data-jin-kind` の 9 種（要件書 §2.5 / layout.md §3）。**10 種目を増やさない。**
DATA_JIN_KINDS: tuple[str, ...] = (
    "circle",
    "core",
    "rune",
    "tool",
    "state",
    "flow-edge",
    "guard",
    "await",
    "delegate",
)

#: 矢じりの長さは `geometry` にある（layout.md §6「定数は geometry」・F-V-P3-017）。
#: ここは再輸出（テストと `__all__` の互換のため）。
ARROW_HEAD = geo.ARROW_HEAD

#: 指示環に収まる rune の文字数。周長 / 文字の高さ で決まるので**縮尺に依らない**
#: （入れ子の小陣でも同じ位置で切り詰める）。
RUNE_MAX_CHARS = max(1, int(2.0 * math.pi * geo.RING_INSTRUCTION / geo.RUNE_FONT))

#: 切り詰めたことを示す記号。
RUNE_ELLIPSIS = "…"


class RenderError(Exception):
    """描画できない引数（未定義の `focus` など）。

    **診断コード（JINxxx）は増やさない**（`CLAUDE.md` / ADR-012）。描画の失敗は
    `.jin` の意味エラーではなく呼び出し側の引数の誤りである。
    """


# --------------------------------------------------------------------------------------
# パス生成（数値はすべて fmt_coord を通す）
# --------------------------------------------------------------------------------------
def _move(point: tuple[float, float]) -> str:
    return f"M {fmt_coord(point[0])} {fmt_coord(point[1])}"


def _line_to(point: tuple[float, float]) -> str:
    return f"L {fmt_coord(point[0])} {fmt_coord(point[1])}"


def _curve_to(c1: tuple[float, float], c2: tuple[float, float], end: tuple[float, float]) -> str:
    return (
        f"C {fmt_coord(c1[0])} {fmt_coord(c1[1])} "
        f"{fmt_coord(c2[0])} {fmt_coord(c2[1])} "
        f"{fmt_coord(end[0])} {fmt_coord(end[1])}"
    )


def _arc_d(frame: geo.Frame, radius: float, start_deg: float, sweep_deg: float) -> str:
    start, segments = geo.arc_segments(frame, radius, start_deg, sweep_deg)
    return " ".join([_move(start)] + [_curve_to(*segment) for segment in segments])


def _square_d(frame: geo.Frame, angle_deg: float, radius: float, half: float) -> str:
    """半径方向と接線方向に辺を持つ正方形。`transform` を使わずに 4 頂点を直接計算する。"""
    cx, cy = geo.point(frame, radius, angle_deg)
    theta = math.radians(angle_deg)
    ux, uy = math.cos(theta), math.sin(theta)
    vx, vy = -math.sin(theta), math.cos(theta)
    size = half * frame.scale
    corners = [
        (cx + size * (ux + vx), cy + size * (uy + vy)),
        (cx + size * (-ux + vx), cy + size * (-uy + vy)),
        (cx + size * (-ux - vx), cy + size * (-uy - vy)),
        (cx + size * (ux - vx), cy + size * (uy - vy)),
    ]
    return " ".join(
        [_move(corners[0]), _line_to(corners[1]), _line_to(corners[2]), _line_to(corners[3]), "Z"]
    )


def _diamond_d(frame: geo.Frame, radius: float) -> str:
    size = radius * frame.scale
    cx, cy = frame.cx, frame.cy
    corners = [(cx, cy - size), (cx + size, cy), (cx, cy + size), (cx - size, cy)]
    return " ".join(
        [_move(corners[0]), _line_to(corners[1]), _line_to(corners[2]), _line_to(corners[3]), "Z"]
    )


def _arrow_d(
    start: tuple[float, float],
    end: tuple[float, float],
    gap_start: float,
    gap_end: float,
    head: float,
) -> str | None:
    """両端を `gap_*` だけ詰めた線分。`head > 0` なら終端に矢じりを足す。

    詰めたあとに長さが残らない（節が重なっている）ときは `None`（描かない）。
    """
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= gap_start + gap_end:
        return None
    ux, uy = dx / length, dy / length
    tail = (start[0] + ux * gap_start, start[1] + uy * gap_start)
    tip = (end[0] - ux * gap_end, end[1] - uy * gap_end)
    parts = [_move(tail), _line_to(tip)]
    if head > 0.0:
        back = (tip[0] - ux * head, tip[1] - uy * head)
        wing = head * 0.5
        nx, ny = -uy, ux
        parts += [
            _move((back[0] + nx * wing, back[1] + ny * wing)),
            _line_to(tip),
            _line_to((back[0] - nx * wing, back[1] - ny * wing)),
        ]
    return " ".join(parts)


def _dot(
    center: tuple[float, float], radius: float, pointer: str, kind: str, *, ref: str | None
) -> Node:
    attrs = [
        ("cx", fmt_coord(center[0])),
        ("cy", fmt_coord(center[1])),
        ("r", fmt_coord(radius)),
    ]
    if ref is None:
        # 解決できない参照は破線の空円（layout.md §5）。
        attrs.append(("stroke-dasharray", DASH))
    return Node("circle", attrs, pointer=pointer, kind=kind, ref=ref)


def fit_rune(text: str) -> str:
    """指示環に沿わせる文字列。空白の並びを 1 個に潰し、長すぎれば決定的に切り詰める。"""
    flat = " ".join(text.split())
    if len(flat) <= RUNE_MAX_CHARS:
        return flat
    return flat[: RUNE_MAX_CHARS - 1] + RUNE_ELLIPSIS


# --------------------------------------------------------------------------------------
# 陣を描く
# --------------------------------------------------------------------------------------
@dataclass
class _Builder:
    """1 回の `render` の中だけで生きる組み立て器（モジュールレベルの状態を持たないため）。"""

    model: JinFile
    index_of: dict[str, int]
    defs: list[Node] = field(default_factory=list)
    _rune_paths: int = 0

    def _next_rune_id(self) -> str:
        """`<textPath>` が参照する `<path>` の id。

        pointer をそのまま id にしない（`/` は XML の NCName に使えない）。同じ circle を
        2 回描いても衝突しないよう、**描画順の連番**にする。
        """
        name = f"jin-rune-{self._rune_paths}"
        self._rune_paths += 1
        return name

    # -- 陣 ------------------------------------------------------------------------------
    def draw_circle(self, index: int, frame: geo.Frame, depth: int) -> Node:
        circle = self.model.circles[index]
        base = f"/circles/{index}"
        group = Node(
            "g",
            [
                ("fill", "none"),
                ("stroke", INK),
                ("stroke-width", fmt_coord(STROKE_WIDTH)),
                ("stroke-linecap", "round"),
                ("stroke-linejoin", "round"),
            ],
            pointer=base,
            kind="circle",
        )
        body = group.children
        body.extend(self._rings(circle, base, frame))
        body.extend(self._flow_edges(circle, base, frame, depth))
        body.extend(self._radials(circle, base, frame, depth))
        body.extend(self._delegate_lines(circle, base, frame))
        if circle.core is not None:
            body.append(
                Node(
                    "circle",
                    [
                        ("cx", fmt_coord(frame.cx)),
                        ("cy", fmt_coord(frame.cy)),
                        ("r", fmt_coord(geo.CORE_RADIUS * frame.scale)),
                    ],
                    pointer=f"{base}/core",
                    kind="core",
                )
            )
        body.extend(self._tools(circle, base, frame, depth))
        body.extend(self._flow_nodes(circle, base, frame, depth))
        body.extend(self._states(circle, base, frame))
        body.extend(self._delegates(circle, base, frame))
        body.extend(self._guards(circle, base, frame))
        body.extend(self._awaits(circle, base, frame))
        body.extend(self._rune(circle, base, frame))
        return group

    # -- 環 ------------------------------------------------------------------------------
    def _ring(self, base: str, frame: geo.Frame, radius: float) -> Node:
        return Node(
            "circle",
            [
                ("cx", fmt_coord(frame.cx)),
                ("cy", fmt_coord(frame.cy)),
                ("r", fmt_coord(radius * frame.scale)),
            ],
            pointer=base,
            kind="circle",
        )

    def _rings(self, circle: Circle, base: str, frame: geo.Frame) -> list[Node]:
        """存在する環だけを描く。**半径は詰めない**（layout.md §1）。"""
        out: list[Node] = []
        if circle.instruction is not None:
            out.append(self._ring(base, frame, geo.RING_INSTRUCTION))
        if circle.tools:
            out.append(self._ring(base, frame, geo.RING_TOOLS))
        if circle.state:
            out.append(self._ring(base, frame, geo.RING_STATE))
        if circle.boundary is not None:
            out.extend(self._boundary_ring(circle, base, frame))
        return out

    @staticmethod
    def _await_angles(circle: Circle, boundary: Boundary) -> list[tuple[int, str, float | None]]:
        """`(添字, 名前, 角度)`。名前が `tools` に無ければ角度は `None`（JIN070）。

        `boundary` を引数で受ける（`assert` は `-O` で消えるので前提条件の置き場にしない・
        F-V-P3-020）。呼び出し側が `None` を弾いてから渡す。
        """
        names = [tool.name for tool in circle.tools]
        out: list[tuple[int, str, float | None]] = []
        for position, name in enumerate(boundary.await_):
            angle = geo.angle_at(names.index(name), len(names)) if name in names else None
            out.append((position, name, angle))
        return out

    def _boundary_ring(self, circle: Circle, base: str, frame: geo.Frame) -> list[Node]:
        gaps = [
            (
                angle - geo.AWAIT_HALF_ANGLE - geo.TOP_ANGLE,
                angle + geo.AWAIT_HALF_ANGLE - geo.TOP_ANGLE,
            )
            for _, _, angle in self._await_angles(circle, circle.boundary)
            if angle is not None
        ]
        if not gaps:
            return [self._ring(base, frame, geo.RING_BOUNDARY)]
        out: list[Node] = []
        for start, sweep in geo.complement_arcs(gaps):
            d = _arc_d(frame, geo.RING_BOUNDARY, geo.TOP_ANGLE + start, sweep)
            out.append(Node("path", [("d", d)], pointer=base, kind="circle"))
        return out

    # -- 入れ子の大きさ --------------------------------------------------------------------
    def _outer_extent(self, index: int) -> float:
        """circle `index` の**主要素の外接半径**（その circle 自身の単位）。

        `RING_BOUNDARY` 固定ではない。境界の無い陣（`examples/pipeline` の Drafter は
        指示環 0.35 までしか描かない）では、放射線と flow の弦が小陣の外側で止まっていた
        （F-C-P3-005）。**存在する要素だけ**から求める（layout.md §1「半径は詰めない」の系）。

        四角（`builtin` の紋・記憶の四角）は半径方向・接線方向とも ±half の正方形なので、
        角は `hypot(環 + half, half)` まで届き、下の列挙を 0.0029 / 0.0016 だけ超える
        （F-C-P3-102）。この差は隙間 `SUMMON_GAP`（0.04）に吸収され、外枠が中身に接する
        ことは無い。角まで数えないのは、外枠の半径が紋の**向き**に依存しないほうが
        読み手に予測しやすいためである。
        """
        circle = self.model.circles[index]
        reach = [geo.POINT_RADIUS]
        if circle.core is not None:
            reach.append(geo.CORE_RADIUS)
        if circle.instruction is not None:
            reach.append(geo.RING_INSTRUCTION + geo.RUNE_FONT)
        if circle.tools:
            reach.append(geo.RING_TOOLS + geo.TOOL_GLYPH_RADIUS)
        if circle.flow is not None:
            reach.append(geo.FLOW_RING + geo.POINT_RADIUS)
            if circle.flow.exit is not None:
                reach.append(geo.EXIT_MARK)
        if circle.state:
            reach.append(geo.RING_STATE + geo.STATE_HALF)
        if circle.delegate:
            reach.append(geo.DELEGATE_RING + geo.DELEGATE_RADIUS)
        if circle.boundary is not None:
            has_tick = bool(circle.boundary.guards) or bool(circle.boundary.await_)
            reach.append(geo.RING_BOUNDARY + (geo.GUARD_TICK_HALF if has_tick else 0.0))
        return max(reach)

    def _summon_extent(self, name: str, depth: int) -> float:
        """参照の紋が占める半径（参照する側の単位）。兄弟の数は見ない（道具環の紋）。"""
        return self._reference_size(name, depth)[0]

    def _reference_size(
        self, name: str, depth: int, limit: float | None = None
    ) -> tuple[float, float | None]:
        """`(外枠の半径, 中身の縮尺係数)`。係数 `None` は「小陣ではなく点を描く」。

        `limit` は外枠に許される最大半径（参照する側の単位）。`None` なら制限しない。
        制限に掛かったときは**外枠だけを詰めない**。外枠・中身・隙間を同じ係数で
        縮めるので、中身が外枠からはみ出すことは無い（F-C-P3-101）。
        """
        target = self.index_of.get(name)
        if target is None or depth >= 1:
            return (geo.POINT_RADIUS, None)
        natural = geo.NESTED_SCALE * self._outer_extent(target) + geo.SUMMON_GAP
        if limit is None or natural <= limit:
            return (natural, 1.0)
        if limit < geo.POINT_RADIUS:
            # ここまで詰まると小陣として読めない。点に落とす（layout.md §6 の下限）。
            return (geo.POINT_RADIUS, None)
        return (limit, limit / natural)

    def _flow_node_limit(self, count: int) -> float:
        """flow の節 1 つに許される外枠の半径（layout.md §6）。

        隣り合う節の中心距離は `2 * FLOW_RING * sin(pi / n)` である。両端の外枠を引いた
        残りが弦の本体になるので、外枠が半径の半分を超えると弦が 1 本も描かれない
        （`_arrow_d` が `None` を返す）。訪問順を示す弦がモデルの大きさで**黙って消える**
        のを防ぐため、外枠を

            r <= FLOW_RING * sin(pi / n) - (ARROW_HEAD + FLOW_NODE_EPSILON)

        に収める。これで本体長は `2 * (ARROW_HEAD + FLOW_NODE_EPSILON)` 以上になり、
        矢じりが必ず収まる。`loop` の弦（角位置 s -> s+k）は隣接より長いので、
        隣接距離だけを見れば足りる。
        """
        if count < 2:
            return math.inf
        return geo.FLOW_RING * math.sin(math.pi / count) - (geo.ARROW_HEAD + geo.FLOW_NODE_EPSILON)

    # -- 核と道具 -------------------------------------------------------------------------
    def _tool_extent(self, circle: Circle, position: int, depth: int) -> float:
        tool = circle.tools[position]
        if tool.kind != "summon":
            return geo.TOOL_GLYPH_RADIUS
        return self._summon_extent(tool.circle, depth)

    def _radials(self, circle: Circle, base: str, frame: geo.Frame, depth: int) -> list[Node]:
        if circle.core is None or not circle.tools:
            return []
        count = len(circle.tools)
        out: list[Node] = []
        for position in range(count):
            angle = geo.angle_at(position, count)
            start = geo.point(frame, geo.CORE_RADIUS, angle)
            end = geo.point(
                frame, geo.RING_TOOLS - self._tool_extent(circle, position, depth), angle
            )
            out.append(
                Node(
                    "line",
                    [
                        ("x1", fmt_coord(start[0])),
                        ("y1", fmt_coord(start[1])),
                        ("x2", fmt_coord(end[0])),
                        ("y2", fmt_coord(end[1])),
                    ],
                    pointer=f"{base}/tools/{position}",
                    kind="tool",
                )
            )
        return out

    def _tools(self, circle: Circle, base: str, frame: geo.Frame, depth: int) -> list[Node]:
        count = len(circle.tools)
        out: list[Node] = []
        for position, tool in enumerate(circle.tools):
            angle = geo.angle_at(position, count)
            center = geo.point(frame, geo.RING_TOOLS, angle)
            pointer = f"{base}/tools/{position}"
            if tool.kind == "summon":
                out.append(self._reference(tool.circle, pointer, "tool", center, frame, depth))
            elif tool.kind == "builtin":
                out.append(
                    Node(
                        "path",
                        [("d", _square_d(frame, angle, geo.RING_TOOLS, geo.TOOL_GLYPH_RADIUS))],
                        pointer=pointer,
                        kind="tool",
                    )
                )
            else:
                out.append(
                    Node(
                        "circle",
                        [
                            ("cx", fmt_coord(center[0])),
                            ("cy", fmt_coord(center[1])),
                            ("r", fmt_coord(geo.TOOL_GLYPH_RADIUS * frame.scale)),
                        ],
                        pointer=pointer,
                        kind="tool",
                    )
                )
        return out

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
        """circle への参照を描く。深さ 1 までは入れ子の小陣、それ以下は点（layout.md §2）。

        `data-jin` は**参照側**の pointer（編集の hit-test はここを掴む）、参照先は
        `data-jin-ref` に置く（DP-IMPL-JIN-P3-OVERLAY-REFERENT-01）。
        """
        target = self.index_of.get(name)
        if target is None:
            return _dot(center, geo.POINT_RADIUS * frame.scale, pointer, kind, ref=None)
        radius, factor = self._reference_size(name, depth, limit)
        if factor is None:
            return _dot(
                center,
                radius * frame.scale,
                pointer,
                kind,
                ref=None if target is None else f"/circles/{target}",
            )
        wrapper = Node("g", [], pointer=pointer, kind=kind, ref=f"/circles/{target}")
        # 参照そのものを表す**見える**外枠。wrapper の朱は入れ子 `<g>` の `stroke` に
        # 断たれるので、参照側 pointer を持つ描画要素をここに 1 つ置く（F-C-P3-003）。
        # 半径は入れ子の**主要素の外接半径** + 隙間（`_outer_extent` は四角の角を
        # 数えない・F-C-P3-102）。flow の節では兄弟間隔でさらに縮む（F-C-P3-101）。
        wrapper.children.append(
            Node(
                "circle",
                [
                    ("cx", fmt_coord(center[0])),
                    ("cy", fmt_coord(center[1])),
                    ("r", fmt_coord(radius * frame.scale)),
                ],
                pointer=pointer,
                kind=kind,
                ref=f"/circles/{target}",
            )
        )
        nested = frame.nested(center[0], center[1], geo.NESTED_SCALE * factor)
        wrapper.children.append(self.draw_circle(target, nested, depth + 1))
        return wrapper

    # -- 記憶 ----------------------------------------------------------------------------
    def _states(self, circle: Circle, base: str, frame: geo.Frame) -> list[Node]:
        count = len(circle.state)
        out: list[Node] = []
        for position, state in enumerate(circle.state):
            angle = geo.angle_at(position, count)
            attrs = [("d", _square_d(frame, angle, geo.RING_STATE, geo.STATE_HALF))]
            if state.out:
                # `out: true` だけが ADK の output_key になる（要件書 §3.3）。太い線で描き分ける。
                attrs.append(("stroke-width", fmt_coord(OUT_STROKE_WIDTH)))
            out.append(Node("path", attrs, pointer=f"{base}/state/{position}", kind="state"))
        return out

    # -- 委譲 ----------------------------------------------------------------------------
    def _delegate_lines(self, circle: Circle, base: str, frame: geo.Frame) -> list[Node]:
        count = len(circle.delegate)
        out: list[Node] = []
        for position in range(count):
            angle = geo.angle_at(position, count)
            start = (
                geo.point(frame, geo.CORE_RADIUS, angle)
                if circle.core is not None
                else (frame.cx, frame.cy)
            )
            end = geo.point(frame, geo.DELEGATE_RING - geo.DELEGATE_RADIUS, angle)
            out.append(
                Node(
                    "line",
                    [
                        ("x1", fmt_coord(start[0])),
                        ("y1", fmt_coord(start[1])),
                        ("x2", fmt_coord(end[0])),
                        ("y2", fmt_coord(end[1])),
                        ("stroke-dasharray", DASH),
                    ],
                    pointer=f"{base}/delegate/{position}",
                    kind="delegate",
                )
            )
        return out

    def _delegates(self, circle: Circle, base: str, frame: geo.Frame) -> list[Node]:
        count = len(circle.delegate)
        out: list[Node] = []
        for position, name in enumerate(circle.delegate):
            angle = geo.angle_at(position, count)
            center = geo.point(frame, geo.DELEGATE_RING, angle)
            target = self.index_of.get(name)
            out.append(
                _dot(
                    center,
                    geo.DELEGATE_RADIUS * frame.scale,
                    f"{base}/delegate/{position}",
                    "delegate",
                    ref=None if target is None else f"/circles/{target}",
                )
            )
        return out

    # -- 境界 ----------------------------------------------------------------------------
    def _guards(self, circle: Circle, base: str, frame: geo.Frame) -> list[Node]:
        if circle.boundary is None or not circle.boundary.guards:
            return []
        count = len(circle.boundary.guards)
        out: list[Node] = []
        for position in range(count):
            angle = geo.angle_at(position, count)
            d = " ".join(
                [
                    _move(geo.point(frame, geo.RING_BOUNDARY - geo.GUARD_TICK_HALF, angle)),
                    _line_to(geo.point(frame, geo.RING_BOUNDARY + geo.GUARD_TICK_HALF, angle)),
                ]
            )
            out.append(
                Node(
                    "path",
                    [("d", d)],
                    pointer=f"{base}/boundary/guards/{position}",
                    kind="guard",
                )
            )
        return out

    def _awaits(self, circle: Circle, base: str, frame: geo.Frame) -> list[Node]:
        if circle.boundary is None or not circle.boundary.await_:
            return []
        inner = geo.RING_BOUNDARY - geo.GUARD_TICK_HALF
        outer = geo.RING_BOUNDARY + geo.GUARD_TICK_HALF
        out: list[Node] = []
        for position, _name, angle in self._await_angles(circle, circle.boundary):
            pointer = f"{base}/boundary/await/{position}"
            if angle is None:
                # JIN070: `await` の対象が `tools` に無い。欠けを作れないので 12 時に破線の印。
                d = " ".join(
                    [
                        _move(geo.point(frame, inner, geo.TOP_ANGLE)),
                        _line_to(geo.point(frame, outer, geo.TOP_ANGLE)),
                    ]
                )
                out.append(
                    Node(
                        "path",
                        [("d", d), ("stroke-dasharray", DASH)],
                        pointer=pointer,
                        kind="await",
                    )
                )
                continue
            parts: list[str] = []
            for edge in (angle - geo.AWAIT_HALF_ANGLE, angle + geo.AWAIT_HALF_ANGLE):
                parts.append(_move(geo.point(frame, inner, edge)))
                parts.append(_line_to(geo.point(frame, outer, edge)))
            out.append(Node("path", [("d", " ".join(parts))], pointer=pointer, kind="await"))
        return out

    # -- flow ----------------------------------------------------------------------------
    def _flow_extent(self, flow: Flow, position: int, depth: int) -> float:
        """弦の端に空ける隙間 = 節の外枠の半径。`_flow_nodes` と**同じ関数**から採る。"""
        return self._reference_size(
            flow.steps[position], depth, self._flow_node_limit(len(flow.steps))
        )[0]

    @staticmethod
    def _flow_slots(flow: Flow) -> list[int]:
        """`flow.steps[j]` を置く角位置（layout.md §2.1）。

        `loop` は星形多角形 {n/k} の頂点を **訪問順に** 辿る並びにする: 節 j を
        角位置 `(j*k) mod n` へ置くと、辺 `j → j+1` がそのまま星の辺になる
        （`gcd(n, k) = 1` なので写像は全単射）。矢じりの向きが `flow.steps` の
        実行順と一致する（要件書 §2.5「辺の順を訪問順に一致させる」・F-C-P3-002）。
        `sequence` / `parallel` は k=1（配列順）。
        """
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
                # 辺は**実行順**（j → j+1）。星形は `_flow_slots` の角位置が作る。
                pairs = [(j, (j + 1) % count) for j in range(count)]
            else:
                pairs = []  # parallel は弦なし対称配置（要件書 §2.5）
            for source, target in pairs:
                if source == target:
                    continue
                d = _arrow_d(
                    positions[source],
                    positions[target],
                    self._flow_extent(circle.flow, source, depth) * frame.scale,
                    self._flow_extent(circle.flow, target, depth) * frame.scale,
                    ARROW_HEAD * frame.scale,
                )
                if d is None:
                    continue
                out.append(Node("path", [("d", d)], pointer=f"{base}/flow", kind="flow-edge"))
        if circle.flow.exit is not None:
            # 星形多角形には「閉じ目の辺」が一意に定まらないので、中心に印を置く（layout.md §6）。
            out.append(
                Node(
                    "path",
                    [("d", _diamond_d(frame, geo.EXIT_MARK))],
                    pointer=f"{base}/flow/exit",
                    kind="flow-edge",
                )
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
            angle = geo.angle_at(slots[position], count)
            center = geo.point(frame, geo.FLOW_RING, angle)
            out.append(
                self._reference(
                    name,
                    f"{base}/flow/steps/{position}",
                    "flow-edge",
                    center,
                    frame,
                    depth,
                    limit,
                )
            )
        return out

    # -- 指示環 --------------------------------------------------------------------------
    def _rune(self, circle: Circle, base: str, frame: geo.Frame) -> list[Node]:
        if circle.instruction is None:
            return []
        pointer = f"{base}/instruction/rune"
        rune = circle.instruction.rune
        path_id = self._next_rune_id()
        self.defs.append(
            Node(
                "path",
                [
                    ("id", path_id),
                    ("d", _arc_d(frame, geo.RING_INSTRUCTION, geo.TOP_ANGLE, 360.0)),
                ],
            )
        )
        text = Node(
            "text",
            [
                ("stroke", "none"),
                ("fill", INK),
                ("font-family", FONT_FAMILY),
                ("font-size", fmt_coord(geo.RUNE_FONT * frame.scale)),
            ],
            pointer=pointer,
            kind="rune",
            accent_attr="fill",
        )
        text.children.append(
            Node(
                "textPath",
                [("href", f"#{path_id}")],
                pointer=pointer,
                kind="rune",
                text=fit_rune(rune),
                accent_attr="fill",
            )
        )
        out = [text]
        for angle, radius, size in ornament_dots(rune):
            center = geo.point(frame, radius, angle)
            out.append(
                Node(
                    "circle",
                    [
                        ("cx", fmt_coord(center[0])),
                        ("cy", fmt_coord(center[1])),
                        ("r", fmt_coord(size * frame.scale)),
                        ("stroke", "none"),
                        ("fill", INK),
                    ],
                    pointer=pointer,
                    kind="rune",
                    accent_attr="fill",
                )
            )
        return out


# --------------------------------------------------------------------------------------
# trace overlay
# --------------------------------------------------------------------------------------
def fired_indices(elements: list[Node], rows: list[TraceRow]) -> set[int]:
    """発火した要素の**添字**の集合（layout.md §7）。

    `data-jin` か `data-jin-ref` が行の pointer と**同じか祖先**である要素のうち、
    最も長い（= 最も深い）ものを採る（完全一致 → 祖先。参照を表す要素は参照先の配下 pointer でも当たる）。
    `pointer: null` の行と、どこにも当たらない行は強調しない（点だけに数える）。

    走査は「行の pointer を削る」のではなく「**描いた要素の鍵**を舐める」向きにする。
    要素数は `.jin` の大きさで決まる有限値なので、pointer が何万段あってもコストが跳ねない
    （F-S-P3-002）。`id()` を使わず添字で数えるので、同じ入力なら同じ集合になる。
    """
    by_pointer: dict[str, list[int]] = {}
    for position, node in enumerate(elements):
        if node.pointer is not None:
            by_pointer.setdefault(node.pointer, []).append(position)
        if node.ref is not None:
            by_pointer.setdefault(node.ref, []).append(position)
    fired: set[int] = set()
    for row in rows:
        if row.pointer is None:
            continue
        best: str | None = None
        for candidate in by_pointer:
            if is_ancestor_or_same(candidate, row.pointer) and (
                best is None or len(candidate) > len(best)
            ):
                best = candidate
        if best is not None:
            fired.update(by_pointer[best])
    return fired


def _trace_dots(frame: geo.Frame, pointer: str, total: int, rows: list[TraceRow]) -> list[Node]:
    """境界環の外側に「発火したイベント数」ぶんの点を並べる（要件書 §4）。

    位置はトレース**全体**の行数で決まるので、`upto` を増やしても既に置いた点は動かない
    （増えるだけ）。`data-jin-kind` は 9 種の中から `circle`、pointer は焦点の circle
    （layout.md §7）。
    """
    # 点は `fired_indices` の**あと**に足すので `fired` にならない（§7.4 の意図どおり）。
    # 以前は `accent_attr="fill"` を渡していたが到達しない設定だった（F-C-P3-007）。
    out: list[Node] = []
    for position, row in enumerate(rows):
        angle = geo.angle_at(position, total)
        center = geo.point(frame, geo.TRACE_RING, angle)
        out.append(
            Node(
                "circle",
                [
                    ("cx", fmt_coord(center[0])),
                    ("cy", fmt_coord(center[1])),
                    ("r", fmt_coord(geo.TRACE_DOT_RADIUS * frame.scale)),
                    ("stroke", "none"),
                    ("fill", INK),
                    ("data-jin-seq", str(row.seq)),
                ],
                pointer=pointer,
                kind="circle",
            )
        )
    return out


# --------------------------------------------------------------------------------------
# 公開 API
# --------------------------------------------------------------------------------------
def render(
    model: JinFile,
    *,
    focus: str | None = None,
    trace: Sequence[Mapping[str, Any]] | None = None,
    upto: int | None = None,
) -> str:
    """意味モデルを SVG 文字列にする。**同じ入力なら常にバイト単位で同じ**（NFR-DET-001）。

    - `focus`: 展開対象の circle 名。省略時は `root` の circle
    - `trace`: `seq` と `pointer` を持つ行の並び（`jin run --trace` の JSONL を読んだもの）
    - `upto`: `seq <= upto` のイベントまで発火済みとみなす。省略時は全イベント
    """
    if upto is not None and trace is None:
        raise ValueError(
            "upto は trace と一緒にしか使えません（trace が無いと seq を数えられません）"
        )
    if upto is not None and upto < 0:
        raise ValueError(f"upto は 0 以上でなければなりません: {upto}")

    all_rows = read_trace(trace) if trace is not None else []
    fired_rows = [row for row in all_rows if upto is None or row.seq <= upto]

    index_of: dict[str, int] = {}
    for position, circle in enumerate(model.circles):
        # 名前の重複（JIN010）は先に宣言されたほうを採る。落ちない・順序に依らない。
        index_of.setdefault(circle.name, position)

    focus_index: int | None = None
    root_unresolved = False
    if focus is not None:
        if focus not in index_of:
            names = "、".join(circle.name for circle in model.circles) or "（circle がありません）"
            raise RenderError(
                f"focus '{focus}' という circle はありません。定義済みの circle: {names}"
            )
        focus_index = index_of[focus]
    elif model.root in index_of:
        focus_index = index_of[model.root]
    elif model.circles:
        # JIN060（root が未定義）。落ちずに circles[0] を描き、印を付ける（layout.md §5）。
        focus_index = 0
        root_unresolved = True

    builder = _Builder(model=model, index_of=index_of)
    body: list[Node] = []
    if focus_index is not None:
        frame = geo.root_frame()
        group = builder.draw_circle(focus_index, frame, 0)
        if root_unresolved:
            group.attrs.append(("stroke-dasharray", DASH))
            group.attrs.append(("data-jin-root", "unresolved"))
        body.append(group)
        if trace is not None:
            elements = group.walk()
            for position in sorted(fired_indices(elements, fired_rows)):
                elements[position].fired = True
            group.children.extend(
                _trace_dots(frame, f"/circles/{focus_index}", len(all_rows), fired_rows)
            )
    return document(builder.defs, body, geo.CANVAS_PX)


__all__ = [
    "ARROW_HEAD",
    "DATA_JIN_KINDS",
    "RUNE_ELLIPSIS",
    "RUNE_MAX_CHARS",
    "RenderError",
    "fired_indices",
    "fit_rune",
    "render",
]
