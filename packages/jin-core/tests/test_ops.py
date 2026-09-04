"""意味オペレーション（docs/spec/ops.md）のテスト。

要件書 §9 の「オペレーション」行:
「各オペレーションについて applyOps → 再パース → 期待モデル と 逆オペレーションで元に戻る」
再パースは正準形テキストを経由して行う（サーバは正準形でクライアントへ返すため）。
"""

from __future__ import annotations

import json

import pytest
from jin_core.canonical import dumps
from jin_core.check import check_text
from jin_core.model import JinFile
from jin_core.ops import OPERATIONS, OpError, apply_op, apply_ops

SCHEMA = "https://xtone.internal/jin/schemas/jin.schema.json"


def sample() -> JinFile:
    return JinFile.model_validate(
        {
            "$schema": SCHEMA,
            "version": 1,
            "root": "A",
            "circles": [
                {
                    "name": "A",
                    "core": "gemini-2.5-flash",
                    "description": "説明",
                    "instruction": {"rune": "{q} を調べる"},
                    "tools": [
                        {"name": "search", "kind": "tool", "ref": "m:search"},
                        {"name": "summarize", "kind": "summon", "circle": "B"},
                    ],
                    "delegate": ["B"],
                    "state": [{"name": "q", "type": "str"}],
                    "boundary": {
                        "guards": [{"on": "before_model", "ref": "m:guard"}],
                        "await": ["search"],
                    },
                },
                {"name": "B", "core": "gemini-2.5-flash"},
            ],
        }
    )


def roundtrip(model: JinFile) -> JinFile:
    """正準形テキストを経由して再パースする。"""
    return JinFile.model_validate(json.loads(dumps(model)))


def check(op: dict, *, expect) -> None:
    """op を適用 → 再パース → 期待どおり、逆 op で元に戻ることを確認する。"""
    before = sample()
    result = apply_op(before, op)
    after = roundtrip(result.model)
    expect(after)
    restored = roundtrip(apply_op(after, result.inverse).model)
    assert dumps(restored) == dumps(before), f"{op['op']} の逆オペレーションで元に戻らない"


# --------------------------------------------------------------------------------------
def test_all_19_operations_are_registered() -> None:
    assert sorted(OPERATIONS) == sorted(
        [
            "addCircle",
            "removeCircle",
            "setCore",
            "setDescription",
            "setRune",
            "addTool",
            "removeTool",
            "moveTool",
            "addState",
            "removeState",
            "setState",
            "setFlow",
            "addDelegate",
            "removeDelegate",
            "setGuard",
            "removeGuard",
            "toggleAwait",
            "setRoot",
            "rename",
        ]
    )


def test_operations_match_the_spec_document() -> None:
    from pathlib import Path

    spec = Path(__file__).resolve().parents[3] / "docs" / "spec" / "ops.md"
    body = spec.read_text(encoding="utf-8").split("<!-- machine-readable: ops-list -->", 1)[1]
    body = body.split("<!-- /machine-readable -->", 1)[0]
    import re

    listed = re.findall(r"^\| `([A-Za-z]+)`", body, re.MULTILINE)
    assert sorted(listed) == sorted(OPERATIONS)


# --------------------------------------------------------------------------------------
def test_add_circle() -> None:
    check(
        {"op": "addCircle", "pointer": "/circles", "index": 1, "value": {"name": "C", "core": "m"}},
        expect=lambda m: [c.name for c in m.circles] == ["A", "C", "B"],
    )


def test_remove_circle() -> None:
    check(
        {"op": "removeCircle", "pointer": "/circles/1"},
        expect=lambda m: [c.name for c in m.circles] == ["A"],
    )


def test_set_core() -> None:
    check(
        {"op": "setCore", "pointer": "/circles/1", "value": "gemini-2.5-pro"},
        expect=lambda m: m.circles[1].core == "gemini-2.5-pro",
    )


def test_set_description() -> None:
    check(
        {"op": "setDescription", "pointer": "/circles/0", "value": None},
        expect=lambda m: m.circles[0].description is None,
    )


def test_set_rune() -> None:
    check(
        {"op": "setRune", "pointer": "/circles/0", "value": "新しい指示"},
        expect=lambda m: m.circles[0].instruction.rune == "新しい指示",
    )


def test_set_rune_none_removes_instruction() -> None:
    check(
        {"op": "setRune", "pointer": "/circles/0", "value": None},
        expect=lambda m: m.circles[0].instruction is None,
    )


