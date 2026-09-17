# 鑑賞ページ（stage）API 実測 probe

計測日: 2026-09-17。作業ディレクトリ `/Users/toyota/.claude/jobs/68fdfc7b/tmp/jin-stage-probe`（git リポジトリの外・コミットしない）。
macOS 15.7.7（`sw_vers`）、Node v22.12.0、pnpm 10.15.1。
すべての値はこのディレクトリで実際に実行して得た生出力から転記した。推測値は無い。
スクリプト全文は同ディレクトリの `src/probe.ts`（Step 3 の内容そのまま）、`probe.mjs`（Step 4〜6 を合成）、
`check_gpu.mjs` / `check_gpu_chrome.mjs` / `chrome_ver.mjs`（追加の確認用）に残してある。

## 計測値一覧

| 項目 | 値 |
|---|---|
| `three` / `mediabunny` / `@types/three` 版 | `0.186.0` / `1.57.0` / `0.186.0`（指定どおり） |
| `CanvasSource` の `bitrate: QUALITY_HIGH` | 動く。ただし `bitrate` フィールドも `QUALITY_HIGH` 定数も型定義上 `@deprecated`。**推奨は `quality: new Quality('high')`**（§B.3） |
| `canEncodeVideo("avc")`（Playwright 同梱 Chromium・ヘッドレス・SwiftShader） | `true` |
| `canEncodeVideo("vp9")`（同上） | `true` |
| `canEncodeVideo("avc")`（`channel: "chrome"`） | `true` |
| `canEncodeVideo("vp9")`（`channel: "chrome"`） | `true` |
| `canEncodeVideo("avc")` / `("vp9")`（Linux x86_64・CI と同じ Chromium 151.0.7922.34・PR #92 のマージ後に追記） | `true` / `true`（§C.1。CI の動画の往復は MP4 で走っている） |
| WebGL2（Playwright 同梱 Chromium・GPU なし） | `true`（`isWebGL2`）。renderer 文字列は `ANGLE (…, Vulkan 1.3.0 (SwiftShader Device …), SwiftShader driver)` |
| `UnrealBloomPass` を含む 30 コマ（640×360, 1 秒）の書き出し時間 | 同梱 Chromium: **520 ms** / `channel: "chrome"`: 2269 ms（§D） |
| Node での読み戻し | 可（`node readback 1 30 640 360`） |

---

## A. three 0.186.0

### A.1 addon の import パス

`node_modules/three/examples/jsm/` 配下に実在を確認:

```
$ ls node_modules/three/examples/jsm/lines/ node_modules/three/examples/jsm/postprocessing/ | grep -E "LineSegments2|LineMaterial|LineSegmentsGeometry|UnrealBloom|OutputPass|RenderPass|EffectComposer"
LineMaterial.js
LineSegments2.js
LineSegmentsGeometry.js
EffectComposer.js
OutputPass.js
RenderPass.js
SSAARenderPass.js
TAARenderPass.js
UnrealBloomPass.js

$ ls node_modules/three/examples/jsm/environments/
ColorEnvironment.js
DebugEnvironment.js
RoomEnvironment.js
```

つまり import パスは `three/addons/lines/LineMaterial.js`、`three/addons/lines/LineSegments2.js`、
`three/addons/lines/LineSegmentsGeometry.js`、`three/addons/postprocessing/{EffectComposer,RenderPass,UnrealBloomPass,OutputPass}.js`、
`three/addons/environments/RoomEnvironment.js`（`three/addons/` は `three` パッケージの `exports` マップが
`examples/jsm/` に貼るエイリアス。probe.ts で実際にこの形で import して動いた）。

`@types/three` 側にも同じ addon の型が揃っていることを確認した（TS のビルドが通る根拠）:

```
$ ls node_modules/@types/three/src/core/Timer.d.ts node_modules/@types/three/examples/jsm/lines/ node_modules/@types/three/examples/jsm/postprocessing/UnrealBloomPass.d.ts
node_modules/@types/three/examples/jsm/postprocessing/UnrealBloomPass.d.ts
node_modules/@types/three/src/core/Timer.d.ts

node_modules/@types/three/examples/jsm/lines/:
Line2.d.ts
LineGeometry.d.ts
LineMaterial.d.ts
LineSegments2.d.ts
LineSegmentsGeometry.d.ts
webgpu
Wireframe.d.ts
WireframeGeometry2.d.ts
```

### A.2 `LineSegments2` / `LineMaterial` / `LineSegmentsGeometry`

```
$ grep -n "class LineSegments2" -A15 node_modules/three/examples/jsm/lines/LineSegments2.js | head -20
251:class LineSegments2 extends Mesh {
252-
253-	/**
254-	 * Constructs a new wide line.
255-	 *
256-	 * @param {LineSegmentsGeometry} [geometry] - The line geometry.
257-	 * @param {LineMaterial} [material] - The line material.
258-	 */
259-	constructor( geometry = new LineSegmentsGeometry(), material = new LineMaterial( { color: Math.random() * 0xffffff } ) ) {
260-
261-		super( geometry, material );
262-
263-		/**
264-		 * This flag can be used for type testing.
265-		 *
266-		 * @type {boolean}
```

