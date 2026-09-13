"""Jin v2 の意味編集オペレーション（32 種）。正本は docs/spec/v2/ops.md。

v1 の `jin_core.ops` と同じ契約:

- 対象は JSON Pointer で指定する。**純関数**（入力のモデルを書き換えない）
- 失敗は `OpError`（v1 と同じクラス）で、理由を診断コードで持つ
- 各オペレーションは**逆オペレーション**を返す。合成で書くもの（`extractRite`）の逆は
  オペレーションの**列**で、`apply_ops` はそれを undo 順に平らにして返す
- 「モデル → 素の dict → 編集 → `JinFileV2` で再検証」なので、結果は常にスキーマとして妥当

式を受ける欄は文字列のまま受け取る（構文・型は適用後の診断で返す。ops.md §1）。
`rename` の参照追随は式を構文解析して識別子の位置で置換する（文字列リテラルの中は触らない）。
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from jin_core.ops import Op, OpError
from jin_core.pointer import is_index_token, resolve_pointer, split_pointer
from jin_core.v2 import expr as ex
from jin_core.v2.model import JinFileV2, parse_type
from jin_core.v2.semantic import typed_nodes

#: ステップ列を持つキー（`addStep` などの pointer の末尾）。
STEP_LIST_KEYS = ("steps", "then", "else")

#: 逆オペレーション。1 つのオペレーションか、その列（合成の逆）。
Inverse = Op | list[Op]


@dataclass(slots=True)
class OpResult:
    model: JinFileV2
    inverse: Inverse
    #: `rename` が追随できなかった式の pointer（構文エラーや型が決まらない式）。ops.md §3。
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class OpsResult:
    model: JinFileV2
    #: undo する順（適用と逆順）に並んだ逆オペレーション列（平ら）。
    inverses: list[Op]
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------------------
# 共通
# --------------------------------------------------------------------------------------
def _plain(model: JinFileV2) -> dict[str, Any]:
    return model.model_dump(by_alias=True, mode="json")


def _validate(document: dict[str, Any], pointer: str) -> JinFileV2:
    try:
        return JinFileV2.model_validate(document)
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
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise OpError(
            "JIN002",
            f"pointer {pointer!r} が解決できません",
            "対象が存在する pointer を指定してください",
            pointer,
        ) from exc


def _pointer(op: Op) -> str:
    return op.get("pointer", "")


def _require(op: Op, key: str) -> Any:
    if key not in op:
        raise OpError(
            "JIN002", f"{key} が指定されていません", f"{key} を指定してください", _pointer(op)
        )
    return op[key]


def _require_int(op: Op, key: str) -> int:
    value = _require(op, key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise OpError("JIN002", f"{key} は 0 以上の整数です", f"実際の値: {value!r}", _pointer(op))
    return value


def _require_str(op: Op, key: str) -> str:
    value = _require(op, key)
    if not isinstance(value, str):
        raise OpError("JIN002", f"{key} は文字列です", f"実際の値: {value!r}", _pointer(op))
    return value


def _require_dict(op: Op, key: str) -> dict[str, Any]:
    value = _require(op, key)
    if not isinstance(value, dict):
        raise OpError("JIN002", f"{key} はオブジェクトです", f"実際の値: {value!r}", _pointer(op))
    return copy.deepcopy(value)


def _check_index(op: Op, index: int, container: list[Any], *, allow_append: bool) -> None:
    limit = len(container) if allow_append else len(container) - 1
    if not 0 <= index <= limit:
        raise OpError(
            "JIN002",
            f"添字 {index} は範囲外です（要素数 {len(container)}）",
            f"0〜{max(limit, 0)} の範囲を指定してください",
            _pointer(op),
        )


def _last_index(op: Op, container: list[Any]) -> int:
    token = _tokens(op)[-1]
    if not is_index_token(token):
        raise OpError(
            "JIN002", f"添字ではありません: {token!r}", "数値の添字を指定してください", _pointer(op)
        )
    index = int(token)
    _check_index(op, index, container, allow_append=False)
    return index


def _expect_shape(op: Op, shape: list[str | None]) -> list[str]:
    """pointer のセグメント列が `shape`（None は添字）に一致することを検査する。"""
    tokens = _tokens(op)
    ok = len(tokens) == len(shape) and all(
        (is_index_token(t) if s is None else t == s) for t, s in zip(tokens, shape, strict=True)
    )
    if not ok:
        expected = "/" + "/".join("<i>" if s is None else s for s in shape)
        raise OpError(
            "JIN002",
            f"pointer {_pointer(op)!r} の形が違います",
            f"{expected} の形の pointer を指定してください",
            _pointer(op),
        )
    return tokens


def _reject_duplicate(names: list[str], new_name: str, noun: str, pointer: str = "") -> None:
    if new_name in names:
        raise OpError(
            "JIN010",
            f"{noun} 名 '{new_name}' は既に使われています",
            f"使われていない名前にしてください（既存: {' / '.join(names)}）",
            pointer,
        )


def _parent_list(op: Op) -> str:
    return "/" + "/".join(_tokens(op)[:-1])


# --------------------------------------------------------------------------------------
# 汎用の追加 / 削除 / 移動 / 部分更新
# --------------------------------------------------------------------------------------
def _adder(shape: list[str | None], remove_op: str, noun: str) -> Callable[[dict, Op], Inverse]:
    def add(doc: dict[str, Any], op: Op) -> Inverse:
        _expect_shape(op, shape)
        container = _at(doc, _pointer(op))
        index = op.get("index", len(container))
        if not isinstance(index, int) or isinstance(index, bool):
            raise OpError("JIN002", "index は整数です", f"実際の値: {index!r}", _pointer(op))
        _check_index(op, index, container, allow_append=True)
        value = _require(op, "value")
        if isinstance(value, dict) and isinstance(value.get("name"), str):
            _reject_duplicate(
                [x.get("name") for x in container if isinstance(x, dict)], value["name"], noun
            )
        container.insert(index, copy.deepcopy(value))
        return {"op": remove_op, "pointer": f"{_pointer(op)}/{index}"}

    return add


def _remover(shape: list[str | None], add_op: str) -> Callable[[dict, Op], Inverse]:
    def remove(doc: dict[str, Any], op: Op) -> Inverse:
        _expect_shape(op, shape)
        parent = _parent_list(op)
        container = _at(doc, parent)
        index = _last_index(op, container)
        old = container.pop(index)
        return {"op": add_op, "pointer": parent, "index": index, "value": old}

    return remove


def _mover(shape: list[str | None], op_name: str) -> Callable[[dict, Op], Inverse]:
    def move(doc: dict[str, Any], op: Op) -> Inverse:
        _expect_shape(op, shape)
        parent = _parent_list(op)
        container = _at(doc, parent)
        src = _last_index(op, container)
        dst = _require_int(op, "to")
        _check_index(op, dst, container, allow_append=False)
        container.insert(dst, container.pop(src))
        return {"op": op_name, "pointer": f"{parent}/{dst}", "to": src}

    return move


def _patcher(
    shape: list[str | None], op_name: str, noun: str | None, immutable: tuple[str, ...] = ()
) -> Callable[[dict, Op], Inverse]:
    """`value` の欄で部分更新する。`null` は欄の削除。逆は触った欄の旧値（無かった欄は null）。"""

    def patch(doc: dict[str, Any], op: Op) -> Inverse:
        _expect_shape(op, shape)
        target = _at(doc, _pointer(op))
        if not isinstance(target, dict):
            raise OpError(
                "JIN002",
                "対象がオブジェクトではありません",
                "pointer を見直してください",
                _pointer(op),
            )
        changes = _require_dict(op, "value")
        for key in immutable:
            if key in changes and changes[key] != target.get(key):
                raise OpError(
                    "JIN002",
                    f"{key} は変更できません",
                    f"{key} を変えるには削除して追加し直します",
                    _pointer(op),
                )
        if noun is not None and "name" in changes and changes["name"] != target.get("name"):
            siblings = _at(doc, _parent_list(op))
            _reject_duplicate(
                [x.get("name") for x in siblings if isinstance(x, dict) and x is not target],
                changes["name"],
                noun,
                _pointer(op),
            )
        old: dict[str, Any] = {key: copy.deepcopy(target.get(key)) for key in changes}
        for key, value in changes.items():
            if value is None:
                target.pop(key, None)
            else:
                target[key] = value
        return {"op": op_name, "pointer": _pointer(op), "value": old}

    return patch


# --------------------------------------------------------------------------------------
# 個別
# --------------------------------------------------------------------------------------
def _set_core(doc: dict[str, Any], op: Op) -> Inverse:
    _expect_shape(op, ["circles", None])
    circle = _at(doc, _pointer(op))
    old = circle.get("core")
    circle["core"] = _require_str(op, "value")
    return {"op": "setCore", "pointer": _pointer(op), "value": old}


def _set_flow(doc: dict[str, Any], op: Op) -> Inverse:
    _expect_shape(op, ["circles", None])
    circle = _at(doc, _pointer(op))
    old = copy.deepcopy(circle.get("flow"))
    circle["flow"] = copy.deepcopy(_require(op, "value"))
    return {"op": "setFlow", "pointer": _pointer(op), "value": old}


def _set_root(doc: dict[str, Any], op: Op) -> Inverse:
    if _tokens(op):
        raise OpError(
            "JIN002", "setRoot の pointer はルート（空文字列）です", 'pointer を "" にしてください'
        )
    old = doc["root"]
    doc["root"] = _require_str(op, "value")
    return {"op": "setRoot", "pointer": "", "value": old}


def _boundary(circle: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    boundary = circle.get("boundary")
    created = boundary is None
    if boundary is None:
        boundary = {"on": [], "guards": []}
        circle["boundary"] = boundary
    boundary.setdefault("on", [])
    boundary.setdefault("guards", [])
    return boundary, created


def _prune_boundary(circle: dict[str, Any], op: Op) -> None:
    if op.get("pruneBoundary") is not True:
        return
    boundary = circle.get("boundary")
    if isinstance(boundary, dict) and not boundary.get("on") and not boundary.get("guards"):
        circle["boundary"] = None


def _set_on(doc: dict[str, Any], op: Op) -> Inverse:
    _expect_shape(op, ["circles", None, "boundary", "on"])
    circle = _at(doc, "/" + "/".join(_tokens(op)[:2]))
    boundary, created = _boundary(circle)
    handlers = boundary["on"]
    value = _require_dict(op, "value")
    event = value.get("event")
    for k, handler in enumerate(handlers):
        if handler.get("event") == event:
            old = copy.deepcopy(handler)
            handlers[k] = value
            return {"op": "setOn", "pointer": _pointer(op), "value": old}
    index = op.get("index", len(handlers))
    if not isinstance(index, int) or isinstance(index, bool):
        raise OpError("JIN002", "index は整数です", f"実際の値: {index!r}", _pointer(op))
    _check_index(op, index, handlers, allow_append=True)
    handlers.insert(index, value)
    inverse: Op = {"op": "removeOn", "pointer": f"{_pointer(op)}/{index}"}
    if created:
        inverse["pruneBoundary"] = True
    return inverse


def _remove_on(doc: dict[str, Any], op: Op) -> Inverse:
    _expect_shape(op, ["circles", None, "boundary", "on", None])
    circle = _at(doc, "/" + "/".join(_tokens(op)[:2]))
    boundary, _created = _boundary(circle)
    handlers = boundary["on"]
    index = _last_index(op, handlers)
    old = handlers.pop(index)
    _prune_boundary(circle, op)
    return {"op": "setOn", "pointer": _parent_list(op), "index": index, "value": old}


def _set_guard(doc: dict[str, Any], op: Op) -> Inverse:
    tokens = _tokens(op)
    if len(tokens) == 4:
        _expect_shape(op, ["circles", None, "boundary", "guards"])
        circle = _at(doc, "/" + "/".join(tokens[:2]))
        boundary, created = _boundary(circle)
        guards = boundary["guards"]
        index = op.get("index", len(guards))
        if not isinstance(index, int) or isinstance(index, bool):
            raise OpError("JIN002", "index は整数です", f"実際の値: {index!r}", _pointer(op))
        _check_index(op, index, guards, allow_append=True)
        guards.insert(index, _require_dict(op, "value"))
        inverse: Op = {"op": "removeGuard", "pointer": f"{_pointer(op)}/{index}"}
        if created:
            inverse["pruneBoundary"] = True
        return inverse
    _expect_shape(op, ["circles", None, "boundary", "guards", None])
    circle = _at(doc, "/" + "/".join(tokens[:2]))
    boundary, _created = _boundary(circle)
    guards = boundary["guards"]
    index = _last_index(op, guards)
    old = copy.deepcopy(guards[index])
    guards[index] = _require_dict(op, "value")
    return {"op": "setGuard", "pointer": _pointer(op), "value": old}


def _remove_guard(doc: dict[str, Any], op: Op) -> Inverse:
    _expect_shape(op, ["circles", None, "boundary", "guards", None])
    circle = _at(doc, "/" + "/".join(_tokens(op)[:2]))
    boundary, _created = _boundary(circle)
    guards = boundary["guards"]
    index = _last_index(op, guards)
    old = guards.pop(index)
    _prune_boundary(circle, op)
    return {"op": "setGuard", "pointer": _parent_list(op), "index": index, "value": old}


# ---------------------------------------------------------------- ステップ列


def _step_list(doc: dict[str, Any], op: Op, pointer: str) -> list[Any]:
    tokens = split_pointer(pointer) if pointer else []
    if (
        len(tokens) < 4
        or tokens[0] != "circles"
        or tokens[2] != "rites"
        or tokens[-1] not in STEP_LIST_KEYS
    ):
        raise OpError(
            "JIN002",
            f"pointer {pointer!r} はステップ列を指していません",
            "/circles/<i>/rites/<j>/steps（または …/then, …/else, …/steps）を指定してください",
            _pointer(op),
        )
    container = _at(doc, pointer)
    if not isinstance(container, list):
        raise OpError(
            "JIN002",
            f"pointer {pointer!r} は配列ではありません",
            "ステップ列を指定してください",
            _pointer(op),
        )
    return container


def _add_step(doc: dict[str, Any], op: Op) -> Inverse:
    container = _step_list(doc, op, _pointer(op))
    index = op.get("index", len(container))
    if not isinstance(index, int) or isinstance(index, bool):
        raise OpError("JIN002", "index は整数です", f"実際の値: {index!r}", _pointer(op))
    _check_index(op, index, container, allow_append=True)
    container.insert(index, _require_dict(op, "value"))
    return {"op": "removeStep", "pointer": f"{_pointer(op)}/{index}"}


def _remove_step(doc: dict[str, Any], op: Op) -> Inverse:
    parent = _parent_list(op)
    container = _step_list(doc, op, parent)
    index = _last_index(op, container)
    old = container.pop(index)
    return {"op": "addStep", "pointer": parent, "index": index, "value": old}


def _move_step(doc: dict[str, Any], op: Op) -> Inverse:
    parent = _parent_list(op)
    container = _step_list(doc, op, parent)
    src = _last_index(op, container)
    dst = _require_int(op, "to")
    _check_index(op, dst, container, allow_append=False)
    container.insert(dst, container.pop(src))
    return {"op": "moveStep", "pointer": f"{parent}/{dst}", "to": src}


def _set_step(doc: dict[str, Any], op: Op) -> Inverse:
    parent = _parent_list(op)
    container = _step_list(doc, op, parent)
    index = _last_index(op, container)
    step = container[index]
    changes = _require_dict(op, "value")
    if "do" in changes and changes["do"] != step.get("do"):
        raise OpError(
            "JIN002", "do は変更できません", "種別を変えるには removeStep + addStep", _pointer(op)
        )
    old = {key: copy.deepcopy(step.get(key)) for key in changes}
    for key, value in changes.items():
        if value is None:
            step.pop(key, None)
        else:
            step[key] = value
    return {"op": "setStep", "pointer": _pointer(op), "value": old}


def _range_args(op: Op, container: list[Any]) -> tuple[int, int]:
    start = _require_int(op, "from")
    count = _require_int(op, "count")
    if count < 1 or start + count > len(container):
        raise OpError(
            "JIN002",
            f"from={start} count={count} は範囲外です（要素数 {len(container)}）",
            "1 個以上、列の中に収まる範囲を指定してください",
            _pointer(op),
        )
    return start, count


def _branch_key(wrapper: dict[str, Any], op: Op) -> str:
    branch = op.get("branch")
    if branch is None:
        branch = "then" if wrapper.get("do") == "if" else "steps"
    if wrapper.get("do") == "if" and branch not in ("then", "else"):
        raise OpError(
            "JIN002", "if の branch は then か else です", f"実際の値: {branch!r}", _pointer(op)
        )
    if wrapper.get("do") == "loop" and branch != "steps":
        raise OpError(
            "JIN002", "loop の branch は steps です", f"実際の値: {branch!r}", _pointer(op)
        )
    if wrapper.get("do") not in ("if", "loop"):
        raise OpError(
            "JIN002",
            "包めるのは if か loop です",
            f"実際の do: {wrapper.get('do')!r}",
            _pointer(op),
        )
    return branch


def _wrap_steps(doc: dict[str, Any], op: Op) -> Inverse:
    container = _step_list(doc, op, _pointer(op))
    start, count = _range_args(op, container)
    wrapper = _require_dict(op, "value")
    branch = _branch_key(wrapper, op)
    wrapped = container[start : start + count]
    wrapper[branch] = wrapped
    if wrapper["do"] == "if":
        wrapper.setdefault("then", [])
    container[start : start + count] = [wrapper]
    return {"op": "unwrapSteps", "pointer": f"{_pointer(op)}/{start}", "branch": branch}


def _unwrap_steps(doc: dict[str, Any], op: Op) -> Inverse:
    parent = _parent_list(op)
    container = _step_list(doc, op, parent)
    index = _last_index(op, container)
    wrapper = container[index]
    branch = _branch_key(wrapper, op)
    inner = list(wrapper.get(branch) or [])
    shell = copy.deepcopy(wrapper)
    shell[branch] = []
    container[index : index + 1] = inner
    inverse: Op = {
        "op": "wrapSteps",
        "pointer": parent,
        "from": index,
        "count": len(inner),
        "value": shell,
        "branch": branch,
    }
    if not inner:
        # 空の枝を外すと 0 個になり wrapSteps では戻せない。addStep で戻す
        return {"op": "addStep", "pointer": parent, "index": index, "value": wrapper}
    return inverse


def _extract_rite(doc: dict[str, Any], op: Op) -> Inverse:
    container = _step_list(doc, op, _pointer(op))
    tokens = _tokens(op)
    circle = _at(doc, "/" + "/".join(tokens[:2]))
    rites = circle.setdefault("rites", [])
    start, count = _range_args(op, container)
    name = _require_str(op, "name")
    _reject_duplicate([r.get("name") for r in rites], name, "手順", _pointer(op))
    extracted = container[start : start + count]
    rites.append({"name": name, "steps": extracted})
    rite_index = len(rites) - 1
    container[start : start + count] = [{"do": "cast", "target": name}]
    circle_pointer = "/" + "/".join(tokens[:2])
    inverse: list[Op] = [{"op": "removeStep", "pointer": f"{_pointer(op)}/{start}"}]
    inverse.extend(
        {"op": "addStep", "pointer": _pointer(op), "index": start + k, "value": step}
        for k, step in enumerate(copy.deepcopy(extracted))
    )
    inverse.append({"op": "removeRite", "pointer": f"{circle_pointer}/rites/{rite_index}"})
    return inverse


# ---------------------------------------------------------------- rename


def _rename(doc: dict[str, Any], op: Op) -> Inverse:
    """名前を持つ要素を改名し、参照を追随させる（ops.md §3）。

    追随の対象が式の中にあるときは、型注記付き AST（`semantic.typed_nodes`）で識別子の位置を得て
    置換する。型が決まらない式は触らず `warnings` に載せる（`apply_op` が `OpResult.warnings` に運ぶ）。
    """
    tokens = _tokens(op)
    new_name = _require_str(op, "value")
    warnings: list[str] = []
    kind, owner = _rename_target(tokens)
    if kind == "circle":
        old = _rename_circle(doc, tokens, new_name, warnings)
    elif kind == "form":
        old = _rename_form(doc, tokens, new_name, warnings)
    elif kind == "field":
        old = _rename_field(doc, tokens, new_name, warnings)
    elif kind == "state":
        old = _rename_state(doc, tokens, new_name, warnings)
    elif kind == "sigil":
        old = _rename_sigil(doc, tokens, new_name, warnings)
    elif kind == "rite":
        old = _rename_rite(doc, tokens, new_name, warnings)
    else:
        old = _rename_local(doc, tokens, new_name, owner, warnings)
    inverse: Op = {"op": "rename", "pointer": _pointer(op), "value": old}
    if warnings:
        inverse["warnings"] = warnings  # apply_op が取り出して OpResult.warnings へ移す
    return inverse


def _rename_target(tokens: list[str]) -> tuple[str, str]:
    if len(tokens) == 2 and tokens[0] == "circles":
        return "circle", ""
    if len(tokens) == 2 and tokens[0] == "forms":
        return "form", ""
    if len(tokens) == 4 and tokens[0] == "forms" and tokens[2] == "fields":
        return "field", ""
    if len(tokens) == 4 and tokens[0] == "circles" and tokens[2] in ("state", "sigils", "rites"):
        return {"state": "state", "sigils": "sigil", "rites": "rite"}[tokens[2]], ""
    if len(tokens) >= 5 and tokens[0] == "circles" and tokens[2] == "rites":
        if len(tokens) == 6 and tokens[4] == "params":
            return "local", "param"
        if tokens[4] in STEP_LIST_KEYS or tokens[4] == "steps":
            return "local", "step"
    raise OpError(
        "JIN002",
        f"rename が扱えない pointer です: {'/' + '/'.join(tokens)!r}",
        "circle / form / form の欄 / state / sigil / rite / params / let / loop.name の pointer を指定してください",
        "/" + "/".join(tokens),
    )


def _all_expressions(doc: dict[str, Any]):
    """(pointer, 式文字列, 陣の添字, 手順の添字) を全部列挙する。`set.target` / `cast.into` / `cast.target` も含む。"""
    for i, circle in enumerate(doc.get("circles", [])):
        base = f"/circles/{i}"
        for j, state in enumerate(circle.get("state") or []):
            yield f"{base}/state/{j}/init", state.get("init", ""), i, None
        for j, rite in enumerate(circle.get("rites") or []):
            yield from _step_expressions(f"{base}/rites/{j}/steps", rite.get("steps") or [], i, j)
        boundary = circle.get("boundary") or {}
        for j, guard in enumerate(boundary.get("guards") or []):
            yield f"{base}/boundary/guards/{j}/assert", guard.get("assert", ""), i, None
        flow = circle.get("flow")
        if isinstance(flow, dict) and isinstance(flow.get("exit"), str):
            yield f"{base}/flow/exit", flow["exit"], i, None


_EXPR_KEYS = ("expr", "cond", "target", "into", "in", "times", "ticks", "until")


def _step_expressions(pointer: str, steps: list[Any], circle: int, rite: int):
    for k, step in enumerate(steps):
        sp = f"{pointer}/{k}"
        for key in _EXPR_KEYS:
            if key == "target" and step.get("do") == "cast":
                continue  # cast.target は式ではなく名前（別に扱う）
            if isinstance(step.get(key), str):
                yield f"{sp}/{key}", step[key], circle, rite
        for a, arg in enumerate(step.get("args") or []):
            yield f"{sp}/args/{a}", arg, circle, rite
        for key in ("then", "else", "steps"):
            if isinstance(step.get(key), list):
                yield from _step_expressions(f"{sp}/{key}", step[key], circle, rite)


def _splice(text: str, edits: list[tuple[ex.Span, str]]) -> str:
    for span, replacement in sorted(edits, key=lambda e: e[0].start, reverse=True):
        text = text[: span.start] + replacement + text[span.end :]
    return text


def _set_at(doc: dict[str, Any], pointer: str, value: str) -> None:
    tokens = split_pointer(pointer)
    parent = resolve_pointer(doc, "/" + "/".join(tokens[:-1]))
    key: Any = int(tokens[-1]) if isinstance(parent, list) else tokens[-1]
    parent[key] = value


def _rewrite_expressions(
    doc: dict[str, Any],
    predicate: Callable[[ex.Node, str, int, int | None], list[tuple[ex.Span, str]]],
    warnings: list[str],
) -> None:
    """全式を型付き AST にし、`predicate` が返す置換を適用する。構文エラーの式は warnings へ。"""
    model = _validate(doc, "")
    nodes, _ = typed_nodes(model)
    for pointer, text, circle, rite in list(_all_expressions(doc)):
        node = nodes.get(pointer)
        if node is None:
            try:
                node = ex.parse_expr(text)
            except ex.ExprSyntaxError:
                warnings.append(pointer)
                continue
        edits = predicate(node, pointer, circle, rite)
        if edits:
            _set_at(doc, pointer, _splice(text, edits))


def _locals_of(doc: dict[str, Any], circle: int, rite: int | None) -> set[str]:
    if rite is None:
        return set()
    r = doc["circles"][circle]["rites"][rite]
    names = {p.get("name") for p in r.get("params") or []}
    for step in _walk_plain_steps(r.get("steps") or []):
        if step.get("do") in ("let", "loop") and step.get("name"):
            names.add(step["name"])
    return names


def _walk_plain_steps(steps: list[Any]):
    for step in steps:
        yield step
        for key in ("then", "else", "steps"):
            if isinstance(step.get(key), list):
                yield from _walk_plain_steps(step[key])


def _state_names(doc: dict[str, Any], circle: int) -> set[str]:
    return {s.get("name") for s in doc["circles"][circle].get("state") or []}


def _rename_circle(doc: dict[str, Any], tokens: list[str], new: str, warnings: list[str]) -> str:
    circles = doc["circles"]
    index = int(tokens[1])
    _check_index({"pointer": "/" + "/".join(tokens)}, index, circles, allow_append=False)
    circle = circles[index]
    old = circle["name"]
    _reject_duplicate(
        [c["name"] for c in circles if c is not circle]
        + [f["name"] for f in doc.get("forms") or []],
        new,
        "circle",
    )
    circle["name"] = new
    if doc.get("root") == old:
        doc["root"] = new
    for other in circles:
        other_delegate = other.get("delegate")
        if other_delegate:
            other["delegate"] = [new if d == old else d for d in other_delegate]
        flow = other.get("flow")
        if isinstance(flow, dict):
            flow["steps"] = [new if s == old else s for s in flow.get("steps") or []]
        for sigil in other.get("sigils") or []:
            if sigil.get("kind") == "summon" and sigil.get("circle") == old:
                sigil["circle"] = new
        for rite in other.get("rites") or []:
            for step in _walk_plain_steps(rite.get("steps") or []):
                if step.get("do") in ("emit", "transfer") and step.get("circle") == old:
                    step["circle"] = new

    def predicate(
        node: ex.Node, pointer: str, ci: int, ri: int | None
    ) -> list[tuple[ex.Span, str]]:
        shadow = _state_names(doc, ci) | _locals_of(doc, ci, ri)
        if old in shadow:
            return []
        edits = []
        for n in ex.walk(node):
            if isinstance(n, ex.FieldAccess) and isinstance(n.obj, ex.Name) and n.obj.name == old:
                edits.append((n.obj.span, new))
        return edits

    _rewrite_expressions(doc, predicate, warnings)
    return old


def _rename_type_text(text: str, old: str, new: str) -> str:
    head, inner = parse_type(text)
    if head == "list" and inner is not None:
        return f"list<{_rename_type_text(inner, old, new)}>"
    return new if head == old else text


def _rename_types(doc: dict[str, Any], old: str, new: str) -> None:
    for form in doc.get("forms") or []:
        for f in form.get("fields") or []:
            f["type"] = _rename_type_text(f["type"], old, new)
    for circle in doc.get("circles", []):
        for s in circle.get("state") or []:
            s["type"] = _rename_type_text(s["type"], old, new)
        for rite in circle.get("rites") or []:
            for p in rite.get("params") or []:
                p["type"] = _rename_type_text(p["type"], old, new)
            if isinstance(rite.get("returns"), str):
                rite["returns"] = _rename_type_text(rite["returns"], old, new)
            for step in _walk_plain_steps(rite.get("steps") or []):
                if step.get("do") == "let" and isinstance(step.get("type"), str):
                    step["type"] = _rename_type_text(step["type"], old, new)


def _rename_form(doc: dict[str, Any], tokens: list[str], new: str, warnings: list[str]) -> str:
    forms = doc.get("forms") or []
    index = int(tokens[1])
    _check_index({"pointer": "/" + "/".join(tokens)}, index, forms, allow_append=False)
    form = forms[index]
    old = form["name"]
    _reject_duplicate(
        [f["name"] for f in forms if f is not form]
        + [c["name"] for c in doc["circles"]]
        + ["Pointer"],
        new,
        "型紙",
    )
    form["name"] = new
    _rename_types(doc, old, new)

    def predicate(
        node: ex.Node, pointer: str, ci: int, ri: int | None
    ) -> list[tuple[ex.Span, str]]:
        return [
            (n.form_span, new)
            for n in ex.walk(node)
            if isinstance(n, ex.Construct) and n.form == old
        ]

    _rewrite_expressions(doc, predicate, warnings)
    return old


def _rename_field(doc: dict[str, Any], tokens: list[str], new: str, warnings: list[str]) -> str:
    forms = doc.get("forms") or []
    form_index, field_index = int(tokens[1]), int(tokens[3])
    _check_index({"pointer": "/" + "/".join(tokens)}, form_index, forms, allow_append=False)
    fields = forms[form_index].get("fields") or []
    _check_index({"pointer": "/" + "/".join(tokens)}, field_index, fields, allow_append=False)
    form_name = forms[form_index]["name"]
    old = fields[field_index]["name"]
    _reject_duplicate([f["name"] for i, f in enumerate(fields) if i != field_index], new, "欄")
    fields[field_index]["name"] = new

    def predicate(
        node: ex.Node, pointer: str, ci: int, ri: int | None
    ) -> list[tuple[ex.Span, str]]:
        edits = []
        unresolved = False
        for n in ex.walk(node):
            if isinstance(n, ex.FieldAccess) and n.name == old:
                if n.obj.type == form_name:
                    edits.append((n.name_span, new))
                elif n.obj.type is None and not (
                    isinstance(n.obj, ex.Name) and n.obj.name in _known_non_values(doc, ci)
                ):
                    unresolved = True
            if isinstance(n, ex.Construct) and n.form == form_name:
                edits.extend((span, new) for name, span, _ in n.fields if name == old)
        if unresolved:
            warnings.append(pointer)
        return edits

    _rewrite_expressions(doc, predicate, warnings)
    return old


def _known_non_values(doc: dict[str, Any], circle: int) -> set[str]:
    """`Name.member` の Name が値でない（陣名 / sigil 名）ことが分かる名前。欄名の追随から除く。"""
    names = {c["name"] for c in doc["circles"]}
    names |= {s["name"] for s in doc["circles"][circle].get("sigils") or []}
    return names


def _rename_state(doc: dict[str, Any], tokens: list[str], new: str, warnings: list[str]) -> str:
    ci = int(tokens[1])
    circles = doc["circles"]
    _check_index({"pointer": "/" + "/".join(tokens)}, ci, circles, allow_append=False)
    circle = circles[ci]
    states = circle.get("state") or []
    si = int(tokens[3])
    _check_index({"pointer": "/" + "/".join(tokens)}, si, states, allow_append=False)
    old = states[si]["name"]
    taken = [s["name"] for i, s in enumerate(states) if i != si]
    taken += [s["name"] for s in circle.get("sigils") or []]
    _reject_duplicate(taken, new, "state")
    states[si]["name"] = new
    circle_name = circle["name"]

    def predicate(
        node: ex.Node, pointer: str, other: int, ri: int | None
    ) -> list[tuple[ex.Span, str]]:
        edits = []
        if other == ci:
            if old in _locals_of(doc, ci, ri):
                return []
            for n in ex.walk(node):
                if (
                    isinstance(n, ex.Name)
                    and n.name == old
                    and not _is_member_base_of_non_value(node, n, doc, ci)
                ):
                    edits.append((n.span, new))
        else:
            for n in ex.walk(node):
                if (
                    isinstance(n, ex.FieldAccess)
                    and isinstance(n.obj, ex.Name)
                    and n.obj.name == circle_name
                    and n.name == old
                ):
                    edits.append((n.name_span, new))
        return edits

    _rewrite_expressions(doc, predicate, warnings)
    return old


def _is_member_base_of_non_value(
    root: ex.Node, target: ex.Name, doc: dict[str, Any], ci: int
) -> bool:
    """`target` が `Name.member` の Name で、その Name が陣名 / sigil 名として解決されるか。"""
    if target.name not in _known_non_values(doc, ci):
        return False
    return any(isinstance(n, ex.FieldAccess) and n.obj is target for n in ex.walk(root))


def _rename_sigil(doc: dict[str, Any], tokens: list[str], new: str, warnings: list[str]) -> str:
    ci = int(tokens[1])
    circles = doc["circles"]
    _check_index({"pointer": "/" + "/".join(tokens)}, ci, circles, allow_append=False)
    circle = circles[ci]
    sigils = circle.get("sigils") or []
    gi = int(tokens[3])
    _check_index({"pointer": "/" + "/".join(tokens)}, gi, sigils, allow_append=False)
    old = sigils[gi]["name"]
    taken = [s["name"] for i, s in enumerate(sigils) if i != gi]
    taken += [s["name"] for s in circle.get("state") or []] + [
        r["name"] for r in circle.get("rites") or []
    ]
    _reject_duplicate(taken, new, "sigil")
    sigils[gi]["name"] = new
    for rite in circle.get("rites") or []:
        for step in _walk_plain_steps(rite.get("steps") or []):
            if step.get("do") == "cast":
                head, dot, member = step["target"].partition(".")
                if head == old:
                    step["target"] = new + dot + member

    def predicate(
        node: ex.Node, pointer: str, other: int, ri: int | None
    ) -> list[tuple[ex.Span, str]]:
        if other != ci or old in _locals_of(doc, ci, ri):
            return []
        return [
            (n.obj.span, new)
            for n in ex.walk(node)
            if isinstance(n, ex.FieldAccess) and isinstance(n.obj, ex.Name) and n.obj.name == old
        ]

    _rewrite_expressions(doc, predicate, warnings)
    return old


def _rename_rite(doc: dict[str, Any], tokens: list[str], new: str, warnings: list[str]) -> str:
    del warnings
    ci = int(tokens[1])
    circles = doc["circles"]
    _check_index({"pointer": "/" + "/".join(tokens)}, ci, circles, allow_append=False)
    circle = circles[ci]
    rites = circle.get("rites") or []
    ri = int(tokens[3])
    _check_index({"pointer": "/" + "/".join(tokens)}, ri, rites, allow_append=False)
    old = rites[ri]["name"]
    taken = [r["name"] for i, r in enumerate(rites) if i != ri] + [
        s["name"] for s in circle.get("sigils") or []
    ]
    _reject_duplicate(taken, new, "手順")
    rites[ri]["name"] = new
    if circle.get("core") == old:
        circle["core"] = new
    boundary = circle.get("boundary") or {}
    for on in boundary.get("on") or []:
        if on.get("rite") == old:
            on["rite"] = new
    for rite in rites:
        for step in _walk_plain_steps(rite.get("steps") or []):
            if step.get("do") == "cast" and step.get("target") == old:
                step["target"] = new
    for other in circles:
        for sigil in other.get("sigils") or []:
            if (
                sigil.get("kind") == "summon"
                and sigil.get("circle") == circle["name"]
                and sigil.get("rite") == old
            ):
                sigil["rite"] = new
    return old


def _rename_local(
    doc: dict[str, Any], tokens: list[str], new: str, owner: str, warnings: list[str]
) -> str:
    ci, ri = int(tokens[1]), int(tokens[3])
    circles = doc["circles"]
    _check_index({"pointer": "/" + "/".join(tokens)}, ci, circles, allow_append=False)
    circle = circles[ci]
    rites = circle.get("rites") or []
    _check_index({"pointer": "/" + "/".join(tokens)}, ri, rites, allow_append=False)
    holder = _at(doc, "/" + "/".join(tokens))
    if owner == "step" and holder.get("do") not in ("let", "loop"):
        raise OpError(
            "JIN002",
            "名前を持つステップは let と loop だけです",
            f"実際の do: {holder.get('do')!r}",
        )
    old = holder.get("name")
    if not isinstance(old, str):
        raise OpError("JIN002", "この要素は名前を持っていません", "count ループの name は任意です")
    taken = (
        (_locals_of(doc, ci, ri) - {old})
        | _state_names(doc, ci)
        | {s["name"] for s in circle.get("sigils") or []}
    )
    _reject_duplicate(sorted(taken), new, "局所名")
    holder["name"] = new
    rite_pointer_prefix = f"/circles/{ci}/rites/{ri}/"

    def predicate(
        node: ex.Node, pointer: str, other: int, other_rite: int | None
    ) -> list[tuple[ex.Span, str]]:
        if not pointer.startswith(rite_pointer_prefix):
            return []
        return [
            (n.span, new)
            for n in ex.walk(node)
            if isinstance(n, ex.Name)
            and n.name == old
            and not _is_member_base_of_non_value(node, n, doc, ci)
        ]

    _rewrite_expressions(doc, predicate, warnings)
    return old


# --------------------------------------------------------------------------------------
# 一覧と適用
# --------------------------------------------------------------------------------------
#: オペレーション名 → 実装。docs/spec/v2/ops.md §2 の 32 件と一致すること（test_v2_ops.py が検査する）。
OPERATIONS: dict[str, Callable[[dict[str, Any], Op], Inverse]] = {
    "setStage": _patcher(["stage"], "setStage", None),
    "addForm": _adder(["forms"], "removeForm", "型紙"),
    "removeForm": _remover(["forms", None], "addForm"),
    "setForm": _patcher(["forms", None], "setForm", "型紙"),
    "addCircle": _adder(["circles"], "removeCircle", "circle"),
    "removeCircle": _remover(["circles", None], "addCircle"),
    "setCore": _set_core,
    "addState": _adder(["circles", None, "state"], "removeState", "state"),
    "removeState": _remover(["circles", None, "state", None], "addState"),
    "setState": _patcher(["circles", None, "state", None], "setState", "state"),
    "addSigil": _adder(["circles", None, "sigils"], "removeSigil", "sigil"),
    "removeSigil": _remover(["circles", None, "sigils", None], "addSigil"),
    "moveSigil": _mover(["circles", None, "sigils", None], "moveSigil"),
    "addRite": _adder(["circles", None, "rites"], "removeRite", "手順"),
    "removeRite": _remover(["circles", None, "rites", None], "addRite"),
    "setRiteSignature": _patcher(
        ["circles", None, "rites", None], "setRiteSignature", None, immutable=("name", "steps")
    ),
    "addStep": _add_step,
    "removeStep": _remove_step,
    "moveStep": _move_step,
    "setStep": _set_step,
    "wrapSteps": _wrap_steps,
    "unwrapSteps": _unwrap_steps,
    "extractRite": _extract_rite,
    "setOn": _set_on,
    "removeOn": _remove_on,
    "setGuard": _set_guard,
    "removeGuard": _remove_guard,
    "addDelegate": _adder(["circles", None, "delegate"], "removeDelegate", "delegate"),
    "removeDelegate": _remover(["circles", None, "delegate", None], "addDelegate"),
    "setFlow": _set_flow,
    "setRoot": _set_root,
    "rename": _rename,
}


def apply_op(model: JinFileV2, op: Op) -> OpResult:
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
    warnings: list[str] = []
    if isinstance(inverse, dict) and "warnings" in inverse:
        warnings = list(inverse.pop("warnings"))
    return OpResult(model=_validate(document, _pointer(op)), inverse=inverse, warnings=warnings)


def apply_ops(model: JinFileV2, ops: list[Op]) -> OpsResult:
    """オペレーション列をまとめて適用する。1 つでも失敗したら何も適用しない。"""
    current = model
    inverses: list[Op] = []
    warnings: list[str] = []
    for op in ops:
        result = apply_op(current, op)
        current = result.model
        if isinstance(result.inverse, list):
            # 合成の逆は「undo するときに適用する順」で並んでいる。最後に全体を反転するので、
            # ここでは逆順に積んでおく（反転後に元の順へ戻る）
            inverses.extend(reversed(result.inverse))
        else:
            inverses.append(result.inverse)
        warnings.extend(result.warnings)
    inverses.reverse()
    return OpsResult(model=current, inverses=inverses, warnings=warnings)


__all__ = [
    "OPERATIONS",
    "STEP_LIST_KEYS",
    "Inverse",
    "OpResult",
    "OpsResult",
    "apply_op",
    "apply_ops",
]
