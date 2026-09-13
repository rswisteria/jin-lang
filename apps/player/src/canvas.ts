/**
 * 表示リスト（abilities.md §2 / §4）を `<canvas>` に描く。
 *
 * 描画は tick の戻り値の `ops` を上から順に実行するだけで、状態は `ink`（描画色）だけを持つ。
 * 色の検査はプレリュードが済ませている（不正なら実行時エラーで `ops` に載らない）。
 * 未知の op は無視する（落とさない。表示が欠けるだけ）。
 */
import { AUDIO_OPS, CANVAS_OPS, UI_OPS, op } from "./abilities";
import { CELL_HEIGHT, pixels, textWidth } from "./font";
import type { Op } from "./types";

/** `CanvasRenderingContext2D` のうち使う部分（テストではこれを記録する偽物に差し替える）。 */
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

const DEFAULT_INK = "#fff";

const CLEAR = op("clear");
const INK = op("ink");
const RECT = op("rect");
const CIRCLE = op("circle");
const LINE = op("line");
const TEXT = op("text");
const SPRITE = op("sprite");
const BUTTON = op("button");
const LABEL = op("label");

function num(value: unknown): number {
	return typeof value === "number" ? value : 0;
}
function str(value: unknown): string {
	return typeof value === "string" ? value : "";
}

export class Renderer {
	constructor(
		private readonly surface: Surface,
		private readonly width: number,
		private readonly height: number,
		private readonly sprites: ReadonlyMap<
			string,
			CanvasImageSource
		> = new Map(),
	) {}

	/** 1 tick 分の表示リストを描く。`ink` は tick の先頭で `#fff` に戻る（プレリュードと同じ）。 */
	draw(ops: readonly Op[]): void {
		const s = this.surface;
		s.lineWidth = 1;
		s.fillStyle = DEFAULT_INK;
		s.strokeStyle = DEFAULT_INK;
		for (const item of ops) {
			const [name, ...args] = item;
			switch (name) {
				case CLEAR:
					s.fillStyle = str(args[0]);
					s.fillRect(0, 0, this.width, this.height);
					s.fillStyle = DEFAULT_INK;
					s.strokeStyle = DEFAULT_INK;
					break;
				case INK:
					s.fillStyle = str(args[0]);
					s.strokeStyle = str(args[0]);
					break;
				case RECT:
					s.fillRect(num(args[0]), num(args[1]), num(args[2]), num(args[3]));
					break;
				case CIRCLE:
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
				case LINE:
					s.beginPath();
					s.moveTo(num(args[0]) + 0.5, num(args[1]) + 0.5);
					s.lineTo(num(args[2]) + 0.5, num(args[3]) + 0.5);
					s.stroke();
					break;
				case TEXT:
				case LABEL:
					this.text(str(args[0]), num(args[1]), num(args[2]));
					break;
				case SPRITE: {
					const image = this.sprites.get(str(args[0]));
					if (image !== undefined)
						s.drawImage(image, num(args[1]), num(args[2]));
					break;
				}
				case BUTTON: {
					const [label, x, y, w, h] = [
						str(args[0]),
						num(args[1]),
						num(args[2]),
						num(args[3]),
						num(args[4]),
					];
					s.strokeRect(
						x + 0.5,
						y + 0.5,
						Math.max(0, w - 1),
						Math.max(0, h - 1),
					);
					this.text(
						label,
						x + Math.floor((w - textWidth(label)) / 2),
						y + Math.floor((h - CELL_HEIGHT) / 2),
					);
					break;
				}
				default:
					// カタログに無い op は無視する（CANVAS_OPS / UI_OPS / AUDIO_OPS の外）。
					break;
			}
		}
	}

	private text(text: string, x: number, y: number): void {
		for (const [px, py] of pixels(text, x, y)) {
			this.surface.fillRect(px, py, 1, 1);
		}
	}
}

/** 表示リストに載りうる op の一覧（テスト用）。 */
export const DRAWABLE_OPS: readonly string[] = [...CANVAS_OPS, ...UI_OPS];
export { AUDIO_OPS };
