# 07 間違いを見つけて直す

> 12 分（演習つき）。
> ゴールは、`jin check` と `jin run` が出す知らせから、直す場所と直し方を決められるようになることです。
> 前提：2 章（道具・境界）、3 章（式）、4 章（トレース）。

## 間違いが見つかる 3 つの場面

| 場面 | 見つかるもの | 知らせ方 |
|---|---|---|
| `jin check`（エディタは打つたび） | 書き方の間違い・型の不一致・名前の書き間違い | **診断** |
| `jin run` の途中 | 走らせて初めて分かる間違い（添字が範囲外など） | **実行時エラー** |
| `jin run --trace` の途中 | `guards` に書いた条件が破れた | トレースの `assert` の行 |

この順に、早く見つかります。
走らせる前に `jin check` を通すのが近道です。

## 診断の読み方

診断は、1 つにつき 3 行で出ます。

<!-- output: ex-fix-start -->
```
ex-fix/start.jin:73:32: error JIN202: '++' の右辺は str です（実際 num）
  hint: 型を合わせてください（docs/spec/v2/expr.md §2）
  pointer: /circles/0/rites/2/steps/1/args/0
```

| 部分 | 例 | 意味 |
|---|---|---|
| 場所 | `ex-fix/start.jin:73:32` | ファイル・行・列（1 から数える） |
| 重さと番号 | `error JIN202` | `error` は直さないと走らせられない。`warning` は走らせられる |
| 説明 | `'++' の右辺は str です（実際 num）` | 何が合わないか |
| `hint` | `型を合わせてください…` | 直し方の手がかり |
| `pointer` | `/circles/0/rites/2/steps/1/args/0` | JSON の中の場所。エディタは、この場所の図の要素に診断の印を付ける |

`pointer` は、`circles` の 0 番目の陣の、`rites` の 2 番目の手順の、1 番目のステップの、`args` の 0 番目、と読みます。

## よく出る番号

| 番号 | 何が起きたか | よくある直し方 |
|---|---|---|
| JIN002 | 欄の名前や形が違う | 綴りと必須の欄を確かめる |
| JIN010 | 名前が重なっている | 名前を変える |
| JIN011 | 名前の先が無い（手順・陣・型紙） | 綴りを直す、または定義を足す |
| JIN020 | 記憶・道具・手順が 12 個を超えた | 陣を分ける |
| JIN022 | `core` と `flow` が両方ある、または両方無い | どちらか一方にする |
| JIN201 | 式の書き方が違う | 括弧と演算子を確かめる |
| JIN202 | 型が合わない | `str(x)`・`num(s)` で変える |
| JIN203 | 式の名前が見つからない、または公開していない | 綴り、または相手に `"out": true`（2 章） |
| JIN204 / JIN205 | 道具環に無い名前空間、または無いメンバ | 道具を足す、メンバ名を直す |
| JIN210 / JIN211 | ステップが 12 個を超えた、入れ子が 3 段を超えた | 手順に切り出す |
| JIN212 | `summon` で呼ばれる手順に `wait` がある | `emit` に置き換える（5 章） |
| JIN220 | 終了条件が公開していない記憶を読んでいる | `"out": true` を付ける |
| JIN230 | `key` / `pointer` を受けるのに `input` が無い | 道具環に `input` を足す |
| JIN250 | `init` に計算が書いてある | 決まった値にする（2 章） |

番号の全部は [`docs/spec/v2/diagnostics.md`](../spec/v2/diagnostics.md) にあります。

<!-- exercise: ex-fix -->
### 演習：2 つの間違いを直す

[`examples/ex-fix/start.jin`](examples/ex-fix/start.jin) は、Space を押すとスコアが増えるプログラムです。
`jin check` で error が 2 件出ます。
0 件にしてください。

```sh
uv run jin check ex-fix/start.jin
```

2 件目の診断は次のとおりです。

<!-- output: ex-fix-start -->
```
ex-fix/start.jin:87:11: error JIN230: 'key' イベントを受けるには input の許可が要ります
  hint: "sigils" に {"name": "input", "kind": "host", "host": "input"} を足す
```

<details>
<summary>答え</summary>

1. `canvas.text` の引数を `"\"SCORE \" ++ str(score)"` にします。`++` は文字列どうしをつなぐので、数の `score` は `str` で文字列にします。
2. 道具環に `{"name": "input", "kind": "host", "host": "input"}` を足します。`on` の `key` を受けるには `input` が要ります。

答えは [`examples/ex-fix/answer.jin`](examples/ex-fix/answer.jin) です。

<!-- output: ex-fix-answer -->
```
1 ファイル / error 0 件 / warning 0 件
```

どちらも `hint` に直し方がそのまま書いてありました。
迷ったら、まず `hint` を読みます。

</details>

## 実行時エラー：走らせて初めて分かる間違い

list の添字が範囲を超えるような間違いは、`jin check` では見つかりません。
走らせた tick で止まり、**実行時エラー**として知らされます。

[`examples/debug/oops.jin`](examples/debug/oops.jin) は、3 つしかない list を tick ごとに 1 つずつ読み進めます。

```sh
uv run jin run debug/oops.jin --ticks 5
```

<!-- output: oops-run -->
```
{"Oops.i": 3, "Oops.last": 30}
4 tick 走らせました（seed 0、tick 3 で done）
debug/oops.jin: 実行時エラー: 添字 3 は範囲外です（長さ 3）
```

tick 3 で 4 つ目を読もうとして止まり、そこで終わりました。
実行時エラーで止まった `jin run` は、終了コード 1 を返します。

トレースを取ると、止まった手順が `"kind":"error"` の行に残ります。
エディタの実行パネルでは、その tick まで戻って値を確かめられます。

## 見張り：破れてはいけない条件

`guards` に書いた条件は、`--trace`（または `--debug`）で走らせたときだけ、毎 tick の終わりに確かめます。
破れても止まりませんが、トレースに `"kind":"assert"` の行が残ります。

[`examples/debug/guard.jin`](examples/debug/guard.jin) は、`hp >= 0` を見張りながら、毎 tick `hp` を 1 減らします。

```sh
uv run jin run debug/guard.jin --ticks 4 --trace guard.jsonl
grep '"kind":"assert"' guard.jsonl
```

<!-- output: guard-trace -->
```
{"seq":13,"tick":2,"circle":"Hero","kind":"assert","name":null,"pointer":"/circles/0/boundary/guards/0","input":null,"output":"hp は負にならない"}
```

`hp` が −1 になった tick 2 から、`message` に書いた文が記録されます。
「起きてはいけないこと」を条件にしておくと、どの tick から崩れたかを探せます。

## 理解度チェック

<!-- quiz: read-diagnostic -->
1. `pointer: /circles/1/boundary/on/0` の診断は、ファイルのどこを指していますか。

<details>
<summary>答え</summary>

2 番目の陣（0 から数えて 1）の境界環の、`on` の最初の 1 つです。
`circles` と `on` の添字は、どちらも 0 から数えます。

</details>

<!-- quiz: fix-error -->
2. `jin check` は通るのに、`jin run` が終了コード 1 で止まりました。何を見て、どこを直しますか。

<details>
<summary>答え</summary>

実行時エラーの文（例：「添字 3 は範囲外です（長さ 3）」）と、止まった tick を見ます。
トレースの `"kind":"error"` の行の `pointer` が、止まった手順を指しているので、そこで添字や色の値を直します。

</details>

→ [08 図として読む](08-views.md)