```
$ grep -n "class LineSegmentsGeometry" -A5 node_modules/three/examples/jsm/lines/LineSegmentsGeometry.js
23:class LineSegmentsGeometry extends InstancedBufferGeometry {
24-
25-	/**
26-	 * Constructs a new line segments geometry.
27-	 */
28-	constructor() {
```

`LineMaterial` のコンストラクタは `constructor( parameters )`（単一のオプションオブジェクト。色・幅などマテリアルの
プロパティ全部を受ける）。関連するユニフォームは `worldUnits` / `linewidth` / `resolution`（`new Vector2()`）の 3 つで、
`linewidth` は CSS ピクセル単位（`worldUnits: true` ならワールド単位）。**`resolution` はキャンバスのピクセルサイズを
明示的に渡さないと正しい太さで描けない**（デフォルトは `Vector2(0,0)`）。

**訂正（Task 8 のレビュー・three 0.186.0 のソースで確認）**: `LineSegments2` / `Line2` を使う限り、`resolution` を手で渡す必要は無い
（渡しても効かない）。`LineSegments2.onBeforeRender` が描くたびに `renderer.getViewport(_viewport)` の `z` / `w` で
`resolution` を上書きする（`examples/jsm/lines/LineSegments2.js` 419〜428 行）。`getViewport` が返すのは `setSize` / `setViewport` に
渡した CSS px で、`pixelRatio` を掛けていない（`src/renderers/WebGLRenderer.js` 793 行）。シェーダは `offset *= linewidth; offset /= resolution.y;`
（`LineMaterial.js` 240〜243 行）なので、線の太さは **`linewidth` CSS px（= `linewidth × pixelRatio` デバイス px）**。
画面の高さに占める割合は `linewidth / 高さ(CSS px)` で、EffectComposer の描画先の解像度には依存しない。

### A.3 `UnrealBloomPass`

```
$ grep -n "constructor(" -A5 node_modules/three/examples/jsm/postprocessing/UnrealBloomPass.js | head -10
46:	constructor( resolution, strength = 1, radius, threshold ) {
47-
48-		super();
49-
50-		/**
51-		 * The Bloom strength.
```

引数順は `(resolution: Vector2, strength = 1, radius, threshold)`。brief のコード
`new UnrealBloomPass(new THREE.Vector2(640, 360), 0.6, 0.4, 0.8)` はこの順序どおりで動いた（strength=0.6 / radius=0.4 / threshold=0.8）。

### A.4 `RoomEnvironment` / `PMREMGenerator.fromScene`

```
$ grep -n "class RoomEnvironment" -A5 node_modules/three/examples/jsm/environments/RoomEnvironment.js
33:class RoomEnvironment extends Scene {
34-
35-	constructor() {
36-
37-		super();
38-
```

**このバージョンの `RoomEnvironment` はコンストラクタ引数を取らない**（`Scene` のサブクラスで `new RoomEnvironment()` のみ。
古い three のドキュメントに残る `RoomEnvironment(renderer)` 形は 0.186.0 には無い）。

```
$ grep -n "fromScene\s*(" node_modules/three/src/extras/PMREMGenerator.js
107:	fromScene( scene, sigma = 0, near = 0.1, far = 100, options = {} ) {
```

`fromScene(scene, sigma=0, near=0.1, far=100, options={})`。brief の `fromScene(new RoomEnvironment(), 0.04)` は
`sigma=0.04`（ぼかし量）を指定し `near`/`far` は既定値のまま。戻り値の `.texture` を `scene.environment` に代入する形で動いた。

### A.5 `THREE.Clock` は非推奨・`THREE.Timer` を使う

```
$ grep -n "class Clock" -A5 node_modules/three/src/core/Clock.js
8:class Clock {
9-
10-	/**
11-	 * Constructs a new clock.
12-	 *
13-	 * @deprecated since 183.
```

```
$ grep -n "class Timer" -A3 node_modules/three/src/core/Timer.js
15:class Timer {
16-
17-	/**
18-	 * Constructs a new timer.
```

```
$ grep -n "export { Timer }" node_modules/three/src/Three.Core.js
110:export { Timer } from './core/Timer.js';
```

`import * as THREE from "three"` から実際に `Timer` / `Clock` の両方が生えていることも確認した:

```
$ node -e "import('three').then(m=>console.log(typeof m.Timer, typeof m.Clock))"
function function
```

`THREE.Clock` は r183 以降 `@deprecated`。**`THREE.Timer` を使う**（`three` の主エクスポートに含まれるので
`three/addons/` から import する必要は無い）。API は `new Timer()` → `timer.update(timestamp?)` → `timer.getDelta()` /
`timer.getElapsed()`（`connect(document)` で Page Visibility API を使う任意設定あり）。`Clock.getDelta()` のような
「呼ぶたびに時間が進む」設計ではなく、`update()` で内部状態を進めてから `getDelta()` / `getElapsed()` を
何度呼んでも同じ値を返す設計（Clock との違いとして js コメントに明記されている）。

