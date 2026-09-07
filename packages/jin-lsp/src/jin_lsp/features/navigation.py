"""読み取り系: definition / references / hover / documentSymbol（要件書 §6.2）。

いずれも `model_for_display` を使う。JSON 構文エラー中は **last-good モデル**で答える
（NFR-AVAIL-001 のエラー回復）。そのとき座標も last-good 世代のものを使う
（`lines_for_display` / `table_for_display`）ので、範囲が現在のテキストとずれることはある。
ずれても落ちないことのほうが要件（「直前の正常なモデルで hover を提供する」）に近い。
"""

from __future__ import annotations

from jin_core.model import Circle, JinFile
from jin_core.pointer import split_pointer
from lsprotocol import types

from jin_lsp import adk_names, locate, positions
from jin_lsp.session import DocumentState


def _context(
    state: DocumentState | None, position: types.Position
) -> tuple[JinFile, list[str], object, str] | None:
    """表示用のモデル・行・対応表と、カーソル位置の pointer。"""
    if state is None:
        return None
    model = state.model_for_display
    table = state.table_for_display
    if model is None or table is None:
        return None
    lines = state.lines_for_display
    if not lines:
        return None
    # **表示用の行**で変換する。現在のテキストが壊れているとき、その行数は
    # last-good 世代と違う（打鍵の途中で行が消えていることがある）。現在の行で
    # 変換すると位置が範囲外に落ち、hover が黙って None を返す（NFR-AVAIL-001 に反する）。
    jin_position = positions.from_lsp_position(lines, position)
    pointer = locate.pointer_at(table, jin_position)
    if pointer is None:
        return None
    return model, lines, table, pointer


def _circle_index_by_name(model: JinFile, name: str) -> int | None:
    for index, circle in enumerate(model.circles):
        if circle.name == name:
            return index
    return None


def _referenced_name(model: JinFile, pointer: str) -> tuple[str, str] | None:
    """`pointer` が**参照**なら（種類, 名前）を返す。定義そのものなら `None`。

    種類は `"circle"` / `"tool"` / `"state"`。
    """
    tokens = split_pointer(pointer)
    if tokens == ["root"]:
        return "circle", model.root
    if tokens[:1] != ["circles"] or len(tokens) < 3 or not tokens[1].isdigit():
        return None
    index = int(tokens[1])
    if index >= len(model.circles):
        return None
    circle = model.circles[index]
    rest = tokens[2:]
    if len(rest) == 2 and rest[0] == "delegate" and rest[1].isdigit():
        position = int(rest[1])
        if position < len(circle.delegate):
            return "circle", circle.delegate[position]
    if rest[:2] == ["flow", "steps"] and len(rest) == 3 and rest[2].isdigit():
        flow = circle.flow
        if flow is not None and int(rest[2]) < len(flow.steps):
            return "circle", flow.steps[int(rest[2])]
    if len(rest) == 3 and rest[0] == "tools" and rest[1].isdigit() and rest[2] == "circle":
        tool = circle.tools[int(rest[1])] if int(rest[1]) < len(circle.tools) else None
        target = getattr(tool, "circle", None)
        if isinstance(target, str):
            return "circle", target
    if rest[:2] == ["boundary", "await"] and len(rest) == 3 and rest[2].isdigit():
        boundary = circle.boundary
        if boundary is not None and int(rest[2]) < len(boundary.await_):
            return "tool", boundary.await_[int(rest[2])]
    if rest[:2] == ["flow", "exit"] and rest[2:] == ["key"]:
        flow = circle.flow
        if flow is not None and flow.exit is not None:
            return "state", flow.exit.key
    return None


