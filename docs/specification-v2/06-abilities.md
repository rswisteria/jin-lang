# 06 能力の一覧：画面・入力・音・乱数・保存

> 所要 8 分（引く用の章）。
> ゴールは、やりたいことに使う道具と、それを式で書くか `cast` で書くかを、表から決められるようになることです。
> 前提：2 章（道具）、3 章（式・`cast`）、4 章（決定性）。

## 式で書くか、`cast` で書くか

道具の名前空間（`canvas` など）のメンバは、4 種類に分かれます。
種類で、書ける場所が決まります。

| 種類 | すること | 書ける場所 |
|---|---|---|
| 描く・鳴らす・書き込む | 画面・音・保存に効果を残す。値は返さない | `cast` だけ |
| 読む | 入力や保存した値を読み、値を返す | 式の中 |
| 描いて読む | ボタンを描き、押されたかを返す | 式の中 |
| 乱数 | 乱数を進めて、値を返す | 式の中 |

## 一覧

| 名前空間 | メンバ | 種類 | すること |
|---|---|---|---|
| `canvas` | `clear(color)` | 描く | 画面を塗りつぶす |
| `canvas` | `ink(color)` | 描く | 以後の色を決める（tick の始めに白へ戻る） |
| `canvas` | `rect(x, y, w, h)` / `circle(x, y, r)` / `line(x1, y1, x2, y2)` | 描く | 四角・円・線 |
| `canvas` | `text(s, x, y)` | 描く | 文字。1 文字の幅は 6 |
| `canvas` | `sprite(name, x, y)` | 描く | `stage.assets` の画像 |
| `input` | `key(name)` | 読む | そのキーが押されている間、真 |
| `input` | `pressed(name)` | 読む | その tick に押されたときだけ、真 |
| `input` | `pointer()` | 読む | `Pointer{x, y, down}` |
| `input` | `text()` | 読む | その tick に確定した文字列（日本語の入力も） |
| `ui` | `button(label, x, y, w, h)` | 描いて読む | ボタンを描き、その中で離されたら真 |
| `ui` | `label(s, x, y)` | 描く | `canvas.text` と同じ |
| `audio` | `tone(hz, ms)` | 鳴らす | 矩形波を鳴らす |
| `audio` | `play(name)` | 鳴らす | `stage.assets` の音 |
| `random` | `next()` | 乱数 | 0 以上 1 未満 |
| `random` | `range(lo, hi)` | 乱数 | `lo` 以上 `hi` **以下**の整数 |
| `storage` | `get(key)` | 読む | 保存した文字列。無ければ `""` |
| `storage` | `set(key, val)` | 書き込む | 文字列を保存する |

時計・ネットワーク・ファイルを使う道具はありません。
4 章の決定性は、この制限で守られています。

## 画面と入力の決まり

- 座標は `stage.width` × `stage.height` の単位で、原点は左上、y は下向きです。
- 画面は毎 tick まっさらから描きます。前の tick の絵は残らないので、毎 tick `clear` から描き直します。
- 色は `"#rgb"` か `"#rrggbb"` です。それ以外の文字列は、走らせたときに止まります（7 章）。
- 文字は 1 文字 6 × 8 の等幅です。文字列の幅は `len(s) * 6` で出せます。
- キーの名前は `ArrowLeft`・`Space`・`KeyA`・`Digit1` のように書きます（ブラウザの `KeyboardEvent.code` の値）。
- `ui.button` は、呼んだ tick にだけ存在します。表示し続けるなら毎 tick 呼びます。

## 乱数

乱数の並びは `stage.seed` で決まります。
`jin run --seed` とプレイヤーの seed 欄で、種だけを変えて試せます。

乱数の状態は画面全体で 1 つです。
`parallel` で同時に動く陣が乱数を使うと、並べた順で値が決まります。

## 保存領域：次の起動まで残す

ハイスコアのように、プログラムを閉じても残したい値は、**保存領域**（`storage`）に書きます。
キーも値も文字列なので、数は `str` で書き、`num` で読み戻します。

正典（[`abilities.md`](../spec/v2/abilities.md)）では、保存領域を「記憶」と呼んでいます。
この本では、陣の記憶（state）と区別するために保存領域と呼びます。

[`examples/memory/visits.jin`](examples/memory/visits.jin) は、起動するたびに回数を 1 増やして保存します。

<!-- source: examples/memory/visits.jin -->
```json
            {
              "do": "set",
              "target": "count",
              "expr": "num(storage.get(\"visits\")) + 1"
            },
            {
              "do": "cast",
              "target": "storage.set",
              "args": [
                "\"visits\"",
                "str(count)"
              ]
            },
```

ブラウザでは、保存領域はそのブラウザの中に残ります。
`jin run` では、`--storage` に渡したファイルに残ります。

```sh
uv run jin run memory/visits.jin --storage memory.json
uv run jin run memory/visits.jin --storage memory.json
```

<!-- output: visits-run -->
```
{"Visits.count": 1}
{"Visits.count": 2}
```

2 回目の起動で、1 回目に保存した 1 を読んで 2 になりました。

## 理解度チェック

<!-- quiz: pick-ability -->
1. 「画面のボタンを押したらスコアを 1 増やす」を書きます。`ui.button` はどこに書きますか。また、なぜ毎 tick 呼ぶ必要があるのですか。

<details>
<summary>答え</summary>

`if` の `cond` に `ui.button("PLUS", 4, 4, 40, 16)` のように書き、`then` でスコアを増やします。
`ui.button` は描いて読む種類なので、式の中に書けます。
呼んだ tick にだけ描かれて判定されるので、表示し続けるには、`on` の `tick` で呼ぶ手順から毎 tick 呼びます。

</details>

<!-- quiz: keep-value -->
2. ハイスコアを `storage` に残したら、次の起動でも 0 から始まってしまいました。どこを確かめますか。

<details>
<summary>答え</summary>

起動時に `num(storage.get(…))` で読み戻しているか、`cast` で `storage.set` を呼んでいるか、を確かめます。
`jin run` で試しているなら、`--storage` に同じファイルを渡しているかも確かめます。

</details>

→ [07 間違いを見つけて直す](07-debug.md)
