/** コーデックの選択（docs/spec/v2/stage.md §5）。判定は注入する（実物は Mediabunny の `canEncodeVideo`）。 */
export type CodecChoice =
	| {
			readonly codec: "avc";
			readonly container: "mp4";
			readonly mime: "video/mp4";
	  }
	| {
			readonly codec: "vp9";
			readonly container: "webm";
			readonly mime: "video/webm";
	  };

export async function chooseCodec(
	canEncode: (
		codec: "avc" | "vp9",
		width: number,
		height: number,
	) => Promise<boolean>,
	width: number,
	height: number,
): Promise<CodecChoice | null> {
	try {
		if (await canEncode("avc", width, height))
			return { codec: "avc", container: "mp4", mime: "video/mp4" };
		if (await canEncode("vp9", width, height))
			return { codec: "vp9", container: "webm", mime: "video/webm" };
	} catch {
		return null;
	}
	return null;
}