def _definition_pointer_of(model: JinFile, pointer: str) -> str | None:
    """参照 pointer → 定義側の pointer（`/circles/<i>/name` など）。"""
    found = _referenced_name(model, pointer)
    if found is None:
        return None
    kind, name = found
    if kind == "circle":
        index = _circle_index_by_name(model, name)
        return f"/circles/{index}/name" if index is not None else None
    # tool / state は**同じ circle の中**を探す（名前の可視範囲が circle 内）。
    tokens = split_pointer(pointer)
    index = int(tokens[1])
    circle = model.circles[index]
    members = circle.tools if kind == "tool" else circle.state
    for member_index, member in enumerate(members):
        if member.name == name:
            key = "tools" if kind == "tool" else "state"
            return f"/circles/{index}/{key}/{member_index}/name"
    return None


def definition(
    state: DocumentState | None, uri: str, position: types.Position
) -> types.Location | None:
    """circle 参照 / state key 参照 → 定義へ跳ぶ（要件書 §6.2）。"""
    context = _context(state, position)
    if context is None or state is None:
        return None
    model, lines, table, pointer = context
    target = _definition_pointer_of(model, pointer)
    if target is None:
        return None
    range_ = locate.range_of(table, target)  # type: ignore[arg-type]
    if range_ is None:
        return None
    return types.Location(uri=uri, range=positions.to_lsp_range(lines, range_))


def _reference_pointers(model: JinFile, kind: str, name: str, owner: int | None) -> list[str]:
    """`name` を指す**参照側**の pointer を全部集める（`docs/spec/ops.md` §3 と同じ範囲）。"""
    found: list[str] = []
    if kind == "circle":
        if model.root == name:
            found.append("/root")
        for index, circle in enumerate(model.circles):
            found.extend(
                f"/circles/{index}/delegate/{position}"
                for position, delegate in enumerate(circle.delegate)
                if delegate == name
            )
            if circle.flow is not None:
                found.extend(
                    f"/circles/{index}/flow/steps/{position}"
                    for position, step in enumerate(circle.flow.steps)
                    if step == name
                )
            found.extend(
                f"/circles/{index}/tools/{position}/circle"
                for position, tool in enumerate(circle.tools)
                if getattr(tool, "circle", None) == name
            )
        return found
    if kind == "tool" and owner is not None:
        boundary = model.circles[owner].boundary
        if boundary is not None:
            found.extend(
                f"/circles/{owner}/boundary/await/{position}"
                for position, awaited in enumerate(boundary.await_)
                if awaited == name
            )
        return found
    if kind == "state":
        # state key は `flow.exit.key` と rune 内 `{key}` から参照される。
        # rune の中の位置は pointer で指せない（`docs/spec/model.md` §3.1 の抽出規則は
        # 文字位置を返さない）ので、ここでは `flow.exit.key` だけを返す。
        # rune 側は rename が `jin_core.ops` で追随する（references に出ないだけ）。
        for index, circle in enumerate(model.circles):
            flow = circle.flow
            if flow is not None and flow.exit is not None and flow.exit.key == name:
                found.append(f"/circles/{index}/flow/exit/key")
    return found


def _definition_at(model: JinFile, pointer: str) -> tuple[str, str, int] | None:
    """`pointer` が**定義側**なら（種類, 名前, 所属 circle の添字）を返す。"""
    tokens = split_pointer(pointer)
    if tokens[:1] != ["circles"] or len(tokens) < 2 or not tokens[1].isdigit():
        return None
    index = int(tokens[1])
    if index >= len(model.circles):
        return None
    circle = model.circles[index]
    rest = tokens[2:]
    if rest in ([], ["name"]):
        return "circle", circle.name, index
    if len(rest) >= 2 and rest[1].isdigit() and rest[2:] in ([], ["name"]):
        position = int(rest[1])
        if rest[0] == "tools" and position < len(circle.tools):
            return "tool", circle.tools[position].name, index
        if rest[0] == "state" and position < len(circle.state):
            return "state", circle.state[position].name, index
    return None


