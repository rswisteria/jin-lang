"""Jin v2（`version: 2`）の definition / references / documentSymbol（設計書 §8・§11 #58）。

「どこが同じ名前を指すか」は **`jin_core.v2.references`** の表から引く。`rename` の参照追随
（`jin_core.v2.ops`・ops.md §3）と同じ表なので、「rename は追うのに references には出ない」
形でずれない。式の中の名前の解決（局所 → state → sigil → 陣 → 型紙）を LSP 側で書き直さない
（設計書 §8「`jin_core.v2.expr` を再実装しない」の LSP 側の写し）。

式の中の位置は JSON 文字列リテラルの中の区間なので、原文の位置との換算は
**`jin_core.v2.spans`**（`offset_in_literal` / `range_in_literal`）が行い、ここでは UTF-16 への
換算（`jin_lsp.positions`）だけを通す。

読み取り系なので hover と同じく表示用のモデル（構文エラー中は last-good 世代）で答える
（NFR-AVAIL-001）。
"""

from __future__ import annotations

from dataclasses import dataclass

from jin_core.diagnostics import Range
from jin_core.parser import PointerTable
from jin_core.v2 import references, spans
from jin_core.v2.expr import Span
from jin_core.v2.model import JinFileV2, SigilAgent, SigilHost
from lsprotocol import types

from jin_lsp import locate, positions
from jin_lsp.session import DocumentState


@dataclass(slots=True)
class SymbolContext:
    """カーソル位置の名前の要素と、位置の換算に要る世代（モデル・行・対応表）。"""

    model: JinFileV2
    lines: list[str]
    table: PointerTable
    symbols: list[references.Symbol]
    symbol: references.Symbol
    #: カーソルが乗っている参照（定義の名前の上なら `None`）。
    occurrence: references.Occurrence | None


def symbol_context(
    model: JinFileV2 | None,
    lines: list[str],
    table: PointerTable | None,
    position: types.Position,
) -> SymbolContext | None:
    """`position` にある名前の要素（定義の名前か参照）。名前の上でなければ `None`。"""
    if model is None or table is None or not lines:
        return None
    jin_position = positions.from_lsp_position(lines, position)
    pointer = locate.pointer_at(table, jin_position)
    if pointer is None:
        return None
    literal = locate.range_of(table, pointer)
    offset = spans.offset_in_literal(lines, literal, jin_position) if literal is not None else None
    symbols = references.index(model)
    symbol = references.symbol_at(symbols, pointer, offset)
    if symbol is None:
        return None
    occurrence = None
    if pointer != symbol.name_pointer:
        occurrence = next(
            (
                o
                for o in symbol.occurrences
                if o.pointer == pointer
                and (
                    o.span is None or (offset is not None and o.span.start <= offset <= o.span.end)
                )
            ),
            None,
        )
    return SymbolContext(model, lines, table, symbols, symbol, occurrence)


def name_range(context: SymbolContext, pointer: str, span: Span | None) -> Range | None:
    """値 `pointer` の中の名前の範囲（引用符の内側）。`span` が無ければ値の文字列の全体。"""
    literal = locate.range_of(context.table, pointer)
    if literal is None:
        return None
    if span is None:
        # 復号後の長さは原文の幅を超えない。区間の終わりは `span_to_range` が末尾に丸める
        span = Span(0, literal.end.col - literal.start.col)
    return spans.range_in_literal(context.lines, literal, span.start, span.end)


def _location(
    context: SymbolContext, uri: str, pointer: str, span: Span | None
) -> types.Location | None:
    found = name_range(context, pointer, span)
    if found is None:
        return None
    return types.Location(uri=uri, range=positions.to_lsp_range(context.lines, found))


def _display_context(state: DocumentState | None, position: types.Position) -> SymbolContext | None:
    if state is None:
        return None
    return symbol_context(
        state.model_v2_for_display, state.lines_for_display, state.table_for_display, position
    )


def definition(
    state: DocumentState | None, uri: str, position: types.Position
) -> types.Location | None:
    """参照 → 定義の名前。定義の名前の上ならそれ自身。"""
    context = _display_context(state, position)
    if context is None:
        return None
    return _location(context, uri, context.symbol.name_pointer, None)


def references_at(
    state: DocumentState | None,
    uri: str,
    position: types.Position,
    *,
    include_declaration: bool = False,
) -> list[types.Location]:
    """定義でも参照でも、その名前への参照を全部（`include_declaration` なら定義の名前を先頭に）。"""
    context = _display_context(state, position)
    if context is None:
        return []
    found: list[types.Location] = []
    if include_declaration:
        declaration = _location(context, uri, context.symbol.name_pointer, None)
        if declaration is not None:
            found.append(declaration)
    for occurrence in context.symbol.occurrences:
        location = _location(context, uri, occurrence.pointer, occurrence.span)
        if location is not None:
            found.append(location)
    return found


