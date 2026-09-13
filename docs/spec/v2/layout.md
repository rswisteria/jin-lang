# Jin v2 決定的レイアウトと data-jin 属性(layout.md)

> 正典。設計書 §7 の実装仕様。実装は Phase 3 の `jin_render.v2`。
> v1 `docs/spec/layout.md` の規律(正方形キャンバス、R=1、12 時から時計回り、`fmt_coord` 1 本、
> 3 桁固定小数、`-0.0` の正規化、楕円弧 `A` 不使用、2 色 + 強調 1 色、`<style>` 不使用、`xml_chars`)を
> **すべて継承**する。ここには v2 で決めることだけを書く。

## 1. 舞台と陣の配置

- 出力は 1 枚の SVG。最外に**額縁**(`stage`)を描く: 正方形の枠と、上辺に `width×height @fps` の文字列
- 型紙(`forms`)は額縁の**左上の隅**に印章として並べる(小さな正方形に頭文字。配列順に右へ)
- 陣は v1 と同じ入れ子規則で配置する: `root` を中央に、核なし陣(`flow`)は子を弦 / 多角形で結び、核あり陣は同心円。**展開は深さ 1 まで**、以下は点(v1 §2)
- `--focus <陣名>` でその陣を中央に。`--focus <陣名>/<手順名>` で §3 の手順の図

## 2. 核あり陣の環

<!-- machine-readable: ring-radii -->

| 環 | 半径 | 中身 |
|---|---|---|
| rites | 0.35 | 手順環。手順ごとに小陣(半径 0.07)。`core` の手順へ核から実線 |
| sigils | 0.55 | 道具環。`host` は名前空間の紋(円に頭文字)、`summon` は入れ子の小陣(深さ 1) |
| state | 0.75 | 記憶環。四角。`out: true` は二重線 |
| boundary | 0.95 | 境界環。`on` は刻印(◇ + イベント名の頭文字)、`guards` は刻印(△)。`delegate` は内側に小円と核への破線 |

<!-- /machine-readable -->

半径の値は v1 と同じ 4 本(`instruction` の 0.35 を `rites` が引き継ぐ)。存在しない環は描かず、半径も詰めない。環を描く条件: rites は `rites` が空でないとき、sigils は `sigils` が空でないとき、state は `state` が空でないとき、boundary は `boundary` があるか `delegate` が空でないとき。核なし陣は環を 1 本も描かない。

紋の角度は v1 と同じ `theta_i = -90° + 360° * i / n`(配列順)。境界環の刻印は `on` を先に、`guards` を後に、1 つの列として等角配置する。

核から道具環の各紋へ放射線(v1 と同じ)。核の中には `core` の手順名を書く(v1 の核はモデル名)。

## 3. 手順の図(`--focus 陣名/手順名`)

手順を 1 つの陣として描く。中心の核には手順名。ステップは**深さ 0** を半径 0.95 の環に、深さ 1 を 0.75、深さ 2 を 0.55、深さ 3 を 0.35 に置く(外から内へ。深さ 4 以上は JIN211 で存在しない)。各環の中では配列順に 12 時から時計回り、**その環に置くステップの数**で等角配置する(入れ子の `then` / `else` / `loop.steps` はそれぞれ**親ステップの角度を中心とした弧**に収める。弧の幅は `360° / (その深さのステップ総数)` を親の子の数で割らず、親の角度の左右 ±(180° / 深さ 0 の個数) に収める)。

<!-- machine-readable: step-glyphs -->

| ステップ | 図形 |
|---|---|
| `set` | 四角 |
| `let` | 小さな四角(辺は `set` の 0.6 倍) |
| `cast` | 円(紋)。target がホスト能力なら環の**外側**へ短い放射線、自陣の手順なら**内側**へ、summon なら破線 |
| `if` | 分岐の弦: 自分の紋から `then` の弧の両端へ実線、`else` の弧へ破線 |
| `loop` | 閉じた多角形(`count` / `while`)。`each` は星形(n ≥ 5 なら v1 §2.1 の {n/k}) |
| `break` | 環の外へ抜ける短い線(先端に横棒) |
| `wait` | 環の欠け(v1 の `await` と同じ記号) |
| `emit` | 環の外へ向かう破線(先端に小円) |
| `return` | 環の外へ抜ける短い線 |
| `finish` | 環の外へ抜ける短い線(先端に二重横棒) |
| `transfer` | 環の外へ向かう破線(先端に小さな陣) |

<!-- /machine-readable -->

ステップ間は配列順に**弦**で結ぶ(矢じり付き。実行順)。`if` の `then` / `else` の中は弧の中で同様に結び、弧の終端から親の次のステップへ戻る。

## 4. data-jin 属性

描かれた**すべての**要素は `data-jin`(JSON Pointer)と `data-jin-kind` を持つ(v1 §3)。

<!-- machine-readable: data-jin-kinds -->

| `data-jin-kind` | 対象 | pointer |
|---|---|---|
| `stage` | 額縁 | `/stage` |
| `form` | 型紙の印章 | `/forms/i` |
| `circle` | 陣(同心円のまとまり)、手順の図の外枠 | `/circles/i`、`/circles/i/rites/j` |
| `core` | 核 | `/circles/i/core`、手順の図では `/circles/i/rites/j/name` |
| `rite` | 手順環の小陣 | `/circles/i/rites/j` |
| `sigil` | 道具環の紋 / 入れ子の小陣 | `/circles/i/sigils/j` |
| `state` | 記憶環の四角 | `/circles/i/state/j` |
| `on` | 境界環の刻印(イベント) | `/circles/i/boundary/on/j` |
| `guard` | 境界環の刻印(不変条件) | `/circles/i/boundary/guards/j` |
| `delegate` | 委譲の小円と破線 | `/circles/i/delegate/j` |
| `flow-edge` | flow の弦 / 多角形の辺 | `/circles/i/flow/steps/j`(辺の始点側) |
| `step` | 手順の図のステップの図形 | ステップの pointer(`/circles/i/rites/j/steps/k`、入れ子は `…/then/m` / `…/else/m` / `…/steps/m`) |
| `step-edge` | ステップ間の弦 | 始点側ステップの pointer |

<!-- /machine-readable -->

**13 種**。v1 の 9 種とは別集合で、`tests/contract/test_render_contract.py` の v2 版が等号で固定する。

## 5. 装飾(識別紋章)

v1 §2.2 の規則をそのまま使い、ハッシュの入力を `instruction.rune` から **`core` の手順の正準 JSON**(`rites[j]` のオブジェクトを正準形で直列化した UTF-8)に替える。`rites` が無い陣(核なし)には描かない。

## 6. トレースのオーバーレイ

v1 §7 と同じ。`upto` までに発火した `pointer` の要素を強調色にし、境界環の外に発火数の点を並べる。手順の図では `step` / `step-edge` が対象。`frame` 行は要素を持たないので**強調しない**(画面はプレイヤー側で出す)。

## 7. エラー回復

v1 と同じ: schema を通るモデルなら意味エラーを含んでいても例外を投げない。未解決の参照は点線で、型紙の無い state は四角の中に `?` を描く。
