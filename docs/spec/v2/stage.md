# Jin v2 鑑賞ページ（stage.md）

> 正典。設計書 `docs/superpowers/specs/2026-09-17-jin-stage-design.md` の実装仕様。
> 実装は `apps/stage`。`<!-- machine-readable -->` の表の書式を変えない
> （`tests/spec/test_stage_spec_consistency.py` と `tests/contract/test_stage_contract.py` が読む）。

## 1. 役割

`jin editor` が `/stage/` として配る静的ページ。エディタから受け取った SVG（`jin/renderSvg` のオーバーレイ無し）・名前の表・トレース行・fps から、魔法陣を「金環」の 3D で描き、発動の演出を付けて MP4 / WebM / PNG に書き出す。**配置は計算しない**: SVG の `viewBox` の中心を原点に、半幅を 1.25 に写した座標をそのまま使う（1.25 は v2 layout.md §8 のキャンバス半幅）。

## 2. 層

描かれた要素を陣ごとに 6 層に分けて持ち上げる。高さは外周 1 に対する値で、実際の高さは高さ × 陣の単位（`circle` の輪の項の「陣の単位」。陣に属さない額縁は 1）。入れ子の小陣は幅に比例して低くなる。

<!-- machine-readable: stage-layers -->

| 層 | 高さ | data-jin-kind |
|---|---|---|
| 0 | -0.32 | `stage` `form` |
| 1 | 0 | `on` `guard` `delegate` |
| 2 | 0.07 | `state` |
| 3 | 0.14 | `sigil` `flow-edge` |
| 4 | 0.21 | `rite` |
| 5 | 0.28 | `core` |

<!-- /machine-readable -->

形から層を決める種別:

- `circle` の輪（`<circle>` で塗り無し）: 属する陣の `<g data-jin-kind="circle">` の中の核（`core` の `<circle>` で塗り無し）の半径を v2 layout.md §8 の核 0.12 で割って陣の単位とし、輪の半径 / 単位に最も近い環の層にする。陣に核が無ければ単位は 1

<!-- machine-readable: stage-ring-layers -->

| 層 | 環の半径 |
|---|---|
| 4 | 0.35 |
| 3 | 0.55 |
| 2 | 0.75 |
| 1 | 0.95 |

<!-- /machine-readable -->

- `step` / `step-edge`（手順の図）: pointer の `steps` / `then` / `else` の段数 − 1 を深さとし、層 = min(深さ, 3) + 1（深さ 0 → 層 1。v2 layout.md §3 の環 0.95 → 0.35 と同じ向き）
- 塗りのある `<circle>`（紋章の点）は種別の層のまま「点」として描く

## 3. 演出

<!-- machine-readable: stage-effects -->

| kind | 演出 | 強さ |
|---|---|---|
| `enter` | `ignite` | `once` |
| `exit` | `fade` | `once` |
| `event` | `chant` | `habit` |
| `rite` | `spin` | `habit` |
| `cast` | `beam` | `habit` |
| `set` | `flash` | `habit` |
| `emit` | `release` | `once` |
| `transfer` | `flow` | `once` |
| `wait` | `breathe` | `habit` |
| `finish` | `crown` | `once` |
| `assert` | `warn` | `once` |
| `error` | `crack` | `once` |
| `frame` | — | `none` |

<!-- /machine-readable -->

演出の見え方は設計書 §2.3 の表のとおり。`wait` は `output` が `"suspend"` の行だけが `breathe` を起こし、`"resume"` の行は光らせない。

### 3.1 光らせる要素

| kind | 光らせる pointer | 光の出どころ |
|---|---|---|
| `cast` | `name` の `.` の前（sigil 名）を名前の表の `sigils` で引いた pointer | 行の pointer の手順（`/circles/i/rites/j`） |
| `set` | `name` を名前の表の `state` で引いた pointer | 無し |
| `transfer` | `name` を名前の表の `delegates` で引いた pointer | 行の pointer の手順 |
| `enter` / `exit` / `finish` / `error`（陣全体の演出） | 行の pointer の陣（`/circles/i`）。その配下すべてが光る（`finish` / `error` の行はステップの pointer を持つ） | 無し |
| それ以外 | 行の pointer | 無し |

