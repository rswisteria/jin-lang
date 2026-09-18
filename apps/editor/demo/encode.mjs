// `pnpm demo` / `pnpm demo:fib` の後段: `demo-results/` に落ちた Playwright の動画（.webm・最新の 1 本）を
// ffmpeg で GIF（README に貼る）と MP4（リンク用）にして `docs/images/<名前>.gif / .mp4` へ書く。
//
//   cd apps/editor && pnpm demo        # tetris の台本（demo/v2-tetris.spec.ts）を収録 → 変換（ffmpeg が要る）
//   cd apps/editor && pnpm demo:fib    # fib のチュートリアル（demo/v2-fib-tutorial.spec.ts）
//   node demo/encode.mjs <名前> [compact]   # 変換だけ（`<名前>` は docs/images/ に書くファイルの basename）
//
// GIF は 10 fps・幅 1120 px・128 色（README で数 MB に収める）。鑑賞モードの 3D（光の粒が毎コマ動く）を含む
// 長い台本は同じ設定だと 20 MB を超えるので、`compact`（6 fps・幅 800 px・64 色・ディザ無し）で 7 MB 程度に収める。
// MP4 の設定は共通（動画として見るならこちら）。
import { execFileSync } from "node:child_process";
import { mkdirSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

const HERE = resolve(import.meta.dirname);
const RESULTS = join(HERE, "..", "demo-results");
const OUT_DIR = resolve(HERE, "../../../docs/images");
const BASENAME = process.argv[2];
if (BASENAME === undefined || !/^[A-Za-z0-9._-]+$/.test(BASENAME)) {
	throw new Error("使い方: node demo/encode.mjs <docs/images に書く名前> [compact]（例: editor-v2-tetris-demo）");
}
const GIF_PROFILES = {
	default: { fps: 10, width: 1120, colors: 128, dither: "dither=bayer:bayer_scale=5" },
	compact: { fps: 6, width: 800, colors: 64, dither: "dither=none" },
};
const PROFILE = GIF_PROFILES[process.argv[3] ?? "default"];
if (PROFILE === undefined) {
	throw new Error(`GIF のプロファイルは ${Object.keys(GIF_PROFILES).join(" / ")} のどれか`);
}

function newestWebm(dir) {
	const found = [];
	const walk = (d) => {
		for (const name of readdirSync(d)) {
			const path = join(d, name);
			if (statSync(path).isDirectory()) walk(path);
			else if (name.endsWith(".webm")) found.push(path);
		}
	};
	walk(dir);
	if (found.length === 0) throw new Error(`${dir} に .webm がありません（先に収録が要ります）`);
	found.sort((a, b) => statSync(b).mtimeMs - statSync(a).mtimeMs);
	return found[0];
}

const source = newestWebm(RESULTS);
mkdirSync(OUT_DIR, { recursive: true });
const gif = join(OUT_DIR, `${BASENAME}.gif`);
const mp4 = join(OUT_DIR, `${BASENAME}.mp4`);

execFileSync(
	"ffmpeg",
	[
		"-y",
		"-loglevel",
		"error",
		"-i",
		source,
		"-vf",
		`fps=${PROFILE.fps},scale=${PROFILE.width}:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=${PROFILE.colors}:stats_mode=diff[p];[b][p]paletteuse=${PROFILE.dither}:diff_mode=rectangle`,
		"-loop",
		"0",
		gif,
	],
	{ stdio: "inherit" },
);
execFileSync(
	"ffmpeg",
	[
		"-y",
		"-loglevel",
		"error",
		"-i",
		source,
		"-c:v",
		"libx264",
		"-pix_fmt",
		"yuv420p",
		"-crf",
		"23",
		"-preset",
		"slow",
		"-movflags",
		"+faststart",
		"-an",
		mp4,
	],
	{ stdio: "inherit" },
);
for (const path of [gif, mp4]) {
	console.log(`${path}: ${(statSync(path).size / 1024 / 1024).toFixed(2)} MB`);
}
