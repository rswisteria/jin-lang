# Jin v2 モデル仕様(model.md)

> 正典。上位設計は `docs/superpowers/specs/2026-09-13-jin-v2-general-design.md`(以下「設計書」)。
> Phase 0 の文書。Phase 1 で `jin_core.v2.model`(Pydantic)を書くときの入力であり、
> 実装後は Pydantic 定義が唯一の真実になる(v1 と同じ運び)。
> `<!-- machine-readable: … -->` ブロックは `tests/spec/test_v2_spec_consistency.py` が
> 設計書と突き合わせる。書式を変えない。

## 0. ファイル

拡張子は `.jin`、中身は JSON、`version` は **2**。v1 と同じファイルに同居せず、
`jin_core.load` が `version` を見て v1 / v2 のモデルへ振り分ける。

トップレベルのキー(スキーマ順 = 正準形のキー順):

| キー | 必須 | 型 | 意味 |
|---|---|---|---|
| `$schema` | 任意 | str | 先頭固定 |
| `version` | 必須 | `2` | 先頭固定(`$schema` の次) |
| `root` | 必須 | str | 入口の陣の名前(JIN060) |
| `stage` | 必須 | Stage | 舞台 |
| `forms` | 任意 | Form[] | 型紙。既定は `[]`(書かない) |
| `circles` | 必須 | Circle[] | 陣。1 つ以上 |

未知のキーはスキーマ違反(`additionalProperties: false`)。

## 1. Stage(舞台)

| キー | 必須 | 型 | 意味 |
|---|---|---|---|
| `width` | 必須 | num(整数値、16〜1024) | 論理解像度の幅。`canvas` の座標系はこの単位 |
| `height` | 必須 | num(整数値、16〜1024) | 同、高さ |
| `fps` | 任意 | num(整数値、1〜120)。既定 `60` | 1 秒あたりの tick 数。`dt = 1 / fps` |
| `seed` | 任意 | num(整数値、0〜2^32-1)。既定 `0` | 乱数の seed。`jin run --seed` とプレイヤーの seed 欄が上書きできる |
| `assets` | 任意 | Asset[]。既定 `[]` | `{ "name", "kind": "sprite" \| "sound", "path" }`。`path` は `.jin` からの相対パス |

`width` / `height` / `fps` / `seed` は JSON では**整数**で書く(`num` 型に整数型は無いが、スキーマは `"type": "integer"` で、Pydantic の strict モードは `60.0` を JIN002 にする)。

## 2. Form(型紙)

```json
{ "name": "Ball", "fields": [ { "name": "x", "type": "num" }, { "name": "y", "type": "num" } ] }
```

- `name` はファイル内一意で、circle 名とも衝突不可(JIN010)
- `fields[].type` は §5 の型。型紙の欄に別の型紙を入れてよい(入れ子)が、**自分自身を直接・間接に含めない**(JIN012 と同じ意味の閉路検出。`list<自分>` は許す)
- 組み込みの型紙が 1 つある: `Pointer { x: num, y: num, down: bool }`。`forms` に同名を定義すると JIN010

## 3. Circle(陣)

| キー | 必須 | 型 | 意味 |
|---|---|---|---|
| `name` | 必須 | str | ファイル内一意の ID |
| `description` | 任意 | str | 説明(描画されない) |
| `core` | 核あり | str | **入口の手順名**(`rites[].name` の 1 つ。JIN011) |
| `flow` | 核なし | Flow | §7 |
| `state` | 任意 | State[] | 記憶環。12 個まで(JIN020) |
| `sigils` | 任意 | Sigil[] | 道具環。12 個まで(JIN020) |
| `rites` | 任意 | Rite[] | 手順環。12 個まで(JIN020) |
| `boundary` | 任意 | Boundary | 境界環 |
| `delegate` | 任意 | str[] | `transfer` で制御を渡せる陣の名前 |

`core` と `flow` は**どちらか一方**(両方 / 両方無しは JIN022)。核なし陣は `state` / `sigils` / `rites` / `boundary` / `delegate` を持てない(JIN002)。

