# Jin v2 鑑賞ページ（stage.md）

> 正典。設計書 `docs/superpowers/specs/2026-09-17-jin-stage-design.md` の実装仕様。
> 実装は `apps/stage`。`<!-- machine-readable -->` の表の書式を変えない
> （`tests/spec/test_stage_spec_consistency.py` と `tests/contract/test_stage_contract.py` が読む）。

## 1. 役割

`jin editor` が `/stage/` として配る静的ページ。エディタから受け取った SVG（`jin/renderSvg` のオーバーレイ無し）・名前の表・トレース行・fps から、魔法陣を「金細工と宝玉」の 3D で描き、発動の演出を付けて MP4 / WebM / PNG に書き出す。金細工は陣ごとの地金、宝玉は力（名前空間）と記憶の型の色で、光は宝玉の色で走る（§2.1・設計書 `docs/superpowers/specs/2026-10-01-jin-stage-gem-worldview-design.md`）。**配置は計算しない**: SVG の `viewBox` の中心を原点に、半幅を 1.25 に写した座標をそのまま使う（1.25 は v2 layout.md §8 のキャンバス半幅）。

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

### 2.1 宝玉と地金

設計書 `docs/superpowers/specs/2026-10-01-jin-stage-gem-worldview-design.md` §2。金細工の陣に宝玉がはめ込まれ、
発動するとその力の宝玉が灯り、光が宝玉の色で走る。色は**意味**を運ぶ（何の力か・何の値か・どの陣か）。
実装は `apps/stage/src/palette.ts`（three を import しない純関数）で、4 つの表と等号（`tests/contract/test_stage_contract.py`）。

力（`cast` の `name` の sigil を名前の表の `sigilKinds` で引いた値）→ 宝玉。host の能力の行は `name` が `ns.member`
（`.` の前が sigil 名）、`agent` / `summon` の sigil への行は sigil 名だけ（runtime.md §11）。自陣の手順の呼び出しは `cast` 行を
出さない（`rite` 行だけ）。効果（`push` / `clear`）の行と引けない力は金。

<!-- machine-readable: stage-powers -->

| 力 | 宝玉 |
|---|---|
| `canvas` | `sapphire` |
| `input` | `emerald` |
| `ui` | `peridot` |
| `audio` | `amethyst` |
| `random` | `opal` |
| `storage` | `amber` |
| `agent` | `moonstone` |
| `summon` | `gold` |

<!-- /machine-readable -->

行の kind が決める宝玉: `transfer` → `topaz`・`emit` → `diamond`・`assert` → `ruby`・`error` → `garnet`・
`event` は `name` が `key` / `pointer` なら `emerald`、`message` なら `diamond`、それ以外は `gold`。
`set` は記憶の型の宝玉（下の表）で、`bool` の値が `false` なら `onyx`。それ以外の kind は `gold`。

記憶の型（名前の表の `stateTypes`）→ 宝玉。型が無い・読めなければ金。

<!-- machine-readable: stage-state-gems -->

| 型 | 宝玉 |
|---|---|
| `num` | `citrine` |
| `str` | `aquamarine` |
| `bool` | `pearl` |
| `list<…>` | `tourmaline` |
| 型紙 | `spinel` |

<!-- /machine-readable -->

宝玉 → 色と屈折率（色は初期値。目視で変えたら §7 に根拠を残す）。`opal` の色は時刻と `seq` で色相が巡り（毎秒 0.15 周・
彩度 0.6・明度 0.7）、表の色は使わない。2 色目は `tourmaline` のグラデーションの先と `onyx` の光の銀。

<!-- machine-readable: stage-gems -->

| 宝玉 | 色 | 屈折率 | 2 色目 |
|---|---|---|---|
| `sapphire` | `#2f6bff` | 1.77 | |
| `emerald` | `#1fd47a` | 1.58 | |
| `peridot` | `#a8e83a` | 1.67 | |
| `amethyst` | `#a05cff` | 1.54 | |
| `opal` | `#d8e8f0` | 1.45 | |
| `amber` | `#ffa62b` | 1.54 | |
| `moonstone` | `#cfe3ff` | 1.52 | |
| `gold` | `#ffd27a` | 1.5 | |
| `topaz` | `#ff8a3d` | 1.62 | |
| `diamond` | `#ffffff` | 2.42 | |
| `ruby` | `#ff2a4a` | 1.77 | |
| `garnet` | `#b0102a` | 1.79 | |
| `citrine` | `#ffc83a` | 1.55 | |
| `aquamarine` | `#5fd8e8` | 1.58 | |
| `pearl` | `#f4f0e8` | 1.53 | |
| `onyx` | `#14141a` | 1.54 | `#c8ccd8` |
| `tourmaline` | `#3ad08a` | 1.62 | `#ff7aa8` |
| `spinel` | `#ff3a7a` | 1.72 | |
| `crystal` | `#e8f0ff` | 1.54 | |

