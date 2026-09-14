"""Jin v2（`version: 2`）の hover と completion（設計書 §8・Phase 5）。

設計書 §8 の範囲そのまま:

- hover: **式の型**、**ホスト能力のシグネチャ**（カタログ `jin_core.v2.abilities` 由来）、
  **state の公開 / 非公開**。加えて陣 / 手順 / 型紙 / `on` の要約
- completion: **式の中の識別子（スコープ順・expr.md §3.1）**、**`.` の後の名前空間メンバ**、
  **`do` の値**、**型名**。参照名（陣名 / 手順名 / 名前空間名）とキー名 / enum 値は
  v1 と同じ機構（`schema_items`）

式の中の情報は **`jin_core.v2.semantic.analyze_model`** から引く（AST / 型 / スコープ）。
ここで式を構文解析したり型を決めたりはしない（設計書 §8「式エディタは `jin_core.v2.expr` を
再実装しない」の LSP 側の写し）。「どの欄が式か」も `jin_core.v2.model.expr_fields`
（schema の `x-jin-expr` と同じ印）から引き、欄の名前を書き写さない。

## 補完の位置とクライアント側の絞り込み

ブラウザの式エディタ（`apps/editor`）は式のリテラルの**先頭位置**で completion を求め、候補を
カーソル直前のトークンで自分で絞る（`docs/spec/v2/ops.md` §5 / 設計書 §8）。そのため
「識別子（スコープ順）」の応答には `名前空間.メンバ` / `陣名.key` / `局所.欄` の**点付きのラベル**も
含める（クライアントは `input.` で始まる候補だけを残せる）。カーソルが実際に `名前.` の直後に
あるとき（Claude Code / VS Code がドキュメント上で補完を求めるとき）は、そのメンバだけを
点なしのラベルで返す。
"""

from __future__ import annotations

import re
from typing import Any

from jin_core.check import models_at
from jin_core.pointer import parent_of, resolve_pointer, split_pointer
from jin_core.v2 import abilities
from jin_core.v2 import expr as ex
from jin_core.v2.model import (
    PRIMITIVE_TYPES,
    CastStep,
    Circle,
    JinFileV2,
    Rite,
    SigilAgent,
    SigilHost,
    SigilSummon,
    expr_fields,
)
from jin_core.v2.semantic import BUILTIN_FORMS, EVENT_PARAMS, Analysis, analyze_model
from lsprotocol import types

from jin_lsp import locate, positions
from jin_lsp.features.schema_items import dedupe, enum_then_keys, item
from jin_lsp.session import DocumentState

#: カーソル直前が `名前.` の形か（式の中の `.` の後のメンバ補完）。
_DOTTED_PREFIX = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\.$")


# ---------------------------------------------------------------- 共通


def _context(
    state: DocumentState | None, position: types.Position
) -> tuple[JinFileV2, list[str], str, str] | None:
    """v2 の表示用モデル・行・カーソル位置の pointer・その行のカーソルまでの文字列。"""
    if state is None:
        return None
    model = state.model_v2_for_display
    table = state.table_for_display
    lines = state.lines_for_display
    if model is None or table is None or not lines:
        return None
    jin_position = positions.from_lsp_position(lines, position)
    pointer = locate.pointer_at(table, jin_position)
    if pointer is None:
        return None
    line_index = jin_position.line - 1
    before = lines[line_index][: jin_position.col - 1] if 0 <= line_index < len(lines) else ""
    return model, lines, pointer, before


def _signature(
    params: list[tuple[str, str]] | tuple[tuple[str, str], ...], returns: str | None
) -> str:
    inside = ", ".join(f"{name}: {type_}" for name, type_ in params)
    return f"({inside})" + (f" → {returns}" if returns is not None else "")


def _rite_signature(rite: Rite) -> str:
    return rite.name + _signature([(p.name, p.type) for p in rite.params], rite.returns)


def _member_signature(namespace: str, member: abilities.Member) -> str:
    return f"{namespace}.{member.name}" + _signature(member.params, member.returns)


