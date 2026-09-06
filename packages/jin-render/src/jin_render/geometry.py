"""決定的レイアウトの幾何計算（`docs/spec/layout.md` §1 / §2 / §6）。

**純関数だけを置く**（DP-COMMON-07 の constraint「`jin_core` / `jin_render` はキャッシュの存在を
知らない純関数のままとし、内部に状態を持たない」）。モジュールレベルの可変状態を持たず、
乱数・時刻・辞書順序・`id()` に依存しない。ファイルも読まない（要件書 §4「入力は意味モデル」）。

環の半径 4 本（`RING_*`）は**要件値**（要件書 §2.5 / layout.md §1）。それ以外の定数は
**Phase 3 の実装で確定した値**であり、要件書には無い。根拠は `docs/spec/layout.md` §6 と
`delivery/20260904-1445-jin/decision-conformance.md` §2 に書いてある。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# --------------------------------------------------------------------------------------
# 要件値（要件書 §2.5 / layout.md §1）。存在しない環は描かないが、半径は詰めない。
# --------------------------------------------------------------------------------------
RING_INSTRUCTION = 0.35
RING_TOOLS = 0.55
RING_STATE = 0.75
RING_BOUNDARY = 0.95

#: layout.md §1 の表と同じ並び（テストが突合する）。
RING_RADII: tuple[tuple[str, float], ...] = (
    ("instruction", RING_INSTRUCTION),
    ("tools", RING_TOOLS),
    ("state", RING_STATE),
    ("boundary", RING_BOUNDARY),
)

#: 12 時位置。SVG は y 軸が下向きなので、角度を増やすと画面上は時計回りになる。
TOP_ANGLE = -90.0

# --------------------------------------------------------------------------------------
# 実装で確定した値（要件書に無い。layout.md §6 / decision-conformance.md §2）
# --------------------------------------------------------------------------------------
#: キャンバスの一辺（px）。`viewBox="0 0 1000 1000"`。
CANVAS_PX = 1000.0
#: 正規化座標 1.0 あたりの px 数。中心は (500, 500)、キャンバス半幅は 500/400 = 1.25 正規化単位。
#: 境界環 0.95 の外側にトレースの点（1.10）を置いてもキャンバスに収まる。
UNIT_PX = 400.0

CORE_RADIUS = 0.12
TOOL_GLYPH_RADIUS = 0.06
STATE_HALF = 0.05
GUARD_TICK_HALF = 0.06
DELEGATE_RING = 0.82
DELEGATE_RADIUS = 0.05
#: 入れ子の小陣（深さ 1）の縮尺の**上限**。0.55 + 0.28 * 1.01 + 0.04 = 0.873 < 0.95 なので
#: 最も大きい小陣（境界 + 目盛りまで持つもの）でも外枠ごと境界環の内側に収まる。
#: flow の節はこれを上限とし、兄弟の数が多いときは `_Builder._flow_node_limit` まで
#: **中身ごと**縮む（layout.md §6・F-C-P3-101）。道具環の紋には適用しない。
NESTED_SCALE = 0.28
#: flow の弦に付ける矢じりの長さ（layout.md §6・実装が決めた）。
ARROW_HEAD = 0.05
#: 参照の紋（入れ子の小陣の外枠）と中身の最外到達半径との隙間。外枠が中身に接して
#: 読めなくならない程度の値（実装が決めた・layout.md §6）。
SUMMON_GAP = 0.04
#: flow の節を兄弟間隔から詰めるときの余裕。弦の本体が矢じりちょうどにならないための
#: 上乗せ（実装が決めた・layout.md §6）。
FLOW_NODE_EPSILON = 0.01
#: 深さ 2 以降の参照は展開せず、この半径の点にする（layout.md §2「以下は点にする」）。
POINT_RADIUS = 0.03
#: トレースの点を並べる環（境界環 0.95 の外側・キャンバス半幅 1.25 の内側）。
TRACE_RING = 1.10
TRACE_DOT_RADIUS = 0.025
#: `boundary.await` が作る境界環の欠けの半角（度）。欠けの角幅は 2 倍の 16 度。
AWAIT_HALF_ANGLE = 8.0
#: rune の文字の高さ（正規化単位）。指示環 0.35 の周長との比だけで切り詰め位置が決まるので、
#: 縮尺（入れ子の深さ）によらず同じ文字数になる。
RUNE_FONT = 0.05
#: `flow.exit` の印（中心に置く菱形）の半径。星形多角形には「閉じ目の辺」が一意に定まらないため、
#: 曖昧さの無い中心に置く（layout.md §6）。
EXIT_MARK = 0.05
#: `flow.steps` の circle を置く環。道具環と同じ半径を使う（核なし circle には紋が無いので衝突しない）。
FLOW_RING = RING_TOOLS

#: 3 次ベジェで円弧を近似するときの制御点係数の分子（k = 4/3 * tan(θ/4)）。
_KAPPA_NUMERATOR = 4.0 / 3.0


@dataclass(frozen=True)
class Frame:
    """描画の座標枠。正規化座標 (r, θ) を px に写す。

    `scale` は正規化 1.0 あたりの px 数。入れ子の小陣は中心と縮尺だけが違う同じ枠であり、
    SVG の `transform` を使わない（`transform` の中の数値も丸め関数を通す必要があり、
    経路が 2 本になる。layout.md §4「丸め関数 1 本」）。
    """

    cx: float
    cy: float
    scale: float

    def nested(self, cx: float, cy: float, factor: float) -> Frame:
        return Frame(cx, cy, self.scale * factor)


def root_frame() -> Frame:
    """キャンバス中央・縮尺 `UNIT_PX` の枠。"""
    return Frame(CANVAS_PX / 2.0, CANVAS_PX / 2.0, UNIT_PX)


def angle_at(index: int, count: int) -> float:
    """12 時位置から時計回り・等角配置の i 番目の角度（度）。

    layout.md §2: `theta_i = -90° + 360° * i / n`。`count <= 0` は呼ばない
    （呼び出し側が空の配列を描かない）。
    """
    if count <= 0:
        raise ValueError("count は 1 以上でなければなりません")
    return TOP_ANGLE + 360.0 * index / count


def point(frame: Frame, radius: float, angle_deg: float) -> tuple[float, float]:
    """正規化半径と角度を px 座標へ写す。"""
    theta = math.radians(angle_deg)
    r = radius * frame.scale
    return (frame.cx + r * math.cos(theta), frame.cy + r * math.sin(theta))


def tangent(frame: Frame, radius: float, angle_deg: float) -> tuple[float, float]:
    """円周上の点の接ベクトル（角度で微分したもの）。ベジェの制御点に使う。"""
    theta = math.radians(angle_deg)
    r = radius * frame.scale
    return (-r * math.sin(theta), r * math.cos(theta))


def star_step(n: int) -> int:
    """星形多角形 {n/k} の k（layout.md §2.1）。

    `k = max{ j : 1 <= j < n/2 かつ gcd(n, j) == 1 }`。判定は整数演算だけで行う（`2*j < n`）。
    `n < 5` は星形にせず単純な閉多角形（k = 1）。
    """
    if n < 5:
        return 1
    return max(j for j in range(1, n) if 2 * j < n and math.gcd(n, j) == 1)


def arc_segments(
    frame: Frame, radius: float, start_deg: float, sweep_deg: float
) -> tuple[
    tuple[float, float], list[tuple[tuple[float, float], tuple[float, float], tuple[float, float]]]
]:
    """円弧を 90 度以下の 3 次ベジェへ分割する。戻り値は `(始点, [(制御点 1, 制御点 2, 終点)])`。

    **SVG の楕円弧コマンド `A` は使わない。** `A` の large-arc-flag / sweep-flag は
    「0」か「1」の 1 文字でなければならず、すべての数値を固定小数 3 桁で書き出す規約
    （layout.md §4）と両立しない（`0.000` は文法違反）。
    """
    count = max(1, math.ceil(abs(sweep_deg) / 90.0))
    step = sweep_deg / count
    kappa = _KAPPA_NUMERATOR * math.tan(math.radians(step) / 4.0)
    start = point(frame, radius, start_deg)
    segments = []
    angle = start_deg
    for _ in range(count):
        end_angle = angle + step
        p0 = point(frame, radius, angle)
        p1 = point(frame, radius, end_angle)
        t0 = tangent(frame, radius, angle)
        t1 = tangent(frame, radius, end_angle)
        c1 = (p0[0] + kappa * t0[0], p0[1] + kappa * t0[1])
        c2 = (p1[0] - kappa * t1[0], p1[1] - kappa * t1[1])
        segments.append((c1, c2, p1))
        angle = end_angle
    return start, segments


def complement_arcs(gaps: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """`TOP_ANGLE` を 0 とした相対角 [0, 360) 上で、欠け（gaps）の補集合を返す。

    戻り値は `(開始角, 掃引角)` の並び。欠けが 1 つも無ければ `[(0.0, 360.0)]`、
    欠けが全周を覆えば空。並びは開始角の昇順で決定的。
    """
    normalized: list[tuple[float, float]] = []
    for start, end in gaps:
        low = start % 360.0
        high = low + (end - start)
        if high > 360.0:
            normalized.append((low, 360.0))
            normalized.append((0.0, high - 360.0))
        else:
            normalized.append((low, high))
    if not normalized:
        return [(0.0, 360.0)]
    normalized.sort()
    merged: list[list[float]] = [list(normalized[0])]
    for low, high in normalized[1:]:
        if low <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], high)
        else:
            merged.append([low, high])
    arcs: list[tuple[float, float]] = []
    cursor = 0.0
    for low, high in merged:
        if low > cursor:
            arcs.append((cursor, low - cursor))
        cursor = max(cursor, high)
    if cursor < 360.0:
        arcs.append((cursor, 360.0 - cursor))
    return arcs


__all__ = [
    "ARROW_HEAD",
    "AWAIT_HALF_ANGLE",
    "CANVAS_PX",
    "CORE_RADIUS",
    "DELEGATE_RADIUS",
    "DELEGATE_RING",
    "EXIT_MARK",
    "FLOW_NODE_EPSILON",
    "FLOW_RING",
    "GUARD_TICK_HALF",
    "NESTED_SCALE",
    "POINT_RADIUS",
    "RING_BOUNDARY",
    "RING_INSTRUCTION",
    "RING_RADII",
    "RING_STATE",
    "RING_TOOLS",
    "RUNE_FONT",
    "STATE_HALF",
    "SUMMON_GAP",
    "TOOL_GLYPH_RADIUS",
    "TOP_ANGLE",
    "TRACE_DOT_RADIUS",
    "TRACE_RING",
    "UNIT_PX",
    "Frame",
    "angle_at",
    "arc_segments",
    "complement_arcs",
    "point",
    "root_frame",
    "star_step",
    "tangent",
]