def test_add_tool() -> None:
    check(
        {
            "op": "addTool",
            "pointer": "/circles/0/tools",
            "index": 0,
            "value": {"name": "fetch", "kind": "tool", "ref": "m:fetch"},
        },
        expect=lambda m: [t.name for t in m.circles[0].tools] == ["fetch", "search", "summarize"],
    )


def test_remove_tool() -> None:
    check(
        {"op": "removeTool", "pointer": "/circles/0/tools/1"},
        expect=lambda m: [t.name for t in m.circles[0].tools] == ["search"],
    )


def test_move_tool_changes_angle_order() -> None:
    check(
        {"op": "moveTool", "pointer": "/circles/0/tools/0", "index": 1},
        expect=lambda m: [t.name for t in m.circles[0].tools] == ["summarize", "search"],
    )


def test_add_state() -> None:
    check(
        {
            "op": "addState",
            "pointer": "/circles/0/state",
            "index": 1,
            "value": {"name": "findings", "type": "str", "out": True},
        },
        expect=lambda m: [s.name for s in m.circles[0].state] == ["q", "findings"],
    )


def test_remove_state() -> None:
    check(
        {"op": "removeState", "pointer": "/circles/0/state/0"},
        expect=lambda m: m.circles[0].state == [],
    )


def test_set_state() -> None:
    check(
        {"op": "setState", "pointer": "/circles/0/state/0", "value": {"out": True}},
        expect=lambda m: m.circles[0].state[0].out is True,
    )


def test_set_flow() -> None:
    check(
        {
            "op": "setFlow",
            "pointer": "/circles/1",
            "value": {"kind": "sequence", "steps": []},
        },
        expect=lambda m: m.circles[1].flow is not None and m.circles[1].flow.kind == "sequence",
    )


def test_add_delegate() -> None:
    check(
        {"op": "addDelegate", "pointer": "/circles/1/delegate", "index": 0, "value": "A"},
        expect=lambda m: m.circles[1].delegate == ["A"],
    )


def test_remove_delegate() -> None:
    check(
        {"op": "removeDelegate", "pointer": "/circles/0/delegate/0"},
        expect=lambda m: m.circles[0].delegate == [],
    )


def test_set_guard_updates_existing() -> None:
    check(
        {
            "op": "setGuard",
            "pointer": "/circles/0/boundary/guards/0",
            "value": {"on": "after_tool", "ref": "m:other"},
        },
        expect=lambda m: m.circles[0].boundary.guards[0].on == "after_tool",
    )


def test_set_guard_appends_at_end() -> None:
    check(
        {
            "op": "setGuard",
            "pointer": "/circles/0/boundary/guards/1",
            "value": {"on": "after_model", "ref": "m:g2"},
        },
        expect=lambda m: len(m.circles[0].boundary.guards) == 2,
    )


def test_remove_guard() -> None:
    check(
        {"op": "removeGuard", "pointer": "/circles/0/boundary/guards/0"},
        expect=lambda m: m.circles[0].boundary.guards == [],
    )


def test_toggle_await_removes() -> None:
    check(
        {"op": "toggleAwait", "pointer": "/circles/0", "value": "search"},
        expect=lambda m: m.circles[0].boundary.await_ == [],
    )


def test_toggle_await_adds() -> None:
    check(
        {"op": "toggleAwait", "pointer": "/circles/0", "value": "summarize"},
        expect=lambda m: m.circles[0].boundary.await_ == ["search", "summarize"],
    )


def test_set_root() -> None:
    check(
        {"op": "setRoot", "pointer": "", "value": "B"},
        expect=lambda m: m.root == "B",
    )


# --------------------------------------------------------------------------------------
# rename の参照追随（docs/spec/ops.md §3）
# --------------------------------------------------------------------------------------
def test_rename_circle_follows_all_references() -> None:
    def expect(m: JinFile) -> None:
        assert [c.name for c in m.circles] == ["A", "Bee"]
        assert m.circles[0].delegate == ["Bee"]
        assert m.circles[0].tools[1].circle == "Bee"

    check({"op": "rename", "pointer": "/circles/1", "value": "Bee"}, expect=expect)


