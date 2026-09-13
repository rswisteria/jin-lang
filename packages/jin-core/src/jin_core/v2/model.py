"""Jin v2 の意味モデル（Pydantic v2）。

**このファイルが v2 の意味モデルの唯一の真実**。`schemas/jin-v2.schema.json` はここから生成し、
CI でドリフトを検出する。正準形のキー順（docs/spec/v2/model.md §9）は各モデルのフィールド定義順
そのものである。フィールドを並べ替えると正準形の出力が変わるので、model.md の表と同時に直すこと。

v1 の `jin_core.model` とは独立している（共有するのは `JinModel` の設定と文字列型だけ）。
"""

from __future__ import annotations

import functools
import re
import typing
from typing import Annotated, Literal, Union, get_args, get_origin

from pydantic import BaseModel, Field, model_validator
from pydantic.fields import FieldInfo

from jin_core.model import MAX_IDENT_LENGTH, Ident, JinModel, Text, Url

#: v2 の既定スキーマ URL。v1 の `jin.schema.json` とは別ファイル（設計書 §11 #16）。
DEFAULT_SCHEMA_URL_V2 = "https://xtone.internal/jin/schemas/jin-v2.schema.json"

#: 名前の文法（docs/spec/v2/model.md §3）。式の識別子と同じなので、式の中からそのまま参照できる。
NAME_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*$"

#: 舞台の論理解像度の範囲（model.md §1）。
MIN_STAGE_SIZE = 16
MAX_STAGE_SIZE = 1024
MIN_FPS = 1
MAX_FPS = 120
MAX_SEED = 2**32 - 1

#: 名前（circle / form / state / sigil / rite / 局所）。識別子の文法に合致する Ident。
Name = Annotated[str, Field(max_length=MAX_IDENT_LENGTH, pattern=NAME_PATTERN)]

#: 型の文字列（model.md §5.1）。文法の検査は `_validate_type` が行う。
#: 存在しない型紙を指すかどうかは段 3（JIN011）で見る。
TypeStr = Annotated[Ident, Field(pattern=r"^[A-Za-z_<>][A-Za-z0-9_<>]*$")]

#: 葉の式（docs/spec/v2/expr.md）。モデル段では文字列として保持し、構文と型は段 3 で検査する。
#: 改行やタブを含む式は段 3 の JIN201 が落とす（Text は改行を許すので、ここでは通す）。
#:
#: `x-jin-expr` は **schema の印**（設計書 §8「式の欄だけ式エディタにする」）。エディタは
#: `schemas/jin-v2.schema.json` のこの印だけを見て式エディタを出し、欄の名前を書き写さない。
#: LSP の completion も同じ印（`expr_fields`）で「式の中か」を判定する。v1 の `Text` には付けない
#: （`jin.schema.json` を 1 バイトも変えない・設計書 §11 #16）。
EXPR_SCHEMA_MARK = "x-jin-expr"
Expr = Annotated[Text, Field(json_schema_extra={EXPR_SCHEMA_MARK: True})]

FlowKind = Literal["sequence", "parallel", "loop"]
SigilKind = Literal["host", "summon"]
LoopKind = Literal["each", "while", "count"]
EventKind = Literal["tick", "key", "pointer", "message", "exit"]
AssetKind = Literal["sprite", "sound"]

PRIMITIVE_TYPES = ("num", "bool", "str")


def parse_type(text: str) -> tuple[str, str | None]:
    """型文字列を（先頭の型名, list の要素型）に分解する。文法違反は ValueError。

    `list<T>` は再帰的に検査する。返り値は `("num", None)` / `("list", "Ball")` の形で、
    要素型の更なる分解は呼び出し側が再帰する。
    """
    if text.startswith("list<"):
        if not text.endswith(">"):
            raise ValueError(f"型 {text!r} の '>' が閉じていません")
        inner = text[5:-1]
        parse_type(inner)
        return "list", inner
    if text in PRIMITIVE_TYPES:
        return text, None
    if re.fullmatch(NAME_PATTERN, text):
        return text, None
    raise ValueError(f"型 {text!r} は num / bool / str / list<T> / 型紙名 のいずれでもありません")


class Asset(JinModel):
    name: Name
    kind: AssetKind
    path: Ident


class Stage(JinModel):
    """舞台（model.md §1）。数値は整数値（`60.0` は正準形でなくスキーマ違反）。"""

    width: int = Field(ge=MIN_STAGE_SIZE, le=MAX_STAGE_SIZE)
    height: int = Field(ge=MIN_STAGE_SIZE, le=MAX_STAGE_SIZE)
    fps: int = Field(default=60, ge=MIN_FPS, le=MAX_FPS)
    seed: int = Field(default=0, ge=0, le=MAX_SEED)
    assets: list[Asset] = Field(default_factory=list)