---

## B. Mediabunny 1.57.0

`node_modules/mediabunny/dist/mediabunny.d.ts`（5580 行）から書き写した。パッケージは
`node_modules/mediabunny -> .pnpm/mediabunny@1.57.0/node_modules/mediabunny`（symlink）で、この環境の `find`
（macOS 同梱 BSD find）は `find node_modules/mediabunny -name "*.d.ts"` を素直に打つとヒット 0 件を返した
（`node_modules/mediabunny` 自体が symlink のため、既定ではシンボリックリンクの中を辿らない）。`ls` /
`grep` は symlink 越しでも問題なく通った。後続タスクで同種のスクリプトを書くときは `find -L` を使うか
`grep` を直接使うこと（GNU find でも同じ挙動になるかは未確認）。

### B.1 `Output` / `OutputOptions`

```
$ grep -n "export declare class Output\b" -A40 node_modules/mediabunny/dist/mediabunny.d.ts | head -80
3688:export declare class Output<F extends OutputFormat = OutputFormat, T extends Target = Target> extends EventEmitter<OutputEvents> {
3689-    /** The format of the output file. */
3690-    readonly format: F;
3691-    /** The current state of the output. */
3692-    state: 'pending' | 'started' | 'canceled' | 'finalizing' | 'finalized';
3693-    /**
3694-     * The {@link OutputTrackGroup} that all tracks are assigned to by default unless otherwise specified by
3695-     * {@link BaseTrackMetadata.group}.
3696-     */
3697-    readonly defaultTrackGroup: OutputTrackGroup;
3698-    /**
3699-     * The tracks that have been added to this output. Treat it as a readonly field; to add tracks, use the methods.
3700-     */
3701-    readonly tracks: OutputTrack[];
3702-    /**
3703-     * The target to which the root file will be written. Throws when using {@link PathedTarget} with an async callback;
3704-     * prefer the `'target'` event for those cases.
3705-     */
3706-    get target(): T;
3707-    /**
3708-     * Creates a new instance of {@link Output} which can then be used to create a new media file according to the
3709-     * specified {@link OutputOptions}.
3710-     */
3711-    constructor(options: OutputOptions<F, T>);
3712-    /** Adds a video track to the output with the given source. Can only be called before the output is started. */
3713-    addVideoTrack(source: VideoSource, metadata?: VideoTrackMetadata): OutputVideoTrack;
3714-    /** Adds an audio track to the output with the given source. Can only be called before the output is started. */
3715-    addAudioTrack(source: AudioSource, metadata?: AudioTrackMetadata): OutputAudioTrack;
3716-    /** Adds a subtitle track to the output with the given source. Can only be called before the output is started. */
3717-    addSubtitleTrack(source: SubtitleSource, metadata?: SubtitleTrackMetadata): OutputSubtitleTrack;
3718-    /**
3719-     * Sets descriptive metadata tags about the media file, such as title, author, date, or cover art. When called
3720-     * multiple times, only the metadata from the last call will be used.
3721-     *
3722-     * Can only be called before the output is started.
3723-     */
3724-    setMetadataTags(tags: MetadataTags): void;
3725-    /**
3726-     * Whether the output has enough tracks (of the correct type) to be started, based on the requirements of the output
3727-     * format.
3728-     */
```

続き（`start()` / `getMimeType()` / `cancel()` / `finalize()`。表示範囲外なので別途）:

```
$ sed -n '3729,3753p' node_modules/mediabunny/dist/mediabunny.d.ts
    hasEnoughTracks(): boolean;
    /**
     * Starts the creation of the output file. This method should be called after all tracks have been added. Only after
     * the output has started can media samples be added to the tracks.
     *
     * @returns A promise that resolves when the output has successfully started and is ready to receive media samples.
     */
    start(): Promise<void>;
    /**
     * Resolves with the full MIME type of the output file, including track codecs.
     *
     * The returned promise will resolve only once the precise codec strings of all tracks are known.
     */
    getMimeType(): Promise<string>;
    /**
     * Cancels the creation of the output file, releasing internal resources like encoders and preventing further
     * samples from being added.
     *
     * @returns A promise that resolves once all internal resources have been released.
     */
    cancel(): Promise<void>;
    /**
     * Finalizes the output file. This method must be called after all media samples across all tracks have been added.
     * Once the Promise returned by this method completes, the output file is ready.
     */
    finalize(): Promise<void>;
}
```