名前の表で引けなければ行の pointer を使う。その pointer が場面に無ければ、`/` で 1 段ずつ祖先へ遡って最初に場面にある pointer を光らせる（overlay の規則 1 と同じ段一致）。どこにも無ければ光らせない。

### 3.2 慣れの規則

- 強さ `once` の行は常に 1
- 強さ `habit` の行は、同じ（演出, 光らせる pointer）が前の tick か同じ tick にも出ていれば連続回数を 1 増やし（同じ tick の中では増やさない）、そうでなければ 0 に戻す。強さ = 連続回数が 3 以上なら 0.15、それ未満なら `1 − 連続回数 × (1 − 0.15) / 3`
- `set` は、同じ陣の同じ state の直前の値と `JSON.stringify` が一致すれば強さ 0.15
- 行の時刻は `max(tick, 0)`（`boot` の行の tick −1 は 0 に置く）

### 3.3 光の時間変化

演出ごとの長さ（秒）: `ignite` 2.4 / `fade` 1.6 / `chant` 0.8 / `spin` 0.9 / `beam` 0.6 / `flash` 0.7 / `release` 1.2 / `flow` 1.2 / `breathe` 1.5 / `crown` 2.8 / `warn` 1.4 / `crack` 2.0。時刻 `t`（tick 単位の実数）での進み `p = (t − 行の時刻) / fps / 長さ`、`0 ≤ p < 1` の間だけ光り、明るさ = 強さ × 包絡（`p < 0.15` なら `p / 0.15`、それ以外は `1 − (p − 0.15) / 0.85`）。

### 3.4 決定性

絵は「トレース行・名前の表・SVG・時刻 `t`・構図・縦横比」だけで決まる。演出の乱数は `seq` を種にした mulberry32 で作り、`Math.random` / 時刻を使わない。保証するのは**場面の列**までで、GPU やブラウザの違いによるピクセルの差は保証しない。

## 4. カメラ

構図は `overhead`（仰角 80°）/ `oblique`（45°・既定）/ `low`（16°）。視野角（縦）35°、陣を収める半径 1.45、方位角は秒あたり 4° で周回。プレビューではドラッグで方位角と仰角を足せる（横 1 px = 0.3°、縦 1 px = 0.2°、仰角は 5°〜89° に収める）。書き出しは、そのときの足し分を初期値にした同じ周回になる。距離 = 1.45 / sin(min(縦の半視野, 横の半視野))、横の半視野 = atan(tan(縦の半視野) × 縦横比)。

## 5. 書き出し

- 動画は 1 コマずつ描く。`n` 枚目の時刻は `開始 tick + n / 動画fps × 速度 × fps`、エンコーダには `(n / 動画fps, 1 / 動画fps)` を渡す。動画fps は 60、速度は 1 か 0.5、長さは 60 秒まで
- コーデックは `avc`（MP4）→ `vp9`（WebM）の順に `canEncodeVideo` で確かめ、どちらも無理なら書き出さない
- 解像度は長辺 1080 / 1440 / 2160、縦横比 1:1 / 16:9 / 9:16（短辺は偶数に切り下げる）。PNG の長辺は最大 4096
- 銘（既定 on）: 右下に「<陣名> — written in Jin(陣)」
- ファイル名は `<jin 名>-<陣名>-seed<seed>-t<開始>-<終了>.<拡張子>`。保存は親（エディタ）がダウンロードさせる。中止したら何も渡さない

## 6. エディタとの語彙

同一オリジンの iframe。送り先と受け取り元は相手の window に限る。

