# Researcher：調査と要約を組み合わせる

[researcher.jin](researcher.jin)は、情報を調べ、要約し、人の確認を経て公開する構成を表したサンプルです。ツールの呼び出し、別のエージェントへの依頼、処理前のチェックを、ひとつの魔法陣で確認できます。

検索サービスや公開先との接続は含まれていません。まずはエディタで構成を見たり、テスト用の応答で実行の仕組みを試したりするための例です。

## 処理の流れ

入口は調査担当の `Researcher` です。「出典を示す」「公開前に人間の確認を求める」という指示を受け、必要な道具を選びます。

| 道具 | 役割 | 接続先 |
|---|---|---|
| `search` | 情報を検索する | `research.tools:web_search` |
| `fetch` | ページの本文を取得する | `research.tools:fetch_page` |
| `summarize` | 本文の要約を依頼する | `Summarizer` |
| `publish` | 結果を公開する | `research.tools:publish` |

これらは固定順の手順ではありません。どの道具をいつ使うかはモデルが判断します。`Summarizer` には、受け取った本文を200字で要約する指示があります。文字数や出典の正しさを検証する処理はありません。

## 設計と実装

2つの陣は、どちらも `gemini-2.5-flash` を使うLLMエージェントです。調査と要約を分担し、`summon` を通じて要約担当を道具として呼び出します。生成コードでは `Summarizer` を `AgentTool` で包み、結果を調査担当へ返します。

`state` は実行中に情報を受け渡すための記憶です。`Researcher` の応答は `findings`、`Summarizer` の応答は `summary` に保存されます。`{findings}` は指示文へ記憶を埋め込む書き方です。`query` も宣言されていますが、入力を自動で代入する設定はありません。`jin run` は宣言済みの記憶を最初に `None` で初期化します。

処理の境界には、次の拡張点があります。

- `before_model`：モデルへ送る前に `pii_filter` を呼ぶ。
- `before_tool`：道具を使う前に `audit_log` を呼ぶ。
- `await: ["publish"]`：公開処理を `LongRunningFunctionTool` として生成し、外部の応答を待つ処理に対応させる。

`await` だけで承認画面や公開の制御が完成するわけではありません。実用化には、承認待ちの管理・結果の返却と、各関数の実装が必要です。付属の[ツール](../../tests/fixtures/stubs/research/tools.py)は固定の文字列を返し、[チェック関数](../../tests/fixtures/stubs/research/guards.py)は何もせず通過します。実際の検索・公開・個人情報の除去・監査ログの記録は行いません。

## 試す

[セットアップ](../../README.md#エディタの実行方法)を済ませ、リポジトリのルートで実行してください。表示・編集にはAPIキーは不要です。

```bash
uv run jin editor examples/researcher/researcher.jin
```

APIを呼ばずに実行するには、テスト用の関数を読み込めるようにします。

```bash
PYTHONPATH=tests/fixtures/stubs uv run jin run examples/researcher/researcher.jin "公開情報を調べて要約してください" --model fake
```

この実行では `fake-response` が返ります。既定の疑似モデルは道具を呼ばないため、要約担当の呼び出しや公開前の承認を体験するものではありません。

実モデルで使う場合は、モデルの認証設定に加え、`research.tools` と `research.guards` の実装を用意してください。`jin run` は参照先のPythonコードを読み込んで実行するため、内容を確認したコードを使います。