<!-- /machine-readable -->

陣の地金。root（名前の表の `isRoot`）は `yellow`。root 以外は pointer `/circles/i` の i の順（root を除いて数える）に
表の 2 行目からを巡る。陣に属さない要素（額縁・型紙の印章）は `yellow`。`isRoot` がどこにも無い表では全部の陣を巡らせる。

<!-- machine-readable: stage-metals -->

| 順 | 地金 | 色 | 粗さ |
|---|---|---|---|
| root | `yellow` | `#d4a24a` | 0.3 |
| 1 | `rose` | `#d68a6e` | 0.32 |
| 2 | `white` | `#d8d4c8` | 0.28 |
| 3 | `platinum` | `#b8bcc4` | 0.24 |

<!-- /machine-readable -->

### 2.2 銘環の帯（陣書き S7）

glyph 設計書 `docs/superpowers/specs/2026-10-03-jin-glyph-design.md` §6 の S7・§9 #52〜#55。プログラムの銘文（完全陣の銘帯と同じ升の列）を、
陣の外周に巡る文字の帯として刻み、発動した行の升を灯す。帯は飾りで、無くても陣は描く。

- **配置の元は SVG**: エディタが `jin/renderSvg` を `inscription: true` で呼んだ SVG（`jin render x.jin --inscription` とバイト一致・
  `jin_render.v2.inscription`）を `stage.scene` の `inscription` で送る。**通常の図と同じ座標系**（1000 px 四方）で、升は環 1.10〜1.30
  （手順の図の環の外へ抜ける線の先 1.07 より外・陣を収める半径 1.45 の内）に、12 時から時計回り・内の周から外の周へ螺旋で並ぶ。
  stage は §1 と同じ写し（`scene.ts` の `svgFrame`）で読むだけで、升を置き直さない（`inscription.ts` の `parseInscription`）
- **中身**: 額縁の銘帯 → 陣ごとに陣の銘環 → その陣の手順の銘環（モデルの順・`focus` によらない）。升の大きさは帯に収まる最大
  （上限 0.06・fib 0.06・paddle 0.025・tetris 0.012・othello 0.011）。升は欄の pointer と持ち主の kind（13 種のまま）を持つ
- **帯の升は場面（`Scene`）に入れない**。`pointers` / 宝玉 / 光線の端点を欄の pointer に解決させないため
- **灯す升**: 発火（§3 の表の行）ごとに、**行の pointer**（実行したステップ・手順・境界のイベント）の配下（`/` の段で同じか下）の升。
  陣全体の演出（`ignite` / `fade` / `crown` / `crack`）は陣（`/circles/i`）へ上げる。`frame` は `/stage`（額縁の銘帯）。
  §3.1 の光らせる先（`cast` なら sigil）は使わない。明るさは §3.2 / §3.3 の強さと包絡のまま、色はその発火の宝玉（§2.1）。
  同じ升に重なれば強い方
- **読み上げ**: 灯る升の列（帯の順）を、光の先頭が進み 0 から 0.6 までに端から端へ渡る（`bandLights`）。先頭の升は強さそのまま、
  通り過ぎた升は 0.35 倍で残り、まだ来ていない升は先頭の幅（列の長さ × 0.08・2 升以上）の中だけ立ち上がる。陣の鼓動（`pulse`）は渡らず一様
- **巡る**: 帯全体が陣の中心まわりに毎秒 −0.02 rad で回る（層の自転より遅い・時刻だけで決まる）。高さは層 1（外周の環と同じ面）
- 描画は `render/inscriptionView.ts`: 刻まれた銘（全升・地金のイエロー × 0.55・1 本の `LineSegments`）と、灯った銘（宝玉の色 × 明るさ × 1.4 の
  加算・枠 40000 区間の `LineSegments` を `setDrawRange` で絞る。枠を超えたら帯の順で先の升から描く）。**太い線（`LineSegments2`）にしない**:
  被写界深度の深度のパスは場面を `MeshDepthMaterial` で上書きして描き直し、インスタンス描画の太い線は区間の数だけ素の四角を重ね描きする。
  帯（paddle で 3.7 万区間）を太い線にすると、ソフトウェア GL（CI の Chromium）で 1 コマに数分かかり固まった。素の線なら深度のパスでも線のまま
  正しい深度を書き、描画の回数は帯なしとほぼ同じ（5 秒で 16 回 → 14 回・paddle）

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
| `frame` | `pulse` | `beat` |

