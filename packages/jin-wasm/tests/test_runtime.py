"""lupa ホストとスケジューラ（手書きの生成部で runtime.md §2 / §3 を固める）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jin_wasm.runtime import InputState, LuaHost, RunError, run_headless

from .conftest import program

#: loop(Play, Result) の最小の陣。Play は tick 3 回で finish、Result は 2 tick 待って quit=true。
LOOP_PROGRAM = """
DEBUG = true
ROOT = 1
FPS = 60
R[2] = {}
R[3] = {}
R[2][1] = function() S[2].k_0 = 0.0 end
R[2][2] = function(dt)
  S[2].k_0 = S[2].k_0 + 1.0
  TS(2, "n", "/circles/1/rites/1/steps/0", JN(S[2].k_0))
  H.canvas.clear("#000")
  H.canvas.rect(1.0, 2.0, 3.0, 4.0)
  if S[2].k_0 >= 3.0 then
    T("finish", 2, nil, "/circles/1/rites/1/steps/2/then/0", nil, nil)
    FINISH(2)
    return
  end
end
R[3][1] = function()
  WAIT_TICKS(2.0, "/circles/2/rites/0/steps/0")
  S[3].k_0 = true
  TS(3, "quit", "/circles/2/rites/0/steps/1", JB(S[3].k_0))
  FINISH(3)
end
CIRCLES[1] = { name = "Game", flow = "loop", children = { 2, 3 }, exit = function() return P[3].k_0 end }
CIRCLES[2] = {
  name = "Play",
  init = function() return { k_0 = 0.0 } end,
  publish = function() P[2].k_0 = S[2].k_0 end,
  dump = function() return '{"n":' .. JN(S[2].k_0) .. '}' end,
  pub = function() return '"Play.n":' .. JN(P[2].k_0) end,
  core = R[2][1], core_waits = false,
  on = { tick = R[2][2] }, on_waits = { tick = false }, on_ptr = { tick = "/circles/1/boundary/on/0" },
  guards = { { fn = function() return S[2].k_0 < 2.0 end, message = "n < 2", pointer = "/circles/1/boundary/guards/0" } },
}
CIRCLES[3] = {
  name = "Result",
  init = function() return { k_0 = false } end,
  publish = function() P[3].k_0 = S[3].k_0 end,
  dump = function() return '{"quit":' .. JB(S[3].k_0) .. '}' end,
  pub = function() return '"Result.quit":' .. JB(P[3].k_0) end,
  core = R[3][1], core_waits = true,
}
"""


def test_loop_program_runs_to_done(tmp_path) -> None:
    result = run_headless(program(LOOP_PROGRAM), {"debug": True}, seed=0, ticks=100)
    assert result.error is None
    assert result.done_tick == 4
    assert result.ticks == 5
    assert [f["ops"] for f in result.frames[:3]] == [
        [["clear", "#000"], ["rect", 1, 2, 3, 4]],
    ] * 3
    assert result.frames[3]["ops"] == [] and result.frames[4]["ops"] == []
    assert result.public == {"Play.n": 3, "Result.quit": True}

    kinds = [(r["tick"], r["kind"]) for r in result.rows]
    assert kinds[0] == (-1, "enter")  # boot は tick -1
    assert (2, "finish") in kinds and (2, "exit") in kinds
    assert (1, "assert") in kinds  # n == 2 のとき n < 2 が偽。実行は止まらない
    assert (2, "enter") in kinds  # Result は Play が done になった tick の 6 で entered
    waits = [r for r in result.rows if r["kind"] == "wait"]
    assert [(r["tick"], r["output"]) for r in waits] == [(2, "suspend"), (4, "resume")]
    assert [r["tick"] for r in result.rows if r["kind"] == "frame"] == [0, 1, 2, 3, 4]
    seqs = [r["seq"] for r in result.rows]
    assert seqs == list(range(len(seqs)))
    assert all(
        list(r) == ["seq", "tick", "circle", "kind", "name", "pointer", "input", "output"]
        for r in result.rows
    )


def test_two_runs_are_byte_identical() -> None:
    jil = program(LOOP_PROGRAM)
    a = run_headless(jil, {}, seed=0, ticks=100)
    b = run_headless(jil, {}, seed=0, ticks=100)
    assert json.dumps(a.rows) == json.dumps(b.rows)
    assert json.dumps(a.frames) == json.dumps(b.frames)


def test_release_build_has_no_trace_but_the_same_frames() -> None:
    debug = run_headless(program(LOOP_PROGRAM), {}, seed=0, ticks=100)
    release = run_headless(
        program(LOOP_PROGRAM.replace("DEBUG = true", "DEBUG = false")), {}, seed=0, ticks=100
    )
    assert release.rows == []
    assert [f["ops"] for f in release.frames] == [f["ops"] for f in debug.frames]
    assert release.done_tick == debug.done_tick


def test_ticks_after_done_do_nothing() -> None:
    host = LuaHost(program(LOOP_PROGRAM))
    host.boot(0, {})
    state = InputState()
    for t in range(5):
        host.tick(t, state.apply([]))
    late = host.tick(5, state.apply([]))
    assert late["done"] is True and late["ops"] == [] and late["trace"] == []


ERROR_PROGRAM = """
DEBUG = true
ROOT = 1
FPS = 60
R[1] = {}
R[1][1] = function()
  T("cast", 1, "x", "/circles/0/rites/0/steps/0", "[]", nil)
  local v = AT({}, 0.0)
