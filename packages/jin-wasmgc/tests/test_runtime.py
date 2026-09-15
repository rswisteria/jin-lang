"""wasmtime でのヘッドレス実行: Lua 経路との一致（fixture・算術・制御・文字列 / list / 型紙 / 能力 / エラー・
スケジューラ / wait の状態機械 / debug のトレース・agent）と trap の扱い（jil.md §6.2 / §6.4〜§6.7）。

Lua 経路が正なので、ほとんどの検査は「生の tick 結果（JSON の文字列）が同じ」（`raw_ticks`）で行う。
"""

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
    debug: bool = False,
    stop_when_done: bool = False,
) -> tuple[list[str], list[str]]:
    """生の tick 結果（JSON の文字列）を両経路で。`json.loads` を通すと 1 / 1.0 とエスケープの違いが消えるので、文字列で比べる。"""
    lua_game = generate_lua(model, source_name="t.jin", debug=debug)
    wasm_game = assemble(model, source_name="t.jin", debug=debug)
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
        if stop_when_done and json.loads(text).get("done"):
            break
    return out_l, out_w


def circles_doc(*circles: dict, root: str, forms: list[dict] = (), fps: int = 60) -> JinFileV2:
    """複数の陣（flow を含む）を持つ `.jin`。"""
    doc: dict[str, Any] = {
        "$schema": "https://xtone.internal/jin/schemas/jin-v2.schema.json",
        "version": 2,
        "root": root,
        "stage": {"width": 64, "height": 64, "fps": fps},
        "circles": list(circles),
    }
    if forms:
        doc["forms"] = list(forms)
    return model_from(doc)


def core_circle(name: str, state: list[dict], rites: list[dict], **extra: Any) -> dict:
    return {"name": name, "core": rites[0]["name"], "state": state, "rites": rites, **extra}


def assert_same_text(model: JinFileV2, **kw: Any) -> list[dict]:
    """debug の生の tick 結果（トレース・snapshot 込み）が Lua と同じ文字列。読んだ結果を返す。"""
    lua, wasm = raw_ticks(model, debug=True, **kw)
    assert wasm == lua
    return [json.loads(text) for text in wasm]


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


# ---------------------------------------------------------------- スケジューラ / wait / debug / agent（Sub-Issue C・jil.md §6.5〜§6.7）

ALL_EVENTS = {
    **EVENTS,
    "agent": [{"tick": 2, "kind": "reply", "id": 1, "text": "canned"}],
    "paddle": [
        {"tick": 3, "kind": "key", "name": "ArrowLeft", "down": True},
        {"tick": 20, "kind": "key", "name": "ArrowLeft", "down": False},
        {"tick": 35, "kind": "key", "name": "ArrowRight", "down": True},
    ],
    "clicker": [
        {"tick": 5, "kind": "pointer", "x": 30, "y": 70, "down": True},
        {"tick": 6, "kind": "pointer", "x": 30, "y": 70, "down": False},
        {"tick": 70, "kind": "pointer", "x": 140, "y": 70, "down": True},
        {"tick": 71, "kind": "pointer", "x": 140, "y": 70, "down": False},
    ],
}
ALL_PROGRAMS = sorted(p.stem for p in PROGRAMS.glob("*.jin")) + ["fib", "paddle", "clicker"]
EXAMPLES = REPO_ROOT / "examples-v2"


def any_path(name: str) -> Path:
    return (
        (EXAMPLES / name / f"{name}.jin")
        if (EXAMPLES / name).is_dir()
        else PROGRAMS / f"{name}.jin"
    )


@pytest.mark.parametrize("name", ALL_PROGRAMS)
def test_every_program_gives_the_same_debug_tick_text_as_lua(name: str) -> None:
    """17 本すべての debug の tick 結果（trace / snapshot / asks / storage を含む JSON）が文字列で一致する。"""
    ticks = {"paddle": 40, "clicker": 80}.get(name, 6)
    lua, wasm = raw_ticks(
        load(any_path(name)),
        ticks=ticks,
        events=ALL_EVENTS.get(name, []),
        storage=STORAGE if name == "storage" else None,
        debug=True,
        stop_when_done=True,
    )
    assert wasm == lua
    # boot で done になる陣は tick 0 で何もせず frame 行も無い（Lua と同じ）。それ以外は毎 tick 1 行
    first = json.loads(wasm[0])
    assert ('"kind":"frame"' in wasm[0]) == (
        first["trace"][0]["tick"] == -1 and not (first["done"] and first["trace"][-1]["tick"] == -1)
    )