def test_rename_root_circle_updates_root() -> None:
    def expect(m: JinFile) -> None:
        assert m.root == "Alpha"
        assert m.circles[0].name == "Alpha"

    check({"op": "rename", "pointer": "/circles/0", "value": "Alpha"}, expect=expect)


def test_rename_tool_updates_await() -> None:
    def expect(m: JinFile) -> None:
        assert m.circles[0].tools[0].name == "find"
        assert m.circles[0].boundary.await_ == ["find"]

    check({"op": "rename", "pointer": "/circles/0/tools/0", "value": "find"}, expect=expect)


def test_rename_state_updates_rune_template() -> None:
    def expect(m: JinFile) -> None:
        assert m.circles[0].state[0].name == "question"
        assert m.circles[0].instruction.rune == "{question} を調べる"

    check({"op": "rename", "pointer": "/circles/0/state/0", "value": "question"}, expect=expect)


def test_rename_state_updates_flow_exit_key() -> None:
    model = JinFile.model_validate(
        {
            "$schema": SCHEMA,
            "version": 1,
            "root": "P",
            "circles": [
                {
                    "name": "P",
                    "flow": {
                        "kind": "loop",
                        "steps": ["C"],
                        "max": 2,
                        "exit": {"key": "done", "equals": True},
                    },
                },
                {
                    "name": "C",
                    "core": "m",
                    "state": [{"name": "done", "type": "bool", "out": True}],
                },
            ],
        }
    )
    result = apply_op(model, {"op": "rename", "pointer": "/circles/1/state/0", "value": "ok"})
    assert result.model.circles[0].flow.exit.key == "ok"
    back = apply_op(result.model, result.inverse).model
    assert dumps(back) == dumps(model)


# --------------------------------------------------------------------------------------
# 失敗時は診断コードで理由を返す
# --------------------------------------------------------------------------------------
def test_unknown_operation_raises() -> None:
    with pytest.raises(OpError) as excinfo:
        apply_op(sample(), {"op": "nope", "pointer": ""})
    assert excinfo.value.code == "JIN002"


def test_bad_pointer_raises_with_code() -> None:
    with pytest.raises(OpError) as excinfo:
        apply_op(sample(), {"op": "removeTool", "pointer": "/circles/0/tools/9"})
    assert excinfo.value.code == "JIN002"
    assert excinfo.value.hint


def test_duplicate_name_is_rejected() -> None:
    with pytest.raises(OpError) as excinfo:
        apply_op(sample(), {"op": "rename", "pointer": "/circles/1", "value": "A"})
    assert excinfo.value.code == "JIN010"


def test_invalid_value_is_rejected() -> None:
    with pytest.raises(OpError) as excinfo:
        apply_op(
            sample(), {"op": "addTool", "pointer": "/circles/0/tools", "index": 0, "value": {}}
        )
    assert excinfo.value.code == "JIN002"


def test_apply_ops_returns_inverses_in_undo_order() -> None:
    model = sample()
    result = apply_ops(
        model,
        [
            {"op": "setCore", "pointer": "/circles/1", "value": "x"},
            {"op": "setRoot", "pointer": "", "value": "B"},
        ],
    )
    assert result.model.root == "B"
    assert [op["op"] for op in result.inverses] == ["setRoot", "setCore"]
    undone = result.model
    for inverse in result.inverses:
        undone = apply_op(undone, inverse).model
    assert dumps(undone) == dumps(model)


def test_apply_ops_is_atomic_on_failure() -> None:
    model = sample()
    with pytest.raises(OpError):
        apply_ops(
            model,
            [
                {"op": "setCore", "pointer": "/circles/1", "value": "x"},
                {"op": "removeTool", "pointer": "/circles/0/tools/9"},
            ],
        )
    assert dumps(model) == dumps(sample())


# ======================================================================================
# 修正ラウンド 1 の回帰テスト
# ======================================================================================
def bare() -> JinFile:
    """`boundary` を**持たない** circle だけの文書。A-2 の再現に使う。"""
    return JinFile.model_validate(
        {
            "$schema": SCHEMA,
            "version": 1,
            "root": "A",
            "circles": [
                {
                    "name": "A",
                    "core": "gemini-2.5-flash",
                    "tools": [
                        {"name": "t1", "kind": "tool", "ref": "m:a"},
                        {"name": "t2", "kind": "tool", "ref": "m:b"},
                        {"name": "t3", "kind": "tool", "ref": "m:c"},
                    ],
                }
            ],
        }
    )


