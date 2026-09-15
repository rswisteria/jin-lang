"""状態を保った差し替え（runtime.md §1.3）の wasm-GC 版（`packages/jin-wasm/tests/test_resume.py` と同じ主張）。

`tick` の結果（debug）の `snapshot` を次の `boot` の `manifest.resume` に渡すと、名前で照合して
状態（state / 公開 state の確定値 / 生存 / flow の位置 / tick / seq / PCG32）が続く。
最も強い検査は「途切れずに走らせた列と、途中で差し替えて続けた列が **行（seq を含む）も画面も一致**する」。
加えて、snapshot そのものと復元後の tick 結果が Lua 経路と**文字列で一致**することも見る。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jin_core.check import check_file, check_text
from jin_wasm.codegen import generate as generate_lua
from jin_wasm.runtime import InputState, LuaHost
from jin_wasmgc.assemble import assemble
from jin_wasmgc.runtime import WasmGcHost

REPO_ROOT = Path(__file__).resolve().parents[3]
PADDLE = REPO_ROOT / "examples-v2" / "paddle" / "paddle.jin"
PROGRAMS = REPO_ROOT / "tests" / "fixtures" / "v2-programs"


def load(path: Path):
    result = check_file(path)
    assert result.ok, result.diagnostics
    assert result.model is not None
    return result.model


def run_ticks(
    host: WasmGcHost | LuaHost,
    first: int,
    last: int,
    events: dict[int, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    state = InputState()
    for t in range(first):
        state.apply((events or {}).get(t, []))
    return [host.tick(t, state.apply((events or {}).get(t, []))) for t in range(first, last + 1)]


def rows_of(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for result in results for row in result.get("trace", [])]


def frames_of(results: list[dict[str, Any]]) -> list[Any]:
    return [(result["ops"], result["audio"]) for result in results]


def wasm_game(path: Path):
    return assemble(load(path), source_name=path.name, debug=True)


def paddle_run(ticks: int = 60, events: dict[int, list[dict[str, Any]]] | None = None):
    game = wasm_game(PADDLE)
    host = WasmGcHost(game.wasm)
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
    game, a_results = paddle_run(60, KEYS)
    snapshot = a_results[at]["snapshot"]
    assert snapshot["tick"] == at and snapshot["seed"] == 7 and snapshot["rng"].startswith("0x")
    b = WasmGcHost(game.wasm)
    b.boot(999, {**game.manifest, "resume": snapshot})  # seed は snapshot の 7 が勝つ
    b_results = run_ticks(b, at + 1, 59, KEYS)
    assert b_results[0]["resume"]["mode"] == "resumed"
    assert sorted(b_results[0]["resume"]["kept"]) == ["Game", "Play", "Result"]
    assert "resume" not in b_results[1]
    assert rows_of(b_results) == rows_of(a_results[at + 1 :])
    assert frames_of(b_results) == frames_of(a_results[at + 1 :])
    assert [r["public"] for r in b_results] == [r["public"] for r in a_results[at + 1 :]]
    assert b_results[-1]["snapshot"]["seq"] == a_results[-1]["snapshot"]["seq"]


def test_the_snapshot_and_the_resumed_tick_match_the_lua_path_byte_for_byte() -> None:
    """snapshot（rng の 16 進・cursor・delegate …）と復元直後の tick 結果（resume の知らせ）が Lua と同じ文字列。"""
    path = PADDLE
    lua_game = generate_lua(load(path), source_name=path.name, debug=True)
    game = wasm_game(path)
    lua = LuaHost(lua_game.lua)
    wasm = WasmGcHost(game.wasm)
    lua.boot(7, lua_game.manifest)
    wasm.boot(7, game.manifest)
    state_l, state_w = InputState(), InputState()
    raw_l = raw_w = ""
    for t in range(12):
        ev = KEYS.get(t, [])
        raw_l = lua._tick(t, lua._runtime.table_from(state_l.apply(ev), recursive=True))
        raw_w = wasm.tick_raw(t, state_w.apply(ev)).decode("utf-8")
        assert raw_w == raw_l, t
    snapshot = json.loads(raw_w)["snapshot"]
    lua2 = LuaHost(lua_game.lua)
    wasm2 = WasmGcHost(game.wasm)
    lua2.boot(7, {**lua_game.manifest, "resume": snapshot})
    wasm2.boot(7, {**game.manifest, "resume": snapshot})
    for t in range(12, 16):
        inputs = state_l.apply(KEYS.get(t, []))
        state_w.apply(KEYS.get(t, []))
        raw_l = lua2._tick(t, lua2._runtime.table_from(inputs, recursive=True))
        raw_w = wasm2.tick_raw(t, inputs).decode("utf-8")
        assert raw_w == raw_l, t
        # 復元の知らせは直後の 1 回だけ
        assert ('"resume":{"mode":"resumed","tick":11,' in raw_w) == (t == 12)


def test_resume_with_a_value_of_the_wrong_shape_keeps_the_init_value() -> None:
    """形が合わない欄は init のまま（黙って壊れた値を入れない）。合う欄だけ写す。"""
    game, a_results = paddle_run(6)
    snapshot = a_results[-1]["snapshot"]
    play = next(c for c in snapshot["circles"] if c["name"] == "Play")
    play["state"]["score"] = "five"  # 文字列は num に合わない
    play["state"]["paddle"] = 11
    play["state"]["ball"]["x"] = True  # 型紙の欄が 1 つ合わない → 型紙ごと init のまま
    other = WasmGcHost(game.wasm)
    other.boot(7, {**game.manifest, "resume": snapshot})
    first = other.tick(6, InputState().apply([]))
    assert first["resume"]["mode"] == "resumed"
    after = next(c for c in first["snapshot"]["circles"] if c["name"] == "Play")
    assert after["state"]["paddle"] == 11
    assert after["state"]["score"] == 0
    assert after["state"]["ball"]["x"] != True  # noqa: E712  # init の値から 1 tick 進んだ数値


def test_resume_drops_unknown_circles_and_falls_back_to_a_fresh_boot_when_the_root_is_missing() -> (
    None
):
    game, a_results = paddle_run(6)
    snapshot = a_results[-1]["snapshot"]
    renamed = json.loads(json.dumps(snapshot))
    for c in renamed["circles"]:
        if c["name"] == "Game":
            c["name"] = "Elsewhere"
    fresh = WasmGcHost(game.wasm)
    fresh.boot(7, {**game.manifest, "resume": renamed})
    first = fresh.tick(0, InputState().apply([]))
    assert first["resume"] == {"mode": "fresh", "tick": -1, "kept": [], "dropped": ["Elsewhere"]}
    assert first["trace"][0]["kind"] == "enter" and first["trace"][0]["seq"] == 0
    extra = json.loads(json.dumps(snapshot))
    extra["circles"].append({"name": "Ghost", "status": "active", "state": {}})
    cont = WasmGcHost(game.wasm)
    cont.boot(7, {**game.manifest, "resume": extra})
    first = cont.tick(6, InputState().apply([]))
    assert first["resume"] == {
        "mode": "resumed",
        "tick": 5,
        "kept": ["Game", "Play", "Result"],
        "dropped": ["Ghost"],
    }


def test_resume_is_ignored_without_a_snapshot_shape() -> None:
    """`resume` が壊れていれば（配列でない・欄が無い）通常の boot。table でなければ知らせも無い。"""
    game = wasm_game(PADDLE)
    for resume in ({}, {"circles": 3}, {"circles": []}, "text", 5):
        host = WasmGcHost(game.wasm)
        host.boot(7, {**game.manifest, "resume": resume})
        first = host.tick(0, InputState().apply([]))
        assert first["trace"][0]["kind"] == "enter"
        if isinstance(resume, dict):
            assert first["resume"]["mode"] == "fresh"
        else:
            assert "resume" not in first


def test_release_results_have_no_snapshot() -> None:
    game = assemble(load(PADDLE), source_name="paddle.jin")
    host = WasmGcHost(game.wasm)
    host.boot(7, game.manifest)
    result = host.tick(0, InputState().apply([]))
    assert "snapshot" not in result and "resume" not in result and "trace" not in result
    assert list(result) == ["ops", "audio", "done", "error", "public"]


def paddle_text(**edits: Any) -> str:
    data = json.loads(PADDLE.read_text(encoding="utf-8"))
    for fn in edits.values():
        fn(data)
    return json.dumps(data, ensure_ascii=False)


def game_of(text: str, name: str = "paddle.jin"):
    result = check_text(text, name)
    assert result.ok, result.diagnostics
    assert result.model is not None
    return assemble(result.model, source_name=name, debug=True)


def test_an_edited_expression_keeps_the_running_state() -> None:
    """式を書き換えた module に差し替えても、score / ball / paddle は続く（ライブリロードの目的）。"""
    game, a_results = paddle_run(40, KEYS)
    snapshot = a_results[29]["snapshot"]

    def faster(data: dict[str, Any]) -> None:
        play = next(c for c in data["circles"] if c["name"] == "Play")
        step = next(r for r in play["rites"] if r["name"] == "step")
        branch = step["steps"][1]["then"][0]
        assert "180" in branch["expr"], branch
        branch["expr"] = branch["expr"].replace("180", "360")

    edited = game_of(paddle_text(edit=faster))
    assert edited.wasm != game.wasm
    b = WasmGcHost(edited.wasm)
    b.boot(7, {**edited.manifest, "resume": snapshot})
    b_results = run_ticks(b, 30, 39, KEYS)
    assert b_results[0]["resume"]["mode"] == "resumed"
    assert b_results[0]["public"] == a_results[30]["public"]
    assert frames_of(b_results[:5]) == frames_of(a_results[30:35])
    assert frames_of(b_results[5:]) != frames_of(a_results[35:])


def test_structural_edits_add_init_values_remove_silently_and_rename_starts_fresh() -> None:
    game, a_results = paddle_run(30)
    snapshot = a_results[-1]["snapshot"]

    def add_state(data: dict[str, Any]) -> None:
        play = next(c for c in data["circles"] if c["name"] == "Play")
        play["state"].append({"name": "lives", "type": "num", "init": "3"})

    added = game_of(paddle_text(edit=add_state))
    b = WasmGcHost(added.wasm)
    b.boot(7, {**added.manifest, "resume": snapshot})
    first = b.tick(30, InputState().apply([]))
    play = next(c for c in first["snapshot"]["circles"] if c["name"] == "Play")
    assert play["state"]["lives"] == 3
    before = next(c for c in snapshot["circles"] if c["name"] == "Play")
    assert play["state"]["paddle"] == before["state"]["paddle"]

    with_lives = first["snapshot"]
    c = WasmGcHost(game.wasm)
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
    d = WasmGcHost(renamed.wasm)
    d.boot(7, {**renamed.manifest, "resume": snapshot})
    first = d.tick(0, InputState().apply([]))
    assert first["resume"]["mode"] == "fresh" and first["resume"]["dropped"] == ["Game"]
    assert first["trace"][0]["kind"] == "enter" and first["trace"][0]["tick"] == -1


# ---------------------------------------------------------------- 生存の復元（fixture）


def fixture_run(name: str, ticks: int):
    path = PROGRAMS / f"{name}.jin"
    game = wasm_game(path)
    host = WasmGcHost(game.wasm)
    host.boot(7, game.manifest)
    return game, run_ticks(host, 0, ticks - 1)


def test_a_waiting_rite_is_dropped_but_the_events_keep_arriving() -> None:
    """`wait` 中の手順は差し替えで捨てる（フレームは snapshot に載らない）。`on tick` は届き続ける。"""
    game, a_results = fixture_run("wait_until", 10)
    assert a_results[3]["done"]
    snapshot = a_results[1]["snapshot"]
    only = snapshot["circles"][0]
    assert only["state"] == {"n": 2, "flag": False} and only["status"] == "active"
    b = WasmGcHost(game.wasm)
    b.boot(7, {**game.manifest, "resume": snapshot})
    b_results = run_ticks(b, 2, 9)
    assert b_results[0]["resume"]["mode"] == "resumed"
    assert [row["kind"] for row in rows_of(b_results) if row["kind"] == "wait"] == []
    assert not any(result["done"] for result in b_results)
    assert b_results[-1]["public"] == {"Only.n": 10, "Only.flag": False}


def test_a_delegation_in_progress_is_restored() -> None:
    game, a_results = fixture_run("transfer", 6)
    snapshot = a_results[2]["snapshot"]
    by_name = {c["name"]: c for c in snapshot["circles"]}
    assert by_name["Main"]["paused"] and by_name["Main"]["delegate"] == "Sub"
    assert by_name["Sub"]["status"] == "active"
    b = WasmGcHost(game.wasm)
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


def test_the_asked_counter_continues_across_a_resume() -> None:
    """v1 の陣への問いの通し番号は snapshot の `asked` から続く（未回答の問いは捨てる）。"""
    game, a_results = fixture_run("agent", 2)
    snapshot = a_results[-1]["snapshot"]
    assert snapshot["asked"] == 1
    b = WasmGcHost(game.wasm)
    b.boot(7, {**game.manifest, "resume": snapshot})
    # 未回答の問い（id 1）は捨てられているので、答えが来ても配達されない（emit 行の output が false）
    first = b.tick(2, InputState().apply([{"kind": "reply", "id": 1, "text": "late"}]))
    emit = next(r for r in first["trace"] if r["kind"] == "emit")
    assert emit["output"] is False and emit["circle"] is None
    assert first["snapshot"]["asked"] == 1
