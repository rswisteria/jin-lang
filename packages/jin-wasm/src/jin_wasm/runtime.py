"""lupa（`lupa.lua54`）で JIL を走らせるホスト（runtime.md §8 のヘッドレス実行）。

## これは任意コード実行ではない

JIL は `require` / `load` / `os` / `io` を持たない Lua の静的サブセット（jil.md §2）で、
Lua からホスト（Python）を呼ぶ口も無い（runtime.md §1）。それでも多層防御として、
JIL を読む**前**に次を行う（probe §B.2 の実測に基づく）:

- `LuaRuntime(register_eval=False, register_builtins=False, unpack_returned_tuples=True)`。
  `register_eval=False` だけでは `python.builtins`（Python の `open` そのもの）が残る
- `globals().python = None` で `python` テーブル自体を消す
- `load` / `loadstring` / `dofile` / `loadfile` / `require` / `package` / `os` / `io` / `debug` /
  `collectgarbage` を `None` にし、`string.dump` も消す
- 命令数の上限（`INSTRUCTION_BUDGET`）を `debug.sethook` の count hook で掛ける。hook は
  `debug` を消した後も生きる（probe_lupa2.py・2026-09-13 実測）。`arm` はこのモジュールだけが
  握り、Lua のグローバルには置かない。boot と毎 tick の前に掛け直す。上限を超えると
  `{code = "budget"}` がスケジューラの `pcall` に捕まり、`error` 行 + `done = true` になる。
  JSON 直列化の途中で超えたときだけ `LuaError` としてここまで届くので `RunError` にする

`jin_adk.runtime` と違い、`sys.path` も `importlib` も触らない。

    guard: sandboxed_runtime -> lua54.LuaRuntime
    guard: sandboxed_runtime -> setattr(globals_,name,None)
    guard: _arm -> self._arm_fn(self._budget)
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from lupa import lua54

from jin_wasm.jil import HOST_ENTRY_POINTS

#: JIL を読む前に Lua のグローバルから消す名前（runtime.md §8 / probe §B.2）。
SANDBOX_REMOVED: tuple[str, ...] = (
    "load",
    "loadstring",
    "dofile",
    "loadfile",
    "require",
    "package",
    "os",
    "io",
    "debug",
    "collectgarbage",
)

#: 1 回の `boot` / `tick` で実行してよい Lua 命令数の上限。
#: 根拠: examples-v2 の 1 tick は 1 万命令に満たない（paddle で実測 ≈ 2,000）。無限ループの
#: `while true do end` を CI で数十 ms で止められる値として 10^7 に置く（runtime.md §8）。
INSTRUCTION_BUDGET = 10_000_000

_SETUP = """
local sethook = debug.sethook
return function(limit)
  sethook(function()
    error({ code = "budget", message = "命令数の上限 " .. limit .. " を超えました（無限ループ？）" }, 0)
  end, "", limit)
