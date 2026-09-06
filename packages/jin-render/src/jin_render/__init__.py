"""jin-render — 意味モデルから魔法陣 SVG を決定的に描く（要件書 §4 / `docs/spec/layout.md`）。

`render` が**唯一の入口**である。CLI の `jin render` と Phase 4 の `jin/renderSvg` は
この関数だけを呼び、同じ出力を返す（要件書 §4 最終項）。

契約はこの `__all__` の名前だけである。サブモジュール（`jin_render.layout` など）の
`__all__` はパッケージ内のテストが直接 import するためのもので、外向きの約束ではない
（F-V-P3-018）。

依存は `jin_core` と標準ライブラリだけ。`jin_adk`（兄弟パッケージ）にも `google-adk` にも
依存しない（design.yaml rule 4 / import-linter）。動的 import（`importlib` / `__import__` /
`exec` / `eval` / `runpy`）は 1 箇所も無い。
"""

from __future__ import annotations

from jin_render.layout import DATA_JIN_KINDS, RenderError, render
from jin_render.overlay import SEQ_MAX, TraceRowError, brief
from jin_render.svg import COORD_DECIMALS

__all__ = [
    "COORD_DECIMALS",
    "DATA_JIN_KINDS",
    "SEQ_MAX",
    "RenderError",
    "TraceRowError",
    "brief",
    "render",
]
