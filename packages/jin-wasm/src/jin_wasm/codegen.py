"""`JinFileV2` → JIL（`game.lua` の生成部）と `game.manifest.json`（jil.md §3 / §4、runtime.md §9）。

## 形

`game.lua` = ヘッダ + プレリュード（`prelude.lua` そのまま）+ 生成部 + `return { boot = boot, tick = tick }`。
生成部が定義するものはプレリュード先頭のコメントと 1:1（`CIRCLES` / `R` / `JF` / `DEBUG` / `ROOT` / `FPS`）。

## 名前の写像（jil.md §3）

`.jin` の名前は Lua の識別子に**埋め込まない**。陣は `S[i]` / `P[i]` / `R[i]`（`i` は `circles` の
添字 + 1。Lua のテーブルは 1 始まり）、手順は `R[i][j]`（`j` は `rites` の添字 + 1）、state は
`k_<j>`（0 始まり）、型紙の欄は `f_<j>`（0 始まり）、局所は `l_<n>`（手順ごとの通し番号）。
名前は文字列としてトレース行（`name`）と `CIRCLES[i].name` にだけ載る。JSON Pointer は 0 始まりのまま。

## 数値と文字列

`num` は常に float で出す（`160.0` / `1.05` / `1e+20`。Python の `repr(float)` は必ず `.` か `e` を含む）。
文字列は `lua_string` で Lua のリテラルにする（`"` / `\\` / 制御文字を `\\ddd` に。非 ASCII は
UTF-8 のまま）。`.jin` 由来の文字列**値**が Lua の式へ流れる経路はこの 1 つだけで、識別子として
埋め込むものは無い（名前は添字に写像する）。ヘッダの `source:` も同じ関数を通す。

    guard: _header -> lua_string(source_name)
    guard: lua_string -> text.replace

## トレース（DEBUG のときだけ生成する）

`set`（state への代入だけ）/ `cast`（ホスト能力・summon・効果）/ `rite`（起動直前）/ `emit` /
`transfer` / `finish` の行を該当ステップに挿む。`enter` / `exit` / `event` / `wait` / `assert` /
`error` / `frame` はプレリュードが出す。リリースビルドは 1 行も生成せず、**表示リストは同じ**
（`packages/jin-wasm/tests/test_codegen.py` が固定）。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from jin_core.v2 import abilities
from jin_core.v2 import expr as ex
from jin_core.v2.model import (
    BreakStep,
    CastStep,
    Circle,
    EmitStep,
    FinishStep,
    IfStep,
    JinFileV2,
    LetStep,
    LoopStep,
    ReturnStep,
    Rite,
    SetStep,
    SigilHost,
    Step,
    TransferStep,
    WaitStep,
    parse_type,
)
from jin_core.v2.semantic import BUILTIN_FORMS, typed_nodes

from jin_wasm.jil import JIL_VERSION
from jin_wasm.prelude import prelude_source


class CodegenError(Exception):
    """生成できない（診断に error が残っている、など）。利用者向けの文で伝える。"""


@dataclass(frozen=True, slots=True)
class GeneratedGame:
    """`jin build` / `jin run` が受け取る生成物。"""

    lua: str
    manifest: dict[str, Any]
    debug: bool


# ---------------------------------------------------------------- リテラル


def lua_string(text: str) -> str:
    """Lua の文字列リテラル。

    guard: lua_string -> text.replace
    """
    out = text.replace("\\", "\\\\").replace('"', '\\"')
    escaped: list[str] = []
    for ch in out:
        code = ord(ch)
        if code < 0x20 or code == 0x7F:
            escaped.append(f"\\{code:03d}")
        else:
            escaped.append(ch)
    return '"' + "".join(escaped) + '"'


def lua_number(value: float) -> str:
    """float のリテラル。整数値でも `160.0` の形（整数サブタイプを作らない・jil.md §2）。"""
    text = repr(float(value))
    if "inf" in text:
        return "(1.0 / 0.0)" if value > 0 else "(-1.0 / 0.0)"
    if "nan" in text:
        return "(0.0 / 0.0)"
    if "." not in text and "e" not in text:
        text += ".0"
    return text


def _lua_bool(value: bool) -> str:
    return "true" if value else "false"


# ---------------------------------------------------------------- 文脈


@dataclass(slots=True)
class _FormInfo:
    index: int  # JF の添字（Pointer = 0、forms は 1 始まり）
    fields: dict[str, tuple[int, str]]  # 欄名 → (添字, 型)


@dataclass(slots=True)
class _CircleInfo:
    index: int  # Lua の添字（1 始まり）
    pointer_index: int  # JSON Pointer の添字（0 始まり）
    circle: Circle
    states: dict[str, tuple[int, str]]  # state 名 → (添字, 型)
    rites: dict[str, int]  # 手順名 → Lua の添字（1 始まり）
    sigils: dict[str, tuple[str, ...]]  # ("host", ns) | ("summon", circle, rite)
    waits: dict[str, bool] = field(default_factory=dict)


@dataclass(slots=True)
class _RiteCtx:
    info: _CircleInfo
    rite: Rite
    rite_index: int
    locals: dict[str, str]  # 局所名 → l_n
    next_local: int = 0
    next_temp: int = 0
    rite_row: str | None = None  # DEBUG のときの rite 行の Lua 変数名

    def new_local(self, name: str) -> str:
        lua = f"l_{self.next_local}"
        self.next_local += 1
        self.locals[name] = lua
        return lua

    def temp(self, stem: str) -> str:
        self.next_temp += 1
        return f"{stem}_{self.next_temp}"


class _Generator:
    def __init__(self, model: JinFileV2, *, debug: bool) -> None:
        self.model = model
        self.debug = debug
        nodes, diagnostics = typed_nodes(model)
        errors = [d for d in diagnostics if d.severity == "error"]
        if errors:
            first = errors[0]
            raise CodegenError(
                f"診断に error があるため生成できません（{first.code} {first.pointer}: {first.message}）。"
                "先に jin check を通してください"
            )
        self.nodes = nodes
        self.forms: dict[str, _FormInfo] = {
            "Pointer": _FormInfo(
                0, {n: (j, t) for j, (n, t) in enumerate(BUILTIN_FORMS["Pointer"].items())}
            )
        }
        for k, form in enumerate(model.forms, start=1):
            self.forms[form.name] = _FormInfo(
                k, {f.name: (j, f.type) for j, f in enumerate(form.fields)}
            )
        self.circles: dict[str, _CircleInfo] = {}
        for i, circle in enumerate(model.circles):
            sigils: dict[str, tuple[str, ...]] = {}
            for sigil in circle.sigils:
                if isinstance(sigil, SigilHost):
                    sigils[sigil.name] = ("host", sigil.host)
                else:
                    sigils[sigil.name] = ("summon", sigil.circle, sigil.rite)
            self.circles[circle.name] = _CircleInfo(
                index=i + 1,
                pointer_index=i,
                circle=circle,
                states={s.name: (j, s.type) for j, s in enumerate(circle.state)},
                rites={r.name: j + 1 for j, r in enumerate(circle.rites)},
                sigils=sigils,
            )
        for info in self.circles.values():
            info.waits = _waits(info.circle)
        self.lines: list[str] = []

    # ---------------------------------------------------------------- 出力
    def out(self, text: str, indent: int = 0) -> None:
        self.lines.append("  " * indent + text)

    def node(self, pointer: str) -> ex.Node:
        node = self.nodes.get(pointer)
        if node is None:
            raise CodegenError(f"式 {pointer} の型注記がありません（jin check を通してください）")
        return node

    # ---------------------------------------------------------------- 直列化
    def serializer(self, type_text: str | None) -> str:
        """型に対応する JSON 直列化の Lua 式（`JV` / `JF[k]` / `JL(...)`）。"""
        if type_text is None or type_text == ex.LIST_OF_UNKNOWN:
            return "JV"
        head, inner = parse_type(type_text)
        if head == "list":
            return f"JL({self.serializer(inner)})"
        if head in self.forms:
            return f"JF[{self.forms[head].index}]"
        return "JV"

    def emit_form_serializers(self) -> None:
        for name, info in self.forms.items():
            parts: list[str] = []
            for field_name, (j, type_text) in info.fields.items():
                parts.append(f"'{_json_key(field_name)}' .. {self.serializer(type_text)}(v.f_{j})")
            body = " .. ',' .. ".join(parts) if parts else "''"
            self.out(f"JF[{info.index}] = function(v) return '{{' .. {body} .. '}}' end  -- {name}")
            if self.debug:
                self.out(self.form_reader(name, info))

    def reader(self, type_text: str) -> str:
        """型に対応する resume の読み手の Lua 式（`RN` / `RB` / `RSTR` / `JR[k]` / `RL(...)`）。

        JSON（ホストのテーブル）を型どおりの Lua の値にし、合わなければ nil を返す関数。
        """
        head, inner = parse_type(type_text)
        if head == "list":
            assert inner is not None
            return f"RL({self.reader(inner)})"
        if head in self.forms:
            return f"JR[{self.forms[head].index}]"
        return {"num": "RN", "bool": "RB", "str": "RSTR"}.get(head, "RN")

    def form_reader(self, name: str, info: _FormInfo) -> str:
        """`JR[k]`: 型紙 k の読み手（欄が 1 つでも合わなければ nil）。debug だけに出す。"""
        reads = " ".join(
            f"local f_{j} = {self.reader(type_text)}(v[{lua_string(field_name)}])"
            for field_name, (j, type_text) in info.fields.items()
        )
        misses = " or ".join(f"f_{j} == nil" for _, (j, _) in info.fields.items()) or "false"
        fields = ", ".join(f"f_{j} = f_{j}" for _, (j, _) in info.fields.items())
        return (
            f"JR[{info.index}] = function(v) if RREC(v) == nil then return nil end {reads} "
            f"if {misses} then return nil end return {{ {fields} }} end  -- {name}"
        ).replace("  if false then", " if false then")

    # ---------------------------------------------------------------- 式
    def expr(self, node: ex.Node, ctx: _RiteCtx | None, info: _CircleInfo | None) -> str:
        if isinstance(node, ex.Number):
            return lua_number(node.value)
        if isinstance(node, ex.String):
            return lua_string(node.value)
        if isinstance(node, ex.Boolean):
            return _lua_bool(node.value)
        if isinstance(node, ex.Name):
            return self.name(node.name, ctx, info)
        if isinstance(node, ex.Unary):
            operand = self.expr(node.operand, ctx, info)
            return f"(-{operand})" if node.op == "-" else f"(not {operand})"
        if isinstance(node, ex.Binary):
            left = self.expr(node.left, ctx, info)
            right = self.expr(node.right, ctx, info)
            return f"({left} {_BINARY[node.op]} {right})"
        if isinstance(node, ex.FieldAccess):
            return self.field(node, ctx, info)
        if isinstance(node, ex.Index):
            return f"AT({self.expr(node.obj, ctx, info)}, {self.expr(node.index, ctx, info)})"
        if isinstance(node, ex.Call):
            return self.call(node, ctx, info)
        if isinstance(node, ex.Construct):
            form = self.forms[node.form]
            values = {name: value for name, _, value in node.fields}
            parts = [
                f"f_{j} = {self.expr(values[field_name], ctx, info)}"
                for field_name, (j, _) in form.fields.items()
            ]
            return "{ " + ", ".join(parts) + " }"
        if isinstance(node, ex.ListLiteral):
            return "{ " + ", ".join(self.expr(item, ctx, info) for item in node.items) + " }"
        raise CodegenError(f"式の形 {type(node).__name__} は生成できません")  # pragma: no cover

    def name(self, name: str, ctx: _RiteCtx | None, info: _CircleInfo | None) -> str:
        if ctx is not None and name in ctx.locals:
            return ctx.locals[name]
        if info is not None and name in info.states:
            j, _ = info.states[name]
            return f"S[{info.index}].k_{j}"
        raise CodegenError(f"識別子 '{name}' を解決できません")

    def field(self, node: ex.FieldAccess, ctx: _RiteCtx | None, info: _CircleInfo | None) -> str:
        base = node.obj
        if isinstance(base, ex.Name):
            is_value = (ctx is not None and base.name in ctx.locals) or (
                info is not None and base.name in info.states
            )
            if not is_value and base.name in self.circles:
                other = self.circles[base.name]
                j, _ = other.states[node.name]
                return f"P[{other.index}].k_{j}"
        obj_type = base.type
        if obj_type is None or obj_type not in self.forms:
            raise CodegenError(f"'.{node.name}' の左辺の型紙が分かりません（{obj_type}）")
        j, _ = self.forms[obj_type].fields[node.name]
        return f"{self.expr(base, ctx, info)}.f_{j}"

    def call(self, node: ex.Call, ctx: _RiteCtx | None, info: _CircleInfo | None) -> str:
        args = ", ".join(self.expr(a, ctx, info) for a in node.args)
        callee = node.callee
        if isinstance(callee, ex.Name):
            return f"F.{callee.name}({args})"
        if isinstance(callee, ex.FieldAccess) and isinstance(callee.obj, ex.Name):
            sigil = info.sigils.get(callee.obj.name) if info is not None else None
            if sigil is not None and sigil[0] == "host":
                return f"H.{sigil[1]}.{callee.name}({args})"
        raise CodegenError("呼び出せるのは純関数と '名前空間.メンバ' だけです")

    # ---------------------------------------------------------------- 代入先
    def assign(self, target: ex.Node, value: str, ctx: _RiteCtx, pointer: str, indent: int) -> None:
        """`target = value` を出し、根が state なら set 行（DEBUG）を続ける。"""
        info = ctx.info
        if isinstance(target, ex.Index):
            obj = self.expr(target.obj, ctx, info)
            idx = self.expr(target.index, ctx, info)
            self.out(f"SETAT({obj}, {idx}, {value})", indent)
        else:
            self.out(f"{self.expr(target, ctx, info)} = {value}", indent)
        root = ex.place_root(target)
        if (
            self.debug
            and root is not None
            and root.name in info.states
            and root.name not in ctx.locals
        ):
            j, type_text = info.states[root.name]
            self.out(
                f"TS({info.index}, {lua_string(root.name)}, {lua_string(pointer)}, "
                f"{self.serializer(type_text)}(S[{info.index}].k_{j}))",
                indent,
            )

    # ---------------------------------------------------------------- ステップ
    def steps(self, steps: list[Step], pointer: str, ctx: _RiteCtx, indent: int) -> None:
        for k, step in enumerate(steps):
            self.step(step, f"{pointer}/{k}", ctx, indent)

    def step(self, step: Step, sp: str, ctx: _RiteCtx, indent: int) -> None:
        info = ctx.info
        ci = info.index
        if isinstance(step, SetStep):
            value = self.expr(self.node(f"{sp}/expr"), ctx, info)
            self.assign(self.node(f"{sp}/target"), value, ctx, sp, indent)
            return
        if isinstance(step, LetStep):
            value = self.expr(self.node(f"{sp}/expr"), ctx, info)
            lua = ctx.new_local(step.name)
            self.out(f"local {lua} = {value}", indent)
            return
        if isinstance(step, CastStep):
            self.cast(step, sp, ctx, indent)
            return
        if isinstance(step, IfStep):
            cond = self.expr(self.node(f"{sp}/cond"), ctx, info)
            self.out(f"if {cond} then", indent)
            self.steps(step.then, f"{sp}/then", ctx, indent + 1)
            if step.else_:
                self.out("else", indent)
                self.steps(step.else_, f"{sp}/else", ctx, indent + 1)
            self.out("end", indent)
            return
        if isinstance(step, LoopStep):
            self.loop(step, sp, ctx, indent)
            return
        if isinstance(step, BreakStep):
            self.out("do break end", indent)
            return
        if isinstance(step, WaitStep):
            if step.ticks is not None:
                ticks = self.expr(self.node(f"{sp}/ticks"), ctx, info)
                self.out(f"WAIT_TICKS({ticks}, {lua_string(sp)})", indent)
            else:
                until = self.expr(self.node(f"{sp}/until"), ctx, info)
                self.out(f"WAIT_UNTIL(function() return {until} end, {lua_string(sp)})", indent)
            return
        if isinstance(step, EmitStep):
            self.emit_step(step, sp, ctx, indent)
            return
        if isinstance(step, ReturnStep):
            if step.expr is None:
                self.out("do return end", indent)
                return
            value = self.expr(self.node(f"{sp}/expr"), ctx, info)
            if self.debug and ctx.rite_row is not None:
                tmp = ctx.temp("r")
                self.out(f"local {tmp} = {value}", indent)
                self.out(
                    f"TRET({ctx.rite_row}, {self.serializer(ctx.rite.returns)}({tmp}))", indent
                )
                self.out(f"do return {tmp} end", indent)
            else:
                self.out(f"do return {value} end", indent)
            return
        if isinstance(step, FinishStep):
            if self.debug:
                self.out(f'T("finish", {ci}, nil, {lua_string(sp)}, nil, nil)', indent)
            self.out(f"FINISH({ci})", indent)
            self.out("do return end", indent)
            return
        if isinstance(step, TransferStep):
            target = self.circles[step.circle]
            if self.debug:
                self.out(
                    f'T("transfer", {ci}, {lua_string(step.circle)}, {lua_string(sp)}, '
                    f"{lua_string(_json_string(step.circle))}, nil)",
                    indent,
                )
            self.out(f"TRANSFER({ci}, {target.index})", indent)
            self.out("do return end", indent)
            return
        raise CodegenError(type(step).__name__)  # pragma: no cover

    def loop(self, step: LoopStep, sp: str, ctx: _RiteCtx, indent: int) -> None:
        info = ctx.info
        if step.kind == "while":
            cond = self.expr(self.node(f"{sp}/cond"), ctx, info)
            self.out(f"while {cond} do", indent)
            self.steps(step.steps, f"{sp}/steps", ctx, indent + 1)
            self.out("end", indent)
            return
        if step.kind == "each":
            source = self.expr(self.node(f"{sp}/in"), ctx, info)
            list_var = ctx.temp("list")
            idx_var = ctx.temp("i")
            self.out("do", indent)
            self.out(f"local {list_var} = {source}", indent + 1)
            self.out(f"for {idx_var} = 1, #{list_var} do", indent + 1)
            item = ctx.new_local(step.name or "")
            self.out(f"local {item} = {list_var}[{idx_var}]", indent + 2)
            self.steps(step.steps, f"{sp}/steps", ctx, indent + 2)
            self.out("end", indent + 1)
            self.out("end", indent)
            return
        times = self.expr(self.node(f"{sp}/times"), ctx, info)
        count_var = ctx.temp("n")
        idx_var = ctx.temp("i")
        self.out("do", indent)
        self.out(f"local {count_var} = math.floor({times})", indent + 1)
        self.out(f"for {idx_var} = 0, {count_var} - 1 do", indent + 1)
        if step.name is not None:
            item = ctx.new_local(step.name)
            self.out(f"local {item} = {idx_var} + 0.0", indent + 2)
        self.steps(step.steps, f"{sp}/steps", ctx, indent + 2)
        self.out("end", indent + 1)
        self.out("end", indent)

    def cast(self, step: CastStep, sp: str, ctx: _RiteCtx, indent: int) -> None:
        info = ctx.info
        ci = info.index
        arg_nodes = [self.node(f"{sp}/args/{k}") for k in range(len(step.args))]
        parts = step.target.split(".")
        returns: str | None = None
        callee: str
        kind: str
        if len(parts) == 1 and parts[0] in info.rites:
            rite = info.circle.rites[info.rites[parts[0]] - 1]
            callee = f"R[{ci}][{info.rites[parts[0]]}]"
            returns = rite.returns
            kind = "rite"
        elif len(parts) == 1 and parts[0] in info.sigils:
            _, target_circle, target_rite = info.sigils[parts[0]]
            other = self.circles[target_circle]
            rite = other.circle.rites[other.rites[target_rite] - 1]
            callee = f"R[{other.index}][{other.rites[target_rite]}]"
            returns = rite.returns
            kind = "summon"
        elif len(parts) == 1:
            callee = f"E.{parts[0]}"
            kind = "effect"
        else:
            ns = info.sigils[parts[0]][1]
            member = abilities.namespace(ns).member(parts[1])  # type: ignore[union-attr]
            callee = f"H.{ns}.{parts[1]}"
            returns = member.returns  # type: ignore[union-attr]
            kind = "host"
        into = self.node(f"{sp}/into") if step.into is not None else None

        if not self.debug:
            args = ", ".join(self.expr(a, ctx, info) for a in arg_nodes)
            call = f"{callee}({args})"
            if into is not None:
                tmp = ctx.temp("r")
                self.out(f"local {tmp} = {call}", indent)
                if kind == "rite":
                    self.out(f"if STOP({ci}) then return end", indent)
                self.assign(into, tmp, ctx, sp, indent)
            else:
                self.out(call, indent)
                if kind == "rite":
                    self.out(f"if STOP({ci}) then return end", indent)
            return

        # DEBUG: 引数を一度だけ評価して局所に置き、cast 行を**呼び出しの前に**積む
        # （list の効果で引数が変わる前の値を載せる。error 行の pointer もこのステップになる）。
        # 戻り値は呼び出しの後に TRET で埋める（行は tick の終わりまで表なので書き換えられる）。
        self.out("do", indent)
        arg_vars = [ctx.temp("a") for _ in arg_nodes]
        if arg_vars:
            values = ", ".join(self.expr(a, ctx, info) for a in arg_nodes)
            self.out(f"local {', '.join(arg_vars)} = {values}", indent + 1)
        args_json = _json_array(
            [f"{self.serializer(a.type)}({v})" for a, v in zip(arg_nodes, arg_vars, strict=True)]
        )
        call = f"{callee}({', '.join(arg_vars)})"
        row_var: str | None = None
        if kind != "rite":
            row_var = ctx.temp("c")
            self.out(
                f'local {row_var} = T("cast", {ci}, {lua_string(step.target)}, {lua_string(sp)}, '
                f"{args_json}, nil)",
                indent + 1,
            )
        result_var: str | None = None
        if returns is not None:
            result_var = ctx.temp("r")
            self.out(f"local {result_var} = {call}", indent + 1)
        else:
            self.out(call, indent + 1)
        if kind == "rite":
            self.out(f"if STOP({ci}) then return end", indent + 1)
        elif result_var is not None:
            self.out(f"TRET({row_var}, {self.serializer(returns)}({result_var}))", indent + 1)
        if into is not None and result_var is not None:
            self.assign(into, result_var, ctx, sp, indent + 1)
        self.out("end", indent)

    def emit_step(self, step: EmitStep, sp: str, ctx: _RiteCtx, indent: int) -> None:
        info = ctx.info
        ci = info.index
        target = self.circles[step.circle]
        arg_nodes = [self.node(f"{sp}/args/{k}") for k in range(len(step.args))]
        if not self.debug:
            args = ", ".join(self.expr(a, ctx, info) for a in arg_nodes)
            self.out(f"EMIT({target.index}, {lua_string(step.message)}, {{ {args} }}, nil)", indent)
            return
        self.out("do", indent)
        arg_vars = [ctx.temp("a") for _ in arg_nodes]
        if arg_vars:
            values = ", ".join(self.expr(a, ctx, info) for a in arg_nodes)
            self.out(f"local {', '.join(arg_vars)} = {values}", indent + 1)
        args_json = _json_array(
            [f"{self.serializer(a.type)}({v})" for a, v in zip(arg_nodes, arg_vars, strict=True)]
        )
        self.out(
            f"EMIT({target.index}, {lua_string(step.message)}, {{ {', '.join(arg_vars)} }}, "
            f"{{ ci = {ci}, pointer = {lua_string(sp)}, args_json = {args_json} }})",
            indent + 1,
        )
        self.out("end", indent)

    # ---------------------------------------------------------------- 手順と陣
    def emit_rite(self, info: _CircleInfo, rite: Rite, j: int) -> None:
        ctx = _RiteCtx(info=info, rite=rite, rite_index=j, locals={})
        params = [ctx.new_local(p.name) for p in rite.params]
        pointer = f"/circles/{info.pointer_index}/rites/{j - 1}"
        self.out(f"R[{info.index}][{j}] = function({', '.join(params)})  -- {rite.name}")
        if self.debug:
            args_json = _json_array(
                [
                    f"{self.serializer(p.type)}({v})"
                    for p, v in zip(rite.params, params, strict=True)
                ]
            )
            ctx.rite_row = "rr_"
            self.out(
                f"local rr_ = TR({info.index}, {lua_string(rite.name)}, {lua_string(pointer)}, "
                f"{args_json})",
                1,
            )
        self.steps(rite.steps, f"{pointer}/steps", ctx, 1)
        self.out("end")

    def emit_circle(self, info: _CircleInfo) -> None:
        circle = info.circle
        i = info.index
        pi = info.pointer_index
        if circle.flow is not None:
            children = ", ".join(str(self.circles[c].index) for c in circle.flow.steps)
            exit_text = "nil"
            if circle.flow.exit is not None:
                exit_expr = self.expr(self.node(f"/circles/{pi}/flow/exit"), None, None)
                exit_text = f"function() return {exit_expr} end"
            self.out(
                f"CIRCLES[{i}] = {{ name = {lua_string(circle.name)}, flow = "
                f"{lua_string(circle.flow.kind)}, children = {{ {children} }}, exit = {exit_text} }}"
            )
            return
        self.out(f"CIRCLES[{i}] = {{")
        self.out(f"name = {lua_string(circle.name)},", 1)
        inits = ", ".join(
            f"k_{j} = {self.expr(self.node(f'/circles/{pi}/state/{j}/init'), None, None)}"
            for j, _ in enumerate(circle.state)
        )
        self.out(f"init = function() return {{ {inits} }} end,", 1)
        outs = [(j, s) for j, s in enumerate(circle.state) if s.out]
        if outs:
            body = " ".join(f"P[{i}].k_{j} = S[{i}].k_{j}" for j, _ in outs)
            self.out(f"publish = function() {body} end,", 1)
            pub = " .. ',' .. ".join(
                f"'{_json_key(f'{circle.name}.{s.name}')}' .. {self.serializer(s.type)}(P[{i}].k_{j})"
                for j, s in outs
            )
            self.out(f"pub = function() return {pub} end,", 1)
        if self.debug:
            if circle.state:
                dump = " .. ',' .. ".join(
                    f"'{_json_key(s.name)}' .. {self.serializer(s.type)}(S[{i}].k_{j})"
                    for j, s in enumerate(circle.state)
                )
                self.out(f"dump = function() return '{{' .. {dump} .. '}}' end,", 1)
            else:
                self.out("dump = function() return '{}' end,", 1)
            # 状態を保った差し替え（runtime.md §1 の manifest.resume・設計書 §11 #42）: 名前で引き、
            # 形が合う欄だけを写す。公開 state の確定値 P は別に写す（#43）。
            restores = " ".join(
                f"do local x = {self.reader(s.type)}(v[{lua_string(s.name)}]) "
                f"if x ~= nil then S[{i}].k_{j} = x end end"
                for j, s in enumerate(circle.state)
            )
            self.out(f"restore = function(v) {restores} end,".replace("(v)  end", "(v) end"), 1)
            prestores = " ".join(
                f"do local x = {self.reader(s.type)}(v[{lua_string(s.name)}]) "
                f"if x ~= nil then P[{i}].k_{j} = x end end"
                for j, s in outs
            )
            self.out(f"prestore = function(v) {prestores} end,".replace("(v)  end", "(v) end"), 1)
            if outs:
                pdump = " .. ',' .. ".join(
                    f"'{_json_key(s.name)}' .. {self.serializer(s.type)}(P[{i}].k_{j})"
                    for j, s in outs
                )
                self.out(f"pdump = function() return '{{' .. {pdump} .. '}}' end,", 1)
            else:
                self.out("pdump = function() return '{}' end,", 1)
        core_index = info.rites[circle.core or ""]
        self.out(
            f"core = R[{i}][{core_index}], core_waits = {_lua_bool(info.waits[circle.core or ''])},",
            1,
        )
        if circle.boundary is not None and circle.boundary.on:
            handlers = ", ".join(
                f"{on.event} = R[{i}][{info.rites[on.rite]}]" for on in circle.boundary.on
            )
            waits = ", ".join(
                f"{on.event} = {_lua_bool(info.waits[on.rite])}" for on in circle.boundary.on
            )
            pointers = ", ".join(
                f"{on.event} = {lua_string(f'/circles/{pi}/boundary/on/{k}')}"
                for k, on in enumerate(circle.boundary.on)
            )
            self.out(f"on = {{ {handlers} }},", 1)
            self.out(f"on_waits = {{ {waits} }},", 1)
            self.out(f"on_ptr = {{ {pointers} }},", 1)
        if self.debug and circle.boundary is not None and circle.boundary.guards:
            self.out("guards = {", 1)
            for k, guard in enumerate(circle.boundary.guards):
                pointer = f"/circles/{pi}/boundary/guards/{k}"
                cond = self.expr(self.node(f"{pointer}/assert"), None, info)
                message = lua_string(guard.message) if guard.message is not None else "nil"
                self.out(
                    f"{{ fn = function() return {cond} end, message = {message}, "
                    f"pointer = {lua_string(pointer)} }},",
                    2,
                )
            self.out("},", 1)
        self.out("}")

    # ---------------------------------------------------------------- 全体
    def program(self) -> str:
        model = self.model
        self.out(f"DEBUG = {_lua_bool(self.debug)}")
        self.out(f"ROOT = {self.circles[model.root].index}")
        self.out(f"FPS = {lua_number(model.stage.fps)}")
        self.emit_form_serializers()
        for info in self.circles.values():
            if info.circle.core is None:
                continue
            self.out(f"R[{info.index}] = {{}}")
        for info in self.circles.values():
            if info.circle.core is None:
                continue
            self.out(f"-- circle {info.pointer_index}: {info.circle.name}")
            for j, rite in enumerate(info.circle.rites, start=1):
                self.emit_rite(info, rite, j)
        for info in self.circles.values():
            self.emit_circle(info)
        return "\n".join(self.lines) + "\n"


# ---------------------------------------------------------------- 補助


_BINARY = {
    "and": "and",
    "or": "or",
    "==": "==",
    "!=": "~=",
    "<": "<",
    "<=": "<=",
    ">": ">",
    ">=": ">=",
    "+": "+",
    "-": "-",
    "*": "*",
    "/": "/",
    "%": "%",
    "++": "..",
}


def _json_key(name: str) -> str:
    """JSON のキー `"name":` を Lua の**単引用**リテラルの中に置ける形にする（名前は識別子の文法）。"""
    return f'"{name}":'


def _json_string(text: str) -> str:
    """名前（識別子の文法なのでエスケープ不要）を JSON 文字列にする。"""
    return f'"{text}"'


def _json_array(items: list[str]) -> str:
    """Lua 式の列を JSON 配列の文字列にする Lua 式。"""
    if not items:
        return "'[]'"
    return "'[' .. " + " .. ',' .. ".join(items) + " .. ']'"


def _waits(circle: Circle) -> dict[str, bool]:
    """手順ごとに「wait を含む（自陣の手順への cast を辿って）」か。semantic の JIN212 と同じ閉包。"""
    direct: dict[str, bool] = {}
    casts: dict[str, set[str]] = {}
    names = {r.name for r in circle.rites}
    for rite in circle.rites:
        direct[rite.name] = False
        casts[rite.name] = set()
        for step in _walk(rite.steps):
            if isinstance(step, WaitStep):
                direct[rite.name] = True
            elif isinstance(step, CastStep) and step.target in names:
                casts[rite.name].add(step.target)
    changed = True
    while changed:
        changed = False
        for name in names:
            if not direct[name] and any(direct[c] for c in casts[name]):
                direct[name] = True
                changed = True
    return direct


def _walk(steps: list[Step]):
    for step in steps:
        yield step
        if isinstance(step, IfStep):
            yield from _walk(step.then)
            yield from _walk(step.else_)
        elif isinstance(step, LoopStep):
            yield from _walk(step.steps)


def _header(source_name: str | None) -> str:
    """`game.lua` の先頭 3 行。`.jin` のファイル名も入力なので Lua のリテラルを通す。

    guard: _header -> lua_string(source_name)
    """
    source = lua_string(source_name) if source_name is not None else '"<memory>"'
    return (
        f"-- generated by jin — do not edit\n-- source: {source}\n-- jin: 2  jil: {JIL_VERSION}\n"
    )


def generate(
    model: JinFileV2, *, source_name: str | None = None, debug: bool = False
) -> GeneratedGame:
    """`game.lua` と `game.manifest.json` を作る。診断に error があれば `CodegenError`。"""
    generator = _Generator(model, debug=debug)
    program = generator.program()
    lua = (
        _header(source_name)
        + prelude_source()
        + "\n-- program\n"
        + program
        + "return { boot = boot, tick = tick }\n"
    )
    namespaces = sorted(
        {s.host for c in model.circles for s in c.sigils if isinstance(s, SigilHost)}
    )
    manifest = {
        "file": source_name,
        "stage": {
            "width": model.stage.width,
            "height": model.stage.height,
            "fps": model.stage.fps,
            "seed": model.stage.seed,
        },
        "namespaces": namespaces,
        "assets": [{"name": a.name, "kind": a.kind, "path": a.path} for a in model.stage.assets],
        "debug": debug,
        "jil": hashlib.sha256(lua.encode("utf-8")).hexdigest(),
    }
    return GeneratedGame(lua=lua, manifest=manifest, debug=debug)


__all__ = ["CodegenError", "GeneratedGame", "generate", "lua_number", "lua_string"]
