"""Jin v2（汎用ビジュアル言語）の意味モデル・式・意味検査・オペレーション。

正典は `docs/spec/v2/*.md`。v1 のモジュール（`jin_core.model` など）とは別集合で、
`jin_core.check` が `.jin` の `version` を見て振り分ける。v1 の公開 API は変えない。
"""

from __future__ import annotations
