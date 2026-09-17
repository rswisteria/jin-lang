/**
 * WebGL の絵に銘を重ねた 2D canvas（docs/spec/v2/stage.md §5）。動画のエンコーダと PNG はこの canvas を読む。
 * 銘の既定は on（「<陣名> — written in Jin(陣)」を右下に小さく）。
 */
export function captionText(circleName: string): string {
	return circleName === ""
		? "written in Jin(陣)"
		: `${circleName} — written in Jin(陣)`;
}

export class Composer2D {
	readonly canvas = document.createElement("canvas");
	private readonly context: CanvasRenderingContext2D;

	constructor() {
		const context = this.canvas.getContext("2d");
		if (context === null) throw new Error("2D の描画文脈を取れません");
		this.context = context;
	}

	resize(width: number, height: number): void {
		this.canvas.width = width;
		this.canvas.height = height;
	}

	compose(source: HTMLCanvasElement, caption: string | null): void {
		const { width, height } = this.canvas;
		this.context.drawImage(source, 0, 0, width, height);
		if (caption === null) return;
		const size = Math.round(Math.min(width, height) * 0.022);
		this.context.font = `500 ${String(size)}px "Times New Roman", "Hiragino Mincho ProN", serif`;
		this.context.textAlign = "right";
		this.context.textBaseline = "bottom";
		this.context.fillStyle = "rgba(240, 214, 160, 0.72)";
		this.context.fillText(caption, width - size, height - size);
	}

	toPng(): Promise<ArrayBuffer> {
		return new Promise((resolve, reject) => {
			this.canvas.toBlob((blob) => {
				if (blob === null) reject(new Error("PNG を作れません"));
				else void blob.arrayBuffer().then(resolve, reject);
			}, "image/png");
		});
	}
}