def with_awaits() -> JinFile:
    """await を 3 つ持つ文書。A-1（配列順の復元）の再現に使う。"""
    model = bare().model_copy(deep=True)
    document = json.loads(dumps(model))
    document["circles"][0]["boundary"] = {"await": ["t1", "t2", "t3"]}
    return JinFile.model_validate(document)


# ---- A-1: toggleAwait の逆オペレーションが配列順を戻す --------------------------------
@pytest.mark.parametrize("removed", ["t1", "t2", "t3"])
def test_toggle_await_inverse_restores_the_original_order(removed: str) -> None:
    """A-1: 外して戻したときに末尾へ付き直さないこと。

    `await` は宣言順を保持する配列（docs/spec/model.md §7 規則 3）なので、
    順序が変わると undo 後の正準形が元とバイト一致しない。
    """
    before = with_awaits()
    original = dumps(before)
    result = apply_op(before, {"op": "toggleAwait", "pointer": "/circles/0", "value": removed})
    after = roundtrip(result.model)
    assert after.circles[0].boundary is not None
    assert removed not in after.circles[0].boundary.await_
    assert len(after.circles[0].boundary.await_) == 2

    restored = apply_op(after, result.inverse).model
    assert restored.circles[0].boundary is not None
    assert restored.circles[0].boundary.await_ == ["t1", "t2", "t3"]
    assert dumps(restored) == original


def test_toggle_await_inverse_carries_the_original_index() -> None:
    result = apply_op(with_awaits(), {"op": "toggleAwait", "pointer": "/circles/0", "value": "t1"})
    assert result.inverse["index"] == 0


# ---- A-2: boundary を作ったオペレーションの逆が boundary を畳む ------------------------
def test_toggle_await_on_a_circle_without_boundary_round_trips_byte_identically() -> None:
    """A-2: 逆適用のあとに `"boundary": {}` が残らないこと。

    残ると「ファイル → モデル → ファイル」のバイト同一（成功条件 5）が undo 経路で崩れる。
    """
    before = bare()
    original = dumps(before)
    assert '"boundary"' not in original

    result = apply_op(before, {"op": "toggleAwait", "pointer": "/circles/0", "value": "t1"})
    after = roundtrip(result.model)
    assert after.circles[0].boundary is not None
    assert result.inverse["pruneBoundary"] is True

    restored = apply_op(after, result.inverse).model
    assert restored.circles[0].boundary is None
    assert dumps(restored) == original


def test_set_guard_on_a_circle_without_boundary_round_trips_byte_identically() -> None:
    """A-2: setGuard も同じ。"""
    before = bare()
    original = dumps(before)
    result = apply_op(
        before,
        {
            "op": "setGuard",
            "pointer": "/circles/0/boundary/guards/0",
            "value": {"on": "before_model", "ref": "m:g"},
        },
    )
    after = roundtrip(result.model)
    assert after.circles[0].boundary is not None
    assert result.inverse["pruneBoundary"] is True

    restored = apply_op(after, result.inverse).model
    assert restored.circles[0].boundary is None
    assert dumps(restored) == original


def test_an_explicitly_written_empty_boundary_is_not_pruned() -> None:
    """順オペレーションが作っていない `"boundary": {}` は消さない。

    元のファイルに書かれていたものを undo が勝手に消したら、それも
    バイト同一の破れになる。判定は「作ったかどうか」であって「空かどうか」ではない。
    """
    document = json.loads(dumps(bare()))
    document["circles"][0]["boundary"] = {}
    before = JinFile.model_validate(document)
    original = dumps(before)
    assert '"boundary": {}' in original

    result = apply_op(before, {"op": "toggleAwait", "pointer": "/circles/0", "value": "t1"})
    assert "pruneBoundary" not in result.inverse
    restored = apply_op(roundtrip(result.model), result.inverse).model
    assert dumps(restored) == original


def test_toggle_await_undo_redo_undo_is_stable() -> None:
    """undo → redo → undo でも元の正準形へ戻ること。"""
    before = bare()
    original = dumps(before)
    forward = apply_op(before, {"op": "toggleAwait", "pointer": "/circles/0", "value": "t2"})
    undone = apply_op(roundtrip(forward.model), forward.inverse)
    assert dumps(undone.model) == original
    redone = apply_op(roundtrip(undone.model), undone.inverse)
    assert dumps(redone.model) == dumps(roundtrip(forward.model))
    undone_again = apply_op(roundtrip(redone.model), redone.inverse)
    assert dumps(undone_again.model) == original