end
CIRCLES[1] = {
  name = "Only",
  init = function() return {} end,
  core = R[1][1], core_waits = false,
  on = { tick = R[1][1] }, on_waits = { tick = false }, on_ptr = { tick = "/circles/0/boundary/on/0" },
}
"""


def test_runtime_error_writes_an_error_row_and_finishes() -> None:
    result = run_headless(program(ERROR_PROGRAM), {}, seed=0, ticks=10)
    assert result.error is not None and "添字" in result.error
    assert result.done_tick == 0
    errors = [r for r in result.rows if r["kind"] == "error"]
    assert len(errors) == 1
    assert errors[0]["tick"] == -1  # boot の核の手順で起きた
    assert errors[0]["pointer"] == "/circles/0/rites/0/steps/0"
    assert errors[0]["circle"] == "Only"


BUSY_PROGRAM = """
DEBUG = false
ROOT = 1
FPS = 60
R[1] = {}
R[1][1] = function() end
R[1][2] = function(dt) while true do end end
CIRCLES[1] = {
  name = "Busy",
  init = function() return {} end,
  core = R[1][1], core_waits = false,
  on = { tick = R[1][2] }, on_waits = { tick = false }, on_ptr = { tick = "/circles/0/boundary/on/0" },
}
"""


def test_instruction_budget_stops_an_infinite_loop() -> None:
    result = run_headless(program(BUSY_PROGRAM), {}, seed=0, ticks=3, budget=1_000_000)
    assert result.error is not None and "命令数" in result.error
    assert result.done_tick == 0


def test_lua_syntax_error_is_a_run_error() -> None:
    with pytest.raises(RunError):
        LuaHost("this is not lua")


def test_missing_entry_point_is_a_run_error() -> None:
    with pytest.raises(RunError):
        LuaHost("function boot() end")


def test_sandbox_removes_dangerous_globals() -> None:
    from jin_wasm.runtime import SANDBOX_REMOVED, sandboxed_runtime

    runtime = sandboxed_runtime()
    for name in (*SANDBOX_REMOVED, "python"):
        assert runtime.eval(f"type({name})") == "nil", name
    assert runtime.eval("type(string.dump)") == "nil"
    assert runtime.eval("_VERSION") == "Lua 5.4"
    # JIL を読む前は JIN_ARM / JIN_HOOK が置かれている（プレリュードが local へ捕まえる）
    assert runtime.eval("type(JIN_ARM) .. type(JIN_HOOK)") == "functionfunction"


def test_hook_globals_are_removed_after_the_jil_is_loaded() -> None:
    """読み込み後のグローバルは boot / tick だけ（jil.md §2）。プレリュードは local に捕まえ済み。"""
    from jin_wasm.jil import HOST_HOOK_GLOBALS

    host = LuaHost(program(LOOP_PROGRAM))
    for name in HOST_HOOK_GLOBALS:
        assert host._runtime.eval(f"type({name})") == "nil", name
    # 消した後も上限は効く（boot / tick の中でプレリュードの ARM が掛け直す）
    result = run_headless(program(BUSY_PROGRAM), {}, seed=0, ticks=3, budget=100_000)
    assert result.error is not None and "命令数" in result.error


#: `wait` を含む（コルーチンで走る）手順の中の無限ループ。Phase 2 の hook（メインスレッドだけ）では
#: 止まらなかった（probe §B.8）。
BUSY_COROUTINE_PROGRAM = """
DEBUG = false
ROOT = 1
FPS = 60
R[1] = {}
R[1][1] = function() end
R[1][2] = function(dt) local i = 0 while true do i = i + 1 end end
CIRCLES[1] = {
  name = "Busy",
  init = function() return {} end,
  core = R[1][1], core_waits = false,
  on = { tick = R[1][2] }, on_waits = { tick = true }, on_ptr = { tick = "/circles/0/boundary/on/0" },
}
"""


def test_instruction_budget_stops_an_infinite_loop_inside_a_coroutine() -> None:
    result = run_headless(program(BUSY_COROUTINE_PROGRAM), {}, seed=0, ticks=3, budget=1_000_000)
    assert result.error is not None and "命令数" in result.error
    assert result.done_tick == 0


#: 5 tick 生きる手順（毎 tick ≈ 12,000 命令）。hook を resume のたびに掛け直さないと、コルーチンの
#: count が累積して 2 tick 目で 20,000 を超える。
LONG_LIVED_COROUTINE_PROGRAM = """
DEBUG = false
ROOT = 1
FPS = 60
R[1] = {}
R[1][1] = function()
  for i = 1, 5 do
    local j = 0
    while j < 3000 do j = j + 1 end
    WAIT_TICKS(1.0, "/circles/0/rites/0/steps/1")
  end
  FINISH(1)
