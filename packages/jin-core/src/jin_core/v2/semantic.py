"""Jin v2 の意味検査（段 3）。正典は docs/spec/v2/diagnostics.md と model.md。

v1 の `jin_core.semantic` と同じ流儀: 1 件目で止めず、出力は位置 → コード → pointer で決定的に並べる。
式の中の位置は `jin_core.v2.spans` で JSON 文字列リテラル内の列へ写す（原文 `source` が要る。
無ければリテラル全体を指す）。

検査の順序（コードの番号順ではなく依存順）:

1. 名前表（JIN010）と参照（JIN011 / JIN060 / JIN022 / JIN020）
2. グラフ（JIN012 / JIN013）
3. 手順の中（JIN201〜JIN205 / JIN210〜JIN213 / JIN240 / JIN250）
4. 境界（JIN221 / JIN230）と flow（JIN220）
"""

from __future__ import annotations

from dataclasses import dataclass, field

from jin_core.diagnostics import MAX_ELEMENTS, Diagnostic, Position, Range, severity_of
from jin_core.parser import PointerTable
from jin_core.semantic import _find_cycle, _sorted, close_names
from jin_core.v2 import abilities
from jin_core.v2 import expr as ex
from jin_core.v2.model import (
    PRIMITIVE_TYPES,
    BreakStep,
    CastStep,
    Circle,
    EmitStep,
    FinishStep,
    IfStep,
    JinFileV2,
    LetStep,
    LoopStep,
    ReturnStep,
    Rite,
    SetStep,
    SigilHost,
    SigilSummon,
    Step,
    TransferStep,
    WaitStep,
    parse_type,
)
from jin_core.v2.spans import decode_offsets, span_to_range

#: 手順あたりのステップ数と入れ子の上限（diagnostics.md JIN210 / JIN211）。
MAX_STEPS = MAX_ELEMENTS
MAX_NESTING = 3

#: イベントごとの手順の引数の形（model.md §3.5）。`message` は `name` の後ろが自由。
EVENT_PARAMS: dict[str, tuple[str, ...]] = {
    "tick": ("num",),
    "key": ("str", "bool"),
    "pointer": ("Pointer",),
    "message": ("str",),
    "exit": (),
}

#: 組み込みの型紙。
BUILTIN_FORMS: dict[str, dict[str, str]] = {"Pointer": dict(abilities.POINTER_FIELDS)}


@dataclass(slots=True)
class _RiteInfo:
    params: list[tuple[str, str]]
    returns: str | None
    waits: bool = False
    casts: set[str] = field(default_factory=set)