def _circle_at(model: JinFileV2, tokens: list[str]) -> tuple[int, Circle] | None:
    if tokens[:1] != ["circles"] or len(tokens) < 2 or not tokens[1].isdigit():
        return None
    index = int(tokens[1])
    if index >= len(model.circles):
        return None
    return index, model.circles[index]


def _rite_names(model: JinFileV2, name: str) -> list[str]:
    for circle in model.circles:
        if circle.name == name:
            return [rite.name for rite in circle.rites]
    return []


# ---------------------------------------------------------------- hover


def hover(state: DocumentState | None, position: types.Position) -> types.Hover | None:
    context = _context(state, position)
    if context is None:
        return None
    model, _lines, pointer, _before = context
    markdown = _hover_markdown(model, analyze_model(model), pointer)
    if markdown is None:
        return None
    return types.Hover(contents=types.MarkupContent(kind=types.MarkupKind.Markdown, value=markdown))


def _hover_markdown(model: JinFileV2, analysis: Analysis, pointer: str) -> str | None:
    document = model.model_dump(by_alias=True, mode="json")
    tokens = split_pointer(pointer)

    # 式（型検査まで進んだもの）: 式の型
    if pointer in analysis.types:
        text = resolve_pointer(document, pointer)
        type_ = analysis.types[pointer]
        typed = f"型: `{type_}`" if type_ is not None else "型: 決められません（診断を参照）"
        return f"**式** `{text}`\n\n{typed}"

    if tokens == ["root"]:
        return f"**`root`** → 起動する陣 `{model.root}`（`transfer` で移る）"
    if tokens[:1] == ["stage"]:
        stage = model.stage
        return (
            f"**stage** {stage.width}×{stage.height} / {stage.fps} fps / seed {stage.seed}"
            f"（アセット {len(stage.assets)} 件）"
        )
    if tokens[:1] == ["forms"] and len(tokens) >= 2 and tokens[1].isdigit():
        index = int(tokens[1])
        if index >= len(model.forms):
            return None
        form = model.forms[index]
        fields = "\n".join(f"- `{f.name}: {f.type}`" for f in form.fields)
        return f"**型紙 `{form.name}`**（`{form.name}{{…}}` で作る）\n{fields}"

    found = _circle_at(model, tokens)
    if found is None:
        return None
    _index, circle = found
    rest = tokens[2:]
    if rest in ([], ["name"], ["core"], ["description"]) or rest[:1] == ["flow"]:
        return _circle_hover(circle)
    if rest[:1] == ["state"] and len(rest) >= 2 and rest[1].isdigit():
        position = int(rest[1])
        if position >= len(circle.state):
            return None
        member = circle.state[position]
        visibility = (
            f"**公開**（他の陣から `{circle.name}.{member.name}` で読める・`flow.exit` に使える）"
            if member.out
            else "**非公開**（この陣の手順だけが読み書きする。公開するには `out: true`）"
        )
        return (
            f"**state `{member.name}`**（型 `{member.type}`・init `{member.init}`）→ {visibility}"
        )
    if rest[:1] == ["sigils"] and len(rest) >= 2 and rest[1].isdigit():
        position = int(rest[1])
        if position >= len(circle.sigils):
            return None
        return _sigil_hover(model, circle.sigils[position])
    if rest[:1] == ["rites"] and len(rest) >= 2 and rest[1].isdigit():
        position = int(rest[1])
        if position >= len(circle.rites):
            return None
        rite = circle.rites[position]
        if len(rest) >= 3 and rest[2] == "steps":
            step_hover = _step_hover(model, circle, document, pointer, rest)
            if step_hover is not None:
                return step_hover
        core = "（核。`boot` 直後に起動する）" if circle.core == rite.name else ""
        handlers = [
            on.event
            for on in (circle.boundary.on if circle.boundary else [])
            if on.rite == rite.name
        ]
        via = f"\n- `on`: {' / '.join(handlers)}" if handlers else ""
        return f"**手順 `{_rite_signature(rite)}`**{core}\n- ステップ {len(rite.steps)} 個{via}"
    if rest[:2] == ["boundary", "on"] and len(rest) >= 3 and rest[2].isdigit():
        boundary = circle.boundary
        position = int(rest[2])
        if boundary is None or position >= len(boundary.on):
            return None
        on = boundary.on[position]
        params = EVENT_PARAMS[on.event]
        shape = ", ".join(params) + ("…" if on.event == "message" else "")
        return f"**on `{on.event}`** → 手順 `{on.rite}`（引数の形: `({shape})`）"
    if rest[:2] == ["boundary", "guards"]:
        return (
            "**guards[]** → デバッグビルドで毎 tick の終わりに評価し、偽ならトレースに `assert` 行"
        )
    if rest[:1] == ["delegate"] and len(rest) >= 2 and rest[1].isdigit():
        position = int(rest[1])
        if position >= len(circle.delegate):
            return None
        return f"**delegate** → 陣 `{circle.delegate[position]}`（`transfer` で移れる先）"
    return None


