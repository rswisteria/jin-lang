"""Jin v2 の意味編集オペレーション（docs/spec/v2/ops.md）。

v1 の `test_ops.py` と同じ規律: 各オペレーションを適用 → 再検証 → 逆オペレーションで**バイト単位**で
元に戻る。`rename` は参照追随の具体値も見る。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jin_core.canonical import dumps
from jin_core.check import check_file, check_text
from jin_core.ops import Op, OpError
from jin_core.v2.model import JinFileV2
from jin_core.v2.ops import OPERATIONS, apply_op, apply_ops

REPO_ROOT = Path(__file__).resolve().parents[3]
PADDLE = REPO_ROOT / "examples-v2" / "paddle" / "paddle.jin"
FIB = REPO_ROOT / "examples-v2" / "fib" / "fib.jin"


def load(path: Path = PADDLE) -> JinFileV2:
    result = check_file(path)
    assert isinstance(result.model, JinFileV2) and result.ok
    return result.model


def roundtrip(ops: list[Op], path: Path = PADDLE) -> JinFileV2:
    """ops を適用し、逆オペレーション列で元のバイト列に戻ることを確かめて、適用後のモデルを返す。"""
    before = load(path)
    original = dumps(before)
    forward = apply_ops(before, ops)
    assert dumps(before) == original, "入力のモデルを書き換えてはいけない"
    restored = apply_ops(forward.model, forward.inverses)
    assert dumps(restored.model) == original
    return forward.model


def clean(model: JinFileV2) -> list[str]:
    """適用後のモデルの診断コード（意味エラーが無いことの確認に使う）。"""
    return [d.code for d in check_text(dumps(model), "m.jin").diagnostics]


MINIMAL_CIRCLE = {"name": "Extra", "core": "main", "rites": [{"name": "main", "steps": []}]}


# ---------------------------------------------------------------- 一覧


def test_operations_are_exactly_the_32_of_the_spec() -> None:
    assert len(OPERATIONS) == 32


# ---------------------------------------------------------------- 往復（1 つずつ）


@pytest.mark.parametrize(
    "op",
    [
        {"op": "setStage", "pointer": "/stage", "value": {"fps": 30, "seed": None, "width": 640}},
        {"op": "addForm", "pointer": "/forms", "index": 0, "value": {"name": "Vec", "fields": []}},
        {"op": "removeForm", "pointer": "/forms/0"},
        {"op": "setForm", "pointer": "/forms/0", "value": {"name": "Orb"}},
        {"op": "addCircle", "pointer": "/circles", "index": 1, "value": MINIMAL_CIRCLE},
        {"op": "removeCircle", "pointer": "/circles/2"},
        {"op": "setCore", "pointer": "/circles/1", "value": "serve"},
        {
            "op": "addState",
            "pointer": "/circles/1/state",
            "value": {"name": "lives", "type": "num", "init": "3"},
        },
        {"op": "removeState", "pointer": "/circles/1/state/0"},
        {"op": "setState", "pointer": "/circles/1/state/2", "value": {"out": False, "init": "5"}},
        {
            "op": "addSigil",
            "pointer": "/circles/1/sigils",
            "index": 0,
            "value": {"name": "ui", "kind": "host", "host": "ui"},
        },
        {"op": "removeSigil", "pointer": "/circles/1/sigils/2"},
        {"op": "moveSigil", "pointer": "/circles/1/sigils/0", "to": 2},
        {"op": "addRite", "pointer": "/circles/1/rites", "value": {"name": "extra", "steps": []}},
        {"op": "removeRite", "pointer": "/circles/1/rites/3"},
        {
            "op": "setRiteSignature",
            "pointer": "/circles/1/rites/2",
            "value": {"returns": "num", "params": []},
        },
        {
            "op": "addStep",
            "pointer": "/circles/1/rites/2/steps",
            "index": 0,
            "value": {"do": "finish"},
        },
        {"op": "addStep", "pointer": "/circles/1/rites/2/steps/0/then", "value": {"do": "break"}},
        {"op": "removeStep", "pointer": "/circles/1/rites/2/steps/2"},
        {"op": "moveStep", "pointer": "/circles/1/rites/2/steps/0", "to": 3},
        {
            "op": "setStep",
            "pointer": "/circles/1/rites/2/steps/2",
            "value": {"expr": "ball.x"},
        },
        {
            "op": "wrapSteps",
            "pointer": "/circles/1/rites/2/steps",
            "from": 2,
            "count": 2,
            "value": {"do": "if", "cond": "true"},
        },
        {
            "op": "wrapSteps",
            "pointer": "/circles/1/rites/2/steps",
            "from": 0,
            "count": 1,
            "value": {"do": "loop", "kind": "count", "times": "3"},
        },
        {"op": "unwrapSteps", "pointer": "/circles/1/rites/2/steps/0", "branch": "then"},
        {"op": "unwrapSteps", "pointer": "/circles/1/rites/2/steps/0", "branch": "else"},
        {
            "op": "extractRite",
            "pointer": "/circles/1/rites/2/steps",
            "from": 2,
            "count": 3,
            "name": "move",
        },
        {
            "op": "setOn",
            "pointer": "/circles/1/boundary/on",
            "value": {"event": "exit", "rite": "serve"},
        },
        {
            "op": "setOn",
            "pointer": "/circles/1/boundary/on",
            "value": {"event": "tick", "rite": "serve"},
        },
        {
            "op": "setOn",
            "pointer": "/circles/2/boundary/on",
            "index": 0,
            "value": {"event": "exit", "rite": "show"},
        },
        {"op": "removeOn", "pointer": "/circles/1/boundary/on/0"},
        {"op": "setGuard", "pointer": "/circles/1/boundary/guards", "value": {"assert": "true"}},
        {
            "op": "setGuard",
            "pointer": "/circles/1/boundary/guards/0",
            "value": {"assert": "false", "message": "x"},
        },
        {"op": "setGuard", "pointer": "/circles/2/boundary/guards", "value": {"assert": "true"}},
        {"op": "removeGuard", "pointer": "/circles/1/boundary/guards/0"},
        {"op": "addDelegate", "pointer": "/circles/1/delegate", "value": "Result"},
        {
            "op": "setFlow",
            "pointer": "/circles/0",
            "value": {"kind": "sequence", "steps": ["Play"]},
        },
        {"op": "setRoot", "pointer": "", "value": "Play"},
    ],
    ids=lambda op: op["op"] + ":" + op.get("pointer", ""),
)
def test_each_operation_roundtrips(op: Op) -> None:
    roundtrip([op])


def test_remove_delegate_roundtrips_after_add() -> None:
    model = roundtrip(
        [
            {"op": "addDelegate", "pointer": "/circles/1/delegate", "value": "Result"},
            {"op": "removeDelegate", "pointer": "/circles/1/delegate/0"},
        ]
    )
    assert model.circles[1].delegate == []


def test_set_on_replaces_the_same_event_in_place() -> None:
    model = roundtrip(
        [
            {
                "op": "setOn",
                "pointer": "/circles/1/boundary/on",
                "value": {"event": "tick", "rite": "serve"},
            }
        ]
    )
    assert [(h.event, h.rite) for h in model.circles[1].boundary.on] == [("tick", "serve")]


def test_boundary_created_by_set_on_is_pruned_on_undo() -> None:
    """Result 以外に boundary を持たない陣（clicker には無いので Play に guards を消してから）。"""
    model = roundtrip(
        [
            {"op": "removeGuard", "pointer": "/circles/1/boundary/guards/0"},
            {"op": "removeOn", "pointer": "/circles/1/boundary/on/0"},
            {
                "op": "setOn",
                "pointer": "/circles/1/boundary/on",
                "value": {"event": "exit", "rite": "serve"},
            },
        ]
    )
    assert model.circles[1].boundary is not None


def test_wrap_and_unwrap_move_the_steps() -> None:
    model = roundtrip(
        [
            {
                "op": "wrapSteps",
                "pointer": "/circles/1/rites/2/steps",
                "from": 2,
                "count": 2,
                "value": {"do": "if", "cond": "true"},
            }
        ]
    )
    step = model.circles[1].rites[2].steps[2]
    assert step.do == "if" and len(step.then) == 2 and len(model.circles[1].rites[2].steps) == 8
    assert clean(model) == []


def test_extract_rite_leaves_a_cast_and_a_new_rite() -> None:
    model = roundtrip(
        [
            {
                "op": "extractRite",
                "pointer": "/circles/1/rites/2/steps",
                "from": 4,
                "count": 3,
                "name": "move",
            }
        ]
    )
    play = model.circles[1]
    assert [r.name for r in play.rites] == ["begin", "serve", "step", "paint", "move"]
    assert play.rites[2].steps[4].do == "cast" and play.rites[2].steps[4].target == "move"
    assert len(play.rites[4].steps) == 3
    assert clean(model) == []


# ---------------------------------------------------------------- rename の追随


def test_rename_circle_follows_flow_root_and_public_references() -> None:
    model = roundtrip([{"op": "rename", "pointer": "/circles/1", "value": "Arena"}])
    assert model.circles[0].flow.steps == ["Arena", "Result"]
    menu = model.circles[2].rites[1]
    assert menu.steps[1].args[0] == '"SCORE " ++ str(Arena.score)'
    assert clean(model) == []


def test_rename_form_follows_types_and_constructors() -> None:
    model = roundtrip([{"op": "rename", "pointer": "/forms/0", "value": "Orb"}])
    play = model.circles[1]
    assert play.state[0].type == "Orb"
    assert play.state[0].init == "Orb{x: 160, y: 40, vx: 90, vy: 70}"
    assert play.rites[1].steps[0].expr == "Orb{x: 160, y: 40, vx: 90, vy: 70}"
    assert clean(model) == []


def test_rename_field_follows_typed_accesses_and_constructors() -> None:
    model = roundtrip([{"op": "rename", "pointer": "/forms/0/fields/0", "value": "px"}])
    play = model.circles[1]
    assert play.state[0].init == "Ball{px: 160, y: 40, vx: 90, vy: 70}"
    assert play.rites[2].steps[2].target == "ball.px"
    assert play.rites[2].steps[2].expr == "ball.px + ball.vx * dt"
    assert play.rites[2].steps[4].cond == "ball.px < 0 or ball.px > 320"
    assert clean(model) == []


def test_rename_state_follows_own_and_public_references() -> None:
    model = roundtrip([{"op": "rename", "pointer": "/circles/1/state/2", "value": "points"}])
    play, result = model.circles[1], model.circles[2]
    assert play.rites[0].steps[0].target == "points"
    assert play.rites[3].steps[4].args[0] == '"SCORE " ++ str(points)'
    assert play.boundary.guards[0].assert_ == "points >= 0"
    assert result.rites[1].steps[1].args[0] == '"SCORE " ++ str(Play.points)'
    assert clean(model) == []


def test_rename_sigil_follows_cast_targets_and_expressions() -> None:
    model = roundtrip([{"op": "rename", "pointer": "/circles/1/sigils/1", "value": "keys"}])
    play = model.circles[1]
    assert play.rites[2].steps[0].cond == 'keys.key("ArrowLeft")'
    assert clean(model) == []
    model = roundtrip([{"op": "rename", "pointer": "/circles/1/sigils/0", "value": "gfx"}])
    assert model.circles[1].rites[3].steps[0].target == "gfx.clear"
    assert clean(model) == []


def test_rename_rite_follows_core_on_cast_and_summon() -> None:
    model = roundtrip([{"op": "rename", "pointer": "/circles/1/rites/3", "value": "draw"}])
    assert model.circles[1].rites[2].steps[8].target == "draw"
    model = roundtrip([{"op": "rename", "pointer": "/circles/1/rites/0", "value": "start"}])
    assert model.circles[1].core == "start"
    model = roundtrip([{"op": "rename", "pointer": "/circles/1/rites/2", "value": "update"}])
    assert model.circles[1].boundary.on[0].rite == "update"
    assert clean(model) == []


def test_rename_local_follows_expressions_in_its_rite_only() -> None:
    model = roundtrip(
        [{"op": "rename", "pointer": "/circles/1/rites/2/params/0", "value": "delta"}]
    )
    step = model.circles[1].rites[2]
    assert step.params[0].name == "delta"
    assert step.steps[0].then[0].expr == "max(0, paddle - 180 * delta)"
    assert step.steps[2].expr == "ball.x + ball.vx * delta"
    assert clean(model) == []
    model = roundtrip(
        [{"op": "rename", "pointer": "/circles/0/rites/0/steps/0", "value": "acc"}], FIB
    )
    fib = model.circles[0].rites[0]
    assert fib.steps[0].name == "acc"
    assert fib.steps[2].steps[0].expr == "acc + b"
    assert fib.steps[2].steps[1].target == "acc"
    assert fib.steps[3].expr == "acc"
    assert clean(model) == []


def test_rename_reports_unresolvable_expressions_as_warnings() -> None:
    broken = apply_op(
        load(),
        {
            "op": "setStep",
            "pointer": "/circles/1/rites/3/steps/2",
            "value": {"args": ["ball.x +", "1", "2"]},
        },
    ).model
    result = apply_op(broken, {"op": "rename", "pointer": "/forms/0/fields/0", "value": "px"})
    assert result.warnings == ["/circles/1/rites/3/steps/2/args/0"]
    assert result.model.circles[1].rites[2].steps[2].expr == "ball.px + ball.vx * dt"


def test_rename_does_not_touch_string_literals_or_shadowed_names() -> None:
    model = roundtrip([{"op": "rename", "pointer": "/circles/1/state/2", "value": "pts"}])
    assert '"SCORE "' in model.circles[1].rites[3].steps[4].args[0]


# ---------------------------------------------------------------- 失敗


@pytest.mark.parametrize(
    ("op", "code"),
    [
        ({"op": "nope", "pointer": ""}, "JIN002"),
        ({"op": "setCore", "pointer": "/circles/9", "value": "x"}, "JIN002"),
        (
            {
                "op": "addState",
                "pointer": "/circles/1/state",
                "value": {"name": "score", "type": "num", "init": "0"},
            },
            "JIN010",
        ),
        ({"op": "addStep", "pointer": "/circles/1/rites/2", "value": {"do": "finish"}}, "JIN002"),
        (
            {"op": "addStep", "pointer": "/circles/1/rites/2/steps", "value": {"do": "jump"}},
            "JIN002",
        ),
        ({"op": "moveStep", "pointer": "/circles/1/rites/2/steps/0", "to": 99}, "JIN002"),
        (
            {"op": "setStep", "pointer": "/circles/1/rites/2/steps/0", "value": {"do": "set"}},
            "JIN002",
        ),
        (
            {
                "op": "wrapSteps",
                "pointer": "/circles/1/rites/2/steps",
                "from": 8,
                "count": 2,
                "value": {"do": "if", "cond": "true"},
            },
            "JIN002",
        ),
        (
            {
                "op": "wrapSteps",
                "pointer": "/circles/1/rites/2/steps",
                "from": 0,
                "count": 1,
                "value": {"do": "set"},
            },
            "JIN002",
        ),
        ({"op": "unwrapSteps", "pointer": "/circles/1/rites/2/steps/2"}, "JIN002"),
        (
            {
                "op": "extractRite",
                "pointer": "/circles/1/rites/2/steps",
                "from": 0,
                "count": 1,
                "name": "paint",
            },
            "JIN010",
        ),
        ({"op": "rename", "pointer": "/circles/1", "value": "Result"}, "JIN010"),
        ({"op": "rename", "pointer": "/circles/1/state/2", "value": "canvas"}, "JIN010"),
        ({"op": "rename", "pointer": "/stage", "value": "x"}, "JIN002"),
        ({"op": "setRoot", "pointer": "/root", "value": "Play"}, "JIN002"),
        (
            {"op": "setRiteSignature", "pointer": "/circles/1/rites/2", "value": {"name": "z"}},
            "JIN002",
        ),
    ],
    ids=lambda v: v if isinstance(v, str) else v["op"],
)
def test_failures_carry_a_diagnostic_code(op: Op, code: str) -> None:
    before = load()
    original = dumps(before)
    with pytest.raises(OpError) as info:
        apply_op(before, op)
    assert info.value.code == code
    assert dumps(before) == original


def test_apply_ops_is_all_or_nothing() -> None:
    before = load()
    with pytest.raises(OpError):
        apply_ops(before, [{"op": "setRoot", "pointer": "", "value": "X"}, {"op": "nope"}])
    assert before.root == "Game"


def test_results_always_validate_against_the_schema() -> None:
    model = roundtrip([{"op": "setStage", "pointer": "/stage", "value": {"fps": 120}}])
    assert json.loads(dumps(model))["stage"]["fps"] == 120
