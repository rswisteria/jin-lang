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
		};
	});
	return table;
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