class FormField(JinModel):
    name: Name
    type: TypeStr

    @model_validator(mode="after")
    def _type_is_well_formed(self) -> FormField:
        parse_type(self.type)
        return self


class Form(JinModel):
    """型紙（model.md §2）。"""

    name: Name
    fields: list[FormField]


class State(JinModel):
    name: Name
    type: TypeStr
    init: Expr
    out: bool = False

    @model_validator(mode="after")
    def _type_is_well_formed(self) -> State:
        parse_type(self.type)
        return self


class SigilHost(JinModel):
    """kind: host → ホスト能力の名前空間を許可する（abilities.md）。"""

    name: Name
    kind: Literal["host"]
    host: Name


class SigilSummon(JinModel):
    """kind: summon → 他の陣の手順の同期呼び出し。"""

    name: Name
    kind: Literal["summon"]
    circle: Name
    rite: Name


Sigil = Annotated[SigilHost | SigilSummon, Field(discriminator="kind")]


class Param(JinModel):
    name: Name
    type: TypeStr

    @model_validator(mode="after")
    def _type_is_well_formed(self) -> Param:
        parse_type(self.type)
        return self


# ---------------------------------------------------------------- ステップ（11 種）


class SetStep(JinModel):
    do: Literal["set"]
    target: Expr
    expr: Expr


class LetStep(JinModel):
    do: Literal["let"]
    name: Name
    expr: Expr
    type: TypeStr | None = None

    @model_validator(mode="after")
    def _type_is_well_formed(self) -> LetStep:
        if self.type is not None:
            parse_type(self.type)
        return self


class CastStep(JinModel):
    do: Literal["cast"]
    target: Expr
    args: list[Expr] = Field(default_factory=list)
    into: Expr | None = None


class IfStep(JinModel):
    do: Literal["if"]
    cond: Expr
    then: list[Step]
    # `else` は Python の予約語なので属性名は else_ とし、JSON 側の名前は alias で与える。
    else_: list[Step] = Field(default_factory=list, alias="else")


class LoopStep(JinModel):
    """`kind` ごとに許すキーが違う（model.md §3.4）。違反は段 2（JIN002）で落とす。"""

    do: Literal["loop"]
    kind: LoopKind
    name: Name | None = None
    # `in` は Python の予約語。
    in_: Expr | None = Field(default=None, alias="in")
    cond: Expr | None = None
    times: Expr | None = None
    steps: list[Step]

    @model_validator(mode="after")
    def _keys_match_kind(self) -> LoopStep:
        required = {"each": ("name", "in_"), "while": ("cond",), "count": ("times",)}[self.kind]
        allowed = {
            "each": ("name", "in_"),
            "while": ("cond",),
            "count": ("times", "name"),
        }[self.kind]
        for key in required:
            if getattr(self, key) is None:
                raise ValueError(f"loop の kind: {self.kind} には {_json_key(key)} が要ります")
        for key in ("name", "in_", "cond", "times"):
            if key not in allowed and getattr(self, key) is not None:
                raise ValueError(f"{_json_key(key)} は loop の kind: {self.kind} では使えません")
        return self


def _json_key(attr: str) -> str:
    return attr.rstrip("_")


class BreakStep(JinModel):
    do: Literal["break"]


class WaitStep(JinModel):
    do: Literal["wait"]
    ticks: Expr | None = None
    until: Expr | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> WaitStep:
        if (self.ticks is None) == (self.until is None):
            raise ValueError("wait には ticks か until のどちらか 1 つを書きます")
        return self


class EmitStep(JinModel):
    do: Literal["emit"]
    circle: Name
    message: Name
    args: list[Expr] = Field(default_factory=list)


class ReturnStep(JinModel):
    do: Literal["return"]
    expr: Expr | None = None


class FinishStep(JinModel):
    do: Literal["finish"]


class TransferStep(JinModel):
    do: Literal["transfer"]
    circle: Name


Step = Annotated[
    SetStep
    | LetStep
    | CastStep
    | IfStep
    | LoopStep
    | BreakStep
    | WaitStep
    | EmitStep
    | ReturnStep
    | FinishStep
    | TransferStep,
    Field(discriminator="do"),
]

IfStep.model_rebuild()
LoopStep.model_rebuild()

#: ステップの `do` の値（11 種）。docs/spec/v2/model.md §3.4 と一致させる。
STEP_KINDS: tuple[str, ...] = (
    "set",
    "let",
    "cast",
    "if",
    "loop",
    "break",
    "wait",
    "emit",
    "return",
    "finish",
    "transfer",
)


class Rite(JinModel):
    """手順（model.md §3.3）。ステップ数の上限（12）は段 3（JIN210）で見る。"""

    name: Name
    params: list[Param] = Field(default_factory=list)
    returns: TypeStr | None = None
    steps: list[Step]

    @model_validator(mode="after")
    def _returns_is_well_formed(self) -> Rite:
        if self.returns is not None:
            parse_type(self.returns)
        return self


