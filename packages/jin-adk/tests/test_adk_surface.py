"""google-adk 2.8.0 の実 API を**実物に対して**固定する（NFR-VER-001）。

`delivery/20260904-1445-jin/adk-api-probe.md` は親セッションが隔離 venv で採った
introspection の結果で、`docs/spec/adk-mapping.md` §2 がそれを仕様として写している。
だがドキュメントは版が上がっても勝手には赤くならない。**生成コードが使う名前を
実物に対して assert する**のがこのファイルの役目である。

ここが赤くなったら、直すのは `codegen` のテンプレートと `adk-mapping.md` の両方
（申し送り §8-4「仕様側とコード側は同じ欠陥」）。**assert を緩めて通してはいけない。**
"""

from __future__ import annotations

import inspect
from importlib.metadata import version

import pytest
from google.adk.agents import BaseAgent, LlmAgent, LoopAgent, ParallelAgent, SequentialAgent
from google.adk.events import Event, EventActions
from google.adk.models import BaseLlm
from google.adk.runners import Runner
from google.adk.tools import FunctionTool, LongRunningFunctionTool
from google.adk.tools.agent_tool import AgentTool
from jin_adk.codegen import BUILTIN_TOOLS
from pydantic import ValidationError

#: `packages/jin-adk/pyproject.toml` が `>=2.8,<2.9` に固定している版。
PINNED_MAJOR_MINOR = "2.8"


def test_the_installed_adk_is_the_pinned_version() -> None:
    """テンプレートは 2.8.0 の実測に固定してある。別版で緑になっては意味がない。"""
    installed = version("google-adk")
    assert installed.startswith(f"{PINNED_MAJOR_MINOR}."), (
        f"google-adk {installed} が入っている。テンプレートは {PINNED_MAJOR_MINOR}.x の"
        "実測に固定してあるので、上げるなら adk-api-probe.md の採り直しと"
        "codegen のテンプレート見直しを同時に行うこと"
    )


# --------------------------------------------------------------------------------------
# エージェントクラス
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "field",
    [
        "name",
        "model",
        "description",
        "instruction",
        "tools",
        "sub_agents",
        "output_key",
        "before_agent_callback",
        "after_agent_callback",
        "before_model_callback",
        "after_model_callback",
        "before_tool_callback",
        "after_tool_callback",
    ],
)
def test_llm_agent_accepts_every_argument_the_template_emits(field: str) -> None:
    assert field in LlmAgent.model_fields


@pytest.mark.parametrize("cls", [SequentialAgent, ParallelAgent, LoopAgent])
@pytest.mark.parametrize("field", ["name", "description", "sub_agents"])
def test_workflow_agents_accept_the_arguments_the_template_emits(cls: type, field: str) -> None:
    assert field in cls.model_fields


def test_loop_agent_takes_max_iterations_and_not_max() -> None:
    """`flow.max` → `LoopAgent(max_iterations=...)`。`max` という引数名は**無い**。

    要件書 §2.2 のキー名（`max`）をそのまま渡すと、`extra` が禁止なら例外、
    許されていれば**黙って無視される**。後者が怖いのでここで固定する。
    """
    assert "max_iterations" in LoopAgent.model_fields
    assert "max" not in LoopAgent.model_fields


@pytest.mark.parametrize("field", ["instruction", "tools", "output_key", "model"])
def test_workflow_agents_do_not_have_llm_only_fields(field: str) -> None:
    """`codegen` が「核なし circle に写せない」と落としている根拠そのもの。

    ここが逆に通るようになったら、コンパイル時エラーのほうが過剰になっている。
    """
    for cls in (SequentialAgent, ParallelAgent, LoopAgent):
        assert field not in cls.model_fields, f"{cls.__name__} に {field} ができた"


def test_agent_name_must_be_a_python_identifier() -> None:
    """`_check_names` の根拠（実測）。文言も実測に合わせてある。"""
    with pytest.raises(ValidationError, match="must be a valid Python identifier"):
        SequentialAgent(name="my agent")
    with pytest.raises(ValidationError, match="cannot be `user`"):
        SequentialAgent(name="user")


