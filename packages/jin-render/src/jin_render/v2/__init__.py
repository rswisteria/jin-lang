"""jin-render の Jin v2 レイアウト（`docs/spec/v2/layout.md`・設計書 §7）。

v1 の規律（正方形キャンバス・R=1・12 時から時計回り・`fmt_coord` 1 本・3 桁固定小数・
楕円弧 `A` 不使用・2 色 + 強調 1 色・`<style>` 不使用・`xml_chars`）をそのまま継承し、
`jin_render.geometry` / `svg` / `paths` / `ornament` / `overlay` を共有する。
ここに置くのは v2 で決めること（額縁・型紙の印章・4 環の中身・手順の図・13 種の `data-jin-kind`）だけ。

入口は `jin_render.render`（version で振り分ける）。このパッケージの `render_v2` を直接呼ぶのは
パッケージ内のテストだけである。
"""

from __future__ import annotations

from jin_render.v2.layout import DATA_JIN_KINDS_V2, render_v2, split_focus

__all__ = ["DATA_JIN_KINDS_V2", "render_v2", "split_focus"]
