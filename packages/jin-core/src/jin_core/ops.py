"""意味編集オペレーション（19 種）。

正本は `docs/spec/ops.md`。エディタ（Phase 5）と LSP の `jin/applyOps`（Phase 4）が使う。

契約:

- 対象は **JSON Pointer** で指定する
- **純関数**である。入力のモデルを書き換えず、新しいモデルを返す（I/O も持たない）
- 失敗は `OpError` で、理由を**診断コード**として持つ（`docs/spec/diagnostics.md` の体系）
- 各オペレーションは**逆オペレーション**を返す。undo / redo はクライアントが逆オペレーション列を保持する

実装は「モデル → 素の dict → 編集 → 再検証」で行う。再検証を通すことで、
どのオペレーションも常にスキーマとして妥当なモデルしか作らないことが構造的に保証される。
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from jin_core.model import JinFile
from jin_core.pointer import is_index_token, resolve_pointer, split_pointer
from jin_core.semantic import replace_rune_key

Op = dict[str, Any]


class OpError(Exception):
    """オペレーションの失敗。理由を診断コードで返す（要件書 §6.3）。"""

    def __init__(self, code: str, message: str, hint: str, pointer: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.pointer = pointer


@dataclass(slots=True)
class OpResult:
    model: JinFile
    inverse: Op


@dataclass(slots=True)
class OpsResult:
    model: JinFile
    #: undo する順（適用と逆順）に並んだ逆オペレーション列。
    inverses: list[Op]


def _plain(model: JinFile) -> dict[str, Any]:
    """モデルを素の JSON 値にする（キーは JSON 側の名前）。"""
    return model.model_dump(by_alias=True, mode="json")


def _validate(document: dict[str, Any], pointer: str) -> JinFile:
    try:
        return JinFile.model_validate(document)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise OpError(
            "JIN002",
            f"オペレーションの結果がスキーマ違反になります: {first['msg']}",
            f"loc={list(first['loc'])} を見直してください",
            pointer,
        ) from exc


def _tokens(op: Op) -> list[str]:
    pointer = op.get("pointer", "")
    try:
        return split_pointer(pointer)
    except ValueError as exc:
        raise OpError("JIN002", str(exc), "JSON Pointer は '/' で始めます", pointer) from exc


def _at(document: Any, pointer: str) -> Any:
    try:
        return resolve_pointer(document, pointer)
    except (KeyError, IndexError, ValueError) as exc:
        raise OpError(
            "JIN002",
            f"pointer {pointer!r} が解決できません",
            "対象が存在する pointer を指定してください",
            pointer,
        ) from exc


def _circle_index(doc: dict[str, Any], op: Op, expected_depth: int) -> int:
    """pointer の 2 段目を circle の添字として取り出す。

    **範囲も検査する**。検査を省くと `doc["circles"][index]` が素の `IndexError` で
    落ちて、`OpError` ではなくトレースバックが表に出る（security review S9）。
    """
    tokens = _tokens(op)
    if len(tokens) < 2 or tokens[0] != "circles" or not is_index_token(tokens[1]):
        raise OpError(
            "JIN002",
            f"pointer {op.get('pointer')!r} は circle を指していません",
            "/circles/<index> から始まる pointer を指定してください",
            op.get("pointer", ""),
        )
    if len(tokens) != expected_depth:
        raise OpError(
            "JIN002",
            f"pointer {op.get('pointer')!r} の深さが不正です",
            f"深さ {expected_depth} の pointer を指定してください",
            op.get("pointer", ""),
        )
    index = int(tokens[1])
    circles = doc["circles"]
    if not 0 <= index < len(circles):
        raise OpError(
            "JIN002",
            f"circle の添字 {index} は範囲外です（circle 数 {len(circles)}）",
            f"0〜{max(len(circles) - 1, 0)} の範囲を指定してください",
            op.get("pointer", ""),
        )
    return index


def _require_segment(op: Op, position: int, expected: str) -> None:
    """pointer の固定セグメントを検査する（correctness review A-3）。

    検査を省くと、たとえば `/circles/0/state/0` を `moveTool` に渡したときに
    handler が `/circles/0/tools` を組み立てて**指していない配列**を編集する。
    """
    tokens = _tokens(op)
    if len(tokens) <= position or tokens[position] != expected:
        actual = tokens[position] if len(tokens) > position else "（無し）"
        raise OpError(
            "JIN002",
            f"pointer {op.get('pointer')!r} の {position + 1} 段目は "
            f"{expected!r} である必要があります（実際: {actual!r}）",
            f"{position + 1} 段目が {expected!r} の pointer を指定してください",
            op.get("pointer", ""),
        )


def _index_of(op: Op, container: list[Any], *, allow_append: bool = False) -> int:
    tokens = _tokens(op)
    token = tokens[-1]
    if not is_index_token(token):
        raise OpError("JIN002", f"添字ではありません: {token!r}", "数値の添字を指定してください")
    index = int(token)
    limit = len(container) if allow_append else len(container) - 1
    if not 0 <= index <= limit:
        raise OpError(
            "JIN002",
            f"添字 {index} は範囲外です（要素数 {len(container)}）",
            f"0〜{max(limit, 0)} の範囲を指定してください",
            op.get("pointer", ""),
        )
    return index


def _require_index(op: Op) -> int:
    index = op.get("index")
    if not isinstance(index, int) or isinstance(index, bool) or index < 0:
        raise OpError(
            "JIN002", "index が指定されていません", "0 以上の整数を index に指定してください"
        )
    return index


def _require_value(op: Op) -> Any:
    if "value" not in op:
        raise OpError("JIN002", "value が指定されていません", "value を指定してください")
    return op["value"]


def _require_str(op: Op) -> str:
    value = _require_value(op)
    if not isinstance(value, str):
        raise OpError("JIN002", "value は文字列である必要があります", f"実際の値: {value!r}")
    return value


def _reject_duplicate(names: list[str], new_name: str, noun: str) -> None:
    if new_name in names:
        raise OpError(
            "JIN010",
            f"{noun} 名 '{new_name}' は既に使われています",
            f"使われていない名前にしてください（既存: {' / '.join(names)}）",
        )


def _boundary(circle: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """circle の boundary を取り出す。無ければ作る。

    **作ったかどうかも返す**。作ったことを覚えておかないと、逆オペレーションを
    当てたあとに空の `boundary` が残り、元の正準形に戻らない（correctness review A-2）。
    """
    boundary = circle.get("boundary")
    created = boundary is None
    if boundary is None:
        boundary = {"guards": [], "await": []}
        circle["boundary"] = boundary
    boundary.setdefault("guards", [])
    boundary.setdefault("await", [])
    return boundary, created


def _prune_boundary(circle: dict[str, Any], op: Op) -> None:
    """逆オペレーションが `pruneBoundary` を持つとき、空になった boundary を消す。

    `pruneBoundary` は「順オペレーションが boundary を新しく作った」という事実を
    逆オペレーションへ運ぶ印。元から `"boundary": {}` が書かれていたファイルでは
    順オペレーションが作っていないので印が付かず、`{}` はそのまま残る。
    """
    if op.get("pruneBoundary") is not True:
        return
    boundary = circle.get("boundary")
    if isinstance(boundary, dict) and not boundary.get("guards") and not boundary.get("await"):
        circle["boundary"] = None


# --------------------------------------------------------------------------------------
# 各オペレーション
# --------------------------------------------------------------------------------------
def _add_circle(doc: dict[str, Any], op: Op) -> Op:
    if _tokens(op) != ["circles"]:
        raise OpError(
            "JIN002", "addCircle の pointer は /circles です", "pointer を /circles にしてください"
        )
    index = _require_index(op)
    value = copy.deepcopy(_require_value(op))
    circles = doc["circles"]
    if index > len(circles):
        raise OpError(
            "JIN002", f"index {index} は範囲外です", f"0〜{len(circles)} を指定してください"
        )
    if isinstance(value, dict) and isinstance(value.get("name"), str):
        _reject_duplicate([c["name"] for c in circles], value["name"], "circle")
    circles.insert(index, value)
    return {"op": "removeCircle", "pointer": f"/circles/{index}"}


def _remove_circle(doc: dict[str, Any], op: Op) -> Op:
    index = _circle_index(doc, op, 2)
    circles = doc["circles"]
    index = _index_of(op, circles)
    old = circles.pop(index)
    return {"op": "addCircle", "pointer": "/circles", "index": index, "value": old}


def _make_circle_field_setter(field: str, op_name: str) -> Callable[[dict[str, Any], Op], Op]:
    def setter(doc: dict[str, Any], op: Op) -> Op:
        index = _circle_index(doc, op, 2)
        circle = _at(doc, op["pointer"])
        old = circle.get(field)
        circle[field] = _require_value(op)
        return {"op": op_name, "pointer": f"/circles/{index}", "value": old}

    return setter


def _set_rune(doc: dict[str, Any], op: Op) -> Op:
    index = _circle_index(doc, op, 2)
    circle = _at(doc, op["pointer"])
    instruction = circle.get("instruction")
    old = instruction.get("rune") if isinstance(instruction, dict) else None
    value = _require_value(op)
    circle["instruction"] = None if value is None else {"rune": value}
    return {"op": "setRune", "pointer": f"/circles/{index}", "value": old}


def _add_to_list(field: str, remove_op: str) -> Callable[[dict[str, Any], Op], Op]:
    def add(doc: dict[str, Any], op: Op) -> Op:
        circle_index = _circle_index(doc, op, 3)
        _require_segment(op, 2, field)
        index = _require_index(op)
        container = _at(doc, op["pointer"])
        if index > len(container):
            raise OpError(
                "JIN002", f"index {index} は範囲外です", f"0〜{len(container)} を指定してください"
            )
        container.insert(index, copy.deepcopy(_require_value(op)))
        return {"op": remove_op, "pointer": f"/circles/{circle_index}/{field}/{index}"}

    return add


def _remove_from_list(field: str, add_op: str) -> Callable[[dict[str, Any], Op], Op]:
    def remove(doc: dict[str, Any], op: Op) -> Op:
        circle_index = _circle_index(doc, op, 4)
        _require_segment(op, 2, field)
        container = _at(doc, f"/circles/{circle_index}/{field}")
        index = _index_of(op, container)
        old = container.pop(index)
        return {
            "op": add_op,
            "pointer": f"/circles/{circle_index}/{field}",
            "index": index,
            "value": old,
        }

    return remove


def _move_tool(doc: dict[str, Any], op: Op) -> Op:
    circle_index = _circle_index(doc, op, 4)
    _require_segment(op, 2, "tools")
    tools = _at(doc, f"/circles/{circle_index}/tools")
    src = _index_of(op, tools)
    dst = _require_index(op)
    if dst >= len(tools):
        raise OpError(
            "JIN002", f"index {dst} は範囲外です", f"0〜{len(tools) - 1} を指定してください"
        )
    tools.insert(dst, tools.pop(src))
    return {"op": "moveTool", "pointer": f"/circles/{circle_index}/tools/{dst}", "index": src}


def _set_state(doc: dict[str, Any], op: Op) -> Op:
    circle_index = _circle_index(doc, op, 4)
    _require_segment(op, 2, "state")
    states = _at(doc, f"/circles/{circle_index}/state")
    index = _index_of(op, states)
    old = copy.deepcopy(states[index])
    patch = _require_value(op)
    if not isinstance(patch, dict):
        raise OpError("JIN002", "setState の value はオブジェクトです", '例: {"out": true}')
    if "name" in patch and patch["name"] != old.get("name"):
        _reject_duplicate([s["name"] for s in states], patch["name"], "state")
    states[index] = {**old, **patch}
    return {
        "op": "setState",
        "pointer": f"/circles/{circle_index}/state/{index}",
        "value": old,
    }


def _set_flow(doc: dict[str, Any], op: Op) -> Op:
    index = _circle_index(doc, op, 2)
    circle = _at(doc, op["pointer"])
    old = copy.deepcopy(circle.get("flow"))
    circle["flow"] = copy.deepcopy(_require_value(op))
    return {"op": "setFlow", "pointer": f"/circles/{index}", "value": old}


def _set_guard(doc: dict[str, Any], op: Op) -> Op:
    circle_index = _circle_index(doc, op, 5)
    _require_segment(op, 2, "boundary")
    _require_segment(op, 3, "guards")
    circle = _at(doc, f"/circles/{circle_index}")
    boundary, created = _boundary(circle)
    guards = boundary["guards"]
    index = _index_of(op, guards, allow_append=True)
    pointer = f"/circles/{circle_index}/boundary/guards/{index}"
    if index == len(guards):
        guards.append(copy.deepcopy(_require_value(op)))
        inverse: Op = {"op": "removeGuard", "pointer": pointer}
        if created:
            # この setGuard が boundary を作った。逆オペレーションはそれも畳む。
            inverse["pruneBoundary"] = True
        return inverse
    old = copy.deepcopy(guards[index])
    guards[index] = copy.deepcopy(_require_value(op))
    return {"op": "setGuard", "pointer": pointer, "value": old}


def _remove_guard(doc: dict[str, Any], op: Op) -> Op:
    circle_index = _circle_index(doc, op, 5)
    _require_segment(op, 2, "boundary")
    _require_segment(op, 3, "guards")
    circle = _at(doc, f"/circles/{circle_index}")
    boundary, _created = _boundary(circle)
    guards = boundary["guards"]
    index = _index_of(op, guards)
    old = guards.pop(index)
    _prune_boundary(circle, op)
    return {
        "op": "setGuard",
        "pointer": f"/circles/{circle_index}/boundary/guards/{index}",
        "value": old,
    }


def _toggle_await(doc: dict[str, Any], op: Op) -> Op:
    """await 対象の付け外し。

    逆オペレーションは **元の位置（index）** を持つ。持たせないと、外して戻したときに
    末尾へ付き直して配列の順序が変わり、正準形がバイト一致しなくなる
    （correctness review A-1・配列は宣言順を保持する / docs/spec/model.md §7 規則 3）。
    """
    index = _circle_index(doc, op, 2)
    circle = _at(doc, op["pointer"])
    name = _require_str(op)
    boundary, created = _boundary(circle)
    awaited = boundary["await"]
    inverse: Op = {"op": "toggleAwait", "pointer": f"/circles/{index}", "value": name}
    if name in awaited:
        position = awaited.index(name)
        awaited.pop(position)
        inverse["index"] = position
        _prune_boundary(circle, op)
        return inverse
    if "index" in op:
        position = _require_index(op)
        if position > len(awaited):
            raise OpError(
                "JIN002",
                f"index {position} は範囲外です（要素数 {len(awaited)}）",
                f"0〜{len(awaited)} を指定してください",
                op.get("pointer", ""),
            )
        awaited.insert(position, name)
    else:
        awaited.append(name)
    if created:
        # この toggleAwait が boundary を作った。逆オペレーションはそれも畳む。
        inverse["pruneBoundary"] = True
    return inverse


def _set_root(doc: dict[str, Any], op: Op) -> Op:
    if _tokens(op):
        raise OpError(
            "JIN002", "setRoot の pointer はルート（空文字列）です", 'pointer を "" にしてください'
        )
    old = doc["root"]
    doc["root"] = _require_str(op)
    return {"op": "setRoot", "pointer": "", "value": old}


def _rename(doc: dict[str, Any], op: Op) -> Op:
    tokens = _tokens(op)
    new_name = _require_str(op)

    if len(tokens) == 2:  # circle
        # **期待深さはリテラルで渡す**。`len(tokens)` を渡すと `_circle_index` の
        # 深さ検査が常に成立し、検査が何も守らなくなる（correctness review A-4）。
        circle_index = _circle_index(doc, op, 2)
        circle = doc["circles"][circle_index]
        old = circle["name"]
        _reject_duplicate(
            [c["name"] for c in doc["circles"] if c is not circle], new_name, "circle"
        )
        circle["name"] = new_name
        if doc["root"] == old:
            doc["root"] = new_name
        for other in doc["circles"]:
            other["delegate"] = [new_name if d == old else d for d in other.get("delegate") or []]
            flow = other.get("flow")
            if isinstance(flow, dict):
                flow["steps"] = [new_name if s == old else s for s in flow.get("steps") or []]
            for tool in other.get("tools") or []:
                if tool.get("kind") == "summon" and tool.get("circle") == old:
                    tool["circle"] = new_name
        return {"op": "rename", "pointer": op["pointer"], "value": old}

    if len(tokens) == 4 and tokens[2] == "tools":
        circle_index = _circle_index(doc, op, 4)
        circle = doc["circles"][circle_index]
        tools = circle.get("tools") or []
        index = _index_of(op, tools)
        old = tools[index]["name"]
        _reject_duplicate([t["name"] for i, t in enumerate(tools) if i != index], new_name, "tool")
        tools[index]["name"] = new_name
        boundary = circle.get("boundary")
        if isinstance(boundary, dict):
            boundary["await"] = [new_name if a == old else a for a in boundary.get("await") or []]
        return {"op": "rename", "pointer": op["pointer"], "value": old}

    if len(tokens) == 4 and tokens[2] == "state":
        circle_index = _circle_index(doc, op, 4)
        circle = doc["circles"][circle_index]
        states = circle.get("state") or []
        index = _index_of(op, states)
        old = states[index]["name"]
        _reject_duplicate(
            [s["name"] for i, s in enumerate(states) if i != index], new_name, "state"
        )
        states[index]["name"] = new_name
        # flow.exit.key と、**全 circle** の rune 内 {key} を追随させる。
        # 可視範囲には絞らない（docs/spec/ops.md §3 / ADR-013 DP-JIN-RENAME-SCOPE-01 案 (a)）。
        # 絞ると、あとで親子関係を変えたときに追随し損ねた {key} が残って壊れる。
        for other in doc["circles"]:
            flow = other.get("flow")
            if isinstance(flow, dict):
                exit_ = flow.get("exit")
                if isinstance(exit_, dict) and exit_.get("key") == old:
                    exit_["key"] = new_name
            instruction = other.get("instruction")
            if isinstance(instruction, dict) and isinstance(instruction.get("rune"), str):
                instruction["rune"] = replace_rune_key(instruction["rune"], old, new_name)
        return {"op": "rename", "pointer": op["pointer"], "value": old}

    raise OpError(
        "JIN002",
        f"rename が扱えない pointer です: {op.get('pointer')!r}",
        "/circles/N か /circles/N/tools/M か /circles/N/state/M を指定してください",
        op.get("pointer", ""),
    )


#: オペレーション名 → 実装。docs/spec/ops.md §2 の 19 件と一致すること（test_ops.py が検査する）。
OPERATIONS: dict[str, Callable[[dict[str, Any], Op], Op]] = {
    "addCircle": _add_circle,
    "removeCircle": _remove_circle,
    "setCore": _make_circle_field_setter("core", "setCore"),
    "setDescription": _make_circle_field_setter("description", "setDescription"),
    "setRune": _set_rune,
    "addTool": _add_to_list("tools", "removeTool"),
    "removeTool": _remove_from_list("tools", "addTool"),
    "moveTool": _move_tool,
    "addState": _add_to_list("state", "removeState"),
    "removeState": _remove_from_list("state", "addState"),
    "setState": _set_state,
    "setFlow": _set_flow,
    "addDelegate": _add_to_list("delegate", "removeDelegate"),
    "removeDelegate": _remove_from_list("delegate", "addDelegate"),
    "setGuard": _set_guard,
    "removeGuard": _remove_guard,
    "toggleAwait": _toggle_await,
    "setRoot": _set_root,
    "rename": _rename,
}


def apply_op(model: JinFile, op: Op) -> OpResult:
    """1 オペレーションを適用し、新しいモデルと逆オペレーションを返す。"""
    name = op.get("op")
    handler = OPERATIONS.get(name) if isinstance(name, str) else None
    if handler is None:
        raise OpError(
            "JIN002",
            f"未知のオペレーションです: {name!r}",
            "使えるオペレーション: " + " / ".join(sorted(OPERATIONS)),
        )
    document = _plain(model)
    inverse = handler(document, op)
    return OpResult(model=_validate(document, op.get("pointer", "")), inverse=inverse)


def apply_ops(model: JinFile, ops: list[Op]) -> OpsResult:
    """オペレーション列をまとめて適用する。

    1 つでも失敗したら**何も適用しない**（呼び出し元のモデルは変わらない）。
    逆オペレーション列は undo する順（適用と逆順）で返す。
    """
    current = model
    inverses: list[Op] = []
    for op in ops:
        result = apply_op(current, op)
        current = result.model
        inverses.append(result.inverse)
    inverses.reverse()
    return OpsResult(model=current, inverses=inverses)


__all__ = ["OPERATIONS", "Op", "OpError", "OpResult", "OpsResult", "apply_op", "apply_ops"]
