"""wasmtime でのヘッドレス実行（`jin run --target wasm-gc`・jil.md §6.7）。

`jin_wasm.runtime.run_headless` と同じ引数・同じ `HeadlessResult` を返す。ホストが呼ぶ export は
`input(n)` / `boot(n)` / `tick(n)` の 3 つで、引数は `{"seed", "manifest"}` / `{"t", "inputs"}` の JSON
（UTF-8）を線形メモリに書いて渡し、`tick` の結果 `(先頭, 長さ)` を線形メモリから読む（jil.md §6.2）。

module は import を持たず、線形メモリの外へ出る手段が無い（lupa 側の「消すグローバル」に相当する
手続きは無い）。`jin run --target wasm-gc` が任意コードを実行しないのは Lua 経路と同じ。

命令数の上限は module の中のカウンタ（jil.md §6.6。生成部がループの戻り辺と手順の呼び出しに埋める。値 10^7 と
`error` の文は Lua 経路の `INSTRUCTION_BUDGET` / `_SETUP` と同じ）で掛かり、両経路が同じ tick に `error` 行を出す。
wasmtime の fuel（`consume_fuel`・`FUEL_PER_CALL`）は**保険**で、カウンタが 10^7 回減る前に尽きない大きさに置く
（module が止まらないのは生成系のバグ・§6.2。ブラウザには fuel が無い）。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from typing import Any

from jin_wasm.runtime import HeadlessResult, InputState, answer_asks, apply_storage_writes
from wasmtime import Config, Engine, Instance, Module, Store, Trap

#: 1 回の `boot` / `tick` に許す wasmtime の fuel（おおよそ wasm 命令数）。module 内のカウンタ（10^7 回の
#: 戻り辺 / 呼び出し）が先に当たるよう、1 回の反復が 10^4 命令でも尽きない 10^11 に置く（保険。jil.md §6.6）。
FUEL_PER_CALL = 100_000_000_000

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

    def tick_raw(self, t: int, inputs: dict[str, Any]) -> bytes:
        """`tick` の結果を JSON のバイト列のまま返す（パリティのテストが Lua の文字列と突き合わせる）。"""
        returned = self._call(self._tick, {"t": int(t), "inputs": inputs}, f"tick {t}")
        try:
            ptr, length = (int(v) for v in returned)
        except (TypeError, ValueError) as exc:
            raise WasmGcRunError(
                f"tick {t} の戻り値が (先頭, 長さ) ではありません: {returned!r}"
            ) from exc
        return bytes(self.memory.read(self.store, ptr, ptr + length))

    def tick(self, t: int, inputs: dict[str, Any]) -> dict[str, Any]:
        raw = self.tick_raw(t, inputs)
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise WasmGcRunError(f"tick {t} の戻り値を JSON として読めません: {exc}") from exc


def _trap_message(exc: Trap) -> str:
    text = str(exc).strip().splitlines()
    last = text[-1].strip() if text else str(exc)
    if "fuel" in last:
        return (
            f"wasmtime の fuel（{FUEL_PER_CALL} / 回）が尽きました。module 内のカウンタ（jil.md §6.6）が"
            "先に止めるはずなので、生成系の不備です"
        )
    if "unreachable" in last or "trap" in last:
        return "生成した module が trap しました（生成系の不備・jil.md §6.2）: " + last
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

    `answer` / `replay`（v1 の陣への問い・runtime.md §11）は Lua 経路と同じ `answer_asks` で次の tick の
    `reply` に積む（`jin_wasm` の実装を共有し、再実装しない）。
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
    replies: list[dict[str, Any]] = []
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
        for reply in answer_asks(result, t, answer=answer, replay=replay):
            by_tick.setdefault(t + 1, []).append(reply)
            replies.append(reply)
        if result.get("error") is not None:
            error = str(result["error"])
        if result.get("done"):
            done_tick = t
            break
    return HeadlessResult(rows, frames, public, error, done_tick, ran, store, replies)


__all__ = ["EXPORTS", "FUEL_PER_CALL", "WasmGcHost", "WasmGcRunError", "run_headless_wasm"]
