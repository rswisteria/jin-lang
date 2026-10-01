import type { Glow } from "./effects";
import { arcPoint, type Vec3 } from "./motion";
import { GEMS, type GemId, gemColorAt } from "./palette";
import { mulberry32 } from "./random";

/**
 * 粒子の置き方（仕様書 docs/superpowers/specs/2026-10-01-jin-stage-gem-worldview-design.md §5.1 / §6）。
 * three を import しない純関数。座標は金細工の root の局所座標（陣は xy 面・z が上）。
 * 乱数は発火の `seq`（漂う粒子は固定の種）の mulberry32 だけ。
 */
export const MAX_PARTICLES = 4096;
/** 粒子 1 つの既定の大きさ。 */
const SIZE = 0.012;

export interface Particle {
	readonly position: Vec3;
	readonly color: number;
	readonly size: number;
	readonly alpha: number;
}

/** 発火ごとの粒子の数。 */
const COUNTS = {
	chant: 24,
	release: 32,
	crown: 48,
	flow: 24,
	breathe: 12,
	beam: 16,
	flash: 6,
} as const;

/** crown の火の粉が巡る宝玉の色。 */
const CROWN_GEMS: readonly GemId[] = [
	"sapphire",
	"emerald",
	"amethyst",
	"amber",
	"ruby",
	"citrine",
	"aquamarine",
	"peridot",
];

function hsl(h: number, s: number, l: number): number {
	const k = (n: number): number => (n + h * 12) % 12;
	const a = s * Math.min(l, 1 - l);
	const f = (n: number): number =>
		l - a * Math.max(-1, Math.min(k(n) - 3, 9 - k(n), 1));
	const byte = (v: number): number => Math.round(v * 255);
	return (byte(f(0)) << 16) | (byte(f(8)) << 8) | byte(f(4));
}

/** 正方形（中心 at・半辺 half）の輪郭の上の点。s は周の割合 [0, 1)。 */
function onSquare(at: Vec3, half: number, s: number): Vec3 {
	const u = ((s % 1) + 1) % 1;
	const side = Math.floor(u * 4);
	const t = u * 4 - side;
	const a = -half + 2 * half * t;
	const [x, y] =
		side === 0
			? [a, -half]
			: side === 1
				? [half, a]
				: side === 2
					? [-a, half]
					: [-half, -a];
	return [at[0] + x, at[1] + y, at[2] + 0.01];
}

/**
 * 1 つの発火の粒子。`at` は光らせる要素の中心、`from` は出どころ（無ければ null）、`size` は要素の半径
 * （`flash` の四角の半辺）。光らない演出（層や宝玉だけを動かすもの）は空。
 */
export function burst(
	glow: Glow,
	at: Vec3,
	from: Vec3 | null,
	size: number,
	seconds: number,
): readonly Particle[] {
	const random = mulberry32(glow.seq);
	const p = glow.progress;
	const color = gemColorAt(glow.gem, seconds, glow.seq);
	const alpha = glow.intensity;
	const out: Particle[] = [];
	const push = (
		position: Vec3,
		c: number = color,
		a: number = alpha,
		s: number = SIZE,
	): void => {
		out.push({ position, color: c, size: s, alpha: a });
	};
	switch (glow.effect) {
		case "chant":
			for (let k = 0; k < COUNTS.chant; k++) {
				const angle = random() * Math.PI * 2 + p * 3;
				const radius = (0.12 + random() * 0.3) * (1 - p);
				push([
					at[0] + Math.cos(angle) * radius,
					at[1] + Math.sin(angle) * radius,
					at[2] + 0.02 + random() * 0.05 * (1 - p),
				]);
			}
			break;
		case "release":
			for (let k = 0; k < COUNTS.release; k++) {
				const angle = (k / COUNTS.release) * Math.PI * 2 + random() * 0.2;
				const radius = p * (0.4 + random() * 0.4);
				const prism =
					k % 2 === 0 ? GEMS.diamond.color : hsl(k / COUNTS.release, 0.8, 0.75);
				push(
					[
						at[0] + Math.cos(angle) * radius,
						at[1] + Math.sin(angle) * radius,
						at[2] + 0.02,
					],
					prism,
				);
			}
			break;
		case "crown":
			for (let k = 0; k < COUNTS.crown; k++) {
				const angle = random() * Math.PI * 2;
				const radius = random() * 0.3;
				const gem = CROWN_GEMS[k % CROWN_GEMS.length] ?? "gold";
				push(
					[
						at[0] + Math.cos(angle) * radius,
						at[1] + Math.sin(angle) * radius,
						at[2] + p * (0.6 + random() * 0.8),
					],
					GEMS[gem].color,
					alpha * (1 - p * 0.5),
				);
			}
			break;
		case "flow":
			if (from === null) break;
			for (let k = 0; k < COUNTS.flow; k++) {
				const t = (p * 1.5 + k / COUNTS.flow) % 1;
				const jitter = (random() - 0.5) * 0.02;
				push(
					[
						from[0] + (at[0] - from[0]) * t + jitter,
						from[1] + (at[1] - from[1]) * t + jitter,
						from[2] + (at[2] - from[2]) * t,
					],
					color,
					alpha,
					SIZE * 1.6,
				);
			}
			break;
		case "breathe":
			for (let k = 0; k < COUNTS.breathe; k++) {
				const angle = random() * Math.PI * 2;
				const radius = 0.04 + random() * 0.03;
				const fall = (p * 2 + random()) % 1;
				push(
					[
						at[0] + Math.cos(angle) * radius,
						at[1] + Math.sin(angle) * radius,
						at[2] + 0.12 * (1 - fall),
					],
					color,
					alpha * 0.6,
					SIZE * 0.6,
				);
			}
			break;
		case "beam":
			if (from === null) break;
			for (let k = 0; k < COUNTS.beam; k++) {
				const t = Math.min(1, Math.max(0, p * 1.6 - k * 0.025));
				push(arcPoint(from, at, t), color, alpha, SIZE * 1.8);
			}
			break;
		case "flash":
			for (let k = 0; k < COUNTS.flash; k++)
				push(onSquare(at, size, p + k / COUNTS.flash));
			break;
		default:
			break;
	}
	return out;
}

