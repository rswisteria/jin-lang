"""Jin v2（`version: 2`）の prepareRename / rename / codeAction（設計書 §8・§11 #58）。

v1 の `jin_lsp.features.edits` と同じ流儀: 編集は**モデルへの意味編集**（`jin_core.v2.ops` の
32 件）として組み立て、テキストは正準形（`jin_core.canonical.dumps`）を通した**全文 1 個**の
`TextEdit` で返す。テキストを直接いじる経路を作らない（`docs/spec/v2/ops.md` §1）。
**33 個目のオペレーションを作らない**（式の書き換えも既存の `setStep` / `setState` /
`setGuard` / `setFlow` に載せる）。

- rename: カーソルの名前の要素（`jin_core.v2.references` の表）を `rename` で改名する。
  追随の規則は ops.md §3 そのもの（LSP では書き直さない）
- codeAction: ops.md §4 の表（診断 → オペレーション）の quickfix と、32 件の command 露出

編集系なので**現在の**モデルだけで答える（構文エラー中は答えない。last-good に落として編集すると
いま書いている内容を黙って捨てる）。
"""

from __future__ import annotations

import logging
from typing import Any

from jin_core import canonical
from jin_core.diagnostics import MAX_ELEMENTS
from jin_core.ops import OpError
from jin_core.pointer import parent_of, resolve_pointer, split_pointer
from jin_core.v2 import expr as ex
from jin_core.v2 import ops, spans
from jin_core.v2.model import JinFileV2
from lsprotocol import types

from jin_lsp import locate, positions
from jin_lsp.features.edits import APPLY_OPS_COMMAND, whole_document_edit
from jin_lsp.features.v2_navigation import name_range, symbol_context
from jin_lsp.session import DocumentState

logger = logging.getLogger(__name__)

#: 手順の中のステップ列のキー（`ops.STEP_LIST_KEYS`）。
_STEP_LISTS = frozenset(ops.STEP_LIST_KEYS)


def _current(state: DocumentState | None) -> JinFileV2 | None:
    if state is None or state.table is None:
        return None
    return state.model if isinstance(state.model, JinFileV2) else None


# ---------------------------------------------------------------- rename


def prepare_rename(
    state: DocumentState | None, position: types.Position
) -> types.PrepareRenameResult | None:
    """名前の上なら、その名前の範囲（引用符の内側・式の中なら識別子だけ）と今の名前。"""
    model = _current(state)
    if model is None or state is None:
        return None
    context = symbol_context(model, state.lines, state.table, position)
    if context is None:
        return None
    if context.occurrence is None:
        found = name_range(context, context.symbol.name_pointer, None)
    else:
        found = name_range(context, context.occurrence.pointer, context.occurrence.span)
    if found is None:
        return None
    return types.PrepareRenamePlaceholder(
        range=positions.to_lsp_range(state.lines, found), placeholder=context.symbol.name
    )


def rename(
    state: DocumentState | None, uri: str, position: types.Position, new_name: str
) -> types.WorkspaceEdit | None:
    """名前の要素を改名し、参照を全て追随させる（`jin_core.v2.ops` の `rename`）。

    名前の重複（JIN010）やスキーマ違反の名前は `None`（LSP の rename に診断を返す口が無いので、
    クライアントは「変更なし」を見る。v1 と同じ）。追随できなかった式（ops.md §3 の `warnings`）は
    編集を止めずにログへ出す。
    """
    model = _current(state)
    if model is None or state is None:
        return None
    context = symbol_context(model, state.lines, state.table, position)
    if context is None:
        return None
    try:
        result = ops.apply_op(
            model, {"op": "rename", "pointer": context.symbol.target, "value": new_name}
        )
    except OpError:
        return None
    if result.warnings:
        logger.warning("rename が追随できなかった式: %s", " / ".join(result.warnings))
    return types.WorkspaceEdit(
        changes={uri: [whole_document_edit(state.lines, canonical.dumps(result.model))]}
    )


# ---------------------------------------------------------------- codeAction