<!-- /machine-readable -->

演出の見え方は設計書 2026-10-01 §5.1 の表のとおり（2026-09-17 §2.3 を置き換えた）。何が起きたかは色ではなく動きで表す。`wait` は `output` が `"suspend"` の行だけが `breathe` を起こし、`"resume"` の行は光らせない。

| 演出 | 動き（実装） |
|---|---|
| `ignite` | 層は沈んだ位置（層 i は −0.05 × i × 単位）から下の層ほど先に上がって元の高さに収まる。光は核（層 5）から外の層へ 1 段ずつ走り、最後に全体が弱く（0.35）一度息づく（`motion.ts` の `layerOffset` / `igniteLight`）。カメラは中ほどで距離 0.9 倍まで寄る |
| `fade` | 外側の層ほど深く沈んで戻る（層 i は −0.04 × i × sin(πp)）。陣全体を強さ × 0.5 で灯す |
| `chant` | 24 粒が渦を描いて ◇ へ吸い込まれ、◇ の水晶が届いたイベントの宝玉の色に染まる |
| `spin` | 手順の小円が灯り、同じ輪の写しが回りながら浮いて（0.08 × 単位）広がり消える |
| `beam` | 手順の小円から力の宝玉へ 12 分割の弧の光線と、弧の上を走る 16 粒。着いた宝玉が灯り、床に宝玉の色の波紋（半径 0.25 × 単位まで）。核の宝玉が強さ 0.35 でその色を映す |
| `flash` | 記憶の四角の輪郭を型の宝玉の色の 6 粒が一周し、宝玉が灯る |
| `release` | 核から 32 粒がダイヤの白と分光の色で放射状に放たれる |
| `flow` | 手順から委譲の小円へトパーズの弧の芯と 24 粒の太い流れ |
| `breathe` | 手順の小円の周りに砂のような 12 粒が細く落ちる |
| `crown` | 陣全体が灯り、核から天へ光の柱（高さ 2.4 × 単位まで）と、宝玉の色を巡る 48 粒の火の粉。カメラは中ほどで仰角 +8° |
| `warn` | △ のルビーが 3 回脈打ち、陣の外周の 1.1 倍まで広がるルビーの環が床を走る |
| `crack` | 陣の外周から内へ折れた 6 本のガーネットの亀裂、宝玉が外側から暗転、陣が傾いて（最大 0.06 rad）沈む。カメラは始めの 0.4 秒だけ揺れる（振幅 0.6°・18 Hz・位相は `seq` の mulberry32） |
| `pulse` | 額縁（`/stage`）を強さ 0.1 で灯す（陣の鼓動） |

常に動くもの（意味を持たない飾り）: 各層の金細工の自転（偶数層 +、奇数層 −、毎秒 0.03 rad・陣の輪の中心まわり。宝玉と光線・粒子の端点も同じ変換を通す）、輪の外の目盛りの逆回転、天球儀の飾りの輪 2 本（半径 1.32 / 1.38）、昇る火の粉 260 粒（5 つに 1 つは宝玉の色）と藍の塵 200 粒。

### 3.1 光らせる要素

| kind | 光らせる pointer | 光の出どころ |
|---|---|---|
| `cast` | `name` の `.` の前（sigil 名）を名前の表の `sigils` で引いた pointer | 行の pointer の手順（`/circles/i/rites/j`） |
| `set` | `name` を名前の表の `state` で引いた pointer | 無し |
| `transfer` | `name` を名前の表の `delegates` で引いた pointer | 行の pointer の手順 |
| `enter` / `exit` / `finish` / `error`（陣全体の演出） | 行の pointer の陣（`/circles/i`）。その配下すべてが光る（`finish` / `error` の行はステップの pointer を持つ） | 無し |
| `frame`（陣の鼓動 `pulse`） | `/stage`（額縁。行の `circle` は null で名前の表を引かない） | 無し |
| それ以外 | 行の pointer | 無し |

名前の表で引けなければ行の pointer を使う。その pointer が場面に無ければ、`/` で 1 段ずつ祖先へ遡って最初に場面にある pointer を光らせる（overlay の規則 1 と同じ段一致）。どこにも無ければ光らせない。

