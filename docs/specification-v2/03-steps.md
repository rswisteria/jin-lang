# 03 ステップと式

> 所要 12 分。
> ゴールは、11 種のステップと式で手順の中身を書き、`jin fmt` が式をどう揃えるかを予想できるようになることです。
> 前提：1 章（ステップ・式）、2 章（道具・型紙）。

## 11 種のステップ

手順の `steps` に並べられるのは、次の 11 種だけです。
`do` の値で種類を決めます。

| `do` | 書くもの | すること |
|---|---|---|
| `set` | `target`・`expr` | 記憶か局所変数に代入する |
| `let` | `name`・`expr`・`type`（任意） | 局所変数を作る |
| `cast` | `target`・`args`・`into`（任意） | 手順・道具を呼ぶ。戻り値は `into` に入れる |
| `if` | `cond`・`then`・`else`（任意） | 分岐する |
| `loop` | `kind`（`each` / `while` / `count`）と、その種類の欄・`steps` | 繰り返す |
| `break` | — | いちばん内側の `loop` を抜ける |
| `return` | `expr`（任意） | 手順から戻る |
| `finish` | — | 陣を終える。この tick の残りのステップは走らない |
| `wait` | `ticks` か `until` | 次の tick 以降まで止まる（4 章） |
| `emit` | `circle`・`message`・`args` | ほかの陣の `on message` へ、次の tick に届ける（5 章） |
| `transfer` | `circle` | `delegate` に書いた陣へ制御を渡す（5 章） |

`if` と `loop` の中にもステップを並べられます。
入れ子は 3 段までです。

`loop` の種類ごとの欄は次のとおりです。

| `kind` | 欄 | 回り方 |
|---|---|---|
| `each` | `name`・`in` | `in` の list の要素を順に `name` へ入れる |
| `while` | `cond` | `cond` が真の間 |
| `count` | `times`・`name`（任意） | `floor(times)` 回。`name` は 0 から数える |

## 例：list を数える

[`examples/steps/steps.jin`](examples/steps/steps.jin) の手順 `begin` は、list の合計と偶数の個数を数え、別の手順で 2 倍にして、ラベルを作ります。

<!-- source: examples/steps/steps.jin -->
```json
            {
              "do": "loop",
              "kind": "each",
              "name": "x",
              "in": "xs",
              "steps": [
                {
                  "do": "set",
                  "target": "total",
                  "expr": "total + x"
                },
                {
                  "do": "if",
                  "cond": "x % 2 == 0",
                  "then": [
                    {
                      "do": "set",
                      "target": "evens",
                      "expr": "evens + 1"
                    }
                  ]
                }
              ]
            },
```

<!-- source: examples/steps/steps.jin -->
```json
            {
              "do": "cast",
              "target": "double",
              "args": [
                "total"
              ],
              "into": "big"
            },
```

`cast` は、同じ陣の手順 `double` を呼び、戻り値を局所変数 `big` に入れます。
`double` は `params` に引数 `n`、`returns` に戻り値の型 `num` を書いた手順です。

```sh
uv run jin run steps/steps.jin
```

<!-- output: steps-run -->
```
{"Calc.total": 31, "Calc.evens": 3, "Calc.label": "big 62"}
1 tick 走らせました（seed 0、tick 0 で done）
```

合計は 31、偶数は 3 個、2 倍の 62 は 50 より大きいので `big 62` です。
最後の `finish` で陣が終わったので、`jin run` は tick 0 で止まりました。

## 式の書き方

式は、ふつうの言語の式とほぼ同じです。
違うところだけを挙げます。

