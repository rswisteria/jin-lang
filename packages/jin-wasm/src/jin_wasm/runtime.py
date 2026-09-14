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
  `debug` を消した後も生きる（probe §B.7 の実測）。**Lua の hook はスレッドごと**なので、
  ホストがメインスレッドに掛けるだけでは `wait` を含む手順（コルーチン）の無限ループを
  止められない（probe §B.8 / §A.10 の実測。Phase 2 の残存）。そこで JIL を読む前に
  `JIN_ARM()`（今のスレッドに掛け直す）と `JIN_HOOK(co)`（コルーチンに掛ける）の 2 つの
  グローバルを置き、プレリュードが `boot` / `tick` の先頭と毎 `coroutine.resume` の前に呼ぶ
  （`jil.HOST_HOOK_GLOBALS`）。JIL を読んだ後はその 2 つを消す（プレリュードは読み込み時に
  `local` へ捕まえているので、ホストが呼ぶ Lua の関数は引き続き `boot` / `tick` の 2 つだけ）。
  上限を超えると `{code = "budget"}` がスケジューラの `pcall` に捕まり、`error` 行 +
  `done = true` になる。JSON 直列化の途中で超えたときだけ `LuaError` としてここまで届くので
  `RunError` にする

`jin_adk.runtime` と違い、`sys.path` も `importlib` も触らない。

    guard: sandboxed_runtime -> lua54.LuaRuntime
    guard: sandboxed_runtime -> setattr(globals_,name,None)
    guard: sandboxed_runtime -> runtime.execute(_SETUP)
    guard: _drop_hook_globals -> setattr(globals_,name,None)
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from lupa import lua54

from jin_wasm.jil import HOST_ENTRY_POINTS, HOST_HOOK_GLOBALS
from jin_wasm.jinrec import clean_reply_text

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

#: `JIN_ARM` / `JIN_HOOK`（`jil.HOST_HOOK_GLOBALS`）を置くチャンク。`debug` を消す**前**に
#: `sethook` を捕まえる。`apps/player/src/host.ts` の `HOOK_SETUP` と同じ Lua（文言も同じ。
#: `error` 行の文がホストで変わるとパリティが割れる）。
_SETUP = """
local sethook = debug.sethook
return function(limit)
  local function over()
    error({ code = "budget", message = "命令数の上限 " .. limit .. " を超えました（無限ループ？）" }, 0)
  end
  JIN_ARM = function() sethook(over, "", limit) end
  JIN_HOOK = function(co) sethook(co, over, "", limit) end
end
"""


class RunError(Exception):
    """JIL の読み込みや実行が続けられない（利用者向けの文で伝える）。"""


def sandboxed_runtime(budget: int = INSTRUCTION_BUDGET) -> Any:
    """サンドボックス化した `lupa.lua54.LuaRuntime` を返す（`JIN_ARM` / `JIN_HOOK` を置いた状態）。

    JIL を読んだ後は `_drop_hook_globals` で 2 つを消す（`LuaHost` がそうする）。

    guard: sandboxed_runtime -> lua54.LuaRuntime
    guard: sandboxed_runtime -> setattr(globals_,name,None)
    guard: sandboxed_runtime -> runtime.execute(_SETUP)
    """
    runtime = lua54.LuaRuntime(
        register_eval=False, register_builtins=False, unpack_returned_tuples=True
    )
    globals_ = runtime.globals()
    globals_.python = None
    runtime.execute(_SETUP)(int(budget))
    for name in SANDBOX_REMOVED:
        setattr(globals_, name, None)
    runtime.execute("string.dump = nil")
    return runtime


def _drop_hook_globals(runtime: Any) -> None:
    """JIL を読んだ後に `JIN_ARM` / `JIN_HOOK` を消す（グローバルは `boot` / `tick` だけに戻る）。

    guard: _drop_hook_globals -> setattr(globals_,name,None)
    """
    globals_ = runtime.globals()
    for name in HOST_HOOK_GLOBALS:
        setattr(globals_, name, None)