def references(
    state: DocumentState | None, uri: str, position: types.Position
) -> list[types.Location]:
    """定義でも参照でも、その名前を指す**全ての参照**を返す。"""
    context = _context(state, position)
    if context is None:
        return []
    model, lines, table, pointer = context
    target = _definition_at(model, pointer)
    if target is None:
        referenced = _referenced_name(model, pointer)
        if referenced is None:
            return []
        kind, name = referenced
        owner = (
            int(split_pointer(pointer)[1]) if split_pointer(pointer)[:1] == ["circles"] else None
        )
        target = (kind, name, owner if owner is not None else 0)
    kind, name, owner = target
    locations: list[types.Location] = []
    for reference in _reference_pointers(model, kind, name, owner):
        range_ = locate.range_of(table, reference)  # type: ignore[arg-type]
        if range_ is not None:
            locations.append(types.Location(uri=uri, range=positions.to_lsp_range(lines, range_)))
    return locations


def _circle_hover(circle: Circle) -> list[str]:
    if circle.core is not None:
        name, arguments = adk_names.LLM_AGENT
        return [
            f"**circle `{circle.name}`** → ADK `{name}`",
            f"- `core` → `model={circle.core!r}`",
            f"- 引数: {arguments}",
        ]
    if circle.flow is not None:
        name, arguments = adk_names.FLOW_AGENTS[circle.flow.kind]
        lines = [
            f"**circle `{circle.name}`** → ADK `{name}`（`flow.kind = {circle.flow.kind}`）",
            "- `flow.steps` → `sub_agents`",
            f"- 引数: {arguments}",
        ]
        if circle.flow.max is not None:
            lines.append(f"- `flow.max` → `{adk_names.LOOP_MAX_ARGUMENT}={circle.flow.max}`")
        if circle.flow.exit is not None:
            lines.append("- `flow.exit` → 判定エージェント `StateCheckAgent`（escalate=True）")
        return lines
    return [f"**circle `{circle.name}`**（`core` も `flow` も無い → JIN022）"]


def _hover_markdown(model: JinFile, pointer: str) -> str | None:
    """pointer に対する hover の中身（Markdown）。

    要件書 §6.2 の hover 行は「要素 → ADK クラス名と生成される引数、rune の全文、
    **Python 参照の docstring（`--resolve` 相当）**」だが、docstring は Phase 4 では**出さない**。
    `ref` の docstring を読むにはそのモジュールを import する必要があり、
    それは「hover のたびに任意の Python コードをこの長寿命プロセスの権限で実行する」ことになる
    （`jin_cli.resolver` の hazard と同じ。`jin lsp --ws` は外に口が開いている）。
    import-linter の forbidden 契約が `jin_lsp → jin_cli.resolver` を機械で落としており、
    ここで別実装を書けば同じ危険を新設することになる。
    """
    tokens = split_pointer(pointer)
    if tokens == ["root"]:
        return f"**`root`** → 生成モジュールの `root_agent`（`{model.root}`）"
    if tokens[:1] != ["circles"] or len(tokens) < 2 or not tokens[1].isdigit():
        return None
    index = int(tokens[1])
    if index >= len(model.circles):
        return None
    circle = model.circles[index]
    rest = tokens[2:]

    if rest in ([], ["name"]):
        return "\n".join(_circle_hover(circle))
    if rest[:1] == ["core"]:
        return f"**`core`** → `LlmAgent.model={circle.core!r}`"
    if rest[:1] == ["instruction"]:
        rune = circle.instruction.rune if circle.instruction is not None else ""
        return (
            "**`instruction.rune`** → `LlmAgent.instruction`"
            "（`{state_key}` テンプレートは透過）\n\n```\n" + rune + "\n```"
        )
    if rest[:1] == ["flow"]:
        return "\n".join(_circle_hover(circle))
    if rest[:1] == ["delegate"]:
        return "**`delegate[]`** → `LlmAgent.sub_agents`（LLM が transfer する先）"
    if rest[:1] == ["tools"] and len(rest) >= 2 and rest[1].isdigit():
        position = int(rest[1])
        if position >= len(circle.tools):
            return None
        tool = circle.tools[position]
        name, signature = adk_names.TOOL_CLASSES[tool.kind]
        body = [f"**tool `{tool.name}`**（`kind: {tool.kind}`）→ ADK `{name}`", f"- `{signature}`"]
        boundary = circle.boundary
        if boundary is not None and tool.name in boundary.await_:
            long_name, long_signature = adk_names.AWAIT_TOOL_CLASS
            body.append(f"- `boundary.await` に載っているので `{long_name}`（`{long_signature}`）")
        return "\n".join(body)
    if rest[:1] == ["state"] and len(rest) >= 2 and rest[1].isdigit():
        position = int(rest[1])
        if position >= len(circle.state):
            return None
        member = circle.state[position]
        target = "`output_key`" if member.out else "`session.state`"
        return f"**state `{member.name}`**（型 `{member.type}`）→ {target}"
    if rest[:2] == ["boundary", "guards"]:
        return f"**`boundary.guards[]`** → コールバック（{adk_names.GUARD_CALLBACKS}）"
    if rest[:2] == ["boundary", "await"]:
        long_name, long_signature = adk_names.AWAIT_TOOL_CLASS
        return f"**`boundary.await[]`** → `{long_name}`（`{long_signature}`）"
    return None


