import { circleOf, type StageNames, type TraceRow } from "./names";
import { mulberry32 } from "./random";

/**
 * 色の意味体系（仕様書 docs/superpowers/specs/2026-10-01-jin-stage-gem-worldview-design.md §2・
 * docs/spec/v2/stage.md §2.1）。**表は stage.md の `stage-gems` / `stage-state-gems` / `stage-metals` と等号**
 * （`tests/contract/test_stage_contract.py`）。three を import しない純関数。
 *
 * 引けない名前・欄の無い古い表は例外を投げず金（§2.5）。
 */
export type GemId =
	| "sapphire"
	| "emerald"
	| "peridot"
	| "amethyst"
	| "opal"
	| "amber"
	| "moonstone"
	| "gold"
	| "topaz"
	| "diamond"
	| "ruby"
	| "garnet"
	| "citrine"
	| "aquamarine"
	| "pearl"
	| "onyx"
	| "tourmaline"
	| "spinel"
	| "crystal";

export interface GemSpec {
	readonly color: number;
	readonly ior: number;
	/** 2 色目（トルマリンのグラデーションの先・オニキスの光の銀）。 */
	readonly color2?: number;
}

export const GEMS: Readonly<Record<GemId, GemSpec>> = {
	sapphire: { color: 0x2f6bff, ior: 1.77 },
	emerald: { color: 0x1fd47a, ior: 1.58 },
	peridot: { color: 0xa8e83a, ior: 1.67 },
	amethyst: { color: 0xa05cff, ior: 1.54 },
	opal: { color: 0xd8e8f0, ior: 1.45 },
	amber: { color: 0xffa62b, ior: 1.54 },
	moonstone: { color: 0xcfe3ff, ior: 1.52 },
	gold: { color: 0xffd27a, ior: 1.5 },
	topaz: { color: 0xff8a3d, ior: 1.62 },
	diamond: { color: 0xffffff, ior: 2.42 },
	ruby: { color: 0xff2a4a, ior: 1.77 },
	garnet: { color: 0xb0102a, ior: 1.79 },
	citrine: { color: 0xffc83a, ior: 1.55 },
	aquamarine: { color: 0x5fd8e8, ior: 1.58 },
	pearl: { color: 0xf4f0e8, ior: 1.53 },
	onyx: { color: 0x14141a, ior: 1.54, color2: 0xc8ccd8 },
	tourmaline: { color: 0x3ad08a, ior: 1.62, color2: 0xff7aa8 },
	spinel: { color: 0xff3a7a, ior: 1.72 },
	crystal: { color: 0xe8f0ff, ior: 1.54 },
};

/** 力（host の名前空間 / "summon" / "agent"）→ 宝玉。 */
export const POWER_GEMS: Readonly<Record<string, GemId>> = {
	canvas: "sapphire",
	input: "emerald",
	ui: "peridot",
	audio: "amethyst",
	random: "opal",
	storage: "amber",
	agent: "moonstone",
	summon: "gold",
};

export type MetalId = "yellow" | "rose" | "white" | "platinum";

export interface MetalSpec {
	readonly color: number;
	readonly roughness: number;
}

export const METALS: Readonly<Record<MetalId, MetalSpec>> = {
	yellow: { color: 0xd4a24a, roughness: 0.3 },
	rose: { color: 0xd68a6e, roughness: 0.32 },
	white: { color: 0xd8d4c8, roughness: 0.28 },
	platinum: { color: 0xb8bcc4, roughness: 0.24 },
};

/** root 以外の陣が並び順に巡る地金。 */
export const METAL_CYCLE: readonly MetalId[] = ["rose", "white", "platinum"];

const LIST_TYPE = /^list</;

export function stateGem(type: string | undefined): GemId {
	if (type === undefined || type === "") return "gold";
	if (type === "num") return "citrine";
	if (type === "str") return "aquamarine";
	if (type === "bool") return "pearl";
	if (LIST_TYPE.test(type)) return "tourmaline";
	return "spinel";
}

function circleIndex(pointer: string): number | null {
	const match = /^\/circles\/(\d+)$/.exec(pointer);
	return match === null ? null : Number(match[1]);
}

