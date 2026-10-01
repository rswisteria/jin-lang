# 鑑賞ページ: 召喚の窓（魔法の出力）と音 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 鑑賞ページの陣の上空に、トレースの `frame` 行の表示リスト（ゲーム画面）を映す「召喚の窓」を出し、`tone` の音をプレビューで鳴らし、書き出しの動画に音声トラックとして入れる。

**Architecture:** プレイヤーの描画（`canvas.ts`）の写しを `apps/stage/src/screen/draw.ts` に、字形（`glyphs.ts` / `font.ts`）の写しを `screen/` に置き、プレイヤーと鑑賞ページの両方が同じ正解の PNG と画素一致することで写しのずれを捕まえる。どの `frame` を映すか・窓の開閉・音の PCM は three を import しない純関数（`screen/frames.ts` / `screen/sound.ts`）で決め、窓の描画は `render/summonWindow.ts`。舞台の大きさは `stage.scene` の新しい欄 `stageSize` で渡す（語彙は 4 語のまま）。

**Tech Stack:** TypeScript 5.9.3 / three 0.186.0 / mediabunny 1.57.0（音声トラック）/ WebAudio / vitest 5.0.0 / Playwright 1.62.0 / pytest

**Spec:** `docs/superpowers/specs/2026-10-01-jin-stage-summon-design.md`（仕様書 ②）。前提は仕様書 ① `docs/superpowers/specs/2026-10-01-jin-stage-gem-worldview-design.md` と `docs/spec/v2/stage.md`

## Global Constraints

- 依存は増やさない（`apps/stage` の dependencies は `three` 0.186.0 と `mediabunny` 1.57.0 だけ）
- `apps/stage/src/` のうち `main.ts` 以外で `Math.random` / `Date.now` / `performance.now` / `new Date(` を書かない（`AudioContext` の時計を読むのは `main.ts` だけ）
- 鑑賞ページはリポジトリのファイルも `schemas/` も読まない。apps 同士は import しない（写しは生成物かバイト一致で守る）
- 語彙は `stage.scene` / `stage.trace` / `stage.status` / `stage.file` の 4 語。書いてよいのは `apps/stage/src/messages.ts` と `apps/editor/src/stage/StagePanel.tsx` だけ
- API は記憶で書かない: Mediabunny の音声と `AudioEncoder` は Task 1 の probe（`delivery/<最新の *-jin>/stage-api-probe.md` §G）の実測どおりに使う
- 音はプレイヤーと同じ矩形波・音量 0.08。差は頭と終わりの 5ms のフェードだけ
- 値（窓の位置・大きさ・カメラの半径・開閉の長さ）は初期値。目視で変えたら stage.md §7 に根拠つきで残す
- 各タスクの終わりに `cd apps/stage && pnpm lint && pnpm test`、触ったなら `cd apps/editor && pnpm test` / `cd apps/player && pnpm test`、
  `uv run pytest tests/contract/test_stage_contract.py tests/contract/test_player_contract.py tests/spec/test_stage_spec_consistency.py` が通る
- コミットメッセージの末尾に `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`

## 仕様書からの決め足し（実装で採る形）

- **画面は論理解像度の 2D キャンバスに描き、テクスチャの拡大を `NearestFilter` にする**（仕様書 §1.2 の「整数倍（初期値 4 倍）で描く」と見え方は同じで、プレイヤーと同じ方式）
- **画素一致の fixture に `sprite` を入れない**（プレイヤーは素材が無いと何も描かず、鑑賞ページは印を描く。印は鑑賞ページの単体テストで見る）
- **窓の幅は世界座標で 1.2**（仕様書 §1.1 の「外周の約 0.9 倍」は半径か直径か曖昧。初期値として置いて目視で詰める）
- 音声のコーデックが無いときの知らせは鑑賞ページの状態の表示（`#status`）に出す。`stage.status` の欄は増やさない

## Review Focus