# ---- A-3: 経路セグメントの検証（全ハンドラ） -------------------------------------------
#: オペレーション名 → 「そのオペレーションが受け付けてはならない pointer」と最小の引数。
#: `/circles/0/state/0` を moveTool に渡すと tools が並べ替わる、といった取り違えを塞ぐ。
WRONG_ARRAY_POINTERS: dict[str, dict] = {
    "addCircle": {"op": "addCircle", "pointer": "/circles/0/tools", "index": 0, "value": {}},
    "removeCircle": {"op": "removeCircle", "pointer": "/circles/0/tools/0"},
    "setCore": {"op": "setCore", "pointer": "/circles/0/tools/0", "value": "m"},
    "setDescription": {"op": "setDescription", "pointer": "/circles/0/state/0", "value": "d"},
    "setRune": {"op": "setRune", "pointer": "/circles/0/tools/0", "value": "r"},
    "addTool": {"op": "addTool", "pointer": "/circles/0/state", "index": 0, "value": {}},
    "removeTool": {"op": "removeTool", "pointer": "/circles/0/state/0"},
    "moveTool": {"op": "moveTool", "pointer": "/circles/0/state/0", "index": 0},
    "addState": {"op": "addState", "pointer": "/circles/0/tools", "index": 0, "value": {}},
    "removeState": {"op": "removeState", "pointer": "/circles/0/tools/0"},
    "setState": {"op": "setState", "pointer": "/circles/0/tools/0", "value": {"out": True}},
    "setFlow": {"op": "setFlow", "pointer": "/circles/0/tools/0", "value": None},
    "addDelegate": {"op": "addDelegate", "pointer": "/circles/0/tools", "index": 0, "value": "B"},
    "removeDelegate": {"op": "removeDelegate", "pointer": "/circles/0/tools/0"},
    "setGuard": {
        "op": "setGuard",
        "pointer": "/circles/0/tools/0/guards/0",
        "value": {"on": "before_model", "ref": "m:g"},
    },
    "removeGuard": {"op": "removeGuard", "pointer": "/circles/0/tools/0/guards/0"},
    "toggleAwait": {"op": "toggleAwait", "pointer": "/circles/0/tools/0", "value": "search"},
    "setRoot": {"op": "setRoot", "pointer": "/circles/0", "value": "B"},
    "rename": {"op": "rename", "pointer": "/circles/0/boundary/guards/0", "value": "x"},
}


def test_every_operation_has_a_wrong_pointer_case() -> None:
    """新しいオペレーションを足したら、この表にも足すことを強制する。"""
    assert set(WRONG_ARRAY_POINTERS) == set(OPERATIONS)


@pytest.mark.parametrize("name", sorted(WRONG_ARRAY_POINTERS))
def test_operations_reject_a_pointer_into_the_wrong_array(name: str) -> None:
    """A-3: 経路セグメントを見ないと**指していない配列**を書き換える。

    修正前は `moveTool` に `/circles/0/state/0` を渡すと tools が並べ替わっていた。
    """
    with pytest.raises(OpError) as caught:
        apply_op(sample(), WRONG_ARRAY_POINTERS[name])
    assert caught.value.code in {"JIN002", "JIN010"}


def test_move_tool_with_a_state_pointer_does_not_touch_tools() -> None:
    """A-3 の実害を名指しで固定する（親が再現確認したケース）。"""
    before = sample()
    names_before = [t.name for t in before.circles[0].tools]
    with pytest.raises(OpError):
        apply_op(before, {"op": "moveTool", "pointer": "/circles/0/state/0", "index": 1})
    assert [t.name for t in before.circles[0].tools] == names_before


# ---- A-4 / S9: rename の深さ検査と添字の範囲検査 ---------------------------------------
@pytest.mark.parametrize(
    "pointer",
    ["/circles", "/circles/0/tools/0/name", "/circles/0/state/0/name", "", "/root"],
)
def test_rename_rejects_unsupported_depths(pointer: str) -> None:
    """A-4: 期待深さに実際の長さを渡していたので深さ検査が空振りしていた。"""
    with pytest.raises(OpError):
        apply_op(sample(), {"op": "rename", "pointer": pointer, "value": "X"})


