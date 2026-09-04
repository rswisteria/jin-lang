"""Jin の意味モデル（Pydantic v2）。

**このファイルが意味モデルの唯一の真実**（NFR-SSOT-001）。
`schemas/jin.schema.json` はここから生成し、CI でドリフトを検出する。
正準形のキー順（docs/spec/model.md §7 規則 2）は、各モデルのフィールド定義順そのものである。
フィールドを並べ替えると正準形の出力が変わるので、docs/spec/model.md の表と同時に直すこと。
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

#: `.jin` の既定スキーマ URL（要件書 §2.2 の例）。
DEFAULT_SCHEMA_URL = "https://xtone.internal/jin/schemas/jin.schema.json"

#: 識別子的な文字列（circle 名 / tool 名 / state 名 / 参照）の最大長。
#: 決定根拠は delivery/20260904-1445-jin/decision-conformance.md（DP-JIN-STRLIMIT-01）。
MAX_IDENT_LENGTH = 128

#: 自由記述文字列（instruction.rune / description）の最大長。
MAX_TEXT_LENGTH = 65536

#: `$schema` に許す最大長。
MAX_URL_LENGTH = 2048

#: guards[].on の許容値（docs/spec/model.md §3.5）。ADK のコールバック引数名に 1:1 対応する。
GuardOn = Literal[
    "before_agent",
    "after_agent",
    "before_model",
    "after_model",
    "before_tool",
    "after_tool",
]

#: flow.kind の許容値。
FlowKind = Literal["sequence", "parallel", "loop"]

#: 自由記述の中でだけ許す空白制御文字。
_ALLOWED_CONTROL = frozenset("\n\r\t")


def _describe(ch: str) -> str:
    return f"U+{ord(ch):04X}"


def _reject_bad_chars(value: str, *, allow_whitespace: bool) -> str:
    """制御文字と孤立サロゲートを拒む。

    - 制御文字（C0 / DEL / C1）は診断メッセージやターミナル出力に混ざると
      表示を偽装できる（ANSI エスケープ注入）。
    - 孤立サロゲートは UTF-8 に符号化できず、`jin fmt` の書き出しが
      `UnicodeEncodeError` で落ちる。段 2（スキーマ）で JIN002 として弾く。
    """
    for ch in value:
        code = ord(ch)
        if 0xD800 <= code <= 0xDFFF:
            raise ValueError(
                f"孤立サロゲート {_describe(ch)} は使えません（UTF-8 に符号化できません）"
            )
        is_control = code < 0x20 or code == 0x7F or 0x80 <= code <= 0x9F
        if is_control and not (allow_whitespace and ch in _ALLOWED_CONTROL):
            raise ValueError(f"制御文字 {_describe(ch)} は使えません")
    return value


def _validate_ident(value: str) -> str:
    return _reject_bad_chars(value, allow_whitespace=False)


def _validate_text(value: str) -> str:
    return _reject_bad_chars(value, allow_whitespace=True)


#: 名前・参照に使う文字列。改行やタブも含め制御文字を一切許さない。
Ident = Annotated[str, Field(max_length=MAX_IDENT_LENGTH), AfterValidator(_validate_ident)]

#: 自由記述の文字列。改行 / 復帰 / タブだけ許す。
Text = Annotated[str, Field(max_length=MAX_TEXT_LENGTH), AfterValidator(_validate_text)]

#: URL 文字列。制御文字は許さないが、識別子より長い値を許す。
Url = Annotated[str, Field(max_length=MAX_URL_LENGTH), AfterValidator(_validate_ident)]


class JinModel(BaseModel):
    """全モデル共通の設定。

    - ``extra="forbid"``: 未知のキーはスキーマ違反（要件書 §2.2 / JIN002）
    - ``strict=True``: ``"max": "3"`` のような暗黙変換を禁じる。変換を許すと
      ``jin fmt`` が値を書き換えてしまい、意味保存（NFR-DET-002）が崩れる
    - ``populate_by_name=True``: ``$schema`` / ``await`` を Python 側の別名でも扱えるようにする
    """

    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)


class Instruction(JinModel):
    rune: Text


class ToolFunction(JinModel):
    """kind: tool → ADK の FunctionTool（await 対象なら LongRunningFunctionTool）。"""

    name: Ident
    kind: Literal["tool"]
    ref: Ident


class ToolBuiltin(JinModel):
    """kind: builtin → ADK の組み込みツールのインスタンス。"""

    name: Ident
    kind: Literal["builtin"]
    builtin: Ident


class ToolSummon(JinModel):
    """kind: summon → ADK の AgentTool。親子辺は作らない（docs/spec/model.md §4）。"""

    name: Ident
    kind: Literal["summon"]
    circle: Ident


Tool = Annotated[ToolFunction | ToolBuiltin | ToolSummon, Field(discriminator="kind")]


class State(JinModel):
    name: Ident
    type: Ident
    out: bool = False


class FlowExit(JinModel):
    key: Ident
    equals: bool | int | float | Text


class Flow(JinModel):
    kind: FlowKind
    steps: list[Ident]
    max: int | None = Field(default=None, ge=1)
    exit: FlowExit | None = None

    @model_validator(mode="after")
    def _max_and_exit_are_loop_only(self) -> Flow:
        """`max` / `exit` は kind: loop でだけ意味を持つ（docs/spec/model.md §3.4）。

        sequence / parallel に付いた `max` / `exit` は ADK 生成側で捨てられ、
        書いた人の意図が黙って消える。段 2（スキーマ）で JIN002 として弾く。
        """
        if self.kind != "loop":
            for key in ("max", "exit"):
                if getattr(self, key) is not None:
                    raise ValueError(f"{key} は kind: loop でだけ使えます（kind: {self.kind}）")
        return self


class Guard(JinModel):
    on: GuardOn
    ref: Ident


class Boundary(JinModel):
    guards: list[Guard] = Field(default_factory=list)
    # `await` は Python の予約語なので属性名は await_ とし、JSON 側の名前は alias で与える。
    await_: list[Ident] = Field(default_factory=list, alias="await")


class Circle(JinModel):
    """陣。核あり（core）と核なし（flow）の 2 種類がある（JIN022）。"""

    name: Ident
    core: Ident | None = None
    description: Text | None = None
    instruction: Instruction | None = None
    tools: list[Tool] = Field(default_factory=list)
    delegate: list[Ident] = Field(default_factory=list)
    state: list[State] = Field(default_factory=list)
    flow: Flow | None = None
    boundary: Boundary | None = None


class JinFile(JinModel):
    """`.jin` ファイル 1 本に対応するルートモデル。"""

    # `$schema` は Python の識別子にできないので属性名は schema_url とする。
    schema_url: Url = Field(alias="$schema")
    version: Literal[1]
    root: Ident
    circles: list[Circle]


__all__ = [
    "DEFAULT_SCHEMA_URL",
    "MAX_IDENT_LENGTH",
    "MAX_TEXT_LENGTH",
    "MAX_URL_LENGTH",
    "Boundary",
    "Circle",
    "Flow",
    "FlowExit",
    "FlowKind",
    "Guard",
    "GuardOn",
    "Ident",
    "Instruction",
    "JinFile",
    "JinModel",
    "State",
    "Text",
    "Tool",
    "ToolBuiltin",
    "ToolFunction",
    "ToolSummon",
    "Url",
]