- **`stageSize` が無い / 0 / 負 / 数でない場面**（古いエディタ）→ 窓を出さず、例外も出さない（Task 4 の `messages.test.ts`・Task 6 の e2e）
- **`frame` 行の無いトレース**（release ビルドの録画・`stage.trace` が空）→ 窓は開かず、音も鳴らない（Task 5 の `frames.test.ts`・Task 7 の `sound.test.ts`）
- **書き出しの範囲の途中から始まる `tone`**（開始 tick より前に鳴り始め、範囲に食い込む音）と **範囲の終わりを越える `tone`** → 範囲の中の分だけが鳴り、PCM の長さは映像の長さと同じ（Task 7）
- **音声のコーデックが使えない環境**（`canEncodeAudio` が false）→ 無音の動画を書き出し、書き出し自体は成功する（Task 7 の `mediabunnyEncoder` の分岐を e2e で強制する口）
- **場面の送り直し**（編集のたび）→ 窓のテクスチャと裏のキャンバスを前の分まで解放し、GPU の資源が増え続けない（Task 6 で既存の e2e「GPU の資源が増え続けない」を窓ありの場面で通す）

---

### Task 1: Mediabunny の音声トラックと AudioEncoder の probe

**Files:**
- Modify: `delivery/<最新の *-jin>/stage-api-probe.md`（§G）
- Create: `apps/stage/test/audioApi.test.ts`
- Create（e2e の一時 spec ではなく残す）: `apps/stage/e2e/audioProbe.spec.ts`

**Interfaces:**
- Produces: probe §G に「音声のソースのクラス名・コンストラクタの引数・`Output.addAudioTrack` の形・`canEncodeAudio(codec, options)` の形・Chromium（Playwright 同梱）で `aac` / `opus` が使えるか」の実測

- [ ] **Step 1: 失敗するテストを書く** — `audioApi.test.ts`: `import { AudioSample, AudioSampleSource, canEncodeAudio } from "mediabunny"` が関数（クラス）として存在し、`Output.prototype.addAudioTrack` が関数。名前が違えば Step 2 で落ちるので、型定義（`node_modules/mediabunny/dist/*.d.ts`）を読んで正しい名前に直してから進む（直した名前を probe に書く）
- [ ] **Step 2: 走らせる** — `pnpm vitest run test/audioApi.test.ts`。期待: 名前が合っていれば PASS
- [ ] **Step 3: ブラウザの実測** — `audioProbe.spec.ts`: 鑑賞ページの dist を harness で開き、iframe の中で `canEncodeAudio("aac")` / `canEncodeAudio("opus")` を評価して結果をテストの出力（`console.log`）と `expect(typeof …).toBe("boolean")` で残す。さらに 1 秒の 440Hz の PCM を音声トラックに足して MP4 を finalize し、Node 側で読み戻して音声トラックがあることを見る（`aac` が false なら WebM + opus）
- [ ] **Step 4: probe に追記** — §G に表で: クラス名・引数・`numberOfChannels` / `sampleRate` / `format`（`"f32"` など）・`timestamp` の単位・`canEncodeAudio` の結果（Chromium 同梱）
- [ ] **Step 5: Commit** — `test(stage): Mediabunny 1.57.0 の音声トラックと AudioEncoder を実測`

---

### Task 2: 字形と ASCII 字形の写し

**Files:**
- Modify: `scripts/generate_glyphs.py`（出力先を 2 つに）
- Create: `apps/stage/src/screen/glyphs.ts`（生成物）・`apps/stage/src/screen/font.ts`（`apps/player/src/font.ts` のバイト一致の写し）
- Modify: `tests/contract/test_stage_contract.py`・`.github/workflows/ci.yml`（stage のジョブに `diff`）

**Interfaces:**
- Produces: `screen/font.ts` の `CELL_WIDTH` / `CELL_HEIGHT` / `pixels(text, x, y)` / `textWidth(text)`（プレイヤーと同じ）。`generate_glyphs.py` の `OUTPUTS: tuple[Path, Path]`