```
$ sed -n '3836,3853p' node_modules/mediabunny/dist/mediabunny.d.ts
export declare type OutputOptions<F extends OutputFormat = OutputFormat, T extends Target = Target> = {
    /** The format of the output file. */
    format: F;
    /** The target to which the file will be written. */
    target: T | PathedTarget<T>;
    /**
     * Optional; the target to which the track initialization data will be written. Most formats do not make use of
     * this, but some do, such as {@link CmafOutputFormat}.
     *
     * When this is a function, it will only be called if an init target is needed.
     */
    initTarget?: T | (() => MaybePromise<T>);
    /**
     * Optional; a callback to be called at the end of {@link Output.finalize}. Can be used to run logic once the
     * output has completed. If a promise is returned, it will be awaited internally by {@link Output.finalize}.
     */
    onFinalize?: () => MaybePromise<unknown>;
};
```

`new Output({ format, target })` は brief どおり。`output.addVideoTrack(source, { frameRate })` の第 2 引数は
`VideoTrackMetadata`（`frameRate?: number` を含む・`BaseTrackMetadata` を継承）。`output.start()` / `finalize()` /
`cancel()` はすべて `Promise<void>`。`state` は 5 値（`pending` / `started` / `canceled` / `finalizing` / `finalized`）。

### B.2 `BufferTarget`

```
$ sed -n '668,681p' node_modules/mediabunny/dist/mediabunny.d.ts
export declare class BufferTarget extends Target {
    /** Stores the final output buffer. Until the output is finalized, this will be `null`. */
    buffer: ArrayBuffer | null;
    /** Creates a new {@link BufferTarget}. The buffer holding the data will be created and managed internally. */
    constructor(options?: BufferTargetOptions);
}

/**
 * Options for {@link BufferTarget}.
 * @group Output targets
 * @public
 */
export declare type BufferTargetOptions = {
    /**
```

`target.buffer` の型は **`ArrayBuffer | null`**（finalize 前は `null`）。brief の `output.target.buffer!` は
non-null assertion で妥当（finalize 後に読むので null になり得ない）。

### B.3 `CanvasSource` / `VideoEncodingConfig` / `Quality`

```
$ grep -n "export declare class CanvasSource" -A8 node_modules/mediabunny/dist/mediabunny.d.ts
877:export declare class CanvasSource extends VideoSource {
878-    /**
879-     * Creates a new {@link CanvasSource} from a canvas element or `OffscreenCanvas` whose samples are encoded
880-     * according to the specified {@link VideoEncodingConfig}.
881-     */
882-    constructor(canvas: HTMLCanvasElement | OffscreenCanvas, encodingConfig: VideoEncodingConfig);
883-    /**
884-     * Captures the current canvas state as a video sample (frame), encodes it and adds it to the output.
885-     *
```

```
$ sed -n '4808,4823p' node_modules/mediabunny/dist/mediabunny.d.ts
 * Configuration object that controls video encoding. Can be used to set codec, quality, and more.
 * @group Encoding
 * @public
 */
export declare type VideoEncodingConfig = {
    /** The video codec that should be used for encoding the video samples (frames). */
    codec: VideoCodec;
    /** The desired quality of the encoded video. */
    quality?: Quality;
    /**
     * The target bitrate for the encoded video, in bits per second. Alternatively, a {@link Quality} can be provided.
     * @deprecated Use `quality` instead.
     */
    bitrate?: number | Quality;
    /**
     * The interval, in seconds, of how often frames are encoded as a key frame. The default is 2 seconds. Frequent key
```

```
$ sed -n '4095,4115p' node_modules/mediabunny/dist/mediabunny.d.ts
 * Represents a desired encoding quality. Can express a qualitative quality level, an explicit bitrate, an explicit
 * quantizer value, or a combination thereof.
 * @group Encoding
 * @public
 */
export declare class Quality {
    constructor(options: QualityOptions | number | QualityLevel);
}

/**
 * Represents a high media quality.
 * @deprecated Use `new Quality('high')` instead.
 * @group Encoding
 * @public
 */
export declare const QUALITY_HIGH: Quality;

/**
 * Represents a low media quality.
 * @deprecated Use `new Quality('low')` instead.
 * @group Encoding
```

**`bitrate` に `QUALITY_HIGH` を渡す brief のコード（`bitrate: MB.QUALITY_HIGH`）は実際に動く**（§C・§D の
書き出しはすべてこの形で成功した）。ただし `bitrate` フィールドも `QUALITY_HIGH` 定数も型定義上
`@deprecated`。**現行の書き方は `{ codec, quality: new Quality("high") }`**（§E に差分として記録）。

### B.4 `canEncodeVideo`

