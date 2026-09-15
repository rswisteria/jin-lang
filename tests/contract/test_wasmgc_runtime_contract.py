"""パッケージ横断契約: wasm-GC のランタイム部（`runtime.wat`）がプレリュードと同じ網を張る（jil.md §6.4 / §6.6）。

- 能力カタログ（`jin_core.v2.abilities`）の全メンバと `PURE_FUNCTION_NAMES` の全部に対応する関数がある
  （`test_jil_contract.py::test_the_prelude_implements_every_catalog_namespace_and_pure_function` の wasm 版）
- 命令数の上限の文は Lua 経路（`jin_wasm.runtime._SETUP` / `INSTRUCTION_BUDGET`）と同じ
  （`test_player_contract.py::test_the_sandbox_matches_the_lupa_host` の 3 つ目）
- ランタイム部の文字列は `codegen.DATA_BASE` より下に閉じる
"""

from __future__ import annotations

import re

from jin_core.v2 import abilities
from jin_core.v2.expr import PURE_FUNCTION_NAMES
from jin_wasm.runtime import _SETUP, INSTRUCTION_BUDGET
from jin_wasmgc.assemble import runtime_source
from jin_wasmgc.codegen import DATA_BASE


def defined_functions(source: str) -> set[str]:
    return set(re.findall(r"\(func \$([A-Za-z0-9_]+)", source))


def test_the_runtime_implements_every_catalog_namespace_and_pure_function() -> None:
    funcs = defined_functions(runtime_source())
    for ns in abilities.NAMESPACES:
        for member in ns.members:
            assert f"h_{ns.name}_{member.name}" in funcs, (
                f"$h_{ns.name}_{member.name} が runtime.wat に無い"
            )
    for name in PURE_FUNCTION_NAMES:
        assert any(f == f"f_{name}" or f.startswith(f"f_{name}_") for f in funcs), (
            f"$f_{name} が runtime.wat に無い"
        )
    for effect in ("push", "remove", "clear"):
        for variant in ("f", "i", "r"):
            assert f"e_{effect}_{variant}" in funcs


def test_the_budget_value_and_message_match_the_lua_path() -> None:
    source = runtime_source()
    limit = re.search(r"\(global \$BUDGET \(mut i32\) \(i32\.const (\d+)\)\)", source)
    assert limit is not None and int(limit.group(1)) == INSTRUCTION_BUDGET
    assert (
        source.count(f"(global.set $BUDGET (i32.const {INSTRUCTION_BUDGET}))") == 2
    )  # boot と tick の先頭
    message = re.search(r'message = "(命令数の上限 )" \.\. limit \.\. "(.*?)"', _SETUP)
    assert message is not None
    expected = f"{message.group(1)}{INSTRUCTION_BUDGET}{message.group(2)}"
    encoded = "".join(
        chr(b) if 0x20 <= b < 0x7F and b not in (0x22, 0x5C) else f"\\{b:02x}"
        for b in expected.encode()
    )
    assert f'"{encoded}"' in source, "命令数の上限の文が Lua 経路（_SETUP）とずれた"


def test_the_runtime_strings_end_below_the_program_data_base() -> None:
    ends = [
        int(m.group(1)) + len(re.sub(r"\\[0-9a-f]{2}", "x", m.group(2)))
        for m in re.finditer(r'\(data \(i32\.const (\d+)\) "((?:[^"\\]|\\.)*)"\)', runtime_source())
    ]
    assert ends and max(ends) <= DATA_BASE
    assert f"[0, {DATA_BASE})" in runtime_source()


def test_the_shared_number_fixture_is_up_to_date() -> None:
    """`tests/fixtures/numbers.jsonl` は `scripts/generate_number_fixture.py` の出力そのもの（Lua 経路の NUMSTR が正）。"""
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "generate_number_fixture.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
        cwd=root,
    )
    assert result.returncode == 0, result.stderr