end
CIRCLES[1] = {
  name = "Long",
  init = function() return {} end,
  core = R[1][1], core_waits = true,
  on = {}, on_waits = {}, on_ptr = {},
}
"""


def test_the_coroutine_budget_is_reset_on_every_resume() -> None:
    result = run_headless(
        program(LONG_LIVED_COROUTINE_PROGRAM), {}, seed=0, ticks=10, budget=20_000
    )
    assert result.error is None
    assert result.done_tick == 4  # boot で 1 回 + tick 0..3 で 4 回待ち、tick 4 で finish


#: Python（`InputState.apply`）と TS（`apps/player/src/input.ts` の `InputReducer`）が同じ期待値で検算する
#: 共有 fixture。プレイヤーの `inputs` と `.jinrec` が同じ reducer から出ることがパリティの根拠。
JINREC_FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "jinrec"


def test_input_state_matches_the_reducer_fixture_shared_with_the_player() -> None:
    from jin_wasm.jinrec import read_jinrec

    recording = read_jinrec(JINREC_FIXTURES / "reducer.jinrec")
    expected = json.loads((JINREC_FIXTURES / "reducer.expected.json").read_text(encoding="utf-8"))
    assert recording.ticks == len(expected)
    state = InputState()
    actual = [
        state.apply(
            [
                {k: v for k, v in ev.items() if k != "tick"}
                for ev in recording.events
                if ev["tick"] == t
            ]
        )
        for t in range(recording.ticks)
    ]
    assert actual == expected


def test_input_state_reconstructs_held_keys_and_pointer() -> None:
    state = InputState()
    first = state.apply(
        [
            {"kind": "key", "name": "ArrowLeft", "down": True},
            {"kind": "pointer", "x": 1, "y": 2, "down": True},
        ]
    )
    assert first["keys"] == {"ArrowLeft": True}
    assert first["pointer"] == {"x": 1.0, "y": 2.0, "down": True}
    second = state.apply([{"kind": "key", "name": "ArrowLeft", "down": False}])
    assert second["keys"] == {}
    assert second["events"] == [{"kind": "key", "name": "ArrowLeft", "down": False}]
    assert second["pointer"] == {"x": 1.0, "y": 2.0, "down": True}