class OnHandler(JinModel):
    event: EventKind
    rite: Name


class Guard(JinModel):
    # `assert` は Python の予約語。
    assert_: Expr = Field(alias="assert")
    message: Text | None = None


class Boundary(JinModel):
    on: list[OnHandler] = Field(default_factory=list)
    guards: list[Guard] = Field(default_factory=list)


class Flow(JinModel):
    kind: FlowKind
    steps: list[Name] = Field(min_length=1)
    exit: Expr | None = None

    @model_validator(mode="after")
    def _exit_is_loop_only_and_required(self) -> Flow:
        """`exit` は kind: loop のとき必須で、それ以外では使えない（model.md §6）。"""
        if self.kind == "loop" and self.exit is None:
            raise ValueError("kind: loop には exit が要ります")
        if self.kind != "loop" and self.exit is not None:
            raise ValueError(f"exit は kind: loop でだけ使えます（kind: {self.kind}）")
        return self


class Circle(JinModel):
    """陣。核あり（core）と核なし（flow）の 2 種類がある（JIN022 は段 3）。"""

    name: Name
    description: Text | None = None
    core: Name | None = None
    flow: Flow | None = None
    state: list[State] = Field(default_factory=list)
    sigils: list[Sigil] = Field(default_factory=list)
    rites: list[Rite] = Field(default_factory=list)
    boundary: Boundary | None = None
    delegate: list[Name] = Field(default_factory=list)

    @model_validator(mode="after")
    def _flow_circles_carry_nothing_else(self) -> Circle:
        """核なし陣は state / sigils / rites / boundary / delegate を持てない（model.md §3）。"""
        if self.flow is not None and self.core is None:
            for key in ("state", "sigils", "rites", "delegate"):
                if getattr(self, key):
                    raise ValueError(f"flow を持つ陣に {key} は置けません")
            if self.boundary is not None:
                raise ValueError("flow を持つ陣に boundary は置けません")
        return self


def _carries_expr_mark(annotation: object) -> bool:
    """型注釈の木のどこかに `Expr`（`x-jin-expr` 付き `Field`）があるか。"""
    if get_origin(annotation) is Annotated:
        base, *extras = get_args(annotation)
        for extra in extras:
            if isinstance(extra, FieldInfo):
                extra_schema = extra.json_schema_extra
                if isinstance(extra_schema, dict) and extra_schema.get(EXPR_SCHEMA_MARK):
                    return True
        return _carries_expr_mark(base)
    if get_origin(annotation) in (Union, type(int | str), list):
        return any(_carries_expr_mark(argument) for argument in get_args(annotation))
    return False


@functools.cache
def expr_fields(cls: type[BaseModel]) -> frozenset[str]:
    """`cls` の欄のうち**式**を受けるもの（JSON 側のキー名）。

    `list[Expr]`（`cast.args`）と `Expr | None` も含む。名前を書き写さず `Expr` の印から引くので、
    モデルに式の欄を足せば LSP の completion もエディタの式エディタも追随する。
    """
    hints = typing.get_type_hints(cls, include_extras=True)
    names: set[str] = set()
    for name, info in cls.model_fields.items():
        if _carries_expr_mark(hints.get(name)):
            names.add(info.alias or name)
    return frozenset(names)


class JinFileV2(JinModel):
    """`.jin`（version 2）1 本に対応するルートモデル。"""

    schema_url: Url = Field(alias="$schema")
    version: Literal[2]
    root: Name
    stage: Stage
    forms: list[Form] = Field(default_factory=list)
    circles: list[Circle] = Field(min_length=1)


__all__ = [
    "DEFAULT_SCHEMA_URL_V2",
    "EXPR_SCHEMA_MARK",
    "MAX_FPS",
    "MAX_SEED",
    "MAX_STAGE_SIZE",
    "MIN_FPS",
    "MIN_STAGE_SIZE",
    "NAME_PATTERN",
    "PRIMITIVE_TYPES",
    "STEP_KINDS",
    "Asset",
    "AssetKind",
    "Boundary",
    "BreakStep",
    "CastStep",
    "Circle",
    "EmitStep",
    "EventKind",
    "Expr",
    "FinishStep",
    "Flow",
    "FlowKind",
    "Form",
    "FormField",
    "Guard",
    "IfStep",
    "JinFileV2",
    "LetStep",
    "LoopKind",
    "LoopStep",
    "Name",
    "OnHandler",
    "Param",
    "ReturnStep",
    "Rite",
    "SetStep",
    "Sigil",
    "SigilHost",
    "SigilKind",
    "SigilSummon",
    "Stage",
    "State",
    "Step",
    "TransferStep",
    "TypeStr",
    "WaitStep",
    "expr_fields",
    "parse_type",
]
