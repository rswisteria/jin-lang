"""`JinFileV2` → WAT の生成部（docs/spec/v2/jil.md §6.3〜§6.5・設計書 §11 #56）。

解析（型付き AST・添字・`wait` の閉包・manifest の共通部）は `jin_wasm.program` から読む。
ここは wasm-GC のテキスト形式（WAT）を出す側だけで、Lua を出す `jin_wasm.codegen` と同じ解析を共有する。

## 名前の写像（jil.md §6.3）

`.jin` の名前を WAT の識別子に**埋め込まない**。陣 i（0 始まり）の state は `(type $S<i>)` の
struct で欄は宣言順の添字、確定値は同じ型の `$P<i>`、手順は `$r<i>_<j>`（`wait` を含む手順は
`$r<i>_<j>w` とフレーム `$W<i>_<j>`）、局所は `$l<n>`（手順ごとの通し番号）、型紙 k は `$F<k>`
（`$F0` はランタイム部の Pointer）。名前は data 区画の文字列（公開 state の鍵 / 型紙の欄の鍵 /
陣名 / トレース行の name と pointer）にだけ載る。

## 値の表現（jil.md §6.3）

`num` = `f64`、`bool` = `i32`、`str` = `(ref $str)`（UTF-8 の `array i8`・作ったら書き換えない）、
`list<num>` / `list<bool>` / それ以外の list = ランタイム部の `$Lf` / `$Li` / `$Lr`（`$Lr` の要素は
`anyref` で、読むときに要素の型へ `ref.cast`）、型紙 = `(ref $F<k>)` の struct。式の文字列リテラルは
passive の data（`(data $L<i> "…")`）から `array.new_data` で作る。

## スケジューラとの分担（jil.md §6.4〜§6.5・Issue #75）

陣の生存（status / paused / pending / cursor / delegate / published）と tick の手順（配達 / 再開 /
イベント / 確定 / 検査 / 進行）はランタイム部（`runtime.wat`）が陣の添字で持つ。生成部は「添字 → 陣ごとの
関数」の振り分け（`$prog_flow` / `$prog_init` / `$prog_core` / `$prog_on_*` / `$prog_deliver` / …。
一覧は `runtime.wat` の先頭）を出す。

## `wait` の状態機械（jil.md §6.5）

`wait` に到達しうる手順（`jin_wasm.program.rite_waits` の閉包）だけを変換する。局所変数と再開点 `pc` を
フレーム `$W<i>_<j>` の struct に持ち上げ、手順の関数 `$r<i>_<j>w(frame) -> 中断したか` は毎 tick
**先頭から早送り**して再開点まで進む（構造化制御では loop の途中へ飛べない）: 早送り中（`$rs`）は
`if` の cond を評価せず再開点を含む枝へ、loop のヘッダで回数 / 添字を再初期化せず、`each` の item を
読み直さない。自陣の待つ手順への `cast` は呼び先のフレームを呼び元のフレームに保持し、戻り値は
フレームの欄で受ける（tick を跨げる）。`until` の式は最も内側のフレームで評価する（`$u<n>`）。

## エラー機構（jil.md §6.4）

wasm に例外は使わない。ランタイム部の `$ERR` がフラグ `$ERRED` を立てるので、生成部は**エラーし得る
ステップの後**（添字を含む式・cast・ループ）と手順の呼び出しの後にフラグを見て返る（Lua の error が
手順を抜ける形の写し）。ループの戻り辺と手順の呼び出しには命令数のカウンタ `$bud` を埋める（§6.6）。

## トレース（DEBUG のときだけ生成する・runtime.md §5）

`set` / `cast` / `rite` / `event` / `transfer` / `finish` / `assert` の行は生成部が積み（`$row`）、
`enter` / `exit` / `emit` / `wait` / `error` / `frame` はランタイム部が積む。リリースビルドは 1 行も
生成せず、表示リストは同じ。

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

#: トレース行の kind（`runtime.wat` の `$kind_str` と 1:1）。
_KIND = {
    "enter": 0,
    "exit": 1,
    "event": 2,
    "rite": 3,
    "cast": 4,
    "set": 5,
    "emit": 6,
    "transfer": 7,
    "wait": 8,
    "finish": 9,
    "assert": 10,
    "error": 11,
    "frame": 12,
}

#: `on` の種類（`runtime.wat` の `$prog_has_on` の kind）。
_ON_KIND = {"key": 1, "pointer": 2, "tick": 3, "exit": 4, "message": 5}

#: flow の種類（`$prog_flow`）。
_FLOW_KIND = {"sequence": 1, "parallel": 2, "loop": 3}


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
    """手順 1 つの生成の文脈。`frame` が無ければ局所は wasm の local、あればフレーム（struct）の欄。"""

    info: CircleInfo
    returns: str | None
    locals: dict[str, tuple[str, str | None]]  # 局所名 → ($l<n>, 型)
    decls: list[tuple[str, str]] = field(default_factory=list)  # ($l<n>, WAT の型)
    slots: dict[str, int] = field(default_factory=dict)  # フレームの欄の添字
    next_local: int = 0
    next_label: int = 0
    loop_labels: list[str] = field(default_factory=list)  # break の飛び先（内側が末尾）
    frame: str | None = None  # `$W<i>_<j>`（wait を含む手順）
    next_pc: int = 0  # 中断点の番号（1 始まり。0 は先頭）
    until_fn: bool = False  # until の式の関数（早い return は 0）
    rite_row: str | None = None  # DEBUG の rite 行（return で output を埋める）

    def label(self, stem: str) -> str:
        self.next_label += 1
        return f"${stem}{self.next_label}"

    def pc(self) -> int:
        self.next_pc += 1
        return self.next_pc


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


def _json_string(text: str) -> str:
    """名前（識別子の文法なのでエスケープ不要）を JSON 文字列にする。"""
    return f'"{text}"'


class _Generator:
    def __init__(self, program: Program, *, debug: bool) -> None:
        self.program = program
        self.debug = debug
        self.model = program.model
        self.circles = program.circles
        self.forms: dict[str, FormInfo] = program.forms
        self.data = _Data()
        self.lits = _Literals()
        self.lines: list[str] = []
        self.serializers: dict[str, str] = {}  # 型 → 直列化関数の名前
        self.serializer_lines: list[str] = []
        self.readers: dict[str, str] = {}  # 型 → resume の読み手の名前
        self.reader_lines: list[str] = []
        self.frame_types: list[str] = []  # (type $W…) / (type $M…)
        self.waiting: list[tuple[int, int]] = []  # 手順の番号 → (陣, 手順)
        self.untils: list[tuple[str, str]] = []  # until の式の番号 → (関数名, フレーム型)
        self.emit_sites: list[str] = []  # emit の場所 → $dlv<n>
        self.ask_sites: list[str] = []  # agent の cast の場所 → $rpl<n>
        self.frame_of: dict[tuple[int, int], str] = {}
        for info in self.circles.values():
            for j, rite in enumerate(info.circle.rites):
                if info.waits[rite.name]:
                    self.frame_of[info.pointer_index, j] = f"$W{info.pointer_index}_{j}"

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

    def dstr(self, text: str) -> str:
        """data 区画の文字列を str にする式（名前 / pointer など）。"""
        off, length = self.data.put(text)
        return f"(call $mem_str (i32.const {off}) (i32.const {length}))"

    def puts(self, text: str) -> str:
        off, length = self.data.put(text)
        return f"(call $puts (i32.const {off}) (i32.const {length}))"

    # ---------------------------------------------------------------- 直列化（公開 state / トレースの JSON）
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
                self.out(self.puts(("," if pos else "") + f'"{field_name}":'), 2)
                self.out(
                    f"(call {self.serializer(type_text)} (struct.get $F{k} {j} (local.get $v)))", 2
                )
            self.out("(call $putc (i32.const 125)))", 2)
            if self.debug:
                self.emit_form_reader(name, info)

    # ---------------------------------------------------------------- resume の読み手（DEBUG・runtime.md §1.3）
    def reader(self, type_text: str) -> str:
        """JSON（`$J`）を型どおりの値にする関数の名前（合わなければ `$RD_OK` を 0 に）。"""
        head, inner = parse_type(type_text)
        if head == "num":
            return "$rd_n"
        if head == "bool":
            return "$rd_b"
        if head == "str":
            return "$rd_s"
        if type_text in self.readers:
            return self.readers[type_text]
        if head == "list":
            assert inner is not None
            name = f"$rl{len(self.readers)}"
            self.readers[type_text] = name
            v = list_variant(inner)
            item = self.reader(inner)
            elem = self.wtype(inner)
            got = "(ref.as_non_null (local.get $x))" if _is_ref(elem) else "(local.get $x)"
            # RL: table でなければ null。要素の読みが 1 つでも合わなければ全体を null（JSON の object は空の list）
            self.reader_lines.extend(
                [
                    f"  (func {name} (param $v (ref null $J)) (result (ref null $L{v}))  ;; {type_text}",
                    f"    (local $k i32) (local $n i32) (local $l (ref null $L{v})) (local $x {_nullable(elem)})",
                    "    (if (i32.eqz (call $rd_rec (local.get $v)))",
                    f"      (then (global.set $RD_OK (i32.const 0)) (return (ref.null $L{v}))))",
                    "    (local.set $n (call $j_len (local.get $v)))",
                    f"    (local.set $l (call $l{v}_new (local.get $n)))",
                    "    (block $done (loop $next",
                    "      (br_if $done (i32.ge_u (local.get $k) (local.get $n)))",
                    f"      (local.set $x (call {item} (call $j_at (local.get $v) (local.get $k))))",
                    f"      (if (i32.eqz (global.get $RD_OK)) (then (return (ref.null $L{v}))))",
                    f"      (call $l{v}_push (local.get $l) {got})",
                    "      (local.set $k (i32.add (local.get $k) (i32.const 1)))",
                    "      (br $next)))",
                    "    (global.set $RD_OK (i32.const 1))",
                    "    (local.get $l))",
                ]
            )
            return name
        name = f"$jr{self.form_index(head)}"
        self.readers[type_text] = name
        return name

    def emit_form_reader(self, name: str, info: FormInfo) -> None:
        """`$jr<k>`: 型紙 k の読み手（欄が 1 つでも合わなければ null・`$RD_OK` = 0）。"""
        k = info.index
        self.out(f"(func $jr{k} (param $v (ref null $J)) (result (ref null $F{k}))  ;; {name}", 1)
        decls = " ".join(
            f"(local $f{j} {_nullable(self.wtype(t))})" for _, (j, t) in info.fields.items()
        )
        if decls:
            self.out(decls, 2)
        self.out(
            f"(if (i32.eqz (call $rd_rec (local.get $v))) (then (global.set $RD_OK (i32.const 0)) (return (ref.null $F{k}))))",
            2,
        )
        for field_name, (j, t) in info.fields.items():
            off, length = self.data.put(field_name)
            self.out(
                f"(local.set $f{j} (call {self.reader(t)} (call $j_getk (local.get $v) (i32.const {off}) (i32.const {length}))))",
                2,
            )
            self.out(f"(if (i32.eqz (global.get $RD_OK)) (then (return (ref.null $F{k}))))", 2)
        values = " ".join(
            f"(ref.as_non_null (local.get $f{j}))"
            if _is_ref(self.wtype(t))
            else f"(local.get $f{j})"
            for _, (j, t) in info.fields.items()
        )
        self.out("(global.set $RD_OK (i32.const 1))", 2)
        self.out(f"(struct.new $F{k}{' ' + values if values else ''}))", 2)

    # ---------------------------------------------------------------- 局所（wasm の local かフレームの欄）
    def get(self, ctx: _RiteCtx, handle: str) -> str:
        if ctx.frame is None:
            return f"(local.get {handle})"
        return f"(struct.get {ctx.frame} {ctx.slots[handle]} (local.get $fr))"

    def setv(self, ctx: _RiteCtx, handle: str, value: str) -> str:
        if ctx.frame is None:
            return f"(local.set {handle} {value})"
        return f"(struct.set {ctx.frame} {ctx.slots[handle]} (local.get $fr) {value})"

    def new_local(self, ctx: _RiteCtx, name: str | None, type_text: str | None) -> str:
        return self.new_raw_local(ctx, _nullable(self.wtype(type_text)), name, type_text)

    def new_raw_local(
        self,
        ctx: _RiteCtx,
        wat_type_text: str,
        name: str | None = None,
        type_text: str | None = None,
    ) -> str:
        wat = f"$l{ctx.next_local}"
        ctx.next_local += 1
        ctx.decls.append((wat, wat_type_text))
        if ctx.frame is not None:
            ctx.slots[wat] = len(ctx.decls)  # 欄 0 は pc（returns があれば 1 は戻り値）
            if ctx.returns is not None:
                ctx.slots[wat] += 1
        if name is not None:
            ctx.locals[name] = (wat, type_text)
        return wat

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
            get = self.get(ctx, wat)
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
    def assign(self, target: ex.Node, value: str, ctx: _RiteCtx, sp: str, indent: int) -> None:
        """`target = value` を出し、根が state なら set 行（DEBUG）を続ける。"""
        info = ctx.info
        if isinstance(target, ex.Index):
            obj_type = target.obj.type or ""
            _, inner = parse_type(obj_type)
            v = list_variant(inner or "?")
            obj = self.expr(target.obj, ctx, info)
            idx = self.expr(target.index, ctx, info)
            self.out(f"(call $l{v}_set {obj} {idx} {value})", indent)
        elif isinstance(target, ex.Name) and target.name in ctx.locals:
            self.out(self.setv(ctx, ctx.locals[target.name][0], value), indent)
        elif isinstance(target, ex.Name) and target.name in info.states:
            j, _ = info.states[target.name]
            pi = info.pointer_index
            self.out(f"(struct.set $S{pi} {j} (global.get $S{pi}) {value})", indent)
        elif isinstance(target, ex.FieldAccess):
            obj_type = target.obj.type
            if obj_type is None or obj_type not in self.forms:
                raise CodegenError(f"'.{target.name}' の左辺の型紙が分かりません（{obj_type}）")
            k = self.forms[obj_type].index
            j, _ = self.forms[obj_type].fields[target.name]
            self.out(f"(struct.set $F{k} {j} {self.expr(target.obj, ctx, info)} {value})", indent)
        else:
            raise CodegenError("代入先の形が分かりません")  # pragma: no cover
        root = ex.place_root(target)
        if (
            self.debug
            and root is not None
            and root.name in info.states
            and root.name not in ctx.locals
        ):
            j, type_text = info.states[root.name]
            pi = info.pointer_index
            value_json = self.json_of(
                ctx,
                indent,
                [
                    f"(call {self.serializer(type_text)} (struct.get $S{pi} {j} (global.get $S{pi})))"
                ],
            )
            self.out(
                self.row(
                    "set", pi, self.dstr(root.name), self.dstr(sp), "(ref.null $str)", value_json
                ),
                indent,
            )

    # ---------------------------------------------------------------- トレース行の補助（DEBUG）
    def row(self, kind: str, ci: int, name: str, ptr: str, input_: str, output: str) -> str:
        """`$row` を呼ぶ文（戻り値は捨てる）。"""
        return f"(drop (call $row (i32.const {_KIND[kind]}) (i32.const {ci}) {name} {ptr} {input_} {output}))"

    def json_of(self, ctx: _RiteCtx, indent: int, puts: list[str]) -> str:
        """書き手を一時 buf に向けて `puts` を並べ、できた JSON の str を返す式（直後の文で使う）。"""
        self.out("(local.set $ob (call $fmt_begin))", indent)
        for text in puts:
            self.out(text, indent)
        return "(call $fmt_end (local.get $ob))"

    def json_array(self, ctx: _RiteCtx, indent: int, items: list[str]) -> str:
        """`[a,b,…]` の JSON（items は書き手への呼び出し）。"""
        puts = ["(call $putc (i32.const 91))"]
        for k, item in enumerate(items):
            if k:
                puts.append("(call $putc (i32.const 44))")
            puts.append(item)
        puts.append("(call $putc (i32.const 93))")
        return self.json_of(ctx, indent, puts)

    # ---------------------------------------------------------------- ステップ
    def value(self, node: ex.Node, ctx: _RiteCtx, indent: int, expect: str | None = None) -> str:
        """式の値。添字を含む（エラーし得る）式は局所に置き、フラグを見てから使う。"""
        text = self.expr(node, ctx, ctx.info, expect)
        if not _contains_index(node):
            return text
        tmp = self.new_local(ctx, None, node.type if node.type != ex.LIST_OF_UNKNOWN else expect)
        self.out(self.setv(ctx, tmp, text), indent)
        self.out(f"(if (global.get $ERRED) (then {self.early_return(ctx)}))", indent)
        get = self.get(ctx, tmp)
        return f"(ref.as_non_null {get})" if _is_ref(self.wtype(node.type or expect)) else get

    def early_return(self, ctx: _RiteCtx) -> str:
        if ctx.frame is not None or ctx.until_fn:
            return "(return (i32.const 0))"
        if ctx.returns is None:
            return "(return)"
        return f"(return {self.default_const(ctx.returns)})"

    def suspends(self, step: Step, ctx: _RiteCtx) -> bool:
        """ステップが中断点（wait・自陣の待つ手順への cast）を含むか（wait を含む手順の中でだけ意味を持つ）。"""
        if isinstance(step, WaitStep):
            return True
        if isinstance(step, CastStep):
            parts = step.target.split(".")
            return len(parts) == 1 and parts[0] in ctx.info.rites and ctx.info.waits[parts[0]]
        if isinstance(step, IfStep):
            return any(self.suspends(s, ctx) for s in [*step.then, *step.else_])
        if isinstance(step, LoopStep):
            return any(self.suspends(s, ctx) for s in step.steps)
        return False

    def steps(self, steps: list[Step], pointer: str, ctx: _RiteCtx, indent: int) -> None:
        if ctx.frame is None:
            for k, step in enumerate(steps):
                self.step(step, f"{pointer}/{k}", ctx, indent)
            return
        # 早送り中（$rs）は中断点を含まないステップをまとめて飛ばす
        group: list[tuple[int, Step]] = []

        def flush() -> None:
            if not group:
                return
            self.out("(if (i32.eqz (local.get $rs))", indent)
            self.out("(then", indent + 1)
            for k, step in group:
                self.step(step, f"{pointer}/{k}", ctx, indent + 2)
            self.out("))", indent + 1)
            group.clear()

        for k, step in enumerate(steps):
            if self.suspends(step, ctx):
                flush()
                self.step(step, f"{pointer}/{k}", ctx, indent)
            else:
                group.append((k, step))
        flush()

    def pc_in(self, ctx: _RiteCtx, lo: int, hi: int) -> str:
        """再開点が (lo, hi] にあるか（フレームの pc）。"""
        pc = f"(struct.get {ctx.frame} 0 (local.get $fr))"
        return f"(i32.and (i32.gt_s {pc} (i32.const {lo})) (i32.le_s {pc} (i32.const {hi})))"

    def step(self, step: Step, sp: str, ctx: _RiteCtx, indent: int) -> None:
        info = ctx.info
        node = self.program.node
        pi = info.pointer_index
        if isinstance(step, SetStep):
            target = node(f"{sp}/target")
            value = self.value(node(f"{sp}/expr"), ctx, indent, target.type)
            self.assign(target, value, ctx, sp, indent)
            if _contains_index(target):
                # 代入先の添字が範囲外（`set xs[9] = …`）でも ERR は代入の中で立つ。次のステップへ進まない
                self.out(f"(if (global.get $ERRED) (then {self.early_return(ctx)}))", indent)
            return
        if isinstance(step, LetStep):
            value_node = node(f"{sp}/expr")
            value = self.value(value_node, ctx, indent)
            local = self.new_local(ctx, step.name, value_node.type)
            self.out(self.setv(ctx, local, value), indent)
            return
        if isinstance(step, CastStep):
            self.cast(step, sp, ctx, indent)
            return
        if isinstance(step, IfStep):
            if ctx.frame is not None and self.suspends(step, ctx):
                self.if_resumable(step, sp, ctx, indent)
                return
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
            self.wait(step, sp, ctx, indent)
            return
        if isinstance(step, EmitStep):
            self.emit_step(step, sp, ctx, indent)
            return
        if isinstance(step, ReturnStep):
            if step.expr is None:
                self.out(self.early_return(ctx) if ctx.frame is not None else "(return)", indent)
                return
            value = self.value(node(f"{sp}/expr"), ctx, indent)
            assert ctx.returns is not None
            tmp = self.new_local(ctx, None, ctx.returns)
            self.out(self.setv(ctx, tmp, value), indent)
            got = self.get(ctx, tmp)
            if _is_ref(self.wtype(ctx.returns)):
                got = f"(ref.as_non_null {got})"
            if self.debug and ctx.rite_row is not None:
                out_json = self.json_of(
                    ctx, indent, [f"(call {self.serializer(ctx.returns)} {got})"]
                )
                self.out(f"(call $row_out {self.get(ctx, ctx.rite_row)} {out_json})", indent)
            if ctx.frame is not None:
                self.out(f"(struct.set {ctx.frame} 1 (local.get $fr) {got})", indent)
                self.out("(return (i32.const 0))", indent)
            else:
                self.out(f"(return {got})", indent)
            return
        if isinstance(step, FinishStep):
            if self.debug:
                self.out(
                    self.row(
                        "finish",
                        pi,
                        "(ref.null $str)",
                        self.dstr(sp),
                        "(ref.null $str)",
                        "(ref.null $str)",
                    ),
                    indent,
                )
            self.out(f"(call $finish (i32.const {pi}))", indent)
            self.out(self.early_return(ctx), indent)
            return
        if isinstance(step, TransferStep):
            target = self.circles[step.circle]
            if self.debug:
                self.out(
                    self.row(
                        "transfer",
                        pi,
                        self.dstr(step.circle),
                        self.dstr(sp),
                        self.dstr(_json_string(step.circle)),
                        "(ref.null $str)",
                    ),
                    indent,
                )
            self.out(
                f"(call $transfer (i32.const {pi}) (i32.const {target.pointer_index}))", indent
            )
            self.out(self.early_return(ctx), indent)
            return
        raise CodegenError(type(step).__name__)  # pragma: no cover

    def if_resumable(self, step: IfStep, sp: str, ctx: _RiteCtx, indent: int) -> None:
        """中断点を含む `if`（wait を含む手順）: 早送り中は cond を評価せず再開点を含む枝へ。"""
        node = self.program.node
        cv = self.new_raw_local(ctx, "i32")
        # 枝を先に生成して、その枝が持つ中断点の番号の範囲を知る（番号は生成順に連続）
        lo = ctx.next_pc
        start = len(self.lines)
        self.steps(step.then, f"{sp}/then", ctx, indent + 2)
        then_lines = self.lines[start:]
        del self.lines[start:]
        hi = ctx.next_pc
        start = len(self.lines)
        if step.else_:
            self.steps(step.else_, f"{sp}/else", ctx, indent + 2)
        else_lines = self.lines[start:]
        del self.lines[start:]
        self.out("(if (local.get $rs)", indent)
        self.out(f"(then {self.setv(ctx, cv, self.pc_in(ctx, lo, hi))})", indent + 1)
        self.out("(else", indent + 1)
        cond = self.value(node(f"{sp}/cond"), ctx, indent + 2)
        self.out(self.setv(ctx, cv, cond), indent + 2)
        self.out("))", indent + 1)
        self.out(f"(if {self.get(ctx, cv)}", indent)
        self.out("(then", indent + 1)
        self.lines.extend(then_lines)
        self.out(")", indent + 1)
        if step.else_:
            self.out("(else", indent + 1)
            self.lines.extend(else_lines)
            self.out(")", indent + 1)
        self.out(")", indent)

    def wait(self, step: WaitStep, sp: str, ctx: _RiteCtx, indent: int) -> None:
        if ctx.frame is None:
            raise CodegenError("wait を含む手順が待つ手順の閉包に無い")  # pragma: no cover
        node = self.program.node
        w = ctx.pc()
        pc = f"(struct.get {ctx.frame} 0 (local.get $fr))"
        self.out("(if (local.get $rs)", indent)
        self.out(
            f"(then (if (i32.eq {pc} (i32.const {w})) (then (local.set $rs (i32.const 0)))))",
            indent + 1,
        )
        self.out("(else", indent + 1)
        if step.ticks is not None:
            ticks = self.value(node(f"{sp}/ticks"), ctx, indent + 2)
            self.out("(global.set $WREQ_KIND (i32.const 1))", indent + 2)
            self.out(f"(global.set $WREQ_TICKS (call $wait_ticks_of {ticks}))", indent + 2)
        else:
            uid = len(self.untils)
            fn = f"$u{uid}"
            self.untils.append((fn, ctx.frame))
            self.emit_until(fn, node(f"{sp}/until"), ctx)
            self.out("(global.set $WREQ_KIND (i32.const 2))", indent + 2)
            self.out(f"(global.set $WREQ_UID (i32.const {uid}))", indent + 2)
        self.out(f"(global.set $WREQ_PTR {self.dstr(sp)})", indent + 2)
        self.out("(global.set $WREQ_TOP (local.get $fr))", indent + 2)
        self.out(f"(struct.set {ctx.frame} 0 (local.get $fr) (i32.const {w}))", indent + 2)
        self.out("(return (i32.const 1))))", indent + 2)

    def emit_until(self, fn: str, cond: ex.Node, ctx: _RiteCtx) -> None:
        """`$u<n>(frame) -> bool`: until の式を最も内側のフレームで評価する（局所はフレームの欄）。"""
        sub = _RiteCtx(
            info=ctx.info,
            returns=ctx.returns,
            locals=ctx.locals,
            decls=ctx.decls,
            slots=ctx.slots,
            next_local=ctx.next_local,
            frame=ctx.frame,
            until_fn=True,
        )
        start = len(self.lines)
        value = self.value(cond, sub, 2)
        body = self.lines[start:]
        del self.lines[start:]
        ctx.next_local = sub.next_local  # 一時変数はフレームの欄として足された
        self.frame_fns.extend(
            [
                f"  (func {fn} (param $fr (ref {ctx.frame})) (result i32)",
                "    (local $ob (ref null $buf))",
                *body,
                f"    {value})",
            ]
        )

    def back_edge(self, brk: str, cont: str, indent: int) -> None:
        """ループの戻り辺: 命令数のカウンタを減らし、上限に当たっていたら抜ける（jil.md §6.6）。"""
        self.out("(call $bud)", indent)
        self.out(f"(br_if {brk} (global.get $ERRED))", indent)
        self.out(f"(br {cont})", indent)

    def guard_rs(self, ctx: _RiteCtx, indent: int, body: list[str]) -> None:
        """wait を含む手順では早送り中に飛ばす文（ループのヘッダなど）。"""
        if ctx.frame is None or not body:
            for text in body:
                self.out(text, indent)
            return
        self.out("(if (i32.eqz (local.get $rs))", indent)
        self.out("(then", indent + 1)
        for text in body:
            self.out(text, indent + 2)
        self.out("))", indent + 1)

    def loop(self, step: LoopStep, sp: str, ctx: _RiteCtx, indent: int) -> None:
        resumable = ctx.frame is not None and self.suspends(step, ctx)
        if not resumable:
            self.loop_body(step, sp, ctx, indent)
            return
        # 早送り中は、再開点がこの loop の中に無ければ loop ごと飛ばす（ヘッダの検査を飛ばすので、入ると
        # 抜けられない）。再開点の番号は生成順に連続するので、本文を先に生成して範囲を知る
        lo = ctx.next_pc
        start = len(self.lines)
        self.loop_body(step, sp, ctx, indent + 2)
        body = self.lines[start:]
        del self.lines[start:]
        hi = ctx.next_pc
        self.out(f"(if (i32.or (i32.eqz (local.get $rs)) {self.pc_in(ctx, lo, hi)})", indent)
        self.out("(then", indent + 1)
        self.lines.extend(body)
        self.out("))", indent + 1)

    def loop_body(self, step: LoopStep, sp: str, ctx: _RiteCtx, indent: int) -> None:
        node = self.program.node
        brk = ctx.label("brk")
        cont = ctx.label("loop")
        resumable = ctx.frame is not None and self.suspends(step, ctx)
        if step.kind == "while":
            self.out(f"(block {brk}", indent)
            self.out(f"(loop {cont}", indent + 1)
            if resumable:
                self.out("(if (i32.eqz (local.get $rs))", indent + 2)
                self.out("(then", indent + 3)
                cond = self.value(node(f"{sp}/cond"), ctx, indent + 4)
                self.out(f"(br_if {brk} (i32.eqz {cond}))", indent + 4)
                self.out("))", indent + 3)
            else:
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
            start = len(self.lines)
            source = self.value(source_node, ctx, indent + (2 if resumable else 0))
            pre = self.lines[start:]
            del self.lines[start:]
            lst = self.new_local(ctx, None, source_type)
            count = self.new_raw_local(ctx, "i32")
            index = self.new_raw_local(ctx, "i32")
            item = self.new_local(ctx, step.name or "", inner)
            self.guard_rs(
                ctx,
                indent,
                [
                    *[line.strip() for line in pre],
                    self.setv(ctx, lst, source),
                    self.setv(ctx, count, f"(call $l{v}_len {self.get(ctx, lst)})"),
                    self.setv(ctx, index, "(i32.const 0)"),
                ],
            )
            self.out(f"(block {brk}", indent)
            self.out(f"(loop {cont}", indent + 1)
            get = self.cast_elem(
                f"(call $l{v}_get {self.get(ctx, lst)} {self.get(ctx, index)})", inner
            )
            self.guard_rs(
                ctx,
                indent + 2,
                [
                    f"(br_if {brk} (i32.ge_u {self.get(ctx, index)} {self.get(ctx, count)}))",
                    f"(br_if {brk} (i32.ge_u {self.get(ctx, index)} (call $l{v}_len {self.get(ctx, lst)})))",
                    self.setv(ctx, item, get),
                ],
            )
            ctx.loop_labels.append(brk)
            self.steps(step.steps, f"{sp}/steps", ctx, indent + 2)
            ctx.loop_labels.pop()
            self.out(
                self.setv(ctx, index, f"(i32.add {self.get(ctx, index)} (i32.const 1))"), indent + 2
            )
            self.back_edge(brk, cont, indent + 2)
            self.out(")", indent + 1)
            self.out(")", indent)
        else:
            # count: Lua の `for i = 0, math.floor(times) - 1`。回数は f64 のまま比べる（NaN / 巨大な値で
            # i32 に変換すると trap する。NaN は 1 回も回らない・Lua の math.floor(NaN) と同じ）。
            start = len(self.lines)
            times = self.value(node(f"{sp}/times"), ctx, indent + (2 if resumable else 0))
            pre = self.lines[start:]
            del self.lines[start:]
            count = self.new_local(ctx, None, "num")
            index = self.new_local(ctx, None, "num")
            self.guard_rs(
                ctx,
                indent,
                [
                    *[line.strip() for line in pre],
                    self.setv(ctx, count, f"(f64.floor {times})"),
                    self.setv(ctx, index, "(f64.const 0)"),
                ],
            )
            self.out(f"(block {brk}", indent)
            self.out(f"(loop {cont}", indent + 1)
            header = [
                f"(br_if {brk} (i32.eqz (f64.lt {self.get(ctx, index)} {self.get(ctx, count)})))"
            ]
            if step.name is not None:
                item = self.new_local(ctx, step.name, "num")
                header.append(self.setv(ctx, item, self.get(ctx, index)))
            self.guard_rs(ctx, indent + 2, header)
            ctx.loop_labels.append(brk)
            self.steps(step.steps, f"{sp}/steps", ctx, indent + 2)
            ctx.loop_labels.pop()
            self.out(
                self.setv(ctx, index, f"(f64.add {self.get(ctx, index)} (f64.const 1))"), indent + 2
            )
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
        stop = f"(if (i32.or (global.get $ERRED) (call $stop (i32.const {pi}))) (then {self.early_return(ctx)}))"
        if len(parts) == 1 and parts[0] in info.rites:
            j = info.rites[parts[0]] - 1
            rite = info.circle.rites[j]
            if info.waits[parts[0]]:
                self.cast_waiting(step, sp, ctx, indent, j, rite)
                return
            args = " ".join(
                self.value(a, ctx, indent, p.type)
                for a, p in zip(arg_nodes, rite.params, strict=True)
            )
            call = f"(call $r{pi}_{j}{' ' + args if args else ''})"
            # 手順の呼び出しにもカウンタを埋める（再帰の無限ループ・jil.md §6.6）
            self.out("(call $bud)", indent)
            self.out(errcheck, indent)
            # Lua と同じ順: 呼ぶ → STOP なら返る → into に代入（STOP はエラーも含む）
            if step.into is not None and rite.returns is not None:
                tmp = self.new_local(ctx, None, rite.returns)
                self.out(self.setv(ctx, tmp, call), indent)
                self.out(stop, indent)
                self.assign(
                    node(f"{sp}/into"), self.nonnull(ctx, tmp, rite.returns), ctx, sp, indent
                )
                return
            self.out(f"(drop {call})" if rite.returns is not None else call, indent)
            self.out(stop, indent)
            return
        kind: str
        returns: str | None
        callee: str
        expected: list[str]
        prefix = ""
        sigil = info.sigils.get(parts[0])
        if len(parts) == 1 and sigil is not None and sigil[0] == "agent":
            # v1 の陣に問う（runtime.md §11）。$ask(ci, sigil 名, sigil の pointer, 場所, prompt) → 要求 id
            position = next(k for k, s in enumerate(info.circle.sigils) if s.name == parts[0])
            site = len(self.ask_sites)
            self.ask_sites.append(f"$rpl{site}")
            self.emit_reply(site, info, parts[0], position)
            callee = "$ask"
            prefix = (
                f"(i32.const {pi}) {self.dstr(parts[0])} "
                f"{self.dstr(f'/circles/{pi}/sigils/{position}')} (i32.const {site})"
            )
            returns = "num"
            expected = ["str"]
            kind = "agent"
        elif len(parts) == 1 and sigil is not None and sigil[0] == "summon":
            _, target_circle, target_rite = sigil
            other = self.circles[target_circle]
            oj = other.rites[target_rite] - 1
            rite = other.circle.rites[oj]
            if other.waits[target_rite]:
                raise CodegenError(  # pragma: no cover（JIN212 が落とす）
                    f"summon 先の手順 {target_circle}.{target_rite} は wait を含みます"
                )
            callee = f"$r{other.pointer_index}_{oj}"
            returns = rite.returns
            expected = [p.type for p in rite.params]
            kind = "summon"
        elif len(parts) == 1:
            # 効果（expr.md §4.2）: push / removeAt / clear。list の要素の表現で関数を選ぶ
            list_type = arg_nodes[0].type or ""
            _, inner = parse_type(list_type) if list_type.startswith("list<") else ("", None)
            if inner is None:
                raise CodegenError(
                    f"効果 {parts[0]} の 1 つ目の引数の型が list ではありません（{list_type}）"
                )
            v = list_variant(inner)
            expected = [list_type, inner] if parts[0] == "push" else [list_type, "num"]
            callee = {
                "push": f"$e_push_{v}",
                "removeAt": f"$e_remove_{v}",
                "clear": f"$e_clear_{v}",
            }[parts[0]]
            returns = None
            kind = "effect"
        else:
            # ホスト能力（abilities.md）
            if sigil is None or sigil[0] != "host":
                raise CodegenError(f"'{parts[0]}' は host の sigil ではありません")
            ns = sigil[1]
            member = abilities.namespace(ns).member(parts[1])  # type: ignore[union-attr]
            if member is None:
                raise CodegenError(f"ホスト能力 {ns}.{parts[1]} が分かりません")
            callee = _HOST_FUNC[ns, parts[1]]
            returns = member.returns
            expected = [t for _, t in member.params]
            kind = "host"
        # 引数を評価する（DEBUG では局所に置いて cast 行に載せる。list の効果で引数が変わる前の値が載る）
        values = [
            self.value(a, ctx, indent, t)
            for a, t in zip(arg_nodes, expected[: len(arg_nodes)], strict=True)
        ]
        crow: str | None = None
        if self.debug:
            temps = []
            for a, v, t in zip(arg_nodes, values, expected, strict=False):
                tmp = self.new_local(ctx, None, a.type if a.type != ex.LIST_OF_UNKNOWN else t)
                self.out(self.setv(ctx, tmp, v), indent)
                temps.append(self.nonnull(ctx, tmp, a.type or t))
            values = temps
            args_json = self.json_array(
                ctx,
                indent,
                [
                    f"(call {self.serializer(a.type or t)} {v})"
                    for a, v, t in zip(arg_nodes, values, expected, strict=False)
                ],
            )
            crow = self.new_raw_local(ctx, "(ref null $Row)")
            self.out(
                self.setv(
                    ctx,
                    crow,
                    f"(call $row (i32.const {_KIND['cast']}) (i32.const {pi}) {self.dstr(step.target)} {self.dstr(sp)} {args_json} (ref.null $str))",
                ),
                indent,
            )
        args = " ".join([prefix, *values]).strip()
        call = f"(call {callee}{' ' + args if args else ''})"
        if kind == "summon":
            self.out("(call $bud)", indent)
            self.out(errcheck, indent)
        if returns is not None:
            tmp = self.new_local(ctx, None, returns)
            self.out(self.setv(ctx, tmp, call), indent)
            self.out(errcheck, indent)
            got = self.nonnull(ctx, tmp, returns)
            if crow is not None:
                out_json = self.json_of(ctx, indent, [f"(call {self.serializer(returns)} {got})"])
                self.out(f"(call $row_out {self.get(ctx, crow)} {out_json})", indent)
            if step.into is not None:
                self.assign(node(f"{sp}/into"), got, ctx, sp, indent)
            return
        self.out(call, indent)
        self.out(errcheck, indent)

    def nonnull(self, ctx: _RiteCtx, handle: str, type_text: str) -> str:
        got = self.get(ctx, handle)
        return f"(ref.as_non_null {got})" if _is_ref(self.wtype(type_text)) else got

    def cast_waiting(
        self, step: CastStep, sp: str, ctx: _RiteCtx, indent: int, j: int, rite: Rite
    ) -> None:
        """自陣の待つ手順への cast（wait を含む手順の中）: 呼び先のフレームを保持し、中断は呼び元にも伝える。"""
        node = self.program.node
        info = ctx.info
        pi = info.pointer_index
        assert ctx.frame is not None
        frame = self.frame_of[pi, j]
        slot = self.new_raw_local(ctx, f"(ref null {frame})")
        c = ctx.pc()
        pc = f"(struct.get {ctx.frame} 0 (local.get $fr))"
        skip = ctx.label("skip")
        self.out(f"(block {skip}", indent)
        self.out("(if (local.get $rs)", indent + 1)
        self.out(f"(then (br_if {skip} (i32.ne {pc} (i32.const {c}))))", indent + 2)
        self.out("(else", indent + 2)
        self.out("(call $bud)", indent + 3)
        self.out(f"(if (global.get $ERRED) (then {self.early_return(ctx)}))", indent + 3)
        args = [
            self.value(a, ctx, indent + 3, p.type)
            for a, p in zip(
                [node(f"{sp}/args/{k}") for k in range(len(step.args))], rite.params, strict=True
            )
        ]
        self.out(self.setv(ctx, slot, f"(struct.new_default {frame})"), indent + 3)
        for k, value in enumerate(args):
            field_index = k + 1 + (1 if rite.returns is not None else 0)
            self.out(
                f"(struct.set {frame} {field_index} {self.get(ctx, slot)} {value})", indent + 3
            )
        self.out("))", indent + 2)
        self.out(f"(if (call $r{pi}_{j}w (ref.as_non_null {self.get(ctx, slot)}))", indent + 1)
        self.out(
            f"(then (struct.set {ctx.frame} 0 (local.get $fr) (i32.const {c})) (return (i32.const 1))))",
            indent + 2,
        )
        self.out("(local.set $rs (i32.const 0))", indent + 1)
        self.out(
            f"(if (i32.or (global.get $ERRED) (call $stop (i32.const {pi}))) (then {self.early_return(ctx)}))",
            indent + 1,
        )
        if step.into is not None and rite.returns is not None:
            got = f"(struct.get {frame} 1 {self.get(ctx, slot)})"
            if _is_ref(self.wtype(rite.returns)):
                got = f"(ref.as_non_null {got})"
            self.assign(node(f"{sp}/into"), got, ctx, sp, indent + 1)
        self.out(")", indent)

    def emit_step(self, step: EmitStep, sp: str, ctx: _RiteCtx, indent: int) -> None:
        info = ctx.info
        pi = info.pointer_index
        node = self.program.node
        target = self.circles[step.circle]
        arg_nodes = [node(f"{sp}/args/{k}") for k in range(len(step.args))]
        site = len(self.emit_sites)
        self.emit_sites.append(f"$dlv{site}")
        # 宛先の on message の手順の引数の型（name の後ろ）に合わせて評価する
        handler = self.on_rite(target, "message")
        expected = [p.type for p in handler.params[1:]] if handler is not None else []
        values = [
            self.value(a, ctx, indent, expected[k] if k < len(expected) else None)
            for k, a in enumerate(arg_nodes)
        ]
        types = [
            a.type if a.type != ex.LIST_OF_UNKNOWN else expected[k] for k, a in enumerate(arg_nodes)
        ]
        if self.debug:
            temps = []
            for v, t in zip(values, types, strict=True):
                tmp = self.new_local(ctx, None, t)
                self.out(self.setv(ctx, tmp, v), indent)
                temps.append(self.nonnull(ctx, tmp, t or "num"))
            values = temps
            args_json = self.json_array(
                ctx,
                indent,
                [
                    f"(call {self.serializer(t or 'num')} {v})"
                    for v, t in zip(values, types, strict=True)
                ],
            )
            meta = f"(i32.const {pi}) {self.dstr(sp)} {args_json}"
        else:
            meta = "(i32.const -1) (ref.null $str) (ref.null $str)"
        if values:
            mtype = f"$M{site}"
            fields = " ".join(f"(field (mut {_nullable(self.wtype(t))}))" for t in types)
            self.frame_types.append(f"(type {mtype} (struct {fields}))")
            args = f"(struct.new {mtype} {' '.join(values)})"
        else:
            args = "(ref.null any)"
        self.emit_deliver(site, target, handler, types)
        self.out(
            f"(call $emit (i32.const {site}) (i32.const {target.pointer_index}) {self.dstr(step.message)} {args} {meta})",
            indent,
        )

    # ---------------------------------------------------------------- 手順と陣
    def on_rite(self, info: CircleInfo, event: str) -> Rite | None:
        boundary = info.circle.boundary
        if boundary is None:
            return None
        for on in boundary.on:
            if on.event == event:
                return info.circle.rites[info.rites[on.rite] - 1]
        return None

    def on_pointer(self, info: CircleInfo, event: str) -> str:
        assert info.circle.boundary is not None
        k = next(k for k, on in enumerate(info.circle.boundary.on) if on.event == event)
        return f"/circles/{info.pointer_index}/boundary/on/{k}"

    def run_call(self, info: CircleInfo, rite: Rite, args: list[str]) -> str:
        """手順の起動（`$run<i>_<j>`）。Lua は余分な引数を捨てるので、宣言した数だけ渡す。"""
        j = info.rites[rite.name] - 1
        passed = " ".join(args[: len(rite.params)])
        return f"(call $run{info.pointer_index}_{j}{' ' + passed if passed else ''})"

    def emit_deliver(
        self, site: int, target: CircleInfo, handler: Rite | None, types: list[str | None]
    ) -> None:
        """`$dlv<n>(msg)`: emit の場所 n のメッセージを宛先の on message へ（event 行は DEBUG）。"""
        pi = target.pointer_index
        lines = [
            f"  (func $dlv{site} (param $m (ref null $Msg))",
            "    (local $ob (ref null $buf))",
        ]
        if handler is None:
            lines.append("  )")
            self.frame_fns.extend(lines)
            return
        if types:
            lines.append(f"    (local $a (ref null $M{site}))")
            lines.append(
                f"    (local.set $a (ref.cast (ref null $M{site}) (struct.get $Msg 3 (local.get $m))))"
            )
        if self.debug:
            lines.extend(
                [
                    "    (local.set $ob (call $fmt_begin))",
                    "    (call $putc (i32.const 91))",
                    "    (call $put_js (struct.get $Msg 2 (local.get $m)))",
                    "    (call $put_inner (struct.get $Msg 6 (local.get $m)))",
                    "    (call $putc (i32.const 93))",
                    f"    {self.row('event', pi, self.dstr('message'), self.dstr(self.on_pointer(target, 'message')), '(call $fmt_end (local.get $ob))', '(ref.null $str)')}",
                ]
            )
        args = ["(ref.as_non_null (struct.get $Msg 2 (local.get $m)))"]
        for k, t in enumerate(types):
            got = f"(struct.get $M{site} {k} (local.get $a))"
            args.append(f"(ref.as_non_null {got})" if _is_ref(self.wtype(t)) else got)
        lines.append(f"    {self.run_call(target, handler, args)})")
        self.frame_fns.extend(lines)

    def emit_reply(self, site: int, info: CircleInfo, sigil_name: str, position: int) -> None:
        """`$rpl<n>(id, text)`: v1 の陣の答えを sigil を持つ陣の on message へ `(sigil 名, id, text)` で。"""
        pi = info.pointer_index
        handler = self.on_rite(info, "message")
        lines = [
            f"  (func $rpl{site} (param $id f64) (param $text (ref $str))",
            "    (local $ob (ref null $buf))",
        ]
        if handler is None:
            lines.append("  )")
            self.frame_fns.extend(lines)
            return
        if self.debug:
            lines.extend(
                [
                    "    (local.set $ob (call $fmt_begin))",
                    "    (call $putc (i32.const 91))",
                    f"    (call $put_js {self.dstr(sigil_name)})",
                    "    (call $putc (i32.const 44))",
                    "    (call $put_jn (local.get $id))",
                    "    (call $putc (i32.const 44))",
                    "    (call $put_js (local.get $text))",
                    "    (call $putc (i32.const 93))",
                    f"    {self.row('event', pi, self.dstr('message'), self.dstr(self.on_pointer(info, 'message')), '(call $fmt_end (local.get $ob))', '(ref.null $str)')}",
                ]
            )
        lines.append(
            f"    {self.run_call(info, handler, [self.dstr(sigil_name), '(local.get $id)', '(local.get $text)'])})"
        )
        self.frame_fns.extend(lines)

    def emit_rite(self, info: CircleInfo, rite: Rite, j: int) -> None:
        pi = info.pointer_index
        frame = self.frame_of.get((pi, j))
        ctx = _RiteCtx(info=info, returns=rite.returns, locals={}, frame=frame)
        params: list[str] = []
        if frame is None:
            for p in rite.params:
                wat = f"$l{ctx.next_local}"
                ctx.next_local += 1
                ctx.locals[p.name] = (wat, p.type)
                params.append(f"(param {wat} {self.wtype(p.type)})")
        else:
            for p in rite.params:
                self.new_local(ctx, p.name, p.type)
        pointer = f"/circles/{pi}/rites/{j}"
        start = len(self.lines)
        if self.debug:
            ctx.rite_row = self.new_raw_local(ctx, "(ref null $Row)")
            args_json = self.json_array(
                ctx,
                2,
                [
                    f"(call {self.serializer(p.type)} {self.name(p.name, ctx, info)})"
                    for p in rite.params
                ],
            )
            self.out(
                self.setv(
                    ctx,
                    ctx.rite_row,
                    f"(call $row (i32.const {_KIND['rite']}) (i32.const {pi}) {self.dstr(rite.name)} {self.dstr(pointer)} {args_json} (ref.null $str))",
                ),
                2,
            )
            if frame is not None:
                # 再開では rite 行を出さない（起動は 1 回）
                head_lines = self.lines[start:]
                del self.lines[start:]
                self.out("(if (i32.eqz (local.get $rs))", 2)
                self.out("(then", 3)
                self.lines.extend("  " + line for line in head_lines)
                self.out("))", 3)
        self.steps(rite.steps, f"{pointer}/steps", ctx, 2)
        body = self.lines[start:]
        del self.lines[start:]
        if rite.returns is not None and not _exits(rite.steps):
            # 末尾まで `return` せずに抜ける手順は Lua では nil を返し、`into` の state が nil になって
            # 次の算術で error 行になる。wasm には nil が無く、黙って既定値を返すと「一致」が汚れるので、
            # 生成の時点で拒む（Sub-Issue ではなく恒久。JIN213 / JIN202 はこの形を落とさない）
            raise CodegenError(
                f"--target wasm-gc: 手順 {info.circle.name}.{rite.name} は returns を持つのに"
                "末尾まで return / finish せずに抜ける経路があります（Lua では nil が返る形）。"
                "最後のステップを return にするか、if の両枝で return してください"
            )
        if frame is None:
            result = f" (result {self.wtype(rite.returns)})" if rite.returns is not None else ""
            head = f"(func $r{pi}_{j}{' ' + ' '.join(params) if params else ''}{result}"
            self.out(f"{head} ;; {info.circle.name}.{rite.name}", 1)
            self.out("(local $ob (ref null $buf))", 2)
            for wat, type_text in ctx.decls:
                self.out(f"(local {wat} {type_text})", 2)
            self.lines.extend(body)
            if rite.returns is not None:
                # 静的に抜けることを確かめたので、ここには来ない（型付きの関数の末尾には命令が要る）
                self.out("(unreachable)", 2)
            self.out(")", 1)
            # 起動の入口（核 / on / 配達）
            self.out(f"(func $run{pi}_{j}{' ' + ' '.join(params) if params else ''}", 1)
            args = " ".join(f"(local.get $l{k})" for k in range(len(rite.params)))
            call = f"(call $r{pi}_{j}{' ' + args if args else ''})"
            self.out(f"(drop {call}))" if rite.returns is not None else f"{call})", 2)
            return
        # wait を含む手順: フレーム（pc / 戻り値 / 局所）と、先頭から早送りする関数
        rite_id = len(self.waiting)
        self.waiting.append((pi, j))
        fields = ["(field (mut i32))"]
        if rite.returns is not None:
            fields.append(f"(field (mut {_nullable(self.wtype(rite.returns))}))")
        fields.extend(f"(field (mut {t}))" for _, t in ctx.decls)
        self.frame_types.append(
            f"(type {frame} (struct {' '.join(fields)}))  ;; {info.circle.name}.{rite.name}"
        )
        self.out(
            f"(func $r{pi}_{j}w (param $fr (ref {frame})) (result i32) ;; {info.circle.name}.{rite.name}（wait を含む）",
            1,
        )
        self.out("(local $rs i32) (local $ob (ref null $buf))", 2)
        self.out(
            f"(local.set $rs (i32.ne (struct.get {frame} 0 (local.get $fr)) (i32.const 0)))", 2
        )
        self.lines.extend(body)
        self.out("(i32.const 0))", 2)
        wparams = " ".join(f"(param $p{k} {self.wtype(p.type)})" for k, p in enumerate(rite.params))
        self.out(f"(func $run{pi}_{j}{' ' + wparams if wparams else ''}", 1)
        self.out(f"(local $fr (ref null {frame}))", 2)
        self.out(f"(local.set $fr (struct.new_default {frame}))", 2)
        for k, p in enumerate(rite.params):
            self.out(
                f"(struct.set {frame} {ctx.slots[ctx.locals[p.name][0]]} (local.get $fr) (local.get $p{k}))",
                2,
            )
        self.out(
            f"(if (call $r{pi}_{j}w (ref.as_non_null (local.get $fr))) (then (call $register_wait (i32.const {pi}) (i32.const {rite_id}) (local.get $fr)))))",
            2,
        )

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
        self.out(f";; circle {pi}: {circle.name}", 1)
        if circle.flow is not None:
            self.out(f"(func $init{pi})", 1)
            self.out(f"(func $publish{pi})", 1)
            self.out(f"(func $pub{pi})", 1)
            if self.debug:
                self.out(f"(func $dump{pi})", 1)
                self.out(f"(func $pdump{pi})", 1)
                self.out(f"(func $restore{pi} (param $v (ref null $J)))", 1)
                self.out(f"(func $prestore{pi} (param $v (ref null $J)))", 1)
            if circle.flow.exit is not None:
                exit_expr = self.expr(self.program.node(f"/circles/{pi}/flow/exit"), None, None)
                self.out(f"(func $exit{pi} (result i32) {exit_expr})", 1)
            return
        defaults = " ".join(self.default_const(s.type) for s in circle.state)
        new = f"(struct.new $S{pi}{' ' + defaults if defaults else ''})"
        self.out(f"(global $S{pi} (mut (ref $S{pi})) {new})", 1)
        self.out(f"(global $P{pi} (mut (ref $S{pi})) {new})", 1)
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
        self.out(")", 1)
        self.out(f"(func $pub{pi}", 1)
        for j, s in outs:
            self.out("(call $pub_comma)", 2)
            self.out(self.puts(f'"{circle.name}.{s.name}":'), 2)
            self.out(
                f"(call {self.serializer(s.type)} (struct.get $S{pi} {j} (global.get $P{pi})))", 2
            )
        self.out(")", 1)
        if self.debug:
            # snapshot / resume（runtime.md §1.3）: state の JSON と、名前で引いて形が合う欄だけ写す読み手
            for fn, source, items in (
                ("dump", "$S", list(enumerate(circle.state))),
                ("pdump", "$P", outs),
            ):
                self.out(f"(func ${fn}{pi}", 1)
                self.out("(call $putc (i32.const 123))", 2)
                for pos, (j, s) in enumerate(items):
                    self.out(self.puts(("," if pos else "") + f'"{s.name}":'), 2)
                    self.out(
                        f"(call {self.serializer(s.type)} (struct.get $S{pi} {j} (global.get {source}{pi})))",
                        2,
                    )
                self.out("(call $putc (i32.const 125)))", 2)
            for fn, target, items in (
                ("restore", "$S", list(enumerate(circle.state))),
                ("prestore", "$P", outs),
            ):
                self.out(f"(func ${fn}{pi} (param $v (ref null $J))", 1)
                for j, s in items:
                    self.out(f"(local $x{j} {_nullable(self.wtype(s.type))})", 2)
                for j, s in items:
                    off, length = self.data.put(s.name)
                    self.out(
                        f"(local.set $x{j} (call {self.reader(s.type)} (call $j_getk (local.get $v) (i32.const {off}) (i32.const {length}))))",
                        2,
                    )
                    got = (
                        f"(ref.as_non_null (local.get $x{j}))"
                        if _is_ref(self.wtype(s.type))
                        else f"(local.get $x{j})"
                    )
                    self.out(
                        f"(if (global.get $RD_OK) (then (struct.set $S{pi} {j} (global.get {target}{pi}) {got})))",
                        2,
                    )
                self.out(")", 1)
            # guards: 偽なら assert 行（message は JSON 文字列か null）
            self.out(f"(func $guards{pi}", 1)
            self.out("(local $ob (ref null $buf))", 2)
            gctx = _RiteCtx(info=info, returns=None, locals={})
            start = len(self.lines)
            guards = circle.boundary.guards if circle.boundary is not None else []
            for k, guard in enumerate(guards):
                pointer = f"/circles/{pi}/boundary/guards/{k}"
                cond = self.value(self.program.node(f"{pointer}/assert"), gctx, 2)
                message = (
                    self.json_of(gctx, 2, [f"(call $put_js {self.dstr(guard.message)})"])
                    if guard.message is not None
                    else "(ref.null $str)"
                )
                self.out(
                    f"(if (i32.eqz {cond}) (then {self.row('assert', pi, '(ref.null $str)', self.dstr(pointer), '(ref.null $str)', message)}))",
                    2,
                )
            body = self.lines[start:]
            del self.lines[start:]
            for wat, type_text in gctx.decls:
                self.out(f"(local {wat} {type_text})", 2)
            self.lines.extend(body)
            self.out(")", 1)
        # on の配達（event 行は生成部が積む・runtime.md §5）
        for event in ("key", "pointer", "tick", "exit"):
            handler = self.on_rite(info, event)
            if handler is None:
                continue
            ptr = self.dstr(self.on_pointer(info, event))
            param = " (param $k i32)" if event in ("key", "pointer") else ""
            self.out(f"(func $on_{event}{pi}{param}", 1)
            self.out("(local $ob (ref null $buf))", 2)
            if event == "key":
                items = [
                    "(call $put_js (call $ev_name (local.get $k)))",
                    "(call $put_bool (call $ev_down (local.get $k)))",
                ]
                args = ["(call $ev_name (local.get $k))", "(call $ev_down (local.get $k))"]
            elif event == "pointer":
                items = ["(call $jf0 (call $ev_pointer (local.get $k)))"]
                args = ["(call $ev_pointer (local.get $k))"]
            elif event == "tick":
                items = ["(call $put_jn (f64.div (f64.const 1) (global.get $FPS)))"]
                args = ["(f64.div (f64.const 1) (global.get $FPS))"]
            else:
                items = []
                args = []
            if self.debug:
                gctx = _RiteCtx(info=info, returns=None, locals={})
                input_json = self.json_array(gctx, 2, items)
                self.out(
                    self.row("event", pi, self.dstr(event), ptr, input_json, "(ref.null $str)"), 2
                )
            self.out(f"{self.run_call(info, handler, args)})", 2)

    def dispatch(
        self, name: str, params: str, result: str | None, cases: dict[int, str], default: str
    ) -> None:
        """`$prog_*`: 陣の添字で振り分ける（if の連鎖）。"""
        head = f"(func {name} (param $i i32){' ' + params if params else ''}{f' (result {result})' if result else ''}"
        self.out(head, 1)
        for pi, text in cases.items():
            if result is not None:
                self.out(f"(if (i32.eq (local.get $i) (i32.const {pi})) (then (return {text})))", 2)
            else:
                self.out(f"(if (i32.eq (local.get $i) (i32.const {pi})) (then {text} (return)))", 2)
        self.out(f"{default})", 2)

    def emit_dispatchers(self) -> None:
        infos = list(self.circles.values())
        core = {i.pointer_index: i for i in infos if i.circle.flow is None}
        flows = {i.pointer_index: i for i in infos if i.circle.flow is not None}
        self.dispatch(
            "$prog_flow",
            "",
            "i32",
            {pi: f"(i32.const {_FLOW_KIND[i.circle.flow.kind]})" for pi, i in flows.items()},  # type: ignore[union-attr]
            "(i32.const 0)",
        )
        self.dispatch(
            "$prog_nchildren",
            "",
            "i32",
            {pi: f"(i32.const {len(i.circle.flow.steps)})" for pi, i in flows.items()},  # type: ignore[union-attr]
            "(i32.const 0)",
        )
        self.out("(func $prog_child (param $i i32) (param $k i32) (result i32)", 1)
        for pi, i in flows.items():
            for k, child in enumerate(i.circle.flow.steps):  # type: ignore[union-attr]
                self.out(
                    f"(if (i32.and (i32.eq (local.get $i) (i32.const {pi})) (i32.eq (local.get $k) (i32.const {k}))) (then (return (i32.const {self.circles[child].pointer_index}))))",
                    2,
                )
        self.out("(i32.const -1))", 2)
        self.dispatch(
            "$prog_exit",
            "",
            "i32",
            {pi: f"(call $exit{pi})" for pi, i in flows.items() if i.circle.flow.exit is not None},  # type: ignore[union-attr]
            "(i32.const 0)",
        )
        self.dispatch("$prog_init", "", None, {pi: f"(call $init{pi})" for pi in core}, "")
        self.dispatch("$prog_publish", "", None, {pi: f"(call $publish{pi})" for pi in core}, "")
        self.dispatch(
            "$prog_has_outs",
            "",
            "i32",
            {pi: "(i32.const 1)" for pi, i in core.items() if any(s.out for s in i.circle.state)},
            "(i32.const 0)",
        )
        self.dispatch("$prog_pub", "", None, {pi: f"(call $pub{pi})" for pi in core}, "")
        cores: dict[int, str] = {}
        for pi, i in core.items():
            rite = i.circle.rites[i.rites[i.circle.core or ""] - 1]
            cores[pi] = self.run_call(i, rite, [])
        self.dispatch("$prog_core", "", None, cores, "")
        self.dispatch(
            "$prog_name",
            "",
            "(ref $str)",
            {i.pointer_index: self.dstr(i.circle.name) for i in infos},
            "(call $str_empty)",
        )
        self.out("(func $prog_find (param $s (ref null $str)) (result i32)", 1)
        for i in infos:
            off, length = self.data.put(i.circle.name)
            self.out(
                f"(if (call $str_eq_mem (local.get $s) (i32.const {off}) (i32.const {length})) (then (return (i32.const {i.pointer_index}))))",
                2,
            )
        self.out("(i32.const -1))", 2)
        self.out("(func $prog_has_on (param $i i32) (param $kind i32) (result i32)", 1)
        for i in infos:
            for event, kind in _ON_KIND.items():
                if self.on_rite(i, event) is not None:
                    self.out(
                        f"(if (i32.and (i32.eq (local.get $i) (i32.const {i.pointer_index})) (i32.eq (local.get $kind) (i32.const {kind}))) (then (return (i32.const 1))))",
                        2,
                    )
        self.out("(i32.const 0))", 2)
        for event in ("key", "pointer"):
            self.dispatch(
                f"$prog_on_{event}",
                "(param $k i32)",
                None,
                {
                    i.pointer_index: f"(call $on_{event}{i.pointer_index} (local.get $k))"
                    for i in infos
                    if self.on_rite(i, event) is not None
                },
                "",
            )
        for event in ("tick", "exit"):
            self.dispatch(
                f"$prog_on_{event}",
                "",
                None,
                {
                    i.pointer_index: f"(call $on_{event}{i.pointer_index})"
                    for i in infos
                    if self.on_rite(i, event) is not None
                },
                "",
            )
        self.dispatch(
            "$prog_deliver",
            "(param $m (ref null $Msg))",
            None,
            {site: f"(call {fn} (local.get $m))" for site, fn in enumerate(self.emit_sites)},
            "",
        )
        self.dispatch(
            "$prog_reply",
            "(param $id f64) (param $text (ref $str))",
            None,
            {
                site: f"(call {fn} (local.get $id) (local.get $text))"
                for site, fn in enumerate(self.ask_sites)
            },
            "",
        )
        self.dispatch(
            "$prog_resume",
            "(param $fr anyref)",
            "i32",
            {
                rid: f"(call $r{pi}_{j}w (ref.cast (ref {self.frame_of[pi, j]}) (local.get $fr)))"
                for rid, (pi, j) in enumerate(self.waiting)
            },
            "(i32.const 0)",
        )
        self.dispatch(
            "$prog_until",
            "(param $fr anyref)",
            "i32",
            {
                uid: f"(call {fn} (ref.cast (ref {frame}) (local.get $fr)))"
                for uid, (fn, frame) in enumerate(self.untils)
            },
            "(i32.const 0)",
        )
        if self.debug:
            self.dispatch("$prog_dump", "", None, {pi: f"(call $dump{pi})" for pi in core}, "")
            self.dispatch("$prog_pdump", "", None, {pi: f"(call $pdump{pi})" for pi in core}, "")
            self.dispatch(
                "$prog_restore",
                "(param $v (ref null $J))",
                None,
                {pi: f"(call $restore{pi} (local.get $v))" for pi in core},
                "",
            )
            self.dispatch(
                "$prog_prestore",
                "(param $v (ref null $J))",
                None,
                {pi: f"(call $prestore{pi} (local.get $v))" for pi in core},
                "",
            )
            self.dispatch("$prog_guards", "", None, {pi: f"(call $guards{pi})" for pi in core}, "")
        else:
            for name, params in (
                ("$prog_dump", ""),
                ("$prog_pdump", ""),
                ("$prog_restore", " (param $v (ref null $J))"),
                ("$prog_prestore", " (param $v (ref null $J))"),
                ("$prog_guards", ""),
            ):
                self.out(f"(func {name} (param $i i32){params})", 1)

    # ---------------------------------------------------------------- 全体
    def program_part(self) -> str:
        model = self.model
        root = self.circles[model.root]
        self.frame_fns: list[str] = []
        self.emit_types()
        self.emit_form_serializers()
        for info in self.circles.values():
            for j, rite in enumerate(info.circle.rites):
                self.emit_rite(info, rite, j)
        for info in self.circles.values():
            self.emit_circle(info)
        self.emit_dispatchers()
        self.out(f"(global $ROOT i32 (i32.const {root.pointer_index}))", 1)
        self.out(f"(global $N i32 (i32.const {len(self.circles)}))", 1)
        self.out(f"(global $FPS f64 (f64.const {wat_number(model.stage.fps)}))", 1)
        self.out(f"(global $DEBUG i32 (i32.const {1 if self.debug else 0}))", 1)
        # wait のフレーム / emit の引数の struct（型紙と state の rec の後ろ）
        if self.frame_types:
            self.out("(rec", 1)
            for text in self.frame_types:
                self.out(text, 2)
            self.out(")", 1)
        # until の式・emit の配達・v1 の答えの配達（手順の生成中に集めたもの）
        self.lines.extend(self.frame_fns)
        # list の直列化 / 読み手（型ごとに 1 つ）
        self.lines.extend(self.serializer_lines)
        self.lines.extend(self.reader_lines)
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
    return _Generator(analyze(model), debug=debug).program_part()


__all__ = [
    "DATA_BASE",
    "generate_program",
    "header",
    "list_variant",
    "wat_number",
    "wat_string",
    "wat_type",
]
