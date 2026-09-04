"""生成 `agent.py` の形（要件書 §3.2）とスナップショット。

design.yaml Phase 2 machine 条件 1「生成 agent.py のスナップショット（syrupy）が
examples 2 本について安定」。

スナップショットは**回帰の網であって仕様ではない**。仕様は要件書 §3.2 なので、
`test_researcher_matches_the_requirement_example` が要件書の本文そのものと突き合わせる
（スナップショットだけだと「間違ったまま固定」できてしまう）。
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable
from pathlib import Path

import pytest
from jin_adk.codegen import HEADER, generate
from jin_core.model import JinFile

REPO_ROOT = Path(__file__).resolve().parents[3]
REQUIREMENTS = REPO_ROOT / "jin-requirements.md"
RESEARCHER = REPO_ROOT / "examples" / "researcher" / "researcher.jin"


def test_generated_agent_py_snapshot(example_model: JinFile, example_path: Path, snapshot) -> None:
    """machine 1: examples 2 本の生成物をスナップショットで固定する。"""
    _ = example_path
    assert generate(example_model).agent_py == snapshot


def test_generation_is_deterministic(example_model: JinFile) -> None:
    """同じモデルから**バイト単位で同じ**ものが出る（NFR-DET-002 と同じ厳しさ）。

    2 回呼ぶだけでは辞書のハッシュ順の揺れを捕まえられないので、
    `PYTHONHASHSEED` を変えた別プロセスでの一致は
    `tests/contract/test_cli_contract.py` 側と同じ形で `test_project.py` が見る。
    """
    assert generate(example_model).agent_py == generate(example_model).agent_py


def test_generated_module_is_valid_python(example_model: JinFile) -> None:
    """構文として成り立っていること（import できるかは test_object_tree が見る）。"""
    ast.parse(generate(example_model).agent_py)


def test_first_line_is_the_do_not_edit_header(example_model: JinFile) -> None:
    """要件書 §3.2 の 1 行目。`CLAUDE.md`「生成コードは編集しない」の入口でもある。"""
    assert generate(example_model).agent_py.splitlines()[0] == HEADER
    assert generate(example_model).init_py.splitlines()[0] == HEADER


def _requirement_example() -> str:
    """要件書 §3.2 の Python コードブロックを取り出す。"""
    text = REQUIREMENTS.read_text(encoding="utf-8")
    section = text.split("### 3.2 生成コードの形", 1)[1]
    block = re.search(r"```python\n(.*?)```", section, re.DOTALL)
    assert block is not None, "要件書 §3.2 の python コードブロックが見つからない"
    return block.group(1)


def test_researcher_matches_the_requirement_example(load_jin: Callable) -> None:
    """**要件書 §3.2 の本文そのもの**と生成物を突き合わせる。

    スナップショットは「前回と同じか」しか見ないので、最初から間違っていると
    間違いのまま固定される。ここだけは正典（要件書）を読んで比べる。
    """
    model = load_jin(REPO_ROOT / "examples" / "researcher" / "researcher.jin")
    generated = generate(model).agent_py
    for line in _requirement_example().splitlines():
        if not line.strip():
            continue
        assert line in generated, f"要件書 §3.2 の行が生成物に無い: {line!r}"


def test_researcher_generates_no_more_than_the_requirement_example(load_jin: Callable) -> None:
    """余計な行を足していないこと（§3.2 は import + 2 エージェントだけ）。

    空行を除いた行数が一致することを見る。片方向だけの包含だと
    「要件書の行は全部あるが、ほかにも山ほど出している」を許してしまう。
    """
    model = load_jin(REPO_ROOT / "examples" / "researcher" / "researcher.jin")
    generated = [line for line in generate(model).agent_py.splitlines() if line.strip()]
    expected = [line for line in _requirement_example().splitlines() if line.strip()]
    assert generated == expected


# --------------------------------------------------------------------------------------
# マッピング規則（要件書 §3.3）
# --------------------------------------------------------------------------------------
def test_loop_max_becomes_max_iterations(
    tmp_path: Path, load_jin: Callable, minimal_jin: Callable, write_jin: Callable
) -> None:
    """`flow.max` → `LoopAgent(max_iterations=...)`。`max=` と書いてはいけない。"""
    payload = minimal_jin(
        root="Loop",
        circles=[
            {"name": "Loop", "flow": {"kind": "loop", "steps": ["Step"], "max": 4}},
            {"name": "Step", "core": "m", "instruction": {"rune": "x"}},
        ],
    )
    generated = generate(load_jin(write_jin(tmp_path, "a.jin", payload))).agent_py
    assert "max_iterations=4," in generated
    assert "max=4" not in generated


def test_flow_exit_generates_a_state_check_agent_at_the_end(
    tmp_path: Path, load_jin: Callable, minimal_jin: Callable, write_jin: Callable
) -> None:
    """§3.3: 判定エージェントは `LoopAgent.sub_agents` の**末尾**に置く。"""
    payload = minimal_jin(
        root="Loop",
        circles=[
            {
                "name": "Loop",
                "flow": {
                    "kind": "loop",
                    "steps": ["Step"],
                    "exit": {"key": "done", "equals": True},
                },
            },
            {
                "name": "Step",
                "core": "m",
                "instruction": {"rune": "x"},
                "state": [{"name": "done", "type": "bool", "out": True}],
            },
        ],
    )
    generated = generate(load_jin(write_jin(tmp_path, "a.jin", payload))).agent_py
    sub_agents = generated.split("sub_agents=[", 1)[1].split("]", 1)[0]
    assert sub_agents.index("Step") < sub_agents.index("StateCheckAgent")
    assert 'name="Loop__exit"' in generated
    assert "class StateCheckAgent(BaseAgent):" in generated, (
        "ADR-008（案 A）: 判定エージェントのクラス本体は生成物に埋め込む"
    )


def test_the_generated_module_never_imports_jin(example_model: JinFile) -> None:
    """ADR-008: 生成物は `jin` パッケージに依存しない（`adk run` にそのまま載る）。"""
    for line in generate(example_model).agent_py.splitlines():
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")):
            assert "jin_adk" not in stripped and "jin_core" not in stripped, stripped


def test_fake_llm_never_appears_in_the_generated_module(example_model: JinFile) -> None:
    """ADR-008: `FakeLlm` は `jin run` が実行時に差し替えるもので、生成物の一部ではない。"""
    assert "FakeLlm" not in generate(example_model).agent_py


def test_repeated_guards_of_the_same_kind_become_a_list(
    tmp_path: Path, load_jin: Callable, minimal_jin: Callable, write_jin: Callable
) -> None:
    """§3.3「同種が複数あればリストで渡す」。"""
    payload = minimal_jin(
        circles=[
            {
                "name": "Root",
                "core": "m",
                "instruction": {"rune": "x"},
                "boundary": {
                    "guards": [
                        {"on": "before_model", "ref": "g:one"},
                        {"on": "before_model", "ref": "g:two"},
                    ]
                },
            }
        ]
    )
    generated = generate(load_jin(write_jin(tmp_path, "a.jin", payload))).agent_py
    assert "before_model_callback=[one, two]," in generated


def test_await_tool_becomes_long_running(
    tmp_path: Path, load_jin: Callable, minimal_jin: Callable, write_jin: Callable
) -> None:
    """§2.1: `boundary.await[]` → `LongRunningFunctionTool`。"""
    payload = minimal_jin(
        circles=[
            {
                "name": "Root",
                "core": "m",
                "instruction": {"rune": "x"},
                "tools": [
                    {"name": "a", "kind": "tool", "ref": "m:a"},
                    {"name": "b", "kind": "tool", "ref": "m:b"},
                ],
                "boundary": {"await": ["b"]},
            }
        ]
    )
    generated = generate(load_jin(write_jin(tmp_path, "a.jin", payload))).agent_py
    assert "FunctionTool(a)," in generated
    assert "LongRunningFunctionTool(b)," in generated


def test_builtin_tool_is_placed_as_an_instance(
    tmp_path: Path, load_jin: Callable, minimal_jin: Callable, write_jin: Callable
) -> None:
    """§2.2 / adk-mapping §2.2: `builtin` はインスタンスをそのまま置く（`()` を付けない）。"""
    payload = minimal_jin(
        circles=[
            {
                "name": "Root",
                "core": "m",
                "instruction": {"rune": "x"},
                "tools": [{"name": "s", "kind": "builtin", "builtin": "google_search"}],
            }
        ]
    )
    generated = generate(load_jin(write_jin(tmp_path, "a.jin", payload))).agent_py
    assert "from google.adk.tools import google_search" in generated
    assert "        google_search,\n" in generated
    assert "google_search()" not in generated


def test_only_out_state_becomes_output_key(
    tmp_path: Path, load_jin: Callable, minimal_jin: Callable, write_jin: Callable
) -> None:
    """§3.3「`out: true` だけが `output_key` になる」。"""
    payload = minimal_jin(
        circles=[
            {
                "name": "Root",
                "core": "m",
                "instruction": {"rune": "x"},
                "state": [
                    {"name": "input_only", "type": "str"},
                    {"name": "produced", "type": "str", "out": True},
                ],
            }
        ]
    )
    generated = generate(load_jin(write_jin(tmp_path, "a.jin", payload))).agent_py
    assert 'output_key="produced",' in generated
    assert "input_only" not in generated


def test_delegate_becomes_sub_agents(
    tmp_path: Path, load_jin: Callable, minimal_jin: Callable, write_jin: Callable
) -> None:
    """§2.1: `delegate[]` → `LlmAgent.sub_agents`。"""
    payload = minimal_jin(
        circles=[
            {"name": "Root", "core": "m", "instruction": {"rune": "x"}, "delegate": ["Child"]},
            {"name": "Child", "core": "m", "instruction": {"rune": "y"}},
        ]
    )
    generated = generate(load_jin(write_jin(tmp_path, "a.jin", payload))).agent_py
    assert generated.index("Child = LlmAgent(") < generated.index("root_agent = LlmAgent(")
    assert "        Child,\n" in generated


def test_colliding_callable_names_are_aliased(
    tmp_path: Path, load_jin: Callable, minimal_jin: Callable, write_jin: Callable
) -> None:
    """同名の callable が別モジュールから来たら別名にする（黙って 1 つに潰さない）。"""
    payload = minimal_jin(
        circles=[
            {
                "name": "Root",
                "core": "m",
                "instruction": {"rune": "x"},
                "tools": [
                    {"name": "a", "kind": "tool", "ref": "alpha.tools:run"},
                    {"name": "b", "kind": "tool", "ref": "beta.tools:run"},
                ],
            }
        ]
    )
    generated = generate(load_jin(write_jin(tmp_path, "a.jin", payload))).agent_py
    assert "from alpha.tools import run" in generated
    assert "from beta.tools import run as beta_tools__run" in generated
    assert "FunctionTool(run)," in generated
    assert "FunctionTool(beta_tools__run)," in generated


def test_a_callable_named_like_a_circle_is_aliased(
    tmp_path: Path, load_jin: Callable, minimal_jin: Callable, write_jin: Callable
) -> None:
    """circle 名と callable 名がぶつかったときも黙って潰さない。"""
    payload = minimal_jin(
        circles=[
            {
                "name": "Root",
                "core": "m",
                "instruction": {"rune": "x"},
                "tools": [
                    {"name": "s", "kind": "summon", "circle": "Helper"},
                    {"name": "h", "kind": "tool", "ref": "pkg:Helper"},
                ],
            },
            {"name": "Helper", "core": "m", "instruction": {"rune": "y"}},
        ]
    )
    generated = generate(load_jin(write_jin(tmp_path, "a.jin", payload))).agent_py
    assert "from pkg import Helper as pkg__Helper" in generated
    assert "AgentTool(agent=Helper)," in generated
    assert "FunctionTool(pkg__Helper)," in generated


@pytest.mark.parametrize(
    ("rune", "triple_quoted"),
    [
        ("1 行", False),
        ("a\nb", True),
        # 単独の `"` は三重引用符の中に素で置ける（閉じ記号にならない）。
        ('引用符 " を含む\n2 行', True),
        # `"""` を含む / `"` で終わる / `\\` を含むものは三重引用符に入れられない。
        ('三重 """ を含む\n2 行', False),
        ('2 行目が引用符で終わる\n終わり"', False),
        ("バックスラッシュ \\ と\n改行", False),
    ],
)
def test_string_literals_round_trip(
    tmp_path: Path,
    rune: str,
    triple_quoted: bool,
    load_jin: Callable,
    minimal_jin: Callable,
    write_jin: Callable,
) -> None:
    """生成した文字列リテラルが**元の文字列に戻る**こと。

    三重引用符に入れられない値を入れると、生成物が構文エラーになるか、
    もっと悪いことに**別の文字列**になる。`ast.literal_eval` で往復を確かめる。
    どちらの書き方を選んだかも固定する（片方の経路だけ通って気づかないのを防ぐ）。
    """
    payload = minimal_jin(
        circles=[{"name": "Root", "core": "m", "instruction": {"rune": rune}}],
    )
    generated = generate(load_jin(write_jin(tmp_path, "a.jin", payload))).agent_py
    ast.parse(generated)
    literal = generated.split("instruction=", 1)[1].rsplit(",\n", 1)[0]
    assert ast.literal_eval(literal) == rune
    assert literal.startswith('"""') is triple_quoted, literal
