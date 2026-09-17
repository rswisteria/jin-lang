/** 書き出しのファイル名（docs/spec/v2/stage.md §5）。`<jin 名>-seed<seed>-<ticks>t.jinrec` と同じ並び方。 */
export function exportFileName(parts: {
	readonly jinName: string;
	readonly circleName: string;
	readonly seed: number | null;
	readonly startTick: number;
	readonly endTick: number;
	readonly extension: "mp4" | "webm" | "png";
}): string {
	const stem = parts.jinName.replace(/\.jin$/, "") || "game";
	const circle = parts.circleName.replace(/[/\\]/g, "_");
	return `${stem}-${circle}-seed${String(parts.seed ?? 0)}-t${String(Math.round(parts.startTick))}-${String(Math.round(parts.endTick))}.${parts.extension}`;
}