### 3.2 慣れの規則

- 強さ `once` の行は常に 1
- 強さ `beat` の行（`frame`）は常に 0.1（`BEAT`）。慣れの対象外で、光線も火花も出さない。陣の鼓動であって発動の演出ではない（設計書 2026-10-01 §5.1）
- 強さ `habit` の行は、同じ（演出, 光らせる pointer）が前の tick か同じ tick にも出ていれば連続回数を 1 増やし（同じ tick の中では増やさない）、そうでなければ 0 に戻す。強さ = 連続回数が 3 以上なら 0.15、それ未満なら `1 − 連続回数 × (1 − 0.15) / 3`
- `set` は、同じ陣の同じ state の直前の値と `JSON.stringify` が一致すれば強さ 0.15
- 行の時刻は `max(tick, 0)`（`boot` の行の tick −1 は 0 に置く）

### 3.3 光の時間変化

演出ごとの長さ（秒）: `ignite` 2.4 / `fade` 1.6 / `chant` 1.0 / `spin` 0.9 / `beam` 0.8 / `flash` 0.8 / `release` 1.4 / `flow` 1.2 / `breathe` 1.5 / `crown` 3.2 / `warn` 1.4 / `crack` 2.0 / `pulse` 0.5（設計書 2026-10-01 §5.4 の初期値）。時刻 `t`（tick 単位の実数）での進み `p = (t − 行の時刻) / fps / 長さ`、`0 ≤ p < 1` の間だけ光り、明るさ = 強さ × 包絡（`p < 0.15` なら `p / 0.15`、それ以外は `1 − (p − 0.15) / 0.85`）。

### 3.4 決定性

絵は「トレース行・名前の表・SVG・時刻 `t`・構図・縦横比」だけで決まる。演出の乱数は `seq` を種にした mulberry32 で作り、`Math.random` / 時刻を使わない。保証するのは**場面の列**までで、GPU やブラウザの違いによるピクセルの差は保証しない。

## 4. カメラ

構図は `overhead`（仰角 80°）/ `oblique`（45°・既定）/ `low`（16°）。視野角（縦）35°、陣を収める半径 1.45、方位角は秒あたり 4° で周回。プレビューでは左ドラッグで方位角と仰角を足せる（横 1 px = 0.3°、縦 1 px = 0.2°、仰角は 5°〜89° に収める）。ホイールとピンチで寄る・引く（注視点からの距離の倍率 `zoom`・0.25〜2.5・ホイール 1 px あたり倍率 e^(0.0015 × deltaY)、下へ回すと引く）。右ドラッグか Shift + ドラッグ、2 本指のドラッグで注視点を床の上でずらす（`pan`。注視点の深さで陣がポインタについてくる量・縦は仰角で縮む分を戻し sin の下限 0.25・中心から 1.25 = 額縁の内側に収める）。周回はずらした注視点のまわりを回り、トレースから決まる寄りと召喚の窓の半径にも `zoom` を掛ける。ダブルクリックと構図の切り替えで全部戻す。値と計算は `camera.ts`（`zoomBy` / `wheelZoomFactor` / `panBy`）。書き出しは、そのときの足し分（回す・寄る・ずらす）を初期値にした同じ周回になる。距離 = 1.45 / sin(min(縦の半視野, 横の半視野))、横の半視野 = atan(tan(縦の半視野) × 縦横比)。

トレースから決まる足し分（設計書 2026-10-01 §5.3・`motion.ts` の `cameraNudge`）を重ねる: `ignite` は距離を最大 0.9 倍、`crown` は仰角を最大 +8°（どちらも sin(πp) の山）、`crack` は始めの 0.4 秒だけ方位角と仰角を揺らす。同じ時刻の光は足し合わせ、仰角は 5°〜89° に収める。

## 5. 書き出し

