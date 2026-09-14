# Jin v2 実行系(runtime.md)

> 正典。設計書 §4.2〜§4.7 の実装仕様。実装は Phase 2 の `jin_wasm`(codegen / prelude.lua / runtime)と
> Phase 4 の `apps/player`。ここに書いた順序と形が、ブラウザ(Wasmoon)と CI(lupa)の
> **両方**で同じトレースを出す根拠になる。

## 1. ホスト境界

ホストが呼ぶ Lua の関数は **2 つ**だけ。Lua はホストを呼ばない。

| 関数 | 引数 | 戻り |
|---|---|---|
| `boot(seed, manifest)` | seed: 整数、manifest: `game.manifest.json` の内容(Lua テーブル)。ホストが `storage`(記憶の写し・abilities.md §8)を足し、差し替えのときだけ `resume`(§1.3)も付く | なし |
| `tick(t, inputs)` | t: 0 始まりの tick 番号、inputs: §1.1 | §1.2 の結果を **JSON 文字列**にしたもの(UTF-8) |

戻り値を Lua テーブルでなく JSON 文字列にするのは、Wasmoon の Lua→JS テーブル変換が 50 行で約 600 µs/回かかるのに対し JSON 文字列 + `JSON.parse` なら 35 µs で済み、かつ Lua→JS で integer / float の区別と 64 bit 精度が落ちる経路を通らないため(`wasm-api-probe.md` A.3 / A.9)。直列化はプレリュードが行う(外部の JSON ライブラリは無い。数値は §6 の書式)。

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

`events` には確定した文字列の `{kind="text", text="名前"}`(v2.1・abilities.md §3 の `input.text`)も並ぶ。押下状態(`keys` / `pointer`)には触らず、プレリュードは状態を持たずに `text()` の呼び出しのたびに `events` を読むだけなので、snapshot / resume(§1.3)に運ぶものは増えない。プレイヤーは canvas の上に置いた見えない 1 行の入力欄にフォーカスを置き、合成中でない `input` と `compositionend` のたびに値を取り出して空にし、制御文字と対にならないサロゲートを落としてから積む。IME の合成中のキー(`isComposing` / `key == "Process"`)は集めない。

`events` には v1 の陣の答え `{kind="reply", id=1, text="…"}`(v2.1・§11)も並ぶ。`id` は `agent` の `cast` が返した要求 id、`text` は答えの文字列(`text` イベントと同じく制御文字と対にならないサロゲートを含まない。空でもよい)。押下状態には触らず、プレリュードは §2 の 1 で配達するだけ。ヘッドレスのホストが積む(録画の再生ではログの行)。ブラウザは積まない(§10)。

### 1.2 結果テーブル

```
{ ops = { {"clear","#000"}, {"ink","#fff"}, {"rect",140.0,172.0,40.0,4.0}, {"text","SCORE 1",4.0,4.0} },
  audio = { {"tone",440.0,50.0} },
  trace = { … },     -- デバッグビルドだけ(リリースビルドではキーごと無い)。§5 の行の配列
  done = false,      -- root が done になったら true。以後の tick は何もしない
  error = nil,       -- 実行時エラーの文(§5 の error 行と同じ。リリースビルドでも出る。無ければ null)
  public = { … },    -- 公開 state の確定値 { "Play.score": 3, "Result.quit": true }(jin run が標準出力に出す)
  storage = { {"runs", "3"}, … },  -- 記憶への書き込みの一覧(書き込みがあった tick だけ。release でも出る。abilities.md §8)
  asks = { { id = 1, circle = "Npc", name = "oracle", prompt = "…" }, … },  -- v1 の陣への問い(問いがあった tick だけ。release でも出る。§11)
  snapshot = { … },  -- デバッグビルドだけ。次の boot の manifest.resume にそのまま渡せる状態(§1.3)
  resume = { … } }   -- デバッグビルドだけ。manifest.resume 付きで boot した直後の 1 回だけ(§1.3)
```

