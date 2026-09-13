"""v2 のモデルから JIL（`game.lua`）と manifest を**できる範囲で**作る（設計書 §8「ライブリロード」）。

エディタの実行パネル（`apps/editor` の `/play/` iframe）は `jin/model` と `jin/applyOps` の応答に
載った `jil` / `manifest` をプレイヤーへ `postMessage` して、保存せずに動かす。`POST /run` は
使わない（v1 の ADK 実行だけがそこを通る・`docs/spec/ops.md` §5.2）。

**best-effort である。** `docs/spec/v2/ops.md` §1 は「式の構文・型エラーはオペレーションの失敗に
しない」と決めているので、`applyOps` は通ったが JIL は作れない（診断に error が残る）状態は普通に
起きる。そのとき `jin_wasm.codegen.generate` は `CodegenError` を投げる。ここでは `jil: None` と
理由の文字列（`jilError`）で返し、`ok: true` を保つ。

import するのは **`jin_wasm.codegen` だけ**（jin-core だけに依存する純関数）。`jin_wasm.runtime`
（lupa の実行系）を LSP プロセスに読み込まない（`tests/contract/test_lsp_contract.py` が固定する）。
"""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote, urlsplit

from jin_core.v2.model import JinFileV2
from jin_wasm.codegen import CodegenError, generate


def source_name_of(uri: str) -> str:
    """URI の末尾のファイル名（manifest の `file` とヘッダの `source:` に載せる）。"""
    path = unquote(urlsplit(uri).path)
    return path.rsplit("/", 1)[-1] or uri


def generated(model: JinFileV2, uri: str) -> dict[str, Any]:
    """`{"jil": str | None, "manifest": dict | None, "jilError": str | None}`。

    **常に `debug=True`** で作る。実行パネルはトレース行（`jin.trace`）をオーバーレイに使うので、
    リリースビルド（トレース無し）は要らない。`jin build` の既定（release）とは別物である。
    """
    try:
        game = generate(model, source_name=source_name_of(uri), debug=True)
    except CodegenError as exc:
        return {"jil": None, "manifest": None, "jilError": str(exc)}
    return {"jil": game.lua, "manifest": game.manifest, "jilError": None}


__all__ = ["generated", "source_name_of"]