def code_actions(
    state: DocumentState | None, uri: str, params: types.CodeActionParams
) -> list[types.CodeAction | types.Command]:
    """ops.md §4 の quickfix と、v2 の 32 オペレーションの command 露出（v1 と同じ形）。"""
    model = _current(state)
    if model is None or state is None:
        return []
    actions: list[types.CodeAction | types.Command] = []
    for diagnostic in params.context.diagnostics:
        for title, op_list in _quick_fixes(state, model, diagnostic):
            edit = _edit_from_ops(state, model, uri, op_list)
            if edit is not None:
                actions.append(
                    types.CodeAction(
                        title=title,
                        kind=types.CodeActionKind.QuickFix,
                        diagnostics=[diagnostic],
                        edit=edit,
                    )
                )
    actions.extend(
        types.Command(
            title=f"オペレーション: {name}",
            command=APPLY_OPS_COMMAND,
            arguments=[{"uri": uri, "op": name}],
        )
        for name in sorted(ops.OPERATIONS)
    )
    return actions


def _edit_from_ops(
    state: DocumentState, model: JinFileV2, uri: str, op_list: list[dict[str, Any]]
) -> types.WorkspaceEdit | None:
    try:
        result = ops.apply_ops(model, op_list)
    except OpError:
        return None
    return types.WorkspaceEdit(
        changes={uri: [whole_document_edit(state.lines, canonical.dumps(result.model))]}
    )


def _quick_fixes(
    state: DocumentState, model: JinFileV2, diagnostic: types.Diagnostic
) -> list[tuple[str, list[dict[str, Any]]]]:
    """診断 1 件 → （題, オペレーション列）の候補。ops.md §4 の表の行ごとに分岐する。"""
    code = str(diagnostic.code or "")
    data = diagnostic.data if isinstance(diagnostic.data, dict) else {}
    pointer = str(data.get("pointer", ""))
    hint = str(data.get("hint", ""))
    doc = model.model_dump(by_alias=True, mode="json")
    fixes: list[tuple[str, list[dict[str, Any]]]] = []

    if code in ("JIN203", "JIN220"):
        span = _diagnostic_span(state, pointer, diagnostic.range)
        if span is not None:
            for candidate in _suggested_names(hint):
                op_list = _write_expression(doc, pointer, _splice(doc, pointer, span, candidate))
                if op_list is not None:
                    fixes.append((f"'{candidate}' に置き換える", op_list))
            fixes.extend(_publish_fixes(doc, pointer, span))
    elif code == "JIN204":
        namespace = _namespace_of(state, doc, pointer, diagnostic.range)
        circle = _circle_index(pointer)
        if namespace is not None and circle is not None:
            fixes.append(
                (f"道具環に '{namespace}' を足す", [_add_host_sigil(doc, circle, namespace)])
            )
    elif code in ("JIN210", "JIN211"):
        extract = _extract(doc, pointer, code)
        if extract is not None:
            fixes.append(extract)
    elif code == "JIN230":
        circle = _circle_index(pointer)
        if circle is not None:
            fixes.append(("道具環に 'input' を足す", [_add_host_sigil(doc, circle, "input")]))
    elif code == "JIN240":
        fixes.append(("到達しないステップを消す", [{"op": "removeStep", "pointer": pointer}]))
    return fixes


# ---- 式の中の位置 ---------------------------------------------------------------------


def _diagnostic_span(state: DocumentState, pointer: str, range_: types.Range) -> ex.Span | None:
    """診断の範囲（LSP）→ 値 `pointer` の文字列の中の復号後の区間。値の全体なら `None`。"""
    if state.table is None:
        return None
    literal = locate.range_of(state.table, pointer)
    if literal is None:
        return None
    start = spans.offset_in_literal(
        state.lines, literal, positions.from_lsp_position(state.lines, range_.start)
    )
    end = spans.offset_in_literal(
        state.lines, literal, positions.from_lsp_position(state.lines, range_.end)
    )
    if start is None or end is None or start >= end:
        return None
    return ex.Span(start, end)


def _value(doc: dict[str, Any], pointer: str) -> str | None:
    try:
        value = resolve_pointer(doc, pointer)
    except (KeyError, IndexError, ValueError, TypeError):
        return None
    return value if isinstance(value, str) else None


def _splice(doc: dict[str, Any], pointer: str, span: ex.Span, text: str) -> str:
    value = _value(doc, pointer) or ""
    return value[: span.start] + text + value[span.end :]


