"""プレリュードの単体（数値書式 / JSON / PCG32 / 純関数 / ホスト能力）。

`conftest.prelude_internals` がプレリュードの局所を返すので、生成部無しで直接叩ける。
"""

from __future__ import annotations

import json
import math
import random

import pytest
from jin_wasm.jil import forbidden_uses
from jin_wasm.prelude import prelude_source

# ---------------------------------------------------------------- 契約


def test_prelude_has_no_forbidden_words() -> None:
    assert forbidden_uses(prelude_source()) == []


# ---------------------------------------------------------------- 数値の書式（runtime.md §6）


def expected_numstr(x: float) -> str:
    if math.isnan(x):
        return "NaN"
    if math.isinf(x):
        return "Infinity" if x > 0 else "-Infinity"
    if x == math.floor(x) and abs(x) < 2**53:
        return str(int(x)) if x != 0 else "0"
    return repr(x)


_SAMPLES = [
    0.0,
    -0.0,
    1.0,
    -3.0,
    0.1,
    0.5,
    -2.5,
    1 / 3,
    100.25,
    123456.789,
    1e-5,
    1.5e-7,
    0.0001,
    0.00001,
    1e15 + 0.5,
    4503599627370495.5,
    2.0**53,
    2.0**53 + 2,
    1e16,
    1.2345678901234568e16,
    1e22,
    1e300,
    5e-324,
    1.7976931348623157e308,
    0.016666666666666666,
    1.05,
]


@pytest.mark.parametrize("x", _SAMPLES)
def test_numstr_matches_python_repr(prelude, x: float) -> None:
    assert prelude.NUMSTR(x) == expected_numstr(x)


def test_expression_number_literals_use_the_same_format_as_str(prelude) -> None:
    """式の数値リテラルの正準形（expr.md §8・`jin_core.v2.expr.format_number`）は `str(x)` と同じ書式。

    jin-core は jin-wasm を import できないので、両者の一致はここで見る（有限の値だけ。
    `format_number` は NaN / inf を書けないので ValueError）。
    """
    from jin_core.v2.expr import format_number

    rng = random.Random(20260914)
    values = [x for x in _SAMPLES if math.isfinite(x)]
    values += [rng.uniform(-1, 1) * 10.0 ** rng.randint(-12, 24) for _ in range(300)]
    values += [float(rng.randint(-(2**54), 2**54)) for _ in range(100)]
    for x in values:
        assert format_number(x) == prelude.NUMSTR(x), x
    for x in (math.inf, -math.inf, math.nan):
        with pytest.raises(ValueError):
            format_number(x)


def test_numstr_matches_python_repr_for_random_values(prelude) -> None:
    rng = random.Random(20260913)
    for _ in range(500):
        x = rng.uniform(-1, 1) * 10.0 ** rng.randint(-12, 24)
        assert prelude.NUMSTR(x) == expected_numstr(x), x
    for _ in range(200):
        x = rng.random()
        assert prelude.NUMSTR(x) == expected_numstr(x), x


def test_numstr_matches_the_shared_fixture(prelude) -> None:
    """`tests/fixtures/numbers.jsonl`（`scripts/generate_number_fixture.py`）は Lua 経路の出力が正で、wasm-GC 経路
    （`packages/jin-wasmgc/tests/test_numbers.py`）が同じ文字列を出すことを固定する共有 fixture（jil.md §6.4）。
    repr との差は 2 の冪（往復の区間が非対称な値）だけ（`%.{p}e` の探索の既知の差）。
    """
    from pathlib import Path

    fixture = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "numbers.jsonl"
    rows = [json.loads(line) for line in fixture.read_text(encoding="utf-8").splitlines()]
    assert len(rows) >= 700
    for row in rows:
        x = float.fromhex(row["hex"])
        assert prelude.NUMSTR(x) == row["str"], row
        assert row["repr"] == expected_numstr(x), row
        if row["str"] != row["repr"]:
            assert abs(x) == 2.0 ** math.floor(math.log2(abs(x))), row


def test_numstr_special_values(prelude) -> None:
    assert prelude.NUMSTR(float("nan")) == "NaN"
    assert prelude.NUMSTR(float("inf")) == "Infinity"
    assert prelude.NUMSTR(float("-inf")) == "-Infinity"
    assert prelude.JN(float("nan")) == '"NaN"'
    assert prelude.JN(float("inf")) == '"Infinity"'
    assert prelude.JN(3.0) == "3"
    assert prelude.JN(2.5) == "2.5"


