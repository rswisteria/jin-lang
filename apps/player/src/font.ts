/**
 * 固定ビットマップ書体（abilities.md §2 `canvas.text`: 1 文字 6×8 論理単位・等幅）。
 *
 * ASCII（U+0020〜U+007E）は下の表の 5×7 を 6×8 の枠に左上詰めで置く（右 1 列と下 1 行は字間）。
 * それ以外のコードポイントは k6x8ゴシックの字形（`glyphs.ts`・JIS X 0208 の全区点を含む 7001 字。
 * 罫線などは右端の列と下端の行まで使う）で、そこにも無いものは □ で描く（設計書 §11 #33 / #49）。
 * 幅は字形によらず 1 コードポイント = 6 で、プレリュードの `len(s) * 6` と一致する。
 *
 * ASCII の各字形は 5 バイト（列ごと・bit0 が最上段）を 10 桁の 16 進で書く（`glyphs.ts` の 6 バイトと
 * 同じ向き）。字形の正誤はパリティに影響しない（トレースは表示リストの op と引数だけを持ち、画素は持たない）。
 */
import { BITMAPS, CODEPOINTS } from "./glyphs";

export const CELL_WIDTH = 6;
export const CELL_HEIGHT = 8;

const GLYPHS: readonly string[] = [
	"0000000000", // space
	"00005F0000", // !
	"0007000700", // "
	"147F147F14", // #
	"242A7F2A12", // $
	"2313086462", // %
	"3649552250", // &
	"0005030000", // '
	"001C224100", // (
	"0041221C00", // )
	"14083E0814", // *
	"08083E0808", // +
	"0050300000", // ,
	"0808080808", // -
	"0060600000", // .
	"2010080402", // /
	"3E5149453E", // 0
	"00427F4000", // 1
	"4261514946", // 2
	"2141454B31", // 3
	"1814127F10", // 4
	"2745454539", // 5
	"3C4A494930", // 6
	"0171090503", // 7
	"3649494936", // 8
	"064949291E", // 9
	"0036360000", // :
	"0056360000", // ;
	"0814224100", // <
	"1414141414", // =
	"0041221408", // >
	"0201510906", // ?
	"324979413E", // @
	"7E1111117E", // A
	"7F49494936", // B
	"3E41414122", // C
	"7F4141221C", // D
	"7F49494941", // E
	"7F09090901", // F
	"3E4149497A", // G
	"7F0808087F", // H
	"00417F4100", // I
	"2040413F01", // J
	"7F08142241", // K
	"7F40404040", // L
	"7F020C027F", // M
	"7F0408107F", // N
	"3E4141413E", // O
	"7F09090906", // P
	"3E4151215E", // Q
	"7F09192946", // R
	"4649494931", // S
	"01017F0101", // T
	"3F4040403F", // U
	"1F2040201F", // V
	"3F4038403F", // W
	"6314081463", // X
	"0708700807", // Y
	"6151494543", // Z
	"007F414100", // [
	"0204081020", // backslash
	"0041417F00", // ]
	"0402010204", // ^
	"4040404040", // _
	"0001020400", // `
	"2054545478", // a
	"7F48444438", // b
	"3844444420", // c
	"384444487F", // d
	"3854545418", // e
	"087E090102", // f
	"0C5252523E", // g
	"7F08040478", // h
	"00447D4000", // i
	"2040443D00", // j
	"7F10284400", // k
	"00417F4000", // l
	"7C04180478", // m
	"7C08040478", // n
	"3844444438", // o
	"7C14141408", // p
	"081414187C", // q
	"7C08040408", // r
	"4854545420", // s
	"043F444020", // t
	"3C4040207C", // u
	"1C2040201C", // v
	"3C4030403C", // w
	"4428102844", // x
	"0C5050503C", // y
	"4464544C44", // z
	"0008364100", // {
	"00007F0000", // |
	"0041360800", // }
	"0804081008", // ~
];

/** ASCII の外で k6x8 にも無いコードポイントに使う □。 */
const BOX = "7F4141417F";

function decode(base64: string): Uint8Array {
	return Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
}

/** k6x8 の字形（1 字 6 バイト）と、コードポイント → 字形の番号。 */
const K6X8_BITMAPS = decode(BITMAPS);
const K6X8_INDEX: ReadonlyMap<number, number> = (() => {
	const bytes = decode(CODEPOINTS);
	const index = new Map<number, number>();
	for (let i = 0; i * 2 < bytes.length; i++) {
		index.set(((bytes[i * 2] ?? 0) << 8) | (bytes[i * 2 + 1] ?? 0), i);
	}
	return index;
})();

/** 6×8 の枠の 6 列（bit0 が最上段）。 */
function columns(codePoint: number): readonly number[] {
	const ascii = codePoint - 0x20;
	if (ascii >= 0 && ascii < GLYPHS.length)
		return hexColumns(GLYPHS[ascii] ?? BOX);
	const glyph = K6X8_INDEX.get(codePoint);
	if (glyph === undefined) return hexColumns(BOX);
	return Array.from(
		K6X8_BITMAPS.subarray(glyph * CELL_WIDTH, (glyph + 1) * CELL_WIDTH),
	);
}

function hexColumns(hex: string): readonly number[] {
	const out: number[] = [];
	for (let i = 0; i < CELL_WIDTH; i++) {
		out.push(
			i * 2 < hex.length ? parseInt(hex.slice(i * 2, i * 2 + 2), 16) : 0,
		);
	}
	return out;
}

/**
 * 文字列の点の座標（左上基準・論理単位）を列挙する。描画側は 1 点 = 1×1 の矩形で塗る。
 * コードポイント単位で進める（`for…of` はサロゲートペアを 1 つに数える）。
 */
export function* pixels(
	text: string,
	x: number,
	y: number,
): Generator<readonly [number, number]> {
	let cx = x;
	for (const ch of text) {
		const codePoint = ch.codePointAt(0) ?? 0;
		if (codePoint !== 0x20) {
			const cols = columns(codePoint);
			for (let col = 0; col < CELL_WIDTH; col++) {
				const bits = cols[col] ?? 0;
				for (let row = 0; row < CELL_HEIGHT; row++) {
					if ((bits >> row) & 1) yield [cx + col, y + row];
				}
			}
		}
		cx += CELL_WIDTH;
	}
}

/** `len(s) * 6`（abilities.md §2）。 */
export function textWidth(text: string): number {
	return [...text].length * CELL_WIDTH;
}
