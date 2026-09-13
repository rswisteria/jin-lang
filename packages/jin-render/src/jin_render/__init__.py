"""jin-render — 意味モデルから魔法陣 SVG を決定的に描く（要件書 §4 / `docs/spec/layout.md`）。

`render` が**唯一の入口**である。CLI の `jin render` と Phase 4 の `jin/renderSvg` は
この関数だけを呼び、同じ出力を返す（要件書 §4 最終項）。Jin v2（`JinFileV2`）も同じ入口で、
version により `jin_render.v2`（`docs/spec/v2/layout.md`）へ振り分ける。

契約はこの `__all__` の名前だけである。サブモジュール（`jin_render.layout` など）の
`__all__` はパッケージ内のテストが直接 import するためのもので、外向きの約束ではない
（F-V-P3-018）。

依存は `jin_core` と標準ライブラリだけ。`jin_adk` / `jin_wasm`（兄弟パッケージ）にも
`google-adk` / `lupa` にも依存しない（design.yaml rule 4 / import-linter）。動的 import
（`importlib` / `__import__` / `exec` / `eval` / `runpy`）は 1 箇所も無い。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from jin_core.model import JinFile
from jin_core.v2.model import JinFileV2

from jin_render.layout import DATA_JIN_KINDS, RenderError
from jin_render.layout import render as _render_v1
from jin_render.overlay import SEQ_MAX, TraceRowError, brief
from jin_render.svg import COORD_DECIMALS
from jin_render.v2 import DATA_JIN_KINDS_V2, render_v2


def render(
    model: JinFile | JinFileV2,
    *,
    focus: str | None = None,
    trace: Sequence[Mapping[str, Any]] | None = None,
    upto: int | None = None,
) -> str:
    """意味モデルを SVG 文字列にする。**同じ入力なら常にバイト単位で同じ**（NFR-DET-001）。

    - `focus`: 展開対象の circle 名（v2 は `陣名/手順名` も可）。省略時は `root`
    - `trace`: `seq` と `pointer` を持つ行の並び（`jin run --trace` の JSONL を読んだもの）
    - `upto`: `seq <= upto` のイベントまで発火済みとみなす。省略時は全イベント

    v1（`JinFile`）は `jin_render.layout`、v2（`JinFileV2`）は `jin_render.v2` が描く。
    振り分けはここ 1 か所で、CLI / LSP は version を見ない。
    """
    if isinstance(model, JinFileV2):
        return render_v2(model, focus=focus, trace=trace, upto=upto)
    return _render_v1(model, focus=focus, trace=trace, upto=upto)


__all__ = [
    "COORD_DECIMALS",
    "DATA_JIN_KINDS",
    "DATA_JIN_KINDS_V2",
    "SEQ_MAX",
    "RenderError",
    "TraceRowError",
    "brief",
    "render",
]
