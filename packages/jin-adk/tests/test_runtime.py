"""`jin_adk.runtime`: 生成コードを一時ディレクトリへ書いて import し、Runner で実行する。

design.yaml Phase 2 machine 条件 2 / 4 / 5 / 6 / 7。ネットワーク・API キー不要（FakeLlm）。
`research.*` は `tests/fixtures/stubs` のスタブを `sys.path` に載せて供給する。
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

import pytest
from google.adk.agents import LlmAgent, LoopAgent, SequentialAgent
from google.adk.tools import FunctionTool, LongRunningFunctionTool
from google.adk.tools.agent_tool import AgentTool
from jin_adk.codegen import generate
from jin_adk.fake_llm import FakeLlm, FakeToolCall
from jin_adk.runtime import RunError, load_generated, run_model, run_model_async, swap_models
from jin_adk.trace import KINDS, TRACE_FIELDS
from jin_core.check import check_file
from jin_core.model import JinFile
from jin_core.pointer import resolve_pointer

from tests.conftest import requires_non_root

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPO_ROOT / "examples"
STUBS = REPO_ROOT / "tests" / "fixtures" / "stubs"


@pytest.fixture(autouse=True)
def stubs_on_path(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.syspath_prepend(str(STUBS))
    yield
    for name in [m for m in sys.modules if m == "research" or m.startswith("research.")]:
        sys.modules.pop(name, None)


def load(name: str) -> JinFile:
    result = check_file(EXAMPLES / name / f"{name}.jin")
    assert result.ok and result.model is not None
    return result.model


def document(model: JinFile) -> dict:
    return json.loads(model.model_dump_json(by_alias=True, exclude_defaults=True))


# --------------------------------------------------------------------------------------
# machine 条件 2 / 4: 生成モジュールを import して ADK オブジェクト木を検証（モデル呼び出しなし）
# --------------------------------------------------------------------------------------
def test_researcher_object_tree() -> None:
    import research.guards
    import research.tools

    with load_generated(generate(load("researcher"))) as module:
        root = module.root_agent
        assert isinstance(root, LlmAgent)
        assert root.name == "Researcher"
        assert root.model == "gemini-2.5-flash"
        assert root.output_key == "findings"
        tools = root.tools
        assert [type(t) for t in tools] == [
            FunctionTool,
            FunctionTool,
            AgentTool,
            LongRunningFunctionTool,
        ]
        assert [t.name for t in tools] == ["web_search", "fetch_page", "Summarizer", "publish"]
        assert tools[0].func is research.tools.web_search
        assert tools[2].agent.name == "Summarizer"
        assert tools[2].agent.output_key == "summary"
        # callback の同一性（要件書 §9）
        assert root.before_model_callback is research.guards.pii_filter
        assert root.before_tool_callback is research.guards.audit_log
        assert root.sub_agents == []


def test_pipeline_object_tree() -> None:
    with load_generated(generate(load("pipeline"))) as module:
        root = module.root_agent
        assert isinstance(root, SequentialAgent)
        assert [a.name for a in root.sub_agents] == ["Drafter", "Reviewer", "Refine"]
        refine = root.sub_agents[2]
        assert isinstance(refine, LoopAgent)
        assert refine.max_iterations == 3
        assert [a.name for a in refine.sub_agents] == ["Critic", "Rewriter", "Refine_exit_check"]
        checker = refine.sub_agents[-1]
        assert type(checker).__name__ == "StateCheckAgent"
        assert checker.key == "approved" and checker.expected is True
        assert refine.sub_agents[0].parent_agent is refine


def test_generated_package_init_exports_root_agent(tmp_path: Path) -> None:
    """`<root_name>/__init__.py` 経由（adk run が使う形）でも root_agent が取れる。"""
    from jin_adk.build import write_project

    write_project(generate(load("pipeline")), tmp_path)
    sys.path.insert(0, str(tmp_path))
    try:
        import importlib

        package = importlib.import_module("Pipeline")
        assert package.root_agent.name == "Pipeline"
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("Pipeline", None)
        sys.modules.pop("Pipeline.agent", None)


def test_load_generated_cleans_up_its_temporary_directory() -> None:
    with load_generated(generate(load("pipeline"))) as module:
        path = Path(module.__file__)
        assert path.exists()
        # 一時ディレクトリは所有者だけが読める（security: review_axes_note (1)）
        top = path.parents[1]
        assert stat.S_IMODE(top.stat().st_mode) == 0o700
    assert not path.exists()
    assert not top.exists()


@requires_non_root
def test_cleanup_failure_is_reported_on_stderr_not_swallowed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """F-W-P2-008: 一時ディレクトリを消せなかったとき黙らない（stderr に 1 行・RunError にはしない）。"""
    with load_generated(generate(load("pipeline"))) as module:
        top = Path(module.__file__).parents[1]
        pkg = Path(module.__file__).parent
        pkg.chmod(0o500)  # 中のファイルを unlink できなくする
    try:
        assert top.exists()
        err = capsys.readouterr().err
        assert "一時ディレクトリを消せませんでした" in err and str(top) in err
    finally:
        pkg.chmod(0o700)
        import shutil

        shutil.rmtree(top, ignore_errors=True)


def test_load_generated_reports_import_failure_without_a_traceback() -> None:
    """生成コードの import が落ちても（ref 先が無い）トレースバックでなく RunError にする。"""
    model = JinFile.model_validate(
        {
            "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
            "version": 1,
            "root": "R",
            "circles": [
                {
                    "name": "R",
                    "core": "m",
                    "tools": [{"name": "t", "kind": "tool", "ref": "no_such_module_xyz:fn"}],
                }
            ],
        }
    )
    with pytest.raises(RunError) as info, load_generated(generate(model)):
        pass
    assert "no_such_module_xyz" in str(info.value)


def test_system_exit_in_generated_code_import_is_not_swallowed(tmp_path: Path) -> None:
    """Phase 1 の S2 と同型: ref 先の `sys.exit(0)` で成功扱いにしない。"""
    (tmp_path / "exits").mkdir()
    (tmp_path / "exits" / "__init__.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    sys.path.insert(0, str(tmp_path))
    try:
        model = JinFile.model_validate(
            {
                "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
                "version": 1,
                "root": "R",
                "circles": [
                    {
                        "name": "R",
                        "core": "m",
                        "tools": [{"name": "t", "kind": "tool", "ref": "exits:fn"}],
                    }
                ],
            }
        )
        with pytest.raises(RunError) as info, load_generated(generate(model)):
            pass
        assert "SystemExit" in str(info.value)
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("exits", None)


def test_system_exit_in_a_tool_at_runtime_is_a_run_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """F-S-P2-102: **ツール実行中**の `sys.exit(0)` も成功扱いにしない（import 中と実行中の両方）。

    asyncio は `SystemExit` をループの外へ再送出するので `run_model_async` では捕まらない。
    同期 `run_model` が `asyncio.run` を包んで `RunError` にする。一時ディレクトリは残さず、
    asyncio の shutdown ログ（トレースバック）も stderr に出さない。
    """
    seen: list[str] = []
    original = tempfile.mkdtemp

    def spy(*args, **kwargs):
        path = original(*args, **kwargs)
        seen.append(path)
        return path

    monkeypatch.setattr(tempfile, "mkdtemp", spy)
    model = JinFile.model_validate(
        {
            "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
            "version": 1,
            "root": "R",
            "circles": [
                {
                    "name": "R",
                    "core": "m",
                    "tools": [{"name": "t", "kind": "tool", "ref": "exits_tool:boom"}],
                }
            ],
        }
    )
    llm = FakeLlm(responses=[FakeToolCall(name="boom", args={"x": "1"}), "done"])
    with pytest.raises(RunError) as info:
        run_model(model, "go", llm=llm)
    assert "SystemExit" in str(info.value)
    assert seen and not os.path.exists(seen[0])
    assert "Traceback" not in capsys.readouterr().err
    # asyncio は shutdown 中の未処理例外を logging（asyncio ロガー・ERROR）に出す。
    # pytest の logging プラグインが root にハンドラを付けるので stderr には出ない → caplog で見る
    assert not [r for r in caplog.records if r.name == "asyncio"], caplog.text


def test_extra_sys_path_is_present_only_during_the_import(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """DP-IMPL-JIN-P2-SYSPATH-01（再々判断）: `extra_sys_path` は import 窓の間だけ。

    窓の中では末尾にあり、`yield` の時点（Runner 実行中に相当）では取り除かれている。
    元から `sys.path` にある値は足さないし取り除かない。import が失敗しても取り除く。
    """
    import jin_adk.runtime

    extra = str(tmp_path / "extra")
    during: list[list[str]] = []
    original = jin_adk.runtime._import_agent_module

    def spy(path: Path):
        during.append(list(sys.path))
        return original(path)

    monkeypatch.setattr(jin_adk.runtime, "_import_agent_module", spy)
    with load_generated(generate(load("pipeline")), extra_sys_path=[extra, str(STUBS)]):
        assert extra not in sys.path, "yield の時点で extra が残っている"
        assert str(STUBS) in sys.path, "元からある値を取り除いた"
    assert during[0][-1] == extra and during[0].count(str(STUBS)) == 1
    assert extra not in sys.path
    # import が失敗しても finally で取り除く
    bad = JinFile.model_validate(
        {
            "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
            "version": 1,
            "root": "R",
            "circles": [
                {
                    "name": "R",
                    "core": "m",
                    "tools": [{"name": "t", "kind": "tool", "ref": "no_such_module_xyz:fn"}],
                }
            ],
        }
    )
    with pytest.raises(RunError), load_generated(generate(bad), extra_sys_path=[extra]):
        pass
    assert extra not in sys.path


# --------------------------------------------------------------------------------------
# FakeLlm の差し替え（ADR-008: 生成物には埋め込まず、実行時に木を走査して差し替える）
# --------------------------------------------------------------------------------------
def test_two_guards_of_the_same_kind_become_a_list_in_declaration_order() -> None:
    """要件書 §3.3「同種が複数あればリストで渡す」（F-C-P2-010: 2 つ目を捨てても全スイート緑だった）。"""
    import research.guards

    model = JinFile.model_validate(
        {
            "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
            "version": 1,
            "root": "R",
            "circles": [
                {
                    "name": "R",
                    "core": "m",
                    "boundary": {
                        "guards": [
                            {"on": "before_model", "ref": "research.guards:pii_filter"},
                            {"on": "before_model", "ref": "research.guards:audit_log"},
                        ]
                    },
                }
            ],
        }
    )
    with load_generated(generate(model)) as module:
        assert module.root_agent.before_model_callback == [
            research.guards.pii_filter,
            research.guards.audit_log,
        ]


def test_flow_circle_description_and_delegate_order_survive_generation() -> None:
    """F-C-P2-015: examples に無い構造（flow の description / delegate 2 件以上）を import 後の木で固定する。"""
    model = JinFile.model_validate(
        {
            "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
            "version": 1,
            "root": "Top",
            "circles": [
                {
                    "name": "Top",
                    "description": "全体の流れ",
                    "flow": {"kind": "sequence", "steps": ["Boss"]},
                },
                {"name": "Boss", "core": "m", "delegate": ["W1", "W2", "W3"]},
                {"name": "W1", "core": "m"},
                {"name": "W2", "core": "m"},
                {"name": "W3", "core": "m"},
            ],
        }
    )
    project = generate(model)
    with load_generated(project) as module:
        assert module.root_agent.description == "全体の流れ"
        boss = module.root_agent.sub_agents[0]
        assert [a.name for a in boss.sub_agents] == ["W1", "W2", "W3"]
    assert project.pointers.agents["Boss"].delegate == {
        "W1": "/circles/1/delegate/0",
        "W2": "/circles/1/delegate/1",
        "W3": "/circles/1/delegate/2",
    }


def test_swap_models_replaces_every_llm_agent_but_not_the_state_checker() -> None:
    with load_generated(generate(load("pipeline"))) as module:
        llm = FakeLlm()
        swapped = swap_models(module.root_agent, llm)
        assert sorted(swapped) == ["Critic", "Drafter", "Reviewer", "Rewriter"]
        refine = module.root_agent.sub_agents[2]
        assert refine.sub_agents[0].model is llm
        assert not hasattr(refine.sub_agents[-1], "model")


def test_swap_models_reaches_agent_tool_targets() -> None:
    with load_generated(generate(load("researcher"))) as module:
        swapped = swap_models(module.root_agent, FakeLlm())
        assert sorted(swapped) == ["Researcher", "Summarizer"]


# --------------------------------------------------------------------------------------
# machine 条件 5 / 6 / 7: run --model fake が最後まで通り、トレースがスキーマを満たし pointer が解決する
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["researcher", "pipeline"])
def test_run_with_fake_llm_completes_and_every_pointer_resolves(name: str) -> None:
    model = load(name)
    result = run_model(model, "こんにちは", llm=FakeLlm())
    assert result.rows, "イベントが 1 件も無い"
    doc = document(model)
    for row in result.rows:
        record = row.to_json_dict()
        assert list(record) == list(TRACE_FIELDS)
        assert record["kind"] in KINDS
        assert isinstance(record["seq"], int) and isinstance(record["ts"], float)
        assert isinstance(record["agent"], str) and isinstance(record["name"], str)
        assert record["pointer"] is not None, record
        resolve_pointer(doc, record["pointer"])
        json.dumps(record, ensure_ascii=False)  # JSON にできる
    assert [r.seq for r in result.rows] == list(range(1, len(result.rows) + 1))


def test_pipeline_trace_kinds_and_final() -> None:
    result = run_model(load("pipeline"), "go", llm=FakeLlm())
    kinds = [r.kind for r in result.rows]
    assert kinds[0] == "model"
    assert "escalate" in kinds
    assert kinds[-1] in ("final", "escalate")
    assert sum(1 for k in kinds if k == "final") <= 1
    checks = [r for r in result.rows if r.kind == "escalate"]
    assert all(r.pointer == "/circles/1/flow/exit" and r.name == "Refine" for r in checks)
    assert all(r.output["matched"] is False for r in checks)  # 固定応答は true ではない


def test_researcher_trace_has_final_and_model_rows() -> None:
    result = run_model(load("researcher"), "go", llm=FakeLlm())
    assert result.rows[-1].kind == "final"
    assert result.rows[-1].agent == "Researcher"
    assert result.rows[-1].pointer == "/circles/0/core"
    assert result.rows[-1].name == "gemini-2.5-flash"
    assert result.final_state["findings"]


def test_declared_state_keys_are_seeded_so_instruction_templates_do_not_crash() -> None:
    """実測: `{findings}` が未設定だと ADK は KeyError で落ちる。宣言済み state を None で seed する。"""
    result = run_model(load("researcher"), "go", llm=FakeLlm())
    assert "query" in result.final_state  # 宣言のみ・out ではない key も seed される
    assert result.final_state["query"] is None


# --------------------------------------------------------------------------------------
# flow.exit の判定が効いていること（examples の max: 3 とは別に直接固定する）
# --------------------------------------------------------------------------------------
def _critic_rows(rows) -> int:
    return sum(1 for r in rows if r.agent == "Critic" and r.kind in ("model", "final"))


def test_loop_exits_early_when_the_state_matches() -> None:
    result = run_model(load("pipeline"), "go", llm=FakeLlm(responses=["true"]))
    assert _critic_rows(result.rows) == 1
    checks = [r for r in result.rows if r.kind == "escalate"]
    assert len(checks) == 1 and checks[0].output["matched"] is True
    assert checks[0].input == {"key": "approved", "expected": True}


def test_loop_runs_to_max_when_the_state_never_matches() -> None:
    result = run_model(load("pipeline"), "go", llm=FakeLlm(responses=["no"]))
    assert _critic_rows(result.rows) == 3
    assert sum(1 for r in result.rows if r.kind == "escalate") == 3


@pytest.mark.parametrize(
    ("equals", "actual", "matched"),
    [
        (True, "true", True),
        (True, " true\n", True),
        (True, "True", False),
        (True, "1", False),
        (True, "yes", False),
        (False, "false", True),
        (3, "3", True),
        (3, "3.0", True),
        (3, "true", False),
        (3, '"3"', False),
        (2.5, "2.5", True),
        (2.5, "2", False),
        ("yes", "yes", True),
        ("yes", " yes ", True),
        (" yes", "yes", True),  # equals 側の空白も除く（対称・F-C-P2-008）
        (" yes ", " yes", True),
        ("yes", '"yes"', False),
        ("yes", "no", False),
        (1, "true", False),  # bool を数値に一致させない（F-C-P2-012）
        (0, "false", False),
        (1, "1", True),
    ],
)
def test_state_matches_semantics(equals, actual: str, matched: bool) -> None:
    """docs/spec/model.md §3.4 の比較規則を、生成された `_state_matches` そのもので固定する。"""
    model = JinFile.model_validate(
        {
            "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
            "version": 1,
            "root": "L",
            "circles": [
                {
                    "name": "L",
                    "flow": {
                        "kind": "loop",
                        "steps": ["A"],
                        "max": 1,
                        "exit": {"key": "k", "equals": equals},
                    },
                },
                {"name": "A", "core": "m", "state": [{"name": "k", "type": "any", "out": True}]},
            ],
        }
    )
    with load_generated(generate(model)) as module:
        assert module._state_matches(actual, equals) is matched


# --------------------------------------------------------------------------------------
# tool / transfer の pointer（scripted FakeLlm）
# --------------------------------------------------------------------------------------
def test_tool_call_rows_point_at_the_tool_element() -> None:
    llm = FakeLlm(responses=[FakeToolCall(name="web_search", args={"query": "adk"}), "done"])
    result = run_model(load("researcher"), "go", llm=llm)
    tool_rows = [r for r in result.rows if r.kind == "tool"]
    assert len(tool_rows) == 2  # 呼び出しと応答
    assert all(r.pointer == "/circles/0/tools/0" and r.name == "web_search" for r in tool_rows)
    assert tool_rows[0].input == {"query": "adk"} and tool_rows[0].output is None
    assert tool_rows[1].input is None and tool_rows[1].output == {"result": "stub-search:adk"}


def test_tool_call_rows_use_the_declared_index_not_the_first_tool() -> None:
    """F-C-P2-011: `bind_tools` を「常に tools[0]」に壊しても web_search だけでは見えない。tools[3] を呼ぶ。"""
    llm = FakeLlm(responses=[FakeToolCall(name="publish", args={"text": "t"}), "done"])
    result = run_model(load("researcher"), "go", llm=llm)
    tool_rows = [r for r in result.rows if r.kind == "tool"]
    assert len(tool_rows) == 2
    assert all(r.pointer == "/circles/0/tools/3" and r.name == "publish" for r in tool_rows)
    assert tool_rows[1].output == {"result": "stub-published:t"}


def test_runtime_tool_name_collision_is_reported_as_unresolvable_not_hidden() -> None:
    """`bind_tools` の同名経路は実行時に到達可能: `search_again = web_search` は attribute 名が違うので
    コンパイル時検査（ref の attribute 名）を通るが、`FunctionTool.name == func.__name__` は両方 `web_search`。"""
    model = JinFile.model_validate(
        {
            "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
            "version": 1,
            "root": "R",
            "circles": [
                {
                    "name": "R",
                    "core": "m",
                    "tools": [
                        {"name": "a", "kind": "tool", "ref": "research.tools:web_search"},
                        {"name": "b", "kind": "tool", "ref": "research.tools:search_again"},
                    ],
                }
            ],
        }
    )
    llm = FakeLlm(responses=[FakeToolCall(name="web_search", args={"query": "q"}), "done"])
    result = run_model(model, "go", llm=llm)
    tool_rows = [r for r in result.rows if r.kind == "tool"]
    assert tool_rows and all(r.pointer is None for r in tool_rows)
    assert any("同名の ADK ツール 'web_search'" in reason for reason in result.unresolved)


def test_delegate_transfer_end_to_end_has_no_stray_tool_row(tmp_path: Path) -> None:
    """F-C-P2-004: delegate を持つ `.jin` の transfer は `transfer` 行 1 つで、pointer 未解決の苦情が出ない。"""
    model = JinFile.model_validate(
        {
            "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
            "version": 1,
            "root": "Boss",
            "circles": [
                {"name": "Boss", "core": "m", "delegate": ["Worker"]},
                {"name": "Worker", "core": "m"},
            ],
        }
    )
    llm = FakeLlm(
        responses=[FakeToolCall(name="transfer_to_agent", args={"agent_name": "Worker"}), "done"]
    )
    result = run_model(model, "go", llm=llm)
    kinds = [(r.kind, r.agent, r.name, r.pointer) for r in result.rows]
    assert ("transfer", "Boss", "Worker", "/circles/0/delegate/0") in kinds
    assert not any(r.kind == "tool" for r in result.rows)
    assert result.unresolved == []
    assert all(r.pointer is not None for r in result.rows)


def test_run_model_async_can_be_awaited_from_a_running_loop() -> None:
    """F-C-P2-019: pygls（Phase 4）のようにループが稼働している場所から呼べる。"""

    async def inside_loop() -> int:
        result = await run_model_async(load("pipeline"), "go", llm=FakeLlm())
        return len(result.rows)

    assert asyncio.run(inside_loop()) > 0


def test_cancelled_error_propagates_from_run_model_async() -> None:
    """F-C-P2-102: 稼働中のループから呼んだ `run_model_async` をキャンセルすると `CancelledError` が
    そのまま伝わる（`RunError("実行に失敗しました（CancelledError: ）")` に化かさない。asyncio の規約）。
    LLM 呼び出しの最中（Runner の中）でキャンセルする。"""
    from collections.abc import AsyncGenerator

    from google.adk.models import LlmRequest, LlmResponse

    reached = asyncio.Event()

    class Hanging(FakeLlm):
        async def generate_content_async(
            self, llm_request: LlmRequest, stream: bool = False
        ) -> AsyncGenerator[LlmResponse, None]:
            reached.set()
            await asyncio.Event().wait()  # 永久に待つ（キャンセルされるまで）
            yield LlmResponse()  # pragma: no cover

    async def scenario() -> None:
        task = asyncio.create_task(run_model_async(load("pipeline"), "go", llm=Hanging()))
        await asyncio.wait_for(reached.wait(), timeout=10)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


def _cancel_model(root_kind: str) -> JinFile:
    """ツール `fn`（`cancel_tool:fn`・CancelledError を投げる）を持つモデル。root が LlmAgent か sequence か。"""
    tool = {"name": "t", "kind": "tool", "ref": "cancel_tool:fn"}
    if root_kind == "llm":
        circles = [{"name": "R", "core": "m", "tools": [tool]}]
        root = "R"
    else:
        circles = [
            {"name": "Seq", "flow": {"kind": "sequence", "steps": ["A", "B"]}},
            {"name": "A", "core": "m", "tools": [tool]},
            {"name": "B", "core": "m"},
        ]
        root = "Seq"
    return JinFile.model_validate(
        {
            "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
            "version": 1,
            "root": root,
            "circles": circles,
        }
    )


@pytest.mark.parametrize("root_kind", ["llm", "sequence"])
def test_tool_cancelled_error_is_a_run_error_not_a_success(root_kind: str) -> None:
    """F-S-P2-201 / 202: ツール関数の `asyncio.CancelledError` を成功扱いにしない。

    root=LlmAgent: ADK の `_cleanup_root_task` が root の cancel を握って正常復帰する（修正前は
    `rows=[tool 呼び出し]` で正常終了 = fail-open）→ 応答の無い function_call で検知して `RunError`。
    root=sequence: `CancelledError` が Runner から素通りする（修正前は `asyncio.run` からそのまま出た）
    → `Task.cancelling() == 0` なので `RunError`。
    """
    llm = FakeLlm(responses=[FakeToolCall(name="fn", args={"query": "q"}), "done"])
    with pytest.raises(RunError) as info:
        run_model(_cancel_model(root_kind), "go", llm=llm)
    assert "CancelledError" in str(info.value) or "応答を返さず" in str(info.value)


def test_tool_cancelled_error_under_a_workflow_root_is_a_run_error_from_run_model_async() -> None:
    """F-S-P2-202: workflow root 配下のツール `CancelledError` は Runner から素通りしてくる。`run_model_async` 自身が
    `Task.cancelling() == 0` を見て `RunError` にする（同期 `run_model` / CLI の保険に頼らない。稼働中のループから
    呼ぶ Phase 4 の pygls はその保険を持たない）。"""

    async def inside_loop() -> None:
        llm = FakeLlm(responses=[FakeToolCall(name="fn", args={"query": "q"}), "done"])
        with pytest.raises(RunError) as info:
            await run_model_async(_cancel_model("sequence"), "go", llm=llm)
        assert "asyncio.CancelledError を投げました" in str(info.value)

    asyncio.run(inside_loop())


def test_await_pause_is_not_mistaken_for_a_missing_tool_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F-S-P2-201 の誤検知防止: `boundary.await` の LongRunningFunctionTool が `None` を返す正規の pause は
    トレース上「呼び出し行だけ・応答無し」で F-S-P2-201 と同じ形だが、`Event.long_running_tool_ids` に
    入るので失敗にしない（researcher の `publish` は `await` 対象）。"""
    import research.tools

    def publish(text: str) -> None:
        return None  # 人間の確認待ち（LongRunningFunctionTool の pause）

    monkeypatch.setattr(research.tools, "publish", publish)
    llm = FakeLlm(responses=[FakeToolCall(name="publish", args={"text": "draft"}), "done"])
    result = run_model(load("researcher"), "go", llm=llm)
    assert [(r.kind, r.name) for r in result.rows] == [("tool", "publish")]
    assert result.rows[0].input == {"text": "draft"} and result.rows[0].output is None


def test_temporary_directory_is_created_with_mkdtemp(monkeypatch: pytest.MonkeyPatch) -> None:
    """一時ディレクトリは `tempfile.mkdtemp`（0700）で作る。"""
    seen: list[str] = []
    original = tempfile.mkdtemp

    def spy(*args, **kwargs):
        path = original(*args, **kwargs)
        seen.append(path)
        return path

    monkeypatch.setattr(tempfile, "mkdtemp", spy)
    run_model(load("pipeline"), "go", llm=FakeLlm())
    assert len(seen) == 1
    assert not os.path.exists(seen[0])
