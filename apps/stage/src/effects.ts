import {
	circleOf,
	resolveTargets,
	type StageNames,
	type TraceRow,
} from "./names";
import { type GemId, gemOfRow } from "./palette";

/**
 * 演出（docs/spec/v2/stage.md §3）。**表は stage.md の `stage-effects` と等号**
 * （`tests/contract/test_stage_contract.py`）。
 */
export type EffectName =
	| "ignite"
	| "fade"
	| "chant"
	| "spin"
	| "beam"
	| "flash"
	| "release"
	| "flow"
	| "breathe"
	| "crown"
	| "warn"
	| "crack"
	| "pulse";
/** `beat` は常に `BEAT`（慣れの対象外・仕様書 2026-10-01 §5.1 の `frame`）。 */
export type Strength = "once" | "habit" | "beat";

export const EFFECTS: Readonly<
	Record<
		string,
		{ readonly effect: EffectName | null; readonly strength: Strength }
	>
> = {
	enter: { effect: "ignite", strength: "once" },
	exit: { effect: "fade", strength: "once" },
	event: { effect: "chant", strength: "habit" },
	rite: { effect: "spin", strength: "habit" },
	cast: { effect: "beam", strength: "habit" },
	set: { effect: "flash", strength: "habit" },
	emit: { effect: "release", strength: "once" },
	transfer: { effect: "flow", strength: "once" },
	wait: { effect: "breathe", strength: "habit" },
	finish: { effect: "crown", strength: "once" },
	assert: { effect: "warn", strength: "once" },
	error: { effect: "crack", strength: "once" },
	frame: { effect: "pulse", strength: "beat" },
};

/**
 * 陣全体に効く演出（設計書 §2.3「陣全体が光る / 暗くなる」）。光らせる先は行の pointer の**陣**
 * （`/circles/i`）で、その配下すべてが光る。`finish` / `error` の行はステップの pointer を持つので
 * （runtime.md §5）、陣に上げないと手順の部分木だけが光る。
 */
export const WHOLE_CIRCLE: ReadonlySet<EffectName> = new Set<EffectName>([
	"ignite",
	"fade",
	"crown",
	"crack",
]);

/** 発火の光らせる先。陣全体の演出は行の pointer の陣、それ以外は §3.1 の解決のまま。 */
export function glowTarget(effect: EffectName, primary: string): string {
	return WHOLE_CIRCLE.has(effect) ? (circleOf(primary) ?? primary) : primary;
}

/** 繰り返しが落ち着く明るさ。 */
export const HUM = 0.15;
/** この回数連続したら HUM に落ちる。 */
export const HABIT_AFTER = 3;
/** `frame` の鼓動の強さ（陣の鼓動であって発動の演出ではない）。 */
export const BEAT = 0.1;
/** `frame` 行が光らせる先（額縁）。行の `circle` は null（runtime.md §5）。 */
export const PULSE_TARGET = "/stage";

export const DURATION_SECONDS: Readonly<Record<EffectName, number>> = {
	ignite: 2.4,
	fade: 1.6,
	chant: 1.0,
	spin: 0.9,
	beam: 0.8,
	flash: 0.8,
	release: 1.4,
	flow: 1.2,
	breathe: 1.5,
	crown: 3.2,
	warn: 1.4,
	crack: 2.0,
	pulse: 0.5,
};

const LONGEST_SECONDS = Math.max(...Object.values(DURATION_SECONDS));
/** 包絡の頂点の位置（stage.md §3.3）。 */
const ATTACK = 0.15;

export interface Firing {
	readonly seq: number;
	/** tick 単位の時刻（boot の行の −1 は 0）。 */
	readonly time: number;
	readonly kind: string;
	readonly effect: EffectName;
	readonly target: string;
	readonly source: string | null;
	/**
	 * 銘環の帯で灯す pointer（陣書き S7・stage.md §2.2）。行の pointer（実行したステップ・手順・陣）で、
	 * 陣全体の演出は陣へ上げる。`target` は名前の表で引いた先（`cast` なら sigil）なので帯には使わない。
	 */
	readonly inscribed: string;
	readonly strength: number;
	/** 光の宝玉（仕様書 2026-10-01 §2。`palette.ts` の `gemOfRow`）。 */
	readonly gem: GemId;
}

