"""編集を返す機能: formatting / rename / codeAction（要件書 §6.2）。

いずれも**モデルへの意味編集**として組み立て、テキストは正準形（`jin_core.canonical.dumps`）を
通して作る。テキストを直接いじる経路をここに作らない（`docs/spec/ops.md` §1）。
そのため送る `TextEdit` は常に**全文 1 個**である（`whole_document_edit`）。

最小差分を作らないのは、正準形が要素の順序も整えるからである。行単位の最小差分にしても
実際にはほぼ全行が動き、しかも「サーバが作った正準形」と「クライアントに残るテキスト」が
ずれる余地が生まれる（要件書 成功条件 5 のバイト同一性）。
"""

from __future__ import annotations

from typing import Any

from jin_core import canonical, ops
from jin_core.diagnostics import MAX_ELEMENTS
from jin_core.model import JinFile
from jin_core.pointer import split_pointer
from lsprotocol import types

from jin_lsp import locate, positions
from jin_lsp.session import DocumentState


def whole_document_edit(lines: list[str], text: str) -> types.TextEdit:
    """文書全体を `text` で置き換える `TextEdit`。

    終端は**最終行の次の行の先頭**（`line=len(lines), character=0`）にする。
    最終行の長さを数えて末尾を指す形にすると、行末に改行が無いファイルで
    1 文字ぶん取りこぼす。空文書（`lines == []`）でも `0:0-0:0` になって破綻しない。
    """
    return types.TextEdit(
        range=types.Range(
            start=types.Position(line=0, character=0),
            end=types.Position(line=len(lines), character=0),
        ),
        new_text=text,
    )


def format_document(state: DocumentState | None) -> list[types.TextEdit] | None:
    """正準形（`jin fmt` と同一の出力）。

    壊れたテキスト（構文・スキーマ エラー）は整形しない。last-good に落として
    整形すると、ユーザーが今書いている内容を**黙って捨てる**ことになる
    （エラー回復が許されるのは読み取り = hover / renderSvg までである）。
    差分が無ければ空リストを返す（無意味な編集をクライアントへ送らない）。
    """
    if state is None or state.model is None:
        return None
    text = canonical.dumps(state.model)
    if text == state.text:
        return []
    return [whole_document_edit(state.lines, text)]


def _definition_pointer(model: JinFile, pointer: str) -> tuple[str, str] | None:
    """`pointer` が指す（または参照する）**名前の定義側** pointer と種類を返す。

    返す pointer は `jin_core.ops` の `rename` が受け取れる形
    （`/circles/<i>` / `/circles/<i>/tools/<j>` / `/circles/<i>/state/<j>`）である。
    """
    tokens = split_pointer(pointer)
    circles = model.circles

    def circle_index_of(name: str) -> int | None:
        for index, circle in enumerate(circles):
            if circle.name == name:
                return index
        return None

    # ---- 定義側 --------------------------------------------------------------
    if tokens[:1] == ["circles"] and len(tokens) >= 2 and tokens[1].isdigit():
        index = int(tokens[1])
        if index >= len(circles):
            return None
        rest = tokens[2:]
        if rest in ([], ["name"]):
            return f"/circles/{index}", "circle"
        if len(rest) >= 2 and rest[0] == "tools" and rest[1].isdigit():
            if rest[2:] in ([], ["name"]):
                return f"/circles/{index}/tools/{rest[1]}", "tool"
            # `tools/<j>/circle` は summon 先 circle への**参照**
            if rest[2:] == ["circle"]:
                tool = circles[index].tools[int(rest[1])]
                target = circle_index_of(getattr(tool, "circle", "") or "")
                return (f"/circles/{target}", "circle") if target is not None else None
        if (
            len(rest) >= 2
            and rest[0] == "state"
            and rest[1].isdigit()
            and rest[2:] in ([], ["name"])
        ):
            return f"/circles/{index}/state/{rest[1]}", "state"
        # ---- 参照側 ----------------------------------------------------------
        if len(rest) == 2 and rest[0] == "delegate" and rest[1].isdigit():
            target = circle_index_of(circles[index].delegate[int(rest[1])])
            return (f"/circles/{target}", "circle") if target is not None else None
        if rest[:2] == ["flow", "steps"] and len(rest) == 3 and rest[2].isdigit():
            flow = circles[index].flow
            if flow is None:
                return None
            target = circle_index_of(flow.steps[int(rest[2])])
            return (f"/circles/{target}", "circle") if target is not None else None
        if rest[:2] == ["boundary", "await"] and len(rest) == 3 and rest[2].isdigit():
            boundary = circles[index].boundary
            if boundary is None:
                return None
            name = boundary.await_[int(rest[2])]
            for tool_index, tool in enumerate(circles[index].tools):
                if tool.name == name:
                    return f"/circles/{index}/tools/{tool_index}", "tool"
            return None
        if rest[:2] == ["flow", "exit"] and rest[2:] == ["key"]:
            flow = circles[index].flow
            exit_ = flow.exit if flow is not None else None
            if exit_ is None:
                return None
            for state_index, state in enumerate(circles[index].state):
                if state.name == exit_.key:
                    return f"/circles/{index}/state/{state_index}", "state"
            return None
        return None

    if tokens == ["root"]:
        target = circle_index_of(model.root)
        return (f"/circles/{target}", "circle") if target is not None else None
    return None


