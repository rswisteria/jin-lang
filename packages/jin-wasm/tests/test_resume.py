"""状態を保った差し替え（runtime.md §1 の `manifest.resume`・設計書 §11 #42〜#44）。

`tick` の結果（DEBUG）の `snapshot` を次の `boot` の `manifest.resume` に渡すと、名前で照合して
状態（state / 公開 state の確定値 / 生存 / flow の位置 / tick / seq / PCG32）が続く。
最も強い検査は「途切れずに走らせた列と、途中で差し替えて続けた列が **行（seq を含む）も画面も一致**する」。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jin_core.check import check_file, check_text
from jin_wasm.codegen import generate
from jin_wasm.runtime import InputState, LuaHost

from .conftest import program

REPO_ROOT = Path(__file__).resolve().parents[3]
PADDLE = REPO_ROOT / "examples-v2" / "paddle" / "paddle.jin"

#: 手書きの最小の陣。Only は tick ごとに n を進め、r に乱数を入れる（乱数列が続くことを見る）。
RESUME_PROGRAM = """
DEBUG = true
ROOT = 1
FPS = 60
R[1] = {}
R[1][1] = function() S[1].k_0 = 0.0 end
R[1][2] = function(dt)
  S[1].k_0 = S[1].k_0 + 1.0
  TS(1, "n", "/circles/0/rites/1/steps/0", JN(S[1].k_0))
  S[1].k_1 = H.random.range(0.0, 1000.0)
  TS(1, "r", "/circles/0/rites/1/steps/1", JN(S[1].k_1))
  H.canvas.clear("#000")
  H.canvas.rect(S[1].k_0, S[1].k_1, 3.0, 4.0)