def _circle_hover(circle: Circle) -> str:
    if circle.core is not None:
        public = [s.name for s in circle.state if s.out]
        lines = [
            f"**陣 `{circle.name}`**（核 `{circle.core}`）",
            f"- state {len(circle.state)} 個（公開: {', '.join(public) if public else 'なし'}）",
            f"- 道具環 {len(circle.sigils)} / 手順 {len(circle.rites)}",
        ]
        if circle.boundary is not None and circle.boundary.on:
            lines.append(
                "- on: " + " / ".join(f"{on.event} → {on.rite}" for on in circle.boundary.on)
            )
        return "\n".join(lines)
    if circle.flow is not None:
        lines = [
            f"**陣 `{circle.name}`**（flow `{circle.flow.kind}`）",
            "- steps: " + " → ".join(circle.flow.steps),
        ]
        if circle.flow.exit is not None:
            lines.append(f"- exit: `{circle.flow.exit}`")
        return "\n".join(lines)
    return f"**陣 `{circle.name}`**（`core` も `flow` も無い → JIN022）"


def _sigil_hover(model: JinFileV2, sigil: SigilHost | SigilSummon | SigilAgent) -> str:
    if isinstance(sigil, SigilAgent):
        # v1 の陣に問う（runtime.md §11・v2.1）。答えるのはヘッドレスの Python ホストだけ。
        return (
            f"**sigil `{sigil.name}`**（agent `{sigil.file}`・v1 の陣に問う）\n"
            f"- `{sigil.name}(prompt: str) -> num`（要求 id。答えは `on message` に "
            f"`({sigil.name}, id: num, text: str)` で届く。ブラウザでは答えが来ない）"
        )
    if isinstance(sigil, SigilHost):
        namespace = abilities.namespace(sigil.host)
        if namespace is None:
            return f"**sigil `{sigil.name}`**（host `{sigil.host}` はカタログに無い → JIN205）"
        members = "\n".join(
            f"- `{_member_signature(sigil.name, m)}`（{m.kind}）" for m in namespace.members
        )
        return f"**sigil `{sigil.name}`**（host `{sigil.host}`・ホスト能力）\n{members}"
    for circle in model.circles:
        if circle.name == sigil.circle:
            for rite in circle.rites:
                if rite.name == sigil.rite:
                    return (
                        f"**sigil `{sigil.name}`**（summon `{sigil.circle}.{sigil.rite}`）\n"
                        f"- `{sigil.name}{_rite_signature(rite)[len(rite.name) :]}`"
                    )
    return (
        f"**sigil `{sigil.name}`**（summon `{sigil.circle}.{sigil.rite}` は見つからない → JIN011）"
    )


