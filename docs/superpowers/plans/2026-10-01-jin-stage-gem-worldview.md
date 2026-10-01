# 鑑賞ページ: 宝玉と金細工の世界観と演出の全量 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 鑑賞ページ(`apps/stage`)の金一色の魔法陣を、力・記憶の型・陣ごとに色の違う宝玉と地金で描き、13 種の動きと 3D エフェクトを全部入れて動かせるようにする。

**Architecture:** 色と動きは three に依存しない純関数(`palette.ts` / `motion.ts` / `anchors.ts` / `effects.ts`)で決め、vitest で WebGL 無しに固定する。描画(`render/`)はそれを読んで宝玉・金細工・粒子・床・光の柱・後処理を組み立てる。エディタは名前の表に 3 欄(`sigilKinds` / `stateTypes` / `isRoot`)を足して渡すだけで、語彙は 4 語のまま。

**Tech Stack:** TypeScript 5.9.3 / three 0.186.0(addons の `Reflector` / `BokehPass` / `ShaderPass` / `UnrealBloomPass`)/ vitest 5.0.0 / Playwright 1.62.0 / pytest(契約テスト)

**Spec:** `docs/superpowers/specs/2026-10-01-jin-stage-gem-worldview-design.md`(仕様書 ①)。旧設計 `docs/superpowers/specs/2026-09-17-jin-stage-design.md`、正典 `docs/spec/v2/stage.md`

## Global Constraints

- 依存は増やさない: `apps/stage/package.json` の dependencies は `three` 0.186.0 と `mediabunny` 1.57.0 だけ(`tests/contract/test_stage_contract.py::test_the_only_runtime_dependencies_are_three_and_mediabunny`)
- `apps/stage/src/` のうち `main.ts` 以外で `Math.random` / `Date.now` / `performance.now` / `new Date(` を書かない。乱数は `src/random.ts` の `mulberry32(seed)`(種は `seq` か固定値)
- 配置は SVG から取る。宝玉の位置は場面の要素(`SceneItem.shape`)からだけ求め、レイアウト規則を再実装しない
- エディタとの語彙は `stage.scene` / `stage.trace` / `stage.status` / `stage.file` の 4 語。書いてよいのは `apps/stage/src/messages.ts` と `apps/editor/src/stage/StagePanel.tsx` だけ
- three と mediabunny は `apps/stage` にだけ import する
- `apps/stage` と `apps/editor` は互いに import しない(名前の表の型は両側に同じ形を書く)
- API は記憶で書かない: three 0.186.0 の部品は Task 1 の probe(`delivery/<最新の *-jin>/stage-api-probe.md`)に実測を残してから使う
- 色・長さ・強さの値は仕様書 ① §2 / §5 の初期値をそのまま使い、目視で変えたものだけ stage.md §7 に根拠つきで残す
- 各タスクの終わりに `cd apps/stage && pnpm lint && pnpm test` と `uv run pytest tests/contract/test_stage_contract.py tests/spec/test_stage_spec_consistency.py` が通る
- コミットメッセージの末尾に `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`

## Review Focus

- **古いエディタからの場面**(名前の表に `sigilKinds` / `stateTypes` / `isRoot` が無い)→ 例外を投げず、宝玉は金・地金は並び順で描く(Task 2 の `palette.test.ts`・Task 3 の `messages.test.ts`)
- **手順の図(`--focus 陣/手順`)の場面**(`sigil` / `state` が無く `step` だけ)→ 宝玉を置かずに描け、光線は祖先へ遡った要素へ飛ぶ(Task 4 の `anchors.test.ts`・Task 9 の e2e)
- **長い録画**(tetris の 60000 行)→ 粒子は上限 4096、光線は上限 24 本を超えず、1 フレームの `glowsAt` は今と同じく最長の演出より古い発火を読まない(Task 7 の `particles.test.ts`)
- **陣の中で自分の手順を呼ぶ `cast`**(`name` に `.` が無い・`fits` など)と**未知の名前空間** → 金(Task 2 の `palette.test.ts`)
- **編集のたびに届く `stage.scene`** → 床の映り込みの描画先・後処理・宝玉の素材を前の場面の分まで解放し、GPU の資源が増え続けない(Task 8 の e2e の `renderer.info.memory`)

---

### Task 1: three 0.186.0 の部品の probe

**Files:**
- Modify: `delivery/<最新の *-jin>/stage-api-probe.md`(`tests.conftest.delivery_run()` が解決するディレクトリ。直書きのパスをテストに書かない)
- Create: `apps/stage/test/threeApi.test.ts`

**Interfaces:**
- Produces: probe の節「§E 宝玉と後処理(0.186.0)」。後のタスクはここに書いた import パスと引数の形だけを使う