名前の規則(v1 と同じ): 1 文字以上、`[A-Za-z_][A-Za-z0-9_]*`。式の識別子と同じ文法なので、式の中からそのまま参照できる。

### 3.1 State(記憶環)

```json
{ "name": "score", "type": "num", "init": "0", "out": true }
```

| キー | 必須 | 意味 |
|---|---|---|
| `name` | 必須 | 陣内一意 |
| `type` | 必須 | §5 の型 |
| `init` | 必須 | 初期値の**定数式**(§5.3。JIN250)。陣に入る(`entered`)たびに評価し直す |
| `out` | 任意、既定 `false` | 公開。他の陣から `陣名.name` で読める。陣を出ても値が残る(§8.4) |

### 3.2 Sigil(道具環)

`kind` による判別共用体。

<!-- machine-readable: sigil-kinds -->

| kind | 追加キー | 意味 |
|---|---|---|
| `host` | `host`(名前空間名) | ホスト能力の名前空間を許可する。式や `cast` から `name.member(...)` で使う |
| `summon` | `circle`、`rite` | 他の陣の手順を同期呼び出しする。`cast` の `target` に `name` を書く |

<!-- /machine-readable -->

- `name` は陣内一意。`kind: host` の `name` は慣習として `host` と同じにする(例と補完はそうする)が、別名でもよい
- `host` の値は `docs/spec/v2/abilities.md` の名前空間名(`canvas` / `input` / `ui` / `audio` / `random`)。それ以外は JIN205
- `summon` の `circle` は核あり陣、`rite` はその陣の手順(JIN011)。**その手順が `wait` を含むと JIN212**(陣を跨いだ待ちは無い)。呼ばれた手順は呼び先の陣の state を読み書きする(呼び先が `entered` でなくてもよい。state は陣ごとに 1 つで、`init` は `entered` のときだけ評価される。未 entered の陣の state は `init` の値)
- キー順は `name`, `kind`, その種別の追加キー

### 3.3 Rite(手順環)

```json
{ "name": "step", "params": [ { "name": "dt", "type": "num" } ], "returns": "num", "steps": [ … ] }
```

| キー | 必須 | 意味 |
|---|---|---|
| `name` | 必須 | 陣内一意 |
| `params` | 任意、既定 `[]` | 引数。`{ name, type }` |
| `returns` | 任意 | 戻り値の型。無ければ値を返さない(`return` に `expr` を書くと JIN213) |
| `steps` | 必須 | ステップ列。**12 個まで**(JIN210。`if` / `loop` の中は別勘定) |

手順の中の局所スコープ: `params` → `let` → `loop.name`。同じ名前の再宣言は JIN010。局所変数は state を**隠さない**(同名は JIN010)。

### 3.4 Step(ステップ)— 11 種

`do` による判別共用体。**12 種目を足さない。**

<!-- machine-readable: step-kinds -->

| do | 追加キー | 意味 |
|---|---|---|
| `set` | `target`、`expr` | 代入。`target` は代入先の式(§5.4) |
| `let` | `name`、`expr`、`type`(任意) | 局所変数の導入。`type` が無ければ `expr` から推論 |
| `cast` | `target`、`args`(任意、既定 `[]`)、`into`(任意) | 呼び出し。`into` は代入先の式 |
| `if` | `cond`、`then`、`else`(任意、既定 `[]`) | 分岐 |
| `loop` | `kind`、`steps`、(`each`: `name`、`in`)、(`while`: `cond`)、(`count`: `times`、`name` 任意) | 繰り返し |
| `break` | — | 直近の `loop` を抜ける。`loop` の外は JIN213 |
| `wait` | `ticks` または `until`(どちらか 1 つ) | 次の tick 以降まで中断。`ticks` は num の式(1 以上に切り上げ)、`until` は bool の式 |
| `emit` | `circle`、`message`、`args`(任意、既定 `[]`) | 相手の `on message` へ次の tick に配達 |
| `return` | `expr`(任意) | 手順から戻る |
| `finish` | — | 陣を `done` にする。以後この tick の残りのステップは走らない |
| `transfer` | `circle` | `delegate` の相手へ制御を渡す。相手が `done` になるまで自分は休止 |