def _target_at(
    state: DocumentState, position: types.Position
) -> tuple[str, str, types.Range] | None:
    """カーソル位置の rename 対象（定義側 pointer・種類・元の範囲）。"""
    if state.model is None or state.table is None:
        return None
    jin_position = positions.from_lsp_position(state.lines, position)
    pointer = locate.pointer_at(state.table, jin_position)
    if pointer is None:
        return None
    found = _definition_pointer(state.model, pointer)
    if found is None:
        return None
    range_ = locate.range_of(state.table, pointer)
    if range_ is None:
        return None
    return found[0], found[1], positions.to_lsp_range(state.lines, range_)


def prepare_rename(
    state: DocumentState | None, position: types.Position
) -> types.PrepareRenameResult | None:
    """rename できる位置かをクライアントに先に伝える（名前でない位置では出さない）。"""
    if state is None:
        return None
    target = _target_at(state, position)
    if target is None:
        return None
    return types.PrepareRenameResult_Type2(range=target[2], placeholder="")


def rename(
    state: DocumentState | None, uri: str, position: types.Position, new_name: str
) -> types.WorkspaceEdit | None:
    """circle / tool / state の名前を変え、**参照を全て追随**させる（要件書 §6.2）。

    追随の規則は `jin_core.ops` の `rename` が持つ（`docs/spec/ops.md` §3）。
    ここでは対象 pointer を決めて呼ぶだけである。名前の重複（JIN010）などの
    失敗は `None` を返す（LSP の rename に診断を返す口が無いので、
    クライアントは「変更なし」を見る。理由は `codeAction` 側で出す）。
    """
    if state is None or state.model is None:
        return None
    target = _target_at(state, position)
    if target is None:
        return None
    try:
        result = ops.apply_op(
            state.model, {"op": "rename", "pointer": target[0], "value": new_name}
        )
    except ops.OpError:
        return None
    return types.WorkspaceEdit(
        changes={uri: [whole_document_edit(state.lines, canonical.dumps(result.model))]}
    )


def _edit_from_ops(
    state: DocumentState, uri: str, op_list: list[dict[str, Any]]
) -> types.WorkspaceEdit | None:
    """オペレーション列を当てた結果を `WorkspaceEdit` にする。失敗なら `None`。"""
    if state.model is None:
        return None
    try:
        result = ops.apply_ops(state.model, op_list)
    except ops.OpError:
        return None
    return types.WorkspaceEdit(
        changes={uri: [whole_document_edit(state.lines, canonical.dumps(result.model))]}
    )


def _circle_index_of_diagnostic(diagnostic: types.Diagnostic) -> int | None:
    """診断の `data.pointer` から circle の添字を取り出す。"""
    data = diagnostic.data if isinstance(diagnostic.data, dict) else {}
    tokens = split_pointer(str(data.get("pointer", "")))
    if tokens[:1] == ["circles"] and len(tokens) >= 2 and tokens[1].isdigit():
        return int(tokens[1])
    return None


def _suggested_names(diagnostic: types.Diagnostic) -> list[str]:
    """`hint` の「近い名前: A / B」から候補を取り出す（要件書 §5）。

    `hint` は候補を使い切ると「定義済みの…」に決定的に退化する
    （`jin_core.semantic`）ので、その形は候補として扱わない。
    """
    data = diagnostic.data if isinstance(diagnostic.data, dict) else {}
    hint = str(data.get("hint", ""))
    prefix = "近い名前: "
    if not hint.startswith(prefix):
        return []
    return [name.strip() for name in hint[len(prefix) :].split(" / ") if name.strip()]


