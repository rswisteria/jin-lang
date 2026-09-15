"""ランタイム部の単体: 数値の書式と strtod / JSON の読み書き / 文字列の純関数 / PCG32 / 三角関数（jil.md §6.4）。

数値の書式は `tests/fixtures/numbers.jsonl`（`scripts/generate_number_fixture.py`。Lua 経路の `NUMSTR` が正）と
突き合わせ、`NUMSTR` → strtod が bit 一致することも同じ fixture で見る。
"""

from __future__ import annotations

import json
import math
import random
import struct

import pytest

from tests.conftest import REPO_ROOT

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "numbers.jsonl"


def rows() -> list[dict]:
    return [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()]


def same_float(a: float, b: float) -> bool:
    if math.isnan(a) or math.isnan(b):
        return math.isnan(a) and math.isnan(b)
    return a == b and math.copysign(1.0, a) == math.copysign(1.0, b)


# ---------------------------------------------------------------- 数値の書式（runtime.md §6・jil.md §6.4）


def test_the_shared_fixture_has_the_700_values_and_the_boundaries() -> None:
    values = [float.fromhex(r["hex"]) for r in rows()]
    assert len(values) >= 700 + 26
    assert 5e-324 in values and 2.2250738585072014e-308 in values and 1e23 in values
    assert 2.0**-1022 in values and 2.0**1023 in values and math.nextafter(1.0, 2.0) in values


def test_numstr_matches_the_lua_path_on_every_fixture_row(probe) -> None:
    for row in rows():
        x = float.fromhex(row["hex"])
        assert probe.numstr(x) == row["str"], row


def test_numstr_then_strtod_is_the_identity_on_every_fixture_row(probe) -> None:
    for row in rows():
        x = float.fromhex(row["hex"])
        back = probe.strtod(row["str"])
        # -0.0 の書式は "0"（整数の経路）なので符号は戻らない
        assert same_float(back, x) or (x == 0 and back == 0), row


def test_the_rows_that_differ_from_repr_are_exactly_powers_of_two() -> None:
    """Lua の `%.pe` 探索は往復の区間が非対称な 2 の冪で repr より 1 桁長い（既知の差）。それ以外は repr と同じ。"""
    for row in rows():
        if row["str"] == row["repr"]:
            continue
        x = abs(float.fromhex(row["hex"]))
        assert x == 2.0 ** math.floor(math.log2(x)), row
        assert len(row["str"]) == len(row["repr"]) + 1, row


def test_numstr_specials(probe) -> None:
    assert probe.numstr(float("nan")) == "NaN"
    assert probe.numstr(float("inf")) == "Infinity"
    assert probe.numstr(float("-inf")) == "-Infinity"
    assert probe.numstr(-0.0) == "0"
    assert probe.numstr(2.0**53) == "9007199254740992.0"
    assert probe.numstr(0.1 + 0.2) == "0.30000000000000004"


# ---------------------------------------------------------------- strtod（正確な丸め）


@pytest.mark.parametrize(
    "text",
    [
        "0.1",
        "1e23",
        "8.41e21",
        "9007199254740993",
        "9007199254740992.5",
        "2.2250738585072011e-308",
        "4.9e-324",
        "2.4703282292062327e-324",
        "2.4703282292062328e-324",
        "1.7976931348623158e308",
        "1.7976931348623159e308",
        "1e400",
        "1e-400",
        "123456789012345678901234567890",
        "0.000000000000000000000000000000000000001",
        "1" + "0" * 400,
        "0." + "0" * 400 + "1",
        "-0.0",
        "3.14159265358979323846264338327950288419716939937510582097494459",
    ],
)
def test_strtod_rounds_like_python(probe, text: str) -> None:
    assert same_float(probe.strtod(text), float(text))


def test_strtod_matches_python_on_random_digit_strings(probe) -> None:
    rng = random.Random(20260915)
    for _ in range(300):
        digits = "".join(rng.choice("0123456789") for _ in range(rng.randint(1, 40)))
        text = f"{digits[: rng.randint(1, len(digits))]}.{digits}e{rng.randint(-330, 310)}"
        assert same_float(probe.strtod(text), float(text)), text
    for _ in range(300):
        bits = rng.getrandbits(64)
        x = struct.unpack("<d", struct.pack("<Q", bits))[0]
        if not math.isfinite(x):
            continue
        assert same_float(probe.strtod(repr(x)), x), x


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("12", 12.0),
        ("-0", 0.0),
        ("-0.0", 0.0),
        ("1e5", 100000.0),
        ("1.5E-3", 0.0015),
        ("abc", 0.0),
        ("1.", 0.0),
        (".5", 0.0),
        (" 1", 0.0),
        ("0x10", 0.0),
        ("1e400", 0.0),
        ("inf", 0.0),
        ("12e", 0.0),
        ("--1", 0.0),
        ("", 0.0),
    ],
)
def test_num_accepts_only_the_forms_of_expr_md(probe, text: str, expected: float) -> None:
    got = probe.num(text)
    assert got == expected and math.copysign(1.0, got) == 1.0


# ---------------------------------------------------------------- JSON の書き手と読み手