def _suggested_names(hint: str) -> list[str]:
    """`hint` の「近い名前: A / B」の候補（v1 の `edits._suggested_names` と同じ形）。"""
    prefix = "近い名前: "
    if not hint.startswith(prefix):
        return []
    return [name.strip() for name in hint[len(prefix) :].split(" / ") if name.strip()]


def _write_expression(doc: dict[str, Any], pointer: str, text: str) -> list[dict[str, Any]] | None:
    """式の欄 `pointer` を `text` にするオペレーション（その欄を持つ要素の set 系に載せる）。"""
    tokens = split_pointer(pointer)
    if len(tokens) < 3 or tokens[0] != "circles" or not tokens[1].isdigit():
        return None
    circle = f"/circles/{tokens[1]}"
    rest = tokens[2:]
    if rest[:1] == ["rites"] and any(t in _STEP_LISTS for t in rest[2:]):
        if len(tokens) >= 2 and tokens[-2] == "args" and tokens[-1].isdigit():
            step = "".join(f"/{t}" for t in tokens[:-2])
            args = list(resolve_pointer(doc, f"{step}/args"))
            args[int(tokens[-1])] = text
            return [{"op": "setStep", "pointer": step, "value": {"args": args}}]
        step = parent_of(pointer) or ""
        return [{"op": "setStep", "pointer": step, "value": {tokens[-1]: text}}]
    if len(rest) == 3 and rest[0] == "state" and rest[2] == "init":
        return [{"op": "setState", "pointer": f"{circle}/state/{rest[1]}", "value": {"init": text}}]
    if len(rest) == 4 and rest[:2] == ["boundary", "guards"] and rest[3] == "assert":
        guard = dict(resolve_pointer(doc, f"{circle}/boundary/guards/{rest[2]}"))
        guard["assert"] = text
        return [
            {"op": "setGuard", "pointer": f"{circle}/boundary/guards/{rest[2]}", "value": guard}
        ]
    if rest == ["flow", "exit"]:
        flow = dict(resolve_pointer(doc, f"{circle}/flow"))
        flow["exit"] = text
        return [{"op": "setFlow", "pointer": circle, "value": flow}]
    return None


def _circle_index(pointer: str) -> int | None:
    tokens = split_pointer(pointer)
    if tokens[:1] == ["circles"] and len(tokens) >= 2 and tokens[1].isdigit():
        return int(tokens[1])
    return None


# ---- JIN203 / JIN220: 公開 state にする ----------------------------------------------------


def _publish_fixes(
    doc: dict[str, Any], pointer: str, span: ex.Span
) -> list[tuple[str, list[dict[str, Any]]]]:
    """他陣の非公開 state を指したとき、その state に `out: true` を付ける（diagnostics.md JIN203 / JIN220）。

    - `陣名.key` の `key` を指す診断 → その陣の state `key` を公開する
    - `flow.exit` の裸の名前 `key` → `flow.steps` の陣のうち state `key` を持つものごとに、
      公開して exit を `陣名.key` に書き換える
    """
    text = _value(doc, pointer)
    if text is None:
        return []
    try:
        node = ex.parse_expr(text)
    except ex.ExprSyntaxError:
        return []
    circles = doc["circles"]
    fixes: list[tuple[str, list[dict[str, Any]]]] = []
    for n in ex.walk(node):
        if isinstance(n, ex.FieldAccess) and n.name_span == span and isinstance(n.obj, ex.Name):
            publish = _publish(circles, n.obj.name, n.name)
            if publish is not None:
                fixes.append(
                    (f"{n.obj.name} の state '{n.name}' を公開する（out: true）", [publish])
                )
        if isinstance(n, ex.Name) and n.span == span and pointer.endswith("/flow/exit"):
            owner = circles[_circle_index(pointer) or 0]
            for child in (owner.get("flow") or {}).get("steps") or []:
                publish = _publish(circles, child, n.name)
                if publish is None and not _has_public(circles, child, n.name):
                    continue
                rewrite = _write_expression(
                    doc, pointer, _splice(doc, pointer, span, f"{child}.{n.name}")
                )
                if rewrite is None:
                    continue
                fixes.append(
                    (
                        f"exit を '{child}.{n.name}' にする（state を公開する）",
                        ([publish] if publish is not None else []) + rewrite,
                    )
                )
    return fixes