- [ ] **Step 1: 失敗するテストを書く** — `threeApi.test.ts`(jsdom・描画しない):
  - `import { Reflector } from "three/addons/objects/Reflector.js"` を `new Reflector(new THREE.PlaneGeometry(1, 1), { textureWidth: 64, textureHeight: 64, color: 0x101018 })` で作れて `getRenderTarget()` が `WebGLRenderTarget`
  - `import { BokehPass } from "three/addons/postprocessing/BokehPass.js"` を `new BokehPass(scene, camera, { focus: 3, aperture: 0.002, maxblur: 0.006 })` で作れて `uniforms` に `focus` / `aperture` / `maxblur`
  - `import { ShaderPass } from "three/addons/postprocessing/ShaderPass.js"` が `{ uniforms, vertexShader, fragmentShader }` を受ける
  - `new THREE.MeshPhysicalMaterial({ transmission: 1, ior: 2.42, dispersion: 0.3, thickness: 0.05, attenuationColor: 0x2f6bff, clearcoat: 1 })` の `dispersion === 0.3`
  - `new THREE.InstancedMesh(geometry, material, 4096)` に `setMatrixAt` / `setColorAt` / `count` がある
- [ ] **Step 2: 走らせる** — `cd apps/stage && pnpm vitest run test/threeApi.test.ts`。期待: import パスか欄が違えば FAIL、全部合えば PASS(probe はテストが証拠)
- [ ] **Step 3: probe に追記** — 実測した import パス・コンストラクタの引数・`Reflector` が描画先を `dispose()` で解放すること(`dispose` があるか)・`BokehPass` / `ShaderPass` の `setSize`・`dispersion` が three r163 以降の欄であることを §E に表で書く
- [ ] **Step 4: Commit** — `git commit -m "test(stage): three 0.186.0 の Reflector / BokehPass / ShaderPass / dispersion / InstancedMesh を実測"`

---

### Task 2: 色の意味体系(`palette.ts`)と正典の表