| 語 | 向き | 欄 |
|---|---|---|
| `stage.scene` | 親 → stage | `svg`（string）/ `names`（名前の表）/ `fps` / `jinName` / `circleName` |
| `stage.trace` | 親 → stage | `rows`（トレース行の配列）/ `seed`（number か null） |
| `stage.status` | stage → 親 | `ready` / `rows` / `codec`（`"avc"` / `"vp9"` / null）/ `exporting`（`{done,total}` か null）/ `error` |
| `stage.file` | stage → 親 | `name` / `mime` / `bytes`（ArrayBuffer） |

名前の表: `{ [陣名]: { pointer, sigils: {名前: pointer}, state: {名前: pointer}, delegates: {陣名: pointer} } }`。

`stage.trace` の `rows` は runtime.md §5 の行をそのまま載せる。`frame` 行の `circle` は null で、stage はそれを受けて読み飛ばす（光らせない）。

## 7. 実装で確定した値

要件値ではなく、`apps/stage/src/render/` の実装で目視（`apps/stage/dev.html`・paddle の fixture・斜め 45° / 俯瞰 / 低い煽り）して決めた値。変えたら e2e と手元の書き出しで見え方を確かめ、この表を直す。「初期値」は計画に置いた値で、目視で変えたものだけ太字にしてある。

