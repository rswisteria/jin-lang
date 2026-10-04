"""完全陣: プログラムの情報をすべて載せた 1 枚の SVG(陣書き S2・glyph 設計書 §2・正典 glyph.md §8)。

既存の陣の図と手順の図を**そのまま**使い(入れ子の参照は点になる深さ 1 で描く)、`<text>` を取り除いてから、
連環陣の位置に置き、外周に銘環を巡らせる。既存の出力(`render_v2`)には触れない。

描く順(後が上): 額縁 → 四隅の護符 → 額縁の銘帯 → 円どうしを結ぶ線 → 陣の図 → 手順陣の図 → 銘環の升。
座標は升の単位で決め、`FULL_CELL_PX` 倍して `fmt_coord` で書く。`<text>` は 1 つも出さない(銘文は線の紋とドットの字)。
円どうしを結ぶ線は、陣と手順陣のへその緒・`summon` の道具 → 呼ぶ手順陣・flow の弦・委譲の 4 種(参照の正本は銘文)。

文字列は詠唱帯(Issue #129・glyph.md §8): `quote_l` … `quote_r` の升の並びを、周と周の中間(升の中心から ±`BAND_OFFSET` 升)の
2 本の弧(額縁の銘帯では直線)で囲み、中身のドットの字は珠で描く。帯は飾りで、括りは封の紋だけで決まる(読み取りは帯を見ない)。
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from jin_core.v2.model import JinFileV2

from jin_render import geometry as geo
from jin_render.paths import arc_d
from jin_render.svg import INK, Node, document, fmt_coord
from jin_render.v2 import geometry as g2
from jin_render.v2 import shapes
from jin_render.v2.font import char_d
from jin_render.v2.full_layout import (
    Placement,
    RingCell,
    circle_inner,
    frame_positions,
    place,
    ring_capacity,
    ring_cells,
    rite_inner,
)
from jin_render.v2.glyph_paths import glyph_d
from jin_render.v2.inscribe import InkCell
from jin_render.v2.layout import circle_drawer, circle_index
from jin_render.v2.rite import draw_rite

_TEXT_TAGS = ("text", "textPath")

#: 詠唱帯の 2 本の線の、升の中心からの距離(升の単位)。周の間隔 `FULL_RING_PITCH`(1.6)のちょうど半分で、正立の升が
#: 斜め 45° で張り出す √2 / 2 より外にあり、隣の周の帯とは同じ線に重なる(額縁の銘帯の周の間隔も 1.6)
BAND_OFFSET = 0.8

#: 銘帯の升の文字列の中での役: None(文字列の外)・"open"(quote_l)・"in"(中身)・"close"(quote_r)
_Role = str | None


def _without_text(node: Node) -> Node:
    """`<text>` / `<textPath>` を木から取り除く(完全陣は文字をすべて線とドットで描く)。"""
    node.children = [_without_text(child) for child in node.children if child.tag not in _TEXT_TAGS]
    return node


class _Canvas:
    """升の座標(原点が額縁の中心)を px に写す。"""

    def __init__(self, half: float) -> None:
        self.half = half
        self.unit = g2.FULL_CELL_PX

    def px(self, x: float, y: float) -> tuple[float, float]:
        return ((x + self.half) * self.unit, (y + self.half) * self.unit)

    def frame(self, x: float, y: float) -> geo.Frame:
        cx, cy = self.px(x, y)
        return geo.Frame(cx, cy, g2.FULL_DIAGRAM_R * self.unit)


def _square_d(canvas: _Canvas, x0: float, y0: float, x1: float, y1: float) -> str:
    a, b = canvas.px(x0, y0)
    c, d = canvas.px(x1, y1)
    return (
        f"M{fmt_coord(a)} {fmt_coord(b)} L{fmt_coord(c)} {fmt_coord(b)} "
        f"L{fmt_coord(c)} {fmt_coord(d)} L{fmt_coord(a)} {fmt_coord(d)} Z"
    )


def _roles(cells: Sequence[InkCell]) -> list[_Role]:
    """升ごとの文字列の中での役。`"` は esc の後のラテンの升で書くので、quote_l / quote_r の紋は常に括り。"""
    out: list[_Role] = []
    inside = False
    for cell in cells:
        if cell.t == "glyph" and cell.v == "quote_l" and not inside:
            out.append("open")
            inside = True
        elif cell.t == "glyph" and cell.v == "quote_r" and inside:
            out.append("close")
            inside = False
        else:
            out.append("in" if inside else None)
    return out


def _span(role: _Role, half: float) -> tuple[float, float]:
    """升の中心からの帯の広がり(進む向きの前後)。封の升は中身の側の半分だけ。"""
    return (0.0 if role == "open" else -half, 0.0 if role == "close" else half)


def _ring_band_nodes(
    canvas: _Canvas, placed: Sequence[RingCell], cx: float, cy: float, inner: float
) -> list[Node]:
    """銘環の詠唱帯: 同じ周で続く升の帯を 1 本の弧にまとめる(周が変わるか文字列が閉じたら切る)。"""
    frame = geo.Frame(*canvas.px(cx, cy), canvas.unit)
    out: list[Node] = []
    run: tuple[InkCell, int, float, float] | None = None  # (封の升, 周, 始まりの角, 終わりの角)

    def flush() -> None:
        if run is None:
            return
        owner, ring, start, end = run
        radius = inner + 0.5 + ring * g2.FULL_RING_PITCH
        d = " ".join(
            arc_d(frame, radius + side * BAND_OFFSET, start, end - start) for side in (-1.0, 1.0)
        )
        out.append(shapes.path(d, owner.pointer, owner.kind))

    for item, role in zip(placed, _roles([p.cell for p in placed]), strict=True):
        if role is None:
            continue
        half = 180.0 / ring_capacity(item.ring, inner)
        lo, hi = _span(role, half)
        if run is not None and run[1] == item.ring:
            run = (run[0], run[1], run[2], item.angle + hi)
        else:
            flush()
            run = (item.cell, item.ring, item.angle + lo, item.angle + hi)
        if role == "close":
            flush()
            run = None
    flush()
    return out


def _frame_band_nodes(
    canvas: _Canvas, cells: Sequence[InkCell], centers: Sequence[tuple[float, float]]
) -> list[Node]:
    """額縁の銘帯の詠唱帯: 同じ辺で続く升の帯を 2 本の直線にまとめる(辺が変わるか文字列が閉じたら切る)。"""
    out: list[Node] = []
    run: list[tuple[float, float]] = []  # 帯の中心線の端点(始まり, 終わり)
    owner: InkCell | None = None
    edge: tuple[float, int] | None = None

    def flush() -> None:
        if not run or owner is None:
            return
        (x0, y0), (x1, y1) = run[0], run[-1]
        length = math.hypot(x1 - x0, y1 - y0) or 1.0
        nx, ny = -(y1 - y0) / length, (x1 - x0) / length
        parts = []
        for side in (-1.0, 1.0):
            a = canvas.px(x0 + side * BAND_OFFSET * nx, y0 + side * BAND_OFFSET * ny)
            b = canvas.px(x1 + side * BAND_OFFSET * nx, y1 + side * BAND_OFFSET * ny)
            parts.append(
                f"M{fmt_coord(a[0])} {fmt_coord(a[1])} L{fmt_coord(b[0])} {fmt_coord(b[1])}"
            )
        out.append(shapes.path(" ".join(parts), owner.pointer, owner.kind))

    for cell, (x, y), role in zip(cells, centers, _roles(cells), strict=True):
        if role is None:
            continue
        # 額縁の銘帯は左上から時計回り: 上の辺は +x、右は +y、下は -x、左は -y へ進む
        if abs(y) >= abs(x):
            key, (tx, ty) = (abs(y), 0 if y < 0 else 2), ((1.0, 0.0) if y < 0 else (-1.0, 0.0))
        else:
            key, (tx, ty) = (abs(x), 1 if x > 0 else 3), ((0.0, 1.0) if x > 0 else (0.0, -1.0))
        lo, hi = _span(role, 0.5)
        start, end = (x + lo * tx, y + lo * ty), (x + hi * tx, y + hi * ty)
        if run and edge == key:
            run[-1] = end
        else:
            flush()
            run, owner, edge = [start, end], cell, key
        if role == "close":
            flush()
            run, owner, edge = [], None, None
    flush()
    return out


def _cell_node(
    canvas: _Canvas, cell: InkCell, center: tuple[float, float], bead: bool = False
) -> Node | None:
    x0, y0 = canvas.px(center[0] - 0.5, center[1] - 0.5)
    if cell.t == "latin":
        d = char_d(cell.v, x0, y0, canvas.unit, bead=bead)
        if not d:
            return None
        return Node(
            "path",
            [("d", d), ("fill", INK), ("stroke", "none")],
            pointer=cell.pointer,
            kind=cell.kind,
            accent_attr="fill",
        )
    return Node(
        "path", [("d", glyph_d(cell.v, x0, y0, canvas.unit))], pointer=cell.pointer, kind=cell.kind
    )


def _ring_group(
    canvas: _Canvas,
    pointer: str,
    kind: str,
    placed: Sequence[RingCell],
    center: tuple[float, float],
    inner: float,
) -> Node:
    group = shapes.group(pointer, kind)
    group.children.extend(_ring_band_nodes(canvas, placed, center[0], center[1], inner))
    roles = _roles([item.cell for item in placed])
    for item, role in zip(placed, roles, strict=True):
        node = _cell_node(canvas, item.cell, item.center, bead=role == "in")
        if node is not None:
            group.children.append(node)
    return group


def talisman_nodes(canvas: _Canvas) -> list[Node]:
    """四隅の護符(一辺 FULL_TALISMAN 升)。右上だけ中が丸(向きの印)。完全陣と型紙(S4)で共通。"""
    half = canvas.half
    out: list[Node] = []
    t = g2.FULL_TALISMAN
    corners = ((-half, -half), (half - t, -half), (-half, half - t), (half - t, half - t))
    for n, (x, y) in enumerate(corners):
        out.append(
            shapes.path(
                _square_d(canvas, x + 0.2, y + 0.2, x + t - 0.2, y + t - 0.2), "/stage", "stage"
            )
        )
        cx, cy = canvas.px(x + t / 2, y + t / 2)
        if n == 1:  # 右上だけ丸(向きの印)
            out.append(shapes.circle((cx, cy), 0.6 * canvas.unit, "/stage", "stage", filled=True))
        else:
            out.append(
                Node(
                    "path",
                    [
                        (
                            "d",
                            _square_d(
                                canvas,
                                x + t / 2 - 0.6,
                                y + t / 2 - 0.6,
                                x + t / 2 + 0.6,
                                y + t / 2 + 0.6,
                            ),
                        ),
                        ("fill", INK),
                    ],
                    pointer="/stage",
                    kind="stage",
                    accent_attr="fill",
                )
            )
    return out


def _stage(canvas: _Canvas, cells: Sequence[InkCell]) -> Node:
    half = canvas.half
    group = shapes.group("/stage", "stage")
    group.children.append(
        shapes.path(_square_d(canvas, -half, -half, half, half), "/stage", "stage")
    )
    group.children.extend(talisman_nodes(canvas))
    # 額縁の半辺は銘帯が額縁の余白に収まる大きさ(`full_layout.place`)なので、位置が尽きることは無い
    centers = frame_positions(len(cells), half)
    group.children.extend(_frame_band_nodes(canvas, cells, centers))
    for cell, center, role in zip(cells, centers, _roles(cells), strict=True):
        node = _cell_node(canvas, cell, center, bead=role == "in")
        if node is not None:
            group.children.append(node)
    return group


def _link(
    canvas: _Canvas,
    a: tuple[float, float],
    ra: float,
    b: tuple[float, float],
    rb: float,
    pointer: str,
    kind: str,
    *,
    dashed: bool = False,
    discs: Sequence[tuple[tuple[float, float], float]] = (),
) -> Node | None:
    """2 つの円を、互いの最外周の外で結ぶ線(重なる・近すぎるときは描かない)。

    間にある別の円(discs・最外周まで)の内側は飛ばす(S3: 線が銘環の字を横切ると升が読めなくなる)。
    飛ばした結果いくつかの区間に分かれたら、区間ごとの線を `<g>` に包んで返す。"""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length <= ra + rb:
        return None
    ux, uy = dx / length, dy / length
    s = (a[0] + ux * ra, a[1] + uy * ra)
    e = (b[0] - ux * rb, b[1] - uy * rb)
    pieces = _outside(s, e, discs)
    lines = [
        shapes.line(canvas.px(*p), canvas.px(*q), pointer, kind, dashed=dashed) for p, q in pieces
    ]
    if not lines:
        return None
    if len(lines) == 1:
        return lines[0]
    group = Node("g", [], pointer=pointer, kind=kind)
    group.children.extend(lines)
    return group


def _outside(
    s: tuple[float, float],
    e: tuple[float, float],
    discs: Sequence[tuple[tuple[float, float], float]],
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """線分 s → e のうち、どの円の内側にも入らない区間(0.5 升より短い切れ端は捨てる)。"""
    dx, dy = e[0] - s[0], e[1] - s[1]
    span = math.hypot(dx, dy)
    cuts: list[tuple[float, float]] = []
    for (cx, cy), r in discs:
        fx, fy = s[0] - cx, s[1] - cy
        qa = dx * dx + dy * dy
        qb = 2.0 * (fx * dx + fy * dy)
        qc = fx * fx + fy * fy - r * r
        disc = qb * qb - 4.0 * qa * qc
        if qa == 0.0 or disc <= 0.0:
            continue
        root = math.sqrt(disc)
        t0, t1 = (-qb - root) / (2.0 * qa), (-qb + root) / (2.0 * qa)
        if t1 > 0.0 and t0 < 1.0:
            cuts.append((max(0.0, t0), min(1.0, t1)))
    out = []
    at = 0.0
    for t0, t1 in sorted(cuts):
        if t0 > at:
            out.append((at, t0))
        at = max(at, t1)
    if at < 1.0:
        out.append((at, 1.0))
    return [
        ((s[0] + dx * t0, s[1] + dy * t0), (s[0] + dx * t1, s[1] + dy * t1))
        for t0, t1 in out
        if (t1 - t0) * span >= 0.5
    ]


def _links(
    canvas: _Canvas, model: JinFileV2, placement: Placement, index_of: dict[str, int]
) -> list[Node]:
    discs = [(placement.circles[i], placement.circle_radius[i]) for i in placement.circles] + [
        (placement.rites[k], placement.rite_radius[k]) for k in placement.rites
    ]

    def link(
        canvas: _Canvas,
        a: tuple[float, float],
        ra: float,
        b: tuple[float, float],
        rb: float,
        pointer: str,
        kind: str,
        *,
        dashed: bool = False,
    ) -> Node | None:
        others = [d for d in discs if d[0] not in (a, b)]  # 線の両端の円は除く
        return _link(canvas, a, ra, b, rb, pointer, kind, dashed=dashed, discs=others)

    out: list[Node | None] = []
    for ci, circle in enumerate(model.circles):
        center, radius = placement.circles[ci], placement.circle_radius[ci]
        for ri in range(len(circle.rites)):
            out.append(
                link(
                    canvas,
                    center,
                    radius,
                    placement.rites[(ci, ri)],
                    placement.rite_radius[(ci, ri)],
                    f"/circles/{ci}/rites/{ri}",
                    "rite",
                )
            )
        for j, sigil in enumerate(circle.sigils):
            if sigil.kind != "summon" or sigil.circle not in index_of:
                continue
            target = index_of[sigil.circle]
            found = [
                k for k, rite in enumerate(model.circles[target].rites) if rite.name == sigil.rite
            ]
            key = (target, found[0]) if found else None
            if key is None:
                continue
            out.append(
                link(
                    canvas,
                    center,
                    radius,
                    placement.rites[key],
                    placement.rite_radius[key],
                    f"/circles/{ci}/sigils/{j}",
                    "sigil",
                    dashed=True,
                )
            )
        if circle.flow is not None:
            for j, name in enumerate(circle.flow.steps):
                if name in index_of and index_of[name] != ci:
                    t = index_of[name]
                    out.append(
                        link(
                            canvas,
                            center,
                            radius,
                            placement.circles[t],
                            placement.circle_radius[t],
                            f"/circles/{ci}/flow/steps/{j}",
                            "flow-edge",
                        )
                    )
        for j, name in enumerate(circle.delegate):
            if name in index_of and index_of[name] != ci:
                t = index_of[name]
                out.append(
                    link(
                        canvas,
                        center,
                        radius,
                        placement.circles[t],
                        placement.circle_radius[t],
                        f"/circles/{ci}/delegate/{j}",
                        "delegate",
                        dashed=True,
                    )
                )
    return [node for node in out if node is not None]


def render_full(model: JinFileV2) -> str:
    """完全陣の SVG。schema を通るモデルなら意味エラーを含んでいても例外を投げない。"""
    placement = place(model)
    canvas = _Canvas(placement.half)
    index_of = circle_index(model)
    draw_circle = circle_drawer(model)

    body: list[Node] = [_stage(canvas, placement.inscription.frame)]
    links = shapes.group("/circles", "circle")  # 線の既定(黒・1 px)を効かせる入れ物
    links.children.extend(_links(canvas, model, placement, index_of))
    body.append(links)
    for ci, (x, y) in placement.circles.items():
        body.append(_without_text(draw_circle(ci, canvas.frame(x, y), 1)))
        placed = ring_cells(placement.inscription.circles[ci], x, y, circle_inner())
        body.append(_ring_group(canvas, f"/circles/{ci}", "circle", placed, (x, y), circle_inner()))
    for (ci, ri), (x, y) in placement.rites.items():
        body.append(_without_text(draw_rite(model, ci, ri, canvas.frame(x, y), index_of)))
        placed = ring_cells(placement.inscription.rites[(ci, ri)], x, y, rite_inner())
        body.append(
            _ring_group(canvas, f"/circles/{ci}/rites/{ri}", "circle", placed, (x, y), rite_inner())
        )
    return document([], body, 2.0 * placement.half * canvas.unit)


__all__ = ["frame_positions", "render_full", "talisman_nodes"]