def _step_hover(
    model: JinFileV2, circle: Circle, document: Any, pointer: str, rest: list[str]
) -> str | None:
    """ステップの上 / `cast.target` の上の hover。"""
    key = ""
    try:
        node = resolve_pointer(document, pointer)
    except (KeyError, IndexError, ValueError, TypeError):
        return None
    if not (isinstance(node, dict) and "do" in node):
        parent = parent_of(pointer)
        if parent is None:
            return None
        key = rest[-1]
        try:
            node = resolve_pointer(document, parent)
        except (KeyError, IndexError, ValueError, TypeError):
            return None
        if not (isinstance(node, dict) and "do" in node):
            return None
    do = node["do"]
    if do == "cast" and key == "target":
        return _cast_target_hover(model, circle, str(node.get("target", "")))
    summary = {
        "set": lambda: f"`{node.get('target')}` = `{node.get('expr')}`",
        "let": lambda: f"局所 `{node.get('name')}` = `{node.get('expr')}`",
        "cast": lambda: (
            f"`{node.get('target')}({', '.join(node.get('args', []))})`"
            + (f" → `{node['into']}`" if node.get("into") else "")
        ),
        "if": lambda: f"`{node.get('cond')}`",
        "loop": lambda: f"`{node.get('kind')}`",
        "wait": lambda: (
            f"ticks `{node.get('ticks')}`" if node.get("ticks") else f"until `{node.get('until')}`"
        ),
        "emit": lambda: f"→ 陣 `{node.get('circle')}` message `{node.get('message')}`",
        "transfer": lambda: f"→ 陣 `{node.get('circle')}`",
        "return": lambda: f"`{node.get('expr')}`" if node.get("expr") else "",
    }.get(do, lambda: "")()
    return f"**ステップ `{do}`** {summary}".rstrip()


def _cast_target_hover(model: JinFileV2, circle: Circle, target: str) -> str | None:
    parts = target.split(".")
    sigils = {s.name: s for s in circle.sigils}
    if len(parts) == 2:
        sigil = sigils.get(parts[0])
        if isinstance(sigil, SigilHost):
            namespace = abilities.namespace(sigil.host)
            member = namespace.member(parts[1]) if namespace is not None else None
            if member is not None:
                return f"**ホスト能力** `{_member_signature(sigil.name, member)}`（{member.kind}）"
        return None
    name = parts[0]
    for rite in circle.rites:
        if rite.name == name:
            return f"**手順** `{_rite_signature(rite)}`（同じ陣）"
    sigil = sigils.get(name)
    if isinstance(sigil, (SigilSummon, SigilAgent)):
        return _sigil_hover(model, sigil)
    if name in ex.EFFECTS:
        params, _ = ex.EFFECTS[name]
        return f"**効果** `{name}({', '.join(params)})`（list を書き換える）"
    return None


# ---------------------------------------------------------------- completion


def complete(state: DocumentState | None, position: types.Position) -> types.CompletionList:
    context = _context(state, position)
    if context is None:
        return types.CompletionList(is_incomplete=False, items=[])
    model, _lines, pointer, before = context
    return types.CompletionList(is_incomplete=False, items=_items(model, pointer, before))


def _items(model: JinFileV2, pointer: str, before: str) -> list[types.CompletionItem]:
    document = model.model_dump(by_alias=True, mode="json")
    tokens = split_pointer(pointer)
    if not tokens:
        return enum_then_keys(pointer, document)
    # 値を持つオブジェクトと、その中でのキー名（配列要素なら配列のキー）
    owner_pointer = parent_of(pointer) or ""
    key = tokens[-1]
    if key.isdigit() and len(tokens) >= 2:
        owner_pointer = parent_of(owner_pointer) or ""
        key = tokens[-2]
    owner_models = models_at(owner_pointer, document)

    # ---- 式の中: 識別子（スコープ順）/ `.` の後のメンバ / cast の target ------------------
    if any(key in expr_fields(cls) for cls in owner_models):
        analysis = analyze_model(model)
        scope = analysis.scope_at(pointer) or ex.Scope(
            forms=dict(BUILTIN_FORMS), circles=frozenset(c.name for c in model.circles)
        )
        if key == "target" and any(cls is CastStep for cls in owner_models):
            return _cast_targets(model, scope, before)
        return _expression_items(model, scope, before)

    # ---- 型名 -------------------------------------------------------------------
    if key in ("type", "returns"):
        return _type_items(model)

    # ---- 参照名 -----------------------------------------------------------------
    referenced = _reference_items(model, tokens, document)
    if referenced:
        return referenced

    # ---- enum 値（`do` / `kind` / `event` …）→ キー名 ------------------------------
    return enum_then_keys(pointer, document)


