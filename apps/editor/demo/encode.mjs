// `pnpm demo` の後段: `demo-results/` に落ちた Playwright の動画（.webm）を ffmpeg で
// GIF（README に貼る）と MP4（リンク用）にして `docs/images/` へ書く。
//
//   cd apps/editor && pnpm demo        # 収録 → 変換（ffmpeg が要る）
//
// 収録の台本は `demo/v2-paddle.spec.ts`。GIF は 12 fps・幅 1120 px・128 色（README で数 MB に収める）。
import { execFileSync } from "node:child_process";
import { mkdirSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

const HERE = resolve(import.meta.dirname);
const RESULTS = join(HERE, "..", "demo-results");
const OUT_DIR = resolve(HERE, "../../../docs/images");
const BASENAME = "editor-v2-paddle-demo";

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
		"fps=12,scale=1120:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle",
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
