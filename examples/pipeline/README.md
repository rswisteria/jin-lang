# Pipeline：下書きを作り、レビューを踏まえて改善する

[pipeline.jin](pipeline.jin)は、文章の作成・レビュー・書き直しを担当するエージェントを、決まった順序で動かすサンプルです。処理の順序と、繰り返しを止める条件の書き方が分かります。

## 処理の流れ

```text
Drafter：下書きを作成
  → Reviewer：下書きをレビュー
  → Refine：次の処理を最大3回繰り返す
      Critic：下書きを批評し、承認を判断
        → Rewriter：レビューを踏まえて書き直す
        → 承認条件を確認。一致すれば終了
```

| 担当 | 読む記憶 | 応答の保存先 |
|---|---|---|
| `Drafter` | なし | `draft`（下書き） |
| `Reviewer` | `draft` | `review`（レビュー） |
| `Critic` | `draft` | `approved`（承認判定） |
| `Rewriter` | `review`、`draft` | `draft`（更新後の下書き） |

`Reviewer` は最初の1回だけ動きます。繰り返しの中では、同じレビューを使って下書きを更新します。`Critic` の応答は承認判定に使われ、書き直し担当の指示文には埋め込まれていません。

## 設計と実装

全体を進める `Pipeline` と、改善を繰り返す `Refine` は、モデルを持たず `flow` で進行を制御する陣です。生成コードでは、それぞれ `SequentialAgent` と `LoopAgent` に対応します。残りの4つの陣は `gemini-2.5-flash` を使うLLMエージェントです。このサンプルに並列処理はありません。

`state` の `out: true` は、エージェントの応答を指定の名前で保存する設定です。生成コードでは `output_key` に対応し、`{draft}` や `{review}` を通じて次の担当へ渡します。`Rewriter` は同じ `draft` を上書きします。

`Refine` の終了条件は `approved` と `true` の一致です。Jinはループの末尾に判定役の `StateCheckAgent` を追加します。そのため、`Critic` が承認しても、その回の `Rewriter` は実行されます。判定対象は書き直す前の下書きなので、最後の書き直しが承認済みであることまでは保証しません。

`type: "bool"` は型の表示用の宣言で、応答を真偽値へ変換する設定ではありません。モデルの応答は文字列として保存され、判定役がJSONとして解釈します。`true` は一致しますが、`approved=true` や「承認しました」は一致しません。現状の指示文は応答形式を厳密に制限していないため、条件が成立せず3回で終了する場合があります。

## 試す

[セットアップ](../../README.md#エディタの実行方法)を済ませ、リポジトリのルートで実行してください。

```bash
uv run jin editor examples/pipeline/pipeline.jin
```

APIキーなしで処理の順序を確認できます。外部のPython関数を参照しないため、スタブの指定も不要です。

```bash
uv run jin run examples/pipeline/pipeline.jin "Jinの紹介文を書いてください" --model fake --trace /tmp/jin-pipeline-trace.jsonl
```

疑似モデルは文章の作成や批評をせず、各担当が `fake-response` を返します。承認条件は成立せず、改善を3回繰り返します。トレースはモデルの応答8件と終了判定3件の計11件です。

エディタの「デバッグ」で `/tmp/jin-pipeline-trace.jsonl` を読み込むと、処理の履歴を図上で確認できます。実際に文章を生成するには、モデルの認証を設定して `--model fake` を外してください。