`error` と `public` は Phase 2 で足した(設計書 §11 #22)。リリースビルドにはトレースが無いので、
実行時エラーの理由と最後の公開 state を返す口がここしか無い。`snapshot` と `resume` は v2.1 で足した
(設計書 §11 #42〜#44)。`storage` も v2.1(設計書 §11 #45〜#47。`boot` の核で書いた分は最初の `tick` の結果に載る)。
`asks` は v2.1 の `agent`(§11。問いがあった tick だけ・`storage` の直後)。
キーの順は `ops` / `audio` / `trace` / `done` / `error` / `public` / `storage` / `asks` / `snapshot` / `resume`。

### 1.3 状態を保った差し替え(`manifest.resume`・v2.1)

エディタで式を直すたびに新しい JIL が届く(§10 のライブリロード)。`boot` からやり直すと score も ball も消えるので、
デバッグビルドの `tick` 結果に載る **`snapshot`** を、次の(新しい JIL の)`boot` の `manifest.resume` に**そのまま**渡すと、
プレリュードが**陣を名前で照合して**状態を写し、同じ tick から続ける。

```
snapshot = { seed = 7, tick = 29, seq = 411, rng = "0x970afbe494d8eded", done = false, asked = 0,  -- asked は v1 の陣への問いの通し番号(§11)
  circles = { { name = "Game", status = "active", paused = false, pending = false, cursor = 1, published = false,
                delegate = null, state = null, public = null },     -- 核なし陣は state / public が null
              { name = "Play", status = "active", paused = false, pending = false, cursor = 1, published = true,
                delegate = null, state = { score = 0, paddle = 140.0, ball = { … } }, public = { score = 0 } },
              … } }
```

規則(`prelude.lua` の `restore_from` / `repair_flows`。`packages/jin-wasm/tests/test_resume.py` が固定する):

- **名前で照合する。** 生成部の陣に snapshot と同じ名前があれば、生存(`status` / `paused` / `pending` / `cursor` /
  `published` / `delegate`)と state(`restore`。欄も名前で引き、**型の形が合う欄だけ**写す。合わない欄・無い欄は `init` の値)と
  公開 state の確定値 P(`prestore`)を写す。snapshot にだけある陣は捨て(`dropped`)、生成部にだけある陣は idle のまま
- **核あり ↔ 核なしが変わった陣は照合しない**(idle のまま)
- **root が照合できなければ通常の `boot`**(`resume.mode = "fresh"`。陣の改名など)
- 復元後、active な flow の idle な子は `entered` にする(`repair_flows`。足した子・照合できなかった子がそこで動き出す)
- **`wait` 中の手順と未配達の `emit` は捨てる**(コルーチンは境界を越えない。`on tick` は届き続ける)。録画も続けない
- `seed` は snapshot のものが勝つ(ホストが別の seed を渡しても乱数列が割れない)。PCG32 の 64 bit 状態は
  `"0x…"` の 16 進**文字列**で越える(jil.md §5 の唯一の例外)。`tick` / `seq` は snapshot から続く(§5 の `seq` は通しのまま)
- 通常の `boot` は全陣を確定(`publish_all`)するが、復元では P を snapshot から写したので触らない
  (tick の終わりの進行で `set` された値は次 tick の 4 まで P に出ない・二重バッファのまま)
- 復元の知らせは直後の `tick` 結果に 1 回だけ: `resume = { mode = "resumed" | "fresh", tick, kept = { … }, dropped = { … } }`
- ホストの値の形は `type()` で見ない(lupa は table、Wasmoon は proxy の userdata)。欄の読み取りと `ipairs` で見る(`RREC` / `RN` / `RB` / `RSTR` / `RL` / `JR[k]`)

保証は「途切れずに走らせた列と、途中で差し替えて続けた列が**行(`seq` 込み)も画面も公開 state も乱数列も一致**する」
(`test_paddle_resumed_from_a_snapshot_matches_the_uninterrupted_run`)。式を書き換えた JIL に差し替えれば、その式が効く
tick から列が分かれる。リリースビルドには `snapshot` が無い(差し替えは常に `boot` から)。

## 2. tick の手順

固定タイムステップ `dt = 1 / stage.fps`。tick `t` で次を**この順**に行う。「陣の順」とは陣木の深さ優先・`flow.steps` の配列順・`transfer` のスタックは先頭(委譲先)だけ、である。

1. **配達**: 前 tick に `emit` されたメッセージを、`emit` の実行順に、宛先の `on message` の手順へ配達する。宛先が `active` でなければ捨てる(トレースに `emit` 行は残る)。続けて `events` の `reply`(§1.1・v2.1)を発生順に、その要求 id を出した `agent` の sigil を持つ陣の `on message` へ `(sigil 名, id, text)` で配達する(§11。宛先が `active` でない / `on message` が無い / id を知らないときは捨てる)
2. **再開**: `wait` 中の手順を陣の順に再開する。`ticks` は残数を 1 減らして 0 なら再開、`until` は式を評価して真なら再開。再開した手順が再び `wait` したら次 tick へ
3. **イベント**: `active` な各陣へ、陣の順に、`events` の `key` / `pointer` を発生順に配り、最後に `tick(dt)` を配る。1 つの陣の中では `on` の手順を**その順**で走らせる。手順の中で `finish` したら、その陣への残りの配達は行わない
4. **確定**: `out: true` の state を確定する(二重バッファ。他の陣が読む `Play.score` は、この段までは**前 tick の確定値**)。未 `entered` の陣(summon で書かれた state)も確定する。加えて陣が `entered` になった直後(`init` の値)と `done` になった直後(`finish` の書き込み)にもその陣だけ確定する(設計書 §11 #27)
5. **検査**: デバッグビルドなら `guards[].assert` を陣の順に評価し、偽なら `assert` 行を残す
6. **進行**: `done` になった陣の親 flow を進める(§3)。新しく `entered` になった陣は `init` を評価し、核の手順を**この段で**走らせる(この tick の 3 は済んでいるので `tick` イベントは届かない)。核の手順が `wait` したら 2 で再開される。この段で更に `done` になれば繰り返す(1 tick に何段でも進める)。`exit` が常に偽で子が同期的に `done` になる `loop` のように無限に進む構成は静的には落ちないので、1 tick の進行を **1000 回**で打ち切って `error` 行にする(プレリュードの `ADVANCE_LIMIT`)
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

`transfer`: 委譲元は `active` のまま**休止**(イベントを受けない)、委譲先を `entered` にしてスタックに積む。委譲先が `done` になるとスタックから外し、委譲元がイベントを受け始める(同 tick の 6 で)。委譲先が更に `transfer` すればスタックは深くなる(閉路は JIN012)。`idle` に戻るとき(親 `loop` の次の周)、スタックは空にする。委譲先が `done` になってスタックから外れたら委譲先は `idle` に戻す(再び `transfer` できる。公開 state は残る)。休止中の陣で `wait` している手順は再開しない(委譲先が `done` になった後の tick から再開する)。

root が `done` になったら `tick` は `done = true` を返し、以後は何もしない(プレイヤーは「終了」を表示する)。

## 4. 決定性

同じ `.jin` + 同じ seed + 同じ入力ログ → 同じトレース(バイト一致)+ 同じ表示リストの列。根拠:

- 固定 `dt`。壁時計を読む能力が無い
- 記憶(`storage`・abilities.md §8)は `boot` に渡した写しと自分の書き込みだけを見る(他のタブ・別プロセスの書き込みは次の `boot` まで見えない)。写しは録画のヘッダに載る(§7)ので、同じ録画から同じ列が出る
- 乱数は PCG32(`abilities.md` §6)。整数演算は Lua 5.4 の 64 bit 整数で、Wasmoon と lupa で同じ(probe で確認)
- 文字列の順序(純関数 `cmp`・expr.md §4.1・v2.1)はコードポイント順(= UTF-8 のバイト順)で、プレリュードがバイトを 1 つずつ比べる。Lua の文字列の `<` は `strcoll` を通ってプロセスのロケールの照合順に従い、lupa(Python のプロセス)と Wasmoon で揃う保証が無いので使わない
- 入力は tick 境界で消費。tick の中で入力が変わることは無い
- 公開 state の二重バッファで、`parallel` の子の実行順が読み取り値に影響しない(**例外**: `random` は舞台に 1 つなので順序に依存する。順序自体は配列順で固定なので決定性は保たれる)
- 生成コードはハッシュテーブルを反復しない(`jil.md`)。list は配列、型紙は固定欄
- 浮動小数は IEEE 754 倍精度。`sin` / `cos` / `sqrt` / `atan2` は libm 依存で、**Wasmoon と lupa で最下位ビットが違い得る**。パリティテスト(設計書 §10)はトレースの `set` 行と `frame` 行を `str` の丸め(§6)で比較し、`examples-v2/` は超越関数の結果を state に**直接**入れない(`floor` / `round` を通す)。この制限は v2.1 で「プレリュードに独自の `sin` / `cos` を持つ」ことで解く候補

## 5. トレース行

1 行 1 JSON(JSONL)。デバッグビルド(`--debug`)でだけ出る。`seq` は `boot` から通しの連番(0 始まり。状態を保った差し替え(§1.3)でも snapshot の `seq` から続き、0 に戻らない)。

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
| `rite` | 手順を起動する直前(核 / cast / summon / 配達) | `/circles/i/rites/j` | 引数 / 戻り値(`return` 時に埋める。行は tick の終わりに直列化するので、`wait` で tick を跨いだ手順の戻り値は `null` のまま) |
| `cast` | `cast` ステップの実行(ホスト能力・summon・effect)。**呼び出しの前**に積み、戻り値は呼び出しの後に埋める(list の効果で引数が変わる前の値が載り、実行時エラーの `pointer` がこのステップになる) | ステップの pointer | 評価済み引数 / 戻り値 |
| `set` | **state** への代入(局所は記録しない) | ステップの pointer(`cast … into` なら `cast` 行とは別に `set` 行) | — / 新しい値 |
| `emit` | `emit` ステップ(行を積むのは**配達の tick の 1**。`seq` と `tick` は配達時のもの)。v1 の陣の答えの配達(§11)も同じ行(circle は sigil を持つ陣・name は sigil 名・pointer は `/circles/i/sigils/j`・input は `[id, text]`) | ステップの pointer | 引数 / 配達されたか(`true` / `false`) |
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
- それ以外は最短の往復可能表現を **Python の `repr(float)` と同じ配置**で書く: 指数形は 10 進指数が `-4` 未満か `16` 以上のとき(`1e-05` / `1.5e+16`)、指数は符号付きで 2 桁以上、それ以外は固定小数(`0.0001` / `4503599627370495.5`)。Lua 側はプレリュードが `%.<n>e` の `n` を 0 から増やして往復する最短の桁を探し、配置を組み立てる。JS の `Number.prototype.toString` は指数の桁数が違う(`1e-5`)が、プレイヤーは JSON を parse するだけなので影響しない(設計書 §11 #23)。Python の `repr` と一致することは `packages/jin-wasm/tests/test_prelude.py` が非整数 700 件で固定する
- `NaN` は `"NaN"`、`inf` は `"Infinity"` / `"-Infinity"`(JSON には文字列として載せる)

パリティテストはこの書式で比較する。

## 7. 入力ログと録画(`.jinrec`)

JSONL。1 行目はヘッダ。

```
{ "jinrec": 1, "file": "paddle.jin", "seed": 7, "fps": 60, "ticks": 600, "storage": { "runs": "3" } }
{ "tick": 3, "kind": "key", "name": "ArrowLeft", "down": true }
{ "tick": 9, "kind": "key", "name": "ArrowLeft", "down": false }
{ "tick": 40, "kind": "pointer", "x": 150, "y": 110, "down": true }
{ "tick": 41, "kind": "pointer", "x": 150, "y": 110, "down": false }
```

- `tick` は昇順(同じ tick の複数行は発生順)。`ticks` はヘッダに書いた総 tick 数(`jin run --ticks` の既定値になる)
- プレイヤーは「録画」で seed と入力を集めてこの形で書き出す。`jin run --input rec.jinrec` は同じ tick に同じイベントを渡す
- `keys` / `pointer` の押下状態はイベントから再構成する(ログには載せない)
- `{ "tick": 12, "kind": "text", "text": "名前" }`(v2.1)は確定した文字列(abilities.md §3 の `input.text`)。`text` は空でない文字列で、制御文字(U+0000〜U+001F・U+007F)と対にならないサロゲートを含まない。押下状態には触らない。**版は 1 のまま**: 読み手はすべてこのリポジトリにあり、古い読み手は未知の `kind` を行番号付きで断る(黙って読み飛ばさない)ので、版を上げて既存の録画を読めなくする理由が無い
- `{ "tick": 13, "kind": "reply", "id": 1, "text": "…" }`(v2.1・§11)は v1 の陣の答え。`id` は 1 以上の整数、`text` は文字列(`text` イベントと同じ検査。空でもよい)。押下状態には触らない。ヘッドレスの `jin run --record` が書き、`jin run --input` はこれを同じ tick に配達して v1 の陣を**呼ばない**。プレイヤーも読める(再生は LLM を呼ばないので、ヘッドレスの録画をブラウザで見られる)。版は 1 のまま(`text` と同じ規律)
- `storage`(任意・v2.1)は録画の `boot` に渡した記憶の写し(abilities.md §8)。object で値はすべて文字列。書き手は非空のときだけ最後に書き、`jin run --input` はこれを `manifest.storage` に渡す。無ければ空。版は 1 のまま(任意欄の追加)。`--input` と `--storage` を一緒に指定したら録画のヘッダが正で、`--storage` は読みも書きもしない(§8)

## 8. ヘッドレス実行(`jin run`・v2)

```
jin run game.jin [--ticks N] [--seed S] [--input rec.jinrec] [--storage memory.json] [--trace t.jsonl] [--frames f.jsonl] [--debug] [--model fake] [--record out.jinrec]
```

- `--ticks` の既定は `--input` があればそのヘッダの `ticks`、無ければ 600。`--seed` の既定は `--input` のヘッダの `seed`、無ければ `stage.seed`。root が `done` になったら(その tick を含めて)止める
- `--storage`(v2.1・設計書 §11 #51)は記憶(abilities.md §8)のファイル。起動時に読んで `manifest.storage` に渡し(**無ければ空**。1 回目の実行)、終了時に最後の記憶(写しに書き込みを順に反映したもの)を同じファイルへ書き戻す。形は JSON の object で値はすべて文字列(録画のヘッダの `storage` と同じ検査・`jin_wasm.jinrec.check_storage_copy`)。書き出しは鍵の昇順・2 字下げ・末尾改行。**実行時エラーでもそこまでの書き込みは書き戻す**(プレイヤーは tick ごとに永続化する)
  - `--input` と一緒なら録画のヘッダの写しが正で、`--storage` は**読みも書きもせず** stderr に 1 行知らせる(再生は記憶を上書きしない)
  - 走らせる前に断る(exit 2): 読めない・JSON でない・形が違う・シンボリックリンク・親ディレクトリが無い・対象の `.jin` と同じファイル
  - 書き戻しは `jin render -o` と同じ規律(同じディレクトリの一時ファイルから `os.replace`・リンクを拒む・新規は 0644 & ~umask・既存のモードは引き継ぐ)で、書けなければ診断 1 行で exit 1
- 実行時エラー(§5 の `error`)は stderr に 1 行出して **exit 1**(トレース / frames はそこまでの分を書く)
- `--model fake` / `--record`(v2.1・§11)は `agent` の sigil のためのもの。`--model fake` は v1 の陣を `FakeLlm`(固定応答・ネットワーク不要)で走らせる(無ければ v1 の `jin run` と同じく `.jin` の `core` の実モデル)。`--record` は走らせた入力(`--input` の行)と v1 の答え(`reply` 行)を §7 の形で書く(`--trace` と同じ書き込みの規律)。`--input` があるときは v1 の陣を**呼ばない**(録画の答えが正)
- `--trace` は §5 の行(`--debug` を暗黙に立てる)。`--frames` は `frame` 行だけを別ファイルに(トレース無しでも出せる)
- 標準出力には最後の tick の公開 state を JSON で 1 行出す(`{"Play.score": 3, "Result.quit": true}`)
- lupa は **`lupa.lua54`** を明示する(lupa 2.8 の既定 `LuaRuntime` は Lua 5.5.1。probe B.1)。`LuaRuntime(register_eval=False, register_builtins=False, unpack_returned_tuples=True)` で作り、`globals().python = None` と `load` / `loadstring` / `dofile` / `loadfile` / `require` / `package` / `os` / `io` / `debug` / `collectgarbage` への `None` 代入を**JIL を読む前**に行う(`register_eval=False` だけでは `python.builtins` が残る。probe B.2)。JIL 自体はこれらを使わない(`jil.md`)ので、封じるのは多層防御。`string.dump` も消す
- **命令数の上限**: `debug.sethook` の count hook(`jin_wasm.runtime.INSTRUCTION_BUDGET` = 10^7 / `boot` と `tick` ごと。examples-v2 の 1 tick は 1 万命令に満たない。hook は `debug` を nil にした後も生きる・`delivery/…/wasm-api-probe.md` §B.7 の実測)。超えると `{code = "budget"}` がスケジューラの `pcall` に捕まり `error` 行 + `done = true` になる。**Lua の hook はスレッドごと**なので、ホストがメインスレッドに掛けるだけでは `wait` を含む手順(コルーチン)の中の無限ループを止められない(lupa / Wasmoon とも実測・probe §B.8 / §A.10)。そこでホストは JIL を読む**前**に 2 つのグローバル **`JIN_ARM()`**(今のスレッドに掛け直す)/ **`JIN_HOOK(co)`**(コルーチン `co` に掛ける)を置き(`jin_wasm.jil.HOST_HOOK_GLOBALS`)、プレリュードが読み込み時に `local` へ捕まえて `boot` / `tick` の先頭と毎 `coroutine.resume` の前に呼ぶ。ホストは JIL を読んだ**後**に 2 つを消す(グローバルは `boot` / `tick` だけに戻り、ホストが呼ぶ Lua の関数も 2 つのまま)。`JIN_ARM` / `JIN_HOOK` が無ければ上限なし。lupa(`jin_wasm.runtime._SETUP`)と Wasmoon(`apps/player/src/host.ts`)は同じ Lua のチャンクで置く(`error` の文言も同じ・設計書 §11 #24 / #32)。Wasmoon の `Thread.setTimeout`(C の hook)はコルーチンの中で PANIC するので使わない(probe §A.10)

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
- プレイヤーは `apps/player` のビルド物(`pnpm build` → `dist/` の 3 ファイル)を `scripts/sync_player.py` が `jin_wasm/player/` に**同梱**する(gitignore。wheel には入る。設計書 §11 #25)。同梱されていなければ `jin build` は `game.lua` / `game.manifest.json` / `assets/` だけを書き、同梱の仕方を stderr に 1 行出す。`--single` は同梱が要る
- **`--single` は `index.html` 1 本だけを書く**。`apps/player/public/index.html` の `<!-- jin:bundle -->` を `<script>window.JIN_BUNDLE = { jil, manifest, wasm(base64) }</script>` に、`<script src="player.js">` を本文のインラインに置き換える(`</` は `<\/` に逃がすので JIL / manifest に `</script>` が入っても HTML を壊せない)。**asset は埋められないので `stage.assets` があれば拒む**(設計書 §11 #34)。wasm は `data:application/wasm;base64,…` で Wasmoon に渡り、ページは何も fetch しない(`apps/player/e2e/single.spec.ts` が実測)
- **asset は `.jin` の親ディレクトリの中だけ**(`Asset.path` は `Ident` なので `../x` がモデルを通る)。絶対パスと `..` を拒み、`realpath` が親の中に留まることを確かめ、リンクを辿らず、通常ファイルだけをコピーする。バンドルの `game.manifest.json` の `assets[].path` は `assets/<ファイル名>` に書き換える(同名は拒む)。書き出しは `jin_adk.build` と同じ規律(`O_EXCL` / `O_NOFOLLOW` / `dir_fd` / 一時ファイル + `os.replace`。`jin_wasm.bundle`)
- `game.manifest.json` の `namespaces` は `.jin` が許可した名前空間の和集合。プレイヤーは**それ以外の入力を集めない**(`input` が無ければキーイベントを購読しない)。これは機能であって防御ではない(JIL に外の世界へ出る口が無いのが防御)

## 10. プレイヤーの責務(`apps/player`)

- `requestAnimationFrame` で時間を積み、`1 / fps` ごとに `tick` を呼ぶ。遅れたら最大 4 tick まで連続で呼び、それ以上は捨てる(音と絵が乱れるだけで、トレースの決定性は保たれる。捨てた tick は存在しない)
- 表示リストを `<canvas>` に描く(§2 の `ops`)。音リストを WebAudio で鳴らす
- 入力を集めて §1.1 の形にする。録画モードなら §7 も書く
- Wasmoon は `openStandardLibs: true` で作り(`false` は base ライブラリごと消える)、JIL を読む前に `load` / `loadstring` / `dofile` / `loadfile` / `require` / `package` / `os` / `io` / `debug` / `collectgarbage` を **`lua.global.set(name, undefined)`** で消す(`null` は Wasmoon 1.16.0 で `TypeError` になり消えない。probe A.8)
- `tick` の戻り値(JSON 文字列)を `JSON.parse` する。Lua のテーブルを直接受け取らない(§1)
- 「実行 / 一時停止 / 1 tick / seed / 録画 / 書き出し」の最小 UI。エディタからは iframe で埋め込まれ、`postMessage` でトレース行を親へ流す(`{ "type": "jin.trace", "rows": [...] }`)。親からは `{ "type": "jin.load", "jil": "...", "manifest": {...}, "keep": true }` で差し替える(ライブリロード。`keep` なら §1.3 で状態を保つ)
- Python を import しない。読む生成物は `schemas/abilities.json` だけ(キー名の一覧と TS 型の生成元)。キー名 / op 名のリテラルをソースに書かず、カタログから引く(`tests/contract/test_player_contract.py` が走査する)
- **入力の規則**(`apps/player/src/input.ts`): キーは `KeyboardEvent.code` で、カタログの `keys` にあるものだけ。`repeat` と同じキーの二重押下は捨て、`blur` では押下中のキーを `down: false` として**記録してから**離す。ポインタは主ボタンだけで、座標は論理座標(stage の幅 / 高さに写して整数に切り捨て、枠内に留める)。移動は tick の中で最後の 1 つに畳むが、down → up の遷移は残す(`ui.button` の離しが見る)。`inputs` と `.jinrec` は**同じ reducer**(`jin_wasm.runtime.InputState.apply` の写し)から出す(`tests/fixtures/jinrec/reducer.*` を Python と TS の両方が検算)
- **録画は `boot` し直して tick 0 から始める**(途中からの録画は `jin run --input` と揃わない)。ヘッダの `ticks` は実行した tick 数。トレース(`debug`)は `boot` から通しで溜め、パリティは `jin run --input rec.jinrec --trace` の行と **JSON として読んでから全行一致**で比べる(`apps/player/e2e/parity.spec.ts`)
- 命令数の上限は §8 と同じ Lua(`JIN_ARM` / `JIN_HOOK`)で掛ける。Wasmoon の `Thread.setTimeout` / `functionTimeout` は使わない(コルーチンの中で PANIC・probe §A.10)。`new LuaFactory(wasmUri)` には常に URL を渡す(引数無しは unpkg へ fetch しに行く)
- `canvas.text` の書体は ASCII(U+0020〜U+007E)がプレイヤー内蔵の 5×7(`src/font.ts`)、それ以外が k6x8ゴシックの字形(`src/glyphs.ts`。`scripts/generate_glyphs.py` が `apps/player/fonts/k6x8/k6x8_gothic.bdf` から生成する)で、どちらも 6×8 の枠に置く。字形が無いコードポイントは □(幅は 1 コードポイント = 6 のまま)。字形は `player.js` に同梱する(`stage.assets` の font にしない。埋め込みのプレイヤーは asset を読めない)。字形はトレースに載らないのでパリティに影響しない(設計書 §11 #33 / #49)
- `postMessage` は親(`window.parent`)へ tick ごとに `{ type: "jin.trace", rows }` を送る(targetOrigin は `*`。トレースは秘密ではない)。`{ type: "jin.load", … }` は**親からの message だけ**を受ける
- **埋め込み(iframe)の規則**(Phase 5・設計書 §8 / §11 #38): iframe の中では `game.lua` / `game.manifest.json` を **fetch せず**、親の `{ type: "jin.load", jil, manifest }` を待つ(状態表示は「エディタからの読み込みを待っています」)。`{ type: "jin.control", action }`(`start` / `pause` / `step` / `reboot` / `record` / `stop` / `forget` / `suspend` / `wake`)で親の操作を受ける。**`suspend` / `wake` は親が実行パネルを隠す / 見せるときに送る**(編集モードで隠れている間はプレイヤーを止めておく・設計書 §11 #54): `suspend` はそのとき走っていたかを覚えて止め、止められている間に届いた `jin.load` は(最初からでも)走り出さずに保留し、`wake` で走らせる。止められている間は tick が進まないのでトレースは届かず、親は図を描き直さない。`reboot` は**止めた状態で** tick 0 に戻す(そこから 1 tick ずつ進められる)。`jin.load` のたびに差し替える(ライブリロード。`keep` が真で tick が進んでいれば §1.3 の `manifest.resume` で状態を保ち、そうでなければ `boot` からやり直す)。asset の実体は埋め込みでは読めない(`.jin` の隣にあり、エディタのサーバは配らない)。親側は `apps/editor/src/run/RunPanel.tsx`、配信は `jin editor` の `/play/`
- **埋め込みのデバッグ**(Phase 6・設計書 §8 / §11 #39〜#41): 親は `{ type: "jin.replay", text }` で `.jinrec` の生のテキストを渡す。プレイヤーは `src/jinrec.ts`(`jin_wasm.jinrec.read_jinrec` の写し。壊れた行は同じ行番号で断る)で読み、ヘッダの seed で `boot` し直して tick 0 からヘッダの `ticks` まで、`tick == t` の行を**同じ reducer**に通す(§8 と同じ手順・同じトレース。`apps/player/e2e/replay.spec.ts` が全行一致を見る)。root が `done` になったらそこで止まり、終わったら**止まったまま**(そこからスクラブ / 1 tick)。再生の間に届いた実入力は捨て、トレースは最後に 1 回 `jin.trace` で流す。`{ type: "jin.frame", ops }` は表示リストを描くだけ(止まっている間だけ・Lua は呼ばない)。状態が変わるたびに `{ type: "jin.status", loaded, tick, seed, running, done, error, recording, recordedEvents, generation, notice }` を、`jin.control` の `stop`(録画を止める)には `{ type: "jin.recording", text, seed, ticks }` を親へ送る(書き出しは親)。`jin.control` の `record` は seed を受けて `boot` し直して走り出し、`reboot` も seed を受ける。親とプレイヤーの語彙は `jin.load` / `jin.control` / `jin.replay` / `jin.frame`(親から)と `jin.trace` / `jin.status` / `jin.recording`(親へ)の 7 語で、`tests/contract/test_editor_contract.py` が両側から抜いた集合の等号で固定する
- **状態を保った差し替え**(v2.1・設計書 §11 #42〜#44): `jin.load` の `keep` が真で tick が進んでいれば(終わっていなければ)、新しい JIL のホストを作り、前のプレイヤーの直近の `snapshot` を `manifest.resume` に付けて `boot` する(`Player.resumeFrom`。ホストが呼ぶ Lua の関数は `boot` / `tick` のまま)。tick / seed / reducer / 押下状態(`InputCollector.adopt`。押したままのキーを引き継がないと離しの `down: false` が出ない)/ トレース / 直近の画面と公開 state を引き継ぎ、走っていたなら走らせ続ける。録画は止める。root が照合できず `resume.mode == "fresh"` ならその tick を捨てて `reboot`(tick 0 から。行は流さない)。読み込みは直列(wasm の起動を待つ間に次の `jin.load` が来ても重ねない)。`jin.status` の **`generation`** は `boot` し直すたび(最初から / 録画 / `keep` 無しの差し替え / `fresh`)に増え、続けたときは変わらない。親はこれで行を捨てるかを決める(`seq` が 0 に戻るので。録画の再生では `reboot` の知らせが行の一括より先に届くので、再生の行は残る)。復元の知らせは `notice`。**Wasmoon は JS の `null` を Lua に積めない**(proxy の userdata が欄を読んだ瞬間に PANIC でエンジンごと落ちる・probe §A.11)ので、`boot` に渡す manifest は `withoutNulls` で `null` を欄ごと落とす(核なし陣の `state` / `delegate` が `null`。Lua 側は無い欄を `nil` として読む)
- **記憶**(`storage`・abilities.md §8・v2.1・設計書 §11 #45〜#47): プレイヤー(`Player.store`・`Map`)がホストの記憶の写しを持ち、**すべての `boot`**(最初から / 録画 / 差し替え / 再生)で `manifest.storage` に渡す。tick の戻り値の `storage`(書き込みの一覧)を順に写しへ反映し、`localStorage` の `jin.storage:<manifest.file>` に JSON の object で丸ごと書き戻す(読めない・書けないときは落とさず、その実行の間だけ覚える)。録画は `boot` に渡した写しをヘッダに書く。**再生はヘッダの写しから始まるスクラッチに書き、永続化しない**(次の `reboot` で本物に戻る)。差し替えで続けるときは前のプレイヤーの写しを引き継ぐ。「記憶を消す」(`jin.control` の `forget`・iframe の中のボタン)は空にして `boot` し直す(親からは止めたまま)。`__jinPlayer.storage()` / `forget()` は e2e の口。埋め込み(エディタ)と `--single` は別オリジンなので混ざらない

## 11. v1 の陣を呼ぶ Python ホスト(v2.1・`agent`)

v2 の陣は `sigils[].kind = agent`(model.md §3.2)で v1 の `.jin`(Google ADK 上の LLM エージェント)に**問える**。
設計書 §11 #55。ホスト境界(§1)は変えない: Lua はホストを呼ばず、問いは tick の**戻り値**で出て、答えは次以降の tick の**入力**で戻る。

- **問い**: `cast target=<sigil 名> args=[prompt] into=<id>`。プレリュードは問いを `asks` に積み(`{ id, circle, name, prompt }`。`id` は boot からの 1 始まりの通し番号・`circle` は sigil を持つ陣・`name` は sigil 名)、`id` を返す。同期的に返るのは id だけで、答えは待たない(`wait` と `on message` で受ける)。DEBUG では `cast` 行(input は `[prompt]`・output は id)
- **答え**: ホストは tick 結果の `asks` を順に処理し、答え `text` を **`{kind="reply", id, text}` として次の tick(`t + 1`)の `events` に積む**(§1.1)。プレリュードは §2 の 1 でそれを、id を出した陣の `on message` へ `(name = sigil 名, id, text)` の形で配達する(`emit` 行を残す。§5)。id を知らない・宛先が `active` でない・`on message` が無いときは捨てる(`emit` 行の output が `false`)
- **v1 の走らせ方**(ヘッドレスの `jin run` だけ・実装は `jin_cli`): `file` を v2 の `.jin` の親ディレクトリの中に解決し(外に出る・リンク・無い・`version: 1` でない・`jin check` が通らないなら走らせる前に exit 2)、`jin_adk.runtime.run_model`(v1 の `jin run` と同じ経路。`ref` の import・cwd の `sys.path` 窓・`SystemExit` の扱いも同じ)に `prompt` を最初の利用者メッセージとして渡す。問いごとに新しいセッション(state は問いをまたいで続かない)。答えは v1 のトレースの**最後のモデル応答**の output(str。`final` 行、無ければ最後の `model` 行。root が flow で最後の行が `escalate` のとき `final` は付かない)、モデル応答が無ければ `""`。答えは `reply` に載せる前に**正規化**する(`jin_wasm.jinrec.clean_reply_text`・`run_headless` がホストの答えを受けた直後の 1 か所): 改行 / 復帰 / タブは空白 1 つに、それ以外の制御文字と対にならないサロゲートは落とす。ライブ配達で Lua が見る文字列と録画に残る文字列は同じ。v1 の実行が失敗したら §8 の実行時エラーと同じく stderr 1 行 + exit 1。`--model fake` なら `FakeLlm`(`"fake-response"`)
- **決定性と録画**(§4 / §7): 答えは再現しないので、録画は答えを**入力として**持つ(`reply` 行)。`jin run --record` が書き、`--input` の再生は v1 の陣を呼ばずログの `reply` をそのまま配達する。録画に無い問いには答えが来ない(その手順は待ち続ける)
- **snapshot / resume**(§1.3): 要求 id の通し番号は snapshot に載せる(差し替えても id が続く。`test_resume` の「途切れずに走らせた列と一致」を保つため)。未回答の問い(id → 陣の対応)は未配達の `emit` と同じく捨てる
- **`jin_wasm` は v1 を知らない**: `run_headless` は「問いに答える呼び出し可能」を引数で受けるだけで、`jin_adk` を import しない(層の契約)。答える実装は `jin_cli`(両方を知る唯一の層)。呼び出し可能が無いのに `asks` が出たら `RunError`
- **ブラウザ**(§10 / 設計書 §11 #55): プレイヤーは `asks` を無視する(答えは来ない。`jin build` は agent を含む `.jin` に stderr で 1 行知らせる)。`reply` を含む録画の**再生**はできる(答えは録画にある)。エディタの実行パネルも同じ
- **危険性**: `agent` を持つ v2 の `.jin` を `jin run` すると、その v1 の `.jin` の `ref` が import される(v1 の `jin run` と同じ S1)。「v2 の `jin run` は任意コードを実行しない」は **`agent` の sigil を持たない v2** について成り立つ。`--model fake` でも `ref` は import される
