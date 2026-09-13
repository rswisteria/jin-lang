# Jin v2 実行系(runtime.md)

> 正典。設計書 §4.2〜§4.7 の実装仕様。実装は Phase 2 の `jin_wasm`(codegen / prelude.lua / runtime)と
> Phase 4 の `apps/player`。ここに書いた順序と形が、ブラウザ(Wasmoon)と CI(lupa)の
> **両方**で同じトレースを出す根拠になる。

## 1. ホスト境界

ホストが呼ぶ Lua の関数は **2 つ**だけ。Lua はホストを呼ばない。

| 関数 | 引数 | 戻り |
|---|---|---|
| `boot(seed, manifest)` | seed: 整数、manifest: `game.manifest.json` の内容(Lua テーブル) | なし |
| `tick(t, inputs)` | t: 0 始まりの tick 番号、inputs: §1.1 | §1.2 の結果テーブル |

`boot` は舞台を初期化し、`root` の陣を `entered` にして核の手順を走らせる(`t = -1` 相当。トレースの `tick` は `-1`)。`tick` は §2 を 1 回行う。ホストは `tick` を **`t = 0, 1, 2, …` の順に、飛ばさず**呼ぶ。

### 1.1 入力スナップショット

```
inputs = {
  events = { {kind="key", name="ArrowLeft", down=true}, {kind="pointer", x=12.0, y=40.0, down=false}, … },
  keys   = { ArrowLeft = true, … },          -- 押下中の集合(文字列キー。生成コードは pairs しない。プレリュードが読むだけ)
  pointer = { x = 12.0, y = 40.0, down = false },
}
```

`events` の順は発生順。ブラウザでは前の `tick` の戻りから今の `tick` の呼び出しまでに届いた DOM イベントを論理座標へ変換して積む。ヘッドレスでは入力ログ(§7)の `tick == t` の行。

### 1.2 結果テーブル

```
{ ops = { {"clear","#000"}, {"ink","#fff"}, {"rect",140.0,172.0,40.0,4.0}, {"text","SCORE 1",4.0,4.0} },
  audio = { {"tone",440.0,50.0} },
  trace = { … },     -- デバッグビルドだけ。§5 の行の配列
  done = false }     -- root が done になったら true。以後の tick は何もしない
```

## 2. tick の手順

固定タイムステップ `dt = 1 / stage.fps`。tick `t` で次を**この順**に行う。「陣の順」とは陣木の深さ優先・`flow.steps` の配列順・`transfer` のスタックは先頭(委譲先)だけ、である。

1. **配達**: 前 tick に `emit` されたメッセージを、`emit` の実行順に、宛先の `on message` の手順へ配達する。宛先が `active` でなければ捨てる(トレースに `emit` 行は残る)
2. **再開**: `wait` 中の手順を陣の順に再開する。`ticks` は残数を 1 減らして 0 なら再開、`until` は式を評価して真なら再開。再開した手順が再び `wait` したら次 tick へ
3. **イベント**: `active` な各陣へ、陣の順に、`events` の `key` / `pointer` を発生順に配り、最後に `tick(dt)` を配る。1 つの陣の中では `on` の手順を**その順**で走らせる。手順の中で `finish` したら、その陣への残りの配達は行わない
4. **確定**: `out: true` の state を確定する(二重バッファ。他の陣が読む `Play.score` は、この段までは**前 tick の確定値**)
5. **検査**: デバッグビルドなら `guards[].assert` を陣の順に評価し、偽なら `assert` 行を残す
6. **進行**: `done` になった陣の親 flow を進める(§3)。新しく `entered` になった陣は `init` を評価し、核の手順を**この段で**走らせる(この tick の 3 は済んでいるので `tick` イベントは届かない)。核の手順が `wait` したら 2 で再開される。この段で更に `done` になれば繰り返す(1 tick に何段でも進める。無限に進む構成は JIN012 の閉路検出で静的に落ちる)
7. **返却**: 表示リスト・音リスト・トレース行を返し、両リストを空にする

`wait` 中の手順が待っている間も、その陣の `on` は届く(3)。`finish` した陣で `wait` 中の手順はその場で破棄する。

`transfer` は 3 の中で起きる。`transfer` した陣は同 tick の残りのイベントを受けず、委譲先はこの tick の 6 で `entered` になる。

## 3. 陣の生存と flow

状態: `idle` → `entered` → `active` → `done`。

| flow | 開始時 | 子が `done` になったら | 自分が `done` になる条件 |
|---|---|---|---|
| `sequence` | `steps[0]` を `entered` | 次の子を `entered` | 最後の子が `done` |
| `parallel` | 全員を配列順に `entered` | 何もしない | 全員が `done` |
| `loop` | `steps[0]` を `entered` | 次の子を `entered`。最後の子なら `exit` を評価し、偽なら全員を `idle` に戻して `steps[0]` を `entered` | `exit` が真 |