| 書き方 | 意味 | 気をつけること |
|---|---|---|
| `+ - * / %` | num の計算 | `/` は常に小数。`%` の結果の符号は右側に合わせる |
| `++` | str の連結 | 数を連結するときは `str(x)` にする |
| `== !=` | 等しいか | num・bool・str だけ。list や型紙は比べられない |
| `< <= > >=` | 大小 | num だけ。`a < b < c` のようにつなげない |
| `and or not` | 論理 | 右側は必要なときだけ評価する |
| `xs[i]` | list の要素 | 0 から数える。範囲外は走らせたときに止まる（7 章） |
| `ball.x` | 型紙の欄 | — |
| `Play.score` | ほかの陣の公開した記憶 | 読むだけ |
| `canvas.rect(…)` など | 道具の呼び出し | 値を返すものだけが式に書ける（6 章） |

式は JSON の文字列の中に書くので、式の中の文字列は `"\"SCORE \""` のように二重に囲みます。
エディタの式の欄では、外側の 1 段を外した `"SCORE "` で見えます。

名前は、次の順で探されます。

1. 手順の局所（引数・`let`・`loop` の `name`）
2. 自分の陣の記憶
3. 道具の名前（`canvas.` のように `.` が続くとき）
4. ほかの陣の名前（`Play.` のように `.` が続くとき）
5. 型紙の名前（`Ball{` のように `{` が続くとき）
6. **純関数**

純関数は、宣言なしで使える組み込みの関数です。
状態を変えず、同じ引数なら同じ値を返します。

| 種類 | 名前 |
|---|---|
| 数 | `abs` `min` `max` `floor` `ceil` `round` `sqrt` `sin` `cos` `atan2` `clamp` |
| 文字列 | `str` `num` `len` `sub` `cmp` |
| list | `len` `contains` |

`round` は `.5` を偶数へ丸めます（`round(2.5)` は 2）。
`num("12")` は 12 で、数として読めない文字列は 0 になります。

list を変える 3 つの操作（`push`・`removeAt`・`clear`）は、式ではなく `cast` で呼びます。

## `cast` の呼び先と、代入先

`cast` の `target` は、次の順で探されます。

1. 自分の陣の手順の名前
2. 道具の名前（`canvas.rect` のように `名前.メンバ`）
3. `push` / `removeAt` / `clear`

`set` の `target` と `cast` の `into` に書けるのは、`score`・`ball.x`・`xs[i]` の形だけです。
ほかの陣の記憶には書けません。

## 正準形：保存すると式の形が揃う

`jin fmt` やエディタの保存は、ファイルを決まった形に揃えます。
この形を**正準形**と呼びます。

[`examples/steps/messy.jin`](examples/steps/messy.jin) は、わざと崩して書いた例です。

<!-- source: examples/steps/messy.jin -->
```json
        { "name": "begin", "steps": [{ "do": "set", "target": "total", "expr": "(total+(1))*2.50" }] }
```

`jin fmt` を通すと、式はこうなります。

<!-- output: messy-fmt -->
```
"expr": "(total + 1) * 2.5"
```

演算子の両側に空白が 1 つ入り、要らない括弧が消え、`2.50` は `2.5` になりました。
既定値と同じ欄（`"fps": 60`・`"out": false`）も消えます。

打ち方の揺れが差分に出ないので、人が書いても LLM が書いても、保存すれば同じ形になります。
構文の間違った式は、1 文字も変えずに残します。

## 理解度チェック

<!-- quiz: write-rite -->
1. 「list `xs` の中で 10 以上の要素の数を `big` に数える」ステップを、表の種類で組み立ててください。

<details>
<summary>答え</summary>

`loop`（`kind: "each"`・`name: "x"`・`in: "xs"`）の中に、`if`（`cond: "x >= 10"`）を置き、その `then` に `set`（`target: "big"`・`expr: "big + 1"`）を置きます。
`steps.jin` の偶数を数える部分と同じ形です。

</details>

<!-- quiz: predict-fmt -->
2. `"expr": "((a))+b*2.0"` は、`jin fmt` の後どうなるでしょうか。

<details>
<summary>答え</summary>

`"a + b * 2"` です。
`((a))` の括弧は要らないので消え、演算子の両側に空白が入り、`2.0` は整数の `2` になります。
`messy.jin` の例と同じ規則です。

</details>

→ [04 時間の進み方](04-time.md)
