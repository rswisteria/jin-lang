"""v1 の陣への問い（`agent` の sigil・runtime.md §11・設計書 §11 #55）のヘッドレス側。

- 問いは tick 結果の `asks` に出る（release でも・`storage` の直後）。`cast` は要求 id を返す
- `answer` の答えは次の tick の入力イベント `reply` になり、id を出した陣の `on message` へ
  `(sigil 名, id, text)` で届く（`emit` 行 → `event` 行 → `rite` 行）
- `replay`（`--input` の再生）では `answer` を呼ばず、録画の `reply` をそのまま配達する
- `answer` も `replay` も無いのに問いが出たら `RunError`
- id を知らない答えは捨てる（`emit` 行の output が false）
- 通し番号は snapshot の `asked` に載り、差し替えても続く
"""

from __future__ import annotations

from pathlib import Path

import pytest
from jin_core.check import check_file
from jin_wasm.codegen import generate
from jin_wasm.jil import forbidden_uses
from jin_wasm.runtime import InputState, LuaHost, RunError, run_headless

REPO_ROOT = Path(__file__).resolve().parents[3]
AGENT = REPO_ROOT / "tests" / "fixtures" / "v2-programs" / "agent.jin"


def game(debug: bool = True):
    result = check_file(AGENT)
    assert result.ok, [d.message for d in result.diagnostics]
    g = generate(result.model, source_name=AGENT.name, debug=debug)
    assert forbidden_uses(g.lua) == []
    return g


def echo(ask: dict) -> str:
    return f"echo:{ask['prompt']}"


def test_the_ask_leaves_in_the_tick_result_and_the_answer_arrives_next_tick() -> None:
    g = game()
    result = run_headless(g.lua, g.manifest, seed=7, ticks=10, answer=echo)
    assert result.error is None
    assert result.public == {
        "Npc.pending": 1,
        "Npc.answer": "echo:What is the password?",
        "Npc.replies": 1,
        "Npc.summary": "got:echo:What is the password?",
    }
    assert result.done_tick == 1
    assert result.replies == [
        {"tick": 1, "kind": "reply", "id": 1, "text": "echo:What is the password?"}
    ]
    kinds = [
        (r["tick"], r["kind"], r["circle"], r["name"], r["input"], r["output"]) for r in result.rows
    ]
    # boot の核: cast 行（input は prompt・output は id）。
    assert (-1, "cast", "Npc", "oracle", ["What is the password?"], 1) in kinds
    # 次の tick の 1: emit 行（sigil の pointer・[id, text]・配達された）→ event → rite。
    emit = next(r for r in result.rows if r["kind"] == "emit")
    assert emit["tick"] == 1
    assert emit["circle"] == "Npc"
    assert emit["name"] == "oracle"
    assert emit["pointer"] == "/circles/0/sigils/0"
    assert emit["input"] == [1, "echo:What is the password?"]
    assert emit["output"] is True
    event = next(r for r in result.rows if r["kind"] == "event" and r["name"] == "message")
    assert event["input"] == ["oracle", 1, "echo:What is the password?"]
    rite = next(r for r in result.rows if r["kind"] == "rite" and r["name"] == "recv")
    assert rite["input"] == ["oracle", 1, "echo:What is the password?"]


@pytest.mark.parametrize("debug", [True, False], ids=["debug", "release"])
def test_asks_appear_only_in_the_tick_that_asked_and_after_storage(debug: bool) -> None:
    g = game(debug)
    host = LuaHost(g.lua)
    host.boot(7, g.manifest)
    state = InputState()
    first = host.tick(0, state.apply([]))
    keys = list(first)
    assert "asks" in keys
    assert keys.index("asks") == keys.index("public") + 1  # storage は無いので public の直後
    if not debug:
        assert keys == ["ops", "audio", "done", "error", "public", "asks"]
    assert first["asks"] == [
        {"id": 1, "circle": "Npc", "name": "oracle", "prompt": "What is the password?"}
    ]
    second = host.tick(1, state.apply([]))
    assert "asks" not in second


def test_replay_delivers_the_recorded_reply_and_never_calls_answer() -> None:
    g = game()

    def boom(_ask: dict) -> str:
        raise AssertionError("再生では答えを求めない")

    events = [{"tick": 2, "kind": "reply", "id": 1, "text": "canned"}]
    result = run_headless(
        g.lua, g.manifest, seed=7, ticks=10, events=events, answer=boom, replay=True
    )
    assert result.error is None
    assert result.public["Npc.answer"] == "canned"
    assert result.done_tick == 2
    assert result.replies == []


def test_the_answer_is_normalised_before_delivery_and_recording() -> None:
    """改行 / タブは空白に、他の制御文字と対にならないサロゲートは落とす。Lua が見た文字列と録画の文字列が同じ。"""
    g = game()
    result = run_headless(
        g.lua, g.manifest, seed=7, ticks=5, answer=lambda _ask: "a\nb\tc\x07d\ud800e"
    )
    assert result.public["Npc.answer"] == "a b cde"
    assert result.replies[0]["text"] == "a b cde"


def test_a_program_that_asks_needs_a_host_unless_replaying() -> None:
    g = game()
    with pytest.raises(RunError, match="答えるホストがありません"):
        run_headless(g.lua, g.manifest, seed=7, ticks=3)
    result = run_headless(g.lua, g.manifest, seed=7, ticks=3, replay=True)
    assert result.error is None
    assert result.public["Npc.replies"] == 0  # 録画に無い問いには答えが来ない


def test_an_unknown_id_is_dropped_with_an_emit_row_that_says_so() -> None:
    g = game()
    events = [
        {"tick": 1, "kind": "reply", "id": 9, "text": "stray"},
        {"tick": 1, "kind": "reply", "id": 1, "text": "real"},
        {"tick": 2, "kind": "reply", "id": 1, "text": "again"},  # 一度配達した id は二度目を捨てる
    ]
    result = run_headless(g.lua, g.manifest, seed=7, ticks=5, events=events, replay=True)
    emits = [r for r in result.rows if r["kind"] == "emit"]
    assert [(r["circle"], r["input"], r["output"]) for r in emits] == [
        (None, [9, "stray"], False),
        ("Npc", [1, "real"], True),
    ]
    assert result.public["Npc.answer"] == "real"
    assert result.public["Npc.replies"] == 1


def test_the_ask_counter_survives_a_resume() -> None:
    g = game()
    host = LuaHost(g.lua)
    host.boot(7, g.manifest)
    first = host.tick(0, InputState().apply([]))
    assert first["snapshot"]["asked"] == 1
    other = LuaHost(g.lua)
    other.boot(7, {**g.manifest, "resume": first["snapshot"]})
    second = other.tick(1, InputState().apply([]))
    assert second["resume"]["mode"] == "resumed"
    assert second["snapshot"]["asked"] == 1
    # 未回答の問い（id → 陣）は差し替えで捨てる: 答えが来ても届かない。
    third = other.tick(
        2, InputState().apply([{"tick": 2, "kind": "reply", "id": 1, "text": "late"}])
    )
    emit = next(r for r in third["trace"] if r["kind"] == "emit")
    assert emit["output"] is False