`exit` は公開 state だけを参照する(JIN220)。評価に使う値は 4 で確定した値(同 tick に `finish` した陣の書き込みは 4 で確定済みなので見える)。

`transfer`: 委譲元は `active` のまま**休止**(イベントを受けない)、委譲先を `entered` にしてスタックに積む。委譲先が `done` になるとスタックから外し、委譲元がイベントを受け始める(同 tick の 6 で)。委譲先が更に `transfer` すればスタックは深くなる(閉路は JIN012)。`idle` に戻るとき(親 `loop` の次の周)、スタックは空にする。

root が `done` になったら `tick` は `done = true` を返し、以後は何もしない(プレイヤーは「終了」を表示する)。

## 4. 決定性

同じ `.jin` + 同じ seed + 同じ入力ログ → 同じトレース(バイト一致)+ 同じ表示リストの列。根拠:

- 固定 `dt`。壁時計を読む能力が無い
- 乱数は PCG32(`abilities.md` §6)。整数演算は Lua 5.4 の 64 bit 整数で、Wasmoon と lupa で同じ(probe で確認)
- 入力は tick 境界で消費。tick の中で入力が変わることは無い
- 公開 state の二重バッファで、`parallel` の子の実行順が読み取り値に影響しない(**例外**: `random` は舞台に 1 つなので順序に依存する。順序自体は配列順で固定なので決定性は保たれる)
- 生成コードはハッシュテーブルを反復しない(`jil.md`)。list は配列、型紙は固定欄
- 浮動小数は IEEE 754 倍精度。`sin` / `cos` / `sqrt` / `atan2` は libm 依存で、**Wasmoon と lupa で最下位ビットが違い得る**。パリティテスト(設計書 §10)はトレースの `set` 行と `frame` 行を `str` の丸め(§6)で比較し、`examples-v2/` は超越関数の結果を state に**直接**入れない(`floor` / `round` を通す)。この制限は v2.1 で「プレリュードに独自の `sin` / `cos` を持つ」ことで解く候補

## 5. トレース行

1 行 1 JSON(JSONL)。デバッグビルド(`--debug`)でだけ出る。`seq` は `boot` から通しの連番(0 始まり)。

```
{ "seq": 41, "tick": 12, "circle": "Play", "kind": "set", "name": "score",
  "pointer": "/circles/1/rites/2/steps/7/then/1", "input": null, "output": 1 }
```

<!-- machine-readable: trace-kinds -->

| kind | いつ | pointer | input / output |
|---|---|---|---|
| `enter` | 陣が `entered` になった | `/circles/i` | — / `init` 後の state(公開・非公開とも) |
| `exit` | 陣が `done` になった | `/circles/i` | — / state |
| `event` | `on` の手順を起動する直前 | `/circles/i/boundary/on/j` | イベントの引数 / — |
| `rite` | 手順を起動する直前(核 / cast / summon / 配達) | `/circles/i/rites/j` | 引数 / 戻り値(`return` 時に埋める) |
| `cast` | `cast` ステップの実行(ホスト能力・summon・effect) | ステップの pointer | 評価済み引数 / 戻り値 |
| `set` | **state** への代入(局所は記録しない) | ステップの pointer(`cast … into` なら `cast` 行とは別に `set` 行) | — / 新しい値 |
| `emit` | `emit` ステップ | ステップの pointer | 引数 / 配達されたか(`true` / `false`。配達は次 tick なので**次 tick の 1 で埋めた行を出す**) |
| `transfer` | `transfer` ステップ | ステップの pointer | 委譲先 / — |
| `wait` | 手順が中断した / 再開した | ステップの pointer | `{"ticks": n}` または `{"until": true}` / `"suspend"` または `"resume"` |
| `finish` | `finish` ステップ | ステップの pointer | — / — |
| `assert` | `guards[].assert` が偽 | `/circles/i/boundary/guards/j` | — / `message` |
| `error` | 実行時エラー(添字範囲外・不正な色・スタック溢れ) | 起きたステップの pointer | — / メッセージ。**この tick はここで中断し、以後の tick は `done = true`** |
| `frame` | tick の終わり(7) | `/stage` | — / `{ "ops": …, "audio": … }` |

<!-- /machine-readable -->

`name` は陣名 / 手順名 / state 名 / イベント名 / メッセージ名(kind による)。値は JSON にできる形(型紙は欄名をキーにしたオブジェクト、list は配列。数値は §6 の丸め)。**`frame` 行は tick ごとに必ず 1 行**(表示リストが空でも)。エディタのスクラバは `set` 行を積算して記憶環の値を出し、`frame` 行でその tick の画面を出す。