export interface Glow {
	readonly seq: number;
	readonly target: string;
	readonly source: string | null;
	readonly inscribed: string;
	readonly effect: EffectName;
	readonly gem: GemId;
	readonly intensity: number;
	/** 0 以上 1 未満の進み。 */
	readonly progress: number;
}

/** 行の並び（seq 順）のまま畳み込む。同じ入力なら同じ出力。 */
export function foldTrace(
	rows: readonly TraceRow[],
	names: StageNames,
): readonly Firing[] {
	const streaks = new Map<string, { tick: number; count: number }>();
	const values = new Map<string, string>();
	const firings: Firing[] = [];
	for (const row of rows) {
		const spec = EFFECTS[row.kind];
		if (spec === undefined || spec.effect === null) continue;
		if (spec.strength === "beat") {
			// frame: 陣の鼓動。行の circle は null で名前の表を引けないので、額縁を BEAT で（慣れの対象外）。
			firings.push({
				seq: row.seq,
				time: Math.max(row.tick, 0),
				kind: row.kind,
				effect: spec.effect,
				target: PULSE_TARGET,
				source: null,
				inscribed: PULSE_TARGET,
				strength: BEAT,
				gem: "gold",
			});
			continue;
		}
		const targets = resolveTargets(row, names);
		if (targets === null) continue;
		const time = Math.max(row.tick, 0);
		const target = glowTarget(spec.effect, targets.primary);
		const key = `${spec.effect}|${target}`;
		const previous = streaks.get(key);
		const count =
			previous === undefined
				? 0
				: time === previous.tick
					? previous.count
					: time - previous.tick <= 1
						? previous.count + 1
						: 0;
		streaks.set(key, { tick: time, count });
		let strength =
			spec.strength === "once"
				? 1
				: count >= HABIT_AFTER
					? HUM
					: 1 - (count * (1 - HUM)) / HABIT_AFTER;
		if (row.kind === "set") {
			const valueKey = `${row.circle}|${row.name ?? ""}`;
			const value = JSON.stringify(row.output) ?? "undefined";
			if (values.get(valueKey) === value) strength = HUM;
			values.set(valueKey, value);
		}
		firings.push({
			seq: row.seq,
			time,
			kind: row.kind,
			effect: spec.effect,
			target,
			source: targets.source,
			inscribed: glowTarget(spec.effect, row.pointer),
			strength,
			gem: gemOfRow(row, names),
		});
	}
	return firings;
}

/** 時刻 `t`（tick 単位の実数）に光っているもの。`firings` は時刻の昇順（`foldTrace` の出力）。 */
export function glowsAt(
	firings: readonly Firing[],
	t: number,
	fps: number,
): readonly Glow[] {
	const glows: Glow[] = [];
	for (let i = firings.length - 1; i >= 0; i--) {
		const firing = firings[i];
		if (firing === undefined) continue;
		const ageSeconds = (t - firing.time) / fps;
		if (ageSeconds > LONGEST_SECONDS) break;
		if (ageSeconds < 0) continue;
		const progress = ageSeconds / DURATION_SECONDS[firing.effect];
		if (progress >= 1) continue;
		const envelope =
			progress < ATTACK
				? progress / ATTACK
				: 1 - (progress - ATTACK) / (1 - ATTACK);
		glows.push({
			seq: firing.seq,
			target: firing.target,
			source: firing.source,
			inscribed: firing.inscribed,
			effect: firing.effect,
			gem: firing.gem,
			intensity: firing.strength * envelope,
			progress,
		});
	}
	return glows.reverse();
}

export function tickSpan(rows: readonly TraceRow[]): {
	readonly first: number;
	readonly last: number;
} {
	if (rows.length === 0) return { first: 0, last: 0 };
	let first = Number.POSITIVE_INFINITY;
	let last = 0;
	for (const row of rows) {
		const time = Math.max(row.tick, 0);
		first = Math.min(first, time);
		last = Math.max(last, time);
	}
	return { first, last };
}