def _find_state(
    circles: list[dict[str, Any]], circle: str, key: str
) -> tuple[int, int, dict] | None:
    for i, c in enumerate(circles):
        if c.get("name") == circle:
            for j, s in enumerate(c.get("state") or []):
                if s.get("name") == key:
                    return i, j, s
    return None


def _publish(circles: list[dict[str, Any]], circle: str, key: str) -> dict[str, Any] | None:
    found = _find_state(circles, circle, key)
    if found is None or found[2].get("out"):
        return None
    return {
        "op": "setState",
        "pointer": f"/circles/{found[0]}/state/{found[1]}",
        "value": {"out": True},
    }


def _has_public(circles: list[dict[str, Any]], circle: str, key: str) -> bool:
    found = _find_state(circles, circle, key)
    return found is not None and bool(found[2].get("out"))


# ---- JIN204 / JIN230: 道具環に足す ------------------------------------------------------


def _namespace_of(
    state: DocumentState, doc: dict[str, Any], pointer: str, range_: types.Range
) -> str | None:
    """JIN204 が指す名前空間名（式の中なら区間の文字列、`cast.target` なら頭）。"""
    value = _value(doc, pointer)
    if value is None:
        return None
    span = _diagnostic_span(state, pointer, range_)
    text = value[span.start : span.end] if span is not None else value
    head = text.partition(".")[0]
    return head or None


def _add_host_sigil(doc: dict[str, Any], circle: int, namespace: str) -> dict[str, Any]:
    sigils = doc["circles"][circle].get("sigils") or []
    return {
        "op": "addSigil",
        "pointer": f"/circles/{circle}/sigils",
        "index": len(sigils),
        "value": {"name": namespace, "kind": "host", "host": namespace},
    }


# ---- JIN210 / JIN211: 手順に抽出 --------------------------------------------------------


def _extract(
    doc: dict[str, Any], pointer: str, code: str
) -> tuple[str, list[dict[str, Any]]] | None:
    """溢れたステップを新しい手順に抽出する（`extractRite`）。規則は決定的に決める:

    - JIN210（ステップが 12 を超えた列）: **12 個目以降**を抽出する。抽出したところに `cast` が
      1 つ残るので、12 個目から移さないと 11 + 1 + 溢れ = 上限を超えたままになる
      （v1 の JIN020 の抽出と同じ考え方）
    - JIN211（入れ子が 3 段を超えたステップ）: その**ステップ 1 個**を抽出する
    - 新しい手順の名前は `<元の手順名>Extracted`。手順 / sigil / state と衝突したら 2, 3 … を付ける

    抽出したステップが元の手順の局所（params / let）を読んでいれば、新しい手順では未定義になる
    （JIN203 として診断に出る）。引数への持ち上げは規則で決められないので人に任せる。
    """
    tokens = split_pointer(pointer)
    if len(tokens) < 5 or tokens[0] != "circles" or tokens[2] != "rites":
        return None
    if code == "JIN210":
        list_pointer = pointer
        steps = _list_at(doc, list_pointer)
        if steps is None or len(steps) <= MAX_ELEMENTS:
            return None
        start, count = MAX_ELEMENTS - 1, len(steps) - (MAX_ELEMENTS - 1)
    else:
        list_pointer = parent_of(pointer) or ""
        if not tokens[-1].isdigit() or _list_at(doc, list_pointer) is None:
            return None
        start, count = int(tokens[-1]), 1
    circle = doc["circles"][int(tokens[1])]
    rite = circle["rites"][int(tokens[3])]["name"]
    taken = {x.get("name") for key in ("rites", "sigils", "state") for x in circle.get(key) or []}
    name = f"{rite}Extracted"
    suffix = 2
    while name in taken:
        name = f"{rite}Extracted{suffix}"
        suffix += 1
    op = {"op": "extractRite", "pointer": list_pointer, "from": start, "count": count, "name": name}
    return f"{count} 個のステップを手順 '{name}' に抽出する", [op]


def _list_at(doc: dict[str, Any], pointer: str) -> list[Any] | None:
    try:
        value = resolve_pointer(doc, pointer)
    except (KeyError, IndexError, ValueError, TypeError):
        return None
    return value if isinstance(value, list) else None


__all__ = ["code_actions", "prepare_rename", "rename"]