- 動画は 1 コマずつ描く。`n` 枚目の時刻は `開始 tick + n / 動画fps × 速度 × fps`、エンコーダには `(n / 動画fps, 1 / 動画fps)` を渡す。動画fps は 60、速度は 1 か 0.5、長さは 60 秒まで
- コーデックは `avc`（MP4）→ `vp9`（WebM）の順に `canEncodeVideo` で確かめ、どちらも無理なら書き出さない
- 解像度は長辺 1080 / 1440 / 2160、縦横比 1:1 / 16:9 / 9:16（短辺は偶数に切り下げる）。PNG の長辺は最大 4096
- 銘（既定 on）: 右下に「<陣名> — written in Jin(陣)」
- ファイル名は `<jin 名>-<陣名>-seed<seed>-t<開始>-<終了>.<拡張子>`。保存は親（エディタ）がダウンロードさせる。中止したら何も渡さない
- **音**（設計書 2026-10-01-jin-stage-summon §3）: 範囲の `frame` 行の `tone(hz, ms)` を、プレイヤーと同じ矩形波・音量 0.08 で 48kHz・モノラルに合成し（`screen/sound.ts`・
  置き場所は `(tick − 開始) / fps / 速度` 秒・頭と終わりに 5ms のフェード（範囲の終わりで切れる音は切れる位置で）・同時の音は足して [−1, 1]）、音声トラックにする。音声のコーデックは MP4 なら
  `aac` → 使えなければ `opus`、WebM は `opus`（`mediabunnyEncoder.ts`・probe §G: Playwright 同梱 Chromium は AAC を持たない）。どちらも使えなければ
  無音で書き出し、状態の表示に知らせる。`play(name)`（音の素材）は鳴らさない。プレビューは再生中に tick が進むたびに WebAudio で鳴らす（スクラブ中と消音中は鳴らさない。描画が遅くて 1 回で何 tick 進んでも間の tick の音を落とさず、描画の間隔が 1 秒（`screen/sound.ts` の `CATCHUP_SECONDS`）を超えて空いたときだけ、溜まった音を一度に鳴らさないよう捨てる）

## 5.1 召喚の窓

設計書 `docs/superpowers/specs/2026-10-01-jin-stage-summon-design.md`。陣の上空に、トレースの `frame` 行の表示リスト（ゲーム画面）を映す光の窓。

- **舞台の大きさ**は `stage.scene` の `stageSize`（§6）。無い・壊れている・モデルと同じ範囲（整数・16〜1024・`messages.ts` の `MIN_STAGE_SIZE` / `MAX_STAGE_SIZE`。契約テストが schema と突き合わせる）の外なら、丸めずに窓を出さない（巨大な窓の canvas とテクスチャを作らない）
- **画面**: 時刻 `t` の tick 以前で最新の `frame` 行の `ops` を、論理解像度の 2D キャンバスに描き、補間なし（`NearestFilter`）で拡大して板に貼る（トーンマップを通さない）。
  描画は `screen/draw.ts`（プレイヤーの `canvas.ts` の写し）。`sprite` は素材が届かないので 6×6 のサファイアの菱形の印
- **写しの守り方**: 字形 `screen/glyphs.ts` は `scripts/generate_glyphs.py` がプレイヤーと同じ内容を書く生成物（`--check` と CI の diff）、`screen/font.ts` はプレイヤーとバイト一致、
  `draw.ts` の命令の集合は `abilities.json` と等号（契約テスト）、描き方はプレイヤーと鑑賞ページの両方が `tests/fixtures/screen/*.png`（プレイヤーの描画で作る正解）と画素一致（両アプリの e2e。
  正解の作り直しは `UPDATE_SCREEN_GOLDEN=1` でプレイヤーの e2e）
- **開閉**（`screen/frames.ts`）: 最初の `enter` 行（どの陣でも。核なし陣の root は `enter` 行を出さない）から 0.8 秒で開き、`enter` 行が無ければ最初の `frame`。
  root（名前の表の `isRoot`）の `exit` / `finish` から 0.8 秒で閉じる。最初の `frame` より前は出さない。開閉のあいだ核から窓へ細い光が立つ
- **縁**: 描く力のサファイア。`tone` の直後 0.25 秒はアメジストへ、`play` の直後 0.3 秒は白へ、最初の `error` の後はガーネットで 2Hz の明滅。枠は root の地金
- **置き場所**: 世界の y 0.7 を下端に、カメラから見て陣の奥へ 0.35。幅 1.0（高さは縦横比）。常にカメラを向き、開くと ease-out で広がる。
  窓が開くほどカメラの陣を収める半径を 1.45 → 1.9、注視点の高さを +0.5 へ連続に変える

## 6. エディタとの語彙

同一オリジンの iframe。送り先と受け取り元は相手の window に限る。

| 語 | 向き | 欄 |
|---|---|---|
| `stage.scene` | 親 → stage | `svg`（string）/ `inscription`（銘環の帯の SVG か null・§2.2）/ `names`（名前の表）/ `fps` / `jinName` / `circleName` / `stageSize`（`{width, height}` か null・召喚の窓の舞台の大きさ） |
| `stage.trace` | 親 → stage | `rows`（トレース行の配列）/ `seed`（number か null） |
| `stage.status` | stage → 親 | `ready` / `rows` / `codec`（`"avc"` / `"vp9"` / null）/ `exporting`（`{done,total}` か null）/ `error` |
| `stage.file` | stage → 親 | `name` / `mime` / `bytes`（ArrayBuffer） |