<!-- /machine-readable -->

`cast` の `target` の解決順: 自陣の `rites[].name` → `sigils[]` の `name`(summon はそのまま、host は `name.member`)→ 組み込みの effect(`push` / `removeAt` / `clear`)。`args` は式の配列で、引数の数と型を照合する(JIN202 / JIN205)。

`loop` の `kind` と描画(`docs/spec/v2/layout.md` §3):

| kind | キー | 意味 |
|---|---|---|
| `each` | `name`、`in`(list の式) | 要素を順に `name` へ束縛。反復中の list の `push` / `removeAt` は**その反復では見えない**(反復は開始時の長さで固定し、添字で読む) |
| `while` | `cond` | 条件が真の間 |
| `count` | `times`(num の式)、`name`(任意。0 始まりの回数) | `floor(times)` 回 |

`wait` の意味: `ticks: n` は「`n` 回の tick の終わりを跨いでから再開」(`n = 1` で次の tick)。`until: e` は「毎 tick の再開段(runtime.md §2 の 2)で `e` を評価し、真になった tick に再開」。**`wait` は core の手順と `on` の手順、およびそこから自陣の `cast` で辿れる手順にだけ書ける。** summon 経由で呼ばれる手順に書くと JIN212。

### 3.5 Boundary(境界環)

```json
{ "on": [ { "event": "tick", "rite": "step" } ],
  "guards": [ { "assert": "score >= 0", "message": "score は負にならない" } ] }
```

<!-- machine-readable: event-kinds -->

| event | 手順の引数(前方部分の省略可) | いつ届くか |
|---|---|---|
| `tick` | `(dt: num)` | 毎 tick、陣が `active` のとき |
| `key` | `(name: str, down: bool)` | キーが押された / 離された tick。`input` の許可が要る(JIN230) |
| `pointer` | `(p: Pointer)` | ポインタが動いた / 押された / 離された tick。`input` の許可が要る(JIN230) |
| `message` | `(name: str, …emit の args)` | 前 tick に `emit` されたメッセージ |
| `exit` | `()` | 陣が `done` になった直後(同 tick) |

<!-- /machine-readable -->

- 同じ `event` を複数書けない(JIN010)。`message` は `name` で振り分けるので手順の中で `if` する
- `rite` は自陣の手順名。引数の型が合わなければ JIN221。**手順の `params` はイベント引数の前方部分でよい**(`tick` の手順に `params` が無くてもよい)
- `guards[].assert` は bool の式。デバッグビルドで毎 tick の終わり(runtime.md §2 の 5)に評価し、偽ならトレースに `assert` 行を残す。実行は止めない。リリースビルドでは評価しない。`message` は任意

### 3.6 Delegate(委譲)

`delegate` は陣名の配列。`transfer` の `circle` はここに無ければ JIN011。委譲先は核あり陣。委譲先が `done` になると委譲元が `active` に戻る(スタック。runtime.md §3)。委譲の有向グラフに閉路があれば JIN012。

## 4. 参照と閉路(v1 §4 の写し)

| 参照 | 先 | 親子辺か |
|---|---|---|
| `root` | circle | — |
| `core` | 自陣の rite | — |
| `flow.steps[]` | circle | **親子辺**(JIN013: 入次数 2 以上はエラー) |
| `delegate[]` | circle | 親子辺ではない(閉路は JIN012) |
| `sigils[kind=summon].circle` / `.rite` | circle / rite | 親子辺ではない(閉路は JIN012) |
| `boundary.on[].rite` | 自陣の rite | — |
| `cast.target` | 自陣の rite / sigil | 自陣の rite 同士の再帰は**許す**(実行時のスタック深さは JIL 側の制限) |
| `emit.circle` | circle | 参照のみ |
| `transfer.circle` | `delegate[]` の要素 | 参照のみ |
| 式の中の `陣名.key` | 他の陣の公開 state | 参照のみ(`out: false` は JIN203) |