def _quick_fixes(
    state: DocumentState, uri: str, diagnostic: types.Diagnostic
) -> list[types.CodeAction]:
    """診断 1 件に対する quickfix（要件書 §6.2 の codeAction 行）。"""
    actions: list[types.CodeAction] = []
    code = str(diagnostic.code or "")
    data = diagnostic.data if isinstance(diagnostic.data, dict) else {}
    pointer = str(data.get("pointer", ""))

    if code in {"JIN011", "JIN060"}:
        # 未解決の参照 → 候補名で**参照側を**置き換える。定義側の rename ではない
        # （綴り間違いを直すのであって、正しい circle の名前を変えるのではない）。
        for candidate in _suggested_names(diagnostic):
            edit = _reference_replacement(state, uri, pointer, candidate)
            if edit is not None:
                actions.append(
                    types.CodeAction(
                        title=f"'{candidate}' に置き換える",
                        kind=types.CodeActionKind.QuickFix,
                        diagnostics=[diagnostic],
                        edit=edit,
                    )
                )
    elif code == "JIN030":
        # loop に max も exit も無い → `max: 5` を足す（要件書 §6.2 / diagnostics.md §2）。
        index = _circle_index_of_diagnostic(diagnostic)
        if index is not None and state.model is not None and index < len(state.model.circles):
            flow = state.model.circles[index].flow
            if flow is not None:
                value = flow.model_dump(by_alias=True, mode="json")
                value["max"] = DEFAULT_LOOP_MAX
                edit = _edit_from_ops(
                    state, uri, [{"op": "setFlow", "pointer": f"/circles/{index}", "value": value}]
                )
                if edit is not None:
                    actions.append(
                        types.CodeAction(
                            title=f"max: {DEFAULT_LOOP_MAX} を追加する",
                            kind=types.CodeActionKind.QuickFix,
                            diagnostics=[diagnostic],
                            edit=edit,
                        )
                    )
    elif code == "JIN020":
        action = _extract_subcircle(state, uri, diagnostic)
        if action is not None:
            actions.append(action)
    return actions


#: JIN030 の quickfix が入れる `max`。**要件書 §2.4 と `docs/spec/diagnostics.md` §2 が
#: 「`max: 5` を追加」と名指ししている値**であり、ここで決めた値ではない。
DEFAULT_LOOP_MAX = 5


def _reference_replacement(
    state: DocumentState, uri: str, pointer: str, name: str
) -> types.WorkspaceEdit | None:
    """参照（`root` / `delegate` / `steps` / `summon.circle`）を `name` に差し替える。

    `jin_core.ops` の 19 件に「参照 1 個を書き換える」オペレーションは無い
    （`setRoot` だけが例外）。**20 個目を作らない**（要件書 §6.3 の v1 は 19 件）ので、
    参照を含む入れ物ごと差し替える既存オペレーションに置き換える:

    | 参照 | 使うオペレーション |
    |---|---|
    | `/root` | `setRoot` |
    | `/circles/<i>/delegate/<j>` | `removeDelegate` + `addDelegate` |
    | `/circles/<i>/flow/steps/<j>` | `setFlow`（steps を差し替えた flow） |
    | `/circles/<i>/tools/<j>/circle` | `removeTool` + `addTool` |
    """
    if state.model is None:
        return None
    tokens = split_pointer(pointer)
    if tokens == ["root"]:
        return _edit_from_ops(state, uri, [{"op": "setRoot", "pointer": "", "value": name}])
    if tokens[:1] != ["circles"] or len(tokens) < 3 or not tokens[1].isdigit():
        return None
    index = int(tokens[1])
    if index >= len(state.model.circles):
        return None
    circle = state.model.circles[index]
    rest = tokens[2:]

    if len(rest) == 2 and rest[0] == "delegate" and rest[1].isdigit():
        position = int(rest[1])
        return _edit_from_ops(
            state,
            uri,
            [
                {"op": "removeDelegate", "pointer": f"/circles/{index}/delegate/{position}"},
                {
                    "op": "addDelegate",
                    "pointer": f"/circles/{index}/delegate",
                    "index": position,
                    "value": name,
                },
            ],
        )
    if rest[:2] == ["flow", "steps"] and len(rest) == 3 and rest[2].isdigit():
        flow = circle.flow
        if flow is None:
            return None
        value = flow.model_dump(by_alias=True, mode="json")
        steps = list(value.get("steps") or [])
        steps[int(rest[2])] = name
        value["steps"] = steps
        return _edit_from_ops(
            state, uri, [{"op": "setFlow", "pointer": f"/circles/{index}", "value": value}]
        )
    if len(rest) == 3 and rest[0] == "tools" and rest[1].isdigit() and rest[2] == "circle":
        position = int(rest[1])
        tool = circle.tools[position].model_dump(by_alias=True, mode="json")
        tool["circle"] = name
        return _edit_from_ops(
            state,
            uri,
            [
                {"op": "removeTool", "pointer": f"/circles/{index}/tools/{position}"},
                {
                    "op": "addTool",
                    "pointer": f"/circles/{index}/tools",
                    "index": position,
                    "value": tool,
                },
            ],
        )
    return None


