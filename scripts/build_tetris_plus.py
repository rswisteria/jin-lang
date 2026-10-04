"""`examples-v2/tetris-plus/tetris-plus.jin` を Jin の LSP(`jin lsp`・stdio)に編集操作を送って組み立てる。

didOpen で骨格を開き、`jin/applyOps`(v2 の 32 件・`docs/spec/v2/ops.md` §2)で陣・state・sigil・手順・ステップ・境界を
足していき、最後の応答の正準形の `text` を書き出す。`jin/save` は stdio では無効(ops.md §5.1)なので、ファイルは
このクライアントが書く。サンプルを直すときは、このスクリプトの op を直して再生成する(手で .jin を直さない)。

    uv run python scripts/build_tetris_plus.py           # 書き出す
    uv run python scripts/build_tetris_plus.py --check   # 組み立て直した結果がコミット済みのファイルと一致するか(exit 1 でずれ)
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT = REPO_ROOT / "examples-v2" / "tetris-plus" / "tetris-plus.jin"
CHECK = "--check" in sys.argv[1:]
URI = OUT.as_uri()


# ---- JSON-RPC over stdio -------------------------------------------------------------------------


class Client:
    def __init__(self) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "jin_lsp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE
        )
        self.next_id = 0
        self.diagnostics: list[Any] = []

    def _send(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.proc.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
        self.proc.stdin.flush()

    def _read(self) -> dict[str, Any]:
        length = 0
        while True:
            line = self.proc.stdout.readline()
            if line in (b"\r\n", b""):
                break
            if line.lower().startswith(b"content-length:"):
                length = int(line.split(b":")[1])
        return json.loads(self.proc.stdout.read(length))

    def notify(self, method: str, params: Any) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method: str, params: Any) -> Any:
        self.next_id += 1
        rid = self.next_id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        while True:
            msg = self._read()
            if msg.get("method") == "textDocument/publishDiagnostics":
                self.diagnostics = msg["params"]["diagnostics"]
                continue
            if msg.get("id") == rid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg["result"]


client = Client()
client.request("initialize", {"processId": None, "rootUri": None, "capabilities": {}})
client.notify("initialized", {})

SKELETON = {
    "$schema": "https://xtone.internal/jin/schemas/jin-v2.schema.json",
    "version": 2,
    "root": "Game",
    "stage": {"width": 64, "height": 64},
    "circles": [{"name": "Game", "flow": {"kind": "sequence", "steps": ["Play", "Result"]}}],
}
version = 1
client.notify(
    "textDocument/didOpen",
    {
        "textDocument": {
            "uri": URI,
            "languageId": "jin",
            "version": version,
            "text": json.dumps(SKELETON, indent=2),
        }
    },
)
text = ""


def apply(label: str, ops: list[dict[str, Any]]) -> dict[str, Any]:
    """1 まとまりの編集を送り、返った正準形の全文で didChange してサーバの文書を揃える。"""
    global version, text
    result = client.request("jin/applyOps", {"uri": URI, "ops": ops})
    if not result.get("ok"):
        raise SystemExit(f"[{label}] 失敗: {result['error']}")
    text = result["text"]
    version += 1
    client.notify(
        "textDocument/didChange",
        {"textDocument": {"uri": URI, "version": version}, "contentChanges": [{"text": text}]},
    )
    count = len(result.get("diagnostics", []))
    print(f"[{label}] ops {len(ops)} 件 → 診断 {count} 件", file=sys.stderr)
    return result


# ---- ステップの組み立て ------------------------------------------------------------------------------


def q(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def S(target: str, expr: str) -> dict[str, Any]:
    return {"do": "set", "target": target, "expr": expr}


def L(name: str, expr: str) -> dict[str, Any]:
    return {"do": "let", "name": name, "expr": expr}


def C(target: str, *args: str, into: str | None = None) -> dict[str, Any]:
    step: dict[str, Any] = {"do": "cast", "target": target}
    if args:
        step["args"] = list(args)
    if into:
        step["into"] = into
    return step


def IF(cond: str, then: list[Any], other: list[Any] | None = None) -> dict[str, Any]:
    step: dict[str, Any] = {"do": "if", "cond": cond, "then": then}
    if other:
        step["else"] = other
    return step


def COUNT(name: str, times: str, steps: list[Any]) -> dict[str, Any]:
    return {"do": "loop", "kind": "count", "name": name, "times": times, "steps": steps}


def WHILE(cond: str, steps: list[Any]) -> dict[str, Any]:
    return {"do": "loop", "kind": "while", "cond": cond, "steps": steps}


def RET(expr: str | None = None) -> dict[str, Any]:
    return {"do": "return", "expr": expr} if expr is not None else {"do": "return"}


BREAK = {"do": "break"}
FINISH = {"do": "finish"}


def p(name: str, type_: str) -> dict[str, str]:
    return {"name": name, "type": type_}


def rite(ci: int, name: str, steps: list[Any], params=None, returns=None) -> list[dict[str, Any]]:
    """手順を空で足し(addRite)、ステップを 1 つずつ足す(addStep)。手順の添字は足した順。"""
    value: dict[str, Any] = {"name": name, "steps": []}
    if params:
        value["params"] = params
    if returns:
        value["returns"] = returns
    ops = [{"op": "addRite", "pointer": f"/circles/{ci}/rites", "value": value}]
    index = rite.counts.setdefault(ci, 0)
    rite.counts[ci] += 1
    for step in steps:
        ops.append(
            {"op": "addStep", "pointer": f"/circles/{ci}/rites/{index}/steps", "value": step}
        )
    return ops


rite.counts = {}


def state(ci: int, name: str, type_: str, init: str, out: bool = False) -> dict[str, Any]:
    value: dict[str, Any] = {"name": name, "type": type_, "init": init}
    if out:
        value["out"] = True
    return {"op": "addState", "pointer": f"/circles/{ci}/state", "value": value}


def host(ci: int, name: str) -> dict[str, Any]:
    return {
        "op": "addSigil",
        "pointer": f"/circles/{ci}/sigils",
        "value": {"name": name, "kind": "host", "host": name},
    }


def summon(ci: int, name: str, circle: str, rite_name: str) -> dict[str, Any]:
    return {
        "op": "addSigil",
        "pointer": f"/circles/{ci}/sigils",
        "value": {"name": name, "kind": "summon", "circle": circle, "rite": rite_name},
    }


def on(ci: int, event: str, rite_name: str) -> dict[str, Any]:
    return {
        "op": "setOn",
        "pointer": f"/circles/{ci}/boundary/on",
        "value": {"event": event, "rite": rite_name},
    }


def guard(ci: int, assertion: str, message: str) -> dict[str, Any]:
    return {
        "op": "setGuard",
        "pointer": f"/circles/{ci}/boundary/guards",
        "value": {"assert": assertion, "message": message},
    }


# ---- 舞台・型紙・陣 ---------------------------------------------------------------------------------

GAME, PLAY, BOARD, RESULT = 0, 1, 2, 3
BEST_KEY = q("tetris-plus.best")

apply(
    "舞台と陣",
    [
        {
            "op": "setStage",
            "pointer": "/stage",
            "value": {"width": 200, "height": 176, "fps": 30, "seed": 7},
        },
        {
            "op": "addForm",
            "pointer": "/forms",
            "value": {
                "name": "Piece",
                "fields": [p("kind", "num"), p("rot", "num"), p("x", "num"), p("y", "num")],
            },
        },
        {"op": "addCircle", "pointer": "/circles", "value": {"name": "Play", "core": "begin"}},
        {"op": "addCircle", "pointer": "/circles", "value": {"name": "Board", "core": "idle"}},
        {"op": "addCircle", "pointer": "/circles", "value": {"name": "Result", "core": "show"}},
        {
            "op": "setFlow",
            "pointer": f"/circles/{GAME}",
            "value": {"kind": "loop", "steps": ["Play", "Result"], "exit": "Result.quit"},
        },
    ],
)

# ---- Board: 盤面・形・色と、その上の操作(summon だけで使う陣) ------------------------------------------

SHAPES = (
    "[0, 1, 1, 1, 2, 1, 3, 1, 2, 0, 2, 1, 2, 2, 2, 3, 0, 2, 1, 2, 2, 2, 3, 2, 1, 0, 1, 1, 1, 2, 1, 3, "
    "1, 0, 1, 1, 2, 0, 2, 1, 2, 1, 2, 2, 3, 1, 3, 2, 1, 2, 1, 3, 2, 2, 2, 3, 0, 1, 0, 2, 1, 1, 1, 2, "
    "0, 1, 1, 0, 1, 1, 2, 1, 1, 0, 1, 1, 1, 2, 2, 1, 0, 1, 1, 1, 1, 2, 2, 1, 0, 1, 1, 0, 1, 1, 1, 2, "
    "0, 1, 1, 0, 1, 1, 2, 0, 1, 0, 1, 1, 2, 1, 2, 2, 0, 2, 1, 1, 1, 2, 2, 1, 0, 0, 0, 1, 1, 1, 1, 2, "
    "0, 0, 1, 0, 1, 1, 2, 1, 1, 1, 1, 2, 2, 0, 2, 1, 0, 1, 1, 1, 1, 2, 2, 2, 0, 1, 0, 2, 1, 0, 1, 1, "
    "0, 0, 0, 1, 1, 1, 2, 1, 1, 0, 1, 1, 1, 2, 2, 0, 0, 1, 1, 1, 2, 1, 2, 2, 0, 2, 1, 0, 1, 1, 1, 2, "
    "0, 1, 1, 1, 2, 0, 2, 1, 1, 0, 1, 1, 1, 2, 2, 2, 0, 1, 0, 2, 1, 1, 2, 1, 0, 0, 1, 0, 1, 1, 1, 2]"
)
COLORS = (
    "["
    + ", ".join(
        q(c) for c in ["#4ce0e6", "#f2d541", "#b26ce8", "#5fd463", "#ef5b5b", "#4f7be8", "#f2953d"]
    )
    + "]"
)
CELL_X = "shapes[((kind * 4 + rot) * 4 + i) * 2]"
CELL_Y = "shapes[((kind * 4 + rot) * 4 + i) * 2 + 1]"

board_ops = [
    state(BOARD, "cells", "list<num>", "[]", out=True),
    state(BOARD, "shapes", "list<num>", SHAPES),
    state(BOARD, "colors", "list<str>", COLORS),
    host(BOARD, "canvas"),
]
board_ops += rite(BOARD, "idle", [])
board_ops += rite(
    BOARD, "reset", [C("clear", "cells"), COUNT("i", "200", [C("push", "cells", "0")])]
)
board_ops += rite(
    BOARD,
    "fits",
    [
        COUNT(
            "i",
            "4",
            [
                L("cx", f"x + {CELL_X}"),
                L("cy", f"y + {CELL_Y}"),
                IF("cx < 0 or cx >= 10 or cy >= 20", [RET("false")]),
                IF("cy >= 0 and cells[cy * 10 + cx] != 0", [RET("false")]),
            ],
        ),
        RET("true"),
    ],
    params=[p("kind", "num"), p("rot", "num"), p("x", "num"), p("y", "num")],
    returns="bool",
)
board_ops += rite(
    BOARD,
    "depth",
    [
        L("d", "0"),
        L("ok", "true"),
        WHILE(
            "ok",
            [C("fits", "kind", "rot", "x", "y + d + 1", into="ok"), IF("ok", [S("d", "d + 1")])],
        ),
        RET("d"),
    ],
    params=[p("kind", "num"), p("rot", "num"), p("x", "num"), p("y", "num")],
    returns="num",
)
board_ops += rite(
    BOARD,
    "place",
    [
        COUNT(
            "i",
            "4",
            [
                L("cx", f"x + {CELL_X}"),
                L("cy", f"y + {CELL_Y}"),
                IF("cy >= 0", [S("cells[cy * 10 + cx]", "kind + 1")]),
            ],
        ),
        L("n", "0"),
        C("sweep", into="n"),
        RET("n"),
    ],
    params=[p("kind", "num"), p("rot", "num"), p("x", "num"), p("y", "num")],
    returns="num",
)
board_ops += rite(
    BOARD,
    "sweep",
    [
        L("cleared", "0"),
        COUNT(
            "r",
            "20",
            [
                L("full", "true"),
                COUNT("c", "10", [IF("cells[r * 10 + c] == 0", [S("full", "false")])]),
                IF(
                    "full",
                    [
                        COUNT(
                            "k",
                            "r * 10",
                            [L("j", "r * 10 - 1 - k"), S("cells[j + 10]", "cells[j]")],
                        ),
                        COUNT("c2", "10", [S("cells[c2]", "0")]),
                        S("cleared", "cleared + 1"),
                    ],
                ),
            ],
        ),
        RET("cleared"),
    ],
    returns="num",
)
board_ops += rite(
    BOARD,
    "paint",
    [
        C("canvas.clear", q("#101418")),
        C("canvas.ink", q("#2a3340")),
        C("canvas.rect", "6", "6", "84", "164"),
        C("canvas.ink", q("#000")),
        C("canvas.rect", "8", "8", "80", "160"),
        COUNT(
            "i",
            "200",
            [
                IF(
                    "cells[i] != 0",
                    [
                        C("canvas.ink", "colors[cells[i] - 1]"),
                        C("canvas.rect", "8 + i % 10 * 8", "8 + floor(i / 10) * 8", "7", "7"),
                    ],
                )
            ],
        ),
    ],
)
board_ops += rite(
    BOARD,
    "piece",
    [
        IF("ghost", [C("canvas.ink", q("#3a4250"))], [C("canvas.ink", "colors[kind]")]),
        COUNT(
            "i",
            "4",
            [
                L("py", f"top + {CELL_Y} * size"),
                IF(
                    "py >= 8",
                    [C("canvas.rect", f"left + {CELL_X} * size", "py", "size - 1", "size - 1")],
                ),
            ],
        ),
    ],
    params=[
        p("kind", "num"),
        p("rot", "num"),
        p("left", "num"),
        p("top", "num"),
        p("size", "num"),
        p("ghost", "bool"),
    ],
)
board_ops.append(guard(BOARD, "len(cells) == 0 or len(cells) == 200", "盤面は 10 × 20"))
apply("Board", board_ops)

# ---- Play: 操作・7-bag・ホールド・ゴースト・レベル・ポーズ・ハイスコア ------------------------------------

play_ops = [
    state(PLAY, "piece", "Piece", "Piece{kind: 0, rot: 0, x: 3, y: 0}", out=True),
    state(PLAY, "queue", "list<num>", "[]"),
    state(PLAY, "hold", "num", "-1"),
    state(PLAY, "canHold", "bool", "true"),
    state(PLAY, "score", "num", "0", out=True),
    state(PLAY, "lines", "num", "0", out=True),
    state(PLAY, "level", "num", "0", out=True),
    state(PLAY, "best", "num", "0", out=True),
    state(PLAY, "record", "bool", "false", out=True),
    state(PLAY, "over", "bool", "false"),
    state(PLAY, "paused", "bool", "false"),
    state(PLAY, "soft", "num", "0"),
]
for name in ("canvas", "input", "audio", "random", "storage"):
    play_ops.append(host(PLAY, name))
play_ops += [
    summon(PLAY, "fits", "Board", "fits"),
    summon(PLAY, "depth", "Board", "depth"),
    summon(PLAY, "place", "Board", "place"),
    summon(PLAY, "wipe", "Board", "reset"),
    summon(PLAY, "drawBoard", "Board", "paint"),
    summon(PLAY, "drawPiece", "Board", "piece"),
]
FALL_TICKS = "max(2, 20 - level * 2)"
play_ops += rite(
    PLAY,
    "begin",
    [
        C("reset"),
        WHILE(
            "not over",
            [
                {"do": "wait", "ticks": FALL_TICKS},
                IF("paused", [{"do": "wait", "until": "not paused"}]),
                C("fall", "false"),
            ],
        ),
        IF(
            "score > best",
            [S("record", "true"), S("best", "score"), C("storage.set", BEST_KEY, "str(best)")],
        ),
        C("audio.tone", "110", "300"),
        FINISH,
    ],
)
play_ops += rite(
    PLAY,
    "reset",
    [
        S("score", "0"),
        S("lines", "0"),
        S("level", "0"),
        S("over", "false"),
        S("paused", "false"),
        S("record", "false"),
        S("hold", "-1"),
        S("canHold", "true"),
        S("best", f"num(storage.get({BEST_KEY}))"),
        C("wipe"),
        C("spawn"),
    ],
)
play_ops += rite(
    PLAY,
    "spawn",
    [
        IF(
            "len(queue) < 7",
            [
                L("bag", "[0, 1, 2, 3, 4, 5, 6]"),
                COUNT(
                    "i",
                    "7",
                    [
                        L("j", "random.range(0, len(bag) - 1)"),
                        C("push", "queue", "bag[j]"),
                        C("removeAt", "bag", "j"),
                    ],
                ),
            ],
        ),
        L("k", "queue[0]"),
        C("removeAt", "queue", "0"),
        C("enter", "k"),
    ],
)
play_ops += rite(
    PLAY,
    "enter",
    [
        S("piece", "Piece{kind: k, rot: 0, x: 3, y: 0}"),
        L("ok", "false"),
        C("fits", "k", "0", "3", "0", into="ok"),
        IF("not ok", [S("over", "true")]),
    ],
    params=[p("k", "num")],
)
play_ops += rite(
    PLAY,
    "fall",
    [
        L("ok", "false"),
        C("fits", "piece.kind", "piece.rot", "piece.x", "piece.y + 1", into="ok"),
        IF(
            "ok",
            [S("piece.y", "piece.y + 1"), IF("bySoft", [S("score", "score + 1")])],
            [C("lock")],
        ),
    ],
    params=[p("bySoft", "bool")],
)
play_ops += rite(
    PLAY,
    "lock",
    [
        L("n", "0"),
        C("place", "piece.kind", "piece.rot", "piece.x", "piece.y", into="n"),
        C("audio.tone", "220", "30"),
        IF(
            "n > 0",
            [
                L("bonus", "[0, 100, 300, 500, 800]"),
                S("score", "score + bonus[n] * (level + 1)"),
                S("lines", "lines + n"),
                S("level", "floor(lines / 10)"),
                C("audio.tone", "440 + n * 110", "80"),
            ],
        ),
        S("canHold", "true"),
        C("spawn"),
    ],
)


def MOVE(dx: str) -> list[dict[str, Any]]:
    return [
        C("fits", "piece.kind", "piece.rot", f"piece.x + {dx}", "piece.y", into="ok"),
        IF("ok", [S("piece.x", f"piece.x + {dx}")]),
    ]


play_ops += rite(
    PLAY,
    "control",
    [
        IF(
            'not over and (input.pressed("KeyP") or input.pressed("Escape"))',
            [S("paused", "not paused")],
        ),
        C("paint"),
        IF("paused or over", [RET()]),
        L("ok", "false"),
        IF('input.pressed("ArrowLeft")', MOVE("-1")),
        IF('input.pressed("ArrowRight")', MOVE("1")),
        IF('input.pressed("ArrowUp") or input.pressed("KeyZ")', [C("rotate", "1")]),
        IF('input.pressed("KeyX")', [C("rotate", "-1")]),
        IF('input.pressed("KeyC") or input.pressed("ShiftLeft")', [C("swap")]),
        IF(
            'input.key("ArrowDown")',
            [S("soft", "soft + 1"), IF("soft % 3 == 0", [C("fall", "true")])],
        ),
        IF('input.pressed("Space")', [C("drop")]),
    ],
)
play_ops += rite(
    PLAY,
    "rotate",
    [
        L("r", "(piece.rot + dir + 4) % 4"),
        L("kx", "[0, 1, -1, 2, -2, 0]"),
        L("ky", "[0, 0, 0, 0, 0, -1]"),
        L("ok", "false"),
        COUNT(
            "k",
            "len(kx)",
            [
                C("fits", "piece.kind", "r", "piece.x + kx[k]", "piece.y + ky[k]", into="ok"),
                IF(
                    "ok",
                    [
                        S("piece.rot", "r"),
                        S("piece.x", "piece.x + kx[k]"),
                        S("piece.y", "piece.y + ky[k]"),
                        C("audio.tone", "880", "10"),
                        RET(),
                    ],
                ),
            ],
        ),
    ],
    params=[p("dir", "num")],
)
play_ops += rite(
    PLAY,
    "drop",
    [
        L("d", "0"),
        C("depth", "piece.kind", "piece.rot", "piece.x", "piece.y", into="d"),
        S("piece.y", "piece.y + d"),
        S("score", "score + d * 2"),
        C("lock"),
    ],
)
play_ops += rite(
    PLAY,
    "swap",
    [
        IF("not canHold", [RET()]),
        S("canHold", "false"),
        C("audio.tone", "330", "20"),
        IF(
            "hold < 0",
            [S("hold", "piece.kind"), C("spawn")],
            [L("k", "hold"), S("hold", "piece.kind"), C("enter", "k")],
        ),
    ],
)
play_ops += rite(
    PLAY,
    "paint",
    [
        C("drawBoard"),
        IF(
            "not over",
            [
                L("d", "0"),
                C("depth", "piece.kind", "piece.rot", "piece.x", "piece.y", into="d"),
                C(
                    "drawPiece",
                    "piece.kind",
                    "piece.rot",
                    "8 + piece.x * 8",
                    "8 + (piece.y + d) * 8",
                    "8",
                    "true",
                ),
                C(
                    "drawPiece",
                    "piece.kind",
                    "piece.rot",
                    "8 + piece.x * 8",
                    "8 + piece.y * 8",
                    "8",
                    "false",
                ),
            ],
        ),
        C("canvas.ink", q("#c8d0dc")),
        C("canvas.text", q("HOLD"), "100", "4"),
        C("canvas.text", q("NEXT"), "100", "42"),
        IF("hold >= 0", [C("drawPiece", "hold", "0", "100", "14", "6", "not canHold")]),
        COUNT("i", "3", [C("drawPiece", "queue[i]", "0", "100", "52 + i * 20", "6", "false")]),
        C("canvas.ink", q("#c8d0dc")),
        C("canvas.text", q("SCORE ") + " ++ str(score)", "100", "116"),
        C("canvas.text", q("LINES ") + " ++ str(lines)", "100", "128"),
        C("canvas.text", q("LEVEL ") + " ++ str(level)", "100", "140"),
        IF(
            "paused",
            [C("canvas.ink", q("#f2d541")), C("canvas.text", q("PAUSE"), "33", "84")],
            [C("canvas.text", q("BEST  ") + " ++ str(max(best, score))", "100", "152")],
        ),
    ],
)
play_ops += [
    on(PLAY, "tick", "control"),
    guard(PLAY, "score >= 0 and lines >= 0 and level >= 0", "得点・行数・レベルは負にならない"),
    guard(PLAY, "hold >= -1 and hold <= 6", "ホールドは空(-1)か 7 種のどれか"),
]
apply("Play", play_ops)

# ---- Result: 結果・新記録・やり直し ----------------------------------------------------------------

result_ops = [
    state(RESULT, "quit", "bool", "false", out=True),
    host(RESULT, "canvas"),
    host(RESULT, "ui"),
]
result_ops += rite(RESULT, "show", [S("quit", "false"), {"do": "wait", "ticks": "20"}])
result_ops += rite(
    RESULT,
    "menu",
    [
        C("canvas.clear", q("#101418")),
        C("canvas.ink", q("#3a4250")),
        COUNT(
            "i",
            "200",
            [
                IF(
                    "Board.cells[i] != 0",
                    [C("canvas.rect", "8 + i % 10 * 8", "8 + floor(i / 10) * 8", "7", "7")],
                )
            ],
        ),
        C("canvas.ink", q("#c8d0dc")),
        C("canvas.text", q("GAME OVER"), "100", "8"),
        C("canvas.text", q("SCORE ") + " ++ str(Play.score)", "100", "28"),
        C("canvas.text", q("LINES ") + " ++ str(Play.lines)", "100", "40"),
        C("canvas.text", q("LEVEL ") + " ++ str(Play.level)", "100", "52"),
        C("canvas.text", q("BEST  ") + " ++ str(Play.best)", "100", "64"),
        IF(
            "Play.record",
            [C("canvas.ink", q("#f2d541")), C("canvas.text", q("新記録！"), "100", "76")],
        ),
        IF('ui.button("RETRY", 100, 100, 64, 20)', [FINISH]),
        IF('ui.button("QUIT", 100, 128, 64, 20)', [S("quit", "true"), FINISH]),
    ],
)
result_ops.append(on(RESULT, "tick", "menu"))
final = apply("Result", result_ops)

# ---- 仕上げ: 診断が残っていないことと、JIL が生成できることを LSP に確かめる -----------------------------

model = client.request("jin/model", {"uri": URI})
print(
    f"jin/model: 陣 {len(model['model']['circles'])} / jilError {model.get('jilError')}",
    file=sys.stderr,
)
for d in final.get("diagnostics", []):
    print(f"  {d['code']} {d['pointer']}: {d['message']}", file=sys.stderr)

client.request("shutdown", None)
client.notify("exit", None)
client.proc.wait(timeout=10)
if final.get("diagnostics") or model.get("jil") is None:
    raise SystemExit("診断が残っているか JIL を生成できませんでした")
if CHECK:
    if not OUT.is_file() or OUT.read_text(encoding="utf-8") != text:
        raise SystemExit(f"{OUT} が LSP で組み立て直した結果とずれています(--check 無しで書き直す)")
    print(f"一致: {OUT.relative_to(REPO_ROOT)}", file=sys.stderr)
else:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"書き出しました: {OUT.relative_to(REPO_ROOT)}", file=sys.stderr)