/** 陣の地金。root は yellow、他は root を除いた並び順で `METAL_CYCLE` を巡る。陣に属さない要素（null）は root の地金。 */
export function metalOf(
	circlePointer: string | null,
	names: StageNames,
): MetalId {
	if (circlePointer === null) return "yellow";
	const index = circleIndex(circlePointer);
	if (index === null) return "yellow";
	let root: number | null = null;
	for (const circle of Object.values(names)) {
		if (circle.isRoot === true) root = circleIndex(circle.pointer);
	}
	if (root === index) return "yellow";
	const rank = root !== null && index > root ? index - 1 : index;
	return METAL_CYCLE[rank % METAL_CYCLE.length] ?? "rose";
}

const EVENT_GEMS: Readonly<Record<string, GemId>> = {
	key: "emerald",
	pointer: "emerald",
	message: "diamond",
};

const KIND_GEMS: Readonly<Record<string, GemId>> = {
	transfer: "topaz",
	emit: "diamond",
	assert: "ruby",
	error: "garnet",
};

/** トレースの行 → 光の宝玉（§2.1 / §2.2 / §5.1）。 */
export function gemOfRow(row: TraceRow, names: StageNames): GemId {
	const circle = row.circle === null ? undefined : names[row.circle];
	const name = typeof row.name === "string" ? row.name : "";
	if (row.kind === "cast") {
		const dot = name.indexOf(".");
		if (dot < 0) return "gold";
		const kind = circle?.sigilKinds?.[name.slice(0, dot)];
		return (kind === undefined ? undefined : POWER_GEMS[kind]) ?? "gold";
	}
	if (row.kind === "set") {
		const gem = stateGem(circle?.stateTypes?.[name]);
		return gem === "pearl" && row.output === false ? "onyx" : gem;
	}
	if (row.kind === "event") return EVENT_GEMS[name] ?? "gold";
	return KIND_GEMS[row.kind] ?? "gold";
}

function nameAt(
	table: Readonly<Record<string, string>>,
	pointer: string,
): string | undefined {
	for (const [name, at] of Object.entries(table))
		if (at === pointer) return name;
	return undefined;
}

const FIXED_ELEMENT_GEMS: Readonly<Record<string, GemId>> = {
	core: "diamond",
	on: "crystal",
	guard: "ruby",
	delegate: "topaz",
};

/** 場面の要素にはめる宝玉（§3.1）。宝玉をはめない種別は null。 */
export function gemOfElement(
	kind: string,
	pointer: string,
	names: StageNames,
): GemId | null {
	const fixed = FIXED_ELEMENT_GEMS[kind];
	if (fixed !== undefined) return fixed;
	if (kind !== "sigil" && kind !== "state") return null;
	const circlePointer = circleOf(pointer);
	const circle = Object.values(names).find((c) => c.pointer === circlePointer);
	if (circle === undefined) return "gold";
	if (kind === "sigil") {
		const name = nameAt(circle.sigils, pointer);
		const power = name === undefined ? undefined : circle.sigilKinds?.[name];
		return (power === undefined ? undefined : POWER_GEMS[power]) ?? "gold";
	}
	const name = nameAt(circle.state, pointer);
	return stateGem(name === undefined ? undefined : circle.stateTypes?.[name]);
}

/** オパールの遊色の巡る速さ（周 / 秒）。 */
const OPAL_CYCLES_PER_SECOND = 0.15;

function hslToHex(h: number, s: number, l: number): number {
	const k = (n: number): number => (n + h * 12) % 12;
	const a = s * Math.min(l, 1 - l);
	const f = (n: number): number =>
		l - a * Math.max(-1, Math.min(k(n) - 3, 9 - k(n), 1));
	const byte = (v: number): number => Math.round(v * 255);
	return (byte(f(0)) << 16) | (byte(f(8)) << 8) | byte(f(4));
}

/** 時刻 `seconds` の宝玉の色（0xRRGGBB）。オパールだけが時刻と `seq` で巡る。 */
export function gemColorAt(gem: GemId, seconds: number, seq: number): number {
	if (gem !== "opal") return GEMS[gem].color;
	const hue =
		(((seconds * OPAL_CYCLES_PER_SECOND + mulberry32(seq)()) % 1) + 1) % 1;
	return hslToHex(hue, 0.6, 0.7);
}