def test_adk_accepts_python_keywords_but_generated_code_cannot() -> None:
    """`codegen` が ADK **より厳しい**理由（実測）。

    `"class".isidentifier()` は True なので ADK は `name="class"` を通す。
    しかし生成コードは circle 名をそのまま変数名にするので `class = LlmAgent(...)` は
    構文エラーになる。だから `_check_names` は `keyword.iskeyword` も見る。
    ADK 側だけを見て「通るから大丈夫」と緩めてはいけない。
    """
    assert SequentialAgent(name="class").name == "class"


# --------------------------------------------------------------------------------------
# ツール
# --------------------------------------------------------------------------------------
def test_tool_constructor_signatures() -> None:
    assert list(inspect.signature(FunctionTool.__init__).parameters)[:2] == ["self", "func"]
    assert list(inspect.signature(LongRunningFunctionTool.__init__).parameters)[:2] == [
        "self",
        "func",
    ]
    assert list(inspect.signature(AgentTool.__init__).parameters)[:2] == ["self", "agent"]


def test_builtin_tools_constant_matches_what_adk_actually_exports() -> None:
    """`BUILTIN_TOOLS` を実物から確かめる（記憶で書かない）。

    「クラスではなくインスタンス」であることが `builtin` の生成方法
    （`tools=[google_search]` とそのまま置く）の前提なので、**インスタンスであること**
    まで見る。ADK が増やしたら赤くなる。増やすときは
    `docs/spec/adk-mapping.md` §2.2 も同時に直すこと。
    """
    import google.adk.tools as adk_tools

    measured = set()
    for name in dir(adk_tools):
        if name.startswith("_"):
            continue
        try:
            value = getattr(adk_tools, name)
        except Exception:  # noqa: BLE001, S112 - 任意依存（mcp など）が無いと遅延 import が落ちる
            # ADK の `google/adk/utils/_lazy.py` は属性アクセスで import する。
            # `mcp_tool` は任意依存なので、入っていない環境では ImportError になる。
            # 入っていないものを `builtin` として使えるはずがないので、対象外でよい。
            continue
        if not isinstance(value, type) and hasattr(value, "name") and hasattr(value, "description"):
            measured.add(name)
    assert set(BUILTIN_TOOLS) == measured, (
        "BUILTIN_TOOLS が google.adk.tools の実物とずれている。"
        f"足りない: {measured - set(BUILTIN_TOOLS)} / 余分: {set(BUILTIN_TOOLS) - measured}"
    )


def test_google_search_is_an_instance_not_a_class() -> None:
    from google.adk.tools import google_search

    assert not isinstance(google_search, type), (
        "google_search がクラスになった。生成コードは `tools=[google_search]` と"
        "インスタンスをそのまま置いているので、テンプレートを直すこと"
    )


# --------------------------------------------------------------------------------------
# 実行とトレース
# --------------------------------------------------------------------------------------
def test_runner_is_keyword_only_and_requires_session_service() -> None:
    parameters = inspect.signature(Runner.__init__).parameters
    assert parameters["session_service"].default is inspect.Parameter.empty
    for name, parameter in parameters.items():
        if name == "self":
            continue
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, name


def test_event_has_the_fields_the_trace_reads() -> None:
    """`agent` は `Event.author`、`ts` は `Event.timestamp` から取る（§3.4）。"""
    for field in ("author", "timestamp", "content", "actions"):
        assert field in Event.model_fields
    assert "pointer" not in Event.model_fields, (
        "Event が pointer を持つようになった。ADR-009（生成時に対応表を作る）の"
        "前提が変わるので、判断ごと見直すこと"
    )


def test_event_actions_has_escalate() -> None:
    """§3.3 の `StateCheckAgent` が成立する根拠。"""
    assert "escalate" in EventActions.model_fields
    assert "transfer_to_agent" in EventActions.model_fields


def test_overridden_method_signatures() -> None:
    """生成コード（`StateCheckAgent`）と `FakeLlm` が override する 2 つ。"""
    assert list(inspect.signature(BaseAgent._run_async_impl).parameters) == ["self", "ctx"]
    assert list(inspect.signature(BaseLlm.generate_content_async).parameters) == [
        "self",
        "llm_request",
        "stream",
    ]