```
$ grep -n "canEncodeVideo\|export declare const QUALITY_\|export declare class Quality" -A6 node_modules/mediabunny/dist/mediabunny.d.ts
751:export declare const canEncodeVideo: (codec: VideoCodec, options?: {
752-    /** The width of the video in pixels. */
753-    width?: number;
754-    /** The height of the video in pixels. */
755-    height?: number;
756-    /** The desired quality of the encoded video. */
757-    quality?: Quality;
--
4100:export declare class Quality {
4101-    constructor(options: QualityOptions | number | QualityLevel);
4102-}
4103-
4104-/**
4105- * Represents a high media quality.
4106- * @deprecated Use `new Quality('high')` instead.
--
4110:export declare const QUALITY_HIGH: Quality;
4111-
4112-/**
4113- * Represents a low media quality.
4114- * @deprecated Use `new Quality('low')` instead.
4115- * @group Encoding
4116- * @public
--
4118:export declare const QUALITY_LOW: Quality;
4119-
4120-/**
4121- * Represents a medium media quality.
4122- * @deprecated Use `new Quality('medium')` instead.
4123- * @group Encoding
4124- * @public
--
4126:export declare const QUALITY_MEDIUM: Quality;
4127-
4128-/**
4129- * Represents a very high media quality.
4130- * @deprecated Use `new Quality('very-high')` instead.
4131- * @group Encoding
4132- * @public
--
4134:export declare const QUALITY_VERY_HIGH: Quality;
4135-
4136-/**
4137- * Represents a very low media quality.
4138- * @deprecated Use `new Quality('very-low')` instead.
4139- * @group Encoding
4140- * @public
--
4142:export declare const QUALITY_VERY_LOW: Quality;
4143-
4144-/**
4145- * A named qualitative quality level.
4146- * @group Encoding
4147- * @public
4148- */
```

（`canEncodeVideo` の `options` の残り: `bitrate?: number | Quality`〔`@deprecated Use quality instead`〕/ `frameRate?: number` /
`& VideoEncodingAdditionalOptions`。§B.3 の `VideoEncodingConfig` と同じ形）

brief の `canEncodeVideo(codec, { width: 640, height: 360 })` はこの形どおり（`width` / `height` だけ渡せば十分）。

### B.5 `Input` / `BufferSource` / `ALL_FORMATS` / 読み戻し

```
$ grep -n "export declare class Input\b\|computeDuration\|getPrimaryVideoTrack\|computePacketStats\|class BufferSource\|ALL_FORMATS" node_modules/mediabunny/dist/mediabunny.d.ts | head -20
62:export declare const ALL_FORMATS: InputFormat[];
653:declare class BufferSource_2 extends Source {
2390:export declare class Input<S extends Source = Source> extends EventEmitter<InputEvents> implements Disposable {
2434:    computeDuration(tracks?: InputTrack[], options?: PacketRetrievalOptions): Promise<number>;
2437:     * be approximate or diverge from the actual, precise duration returned by `.computeDuration()`, but compared to
2463:    getPrimaryVideoTrack(query?: InputTrackQuery<InputVideoTrack>): Promise<InputVideoTrack | null>;
2750:    computeDuration(options?: PacketRetrievalOptions): Promise<number>;
2753:     * approximate or diverge from the actual, precise duration returned by `.computeDuration()`, but compared to that
2774:    computePacketStats(targetPacketCount?: number, options?: PacketRetrievalOptions): Promise<PacketStats>;
```

```
$ sed -n '2592,2607p' node_modules/mediabunny/dist/mediabunny.d.ts
export declare type InputOptions<S extends Source = Source> = {
    /** A list of supported formats. If the source file is not of one of these formats, then it cannot be read. */
    formats: InputFormat[];
    /** The source from which data will be read. */
    source: S | SourceRef<S>;
    /**
     * An optional, second {@link Input} instance that contains the necessary metadata to initialize the tracks of
     * this input. This is necessary in cases where track initialization info and media data are carried in separate
     * files, like is the case with segmented MP4 (CMAF) files.
     *
     * The use of this field depends on the input format.
     */
    initInput?: Input;
    /** Can be used to specify additional per-format configuration. */
    formatOptions?: InputFormatOptions;
};
```

```
$ sed -n '2418,2422p;2456,2463p' node_modules/mediabunny/dist/mediabunny.d.ts
    getFirstTimestamp(tracks?: InputTrack[]): Promise<number>;
    /**
     * Computes the duration of the input file, in seconds. More precisely, returns the largest end timestamp among
     * all tracks.
     *
    getAudioTracks(query?: InputTrackQuery<InputAudioTrack>): Promise<InputAudioTrack[]>;
    /**
     * Returns the primary video track of this input file, or null if there are no video tracks.
     *
     * Multiple factors determine which track is considered primary, including its position in the file, disposition,
     * bitrate (higher bitrate is preferred), and if it can be paired with an audio track.
     */
    getPrimaryVideoTrack(query?: InputTrackQuery<InputVideoTrack>): Promise<InputVideoTrack | null>;
```

`new Input({ source: new BufferSource(bytes), formats: ALL_FORMATS })` は brief どおり（`BufferSource` の
コンストラクタ自体は `{source:...}` で包まず生の `AllowSharedBufferSource` を直接受ける）。`getPrimaryVideoTrack()`
の戻りは **`InputVideoTrack | null`**（brief の `!` は妥当だが、null チェック無しで使うコードを書くなら
後続タスクで明示する必要あり）。