def _expression_items(model: JinFileV2, scope: ex.Scope, before: str) -> list[types.CompletionItem]:
    """式の中の識別子。expr.md §3.1 の解決順（局所 → state → sigil → 陣 → 型紙 → 純関数）。"""
    dotted = _DOTTED_PREFIX.search(before)
    if dotted is not None:
        return _members_of(model, scope, dotted.group(1), effects=False)
    items: list[types.CompletionItem] = []
    if scope.exit_mode:
        return _public_items(model, scope, dotted=True)
    if not scope.constant:
        items.extend(
            item(name, types.CompletionItemKind.Variable, f"局所 {type_}")
            for name, type_ in scope.locals.items()
        )
        items.extend(
            item(name, types.CompletionItemKind.Field, f"state {type_}")
            for name, type_ in scope.state.items()
        )
        for name, sigil in scope.sigils.items():
            if sigil[0] == "host":
                items.extend(_namespace_items(name, sigil[1], effects=False, dotted=True))
        items.extend(_public_items(model, scope, dotted=True))
    items.extend(_form_items(scope))
    items.extend(_pure_function_items())
    return dedupe(items)


def _members_of(
    model: JinFileV2, scope: ex.Scope, base: str, *, effects: bool
) -> list[types.CompletionItem]:
    """`base.` の後に置けるメンバ（名前空間のメンバ / 他の陣の公開 state / 型紙の欄）。"""
    sigil = scope.sigils.get(base)
    if sigil is not None and sigil[0] == "host":
        return _namespace_items(base, sigil[1], effects=effects, dotted=False)
    if base in scope.circles and base != scope.circle:
        return [
            item(key, types.CompletionItemKind.Field, f"{base} の公開 state {type_}")
            for key, type_ in scope.public.get(base, {}).items()
        ]
    type_ = scope.locals.get(base, scope.state.get(base))
    if type_ is not None and type_ in scope.forms:
        return [
            item(field, types.CompletionItemKind.Field, f"{type_} の欄 {field_type}")
            for field, field_type in scope.forms[type_].items()
        ]
    return []


def _namespace_items(
    sigil_name: str, host: str, *, effects: bool, dotted: bool
) -> list[types.CompletionItem]:
    """名前空間のメンバ。式の中では戻り値を持つものだけ（expr.md §3.3）、`cast` では全部。"""
    namespace = abilities.namespace(host)
    if namespace is None:
        return []
    found: list[types.CompletionItem] = []
    for member in namespace.members:
        if not effects and member.returns is None:
            continue
        label = f"{sigil_name}.{member.name}" if dotted else member.name
        found.append(
            item(label, types.CompletionItemKind.Function, _member_signature(sigil_name, member))
        )
    return found


def _public_items(model: JinFileV2, scope: ex.Scope, *, dotted: bool) -> list[types.CompletionItem]:
    found: list[types.CompletionItem] = []
    for circle in model.circles:
        if circle.name == scope.circle:
            continue
        for key, type_ in scope.public.get(circle.name, {}).items():
            label = f"{circle.name}.{key}" if dotted else key
            found.append(
                item(label, types.CompletionItemKind.Field, f"{circle.name} の公開 state {type_}")
            )
    return found


def _form_items(scope: ex.Scope) -> list[types.CompletionItem]:
    return [
        item(
            name,
            types.CompletionItemKind.Struct,
            "型紙 " + name + "{" + ", ".join(f"{f}: {t}" for f, t in fields.items()) + "}",
        )
        for name, fields in scope.forms.items()
    ]