# ---------------------------------------------------------------- JSON


@pytest.mark.parametrize(
    "text",
    ["", "plain", 'quote " and \\ backslash', "tab\tnl\ncr\r", "\x00\x1f", "日本語 🎮", " "],
)
def test_js_round_trips_through_json(prelude, text: str) -> None:
    assert json.loads(prelude.JS(text)) == text


def test_jv_and_jl(prelude, prelude_and_runtime) -> None:
    _, runtime = prelude_and_runtime
    assert prelude.JV(True) == "true"
    assert prelude.JV(None) == "null"
    assert prelude.JV("s") == '"s"'
    serializer = prelude.JL(prelude.JV)
    assert serializer(runtime.table_from([1.0, 2.5, "x"], recursive=True)) == '[1,2.5,"x"]'
    assert serializer(runtime.table_from([], recursive=True)) == "[]"


# ---------------------------------------------------------------- PCG32（abilities.md §6）

_MASK64 = (1 << 64) - 1


class Pcg32:
    """参照実装（pcg32_srandom_r で initstate = initseq = seed）。"""

    def __init__(self, seed: int) -> None:
        self.state = 0
        self.inc = ((seed << 1) | 1) & _MASK64
        self.step()
        self.state = (self.state + seed) & _MASK64
        self.step()

    def step(self) -> int:
        old = self.state
        self.state = (old * 6364136223846793005 + self.inc) & _MASK64
        xorshifted = (((old >> 18) ^ old) >> 27) & 0xFFFFFFFF
        rot = old >> 59
        return ((xorshifted >> rot) | (xorshifted << ((32 - rot) & 31))) & 0xFFFFFFFF


@pytest.mark.parametrize("seed", [0, 1, 7, 12345, 2**32 - 1])
def test_pcg32_matches_the_reference(prelude, seed: int) -> None:
    prelude.rng_seed(seed)
    ref = Pcg32(seed)
    assert [prelude.rng_step() for _ in range(32)] == [ref.step() for _ in range(32)]


def test_random_next_is_in_unit_interval_and_range_is_inclusive(prelude) -> None:
    prelude.rng_seed(7)
    ref = Pcg32(7)
    for _ in range(50):
        got = prelude.H.random.next()
        assert got == ref.step() / 2**32
        assert 0.0 <= got < 1.0
    prelude.rng_seed(3)
    ref = Pcg32(3)
    for _ in range(50):
        got = prelude.H.random.range(2.7, 5.2)
        assert got == 2.0 + ref.step() % 4.0
        assert got in (2.0, 3.0, 4.0, 5.0)
    assert prelude.H.random.range(5, 2) == 5.0


# ---------------------------------------------------------------- 純関数（expr.md §4.1）


def test_round_is_half_to_even(prelude) -> None:
    assert [prelude.F.round(x) for x in (0.5, 1.5, 2.5, -0.5, -1.5, 2.4, 2.6)] == [
        0.0,
        2.0,
        2.0,
        -0.0,
        -2.0,
        2.0,
        3.0,
    ]


def test_floor_ceil_len_return_floats(prelude, prelude_and_runtime) -> None:
    _, runtime = prelude_and_runtime
    for value in (prelude.F.floor(2.7), prelude.F.ceil(2.1), prelude.F.len("あいう")):
        assert isinstance(value, float), value
    assert prelude.F.len("あいう") == 3.0
    assert prelude.F.len(runtime.table_from([1.0, 2.0], recursive=True)) == 2.0


