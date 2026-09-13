"""葉の式（docs/spec/v2/expr.md）: 文法・位置付き AST・型検査・定数式の判定。

文法は既存の JSON パーサ（`jin_core.parser`）と同じ流儀で**インラインの Lark 文法**に置き、
`parser="lalr"` と `propagate_positions=True` で位置を取る。`.lark` ファイルは作らない。

位置は復号後の式文字列の**コードポイント添字**（0 始まり・end 排他）。JSON 文字列リテラルの
中の位置への換算は `jin_core.v2.spans` だけが行う。

型は文字列で表す（`num` / `bool` / `str` / `list<T>` / 型紙名）。`list<?>` は空 list リテラルの
「文脈から決まる」型で、代入先や `let.type` から確定する（決まらなければ JIN202）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lark import Lark, Token, Transformer, v_args
from lark.exceptions import UnexpectedEOF, UnexpectedInput

from jin_core.v2 import abilities
from jin_core.v2.model import PRIMITIVE_TYPES, parse_type

#: 式文法（expr.md §1）。予約語は `\b` 付きの正規表現にし、NAME 側は否定先読みで予約語を除く
#: （`andy` が `and` + `y` に割れないため。lark の標準字句解析は最長一致ではない）。
JIN_EXPR_GRAMMAR = r"""
?start: or_

?or_: and_ (OR and_)*
?and_: not_ (AND not_)*
?not_: NOT not_ -> not_
     | cmp
?cmp: add (CMP_OP add)?
?add: mul (ADD_OP mul)*
?mul: unary (MUL_OP unary)*
?unary: MINUS unary -> neg
      | postfix
?postfix: primary
        | postfix "." NAME -> field
        | postfix "[" or_ "]" -> index
        | postfix "(" args ")" -> call
args: [or_ ("," or_)*]
?primary: NUMBER -> number
        | STRING -> string
        | TRUE -> true
        | FALSE -> false
        | NAME -> name
        | "(" or_ ")"
        | NAME "{" [pair ("," pair)*] "}" -> construct
        | "[" args "]" -> list_
pair: NAME ":" or_