class _Analyzer:
    def __init__(
        self, model: JinFileV2, table: PointerTable, file: str, source: str | None
    ) -> None:
        self.model = model
        self.table = table
        self.file = file
        self.lines = source.split("\n") if source is not None else None
        self.out: list[Diagnostic] = []
        #: 型検査を通った式の AST（pointer → 型注記付きノード）。`rename` の参照追随が読む。
        self.nodes: dict[str, ex.Node] = {}
        self.circles = {c.name: c for c in model.circles}
        self.forms: dict[str, dict[str, str]] = dict(BUILTIN_FORMS)
        for form in model.forms:
            self.forms.setdefault(form.name, {f.name: f.type for f in form.fields})
        self.public: dict[str, dict[str, str]] = {
            c.name: {s.name: s.type for s in c.state if s.out}
            for c in model.circles
            if c.core is not None
        }
        self.rites: dict[str, dict[str, _RiteInfo]] = {
            c.name: {
                r.name: _RiteInfo([(p.name, p.type) for p in r.params], r.returns) for r in c.rites
            }
            for c in model.circles
        }

    # ---------------------------------------------------------------- 出力
    def emit(self, code: str, pointer: str, message: str, hint: str | None = None) -> None:
        self.out.append(
            Diagnostic(
                file=self.file,
                pointer=pointer,
                range=self.table.resolve(pointer),
                code=code,
                severity=severity_of(code),
                message=message,
                hint=hint if hint is not None else _fallback_hint(code),
            )
        )

    def emit_at(
        self, code: str, pointer: str, span: ex.Span, message: str, hint: str | None = None
    ) -> None:
        """式の中の区間を指す診断。原文が無い / リテラルを取れないときはリテラル全体。"""
        self.out.append(
            Diagnostic(
                file=self.file,
                pointer=pointer,
                range=self._range_in_literal(pointer, span),
                code=code,
                severity=severity_of(code),
                message=message,
                hint=hint if hint is not None else _fallback_hint(code),
            )
        )

    def _range_in_literal(self, pointer: str, span: ex.Span) -> Range:
        literal_range = self.table.resolve(pointer)
        if self.lines is None or pointer not in self.table.value_ranges:
            return literal_range
        start, end = literal_range.start, literal_range.end
        if start.line != end.line or not (1 <= start.line <= len(self.lines)):
            return literal_range
        line = self.lines[start.line - 1]
        literal = line[start.col - 1 : end.col - 1]
        try:
            offsets = decode_offsets(literal)
        except ValueError:
            return literal_range
        return span_to_range(literal_range, offsets, span.start, span.end)

    # ---------------------------------------------------------------- 入口
    def run(self) -> None:
        self._collect_waits()
        self._names_and_references()
        self._graphs()
        for i, circle in enumerate(self.model.circles):
            if circle.core is not None:
                self._circle_body(i, circle)
            else:
                self._flow(i, circle)

    # ---------------------------------------------------------------- 1. 名前と参照
    def _names_and_references(self) -> None:
        model = self.model
        seen: set[str] = set()
        for i, circle in enumerate(model.circles):
            if circle.name in seen:
                self.emit(
                    "JIN010",
                    f"/circles/{i}/name",
                    f"circle 名 '{circle.name}' が重複しています",
                    "circle 名はファイル内で一意です",
                )
            seen.add(circle.name)
        for i, form in enumerate(model.forms):
            if form.name in seen or form.name in BUILTIN_FORMS:
                self.emit(
                    "JIN010",
                    f"/forms/{i}/name",
                    f"型紙名 '{form.name}' が circle 名か組み込みの型紙と重複しています",
                    "型紙名はファイル内で一意で、circle 名とも衝突できません",
                )
            seen.add(form.name)
            fields: set[str] = set()
            for j, f in enumerate(form.fields):
                if f.name in fields:
                    self.emit(
                        "JIN010", f"/forms/{i}/fields/{j}/name", f"欄 '{f.name}' が重複しています"
                    )
                fields.add(f.name)
                self._type_ref(f"/forms/{i}/fields/{j}/type", f.type)

        if model.root not in self.circles:
            self.emit(
                "JIN060",
                "/root",
                f"root が指す circle '{model.root}' は定義されていません",
                _hint(model.root, list(self.circles), "circle"),
            )

        for i, circle in enumerate(model.circles):
            base = f"/circles/{i}"
            if (circle.core is None) == (circle.flow is None):
                self.emit(
                    "JIN022",
                    base,
                    f"circle '{circle.name}' は core と flow の"
                    + (
                        "両方を持っています"
                        if circle.core is not None
                        else "どちらも持っていません"
                    ),
                    "核あり（core）か核なし（flow）のどちらか一方にしてください",
                )
                continue
            if circle.flow is not None:
                for j, step in enumerate(circle.flow.steps):
                    if step not in self.circles:
                        self.emit(
                            "JIN011",
                            f"{base}/flow/steps/{j}",
                            f"flow.steps の '{step}' は circle として定義されていません",
                            _hint(step, list(self.circles), "circle"),
                        )
                continue
            self._circle_names(base, circle)

    def _circle_names(self, base: str, circle: Circle) -> None:
        for key in ("state", "sigils", "rites"):
            items = getattr(circle, key)
            if len(items) > MAX_ELEMENTS:
                self.emit(
                    "JIN020",
                    f"{base}/{key}",
                    f"{key} が {len(items)} 個あります（上限 {MAX_ELEMENTS}）",
                    "別の陣に分けてください",
                )
        values: set[str] = set()  # state ∪ sigils（式の識別子）
        callables: set[str] = set()  # rites ∪ sigils（cast の target）
        for j, state in enumerate(circle.state):
            if state.name in values:
                self.emit(
                    "JIN010", f"{base}/state/{j}/name", f"state 名 '{state.name}' が重複しています"
                )
            values.add(state.name)
            self._type_ref(f"{base}/state/{j}/type", state.type)
        for j, sigil in enumerate(circle.sigils):
            if sigil.name in values or sigil.name in callables:
                self.emit(
                    "JIN010",
                    f"{base}/sigils/{j}/name",
                    f"sigil 名 '{sigil.name}' が state か別の sigil と重複しています",
                )
            values.add(sigil.name)
            callables.add(sigil.name)
            if isinstance(sigil, SigilHost):
                if abilities.namespace(sigil.host) is None:
                    self.emit(
                        "JIN205",
                        f"{base}/sigils/{j}/host",
                        f"ホスト能力の名前空間 '{sigil.host}' はありません",
                        "使えるのは " + " / ".join(ns.name for ns in abilities.NAMESPACES),
                    )
            else:
                self._summon_ref(f"{base}/sigils/{j}", sigil)
        for j, rite in enumerate(circle.rites):
            if rite.name in callables:
                self.emit(
                    "JIN010",
                    f"{base}/rites/{j}/name",
                    f"手順名 '{rite.name}' が別の手順か sigil と重複しています",
                )
            callables.add(rite.name)
            if rite.returns is not None:
                self._type_ref(f"{base}/rites/{j}/returns", rite.returns)
            for k, param in enumerate(rite.params):
                self._type_ref(f"{base}/rites/{j}/params/{k}/type", param.type)
        if circle.core not in self.rites[circle.name]:
            self.emit(
                "JIN011",
                f"{base}/core",
                f"core が指す手順 '{circle.core}' は rites にありません",
                _hint(circle.core or "", list(self.rites[circle.name]), "手順"),
            )
        for j, name in enumerate(circle.delegate):
            target = self.circles.get(name)
            if target is None or target.core is None:
                self.emit(
                    "JIN011",
                    f"{base}/delegate/{j}",
                    f"delegate の '{name}' は核あり circle として定義されていません",
                    _hint(name, [c.name for c in self.model.circles if c.core], "circle"),
                )
        if circle.boundary is not None:
            events: set[str] = set()
            for j, on in enumerate(circle.boundary.on):
                if on.event in events:
                    self.emit(
                        "JIN010",
                        f"{base}/boundary/on/{j}/event",
                        f"event '{on.event}' が重複しています",
                    )
                events.add(on.event)
                if on.rite not in self.rites[circle.name]:
                    self.emit(
                        "JIN011",
                        f"{base}/boundary/on/{j}/rite",
                        f"on の手順 '{on.rite}' は rites にありません",
                        _hint(on.rite, list(self.rites[circle.name]), "手順"),
                    )

    def _summon_ref(self, pointer: str, sigil: SigilSummon) -> None:
        target = self.circles.get(sigil.circle)
        if target is None or target.core is None:
            self.emit(
                "JIN011",
                f"{pointer}/circle",
                f"summon の circle '{sigil.circle}' は核あり circle として定義されていません",
                _hint(sigil.circle, [c.name for c in self.model.circles if c.core], "circle"),
            )
            return
        if sigil.rite not in self.rites[sigil.circle]:
            self.emit(
                "JIN011",
                f"{pointer}/rite",
                f"summon の手順 '{sigil.rite}' は '{sigil.circle}' の rites にありません",
                _hint(sigil.rite, list(self.rites[sigil.circle]), "手順"),
            )

    def _type_ref(self, pointer: str, type_text: str) -> None:
        """型文字列が指す型紙の存在（JIN011）。`list<…>` は中を辿る。"""
        head, inner = parse_type(type_text)
        while head == "list" and inner is not None:
            head, inner = parse_type(inner)
        if head in PRIMITIVE_TYPES or head in self.forms:
            return
        self.emit(
            "JIN011",
            pointer,
            f"型 '{type_text}' が指す型紙 '{head}' は定義されていません",
            _hint(head, [*PRIMITIVE_TYPES, *self.forms], "型"),
        )

    # ---------------------------------------------------------------- 2. グラフ
    def _graphs(self) -> None:
        edges: list[tuple[str, str]] = []
        parents: dict[str, list[tuple[str, str]]] = {}
        for i, circle in enumerate(self.model.circles):
            if circle.flow is not None:
                for j, step in enumerate(circle.flow.steps):
                    if step in self.circles:
                        edges.append((circle.name, step))
                        parents.setdefault(step, []).append(
                            (circle.name, f"/circles/{i}/flow/steps/{j}")
                        )
            for name in circle.delegate:
                if name in self.circles:
                    edges.append((circle.name, name))
            for sigil in circle.sigils:
                if isinstance(sigil, SigilSummon) and sigil.circle in self.circles:
                    edges.append((circle.name, sigil.circle))
        cycle = _find_cycle(edges)
        if cycle is not None:
            first = next(i for i, c in enumerate(self.model.circles) if c.name == cycle[0])
            self.emit(
                "JIN012",
                f"/circles/{first}",
                "参照が循環しています: " + " → ".join(cycle),
                "flow.steps / delegate / summon の閉路を断ってください",
            )
        for child, refs in parents.items():
            if len(refs) > 1:
                _, pointer = refs[1]
                self.emit(
                    "JIN013",
                    pointer,
                    f"circle '{child}' は複数の親を持っています: "
                    + " / ".join(parent for parent, _ in refs),
                    "flow.steps に載せる親は 1 つだけにしてください",
                )
        # 型紙の入れ子の閉路
        form_edges: list[tuple[str, str]] = []
        for form in self.model.forms:
            for f in form.fields:
                head, _inner = parse_type(f.type)
                if head != "list" and head in self.forms and head not in BUILTIN_FORMS:
                    form_edges.append((form.name, head))
        cycle = _find_cycle(form_edges)
        if cycle is not None:
            first = next(i for i, f in enumerate(self.model.forms) if f.name == cycle[0])
            self.emit(
                "JIN012",
                f"/forms/{first}",
                "型紙が自分自身を含んでいます: " + " → ".join(cycle),
                "直接の入れ子を断ってください（list<自分> は許されます）",
            )

    # ---------------------------------------------------------------- 3. 陣の中身
    def _circle_body(self, index: int, circle: Circle) -> None:
        base = f"/circles/{index}"
        sigils: dict[str, tuple[str, ...]] = {}
        for sigil in circle.sigils:
            if isinstance(sigil, SigilHost):
                sigils[sigil.name] = ("host", sigil.host)
            else:
                sigils[sigil.name] = ("summon", sigil.circle, sigil.rite)
        state_types = {s.name: s.type for s in circle.state}
        scope_base = ex.Scope(
            state=state_types,
            sigils=sigils,
            public=self.public,
            forms=self.forms,
            circle=circle.name,
            circles=frozenset(self.circles),
        )

        # state.init: 定数式（JIN250）と型
        for j, state in enumerate(circle.state):
            pointer = f"{base}/state/{j}/init"
            node = self._parse(pointer, state.init)
            if node is None:
                continue
            if not ex.is_constant(node):
                self.emit_at(
                    "JIN250",
                    pointer,
                    node.span,
                    f"state '{state.name}' の init は定数式ではありません",
                    "リテラル・型紙コンストラクタ・list・単項 - ・純関数だけで書きます",
                )
                continue
            constant = ex.Scope(forms=self.forms, circles=frozenset(self.circles), constant=True)
            self._check(pointer, node, constant, state.type)

        # 手順
        info = self.rites[circle.name]
        for j, rite in enumerate(circle.rites):
            self._rite(f"{base}/rites/{j}", circle, rite, scope_base, info[rite.name])

        # wait の到達可能性（summon 先の JIN212 は呼ぶ側で見る）
        self._propagate_waits(info)
        for j, sigil in enumerate(circle.sigils):
            if isinstance(sigil, SigilSummon):
                target = self.rites.get(sigil.circle, {}).get(sigil.rite)
                if target is not None and self._reaches_wait(sigil.circle, sigil.rite):
                    self.emit(
                        "JIN212",
                        f"{base}/sigils/{j}",
                        f"summon 先の手順 '{sigil.circle}.{sigil.rite}' は wait を含みます（陣を跨いだ待ちは不可）",
                        "相手の陣へ emit で伝え、相手の側で wait してください",
                    )

        # 境界
        if circle.boundary is not None:
            has_input = any(isinstance(s, SigilHost) and s.host == "input" for s in circle.sigils)
            for j, on in enumerate(circle.boundary.on):
                if on.event in ("key", "pointer") and not has_input:
                    self.emit(
                        "JIN230",
                        f"{base}/boundary/on/{j}",
                        f"'{on.event}' イベントを受けるには input の許可が要ります",
                        '"sigils" に {"name": "input", "kind": "host", "host": "input"} を足す',
                    )
                target = info.get(on.rite)
                if target is not None:
                    self._on_params(f"{base}/boundary/on/{j}", on.event, target)
            for j, guard in enumerate(circle.boundary.guards):
                pointer = f"{base}/boundary/guards/{j}/assert"
                node = self._parse(pointer, guard.assert_)
                if node is not None:
                    self._check(pointer, node, scope_base, "bool")

    def _on_params(self, pointer: str, event: str, rite: _RiteInfo) -> None:
        expected = EVENT_PARAMS[event]
        given = [t for _, t in rite.params]
        if event != "message" and len(given) > len(expected):
            self.emit(
                "JIN221",
                pointer,
                f"'{event}' の手順の引数が多すぎます（{len(given)} 個、最大 {len(expected)} 個）",
                f"期待する params: {_signature(expected)}",
            )
            return
        for k, (want, got) in enumerate(zip(expected, given, strict=False)):
            if want != got:
                self.emit(
                    "JIN221",
                    pointer,
                    f"'{event}' の手順の第 {k + 1} 引数は {want} です（実際 {got}）",
                    f"期待する params: {_signature(expected)}",
                )
                return

    def _collect_waits(self) -> None:
        """全陣について「wait を直接含む手順」と「自陣の手順への cast」を集め、閉包を取る。

        陣の解析順に依存させないための前処理（Main が Lib を summon していて Lib が後に並んでいても
        JIN212 が出る）。cast の target が自陣の手順名かどうかは名前だけで見る（型検査は後段）。
        """
        for circle in self.model.circles:
            info = self.rites[circle.name]
            for rite in circle.rites:
                entry = info[rite.name]
                for step in _walk_steps(rite.steps):
                    if isinstance(step, WaitStep):
                        entry.waits = True
                    elif isinstance(step, CastStep) and step.target in info:
                        entry.casts.add(step.target)
            self._propagate_waits(info)

    def _propagate_waits(self, info: dict[str, _RiteInfo]) -> None:
        changed = True
        while changed:
            changed = False
            for rite in info.values():
                if rite.waits:
                    continue
                if any(info[c].waits for c in rite.casts if c in info):
                    rite.waits = True
                    changed = True

    def _reaches_wait(self, circle: str, rite: str) -> bool:
        info = self.rites.get(circle, {})
        # 相手の陣がまだ解析されていなければ、ここで伝播させる（順序に依存しない）
        self._propagate_waits(info)
        target = info.get(rite)
        return target is not None and target.waits

    # ---------------------------------------------------------------- 手順
    def _rite(
        self, pointer: str, circle: Circle, rite: Rite, scope_base: ex.Scope, info: _RiteInfo
    ) -> None:
        scope = ex.Scope(
            locals={},
            state=scope_base.state,
            sigils=scope_base.sigils,
            public=scope_base.public,
            forms=scope_base.forms,
            circle=scope_base.circle,
            circles=scope_base.circles,
        )
        declared: dict[str, str] = {}
        for k, param in enumerate(rite.params):
            self._declare(f"{pointer}/params/{k}/name", param.name, param.type, scope, declared)
        ctx = _RiteContext(circle=circle, rite=rite, info=info, scope=scope, declared=declared)
        self._steps(f"{pointer}/steps", rite.steps, ctx, depth=0, loop_depth=0)

    def _declare(
        self, pointer: str, name: str, type_text: str | None, scope: ex.Scope, declared: dict
    ) -> None:
        if name in declared or name in scope.state or name in scope.sigils:
            self.emit(
                "JIN010",
                pointer,
                f"局所名 '{name}' が state / sigil / 他の局所と重複しています",
                "局所変数は state を隠せません。別の名前にしてください",
            )
            return
        if type_text is not None:
            declared[name] = type_text
            scope.locals[name] = type_text

    def _steps(
        self, pointer: str, steps: list[Step], ctx: _RiteContext, depth: int, loop_depth: int
    ) -> None:
        if len(steps) > MAX_STEPS:
            self.emit(
                "JIN210",
                pointer,
                f"ステップが {len(steps)} 個あります（上限 {MAX_STEPS}）",
                "手順に抽出してください（extractRite）",
            )
        terminated: str | None = None
        for k, step in enumerate(steps):
            sp = f"{pointer}/{k}"
            if terminated is not None:
                self.emit(
                    "JIN240",
                    sp,
                    f"このステップには到達しません（前の '{terminated}' で抜けています）",
                    "削除してください",
                )
                terminated = None  # 1 度だけ出す
            ends = self._step(sp, step, ctx, depth, loop_depth)
            if ends is not None:
                terminated = ends

    def _step(
        self, sp: str, step: Step, ctx: _RiteContext, depth: int, loop_depth: int
    ) -> str | None:
        """1 ステップを検査し、後続に到達しないなら抜けた語（'return' など）を返す。"""
        scope = ctx.scope
        if isinstance(step, SetStep):
            target_type = self._place(f"{sp}/target", step.target, scope)
            node = self._parse(f"{sp}/expr", step.expr)
            if node is not None:
                self._check(f"{sp}/expr", node, scope, target_type)
            return None
        if isinstance(step, LetStep):
            node = self._parse(f"{sp}/expr", step.expr)
            inferred = None
            if node is not None:
                inferred = self._check(f"{sp}/expr", node, scope, step.type)
            self._declare(f"{sp}/name", step.name, step.type or inferred, scope, ctx.declared)
            return None
        if isinstance(step, CastStep):
            self._cast(sp, step, ctx)
            return None
        if isinstance(step, IfStep):
            node = self._parse(f"{sp}/cond", step.cond)
            if node is not None:
                self._check(f"{sp}/cond", node, scope, "bool")
            if depth + 1 > MAX_NESTING:
                self.emit(
                    "JIN211",
                    sp,
                    f"入れ子が {depth + 1} 段です（上限 {MAX_NESTING}）",
                    "手順に抽出してください（extractRite）",
                )
                return None
            then_ends = self._block(f"{sp}/then", step.then, ctx, depth + 1, loop_depth)
            else_ends = self._block(f"{sp}/else", step.else_, ctx, depth + 1, loop_depth)
            if then_ends and else_ends and step.else_:
                return "if"
            return None
        if isinstance(step, LoopStep):
            self._loop_head(sp, step, scope, ctx)
            if depth + 1 > MAX_NESTING:
                self.emit(
                    "JIN211",
                    sp,
                    f"入れ子が {depth + 1} 段です（上限 {MAX_NESTING}）",
                    "手順に抽出してください（extractRite）",
                )
                return None
            self._block(f"{sp}/steps", step.steps, ctx, depth + 1, loop_depth + 1)
            return None
        if isinstance(step, BreakStep):
            if loop_depth == 0:
                self.emit("JIN213", sp, "break が loop の外にあります", "loop の中でだけ使えます")
            return "break"
        if isinstance(step, WaitStep):
            ctx.info.waits = True
            if step.ticks is not None:
                node = self._parse(f"{sp}/ticks", step.ticks)
                if node is not None:
                    self._check(f"{sp}/ticks", node, scope, "num")
            if step.until is not None:
                node = self._parse(f"{sp}/until", step.until)
                if node is not None:
                    self._check(f"{sp}/until", node, scope, "bool")
            return None
        if isinstance(step, EmitStep):
            self._emit_step(sp, step, ctx)
            return None
        if isinstance(step, ReturnStep):
            returns = ctx.rite.returns
            if step.expr is None:
                if returns is not None:
                    self.emit(
                        "JIN202",
                        sp,
                        f"手順 '{ctx.rite.name}' は {returns} を返します。return に expr が要ります",
                    )
            elif returns is None:
                self.emit(
                    "JIN213",
                    f"{sp}/expr",
                    f"手順 '{ctx.rite.name}' に returns が無いので、return に値は書けません",
                    "rites[].returns に型を書くか、expr を外してください",
                )
            else:
                node = self._parse(f"{sp}/expr", step.expr)
                if node is not None:
                    self._check(f"{sp}/expr", node, scope, returns)
            return "return"
        if isinstance(step, FinishStep):
            return "finish"
        if isinstance(step, TransferStep):
            if step.circle not in ctx.circle.delegate:
                self.emit(
                    "JIN011",
                    f"{sp}/circle",
                    f"transfer の '{step.circle}' は delegate にありません",
                    _hint(step.circle, list(ctx.circle.delegate), "delegate"),
                )
            return "transfer"
        raise TypeError(type(step).__name__)  # pragma: no cover

    def _block(
        self, pointer: str, steps: list[Step], ctx: _RiteContext, depth: int, loop_depth: int
    ) -> bool:
        """ブロックを検査し、ブロックが必ず抜ける（最後が終端）なら True。"""
        if len(steps) > MAX_STEPS:
            self.emit(
                "JIN210",
                pointer,
                f"ステップが {len(steps)} 個あります（上限 {MAX_STEPS}）",
                "手順に抽出してください（extractRite）",
            )
        terminated: str | None = None
        ends = False
        for k, step in enumerate(steps):
            sp = f"{pointer}/{k}"
            if terminated is not None:
                self.emit(
                    "JIN240",
                    sp,
                    f"このステップには到達しません（前の '{terminated}' で抜けています）",
                    "削除してください",
                )
                terminated = None
            word = self._step(sp, step, ctx, depth, loop_depth)
            ends = word is not None
            if word is not None:
                terminated = word
        return ends

    def _loop_head(self, sp: str, step: LoopStep, scope: ex.Scope, ctx: _RiteContext) -> None:
        if step.kind == "each":
            node = self._parse(f"{sp}/in", step.in_ or "")
            item = None
            if node is not None:
                list_type = self._check(f"{sp}/in", node, scope, None)
                if list_type is not None:
                    item = ex.item_type(list_type) if ex.is_list(list_type) else None
                    if item is None or item == "?":
                        self.emit_at(
                            "JIN202",
                            f"{sp}/in",
                            node.span,
                            f"each の in は list です（実際 {list_type}）",
                        )
                        item = None
            self._declare(f"{sp}/name", step.name or "", item, scope, ctx.declared)
        elif step.kind == "while":
            node = self._parse(f"{sp}/cond", step.cond or "")
            if node is not None:
                self._check(f"{sp}/cond", node, scope, "bool")
        else:
            node = self._parse(f"{sp}/times", step.times or "")
            if node is not None:
                self._check(f"{sp}/times", node, scope, "num")
            if step.name is not None:
                self._declare(f"{sp}/name", step.name, "num", scope, ctx.declared)

    def _place(self, pointer: str, text: str, scope: ex.Scope) -> str | None:
        """代入先（set.target / cast.into）。形と根を見て型を返す。"""
        node = self._parse(pointer, text)
        if node is None:
            return None
        if not ex.is_place(node):
            self.emit_at(
                "JIN202",
                pointer,
                node.span,
                "代入先は 名前 / 代入先.欄 / 代入先[添字] の形です",
            )
            return None
        root = ex.place_root(node)
        if root is None:  # pragma: no cover - is_place が True なら根は Name
            return None
        if root.name not in scope.locals and root.name not in scope.state:
            if root.name in scope.circles:
                self.emit_at(
                    "JIN203",
                    pointer,
                    root.span,
                    f"他の陣の state '{root.name}.…' には書けません",
                    "自陣の state か局所変数にだけ代入できます",
                )
                return None
            near = close_names(root.name, [*scope.locals, *scope.state])
            self.emit_at(
                "JIN203",
                pointer,
                root.span,
                f"代入先 '{root.name}' は state にも局所にもありません",
                f"近い名前: {' / '.join(near)}" if near else None,
            )
            return None
        return self._check(pointer, node, scope, None)

    def _cast(self, sp: str, step: CastStep, ctx: _RiteContext) -> None:
        scope = ctx.scope
        parts = step.target.split(".")
        if not all(_is_name(p) for p in parts) or len(parts) > 2:
            self.emit(
                "JIN202",
                f"{sp}/target",
                f"cast の target '{step.target}' は 名前 か 名前.メンバ の形です",
            )
            for a in step.args:
                node = self._parse(f"{sp}/args/0", a)
                del node
            return
        params: list[str] | None = None
        returns: str | None = None
        generic = False
        if len(parts) == 1:
            name = parts[0]
            own = ctx.info if name == ctx.rite.name else self.rites[ctx.circle.name].get(name)
            if own is not None:
                ctx.info.casts.add(name)
                params = [t for _, t in own.params]
                returns = own.returns
            elif name in scope.sigils and scope.sigils[name][0] == "summon":
                _, target_circle, target_rite = scope.sigils[name]
                target = self.rites.get(target_circle, {}).get(target_rite)
                if target is None:
                    return  # JIN011 は名前表で出ている
                params = [t for _, t in target.params]
                returns = target.returns
            elif name in scope.sigils:
                self.emit(
                    "JIN202",
                    f"{sp}/target",
                    f"'{name}' は名前空間です。'{name}.メンバ' の形で呼びます",
                )
                return
            elif name in ex.EFFECTS:
                generic = True
            else:
                candidates = [*self.rites[ctx.circle.name], *scope.sigils, *ex.EFFECTS]
                self.emit(
                    "JIN011",
                    f"{sp}/target",
                    f"cast の target '{name}' は手順にも道具環にもありません",
                    _hint(name, candidates, "手順"),
                )
                return
        else:
            ns_name, member_name = parts
            sigil = scope.sigils.get(ns_name)
            if sigil is None:
                if abilities.namespace(ns_name) is not None:
                    self.emit(
                        "JIN204",
                        f"{sp}/target",
                        f"名前空間 '{ns_name}' は道具環で許可されていません",
                        f'sigils に {{"name": "{ns_name}", "kind": "host", "host": "{ns_name}"}} を足す',
                    )
                else:
                    self.emit(
                        "JIN011",
                        f"{sp}/target",
                        f"'{ns_name}' は道具環にありません",
                        _hint(ns_name, list(scope.sigils), "sigil"),
                    )
                return
            if sigil[0] != "host":
                self.emit(
                    "JIN202",
                    f"{sp}/target",
                    f"summon '{ns_name}' にメンバはありません。'{ns_name}' だけで呼びます",
                )
                return
            namespace = abilities.namespace(sigil[1])
            if namespace is None:
                return  # JIN205 は名前表で出ている
            member = namespace.member(member_name)
            if member is None:
                self.emit(
                    "JIN205",
                    f"{sp}/target",
                    f"{namespace.name} にメンバ '{member_name}' はありません",
                    _hint(member_name, [m.name for m in namespace.members], "メンバ"),
                )
                return
            params = [t for _, t in member.params]
            returns = member.returns
            self._asset_ref(sp, namespace.name, member.name, step.args)

        arg_types: list[str | None] = []
        for k, text in enumerate(step.args):
            node = self._parse(f"{sp}/args/{k}", text)
            want = params[k] if params is not None and k < len(params) else None
            arg_types.append(self._check(f"{sp}/args/{k}", node, scope, want) if node else None)
        if generic:
            returns = self._effect(sp, step, arg_types)
        elif params is not None and len(step.args) != len(params):
            self.emit(
                "JIN205" if len(parts) == 2 else "JIN202",
                f"{sp}/args" if step.args else sp,
                f"引数は {len(params)} 個です（実際 {len(step.args)} 個）",
                f"期待: ({', '.join(params)})",
            )
        if step.into is not None:
            if returns is None:
                self.emit(
                    "JIN202",
                    f"{sp}/into",
                    f"'{step.target}' は値を返しません。into は書けません",
                )
                return
            target_type = self._place(f"{sp}/into", step.into, scope)
            if target_type is not None and not ex.assignable(returns, target_type):
                self.emit(
                    "JIN202",
                    f"{sp}/into",
                    f"into の型が合いません: 期待 {returns}、実際 {target_type}",
                )

    def _effect(self, sp: str, step: CastStep, arg_types: list[str | None]) -> None:
        name = step.target
        want = len(ex.EFFECTS[name][0])
        if len(step.args) != want:
            self.emit("JIN202", sp, f"{name} の引数は {want} 個です（実際 {len(step.args)} 個）")
            return
        first = arg_types[0]
        if first is not None and not ex.is_list(first):
            self.emit("JIN202", f"{sp}/args/0", f"{name} の第 1 引数は list です（実際 {first}）")
            return
        if name == "push" and first is not None:
            inner = ex.item_type(first)
            got = arg_types[1]
            if inner not in (None, "?") and got is not None and not ex.assignable(got, inner):
                self.emit(
                    "JIN202", f"{sp}/args/1", f"push の第 2 引数は {inner} です（実際 {got}）"
                )
        if name == "removeAt" and arg_types[1] not in (None, "num"):
            self.emit("JIN202", f"{sp}/args/1", "removeAt の第 2 引数は num です")
        return

    def _asset_ref(self, sp: str, namespace: str, member: str, args: list[str]) -> None:
        kind = {("canvas", "sprite"): "sprite", ("audio", "play"): "sound"}.get((namespace, member))
        if kind is None or not args:
            return
        node = self._parse(f"{sp}/args/0", args[0], quiet=True)
        if isinstance(node, ex.String):
            names = [a.name for a in self.model.stage.assets if a.kind == kind]
            if node.value not in names:
                self.emit_at(
                    "JIN205",
                    f"{sp}/args/0",
                    node.span,
                    f"アセット '{node.value}'（{kind}）は stage.assets にありません",
                    _hint(node.value, names, "アセット"),
                )

    def _emit_step(self, sp: str, step: EmitStep, ctx: _RiteContext) -> None:
        target = self.circles.get(step.circle)
        if target is None or target.core is None:
            self.emit(
                "JIN011",
                f"{sp}/circle",
                f"emit の circle '{step.circle}' は核あり circle として定義されていません",
                _hint(step.circle, [c.name for c in self.model.circles if c.core], "circle"),
            )
            for k, text in enumerate(step.args):
                node = self._parse(f"{sp}/args/{k}", text)
                if node is not None:
                    self._check(f"{sp}/args/{k}", node, ctx.scope, None)
            return
        handler: _RiteInfo | None = None
        if target.boundary is not None:
            for on in target.boundary.on:
                if on.event == "message":
                    handler = self.rites[target.name].get(on.rite)
        expected = [t for _, t in handler.params[1:]] if handler is not None else None
        for k, text in enumerate(step.args):
            node = self._parse(f"{sp}/args/{k}", text)
            want = expected[k] if expected is not None and k < len(expected) else None
            if node is not None:
                self._check(f"{sp}/args/{k}", node, ctx.scope, want)
        if expected is not None and len(step.args) != len(expected):
            self.emit(
                "JIN202",
                sp,
                f"'{step.circle}' の message の手順は引数 {len(expected)} 個です（実際 {len(step.args)} 個）",
            )

    # ---------------------------------------------------------------- 4. flow
    def _flow(self, index: int, circle: Circle) -> None:
        flow = circle.flow
        if flow is None or flow.exit is None:
            return
        pointer = f"/circles/{index}/flow/exit"
        node = self._parse(pointer, flow.exit)
        if node is None:
            return
        scope = ex.Scope(
            public=self.public, forms=self.forms, circles=frozenset(self.circles), exit_mode=True
        )
        self._check(pointer, node, scope, "bool")

    # ---------------------------------------------------------------- 式の共通処理
    def _parse(self, pointer: str, text: str, quiet: bool = False) -> ex.Node | None:
        try:
            return ex.parse_expr(text)
        except ex.ExprSyntaxError as exc:
            if not quiet:
                self.emit_at("JIN201", pointer, exc.span, exc.message, exc.hint)
            return None

    def _check(
        self, pointer: str, node: ex.Node, scope: ex.Scope, expected: str | None
    ) -> str | None:
        result = ex.check_expr(node, scope, expected)
        for issue in result.issues:
            self.emit_at(issue.code, pointer, issue.span, issue.message, issue.hint)
        self.nodes[pointer] = node
        return result.type