def test_str_sub_contains(prelude, prelude_and_runtime) -> None:
    _, runtime = prelude_and_runtime
    assert prelude.F.str(3.0) == "3"
    assert prelude.F.str(0.1) == "0.1"
    assert prelude.F.str(True) == "true"
    assert prelude.F.str("s") == "s"
    assert prelude.F.sub("あいうえお", 1, 3) == "いうえ"
    assert prelude.F.sub("あいうえお", 3, 10) == "えお"
    assert prelude.F.sub("abc", -1, 2) == "a"
    assert prelude.F.sub("abc", 5, 1) == ""
    assert prelude.F.sub("abc", 0, 0) == ""
    items = runtime.table_from([1.0, 2.0, 3.0], recursive=True)
    assert prelude.F.contains(items, 2.0) is True
    assert prelude.F.contains(items, 4.0) is False
    assert prelude.F.clamp(5.0, 0.0, 3.0) == 3.0
    assert prelude.F.atan2(1.0, 0.0) == math.atan2(1.0, 0.0)


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("a", "a", 0.0),
        ("", "", 0.0),
        ("あいう", "あいう", 0.0),
        ("a", "b", -1.0),
        ("B", "a", -1.0),  # コードポイント順（ロケールの照合順なら a が先）
        ("", "a", -1.0),
        ("ab", "abc", -1.0),  # 前方一致は短い方が先
        ("z", "あ", -1.0),  # ASCII は非 ASCII より先
        ("あ", "い", -1.0),
        ("ｱ", "😀", -1.0),  # U+FF71 < U+1F600（UTF-16 のコード単位順なら 0xFF71 > 0xD83D で逆）
        ("�", "\U00010000", -1.0),
        ("a\x00b", "a\x00c", -1.0),  # NUL を含んでも途中で打ち切らない
    ],
)
def test_cmp_orders_strings_by_code_point(prelude, a: str, b: str, expected: float) -> None:
    """expr.md §4.1（v2.1）: `cmp(a, b)` はコードポイント順で -1 / 0 / 1（浮動小数）。"""
    got = prelude.F.cmp(a, b)
    assert got == expected and isinstance(got, float), (a, b, got)
    assert prelude.F.cmp(b, a) == -expected, (b, a)


def test_index_and_effects(prelude, prelude_and_runtime) -> None:
    from lupa import lua54

    _, runtime = prelude_and_runtime
    items = runtime.table_from([10.0, 20.0, 30.0], recursive=True)
    assert prelude.AT(items, 1.0) == 20.0
    assert prelude.AT(items, 1.9) == 20.0
    prelude.SETAT(items, 0.0, 5.0)
    assert prelude.AT(items, 0.0) == 5.0
    prelude.E.push(items, 40.0)
    assert prelude.F.len(items) == 4.0
    prelude.E.removeAt(items, 0.0)
    assert prelude.AT(items, 0.0) == 20.0
    with pytest.raises(lua54.LuaError):
        prelude.AT(items, 3.0)
    with pytest.raises(lua54.LuaError):
        prelude.AT(items, -1.0)
    prelude.E.clear(items)
    assert prelude.F.len(items) == 0.0


# ---------------------------------------------------------------- ホスト能力


def test_color_validation(prelude) -> None:
    from lupa import lua54

    prelude.H.canvas.clear("#000")
    prelude.H.canvas.ink("#A0b0C0")
    for bad in ("red", "#12", "#12345", "#ggg", "000"):
        with pytest.raises(lua54.LuaError):
            prelude.H.canvas.clear(bad)


def test_button_fires_on_release_inside_the_rect(prelude, prelude_and_runtime) -> None:
    _, runtime = prelude_and_runtime

    def inputs(events: list[dict]) -> object:
        return runtime.table_from(
            {"events": events, "keys": {}, "pointer": {"x": 0.0, "y": 0.0, "down": False}},
            recursive=True,
        )

    prelude.prepare_inputs(inputs([{"kind": "pointer", "x": 10.0, "y": 10.0, "down": True}]))
    assert prelude.H.ui.button("A", 0.0, 0.0, 20.0, 20.0) is False
    prelude.prepare_inputs(inputs([{"kind": "pointer", "x": 10.0, "y": 10.0, "down": False}]))
    assert prelude.H.ui.button("A", 0.0, 0.0, 20.0, 20.0) is True
    assert prelude.H.ui.button("B", 30.0, 30.0, 20.0, 20.0) is False
    # 押下なしの「離し」は発火しない
    prelude.prepare_inputs(inputs([{"kind": "pointer", "x": 10.0, "y": 10.0, "down": False}]))
    assert prelude.H.ui.button("A", 0.0, 0.0, 20.0, 20.0) is False


def test_key_and_pressed(prelude, prelude_and_runtime) -> None:
    _, runtime = prelude_and_runtime
    prelude.prepare_inputs(
        runtime.table_from(
            {
                "events": [{"kind": "key", "name": "Space", "down": True}],
                "keys": {"Space": True, "ArrowLeft": True},
                "pointer": {"x": 3.0, "y": 4.0, "down": True},
            },
            recursive=True,
        )
    )
    assert prelude.H.input.key("ArrowLeft") is True
    assert prelude.H.input.key("KeyA") is False
    assert prelude.H.input.pressed("Space") is True
    assert prelude.H.input.pressed("ArrowLeft") is False
    p = prelude.H.input.pointer()
    assert (p.f_0, p.f_1, p.f_2) == (3.0, 4.0, True)
