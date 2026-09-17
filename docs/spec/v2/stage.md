# Jin v2 鑑賞ページ（stage.md）

> 正典。設計書 `docs/superpowers/specs/2026-09-17-jin-stage-design.md` の実装仕様。
> 実装は `apps/stage`。`<!-- machine-readable -->` の表の書式を変えない
> （`tests/spec/test_stage_spec_consistency.py` と `tests/contract/test_stage_contract.py` が読む）。

## 1. 役割

`jin editor` が `/stage/` として配る静的ページ。エディタから受け取った SVG（`jin/renderSvg` のオーバーレイ無し）・名前の表・トレース行・fps から、魔法陣を「金環」の 3D で描き、発動の演出を付けて MP4 / WebM / PNG に書き出す。**配置は計算しない**: SVG の `viewBox` の中心を原点に、半幅を 1.25 に写した座標をそのまま使う（1.25 は v2 layout.md §8 のキャンバス半幅）。

## 2. 層

描かれた要素を陣ごとに 6 層に分けて持ち上げる。高さは外周 1 に対する値。

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