@dataclass(slots=True)
class _RiteContext:
    circle: Circle
    rite: Rite
    info: _RiteInfo
    scope: ex.Scope
    declared: dict[str, str]


def _walk_steps(steps: list[Step]):
    """ステップを深さ優先で列挙する（if / loop の中を含む）。"""
    for step in steps:
        yield step
        if isinstance(step, IfStep):
            yield from _walk_steps(step.then)
            yield from _walk_steps(step.else_)
        elif isinstance(step, LoopStep):
            yield from _walk_steps(step.steps)


def _is_name(text: str) -> bool:
    return (
        bool(text)
        and (text[0].isalpha() or text[0] == "_")
        and all(c.isalnum() or c == "_" for c in text)
        and text.isascii()
    )


def _signature(types: tuple[str, ...]) -> str:
    return "(" + ", ".join(types) + ")"


def _hint(target: str, candidates: list[str], noun: str) -> str:
    near = close_names(target, candidates)
    if near:
        return "近い名前: " + " / ".join(near)
    if candidates:
        return f"定義済みの{noun}: " + " / ".join(candidates[:12])
    return f"{noun}が 1 つも定義されていません"


def analyze(
    model: JinFileV2, table: PointerTable, file: str, *, source: str | None = None
) -> list[Diagnostic]:
    """v2 の意味検査。`source` は原文（式内の位置をリテラル内の列へ写すため。無ければリテラル全体）。"""
    analyzer = _Analyzer(model, table, file, source)
    analyzer.run()
    return _sorted(analyzer.out)