def test_wait_ticks_and_until_inside_loops_with_locals_and_a_waiting_cast() -> None:
    """wait の状態機械: loop の中の wait、局所を読む until、待つ手順への cast と tick を跨ぐ戻り値、複数の待ち。"""
    twice = {
        "name": "twice",
        "params": [{"name": "x", "type": "num"}],
        "returns": "num",
        "steps": [
            {"do": "let", "name": "k", "expr": "x * 2"},
            {"do": "wait", "ticks": "k"},
            {"do": "set", "target": "log", "expr": 'log ++ "t"'},
            {"do": "return", "expr": "k + n"},
        ],
    }
    main = {
        "name": "main",
        "steps": [
            {"do": "let", "name": "xs", "expr": "[1, 2, 3]"},
            {
                "do": "loop",
                "kind": "each",
                "name": "x",
                "in": "xs",
                "steps": [
                    {"do": "wait", "until": "n >= x * 2"},
                    {"do": "set", "target": "log", "expr": "log ++ str(x)"},
                ],
            },
            {
                "do": "loop",
                "kind": "count",
                "times": "2",
                "name": "i",
                "steps": [
                    {"do": "cast", "target": "twice", "args": ["i + 1"], "into": "got"},
                    {"do": "set", "target": "log", "expr": 'log ++ "/" ++ str(got)'},
                ],
            },
            {
                "do": "loop",
                "kind": "while",
                "cond": "n < 30",
                "steps": [
                    {
                        "do": "if",
                        "cond": "n % 2 == 0",
                        "then": [{"do": "wait", "ticks": "1"}],
                        "else": [{"do": "wait", "ticks": "0.5"}],
                    },
                    {"do": "set", "target": "log", "expr": 'log ++ "."'},
                ],
            },
            {"do": "finish"},
        ],
    }
    step = {"name": "step", "steps": [{"do": "set", "target": "n", "expr": "n + 1"}]}
    ping = {
        "name": "ping",
        "steps": [
            {"do": "wait", "ticks": "3"},
            {"do": "set", "target": "pings", "expr": "pings + 1"},
        ],
    }
    state = [
        {"name": "n", "type": "num", "init": "0", "out": True},
        {"name": "got", "type": "num", "init": "0", "out": True},
        {"name": "log", "type": "str", "init": '""', "out": True},
        {"name": "pings", "type": "num", "init": "0", "out": True},
    ]
    model = program(
        state,
        main["steps"],
        [twice, step, ping],
        sigils=[host("input")],
        on=[{"event": "tick", "rite": "step"}, {"event": "key", "rite": "ping"}],
    )
    events = [{"tick": t, "kind": "key", "name": "Space", "down": t % 2 == 0} for t in range(2, 9)]
    results = assert_same_text(model, ticks=45, events=events)
    assert results[-1]["done"]
    public = results[-1]["public"]
    # each の until で "123"、twice の wait を跨いだ戻り値で "t/…" が 2 回、while の wait で "." が並ぶ
    assert public["T.log"].startswith("123t/") and public["T.log"].endswith(".")
    assert public["T.pings"] == 7  # on key の手順は同じ陣で並んで待てる
    waits = [r["output"] for res in results for r in res["trace"] if r["kind"] == "wait"]
    assert waits.count("suspend") > 20 and 0 < waits.count("resume") <= waits.count("suspend")


