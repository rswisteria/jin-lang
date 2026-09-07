"""位置変換 — `jin_core` の座標系と LSP の座標系のあいだの**唯一の橋**。

`docs/spec/diagnostics.md` §5.1 が確定させた 2 つの座標系:

| | 行・列の基点 | 列の単位 | `end` |
|---|---|---|---|
| `jin_core`（`jin check --json`） | **1 始まり** | Unicode コードポイント | 排他 |
| LSP（`lsprotocol.types.Position`） | **0 始まり** | **UTF-16 コードユニット** | 排他 |

`jin_core` 側は一貫してコードポイントで数える。UTF-16 への換算をそちらへ漏らさないため、
変換はこのモジュールだけが行う（CLAUDE.md「書くときの約束」/ diagnostics.md §5.1 の
「LSP への変換は `jin-lsp` の 1 箇所に閉じ込める」）。

列の単位変換は**日本語の rune を含む `.jin` で実際に効く**。本案件の `examples/` がまさに
それであり、`character = col - 1` で済ませるとサロゲートペア（絵文字）を含む行で
診断の下線が右にずれる。換算は pygls の `PositionCodec`（既定 UTF-16）に委ねる。

guard: to_lsp_position -> _CODEC.position_to_client_units
guard: from_lsp_position -> _CODEC.position_from_client_units
"""

from __future__ import annotations

from jin_core.diagnostics import Diagnostic as JinDiagnostic
from jin_core.diagnostics import Position as JinPosition
from jin_core.diagnostics import Range as JinRange
from lsprotocol import types
from pygls.workspace import PositionCodec

#: UTF-16 コードユニット（LSP の既定 `PositionEncodingKind.Utf16`）で数える換算器。
#: **`PositionCodec` は状態を持たない**ので、モジュール定数にしても並行実行で干渉しない
#: （実測: `client_num_units` / `position_*_client_units` はいずれも引数だけで完結する）。
#: 別のエンコーディングを `initialize` で交渉するなら、ここではなくサーバ側で
#: codec を作り分けること（v1 は交渉しない = 既定の UTF-16 固定）。
_CODEC = PositionCodec(encoding=types.PositionEncodingKind.Utf16)

#: `severity` の対応（`jin_core.diagnostics.Severity` は "error" / "warning" の 2 値）。
_SEVERITY = {
    "error": types.DiagnosticSeverity.Error,
    "warning": types.DiagnosticSeverity.Warning,
}

#: LSP `Diagnostic.source`。クライアントが「どのサーバが出した診断か」を表示するのに使う。
DIAGNOSTIC_SOURCE = "jin"


def to_lsp_position(lines: list[str], position: JinPosition) -> types.Position:
    """1 始まり・コードポイント → 0 始まり・UTF-16 コードユニット。

    guard: to_lsp_position -> _CODEC.position_to_client_units

    `lines` はドキュメントの行（改行を含む）。UTF-16 への換算に**その行の中身が要る**ので
    行番号だけでは変換できない。

    行末より後ろの列は落とさずクランプする。診断の `end` は「最後の文字の次」を指すため
    行末 + 1 になることがあり、`jin_core` 側が行の長さを知らないまま作る値もあるからである
    （`PositionCodec` が行の長さで頭打ちにする）。
    """
    if position.line < 1 or position.col < 1:
        raise ValueError(
            f"jin の行・列は 1 始まりです（docs/spec/diagnostics.md §5.1）: "
            f"line={position.line} col={position.col}"
        )
    server_position = types.Position(line=position.line - 1, character=position.col - 1)
    return _CODEC.position_to_client_units(lines, server_position)


def from_lsp_position(lines: list[str], position: types.Position) -> JinPosition:
    """0 始まり・UTF-16 コードユニット → 1 始まり・コードポイント。

    guard: from_lsp_position -> _CODEC.position_from_client_units
    """
    server_position = _CODEC.position_from_client_units(lines, position)
    return JinPosition(line=server_position.line + 1, col=server_position.character + 1)


def to_lsp_range(lines: list[str], range_: JinRange) -> types.Range:
    """`jin_core` の範囲 → LSP の範囲。どちらも `end` は排他なので端の扱いは変えない。"""
    return types.Range(
        start=to_lsp_position(lines, range_.start),
        end=to_lsp_position(lines, range_.end),
    )


def from_lsp_range(lines: list[str], range_: types.Range) -> JinRange:
    """LSP の範囲 → `jin_core` の範囲。"""
    return JinRange(
        start=from_lsp_position(lines, range_.start),
        end=from_lsp_position(lines, range_.end),
    )


def to_lsp_diagnostic(lines: list[str], diagnostic: JinDiagnostic) -> types.Diagnostic:
    """`jin_core` の診断 → LSP `Diagnostic`。

    要件書 §5 の診断 JSON は `pointer` と `hint` を持つが、LSP `Diagnostic` に対応する
    標準フィールドは**無い**（`lsp-api-probe.md` §1 で実測した引数一覧に含まれない）。
    どちらも捨てずに `data`（任意 JSON）へ載せる:

    - `hint` は「どう直すか」の具体値であり、LLM がそのまま編集に使う（要件書 §5）
    - `pointer` はエディタが SVG 上の要素へ診断バッジを出すための鍵（要件書 §7.1）

    `hint` が無いときは **キーごと落とす**。`{"hint": null}` を送るとクライアントが
    「ヒントはある（中身が空）」と読みうる。
    """
    data: dict[str, str] = {"pointer": diagnostic.pointer}
    if diagnostic.hint is not None:
        data["hint"] = diagnostic.hint
    return types.Diagnostic(
        range=to_lsp_range(lines, diagnostic.range),
        message=diagnostic.message,
        severity=_SEVERITY[diagnostic.severity],
        code=diagnostic.code,
        source=DIAGNOSTIC_SOURCE,
        data=data,
    )


__all__ = [
    "DIAGNOSTIC_SOURCE",
    "from_lsp_position",
    "from_lsp_range",
    "to_lsp_diagnostic",
    "to_lsp_position",
    "to_lsp_range",
]
