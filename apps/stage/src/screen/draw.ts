import { CELL_HEIGHT, pixels, textWidth } from "./font";

/**
 * 表示リスト（abilities.md §2 / §4）を 2D キャンバスに描く。**プレイヤーの `apps/player/src/canvas.ts` の写し**
 * （仕様書 docs/superpowers/specs/2026-10-01-jin-stage-summon-design.md §2.2）。apps 同士は import しないので、
 * 命令の名前は書き写し（`abilities.json` との等号は契約テスト）、描き方のずれはプレイヤーと同じ正解の PNG との
 * 画素一致（両アプリの e2e）で捕まえる。
 *
 * プレイヤーとの差は `sprite` だけ: 素材のファイルは鑑賞ページに届かないので、(x, y) を左上とする
 * サファイアの菱形の印を描く。
 */
export type Op = readonly [string, ...(string | number)[]];

/** `CanvasRenderingContext2D` のうち使う部分（プレイヤーの `Surface` と同じ欄）。 */
export interface Surface {
	fillStyle: string | CanvasGradient | CanvasPattern;
	strokeStyle: string | CanvasGradient | CanvasPattern;
	lineWidth: number;
	fillRect(x: number, y: number, w: number, h: number): void;
	strokeRect(x: number, y: number, w: number, h: number): void;
	beginPath(): void;
	arc(x: number, y: number, r: number, start: number, end: number): void;
	fill(): void;
	moveTo(x: number, y: number): void;
	lineTo(x: number, y: number): void;
	stroke(): void;
	drawImage(image: CanvasImageSource, x: number, y: number): void;
}

/** 描く命令（canvas の全メンバと ui の `button` / `label`）。 */
export const DRAWABLE_OPS: readonly string[] = [
	"clear",
	"ink",
	"rect",
	"circle",
	"line",
	"text",
	"sprite",
	"button",
	"label",
];

/** `sprite` の代わりの印（菱形）の一辺（論理 px）と色（描く力の宝玉 = サファイア）。 */
export const SPRITE_MARK = 6;
const SPRITE_MARK_COLOR = "#2f6bff";
const DEFAULT_INK = "#fff";

function num(value: unknown): number {
	return typeof value === "number" ? value : 0;
}
function str(value: unknown): string {
	return typeof value === "string" ? value : "";
}

function text(surface: Surface, value: string, x: number, y: number): void {
	for (const [px, py] of pixels(value, x, y)) surface.fillRect(px, py, 1, 1);
}

function spriteMark(surface: Surface, x: number, y: number): void {
	const previous = surface.fillStyle;
	surface.fillStyle = SPRITE_MARK_COLOR;
	const center = (SPRITE_MARK - 1) / 2;
	for (let dy = 0; dy < SPRITE_MARK; dy++) {
		for (let dx = 0; dx < SPRITE_MARK; dx++) {
			if (Math.abs(dx - center) + Math.abs(dy - center) <= SPRITE_MARK / 2)
				surface.fillRect(x + dx, y + dy, 1, 1);
		}
	}
	surface.fillStyle = previous;
}

/** 1 tick 分の表示リストを描く。`ink` は tick の先頭で `#fff`（プレイヤーと同じ）。未知の op は無視する。 */
export function drawOps(
	surface: Surface,
	ops: readonly Op[],
	width: number,
	height: number,
): void {
	const s = surface;
	s.lineWidth = 1;
	s.fillStyle = DEFAULT_INK;
	s.strokeStyle = DEFAULT_INK;
	for (const [name, ...args] of ops) {
		switch (name) {
			case "clear":
				s.fillStyle = str(args[0]);
				s.fillRect(0, 0, width, height);
				s.fillStyle = DEFAULT_INK;
				s.strokeStyle = DEFAULT_INK;
				break;
			case "ink":
				s.fillStyle = str(args[0]);
				s.strokeStyle = str(args[0]);
				break;
			case "rect":
				s.fillRect(num(args[0]), num(args[1]), num(args[2]), num(args[3]));
				break;
			case "circle":
				s.beginPath();
				s.arc(
					num(args[0]),
					num(args[1]),
					Math.max(0, num(args[2])),
					0,
					Math.PI * 2,
				);
				s.fill();
				break;
			case "line":
				s.beginPath();
				s.moveTo(num(args[0]) + 0.5, num(args[1]) + 0.5);
				s.lineTo(num(args[2]) + 0.5, num(args[3]) + 0.5);
				s.stroke();
				break;
			case "text":
			case "label":
				text(s, str(args[0]), num(args[1]), num(args[2]));
				break;
			case "sprite":
				spriteMark(s, num(args[1]), num(args[2]));
				break;
			case "button": {
				const [label, x, y, w, h] = [
					str(args[0]),
					num(args[1]),
					num(args[2]),
					num(args[3]),
					num(args[4]),
				];
				s.strokeRect(x + 0.5, y + 0.5, Math.max(0, w - 1), Math.max(0, h - 1));
				text(
					s,
					label,
					x + Math.floor((w - textWidth(label)) / 2),
					y + Math.floor((h - CELL_HEIGHT) / 2),
				);
				break;
			}
			default:
				break;
		}
	}
}