## 5. 型

### 5.1 型の書き方

| 書き方 | 意味 |
|---|---|
| `num` | IEEE 754 倍精度 |
| `bool` | 真偽 |
| `str` | Unicode コードポイント列 |
| `list<T>` | `T` の可変長配列。0 始まり |
| 型紙名 | `forms[]` の名前、または組み込み `Pointer` |

`list<list<num>>` のような入れ子を許す。`type` の文字列は上の文法だけ(空白なし。文法違反は JIN002)。
文法は合っているが指す型紙が `forms` にも組み込みにも無いときは **JIN011**(参照解決の一種。設計書 §11 #20)。

### 5.2 値の等価と既定値

- `==` / `!=` は `num` / `bool` / `str` にだけ使える(JIN202)。`list` / 型紙の構造比較は無い
- 型紙の値は**参照**(Lua のテーブル)である。`set ball2 = ball` は同じ値を指す。複製したいときはコンストラクタで作り直す。list も同様
- 型紙コンストラクタ `Ball{x: 1, y: 2, vx: 0, vy: 0}` は**全欄必須**(JIN202)

### 5.3 定数式

`state[].init` と `stage` の値に使える式: リテラル、型紙コンストラクタ(欄も定数式)、list リテラル(要素も定数式)、単項 `-`、純関数の呼び出し(引数も定数式)。識別子(state / 局所 / 他陣)とホスト能力は使えない(JIN250)。

### 5.4 代入先の式(`set.target` / `cast.into`)

`NAME` / `代入先.NAME` / `代入先[expr]` だけ(関数呼び出しや `陣名.key` は不可。JIN202)。先頭の `NAME` は自陣の state か局所変数。他陣の公開 state には書けない(JIN203)。

## 6. Flow(核なし陣)

| キー | 必須 | 意味 |
|---|---|---|
| `kind` | 必須 | `sequence` \| `parallel` \| `loop` |
| `steps` | 必須 | 陣名の配列。1 つ以上。重複不可 |
| `exit` | `loop` のとき必須 | bool の式。**公開 state だけ**を参照できる(JIN220) |

`exit` は `kind: loop` のときだけ許す(それ以外にあれば JIN002)。意味は runtime.md §3。

## 7. 生存状態(runtime.md §3 の要約)

陣の状態は `idle` → `entered` → `active` → `done`。`idle` に戻るのは親の `loop` が次の周に入ったとき(`init` を再評価する)。**公開 state の値は `done` になっても残り、次の `entered` で `init` に戻る。**

## 8. Pointer 空間

v1 `docs/spec/model.md` §6 と同じ: pointer はモデル JSON への JSON Pointer で、ファイル内の位置(pointer→range)、描画要素(`data-jin`)、トレース行(`pointer`)を結ぶ唯一の鍵。**式の中の位置**は「式を持つキーの pointer + 式内のコードポイント列」で表し、診断の `range` は JSON 文字列リテラルの中の該当区間(エスケープを考慮して換算する)を指す。

## 9. 正準形

v1 §2.3 の規則に加えて:

- 式(`init` / `expr` / `cond` / `args[]` / `assert` / `exit` / `ticks` / `until` / `times` / `in` / `target` / `into`。schema の印 `x-jin-expr` を持つ欄)は **AST から書き戻した正準形**にする(expr.md §8・v2.1。設計書 §11 #48。空白は演算子の両側に 1 つ、括弧は必要なときだけ、数値は `str(x)` の書式、文字列は最小エスケープ)。**構文エラーの式は変えない**(入力を失わない。JIN201 は check が出す)
- 既定値(`out: false` / `params: []` / `args: []` / `else: []` / `forms: []` / `assets: []` / `fps: 60` / `seed: 0`)は書かない
- `stage` の数値は整数の JSON 数値で書く(`60`。`60.0` は正準形でない)