- [ ] **Step 1: 失敗するテストを書く** — `test_stage_contract.py` に `test_the_stage_glyphs_are_the_generated_copy`（`generate_glyphs.py --check` が exit 0、`apps/stage/src/screen/glyphs.ts` と `apps/player/src/glyphs.ts` のバイト一致）と `test_the_stage_ascii_font_is_a_byte_copy_of_the_player`（`screen/font.ts` == `apps/player/src/font.ts`）と `test_ci_diffs_the_stage_glyphs`（ci.yml に `diff -u apps/stage/src/screen/glyphs.ts -` がある）
- [ ] **Step 2: 落ちることを見る** — `uv run pytest tests/contract/test_stage_contract.py -k "glyphs or ascii or diffs" -q`。期待: FAIL（ファイルが無い）
- [ ] **Step 3: 実装** — `generate_glyphs.py` は `OUTPUT` を `OUTPUTS`（player と stage）にし、書き込み・`--check` は 2 つとも（`--stdout` は 1 本のまま）。生成して `screen/glyphs.ts` を作り、`font.ts` をコピー。ci.yml の stage ジョブに `uv run python scripts/generate_glyphs.py --stdout | diff -u apps/stage/src/screen/glyphs.ts -`。プレイヤー側の既存の契約テスト（`OUTPUT` を見ていれば）を `OUTPUTS` に合わせる
- [ ] **Step 4: 走らせる** — 上の pytest と `uv run pytest tests/contract/test_player_contract.py -q`、`cd apps/stage && pnpm lint && pnpm typecheck`。期待: PASS
- [ ] **Step 5: Commit** — `feat(stage): 字形（k6x8ゴシック）と ASCII の字形の写し（生成器が 2 か所に書く）`

---

### Task 3: 描画の写し `draw.ts` と画素一致

**Files:**
- Create: `apps/stage/src/screen/draw.ts`・`apps/stage/test/draw.test.ts`
- Create: `tests/fixtures/screen/all-ops.json`・`tests/fixtures/screen/tetris-0.json`・`tetris-1.json`（`frame` 行の `ops` と舞台の大きさ）と正解の PNG `tests/fixtures/screen/*.png`
- Modify: `apps/player/src/main.ts`（e2e の口 `__jinPlayer.renderOps`）・`apps/player/e2e/screen.spec.ts`（新規）
- Modify: `apps/stage/src/main.ts`（e2e の口 `__jinStage.renderOps`）・`apps/stage/e2e/stage.spec.ts`
- Modify: `tests/contract/test_stage_contract.py`

**Interfaces:**
- Produces:
  ```ts
  // screen/draw.ts（three を import しない）
  export type Op = readonly [string, ...(string | number)[]];
  export const DRAWABLE_OPS: readonly string[]; // ["clear","ink","rect","circle","line","text","sprite","button","label"]
  export interface Surface { /* プレイヤーの canvas.ts の Surface と同じ欄 */ }
  export function drawOps(surface: Surface, ops: readonly Op[], width: number, height: number): void;
  export const SPRITE_MARK = 6; // sprite の代わりの菱形の一辺（論理 px）・色はサファイア #2f6bff
  // 両 main.ts の e2e の口: renderOps(ops, width, height) => string（PNG の data URL）
  ```
  fixture の形: `{ "width": number, "height": number, "ops": Op[] }`