`PacketStats`（`computePacketStats()` の戻り値）のキー:

```
$ sed -n '3964,3971p' node_modules/mediabunny/dist/mediabunny.d.ts
export declare type PacketStats = {
    /** The total number of packets. */
    packetCount: number;
    /** The average number of packets per second. For video tracks, this will equal the average frame rate (FPS). */
    averagePacketRate: number;
    /** The average number of bits per second. */
    averageBitrate: number;
};
```

`displayWidth` / `displayHeight`（`InputVideoTrack`）:

```
$ sed -n '2928,2941p' node_modules/mediabunny/dist/mediabunny.d.ts
    /** Returns the display width of the track's frames in pixels, after aspect ratio adjustment and rotation. */
    getDisplayWidth(): Promise<number>;
    /**
     * The display width of the track's frames in pixels, after aspect ratio adjustment and rotation.
     * @deprecated Use {@link InputVideoTrack.getDisplayWidth} instead.
     */
    get displayWidth(): number;
    /** Returns the display height of the track's frames in pixels, after aspect ratio adjustment and rotation. */
    getDisplayHeight(): Promise<number>;
    /**
     * The display height of the track's frames in pixels, after aspect ratio adjustment and rotation.
     * @deprecated Use {@link InputVideoTrack.getDisplayHeight} instead.
     */
    get displayHeight(): number;
```

**`track.displayWidth` / `track.displayHeight`（同期 getter）は動くが `@deprecated`。推奨は
`await track.getDisplayWidth()` / `await track.getDisplayHeight()`。** brief の Step 6 は同期 getter を使い、
実測でも `640` / `360` を正しく返した（§E に記録）。

---

## C. コーデックの可否（Chromium / Chrome）

| ブラウザ | 環境 | `avc` | `vp9` |
|---|---|---|---|
| Chromium（Playwright 同梱・ヘッドレス・`chromium.launch()`）151.0.7922.34 | macOS 15.7.7 / arm64 | `true` | `true` |
| Chrome（`channel: "chrome"`）153.0.8010.48 | macOS 15.7.7 / arm64 | `true` | `true` |
| Chromium（Playwright 同梱・ヘッドレス）151.0.7922.34 | Linux x86_64（`mcr.microsoft.com/playwright:v1.62.0-noble`・Ubuntu 24.04.4）— **CI と同じ Chromium のビルド**（§C.1） | `true`（360 / 1080 / 2160） | `true`（360 / 1080 / 2160） |

**本機（macOS 15.7.7 / arm64）では Chromium 同梱でも `avc` は `true` だった**ので、brief が想定した
「Chromium で `avc` が false なら vp9 に分岐する」フォールバックは今回不要だった。最初の計測は macOS でしか
取っていなかった（`jin-e2e-linux-only-drag-failures` の教訓どおり、Linux の Chromium は同梱の H.264 コーデックの有無が
異なる可能性がある）ので、PR #92 のマージ後に **CI と同じ Chromium のビルドで Linux x86_64 を実測し、`avc` / `vp9` とも
`true` で、実際に書き出して読み戻せる**ことを確かめた（§C.1）。`chooseCodec` は `avc` を先に試すので、CI の `stage` ジョブの
動画の往復は **MP4（H.264）** で走っている。e2e の分岐（`avc` → `vp9` → 不可）は、将来 Chromium の版や CI のイメージが
変わったときの網として残す。決め打ちで `avc` 固定にしない。

Playwright の `chromium.launch()` の版:

```
$ node chrome_ver.mjs
bundled chromium: 151.0.7922.34
channel chrome: 153.0.8010.48
```

`channel: "chrome"` は手元にインストール済みの Chrome を掴めた（Step 5 は `sed` でスクリプトを書き換えて実行）。

### C.1 CI（Linux x86_64）での確認（2026-09-17・PR #92 のマージ後に追記）

**CI の実行（GitHub Actions run 35230241160・`stage` ジョブ）のログから分かること**:

```
Image: ubuntu-24.04
Version: 20260907.300.1
  JIN_REQUIRE_CODEC: 1
Downloading Chrome for Testing 151.0.7922.34 (playwright chromium v1234) from https://cdn.playwright.dev/builds/cft/151.0.7922.34/linu…
Running 3 tests using 1 worker
  ✓  1 [chromium] › e2e/stage.spec.ts:34:1 › 陣が描かれ、トレースの行数が届く (7.1s)
  ✓  2 [chromium] › e2e/stage.spec.ts:55:1 › PNG を書き出す (8.5s)
  ✓  3 [chromium] › e2e/stage.spec.ts:67:1 › 1 秒の動画を書き出し、読み戻すと 60 コマ・約 1 秒 (14.6s)
  3 passed (32.7s)
```

`JIN_REQUIRE_CODEC=1` の下で動画の往復が skip されずに通ったので、CI の Chromium では `avc` か `vp9` の少なくとも
一方が使える。ログにはどちらを選んだかが出ない（e2e は `data-codec` を annotation に積むが、`list` レポーターは表示しない）。

