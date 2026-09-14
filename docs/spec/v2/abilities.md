# Jin v2 ホスト能力カタログ(abilities.md)

> 正典。設計書 §3.4 の実装仕様。実装(正本)は **`jin_core.v2.abilities`**(純データ)で、
> そこから `schemas/abilities.json` を生成する(設計書 §11 #19)。**補完・型検査(jin-core)・
> Lua プレリュード(Phase 2 の `jin_wasm`)・プレイヤーの TS 型**の 4 つが同じカタログを読む。
> 手で 4 か所に書かない。

## 0. 原則

- 名前空間の単位で道具環に載せる(`sigils[].kind = host`)。名前空間 1 つで 1 枠
- **ホストは Lua を呼ぶ側であり、Lua はホストを呼ばない**(設計書 §4.3)。ここに列挙する能力は
  すべて Lua のプレリュード(`prelude.lua`)に実装され、効果は **tick の戻り値**(表示リスト /
  音リスト / 記憶への書き込みの一覧)としてホストへ渡る。読み取り系(`input`)は tick の**入力スナップショット**を、
  `storage.get` は `boot` に渡された記憶の写し(§8)を読む
- 壁時計・`Date`・ネットワーク・ファイルに相当する能力は**無い**
- 引数の数と型は固定(可変長引数は無い)。合わなければ JIN205

## 1. カタログ

<!-- machine-readable: abilities -->

| 名前空間 | メンバ | 引数 | 戻り | 種別 |
|---|---|---|---|---|
| `canvas` | `clear` | color: str | — | effect |
| `canvas` | `ink` | color: str | — | effect |
| `canvas` | `rect` | x: num, y: num, w: num, h: num | — | effect |
| `canvas` | `circle` | x: num, y: num, r: num | — | effect |
| `canvas` | `line` | x1: num, y1: num, x2: num, y2: num | — | effect |
| `canvas` | `text` | s: str, x: num, y: num | — | effect |
| `canvas` | `sprite` | name: str, x: num, y: num | — | effect |
| `input` | `key` | name: str | bool | read |
| `input` | `pressed` | name: str | bool | read |
| `input` | `pointer` | — | Pointer | read |
| `input` | `text` | — | str | read |
| `ui` | `button` | label: str, x: num, y: num, w: num, h: num | bool | effect+read |
| `ui` | `label` | s: str, x: num, y: num | — | effect |
| `audio` | `tone` | hz: num, ms: num | — | effect |
| `audio` | `play` | name: str | — | effect |
| `random` | `next` | — | num | state |
| `random` | `range` | lo: num, hi: num | num | state |
| `storage` | `get` | key: str | str | read |
| `storage` | `set` | key: str, val: str | — | effect |

<!-- /machine-readable -->

種別: `effect` は表示リスト / 音リスト / 書き込みの一覧へ追記(式の中では使えない。`cast` から)。`read` は入力スナップショット / boot 時の記憶を読む純関数(式の中で使える)。`effect+read` は描いて、かつ値を返す(式の中で使える。副作用は評価順)。`state` は乱数状態を進めて値を返す(式の中で使える)。

`storage`(`get` / `set`)は v2.1 で足した(§8)。カタログに無い名前空間は JIN205。

## 2. `canvas`

座標系は `stage.width` × `stage.height` の論理解像度。原点は左上、y は下向き。プレイヤーは論理解像度を整数倍(収まる最大)に拡大して中央に置き、余白は `#000`。

- `clear(color)`: 表示リストに `["clear", color]`。通常 tick の先頭で呼ぶ。呼ばなければ前 tick の絵は**残らない**(表示リストは tick ごとに空から始まる。「残す」なら毎 tick 描く)
- `ink(color)`: 以後の描画色。tick の先頭では `"#fff"` に戻る
- `rect(x, y, w, h)`: 塗り四角。`circle(x, y, r)`: 塗り円。`line(x1, y1, x2, y2)`: 幅 1(論理単位)の線
- `text(s, x, y)`: 左上基準。プレイヤーの固定ビットマップ書体(1 文字 6×8 論理単位、等幅)。ASCII(U+0020〜U+007E)はプレイヤー内蔵の 5×7、それ以外は **k6x8ゴシック(2023-10-19 版)の字形**で、JIS X 0208 の全区点(euc_jp と cp932 の両方の対応先。`〜` / `～` のどちらで打っても描ける)と半角カナ・罫線などの記号を含む(v2.1・設計書 §11 #49)。字形が無いコードポイントは □。**幅は字形によらず 1 コードポイント = 6**(半角の字形も枠の左に寄せて 6 進む)。**計測 API は無い**(`len(s) * 6` で幅を出せる)
- `sprite(name, x, y)`: `stage.assets[]` の `kind: sprite` の画像を左上基準で等倍。`name` が無ければ JIN205(静的)
- 色は `"#rgb"` / `"#rrggbb"`。それ以外の文字列は**実行時エラー**(runtime.md §5)。静的には定数リテラルのときだけ検査する

表示リストの 1 要素は `[op, …args]` の配列。`op` はメンバ名(`clear` / `ink` / `rect` / `circle` / `line` / `text` / `sprite` / `label` / `button`)。`button` / `label` は `ui` 由来だがカンバスに描くので同じリストに入る。

## 3. `input`

tick `t` の入力スナップショットは、ホストが「前の tick の処理が終わってから今 tick の処理を始めるまで」に集めた入力イベントの列と、その時点の押下状態である。

- `key(name)`: `name` のキーが**押下中**なら真
- `pressed(name)`: この tick に押された(押下遷移があった)なら真。押しっぱなしでは偽
- `pointer()`: `Pointer{x, y, down}`。`x` / `y` は論理座標(範囲外の値も返す)。`down` は主ボタン押下中
- `text()`(v2.1): この tick に**確定した**文字列。スナップショットの `text` イベント(runtime.md §1.1 / §7)を発生順につないだもので、無ければ `""`。IME の合成中の文字は含まず、確定したときに 1 つの `text` イベントになる。文字列を保つのはプログラムの `state`(`name = name ++ input.text()`)で、ホストは欄の中身も位置も持たない。消すのは `pressed("Backspace")` などキーで書く(Backspace / Enter は文字にならない)。`len` / `sub` はコードポイントで数え、`canvas.text` は非 ASCII も描く(§2)

キー名は `KeyboardEvent.code` の値(`ArrowLeft` / `Space` / `KeyA` …)。これも `abilities.json` に列挙し、定数リテラルのときは静的に検査する(JIN205)。列挙に無い名前は実行時に常に偽。

`input` の許可を持たない陣は `key` / `pointer` イベントを受けられない(JIN230)が、`ui.button` は使える(§4)。

## 4. `ui`

即時モード。**毎 tick 呼ぶ**。呼ばなかった tick には存在しない。

- `button(label, x, y, w, h)`: 枠と `label` を描き、**この tick にポインタの主ボタンが矩形の中で離された**なら真。押下位置が矩形の外だった場合も、離した位置が中なら真(単純化。押下追跡はしない)。判定は `input` と同じスナップショットから行い、`ui` を使う陣に `input` の許可は要らない
- `label(s, x, y)`: `canvas.text` と同じ描画で、UI の意味付け(将来のアクセシビリティ用)

ホバー表示・フォーカス・キーボード操作は v2 では無い。文字の入力欄もウィジェットとしては持たない(v2.1 の文字入力は `input.text()` の読み取りで、欄の中身と描画はプログラムが `state` と `canvas` で持つ・§3)。

## 5. `audio`

- `tone(hz, ms)`: 音リストに `["tone", hz, ms]`。プレイヤーは矩形波で `ms` ミリ秒鳴らす。同 tick の複数の `tone` は同時に鳴る
- `play(name)`: `stage.assets[]` の `kind: sound` を頭から再生

音リストは tick の戻り値の `audio` 配列。**ヘッドレス実行では記録されるだけ**。

## 6. `random`

PCG32(`state`, `inc` の 64 bit 整数 2 つ)。seed は `stage.seed`(CLI の `--seed` / プレイヤーの seed 欄が上書き)。`boot(seed)` で `state = 0, inc = (seed << 1) | 1` として初期化し、1 回進めてから `state += seed` してもう 1 回進める(PCG の参考実装の `pcg32_srandom_r` と同じ)。

- `next()`: `[0, 1)` の num。32 bit の出力を `2^-32` 倍する
- `range(lo, hi)`: `floor(lo)` 以上 `floor(hi)` **以下**の整数値の num。`hi < lo` なら `lo`。剰余偏りはこの用途では許容する(`(hi - lo + 1)` で割った剰余)

乱数の状態は**舞台に 1 つ**(陣ごとではない)。`random` を許可した陣の呼び出し順が状態を決めるので、`parallel` の子の順序は結果に影響する(公開 state の二重バッファはこの依存を消さない。設計書 §11 #8 の例外として明記)。

## 7. `abilities.json` の形

```json
{ "namespaces": [
    { "name": "canvas", "members": [
        { "name": "rect", "params": [ { "name": "x", "type": "num" }, … ], "returns": null, "kind": "effect" } ] } ],
  "keys": [ "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Space", "Enter", "Escape", "KeyA", … ] }
```

正本は `jin_core.v2.abilities`(`NAMESPACES` / `KEY_NAMES` / `POINTER_FIELDS`)で、`jin_core.v2.semantic` は
それを直接 import する。`schemas/abilities.json` は `scripts/generate_schema.py` が同じデータから出す生成物で、
`jin_wasm`(Phase 2)と `apps/player` が読む。ドリフトは `packages/jin-core/tests/test_v2_model.py` と CI が検出する。
（当初は「`jin_wasm` が生成し `jin_core` が JSON を読む」としていたが、`jin_core` は `jin_wasm` を import できず、
インストール済みパッケージから `schemas/` も見つけられないので、正本を最下層に置いた。設計書 §11 #19。）
`pointer` 配列は組み込みの型紙 `Pointer` の欄。

## 8. `storage`(v2.1)

ホストの**記憶**(ブラウザでは `localStorage`、ヘッドレスでは辞書)。鍵も値も `str`。ホスト境界は変えない
(runtime.md §1): 値の**入り**は `boot(seed, manifest)` の `manifest.storage`(ホストが持つ内容の写し。無ければ空)、
**出**は `tick` の戻り値の `storage`(この tick の書き込みの一覧 `[[key, val], …]`。書き込みが無い tick にはキーごと無い)。
ホストは一覧を順に自分の記憶へ反映する(release でも出る。保存が要るのは release のゲームである)。

- `get(key)`: 自分がこの実行で `set` した値 → 無ければ boot 時の写し → 無ければ `""`。純関数(式の中で使える)
- `set(key, val)`: 以後の `get` に見え、書き込みの一覧に載る。`cast` からだけ

決定性(runtime.md §4): `get` が見るのは boot 時の写しと自分の書き込みだけで、他のタブや別プロセスの書き込みは
次の `boot` まで見えない。録画(`.jinrec`)のヘッダは録画の `boot` に渡した写しを `storage` に持ち、
`jin run --input` はそれを `manifest.storage` に渡す(runtime.md §7)。録画の**再生**はヘッダの写しで `boot` し、
書き込みを**永続化しない**(履歴の再実行であって、利用者の本物の記憶を上書きしない)。
ヘッドレスで実行をまたいで記憶を続けるには `jin run --storage <file.json>`(runtime.md §8。起動時に読み、終了時に書き戻す。`--input` と一緒なら使わない)。
値の大きさに上限は置かない(`localStorage` の quota はホストの事情)。文字列を数に戻すには expr.md §4.1 の `num`。
