/**
 * 鑑賞ページに渡す名前の表（docs/spec/v2/stage.md §6）。
 *
 * トレースの `cast` / `set` / `transfer` の行は名前しか持たないので、どの紋・四角・小円を
 * 光らせるかは SVG だけでは決まらない。モデルから「名前 → pointer」を作って添える。
 * **配置は含まない**（座標は SVG が唯一の元）。
 */
export interface CircleNames {
	readonly pointer: string;
	readonly sigils: Readonly<Record<string, string>>;
	readonly state: Readonly<Record<string, string>>;
	readonly delegates: Readonly<Record<string, string>>;
	/**
	 * 宝玉の色の鍵（仕様書 docs/superpowers/specs/2026-10-01-jin-stage-gem-worldview-design.md §4）。
	 * sigil 名 → host の名前空間名（`kind == "host"`）/ それ以外は `kind`（"summon" / "agent"）。
	 */
	readonly sigilKinds: Readonly<Record<string, string>>;
	/** state 名 → 型の文字列そのまま（解釈は stage の `palette.ts`）。 */
	readonly stateTypes: Readonly<Record<string, string>>;
	/** root の陣だけ true（地金の決定に使う）。他の陣は欄ごと省く。 */
	readonly isRoot?: true;
}

export type StageNames = Readonly<Record<string, CircleNames>>;

export function buildStageNames(
	model: Readonly<Record<string, unknown>>,
): StageNames {
	const circles = model["circles"];
	if (!Array.isArray(circles)) return {};
	const table: Record<string, CircleNames> = {};
	circles.forEach((circle: unknown, i) => {
		if (!isRecord(circle) || typeof circle["name"] !== "string") return;
		const pointer = `/circles/${String(i)}`;
		table[circle["name"]] = {
			pointer,
			sigils: named(circle["sigils"], `${pointer}/sigils`),
			state: named(circle["state"], `${pointer}/state`),
			delegates: listed(circle["delegate"], `${pointer}/delegate`),
			sigilKinds: fieldOf(circle["sigils"], (entry) =>
				entry["kind"] === "host" ? entry["host"] : entry["kind"],
			),
			stateTypes: fieldOf(circle["state"], (entry) => entry["type"]),
			...(circle["name"] === model["root"] ? { isRoot: true as const } : {}),
		};
	});
	return table;
}

/** 名前を持つ要素の配列 → 名前 → 欄の値（文字列のときだけ）。 */
function fieldOf(
	list: unknown,
	pick: (entry: Record<string, unknown>) => unknown,
): Record<string, string> {
	const out: Record<string, string> = {};
	if (!Array.isArray(list)) return out;
	for (const entry of list) {
		if (!isRecord(entry) || typeof entry["name"] !== "string") continue;
		const value = pick(entry);
		if (typeof value === "string") out[entry["name"]] = value;
	}
	return out;
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return value !== null && typeof value === "object" && !Array.isArray(value);
}

function named(list: unknown, base: string): Record<string, string> {
	const out: Record<string, string> = {};
	if (!Array.isArray(list)) return out;
	list.forEach((entry: unknown, j) => {
		if (isRecord(entry) && typeof entry["name"] === "string")
			out[entry["name"]] = `${base}/${String(j)}`;
	});
	return out;
}

function listed(list: unknown, base: string): Record<string, string> {
	const out: Record<string, string> = {};
	if (!Array.isArray(list)) return out;
	list.forEach((entry: unknown, j) => {
		if (typeof entry === "string") out[entry] = `${base}/${String(j)}`;
	});
	return out;
}