名前の表: `{ [陣名]: { pointer, sigils: {名前: pointer}, state: {名前: pointer}, delegates: {陣名: pointer}, sigilKinds: {sigil 名: 名前空間 / "summon" / "agent"}, stateTypes: {state 名: 型}, isRoot?: true } }`（`sigilKinds` / `stateTypes` / `isRoot` は宝玉と地金のため・古いエディタは送らない）。`stageSize` が無い・壊れていれば召喚の窓を出さない。`inscription` が無い・文字列でない・読めなければ帯を描かない（陣は描く）。エディタは帯を、鑑賞モードにいて本文が前に取った時から変わったときだけ取り直す（スクラブ・走らせている間の描き直しでは取らない）。

`stage.trace` の `rows` は runtime.md §5 の行をそのまま載せる。`frame` 行の `circle` は null で、stage は名前の表を引かずに額縁（`/stage`）を鼓動（`pulse`・強さ 0.1）で灯す（§3.1）。

## 7. 実装で確定した値

要件値ではなく、`apps/stage/src/render/` の実装で目視（`apps/stage/dev.html`・paddle の fixture・斜め 45° / 俯瞰 / 低い煽り）して決めた値。変えたら e2e と手元の書き出しで見え方を確かめ、この表を直す。「初期値」は計画に置いた値で、目視で変えたものだけ太字にしてある。