@pytest.mark.parametrize("index", [2, 99, 1000])
def test_rename_rejects_an_out_of_range_circle_index(index: int) -> None:
    """S9: 範囲検査が無いと素の `IndexError` が呼び出し元へ抜ける。"""
    with pytest.raises(OpError) as caught:
        apply_op(sample(), {"op": "rename", "pointer": f"/circles/{index}", "value": "X"})
    assert caught.value.code == "JIN002"
    assert "範囲外" in caught.value.message


def test_set_core_and_rename_agree_on_an_out_of_range_index() -> None:
    """同じ pointer に対して 2 つのオペレーションが違う失敗の仕方をしないこと。"""
    op_rename = {"op": "rename", "pointer": "/circles/9", "value": "X"}
    op_set_core = {"op": "setCore", "pointer": "/circles/9", "value": "m"}
    with pytest.raises(OpError):
        apply_op(sample(), op_rename)
    with pytest.raises(OpError):
        apply_op(sample(), op_set_core)


@pytest.mark.parametrize("token", ["٣", "²", "-1", "01"])
def test_operations_reject_non_ascii_index_tokens(token: str) -> None:
    """S10: `isdigit()` だけだと ASCII 以外の数字が添字として通る。"""
    with pytest.raises(OpError):
        apply_op(sample(), {"op": "setCore", "pointer": f"/circles/{token}", "value": "m"})


# ---- S8: rename の新名がテンプレートとして展開されない ---------------------------------
@pytest.mark.parametrize("new_name", ["\\g<0>", "\\1", "q\\g<0>"])
def test_rename_state_treats_the_new_name_literally(new_name: str) -> None:
    """S8: `re.sub` の置換文字列だと `{q}` が `{{q}}` などに化けた。"""
    result = apply_op(
        sample(), {"op": "rename", "pointer": "/circles/0/state/0", "value": new_name}
    )
    model = roundtrip(result.model)
    assert model.circles[0].state[0].name == new_name
    assert model.circles[0].instruction is not None
    assert model.circles[0].instruction.rune == "{" + new_name + "} を調べる"


def test_rename_passes_a_literal_expected_depth_to_circle_index() -> None:
    """A-4: `_circle_index(op, len(tokens))` だと深さ検査が常に成立して何も守らない。

    「深さ検査が空振りしている」ことは振る舞いに出ないので、**呼び出しの形**を固定する。
    `expected_depth` に pointer 由来の式を渡していないことを AST で見る。
    """
    import ast
    from pathlib import Path

    from jin_core import ops as ops_module

    tree = ast.parse(Path(ops_module.__file__).read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_circle_index"
    ]
    assert calls, "_circle_index の呼び出しが見つからない"
    for call in calls:
        depth = call.args[2]
        assert isinstance(depth, ast.Constant) and isinstance(depth.value, int), (
            f"ops.py:{call.lineno} が expected_depth に定数以外を渡している"
            "（pointer の長さを渡すと深さ検査が空振りする）"
        )


def test_rename_state_cascades_to_circles_that_cannot_see_the_state() -> None:
    """ADR-013（DP-JIN-RENAME-SCOPE-01 案 (a)）: rename は**可視範囲に絞らない**。

    `docs/spec/ops.md` §3 が正であり、実装もそのとおりに動く。ここは
    「絞っていない」ことを固定する（`ops.py` のコメントだけが仕様と矛盾していた）。
    B は A の state を見られない別枝だが、同名 `{q}` は追随して置き換わる。
    """
    model = JinFile.model_validate(
        {
            "$schema": SCHEMA,
            "version": 1,
            "root": "A",
            "circles": [
                {
                    "name": "A",
                    "core": "m",
                    "state": [{"name": "q", "type": "str"}],
                    "instruction": {"rune": "A は {q} を見る"},
                },
                {"name": "B", "core": "m", "instruction": {"rune": "B も {q} と書いてある"}},
            ],
        }
    )
    result = apply_op(model, {"op": "rename", "pointer": "/circles/0/state/0", "value": "query"})
    after = roundtrip(result.model)
    assert after.circles[0].instruction is not None
    assert after.circles[1].instruction is not None
    assert after.circles[0].instruction.rune == "A は {query} を見る"
    # 可視範囲に絞っていれば B は書き換わらない。絞らない仕様なので書き換わる。
    assert after.circles[1].instruction.rune == "B も {query} と書いてある"


