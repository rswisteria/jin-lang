"""`jin run --model fake` とトレース JSONL（要件書 §3.4）。

design.yaml Phase 2 machine 条件:

- 5「`jin run --model fake` が examples 2 本で最後まで通り exit 0」
- 6「トレース JSONL の全行が §3.4 のスキーマ（seq / ts / agent / kind / name /
  pointer / input / output）を満たす」
- 7「トレース JSONL の全 pointer がモデルに解決できる」

**ネットワークにも API キーにも触れない**（NFR-TEST-001）。`--model fake` は
`BaseLlm` を継承した `FakeLlm`（固定応答）に差し替えるだけで、実モデルは呼ばない。
`test_fake_llm.py` がその差し替えの網羅性（`summon` の先まで届くこと）を見る。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

import pytest
from jin_adk.run import initial_state, run
from jin_adk.trace import TRACE_KEYS, TRACE_KINDS
from jin_core.canonical import dumps
from jin_core.model import JinFile
from jin_core.pointer import pointer_exists

REPO_ROOT = Path(__file__).resolve().parents[3]
PIPELINE = REPO_ROOT / "examples" / "pipeline" / "pipeline.jin"


@pytest.fixture
def example_run(example_model: JinFile, example_path: Path):
    return run(
        example_model,
        "テスト用のプロンプト",
        source_dir=example_path.parent,
        use_fake_model=True,
    )


# --------------------------------------------------------------------------------------
# machine 5: examples 2 本が最後まで通る
# --------------------------------------------------------------------------------------
def test_examples_run_to_completion_with_the_fake_model(example_run) -> None:
    assert example_run.trace, "1 行もトレースが出ていない（途中で止まっている）"
    assert example_run.faked_agents, "FakeLlm に差し替えたエージェントが 0 件"


def test_the_cli_exits_zero(example_path: Path, tmp_path: Path) -> None:
    """CLI の exit code まで見る（machine 5 の文言は「exit 0」）。"""
    from jin_cli.main import app
    from typer.testing import CliRunner

    trace = tmp_path / "trace.jsonl"
    result = CliRunner().invoke(
        app,
        [
            "run",
            str(example_path),
            "テスト用のプロンプト",
            "--model",
            "fake",
            "--trace",
            str(trace),
        ],
    )
    assert result.exit_code == 0, result.output
    assert trace.is_file()
    assert trace.read_text(encoding="utf-8").splitlines()


def test_the_cli_rejects_an_unknown_model_option(example_path: Path) -> None:
    """`--model` に取れるのは `fake` だけ。黙って無視して実モデルを呼ばない。"""
    from jin_cli.main import app
    from typer.testing import CliRunner

    result = CliRunner().invoke(app, ["run", str(example_path), "x", "--model", "gemini-2.5-flash"])
    assert result.exit_code == 2
    assert "fake" in result.output


# --------------------------------------------------------------------------------------
# machine 6: トレース行が §3.4 のスキーマを満たす
# --------------------------------------------------------------------------------------
REQUIREMENTS = REPO_ROOT / "jin-requirements.md"


def test_trace_keys_match_the_requirement() -> None:
    """キーの並びを**要件書 §3.4 の本文から**読んで突き合わせる。

    テスト側に期待値を書くだけだと、要件書が変わっても緑のまま残る。
    """
    text = REQUIREMENTS.read_text(encoding="utf-8")
    line = next(line for line in text.splitlines() if '{ "seq", "ts", "agent"' in line)
    keys = re.findall(r'"([a-z]+)"', line.split("スキーマ:", 1)[1])
    # `"kind": "model|tool|..."` の値側も拾ってしまうので、kind の後ろは落とす。
    keys = [k for k in keys if k not in TRACE_KINDS]
    assert tuple(keys) == TRACE_KEYS


def test_trace_kinds_match_the_requirement() -> None:
    text = REQUIREMENTS.read_text(encoding="utf-8")
    line = next(line for line in text.splitlines() if '"kind": "model|tool' in line)
    kinds = re.search(r'"kind": "([a-z|]+)"', line)
    assert kinds is not None
    assert tuple(kinds.group(1).split("|")) == TRACE_KINDS


def test_trace_kind_literal_and_runtime_tuple_agree() -> None:
    """`TraceKind`（型）と `TRACE_KINDS`（実行時）が食い違わないこと。"""
    from typing import get_args

    from jin_adk.trace import TraceKind

    assert get_args(TraceKind) == TRACE_KINDS


def test_every_trace_line_matches_the_schema(example_run) -> None:
    """machine 6: 全行がキーの過不足なく、`kind` は 5 種のいずれか。"""
    for event in example_run.trace:
        payload = event.to_json_dict()
        assert tuple(payload) == TRACE_KEYS, payload
        assert payload["kind"] in TRACE_KINDS, payload
        assert isinstance(payload["seq"], int)
        assert isinstance(payload["ts"], str) and payload["ts"], payload
        assert isinstance(payload["agent"], str) and payload["agent"], payload
        assert isinstance(payload["name"], str)
        assert isinstance(payload["pointer"], str)


def test_seq_is_dense_and_starts_at_one(example_run) -> None:
    """`seq` は 1 から連番（Phase 6 のトレースリプレイが `upto` で切るための鍵）。"""
    assert [e.seq for e in example_run.trace] == list(range(1, len(example_run.trace) + 1))


def test_every_trace_line_is_valid_jsonl(example_run) -> None:
    """1 行 1 JSON。改行を含んだ値が行を割らないこと。"""
    for event in example_run.trace:
        line = event.to_jsonl()
        assert "\n" not in line
        assert json.loads(line) == event.to_json_dict()


def test_written_trace_file_round_trips(example_run, tmp_path: Path) -> None:
    from jin_adk.trace import write_jsonl

    path = tmp_path / "trace.jsonl"
    write_jsonl(path, example_run.trace)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(example_run.trace)
    assert [json.loads(line) for line in lines] == [e.to_json_dict() for e in example_run.trace]


# --------------------------------------------------------------------------------------
# machine 7: 全 pointer がモデルに解決できる
# --------------------------------------------------------------------------------------
def test_every_trace_pointer_resolves_against_the_model(example_run, example_model) -> None:
    """machine 7。pointer はレンダラの `data-jin` と同じ鍵（要件書 §3.4 / §2.5）。"""
    document = json.loads(dumps(example_model))
    for event in example_run.trace:
        assert event.pointer, f"pointer が空: {event.to_json_dict()}"
        assert pointer_exists(document, event.pointer), (
            f"pointer {event.pointer} がモデルに解決できない: {event.to_json_dict()}"
        )


def test_every_pointer_in_the_map_resolves_against_the_model(example_run, example_model) -> None:
    """対応表そのもの（ADR-009）が全部モデルに解決できること。

    トレースに現れなかった経路（tool / guard）も含めて見る。実行で通らなかった枝が
    壊れていても、トレースだけを見ていると気づけない。
    """
    document = json.loads(dumps(example_model))
    pointers = example_run.project.pointer_map.all_pointers()
    assert pointers
    for pointer in pointers:
        assert pointer_exists(document, pointer), pointer


def test_model_kind_points_at_the_core(example_run) -> None:
    """`kind: model` は発火したモデル（`core`）を指す。"""
    for event in example_run.trace:
        if event.kind == "model":
            assert event.pointer.endswith("/core"), event.to_json_dict()
            assert event.name, "モデル ID が空"


# --------------------------------------------------------------------------------------
# escalate（`flow.exit` の判定エージェントが実際に抜けること）
# --------------------------------------------------------------------------------------
def test_flow_exit_escalates_and_shows_up_in_the_trace(
    tmp_path: Path, load_jin: Callable, minimal_jin: Callable, write_jin: Callable
) -> None:
    """条件が成立したとき `kind: escalate` が出て、pointer が `flow/exit` を指す。

    examples/pipeline の `approved` は FakeLlm の固定応答と一致しないので
    `max_iterations` で止まる（= escalate 経路が通らない）。ここでは
    固定応答を `exit.equals` に合わせて、**抜ける側**を実際に通す。
    """
    payload = minimal_jin(
        root="Loop",
        circles=[
            {
                "name": "Loop",
                "flow": {
                    "kind": "loop",
                    "steps": ["Step"],
                    "max": 5,
                    "exit": {"key": "verdict", "equals": "ok"},
                },
            },
            {
                "name": "Step",
                "core": "gemini-2.5-flash",
                "instruction": {"rune": "判定する"},
                "state": [{"name": "verdict", "type": "str", "out": True}],
            },
        ],
    )
    model = load_jin(write_jin(tmp_path, "loop.jin", payload))
    result = run(model, "やって", use_fake_model=True, fake_response="ok")

    escalates = [e for e in result.trace if e.kind == "escalate"]
    assert escalates, f"escalate が出ていない: {[e.to_json_dict() for e in result.trace]}"
    assert escalates[0].agent == "Loop__exit"
    assert escalates[0].pointer == "/circles/0/flow/exit"

    # 5 回まで回れるが、1 周目で抜けるのでモデルは 1 回しか呼ばれない。
    assert len([e for e in result.trace if e.kind == "model"]) == 1


def test_loop_without_a_met_exit_stops_at_max_iterations(
    tmp_path: Path, load_jin: Callable, minimal_jin: Callable, write_jin: Callable
) -> None:
    """抜けない側も固定する（escalate のテストが「常に抜ける」で緑にならないように）。"""
    payload = minimal_jin(
        root="Loop",
        circles=[
            {
                "name": "Loop",
                "flow": {
                    "kind": "loop",
                    "steps": ["Step"],
                    "max": 2,
                    "exit": {"key": "verdict", "equals": "ok"},
                },
            },
            {
                "name": "Step",
                "core": "gemini-2.5-flash",
                "instruction": {"rune": "判定する"},
                "state": [{"name": "verdict", "type": "str", "out": True}],
            },
        ],
    )
    model = load_jin(write_jin(tmp_path, "loop.jin", payload))
    result = run(model, "やって", use_fake_model=True, fake_response="まだ")
    assert [e for e in result.trace if e.kind == "escalate"] == []
    assert len([e for e in result.trace if e.kind == "model"]) == 2


# --------------------------------------------------------------------------------------
# セッション状態の種まき（要件書 §2.1「state[] → session.state」）
# --------------------------------------------------------------------------------------
def test_initial_state_declares_every_state_key(load_jin: Callable) -> None:
    """`{key}` が session.state に無いと ADK が `KeyError` を投げる（実測）。

    値は捏造せず空文字にする。詳細は `jin_adk.run.initial_state` の docstring と
    implementation-plan.json の
    未決 `DP-JIN-STATE-SEED-01`。
    """
    model = load_jin(PIPELINE)
    assert initial_state(model) == {
        "draft": "",
        "review": "",
        "approved": "",
    }


def test_a_rune_referring_to_its_own_output_key_does_not_crash(
    tmp_path: Path, load_jin: Callable, minimal_jin: Callable, write_jin: Callable
) -> None:
    """種まきが無いと 1 ターン目で落ちる形（examples/researcher と同じ）。"""
    payload = minimal_jin(
        circles=[
            {
                "name": "Root",
                "core": "gemini-2.5-flash",
                "instruction": {"rune": "これまで: {memo}"},
                "state": [{"name": "memo", "type": "str", "out": True}],
            }
        ]
    )
    model = load_jin(write_jin(tmp_path, "a.jin", payload))
    assert run(model, "やって", use_fake_model=True).trace


# --------------------------------------------------------------------------------------
# 一時ディレクトリの後始末
# --------------------------------------------------------------------------------------
def test_the_temporary_project_is_removed(example_model: JinFile, example_path: Path) -> None:
    """§3.4「一時ディレクトリに書き出して import」。実行後に残さない。"""
    result = run(example_model, "x", source_dir=example_path.parent, use_fake_model=True)
    assert not Path(result.project.root_name).exists()
