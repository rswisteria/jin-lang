"""Jin v2 のレイアウト定数（`docs/spec/v2/layout.md` §2 / §3 / §8）。

環の半径 4 本は v1 と**同じ値**を使い回す（設計書 §7・v2 layout.md §2。`instruction` の 0.35 を
`rites` が引き継ぐ）。それ以外はすべて **Phase 3 の実装で確定した値**で、根拠は
v2 layout.md §8 に 1 行ずつ書いてある。角度・座標・円弧の関数は `jin_render.geometry` のまま。
"""

from __future__ import annotations

from jin_render import geometry as geo

# --------------------------------------------------------------------------------------
# 環（v1 と同じ 4 本・v2 layout.md §2）
# --------------------------------------------------------------------------------------
RING_RITES = geo.RING_INSTRUCTION
RING_SIGILS = geo.RING_TOOLS
RING_STATE = geo.RING_STATE
RING_BOUNDARY = geo.RING_BOUNDARY

#: v2 layout.md §2 の表と同じ並び（spec テストが突合する）。
RING_RADII_V2: tuple[tuple[str, float], ...] = (
    ("rites", RING_RITES),
    ("sigils", RING_SIGILS),
    ("state", RING_STATE),
    ("boundary", RING_BOUNDARY),
)

# --------------------------------------------------------------------------------------
# 額縁と型紙（v2 layout.md §1 / §8）
# --------------------------------------------------------------------------------------
#: 額縁（正方形）の半辺。トレースの点の環 1.10 の外・キャンバス半幅 1.25 の内。
STAGE_HALF = 1.18
#: 上辺の `width×height @fps` の文字の高さと、上辺からの隙間。
STAGE_FONT = 0.04
STAGE_LABEL_GAP = 0.015
#: 型紙の印章（小さな正方形 + 頭文字）。額縁の左上の隅から右へ並べる。
FORM_SEAL_HALF = 0.035
FORM_SEAL_INSET = 0.06
FORM_SEAL_PITCH = 0.09
FORM_FONT = 0.04

# --------------------------------------------------------------------------------------
# 核あり陣の環の中身（v2 layout.md §2 / §8）
# --------------------------------------------------------------------------------------
CORE_RADIUS = geo.CORE_RADIUS
#: 核の中の手順名。核の直径 0.24 に収まる文字数で切り詰める。
CORE_FONT = 0.045
CORE_MAX_CHARS = 8
#: 手順環の小陣（v2 layout.md §2 の表の値）と、その中の頭文字。
RITE_GLYPH_RADIUS = 0.07
RITE_FONT = 0.06
#: 道具環の紋（`host` の円）。v1 の紋と同じ半径。
SIGIL_GLYPH_RADIUS = geo.TOOL_GLYPH_RADIUS
SIGIL_FONT = 0.06
#: 記憶環の四角。`out: true` は内側にもう 1 つ四角を描く（二重線）。
STATE_HALF = geo.STATE_HALF
STATE_OUT_INNER_HALF = 0.032
#: 型紙の無い state に描く `?`。
STATE_UNKNOWN_FONT = 0.06
#: 境界環の刻印（`on` = ◇ / `guards` = △）の外接半径と、◇ の中のイベントの頭文字。
MARK_RADIUS = 0.05
ON_FONT = 0.04
DELEGATE_RING = geo.DELEGATE_RING
DELEGATE_RADIUS = geo.DELEGATE_RADIUS
#: 装飾（識別紋章）の入力は `core` の手順の正準 JSON（v2 layout.md §5）。点は v1 と同じ帯（0.18〜0.30）。

# --------------------------------------------------------------------------------------
# 手順の図（v2 layout.md §3 / §8）
# --------------------------------------------------------------------------------------
#: 深さ 0 / 1 / 2 / 3 のステップを置く環（外から内へ）。深さ 4 以上（JIN211）は最内環に丸める。
DEPTH_RINGS: tuple[float, ...] = (RING_BOUNDARY, RING_STATE, RING_SIGILS, RING_RITES)
#: ステップの図形の大きさ。`set` の四角の半辺、`let` はその 0.6 倍。
STEP_HALF = 0.05
LET_HALF = 0.03
#: `cast` の円 / `if` の菱形 / `loop` の多角形の外接半径。
STEP_RADIUS = 0.05
#: 環の外（内）へ抜ける短い線の長さ。深さ 0 の環 0.95 から 0.95 + 0.05 + 0.07 = 1.07 で、
#: トレースの点（1.10 − 0.025）に届かない。
STEP_TAIL = 0.07
#: 線の先端の印（横棒の半幅 / `emit` の小円の半径）。
STEP_TIP = 0.02
#: `transfer` の先端の小さな陣（小円 + 中心の点）。
TRANSFER_RADIUS = 0.025
TRANSFER_CORE = 0.008
#: 弦（`step-edge`）が図形の縁から空ける隙間。線で描くステップ（`break` など）は小さめ。
STEP_GAP = STEP_RADIUS + 0.01
LINE_STEP_GAP = 0.03
#: `wait` が作る環の欠けの半角（v1 の `await` と同じ 8 度）と、欠けの両端の刻み。
WAIT_HALF_ANGLE = geo.AWAIT_HALF_ANGLE
WAIT_TICK_HALF = geo.GUARD_TICK_HALF
#: 手順の図の核（手順名）。陣の核と同じ大きさ。
RITE_CORE_FONT = CORE_FONT

__all__ = [
    "CORE_FONT",
    "CORE_MAX_CHARS",
    "CORE_RADIUS",
    "DELEGATE_RADIUS",
    "DELEGATE_RING",
    "DEPTH_RINGS",
    "FORM_FONT",
    "FORM_SEAL_HALF",
    "FORM_SEAL_INSET",
    "FORM_SEAL_PITCH",
    "LET_HALF",
    "LINE_STEP_GAP",
    "MARK_RADIUS",
    "ON_FONT",
    "RING_BOUNDARY",
    "RING_RADII_V2",
    "RING_RITES",
    "RING_SIGILS",
    "RING_STATE",
    "RITE_CORE_FONT",
    "RITE_FONT",
    "RITE_GLYPH_RADIUS",
    "SIGIL_FONT",
    "SIGIL_GLYPH_RADIUS",
    "STAGE_FONT",
    "STAGE_HALF",
    "STAGE_LABEL_GAP",
    "STATE_HALF",
    "STATE_OUT_INNER_HALF",
    "STATE_UNKNOWN_FONT",
    "STEP_GAP",
    "STEP_HALF",
    "STEP_RADIUS",
    "STEP_TAIL",
    "STEP_TIP",
    "TRANSFER_CORE",
    "TRANSFER_RADIUS",
    "WAIT_HALF_ANGLE",
    "WAIT_TICK_HALF",
]