def test_rename_scope_comment_agrees_with_the_spec() -> None:
    """ADR-013: `ops.py` のコメントと `docs/spec/ops.md` §3 が矛盾していた（A-5）。"""
    from pathlib import Path

    from jin_core import ops as ops_module

    source = Path(ops_module.__file__).read_text(encoding="utf-8")
    spec = (Path(ops_module.__file__).resolve().parents[4] / "docs" / "spec" / "ops.md").read_text(
        encoding="utf-8"
    )
    assert "可視範囲に絞らず全 circle に対して行う" in spec
    assert "可視範囲には絞らない" in source
    assert "その state が見える circle" not in source, (
        "旧コメント（可視範囲に絞ると読める）が残っている"
    )


# ======================================================================================
# 修正ラウンド 2 の回帰テスト
# ======================================================================================
def with_flow() -> JinFile:
    """`flow.steps` / `delegate` / `summon` の 3 経路すべてで参照される circle を持つ文書。

    `sample()` には `flow` を持つ circle が無いため、`rename(circle)` の
    `flow.steps` 追随経路が 1 度も実行されていなかった（correctness review E-5）。
    """
    return JinFile.model_validate(
        {
            "$schema": SCHEMA,
            "version": 1,
            "root": "Root",
            "circles": [
                {
                    "name": "Root",
                    "flow": {"kind": "sequence", "steps": ["Target", "Other"]},
                },
                {
                    "name": "Holder",
                    "core": "m",
                    "delegate": ["Sub"],
                    "tools": [{"name": "call", "kind": "summon", "circle": "Target"}],
                },
                {"name": "Target", "core": "m"},
                {"name": "Other", "core": "m"},
                {"name": "Sub", "core": "m"},
            ],
        }
    )


def test_rename_circle_follows_flow_steps() -> None:
    """要件書 §6.3「rename は参照を全て追随」の中核。

    `ops.py` の `flow["steps"] = [...]` を `pass` に差し替えても 442 テストが全緑だった
    （correctness review E-5）。この経路を名指しで固定する。
    """
    result = apply_op(with_flow(), {"op": "rename", "pointer": "/circles/2", "value": "Renamed"})
    after = roundtrip(result.model)
    assert after.circles[0].flow is not None
    assert after.circles[0].flow.steps == ["Renamed", "Other"]
    assert after.circles[2].name == "Renamed"
    # 追随しないと JIN031（steps の要素が circle でない）が出るはずなので、それも見る。
    assert check_text(dumps(after), "t.jin").diagnostics == []


def test_rename_circle_follows_delegate() -> None:
    """E-5: rename(circle) の delegate 追随経路。"""
    result = apply_op(with_flow(), {"op": "rename", "pointer": "/circles/4", "value": "Renamed"})
    after = roundtrip(result.model)
    assert after.circles[1].delegate == ["Renamed"]
    assert check_text(dumps(after), "t.jin").diagnostics == []


def test_rename_circle_follows_summon() -> None:
    """E-5: rename(circle) の summon 追随経路。"""
    result = apply_op(with_flow(), {"op": "rename", "pointer": "/circles/2", "value": "Renamed"})
    after = roundtrip(result.model)
    assert after.circles[1].tools[0].circle == "Renamed"
    assert check_text(dumps(after), "t.jin").diagnostics == []


def test_rename_circle_follows_root() -> None:
    """E-5: rename(circle) の root 追随経路。"""
    result = apply_op(with_flow(), {"op": "rename", "pointer": "/circles/0", "value": "Renamed"})
    after = roundtrip(result.model)
    assert after.root == "Renamed"


def test_rename_circle_leaves_unrelated_references_alone() -> None:
    """同名でない参照まで書き換えないこと（過剰置換の検出）。"""
    result = apply_op(with_flow(), {"op": "rename", "pointer": "/circles/2", "value": "Renamed"})
    after = roundtrip(result.model)
    assert after.circles[0].flow is not None
    assert "Other" in after.circles[0].flow.steps


def test_rename_circle_inverse_restores_every_reference() -> None:
    """逆オペレーションで 4 経路すべてが元に戻ること。"""
    before = with_flow()
    original = dumps(before)
    result = apply_op(before, {"op": "rename", "pointer": "/circles/2", "value": "Renamed"})
    restored = apply_op(roundtrip(result.model), result.inverse).model
    assert dumps(restored) == original
