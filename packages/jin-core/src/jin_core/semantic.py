"""意味検査（診断の段 3）。

正本は `docs/spec/diagnostics.md`。実装するのは正典 12 件のうち段 3 に属する 10 件
（JIN010 / JIN011 / JIN020 / JIN022 / JIN030 / JIN031 / JIN040 / JIN050 / JIN060 / JIN070）と、
ADR-007 / DP-JIN-SEMANTIC-GAPS-01 の追加提案 2 件（JIN012 循環参照 / JIN013 多重親）。

**コードの優先順位**（docs/spec/diagnostics.md §4）: より具体的なコードが勝つ。
JIN011 の守備範囲は summon と delegate の 2 種だけで、steps / root / await / rune の `{key}` は
それぞれ JIN031 / JIN060 / JIN070 / JIN050 が受け持つ。

`jin_core` は ADK に依存しない（ADR-004 の forbidden 契約）。ここに `google.adk` を持ち込まないこと。
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass

from jin_core.diagnostics import MAX_ELEMENTS, Diagnostic, Position, Range, severity_of
from jin_core.model import Circle, JinFile, ToolSummon
from jin_core.parser import PointerTable
from jin_core.pointer import join
from jin_core.resolver import RefResolver

#: rune 内の state key の本体。前後の `{` `}` は `rune_keys` の走査側で扱う。
_RUNE_KEY_BODY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

#: `close_names` が編集距離を計算する候補数の上限。
#: 決定根拠は delivery/20260904-1445-jin/decision-conformance.md（DP-JIN-HINTLIMIT-01）。
MAX_CANDIDATES_SCANNED = 500

#: hint に列挙する名前の最大件数。超えた分は「他 N 件」に畳む。
MAX_NAMES_IN_HINT = 10

#: 1 回の `analyze` で編集距離を計算してよい総回数。
#: 候補数の上限だけでは「診断件数 × 候補数」で二次的に効くので、全体にも上限を置く
#: （security review S3。実測: 600 circle 全件未解決で 30 万回・6.2 秒）。
#: 使い切ったあとの hint は「近い名前」ではなく「定義済みの…」に**決定的に**退化する。
MAX_DISTANCE_COMPUTATIONS = 20000


class DistanceBudget:
    """編集距離の計算回数を 1 回の `analyze` 全体で数える。

    使い切ったら候補探索をやめる。診断そのものは 1 件も減らさず、hint の詳しさだけが落ちる。
    消費は文書順なので、同じ入力なら常に同じ出力になる（NFR-DET-002）。
    """

    __slots__ = ("remaining",)

    def __init__(self, total: int = MAX_DISTANCE_COMPUTATIONS) -> None:
        self.remaining = total

    def take(self, requested: int) -> int:
        granted = max(0, min(requested, self.remaining))
        self.remaining -= granted
        return granted


def levenshtein(a: str, b: str, *, limit: int | None = None) -> int:
    """編集距離（要件書 §2.4「候補名を提示(編集距離)」）。

    `limit` を渡すと、距離が `limit` を超えると確定した時点で打ち切り `limit + 1` を返す。
    候補が多いファイルで O(候補数 × |a| × |b|) を丸ごと払わないための枝刈り
    （security review S3: 88 KB の `.jin` で `jin check` が 107 秒かかった）。
    """
    if a == b:
        return 0
    if limit is not None and abs(len(a) - len(b)) > limit:
        # 長さの差だけで距離の下界が limit を超える。行列を作らずに捨てる。
        return limit + 1
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
        if limit is not None and min(previous) > limit:
            return limit + 1
    return previous[-1]


def close_names(
    target: str,
    candidates: list[str],
    limit: int = 3,
    budget: DistanceBudget | None = None,
) -> list[str]:
    """編集距離が近い候補を近い順に返す。同距離は候補の宣言順を保つ。

    見る候補は `MAX_CANDIDATES_SCANNED` 件まで。さらに `budget` を渡すと、
    `analyze` 全体での計算回数の残りに応じて途中で打ち切る（security review S3）。
    """
    threshold = max(1, len(target) // 3)
    scanned = candidates[:MAX_CANDIDATES_SCANNED]
    if budget is not None:
        scanned = scanned[: budget.take(len(scanned))]
    scored: list[tuple[int, int, str]] = []
    for i, candidate in enumerate(scanned):
        distance = levenshtein(target, candidate, limit=threshold)
        if distance <= threshold:
            scored.append((distance, i, candidate))
    return [c for _, _, c in sorted(scored)][:limit]


def _join_names(names: list[str]) -> str:
    """名前の列挙を hint に載せられる長さへ畳む。"""
    if len(names) <= MAX_NAMES_IN_HINT:
        return " / ".join(names)
    shown = " / ".join(names[:MAX_NAMES_IN_HINT])
    return f"{shown} / 他 {len(names) - MAX_NAMES_IN_HINT} 件"


def _name_hint(
    target: str, candidates: list[str], noun: str, budget: DistanceBudget | None = None
) -> str:
    near = close_names(target, candidates, budget=budget)
    if near:
        return "近い名前: " + " / ".join(near)
    if candidates:
        return f"定義済みの{noun}: " + _join_names(candidates)
    return f"{noun}が 1 つも定義されていません。先に定義を追加してください"


def rune_key_spans(rune: str) -> list[tuple[int, int, str]]:
    """rune 内の `{key}` を `(開始, 終了, key)` で出現順に返す。

    `{{` / `}}` はリテラルのエスケープ（docs/spec/model.md §3.1）なので、
    **左から 1 文字ずつ走査**して判定する。単一の正規表現では `"{a}}"` のように
    key の直後にリテラルの `}` が来る形を取りこぼす（correctness review B-8）。

    `rune_keys`（JIN050）と `replace_rune_key`（rename）はどちらもここを通す。
    エスケープ規則の実装を 1 箇所に閉じるため。
    """
    spans: list[tuple[int, int, str]] = []
    i = 0
    n = len(rune)
    while i < n:
        ch = rune[i]
        if ch == "{":
            if i + 1 < n and rune[i + 1] == "{":
                i += 2  # リテラルの '{'
                continue
            match = _RUNE_KEY_BODY.match(rune, i + 1)
            if match is not None and match.end() < n and rune[match.end()] == "}":
                spans.append((i, match.end() + 1, match.group(0)))
                i = match.end() + 1
                continue
            i += 1
            continue
        if ch == "}":
            i += 2 if (i + 1 < n and rune[i + 1] == "}") else 1
            continue
        i += 1
    return spans


def rune_keys(rune: str) -> list[str]:
    """rune 内の `{key}` を出現順・重複ありで返す。"""
    return [key for _, _, key in rune_key_spans(rune)]


def replace_rune_key(rune: str, old: str, new: str) -> str:
    r"""rune 内の `{old}` を `{new}` に置き換える（rename の参照追随）。

    **文字列連結で組み立てる**。`re.sub` の置換文字列は `\g<0>` や `\1` を
    展開してしまうので、`new` に `\` を含む名前が来ると原文に無い内容を書き込める
    （security review S8）。
    """
    out: list[str] = []
    last = 0
    for start, end, key in rune_key_spans(rune):
        if key != old:
            continue
        out.append(rune[last:start])
        out.append("{" + new + "}")
        last = end
    out.append(rune[last:])
    return "".join(out)


def rune_fingerprint(rune: str) -> str:
    """識別紋章の決定的な種（docs/spec/layout.md §2.2）。Phase 3 のレンダラが使う。"""
    return hashlib.sha256(rune.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class _Graph:
    """circle 名で張られた参照グラフ。"""

    #: 親子辺（flow.steps / delegate）。子 → 親エッジの本数を数えるために親側から持つ。
    parent_edges: list[tuple[str, str]]
    #: 参照辺（親子辺 + summon）。循環判定に使う。
    reference_edges: list[tuple[str, str]]


def _build_graph(model: JinFile, known: set[str]) -> _Graph:
    parent_edges: list[tuple[str, str]] = []
    reference_edges: list[tuple[str, str]] = []
    for circle in model.circles:
        if circle.flow is not None:
            for step in circle.flow.steps:
                if step in known:
                    parent_edges.append((circle.name, step))
                    reference_edges.append((circle.name, step))
        for target in circle.delegate:
            if target in known:
                parent_edges.append((circle.name, target))
                reference_edges.append((circle.name, target))
        for tool in circle.tools:
            if isinstance(tool, ToolSummon) and tool.circle in known:
                reference_edges.append((circle.name, tool.circle))
    return _Graph(parent_edges=parent_edges, reference_edges=reference_edges)


def _find_cycle(edges: list[tuple[str, str]]) -> list[str] | None:
    """有向グラフの閉路を 1 つ返す（見つからなければ None）。決定的に走査する。

    **明示スタックで走査する**（再帰にしない）。`.jin` の circle 数には上限が無いので、
    再帰だと長い連鎖で Python の再帰上限に当たり、診断ではなく `RecursionError` の
    トレースバックが表に出る（security review S4）。
    """
    adjacency: dict[str, list[str]] = {}
    for src, dst in edges:
        adjacency.setdefault(src, []).append(dst)

    WHITE, GREY, BLACK = 0, 1, 2
    color: dict[str, int] = {}

    for root, _ in edges:
        if color.get(root, WHITE) != WHITE:
            continue
        color[root] = GREY
        path: list[str] = [root]
        stack: list[tuple[str, object]] = [(root, iter(adjacency.get(root, ())))]
        while stack:
            node, children = stack[-1]
            descended = False
            for nxt in children:  # type: ignore[union-attr]
                state = color.get(nxt, WHITE)
                if state == GREY:
                    return path[path.index(nxt) :] + [nxt]
                if state == WHITE:
                    color[nxt] = GREY
                    path.append(nxt)
                    stack.append((nxt, iter(adjacency.get(nxt, ()))))
                    descended = True
                    break
            if not descended:
                color[node] = BLACK
                stack.pop()
                path.pop()
    return None


def _parents_of(model: JinFile, graph: _Graph) -> dict[str, list[str]]:
    parents: dict[str, list[str]] = {c.name: [] for c in model.circles}
    for parent, child in graph.parent_edges:
        parents.setdefault(child, []).append(parent)
    return parents


def _strongly_connected_components(
    nodes: list[str], children: dict[str, list[str]]
) -> tuple[dict[str, int], list[list[str]]]:
    """Tarjan の強連結成分分解（**明示スタック**）。

    返す成分列は「到達先の成分が必ず先に来る」順（逆トポロジカル順）になる。
    循環していても打ち切らずに正しく畳めるので、`_subtree_states` を
    circle 数に対して線形にできる。
    """
    index_of: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    component_of: dict[str, int] = {}
    components: list[list[str]] = []
    counter = 0

    for root in nodes:
        if root in index_of:
            continue
        index_of[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        work: list[tuple[str, Iterator[str]]] = [(root, iter(children.get(root, ())))]
        while work:
            node, pending = work[-1]
            descended = False
            for nxt in pending:
                if nxt not in index_of:
                    index_of[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, iter(children.get(nxt, ()))))
                    descended = True
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index_of[nxt])
            if descended:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index_of[node]:
                component: list[str] = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component_of[member] = len(components)
                    component.append(member)
                    if member == node:
                        break
                components.append(component)
    return component_of, components


def _subtree_states(model: JinFile, graph: _Graph) -> dict[str, set[str]]:
    """circle → その部分木（自身 + 親子辺で到達できる circle）の state 名の集合。

    **再帰を使わず、強連結成分ごとに 1 度だけ畳む**（security review S4 / S3）。
    再帰版は長い連鎖で `RecursionError` になり、素朴な反復版は circle 数の 2 乗に効く。

    戻り値の集合は成分内で共有される。呼び出し側は読むだけにすること。
    """
    children: dict[str, list[str]] = {}
    for parent, child in graph.parent_edges:
        children.setdefault(parent, []).append(child)
    own = {c.name: {s.name for s in c.state} for c in model.circles}

    names = list(own)
    component_of, components = _strongly_connected_components(names, children)

    component_states: list[set[str]] = []
    for i, component in enumerate(components):
        acc: set[str] = set()
        for node in component:
            acc |= own.get(node, set())
            for child in children.get(node, ()):
                target = component_of[child]
                if target != i:
                    # 逆トポロジカル順なので target < i、既に確定している。
                    acc |= component_states[target]
        component_states.append(acc)

    return {name: component_states[component_of[name]] for name in names}


def _visible_state_keys(
    circle: Circle,
    by_name: dict[str, Circle],
    parents: dict[str, list[str]],
    subtree: dict[str, set[str]],
) -> set[str]:
    """JIN050 の「可視な state key」（docs/spec/model.md §5）。

    `by_name` / `parents` / `subtree` は呼び出し側で 1 度だけ作って渡す。
    circle ごとに作り直すと circle 数の 2 乗に効いて大きなファイルで遅くなる
    （security review S3）。
    """
    visible = {s.name for s in circle.state}

    # 祖先を辿る。同じ circle を 2 度通らないようにして循環時も止まる。
    current = circle.name
    seen: set[str] = {current}
    while True:
        candidates = parents.get(current, [])
        if not candidates:
            break
        parent_name = candidates[0]
        if parent_name in seen:
            break
        seen.add(parent_name)
        parent = by_name.get(parent_name)
        if parent is None:
            break

        if parent.flow is not None and current in parent.flow.steps:
            index = parent.flow.steps.index(current)
            if parent.flow.kind == "sequence":
                siblings = parent.flow.steps[:index]
            elif parent.flow.kind == "loop":
                siblings = [s for s in parent.flow.steps if s != current]
            else:  # parallel は実行順序の保証が無い
                siblings = []
            for sibling in siblings:
                visible |= subtree.get(sibling, set())
        if current in parent.delegate:
            # delegate は親 → 子の向きのみ（親が動いてから transfer される）
            visible |= {s.name for s in parent.state}

        current = parent_name
    return visible


def analyze(
    model: JinFile, table: PointerTable, file: str, *, resolver: RefResolver | None = None
) -> list[Diagnostic]:
    """意味検査を実行して診断を返す。1 件目で止めない。

    `resolver` を渡したときだけ JIN040（外部参照の解決）を検査する。
    **`jin_core` は import を一切行わない**（security review S1）。実装の注入口は
    `jin_core.resolver.RefResolver` プロトコルで、実装は `jin_cli.resolver` にしか無い。
    """
    out: list[Diagnostic] = []

    def emit(code: str, pointer: str, message: str, hint: str) -> None:
        out.append(
            Diagnostic(
                file=file,
                pointer=pointer,
                range=table.resolve(pointer),
                code=code,
                severity=severity_of(code),
                message=message,
                hint=hint,
            )
        )

    circle_names = [c.name for c in model.circles]
    known = set(circle_names)
    budget = DistanceBudget()

    # 参照グラフと、そこから導く表は 1 度だけ作って使い回す。
    graph = _build_graph(model, known)
    by_name = {c.name: c for c in model.circles}
    parents = _parents_of(model, graph)
    subtree = _subtree_states(model, graph)

    # ---- JIN010: 名前の重複 -------------------------------------------------------
    seen_circles: set[str] = set()
    for i, circle in enumerate(model.circles):
        if circle.name in seen_circles:
            emit(
                "JIN010",
                join(join("", "circles"), i) + "/name",
                f"circle 名 '{circle.name}' が重複しています",
                f"circle 名はファイル内で一意です。'{circle.name}' を別の名前に変えてください",
            )
        seen_circles.add(circle.name)

    for i, circle in enumerate(model.circles):
        base = join(join("", "circles"), i)
        seen_tools: set[str] = set()
        for j, tool in enumerate(circle.tools):
            if tool.name in seen_tools:
                emit(
                    "JIN010",
                    join(join(base, "tools"), j) + "/name",
                    f"tool 名 '{tool.name}' が circle '{circle.name}' 内で重複しています",
                    f"tool 名は circle 内で一意です。'{tool.name}' を別の名前に変えてください",
                )
            seen_tools.add(tool.name)
        seen_states: set[str] = set()
        for j, state in enumerate(circle.state):
            if state.name in seen_states:
                emit(
                    "JIN010",
                    join(join(base, "state"), j) + "/name",
                    f"state 名 '{state.name}' が circle '{circle.name}' 内で重複しています",
                    f"state 名は circle 内で一意です。'{state.name}' を別の名前に変えてください",
                )
            seen_states.add(state.name)

    # ---- JIN020 / JIN022 / JIN030 / JIN031 / JIN011 / JIN050 / JIN070 / JIN040 ----
    for i, circle in enumerate(model.circles):
        base = join(join("", "circles"), i)

        if len(circle.tools) > MAX_ELEMENTS:
            emit(
                "JIN020",
                join(base, "tools"),
                f"circle '{circle.name}' の tools が {len(circle.tools)} 個で上限 {MAX_ELEMENTS} を超えています",
                f"{len(circle.tools) - MAX_ELEMENTS} 個以上をサブ陣（summon する別 circle）に抽出してください",
            )
        if len(circle.state) > MAX_ELEMENTS:
            emit(
                "JIN020",
                join(base, "state"),
                f"circle '{circle.name}' の state が {len(circle.state)} 個で上限 {MAX_ELEMENTS} を超えています",
                f"{len(circle.state) - MAX_ELEMENTS} 個以上をサブ陣（summon する別 circle）に抽出してください",
            )

        has_core = circle.core is not None
        has_flow = circle.flow is not None
        if has_core and has_flow:
            emit(
                "JIN022",
                base,
                f"circle '{circle.name}' が core と flow を両方持っています",
                "核あり（core）か核なし（flow）のどちらかにします。core を消すか flow を消してください",
            )
        elif not has_core and not has_flow:
            emit(
                "JIN022",
                base,
                f"circle '{circle.name}' が core も flow も持っていません",
                'LlmAgent にするなら "core": "gemini-2.5-flash" を、'
                'workflow agent にするなら "flow": {"kind": "sequence", "steps": []} を追加してください',
            )

        if circle.flow is not None:
            flow_pointer = join(base, "flow")
            if circle.flow.kind == "loop" and circle.flow.max is None and circle.flow.exit is None:
                emit(
                    "JIN030",
                    flow_pointer,
                    f"circle '{circle.name}' の loop に max も exit もありません（止まりません）",
                    '"max": 5 を追加するか "exit": {"key": "approved", "equals": true} を追加してください',
                )
            for j, step in enumerate(circle.flow.steps):
                if step not in known:
                    emit(
                        "JIN031",
                        join(join(flow_pointer, "steps"), j),
                        f"flow.steps の '{step}' は circle ではありません",
                        _name_hint(step, circle_names, "circle", budget),
                    )
            if circle.flow.exit is not None:
                # exit.key は「どこにも書かれていない state」を指せてしまうと
                # loop が永久に止まらない。JIN030 は max / exit の有無しか見ないので
                # ここで参照の解決を見る（correctness review B-2 / docs/spec/diagnostics.md §4）。
                reachable = set(_visible_state_keys(circle, by_name, parents, subtree))
                for step in circle.flow.steps:
                    reachable |= subtree.get(step, set())
                if circle.flow.exit.key not in reachable:
                    emit(
                        "JIN011",
                        join(join(flow_pointer, "exit"), "key"),
                        f"flow.exit.key の '{circle.flow.exit.key}' は "
                        f"circle '{circle.name}' から見える state にありません",
                        _name_hint(circle.flow.exit.key, sorted(reachable), "state key", budget),
                    )

        for j, tool in enumerate(circle.tools):
            tool_pointer = join(join(base, "tools"), j)
            if isinstance(tool, ToolSummon) and tool.circle not in known:
                emit(
                    "JIN011",
                    join(tool_pointer, "circle"),
                    f"circle '{tool.circle}' は定義されていません",
                    _name_hint(tool.circle, circle_names, "circle", budget),
                )
            if resolver is not None and getattr(tool, "ref", None) is not None:
                reason = resolver.resolve(tool.ref)  # type: ignore[attr-defined]
                if reason is not None:
                    emit(
                        "JIN040",
                        join(tool_pointer, "ref"),
                        f"Python 参照 '{tool.ref}' を解決できません",  # type: ignore[attr-defined]
                        reason,
                    )

        for j, target in enumerate(circle.delegate):
            if target not in known:
                emit(
                    "JIN011",
                    join(join(base, "delegate"), j),
                    f"circle '{target}' は定義されていません",
                    _name_hint(target, circle_names, "circle", budget),
                )

        if circle.boundary is not None:
            tool_names = [t.name for t in circle.tools]
            for j, awaited in enumerate(circle.boundary.await_):
                if awaited not in tool_names:
                    emit(
                        "JIN070",
                        join(join(join(base, "boundary"), "await"), j),
                        f"await 対象 '{awaited}' が circle '{circle.name}' の tools にありません",
                        _name_hint(awaited, tool_names, "tool", budget),
                    )
            if resolver is not None:
                for j, guard in enumerate(circle.boundary.guards):
                    reason = resolver.resolve(guard.ref)
                    if reason is not None:
                        emit(
                            "JIN040",
                            join(join(join(base, "boundary"), "guards"), j) + "/ref",
                            f"Python 参照 '{guard.ref}' を解決できません",
                            reason,
                        )

    # ---- JIN060: root ------------------------------------------------------------
    if model.root not in known:
        emit(
            "JIN060",
            "/root",
            f"root が指す circle '{model.root}' は定義されていません",
            _name_hint(model.root, circle_names, "circle", budget),
        )

    # ---- JIN012 / JIN013: 参照グラフ（ADR-007・人間承認待ち） ----------------------
    cycle = _find_cycle(graph.reference_edges)
    if cycle is not None:
        index = circle_names.index(cycle[0])
        emit(
            "JIN012",
            join(join("", "circles"), index),
            "参照が循環しています: " + " → ".join(cycle),
            f"閉路のいずれかの参照を外してください（例: '{cycle[0]}' から '{cycle[1]}' への参照）",
        )

    for i, circle in enumerate(model.circles):
        owners = parents.get(circle.name, [])
        if len(owners) > 1:
            # 同じ親から 2 回参照された場合と、別々の親から参照された場合は直し方が違う。
            # 前者を「2 個の親を持っています: P / P」と出すと嘘になる（correctness review B-1）。
            unique_owners = list(dict.fromkeys(owners))
            if len(unique_owners) == 1:
                message = (
                    f"circle '{circle.name}' が親 '{unique_owners[0]}' から "
                    f"{len(owners)} 回参照されています"
                )
                hint = (
                    "ADK の親子関係は 1 対 1 です。"
                    f"'{unique_owners[0]}' の flow.steps / delegate から重複を消し、1 つだけ残してください"
                )
            else:
                message = (
                    f"circle '{circle.name}' が {len(unique_owners)} 個の親を持っています: "
                    + _join_names(unique_owners)
                )
                hint = (
                    "ADK の親子関係は 1 対 1 です。"
                    "1 つだけ残し、他は summon（AgentTool）に変えてください"
                )
            emit("JIN013", join(join("", "circles"), i), message, hint)

    # ---- JIN050: rune 内の {key} --------------------------------------------------
    for i, circle in enumerate(model.circles):
        if circle.instruction is None:
            continue
        visible = _visible_state_keys(circle, by_name, parents, subtree)
        pointer = join(join(join("", "circles"), i), "instruction") + "/rune"
        reported: set[str] = set()
        for key in rune_keys(circle.instruction.rune):
            if key in visible or key in reported:
                continue
            reported.add(key)
            emit(
                "JIN050",
                pointer,
                f"rune 内の '{{{key}}}' は circle '{circle.name}' から見える state にありません",
                (
                    "見える state key: " + " / ".join(sorted(visible))
                    if visible
                    else f'"state": [{{"name": "{key}", "type": "str"}}] を追加してください'
                ),
            )

    return _sorted(out)


def _sorted(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    """出力順を決定的にする（位置 → コード → pointer）。"""

    def key(d: Diagnostic) -> tuple[int, int, str, str]:
        return (d.range.start.line, d.range.start.col, d.code, d.pointer)

    return sorted(diagnostics, key=key)


__all__ = [
    "MAX_DISTANCE_COMPUTATIONS",
    "DistanceBudget",
    "Position",
    "Range",
    "analyze",
    "close_names",
    "levenshtein",
    "replace_rune_key",
    "rune_fingerprint",
    "rune_key_spans",
    "rune_keys",
]
