"""wasmtime でのヘッドレス実行（`jin run --target wasm-gc`・jil.md §6.7）。

`jin_wasm.runtime.run_headless` と同じ引数・同じ `HeadlessResult` を返す。ホストが呼ぶ export は
`input(n)` / `boot(n)` / `tick(n)` の 3 つで、引数は `{"seed", "manifest"}` / `{"t", "inputs"}` の JSON
（UTF-8）を線形メモリに書いて渡し、`tick` の結果 `(先頭, 長さ)` を線形メモリから読む（jil.md §6.2）。

module は import を持たず、線形メモリの外へ出る手段が無い（lupa 側の「消すグローバル」に相当する
手続きは無い）。`jin run --target wasm-gc` が任意コードを実行しないのは Lua 経路と同じ。

命令数の上限は module の中のカウンタ（jil.md §6.6）で掛けるが、それは #74（Sub-Issue B）で入る。
それまでは wasmtime の fuel（`consume_fuel`・`FUEL_PER_CALL`）を boot / tick ごとに掛けて、無限ループの
module を止める（ブラウザには fuel が無い。`wasmgc-api-probe.md` A.3 / A.5）。#74 の後は保険に格下げする。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from typing import Any

from jin_wasm.runtime import HeadlessResult, InputState, apply_storage_writes
from wasmtime import Config, Engine, Instance, Module, Store, Trap

#: 1 回の `boot` / `tick` に許す wasmtime の fuel（おおよそ wasm 命令数）。Lua 経路の `INSTRUCTION_BUDGET`
#: （10^7 VM 命令）に対して十分に余裕を取り、#74 で module 内のカウンタが入るまでの保険。
FUEL_PER_CALL = 1_000_000_000

#: ホストが呼ぶ export（jil.md §6.2）。`memory` は読み書きの口。
EXPORTS = ("memory", "input", "boot", "tick")


class WasmGcRunError(Exception):
    """module が動かない・trap した・結果を読めない。利用者向けの文で伝える。"""


class WasmGcHost:
    """wasm-GC の module を 1 つ持ち、`boot` / `tick` を呼ぶ。"""

    def __init__(self, wasm: bytes, *, fuel: int = FUEL_PER_CALL) -> None:
        config = Config()
        config.consume_fuel = True
        self.engine = Engine(config)
        self.store = Store(self.engine)
        self.fuel = fuel
        try:
            module = Module(self.engine, wasm)
        except Exception as exc:  # wasmtime.WasmtimeError（検証に落ちた module）
            raise WasmGcRunError(f"game.wasm を読めません: {exc}") from exc
        if module.imports:
            raise WasmGcRunError(
                "game.wasm が import を持っています（module はホストを呼びません）"
            )
        # instantiate（data 区画の初期化・グローバルの初期化）も fuel を消費する
        self.store.set_fuel(self.fuel)
        self.instance = Instance(self.store, module, [])
        exports = self.instance.exports(self.store)
        missing = [name for name in EXPORTS if name not in exports]
        if missing:
            raise WasmGcRunError(f"game.wasm に export {missing} がありません（jil.md §6.2）")
        self.memory = exports["memory"]
        self._input = exports["input"]
        self._boot = exports["boot"]
        self._tick = exports["tick"]

    def _call(self, fn: Any, payload: dict[str, Any], label: str) -> Any:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        try:
            ptr = self._input(self.store, len(data))
            self.memory.write(self.store, data, ptr)
            self.store.set_fuel(self.fuel)
            return fn(self.store, len(data))
        except Trap as exc:
            raise WasmGcRunError(f"{label} に失敗しました: {_trap_message(exc)}") from exc

    def boot(self, seed: int, manifest: dict[str, Any]) -> None:
        self._call(self._boot, {"seed": int(seed), "manifest": manifest}, "boot")

    def tick(self, t: int, inputs: dict[str, Any]) -> dict[str, Any]:
        returned = self._call(self._tick, {"t": int(t), "inputs": inputs}, f"tick {t}")
        try:
            ptr, length = (int(v) for v in returned)
        except (TypeError, ValueError) as exc:
            raise WasmGcRunError(
                f"tick {t} の戻り値が (先頭, 長さ) ではありません: {returned!r}"
            ) from exc
        raw = bytes(self.memory.read(self.store, ptr, ptr + length))
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise WasmGcRunError(f"tick {t} の戻り値を JSON として読めません: {exc}") from exc


def _trap_message(exc: Trap) -> str:
    text = str(exc).strip().splitlines()
    last = text[-1].strip() if text else str(exc)
    if "fuel" in last:
        return (
            "命令数の上限を超えました（無限ループ？）。module 内のカウンタ（jil.md §6.6）は #74 で入り、"
            f"それまでは wasmtime の fuel（{FUEL_PER_CALL} / 回）で止めています"
        )
    if "unreachable" in last:
        return "生成した module が trap しました（未実装の経路: 非整数の数値書式は #74）: " + last
    return last


def run_headless_wasm(
    wasm: bytes,
    manifest: dict[str, Any],
    *,
    seed: int,
    ticks: int,
    events: Iterable[dict[str, Any]] = (),
    storage: dict[str, str] | None = None,
    on_row: Callable[[dict[str, Any]], None] | None = None,
    fuel: int = FUEL_PER_CALL,
    answer: Callable[[dict[str, Any]], str] | None = None,
    replay: bool = False,
) -> HeadlessResult:
    """`boot` → `tick(0..ticks-1)` を順に呼ぶ（`jin_wasm.runtime.run_headless` と同じ契約）。

    `answer` / `replay`（v1 の陣への問い・runtime.md §11）は #75 で配線する。A の module は問いを出さない
    （`agent` の sigil は `CodegenError`）ので、`asks` が出たら `WasmGcRunError`。
    """
    by_tick: dict[int, list[dict[str, Any]]] = {}
    for ev in events:
        by_tick.setdefault(int(ev["tick"]), []).append(ev)
    store: dict[str, str] = dict(storage or {})
    host = WasmGcHost(wasm, fuel=fuel)
    host.boot(seed, {**manifest, "storage": dict(store)})
    state = InputState()
    rows: list[dict[str, Any]] = []
    frames: list[dict[str, Any]] = []
    public: dict[str, Any] = {}
    error: str | None = None
    done_tick: int | None = None
    ran = 0
    for t in range(ticks):
        result = host.tick(t, state.apply(by_tick.get(t, [])))
        ran = t + 1
        for row in result.get("trace", []):
            rows.append(row)
            if on_row is not None:
                on_row(row)
        frames.append({"tick": t, "ops": result["ops"], "audio": result["audio"]})
        public = result.get("public", {})
        apply_storage_writes(store, result)
        if result.get("asks"):
            raise WasmGcRunError("v1 の陣への問い（agent）は --target wasm-gc では #75 で入ります")
        if result.get("error") is not None:
            error = str(result["error"])
        if result.get("done"):
            done_tick = t
            break
    return HeadlessResult(rows, frames, public, error, done_tick, ran, store, [])


__all__ = ["EXPORTS", "FUEL_PER_CALL", "WasmGcHost", "WasmGcRunError", "run_headless_wasm"]