def hover(state: DocumentState | None, position: types.Position) -> types.Hover | None:
    context = _context(state, position)
    if context is None:
        return None
    model, _lines, _table, pointer = context
    markdown = _hover_markdown(model, pointer)
    if markdown is None:
        return None
    return types.Hover(contents=types.MarkupContent(kind=types.MarkupKind.Markdown, value=markdown))


def _symbol(
    name: str,
    kind: types.SymbolKind,
    range_: types.Range,
    detail: str = "",
    children: list[types.DocumentSymbol] | None = None,
) -> types.DocumentSymbol:
    return types.DocumentSymbol(
        name=name,
        kind=kind,
        range=range_,
        selection_range=range_,
        detail=detail,
        children=children or [],
    )


def document_symbols(state: DocumentState | None) -> list[types.DocumentSymbol]:
    """circle > tools / state / flow の階層（要件書 §6.2）。"""
    context_state = state
    if context_state is None:
        return []
    model = context_state.model_for_display
    table = context_state.table_for_display
    if model is None or table is None:
        return []
    lines = context_state.lines_for_display
    symbols: list[types.DocumentSymbol] = []

    def range_for(pointer: str, fallback: str) -> types.Range | None:
        found = locate.range_of(table, pointer) or locate.range_of(table, fallback)
        return positions.to_lsp_range(lines, found) if found is not None else None

    for index, circle in enumerate(model.circles):
        circle_range = range_for(f"/circles/{index}", "")
        if circle_range is None:
            continue
        children: list[types.DocumentSymbol] = []
        for position, tool in enumerate(circle.tools):
            tool_range = range_for(f"/circles/{index}/tools/{position}", f"/circles/{index}")
            if tool_range is not None:
                children.append(
                    _symbol(tool.name, types.SymbolKind.Method, tool_range, f"kind: {tool.kind}")
                )
        for position, member in enumerate(circle.state):
            state_range = range_for(f"/circles/{index}/state/{position}", f"/circles/{index}")
            if state_range is not None:
                children.append(
                    _symbol(member.name, types.SymbolKind.Field, state_range, member.type)
                )
        if circle.flow is not None:
            flow_range = range_for(f"/circles/{index}/flow", f"/circles/{index}")
            if flow_range is not None:
                children.append(
                    _symbol(
                        f"flow: {circle.flow.kind}",
                        types.SymbolKind.Event,
                        flow_range,
                        " → ".join(circle.flow.steps),
                    )
                )
        detail = f"core: {circle.core}" if circle.core is not None else "flow"
        symbols.append(_symbol(circle.name, types.SymbolKind.Class, circle_range, detail, children))
    return symbols


__all__ = ["definition", "document_symbols", "hover", "references"]