- [ ] **Step 1: 失敗するテストを書く** — `draw.test.ts`（記録する偽の Surface）: `clear` が全面の `fillRect`、`ink` が色を変え次の `rect` に効く、tick の先頭で `#fff`、`text` が 1 画素ずつの `fillRect`（`pixels` と同じ数）、`button` が枠 + 中央の文字、`sprite` が菱形の印（サファイア）を描く、未知の op は無視。契約テストに `test_the_stage_draws_the_drawable_ops_of_the_abilities`（`draw.ts` の `DRAWABLE_OPS` の文字列リテラルの集合 == `abilities.json` の canvas の全メンバと ui の描く命令（`button` / `label`））
- [ ] **Step 2: 落ちることを見る** — `pnpm vitest run test/draw.test.ts`・契約テスト。期待: FAIL
- [ ] **Step 3: 実装** — `drawOps` はプレイヤーの `Renderer.draw` の写し（op 名はリテラル）。`sprite` だけ: `fillStyle` を一時的にサファイアにし、(x, y) を左上とする 6×6 の菱形を 1 画素の `fillRect` で描いて元の色に戻す
- [ ] **Step 4: fixture と正解** — `all-ops.json`（`sprite` を除く 8 命令・日本語と ASCII の文字・`button`・線・円を含む 64×48）、tetris の 2 コマ（`apps/stage/test/fixtures/tetris-trace.jsonl` の `frame` 行から tick 10 と 60 の `ops`・176×176）。プレイヤーの `screen.spec.ts`: 各 fixture を `__jinPlayer.renderOps` で描き、正解 PNG と画素一致（`UPDATE_SCREEN_GOLDEN=1` のときだけ正解を書く）。正解はこの手順で作る
- [ ] **Step 5: 鑑賞ページの e2e** — `stage.spec.ts` に「`draw.ts` が正解の PNG と画素一致（3 fixture）」: `__jinStage.renderOps` で描いた画素と、正解を `Image` に読み込んだ画素を、ブラウザの中で `getImageData` で比べて差が 0
- [ ] **Step 6: 走らせる** — `cd apps/player && pnpm build && pnpm e2e -g screen`、`cd apps/stage && pnpm build && pnpm e2e -g 画素`。期待: PASS
- [ ] **Step 7: Commit** — `feat(stage): 表示リストの描画の写し（draw.ts）と、プレイヤーとの画素一致`

---

### Task 4: `stageSize` の欄

**Files:**
- Modify: `apps/editor/src/stage/StagePanel.tsx`・`apps/editor/test/stagePanel.test.tsx`
- Modify: `apps/stage/src/messages.ts`・`apps/stage/test/messages.test.ts`
- Modify: `docs/spec/v2/stage.md`（§6 の `stage.scene` の欄。あわせて名前の表の 3 欄（①の先送りの軽微な指摘）も書く）

**Interfaces:**
- Produces: `SceneMessage.stageSize: { readonly width: number; readonly height: number } | null`（`parseInbound` は欄が無い / 数でない / 0 以下なら null にし、メッセージは捨てない）。エディタは `model.stage.width` / `height` を送る

- [ ] **Step 1: 失敗するテストを書く** — `messages.test.ts`: `stageSize: {width: 176, height: 176}` → そのまま、欄なし / `{width: 0}` / `"x"` → `null`（いずれも `type: "scene"` として受ける）。`stagePanel.test.tsx`: 送った `stage.scene` に `stageSize` がモデルの値で載る
- [ ] **Step 2: 落ちることを見る** — 両アプリの vitest。期待: FAIL
- [ ] **Step 3: 実装** — `parseInbound` と `StagePanel`（送り直しの鍵 `key` に `stageSize` を含める）
- [ ] **Step 4: 走らせる** — 両アプリの `pnpm test && pnpm lint`、契約テスト（語彙の等号は変わらない）。期待: PASS
- [ ] **Step 5: Commit** — `feat(stage): stage.scene に stageSize（舞台の大きさ）を足す`

---

### Task 5: 映すコマ・窓の開閉・縁の光（`frames.ts`）

**Files:**
- Create: `apps/stage/src/screen/frames.ts`・`apps/stage/test/frames.test.ts`

**Interfaces:**
- Consumes: `TraceRow` / `StageNames`（`names.ts`）・`circleOf`・`Op`（Task 3）
- Produces:
  ```ts
  export interface ScreenFrame { readonly tick: number; readonly ops: readonly Op[]; readonly audio: readonly Op[] }
  export function framesOf(rows: readonly TraceRow[]): readonly ScreenFrame[]; // kind === "frame" の output {ops, audio} を tick 順に
  export function frameAt(frames: readonly ScreenFrame[], t: number): ScreenFrame | null; // tick ≤ floor(t) で最新・二分探索
  export interface WindowState { readonly open: number; readonly tonePulse: number; readonly playFlash: number; readonly errorPulse: number }
  export const OPEN_SECONDS = 0.8; export const PULSE_SECONDS = 0.25; export const FLASH_SECONDS = 0.3;
  export function windowAt(rows: readonly TraceRow[], frames: readonly ScreenFrame[], names: StageNames, t: number, fps: number): WindowState;
  ```
  `open`: root（`isRoot` の陣の pointer）の `enter` から `OPEN_SECONDS` で 0→1、root の `exit` / `finish`（行の pointer の陣が root）から `OPEN_SECONDS` で 1→0。`isRoot` が無ければ最初の `frame` で開き閉じない。最初の `frame` より前は 0。
  `tonePulse` / `playFlash`: `frameAt(t)` 以前で最後に `tone` / `play` を含む `frame` からの経過で 1→0。`errorPulse`: 最初の `error` 行の後は `0.5 + 0.5 sin(2π·2·経過秒)`、前は 0。