end
"""


class RunError(Exception):
    """JIL の読み込みや実行が続けられない（利用者向けの文で伝える）。"""


def sandboxed_runtime() -> tuple[Any, Callable[[int], None]]:
    """サンドボックス化した `lupa.lua54.LuaRuntime` と、命令数の上限を掛ける関数を返す。

    guard: sandboxed_runtime -> lua54.LuaRuntime
    guard: sandboxed_runtime -> setattr(globals_,name,None)
    """
    runtime = lua54.LuaRuntime(
        register_eval=False, register_builtins=False, unpack_returned_tuples=True
    )
    globals_ = runtime.globals()
    globals_.python = None
    arm = runtime.execute(_SETUP)
    for name in SANDBOX_REMOVED:
        setattr(globals_, name, None)
    runtime.execute("string.dump = nil")
    return runtime, arm


class LuaHost:
    """1 本の JIL を読み、`boot` / `tick` だけを呼ぶ（runtime.md §1）。

    `tick` の戻り値（JSON 文字列）は `json.loads` して辞書で返す。Lua のテーブルは境界を越えない。
    """

    def __init__(self, jil: str, *, budget: int = INSTRUCTION_BUDGET) -> None:
        self._budget = budget
        self._runtime, self._arm_fn = sandboxed_runtime()
        self._arm()
        try:
            self._runtime.execute(jil)
        except lua54.LuaError as exc:
            raise RunError(f"JIL を読めません: {_lua_message(exc)}") from exc
        globals_ = self._runtime.globals()
        for name in HOST_ENTRY_POINTS:
            if lua54.lua_type(getattr(globals_, name)) != "function":
                raise RunError(f"JIL に関数 {name} がありません")
        self._boot = globals_.boot
        self._tick = globals_.tick

    def _arm(self) -> None:
        """命令数の上限を掛け直す（boot と毎 tick の前）。

        guard: _arm -> self._arm_fn(self._budget)
        """
        self._arm_fn(self._budget)

    def boot(self, seed: int, manifest: dict[str, Any]) -> None:
        self._arm()
        try:
            self._boot(int(seed), self._runtime.table_from(manifest, recursive=True))
        except lua54.LuaError as exc:
            raise RunError(f"boot に失敗しました: {_lua_message(exc)}") from exc

    def tick(self, t: int, inputs: dict[str, Any]) -> dict[str, Any]:
        self._arm()
        try:
            text = self._tick(int(t), self._runtime.table_from(inputs, recursive=True))
        except lua54.LuaError as exc:
            raise RunError(f"tick {t} に失敗しました: {_lua_message(exc)}") from exc
        if not isinstance(text, str):
            raise RunError(f"tick {t} の戻り値が文字列ではありません（{type(text).__name__}）")
        try:
            return json.loads(text)
        except ValueError as exc:
            raise RunError(f"tick {t} の戻り値を JSON として読めません: {exc}") from exc


def _lua_message(exc: BaseException) -> str:
    """`error({code=..., message=...})` の表と文字列の両方を 1 行にする。"""
    value = exc.args[0] if exc.args else exc
    if lua54.lua_type(value) == "table":
        message = getattr(value, "message", None) or getattr(value, "code", None)
        if message is not None:
            return str(message)
    return str(value).split("\n", 1)[0]


# ---------------------------------------------------------------- 入力の再構成（runtime.md §7）


@dataclass(slots=True)
class InputState:
    """録画のイベントから押下状態を再構成する（ログには載せない・§7）。"""

    keys: dict[str, bool] = field(default_factory=dict)
    x: float = 0.0
    y: float = 0.0
    down: bool = False

    def apply(self, events: Iterable[dict[str, Any]]) -> dict[str, Any]:
        """`tick(t, inputs)` の `inputs`（§1.1）を返す。`events` はこの tick のイベント（発生順）。"""
        rows: list[dict[str, Any]] = []
        for ev in events:
            kind = ev.get("kind")
            if kind == "key":
                name = str(ev["name"])
                down = bool(ev.get("down", False))
                if down:
                    self.keys[name] = True
                else:
                    self.keys.pop(name, None)
                rows.append({"kind": "key", "name": name, "down": down})
            elif kind == "pointer":
                self.x = float(ev.get("x", self.x))
                self.y = float(ev.get("y", self.y))
                self.down = bool(ev.get("down", self.down))
                rows.append({"kind": "pointer", "x": self.x, "y": self.y, "down": self.down})
        return {
            "events": rows,
            "keys": dict(self.keys),
            "pointer": {"x": self.x, "y": self.y, "down": self.down},
        }


# ---------------------------------------------------------------- ヘッドレス実行


@dataclass(slots=True)
class HeadlessResult:
    #: トレース行（`debug` のときだけ。runtime.md §5）。
    rows: list[dict[str, Any]]
    #: tick ごとの表示リスト `{"tick", "ops", "audio"}`（`frame` 行と同じ内容。トレース無しでも出る）。
    frames: list[dict[str, Any]]
    #: 最後の tick の公開 state（`{"Play.score": 3}`）。
    public: dict[str, Any]
    #: 実行時エラーの文（無ければ None）。
    error: str | None
    #: root が done になった tick（最後まで done にならなければ None）。
    done_tick: int | None
    #: 実際に走らせた tick 数。
    ticks: int


def run_headless(
    jil: str,
    manifest: dict[str, Any],
    *,
    seed: int,
    ticks: int,
    events: Iterable[dict[str, Any]] = (),
    on_row: Callable[[dict[str, Any]], None] | None = None,
    budget: int = INSTRUCTION_BUDGET,
) -> HeadlessResult:
    """`boot` → `tick(0..ticks-1)` を順に呼ぶ。root が done になったら（その tick を含めて）止める。

    `events` は `{tick, kind, ...}` の列（録画の本文。tick 昇順・同じ tick は発生順）。
    """
    by_tick: dict[int, list[dict[str, Any]]] = {}
    for ev in events:
        by_tick.setdefault(int(ev["tick"]), []).append(ev)
    host = LuaHost(jil, budget=budget)
    host.boot(seed, manifest)
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
        if result.get("error") is not None:
            error = str(result["error"])
        if result.get("done"):
            done_tick = t
            break
    return HeadlessResult(rows, frames, public, error, done_tick, ran)


__all__ = [
    "INSTRUCTION_BUDGET",
    "SANDBOX_REMOVED",
    "HeadlessResult",
    "InputState",
    "LuaHost",
    "RunError",
    "run_headless",
    "sandboxed_runtime",
]