const EMBERS = 260;
const DUST = 200;
export const AMBIENT_COUNT = EMBERS + DUST;
const EMBER_COLOR = 0xffb35a;
const DUST_COLOR = 0x8090c0;
/** 火の粉に混ぜる宝玉の色（5 つに 1 つ）。 */
const EMBER_GEMS: readonly GemId[] = [
	"sapphire",
	"emerald",
	"amethyst",
	"aquamarine",
	"ruby",
];

const EMBER_SEEDS = (() => {
	const random = mulberry32(1);
	return Array.from(
		{ length: EMBERS },
		() => [random(), random(), random(), random()] as const,
	);
})();
const DUST_SEEDS = (() => {
	const random = mulberry32(2);
	return Array.from(
		{ length: DUST },
		() => [random(), random(), random(), random()] as const,
	);
})();

/** 漂う粒子: 昇る火の粉（金と宝玉の色）と藍の霞の塵。時刻だけの関数。 */
export function ambient(seconds: number): readonly Particle[] {
	const out: Particle[] = [];
	EMBER_SEEDS.forEach(([a, r, rise, phase], k) => {
		const angle = a * Math.PI * 2;
		const radius = Math.sqrt(r) * 1.1;
		const gem =
			k % 5 === 0 ? EMBER_GEMS[(k / 5) % EMBER_GEMS.length] : undefined;
		out.push({
			position: [
				Math.cos(angle) * radius,
				Math.sin(angle) * radius,
				(phase + seconds * (0.04 + rise * 0.08)) % 1.2,
			],
			color: gem === undefined ? EMBER_COLOR : GEMS[gem].color,
			size: SIZE,
			alpha: 0.8,
		});
	});
	DUST_SEEDS.forEach(([a, r, h, phase]) => {
		const angle = a * Math.PI * 2 + seconds * 0.01;
		const radius = Math.sqrt(r) * 1.6;
		out.push({
			position: [
				Math.cos(angle) * radius,
				Math.sin(angle) * radius,
				(h * 1.0 + Math.sin(seconds * 0.2 + phase * 6) * 0.05) % 1.0,
			],
			color: DUST_COLOR,
			size: SIZE * 0.5,
			alpha: 0.25,
		});
	});
	return out;
}

export interface BurstPlace {
	readonly at: Vec3;
	readonly from: Vec3 | null;
	readonly size: number;
}

/** 漂う粒子を先頭に、発火の粒子を足して `MAX_PARTICLES` で打ち切る。`resolve` が null の発火は飛ばす。 */
export function collect(
	glows: readonly Glow[],
	resolve: (glow: Glow) => BurstPlace | null,
	seconds: number,
): readonly Particle[] {
	const out: Particle[] = [...ambient(seconds)];
	for (const glow of glows) {
		if (out.length >= MAX_PARTICLES) break;
		const place = resolve(glow);
		if (place === null) continue;
		for (const particle of burst(
			glow,
			place.at,
			place.from,
			place.size,
			seconds,
		)) {
			if (out.length >= MAX_PARTICLES) break;
			out.push(particle);
		}
	}
	return out;
}
