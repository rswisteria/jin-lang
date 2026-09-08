# Showcase：魔法陣の全9種類の要素を試す

[showcase.jin](showcase.jin)は、エディタで要素を選び、プロパティを編集し、実行履歴の重なり方を確認するためのサンプルです。受付・要約・引き継ぎ・保管という役割を使って、描画に必要な構成をまとめています。

実際の受付業務や保管サービスは実装していません。画面の動作確認や、Jinの表現を見渡したいときに使います。

## 処理の流れ

入口の `Showcase` が、受付担当の `Desk`、保管担当の `Archivist` の順に、最大3回処理を繰り返します。各回の末尾で `approved` が `true` と一致すれば終了します。

| 陣 | 役割とつながり |
|---|---|
| `Showcase` | モデルを持たず、繰り返しと終了条件を管理する |
| `Desk` | 検索・本文取得・公開の道具を持つ受付担当。応答を `findings` に保存する |
| `Summarizer` | `Desk` が `summon` で呼び出す要約担当。応答を `summary` に保存する |
| `Helper` | `Desk` が `delegate` で仕事を引き継ぐ担当 |
| `Archivist` | 結果の保管と承認を指示された担当。応答を `approved` に保存する |

`Summarizer` と `Helper` は毎回必ず動くわけではありません。`Desk` のモデルが呼び出し・引き継ぎを選んだときに動きます。`Archivist` に保存先の道具やデータベース接続はなく、応答の保存先は実行中の記憶です。指示文には `{findings}` の埋め込みもありません。

## 図で確認できること

既定の表示で、次の9種類の要素を選択できます。名前は描画属性 `data-jin-kind` に対応します。

| 要素 | 図での表現・確認箇所 |
|---|---|
| `circle` | 各担当を表す陣 |
| `core` | `Desk` などのモデルを表す核 |
| `rune` | 担当への指示を表す文字列 |
| `tool` | 検索・要約などの道具を表す紋 |
| `state` | `findings` などの記憶を表す四角 |
| `flow-edge` | 処理順を表す弦・矢印、終了条件の菱形 |
| `guard` | モデルや道具を呼ぶ前のチェックを表す刻印 |
| `await` | 公開処理の応答待ちを表す境界環の欠け |
| `delegate` | `Helper` への引き継ぎを表す小円と破線 |

## 設計と実装

`Showcase` は `LoopAgent`、モデルを持つ4つの陣は `LlmAgent` に変換されます。`summon` は `AgentTool` として要約を依頼し、結果を呼び出し元へ返す構成です。`delegate` は `sub_agents` に担当を登録し、モデルが制御を引き継げる構成です。

`Desk` には通常のPython関数、別の陣の呼び出し、組み込み道具の3種類があります。`finish` は組み込みの `exit_loop` で、モデルが呼べばループを抜けます。各回の末尾に追加される状態判定とは別の終了経路です。

検索・公開・チェックには、Researcherと同じ `research.tools` と `research.guards` を参照します。付属するのは[固定応答のツール](../../tests/fixtures/stubs/research/tools.py)と[何もしないチェック関数](../../tests/fixtures/stubs/research/guards.py)です。`await: ["publish"]` は長時間処理用の道具へ変換する設定で、承認画面や公開制御は別途実装が必要です。

承認判定では、モデルの応答全体がJSONの `true` と解釈できる必要があります。`type: "bool"` を書いても自動変換はされず、「承認しました」という応答では終了条件に一致しません。

## 試す

[セットアップ](../../README.md#エディタの実行方法)を済ませ、リポジトリのルートで実行してください。表示・編集にはAPIキーやスタブは不要です。

```bash
uv run jin editor examples/showcase/showcase.jin
```

要素をクリックしてプロパティを確認します。保存するとサンプル自体が更新されます。

実行履歴を試すには、テスト用の関数を読み込めるようにします。

```bash
PYTHONPATH=tests/fixtures/stubs uv run jin run examples/showcase/showcase.jin "受付の流れを確認してください" --model fake --trace /tmp/jin-showcase-trace.jsonl
```

エディタの「デバッグ」で `/tmp/jin-showcase-trace.jsonl` を読み込みます。疑似モデルは `fake-response` を返し、1回につき `Desk`、`Archivist`、終了判定の3件、3回で計9件のイベントを記録します。

この実行では道具の呼び出しや引き継ぎは起きず、核と終了条件の印が強調されます。全9種類の要素を選べることと、全要素が実行で光ることは別です。実モデルで試す場合も、呼び出す道具はモデルの判断に依存します。`jin run` は参照先のPythonコードを実行するため、内容を確認したコードを使ってください。
