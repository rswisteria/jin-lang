/**
 * トレース行 → 光らせる pointer（docs/spec/v2/stage.md §3.1）。
 *
 * 名前の表の形はエディタの `apps/editor/src/stage/names.ts` と同じ（apps 同士は import しないので
 * ここに同じ形を書く。形の一致は e2e が実物の往復で見る）。
 */
export interface CircleNames {
	readonly pointer: string;
	readonly sigils: Readonly<Record<string, string>>;
	readonly state: Readonly<Record<string, string>>;
	readonly delegates: Readonly<Record<string, string>>;
}

export type StageNames = Readonly<Record<string, CircleNames>>;

/** runtime.md §5 のトレース行のうち、stage が読む欄。 */
export interface TraceRow {
	readonly seq: number;
	readonly tick: number;
	readonly circle: string;
	readonly kind: string;
	readonly name?: string | null;
	readonly pointer: string;
	readonly output?: unknown;
}

export interface Targets {
	/** 光らせる要素。 */
	readonly primary: string;
	/** 光線などの出どころ（無ければ null）。 */
	readonly source: string | null;
}

export function riteOf(pointer: string): string | null {
	return /^\/circles\/\d+\/rites\/\d+/.exec(pointer)?.[0] ?? null;
}

export function resolveTargets(
	row: TraceRow,
	names: StageNames,
): Targets | null {
	if (row.kind === "frame") return null;
	if (row.kind === "wait" && row.output !== "suspend") return null;
	const circle = names[row.circle];
	const name = typeof row.name === "string" ? row.name : "";
	if (row.kind === "cast") {
		const sigil = circle?.sigils[name.split(".")[0] ?? ""];
		if (sigil !== undefined)
			return { primary: sigil, source: riteOf(row.pointer) };
	} else if (row.kind === "set") {
		const state = circle?.state[name];
		if (state !== undefined) return { primary: state, source: null };
	} else if (row.kind === "transfer") {
		const delegate = circle?.delegates[name];
		if (delegate !== undefined)
			return { primary: delegate, source: riteOf(row.pointer) };
	}
	return { primary: row.pointer, source: null };
}

/** `/` 区切りの段で祖先へ遡り、最初に場面にある pointer（overlay の規則 1 と同じ段一致）。 */
export function nearestInScene(
	pointers: ReadonlySet<string>,
	pointer: string,
): string | null {
	let current = pointer;
	while (current !== "") {
		if (pointers.has(current)) return current;
		current = current.slice(0, current.lastIndexOf("/"));
	}
	return null;
}