@pytest.mark.parametrize(
    "text",
    [
        "",
        "plain",
        'quote " and \\ backslash',
        "tab\tnl\ncr\r",
        "\x00\x1f\x7f",
        "日本語 🎮",
        "\b\f/",
        " ",
    ],
)
def test_js_escapes_like_the_prelude(probe, text: str) -> None:
    escaped = probe.js(text)
    assert json.loads(escaped) == text
    # \u00xx は小文字 4 桁・/ は逃がさない（プレリュードの JS）
    assert "\\/" not in escaped
    if "\x1f" in text:
        assert "\\u001f" in escaped


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        0,
        -1.5,
        1e21,
        "s",
        '日本 "\\',
        "😀",
        [],
        {},
        [1, "a", None, [True]],
        {
            "events": [{"kind": "key", "name": "ArrowLeft", "down": True}],
            "keys": {"ArrowLeft": True},
            "pointer": {"x": 50.5, "y": 9, "down": False},
        },
        {"seed": 7, "manifest": {"storage": {"runs": "2"}, "stage": {"width": 64}}},
    ],
)
def test_the_json_reader_round_trips(probe, value) -> None:
    assert probe.json_roundtrip(value) == value


def test_the_json_reader_restores_surrogate_pairs_and_escapes(probe) -> None:
    text = json.dumps({"t": '😀 é \\ " \n'})  # ensure_ascii の \uXXXX
    assert probe.json_roundtrip(json.loads(text)) == {"t": '😀 é \\ " \n'}


# ---------------------------------------------------------------- 文字列の純関数


def test_len_counts_codepoints(probe) -> None:
    assert probe.length("") == 0 and probe.length("abc") == 3 and probe.length("日本😀") == 3


@pytest.mark.parametrize(
    ("text", "i", "n", "expected"),
    [
        ("hello", 1, 3, "ell"),
        ("hello", 0, 99, "hello"),
        ("hello", -2, 3, "h"),
        ("hello", 5, 1, ""),
        ("hello", 2, 0, ""),
        ("日本😀x", 1, 2, "本😀"),
        ("hello", 1.9, 2.9, "el"),
        ("hello", float("nan"), 2, ""),
        ("hello", 1, float("inf"), "ello"),
    ],
)
def test_sub_cuts_at_codepoints_like_the_prelude(probe, text, i, n, expected) -> None:
    assert probe.sub(text, i, n) == expected


def test_cmp_is_byte_order(probe) -> None:
    assert probe.cmp("a", "a") == 0 and probe.cmp("B", "a") == -1 and probe.cmp("ｱ", "😀") == -1
    assert probe.cmp("ab", "a") == 1 and probe.cmp("", "a") == -1


# ---------------------------------------------------------------- 算術の写し（Lua の math.min / max / floor / %）


def test_min_max_floor_follow_lua_not_ieee(probe) -> None:
    nan = float("nan")
    assert math.isnan(probe.call("t_min", nan, 1.0)) and probe.call("t_min", 1.0, nan) == 1.0
    assert math.copysign(1.0, probe.call("t_min", 0.0, -0.0)) == 1.0  # b < a でないので a
    assert math.copysign(1.0, probe.call("t_floor", -0.0)) == 1.0  # math.floor(-0.0) + 0.0
    assert probe.call("t_round", 2.5) == 2.0 and probe.call("t_round", 3.5) == 4.0
    assert probe.call("t_round", -2.5) == -2.0 and probe.call("t_lmod", -7.0, 3.0) == 2.0


# ---------------------------------------------------------------- PCG32（abilities.md §6）

_MASK64 = (1 << 64) - 1


class Pcg32:
    """参照実装（`packages/jin-wasm/tests/test_prelude.py` と同じ）。"""

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
def test_pcg32_matches_the_reference(probe, seed: int) -> None:
    probe.call("t_rng_seed", seed)
    ref = Pcg32(seed)
    for _ in range(50):
        assert probe.call("t_rng_step") & 0xFFFFFFFF == ref.step()


# ---------------------------------------------------------------- sin / cos / atan2（fdlibm）


def ulps(a: float, b: float) -> int:
    if same_float(a, b):
        return 0
    if not (math.isfinite(a) and math.isfinite(b)):
        return 10**9
    ia = struct.unpack("<q", struct.pack("<d", a))[0]
    ib = struct.unpack("<q", struct.pack("<d", b))[0]
    return abs(ia - ib)


def test_sin_cos_atan2_are_within_one_ulp_of_libm(probe) -> None:
    """fdlibm の移植: |x| < 2^19·π/2 で 1 ulp 以内（バイト一致は保証しない・jil.md §6.4）。"""
    rng = random.Random(3)
    xs = [
        0.0,
        -0.0,
        1e-300,
        0.5,
        1.0,
        math.pi / 4,
        math.pi / 2,
        math.pi,
        2 * math.pi,
        3.0,
        -7.5,
        100.0,
        1e5,
        8e5,
    ]
    xs += [rng.uniform(-1000, 1000) for _ in range(500)] + [rng.uniform(-1, 1) for _ in range(200)]
    for x in xs:
        assert ulps(probe.call("t_sin", x), math.sin(x)) <= 1, x
        assert ulps(probe.call("t_cos", x), math.cos(x)) <= 1, x
    assert math.isnan(probe.call("t_sin", float("inf"))) and math.isnan(
        probe.call("t_cos", float("nan"))
    )
    pairs = [
        (0.0, 0.0),
        (0.0, -0.0),
        (-0.0, -1.0),
        (1.0, 0.0),
        (-1.0, 0.0),
        (1.0, 1.0),
        (3.0, -4.0),
        (-3.0, -4.0),
    ]
    pairs += [(math.inf, math.inf), (math.inf, -math.inf), (1.0, math.inf), (1e-300, 1e300)]
    pairs += [(rng.uniform(-10, 10), rng.uniform(-10, 10)) for _ in range(500)]
    for y, x in pairs:
        assert ulps(probe.call("t_atan2", y, x), math.atan2(y, x)) <= 1, (y, x)
    assert math.isnan(probe.call("t_atan2", float("nan"), 1.0))