def typed_nodes(model: JinFileV2) -> tuple[dict[str, ex.Node], list[Diagnostic]]:
    """全ての式の型注記付き AST（pointer → Node）と、その際の診断を返す。

    `rename` の型紙欄追随（docs/spec/v2/ops.md §3）が使う。位置情報は要らないので、
    対応表は空（診断の range はルートに落ちる）。
    """
    table = PointerTable(value_ranges={"": Range(Position(1, 1), Position(1, 1))})
    analyzer = _Analyzer(model, table, "<memory>", None)
    analyzer.run()
    return analyzer.nodes, analyzer.out


#: hint を個別に書いていない診断に付ける既定の直し方（要件書 §5「hint は具体的な値」の最低限）。
_FALLBACK_HINTS: dict[str, str] = {
    "JIN010": "別の名前に変えてください",
    "JIN011": "定義を追加するか、名前を直してください",
    "JIN202": "型を合わせてください（docs/spec/v2/expr.md §2）",
    "JIN203": "名前を確認してください",
    "JIN205": "docs/spec/v2/abilities.md のカタログを確認してください",
    "JIN213": "ステップの置き場所を見直してください",
}


def _fallback_hint(code: str) -> str:
    return _FALLBACK_HINTS.get(code, "docs/spec/v2/diagnostics.md を参照")


__all__ = ["BUILTIN_FORMS", "EVENT_PARAMS", "MAX_NESTING", "MAX_STEPS", "analyze", "typed_nodes"]