# ---------------------------------------------------------------- documentSymbol


def document_symbols(state: DocumentState | None) -> list[types.DocumentSymbol]:
    """型紙 > 欄、陣 > state / sigil / 手順（> 引数）/ on / guard / flow の階層。"""
    if state is None:
        return []
    model = state.model_v2_for_display
    table = state.table_for_display
    lines = state.lines_for_display
    if model is None or table is None or not lines:
        return []

    def make(
        name: str,
        kind: types.SymbolKind,
        pointer: str,
        detail: str = "",
        children: list[types.DocumentSymbol] | None = None,
        name_pointer: str | None = None,
    ) -> types.DocumentSymbol | None:
        whole = locate.range_of(table, pointer)
        if whole is None:
            return None
        selection = locate.range_of(table, name_pointer) if name_pointer is not None else None
        return types.DocumentSymbol(
            name=name,
            kind=kind,
            range=positions.to_lsp_range(lines, whole),
            selection_range=positions.to_lsp_range(lines, selection or whole),
            detail=detail,
            children=[child for child in children or [] if child is not None],
        )

    found: list[types.DocumentSymbol | None] = []
    for i, form in enumerate(model.forms):
        base = f"/forms/{i}"
        fields = [
            make(
                f.name,
                types.SymbolKind.Field,
                f"{base}/fields/{j}",
                f.type,
                None,
                f"{base}/fields/{j}/name",
            )
            for j, f in enumerate(form.fields)
        ]
        found.append(make(form.name, types.SymbolKind.Struct, base, "型紙", fields, f"{base}/name"))

    for i, circle in enumerate(model.circles):
        base = f"/circles/{i}"
        children: list[types.DocumentSymbol | None] = []
        for j, member in enumerate(circle.state):
            detail = member.type + ("（公開）" if member.out else "")
            children.append(
                make(
                    member.name,
                    types.SymbolKind.Field,
                    f"{base}/state/{j}",
                    detail,
                    None,
                    f"{base}/state/{j}/name",
                )
            )
        for j, sigil in enumerate(circle.sigils):
            if isinstance(sigil, SigilHost):
                detail = f"host {sigil.host}"
            elif isinstance(sigil, SigilAgent):
                detail = f"agent {sigil.file}"
            else:
                detail = f"summon {sigil.circle}.{sigil.rite}"
            children.append(
                make(
                    sigil.name,
                    types.SymbolKind.Interface,
                    f"{base}/sigils/{j}",
                    detail,
                    None,
                    f"{base}/sigils/{j}/name",
                )
            )
        for j, rite in enumerate(circle.rites):
            rp = f"{base}/rites/{j}"
            params = [
                make(
                    p.name,
                    types.SymbolKind.Variable,
                    f"{rp}/params/{k}",
                    p.type,
                    None,
                    f"{rp}/params/{k}/name",
                )
                for k, p in enumerate(rite.params)
            ]
            signature = "(" + ", ".join(f"{p.name}: {p.type}" for p in rite.params) + ")"
            if rite.returns is not None:
                signature += f" → {rite.returns}"
            if circle.core == rite.name:
                signature += "（核）"
            children.append(
                make(rite.name, types.SymbolKind.Method, rp, signature, params, f"{rp}/name")
            )
        if circle.boundary is not None:
            for j, on in enumerate(circle.boundary.on):
                children.append(
                    make(
                        f"on {on.event}",
                        types.SymbolKind.Event,
                        f"{base}/boundary/on/{j}",
                        f"→ {on.rite}",
                    )
                )
            for j, guard in enumerate(circle.boundary.guards):
                children.append(
                    make(
                        guard.assert_,
                        types.SymbolKind.Boolean,
                        f"{base}/boundary/guards/{j}",
                        "assert",
                    )
                )
        if circle.flow is not None:
            children.append(
                make(
                    f"flow: {circle.flow.kind}",
                    types.SymbolKind.Event,
                    f"{base}/flow",
                    " → ".join(circle.flow.steps),
                )
            )
        detail = f"core: {circle.core}" if circle.core is not None else "flow"
        found.append(
            make(circle.name, types.SymbolKind.Class, base, detail, children, f"{base}/name")
        )
    return [symbol for symbol in found if symbol is not None]


__all__ = [
    "SymbolContext",
    "definition",
    "document_symbols",
    "name_range",
    "references_at",
    "symbol_context",
]
