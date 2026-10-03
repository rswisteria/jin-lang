"""名前を持つ要素への参照の位置（docs/spec/v2/ops.md §3 の追随範囲）。

`rename` の参照追随（`jin_core.v2.ops`）と LSP の definition / references / rename（`jin_lsp`）が
**同じ表**を読むための 1 か所である。追随範囲の判定（影になる局所・陣名 / sigil 名の `Name.member`・
型が解決できた式の欄だけ）をここ以外に書かない（2 か所で書くと「rename は追うのに references には
出ない」形で静かにずれる）。

参照の位置は (pointer, span) で表す。pointer は文字列の値（式・型・名前）を指し、span は
その文字列の**復号後**の区間（`None` は値の全体）。原文の位置への換算は `jin_core.v2.spans` が行う。
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from jin_core.pointer import resolve_pointer, split_pointer
from jin_core.v2 import expr as ex
from jin_core.v2.model import JinFileV2
from jin_core.v2.semantic import typed_nodes

#: 名前を持つステップ列のキー（`ops.STEP_LIST_KEYS` と同じ。`ops` を import すると循環する）。
_STEP_LIST_KEYS = ("steps", "then", "else")

#: ステップの中で式を持つ欄。`cast.target` は式ではなく名前なので別に扱う。
_EXPR_KEYS = ("expr", "cond", "target", "into", "in", "times", "ticks", "until")


@dataclass(frozen=True, slots=True)
class Occurrence:
    """参照 1 か所。`span` は値の文字列（復号後）の中の区間で、`None` は値の全体。"""

    pointer: str
    span: ex.Span | None = None


@dataclass(slots=True)
class Symbol:
    """名前を持つ要素 1 つと、それへの参照の全部。

    - `kind`: `circle` / `form` / `field` / `state` / `sigil` / `rite` / `local`
    - `target`: `rename` が受ける pointer（`/circles/0` / `/forms/0/fields/1` / … / let の pointer）。
      名前の値は `target + "/name"`
    - `unresolved`: 追随できなかった式の pointer（構文エラー / 型が決まらない欄の参照）。
      `rename` の `warnings` そのもの（ops.md §3）
    """

    kind: str
    target: str
    name: str
    occurrences: list[Occurrence] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)

    @property
    def name_pointer(self) -> str:
        return f"{self.target}/name"


def target_kind(tokens: list[str]) -> tuple[str, str] | None:
    """`rename` の pointer の形 → (種類, 局所の持ち主 `param` / `step`)。扱えない形は `None`。"""
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
        if tokens[4] in _STEP_LIST_KEYS:
            return "local", "step"
    return None


def find(doc: dict[str, Any], target: str, nodes: dict[str, ex.Node] | None = None) -> Symbol:
    """`target`（`rename` の pointer）が指す要素への参照を集める。

    `doc` は素の dict（`model_dump(by_alias=True, mode="json")`）。`nodes` は型注記付き AST
    （無ければここで `typed_nodes` を取る）。pointer の形と添字は呼ぶ側が確かめておく
    （範囲外なら `IndexError` / `KeyError`、形が違えば `ValueError`、名前が無ければ `TypeError`）。
    """
    tokens = split_pointer(target)
    kind = target_kind(tokens)
    if kind is None:
        raise ValueError(f"名前を持つ要素の pointer ではありません: {target!r}")
    if nodes is None:
        nodes, _ = typed_nodes(JinFileV2.model_validate(doc))
    name = resolve_pointer(doc, target)["name"]
    if not isinstance(name, str):
        raise TypeError(f"この要素は名前を持っていません: {target!r}")
    symbol = Symbol(kind=kind[0], target=target, name=name)
    collect = {
        "circle": _circle,
        "form": _form,
        "field": _field,
        "state": _state,
        "sigil": _sigil,
        "rite": _rite,
        "local": _local,
    }[kind[0]]
    collect(doc, tokens, symbol, nodes)
    return symbol


def index(model: JinFileV2) -> list[Symbol]:
    """モデルの名前を持つ要素すべて（文書順）。LSP の definition / references が引く表。"""
    doc = model.model_dump(by_alias=True, mode="json")
    nodes, _ = typed_nodes(model)
    return [find(doc, target, nodes) for target in targets(doc)]


def targets(doc: dict[str, Any]) -> Iterator[str]:
    """名前を持つ要素の pointer（`rename` が受ける形）を文書順に列挙する。"""
    for i, form in enumerate(doc.get("forms") or []):
        yield f"/forms/{i}"
        for j, _ in enumerate(form.get("fields") or []):
            yield f"/forms/{i}/fields/{j}"
    for i, circle in enumerate(doc.get("circles") or []):
        yield f"/circles/{i}"
        for key in ("state", "sigils", "rites"):
            for j, _ in enumerate(circle.get(key) or []):
                yield f"/circles/{i}/{key}/{j}"
        for j, rite in enumerate(circle.get("rites") or []):
            for k, _ in enumerate(rite.get("params") or []):
                yield f"/circles/{i}/rites/{j}/params/{k}"
            for pointer, step in _steps_with_pointers(
                f"/circles/{i}/rites/{j}/steps", rite.get("steps") or []
            ):
                if step.get("do") in ("let", "loop") and isinstance(step.get("name"), str):
                    yield pointer


def symbol_at(symbols: list[Symbol], pointer: str, offset: int | None) -> Symbol | None:
    """値 `pointer` の復号後の添字 `offset` にある名前の要素（定義の名前か参照）。

    `offset` が区間の中にある参照を先に、区間の直後（識別子の末尾にカーソルがある形）を次に見る。
    `Game.score` の `.` の上は `Game` の直後であり `score` の手前なので、中にある方を選ぶ。
    """
    for symbol in symbols:
        if pointer == symbol.name_pointer:
            return symbol
    for inclusive_end in (False, True):
        for symbol in symbols:
            for occurrence in symbol.occurrences:
                if occurrence.pointer != pointer:
                    continue
                span = occurrence.span
                if span is None:
                    return symbol
                if offset is None:
                    continue
                if span.start <= offset < span.end or (inclusive_end and offset == span.end):
                    return symbol
    return None


def apply(doc: dict[str, Any], symbol: Symbol, new: str) -> None:
    """参照を `new` に書き換える（定義の名前は書き換えない。`rename` が別に書く）。"""
    by_pointer: dict[str, list[ex.Span | None]] = {}
    for occurrence in symbol.occurrences:
        by_pointer.setdefault(occurrence.pointer, []).append(occurrence.span)
    for pointer, spans in by_pointer.items():
        if None in spans:
            _set_at(doc, pointer, new)
            continue
        text = resolve_pointer(doc, pointer)
        edits = [span for span in spans if span is not None]
        for span in sorted(edits, key=lambda s: s.start, reverse=True):
            text = text[: span.start] + new + text[span.end :]
        _set_at(doc, pointer, text)


# ---------------------------------------------------------------- 走査の共通


def _steps_with_pointers(pointer: str, steps: list[Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    for k, step in enumerate(steps):
        sp = f"{pointer}/{k}"
        yield sp, step
        for key in _STEP_LIST_KEYS:
            if isinstance(step.get(key), list):
                yield from _steps_with_pointers(f"{sp}/{key}", step[key])


def _all_expressions(doc: dict[str, Any]) -> Iterator[tuple[str, str, int, int | None]]:
    """(pointer, 式文字列, 陣の添字, 手順の添字) を全部列挙する。`set.target` / `cast.into` を含む。"""
    for i, circle in enumerate(doc.get("circles") or []):
        base = f"/circles/{i}"
        for j, state in enumerate(circle.get("state") or []):
            yield f"{base}/state/{j}/init", state.get("init", ""), i, None
        for j, rite in enumerate(circle.get("rites") or []):
            for sp, step in _steps_with_pointers(
                f"{base}/rites/{j}/steps", rite.get("steps") or []
            ):
                for key in _EXPR_KEYS:
                    if key == "target" and step.get("do") == "cast":
                        continue  # cast.target は式ではなく名前（別に扱う）
                    if isinstance(step.get(key), str):
                        yield f"{sp}/{key}", step[key], i, j
                for a, arg in enumerate(step.get("args") or []):
                    yield f"{sp}/args/{a}", arg, i, j
        boundary = circle.get("boundary") or {}
        for j, guard in enumerate(boundary.get("guards") or []):
            yield f"{base}/boundary/guards/{j}/assert", guard.get("assert", ""), i, None
        flow = circle.get("flow")
        if isinstance(flow, dict) and isinstance(flow.get("exit"), str):
            yield f"{base}/flow/exit", flow["exit"], i, None


def _expressions(
    doc: dict[str, Any], nodes: dict[str, ex.Node], symbol: Symbol
) -> Iterator[tuple[str, ex.Node, int, int | None]]:
    """全式の AST。型検査に進まなかった式は構文解析だけし、構文エラーの式は `unresolved` へ。"""
    for pointer, text, circle, rite in _all_expressions(doc):
        node = nodes.get(pointer)
        if node is None:
            try:
                node = ex.parse_expr(text)
            except ex.ExprSyntaxError:
                symbol.unresolved.append(pointer)
                continue
        yield pointer, node, circle, rite


def _locals_of(doc: dict[str, Any], circle: int, rite: int | None) -> set[str]:
    if rite is None:
        return set()
    r = doc["circles"][circle]["rites"][rite]
    names = {p.get("name") for p in r.get("params") or []}
    for _sp, step in _steps_with_pointers("", r.get("steps") or []):
        if step.get("do") in ("let", "loop") and step.get("name"):
            names.add(step["name"])
    return names


def _state_names(doc: dict[str, Any], circle: int) -> set[str]:
    return {s.get("name") for s in doc["circles"][circle].get("state") or []}


def _known_non_values(doc: dict[str, Any], circle: int) -> set[str]:
    """`Name.member` の Name が値でない（陣名 / sigil 名）ことが分かる名前。"""
    names = {c["name"] for c in doc["circles"]}
    names |= {s["name"] for s in doc["circles"][circle].get("sigils") or []}
    return names


def _is_member_base_of_non_value(
    root: ex.Node, target: ex.Name, doc: dict[str, Any], ci: int
) -> bool:
    """`target` が `Name.member` の Name で、その Name が陣名 / sigil 名として解決されるか。"""
    if target.name not in _known_non_values(doc, ci):
        return False
    return any(isinstance(n, ex.FieldAccess) and n.obj is target for n in ex.walk(root))


def _type_span(text: str, name: str) -> ex.Span | None:
    """型文字列の中の型紙名の区間（`list<…>` の中も）。無ければ `None`。"""
    offset = 0
    while text.startswith("list<") and text.endswith(">"):
        offset += len("list<")
        text = text[len("list<") : -1]
    return ex.Span(offset, offset + len(name)) if text == name else None


def _set_at(doc: dict[str, Any], pointer: str, value: str) -> None:
    tokens = split_pointer(pointer)
    parent = resolve_pointer(doc, "".join(f"/{t}" for t in tokens[:-1]))
    key: Any = int(tokens[-1]) if isinstance(parent, list) else tokens[-1]
    parent[key] = value


# ---------------------------------------------------------------- 種類ごとの追随範囲（ops.md §3）


def _circle(doc: dict[str, Any], tokens: list[str], symbol: Symbol, nodes: dict) -> None:
    """`root` / `flow.steps` / `delegate` / `summon.circle` / `emit.circle` / `transfer.circle` / 式の `陣名.key`。"""
    old = symbol.name
    found = symbol.occurrences
    if doc.get("root") == old:
        found.append(Occurrence("/root"))
    for i, other in enumerate(doc["circles"]):
        base = f"/circles/{i}"
        for j, name in enumerate(other.get("delegate") or []):
            if name == old:
                found.append(Occurrence(f"{base}/delegate/{j}"))
        flow = other.get("flow")
        if isinstance(flow, dict):
            for j, step in enumerate(flow.get("steps") or []):
                if step == old:
                    found.append(Occurrence(f"{base}/flow/steps/{j}"))
        for j, sigil in enumerate(other.get("sigils") or []):
            if sigil.get("kind") == "summon" and sigil.get("circle") == old:
                found.append(Occurrence(f"{base}/sigils/{j}/circle"))
        for j, rite in enumerate(other.get("rites") or []):
            for sp, step in _steps_with_pointers(
                f"{base}/rites/{j}/steps", rite.get("steps") or []
            ):
                if step.get("do") in ("emit", "transfer") and step.get("circle") == old:
                    found.append(Occurrence(f"{sp}/circle"))
    for pointer, node, ci, ri in _expressions(doc, nodes, symbol):
        if old in _state_names(doc, ci) | _locals_of(doc, ci, ri):
            continue
        found.extend(
            Occurrence(pointer, n.obj.span)
            for n in ex.walk(node)
            if isinstance(n, ex.FieldAccess) and isinstance(n.obj, ex.Name) and n.obj.name == old
        )


def _form(doc: dict[str, Any], tokens: list[str], symbol: Symbol, nodes: dict) -> None:
    """型（`list<…>` の中も）とコンストラクタ `Name{`。"""
    old = symbol.name
    found = symbol.occurrences

    def type_at(pointer: str, text: Any) -> None:
        if isinstance(text, str):
            span = _type_span(text, old)
            if span is not None:
                found.append(Occurrence(pointer, span))

    for i, form in enumerate(doc.get("forms") or []):
        for j, f in enumerate(form.get("fields") or []):
            type_at(f"/forms/{i}/fields/{j}/type", f.get("type"))
    for i, circle in enumerate(doc.get("circles") or []):
        base = f"/circles/{i}"
        for j, s in enumerate(circle.get("state") or []):
            type_at(f"{base}/state/{j}/type", s.get("type"))
        for j, rite in enumerate(circle.get("rites") or []):
            for k, p in enumerate(rite.get("params") or []):
                type_at(f"{base}/rites/{j}/params/{k}/type", p.get("type"))
            type_at(f"{base}/rites/{j}/returns", rite.get("returns"))
            for sp, step in _steps_with_pointers(
                f"{base}/rites/{j}/steps", rite.get("steps") or []
            ):
                if step.get("do") == "let":
                    type_at(f"{sp}/type", step.get("type"))
    for pointer, node, _ci, _ri in _expressions(doc, nodes, symbol):
        found.extend(
            Occurrence(pointer, n.form_span)
            for n in ex.walk(node)
            if isinstance(n, ex.Construct) and n.form == old
        )


def _field(doc: dict[str, Any], tokens: list[str], symbol: Symbol, nodes: dict) -> None:
    """式の `.欄名`（型が解決できた式だけ。決まらなければ `unresolved`）とコンストラクタの欄。"""
    old = symbol.name
    form_name = doc["forms"][int(tokens[1])]["name"]
    for pointer, node, ci, _ri in _expressions(doc, nodes, symbol):
        unresolved = False
        for n in ex.walk(node):
            if isinstance(n, ex.FieldAccess) and n.name == old:
                if n.obj.type == form_name:
                    symbol.occurrences.append(Occurrence(pointer, n.name_span))
                elif n.obj.type is None and not (
                    isinstance(n.obj, ex.Name) and n.obj.name in _known_non_values(doc, ci)
                ):
                    unresolved = True
            if isinstance(n, ex.Construct) and n.form == form_name:
                symbol.occurrences.extend(
                    Occurrence(pointer, span) for name, span, _ in n.fields if name == old
                )
        if unresolved:
            symbol.unresolved.append(pointer)


def _state(doc: dict[str, Any], tokens: list[str], symbol: Symbol, nodes: dict) -> None:
    """自陣の式の裸の識別子（局所に隠されない）/ 他陣の式の `陣名.key`。"""
    old = symbol.name
    ci = int(tokens[1])
    circle_name = doc["circles"][ci]["name"]
    for pointer, node, other, ri in _expressions(doc, nodes, symbol):
        if other == ci:
            if old in _locals_of(doc, ci, ri):
                continue
            symbol.occurrences.extend(
                Occurrence(pointer, n.span)
                for n in ex.walk(node)
                if isinstance(n, ex.Name)
                and n.name == old
                and not _is_member_base_of_non_value(node, n, doc, ci)
            )
        else:
            symbol.occurrences.extend(
                Occurrence(pointer, n.name_span)
                for n in ex.walk(node)
                if isinstance(n, ex.FieldAccess)
                and isinstance(n.obj, ex.Name)
                and n.obj.name == circle_name
                and n.name == old
            )


def _sigil(doc: dict[str, Any], tokens: list[str], symbol: Symbol, nodes: dict) -> None:
    """自陣の `cast.target`（`名前` / `名前.member` の頭）と式の `名前.member`。"""
    old = symbol.name
    ci = int(tokens[1])
    circle = doc["circles"][ci]
    for j, rite in enumerate(circle.get("rites") or []):
        for sp, step in _steps_with_pointers(
            f"/circles/{ci}/rites/{j}/steps", rite.get("steps") or []
        ):
            if step.get("do") == "cast":
                head, _dot, _member = step["target"].partition(".")
                if head == old:
                    symbol.occurrences.append(Occurrence(f"{sp}/target", ex.Span(0, len(old))))
    for pointer, node, other, ri in _expressions(doc, nodes, symbol):
        if other != ci or old in _locals_of(doc, ci, ri):
            continue
        symbol.occurrences.extend(
            Occurrence(pointer, n.obj.span)
            for n in ex.walk(node)
            if isinstance(n, ex.FieldAccess) and isinstance(n.obj, ex.Name) and n.obj.name == old
        )


def _rite(doc: dict[str, Any], tokens: list[str], symbol: Symbol, nodes: dict) -> None:
    """`core` / `on.rite` / 自陣の `cast.target` / 他陣の `summon.rite`。式の中には現れない。"""
    del nodes
    old = symbol.name
    ci = int(tokens[1])
    circle = doc["circles"][ci]
    base = f"/circles/{ci}"
    if circle.get("core") == old:
        symbol.occurrences.append(Occurrence(f"{base}/core"))
    boundary = circle.get("boundary") or {}
    for j, on in enumerate(boundary.get("on") or []):
        if on.get("rite") == old:
            symbol.occurrences.append(Occurrence(f"{base}/boundary/on/{j}/rite"))
    for j, rite in enumerate(circle.get("rites") or []):
        for sp, step in _steps_with_pointers(f"{base}/rites/{j}/steps", rite.get("steps") or []):
            if step.get("do") == "cast" and step.get("target") == old:
                symbol.occurrences.append(Occurrence(f"{sp}/target"))
    for i, other in enumerate(doc["circles"]):
        for j, sigil in enumerate(other.get("sigils") or []):
            if (
                sigil.get("kind") == "summon"
                and sigil.get("circle") == circle["name"]
                and sigil.get("rite") == old
            ):
                symbol.occurrences.append(Occurrence(f"/circles/{i}/sigils/{j}/rite"))


def _local(doc: dict[str, Any], tokens: list[str], symbol: Symbol, nodes: dict) -> None:
    """その手順（スコープ）の中の式の裸の識別子。"""
    old = symbol.name
    ci = int(tokens[1])
    prefix = f"/circles/{ci}/rites/{tokens[3]}/"
    for pointer, node, _other, _ri in _expressions(doc, nodes, symbol):
        if not pointer.startswith(prefix):
            continue
        symbol.occurrences.extend(
            Occurrence(pointer, n.span)
            for n in ex.walk(node)
            if isinstance(n, ex.Name)
            and n.name == old
            and not _is_member_base_of_non_value(node, n, doc, ci)
        )


__all__ = ["Occurrence", "Symbol", "apply", "find", "index", "symbol_at", "target_kind", "targets"]