class LuaHost:
    """1 本の JIL を読み、`boot` / `tick` だけを呼ぶ（runtime.md §1）。

    `tick` の戻り値（JSON 文字列）は `json.loads` して辞書で返す。Lua のテーブルは境界を越えない。
    """

    def __init__(self, jil: str, *, budget: int = INSTRUCTION_BUDGET) -> None:
        self._runtime = sandboxed_runtime(budget)
        try:
            self._runtime.execute(jil)
        except lua54.LuaError as exc:
            raise RunError(f"JIL を読めません: {_lua_message(exc)}") from exc
        finally:
            _drop_hook_globals(self._runtime)
        globals_ = self._runtime.globals()
        for name in HOST_ENTRY_POINTS:
            if lua54.lua_type(getattr(globals_, name)) != "function":
                raise RunError(f"JIL に関数 {name} がありません")
        self._boot = globals_.boot
        self._tick = globals_.tick

    def boot(self, seed: int, manifest: dict[str, Any]) -> None:
        try:
            self._boot(int(seed), self._runtime.table_from(manifest, recursive=True))
        except lua54.LuaError as exc:
            raise RunError(f"boot に失敗しました: {_lua_message(exc)}") from exc

    def tick(self, t: int, inputs: dict[str, Any]) -> dict[str, Any]:
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
            elif kind == "text":
                # 確定した文字列（abilities.md §3・v2.1）。押下状態には触らない。
                rows.append({"kind": "text", "text": str(ev["text"])})
            elif kind == "reply":
                # v1 の陣の答え（runtime.md §11・v2.1）。押下状態には触らない。プレリュードが配達する。
                rows.append({"kind": "reply", "id": int(ev["id"]), "text": str(ev["text"])})
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
    #: 記憶（`storage`・abilities.md §8）の最後の内容。boot に渡した写しに tick ごとの書き込みを順に反映したもの。
    storage: dict[str, str] = field(default_factory=dict)
    #: v1 の陣の答え（runtime.md §11）。`answer` が返した文字列を配達した tick の `reply` イベント
    #: `{"tick", "kind": "reply", "id", "text"}` の列（`jin run --record` がそのまま録画に書く）。
    replies: list[dict[str, Any]] = field(default_factory=list)


def apply_storage_writes(store: dict[str, str], result: dict[str, Any]) -> None:
    """tick の戻り値の `storage`（書き込みの一覧 `[[key, val], …]`）をホストの記憶へ順に反映する。"""
    for write in result.get("storage", []):
        if isinstance(write, list) and len(write) == 2 and all(isinstance(x, str) for x in write):
            store[write[0]] = write[1]


def run_headless(
    jil: str,
    manifest: dict[str, Any],
    *,
    seed: int,
    ticks: int,
    events: Iterable[dict[str, Any]] = (),
    storage: dict[str, str] | None = None,
    on_row: Callable[[dict[str, Any]], None] | None = None,
    budget: int = INSTRUCTION_BUDGET,
    answer: Callable[[dict[str, Any]], str] | None = None,
    replay: bool = False,
) -> HeadlessResult:
    """`boot` → `tick(0..ticks-1)` を順に呼ぶ。root が done になったら（その tick を含めて）止める。

    `events` は `{tick, kind, ...}` の列（録画の本文。tick 昇順・同じ tick は発生順）。
    `storage` は boot に渡す記憶の写し（録画のヘッダの `storage`。無ければ空）。

    `answer` は v1 の陣への問い（tick 結果の `asks`・runtime.md §11）に答える呼び出し可能
    （`{"id", "circle", "name", "prompt"}` → 答えの文字列）。実装は `jin_cli`（`jin_wasm` は `jin_adk` を
    知らない）。答えは次の tick の入力イベント `reply` として積み、`HeadlessResult.replies` にも残す。
    `replay` が真なら（`--input` の再生）問いには**答えない**（録画の `reply` 行が正）。`replay` でも
    `answer` でもないのに問いが出たら `RunError`。
    """
    by_tick: dict[int, list[dict[str, Any]]] = {}
    for ev in events:
        by_tick.setdefault(int(ev["tick"]), []).append(ev)
    store: dict[str, str] = dict(storage or {})
    host = LuaHost(jil, budget=budget)
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
        for reply in _answer_asks(result, t, answer=answer, replay=replay):
            by_tick.setdefault(t + 1, []).append(reply)
            replies.append(reply)
        if result.get("error") is not None:
            error = str(result["error"])
        if result.get("done"):
            done_tick = t
            break
    return HeadlessResult(rows, frames, public, error, done_tick, ran, store, replies)


def _answer_asks(
    result: dict[str, Any],
    t: int,
    *,
    answer: Callable[[dict[str, Any]], str] | None,
    replay: bool,
) -> list[dict[str, Any]]:
    """tick 結果の `asks` を順に `answer` へ渡し、次の tick に積む `reply` イベントを返す（runtime.md §11）。"""
    asks = result.get("asks", [])
    if not asks or replay:
        return []
    if answer is None:
        raise RunError(
            "v1 の陣への問い（agent）に答えるホストがありません（jin run は jin_cli が答えます。"
            "録画の再生なら replay=True）"
        )
    replies: list[dict[str, Any]] = []
    for ask in asks:
        if not isinstance(ask, dict) or not isinstance(ask.get("id"), (int, float)):
            continue
        text = clean_reply_text(str(answer(ask)))
        replies.append({"tick": t + 1, "kind": "reply", "id": int(ask["id"]), "text": text})
    return replies


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
