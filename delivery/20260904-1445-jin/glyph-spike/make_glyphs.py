"""陣書き S0 spike: 試作の紋 57 字を glyphs.json に書く(使い捨て)。

字形は 1 升 = 0〜100 の正方形の線(塗らない)。円は楕円弧 `A` を使わず 3 次ベジェ 4 本で描く
(リポジトリの SVG の規律に合わせる)。設計規則は spec §1.1: ラテン文字・数字に似せない /
対は鏡像 / 3 画以内。判別の紋は決まった枠にだけ現れる。
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
K = 0.5523


def f(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def circle(cx: float, cy: float, r: float) -> str:
    k = K * r
    return (
        f"M{f(cx)} {f(cy - r)} "
        f"C{f(cx + k)} {f(cy - r)} {f(cx + r)} {f(cy - k)} {f(cx + r)} {f(cy)} "
        f"C{f(cx + r)} {f(cy + k)} {f(cx + k)} {f(cy + r)} {f(cx)} {f(cy + r)} "
        f"C{f(cx - k)} {f(cy + r)} {f(cx - r)} {f(cy + k)} {f(cx - r)} {f(cy)} "
        f"C{f(cx - r)} {f(cy - k)} {f(cx - k)} {f(cy - r)} {f(cx)} {f(cy - r)}"
    )


def mirror(d: str) -> str:
    """x を 100 - x にした鏡像(M/L/H/V/C/Z だけを扱う)。"""
    out: list[str] = []
    toks = d.replace(",", " ").split()
    cmd = ""
    i = 0
    nums: list[str] = []
    for t in toks:
        if t[0].isalpha():
            cmd = t[0]
            out.append(cmd)
            rest = t[1:]
            i = 0
            if not rest:
                continue
            t = rest
        if cmd == "H":
            out.append(f(100 - float(t)))
        elif cmd == "V":
            out.append(t)
        elif cmd in "MLC":
            out.append(f(100 - float(t)) if i % 2 == 0 else t)
            i += 1
        nums.append(t)
    return " ".join(out).replace("M ", "M").replace("L ", "L").replace("C ", "C").replace("H ", "H").replace("V ", "V")


STAR4 = "M50 18 L58 42 L82 50 L58 58 L50 82 L42 58 L18 50 L42 42 Z"
STAR5 = "M50 15 L58 39 L83 39 L63 54 L71 79 L50 64 L29 79 L37 54 L17 39 L42 39 Z"
TRI_UP = "M50 18 L84 80 L16 80 Z"
TRI_DOWN = "M16 20 L84 20 L50 82 Z"
INF = "M50 50 C40 30 18 30 18 50 C18 70 40 70 50 50 C60 30 82 30 82 50 C82 70 60 70 50 50"
PAREN_L = "M60 12 C32 32 32 68 60 88 M42 50 H58"
BRACK_L = "M60 12 H38 V88 H60"
BRACE_L = "M62 12 C46 12 50 24 50 36 C50 46 44 50 36 50 C44 50 50 54 50 64 C50 76 46 88 62 88"
QUOTE_L = "M62 14 H34 V48"
LIST_L = "M62 12 H34 V88 H62 M44 12 V88"
CHEVRON_L = "M76 18 L24 50 L76 82"
# 閉じた円 + 円の上の矢じり(開いた弧は C に見えるので閉じる)
CYCLE = circle(50, 54, 28) + " M38 14 L50 26 L38 38"

GLYPHS: list[tuple[str, str, str, str | None, str]] = [
    # (id, layer, token, slot, d)
    ("add", "expr", "+", None, "M50 15 V85 M15 50 H85 " + circle(50, 50, 9)),
    ("sub", "expr", "-", None, "M15 50 H85 M15 38 V62 M85 38 V62"),
    ("mul", "expr", "*", None, "M50 15 V85 M20 32 L80 68 M20 68 L80 32"),
    ("div", "expr", "/", None, "M15 50 H85 " + circle(50, 26, 7) + " " + circle(50, 74, 7)),
    ("mod", "expr", "%", None, "M80 15 L20 85 " + circle(28, 28, 10) + " " + circle(72, 72, 10)),
    ("cat", "expr", "++", None, INF),
    ("eq", "expr", "==", None, "M18 38 H82 M18 62 H82"),
    ("ne", "expr", "!=", None, "M18 38 H82 M18 62 H82 M66 18 L34 82"),
    ("lt", "expr", "<", None, CHEVRON_L),
    ("le", "expr", "<=", None, "M76 12 L24 40 L76 68 M24 86 H76"),
    ("gt", "expr", ">", None, mirror(CHEVRON_L)),
    ("ge", "expr", ">=", None, "M24 12 L76 40 L24 68 M24 86 H76"),
    ("and", "expr", "and", None, TRI_UP),
    ("or", "expr", "or", None, TRI_DOWN),
    ("not", "expr", "not", None, "M14 42 H84 V60 " + circle(26, 64, 6)),
    ("paren_l", "expr", "(", None, PAREN_L),
    ("paren_r", "expr", ")", None, mirror(PAREN_L)),
    ("brack_l", "expr", "[", None, BRACK_L),
    ("brack_r", "expr", "]", None, mirror(BRACK_L)),
    ("brace_l", "expr", "{", None, BRACE_L),
    ("brace_r", "expr", "}", None, mirror(BRACE_L)),
    ("comma", "expr", ",", None, "M40 60 L60 60 L44 88 Z"),
    ("colon", "expr", ":", None, circle(50, 32, 7) + " " + circle(50, 68, 7)),
    ("dot", "expr", ".", None, "M50 36 L64 50 L50 64 L36 50 Z"),
    ("quote_l", "expr", '"', None, QUOTE_L),
    ("quote_r", "expr", '"', None, "M38 86 H66 V52"),
    ("esc", "expr", "\\", None, "M50 12 V88 M30 34 H70 M30 64 H70"),
    ("true", "expr", "true", None, circle(50, 50, 30) + " " + circle(50, 50, 6)),
    ("false", "expr", "false", None, circle(50, 50, 30) + " M34 34 L66 66 M66 34 L34 66"),
    ("t_num", "expr", "num", None, circle(50, 28, 6) + " " + circle(28, 70, 6) + " " + circle(72, 70, 6)),
    ("t_bool", "expr", "bool", None, "M28 18 H72 L28 82 H72 Z"),
    ("t_str", "expr", "str", None, "M14 50 C26 30 38 30 50 50 C62 70 74 70 86 50"),
    ("t_list_l", "expr", "list<", None, LIST_L),
    ("t_list_r", "expr", ">", None, mirror(LIST_L)),
    ("sep", "expr", "<sep>", None, STAR4),
    ("cont", "expr", "<cont>", None, "M20 70 C20 30 76 24 80 56 M68 48 L80 60 L90 46"),
    # 判別の紋(決まった枠にだけ現れる)
    ("loop_each", "disc", "each", "loop", STAR5),
    ("loop_while", "disc", "while", "loop", CYCLE + " M50 44 L60 54 L50 64 L40 54 Z"),
    ("loop_count", "disc", "count", "loop", circle(32, 32, 6) + " " + circle(68, 32, 6) + " " + circle(32, 68, 6) + " " + circle(68, 68, 6)),
    ("wait_ticks", "disc", "ticks", "wait", circle(50, 20, 6) + " " + circle(50, 50, 6) + " " + circle(50, 80, 6)),
    ("wait_until", "disc", "until", "wait", "M14 50 H78 M60 34 L78 50 L60 66 M86 26 V74"),
    ("sigil_host", "disc", "host", "sigil", "M20 84 V44 L50 16 L80 44 V84 Z"),
    ("sigil_summon", "disc", "summon", "sigil", circle(50, 50, 32) + " " + circle(50, 50, 14)),
    ("sigil_agent", "disc", "agent", "sigil", "M12 50 C30 22 70 22 88 50 C70 78 30 78 12 50 " + circle(50, 50, 9)),
    ("asset_sprite", "disc", "sprite", "asset", "M18 18 H82 V82 H18 Z M18 82 L82 18"),
    ("asset_sound", "disc", "sound", "asset", circle(36, 74, 12) + " M48 74 V16 L76 28"),
    ("flow_sequence", "disc", "sequence", "flow", "M12 50 H84 M66 32 L84 50 L66 68"),
    ("flow_parallel", "disc", "parallel", "flow", "M12 36 H84 M12 64 H84 M70 22 L88 50 L70 78"),
    ("flow_loop", "disc", "loop", "flow", CYCLE),
    ("event_tick", "disc", "tick", "event", circle(50, 50, 34) + " M50 24 V50 L70 62"),
    ("event_key", "disc", "key", "event", "M20 20 H80 V80 H20 Z M36 64 H64"),
    ("event_pointer", "disc", "pointer", "event", "M24 14 L24 78 L42 62 L56 88 L66 82 L52 58 L76 56 Z"),
    ("event_message", "disc", "message", "event", "M14 26 H86 V76 H14 Z M14 26 L50 54 L86 26"),
    ("event_exit", "disc", "exit", "event", "M18 64 L50 22 L82 64 Z M18 82 H82"),
    ("mark_into", "disc", "into", "optional", "M12 40 H72 M12 60 H72 M60 22 L88 50 L60 78"),
    ("mark_name", "disc", "name", "optional", "M12 50 H52 " + circle(70, 50, 16)),
    ("mark_message", "disc", "message", "optional", "M16 20 H84 V64 H44 L28 84 V64 H16 Z"),
]


def main() -> None:
    ids = [g[0] for g in GLYPHS]
    assert len(ids) == len(set(ids)) == 57, len(ids)
    assert sum(g[1] == "expr" for g in GLYPHS) == 36
    assert sum(g[1] == "disc" for g in GLYPHS) == 21
    data = {gid: {"layer": layer, "token": token, "slot": slot, "d": d} for gid, layer, token, slot, d in GLYPHS}
    (HERE / "glyphs.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"glyphs.json: {len(data)} 字")


if __name__ == "__main__":
    main()