- [ ] **Step 1: 失敗するテストを書く** — `frames.test.ts`: `frameAt` が tick の境目（t = 9.99 → tick 9）と最初の `frame` より前（null）と最後のコマで止まる（t が最後の tick を越えても最後）、`frame` 行の無いトレースで常に null、`windowAt` の open（root の enter から 0.4 秒で 0.5・exit 後に閉じる・`isRoot` 無しは最初の frame で開き閉じない）、`tone` を含む frame の直後に tonePulse ≈ 1 で `PULSE_SECONDS` 後に 0、error の後に errorPulse が 0〜1 の間で振れる
- [ ] **Step 2: 落ちることを見る** — `pnpm vitest run test/frames.test.ts`。期待: FAIL
- [ ] **Step 3: 実装**
- [ ] **Step 4: 走らせる** — `pnpm test && pnpm lint`。期待: PASS
- [ ] **Step 5: Commit** — `feat(stage): 映すコマと窓の開閉・縁の光を時刻から決める（frames.ts）`

---

### Task 6: 召喚の窓の描画

**Files:**
- Create: `apps/stage/src/render/summonWindow.ts`
- Modify: `apps/stage/src/render/stageRenderer.ts`（`setScene(scene, names, stageSize)`・`draw` に窓・カメラの半径）・`apps/stage/src/camera.ts`（`cameraPose` に `fitRadius` 引数）・`apps/stage/src/main.ts`（`framesOf` を `stage.trace` のたびに作り、`StageFrame` に `frame` と `window` を足す）
- Modify: `apps/stage/test/camera.test.ts`・`apps/stage/e2e/stage.spec.ts`・`apps/stage/e2e/harness.ts`（`stageSize` を送る）

**Interfaces:**
- Consumes: `drawOps`（Task 3）・`ScreenFrame` / `WindowState`（Task 5）・`METALS` / `metalOf`（①）
- Produces:
  ```ts
  export const WINDOW = { width: 1.2, height: 1.05, back: 0.35, fitRadius: 1.75 } as const; // 世界座標・初期値
  export class SummonWindow {
    readonly object: THREE.Object3D;
    setStage(size: { width: number; height: number } | null, frameColor: number): void; // null なら隠す。裏の canvas とテクスチャを作り直し（前の分を dispose）
    update(frame: ScreenFrame | null, state: WindowState, camera: THREE.Camera, seconds: number): void;
    dispose(): void;
  }
  // camera.ts: cameraPose(preset, aspect, seconds, offset?, nudge?, fitRadius = FIT_RADIUS)
  ```
  板は `MeshBasicMaterial`（`map` = `CanvasTexture`・`NearestFilter`・`toneMapped: false`・`transparent`、不透明度 = `open`）。縁は加算の枠（サファイア → `tonePulse` でアメジストへ寄せる → `playFlash` で白 → `errorPulse` でガーネット）、枠は地金の細い板 4 本。位置は世界 (0, 0.95 + 高さ/2, 0) からカメラの水平の向きの逆へ `back`、ビルボード、`open` で拡大縮小。窓がある場面では `cameraPose` に `WINDOW.fitRadius`。