| 値 | 確定値 | 置き場所 | 根拠 |
|---|---|---|---|
| 背景色と霧 | `#080503`・`FogExp2` の濃さ 0.1（霧の色は背景と同じ） | `render/stageRenderer.ts` の `BACKGROUND` | 初期値のまま |
| 環境マップ | `RoomEnvironment` を `PMREMGenerator.fromScene(…, 0.04)`・トーンマップは ACES Filmic | `render/stageRenderer.ts` | 初期値のまま。金属の陰影はこれの映り込みで出る |
| ブルーム（strength / radius / threshold） | 0.7 / 0.45 / 0.82 | `render/stageRenderer.ts` の `BLOOM` | 初期値のまま。光の強さ側を下げれば白く飛ばなかった |
| 主光源 | 点光源 `#ffd8a0`・強さ 8・距離 8・減衰 1.3。位置は (cos 0.5s × 1.4, 1.1, sin 0.5s × 1.4)（s は秒 = tick / fps） | `render/stageRenderer.ts` の `key` と `draw` | 初期値のまま |
| 補助光 | 平行光 `#ffc27a`・強さ 1.2・位置 (−1.5, 0.6, −2)、環境光 `#3a2a18`・強さ 0.6 | `render/stageRenderer.ts` | 初期値のまま |
| 視野角 / 近い面 / 遠い面 | 35° / 0.05 / 50（注視点 (0, 0.1, 0)） | `render/stageRenderer.ts` の `camera`・`camera.ts` の `FOV_DEG` | 初期値のまま（構図は §4） |
| 輪の太さ（陣の輪 / 小さな輪） | 0.009 / 0.005 | `render/gilded.ts` の `RING_TUBE` / `SMALL_RING_TUBE` | 初期値のまま |
| 金属の素材 | `metalness` 1・`roughness` 0.3・輪の色 `#c8943a`・線の色 `#d9a54f`・目盛りの色 `#5a3c16`・光の色 `#fff0c8`・警告 `#ff2a2a`・火の粉 `#ffb35a` | `render/gilded.ts` の `GOLD` / `GOLD_LINE` / `GOLD_DIM` / `GOLD_HOT` / `WARN_RED` / `EMBER` | 初期値のまま |
| 線の太さ | 描画の高さ 1080 CSS px のとき 1.4 CSS px。`linewidth = 1.4 × 高さ(CSS px) / 1080`（頭打ちなし）で、画面の高さに対する太さはプレビュー（倍率 2 など）と書き出し（出力の大きさ・倍率 1）で等しい。three 0.186 の `LineSegments2` は `resolution` を CSS px のビューポートで上書きするので、`linewidth` は CSS px（倍率を掛けたデバイス px で描かれる） | `render/gilded.ts` の `LINE_WIDTH_PX`・`render/stageRenderer.ts` の `LINE_REFERENCE_HEIGHT` | 基準の値は初期値のまま。高さ 842 CSS px・倍率 2 のプレビューで 1.09 CSS px になり、細くはなるが輪の目盛り・スポーク・額縁は読める |
| 光線の太さ | 2.5 CSS px（高さ 1080 基準。線の太さと同じ比例を掛ける） | `render/glowView.ts` の `BEAM_WIDTH_PX` | 初期値のまま（Task 8 の目視で変えていない） |
| 輪の外の目盛り（飾り） | 本数 max(24, round(半径 × 72))・内側 半径 + 0.014・長さ 0.03（6 本ごと）/ 0.012・回転 ±0.05 / max(半径, 0.3) rad/秒（層の偶奇で向きが逆） | `render/gilded.ts` の `ticker` | 初期値のまま。意味を持たない（設計書 §2.1） |
| 文字 | SVG の文字をテクスチャに描く（1 文字 128 × 128・84 px、2 文字以上 512 × 128・72 px）。スプライトの高さは SVG の `font-size` × 1.6 | `render/gilded.ts` の `glyph` | 初期値のまま |
| 光っていないときの自発光 | **0.12**（初期値 0.35） | `render/gilded.ts` の `BASE_EMISSIVE` | 0.35 だと輪が一様な黄色の板に見え、環境マップの陰影が消えた |
| 光ったときの自発光の増分（強さ 1 あたり） | **1.6**（初期値 5） | `render/glowView.ts` の `EMISSIVE_GAIN` | 5 だと `ignite`（2.4 秒）の間ずっと陣全体が白く飛んだ |
| 光ったときの線と文字の色の増分（強さ 1 あたり） | **1.2**（初期値 2.2） | `render/glowView.ts` の `COLOR_GAIN` | 同上 |
| 陣全体を光らせる演出 | `ignite` / `fade` / `crown` / `crack` は陣の pointer の配下すべて（`fade` は強さ × 0.5）。`ignite` は光った陣の i 番目の層だけを強さ × 0.05 × i × min(1, 進み × 3) × 陣の単位だけ浮かせる | `effects.ts` の `WHOLE_CIRCLE` / `glowTarget`・`render/glowView.ts` | 初期値のまま |
| 光線と火花の明るさ | 強さを頂点色に掛ける。同じ出どころ → 行き先の光線は 1 本に畳んで強い方 | `render/glowView.ts` | 色を固定にすると、慣れて HUM に落ちた毎 tick の `cast` が加算で重なり、中心に白い棒ができた |
| 光線の上限 | 24 本（1 本の `LineSegments2` に枠を持ち `instanceCount` で絞る） | `render/glowView.ts` の `MAX_BEAMS` | 本数は初期値のまま。枠を固定したのは、毎フレーム `setPositions` すると GPU のバッファを作り直し続けるため |
| 火花（1 回の数 / 上限 / 大きさ） | 18 / 540 / 0.014。`chant` / `release` / `crown` / `flow` で出し、乱数は発火の `seq` を種にした mulberry32 | `render/glowView.ts` の `SPARKS_PER_BURST` / `MAX_SPARKS` | 初期値のまま |
| 漂う火の粉（数 / 大きさ / 不透明度） | 260 / 0.012 / 0.8。種は `mulberry32(1)`、半径 √r × 1.1、高さ (位相 + 秒 × (0.04 + r × 0.08)) mod 1.2 | `render/glowView.ts` の `AMBIENT_EMBERS` | 初期値のまま |
| 銘 | 大きさ round(短辺 × 0.022) px・`500` の明朝系（`"Times New Roman", "Hiragino Mincho ProN", serif`）・`rgba(240, 214, 160, 0.72)`・右下（端から 1 文字ぶん内側） | `render/compose.ts` の `Composer2D.compose` | 初期値のまま |