**どちらかを確かめるため、CI と同じ Chromium のビルドを手元の Docker で x86_64 として動かした**
（本機は arm64 なので `--platform linux/amd64` のエミュレーション）。呼び方は `apps/stage/src/mediabunnyEncoder.ts` の
`canEncode` と同じ `canEncodeVideo(codec, { width, height, quality: new Quality("high") })`。続けて 360×360 の 2D canvas を
60 コマ（60 fps）書き出し、Mediabunny の `Input` で読み戻した。作業ディレクトリは
`/Users/toyota/.claude/jobs/68fdfc7b/tmp/ci-codec-probe`（リポジトリの外・コミットしない。`index.html` / `run.mjs`）。

```
$ docker run --rm --platform linux/amd64 --ipc=host -v "$S:/stage:ro" -v "$P:/probe" -w /probe \
    mcr.microsoft.com/playwright:v1.62.0-noble bash -c 'uname -m; cat /etc/os-release | grep PRETTY; node --version; node run.mjs'
x86_64
PRETTY_NAME="Ubuntu 24.04.4 LTS"
v24.18.0
chromium version: 151.0.7922.34
{
  "userAgent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/151.0.7922.34 Safari/537.36",
  "hasVideoEncoder": true,
  "canEncode": {
    "avc@360": true,
    "avc@1080": true,
    "avc@2160": true,
    "vp9@360": true,
    "vp9@1080": true,
    "vp9@2160": true
  },
  "encode": {
    "avc": {
      "bytes": 41091,
      "duration": 1,
      "packets": 60,
      "codec": "avc",
      "width": 360,
      "height": 360
    },
    "vp9": {
      "bytes": 57846,
      "duration": 1,
      "packets": 60,
      "codec": "vp9",
      "width": 360,
      "height": 360
    }
  }
}
```

- Chromium のビルドは CI と同じ `151.0.7922.34`（`playwright chromium v1234`）で、OS も CI と同じ Ubuntu 24.04 系
- `avc` / `vp9` とも、鑑賞ページの選択肢の長辺（1080 / 1440 / 2160 のうち 1080 と 2160）と e2e の 360 で `true`
- 実際の書き出しと読み戻しも、両コーデックで 60 パケット・1 秒・360×360
- **結論**: CI の `stage` ジョブの動画の往復は、`chooseCodec` が先に試す `avc`（MP4）で走っている。**VP9 の経路（WebM への
  フォールバック）は CI でも手元でも、e2e としてはまだ一度も通っていない**（両方 `true` なので分岐に入らない）。単体では
  `apps/stage/test/codec.test.ts` が分岐を固定している

---

## D. GPU なし環境（SwiftShader）での可否と書き出し時間

Playwright 同梱 Chromium（`chromium.launch()`）はデフォルトで SwiftShader（ソフトウェア WebGL）を使うことを
実測で確認した:

```
$ node check_gpu.mjs
{"vendor":"Google Inc. (Google)","renderer":"ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (LLVM 10.0.0) (0x0000C0DE)), SwiftShader driver)"}
```

この環境での probe 実行結果（`renderer.capabilities.isWebGL2` / `UnrealBloomPass` を含む 30 コマ・640×360・1 秒の書き出し）:

```
$ pnpm exec vite --port 5199 --strictPort > .../vite.log 2>&1 &
$ node probe.mjs
console: [vite] connecting...
console: [.WebGL-0x124004c6c00]GL Driver Message (OpenGL, Performance, GL_CLOSE_PATH_NV, High): GPU stall due to ReadPixels
console: [vite] connected.
console: [.WebGL-0x124004c6c00]GL Driver Message (OpenGL, Performance, GL_CLOSE_PATH_NV, High): GPU stall due to ReadPixels
console: [.WebGL-0x124004c6c00]GL Driver Message (OpenGL, Performance, GL_CLOSE_PATH_NV, High): GPU stall due to ReadPixels
console: [.WebGL-0x124004c6c00]GL Driver Message (OpenGL, Performance, GL_CLOSE_PATH_NV, High): GPU stall due to ReadPixels (this message will no longer repeat)
{
  "webgl2": true,
  "canEncode_avc": true,
  "canEncode_vp9": true,
  "encodeMs": 520,
  "bytes": 7494,
  "duration": 1,
  "packets": {
    "packetCount": 30,
    "averagePacketRate": 30,
    "averageBitrate": 53216
  }
}
node readback 1 30 640 360
```

`webgl2: true`（SwiftShader でも `WebGLRenderer` は WebGL2 コンテキストを取れる）。`UnrealBloomPass` を含む
`EffectComposer` のパイプラインは例外なく描画できた（GL Driver Message は `GPU stall due to ReadPixels` という
性能に関する警告のみで、失敗ではない。原因は未確認だが、`preserveDrawingBuffer: true` + 毎フレーム `add()` で
GPU→CPU の読み戻しが起きることと符合する）。30 コマ（640×360, 1 秒 @30fps）の `Output.start()` 〜 `finalize()` は
**520 ms**。Node での読み戻し（`Input` + `BufferSource` + `ALL_FORMATS`）は `node readback 1 30 640 360` で、
期待値（duration≈1, packetCount=30, 640×360）と一致した。