- [ ] **Step 1: 失敗するテストを書く** — `camera.test.ts`: `fitRadius` を渡すと距離がその比で伸びる。e2e: 「tetris の場面で窓の領域に盤面の色がある」（harness が `stageSize: {176, 176}` を送り、tick 60 の画面の上半分に `frame` の ops の `clear` 色と異なる宝玉以外の色、具体的には tetris のミノの色 `#4ce0e6` 系（H 180°〜190°）の画素が 0.05% 以上）と「`stageSize` 無しの場面（paddle の既定の harness）で窓が出ず `JIN_STATUS.error` が null」。既存の「GPU の資源が増え続けない」を tetris（窓あり）でも回す
- [ ] **Step 2: 落ちることを見る** — `pnpm vitest run test/camera.test.ts`・`pnpm build && pnpm e2e -g "窓|GPU"`。期待: FAIL
- [ ] **Step 3: 実装** — `summonWindow.ts`、`stageRenderer.ts`（窓は `decor` と同じく場面が変わっても作り直さず、`setStage` で中身を差し替える）、`main.ts`
- [ ] **Step 4: 目視で詰める** — dev.html（tetris）で位置・大きさ・縁の光を見て、変えた値を控える（Task 8 で stage.md §7 に書く）
- [ ] **Step 5: 走らせる** — `pnpm test && pnpm lint && pnpm build && pnpm e2e`。期待: PASS（既存の 6 件 + 新しい 2 件 + GPU の tetris 版）
- [ ] **Step 6: Commit** — `feat(stage): 召喚の窓（陣の上空にゲーム画面をドットのまま映す・縁の光・開閉）`

---

### Task 7: 音（合成・プレビュー・書き出し）

**Files:**
- Create: `apps/stage/src/screen/sound.ts`・`apps/stage/test/sound.test.ts`
- Modify: `apps/stage/src/mediabunnyEncoder.ts`（`createEncoder(canvas, choice, audio)`）・`apps/stage/src/main.ts`（プレビューの WebAudio・音の入り切り・書き出しで PCM を渡す）・`apps/stage/index.html`（`stage-mute` のボタン）・`apps/stage/e2e/stage.spec.ts`

**Interfaces:**
- Consumes: `ScreenFrame`（Task 5）・`ExportRange` / `clampRange` / `frameCount`（`timeline.ts`）・Task 1 の probe の API
- Produces:
  ```ts
  export const SAMPLE_RATE = 48000; export const TONE_GAIN = 0.08; export const FADE_SECONDS = 0.005;
  export function toneEvents(frames: readonly ScreenFrame[], range: ExportRange): readonly { startSeconds: number; hz: number; seconds: number }[];
  export function synthesize(frames: readonly ScreenFrame[], range: ExportRange): Float32Array; // 長さ = round(frameCount(range) / VIDEO_FPS × SAMPLE_RATE)
  // mediabunnyEncoder.ts
  export async function createEncoder(canvas: HTMLCanvasElement, choice: CodecChoice, audio: Float32Array | null): Promise<FrameEncoder & { readonly audio: boolean }>;
  ```
  `toneEvents`: `tick` が [開始 − 鳴る長さぶん, 終了) の `frame` の `tone(hz, ms)` を `(tick − 開始) / fps / 速度` 秒に置く（負の開始は頭を切る）。`hz ≤ 0` / `ms ≤ 0` は捨てる。矩形波は位相 0 から `sign(sin(2π hz τ))`（τ は音の頭からの秒）× `TONE_GAIN`、頭と終わりに `FADE_SECONDS` の線形フェード、足して [−1, 1] に収める。
  `createEncoder`: `audio` があり、MP4 なら `aac`・WebM なら `opus` が `canEncodeAudio` で true のときだけ音声トラックを足す（`audio: true`）。無ければ映像だけ（`audio: false`）。e2e は URL の `?noaudio=1` で `canEncodeAudio` を false と見なす口（`main.ts` が読む）で無音の分岐を通す