OR: /or\b/
AND: /and\b/
NOT: /not\b/
TRUE: /true\b/
FALSE: /false\b/
NAME: /(?!(?:and|or|not|true|false)\b)[A-Za-z_][A-Za-z0-9_]*/
NUMBER: /[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?/
STRING: /"([^"\\\x00-\x1f]|\\["\\\/bfnrt]|\\u[0-9a-fA-F]{4})*"/
CMP_OP: "==" | "!=" | "<=" | ">=" | "<" | ">"
ADD_OP: "++" | "+" | "-"
MUL_OP: "*" | "/" | "%"
MINUS: "-"

WS: /[ \t]+/
%ignore WS
"""

_PARSER = Lark(JIN_EXPR_GRAMMAR, start="start", parser="lalr", propagate_positions=True)


# ---------------------------------------------------------------- AST


@dataclass(frozen=True, slots=True)
class Span:
    start: int
    end: int


@dataclass(slots=True)
class Node:
    span: Span
    #: 型検査が埋める（未検査は None）。`rename` の型紙欄追随がこれを読む。
    type: str | None = field(default=None, init=False, compare=False)


@dataclass(slots=True)
class Number(Node):
    value: float = 0.0


@dataclass(slots=True)
class String(Node):
    value: str = ""


@dataclass(slots=True)
class Boolean(Node):
    value: bool = False


@dataclass(slots=True)
class Name(Node):
    name: str = ""


@dataclass(slots=True)
class Unary(Node):
    op: str = ""
    operand: Node = field(default_factory=lambda: Number(Span(0, 0)))


@dataclass(slots=True)
class Binary(Node):
    op: str = ""
    left: Node = field(default_factory=lambda: Number(Span(0, 0)))
    right: Node = field(default_factory=lambda: Number(Span(0, 0)))


@dataclass(slots=True)
class FieldAccess(Node):
    obj: Node = field(default_factory=lambda: Number(Span(0, 0)))
    name: str = ""
    name_span: Span = Span(0, 0)


@dataclass(slots=True)
class Index(Node):
    obj: Node = field(default_factory=lambda: Number(Span(0, 0)))
    index: Node = field(default_factory=lambda: Number(Span(0, 0)))


@dataclass(slots=True)
class Call(Node):
    callee: Node = field(default_factory=lambda: Name(Span(0, 0)))
    args: list[Node] = field(default_factory=list)


@dataclass(slots=True)
class Construct(Node):
    form: str = ""
    form_span: Span = Span(0, 0)
    fields: list[tuple[str, Span, Node]] = field(default_factory=list)


@dataclass(slots=True)
class ListLiteral(Node):
    items: list[Node] = field(default_factory=list)


class ExprSyntaxError(Exception):
    """JIN201。`span` は式の中の位置。"""

    def __init__(self, message: str, span: Span, hint: str) -> None:
        super().__init__(message)
        self.message = message
        self.span = span
        self.hint = hint


def _span_of_meta(meta: Any) -> Span:
    if getattr(meta, "empty", False):
        return Span(0, 0)
    return Span(int(meta.start_pos), int(meta.end_pos))


def _span_of_token(token: Token) -> Span:
    return Span(int(token.start_pos), int(token.end_pos))


def _decode_json_string(text: str) -> str:
    import json

    return json.loads(text)


@v_args(meta=True)
class _Builder(Transformer):
    """Lark の木 → AST。左結合の二項演算は繰り返しを畳む。"""

    def or_(self, meta: Any, items: list[Any]) -> Node:
        return self._fold(meta, items)

    def and_(self, meta: Any, items: list[Any]) -> Node:
        return self._fold(meta, items)

    def cmp(self, meta: Any, items: list[Any]) -> Node:
        return self._fold(meta, items)

    def add(self, meta: Any, items: list[Any]) -> Node:
        return self._fold(meta, items)

    def mul(self, meta: Any, items: list[Any]) -> Node:
        return self._fold(meta, items)

    def _fold(self, meta: Any, items: list[Any]) -> Node:
        node = items[0]
        i = 1
        while i + 1 < len(items):
            op = str(items[i])
            right = items[i + 1]
            node = Binary(Span(node.span.start, right.span.end), op, node, right)
            i += 2
        return node

    def not_(self, meta: Any, items: list[Any]) -> Node:
        return Unary(_span_of_meta(meta), "not", items[1])

    def neg(self, meta: Any, items: list[Any]) -> Node:
        return Unary(_span_of_meta(meta), "-", items[1])

    def field(self, meta: Any, items: list[Any]) -> Node:
        obj, name = items
        return FieldAccess(_span_of_meta(meta), obj, str(name), _span_of_token(name))

    def index(self, meta: Any, items: list[Any]) -> Node:
        obj, idx = items
        return Index(_span_of_meta(meta), obj, idx)

    def call(self, meta: Any, items: list[Any]) -> Node:
        callee, args = items
        return Call(_span_of_meta(meta), callee, list(args))

    def args(self, meta: Any, items: list[Any]) -> list[Node]:
        return [item for item in items if item is not None]

    def number(self, meta: Any, items: list[Any]) -> Node:
        token = items[0]
        return Number(_span_of_token(token), float(str(token)))

    def string(self, meta: Any, items: list[Any]) -> Node:
        token = items[0]
        return String(_span_of_token(token), _decode_json_string(str(token)))

    def true(self, meta: Any, items: list[Any]) -> Node:
        return Boolean(_span_of_token(items[0]), True)

    def false(self, meta: Any, items: list[Any]) -> Node:
        return Boolean(_span_of_token(items[0]), False)

    def name(self, meta: Any, items: list[Any]) -> Node:
        token = items[0]
        return Name(_span_of_token(token), str(token))

    def construct(self, meta: Any, items: list[Any]) -> Node:
        form = items[0]
        pairs = [item for item in items[1:] if item is not None]
        return Construct(_span_of_meta(meta), str(form), _span_of_token(form), pairs)

    def pair(self, meta: Any, items: list[Any]) -> tuple[str, Span, Node]:
        name, value = items
        return (str(name), _span_of_token(name), value)

    def list_(self, meta: Any, items: list[Any]) -> Node:
        return ListLiteral(_span_of_meta(meta), list(items[0]))


_BUILDER = _Builder()


def parse_expr(text: str) -> Node:
    """式を AST にする。構文エラーは `ExprSyntaxError`（JIN201）。"""
    if text.strip(" \t") == "":
        raise ExprSyntaxError("式が空です", Span(0, len(text)), "式を書いてください")
    for i, ch in enumerate(text):
        if ch in "\r\n":
            raise ExprSyntaxError(
                "式に改行は書けません",
                Span(i, i + 1),
                "式は 1 行で書き、空白は半角スペースかタブだけ",
            )
    try:
        tree = _PARSER.parse(text)
    except UnexpectedInput as exc:
        pos = int(getattr(exc, "pos_in_stream", 0) or 0)
        token = getattr(exc, "token", None)
        at_end = isinstance(exc, UnexpectedEOF) or (
            token is not None and getattr(token, "type", "") == "$END"
        )
        if at_end or pos < 0:
            # lark は $END に最後のトークンの位置を与えるので、末尾のエラーは式の終端を指す
            pos = len(text)
        expected = sorted(getattr(exc, "expected", []) or getattr(exc, "allowed", []) or [])
        hint = "期待: " + " / ".join(_label(e) for e in expected) if expected else "式の形を確認"
        raise ExprSyntaxError(
            f"式の構文エラー（{pos + 1} 文字目）", Span(pos, min(pos + 1, len(text))), hint
        ) from exc
    node = _BUILDER.transform(tree)
    if isinstance(node, Token):  # pragma: no cover - 単一終端は各 -> 別名で Node になる
        raise ExprSyntaxError("式の構文エラー", Span(0, len(text)), "式の形を確認")
    return node


_LABELS = {
    "NAME": "識別子",
    "NUMBER": "数値",
    "STRING": "文字列",
    "AND": "'and'",
    "OR": "'or'",
    "NOT": "'not'",
    "TRUE": "'true'",
    "FALSE": "'false'",
    "CMP_OP": "比較演算子",
    "ADD_OP": "'+' / '-' / '++'",
    "MUL_OP": "'*' / '/' / '%'",
    "MINUS": "'-'",
    "RPAR": "')'",
    "LPAR": "'('",
    "RSQB": "']'",
    "LSQB": "'['",
    "RBRACE": "'}'",
    "LBRACE": "'{'",
    "COMMA": "','",
    "COLON": "':'",
    "DOT": "'.'",
    "$END": "式の終わり",
}


def _label(name: str) -> str:
    return _LABELS.get(name, name)


# ---------------------------------------------------------------- 型


LIST_OF_UNKNOWN = "list<?>"


def list_of(item: str) -> str:
    return f"list<{item}>"


def item_type(list_type: str) -> str | None:
    head, inner = parse_type(list_type) if list_type != LIST_OF_UNKNOWN else ("list", "?")
    return inner if head == "list" else None


def is_list(type_name: str) -> bool:
    return type_name.startswith("list<")


def assignable(value: str, target: str) -> bool:
    """`value` 型の値を `target` 型の場所へ置けるか。`list<?>` は任意の list に置ける。"""
    if value == target:
        return True
    if value == LIST_OF_UNKNOWN and is_list(target):
        return True
    if is_list(value) and is_list(target):
        inner_v, inner_t = item_type(value), item_type(target)
        return inner_v is not None and inner_t is not None and assignable(inner_v, inner_t)
    return False


#: 純関数（expr.md §4.1）。引数型の `T` は `contains` の総称。`len` / `str` は多重定義なので個別に扱う。
PURE_FUNCTIONS: dict[str, tuple[tuple[str, ...], str]] = {
    "abs": (("num",), "num"),
    "min": (("num", "num"), "num"),
    "max": (("num", "num"), "num"),
    "floor": (("num",), "num"),
    "ceil": (("num",), "num"),
    "round": (("num",), "num"),
    "sqrt": (("num",), "num"),
    "sin": (("num",), "num"),
    "cos": (("num",), "num"),
    "atan2": (("num", "num"), "num"),
    "clamp": (("num", "num", "num"), "num"),
    "sub": (("str", "num", "num"), "str"),
}
#: 多重定義・総称の純関数。表の形に収まらないので名前だけ列挙し、`_check_call` が個別に見る。
SPECIAL_PURE_FUNCTIONS: tuple[str, ...] = ("len", "str", "contains")
PURE_FUNCTION_NAMES: tuple[str, ...] = (*PURE_FUNCTIONS, *SPECIAL_PURE_FUNCTIONS)

#: 組み込み effect（`cast` からだけ）。expr.md §4.2。
EFFECTS: dict[str, tuple[tuple[str, ...], None]] = {
    "push": (("list<T>", "T"), None),
    "removeAt": (("list<T>", "num"), None),
    "clear": (("list<T>",), None),
}


@dataclass(frozen=True, slots=True)
class TypeIssue:
    """型検査の指摘。`code` は JIN202 / JIN203 / JIN204 / JIN205。"""

    code: str
    span: Span
    message: str
    hint: str | None = None


@dataclass(slots=True)
class Scope:
    """式を評価する場所（expr.md §3.1 の解決順に必要な情報）。

    - `locals`: 局所（params / let / loop.name）名 → 型
    - `state`: 自陣の state 名 → 型
    - `sigils`: 自陣の道具環。値は `("host", 名前空間名)` か `("summon", circle, rite)`
    - `public`: 他の陣の公開 state。陣名 → {key: 型}
    - `forms`: 型紙名 → {欄: 型}（組み込み `Pointer` を含む）
    - `circle`: 自陣の名前（`自陣名.key` を JIN203 にするため）
    - `circles`: 全陣の名前（`陣名.key` の陣名解決）
    """

    locals: dict[str, str] = field(default_factory=dict)
    state: dict[str, str] = field(default_factory=dict)
    sigils: dict[str, tuple[str, ...]] = field(default_factory=dict)
    public: dict[str, dict[str, str]] = field(default_factory=dict)
    forms: dict[str, dict[str, str]] = field(default_factory=dict)
    circle: str = ""
    circles: frozenset[str] = frozenset()
    #: 定数式（state.init）として検査するとき True（識別子・ホスト能力を JIN250 にする）。
    constant: bool = False


@dataclass(slots=True)
class TypeCheck:
    """型検査の結果。`type` は式全体の型（決められなければ None）。"""

    type: str | None
    issues: list[TypeIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues


def check_expr(node: Node, scope: Scope, expected: str | None = None) -> TypeCheck:
    """式の型を決め、指摘を集める。`expected` は代入先などの文脈の型（空 list の型を決める）。"""
    checker = _Checker(scope)
    result_type = checker.infer(node, expected)
    if result_type is not None and expected is not None and not assignable(result_type, expected):
        checker.issue(
            "JIN202",
            node.span,
            f"型が合いません: 期待 {expected}、実際 {result_type}",
            f"{expected} の式にしてください",
        )
    return TypeCheck(result_type, checker.issues)


class _Checker:
    def __init__(self, scope: Scope) -> None:
        self.scope = scope
        self.issues: list[TypeIssue] = []

    def issue(self, code: str, span: Span, message: str, hint: str | None = None) -> None:
        self.issues.append(TypeIssue(code, span, message, hint))

    # -- 入口 -----------------------------------------------------------------------
    def infer(self, node: Node, expected: str | None = None) -> str | None:
        result = self._infer(node, expected)
        node.type = result
        return result

    def _infer(self, node: Node, expected: str | None) -> str | None:
        if isinstance(node, Number):
            return "num"
        if isinstance(node, String):
            return "str"
        if isinstance(node, Boolean):
            return "bool"
        if isinstance(node, Name):
            return self._name(node)
        if isinstance(node, Unary):
            return self._unary(node)
        if isinstance(node, Binary):
            return self._binary(node)
        if isinstance(node, FieldAccess):
            return self._field(node)
        if isinstance(node, Index):
            return self._index(node)
        if isinstance(node, Call):
            return self._call(node)
        if isinstance(node, Construct):
            return self._construct(node)
        if isinstance(node, ListLiteral):
            return self._list(node, expected)
        raise TypeError(f"未知のノード: {type(node).__name__}")  # pragma: no cover

    # -- 識別子 ---------------------------------------------------------------------
    def _name(self, node: Name) -> str | None:
        scope = self.scope
        if scope.constant:
            self.issue(
                "JIN250",
                node.span,
                f"init に識別子 '{node.name}' は使えません（定数式だけ）",
                "リテラル・型紙コンストラクタ・純関数で書いてください",
            )
            return None
        if node.name in scope.locals:
            return scope.locals[node.name]
        if node.name in scope.state:
            return scope.state[node.name]
        if node.name in scope.sigils:
            self.issue(
                "JIN202",
                node.span,
                f"'{node.name}' は道具環の名前です。'{node.name}.メンバ(...)' の形で使います",
            )
            return None
        if node.name in scope.circles:
            self.issue(
                "JIN203",
                node.span,
                f"'{node.name}' は陣の名前です。公開 state は '{node.name}.key' で読みます",
            )
            return None
        if node.name in scope.forms:
            self.issue(
                "JIN203",
                node.span,
                f"'{node.name}' は型紙の名前です。値を作るには '{node.name}{{...}}' と書きます",
            )
            return None
        if node.name in PURE_FUNCTION_NAMES or node.name in EFFECTS:
            self.issue("JIN202", node.span, f"'{node.name}' は関数です。'(...)' を付けて呼びます")
            return None
        candidates = [*scope.locals, *scope.state]
        near = _close(node.name, candidates)
        self.issue(
            "JIN203",
            node.span,
            f"識別子 '{node.name}' は定義されていません",
            f"近い名前: {' / '.join(near)}" if near else "state か局所変数を宣言してください",
        )
        return None

    # -- 演算子 ---------------------------------------------------------------------
    def _unary(self, node: Unary) -> str | None:
        operand = self.infer(node.operand)
        want = "bool" if node.op == "not" else "num"
        if operand is not None and operand != want:
            self.issue(
                "JIN202", node.span, f"'{node.op}' は {want} にだけ使えます（実際 {operand}）"
            )
            return None
        return want

    def _binary(self, node: Binary) -> str | None:
        op = node.op
        left = self.infer(node.left)
        right = self.infer(node.right)
        if left is None or right is None:
            return _binary_result(op, left, right)
        if op in ("and", "or"):
            return self._require(node, "bool", left, right, op)
        if op in ("+", "-", "*", "/", "%"):
            return self._require(node, "num", left, right, op)
        if op == "++":
            return self._require(node, "str", left, right, op)
        if op in ("<", "<=", ">", ">="):
            self._require(node, "num", left, right, op)
            return "bool"
        # == / !=
        if left != right:
            self.issue("JIN202", node.span, f"'{op}' の両辺の型が違います（{left} と {right}）")
        elif left not in PRIMITIVE_TYPES:
            self.issue(
                "JIN202",
                node.span,
                f"'{op}' は num / bool / str にだけ使えます（{left} の構造比較はありません）",
            )
        return "bool"

    def _require(self, node: Binary, want: str, left: str, right: str, op: str) -> str | None:
        ok = True
        if left != want:
            self.issue("JIN202", node.left.span, f"'{op}' の左辺は {want} です（実際 {left}）")
            ok = False
        if right != want:
            self.issue("JIN202", node.right.span, f"'{op}' の右辺は {want} です（実際 {right}）")
            ok = False
        return want if ok else None

    # -- 後置 -----------------------------------------------------------------------
    def _field(self, node: FieldAccess) -> str | None:
        base = node.obj
        # 陣名.key（他陣の公開 state）と sigil.member（呼び出しの一部）は識別子の層で解決する
        if isinstance(base, Name) and base.name not in self.scope.locals | self.scope.state:
            if base.name in self.scope.sigils:
                self.issue(
                    "JIN202",
                    node.span,
                    f"'{base.name}.{node.name}' は呼び出しです。'(...)' を付けてください",
                )
                base.type = None
                return None
            if base.name in self.scope.circles:
                return self._public(base, node)
            if base.name in self.scope.forms:
                self.issue("JIN203", base.span, f"'{base.name}' は型紙の名前です")
                return None
            if abilities.namespace(base.name) is not None and not self.scope.constant:
                self.issue(
                    "JIN204",
                    base.span,
                    f"名前空間 '{base.name}' は道具環で許可されていません",
                    f'sigils に {{"name": "{base.name}", "kind": "host", "host": "{base.name}"}} を足す',
                )
                return None
        obj_type = self.infer(base)
        if obj_type is None:
            return None
        fields = self.scope.forms.get(obj_type)
        if fields is None:
            self.issue("JIN202", node.name_span, f"{obj_type} に欄はありません（'.{node.name}'）")
            return None
        if node.name not in fields:
            near = _close(node.name, list(fields))
            self.issue(
                "JIN203",
                node.name_span,
                f"型紙 {obj_type} に欄 '{node.name}' はありません",
                f"近い名前: {' / '.join(near)}" if near else f"欄: {' / '.join(fields)}",
            )
            return None
        return fields[node.name]

    def _public(self, base: Name, node: FieldAccess) -> str | None:
        if base.name == self.scope.circle:
            self.issue(
                "JIN203",
                base.span,
                f"自陣の state は裸の名前で指します（'{base.name}.' は要りません）",
            )
            return None
        keys = self.scope.public.get(base.name)
        if keys is None:
            self.issue(
                "JIN203", base.span, f"陣 '{base.name}' に公開 state はありません（核なし陣）"
            )
            return None
        if node.name not in keys:
            self.issue(
                "JIN203",
                node.name_span,
                f"陣 '{base.name}' に公開 state '{node.name}' はありません",
                f"{base.name} の state '{node.name}' に \"out\": true を付ける",
            )
            return None
        base.type = None
        return keys[node.name]

    def _index(self, node: Index) -> str | None:
        obj_type = self.infer(node.obj)
        idx_type = self.infer(node.index)
        if idx_type is not None and idx_type != "num":
            self.issue("JIN202", node.index.span, f"添字は num です（実際 {idx_type}）")
        if obj_type is None:
            return None
        inner = item_type(obj_type) if is_list(obj_type) else None
        if inner is None or inner == "?":
            self.issue("JIN202", node.obj.span, f"添字は list にだけ使えます（実際 {obj_type}）")
            return None
        return inner

    # -- 呼び出し -------------------------------------------------------------------
    def _call(self, node: Call) -> str | None:
        callee = node.callee
        if isinstance(callee, Name):
            return self._call_pure(node, callee)
        if isinstance(callee, FieldAccess) and isinstance(callee.obj, Name):
            return self._call_member(node, callee.obj, callee)
        self.issue("JIN202", callee.span, "呼び出せるのは純関数と '名前空間.メンバ' だけです")
        return None

    def _call_pure(self, node: Call, callee: Name) -> str | None:
        name = callee.name
        if name in self.scope.locals or name in self.scope.state:
            self.issue("JIN202", callee.span, f"'{name}' は値であり呼び出せません")
            return None
        if name in EFFECTS:
            self.issue(
                "JIN202",
                callee.span,
                f"'{name}' は効果です。式の中では使えず、cast の target に書きます",
            )
            return None
        if name == "len":
            args = self._args(node, 1)
            if args is None:
                return None
            (arg,) = args
            if arg is not None and not is_list(arg) and arg != "str":
                self.issue(
                    "JIN202", node.args[0].span, f"len は list か str を取ります（実際 {arg}）"
                )
            return "num"
        if name == "str":
            args = self._args(node, 1)
            if args is None:
                return None
            (arg,) = args
            if arg is not None and arg not in PRIMITIVE_TYPES:
                self.issue(
                    "JIN202", node.args[0].span, f"str は num / bool / str を取ります（実際 {arg}）"
                )
            return "str"
        if name == "contains":
            args = self._args(node, 2)
            if args is None:
                return None
            list_type, value_type = args
            inner = item_type(list_type) if list_type and is_list(list_type) else None
            if list_type is not None and inner is None:
                self.issue("JIN202", node.args[0].span, "contains の第 1 引数は list です")
            elif inner is not None and inner not in PRIMITIVE_TYPES:
                self.issue(
                    "JIN202",
                    node.args[0].span,
                    "contains は num / bool / str の list にだけ使えます",
                )
            elif inner is not None and value_type is not None and value_type != inner:
                self.issue(
                    "JIN202",
                    node.args[1].span,
                    f"contains の第 2 引数は {inner} です（実際 {value_type}）",
                )
            return "bool"
        if name in PURE_FUNCTIONS:
            params, returns = PURE_FUNCTIONS[name]
            args = self._args(node, len(params))
            if args is None:
                return None
            for want, got, arg_node in zip(params, args, node.args, strict=True):
                if got is not None and got != want:
                    self.issue(
                        "JIN202", arg_node.span, f"{name} の引数は {want} です（実際 {got}）"
                    )
            return returns
        near = _close(name, [*PURE_FUNCTION_NAMES, *self.scope.sigils])
        self.issue(
            "JIN203",
            callee.span,
            f"関数 '{name}' はありません",
            f"近い名前: {' / '.join(near)}" if near else "純関数か '名前空間.メンバ' を使います",
        )
        return None

    def _call_member(self, node: Call, base: Name, callee: FieldAccess) -> str | None:
        if self.scope.constant:
            self.issue("JIN250", node.span, "init にホスト能力は使えません（定数式だけ）")
            return None
        sigil = self.scope.sigils.get(base.name)
        if sigil is None:
            if abilities.namespace(base.name) is not None:
                self.issue(
                    "JIN204",
                    base.span,
                    f"名前空間 '{base.name}' は道具環で許可されていません",
                    f'sigils に {{"name": "{base.name}", "kind": "host", "host": "{base.name}"}} を足す',
                )
                return None
            # 陣名.rite(...) のような形も、式の中では呼べない
            self.issue(
                "JIN203",
                base.span,
                f"'{base.name}' は道具環にありません",
                "sigils に host か summon を宣言してください",
            )
            return None
        if sigil[0] == "summon":
            self.issue(
                "JIN202",
                node.span,
                f"summon '{base.name}' は式の中では呼べません。cast で呼んで into に受けます",
            )
            return None
        namespace = abilities.namespace(sigil[1])
        if namespace is None:  # pragma: no cover - sigil の host 名は段 3 の JIN205 で先に落ちる
            return None
        member = namespace.member(callee.name)
        if member is None:
            near = _close(callee.name, [m.name for m in namespace.members])
            self.issue(
                "JIN205",
                callee.name_span,
                f"{namespace.name} にメンバ '{callee.name}' はありません",
                f"近い名前: {' / '.join(near)}"
                if near
                else f"メンバ: {' / '.join(m.name for m in namespace.members)}",
            )
            return None
        if member.returns is None:
            self.issue(
                "JIN202",
                node.span,
                f"{namespace.name}.{member.name} は値を返しません。cast で呼びます",
            )
            return None
        args = self._args(node, len(member.params), code="JIN205")
        if args is None:
            return None
        for (param_name, want), got, arg_node in zip(member.params, args, node.args, strict=True):
            if got is not None and got != want:
                self.issue(
                    "JIN202",
                    arg_node.span,
                    f"{namespace.name}.{member.name} の {param_name} は {want} です（実際 {got}）",
                )
        if member.name in ("key", "pressed"):
            first = node.args[0]
            if isinstance(first, String) and first.value not in abilities.KEY_NAMES:
                self.issue(
                    "JIN205",
                    first.span,
                    f"キー名 '{first.value}' はありません",
                    "KeyboardEvent.code の値（ArrowLeft / Space / KeyA …）",
                )
        return member.returns

    def _args(self, node: Call, count: int, code: str = "JIN202") -> list[str | None] | None:
        if len(node.args) != count:
            self.issue(
                code,
                node.span,
                f"引数は {count} 個です（実際 {len(node.args)} 個）",
            )
            for arg in node.args:
                self.infer(arg)
            return None
        return [self.infer(arg) for arg in node.args]

    # -- 型紙と list --------------------------------------------------------------
    def _construct(self, node: Construct) -> str | None:
        fields = self.scope.forms.get(node.form)
        if fields is None:
            near = _close(node.form, list(self.scope.forms))
            self.issue(
                "JIN203",
                node.form_span,
                f"型紙 '{node.form}' はありません",
                f"近い名前: {' / '.join(near)}" if near else "forms に宣言してください",
            )
            for _, _, value in node.fields:
                self.infer(value)
            return None
        seen: set[str] = set()
        for name, name_span, value in node.fields:
            if name in seen:
                self.issue("JIN202", name_span, f"欄 '{name}' が重複しています")
            seen.add(name)
            if name not in fields:
                self.issue("JIN202", name_span, f"型紙 {node.form} に欄 '{name}' はありません")
                self.infer(value)
                continue
            got = self.infer(value, fields[name])
            if got is not None and not assignable(got, fields[name]):
                self.issue(
                    "JIN202", value.span, f"欄 '{name}' は {fields[name]} です（実際 {got}）"
                )
        missing = [name for name in fields if name not in seen]
        if missing:
            self.issue(
                "JIN202",
                node.span,
                f"型紙 {node.form} の欄が足りません: {' / '.join(missing)}",
                "全欄必須です（既定値はありません）",
            )
        return node.form

    def _list(self, node: ListLiteral, expected: str | None) -> str | None:
        if not node.items:
            if expected is not None and is_list(expected):
                return expected
            if expected is None:
                self.issue(
                    "JIN202",
                    node.span,
                    "空の list の型が決まりません",
                    "let に type を書くか、要素を 1 つ入れてください",
                )
            return LIST_OF_UNKNOWN
        want = item_type(expected) if expected is not None and is_list(expected) else None
        first = self.infer(node.items[0], want)
        for item in node.items[1:]:
            got = self.infer(item, want or first)
            if first is not None and got is not None and got != first:
                self.issue("JIN202", item.span, f"list の要素は同じ型です（{first} と {got}）")
        return list_of(first) if first is not None else None


def _binary_result(op: str, left: str | None, right: str | None) -> str | None:
    """片方の型が決まらないときの暫定の型（診断の連鎖を抑える）。"""
    if op in ("and", "or", "==", "!=", "<", "<=", ">", ">="):
        return "bool"
    if op == "++":
        return "str"
    if op in ("+", "-", "*", "/", "%"):
        return "num"
    return None


def _close(name: str, candidates: list[str]) -> list[str]:
    from jin_core.semantic import close_names

    return close_names(name, candidates)


# ---------------------------------------------------------------- 定数式・形の判定


def is_constant(node: Node) -> bool:
    """`state[].init` に許す形か（model.md §5.3）。型検査とは独立に**形**だけを見る。"""
    if isinstance(node, (Number, String, Boolean)):
        return True
    if isinstance(node, Unary):
        return node.op == "-" and is_constant(node.operand)
    if isinstance(node, Construct):
        return all(is_constant(value) for _, _, value in node.fields)
    if isinstance(node, ListLiteral):
        return all(is_constant(item) for item in node.items)
    if isinstance(node, Call):
        return (
            isinstance(node.callee, Name)
            and node.callee.name in PURE_FUNCTION_NAMES
            and all(is_constant(arg) for arg in node.args)
        )
    return False


def is_place(node: Node) -> bool:
    """代入先の式の形か（model.md §5.4）: NAME / 代入先.NAME / 代入先[expr]。"""
    if isinstance(node, Name):
        return True
    if isinstance(node, FieldAccess):
        return is_place(node.obj)
    if isinstance(node, Index):
        return is_place(node.obj)
    return False


def place_root(node: Node) -> Name | None:
    """代入先の先頭の識別子。"""
    while isinstance(node, (FieldAccess, Index)):
        node = node.obj
    return node if isinstance(node, Name) else None


def walk(node: Node):
    """AST を深さ優先で列挙する（rename の識別子追随・参照の走査に使う）。"""
    yield node
    if isinstance(node, Unary):
        yield from walk(node.operand)
    elif isinstance(node, Binary):
        yield from walk(node.left)
        yield from walk(node.right)
    elif isinstance(node, FieldAccess):
        yield from walk(node.obj)
    elif isinstance(node, Index):
        yield from walk(node.obj)
        yield from walk(node.index)
    elif isinstance(node, Call):
        yield from walk(node.callee)
        for arg in node.args:
            yield from walk(arg)
    elif isinstance(node, Construct):
        for _, _, value in node.fields:
            yield from walk(value)
    elif isinstance(node, ListLiteral):
        for item in node.items:
            yield from walk(item)


__all__ = [
    "EFFECTS",
    "JIN_EXPR_GRAMMAR",
    "LIST_OF_UNKNOWN",
    "PURE_FUNCTIONS",
    "PURE_FUNCTION_NAMES",
    "SPECIAL_PURE_FUNCTIONS",
    "Binary",
    "Boolean",
    "Call",
    "Construct",
    "ExprSyntaxError",
    "FieldAccess",
    "Index",
    "ListLiteral",
    "Name",
    "Node",
    "Number",
    "Scope",
    "Span",
    "String",
    "TypeCheck",
    "TypeIssue",
    "Unary",
    "assignable",
    "check_expr",
    "is_constant",
    "is_list",
    "is_place",
    "item_type",
    "list_of",
    "parse_expr",
    "place_root",
    "walk",
]