end
CIRCLES[1] = {
  name = "Only",
  init = function() return { k_0 = 0.0, k_1 = 0.0 } end,
  publish = function() P[1].k_0 = S[1].k_0 end,
  dump = function() return '{"n":' .. JN(S[1].k_0) .. ',"r":' .. JN(S[1].k_1) .. '}' end,
  pdump = function() return '{"n":' .. JN(P[1].k_0) .. '}' end,
  restore = function(v)
    do local x = RN(v["n"]) if x ~= nil then S[1].k_0 = x end end
    do local x = RN(v["r"]) if x ~= nil then S[1].k_1 = x end end
  end,
  prestore = function(v) do local x = RN(v["n"]) if x ~= nil then P[1].k_0 = x end end end,
  pub = function() return '"Only.n":' .. JN(P[1].k_0) end,
  core = R[1][1], core_waits = false,
  on = { tick = R[1][2] }, on_waits = { tick = false }, on_ptr = { tick = "/circles/0/boundary/on/0" },
}
"""


def run_ticks(
    host: LuaHost, first: int, last: int, events: dict[int, list[dict[str, Any]]] | None = None
) -> list[dict[str, Any]]:
    """`tick(first..last)` の結果の列。

    押下状態（`inputs.keys`）はホストの外にある（プレイヤーの reducer / `jin run` の `InputState`）ので、
    途中から続けるときは `first` より前のイベントを先に reducer に通す（差し替えでは reducer は作り直さない）。
    """
    state = InputState()
    for t in range(first):
        state.apply((events or {}).get(t, []))
    return [host.tick(t, state.apply((events or {}).get(t, []))) for t in range(first, last + 1)]


def rows_of(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for result in results for row in result.get("trace", [])]


def frames_of(results: list[dict[str, Any]]) -> list[Any]:
    return [(result["ops"], result["audio"]) for result in results]


# ---------------------------------------------------------------- プレリュードだけ（手書きの生成部）


def test_resume_continues_the_same_rows_frames_and_random_sequence() -> None:
    """tick 9 の snapshot から新しいホストで続けると、tick 10〜19 の行（seq 込み）・画面・公開 state が一致する。"""
    jil = program(RESUME_PROGRAM)
    a = LuaHost(jil)
    a.boot(7, {"debug": True})
    a_results = run_ticks(a, 0, 19)
    snapshot = a_results[9]["snapshot"]
    assert snapshot["tick"] == 9 and snapshot["seed"] == 7
    assert snapshot["rng"].startswith("0x")
    assert [c["name"] for c in snapshot["circles"]] == ["Only"]
    assert snapshot["circles"][0]["state"] == {"n": 10, "r": snapshot["circles"][0]["state"]["r"]}
    assert snapshot["circles"][0]["public"] == {"n": 10}
    assert snapshot["circles"][0]["status"] == "active"

    b = LuaHost(jil)
    b.boot(999, {"debug": True, "resume": snapshot})  # seed は snapshot の 7 が勝つ
    b_results = run_ticks(b, 10, 19)
    assert rows_of(b_results) == rows_of(a_results[10:])
    assert frames_of(b_results) == frames_of(a_results[10:])
    assert [r["public"] for r in b_results] == [r["public"] for r in a_results[10:]]
    # 復元の知らせは直後の tick 結果に 1 回だけ。
    assert b_results[0]["resume"] == {"mode": "resumed", "tick": 9, "kept": ["Only"], "dropped": []}
    assert "resume" not in b_results[1]
    # snapshot も続く（seq は通し）。
    assert b_results[-1]["snapshot"]["seq"] == a_results[-1]["snapshot"]["seq"]


def test_release_results_have_no_snapshot() -> None:
    jil = program(RESUME_PROGRAM.replace("DEBUG = true", "DEBUG = false"))
    host = LuaHost(jil)
    host.boot(7, {})
    result = host.tick(0, InputState().apply([]))
    assert "snapshot" not in result and "resume" not in result
    assert list(result) == ["ops", "audio", "done", "error", "public"]


def test_resume_with_a_value_of_the_wrong_shape_keeps_the_init_value() -> None:
    """形が合わない欄は init のまま（黙って壊れた値を入れない）。合う欄だけ写す。"""
    jil = program(RESUME_PROGRAM)
    host = LuaHost(jil)
    host.boot(7, {"debug": True})
    snapshot = run_ticks(host, 0, 4)[-1]["snapshot"]
    snapshot["circles"][0]["state"]["n"] = "five"  # 文字列は num に合わない
    snapshot["circles"][0]["state"]["r"] = 42
    snapshot["circles"][0]["public"]["n"] = True
    other = LuaHost(jil)
    other.boot(7, {"resume": snapshot})
    first = other.tick(5, InputState().apply([]))
    assert first["resume"]["mode"] == "resumed"
    sets = {row["name"]: row["output"] for row in first["trace"] if row["kind"] == "set"}
    assert sets["n"] == 1  # init の 0 から 1 つ進んだ（5 ではない）
    assert first["snapshot"]["circles"][0]["state"]["r"] != 42  # r は乱数で上書きされる


def test_resume_drops_unknown_circles_and_falls_back_to_a_fresh_boot_when_the_root_is_missing() -> (
    None
):
    jil = program(RESUME_PROGRAM)
    host = LuaHost(jil)
    host.boot(7, {"debug": True})
    snapshot = run_ticks(host, 0, 4)[-1]["snapshot"]
    # 陣の名前が変わった（root が照合できない）→ 通常の boot に落ちる。知らせは fresh。
    renamed = json.loads(json.dumps(snapshot))
    renamed["circles"][0]["name"] = "Elsewhere"
    fresh = LuaHost(jil)
    fresh.boot(7, {"resume": renamed})
    first = fresh.tick(0, InputState().apply([]))
    assert first["resume"] == {"mode": "fresh", "tick": -1, "kept": [], "dropped": ["Elsewhere"]}
    kinds = [row["kind"] for row in first["trace"]]
    assert kinds[0] == "enter" and first["trace"][0]["seq"] == 0
    # 知らない陣が混ざっていても、root が照合できれば続く。
    extra = json.loads(json.dumps(snapshot))
    extra["circles"].append({"name": "Ghost", "status": "active", "state": {}})
    cont = LuaHost(jil)
    cont.boot(7, {"resume": extra})
    first = cont.tick(5, InputState().apply([]))
    assert first["resume"] == {"mode": "resumed", "tick": 4, "kept": ["Only"], "dropped": ["Ghost"]}


def test_resume_is_ignored_without_debug_snapshot_shape() -> None:
    """`resume` が壊れていれば（配列でない・欄が無い）通常の boot。"""
    jil = program(RESUME_PROGRAM)
    for resume in ({}, {"circles": 3}, {"circles": []}, "text", 5):
        host = LuaHost(jil)
        host.boot(7, {"resume": resume})
        first = host.tick(0, InputState().apply([]))
        assert first["trace"][0]["kind"] == "enter"
        assert (
            first["resume"]["mode"] == "fresh"
            if isinstance(resume, dict)
            else "resume" not in first
        )


# ---------------------------------------------------------------- codegen（paddle）


def load(path: Path):
    result = check_file(path)
    assert result.ok, result.diagnostics
    assert result.model is not None
    return result.model


def paddle_text(**edits: Any) -> str:
    """paddle.jin の JSON に手を入れた本文。"""
    data = json.loads(PADDLE.read_text(encoding="utf-8"))
    for fn in edits.values():
        fn(data)
    return json.dumps(data, ensure_ascii=False)


def game_of(text: str, name: str = "paddle.jin"):
    result = check_text(text, name)
    assert result.ok, result.diagnostics
    assert result.model is not None
    return generate(result.model, source_name=name, debug=True)


def paddle_run(ticks: int = 60, events: dict[int, list[dict[str, Any]]] | None = None):
    game = generate(load(PADDLE), source_name="paddle.jin", debug=True)
    host = LuaHost(game.lua)
    host.boot(7, game.manifest)
    return game, run_ticks(host, 0, ticks - 1, events)


KEYS = {
    3: [{"kind": "key", "name": "ArrowLeft", "down": True}],
    20: [{"kind": "key", "name": "ArrowLeft", "down": False}],
    35: [{"kind": "key", "name": "ArrowRight", "down": True}],
    50: [{"kind": "key", "name": "ArrowRight", "down": False}],
}


@pytest.mark.parametrize("at", [0, 14, 29, 44])
def test_paddle_resumed_from_a_snapshot_matches_the_uninterrupted_run(at: int) -> None:
    """生成部の restore / prestore / JR で paddle を途中から続けても、行・画面・公開 state が一致する。"""
    game, a_results = paddle_run(60, KEYS)
    snapshot = a_results[at]["snapshot"]
    b = LuaHost(game.lua)
    b.boot(7, {**game.manifest, "resume": snapshot})
    b_results = run_ticks(b, at + 1, 59, KEYS)
    assert b_results[0]["resume"]["mode"] == "resumed"
    assert sorted(b_results[0]["resume"]["kept"]) == ["Game", "Play", "Result"]
    assert rows_of(b_results) == rows_of(a_results[at + 1 :])
    assert frames_of(b_results) == frames_of(a_results[at + 1 :])


def test_an_edited_expression_keeps_the_running_state() -> None:
    """式を書き換えた JIL に差し替えても、score / ball / paddle は続く（ライブリロードの目的）。"""
    game, a_results = paddle_run(40, KEYS)
    snapshot = a_results[29]["snapshot"]

    def faster(data: dict[str, Any]) -> None:
        play = next(c for c in data["circles"] if c["name"] == "Play")
        step = next(r for r in play["rites"] if r["name"] == "step")
        # ArrowRight の枝 `paddle + 180 * dt` → `paddle + 360 * dt`（押している間だけ効く）
        branch = step["steps"][1]["then"][0]
        assert "180" in branch["expr"], branch
        branch["expr"] = branch["expr"].replace("180", "360")

    edited = game_of(paddle_text(edit=faster))
    assert edited.lua != game.lua
    b = LuaHost(edited.lua)
    b.boot(7, {**edited.manifest, "resume": snapshot})
    b_results = run_ticks(b, 30, 39, KEYS)
    assert b_results[0]["resume"]["mode"] == "resumed"
    play_before = next(c for c in snapshot["circles"] if c["name"] == "Play")
    play_after = next(c for c in b_results[0]["snapshot"]["circles"] if c["name"] == "Play")
    # tick 30 では ArrowLeft を離しているので paddle はそのまま、ball は 1 tick 進む。
    assert play_after["state"]["paddle"] == play_before["state"]["paddle"]
    assert play_after["state"]["ball"] != play_before["state"]["ball"]
    assert b_results[0]["public"] == a_results[30]["public"]
    # ArrowRight を押す tick 35 からは速さが違うので列が分かれる（差し替えが効いている）。
    assert frames_of(b_results[:5]) == frames_of(a_results[30:35])
    assert frames_of(b_results[5:]) != frames_of(a_results[35:])


def test_structural_edits_add_init_values_remove_silently_and_rename_starts_fresh() -> None:
    game, a_results = paddle_run(30)
    snapshot = a_results[-1]["snapshot"]

    def add_state(data: dict[str, Any]) -> None:
        play = next(c for c in data["circles"] if c["name"] == "Play")
        play["state"].append({"name": "lives", "type": "num", "init": "3"})

    added = game_of(paddle_text(edit=add_state))
    b = LuaHost(added.lua)
    b.boot(7, {**added.manifest, "resume": snapshot})
    first = b.tick(30, InputState().apply([]))
    play = next(c for c in first["snapshot"]["circles"] if c["name"] == "Play")
    assert play["state"]["lives"] == 3  # 足した state は init の値
    before = next(c for c in snapshot["circles"] if c["name"] == "Play")
    assert play["state"]["paddle"] == before["state"]["paddle"]  # 残りは続く

    # 消した state（`lives` 付きの snapshot を元の paddle に渡す）は黙って捨て、残りは続く。
    with_lives = first["snapshot"]
    c = LuaHost(game.lua)
    c.boot(7, {**game.manifest, "resume": with_lives})
    first = c.tick(31, InputState().apply([]))
    assert first["resume"]["mode"] == "resumed"
    play = next(c for c in first["snapshot"]["circles"] if c["name"] == "Play")
    assert "lives" not in play["state"]
    assert play["state"]["score"] == before["state"]["score"]

    def rename_root(data: dict[str, Any]) -> None:
        for circle in data["circles"]:
            if circle["name"] == "Game":
                circle["name"] = "Arena"
        data["root"] = "Arena"

    renamed = game_of(paddle_text(edit=rename_root))
    d = LuaHost(renamed.lua)
    d.boot(7, {**renamed.manifest, "resume": snapshot})
    first = d.tick(0, InputState().apply([]))
    assert first["resume"]["mode"] == "fresh" and first["resume"]["dropped"] == ["Game"]
    assert first["trace"][0]["kind"] == "enter" and first["trace"][0]["tick"] == -1


# ---------------------------------------------------------------- 生存の復元（fixture）

PROGRAMS = REPO_ROOT / "tests" / "fixtures" / "v2-programs"


def fixture_run(name: str, ticks: int):
    path = PROGRAMS / f"{name}.jin"
    game = generate(load(path), source_name=path.name, debug=True)
    host = LuaHost(game.lua)
    host.boot(7, game.manifest)
    return game, run_ticks(host, 0, ticks - 1)


def test_a_waiting_rite_is_dropped_but_the_events_keep_arriving() -> None:
    """`wait` 中の手順は差し替えで捨てる（コルーチンは越えられない）。`on tick` は届き続ける。

    wait_until の core は `wait until n >= 3` → `set flag` → `finish`。tick 1（n = 2）の snapshot から
    続けると、待っていた手順は再開しない（`wait … resume` の行が出ない・flag は false のまま・done に
    ならない）が、`step` は毎 tick 走って n は増え続ける。
    """
    game, a_results = fixture_run("wait_until", 10)
    assert a_results[3]["done"]  # 途切れずに走らせれば tick 3 で終わる
    snapshot = a_results[1]["snapshot"]
    only = snapshot["circles"][0]
    assert only["state"] == {"n": 2, "flag": False} and only["status"] == "active"

    b = LuaHost(game.lua)
    b.boot(7, {**game.manifest, "resume": snapshot})
    b_results = run_ticks(b, 2, 9)
    assert b_results[0]["resume"]["mode"] == "resumed"
    assert [row["kind"] for row in rows_of(b_results) if row["kind"] == "wait"] == []
    assert not any(result["done"] for result in b_results)
    assert b_results[-1]["public"] == {"Only.n": 10, "Only.flag": False}


def test_a_delegation_in_progress_is_restored() -> None:
    """`transfer` 中（委譲元は paused・委譲先は active）の snapshot から続けると、委譲先が動き続け、
    `done` で委譲元に戻る。行（seq 込み）と公開 state は途切れずに走らせた列と一致する。"""
    game, a_results = fixture_run("transfer", 6)
    snapshot = a_results[2]["snapshot"]
    by_name = {c["name"]: c for c in snapshot["circles"]}
    assert by_name["Main"]["paused"] and by_name["Main"]["delegate"] == "Sub"
    assert by_name["Sub"]["status"] == "active"

    b = LuaHost(game.lua)
    b.boot(7, {**game.manifest, "resume": snapshot})
    b_results = run_ticks(b, 3, 5)
    assert b_results[0]["resume"] == {
        "mode": "resumed",
        "tick": 2,
        "kept": ["Main", "Sub"],
        "dropped": [],
    }
    assert rows_of(b_results) == rows_of(a_results[3:])
    assert b_results[-1]["public"] == {"Main.n": 4, "Sub.m": 2}
