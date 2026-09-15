"""`JinFileV2` → WAT の生成部（docs/spec/v2/jil.md §6.3 / §6.4・設計書 §11 #56）。

解析（型付き AST・添字・`wait` の閉包・manifest の共通部）は `jin_wasm.program` から読む。
ここは wasm-GC のテキスト形式（WAT）を出す側だけで、Lua を出す `jin_wasm.codegen` と同じ解析を共有する。

## 名前の写像（jil.md §6.3）

`.jin` の名前を WAT の識別子に**埋め込まない**。陣 i（0 始まり）の state は `(type $S<i>)` の
struct で欄は宣言順の添字、確定値は同じ型の `$P<i>`、手順は `$r<i>_<j>`、局所は `$l<n>`
（手順ごとの通し番号）、型紙 k は `$F<k>`（`$F0` はランタイム部の Pointer）。名前は data 区画の
文字列（公開 state の鍵 `"Fib.answer":` / 型紙の欄の鍵）にだけ載る。

## 値の表現（jil.md §6.3）

`num` = `f64`、`bool` = `i32`、`str` = `(ref $str)`（UTF-8 の `array i8`・作ったら書き換えない）、
`list<num>` / `list<bool>` / それ以外の list = ランタイム部の `$Lf` / `$Li` / `$Lr`（`$Lr` の要素は
`anyref` で、読むときに要素の型へ `ref.cast`）、型紙 = `(ref $F<k>)` の struct。式の文字列リテラルは
passive の data（`(data $L<i> "…")`）から `array.new_data` で作る。

## エラー機構（jil.md §6.4）

wasm に例外は使わない。ランタイム部の `$ERR` がフラグ `$ERRED` を立てるので、生成部は**エラーし得る
ステップの後**（添字を含む式・cast・ループ）と手順の呼び出しの後にフラグを見て返る（Lua の error が
手順を抜ける形の写し）。ループの戻り辺と手順の呼び出しには命令数のカウンタ `$bud` を埋める（§6.6）。

## Sub-Issue B（#74）の後に残るもの

`wait` / `emit` / `transfer` / flow / summon / agent / debug は #75（Sub-Issue C）で、それまでは
`CodegenError` で名指しする。

## 文字列（WAT のリテラル）

data 区画の文字列は `wat_string` で WAT の文字列リテラルにする（`"` / `\\` / 制御文字 / 非 ASCII を
`\\XX` の 16 進バイトに）。ヘッダの `source:` はコメントに入るので `jin_wasm.codegen.lua_string`
（制御文字を `\\ddd` に逃がす）を通し、改行でコメントから抜けない。

    guard: header -> lua_string(source_name)
    guard: wat_string -> text.encode
"""

from __future__ import annotations

from dataclasses import dataclass, field

from jin_core.v2 import abilities
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
    parse_type,
)
from jin_wasm.codegen import lua_string
from jin_wasm.jil import JIL_VERSION
from jin_wasm.program import CircleInfo, CodegenError, FormInfo, Program, analyze

#: 生成部の data 区画の先頭。ランタイム部（`runtime.wat`）の文字列は [0, 2048) に閉じる。
DATA_BASE = 2048

#: 入力域の直後に確保しておく出力域（`runtime.wat` の `input` と同じ 64 KiB）。
_PAGE = 65536