`channel: "chrome"`（実 Chrome・153.0.8010.48・こちらもデフォルトはヘッドレス）は SwiftShader ではなく
**実 GPU（ANGLE 経由の Metal）**を使うことを確認した:

```
$ node check_gpu_chrome.mjs
{"vendor":"Google Inc. (Apple)","renderer":"ANGLE (Apple, ANGLE Metal Renderer: Apple M4 Pro, Unspecified Version)"}
```

同じ書き出しは:

```
$ node probe.mjs   # channel: "chrome" に書き換え後
console: [vite] connecting...
console: [vite] connected.
console: Failed to load resource: the server responded with a status of 404 (Not Found)
{
  "webgl2": true,
  "canEncode_avc": true,
  "canEncode_vp9": true,
  "encodeMs": 2269,
  "bytes": 9953,
  "duration": 1,
  "packets": {
    "packetCount": 30,
    "averagePacketRate": 30,
    "averageBitrate": 72872
  }
}
node readback 1 30 640 360
```

（404 は `favicon.ico` 相当の無害なリクエスト。`encodeMs` が同梱 Chromium〔SwiftShader・520 ms〕より
`channel: "chrome"`〔実 GPU・2269 ms〕の方が長いのは、実測はこの 1 回だけで確定的な原因までは切り分けていないが、
`preserveDrawingBuffer: true` + 毎フレーム `add()` で行う GPU→CPU 読み戻しのコストが実 GPU 経由（Metal）の方が
大きく出た、という向きと符合する。後続タスクでタイミングに依存する assertion を書くなら、両ブラウザで測り直すこと）

---

## E. 本計画のコードとの差分

brief の Step 3 の `probe.ts` はそのままの形（1 文字も変えず）で動いた。例外は出ていない。差分は次の 3 点（1・2 は
「動くが非推奨」という形で、値やロジックは変わらない）:

1. **`CanvasSource` の `bitrate: MB.QUALITY_HIGH` は動くが非推奨**（§B.3）。`bitrate` フィールドと `QUALITY_HIGH`
   定数の両方が型定義上 `@deprecated`。後続タスクのコードは `quality: new Quality("high")`（`import { Quality } from
   "mediabunny"`）を使うこと。`canEncodeVideo` の `bitrate` オプションも同様（brief は使っていないので影響なし）。
2. **`InputVideoTrack.displayWidth` / `.displayHeight`（同期 getter）は動くが非推奨**（§B.5）。後続タスクで
   Node 側の読み戻しコードを書くときは `await track.getDisplayWidth()` / `await track.getDisplayHeight()` を使うこと。
3. **`LineMaterial.resolution` を手で渡す必要は無い**（§A.2 の訂正。Task 8 のレビューで判明）。`LineSegments2.onBeforeRender` が
   毎回 CSS px のビューポートで上書きするので、`linewidth` は CSS px。解像度に比例させたいなら `linewidth` 側を変える。
4. **Task 11（書き出し）で 1・2 を反映した実測**（2026-09-17・Playwright 同梱 Chromium・macOS arm64）。
   `apps/stage/src/mediabunnyEncoder.ts` は `canEncodeVideo(codec, { width, height, quality: new Quality("high") })` と
   `new CanvasSource(canvas, { codec, quality: new Quality("high") })` で書いた（brief の `bitrate: QUALITY_HIGH` は
   両方とも使わない）。クエリ無しの 1080×1080・tick 0〜60・1× の書き出しは `paddle-Play-seed7-t0-60.mp4`（1,119,730 byte・
   約 1.7 秒）になり、ページ内で `Input` + `BufferSource` + `ALL_FORMATS` で読み戻すと `computeDuration() = 1` /
   `packetCount = 60` / `averagePacketRate = 60` / `await getDisplayWidth() = 1080` / `await getDisplayHeight() = 1080` /
   `codec = "avc"`。`output.cancel()` の後に次の `Output` を作って書き出しても問題なく完了した。

上記以外の差分は無い（`Output` / `BufferTarget` / `Mp4OutputFormat` / `WebMOutputFormat` / `Input` / `ALL_FORMATS` /
`computeDuration` / `computePacketStats` / `getPrimaryVideoTrack` / three の addon import パス / `THREE.Timer` /
`PMREMGenerator.fromScene` / `UnrealBloomPass` の引数順は brief のコードと完全に一致した）。

`channel: "chrome"` は本機に Chrome がインストール済みだったため §5 の代替手順（未インストール時の記録のみ）は
発生しなかった。Chromium 同梱でも `avc` が `true` だったため、brief が用意した「Chromium で `avc` が false なら
vp9 に分岐する」の判断も不要だった（§C）。