def test_finish_transfer_and_errors_while_waiting_match_lua() -> None:
    """待っている手順は finish で捨てられ、on exit の手順が wait しても黙って落ち、transfer 先が idle でなければ error 行。"""
    main = {
        "name": "main",
        "steps": [{"do": "wait", "until": "n >= 100"}, {"do": "set", "target": "n", "expr": "-1"}],
    }
    step = {
        "name": "step",
        "steps": [
            {"do": "set", "target": "n", "expr": "n + 1"},
            {"do": "if", "cond": "n == 2", "then": [{"do": "transfer", "circle": "Sub"}]},
            {"do": "if", "cond": "n == 4", "then": [{"do": "finish"}]},
        ],
    }
    bye = {
        "name": "bye",
        "steps": [{"do": "wait", "ticks": "1"}, {"do": "set", "target": "n", "expr": "n + 100"}],
    }
    main_c = core_circle(
        "Main",
        [{"name": "n", "type": "num", "init": "0", "out": True}],
        [main, step, bye],
        delegate=["Sub"],
        boundary={"on": [{"event": "tick", "rite": "step"}, {"event": "exit", "rite": "bye"}]},
    )
    sub = core_circle(
        "Sub",
        [{"name": "m", "type": "num", "init": "0", "out": True}],
        [
            {"name": "start", "steps": []},
            {
                "name": "tick",
                "steps": [
                    {"do": "set", "target": "m", "expr": "m + 1"},
                    {"do": "if", "cond": "m == 1", "then": [{"do": "finish"}]},
                ],
            },
        ],
        boundary={"on": [{"event": "tick", "rite": "tick"}]},
    )
    results = assert_same_text(circles_doc(main_c, sub, root="Main"), ticks=8)
    assert results[-1]["done"] and results[-1]["public"] == {"Main.n": 4, "Sub.m": 1}
    # transfer 先が idle でない: Sub が active のうちに Main がもう一度 transfer する
    step_twice = {
        "name": "step",
        "steps": [
            {"do": "set", "target": "n", "expr": "n + 1"},
            {"do": "if", "cond": "n == 1", "then": [{"do": "transfer", "circle": "Sub"}]},
        ],
    }
    sub_slow = core_circle(
        "Sub",
        [{"name": "m", "type": "num", "init": "0", "out": True}],
        [
            {
                "name": "start",
                "steps": [{"do": "emit", "circle": "Main", "message": "again", "args": []}],
            },
            {
                "name": "back",
                "steps": [
                    {"do": "cast", "target": "poke"},
                ],
            },
            {"name": "poke", "steps": [{"do": "set", "target": "m", "expr": "m + 1"}]},
        ],
        boundary={"on": [{"event": "message", "rite": "back"}]},
    )
    main_again = core_circle(
        "Main",
        [{"name": "n", "type": "num", "init": "0", "out": True}],
        [
            {"name": "main", "steps": []},
            step_twice,
            {
                "name": "recv",
                "params": [{"name": "name", "type": "str"}],
                "steps": [{"do": "transfer", "circle": "Sub"}],
            },
        ],
        delegate=["Sub"],
        boundary={"on": [{"event": "tick", "rite": "step"}, {"event": "message", "rite": "recv"}]},
    )
    results = assert_same_text(circles_doc(main_again, sub_slow, root="Main"), ticks=4)
    assert (
        results[-1]["error"] is None
    )  # Main は休止中なので message は捨てられる（emit 行の output が false）
    emits = [r for res in results for r in res["trace"] if r["kind"] == "emit"]
    assert emits and emits[0]["output"] is False


def test_flows_advance_like_lua_including_the_loop_exit_and_the_advance_limit() -> None:
    """sequence / parallel / loop の進行と exit、同じ tick に何段も進む形、1 tick に 1000 回で advance の error。"""

    def leaf(name: str, finish_at: int) -> dict:
        return core_circle(
            name,
            [{"name": "n", "type": "num", "init": "0", "out": True}],
            [
                {"name": "start", "steps": []},
                {
                    "name": "step",
                    "steps": [
                        {"do": "set", "target": "n", "expr": "n + 1"},
                        {"do": "if", "cond": f"n >= {finish_at}", "then": [{"do": "finish"}]},
                    ],
                },
            ],
            boundary={"on": [{"event": "tick", "rite": "step"}]},
        )

    doc = circles_doc(
        {
            "name": "Root",
            "flow": {"kind": "loop", "steps": ["Pair", "Tail"], "exit": "Tail.n >= 1"},
        },
        {"name": "Pair", "flow": {"kind": "parallel", "steps": ["A", "B"]}},
        leaf("A", 2),
        leaf("B", 3),
        leaf("Tail", 1),
        root="Root",
    )
    results = assert_same_text(doc, ticks=14)
    assert results[-1]["done"]
    # 同期的に done になる loop は 1000 回で止まる
    instant = core_circle("Now", [], [{"name": "start", "steps": [{"do": "finish"}]}])
    doc = circles_doc(
        {"name": "Root", "flow": {"kind": "loop", "steps": ["Now"], "exit": "false"}},
        instant,
        root="Root",
    )
    results = assert_same_text(doc, ticks=2)
    assert (
        results[0]["error"]
        == "1 tick の中で陣の進行が 1000 回を超えました（exit が常に偽の loop など）"
    )
    assert (
        results[0]["trace"][-1]["kind"] == "error" and results[0]["done"]
    )  # boot で当たる（frame 行は無い）


