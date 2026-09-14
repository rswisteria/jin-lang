"""wasmtime でのヘッドレス実行: Lua 経路との一致（fib・算術・制御）・trap の扱い（jil.md §6.2 / §6.7）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jin_core.check import check_file, check_text
from jin_core.v2.model import JinFileV2
from jin_wasm.codegen import generate as generate_lua
from jin_wasm.runtime import HeadlessResult, run_headless
from jin_wasmgc.assemble import assemble
from jin_wasmgc.runtime import WasmGcHost, WasmGcRunError, run_headless_wasm

REPO_ROOT = Path(__file__).resolve().parents[3]
FIB = REPO_ROOT / "examples-v2" / "fib" / "fib.jin"


def load(path: Path) -> JinFileV2:
    result = check_file(path)
    assert result.ok, [d.message for d in result.diagnostics]
    assert isinstance(result.model, JinFileV2)
    return result.model


def model_from(doc: dict) -> JinFileV2:
    result = check_text(json.dumps(doc), "t.jin")
    assert result.ok, [d.message for d in result.diagnostics]
    assert isinstance(result.model, JinFileV2)
    return result.model


def program(state: list[dict], steps: list[dict], rites: list[dict] = ()) -> JinFileV2:
    """root 1 つ・核 `main` の最小の `.jin`。"""
    return model_from(
        {
            "$schema": "https://xtone.internal/jin/schemas/jin-v2.schema.json",
            "version": 2,
            "root": "T",
            "stage": {"width": 64, "height": 64},
            "circles": [
                {
                    "name": "T",
                    "core": "main",
                    "state": state,
                    "rites": [*rites, {"name": "main", "steps": steps}],
                }
            ],
        }
    )


def both(
    model: JinFileV2, *, ticks: int = 3, seed: int = 7
) -> tuple[HeadlessResult, HeadlessResult]:
    lua = generate_lua(model, source_name="t.jin")
    wasm = assemble(model, source_name="t.jin")
    return (
        run_headless(lua.lua, lua.manifest, seed=seed, ticks=ticks),
        run_headless_wasm(wasm.wasm, wasm.manifest, seed=seed, ticks=ticks),
    )


def assert_same(model: JinFileV2, **kw) -> HeadlessResult:
    lua, wasm = both(model, **kw)
    assert wasm.public == lua.public
    assert wasm.frames == lua.frames
    assert wasm.done_tick == lua.done_tick and wasm.ticks == lua.ticks
    assert wasm.error == lua.error
    return wasm


# ---------------------------------------------------------------- fib（Sub-Issue A の完了条件）


def test_fib_matches_the_lua_path() -> None:
    wasm = assert_same(load(FIB), ticks=300, seed=0)
    assert wasm.public == {"Fib.answer": 6765}
    assert wasm.done_tick == 0
    assert wasm.frames == [{"tick": 0, "ops": [], "audio": []}]


def test_the_host_boundary_carries_json_both_ways() -> None:
    game = assemble(load(FIB))
    host = WasmGcHost(game.wasm)
    host.boot(0, {**game.manifest, "storage": {}})
    inputs = {"events": [], "keys": {}, "pointer": {"x": 0.0, "y": 0.0, "down": False}}
    result = host.tick(0, inputs)
    # キーの順は runtime.md §1.2（Lua の result() と同じ）
    assert list(result) == ["ops", "audio", "done", "error", "public"]
    assert result == {
        "ops": [],
        "audio": [],
        "done": True,
        "error": None,
        "public": {"Fib.answer": 6765},
    }
    assert host.tick(1, inputs) == result


def test_a_large_input_grows_the_memory_instead_of_trapping() -> None:
    game = assemble(load(FIB))
    host = WasmGcHost(game.wasm)
    big = {**game.manifest, "storage": {"pad": "x" * 300_000}}
    host.boot(0, big)
    inputs = {"events": [], "keys": {}, "pointer": {"x": 0.0, "y": 0.0, "down": False}}
    assert host.tick(0, inputs)["public"] == {"Fib.answer": 6765}


# ---------------------------------------------------------------- 算術と制御（Lua と同じ値）

MOD_PAIRS = [
    (7, 3),
    (-7, 3),
    (7, -3),
    (-7, -3),
    (0, 5),
    (5, 0),
    (1e15, 7),
    (-1e15, 7),
    (9007199254740991, 10),
    (5, 1e308),
]  # -5 % 1e308 = 1e308 - 5 は 2^53 以上の整数値なので書式が #74（非整数の経路）  # 11 組（state / ステップの上限 12 に収める）


def test_modulo_matches_lua_for_integers_and_specials() -> None:
    state = [
        {"name": f"r{k}", "type": "num", "init": "0", "out": True} for k in range(len(MOD_PAIRS))
    ]
    steps = [
        {"do": "set", "target": f"r{k}", "expr": f"{a} % {b}"} for k, (a, b) in enumerate(MOD_PAIRS)
    ] + [{"do": "finish"}]
    wasm = assert_same(program(state, steps))
    assert wasm.public["T.r0"] == 1 and wasm.public["T.r1"] == 2 and wasm.public["T.r2"] == -2
    assert (
        wasm.public["T.r3"] == -1 and wasm.public["T.r5"] == "NaN"
    )  # 5 % 0 は NaN（JSON では文字列）


def test_loops_conditions_and_early_returns_match_lua() -> None:
    state = [
        {"name": "count", "type": "num", "init": "0", "out": True},
        {"name": "hit", "type": "num", "init": "0", "out": True},
        {"name": "flag", "type": "bool", "init": "false", "out": True},
        {"name": "nan_loops", "type": "num", "init": "0", "out": True},
        {"name": "ret", "type": "num", "init": "0", "out": True},
    ]
    helper = {
        "name": "clamp",
        "params": [{"name": "x", "type": "num"}],
        "returns": "num",
        "steps": [
            {"do": "if", "cond": "x > 10", "then": [{"do": "return", "expr": "10"}]},
            {"do": "return", "expr": "x"},
        ],
    }
    steps = [
        {
            "do": "loop",
            "kind": "while",
            "cond": "count < 100",
            "steps": [
                {"do": "set", "target": "count", "expr": "count + 1"},
                {
                    "do": "if",
                    "cond": "count % 7 == 0 and (count > 20 or count == 7)",
                    "then": [{"do": "set", "target": "hit", "expr": "hit + 1"}],
                },
                {"do": "if", "cond": "count == 50", "then": [{"do": "break"}]},
            ],
        },
        {
            "do": "loop",
            "kind": "count",
            "times": "0 / 0",
            "steps": [{"do": "set", "target": "nan_loops", "expr": "nan_loops + 1"}],
        },
        {
            "do": "loop",
            "kind": "count",
            "times": "2.9",
            "name": "i",
            "steps": [{"do": "set", "target": "nan_loops", "expr": "nan_loops + i + 10"}],
        },
        {"do": "set", "target": "flag", "expr": "not (hit == 0) and count >= 50"},
        {"do": "cast", "target": "clamp", "args": ["count * 3"], "into": "ret"},
        {"do": "finish"},
    ]
    wasm = assert_same(program(state, steps, [helper]))
    assert (
        wasm.public
        == {
            "T.count": 50,  # break で 50 で止まる
            "T.hit": 6,  # 7 の倍数 7 / 21 / 28 / 35 / 42 / 49（14 は `count > 20 or count == 7` を満たさない）
            "T.flag": True,
            "T.nan_loops": 21,  # NaN 回は 0 回、2.9 回は floor して 2 回（0 + 10）+（1 + 10）
            "T.ret": 10,  # clamp(150)
        }
    )


def test_finish_inside_a_cast_stops_the_caller_before_the_assignment() -> None:
    """Lua と同じ順: 呼ぶ → STOP なら返る → into に代入（jil.md §4 の `if STOP(i) then return end`）。"""
    state = [
        {"name": "a", "type": "num", "init": "1", "out": True},
        {"name": "b", "type": "num", "init": "1", "out": True},
    ]
    stopper = {
        "name": "stop",
        "returns": "num",
        "steps": [{"do": "finish"}, {"do": "return", "expr": "99"}],
    }
    steps = [
        {"do": "cast", "target": "stop", "into": "a"},
        {"do": "set", "target": "b", "expr": "2"},
    ]
    wasm = assert_same(program(state, steps, [stopper]))
    assert wasm.public == {"T.a": 1, "T.b": 1} and wasm.done_tick == 0


def test_published_state_is_the_confirmed_value_not_the_working_copy() -> None:
    """公開 state は確定値 P（二重バッファ・runtime.md §4）。boot の終わりに全陣を確定する。"""
    state = [{"name": "n", "type": "num", "init": "1", "out": True}]
    steps = [
        {"do": "set", "target": "n", "expr": "n * 5"}
    ]  # finish しない → tick ごとに走らない（核は 1 回）
    wasm = assert_same(program(state, steps), ticks=2)
    assert wasm.public == {"T.n": 5} and wasm.done_tick is None and wasm.ticks == 2


def test_negative_zero_and_specials_format_like_lua() -> None:
    state = [
        {"name": "z", "type": "num", "init": "0", "out": True},
        {"name": "inf", "type": "num", "init": "0", "out": True},
        {"name": "ninf", "type": "num", "init": "0", "out": True},
        {"name": "big", "type": "num", "init": "0", "out": True},
    ]
    steps = [
        {"do": "set", "target": "z", "expr": "-0.0"},
        {"do": "set", "target": "inf", "expr": "1 / 0"},
        {"do": "set", "target": "ninf", "expr": "-1 / 0"},
        {"do": "set", "target": "big", "expr": "-9007199254740991"},
        {"do": "finish"},
    ]
    lua_game = generate_lua(program(state, steps), source_name="t.jin")
    wasm_game = assemble(program(state, steps), source_name="t.jin")
    lua = run_headless(lua_game.lua, lua_game.manifest, seed=0, ticks=1)
    wasm = run_headless_wasm(wasm_game.wasm, wasm_game.manifest, seed=0, ticks=1)
    assert json.dumps(wasm.public) == json.dumps(lua.public)
    # NaN / Infinity は JSON には文字列として載る（runtime.md §6・プレリュードの JN）
    assert json.dumps(wasm.public) == (
        '{"T.z": 0, "T.inf": "Infinity", "T.ninf": "-Infinity", "T.big": -9007199254740991}'
    )


# ---------------------------------------------------------------- trap（生成系の不備・未実装）は名指しの WasmGcRunError


def test_an_infinite_loop_raises_until_the_counter_lands_while_lua_reports_an_error_row() -> None:
    """#73 時点の既知の差: Lua は `error`（budget）を持って正常に返り、wasm は fuel の Trap で例外になる。

    #74 で module 内のカウンタが入ると、両経路が同じ tick に同じ `error` を出す形に揃う（jil.md §6.6）。
    """
    steps = [{"do": "loop", "kind": "while", "cond": "true", "steps": []}]
    lua_game = generate_lua(program([], steps), source_name="t.jin")
    lua = run_headless(lua_game.lua, lua_game.manifest, seed=0, ticks=1, budget=100_000)
    assert lua.error is not None and "命令数の上限" in lua.error
    game = assemble(program([], steps))
    with pytest.raises(WasmGcRunError, match="#74") as info:
        run_headless_wasm(game.wasm, game.manifest, seed=0, ticks=1, fuel=1_000_000)
    assert "boot に失敗しました" in str(info.value)


def test_a_non_integer_number_traps_with_the_sub_issue_named() -> None:
    state = [{"name": "x", "type": "num", "init": "0.5", "out": True}]
    game = assemble(program(state, [{"do": "finish"}]))
    with pytest.raises(WasmGcRunError, match="#74"):
        run_headless_wasm(game.wasm, game.manifest, seed=0, ticks=1)


def test_a_typed_rite_that_can_fall_off_the_end_is_refused() -> None:
    """Lua は nil を返す形。wasm は黙って既定値を返せないので生成の時点で拒む（恒久・Sub-Issue ではない）。"""
    from jin_wasm.program import CodegenError

    half = {
        "name": "half",
        "params": [{"name": "x", "type": "num"}],
        "returns": "num",
        "steps": [{"do": "if", "cond": "x > 0", "then": [{"do": "return", "expr": "x"}]}],
    }
    state = [{"name": "a", "type": "num", "init": "0", "out": True}]
    steps = [{"do": "cast", "target": "half", "args": ["1"], "into": "a"}, {"do": "finish"}]
    with pytest.raises(CodegenError, match="nil"):
        assemble(program(state, steps, [half]))
    # 両枝で return すれば通る
    half["steps"][0]["else"] = [{"do": "return", "expr": "0 - x"}]
    assert assert_same(program(state, steps, [half])).public == {"T.a": 1}


def test_a_module_with_an_import_is_refused() -> None:
    from wasmtime import wat2wasm

    wasm = bytes(wat2wasm('(module (import "env" "f" (func)) (memory (export "memory") 1))'))
    with pytest.raises(WasmGcRunError, match="import"):
        WasmGcHost(wasm)


def test_a_module_without_the_host_exports_is_refused() -> None:
    from wasmtime import wat2wasm

    wasm = bytes(wat2wasm('(module (memory (export "memory") 1))'))
    with pytest.raises(WasmGcRunError, match="input"):
        WasmGcHost(wasm)
