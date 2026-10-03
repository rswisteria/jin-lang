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
from jin_core.v2 import references
from jin_core.v2.model import JinFileV2
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

    追随する参照の位置は `jin_core.v2.references.find` が決める（LSP の references と同じ表）。
    **定義の名前を書き換える前に**集め、集めた位置を書き換えてから定義の名前を書く。型が決まらない
    式と構文エラーの式は触らず `warnings` に載せる（`apply_op` が `OpResult.warnings` に運ぶ）。
    """
    tokens = _tokens(op)
    new_name = _require_str(op, "value")
    kind = references.target_kind(tokens)
    if kind is None:
        raise OpError(
            "JIN002",
            f"rename が扱えない pointer です: {'/' + '/'.join(tokens)!r}",
            "circle / form / form の欄 / state / sigil / rite / params / let / loop.name の pointer を指定してください",
            "/" + "/".join(tokens),
        )
    holder = _rename_holder(doc, op, tokens, kind)
    old = holder.get("name")
    if not isinstance(old, str):
        raise OpError("JIN002", "この要素は名前を持っていません", "count ループの name は任意です")
    _reject_duplicate(_taken_names(doc, tokens, kind, old), new_name, _NOUNS[kind[0]])
    symbol = references.find(doc, "/" + "/".join(tokens), _typed(doc))
    references.apply(doc, symbol, new_name)
    holder["name"] = new_name
    inverse: Op = {"op": "rename", "pointer": _pointer(op), "value": old}
    if symbol.unresolved:
        inverse["warnings"] = symbol.unresolved  # apply_op が取り出して OpResult.warnings へ移す
    return inverse


#: 重複の診断に出す名詞。
_NOUNS = {
    "circle": "circle",
    "form": "型紙",
    "field": "欄",
    "state": "state",
    "sigil": "sigil",
    "rite": "手順",
    "local": "局所名",
}


def _typed(doc: dict[str, Any]) -> dict[str, ex.Node]:
    nodes, _ = typed_nodes(_validate(doc, ""))
    return nodes


def _rename_holder(
    doc: dict[str, Any], op: Op, tokens: list[str], kind: tuple[str, str]
) -> dict[str, Any]:
    """名前を持つ dict（添字の範囲を確かめてから返す）。"""
    if kind[0] in ("form", "field"):
        forms = doc.get("forms") or []
        _check_index(op, int(tokens[1]), forms, allow_append=False)
        if kind[0] == "form":
            return forms[int(tokens[1])]
        fields = forms[int(tokens[1])].get("fields") or []
        _check_index(op, int(tokens[3]), fields, allow_append=False)
        return fields[int(tokens[3])]
    circles = doc["circles"]
    _check_index(op, int(tokens[1]), circles, allow_append=False)
    if kind[0] == "circle":
        return circles[int(tokens[1])]
    key = {"state": "state", "sigil": "sigils"}.get(kind[0], "rites")
    items = circles[int(tokens[1])].get(key) or []
    _check_index(op, int(tokens[3]), items, allow_append=False)
    if kind[0] != "local":
        return items[int(tokens[3])]
    holder = _at(doc, "/" + "/".join(tokens))
    if kind[1] == "step" and holder.get("do") not in ("let", "loop"):
        raise OpError(
            "JIN002",
            "名前を持つステップは let と loop だけです",
            f"実際の do: {holder.get('do')!r}",
        )
    return holder


def _taken_names(
    doc: dict[str, Any], tokens: list[str], kind: tuple[str, str], old: str
) -> list[str]:
    """新しい名前と衝突してはいけない名前（並びは診断の hint にそのまま出る）。"""
    if kind[0] == "circle":
        circles = doc["circles"]
        me = circles[int(tokens[1])]
        return [c["name"] for c in circles if c is not me] + [
            f["name"] for f in doc.get("forms") or []
        ]
    if kind[0] == "form":
        forms = doc.get("forms") or []
        me = forms[int(tokens[1])]
        return (
            [f["name"] for f in forms if f is not me]
            + [c["name"] for c in doc["circles"]]
            + ["Pointer"]
        )
    if kind[0] == "field":
        fields = doc["forms"][int(tokens[1])].get("fields") or []
        return [f["name"] for i, f in enumerate(fields) if i != int(tokens[3])]
    circle = doc["circles"][int(tokens[1])]
    position = int(tokens[3])
    states = [s["name"] for s in circle.get("state") or []]
    sigils = [s["name"] for s in circle.get("sigils") or []]
    rites = [r["name"] for r in circle.get("rites") or []]
    if kind[0] == "state":
        return [n for i, n in enumerate(states) if i != position] + sigils
    if kind[0] == "sigil":
        return [n for i, n in enumerate(sigils) if i != position] + states + rites
    if kind[0] == "rite":
        return [n for i, n in enumerate(rites) if i != position] + sigils
    rite = circle["rites"][position]
    locals_ = {p.get("name") for p in rite.get("params") or []}
    for step in _walk_plain_steps(rite.get("steps") or []):
        if step.get("do") in ("let", "loop") and step.get("name"):
            locals_.add(step["name"])
    return sorted((locals_ - {old}) | set(states) | set(sigils))


def _walk_plain_steps(steps: list[Any]):
    for step in steps:
        yield step
        for key in STEP_LIST_KEYS:
            if isinstance(step.get(key), list):
                yield from _walk_plain_steps(step[key])


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