_LATER = {
    "wait": "#75（Sub-Issue C: wait）",
    "emit": "#75（Sub-Issue C: emit）",
    "transfer": "#75（Sub-Issue C: transfer）",
    "flow": "#75（Sub-Issue C: flow を持つ陣）",
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


def list_variant(elem_type: str) -> str:
    """list の要素の表現（`f` = f64 / `i` = i32 / `r` = anyref）。"""
    if elem_type == "num":
        return "f"
    if elem_type == "bool":
        return "i"
    return "r"


def wat_type(type_text: str | None) -> str:
    """型紙を含まない型の WAT の型（型紙は `_Generator.wtype`）。"""
    if type_text == "num":
        return "f64"
    if type_text == "bool":
        return "i32"
    if type_text == "str":
        return "(ref $str)"
    if type_text is not None and type_text.startswith("list<"):
        _, inner = parse_type(type_text)
        return f"(ref $L{list_variant(inner or '?')})"
    if type_text == "Pointer":
        return "(ref $F0)"
    raise CodegenError(f"型 {type_text} は wasm の型に写せません")


# ---------------------------------------------------------------- 文脈


@dataclass(slots=True)
class _Data:
    """data 区画（active。公開 state の鍵など、書き手が `$puts` で写す文字列）。同じ文字列は 1 度だけ置く。"""

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
class _Literals:
    """式の文字列リテラル（passive の data。`array.new_data` で str を作る）。"""

    items: list[bytes] = field(default_factory=list)
    index: dict[bytes, int] = field(default_factory=dict)

    def get(self, text: str) -> str:
        raw = text.encode("utf-8")
        if raw not in self.index:
            self.index[raw] = len(self.items)
            self.items.append(raw)
        return f"(array.new_data $str $L{self.index[raw]} (i32.const 0) (i32.const {len(raw)}))"


@dataclass(slots=True)
class _RiteCtx:
    info: CircleInfo
    rite: Rite
    locals: dict[str, tuple[str, str | None]]  # 局所名 → ($l<n>, 型)
    decls: list[tuple[str, str]] = field(default_factory=list)  # ($l<n>, WAT の型)
    next_local: int = 0
    next_label: int = 0
    loop_labels: list[str] = field(default_factory=list)  # break の飛び先（内側が末尾）

    def label(self, stem: str) -> str:
        self.next_label += 1
        return f"${stem}{self.next_label}"


def _is_ref(wat: str) -> bool:
    return wat.startswith("(ref")


def _nullable(wat: str) -> str:
    return wat.replace("(ref $", "(ref null $", 1) if _is_ref(wat) else wat


def _contains_index(node: ex.Node) -> bool:
    """式がエラーし得る（添字を含む）か。"""
    if isinstance(node, ex.Index):
        return True
    if isinstance(node, ex.Unary):
        return _contains_index(node.operand)
    if isinstance(node, ex.Binary):
        return _contains_index(node.left) or _contains_index(node.right)
    if isinstance(node, ex.FieldAccess):
        return _contains_index(node.obj)
    if isinstance(node, ex.Call):
        return _contains_index(node.callee) or any(_contains_index(a) for a in node.args)
    if isinstance(node, ex.Construct):
        return any(_contains_index(v) for _, _, v in node.fields)
    if isinstance(node, ex.ListLiteral):
        return any(_contains_index(i) for i in node.items)
    return False


_HOST_FUNC = {
    (ns.name, m.name): f"$h_{ns.name}_{m.name}" for ns in abilities.NAMESPACES for m in ns.members
}

_PURE_SIMPLE = {
    "abs": "$f_abs",
    "min": "$f_min",
    "max": "$f_max",
    "floor": "$f_floor",
    "ceil": "$f_ceil",
    "round": "$f_round",
    "sqrt": "$f_sqrt",
    "sin": "$f_sin",
    "cos": "$f_cos",
    "atan2": "$f_atan2",
    "clamp": "$f_clamp",
    "sub": "$f_sub",
    "num": "$f_num",
    "cmp": "$f_cmp",
}


class _Generator:
    def __init__(self, program: Program) -> None:
        self.program = program
        self.model = program.model
        self.circles = program.circles
        self.forms: dict[str, FormInfo] = program.forms
        self.data = _Data()
        self.lits = _Literals()
        self.lines: list[str] = []
        self.serializers: dict[str, str] = {}  # 型 → 直列化関数の名前
        self.serializer_lines: list[str] = []

    def out(self, text: str, indent: int = 1) -> None:
        self.lines.append("  " * indent + text)

    # ---------------------------------------------------------------- 型
    def form_index(self, name: str) -> int:
        info = self.forms.get(name)
        if info is None:
            raise CodegenError(f"型紙 '{name}' が分かりません")
        return info.index

    def wtype(self, type_text: str | None) -> str:
        if type_text is None or type_text == ex.LIST_OF_UNKNOWN:
            raise CodegenError(
                "--target wasm-gc: 要素の型が決まらない list（空の list リテラルだけの let など）は"
                "生成できません。state か型紙の欄に置くか、要素を 1 つ入れてください"
            )
        head, _ = parse_type(type_text)
        if head in ("num", "bool", "str", "list", "Pointer"):
            return wat_type(type_text)
        return f"(ref $F{self.form_index(head)})"

    def default_const(self, type_text: str) -> str:
        """型ごとの既定値（グローバルの初期化や早い return に使う定数式）。"""
        head, inner = parse_type(type_text)
        if head == "num":
            return "(f64.const 0)"
        if head == "bool":
            return "(i32.const 0)"
        if head == "str":
            return "(array.new_fixed $str 0)"
        if head == "list":
            v = list_variant(inner or "?")
            return f"(struct.new $L{v} (array.new_default $l{v} (i32.const 0)) (i32.const 0))"
        k = self.form_index(head)
        fields = " ".join(self.default_const(t) for _, (_, t) in self.forms[head].fields.items())
        return f"(struct.new $F{k}{' ' + fields if fields else ''})"

    def cast_elem(self, value: str, elem_type: str) -> str:
        """`$Lr` の要素（anyref）を要素の型へ。"""
        if list_variant(elem_type) != "r":
            return value
        return f"(ref.cast {self.wtype(elem_type)} {value})"

    # ---------------------------------------------------------------- 直列化（公開 state の JSON）
    def serializer(self, type_text: str) -> str:
        """型の値を書き手（$OUT）へ JSON で書く関数の名前。"""
        head, inner = parse_type(type_text)
        if head == "num":
            return "$put_jn"
        if head == "bool":
            return "$put_bool"
        if head == "str":
            return "$put_js"
        if type_text in self.serializers:
            return self.serializers[type_text]
        if head == "list":
            assert inner is not None
            name = f"$ser{len(self.serializers)}"
            self.serializers[type_text] = name
            v = list_variant(inner)
            item = self.serializer(inner)
            get = self.cast_elem(f"(call $l{v}_get (local.get $l) (local.get $i))", inner)
            self.serializer_lines.extend(
                [
                    f"  (func {name} (param $l (ref null $L{v}))  ;; {type_text}",
                    "    (local $i i32) (local $n i32)",
                    f"    (local.set $n (call $l{v}_len (local.get $l)))",
                    "    (call $putc (i32.const 91))",
                    "    (block $done (loop $next",
                    "      (br_if $done (i32.ge_u (local.get $i) (local.get $n)))",
                    "      (if (local.get $i) (then (call $putc (i32.const 44))))",
                    f"      (call {item} {get})",
                    "      (local.set $i (i32.add (local.get $i) (i32.const 1)))",
                    "      (br $next)))",
                    "    (call $putc (i32.const 93)))",
                ]
            )
            return name
        name = f"$jf{self.form_index(head)}"
        self.serializers[type_text] = name
        return name

    def emit_form_serializers(self) -> None:
        """`$jf<k>`: 型紙 k を `{"x":…,"y":…}` で書く（Lua の JF[k] と 1:1。$jf0 は Pointer）。"""
        for name, info in self.forms.items():
            k = info.index
            self.out(f"(func $jf{k} (param $v (ref null $F{k}))  ;; {name}", 1)
            self.out("(call $putc (i32.const 123))", 2)
            for pos, (field_name, (j, type_text)) in enumerate(info.fields.items()):
                off, length = self.data.put(("," if pos else "") + f'"{field_name}":')
                self.out(f"(call $puts (i32.const {off}) (i32.const {length}))", 2)
                self.out(
                    f"(call {self.serializer(type_text)} (struct.get $F{k} {j} (local.get $v)))", 2
                )
            self.out("(call $putc (i32.const 125)))", 2)

    # ---------------------------------------------------------------- 式
    def expr(
        self,
        node: ex.Node,
        ctx: _RiteCtx | None,
        info: CircleInfo | None,
        expect: str | None = None,
    ) -> str:
        if isinstance(node, ex.Number):
            return f"(f64.const {wat_number(node.value)})"
        if isinstance(node, ex.Boolean):
            return f"(i32.const {1 if node.value else 0})"
        if isinstance(node, ex.String):
            return self.lits.get(node.value)
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
            obj_type = node.obj.type or ""
            _, inner = parse_type(obj_type) if obj_type.startswith("list<") else ("", None)
            if inner is None:
                raise CodegenError(f"添字の左辺の型が list ではありません（{obj_type}）")
            v = list_variant(inner)
            obj = self.expr(node.obj, ctx, info)
            idx = self.expr(node.index, ctx, info)
            # 範囲外は ERR して既定値が返る（$Lr の要素は非 null へ cast するので null は渡せない）。
            # 続くステップのフラグ検査で手順を抜けるので、既定値が観測されることはない
            return self.cast_elem(f"(call $l{v}_at {obj} {idx} {self.default_const(inner)})", inner)
        if isinstance(node, ex.Call):
            return self.call(node, ctx, info)
        if isinstance(node, ex.Construct):
            form = self.forms[node.form]
            values = {name: value for name, _, value in node.fields}
            parts = [
                self.expr(values[field_name], ctx, info, type_text)
                for field_name, (_, type_text) in form.fields.items()
            ]
            return f"(struct.new $F{form.index}{' ' + ' '.join(parts) if parts else ''})"
        if isinstance(node, ex.ListLiteral):
            type_text = node.type if node.type != ex.LIST_OF_UNKNOWN else expect
            if type_text is None or not type_text.startswith("list<"):
                self.wtype(ex.LIST_OF_UNKNOWN)  # 要素の型が決まらない → CodegenError
            _, inner = parse_type(type_text or "")
            assert inner is not None
            v = list_variant(inner)
            text = f"(call $l{v}_new (i32.const {len(node.items)}))"
            for item in node.items:
                text = f"(call $l{v}_pushr {text} {self.expr(item, ctx, info, inner)})"
            return text
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
            return f"(call $str_cat {left} {right})"
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
        if operand_type == "str" and op in ("==", "!="):
            eq = f"(call $str_eq {left} {right})"
            return eq if op == "==" else f"(i32.eqz {eq})"
        if op in ("==", "!="):
            # list / 型紙は同一性（Lua のテーブルの == と同じ）
            eq = f"(ref.eq (ref.cast (ref null eq) {left}) (ref.cast (ref null eq) {right}))"
            return eq if op == "==" else f"(i32.eqz {eq})"
        raise CodegenError(f"{operand_type} の比較 {op} は生成できません")

    def name(self, name: str, ctx: _RiteCtx | None, info: CircleInfo | None) -> str:
        if ctx is not None and name in ctx.locals:
            wat, type_text = ctx.locals[name]
            get = f"(local.get {wat})"
            return f"(ref.as_non_null {get})" if _is_ref(self.wtype(type_text)) else get
        if info is not None and name in info.states:
            j, _ = info.states[name]
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
                j, _ = other.states[node.name]
                return (
                    f"(struct.get $S{other.pointer_index} {j} (global.get $P{other.pointer_index}))"
                )
        obj_type = base.type
        if obj_type is None or obj_type not in self.forms:
            raise CodegenError(f"'.{node.name}' の左辺の型紙が分かりません（{obj_type}）")
        k = self.forms[obj_type].index
        j, _ = self.forms[obj_type].fields[node.name]
        return f"(struct.get $F{k} {j} {self.expr(base, ctx, info)})"

    def call(self, node: ex.Call, ctx: _RiteCtx | None, info: CircleInfo | None) -> str:
        callee = node.callee
        if isinstance(callee, ex.Name):
            return self.pure_call(callee.name, node.args, ctx, info)
        if isinstance(callee, ex.FieldAccess) and isinstance(callee.obj, ex.Name):
            sigil = info.sigils.get(callee.obj.name) if info is not None else None
            if sigil is not None and sigil[0] == "host":
                func = _HOST_FUNC.get((sigil[1], callee.name))
                if func is None:
                    raise CodegenError(f"ホスト能力 {sigil[1]}.{callee.name} が分かりません")
                args = " ".join(self.expr(a, ctx, info) for a in node.args)
                return f"(call {func}{' ' + args if args else ''})"
            if sigil is not None:
                raise _later(sigil[0], f"式の中の {callee.obj.name}.{callee.name}")
        raise CodegenError("呼び出せるのは純関数と '名前空間.メンバ' だけです")

    def pure_call(
        self, name: str, args: list[ex.Node], ctx: _RiteCtx | None, info: CircleInfo | None
    ) -> str:
        arg_type = args[0].type if args else None
        if name in _PURE_SIMPLE:
            values = " ".join(self.expr(a, ctx, info) for a in args)
            return f"(call {_PURE_SIMPLE[name]} {values})"
        if name == "len":
            value = self.expr(args[0], ctx, info)
            if arg_type == "str":
                return f"(call $f_len {value})"
            _, inner = parse_type(arg_type or "")
            return f"(call $f_len_{list_variant(inner or '?')} {value})"
        if name == "str":
            value = self.expr(args[0], ctx, info)
            if arg_type == "num":
                return f"(call $f_str {value})"
            if arg_type == "bool":
                return f"(call $f_str_b {value})"
            return value
        if name == "contains":
            value = self.expr(args[0], ctx, info)
            item = self.expr(args[1], ctx, info)
            _, inner = parse_type(arg_type or "")
            if inner == "str":
                return f"(call $f_contains_s {value} {item})"
            return f"(call $f_contains_{list_variant(inner or '?')} {value} {item})"
        raise CodegenError(f"純関数 {name} が分かりません")

    # ---------------------------------------------------------------- 代入先
    def assign(self, target: ex.Node, value: str, ctx: _RiteCtx, indent: int) -> None:
        info = ctx.info
        if isinstance(target, ex.Index):
            obj_type = target.obj.type or ""
            _, inner = parse_type(obj_type)
            v = list_variant(inner or "?")
            obj = self.expr(target.obj, ctx, info)
            idx = self.expr(target.index, ctx, info)
            self.out(f"(call $l{v}_set {obj} {idx} {value})", indent)
            return
        if isinstance(target, ex.Name):
            if target.name in ctx.locals:
                self.out(f"(local.set {ctx.locals[target.name][0]} {value})", indent)
                return
            if target.name in info.states:
                j, _ = info.states[target.name]
                pi = info.pointer_index
                self.out(f"(struct.set $S{pi} {j} (global.get $S{pi}) {value})", indent)
                return
        if isinstance(target, ex.FieldAccess):
            obj_type = target.obj.type
            if obj_type is None or obj_type not in self.forms:
                raise CodegenError(f"'.{target.name}' の左辺の型紙が分かりません（{obj_type}）")
            k = self.forms[obj_type].index
            j, _ = self.forms[obj_type].fields[target.name]
            self.out(f"(struct.set $F{k} {j} {self.expr(target.obj, ctx, info)} {value})", indent)
            return
        raise CodegenError("代入先の形が分かりません")  # pragma: no cover

    # ---------------------------------------------------------------- ステップ
    def new_local(self, ctx: _RiteCtx, name: str | None, type_text: str | None) -> str:
        wat = f"$l{ctx.next_local}"
        ctx.next_local += 1
        ctx.decls.append((wat, _nullable(self.wtype(type_text))))
        if name is not None:
            ctx.locals[name] = (wat, type_text)
        return wat

    def new_raw_local(self, ctx: _RiteCtx, wat_type_text: str) -> str:
        wat = f"$l{ctx.next_local}"
        ctx.next_local += 1
        ctx.decls.append((wat, wat_type_text))
        return wat

    def value(self, node: ex.Node, ctx: _RiteCtx, indent: int, expect: str | None = None) -> str:
        """式の値。添字を含む（エラーし得る）式は局所に置き、フラグを見てから使う。"""
        text = self.expr(node, ctx, ctx.info, expect)
        if not _contains_index(node):
            return text
        tmp = self.new_local(ctx, None, node.type if node.type != ex.LIST_OF_UNKNOWN else expect)
        self.out(f"(local.set {tmp} {text})", indent)
        self.out(f"(if (global.get $ERRED) (then {self.early_return(ctx)}))", indent)
        get = f"(local.get {tmp})"
        return f"(ref.as_non_null {get})" if _is_ref(self.wtype(node.type or expect)) else get

    def steps(self, steps: list[Step], pointer: str, ctx: _RiteCtx, indent: int) -> None:
        for k, step in enumerate(steps):
            self.step(step, f"{pointer}/{k}", ctx, indent)

    def step(self, step: Step, sp: str, ctx: _RiteCtx, indent: int) -> None:
        info = ctx.info
        node = self.program.node
        if isinstance(step, SetStep):
            target = node(f"{sp}/target")
            value = self.value(node(f"{sp}/expr"), ctx, indent, target.type)
            self.assign(target, value, ctx, indent)
            if _contains_index(target):
                # 代入先の添字が範囲外（`set xs[9] = …`）でも ERR は代入の中で立つ。次のステップへ進まない
                self.out(f"(if (global.get $ERRED) (then {self.early_return(ctx)}))", indent)
            return
        if isinstance(step, LetStep):
            value_node = node(f"{sp}/expr")
            value = self.value(value_node, ctx, indent)
            local = self.new_local(ctx, step.name, value_node.type)
            self.out(f"(local.set {local} {value})", indent)
            return
        if isinstance(step, CastStep):
            self.cast(step, sp, ctx, indent)
            return
        if isinstance(step, IfStep):
            cond = self.value(node(f"{sp}/cond"), ctx, indent)
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
            self.out(f"(return {self.value(node(f'{sp}/expr'), ctx, indent)})", indent)
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
        return f"(return {self.default_const(ctx.rite.returns)})"

    def back_edge(self, brk: str, cont: str, indent: int) -> None:
        """ループの戻り辺: 命令数のカウンタを減らし、上限に当たっていたら抜ける（jil.md §6.6）。"""
        self.out("(call $bud)", indent)
        self.out(f"(br_if {brk} (global.get $ERRED))", indent)
        self.out(f"(br {cont})", indent)

    def loop(self, step: LoopStep, sp: str, ctx: _RiteCtx, indent: int) -> None:
        node = self.program.node
        brk = ctx.label("brk")
        cont = ctx.label("loop")
        if step.kind == "while":
            self.out(f"(block {brk}", indent)
            self.out(f"(loop {cont}", indent + 1)
            cond = self.value(node(f"{sp}/cond"), ctx, indent + 2)
            self.out(f"(br_if {brk} (i32.eqz {cond}))", indent + 2)
            ctx.loop_labels.append(brk)
            self.steps(step.steps, f"{sp}/steps", ctx, indent + 2)
            ctx.loop_labels.pop()
            self.back_edge(brk, cont, indent + 2)
            self.out(")", indent + 1)
            self.out(")", indent)
        elif step.kind == "each":
            # Lua の `for i = 1, #list do local item = list[i]`: 長さは最初に 1 度だけ評価する。本文で list が
            # 縮んだら（Lua は nil を読んで後で落ちる）添字が長さを超えた時点で抜ける（既知の差・jil.md §6.4）
            source_node = node(f"{sp}/in")
            source_type = source_node.type or ""
            _, inner = parse_type(source_type) if source_type.startswith("list<") else ("", None)
            if inner is None:
                raise CodegenError(f"loop each の in の型が list ではありません（{source_type}）")
            v = list_variant(inner)
            source = self.value(source_node, ctx, indent)
            lst = self.new_local(ctx, None, source_type)
            count = self.new_raw_local(ctx, "i32")
            index = self.new_raw_local(ctx, "i32")
            item = self.new_local(ctx, step.name or "", inner)
            self.out(f"(local.set {lst} {source})", indent)
            self.out(f"(local.set {count} (call $l{v}_len (local.get {lst})))", indent)
            self.out(f"(local.set {index} (i32.const 0))", indent)
            self.out(f"(block {brk}", indent)
            self.out(f"(loop {cont}", indent + 1)
            self.out(
                f"(br_if {brk} (i32.ge_u (local.get {index}) (local.get {count})))", indent + 2
            )
            self.out(
                f"(br_if {brk} (i32.ge_u (local.get {index}) (call $l{v}_len (local.get {lst}))))",
                indent + 2,
            )
            get = self.cast_elem(f"(call $l{v}_get (local.get {lst}) (local.get {index}))", inner)
            self.out(f"(local.set {item} {get})", indent + 2)
            ctx.loop_labels.append(brk)
            self.steps(step.steps, f"{sp}/steps", ctx, indent + 2)
            ctx.loop_labels.pop()
            self.out(f"(local.set {index} (i32.add (local.get {index}) (i32.const 1)))", indent + 2)
            self.back_edge(brk, cont, indent + 2)
            self.out(")", indent + 1)
            self.out(")", indent)
        else:
            # count: Lua の `for i = 0, math.floor(times) - 1`。回数は f64 のまま比べる（NaN / 巨大な値で
            # i32 に変換すると trap する。NaN は 1 回も回らない・Lua の math.floor(NaN) と同じ）。
            times = self.value(node(f"{sp}/times"), ctx, indent)
            count = self.new_local(ctx, None, "num")
            index = self.new_local(ctx, None, "num")
            self.out(f"(local.set {count} (f64.floor {times}))", indent)
            self.out(f"(local.set {index} (f64.const 0))", indent)
            self.out(f"(block {brk}", indent)
            self.out(f"(loop {cont}", indent + 1)
            self.out(
                f"(br_if {brk} (i32.eqz (f64.lt (local.get {index}) (local.get {count}))))",
                indent + 2,
            )
            if step.name is not None:
                item = self.new_local(ctx, step.name, "num")
                self.out(f"(local.set {item} (local.get {index}))", indent + 2)
            ctx.loop_labels.append(brk)
            self.steps(step.steps, f"{sp}/steps", ctx, indent + 2)
            ctx.loop_labels.pop()
            self.out(f"(local.set {index} (f64.add (local.get {index}) (f64.const 1)))", indent + 2)
            self.back_edge(brk, cont, indent + 2)
            self.out(")", indent + 1)
            self.out(")", indent)
        # 戻り辺で上限に当たって抜けた形（本文のステップは自分で返っている）
        self.out(f"(if (global.get $ERRED) (then {self.early_return(ctx)}))", indent)

    def cast(self, step: CastStep, sp: str, ctx: _RiteCtx, indent: int) -> None:
        info = ctx.info
        node = self.program.node
        arg_nodes = [node(f"{sp}/args/{k}") for k in range(len(step.args))]
        parts = step.target.split(".")
        pi = info.pointer_index
        errcheck = f"(if (global.get $ERRED) (then {self.early_return(ctx)}))"
        if len(parts) == 1 and parts[0] in info.rites:
            j = info.rites[parts[0]]
            rite = info.circle.rites[j - 1]
            args = " ".join(
                self.value(a, ctx, indent, p.type)
                for a, p in zip(arg_nodes, rite.params, strict=True)
            )
            call = f"(call $r{pi}_{j - 1}{' ' + args if args else ''})"
            # 手順の呼び出しにもカウンタを埋める（再帰の無限ループ・jil.md §6.6）
            self.out("(call $bud)", indent)
            self.out(errcheck, indent)
            # Lua と同じ順: 呼ぶ → STOP なら返る → into に代入（STOP はエラーも含む）
            stop = f"(if (i32.or (global.get $ERRED) (i32.ne (global.get $st{pi}) (i32.const 1))) (then {self.early_return(ctx)}))"
            if step.into is not None and rite.returns is not None:
                tmp = self.new_local(ctx, None, rite.returns)
                self.out(f"(local.set {tmp} {call})", indent)
                self.out(stop, indent)
                get = f"(local.get {tmp})"
                if _is_ref(self.wtype(rite.returns)):
                    get = f"(ref.as_non_null {get})"
                self.assign(node(f"{sp}/into"), get, ctx, indent)
                return
            self.out(f"(drop {call})" if rite.returns is not None else call, indent)
            self.out(stop, indent)
            return
        if len(parts) == 1 and parts[0] in info.sigils:
            raise _later(info.sigils[parts[0]][0], f"cast {step.target}")
        if len(parts) == 1:
            # 効果（expr.md §4.2）: push / removeAt / clear。list の要素の表現で関数を選ぶ
            list_type = arg_nodes[0].type or ""
            _, inner = parse_type(list_type) if list_type.startswith("list<") else ("", None)
            if inner is None:
                raise CodegenError(
                    f"効果 {parts[0]} の 1 つ目の引数の型が list ではありません（{list_type}）"
                )
            v = list_variant(inner)
            expected = [list_type, inner] if parts[0] == "push" else [list_type, "num"]
            args = " ".join(
                self.value(a, ctx, indent, t) for a, t in zip(arg_nodes, expected, strict=False)
            )
            func = {"push": f"$e_push_{v}", "removeAt": f"$e_remove_{v}", "clear": f"$e_clear_{v}"}
            self.out(f"(call {func[parts[0]]} {args})", indent)
            self.out(errcheck, indent)
            return
        # ホスト能力（abilities.md）
        sigil = info.sigils.get(parts[0])
        if sigil is None or sigil[0] != "host":
            raise CodegenError(f"'{parts[0]}' は host の sigil ではありません")
        ns = sigil[1]
        member = abilities.namespace(ns).member(parts[1])  # type: ignore[union-attr]
        if member is None:
            raise CodegenError(f"ホスト能力 {ns}.{parts[1]} が分かりません")
        args = " ".join(
            self.value(a, ctx, indent, t)
            for a, (_, t) in zip(arg_nodes, member.params, strict=True)
        )
        call = f"(call {_HOST_FUNC[ns, parts[1]]}{' ' + args if args else ''})"
        if member.returns is not None and step.into is not None:
            tmp = self.new_local(ctx, None, member.returns)
            self.out(f"(local.set {tmp} {call})", indent)
            self.out(errcheck, indent)
            get = f"(local.get {tmp})"
            if _is_ref(self.wtype(member.returns)):
                get = f"(ref.as_non_null {get})"
            self.assign(node(f"{sp}/into"), get, ctx, indent)
            return
        self.out(f"(drop {call})" if member.returns is not None else call, indent)
        self.out(errcheck, indent)

    # ---------------------------------------------------------------- 手順と陣
    def emit_rite(self, info: CircleInfo, rite: Rite, j: int) -> None:
        ctx = _RiteCtx(info=info, rite=rite, locals={})
        params: list[str] = []
        for p in rite.params:
            wat = f"$l{ctx.next_local}"
            ctx.next_local += 1
            ctx.locals[p.name] = (wat, p.type)
            params.append(f"(param {wat} {self.wtype(p.type)})")
        pointer = f"/circles/{info.pointer_index}/rites/{j}"
        result = f" (result {self.wtype(rite.returns)})" if rite.returns is not None else ""
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
            # 末尾まで `return` せずに抜ける手順は Lua では nil を返し、`into` の state が nil になって
            # 次の算術で error 行になる。wasm には nil が無く、黙って既定値を返すと「一致」が汚れるので、
            # 生成の時点で拒む（Sub-Issue ではなく恒久。JIN213 / JIN202 はこの形を落とさない）
            if not _exits(rite.steps):
                raise CodegenError(
                    f"--target wasm-gc: 手順 {info.circle.name}.{rite.name} は returns を持つのに"
                    "末尾まで return / finish せずに抜ける経路があります（Lua では nil が返る形）。"
                    "最後のステップを return にするか、if の両枝で return してください"
                )
            # 静的に抜けることを確かめたので、ここには来ない（型付きの関数の末尾には命令が要る）
            self.out("(unreachable)", 2)
        self.out(")", 1)

    def param_types(self, info: CircleInfo, rite: Rite) -> None:
        for p in rite.params:
            self.wtype(p.type)

    def emit_types(self) -> None:
        """型紙と陣の state の struct（相互参照に備えて 1 つの rec に入れる）。"""
        self.out("(rec", 1)
        for name, info in self.forms.items():
            if info.index == 0:
                continue  # Pointer はランタイム部の $F0
            fields = " ".join(f"(field (mut {self.wtype(t)}))" for _, (_, t) in info.fields.items())
            self.out(
                f"(type $F{info.index} (struct {fields}))  ;; form {name}".replace(
                    "struct )", "struct)"
                ),
                2,
            )
        for info in self.circles.values():
            pi = info.pointer_index
            fields = " ".join(f"(field (mut {self.wtype(s.type)}))" for s in info.circle.state)
            self.out(f"(type $S{pi} (struct {fields}))".replace("struct )", "struct)"), 2)
        self.out(")", 1)

    def emit_circle(self, info: CircleInfo) -> None:
        circle = info.circle
        pi = info.pointer_index
        if circle.flow is not None:
            raise _later("flow", f"陣 {circle.name}（flow）")
        defaults = " ".join(self.default_const(s.type) for s in circle.state)
        new = f"(struct.new $S{pi}{' ' + defaults if defaults else ''})"
        self.out(f";; circle {pi}: {circle.name}", 1)
        self.out(f"(global $S{pi} (mut (ref $S{pi})) {new})", 1)
        self.out(f"(global $P{pi} (mut (ref $S{pi})) {new})", 1)
        self.out(f"(global $st{pi} (mut i32) (i32.const 0))  ;; 0 idle / 1 active / 2 done", 1)
        self.out(f"(global $pubd{pi} (mut i32) (i32.const 0))", 1)
        inits = " ".join(
            self.expr(self.program.node(f"/circles/{pi}/state/{j}/init"), None, None, s.type)
            for j, s in enumerate(circle.state)
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
            self.out("(call $pub_comma)", 2)
            self.out(f"(call $puts (i32.const {off}) (i32.const {length}))", 2)
            self.out(
                f"(call {self.serializer(s.type)} (struct.get $S{pi} {j} (global.get $P{pi})))", 2
            )
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

    def emit_dispatch(self, root: CircleInfo) -> None:
        """`$prog_dispatch`: on key / on pointer / on tick の配達（dispatch_events）。#74 は root だけ（ORDER = [root]）。"""
        circle = root.circle
        pi = root.pointer_index
        handlers = {on.event: on.rite for on in (circle.boundary.on if circle.boundary else [])}
        for event, rite_name in handlers.items():
            if event not in ("key", "pointer", "tick"):
                raise _later("emit" if event == "message" else "flow", f"on {event}")
            if root.waits[rite_name]:
                raise _later("wait", f"on {event} の手順 {rite_name}（wait を含む）")
        self.out("(func $prog_dispatch", 1)
        if not handlers:
            self.out(")", 1)
            return
        self.out("(local $k i32) (local $n i32)", 2)
        stop = f"(i32.or (global.get $ERRED) (i32.ne (global.get $st{pi}) (i32.const 1)))"

        def invoke(rite_name: str, args: list[str]) -> str:
            # Lua は余分な引数を捨てる: 手順が宣言した数だけ渡す（dt を受けない on tick など）
            j = root.rites[rite_name] - 1
            rite = circle.rites[j]
            passed = " ".join(args[: len(rite.params)])
            call = f"(call $r{pi}_{j}{' ' + passed if passed else ''})"
            return f"(drop {call})" if rite.returns is not None else call

        if "key" in handlers or "pointer" in handlers:
            self.out("(local.set $n (call $ev_count))", 2)
            self.out("(block $done (loop $next", 2)
            self.out("(br_if $done (i32.ge_u (local.get $k) (local.get $n)))", 3)
            self.out(f"(br_if $done {stop})", 3)
            if "key" in handlers:
                self.out(
                    "(if (i32.eq (call $ev_kind (local.get $k)) (i32.const 1)) (then "
                    + invoke(
                        handlers["key"],
                        ["(call $ev_name (local.get $k))", "(call $ev_down (local.get $k))"],
                    )
                    + "))",
                    3,
                )
            if "pointer" in handlers:
                self.out(
                    "(if (i32.eq (call $ev_kind (local.get $k)) (i32.const 2)) (then "
                    + invoke(handlers["pointer"], ["(call $ev_pointer (local.get $k))"])
                    + "))",
                    3,
                )
            self.out("(local.set $k (i32.add (local.get $k) (i32.const 1)))", 3)
            self.out("(br $next)))", 3)
        if "tick" in handlers:
            self.out(
                f"(if (i32.eqz {stop}) (then "
                + invoke(handlers["tick"], ["(f64.div (f64.const 1) (global.get $FPS))"])
                + "))",
                2,
            )
        self.out(")", 1)

    # ---------------------------------------------------------------- 全体
    def program_part(self) -> str:
        model = self.model
        for info in self.circles.values():
            if info.circle.core is None:
                raise _later("flow", f"陣 {info.circle.name}（flow）")
            for sigil in info.circle.sigils:
                if sigil.kind != "host":
                    raise _later(sigil.kind, f"陣 {info.circle.name} の sigil {sigil.name}")
            if (
                info.circle.boundary is not None
                and info.circle.boundary.on
                and info.pointer_index != self.circles[model.root].pointer_index
            ):
                raise _later("flow", f"陣 {info.circle.name} の on（root 以外の陣の配達）")
        root = self.circles[model.root]
        self.emit_types()
        self.emit_form_serializers()
        for info in self.circles.values():
            for j, rite in enumerate(info.circle.rites):
                self.emit_rite(info, rite, j)
        for info in self.circles.values():
            self.emit_circle(info)
        self.emit_dispatch(root)
        indices = [info.pointer_index for info in self.circles.values()]
        self.out(f"(global $ROOT i32 (i32.const {root.pointer_index}))", 1)
        self.out(f"(global $FPS f64 (f64.const {wat_number(model.stage.fps)}))", 1)
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
        # list の直列化（型ごとに 1 つ）
        self.lines.extend(self.serializer_lines)
        # 式の文字列リテラル（passive）
        for i, raw in enumerate(self.lits.items):
            self.out(f"(data $L{i} {wat_string(raw.decode('utf-8'))})", 1)
        # data 区画と線形メモリ（runtime.wat の配置に合わせる）
        for off, raw in self.data.chunks:
            self.out(f"(data (i32.const {off}) {wat_string(raw.decode('utf-8'))})", 1)
        in_base = (self.data.end + 15) // 16 * 16
        pages = (in_base + 2 * _PAGE + _PAGE - 1) // _PAGE
        self.out(f"(global $in_base i32 (i32.const {in_base}))", 1)
        self.out(f'(memory (export "memory") {pages})', 1)
        return "\n".join(self.lines) + "\n"


def _exits(steps: list[Step]) -> bool:
    """ステップ列が必ず抜ける（最後が `return` / `finish` / `transfer`、または両枝が抜ける `if`）か。"""
    if not steps:
        return False
    last = steps[-1]
    if isinstance(last, (ReturnStep, FinishStep, TransferStep)):
        return True
    if isinstance(last, IfStep):
        return _exits(last.then) and _exits(last.else_)
    return False


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


__all__ = [
    "DATA_BASE",
    "generate_program",
    "header",
    "list_variant",
    "wat_number",
    "wat_string",
    "wat_type",
]
