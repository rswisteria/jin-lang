"""意味モデル → ADK プロジェクト（`agent.py` / `__init__.py` / `.env.example`）と pointer 対応表。

正典は `docs/spec/adk-mapping.md`。生成コードの引数名は google-adk 2.8.0 の実測
（`delivery/20260904-1445-jin/adk-api-probe.md`）に固定してあり、記憶で書き換えない。

## 安全の約束（design.yaml review_axes_note (1)）

`.jin` 由来の文字列（`name` / `description` / `instruction.rune` / `ref` / `builtin` /
`flow.exit.equals` …）は **すべて `py_literal` を通して Python の文字列リテラルにしてから**
テンプレートへ渡す。**`.jin` の外から来る文字列（`source_name` = ファイル名）も同じ**
（security review F-S-P2-001: 改行入りのファイル名がヘッダのコメントを文にした）。
識別子として埋め込むもの（circle 名 = 変数名 / import する名前）は
`str.isidentifier()` と予約語検査、**NFKC 正規形であること**（Python は識別子を NFKC 正規化して
束縛する・PEP 3131。全角 `ｒｏｏｔ＿ａｇｅｎｔ` は `root_agent` と同じ変数になる・F-S-P2-002）を
通したものしか使わない。テンプレート側で `.jin` の値をそのまま式に置く経路は無い
（`test_jin_strings_cannot_inject_statements` が固定する）。

    guard: py_literal -> json.dumps
    guard: _header -> py_literal(source_name)
    guard: _check_identifier -> keyword.iskeyword
    guard: _check_identifier -> unicodedata.normalize
    guard: _plan_imports -> check_ref_format(ref)

## NFR-FAIL-001

ADK に対応物のない Jin 構造は `BuildError` で落とす。黙って捨てない。
一覧は `docs/spec/adk-mapping.md` §3.1。診断コードは増やさない（`CLAUDE.md` / ADR-012）。

## ADR-008 / ADR-009

- `StateCheckAgent` のクラス本体は生成物に**毎回**埋め込む（1 ファイルに 1 定義、ループごとにインスタンス化）
- FakeLlm は生成物に現れない（`jin_adk.fake_llm`）
- pointer 対応表 `PointerMap` は生成物とは別のオブジェクトとして返す。`agent.py` には埋め込まない
"""

from __future__ import annotations

import inspect
import json
import keyword
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from jin_core.model import (
    Circle,
    Flow,
    FlowExit,
    JinFile,
    ToolBuiltin,
    ToolFunction,
    ToolSummon,
)
from jin_core.pointer import join
from jin_core.resolver import check_ref_format
from jin_core.semantic import rune_key_spans

from jin_adk import TARGET_ADK_VERSION
from jin_adk.templates import render_agent_py

# ======================================================================================
# エラー
# ======================================================================================


class BuildError(Exception):
    """ADK に対応物のない Jin 構造（NFR-FAIL-001）。

    `jin check` を通ったモデルに対して `jin build` / `jin run` が出す唯一のエラー種。
    メッセージは「何が悪いか」、`hint` は「どう直すか」、`pointer` は場所。
    診断コード（JINxxx）は持たない（`CLAUDE.md` / ADR-012・勝手に採番しない）。
    """

    def __init__(self, message: str, *, pointer: str, hint: str) -> None:
        super().__init__(message)
        self.message = message
        self.pointer = pointer
        self.hint = hint

    def __str__(self) -> str:
        return f"{self.message}\n  hint: {self.hint}\n  pointer: {self.pointer or '(root)'}"


# ======================================================================================
# pointer 対応表（ADR-009 案 B）
# ======================================================================================


