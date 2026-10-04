# 01 クイックスタート：四角を 1 つ動かす

> 10 分。
> ゴールは、小さな `.jin` を検査して走らせ、出力から「動いた」と判定できるようになることです。
> 前提：リポジトリで `uv sync` が済んでいること。

## 動かすもの

64 × 32 の画面で、8 × 8 の四角が 1 フレームに 1 マスずつ右へ進むプログラムです。
ファイルは [`examples/hello/hello.jin`](examples/hello/hello.jin) にあります。

<!-- source: examples/hello/hello.jin -->
```json
  "circles": [
    {
      "name": "Hello",
      "core": "begin",
      "state": [
        {
          "name": "x",
          "type": "num",
          "init": "0",
          "out": true
        }
      ],
```

`.jin` は JSON です。
このファイルには、**陣**（circle）が 1 つだけあります。

陣は、Jin のプログラムを組み立てる単位です。
関数とモジュールの中間のようなもので、自分の値と処理を持ちます。

この陣は、**記憶**（state）を 1 つ持っています。
記憶は陣が持ち続ける変数で、ここでは四角の横位置 `x` です。
`init` に書いた `0` から始まります。

## 1 フレームごとに呼ばれる手順

陣の処理は**手順**（rite）に書きます。
手順は関数に当たり、名前と、上から順に実行する**ステップ**の列を持ちます。

<!-- source: examples/hello/hello.jin -->
```json
        {
          "name": "move",
          "steps": [
            {
              "do": "set",
              "target": "x",
              "expr": "x + 1"
            },
```

ステップは `do` で種類を決めた 1 つの命令です。
`set` は代入で、`x` を `x + 1` にします。

`x + 1` のように、値を計算する文字列を**式**と呼びます。
式は JSON の文字列の中に書きます。

この手順 `move` は、1 フレームに 1 回呼ばれます。
Jin では、この 1 フレームを **tick** と呼びます。

<!-- source: examples/hello/hello.jin -->
```json
      "boundary": {
        "on": [
          {
            "event": "tick",
            "rite": "move"
          }
        ]
      }
```

`"event": "tick"` は「tick ごとに `move` を呼ぶ」という指定です。
1 秒あたりの tick の数は `stage.fps`（ここでは 30）で決まります。

## 検査して、走らせる

まず `jin check` で、ファイルに間違いが無いかを確かめます。

```sh
cd docs/specification-v2/examples
uv run jin check hello/hello.jin
```

<!-- output: hello-check -->
```
1 ファイル / error 0 件 / warning 0 件
```

error が 0 件なら、走らせることができます。
`jin run` は画面を出さずに、指定した tick の数だけ走らせます。

```sh
uv run jin run hello/hello.jin --ticks 3
```

<!-- output: hello-run -->
```
{"Hello.x": 3}
3 tick 走らせました（seed 0）
```

1 行目は、最後の tick が終わったときの `x` です。
3 tick 走らせて `x` が 3 なので、`move` が tick ごとに 1 回ずつ呼ばれたと分かります。

ここに出るのは、`"out": true` を付けた記憶だけです（意味は 2 章）。

## 魔法陣として見る

同じファイルを、魔法陣の図として描けます。

```sh
uv run jin render hello/hello.jin -o hello.svg
```

![hello.jin の魔法陣（jin render の出力）](figures/render-hello.png)

中心が、最初に走る手順 `begin` です。
すぐ外の環に手順が頭文字（B と M）で並び、その外の環に記憶 `x` が四角で描かれます。
残りの 2 つの環は 2 章で、図の読み方は 8 章で扱います。

ブラウザで動かしたいときは、`uv run jin editor hello/hello.jin` でエディタを開き、「実行」を押します。

## 理解度チェック

<!-- quiz: run-and-judge -->
1. `jin run hello/hello.jin --ticks 10` の 1 行目は何になるでしょうか。それは何を確かめたことになりますか。

<details>
<summary>答え</summary>

`{"Hello.x": 10}` です。
tick ごとに `move` が 1 回呼ばれ、`x` が 1 ずつ増えたことを確かめています。
この章の「検査して、走らせる」の 3 tick の例と同じ見方です。

</details>

<!-- quiz: read-parts -->
2. `hello.jin` の `"out": true` を消して `jin run` すると、1 行目はどうなるでしょうか。

<details>
<summary>答え</summary>

`{}` になります。
`jin run` が最後に出すのは `"out": true` の記憶だけなので、`x` は動いていても表示されません。
動いたかどうかを `jin run` の出力で判定したい値には、`"out": true` を付けます。

</details>

→ [02 1 枚の .jin の形](02-shape.md)