def test_guards_summon_and_emit_rows_match_lua() -> None:
    lib = core_circle(
        "Lib",
        [{"name": "calls", "type": "num", "init": "0", "out": True}],
        [
            {"name": "noop", "steps": []},
            {
                "name": "twice",
                "params": [{"name": "s", "type": "str"}],
                "returns": "str",
                "steps": [
                    {"do": "set", "target": "calls", "expr": "calls + 1"},
                    {"do": "return", "expr": "s ++ s"},
                ],
            },
        ],
    )
    main = core_circle(
        "Main",
        [
            {"name": "text", "type": "str", "init": '""', "out": True},
            {"name": "xs", "type": "list<num>", "init": "[1]", "out": True},
        ],
        [
            {
                "name": "main",
                "steps": [
                    {"do": "cast", "target": "dbl", "args": ['"ab"'], "into": "text"},
                    {"do": "emit", "circle": "Main", "message": "hello", "args": ["xs", "text"]},
                    {"do": "cast", "target": "push", "args": ["xs", "2"]},
                ],
            },
            {
                "name": "recv",
                "params": [
                    {"name": "name", "type": "str"},
                    {"name": "ys", "type": "list<num>"},
                    {"name": "s", "type": "str"},
                ],
                "steps": [{"do": "set", "target": "text", "expr": "text ++ s ++ str(len(ys))"}],
            },
        ],
        sigils=[{"name": "dbl", "kind": "summon", "circle": "Lib", "rite": "twice"}],
        boundary={
            "on": [{"event": "message", "rite": "recv"}],
            "guards": [{"assert": "len(text) < 8", "message": "短く"}, {"assert": "xs[0] == 1"}],
        },
    )
    results = assert_same_text(circles_doc(main, lib, root="Main"), ticks=3)
    kinds = [(r["kind"], r["name"], r["output"]) for res in results for r in res["trace"]]
    assert ("cast", "dbl", "abab") in kinds and ("emit", "hello", True) in kinds
    assert ("assert", None, "短く") in kinds
    assert results[-1]["public"]["Main.text"] == "abababab2"


def test_a_budget_hit_inside_a_waiting_rite_stops_both_paths_in_the_same_tick() -> None:
    main = {
        "name": "main",
        "steps": [
            {"do": "wait", "ticks": "2"},
            {
                "do": "loop",
                "kind": "while",
                "cond": "true",
                "steps": [{"do": "set", "target": "n", "expr": "n + 1"}],
            },
        ],
    }
    state = [{"name": "n", "type": "num", "init": "0", "out": True}]
    lua, wasm = both(program(state, main["steps"]), ticks=5, budget=10_000_000)
    assert wasm.error == lua.error == "命令数の上限 10000000 を超えました（無限ループ？）"
    assert wasm.done_tick == lua.done_tick == 1


# ---------------------------------------------------------------- agent（runtime.md §11）


def agent_games():
    model = load(PROGRAMS / "agent.jin")
    return generate_lua(model, source_name="agent.jin", debug=True), assemble(
        model, source_name="agent.jin", debug=True
    )


def echo(ask: dict) -> str:
    return f"echo:{ask['prompt']}"


def test_the_ask_leaves_in_the_tick_result_and_the_answer_arrives_next_tick() -> None:
    lua_game, wasm_game = agent_games()
    lua = run_headless(lua_game.lua, lua_game.manifest, seed=7, ticks=10, answer=echo)
    wasm = run_headless_wasm(wasm_game.wasm, wasm_game.manifest, seed=7, ticks=10, answer=echo)
    assert (
        wasm.public
        == lua.public
        == {
            "Npc.pending": 1,
            "Npc.answer": "echo:What is the password?",
            "Npc.replies": 1,
            "Npc.summary": "got:echo:What is the password?",
        }
    )
    assert wasm.replies == lua.replies and wasm.rows == lua.rows and wasm.done_tick == 1


def test_replay_delivers_the_recorded_reply_and_never_calls_answer() -> None:
    _, wasm_game = agent_games()

    def boom(_ask: dict) -> str:
        raise AssertionError("再生では答えを求めない")

    events = [{"tick": 2, "kind": "reply", "id": 1, "text": "canned"}]
    result = run_headless_wasm(
        wasm_game.wasm,
        wasm_game.manifest,
        seed=7,
        ticks=10,
        events=events,
        answer=boom,
        replay=True,
    )
    assert result.error is None and result.public["Npc.answer"] == "canned" and result.replies == []


def test_a_program_that_asks_needs_a_host_unless_replaying() -> None:
    from jin_wasm.runtime import RunError

    _, wasm_game = agent_games()
    with pytest.raises(RunError, match="答えるホストがありません"):
        run_headless_wasm(wasm_game.wasm, wasm_game.manifest, seed=7, ticks=3)
    result = run_headless_wasm(wasm_game.wasm, wasm_game.manifest, seed=7, ticks=3, replay=True)
    assert result.public["Npc.replies"] == 0


def test_an_unknown_id_is_dropped_with_an_emit_row_that_says_so() -> None:
    events = [
        {"tick": 1, "kind": "reply", "id": 9, "text": "stray"},
        {"tick": 1, "kind": "reply", "id": 1, "text": "real"},
        {"tick": 2, "kind": "reply", "id": 1, "text": "again"},
        {"tick": 2, "kind": "reply", "id": 1.5, "text": "half"},
    ]
    results = assert_same_text(load(PROGRAMS / "agent.jin"), ticks=4, events=events)
    emits = [
        (r["circle"], r["input"], r["output"])
        for res in results
        for r in res["trace"]
        if r["kind"] == "emit"
    ]
    assert emits[:2] == [(None, [9, "stray"], False), ("Npc", [1, "real"], True)]