- [ ] **Step 1: 失敗するテストを書く** — `sound.test.ts`: 1 つの `tone(440, 100)` が tick 30（fps 30・開始 0・速度 1）で 1.0 秒・長さ 0.1 秒に置かれる、PCM の長さが映像と同じ、0.5 倍速で 2.0 秒に置かれ長さは 0.1 秒のまま、開始より前に鳴り始めて食い込む音は頭が切れる、終わりを越える音は切れる、同時の 2 音が足されて [−1, 1] に収まる、フェードで頭の 1 サンプル目が 0、同じ入力なら同じ PCM、`frame` の無いトレースで全部 0
- [ ] **Step 2: 落ちることを見る** — `pnpm vitest run test/sound.test.ts`。期待: FAIL
- [ ] **Step 3: 実装** — `sound.ts`・`createEncoder` の音声トラック（probe の API で `AudioSample` を 1 本で足す）・`main.ts`（書き出しの開始で `synthesize` → `createEncoder` に渡す。`audio: false` なら `#status` に「音声のコーデックが無いため無音で書き出しました」。プレビューは再生中に tick が進むたびに、その tick の `frame` の `tone` を `AudioContext` の矩形波（音量 0.08）で鳴らす。スクラブ中と `stage-mute` が押されている間は鳴らさない。`AudioContext` は再生ボタンの click で作る）
- [ ] **Step 4: e2e** — 音の fixture: tetris はミノの固定（`lock`）で `tone` を鳴らすが、操作の無い 90 tick の fixture では固定が起きない。
  ハードドロップを 3 回する 120 tick の録画 `tests/fixtures/jinrec/tetris-drops.jinrec`（手書き: tick 4 / 34 / 64 に `Space` の押下と離し）を置き、
  `uv run jin run examples-v2/tetris/tetris.jin --input tests/fixtures/jinrec/tetris-drops.jinrec --trace apps/stage/test/fixtures/tetris-drops-trace.jsonl` で作る
  （`tone` が 3 回以上あることを `sound.test.ts` の fixture の検査で見る）。e2e: 「この場面の 2 秒（tick 0〜60）を書き出し、読み戻すと音声トラックがあり長さが映像 ± 0.1 秒」と
  「`?noaudio=1` で書き出すと音声トラックが無く、ファイルは渡る」
- [ ] **Step 5: 走らせる** — `pnpm test && pnpm lint && pnpm build && pnpm e2e`。期待: PASS
- [ ] **Step 6: Commit** — `feat(stage): 音（tone の合成・プレビュー・書き出しの音声トラック）`

---

### Task 8: dev.html・変異・文書・見てもらう動画

**Files:**
- Modify: `apps/stage/dev.html`（`stageSize` を送る）
- Modify: `delivery/<最新>/stage-mutations/mutate_stage.py`・`RESULT.md`
- Modify: `docs/spec/v2/stage.md`（§1・新しい節「召喚の窓」・§5 の音・§6・§7）・`CLAUDE.md`・`docs/superpowers/specs/2026-09-17-jin-stage-design.md`（§0 の第 2 段階に注記）

- [ ] **Step 1: 変異を足す** — (1) `draw.ts` の `rect` を描かない → 画素一致の e2e は回さないので `draw.test.ts` が赤 (2) `screen/glyphs.ts` の `BITMAPS` を 1 文字ずらす → 契約テストが赤 (3) `toneEvents` で速度を掛けない → `sound.test.ts` が赤 (4) `frameAt` が最古の frame を返す → `frames.test.ts` が赤。`mutate_stage.py` を回して 21/21 を確かめ、`RESULT.md` を更新
- [ ] **Step 2: 文書** — stage.md に「召喚の窓」の節（位置・画面・縁・開閉・`stageSize`・写しの守り方）と §5 の音（合成・音声トラック・無いときは無音）と §7 の確定値。CLAUDE.md の鑑賞ページの要点（字形の生成先が 2 か所・`font.ts` のバイト一致・画素一致の正解 PNG の作り直し方 `UPDATE_SCREEN_GOLDEN=1`・音）。旧設計書の §0 に注記
- [ ] **Step 3: 全ゲート** — `uv run pytest -q`、`apps/stage` / `apps/editor` / `apps/player` の `pnpm build && pnpm lint && pnpm test && pnpm e2e`（エディタの e2e は単独で回す）
- [ ] **Step 4: 見てもらう動画** — ① と同じ合成の tetris の録画（音を鳴らすよう `tone` を含むプログラムなら音つき。tetris に音が無ければ paddle の録画も 1 本）を鑑賞ページで再生し、斜め 45°・16:9・1080p で 15 秒の MP4 を書き出して場所を知らせる
- [ ] **Step 5: Commit** — `docs(stage): 召喚の窓と音を正典と CLAUDE.md に反映・変異の実測`
