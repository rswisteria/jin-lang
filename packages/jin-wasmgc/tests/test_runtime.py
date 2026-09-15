"""wasmtime でのヘッドレス実行: Lua 経路との一致（fixture・算術・制御・文字列 / list / 型紙 / 能力 / エラー）と
trap の扱い（jil.md §6.2 / §6.4 / §6.6 / §6.7）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jin_core.check import check_file, check_text
from jin_core.v2.model import JinFileV2
from jin_wasm.codegen import generate as generate_lua
from jin_wasm.program import CodegenError
from jin_wasm.runtime import HeadlessResult, InputState, LuaHost, run_headless
from jin_wasmgc.assemble import assemble
from jin_wasmgc.runtime import WasmGcHost, WasmGcRunError, run_headless_wasm

REPO_ROOT = Path(__file__).resolve().parents[3]
FIB = REPO_ROOT / "examples-v2" / "fib" / "fib.jin"
PROGRAMS = REPO_ROOT / "tests" / "fixtures" / "v2-programs"


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


def program(
    state: list[dict],
    steps: list[dict],
    rites: list[dict] = (),
    *,
    sigils: list[dict] = (),
    on: list[dict] = (),
    forms: list[dict] = (),
    assets: list[dict] = (),
) -> JinFileV2:
    """root 1 つ・核 `main` の最小の `.jin`。"""
    circle: dict[str, Any] = {
        "name": "T",
        "core": "main",
        "state": state,
        "sigils": list(sigils),
        "rites": [*rites, {"name": "main", "steps": steps}],
    }
    if on:
        circle["boundary"] = {"on": list(on)}
    doc: dict[str, Any] = {
        "$schema": "https://xtone.internal/jin/schemas/jin-v2.schema.json",
        "version": 2,
        "root": "T",
        "stage": {"width": 64, "height": 64, "assets": list(assets)},
        "circles": [circle],
    }
    if forms:
        doc["forms"] = list(forms)
    return model_from(doc)


def host(name: str) -> dict:
    return {"name": name, "kind": "host", "host": name}


def both(
    model: JinFileV2, *, ticks: int = 3, seed: int = 7, **kw
) -> tuple[HeadlessResult, HeadlessResult]:
    lua = generate_lua(model, source_name="t.jin")
    wasm = assemble(model, source_name="t.jin")
    budget = kw.pop("budget", None)
    lua_kw = {**kw, "budget": budget} if budget is not None else kw
    return (
        run_headless(lua.lua, lua.manifest, seed=seed, ticks=ticks, **lua_kw),
        run_headless_wasm(wasm.wasm, wasm.manifest, seed=seed, ticks=ticks, **kw),
    )


def assert_same(model: JinFileV2, **kw) -> HeadlessResult:
    lua, wasm = both(model, **kw)
    assert wasm.public == lua.public
    assert wasm.frames == lua.frames
    assert wasm.done_tick == lua.done_tick and wasm.ticks == lua.ticks
    assert wasm.error == lua.error
    assert wasm.storage == lua.storage
    return wasm


def raw_ticks(
    model: JinFileV2,
    *,
    ticks: int,
    seed: int = 7,
    events: list[dict] = (),
    storage: dict | None = None,
) -> tuple[list[str], list[str]]:
    """生の tick 結果（JSON の文字列）を両経路で。`json.loads` を通すと 1 / 1.0 とエスケープの違いが消えるので、文字列で比べる。"""
    lua_game = generate_lua(model, source_name="t.jin")
    wasm_game = assemble(model, source_name="t.jin")
    by_tick: dict[int, list[dict]] = {}
    for ev in events:
        by_tick.setdefault(int(ev["tick"]), []).append(ev)
    lua = LuaHost(lua_game.lua)
    wasm = WasmGcHost(wasm_game.wasm)
    lua.boot(seed, {**lua_game.manifest, "storage": dict(storage or {})})
    wasm.boot(seed, {**wasm_game.manifest, "storage": dict(storage or {})})
    state_l, state_w = InputState(), InputState()
    out_l: list[str] = []
    out_w: list[str] = []
    for t in range(ticks):
        inputs = state_l.apply(by_tick.get(t, []))
        text = lua._tick(int(t), lua._runtime.table_from(inputs, recursive=True))
        assert isinstance(text, str)
        out_l.append(text)
        out_w.append(wasm.tick_raw(t, state_w.apply(by_tick.get(t, []))).decode("utf-8"))
    return out_l, out_w


# ---------------------------------------------------------------- fixture（Sub-Issue B の完了条件・jil.md §6.9）

EVENTS = {
    "text_input": [
        {"tick": 0, "kind": "text", "text": "ab"},
        {"tick": 0, "kind": "key", "name": "Backspace", "down": True},
        {"tick": 0, "kind": "text", "text": "c"},
        {"tick": 1, "kind": "key", "name": "Backspace", "down": False},
        {"tick": 2, "kind": "text", "text": "日本😀"},
    ],
    "key_pointer": [
        {"tick": 1, "kind": "key", "name": "ArrowLeft", "down": True},
        {"tick": 1, "kind": "key", "name": "Space", "down": True},
        {"tick": 2, "kind": "pointer", "x": 50, "y": 9, "down": True},
        {"tick": 2, "kind": "key", "name": "Space", "down": False},
        {"tick": 3, "kind": "key", "name": "ArrowLeft", "down": False},
    ],
}
STORAGE = {"runs": "2", "label": "old"}
FIXTURES = ["key_pointer", "storage", "text_input", "each_list", "bad_color", "runtime_error_index"]


@pytest.mark.parametrize("name", FIXTURES)
def test_the_fixture_matches_the_lua_path(name: str) -> None:
    model = load(PROGRAMS / f"{name}.jin")
    kw: dict[str, Any] = {"events": EVENTS.get(name, [])}
    if name == "storage":
        kw["storage"] = STORAGE
    wasm = assert_same(model, ticks=5, **kw)
    if name == "key_pointer":
        assert wasm.public == {
            "Only.keys": 2,
            "Only.held": 2,
            "Only.pressed": 1,
            "Only.lastx": 50,
            "Only.lastdown": True,
        }
    if name == "text_input":
        assert wasm.public == {"Only.name": "ab日本😀", "Only.typed": 6}
    if name == "each_list":
        assert wasm.public == {
            "Only.total": 13,
            "Only.label": "4/ell",
            "Only.count": 3,
            "Only.has": True,
            "Only.second": 2,
        }
    if name == "storage":
        assert wasm.storage == {"runs": "3", "best": "3", "label": "run 3"}
        assert wasm.frames[1]["ops"] == [["clear", "#000"], ["text", "run 3", 2, 2]]
    if name == "bad_color":
        assert wasm.error == '色は "#rgb" か "#rrggbb" で書きます（red）' and wasm.done_tick == 0
    if name == "runtime_error_index":
        assert wasm.error == "添字 5 は範囲外です（長さ 2）" and wasm.done_tick == 0


@pytest.mark.parametrize("name", [*FIXTURES, "fib"])
def test_the_raw_tick_results_are_the_same_text(name: str) -> None:
    """結果の JSON を文字列のまま比べる（数値の書式・エスケープ・キーの順・storage の位置まで）。"""
    path = FIB if name == "fib" else PROGRAMS / f"{name}.jin"
    lua, wasm = raw_ticks(
        load(path),
        ticks=5,
        events=EVENTS.get(name, []),
        storage=STORAGE if name == "storage" else None,
    )
    assert wasm == lua


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
    (-5, 1e308),
]  # 11 組（state / ステップの上限 12 に収める）。-5 % 1e308 は 2^53 以上の整数値（非整数の書式の経路）


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
    assert wasm.public["T.r10"] == 1e308 - 5


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
        {"name": "frac", "type": "num", "init": "0", "out": True},
        {"name": "tiny", "type": "num", "init": "0", "out": True},
    ]
    steps = [
        {"do": "set", "target": "z", "expr": "-0.0"},
        {"do": "set", "target": "inf", "expr": "1 / 0"},
        {"do": "set", "target": "ninf", "expr": "-1 / 0"},
        {"do": "set", "target": "big", "expr": "-9007199254740991"},
        {"do": "set", "target": "frac", "expr": "0.1 + 0.2"},
        {"do": "set", "target": "tiny", "expr": "1 / 3 * 1e-300"},
        {"do": "finish"},
    ]
    lua, wasm = raw_ticks(program(state, steps), ticks=1)
    assert wasm == lua
    # NaN / Infinity は JSON には文字列として載る（runtime.md §6・プレリュードの JN）
    assert (
        '"T.z":0,"T.inf":"Infinity","T.ninf":"-Infinity","T.big":-9007199254740991,'
        '"T.frac":0.30000000000000004,"T.tiny":3.3333333333333334e-301' in wasm[0]
    )


# ---------------------------------------------------------------- 文字列 / list / 型紙


def test_strings_lists_and_forms_match_lua() -> None:
    forms = [
        {
            "name": "Ball",
            "fields": [{"name": "pos", "type": "Pointer"}, {"name": "tag", "type": "str"}],
        }
    ]
    state = [
        {"name": "balls", "type": "list<Ball>", "init": "[]", "out": True},
        {"name": "names", "type": "list<str>", "init": '["b", "a"]', "out": True},
        {"name": "flags", "type": "list<bool>", "init": "[true, false]", "out": True},
        {"name": "text", "type": "str", "init": '"x"', "out": True},
        {"name": "n", "type": "num", "init": "0", "out": True},
        {"name": "ok", "type": "bool", "init": "false", "out": True},
    ]
    each = {
        "do": "loop",
        "kind": "each",
        "name": "b",
        "in": "balls",
        "steps": [
            {"do": "set", "target": "text", "expr": "text ++ b.tag ++ str(b.pos.x)"},
            {"do": "set", "target": "n", "expr": "n + len(b.tag)"},
        ],
    }
    steps = [
        {
            "do": "cast",
            "target": "push",
            "args": ["balls", 'Ball { pos: Pointer { x: 1.5, y: 2, down: true }, tag: "日本" }'],
        },
        {
            "do": "cast",
            "target": "push",
            "args": ["balls", 'Ball { pos: Pointer { x: 3, y: 4, down: false }, tag: "q\\"\\n" }'],
        },
        {"do": "set", "target": "balls[0].pos.x", "expr": "balls[0].pos.x + 10"},
        each,
        {"do": "cast", "target": "push", "args": ["names", "sub(text, 1, 2)"]},
        {"do": "set", "target": "names[0]", "expr": '"zz"'},
        {"do": "cast", "target": "removeAt", "args": ["names", "1"]},
        {"do": "cast", "target": "clear", "args": ["flags"]},
        {"do": "cast", "target": "push", "args": ["flags", 'names[0] == "zz" and names[0] != "a"']},
        {
            "do": "set",
            "target": "ok",
            "expr": 'contains(names, "zz") and contains(flags, true) and not contains(names, "b")',
        },
        {"do": "set", "target": "n", "expr": 'n + cmp(text, "x") + len(balls) + len(flags)'},
        {"do": "finish"},
    ]
    lua, wasm = raw_ticks(program(state, steps, forms=forms), ticks=1)
    assert wasm == lua
    result = json.loads(wasm[0])
    assert result["public"]["T.balls"] == [
        {"pos": {"x": 11.5, "y": 2, "down": True}, "tag": "日本"},
        {"pos": {"x": 3, "y": 4, "down": False}, "tag": 'q"\n'},
    ]
    assert result["public"]["T.text"] == 'x日本11.5q"\n3'
    assert result["public"]["T.names"] == ["zz", "日本"] and result["public"]["T.flags"] == [True]
    assert result["public"]["T.ok"] is True
    assert (
        result["public"]["T.n"] == (2 + 3) + 1 + 2 + 1
    )  # len(tag) の和 + cmp + len(balls) + len(flags)


# ---------------------------------------------------------------- 能力（abilities.md）


def test_random_ui_audio_and_canvas_match_lua() -> None:
    state = [
        {"name": "r", "type": "num", "init": "0", "out": True},
        {"name": "hits", "type": "num", "init": "0", "out": True},
        {
            "name": "p",
            "type": "Pointer",
            "init": "Pointer { x: 0, y: 0, down: false }",
            "out": True,
        },
    ]
    step = {
        "name": "step",
        "steps": [
            {"do": "set", "target": "r", "expr": "r + random.next() + random.range(-2.5, 9)"},
            {"do": "cast", "target": "canvas.clear", "args": ['"#123"']},
            {"do": "cast", "target": "canvas.ink", "args": ['"#AbCdEf"']},
            {
                "do": "cast",
                "target": "canvas.rect",
                "args": ["random.next() * 10", "0.5", "1e21", "-0.0"],
            },
            {"do": "cast", "target": "canvas.circle", "args": ["1", "2", "3"]},
            {"do": "cast", "target": "canvas.line", "args": ["1", "2", "3", "4"]},
            {"do": "cast", "target": "canvas.text", "args": ['"a\\"b\\n日"', "1", "2"]},
            {"do": "cast", "target": "canvas.sprite", "args": ['"hero"', "1", "2"]},
            {"do": "cast", "target": "ui.label", "args": ['"L"', "1", "2"]},
            {"do": "cast", "target": "audio.tone", "args": ["440", "100"]},
            {"do": "cast", "target": "audio.play", "args": ['"coin"']},
            {
                "do": "if",
                "cond": 'ui.button("B", 10, 10, 20, 20)',
                "then": [{"do": "set", "target": "hits", "expr": "hits + 1"}],
            },
        ],
    }
    ptr = {
        "name": "onptr",
        "params": [{"name": "q", "type": "Pointer"}],
        "steps": [{"do": "set", "target": "p", "expr": "q"}],
    }
    events = [
        {"tick": 1, "kind": "pointer", "x": 15, "y": 12, "down": True},
        {
            "tick": 2,
            "kind": "pointer",
            "x": 30,
            "y": 30,
            "down": False,
        },  # 境界（10 + 20）で離す → 当たり
        {"tick": 3, "kind": "pointer", "x": 5, "y": 5, "down": True},
        {"tick": 3, "kind": "pointer", "x": 5, "y": 5, "down": False},  # 外で離す
    ]
    model = program(
        state,
        [],
        [step, ptr],
        sigils=[host("random"), host("canvas"), host("ui"), host("audio"), host("input")],
        on=[{"event": "tick", "rite": "step"}, {"event": "pointer", "rite": "onptr"}],
        assets=[
            {"name": "hero", "kind": "sprite", "path": "hero.png"},
            {"name": "coin", "kind": "sound", "path": "coin.wav"},
        ],
    )
    lua, wasm = raw_ticks(model, ticks=5, events=events, seed=12345)
    assert wasm == lua
    last = json.loads(wasm[4])
    assert last["public"]["T.hits"] == 1
    assert last["public"]["T.p"] == {"x": 5, "y": 5, "down": False}
    assert last["ops"][0] == ["clear", "#123"] and last["ops"][1] == ["ink", "#AbCdEf"]
    assert last["ops"][5] == ["text", 'a"b\n日', 1, 2]
    assert last["audio"] == [["tone", 440, 100], ["play", "coin"]]


def test_storage_and_input_reads_match_lua() -> None:
    state = [
        {"name": "held", "type": "num", "init": "0", "out": True},
        {"name": "typed", "type": "str", "init": '""', "out": True},
        {"name": "got", "type": "str", "init": '""', "out": True},
    ]
    main = [
        {"do": "set", "target": "got", "expr": 'storage.get("k") ++ "/" ++ storage.get("none")'},
        {"do": "cast", "target": "storage.set", "args": ['"k"', '"v1"']},
        {"do": "cast", "target": "storage.set", "args": ['"k"', '"v2"']},
        {"do": "set", "target": "got", "expr": 'got ++ "/" ++ storage.get("k")'},
    ]
    step = {
        "name": "step",
        "steps": [
            {
                "do": "if",
                "cond": 'input.key("KeyA") or input.pressed("KeyB")',
                "then": [{"do": "set", "target": "held", "expr": "held + 1"}],
            },
            {"do": "set", "target": "typed", "expr": "typed ++ input.text()"},
            {
                "do": "if",
                "cond": "input.pointer().down",
                "then": [
                    {
                        "do": "cast",
                        "target": "storage.set",
                        "args": ['"t"', "str(input.pointer().x)"],
                    }
                ],
            },
        ],
    }
    events = [
        {"tick": 0, "kind": "key", "name": "KeyA", "down": True},
        {"tick": 1, "kind": "key", "name": "KeyB", "down": True},
        {"tick": 1, "kind": "text", "text": "é"},
        {"tick": 2, "kind": "key", "name": "KeyA", "down": False},
        {"tick": 2, "kind": "pointer", "x": 1.25, "y": 0, "down": True},
        {"tick": 3, "kind": "key", "name": "KeyB", "down": False},
    ]
    model = program(
        state,
        main,
        [step],
        sigils=[host("storage"), host("input")],
        on=[{"event": "tick", "rite": "step"}],
    )
    lua, wasm = raw_ticks(model, ticks=4, events=events, storage={"k": "base"})
    assert wasm == lua
    first = json.loads(wasm[0])
    assert first["public"]["T.got"] == "base//v2"
    assert first["storage"] == [["k", "v1"], ["k", "v2"]]
    assert json.loads(wasm[2])["storage"] == [["t", "1.25"]]
    assert "storage" not in json.loads(wasm[1])
    # tick 0: key("KeyA") / tick 1: pressed("KeyB") / tick 2: KeyA を離した tick は keys に無い
    assert json.loads(wasm[3])["public"] == {"T.held": 2, "T.typed": "é", "T.got": "base//v2"}


# ---------------------------------------------------------------- エラー機構（jil.md §6.4）と命令数の上限（§6.6）


def test_an_error_leaves_the_state_and_the_display_list_as_lua_does() -> None:
    """エラーの前の効果は残り、後の代入と効果は起きない。boot は publish_all を走らせ、tick は飛ばす。"""
    state = [
        {"name": "a", "type": "num", "init": "1", "out": True},
        {"name": "b", "type": "num", "init": "2", "out": True},
    ]
    step = {
        "name": "step",
        "steps": [
            {"do": "cast", "target": "canvas.rect", "args": ["1", "2", "3", "4"]},
            {"do": "set", "target": "a", "expr": "a + 1"},
            {"do": "let", "name": "xs", "expr": "[1]"},
            {"do": "set", "target": "b", "expr": "xs[7] + 1"},
            {"do": "cast", "target": "canvas.clear", "args": ['"#fff"']},
            {"do": "set", "target": "a", "expr": "100"},
        ],
    }
    model = program(
        state, [], [step], sigils=[host("canvas")], on=[{"event": "tick", "rite": "step"}]
    )
    lua, wasm = raw_ticks(model, ticks=3)
    assert wasm == lua
    first = json.loads(wasm[0])
    assert first["ops"] == [["rect", 1, 2, 3, 4]] and first["done"] is True
    assert first["error"] == "添字 7 は範囲外です（長さ 1）"
    assert first["public"] == {"T.a": 1, "T.b": 2}  # tick のエラーでは publish_all が走らない
    assert json.loads(wasm[2]) == {
        **first,
        "ops": [],
    }  # 以後の tick は同じ error / public で ops は空


def test_an_error_in_boot_still_publishes_like_lua() -> None:
    state = [
        {"name": "a", "type": "num", "init": "1", "out": True},
        {"name": "b", "type": "num", "init": "2", "out": True},
    ]
    steps = [
        {"do": "set", "target": "a", "expr": "5"},
        {"do": "let", "name": "xs", "expr": "[1]"},
        {"do": "set", "target": "b", "expr": "xs[0 - 1]"},
        {"do": "set", "target": "a", "expr": "9"},
    ]
    wasm = assert_same(program(state, steps), ticks=2)
    assert wasm.public == {"T.a": 5, "T.b": 2} and wasm.done_tick == 0
    assert wasm.error == "添字 -1 は範囲外です（長さ 1）"


@pytest.mark.parametrize("where", ["boot", "tick"])
def test_an_out_of_range_index_on_a_str_or_form_list_errors_instead_of_trapping(where: str) -> None:
    """`$Lr` の要素は非 null へ ref.cast するので、範囲外で null を返すと trap した。既定値を返して ERR で抜ける（Lua と同じ error 行）。"""
    forms = [{"name": "Ball", "fields": [{"name": "x", "type": "num"}]}]
    state = [
        {"name": "a", "type": "num", "init": "1", "out": True},
        {"name": "s", "type": "str", "init": '"init"', "out": True},
        {"name": "names", "type": "list<str>", "init": '["x"]', "out": True},
        {"name": "balls", "type": "list<Ball>", "init": "[Ball { x: 1 }]", "out": True},
    ]
    for expr in ("names[9]", "sub(names[2 - 5], 0, 1)"):
        steps = [
            {"do": "set", "target": "s", "expr": expr},
            {"do": "set", "target": "a", "expr": "9"},
        ]
        _check_error_parity(state, steps, forms, where)
    for expr in ("balls[3].x", "balls[1].x + a"):
        steps = [
            {"do": "set", "target": "a", "expr": expr},
            {"do": "set", "target": "s", "expr": '"after"'},
        ]
        _check_error_parity(state, steps, forms, where)
    # 代入先の添字が範囲外（`set xs[9] = …`）でも次のステップへ進まない
    for target, expr in (("names[9]", '"z"'), ("balls[5].x", "7"), ("balls[-1].x", "a")):
        steps = [
            {"do": "set", "target": target, "expr": expr},
            {"do": "set", "target": "a", "expr": "100"},
        ]
        _check_error_parity(state, steps, forms, where)


def _check_error_parity(
    state: list[dict], steps: list[dict], forms: list[dict], where: str
) -> None:
    if where == "boot":
        model = program(state, steps, forms=forms)
    else:
        rite = {"name": "step", "steps": steps}
        model = program(state, [], [rite], forms=forms, on=[{"event": "tick", "rite": "step"}])
    lua, wasm = raw_ticks(model, ticks=3)
    assert wasm == lua, steps
    result = json.loads(wasm[0 if where == "boot" else 1])
    assert result["error"].startswith("添字 ") and "は範囲外です" in result["error"], steps
    assert result["public"]["T.a"] == 1 and result["public"]["T.s"] == "init", steps
    assert_same(model, ticks=3)


def test_an_infinite_loop_stops_both_paths_in_the_same_tick_with_the_same_error() -> None:
    """命令数の上限（jil.md §6.6）: 単位が違うので回数は同じでなくてよいが、同じ tick で止まり release の error と done が一致する。"""
    budget_error = "命令数の上限 10000000 を超えました（無限ループ？）"
    # boot（核）での無限ループ
    steps = [{"do": "loop", "kind": "while", "cond": "true", "steps": []}]
    lua, wasm = both(program([], steps), ticks=2, budget=10_000_000)
    assert wasm.error == lua.error == budget_error
    assert wasm.done_tick == lua.done_tick == 0 and wasm.frames == lua.frames
    # tick（on tick）での無限ループ: tick 1 で当たる
    state = [{"name": "n", "type": "num", "init": "0", "out": True}]
    step = {
        "name": "step",
        "steps": [
            {"do": "set", "target": "n", "expr": "n + 1"},
            {
                "do": "if",
                "cond": "n == 2",
                "then": [
                    {
                        "do": "loop",
                        "kind": "count",
                        "times": "1e300",
                        "steps": [{"do": "set", "target": "n", "expr": "n + 0"}],
                    }
                ],
            },
        ],
    }
    model = program(state, [], [step], on=[{"event": "tick", "rite": "step"}])
    lua, wasm = both(model, ticks=5, budget=10_000_000)
    assert wasm.error == lua.error == budget_error
    assert wasm.done_tick == lua.done_tick == 1
    assert wasm.public == lua.public == {"T.n": 1}  # tick 1 の publish_all は走らない


def test_a_loop_of_rite_calls_hits_the_budget_at_the_call_or_the_back_edge() -> None:
    """手順の呼び出しにもカウンタが埋まる。深い再帰は Lua が "stack overflow" の文（位置付き）で落ち、wasm は
    call stack の trap になるので突き合わせない（既知の差・jil.md §6.4）。"""
    noop = {"name": "noop", "steps": []}
    steps = [
        {"do": "loop", "kind": "while", "cond": "true", "steps": [{"do": "cast", "target": "noop"}]}
    ]
    lua, wasm = both(program([], steps, [noop]), ticks=1, budget=10_000_000)
    assert wasm.error is not None and "命令数の上限" in wasm.error
    assert wasm.error == lua.error and wasm.done_tick == lua.done_tick == 0


def test_the_fuel_is_only_a_safety_net_named_as_a_generator_bug() -> None:
    steps = [{"do": "loop", "kind": "while", "cond": "true", "steps": []}]
    game = assemble(program([], steps))
    with pytest.raises(WasmGcRunError, match="fuel") as info:
        run_headless_wasm(game.wasm, game.manifest, seed=0, ticks=1, fuel=100_000)
    assert "boot に失敗しました" in str(info.value)


def test_a_typed_rite_that_can_fall_off_the_end_is_refused() -> None:
    """Lua は nil を返す形。wasm は黙って既定値を返せないので生成の時点で拒む（恒久・Sub-Issue ではない）。"""
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