**Files:**
- Create: `apps/stage/src/palette.ts`
- Create: `apps/stage/test/palette.test.ts`
- Modify: `apps/stage/src/names.ts`(`CircleNames` に任意の 3 欄)
- Modify: `docs/spec/v2/stage.md`(§2 の後に「宝玉」の節と 3 つの machine-readable 表 `stage-gems` / `stage-state-gems` / `stage-metals`)
- Modify: `docs/superpowers/specs/2026-10-01-jin-stage-gem-worldview-design.md`(§4 と §12 #7 を `isRoot` に直す。下の「仕様書の訂正」)
- Modify: `tests/spec/test_stage_spec_consistency.py`・`tests/contract/test_stage_contract.py`

**仕様書の訂正:** 「root は常にイエローゴールド」には root を知る必要があるが、名前の表に root の情報は無い。陣ごとに任意の `isRoot?: boolean` を足す(地金そのものは送らない)。仕様書 ① §4 のコードブロックに `isRoot` を足し、§12 #7 を「地金は pointer の i と `isRoot` から stage が決める」に直す。

**Interfaces:**
- Consumes: `TraceRow` / `StageNames` / `circleOf`(`src/names.ts`)
- Produces(`src/palette.ts`・three を import しない):
  ```ts
  export type GemId = "sapphire" | "emerald" | "peridot" | "amethyst" | "opal" | "amber" | "moonstone" | "gold"
    | "topaz" | "diamond" | "ruby" | "garnet" | "citrine" | "aquamarine" | "pearl" | "onyx" | "tourmaline" | "spinel" | "crystal";
  export interface GemSpec { readonly color: number; readonly ior: number; readonly color2?: number }
  export const GEMS: Readonly<Record<GemId, GemSpec>>;
  export const POWER_GEMS: Readonly<Record<string, GemId>>;   // 力(名前空間 / "summon" / "agent")→ 宝玉
  export type MetalId = "yellow" | "rose" | "white" | "platinum";
  export interface MetalSpec { readonly color: number; readonly roughness: number }
  export const METALS: Readonly<Record<MetalId, MetalSpec>>;
  export const METAL_CYCLE: readonly MetalId[];               // ["rose", "white", "platinum"]
  export function stateGem(type: string | undefined): GemId;
  export function metalOf(circlePointer: string | null, names: StageNames): MetalId;
  export function gemOfRow(row: TraceRow, names: StageNames): GemId;
  export function gemOfElement(kind: string, pointer: string, names: StageNames): GemId | null;
  export function gemColorAt(gem: GemId, seconds: number, seq: number): number; // 0xRRGGBB
  ```
  `src/names.ts` の `CircleNames` に `readonly sigilKinds?: Readonly<Record<string, string>>; readonly stateTypes?: Readonly<Record<string, string>>; readonly isRoot?: boolean;`

- [ ] **Step 1: 失敗するテストを書く** — `palette.test.ts`。名前の表の fixture は `{ Play: { pointer: "/circles/1", sigils: { canvas: "/circles/1/sigils/0", input: "/circles/1/sigils/1" }, state: { score: "/circles/1/state/3", board: "/circles/1/state/0", over: "/circles/1/state/8", piece: "/circles/1/state/1" }, delegates: {}, sigilKinds: { canvas: "canvas", input: "input" }, stateTypes: { score: "num", board: "list<num>", over: "bool", piece: "Piece" } }, Game: { pointer: "/circles/0", sigils: {}, state: {}, delegates: {}, isRoot: true } }`
  - `gemOfRow({kind:"cast", name:"canvas.rect", circle:"Play", …})` → `"sapphire"`、`"input.pressed"` → `"emerald"`、`"fits"`(`.` 無し)→ `"gold"`、`"nope.x"` → `"gold"`
  - `set score` → `"citrine"`、`set board` → `"tourmaline"`、`set piece` → `"spinel"`、`set over` は `output: true` → `"pearl"`・`output: false` → `"onyx"`
  - `transfer` → `"topaz"`、`emit` → `"diamond"`、`assert` → `"ruby"`、`error` → `"garnet"`、`event` の `name` `"key"` / `"pointer"` → `"emerald"`・`"message"` → `"diamond"`・`"tick"` / `"exit"` → `"gold"`、`enter` / `rite` / `wait` / `finish` → `"gold"`
  - 3 欄の無い表(`{ Play: { pointer, sigils, state, delegates } }`)でも `cast canvas.rect` → `"gold"`、`set score` → `"gold"`(例外なし)
  - `stateGem("num")` `"citrine"`・`"str"` `"aquamarine"`・`"bool"` `"pearl"`・`"list<str>"` `"tourmaline"`・`"Piece"` `"spinel"`・`undefined` / `""` `"gold"`
  - `metalOf("/circles/0", names)` → `"yellow"`(isRoot)・`"/circles/1"` → `"rose"`・root が `/circles/2` の表で `/circles/0` → `"rose"`, `/circles/1` → `"white"`, `/circles/3` → `"platinum"`, `/circles/4` → `"rose"`・`null`(額縁)→ `"yellow"`・`isRoot` がどこにも無い表では i の順に root を数えず `/circles/0` → `"rose"`
  - `gemOfElement("sigil", "/circles/1/sigils/0", names)` → `"sapphire"`・`("state", "/circles/1/state/3")` → `"citrine"`・`("core", …)` → `"diamond"`・`("on", …)` → `"crystal"`・`("guard", …)` → `"ruby"`・`("delegate", …)` → `"topaz"`・`("rite", …)` → `null`
  - `gemColorAt("sapphire", 0, 0) === 0x2f6bff`、`gemColorAt("opal", s, seq)` は s と seq で色相が変わり、同じ引数なら同じ値
- [ ] **Step 2: 走らせて落ちることを見る** — `pnpm vitest run test/palette.test.ts`。期待: `palette.ts` が無くて FAIL
- [ ] **Step 3: 実装** — 色と屈折率は仕様書 ① §2.1〜§2.3 の値。`GEMS.tourmaline` は `color: 0x3ad08a, color2: 0xff7aa8`、`crystal` は `color: 0xe8f0ff, ior: 1.54`、`pearl` `0xf4f0e8`、`onyx` は `color: 0x14141a, color2: 0xc8ccd8`。`gemOfElement` は pointer → 名前を `sigils` / `state` の逆引きで求める。オパールは HSL の色相を `(seconds * 0.15 + mulberry32(seq)()) mod 1`・彩度 0.6・明度 0.7 で回す
- [ ] **Step 4: 正典の表と契約テスト** — stage.md §2 の後に「### 2.1 宝玉」を足し、3 つの表を `<!-- machine-readable: stage-gems -->`(列: 力 | 宝玉 | 色 | 屈折率)・`stage-state-gems`(型 | 宝玉)・`stage-metals`(順 | 地金 | 色 | 粗さ)で書く。`test_stage_spec_consistency.py` に `stage_gems()` などの読み手を足し、`test_stage_contract.py` に `test_the_gems_in_the_code_are_the_tables_of_stage_md`(`palette.ts` の `POWER_GEMS` / `GEMS` の 16 進と屈折率・`METALS` を正規表現で抜いて表と等号)を足す
- [ ] **Step 5: 走らせる** — `pnpm vitest run test/palette.test.ts` と `uv run pytest tests/contract/test_stage_contract.py tests/spec/test_stage_spec_consistency.py -q`。期待: PASS
- [ ] **Step 6: Commit** — `feat(stage): 色の意味体系（力の宝玉・記憶の型の宝玉・陣の地金）と stage.md の表`

---

### Task 3: エディタの名前の表に 3 欄

**Files:**
- Modify: `apps/editor/src/stage/names.ts`
- Modify: `apps/editor/test/stageNames.test.ts`
- Modify: `apps/stage/src/messages.ts`・`apps/stage/test/messages.test.ts`

**Interfaces:**
- Consumes: `CircleNames` の 3 欄(Task 2。エディタ側にも同じ形を書く)
- Produces: `buildStageNames(model)` が陣ごとに `sigilKinds`(`kind == "host"` なら `host`、それ以外は `kind`)・`stateTypes`(state の `type` そのまま)・`isRoot`(`model.root` と陣名が等しい陣だけ `true`、他は欄ごと省く)を出す

- [ ] **Step 1: 失敗するテストを書く** — `stageNames.test.ts` に `examples-v2/tetris/tetris.jin` の JSON を読んだモデルで: `Play.sigilKinds` が `{ canvas: "canvas", input: "input", audio: "audio", random: "random" }`、`Play.stateTypes.board === "list<num>"`・`piece === "Piece"`・`over === "bool"`、`Game.isRoot === true`、`Play.isRoot === undefined`。`examples-v2/othello/othello.jin` で `agent` の sigil が `"agent"`。stage 側の `messages.test.ts` に「3 欄があってもなくても `parseInbound` が `stage.scene` を受ける」
- [ ] **Step 2: 落ちることを見る** — `cd apps/editor && pnpm vitest run test/stageNames.test.ts`。期待: FAIL(欄が無い)
- [ ] **Step 3: 実装** — `names.ts` に 3 欄。stage の `messages.ts` は `names` をそのまま受けている(欄の検査をしない)ので変えない。テストで受けることだけを固定する
- [ ] **Step 4: 走らせる** — `cd apps/editor && pnpm test && pnpm lint`、`cd apps/stage && pnpm test`。期待: PASS
- [ ] **Step 5: Commit** — `feat(editor): 鑑賞ページの名前の表に sigilKinds / stateTypes / isRoot`

---

### Task 4: 宝玉の置き場所と、宝玉・地金の立体

**Files:**
- Create: `apps/stage/src/anchors.ts`・`apps/stage/test/anchors.test.ts`
- Create: `apps/stage/src/render/gems.ts`
- Modify: `apps/stage/src/render/gilded.ts`(`buildGilded(scene, names)`・地金ごとの素材・宝玉の配置)
- Modify: `apps/stage/src/render/stageRenderer.ts`(`setScene(scene, names)`・背景・霧・光)
- Modify: `apps/stage/src/main.ts`(`renderer.setScene(parseScene(svg), names)`)

**Interfaces:**
- Consumes: `GemId` / `GEMS` / `METALS` / `metalOf` / `gemOfElement`(Task 2)
- Produces:
  ```ts
  // src/anchors.ts(three を import しない)
  export interface Anchor { readonly pointer: string; readonly kind: string; readonly center: Vec2; readonly radius: number; readonly layer: LayerIndex; readonly unit: number; readonly circle: string | null }
  export const GEM_KINDS: ReadonlySet<string>; // sigil / state / core / on / guard / delegate
  export function anchorsOf(scene: Scene): readonly Anchor[]; // pointer ごとに text 以外の形の外接矩形 → 中心と半径(長辺の半分)。GEM_KINDS だけ
  // src/render/gems.ts
  export type Cut = "cabochon" | "step" | "brilliant" | "rhombus" | "trillion";
  export const CUT_OF_KIND: Readonly<Record<string, Cut>>; // sigil→cabochon, state→step, core→brilliant, on→rhombus, guard→trillion, delegate→cabochon
  export interface GemHandle { readonly anchor: Anchor; readonly gem: GemId; readonly mesh: THREE.Mesh; readonly material: THREE.MeshPhysicalMaterial; readonly glow: THREE.Sprite }
  export function buildGem(anchor: Anchor, gem: GemId, disposables: { dispose(): void }[]): GemHandle;
  // GildedModel に追加
  readonly gems: ReadonlyMap<string, GemHandle>; // key = pointer
  readonly pivots: ReadonlyMap<string, Vec2>;     // key = 陣の pointer(NO_CIRCLE は [0, 0])。陣の輪(kind "circle" の ring)の中心
  ```
- [ ] **Step 1: 失敗するテストを書く** — `anchors.test.ts`(fixture `test/fixtures/play.svg` を `parseScene`):`anchorsOf` が `sigil` / `state` / `core` / `on` / `guard` を含み `rite` / `circle` を含まない・同じ pointer は 1 つ・半径 > 0・中心がその pointer の要素の外接矩形の中にある。`jin render examples-v2/paddle/paddle.jin --focus Play/step` の SVG(fixture に足す: `test/fixtures/play-step.svg`)では空配列
- [ ] **Step 2: 落ちることを見る** — `pnpm vitest run test/anchors.test.ts`。期待: FAIL
- [ ] **Step 3: 実装** — `anchors.ts`。`gems.ts` の形: cabochon = 半球(`SphereGeometry` の上半分を z 方向に 0.6 倍)、step = 面取りした角柱(`ExtrudeGeometry` の bevel)、brilliant = 上下の錐(`LatheGeometry` の 8 角)、rhombus = 4 角の両錐、trillion = 3 角の両錐。大きさは `anchor.radius × 0.55`(core は × 0.5)を初期値とし、目視で決めた値を stage.md §7 に書く。素材は `MeshPhysicalMaterial`(`transmission` 0.9・`ior` = `GEMS[gem].ior`・`dispersion` 0.25・`thickness` = 半径 × 2・`attenuationColor` = 色・`clearcoat` 1・`roughness` 0.05)、中心に加算の `Sprite`(灯るまで不透明度 0)。`gilded.ts` は輪・線・点の素材を `METALS[metalOf(item.circle, names)]` から作る(段 0 は今の `GOLD_DIM` の比率で暗くする)
- [ ] **Step 4: 背景と光** — `stageRenderer.ts` の `BACKGROUND` を `0x05060c`、霧 `FogExp2(0x0a0d1c, 0.08)`、環境光を `0x1a1e30`・0.5、主光源と補助光の色を白寄り(`0xfff2dc` / `0xbfd0ff`)に。値は初期値で、目視で変えたら stage.md §7
- [ ] **Step 5: 走らせる** — `pnpm test && pnpm lint && pnpm build && pnpm e2e`。期待: 今の e2e(PNG と 1 秒の動画を書き出して読み戻す)が PASS
- [ ] **Step 6: Commit** — `feat(stage): 宝玉の置き場所と、宝玉・地金の立体`

---

### Task 5: 演出の表に `pulse`・発火に宝玉

**Files:**
- Modify: `apps/stage/src/effects.ts`・`apps/stage/test/effects.test.ts`
- Modify: `docs/spec/v2/stage.md`(§3 の `stage-effects` の `frame` の行・§3.2 に `beat`・§3.3 の長さ)
- Modify: `tests/spec/test_stage_spec_consistency.py`(`test_strength_is_one_of_three_words_and_frame_does_not_glow` を `…_and_frame_only_beats` に)

**Interfaces:**
- Consumes: `gemOfRow`(Task 2)
- Produces: `EffectName` に `"pulse"`、`Strength` に `"beat"`、`EFFECTS.frame = { effect: "pulse", strength: "beat" }`、`BEAT = 0.1`、`Firing` と `Glow` に `readonly gem: GemId`。`frame` 行は `target: "/stage"`・`source: null`・強さ `BEAT`(慣れの対象外)。`DURATION_SECONDS` を仕様書 ① §5.4 の値に
- [ ] **Step 1: 失敗するテストを書く** — `effects.test.ts` に: `frame` 行が `{ effect: "pulse", target: "/stage", strength: 0.1 }` の発火になり、100 tick 続いても 0.1 のまま・`cast canvas.rect` の発火の `gem` が `"sapphire"`・長さが `beam` 0.8 / `crown` 3.2 / `pulse` 0.5。今の慣れの規則のテストは残す
- [ ] **Step 2: 落ちることを見る** — `pnpm vitest run test/effects.test.ts`。期待: FAIL
- [ ] **Step 3: 実装** — `foldTrace` で `row.kind === "frame"` を `resolveTargets` より前に扱う(`resolveTargets` は変えない)
- [ ] **Step 4: 正典と突合テスト** — stage.md の表の `frame` を `` `pulse` `` / `` `beat` ``、§3.2 に「`beat` は常に 0.1」、§3.3 の長さを置き換え。spec テストは強さの語を `{"once", "habit", "beat"}` にし、`effects["frame"] == ("pulse", "beat")`
- [ ] **Step 5: 走らせる** — `pnpm test`・`uv run pytest tests/contract/test_stage_contract.py tests/spec/test_stage_spec_consistency.py -q`。期待: PASS
- [ ] **Step 6: Commit** — `feat(stage): frame の鼓動（pulse / beat）と発火ごとの宝玉`

---

### Task 6: 時刻から決まる形の変化(`motion.ts`)とカメラの足し分

**Files:**
- Create: `apps/stage/src/motion.ts`・`apps/stage/test/motion.test.ts`
- Modify: `apps/stage/src/camera.ts`・`apps/stage/test/camera.test.ts`

**Interfaces:**
- Consumes: `Glow`(Task 5)・`Vec2`・`LayerIndex`・`mulberry32`
- Produces:
  ```ts
  export type Vec3 = readonly [number, number, number];
  export const LAYER_SPIN_RAD_PER_SECOND = 0.03;
  export function layerSpin(layer: LayerIndex, seconds: number): number;          // 偶数層 +、奇数層 −
  export function rotateAbout(p: Vec2, pivot: Vec2, angle: number): Vec2;
  export function layerOffset(effect: EffectName, progress: number, layer: LayerIndex): number; // ignite: 層 i は進み (i/6, (i+1)/6) で 0→0.05·i、fade: 逆、crack: 全層 −0.04、他 0(陣の単位を掛ける前)
  export function crackTilt(progress: number): number;                             // rad。0 → 0.06
  export function arcPoint(from: Vec3, to: Vec3, t: number): Vec3;                 // 2 次ベジェ。制御点は中点 + z に 距離 × 0.35
  export function pillarHeight(progress: number): number;                          // 0 → 2.4(ease-out)
  export function rippleRadius(progress: number): number;                          // 0 → 0.25
  export interface CameraNudge { readonly distanceScale: number; readonly elevationDeg: number; readonly azimuthDeg: number }
  export function cameraNudge(glows: readonly Glow[]): CameraNudge;               // 仕様書 ① §5.3
  export function armillary(index: 0 | 1, seconds: number): { readonly tiltX: number; readonly tiltY: number; readonly spin: number };
  // camera.ts: cameraPose(preset, aspect, seconds, offset?, nudge?: CameraNudge)
  ```
- [ ] **Step 1: 失敗するテストを書く** — `motion.test.ts`: `layerSpin(0, 10) === -layerSpin(1, 10)` かつ `layerSpin(0, 10) === 0.3`、`rotateAbout([1, 0], [0, 0], π/2)` ≈ `[0, 1]`、`layerOffset("ignite", 0, 5) === 0`・`("ignite", 0.999, 5)` ≈ 0.25・層 2 は層 3 より先に上がり切る、`arcPoint(a, b, 0) = a`・`(…, 1) = b`・`(…, 0.5)` の z が両端より高い、`pillarHeight` は 0 → 2.4 で単調増加、`cameraNudge([])` = `{1, 0, 0}`・`enter` の進み 0.5 で `distanceScale` ≈ 0.9・`finish` の進み 0.5 で `elevationDeg` ≈ 8・`error` は同じ seq なら同じ揺れ、`armillary` は同じ秒なら同じ値。`camera.test.ts`: `nudge` を渡すと距離と仰角が変わり、仰角は 5°〜89° に収まる
- [ ] **Step 2: 落ちることを見る** — `pnpm vitest run test/motion.test.ts test/camera.test.ts`。期待: FAIL
- [ ] **Step 3: 実装** — 包絡は `effects.ts` と同じ立ち上がり 15% の山形を、寄りと仰ぎの量に掛ける。`error` の揺れは `mulberry32(glow.seq)` の 2 値で位相を決め、振幅 0.6°・周波数 18 Hz・進みに比例して減衰
- [ ] **Step 4: 走らせる** — `pnpm test && pnpm lint`。期待: PASS
- [ ] **Step 5: Commit** — `feat(stage): 時刻から決まる形の変化（層の自転・浮き沈み・弧・柱・カメラの足し分）`

---

### Task 7: 粒子の 1 系統と、光と宝玉の点灯

**Files:**
- Create: `apps/stage/src/particles.ts`(粒子の置き方の純関数)・`apps/stage/test/particles.test.ts`
- Create: `apps/stage/src/render/particleView.ts`(`InstancedMesh` に流す)
- Modify: `apps/stage/src/render/glowView.ts`(色を宝玉から・弧の光線・宝玉の点灯・層の自転と浮き沈み・波紋)

**Interfaces:**
- Consumes: `Glow`(`gem` 付き)・`gemColorAt`・`motion.ts` の関数・`GildedModel.gems` / `pivots`
- Produces:
  ```ts
  // src/particles.ts
  export const MAX_PARTICLES = 4096;
  export interface Particle { readonly position: Vec3; readonly color: number; readonly size: number; readonly alpha: number }
  export function burst(glow: Glow, at: Vec3, from: Vec3 | null, seconds: number): readonly Particle[]; // effect ごとの形(下)
  export function ambient(seconds: number): readonly Particle[];   // 漂う火の粉 260 + 藍の塵 200(種は mulberry32(1) / (2))
  export function collect(glows: readonly Glow[], resolve: (g: Glow) => { at: Vec3; from: Vec3 | null } | null, seconds: number): readonly Particle[]; // ambient を先頭に、合計 MAX_PARTICLES で打ち切る
  ```
  `burst` の形: `chant` 渦を巻いて `at` へ吸い込まれる 24 粒・`release` 放射状に外へ 32 粒(ダイヤの白 + 分光の色相)・`crown` 上へ噴き上がる 48 粒(全宝玉の色を巡る)・`flow` `from` → `at` の太い流れ 24 粒・`breathe` `at` の周りに落ちる砂 12 粒・`beam` 弧の上を走る 8 粒(`arcPoint`)・`flash` 記憶の四角の輪郭を一周する 6 粒(輪郭は `at` を中心にした正方形・半辺は宝玉の半径)・他は 0。色は `gemColorAt(glow.gem, seconds, glow.seq)`、明るさは `glow.intensity`、乱数は `mulberry32(glow.seq)`
- [ ] **Step 1: 失敗するテストを書く** — `particles.test.ts`: 同じ引数なら同じ粒子(決定性)・`beam` の粒子が `from` と `at` の間の弧の上・`chant` の粒子が進みとともに `at` へ近づく・`collect` に `crown` の発火を 200 個渡しても長さが `MAX_PARTICLES` 以下・発火が無くても `ambient` の 460 粒
- [ ] **Step 2: 落ちることを見る** — `pnpm vitest run test/particles.test.ts`。期待: FAIL
- [ ] **Step 3: 実装** — `particles.ts`、`particleView.ts`(1 つの `InstancedMesh`(小さな板・加算・`depthWrite: false`)に `setMatrixAt` / `setColorAt` / `count`。前の `Points` の火花と火の粉は消す)
- [ ] **Step 4: `glowView.ts` を作り直す** — (a) 宝玉の点灯: 光った pointer の `GemHandle` の `emissive` = 宝玉の色・`emissiveIntensity` = `BASE_EMISSIVE + level × EMISSIVE_GAIN`・内側の `Sprite` の不透明度 = level。`core` と `on` の宝玉は届いた発火の `gem` の色に染める (b) 金細工は今の点灯(色は地金)。`warn` / `crack` はルビー / ガーネットの色 (c) 光線: `beam` は `arcPoint` の 12 分割の折れ線にし、色は `gem` (d) 層: 陣ごとに `layerSpin` で `rotation.z`、`pivots` を中心にするよう位置を補正し、`layerOffset` を `layerHeight` に足す。`crack` は陣の root group を `crackTilt` で傾ける (e) 光線と粒子の端点は、ハンドルの中心を同じ `rotateAbout` で回してから使う(ずれない) (f) `spin`: 手順の小円の輪を進み × 2π だけ回し、同じ輪の写し(加算・金)を z に 0.08 × 進みだけ浮かせながら消す (g) `warn`: 陣の外周の半径まで広がる床の波紋をルビーの色で 1 本(Task 8 の `Floor.setRipples` が受ける。Task 8 の前は波紋を出さずに宝玉の脈動だけ) (h) `crack`: 陣の外周の輪から内へ、`mulberry32(seq)` で折れた 6 本の亀裂を光線の枠(`MAX_BEAMS`)を使ってガーネットの色で引き、陣の宝玉の自発光を外側から順に `BASE_EMISSIVE` の 0.3 倍まで落とす。`frame` の `pulse` は `/stage` の要素(額縁)だけを 0.1 で灯す(額縁の無い場面では何もしない)
- [ ] **Step 5: 走らせる** — `pnpm test && pnpm lint && pnpm build && pnpm e2e`。期待: PASS
- [ ] **Step 6: Commit** — `feat(stage): 粒子の 1 系統と、宝玉の色の光・弧の光線・層の自転と浮き沈み`

---

### Task 8: 床・光の柱・天球儀・刻印・後処理

**Files:**
- Create: `apps/stage/src/render/floor.ts`・`pillar.ts`・`armillary.ts`・`post.ts`
- Modify: `apps/stage/src/render/gilded.ts`(文字を刻印に)
- Modify: `apps/stage/src/render/stageRenderer.ts`(組み立て・`resize` で各パスの大きさ・`setScene` / `dispose` で解放・カメラの足し分)
- Modify: `apps/stage/e2e/stage.spec.ts`(GPU の資源が増え続けない)

**Interfaces:**
- Consumes: `pillarHeight` / `rippleRadius` / `armillary` / `cameraNudge`(Task 6)、Task 1 の probe の import パス
- Produces:
  ```ts
  export class Floor { constructor(); readonly object: THREE.Object3D; setRipples(r: readonly { at: Vec2; radius: number; color: number; alpha: number }[]): void; setSize(w: number, h: number): void; dispose(): void }
  export class Pillar { readonly object: THREE.Object3D; set(height: number, alpha: number, seconds: number): void; dispose(): void }
  export class Armillary { readonly object: THREE.Object3D; set(seconds: number): void; dispose(): void }
  export interface PostChain { readonly composer: EffectComposer; setSize(w: number, h: number, pixelRatio: number): void; update(frame: { seconds: number; coreScreen: Vec2; rays: number; focus: number }): void; dispose(): void }
  export function buildPost(renderer: THREE.WebGLRenderer, scene: THREE.Scene, camera: THREE.PerspectiveCamera): PostChain;
  ```
  後処理の順: `RenderPass` → `BokehPass`(focus = カメラから原点までの距離・aperture 0.0015・maxblur 0.005)→ ゴッドレイの `ShaderPass`(核の画面位置から放射状に 48 サンプル・濃さ = `rays`)→ `UnrealBloomPass`(初期値は今の 0.7 / 0.45 / 0.82)→ 仕上げの `ShaderPass`(色収差 0.0015・ビネット 0.35・グレイン 0.04。グレインの乱れは `seconds` から作る)→ `OutputPass`
- [ ] **Step 1: 失敗するテストを書く** — `e2e/stage.spec.ts` に「`stage.scene` を 5 回送り直しても `renderer.info.memory.geometries` と `textures` が 1 回目の後の値から増えない」(harness に `window.__jinStage.memory()` を足す。`main.ts` だけが window に生やす)
- [ ] **Step 2: 落ちることを見る** — `pnpm build && pnpm e2e -g "GPU"`。期待: 床と後処理を足した直後に解放漏れがあれば FAIL(足す前は PASS してよい。Step 3 の後にも見る)
- [ ] **Step 3: 実装** — 床: 層 0 よりさらに 0.05 下に半径 3 の円盤の `Reflector`(`textureWidth` / `Height` = 描画の大きさの半分・色 `0x0a0c16`)と、波紋の加算の輪(`rippleRadius`・色は `gem`)。光の柱: 半径 0.08 の開いた円柱・加算・上へ流れる帯のシェーダ(`seconds` で流す)・`crown` の進みで `pillarHeight`。天球儀: 半径 1.32 と 1.38 の細いトーラス 2 本・地金は root の地金・`armillary(i, seconds)`。刻印: `glyph` のテクスチャから `bumpMap` を作り、文字を金の板(`PlaneGeometry`・`metalness` 1)に貼る。カメラ: `draw` で `cameraNudge(frame.glows)` を `cameraPose` に渡す。`rays` は灯った宝玉の level の和(上限 1.5)
- [ ] **Step 4: 走らせる** — `pnpm test && pnpm lint && pnpm build && pnpm e2e`。期待: PASS(GPU の資源のテストを含む)
- [ ] **Step 5: Commit** — `feat(stage): 床の反射・光の柱・天球儀の輪・刻印の文字・後処理（被写界深度・ゴッドレイ・色収差・ビネット・グレイン）`

---

### Task 9: 目視の切り替えと e2e の色の検査

**Files:**
- Modify: `apps/stage/dev.html`・`apps/stage/e2e/harness.ts`・`apps/stage/e2e/stage.spec.ts`
- Create: `apps/stage/test/fixtures/tetris.svg`・`tetris-names.json`・`tetris-trace.jsonl`・`play-step.svg`(Task 4 で作っていなければ)

**Interfaces:**
- Consumes: すべての前のタスク
- Produces: dev.html で fixture(paddle / tetris)と kind(13 種)を選んで、その kind の発火 1 回だけを流せる

- [ ] **Step 1: fixture を作る** — `uv run jin render examples-v2/tetris/tetris.jin --focus Play -o apps/stage/test/fixtures/tetris.svg`、`uv run jin run examples-v2/tetris/tetris.jin --ticks 90 --trace apps/stage/test/fixtures/tetris-trace.jsonl`、`tetris-names.json` は Task 3 の `buildStageNames` と同じ規則で(`apps/editor` の vitest に「tetris のモデル → この JSON と等しい」を足して、生成物とずれないことを固定する)。`tests/contract/test_stage_contract.py::test_the_svg_fixture_is_what_the_renderer_draws_today` を tetris の SVG にも広げる
- [ ] **Step 2: 失敗する e2e を書く** — 「tetris の場面で `cast canvas.rect` の発火の直後(進み 0.2)の PNG に、サファイアの色相(H 210°〜235°・S ≥ 0.45・V ≥ 0.35)の画素が全体の 0.2% 以上ある」、「手順の図(`play-step.svg`)を送っても `stage.status.error` が null で PNG が書き出せる」
- [ ] **Step 3: 走らせて状態を見る** — `pnpm build && pnpm e2e`。期待: 色の検査が PASS しなければ宝玉の色・自発光の値を見直す
- [ ] **Step 4: dev.html** — fixture と kind の選択を足す(選んだ kind の行だけを残したトレースを `stage.trace` で流す)
- [ ] **Step 5: Commit** — `test(stage): tetris の fixture・宝玉の色の e2e・dev.html の kind の切り替え`

---

### Task 10: 変異の実測・文書・見てもらう動画

**Files:**
- Modify: `delivery/<最新の *-jin>/stage-mutations/mutate_stage.py`・`RESULT.md`
- Modify: `docs/spec/v2/stage.md`(§1・§3 の動き・§4 のカメラの足し分・§7 の確定値)
- Modify: `docs/superpowers/specs/2026-09-17-jin-stage-design.md`(§2.1 / §2.3 の冒頭に置き換えの注記)
- Modify: `CLAUDE.md`(「Jin v2.1(鑑賞ページ)の要点」)

- [ ] **Step 1: 変異を足す** — (1) `POWER_GEMS` の canvas と input を入れ替える → `palette.test.ts` と契約テストが赤 (2) `particles.ts` に `Math.random` を混ぜる → 契約テストが赤 (3) `gemOfRow` で `sigilKinds` が無いときに throw → `palette.test.ts` が赤 (4) `glowView.ts` で光線の端点だけ `rotateAbout` を外す → `motion.test.ts` か e2e が赤。`uv run python delivery/<最新>/stage-mutations/mutate_stage.py` で 14 件(既存 10 + 4)がすべて赤になることを見て `RESULT.md` を更新
- [ ] **Step 2: 文書** — stage.md: §1 に宝玉と地金の一文、§3 に 13 種の動き(仕様書 ① §5.1 の表)、§4 にカメラの足し分(§5.3)、§7 に Task 4〜8 で目視して決めた値(宝玉の大きさの比・背景・霧・光・後処理の値)を「置き場所・根拠」つきで。旧設計書に注記。CLAUDE.md の鑑賞ページの段に: 宝玉と地金の 4 軸・名前の表の 3 欄(`sigilKinds` / `stateTypes` / `isRoot`)・`palette.ts` / `motion.ts` / `particles.ts` / `anchors.ts` は three を import しない純関数・後処理の順序・`frame` の `pulse`
- [ ] **Step 3: 全ゲート** — `uv run pytest -q`、`cd apps/stage && pnpm build && pnpm lint && pnpm test && pnpm e2e`、`cd apps/editor && pnpm build && pnpm lint && pnpm test && pnpm e2e`。期待: すべて PASS
- [ ] **Step 4: 見てもらう動画** — `apps/editor` の dist と `apps/stage` の dist を作り、`uv run jin editor examples-v2/tetris/tetris.jin --no-browser` で鑑賞モードを開き、録画(`tests/fixtures/jinrec/` に tetris の録画が無ければ実行パネルで 20 秒録る)を再生して、斜め 45°・16:9・1080 で 15 秒の MP4 を書き出す。`docs/images/` には置かず、ジョブの一時ディレクトリに置いて場所を知らせる
- [ ] **Step 5: Commit** — `docs(stage): 宝玉と金細工の世界観を正典と CLAUDE.md に反映・変異の実測`