| 値 | 確定値 | 置き場所 | 根拠 |
|---|---|---|---|
| 背景色と霧 | **`#05060c`**（深い藍）・霧 `FogExp2` **`#0a0d1c`・濃さ 0.08**（藍の霞） | `render/stageRenderer.ts` の `BACKGROUND` / `FOG` | 設計書 2026-10-01 §1（宝玉の色が映える背景）。旧 `#080503` |
| 環境マップとトーンマップ | `RoomEnvironment` を `PMREMGenerator.fromScene(…, 0.04)`・**`environmentIntensity` 0.6**・トーンマップは **Khronos PBR Neutral** | `render/stageRenderer.ts` の `ENVIRONMENT_INTENSITY` | ACES は彩度の高い青を紫へずらし、サファイア（223°）が 240〜255° に出た。環境の映り込みが強いと淡い地金が白く飛ぶ |
| ブルーム（strength / radius / threshold） | 0.7 / 0.45 / **0.9** | `render/post.ts` の `BLOOM` | 0.82 だと地金の反射まで滲んで輪が白く飛んだ |
| 主光源 | 点光源 **`#fff2dc`・強さ 4.5**・距離 8・減衰 1.3。位置は (cos 0.5s × 1.4, 1.1, sin 0.5s × 1.4)（s は秒 = tick / fps） | `render/stageRenderer.ts` の `key` と `draw` | 暖色の光は地金の違い（ローズ / ホワイト / プラチナ）を消す。強さ 8 では淡い地金が白く飛んだ |
| 補助光 | 平行光 **`#bfd0ff`**・強さ 1.2・位置 (−1.5, 0.6, −2)、環境光 **`#1a1e30`・強さ 0.5** | `render/stageRenderer.ts` | 藍の背景に合わせた寒色の逆光 |
| 視野角 / 近い面 / 遠い面 | 35° / 0.05 / 50（注視点 (0, 0.1, 0)） | `render/stageRenderer.ts` の `camera`・`camera.ts` の `FOV_DEG` | 初期値のまま（構図は §4） |
| 輪の太さ（陣の輪 / 小さな輪） | 0.009 / 0.005 | `render/gilded.ts` の `RING_TUBE` / `SMALL_RING_TUBE` | 初期値のまま |
| 金属の素材 | `metalness` 1・色と粗さは陣の地金（§2.1 の `stage-metals`）。台座（層 0）は地金 × 0.42、線は地金を白へ 0.1、スポークは暗い側へ。目盛りの色 `#5a3c16` | `palette.ts` の `METALS`・`render/gilded.ts` の `DIM_RATIO` / `GOLD_DIM` | 旧 GOLD / GOLD_LINE / GOLD_HOT / WARN_RED / EMBER は宝玉の色（`palette.ts`）に置き換えた |
| 線の太さ | 描画の高さ 1080 CSS px のとき 1.4 CSS px。`linewidth = 1.4 × 高さ(CSS px) / 1080`（頭打ちなし）で、画面の高さに対する太さはプレビュー（倍率 2 など）と書き出し（出力の大きさ・倍率 1）で等しい。three 0.186 の `LineSegments2` は `resolution` を CSS px のビューポートで上書きするので、`linewidth` は CSS px（倍率を掛けたデバイス px で描かれる） | `render/gilded.ts` の `LINE_WIDTH_PX`・`render/stageRenderer.ts` の `LINE_REFERENCE_HEIGHT` | 基準の値は初期値のまま。高さ 842 CSS px・倍率 2 のプレビューで 1.09 CSS px になり、細くはなるが輪の目盛り・スポーク・額縁は読める |
| 光線の太さ | **3.5** CSS px（高さ 1080 基準。線の太さと同じ比例を掛ける） | `render/glowView.ts` の `BEAM_WIDTH_PX` | 2.5 だとサファイアの光線が画面に出なかった（e2e の色の検査） |
| 輪の外の目盛り（飾り） | 本数 max(24, round(半径 × 72))・内側 半径 + 0.014・長さ 0.03（6 本ごと）/ 0.012・回転 ±0.05 / max(半径, 0.3) rad/秒（層の偶奇で向きが逆） | `render/gilded.ts` の `ticker` | 初期値のまま。意味を持たない（設計書 §2.1） |
| 文字 | SVG の文字を白で描いたテクスチャ（1 文字 128 × 128・84 px、2 文字以上 512 × 128・72 px・色空間の変換なし）を透明度と凹凸（`bumpScale` 2）にして、地金を白へ 0.3 寄せた金属の板（高さ `font-size` × 1.6）に刻印する | `render/gilded.ts` の `glyph` / `ENGRAVE_DEPTH` | 設計書 2026-10-01 §6（書体のファイルを持ち込まない・日本語も描ける） |
| 光っていないときの自発光 | **0.12**（初期値 0.35） | `render/gilded.ts` の `BASE_EMISSIVE` | 0.35 だと輪が一様な黄色の板に見え、環境マップの陰影が消えた |
| 光ったときの自発光の増分（強さ 1 あたり） | **1.6**（初期値 5） | `render/glowView.ts` の `EMISSIVE_GAIN` | 5 だと `ignite`（2.4 秒）の間ずっと陣全体が白く飛んだ |
| 光ったときの線と文字の色の増分（強さ 1 あたり） | **1.2**（初期値 2.2） | `render/glowView.ts` の `COLOR_GAIN` | 同上 |
| 陣全体を光らせる演出 | `ignite` / `fade` / `crown` / `crack` は陣の pointer の配下すべて（`fade` は強さ × 0.5）。**`ignite` は層ごとに `igniteLight`（核から外へ 1 段ずつ）を掛ける** | `effects.ts` の `WHOLE_CIRCLE` / `glowTarget`・`motion.ts` の `igniteLight` | 陣全体を 2.4 秒同時に灯すと白く飛んだ |
| 光線の明るさと色 | 宝玉の色 × 強さを頂点色に掛ける。同じ出どころ → 行き先の光線は 1 本に畳んで強い方 | `render/glowView.ts` の `drawBeams` | 色を固定にすると、慣れて HUM に落ちた毎 tick の `cast` が加算で重なり、中心に白い棒ができた |
| 光線の上限 | 24 本 × 弧 12 分割 = 288 区間の枠（`crack` の亀裂 6 本 × 4 も同じ枠）。1 本の `LineSegments2` に枠を持ち `instanceCount` で絞る | `render/glowView.ts` の `MAX_BEAMS` / `ARC_SEGMENTS` | 枠を固定したのは、毎フレーム `setPositions` すると GPU のバッファを作り直し続けるため |
| 粒子（上限 / 大きさ / 1 回の数） | 上限 4096・大きさ 0.012（光線の粒は × 1.8）。`chant` 24 / `release` 32 / `crown` 48 / `flow` 24 / `breathe` 12 / `beam` **16** / `flash` 6。乱数は発火の `seq` を種にした mulberry32 | `particles.ts`（純関数）・`render/particleView.ts`（`Points` + 自前のシェーダ） | beam 8 粒ではサファイアの色が画面に出なかった |
| 漂う粒子 | 火の粉 260 / 0.012 / 0.8（5 つに 1 つは宝玉の色・種 `mulberry32(1)`）と藍の塵 200 / 0.006 / 0.25（`mulberry32(2)`） | `particles.ts` の `ambient` | 設計書 2026-10-01 §1 |
| 宝玉の大きさ | 置き場所の半径 × **0.8**（核は × 0.5）。内側の光のスプライトは宝玉の半径 × **7** | `render/gems.ts` の `GEM_SCALE` / `CORE_GEM_SCALE` / `GLOW_SCALE` | 0.55 / × 4 では宝玉の色が画面に出なかった（e2e の色の検査） |
| 宝玉の素材 | `MeshPhysicalMaterial`: 透過 0.9（真珠 0.1・オニキス 0・ムーンストーン 0.5・オパール 0.4・琥珀 0.7・金 0 で金属）・屈折率は §2.1・分散 0.25・厚み 半径 × 2・吸収距離 半径 × 3・クリアコート 1・粗さ 0.05 | `render/gems.ts` の `TRANSMISSION` / `buildGem` | 初期値のまま |
| 宝玉が灯ったときの自発光（強さ 1 あたり） | **1.4**（初期値 2.2）。核の宝玉は `cast` で強さ × 0.35 の光を映す | `render/glowView.ts` の `GEM_EMISSIVE_GAIN` / `CORE_ECHO` | 2.2 だとトーンマップで白に寄り、宝玉の色相が残らなかった |
| 層の自転 | 毎秒 0.03 rad（偶数層 +、奇数層 −）。中心は陣の輪の中心 | `motion.ts` の `LAYER_SPIN_RAD_PER_SECOND`・`render/gilded.ts` の `pivots` | 初期値のまま |
| 床 | `Reflector`（半径 3・描画先は描画の大きさの半分）を高さ **−0.45**、色 **`#05060a`**。波紋は加算の輪 32 枠 | `render/floor.ts` の `FLOOR_Z` / `FLOOR_COLOR` | −0.37 / `#0a0c16` では映り込みが強く、陣が二重に見えた |
| 光の柱 | 半径 0.08（根元 × 1.4）の開いた円柱・加算・帯は `sin(28 y − 7 s)` | `render/pillar.ts` | 初期値のまま |
| 天球儀の輪 | 半径 1.32 / 1.38・管 **0.0022**・地金（イエロー）**× 0.45**・自発光 **0** | `render/armillary.ts` | 0.004・自発光 0.08 では飾りが陣より目立った |
| 後処理 | 描画 → 被写界深度（aperture 0.0015・maxblur 0.005・焦点はカメラから注視点）→ ゴッドレイ（48 サンプル・しきい値 0.55・減衰 0.95・濃さ **min(1, 灯った宝玉の和) × 0.35**）→ ブルーム → 出力 → **仕上げ**（色収差 0.0015・ビネット 0.35・グレイン **0.025**） | `render/post.ts` | 仕上げを出力の前に置くと、線形でかけたグレインが暗部で効かず、床の映り込みに同心円の縞（バンディング）が出た。和をそのまま使うと陣全体が灯る演出で白く飛んだ |
| 召喚の窓 | 幅 **1.0**（初期値 1.2）・下端 **0.7**（初期値 0.95）・奥へ 0.35・枠 0.014・縁の光の板 × 1.14。窓が開くほど陣を収める半径 1.45 → **1.9**（初期値 1.75）・注視点 +**0.5**（新） | `render/summonWindow.ts` の `WINDOW` | 初期値では窓の上半分が画面の外に出て、額縁の下も切れた |
| 銘 | 大きさ round(短辺 × 0.022) px・`500` の明朝系（`"Times New Roman", "Hiragino Mincho ProN", serif`）・`rgba(240, 214, 160, 0.72)`・右下（端から 1 文字ぶん内側） | `render/compose.ts` の `Composer2D.compose` | 初期値のまま |
| 銘環の帯 | 環 1.10〜1.30・升の一辺の上限 0.06・刻まれた銘は地金 × **0.55**、灯った銘は宝玉の色 × 明るさ × **1.4**（加算）・どちらも素の線（1 デバイス px）・枠 40000 区間・巡り −0.02 rad/秒・読み上げは進み 0.6 で渡り切り残光 0.35・先頭の幅は列の 8%（2 升以上） | `jin_render.v2.inscription` の `BAND_*`・`inscription.ts`・`render/inscriptionView.ts` | 帯の内縁は手順の図が描く最も外（1.073・examples-v2 と v2-programs の全図で実測）の外。0.55 は目視（paddle・斜め 45°）で帯が陣の輪より暗く、字の並びは読める値。線の太さは上の「素の線」の理由で固定 |