@dataclass(frozen=True)
class AgentEntry:
    """ADK の agent 1 つ分の pointer。キーは ADK 上の識別子（agent 名）。"""

    #: circle 自身: `/circles/i`
    pointer: str
    #: `/circles/i/core`（LlmAgent のとき）。workflow agent は None
    core: str | None
    #: `core` の文字列（モデル名）。トレースの `name` に使う
    model: str | None
    #: `tools[j]` の pointer を宣言順に。生成コードの `tools=[...]` と同じ順序（添字で引く）
    tools: tuple[str, ...]
    #: delegate 先の agent 名 → `/circles/i/delegate/k`
    delegate: dict[str, str]
    #: `/circles/i/flow/exit`（loop かつ exit があるとき）
    exit: str | None

    def to_json(self) -> dict[str, Any]:
        return {
            "pointer": self.pointer,
            "core": self.core,
            "model": self.model,
            "tools": list(self.tools),
            "delegate": dict(self.delegate),
            "exit": self.exit,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> AgentEntry:
        return cls(
            pointer=data["pointer"],
            core=data["core"],
            model=data["model"],
            tools=tuple(data["tools"]),
            delegate=dict(data["delegate"]),
            exit=data["exit"],
        )


@dataclass(frozen=True)
class PointerMap:
    """ADK 識別子 → JSON Pointer の対応表。

    `jin run` の実行時に `Event.author` / function_call 名 / `transfer_to_agent` から引く
    （`jin_adk.trace`）。生成物には埋め込まない（ADR-009 constraint）。
    """

    #: root circle の名前（= `root_agent.name`）
    root: str
    #: agent 名 → entry
    agents: dict[str, AgentEntry]
    #: StateCheckAgent の名前 → それが属する loop circle の名前
    exit_checkers: dict[str, str]

    def all_pointers(self) -> list[str]:
        out: list[str] = []
        for entry in self.agents.values():
            out.append(entry.pointer)
            if entry.core is not None:
                out.append(entry.core)
            out.extend(entry.tools)
            out.extend(entry.delegate.values())
            if entry.exit is not None:
                out.append(entry.exit)
        return out

    def to_json(self) -> str:
        return json.dumps(
            {
                "root": self.root,
                "agents": {name: entry.to_json() for name, entry in self.agents.items()},
                "exit_checkers": dict(self.exit_checkers),
            },
            ensure_ascii=False,
            indent=2,
        )

    @classmethod
    def from_json(cls, text: str) -> PointerMap:
        data = json.loads(text)
        return cls(
            root=data["root"],
            agents={name: AgentEntry.from_json(e) for name, e in data["agents"].items()},
            exit_checkers=dict(data["exit_checkers"]),
        )


@dataclass(frozen=True)
class GeneratedProject:
    """`jin build` の出力（要件書 §3.1）。ファイルへ書くのは `jin_adk.build`。"""

    root_name: str
    agent_py: str
    init_py: str
    env_example: str
    pointers: PointerMap


# ======================================================================================
# 文字列 → Python リテラル
# ======================================================================================

#: Python のソースに生で置きたくない文字。C0 / DEL / C1 は `json.dumps` が `\\uXXXX` に
#: するが、U+2028 / U+2029 は素通しになるので自前で足す（Python の字句解析では改行扱いに
#: ならないが、エディタや diff ツールで行が化けるため）。
_EXTRA_ESCAPES = {0x2028: "\\u2028", 0x2029: "\\u2029", 0x7F: "\\u007f"}
_EXTRA_ESCAPES.update({code: f"\\u{code:04x}" for code in range(0x80, 0xA0)})
#: 孤立サロゲート（不正 UTF-8 バイトを含むファイル名が surrogateescape で `\udcXX` になる）。
#: `json.dumps(ensure_ascii=False)` は素通しするので、生成物を UTF-8 で書けなくなる（F-S-P2-005）。
#: `.jin` 本文は JIN002 が先に弾くが、`source_name` はここで閉じる。
_EXTRA_ESCAPES.update({code: f"\\u{code:04x}" for code in range(0xD800, 0xE000)})


def py_literal(text: str) -> str:
    """文字列を **1 行の** Python 文字列リテラル（二重引用符）にする。

    `json.dumps` のエスケープ（`\\"` `\\\\` `\\n` `\\r` `\\t` `\\uXXXX`）は Python の
    文字列リテラルとしてもそのまま妥当で、`ast.literal_eval` で元の値に戻る
    （`test_py_literal_roundtrips`）。非 ASCII はエスケープしない（読める生成物にする）。

    guard: py_literal -> json.dumps
    """
    return json.dumps(text, ensure_ascii=False).translate(_EXTRA_ESCAPES)


def py_value(value: bool | float | str) -> str:
    """`flow.exit.equals`（bool / int / float / str）を Python リテラルにする。"""
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, int):
        return repr(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ValueError(f"equals に NaN / Infinity は使えません: {value!r}")
        return repr(value)
    return py_literal(value)


def py_text_block(text: str) -> list[str]:
    """複数行の文字列を「1 行 1 リテラル」の並びにする（暗黙の連結で読める形にする）。

    `"a\\nb"` → `['"a\\n"', '"b"']`。末尾が改行で終わるときは空の最終片を出さない。
    """
    parts = text.split("\n")
    lines: list[str] = []
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        if last and part == "" and lines:
            break
        lines.append(py_literal(part + ("" if last else "\n")))
    return lines or [py_literal("")]


# ======================================================================================
# 名前の検査
# ======================================================================================

#: 生成コードの中で既に使われている名前。circle 名（= 変数名）と衝突してはいけない。
#: テンプレート（`_state_matches` / `StateCheckAgent`）が参照する**組み込み名**も含む: circle 名が
#: `str` だと `str = LlmAgent(...)` が組み込みを上書きし、`isinstance(actual, str)` が実行時
#: `TypeError` になる（F-S-P2-103）。列挙の漏れは `test_codegen.py::
#: test_reserved_names_cover_every_free_name_the_template_uses` がテンプレートの AST から落とす。
RESERVED_NAMES = frozenset(
    {
        "AgentTool",
        "AsyncGenerator",
        "BaseAgent",
        "Event",
        "EventActions",
        "FunctionTool",
        "InvocationContext",
        "LlmAgent",
        "LongRunningFunctionTool",
        "LoopAgent",
        "ParallelAgent",
        "SequentialAgent",
        "StateCheckAgent",
        "ValueError",
        "_state_matches",
        "bool",
        "float",
        "int",
        "isinstance",
        "json",
        "object",
        "root_agent",
        "str",
    }
)

#: StateCheckAgent の agent 名の接尾辞。`<loop circle 名> + 接尾辞` が ADK 上の名前になる。
EXIT_CHECKER_SUFFIX = "_exit_check"

#: google-adk 2.8.0 の `instruction` テンプレート置換パターン
#: （実測: `google/adk/utils/instructions_utils.py:41` の `_TEMPLATE_VAR_PATTERN`）。
_ADK_TEMPLATE_VAR = re.compile(r"{+[^{}]*}+")
#: 同 `State.APP_PREFIX` / `USER_PREFIX` / `TEMP_PREFIX`（`_is_valid_state_name`）。
_ADK_STATE_PREFIXES = ("app", "user", "temp")


def _adk_is_valid_state_name(name: str) -> bool:
    """`instructions_utils._is_valid_state_name` の写し（2.8.0 実測）。"""
    parts = name.split(":")
    if len(parts) == 1:
        return name.isidentifier()
    if len(parts) == 2:
        return parts[0] in _ADK_STATE_PREFIXES and parts[1].isidentifier()
    return False


def adk_template_conflicts(rune: str) -> list[str]:
    """ADK が state 参照として置換するが、Jin は参照とみなさない断片を返す。

    Jin の規則（`docs/spec/model.md` §3.1）: `{ident}` だけが参照、`{{` / `}}` はリテラルの
    エスケープ。ADK 2.8.0 の規則（実測）: `{+[^{}]*}+` にマッチした全体を 1 つの変数として扱い、
    `{{lit}}` は変数 `lit`、`{draft}}` は末尾の `}` まで消費、`{key?}` は省略可能な変数、
    `{artifact.x}` / `{app:key}` は別の参照。Jin の読みと ADK の読みが一致する断片
    （素の `{ident}`）だけを許し、それ以外で ADK が置換するものを衝突として返す。
    """
    jin_spans = {(start, end) for start, end, _ in rune_key_spans(rune)}
    conflicts: list[str] = []
    for match in _ADK_TEMPLATE_VAR.finditer(rune):
        if (match.start(), match.end()) in jin_spans:
            continue
        inner = match.group().lstrip("{").rstrip("}").strip()
        name = inner.removesuffix("?")
        if name.startswith("artifact.") or _adk_is_valid_state_name(name):
            conflicts.append(match.group())
    return conflicts


def _check_identifier(name: str, *, pointer: str, what: str) -> None:
    """circle 名は ADK の agent 名（`isidentifier()` かつ `user` 以外・実測）であり、
    生成コードの変数名でもある（Python の予約語は不可・NFKC 正規形のみ）。

    NFKC: Python は識別子を NFKC 正規化してから束縛する（PEP 3131）。`isidentifier()` は
    全角 `ｒｏｏｔ＿ａｇｅｎｔ` を通すが、生成コードでは `root_agent` **と同じ変数**になり、
    予約名・衝突の検査（文字列一致）を迂回して root を乗っ取れる（security review F-S-P2-002・実測）。
    正規形でない名前はそれ自体を拒む（正規化して通すと `.jin` の名前と ADK の agent 名がずれる）。

    guard: _check_identifier -> keyword.iskeyword
    guard: _check_identifier -> unicodedata.normalize
    """
    if not name.isidentifier():
        raise BuildError(
            f"{what} '{name}' は Python の識別子ではないので ADK の agent 名にできません"
            "（ADK 2.8.0 は agent 名に isidentifier() を要求します）",
            pointer=pointer,
            hint="英数字とアンダースコアだけの名前にしてください（先頭は英字か _）",
        )
    normalized = unicodedata.normalize("NFKC", name)
    if normalized != name:
        raise BuildError(
            f"{what} '{name}' は NFKC 正規形ではありません。Python は識別子を NFKC 正規化して"
            f"束縛するので、生成コードでは '{normalized}' と同じ変数になります",
            pointer=pointer,
            hint=f"正規形の名前にしてください（例: {normalized}）",
        )
    if keyword.iskeyword(name) or name in ("True", "False", "None"):
        raise BuildError(
            f"{what} '{name}' は Python の予約語なので生成コードの変数名にできません",
            pointer=pointer,
            hint=f"別の名前にしてください（例: {name}_agent）",
        )
    if name == "user":
        raise BuildError(
            f"{what} 'user' は ADK が利用者の入力用に予約している名前です",
            pointer=pointer,
            hint="別の名前にしてください（例: user_agent）",
        )
    if name in RESERVED_NAMES:
        raise BuildError(
            f"{what} '{name}' は生成コードが使う名前と衝突します",
            pointer=pointer,
            hint=f"別の名前にしてください（例: {name}_circle）。{name!r} は生成コードが使う名前"
            "（組み込み名を含む・jin_adk.codegen.RESERVED_NAMES）です",
        )


# ======================================================================================
# import の解決
# ======================================================================================


@dataclass(frozen=True)
class _ImportPlan:
    """`module.path:callable` → 生成コード上の名前（2 パス目の描画で引く）。"""

    #: ref → 束縛名（別名を付けたときは別名）
    name_of: dict[str, str]
    #: `from m import a, b as m__b` の行（モジュールの初出順）
    lines: list[str]


def _plan_imports(model: JinFile, taken: set[str]) -> _ImportPlan:
    """全 ref を先に集めて名前を確定する（1 パス目）。

    同じ callable 名が別モジュールから来る（`a:run` と `b:run`）か、circle 名・予約名・
    **builtin 名**（`from google.adk.tools import google_search` と同じ名前の束縛・F-C-P2-001）と
    衝突するときは `<module_with_underscores>__<callable>` の別名で import する。
    後から別名に変わる名前が無いよう、描画（2 パス目）の前に全部決める。
    別名にしても `FunctionTool.name == func.__name__` は変わらないので、同じ circle 内で
    ADK のツール名が重なるものは `_validate_core_circle` が先に `BuildError` にする。

    形式検査は `jin check` では行わない（`--resolve` 時だけ `ImportResolver` が見る）ので、
    ここで必ず見る。`from <ref> import` に不正な文字列を流さないための境界。

    guard: _plan_imports -> check_ref_format(ref)
    """
    refs: list[tuple[str, str]] = []  # (ref, pointer) 出現順
    for i, circle in enumerate(model.circles):
        base = join(join("", "circles"), i)
        for j, tool in enumerate(circle.tools):
            if isinstance(tool, ToolFunction):
                refs.append((tool.ref, join(join(join(base, "tools"), j), "ref")))
        if circle.boundary is not None:
            for k, guard in enumerate(circle.boundary.guards):
                refs.append(
                    (guard.ref, join(join(join(join(base, "boundary"), "guards"), k), "ref"))
                )

    owners: dict[str, set[str]] = {}
    parsed: list[tuple[str, str, str]] = []
    for ref, pointer in refs:
        reason = check_ref_format(ref)
        if reason is not None:
            raise BuildError(
                f"ref '{ref}' は {reason}（module.path:callable の形だけを受け付けます）",
                pointer=pointer,
                hint="例: research.tools:web_search",
            )
        module, _, attribute = ref.partition(":")
        owners.setdefault(attribute, set()).add(module)
        parsed.append((ref, module, attribute))

    name_of: dict[str, str] = {}
    by_module: dict[str, list[str]] = {}
    bound = set(taken)
    for ref, module, attribute in parsed:
        if ref in name_of:
            continue
        needs_alias = attribute in taken or len(owners[attribute]) > 1
        name = f"{module.replace('.', '_')}__{attribute}" if needs_alias else attribute
        if name in bound:
            raise BuildError(
                f"ref '{ref}' を '{name}' として import すると既存の名前と衝突します",
                pointer=next(p for r, p in refs if r == ref),
                hint="衝突している circle 名か ref を変えてください",
            )
        bound.add(name)
        name_of[ref] = name
        by_module.setdefault(module, []).append(
            attribute if name == attribute else f"{attribute} as {name}"
        )
    lines = [f"from {module} import {', '.join(names)}" for module, names in by_module.items()]
    return _ImportPlan(name_of=name_of, lines=lines)


def _builtin_tool(name: str) -> object | None:
    """`google.adk.tools` の公開名を 1 つだけ解決する（ツールのインスタンスか関数のときだけ返す）。

    `google.adk.tools` は `__getattr__` で遅延 import する（2.8.0 実測: `_LAZY_MAPPING`）。
    `MCPToolset` のように任意依存（`mcp`）が要る名前は getattr の時点で ImportError になるので、
    それは「使えない名前」として None にする。`dir()` で全属性を触らない。
    """
    import google.adk.tools as adk_tools
    from google.adk.tools import BaseTool
    from google.adk.tools.base_toolset import BaseToolset

    if name not in adk_tools.__all__:
        return None
    try:
        obj = getattr(adk_tools, name)
    except ImportError:
        return None
    if isinstance(obj, (BaseTool, BaseToolset)) or inspect.isfunction(obj):
        return obj
    return None


def _resolve_builtin(name: str, *, pointer: str) -> None:
    """`builtin` は `google.adk.tools` の公開名のうち、ツールのインスタンスか関数だけを受け付ける。

    クラス（`FunctionTool` など）や無関係な属性は「組み込みツール」ではない。
    生成コードは `from google.adk.tools import <name>` を書くので、ここで存在を確定させる
    （NFR-FAIL-001: 生成物を `adk run` した時点で初めて ImportError にしない）。
    """
    import google.adk.tools as adk_tools

    if not name.isidentifier() or keyword.iskeyword(name):
        raise BuildError(
            f"builtin '{name}' は識別子ではないので google.adk.tools から import できません",
            pointer=pointer,
            hint="google.adk.tools の公開名（例: google_search）を書いてください",
        )
    if _builtin_tool(name) is None:
        candidates = [attr for attr in sorted(adk_tools.__all__) if _builtin_tool(attr) is not None]
        raise BuildError(
            f"builtin '{name}' は google.adk.tools {TARGET_ADK_VERSION} の組み込みツール"
            "（ツールのインスタンスか関数）ではありません",
            pointer=pointer,
            hint="使える名前: " + " / ".join(candidates),
        )


# ======================================================================================
# 検査（NFR-FAIL-001）
# ======================================================================================


def _builtin_names(model: JinFile) -> set[str]:
    """生成コードが `from google.adk.tools import <名>` で束縛する名前（`tools[kind=builtin]`）。"""
    return {
        tool.builtin
        for circle in model.circles
        for tool in circle.tools
        if isinstance(tool, ToolBuiltin)
    }


def _adk_tool_name(tool: ToolFunction | ToolBuiltin | ToolSummon) -> str | None:
    """ADK 上のツール名（LLM に見える名前）。`.jin` の `tools[].name` ではない（実測）。

    `kind: tool` → callable 名（`FunctionTool.name == func.__name__`。ref の形式が不正なら
    None を返し、`_plan_imports` に落とさせる）/ `builtin` → その名 / `summon` → circle 名。
    """
    if isinstance(tool, ToolFunction):
        if check_ref_format(tool.ref) is not None:
            return None
        return tool.ref.rpartition(":")[2]
    if isinstance(tool, ToolBuiltin):
        return tool.builtin
    return tool.circle


def _validate(model: JinFile) -> None:
    names = {c.name for c in model.circles}
    builtins = _builtin_names(model)
    for i, circle in enumerate(model.circles):
        base = join(join("", "circles"), i)
        _check_identifier(circle.name, pointer=join(base, "name"), what="circle 名")
        if circle.name in builtins:
            # F-C-P2-003 / F-V-P2-011: `google_search = LlmAgent(...)` が import を上書きし、
            # `tools=[google_search]` が agent を指す。`jin build` は通るが `adk run` で落ちる
            raise BuildError(
                f"circle 名 '{circle.name}' は builtin ツール '{circle.name}' の import 名と衝突します"
                "（生成コードでは同じ変数になり、tools=[...] が agent を指してしまいます）",
                pointer=join(base, "name"),
                hint=f"circle を別の名前にしてください（例: {circle.name}_agent）",
            )
        _check_root_is_not_a_child(model, circle, base)

        if circle.flow is not None and circle.flow.exit is not None:
            checker = circle.name + EXIT_CHECKER_SUFFIX
            if checker in names:
                raise BuildError(
                    f"circle '{checker}' の名前が、circle '{circle.name}' の flow.exit 判定エージェント"
                    f"（{circle.name}{EXIT_CHECKER_SUFFIX}）の名前と衝突します",
                    pointer=join(base, "name"),
                    hint=f"'{checker}' を別の名前にしてください",
                )

        outs = [j for j, state in enumerate(circle.state) if state.out]
        if circle.core is not None and len(outs) > 1:
            raise BuildError(
                f"circle '{circle.name}' に out: true の state が {len(outs)} 件あります。"
                "ADK の LlmAgent.output_key は 1 つしか持てません",
                pointer=join(join(base, "state"), outs[1]),
                hint="out: true を 1 件だけ残し、残りは out を外すか別の circle に分けてください",
            )

        if circle.flow is not None:
            _validate_flow_circle(circle, base, outs)
        else:
            _validate_core_circle(circle, base)


def _check_root_is_not_a_child(model: JinFile, circle: Circle, base: str) -> None:
    """root circle が別 circle の `flow.steps` / `delegate` / `summon` に現れる構造を拒む。

    `jin check` は root の入次数を見ない（JIN012 / JIN013 に当たらない）ので通るが、生成物では
    ADK が `root_agent.parent_agent` に別の agent を付け、`jin run` はその親を一度も使わない
    （書いたが効かない circle・correctness review F-C-P2-016）。診断コードは増やせないので
    ここで落とす（`jin check` 側での診断化は DP-REVIEW-JIN-P2-001 として未決）。
    """
    hint = "root は最外の陣なので他の circle の子にはできません。参照を外すか、別の circle を root にしてください"
    if circle.flow is not None:
        for k, step in enumerate(circle.flow.steps):
            if step == model.root:
                raise BuildError(
                    f"root circle '{model.root}' が circle '{circle.name}' の flow.steps に現れています",
                    pointer=join(join(join(base, "flow"), "steps"), k),
                    hint=hint,
                )
    for k, target in enumerate(circle.delegate):
        if target == model.root:
            raise BuildError(
                f"root circle '{model.root}' が circle '{circle.name}' の delegate に現れています",
                pointer=join(join(base, "delegate"), k),
                hint=hint,
            )
    for j, tool in enumerate(circle.tools):
        if isinstance(tool, ToolSummon) and tool.circle == model.root:
            raise BuildError(
                f"root circle '{model.root}' が circle '{circle.name}' の summon（tools[{j}]）に現れています",
                pointer=join(join(join(base, "tools"), j), "circle"),
                hint=hint,
            )


def _validate_flow_circle(circle: Circle, base: str, outs: list[int]) -> None:
    """核なし circle → workflow agent。ADK の Sequential/Parallel/LoopAgent が持てるのは
    name / description / sub_agents / before_agent_callback / after_agent_callback だけ（実測）。"""
    kind = circle.flow.kind if circle.flow is not None else "flow"
    what = f"flow circle '{circle.name}'（{kind}）"
    if circle.tools:
        raise BuildError(
            f"{what} に tools がありますが、ADK の workflow agent は tools を持てません",
            pointer=join(base, "tools"),
            hint="tools は core を持つ circle（LlmAgent）に移してください",
        )
    if circle.instruction is not None:
        raise BuildError(
            f"{what} に instruction がありますが、ADK の workflow agent は instruction を持てません",
            pointer=join(join(base, "instruction"), "rune"),
            hint="instruction は core を持つ circle に移すか削除してください",
        )
    if circle.delegate:
        raise BuildError(
            f"{what} に delegate がありますが、workflow agent の子は flow.steps で指定します",
            pointer=join(base, "delegate"),
            hint="delegate を flow.steps に移すか、core を持つ circle に移してください",
        )
    if outs:
        raise BuildError(
            f"{what} に out: true の state がありますが、workflow agent には output_key がありません",
            pointer=join(join(join(base, "state"), outs[0]), "out"),
            hint="out: true は core を持つ circle の state に付けてください",
        )
    if circle.boundary is not None:
        for k, guard in enumerate(circle.boundary.guards):
            if guard.on not in ("before_agent", "after_agent"):
                raise BuildError(
                    f"{what} の guard '{guard.on}' は workflow agent に対応するコールバックがありません"
                    "（before_agent / after_agent だけ使えます）",
                    pointer=join(join(join(join(base, "boundary"), "guards"), k), "on"),
                    hint="before_agent か after_agent に変えるか、core を持つ circle に移してください",
                )
        if circle.boundary.await_:
            # `jin check` 済みなら到達しない（flow circle は tools を持てず、await が tools に無ければ
            # JIN070 が先に落とす）。`JinFile.model_validate` を直接呼ぶ経路（ライブラリ利用）の防御として残す。
            # fixture は作れない（`jin check` を通らない）ので §3.1 の表には載せない
            raise BuildError(
                f"{what} に await がありますが、await は tools の関数を LongRunningFunctionTool に"
                "包む指定で、tools を持てない workflow agent には書けません",
                pointer=join(join(base, "boundary"), "await"),
                hint="await は core を持つ circle の boundary に書いてください",
            )


def _validate_core_circle(circle: Circle, base: str) -> None:
    tool_kinds = {tool.name: tool.kind for tool in circle.tools}
    if circle.boundary is not None:
        for k, target in enumerate(circle.boundary.await_):
            kind = tool_kinds.get(target)
            if kind is not None and kind != "tool":
                raise BuildError(
                    f"await '{target}' は kind: {kind} のツールを指しています。"
                    "LongRunningFunctionTool に包めるのは kind: tool（Python 関数）だけです",
                    pointer=join(join(join(base, "boundary"), "await"), k),
                    hint="await の対象を kind: tool のツールにするか、await から外してください",
                )
    if circle.instruction is not None:
        conflicts = adk_template_conflicts(circle.instruction.rune)
        if conflicts:
            shown = " / ".join(conflicts[:5])
            raise BuildError(
                f"circle '{circle.name}' の instruction.rune にある {shown} は、google-adk "
                f"{TARGET_ADK_VERSION} では state 参照として置換され、Jin の読み（リテラル）と食い違います",
                pointer=join(join(base, "instruction"), "rune"),
                hint="波括弧のリテラル（{{ }}）や {key?} / {artifact.x} / {app:key} は使えません。"
                "state 参照は {key} の形だけにしてください",
            )
    seen: dict[str, int] = {}
    for j, tool in enumerate(circle.tools):
        if isinstance(tool, ToolBuiltin):
            _resolve_builtin(tool.builtin, pointer=join(join(join(base, "tools"), j), "builtin"))
        adk_name = _adk_tool_name(tool)
        if adk_name is None:
            continue
        if adk_name in seen:
            # F-C-P2-002: ADK 2.8.0 は同名ツールを警告だけで通し、後勝ちのツールしか呼べない
            raise BuildError(
                f"circle '{circle.name}' の tools[{seen[adk_name]}] と tools[{j}] は ADK 上で"
                f"同じツール名 '{adk_name}' になります（ADK は後勝ちにして片方を呼べなくします）",
                pointer=join(join(base, "tools"), j),
                hint="callable 名が ADK のツール名になります。別名の関数に包むか、1 つにまとめてください",
            )
        seen[adk_name] = j


# ======================================================================================
# 生成
# ======================================================================================

#: `guards[].on` → ADK のコールバック引数名（docs/spec/model.md §3.5・1:1）。
_CALLBACK_KWARG = {
    "before_agent": "before_agent_callback",
    "after_agent": "after_agent_callback",
    "before_model": "before_model_callback",
    "after_model": "after_model_callback",
    "before_tool": "before_tool_callback",
    "after_tool": "after_tool_callback",
}

_FLOW_CLASS = {"sequence": "SequentialAgent", "parallel": "ParallelAgent", "loop": "LoopAgent"}


@dataclass
class _Emitted:
    var: str
    lines: list[str]


def _dependency_order(model: JinFile) -> list[Circle]:
    """参照先を先に並べる（post-order DFS・ファイル順を種にするので決定的）。

    循環は JIN012 で `jin check` が落としているので、ここでは想定しない。
    """
    by_name = {c.name: c for c in model.circles}
    done: list[Circle] = []
    seen: set[str] = set()

    def visit(circle: Circle) -> None:
        if circle.name in seen:
            return
        seen.add(circle.name)
        if circle.flow is not None:
            for step in circle.flow.steps:
                visit(by_name[step])
        for target in circle.delegate:
            visit(by_name[target])
        for tool in circle.tools:
            if isinstance(tool, ToolSummon):
                visit(by_name[tool.circle])
        done.append(circle)

    for circle in model.circles:
        visit(circle)
    return done


def _emit_llm_agent(
    circle: Circle,
    index: int,
    *,
    var_of: dict[str, str],
    imports: _ImportPlan,
) -> list[str]:
    _ = index
    awaited = set(circle.boundary.await_) if circle.boundary is not None else set()
    lines = [f"    name={py_literal(circle.name)},", f"    model={py_literal(circle.core or '')},"]
    if circle.description is not None:
        lines.append(f"    description={py_literal(circle.description)},")
    if circle.instruction is not None:
        block = py_text_block(circle.instruction.rune)
        if len(block) == 1:
            lines.append(f"    instruction={block[0]},")
        else:
            lines.append("    instruction=(")
            lines.extend(f"        {piece}" for piece in block)
            lines.append("    ),")
    if circle.tools:
        lines.append("    tools=[")
        for j, tool in enumerate(circle.tools):
            if isinstance(tool, ToolFunction):
                name = imports.name_of[tool.ref]
                wrapper = "LongRunningFunctionTool" if tool.name in awaited else "FunctionTool"
                lines.append(f"        {wrapper}({name}),")
            elif isinstance(tool, ToolBuiltin):
                lines.append(f"        {tool.builtin},")
            else:
                lines.append(f"        AgentTool(agent={var_of[tool.circle]}),")
        lines.append("    ],")
    if circle.delegate:
        lines.append(f"    sub_agents=[{', '.join(var_of[name] for name in circle.delegate)}],")
    lines.extend(_callback_lines(circle, imports))
    outs = [state.name for state in circle.state if state.out]
    if outs:
        lines.append(f"    output_key={py_literal(outs[0])},")
    return lines


def _callback_lines(circle: Circle, imports: _ImportPlan) -> list[str]:
    if circle.boundary is None or not circle.boundary.guards:
        return []
    grouped: dict[str, list[str]] = {}
    for guard in circle.boundary.guards:
        grouped.setdefault(_CALLBACK_KWARG[guard.on], []).append(imports.name_of[guard.ref])
    lines: list[str] = []
    # 出現順ではなく docs/spec/model.md §3.5 の表の順で安定させる
    for kwarg in _CALLBACK_KWARG.values():
        if kwarg not in grouped:
            continue
        names = grouped[kwarg]
        value = names[0] if len(names) == 1 else "[" + ", ".join(names) + "]"
        lines.append(f"    {kwarg}={value},")
    return lines


def _emit_workflow_agent(
    circle: Circle,
    index: int,
    flow: Flow,
    *,
    var_of: dict[str, str],
    imports: _ImportPlan,
    checker_var: str | None,
) -> list[str]:
    lines = [f"    name={py_literal(circle.name)},"]
    if circle.description is not None:
        lines.append(f"    description={py_literal(circle.description)},")
    children = [var_of[name] for name in flow.steps]
    if checker_var is not None:
        children.append(checker_var)
    lines.append(f"    sub_agents=[{', '.join(children)}],")
    if flow.kind == "loop" and flow.max is not None:
        lines.append(f"    max_iterations={flow.max},")
    lines.extend(_callback_lines(circle, imports))
    return lines


def _emit_checker(circle: Circle, exit_: FlowExit) -> tuple[str, list[str]]:
    var = circle.name + EXIT_CHECKER_SUFFIX
    lines = [
        f"    name={py_literal(var)},",
        f"    key={py_literal(exit_.key)},",
        f"    expected={py_value(exit_.equals)},",
    ]
    return var, lines


def _env_example() -> str:
    """DP-COMMON-15: キー名は google-adk 2.8.0 の実測値だけ。出典を本文に残す。"""
    return "\n".join(
        [
            "# generated by jin — .env.example",
            "# 値は .env に書く（adk run / adk web は <out>/<root_name>/ から親へ辿って .env を読む:",
            "# google/adk/cli/utils/envs.py:53-74 の load_dotenv_for_agent / _walk_to_root_until_found）。",
            f"# キー名は google-adk {TARGET_ADK_VERSION} の実測（推測では書かない・DP-COMMON-15）:",
            "#   書く側: adk create が生成する .env（google/adk/cli/cli_create.py:127-135）",
            "#   読む側: GOOGLE_API_KEY / GEMINI_API_KEY → google/genai/_api_client.py:136-137",
            "#           GOOGLE_GENAI_USE_ENTERPRISE（旧 GOOGLE_GENAI_USE_VERTEXAI は deprecated）",
            "#             → google/adk/utils/env_utils.py:63-79",
            "#           GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_LOCATION → google/adk 内 environ.get",
            "#",
            "# Gemini API（API キー）で動かす場合:",
            "GOOGLE_GENAI_USE_ENTERPRISE=0",
            "GOOGLE_API_KEY=",
            "#",
            "# Vertex AI（Enterprise）で動かす場合は上の 2 行の代わりに:",
            "# GOOGLE_GENAI_USE_ENTERPRISE=1",
            "# GOOGLE_CLOUD_PROJECT=",
            "# GOOGLE_CLOUD_LOCATION=",
            "",
        ]
    )


def generate(model: JinFile, *, source_name: str | None = None) -> GeneratedProject:
    """意味モデルから生成物を組み立てる。ファイルには書かない（`jin_adk.build`）。

    `source_name` はヘッダに載せる `.jin` の**ファイル名だけ**（ディレクトリは載せない。
    絶対パスや時刻を入れると同じモデルから違うバイト列が出て、スナップショットと
    NFR-DET-001 が崩れる）。
    """
    _validate(model)
    by_name = {c.name: c for c in model.circles}
    if model.root not in by_name:  # jin check（JIN060）が先に落とすが、二重に閉じる
        raise BuildError(
            f"root '{model.root}' の circle がありません",
            pointer="/root",
            hint="circles[].name のいずれかを root にしてください",
        )
    index_of = {c.name: i for i, c in enumerate(model.circles)}

    # 変数名: root は root_agent、それ以外は circle 名そのもの（要件書 §3.2 の形）
    var_of = {c.name: ("root_agent" if c.name == model.root else c.name) for c in model.circles}
    taken = set(var_of.values()) | set(RESERVED_NAMES) | _builtin_names(model)
    for circle in model.circles:
        if circle.flow is not None and circle.flow.exit is not None:
            taken.add(circle.name + EXIT_CHECKER_SUFFIX)
    imports = _plan_imports(model, taken)

    agent_classes: set[str] = set()
    tool_imports: set[str] = set()
    uses_agent_tool = False
    has_exit = False
    emitted: list[_Emitted] = []
    agents: dict[str, AgentEntry] = {}
    exit_checkers: dict[str, str] = {}

    for circle in _dependency_order(model):
        i = index_of[circle.name]
        base = join(join("", "circles"), i)
        if circle.flow is not None:
            flow = circle.flow
            checker_var: str | None = None
            if flow.exit is not None:
                has_exit = True
                checker_var, checker_lines = _emit_checker(circle, flow.exit)
                emitted.append(_Emitted(checker_var, ["StateCheckAgent(", *checker_lines, ")"]))
                exit_checkers[checker_var] = circle.name
            cls = _FLOW_CLASS[flow.kind]
            agent_classes.add(cls)
            body = _emit_workflow_agent(
                circle, i, flow, var_of=var_of, imports=imports, checker_var=checker_var
            )
            emitted.append(_Emitted(var_of[circle.name], [f"{cls}(", *body, ")"]))
            agents[circle.name] = AgentEntry(
                pointer=base,
                core=None,
                model=None,
                tools=(),
                delegate={},
                exit=join(join(base, "flow"), "exit") if flow.exit is not None else None,
            )
        else:
            agent_classes.add("LlmAgent")
            for tool in circle.tools:
                if isinstance(tool, ToolFunction):
                    awaited = circle.boundary is not None and tool.name in circle.boundary.await_
                    tool_imports.add("LongRunningFunctionTool" if awaited else "FunctionTool")
                elif isinstance(tool, ToolBuiltin):
                    tool_imports.add(tool.builtin)
                else:
                    uses_agent_tool = True
            body = _emit_llm_agent(circle, i, var_of=var_of, imports=imports)
            emitted.append(_Emitted(var_of[circle.name], ["LlmAgent(", *body, ")"]))
            agents[circle.name] = AgentEntry(
                pointer=base,
                core=join(base, "core"),
                model=circle.core,
                tools=tuple(join(join(base, "tools"), j) for j in range(len(circle.tools))),
                delegate={
                    name: join(join(base, "delegate"), k) for k, name in enumerate(circle.delegate)
                },
                exit=None,
            )

    blocks = [f"{item.var} = " + "\n".join(item.lines) for item in emitted]
    agent_py = render_agent_py(
        header=_header(source_name),
        agent_classes=sorted(agent_classes | ({"BaseAgent"} if has_exit else set())),
        tool_imports=sorted(tool_imports),
        uses_agent_tool=uses_agent_tool,
        has_exit=has_exit,
        ref_imports=imports.lines,
        blocks=blocks,
    )
    init_py = (
        "# generated by jin — do not edit\n"
        "from .agent import root_agent\n\n"
        '__all__ = ["root_agent"]\n'
    )
    return GeneratedProject(
        root_name=model.root,
        agent_py=agent_py,
        init_py=init_py,
        env_example=_env_example(),
        pointers=PointerMap(root=model.root, agents=agents, exit_checkers=exit_checkers),
    )


def _header(source_name: str | None) -> str:
    """ヘッダ。`source_name` は CLI が渡す `.jin` の**ファイル名**で、`.jin` 本文の検査を通っていない。

    改行を含むファイル名（Linux では合法）を生で置くと 2 行目が文になり、`jin run` がそれを
    実行する（security review F-S-P2-001・実測）。`py_literal` で 1 行のリテラルにする。

    guard: _header -> py_literal(source_name)
    """
    source = f"# source: {py_literal(source_name)}\n" if source_name else ""
    return (
        "# generated by jin — do not edit\n"
        f"{source}"
        f"# target: google-adk {TARGET_ADK_VERSION}"
        "（delivery/20260904-1445-jin/adk-api-probe.md の実測 API に固定）\n"
        "#\n"
        "# - このファイルは `jin build` のたびに丸ごと再生成される。直したいことは .jin かテンプレートへ。\n"
        "# - StateCheckAgent（flow.exit）は生成時に埋め込まれたコピーで、jin 側の実装を変えても\n"
        "#   このファイルには反映されない。jin を更新したら `jin build` で再生成すること（ADR-008）。\n"
        "# - トレースの pointer（要件書 §3.4）を付けるのは `jin run`。このファイルを `adk run` で\n"
        "#   単体実行してもトレースに Jin の pointer は付かない（ADR-009）。\n"
    )


__all__ = [
    "EXIT_CHECKER_SUFFIX",
    "RESERVED_NAMES",
    "AgentEntry",
    "BuildError",
    "GeneratedProject",
    "PointerMap",
    "adk_template_conflicts",
    "generate",
    "py_literal",
    "py_text_block",
    "py_value",
]
