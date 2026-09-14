"""`JinFileV2` → WAT の生成部（docs/spec/v2/jil.md §6.3 / §6.4・設計書 §11 #56）。

解析（型付き AST・添字・`wait` の閉包・manifest の共通部）は `jin_wasm.program` から読む。
ここは wasm-GC のテキスト形式（WAT）を出す側だけで、Lua を出す `jin_wasm.codegen` と同じ解析を共有する。

## 名前の写像（jil.md §6.3）

`.jin` の名前を WAT の識別子に**埋め込まない**。陣 i（0 始まり）の state は `(type $S<i>)` の
struct で欄は宣言順の添字、確定値は同じ型の `$P<i>`、手順は `$r<i>_<j>`、局所は `$l<n>`
（手順ごとの通し番号）。名前は data 区画の文字列（公開 state の鍵 `"Fib.answer":`）にだけ載る。

## Sub-Issue A（#73）の範囲

`num` / `bool` の式（リテラル・局所・state・他陣の公開 state・単項・二項）、`let` / `set` / `if` /
`loop count` / `loop while` / `break` / `return` / `finish` / 自陣の手順への `cast`、`out` の state、
release ビルド。それ以外は `CodegenError` で、どの Sub-Issue で入るかを名指しする
（文字列 / list / 型紙 / 純関数 / ホスト能力は #74、`wait` / `emit` / `transfer` / flow / `on` /
summon / agent / debug は #75）。

## 文字列（WAT のリテラル）

data 区画の文字列は `wat_string` で WAT の文字列リテラルにする（`"` / `\\` / 制御文字 / 非 ASCII を
`\\XX` の 16 進バイトに）。ヘッダの `source:` はコメントに入るので `jin_wasm.codegen.lua_string`
（制御文字を `\\ddd` に逃がす）を通し、改行でコメントから抜けない。

    guard: header -> lua_string(source_name)
    guard: wat_string -> text.encode
"""

from __future__ import annotations

from dataclasses import dataclass, field

from jin_core.v2 import expr as ex
from jin_core.v2.model import (
    BreakStep,
    CastStep,
    EmitStep,
    FinishStep,
    IfStep,
    JinFileV2,
    LetStep,
    LoopStep,
    ReturnStep,
    Rite,
    SetStep,
    Step,
    TransferStep,
    WaitStep,
)
from jin_wasm.codegen import lua_string
from jin_wasm.jil import JIL_VERSION
from jin_wasm.program import CircleInfo, CodegenError, Program, analyze

#: 生成部の data 区画の先頭。ランタイム部（`runtime.wat`）の文字列は [0, 128) に閉じる。
DATA_BASE = 128

#: 入力域の直後に確保しておく出力域（`runtime.wat` の `input` と同じ 64 KiB）。
_PAGE = 65536

_LATER = {
    "str": "#74（Sub-Issue B: 文字列）",
    "list": "#74（Sub-Issue B: list）",
    "form": "#74（Sub-Issue B: 型紙）",
    "pure": "#74（Sub-Issue B: 純関数）",
    "host": "#74（Sub-Issue B: ホスト能力）",
    "effect": "#74（Sub-Issue B: 効果）",
    "each": "#74（Sub-Issue B: loop each）",
    "wait": "#75（Sub-Issue C: wait）",
    "emit": "#75（Sub-Issue C: emit）",
    "transfer": "#75（Sub-Issue C: transfer）",
    "flow": "#75（Sub-Issue C: flow を持つ陣）",
    "on": "#75（Sub-Issue C: on の手順）",
    "summon": "#75（Sub-Issue C: summon）",
    "agent": "#75（Sub-Issue C: agent）",
    "debug": "#75（Sub-Issue C: デバッグビルド）",
}


def _later(what: str, where: str) -> CodegenError:
    return CodegenError(
        f"--target wasm-gc はまだ「{where}」を生成できません（{_LATER[what]} で入ります。"
        "それまでは Lua 経路 --target lua を使ってください）"
    )


# ---------------------------------------------------------------- リテラル