def _extract_subcircle(
    state: DocumentState, uri: str, diagnostic: types.Diagnostic
) -> types.CodeAction | None:
    """JIN020（`tools` が 12 を超えた）→ 溢れた紋をサブ陣へ抽出する。

    「選択要素をサブ陣に抽出」（要件書 §6.2）の**決定的な**版である。LSP の
    codeAction には「どの紋を選んだか」が届かない（診断は circle 全体を指す）ので、
    どれを移すかを規則で決める必要がある。実装判断（DP-IMPL-JIN-P4-EXTRACT-01）:

    - 移すのは **13 個目以降**（`MAX_ELEMENTS` を超えた分）。末尾から溢れた分だけを
      動かすので、元の環の並び（= 角度）が保たれる
    - 新しい陣の名前は `<元の名前>Extracted`。衝突したら末尾に 2, 3 … を付ける
    - 新しい陣の `core` は**元の陣の core をそのまま**使う。要件書に無いモデル名を
      ここで捏造しない
    - 元の陣には `summon` の紋を 1 つ足して新しい陣を呼べるようにする

    `state` が 12 を超えた場合と、元の陣に `core` が無い（`flow` だけの）場合は
    **アクションを出さない**。state は陣に固有で移せず、core の無い陣から作る
    サブ陣の core を決める根拠が要件書に無いためである。
    """
    if state.model is None:
        return None
    index = _circle_index_of_diagnostic(diagnostic)
    if index is None or index >= len(state.model.circles):
        return None
    circle = state.model.circles[index]
    if len(circle.tools) <= MAX_ELEMENTS or circle.core is None:
        return None

    existing = {other.name for other in state.model.circles}
    new_name = f"{circle.name}Extracted"
    suffix = 2
    while new_name in existing:
        new_name = f"{circle.name}Extracted{suffix}"
        suffix += 1

    moved = [tool.model_dump(by_alias=True, mode="json") for tool in circle.tools[MAX_ELEMENTS:]]
    op_list: list[dict[str, Any]] = [
        {
            "op": "addCircle",
            "pointer": "/circles",
            "index": len(state.model.circles),
            "value": {"name": new_name, "core": circle.core, "tools": moved},
        }
    ]
    # 末尾から消す（前から消すと以降の添字がずれる）。
    for position in range(len(circle.tools) - 1, MAX_ELEMENTS - 1, -1):
        op_list.append({"op": "removeTool", "pointer": f"/circles/{index}/tools/{position}"})
    op_list.append(
        {
            "op": "addTool",
            "pointer": f"/circles/{index}/tools",
            "index": MAX_ELEMENTS,
            "value": {"name": new_name, "kind": "summon", "circle": new_name},
        }
    )
    edit = _edit_from_ops(state, uri, op_list)
    if edit is None:
        return None
    return types.CodeAction(
        title=f"溢れた {len(moved)} 個の紋を '{new_name}' に抽出する",
        kind=types.CodeActionKind.QuickFix,
        diagnostics=[diagnostic],
        edit=edit,
    )


#: `jin/applyOps` をクライアントから呼ぶための command 名（要件書 §6.2 の
#: 「加えて §6.3 の全オペレーションを command として露出」）。
APPLY_OPS_COMMAND = "jin.applyOps"


def code_actions(
    state: DocumentState | None, uri: str, params: types.CodeActionParams
) -> list[types.CodeAction | types.Command]:
    """診断への quickfix と、19 オペレーションの command 露出。

    command は「引数を埋めるのはクライアント」という形にする。LSP の codeAction は
    引数を対話的に集める口を持たないので、サーバがここで値を決め打ちすると
    使えないアクションが並ぶ。エディタ（Phase 5）は一覧から選んで
    `jin/applyOps` を直接呼ぶ。
    """
    if state is None:
        return []
    actions: list[types.CodeAction | types.Command] = []
    for diagnostic in params.context.diagnostics:
        actions.extend(_quick_fixes(state, uri, diagnostic))
    actions.extend(
        types.Command(
            title=f"オペレーション: {name}",
            command=APPLY_OPS_COMMAND,
            arguments=[{"uri": uri, "op": name}],
        )
        for name in sorted(ops.OPERATIONS)
    )
    return actions


__all__ = [
    "APPLY_OPS_COMMAND",
    "DEFAULT_LOOP_MAX",
    "code_actions",
    "format_document",
    "prepare_rename",
    "rename",
    "whole_document_edit",
]