リリースビルドはトレースを出さないが、**表示リストと音リストは同じ**(設計書 §4.4)。

## 6. 数値の書式

トレース・表示リスト・`str()` で `num` を文字列にする規則は 1 つ:

- 整数値(`x == floor(x)` かつ `|x| < 2^53`)は整数として(`3`)
- それ以外は最短の往復可能表現(JS の `Number.prototype.toString` / Python の `repr` と同じ規則。Lua 側はプレリュードが `%.17g` から桁を削って最短を探す)
- `NaN` は `"NaN"`、`inf` は `"Infinity"` / `"-Infinity"`(JSON には文字列として載せる)

パリティテストはこの書式で比較する。

## 7. 入力ログと録画(`.jinrec`)

JSONL。1 行目はヘッダ。

```
{ "jinrec": 1, "file": "paddle.jin", "seed": 7, "fps": 60, "ticks": 600 }
{ "tick": 3, "kind": "key", "name": "ArrowLeft", "down": true }
{ "tick": 9, "kind": "key", "name": "ArrowLeft", "down": false }
{ "tick": 40, "kind": "pointer", "x": 150, "y": 110, "down": true }
{ "tick": 41, "kind": "pointer", "x": 150, "y": 110, "down": false }
```

- `tick` は昇順(同じ tick の複数行は発生順)。`ticks` はヘッダに書いた総 tick 数(`jin run --ticks` の既定値になる)
- プレイヤーは「録画」で seed と入力を集めてこの形で書き出す。`jin run --input rec.jinrec` は同じ tick に同じイベントを渡す
- `keys` / `pointer` の押下状態はイベントから再構成する(ログには載せない)

## 8. ヘッドレス実行(`jin run`・v2)

```
jin run game.jin [--ticks N] [--seed S] [--input rec.jinrec] [--trace t.jsonl] [--frames f.jsonl] [--debug]
```

- `--ticks` の既定は `--input` があればそのヘッダの `ticks`、無ければ 600
- `--trace` は §5 の行(`--debug` を暗黙に立てる)。`--frames` は `frame` 行だけを別ファイルに(トレース無しでも出せる)
- 標準出力には最後の tick の公開 state を JSON で 1 行出す(`{"Play.score": 3, "Result.quit": true}`)
- lupa は `register_eval=False` で作り、`load` / `os` / `io` / `require` / `dofile` / `debug` を `nil` にしてから JIL を読む(probe で確認した手順)。JIL 自体はこれらを使わない(`jil.md`)

## 9. バンドル(`jin build`・v2)

```
dist/
  index.html            # プレイヤーの殻。<script src="player.js">
  player.js             # apps/player のビルド物(Wasmoon を同梱)
  wasmoon.wasm          # Wasmoon の wasm 本体(固定版。player.js から相対パスで読む)
  game.lua              # JIL(--debug ならトレース挿入版)
  game.manifest.json    # { "file", "stage", "namespaces": [...], "assets": [...], "debug": bool, "jil": "sha256" }
  assets/               # stage.assets の実体をコピー
```

- 任意の静的サーバで開ける。`file://` は wasm の fetch が拒まれるブラウザがあるので `--single`(wasm と JIL を base64 で `index.html` に埋める)を用意する
- `game.manifest.json` の `namespaces` は `.jin` が許可した名前空間の和集合。プレイヤーは**それ以外の入力を集めない**(`input` が無ければキーイベントを購読しない)。これは機能であって防御ではない(JIL に外の世界へ出る口が無いのが防御)

## 10. プレイヤーの責務(`apps/player`)

- `requestAnimationFrame` で時間を積み、`1 / fps` ごとに `tick` を呼ぶ。遅れたら最大 4 tick まで連続で呼び、それ以上は捨てる(音と絵が乱れるだけで、トレースの決定性は保たれる。捨てた tick は存在しない)
- 表示リストを `<canvas>` に描く(§2 の `ops`)。音リストを WebAudio で鳴らす
- 入力を集めて §1.1 の形にする。録画モードなら §7 も書く
- 「実行 / 一時停止 / 1 tick / seed / 録画 / 書き出し」の最小 UI。エディタからは iframe で埋め込まれ、`postMessage` でトレース行を親へ流す(`{ "type": "jin.trace", "rows": [...] }`)。親からは `{ "type": "jin.load", "jil": "...", "manifest": {...} }` で差し替える(ライブリロード)
- Python を import しない。読む生成物は `schemas/abilities.json` だけ(キー名の一覧と TS 型の生成元)