def wat_string(text: str) -> str:
    """WAT の文字列リテラル（data 区画用）。ASCII の印字可能文字以外は UTF-8 のバイトを `\\XX` に。

    guard: wat_string -> text.encode
    """
    out: list[str] = []
    for byte in text.encode("utf-8"):
        if 0x20 <= byte < 0x7F and byte not in (0x22, 0x5C):
            out.append(chr(byte))
        else:
            out.append(f"\\{byte:02x}")
    return '"' + "".join(out) + '"'


def wat_number(value: float) -> str:
    """`f64.const` のリテラル。Python の `repr(float)` は WAT の浮動小数の文法に収まる。"""
    text = repr(float(value))
    if "inf" in text:
        return "inf" if value > 0 else "-inf"
    if "nan" in text:
        return "nan"
    return text


def wat_type(type_text: str | None) -> str:
    if type_text == "num":
        return "f64"
    if type_text == "bool":
        return "i32"
    if type_text == "str":
        raise _later("str", "str の値")
    if type_text is not None and type_text.startswith("list"):
        raise _later("list", "list の値")
    raise _later("form", f"型 {type_text} の値")


def _default(type_text: str | None) -> str:
    """戻り値の型ごとの既定値（`STOP` で早く返るときに積む。Lua の nil に相当・意味は使わない）。"""
    return "(f64.const 0)" if type_text == "num" else "(i32.const 0)"


# ---------------------------------------------------------------- 文脈


@dataclass(slots=True)
class _Data:
    """data 区画。同じ文字列は 1 度だけ置く。"""

    chunks: list[tuple[int, bytes]] = field(default_factory=list)
    offsets: dict[bytes, tuple[int, int]] = field(default_factory=dict)
    end: int = DATA_BASE

    def put(self, text: str) -> tuple[int, int]:
        raw = text.encode("utf-8")
        if raw not in self.offsets:
            self.offsets[raw] = (self.end, len(raw))
            self.chunks.append((self.end, raw))
            self.end += len(raw)
        return self.offsets[raw]


@dataclass(slots=True)
class _RiteCtx:
    info: CircleInfo
    rite: Rite
    locals: dict[str, str]  # 局所名 → $l<n>
    decls: list[tuple[str, str]] = field(default_factory=list)  # ($l<n>, f64 | i32)
    next_local: int = 0
    next_label: int = 0
    loop_labels: list[str] = field(default_factory=list)  # break の飛び先（内側が末尾）

    def new_local(self, name: str | None, type_text: str | None) -> str:
        wat = f"$l{self.next_local}"
        self.next_local += 1
        self.decls.append((wat, wat_type(type_text)))
        if name is not None:
            self.locals[name] = wat
        return wat

    def label(self, stem: str) -> str:
        self.next_label += 1
        return f"${stem}{self.next_label}"


