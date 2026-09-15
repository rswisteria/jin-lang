"""`tests/fixtures/numbers.jsonl`（数値の書式の共有 fixture・jil.md §6.4）を作る。

Lua 経路（`prelude.lua` の `NUMSTR`）と wasm-GC 経路（`runtime.wat` の `$put_num`）が**同じ文字列**を出すことを
固定する fixture。行は `{"hex": float.hex(x), "str": <Lua の NUMSTR>, "repr": <Python の repr>}`。

- `str` が正（パリティの根拠は Lua 経路）。`repr` は runtime.md §6「Python の repr(float) と同じ配置」の突合用で、
  Lua の `%.{p}e` を p = 0…16 で試す探索は **2 の冪の一部**（往復の区間が非対称な値）で repr より 1 桁長い
  文字列を選ぶ。その行は `str != repr` になる（既知の差。`packages/jin-wasm/tests/test_prelude.py` が
  「差があるのは 2 の冪だけ」と固定する）
- 内容は `test_prelude.py` の 700 件（seed 20260913 の 500 + 200）+ `_SAMPLES` + 2 の冪の境界（2^k とその隣）+
  非正規化数 + 指数形の境目 + 17 桁が要る値

    uv run python scripts/generate_number_fixture.py           # 書く
    uv run python scripts/generate_number_fixture.py --check   # ずれていたら exit 1
"""

from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "numbers.jsonl"

#: `test_prelude.py` の `_SAMPLES` と同じ。
SAMPLES = [
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

#: 境界（2 の冪とその両隣・非正規化数・指数形の境目・17 桁が要る値）
BOUNDARIES = [
    5e-324,
    1e-320,
    2.225073858507201e-308,
    2.2250738585072014e-308,
    1e23,
    8.41e21,
    0.1 + 0.2,
    1e-5,
    0.0001,
    9.999999999999999e-5,
    1e16,
    9.999999999999998e15,
    1e15,
    123456789012345680.0,
    0.30000000000000004,
    5e-324 * 3,
    1.7976931348623157e308,
    -1e308,
]


def values() -> list[float]:
    out = list(SAMPLES)
    rng = random.Random(20260913)
    for _ in range(500):
        out.append(rng.uniform(-1, 1) * 10.0 ** rng.randint(-12, 24))
    for _ in range(200):
        out.append(rng.random())
    out.extend(BOUNDARIES)
    for k in range(-1074, 1024):
        x = 2.0**k
        out.extend([x, -x, math.nextafter(x, math.inf), math.nextafter(x, -math.inf)])
    return out


def expected_repr(x: float) -> str:
    if x == math.floor(x) and abs(x) < 2**53:
        return str(int(x)) if x != 0 else "0"
    return repr(x)


def render() -> str:
    sys.path.insert(0, str(REPO_ROOT / "packages" / "jin-wasm" / "tests"))
    from conftest import prelude_internals  # type: ignore[import-not-found]

    prelude, _ = prelude_internals()
    rows = []
    for x in values():
        rows.append(
            json.dumps(
                {"hex": x.hex(), "str": prelude.NUMSTR(x), "repr": expected_repr(x)},
                ensure_ascii=False,
            )
        )
    return "\n".join(rows) + "\n"


def main(argv: list[str]) -> int:
    text = render()
    if "--check" in argv:
        if not FIXTURE.exists() or FIXTURE.read_text(encoding="utf-8") != text:
            print(
                f"{FIXTURE} がずれています。uv run python scripts/generate_number_fixture.py",
                file=sys.stderr,
            )
            return 1
        return 0
    FIXTURE.write_text(text, encoding="utf-8")
    print(f"wrote {FIXTURE} ({text.count(chr(10))} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