def _pure_function_items() -> list[types.CompletionItem]:
    found = [
        item(name, types.CompletionItemKind.Function, f"{name}({', '.join(params)}) → {returns}")
        for name, (params, returns) in ex.PURE_FUNCTIONS.items()
    ]
    special = {
        "len": "len(list | str) → num",
        "str": "str(num | bool | str) → str",
        "contains": "contains(list<T>, T) → bool",
    }
    found.extend(
        item(name, types.CompletionItemKind.Function, special.get(name, name))
        for name in ex.SPECIAL_PURE_FUNCTIONS
    )
    return found


def _cast_targets(model: JinFileV2, scope: ex.Scope, before: str) -> list[types.CompletionItem]:
    """`cast.target`: 同じ陣の手順 / 道具環（summon はそのまま、host は `名前.メンバ`）/ 効果。"""
    dotted = _DOTTED_PREFIX.search(before)
    if dotted is not None:
        return _members_of(model, scope, dotted.group(1), effects=True)
    items: list[types.CompletionItem] = []
    for circle in model.circles:
        if circle.name == scope.circle:
            items.extend(
                item(rite.name, types.CompletionItemKind.Method, "手順 " + _rite_signature(rite))
                for rite in circle.rites
            )
    for name, sigil in scope.sigils.items():
        if sigil[0] == "host":
            items.extend(_namespace_items(name, sigil[1], effects=True, dotted=True))
        else:
            items.append(
                item(name, types.CompletionItemKind.Method, f"summon {sigil[1]}.{sigil[2]}")
            )
    items.extend(
        item(name, types.CompletionItemKind.Function, f"効果 {name}({', '.join(params)})")
        for name, (params, _returns) in ex.EFFECTS.items()
    )
    return dedupe(items)


def _type_items(model: JinFileV2) -> list[types.CompletionItem]:
    """型名: 基本型 / 型紙（組み込み `Pointer` を含む）/ それぞれの `list<…>`。"""
    names = [*PRIMITIVE_TYPES, *BUILTIN_FORMS, *(form.name for form in model.forms)]
    items = [
        item(
            name,
            types.CompletionItemKind.TypeParameter,
            "基本型" if name in PRIMITIVE_TYPES else "型紙",
        )
        for name in names
    ]
    items.extend(
        item(f"list<{name}>", types.CompletionItemKind.TypeParameter, "list") for name in names
    )
    return dedupe(items)


def _reference_items(
    model: JinFileV2, tokens: list[str], document: Any
) -> list[types.CompletionItem]:
    """名前を書く位置の候補（陣名 / 手順名 / 名前空間名）。該当しなければ空。"""
    circles = [item(c.name, types.CompletionItemKind.Class, "陣") for c in model.circles]
    if tokens == ["root"]:
        return circles
    found = _circle_at(model, tokens)
    if found is None:
        return []
    _index, circle = found
    rest = tokens[2:]
    own_rites = [
        item(rite.name, types.CompletionItemKind.Method, "手順 " + _rite_signature(rite))
        for rite in circle.rites
    ]
    if rest == ["core"]:
        return own_rites
    if rest[:1] == ["delegate"] or rest[:2] == ["flow", "steps"]:
        return circles
    if rest[:2] == ["boundary", "on"] and rest[3:] == ["rite"]:
        return own_rites
    if rest[:1] == ["sigils"] and len(rest) == 3:
        if rest[2] == "host":
            return [
                item(
                    ns.name,
                    types.CompletionItemKind.Module,
                    f"ホスト能力（{len(ns.members)} メンバ）",
                )
                for ns in abilities.NAMESPACES
            ]
        if rest[2] == "circle":
            return circles
        if rest[2] == "rite":
            sigil = resolve_pointer(document, "".join(f"/{t}" for t in tokens[:-1]))
            target = sigil.get("circle", "") if isinstance(sigil, dict) else ""
            return [
                item(name, types.CompletionItemKind.Method, f"{target} の手順")
                for name in _rite_names(model, target)
            ]
    if rest[:1] == ["rites"] and rest[-1:] == ["circle"]:
        # emit / transfer の circle
        return circles
    return []


__all__ = ["complete", "hover"]