class _Generator:
    def __init__(self, program: Program) -> None:
        self.program = program
        self.model = program.model
        self.circles = program.circles
        self.data = _Data()
        self.lines: list[str] = []

    def out(self, text: str, indent: int = 1) -> None:
        self.lines.append("  " * indent + text)

    # ---------------------------------------------------------------- 式
    def expr(self, node: ex.Node, ctx: _RiteCtx | None, info: CircleInfo | None) -> str:
        if isinstance(node, ex.Number):
            return f"(f64.const {wat_number(node.value)})"
        if isinstance(node, ex.Boolean):
            return f"(i32.const {1 if node.value else 0})"
        if isinstance(node, ex.String):
            raise _later("str", "文字列リテラル")
        if isinstance(node, ex.Name):
            return self.name(node.name, ctx, info)
        if isinstance(node, ex.Unary):
            operand = self.expr(node.operand, ctx, info)
            return f"(f64.neg {operand})" if node.op == "-" else f"(i32.eqz {operand})"
        if isinstance(node, ex.Binary):
            return self.binary(node, ctx, info)
        if isinstance(node, ex.FieldAccess):
            return self.field(node, ctx, info)
        if isinstance(node, ex.Index):
            raise _later("list", "添字")
        if isinstance(node, ex.Call):
            callee = node.callee
            if isinstance(callee, ex.Name):
                raise _later("pure", f"純関数 {callee.name}")
            raise _later("host", "式の中のホスト能力")
        if isinstance(node, ex.Construct):
            raise _later("form", "型紙のコンストラクタ")
        if isinstance(node, ex.ListLiteral):
            raise _later("list", "list リテラル")
        raise CodegenError(f"式の形 {type(node).__name__} は生成できません")  # pragma: no cover

    def binary(self, node: ex.Binary, ctx: _RiteCtx | None, info: CircleInfo | None) -> str:
        left = self.expr(node.left, ctx, info)
        right = self.expr(node.right, ctx, info)
        op = node.op
        if op == "and":
            return f"(if (result i32) {left} (then {right}) (else (i32.const 0)))"
        if op == "or":
            return f"(if (result i32) {left} (then (i32.const 1)) (else {right}))"
        if op == "++":
            raise _later("str", "文字列の連結")
        if op in ("+", "-", "*", "/"):
            name = {"+": "add", "-": "sub", "*": "mul", "/": "div"}[op]
            return f"(f64.{name} {left} {right})"
        if op == "%":
            return f"(call $lmod {left} {right})"
        operand_type = node.left.type
        if operand_type == "num":
            name = {"==": "eq", "!=": "ne", "<": "lt", "<=": "le", ">": "gt", ">=": "ge"}[op]
            return f"(f64.{name} {left} {right})"
        if operand_type == "bool" and op in ("==", "!="):
            return f"(i32.{'eq' if op == '==' else 'ne'} {left} {right})"
        raise _later("str", f"{operand_type} の比較")

    def name(self, name: str, ctx: _RiteCtx | None, info: CircleInfo | None) -> str:
        if ctx is not None and name in ctx.locals:
            return f"(local.get {ctx.locals[name]})"
        if info is not None and name in info.states:
            j, type_text = info.states[name]
            wat_type(type_text)
            return f"(struct.get $S{info.pointer_index} {j} (global.get $S{info.pointer_index}))"
        raise CodegenError(f"識別子 '{name}' を解決できません")

    def field(self, node: ex.FieldAccess, ctx: _RiteCtx | None, info: CircleInfo | None) -> str:
        base = node.obj
        if isinstance(base, ex.Name):
            is_value = (ctx is not None and base.name in ctx.locals) or (
                info is not None and base.name in info.states
            )
            if not is_value and base.name in self.circles:
                other = self.circles[base.name]
                j, type_text = other.states[node.name]
                wat_type(type_text)
                return (
                    f"(struct.get $S{other.pointer_index} {j} (global.get $P{other.pointer_index}))"
                )
        raise _later("form", f"型紙の欄 .{node.name}")

    # ---------------------------------------------------------------- 代入先
    def assign(self, target: ex.Node, value: str, ctx: _RiteCtx, indent: int) -> None:
        info = ctx.info
        if isinstance(target, ex.Index):
            raise _later("list", "添字への代入")
        if isinstance(target, ex.Name):
            if target.name in ctx.locals:
                self.out(f"(local.set {ctx.locals[target.name]} {value})", indent)
                return
            if target.name in info.states:
                j, _ = info.states[target.name]
                pi = info.pointer_index
                self.out(f"(struct.set $S{pi} {j} (global.get $S{pi}) {value})", indent)
                return
        raise _later("form", "型紙の欄への代入")

    # ---------------------------------------------------------------- ステップ
    def steps(self, steps: list[Step], pointer: str, ctx: _RiteCtx, indent: int) -> None:
        for k, step in enumerate(steps):
            self.step(step, f"{pointer}/{k}", ctx, indent)

    def step(self, step: Step, sp: str, ctx: _RiteCtx, indent: int) -> None:
        info = ctx.info
        node = self.program.node
        if isinstance(step, SetStep):
            value = self.expr(node(f"{sp}/expr"), ctx, info)
            self.assign(node(f"{sp}/target"), value, ctx, indent)
            return
        if isinstance(step, LetStep):
            value_node = node(f"{sp}/expr")
            value = self.expr(value_node, ctx, info)
            local = ctx.new_local(step.name, value_node.type)
            self.out(f"(local.set {local} {value})", indent)
            return
        if isinstance(step, CastStep):
            self.cast(step, sp, ctx, indent)
            return
        if isinstance(step, IfStep):
            cond = self.expr(node(f"{sp}/cond"), ctx, info)
            self.out(f"(if {cond}", indent)
            self.out("(then", indent + 1)
            self.steps(step.then, f"{sp}/then", ctx, indent + 2)
            self.out(")", indent + 1)
            if step.else_:
                self.out("(else", indent + 1)
                self.steps(step.else_, f"{sp}/else", ctx, indent + 2)
                self.out(")", indent + 1)
            self.out(")", indent)
            return
        if isinstance(step, LoopStep):
            self.loop(step, sp, ctx, indent)
            return
        if isinstance(step, BreakStep):
            self.out(f"(br {ctx.loop_labels[-1]})", indent)
            return
        if isinstance(step, WaitStep):
            raise _later("wait", "wait")
        if isinstance(step, EmitStep):
            raise _later("emit", "emit")
        if isinstance(step, ReturnStep):
            if step.expr is None:
                self.out("(return)", indent)
                return
            self.out(f"(return {self.expr(node(f'{sp}/expr'), ctx, info)})", indent)
            return
        if isinstance(step, FinishStep):
            self.out(f"(call $finish{info.pointer_index})", indent)
            self.out(self.early_return(ctx), indent)
            return
        if isinstance(step, TransferStep):
            raise _later("transfer", "transfer")
        raise CodegenError(type(step).__name__)  # pragma: no cover

    def early_return(self, ctx: _RiteCtx) -> str:
        if ctx.rite.returns is None:
            return "(return)"
        return f"(return {_default(ctx.rite.returns)})"

    def loop(self, step: LoopStep, sp: str, ctx: _RiteCtx, indent: int) -> None:
        info = ctx.info
        node = self.program.node
        if step.kind == "each":
            raise _later("each", "loop each")
        brk = ctx.label("brk")
        cont = ctx.label("loop")
        if step.kind == "while":
            self.out(f"(block {brk}", indent)
            self.out(f"(loop {cont}", indent + 1)
            cond = self.expr(node(f"{sp}/cond"), ctx, info)
            self.out(f"(br_if {brk} (i32.eqz {cond}))", indent + 2)
            ctx.loop_labels.append(brk)
            self.steps(step.steps, f"{sp}/steps", ctx, indent + 2)
            ctx.loop_labels.pop()
            self.out(f"(br {cont})", indent + 2)
            self.out(")", indent + 1)
            self.out(")", indent)
            return
        # count: Lua の `for i = 0, math.floor(times) - 1`。回数は f64 のまま比べる（NaN / 巨大な値で
        # i32 に変換すると trap する。NaN は 1 回も回らない・Lua の math.floor(NaN) と同じ）。
        times = self.expr(node(f"{sp}/times"), ctx, info)
        count = ctx.new_local(None, "num")
        index = ctx.new_local(None, "num")
        self.out(f"(local.set {count} (f64.floor {times}))", indent)
        self.out(f"(local.set {index} (f64.const 0))", indent)
        self.out(f"(block {brk}", indent)
        self.out(f"(loop {cont}", indent + 1)
        self.out(
            f"(br_if {brk} (i32.eqz (f64.lt (local.get {index}) (local.get {count}))))", indent + 2
        )
        if step.name is not None:
            item = ctx.new_local(step.name, "num")
            self.out(f"(local.set {item} (local.get {index}))", indent + 2)
        ctx.loop_labels.append(brk)
        self.steps(step.steps, f"{sp}/steps", ctx, indent + 2)
        ctx.loop_labels.pop()
        self.out(f"(local.set {index} (f64.add (local.get {index}) (f64.const 1)))", indent + 2)
        self.out(f"(br {cont})", indent + 2)
        self.out(")", indent + 1)
        self.out(")", indent)

    def cast(self, step: CastStep, sp: str, ctx: _RiteCtx, indent: int) -> None:
        info = ctx.info
        node = self.program.node
        parts = step.target.split(".")
        if len(parts) == 1 and parts[0] in info.rites:
            j = info.rites[parts[0]]
            rite = info.circle.rites[j - 1]
        elif len(parts) == 1 and parts[0] in info.sigils:
            raise _later(info.sigils[parts[0]][0], f"cast {step.target}")
        elif len(parts) == 1:
            raise _later("effect", f"効果 {step.target}")
        else:
            raise _later("host", f"ホスト能力 {step.target}")
        args = " ".join(self.expr(node(f"{sp}/args/{k}"), ctx, info) for k in range(len(step.args)))
        call = f"(call $r{info.pointer_index}_{j - 1}{' ' + args if args else ''})"
        stop = f"(i32.ne (global.get $st{info.pointer_index}) (i32.const 1))"
        if step.into is not None and rite.returns is not None:
            # Lua と同じ順: 呼ぶ → STOP なら返る → into に代入
            tmp = ctx.new_local(None, rite.returns)
            self.out(f"(local.set {tmp} {call})", indent)
            self.out(f"(if {stop} (then {self.early_return(ctx)}))", indent)
            self.assign(node(f"{sp}/into"), f"(local.get {tmp})", ctx, indent)
            return
        self.out(f"(drop {call})" if rite.returns is not None else call, indent)
        self.out(f"(if {stop} (then {self.early_return(ctx)}))", indent)

    # ---------------------------------------------------------------- 手順と陣
    def emit_rite(self, info: CircleInfo, rite: Rite, j: int) -> None:
        ctx = _RiteCtx(info=info, rite=rite, locals={})
        params: list[str] = []
        for p in rite.params:
            wat = f"$l{ctx.next_local}"
            ctx.next_local += 1
            ctx.locals[p.name] = wat
            params.append(f"(param {wat} {wat_type(p.type)})")
        pointer = f"/circles/{info.pointer_index}/rites/{j}"
        result = f" (result {wat_type(rite.returns)})" if rite.returns is not None else ""
        start = len(self.lines)
        self.steps(rite.steps, f"{pointer}/steps", ctx, 2)
        body = self.lines[start:]
        del self.lines[start:]
        head = f"(func $r{info.pointer_index}_{j}{' ' + ' '.join(params) if params else ''}{result}"
        self.out(f"{head}  ;; {info.circle.name}.{rite.name}".replace("  ;;", " ;;"), 1)
        for wat, type_text in ctx.decls:
            self.out(f"(local {wat} {type_text})", 2)
        self.lines.extend(body)
        if rite.returns is not None:
            # 末尾まで return しなかった手順（Lua は nil を返す）。型付きの関数には値が要る
            self.out(_default(rite.returns), 2)
        self.out(")", 1)

    def emit_circle(self, info: CircleInfo) -> None:
        circle = info.circle
        pi = info.pointer_index
        if circle.flow is not None:
            raise _later("flow", f"陣 {circle.name}（flow）")
        if circle.boundary is not None and circle.boundary.on:
            raise _later("on", f"陣 {circle.name} の on")
        fields = " ".join(f"(field (mut {wat_type(s.type)}))" for s in circle.state)
        self.out(f";; circle {pi}: {circle.name}", 1)
        self.out(f"(type $S{pi} (struct {fields}))".replace("struct )", "struct)"), 1)
        self.out(f"(global $S{pi} (mut (ref $S{pi})) (struct.new_default $S{pi}))", 1)
        self.out(f"(global $P{pi} (mut (ref $S{pi})) (struct.new_default $S{pi}))", 1)
        self.out(f"(global $st{pi} (mut i32) (i32.const 0))  ;; 0 idle / 1 active / 2 done", 1)
        self.out(f"(global $pubd{pi} (mut i32) (i32.const 0))", 1)
        inits = " ".join(
            self.expr(self.program.node(f"/circles/{pi}/state/{j}/init"), None, None)
            for j, _ in enumerate(circle.state)
        )
        self.out(
            f"(func $init{pi} (global.set $S{pi} (struct.new $S{pi}{' ' + inits if inits else ''})))",
            1,
        )
        outs = [(j, s) for j, s in enumerate(circle.state) if s.out]
        self.out(f"(func $publish{pi}", 1)
        for j, _ in outs:
            self.out(
                f"(struct.set $S{pi} {j} (global.get $P{pi}) (struct.get $S{pi} {j} (global.get $S{pi})))",
                2,
            )
        if outs:
            self.out(f"(global.set $pubd{pi} (i32.const 1))", 2)
        self.out(")", 1)
        self.out(f"(func $pub{pi}", 1)
        for j, s in outs:
            off, length = self.data.put(f'"{circle.name}.{s.name}":')
            put = "$put_jn" if s.type == "num" else "$put_bool"
            self.out("(call $pub_comma)", 2)
            self.out(f"(call $puts (i32.const {off}) (i32.const {length}))", 2)
            self.out(f"(call {put} (struct.get $S{pi} {j} (global.get $P{pi})))", 2)
        self.out(")", 1)
        self.out(f"(func $finish{pi}", 1)
        self.out(f"(if (i32.ne (global.get $st{pi}) (i32.const 1)) (then (return)))", 2)
        self.out(f"(global.set $st{pi} (i32.const 2))", 2)
        self.out(f"(call $publish{pi})", 2)
        self.out(")", 1)
        core_j = info.rites[circle.core or ""] - 1
        core = info.circle.rites[core_j]
        call = f"(call $r{pi}_{core_j})"
        self.out(f"(func $enter{pi}", 1)
        self.out(f"(global.set $st{pi} (i32.const 1))", 2)
        self.out(f"(call $init{pi})", 2)
        self.out(f"(call $publish{pi})", 2)
        self.out(f"(drop {call})" if core.returns is not None else call, 2)
        self.out(")", 1)

    # ---------------------------------------------------------------- 全体
    def program_part(self) -> str:
        model = self.model
        for info in self.circles.values():
            if info.circle.core is None:
                raise _later("flow", f"陣 {info.circle.name}（flow）")
            for sigil in info.circle.sigils:
                if sigil.kind == "host":
                    raise _later("host", f"陣 {info.circle.name} の sigil {sigil.name}")
                raise _later(sigil.kind, f"陣 {info.circle.name} の sigil {sigil.name}")
        root = self.circles[model.root]
        for info in self.circles.values():
            for j, rite in enumerate(info.circle.rites):
                self.emit_rite(info, rite, j)
        for info in self.circles.values():
            self.emit_circle(info)
        indices = [info.pointer_index for info in self.circles.values()]
        self.out(f"(global $ROOT i32 (i32.const {root.pointer_index}))", 1)
        self.out("(func $prog_fresh_state", 1)
        for pi in indices:
            self.out(f"(global.set $st{pi} (i32.const 0))", 2)
            self.out(f"(global.set $pubd{pi} (i32.const 0))", 2)
            self.out(f"(call $init{pi})", 2)
            self.out(f"(call $publish{pi})", 2)
        self.out(")", 1)
        self.out(f"(func $prog_enter_root (call $enter{root.pointer_index}))", 1)
        self.out("(func $prog_publish_all", 1)
        for pi in indices:
            self.out(f"(call $publish{pi})", 2)
        self.out(")", 1)
        self.out("(func $prog_pub_all", 1)
        for pi in indices:
            self.out(f"(if (global.get $pubd{pi}) (then (call $pub{pi})))", 2)
        self.out(")", 1)
        self.out("(func $prog_advance", 1)
        self.out(
            f"(if (i32.eq (global.get $st{root.pointer_index}) (i32.const 2)) "
            "(then (global.set $DONE (i32.const 1))))",
            2,
        )
        self.out(")", 1)
        # data 区画と線形メモリ（runtime.wat の配置に合わせる）
        for off, raw in self.data.chunks:
            self.out(f"(data (i32.const {off}) {wat_string(raw.decode('utf-8'))})", 1)
        in_base = (self.data.end + 15) // 16 * 16
        pages = (in_base + 2 * _PAGE + _PAGE - 1) // _PAGE
        self.out(f"(global $in_base i32 (i32.const {in_base}))", 1)
        self.out(f'(memory (export "memory") {pages})', 1)
        return "\n".join(self.lines) + "\n"


def header(source_name: str | None) -> str:
    """WAT の先頭 3 行（コメント）。`.jin` のファイル名も入力なのでリテラルを通す。

    guard: header -> lua_string(source_name)
    """
    source = lua_string(source_name) if source_name is not None else '"<memory>"'
    return (
        f";; generated by jin — do not edit\n;; source: {source}\n"
        f";; jin: 2  jil: {JIL_VERSION}  target: wasm-gc\n"
    )


def generate_program(model: JinFileV2, *, debug: bool = False) -> str:
    """生成部（WAT の断片。`(module` の中に置く）。診断に error があれば `CodegenError`。"""
    if debug:
        raise _later("debug", "デバッグビルド（--debug / --trace）")
    return _Generator(analyze(model)).program_part()


__all__ = ["DATA_BASE", "generate_program", "header", "wat_number", "wat_string", "wat_type"]
