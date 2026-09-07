---
name: jin-lang
description: Use when writing, fixing, or reviewing a `.jin` file — Jin(陣) の魔法陣型エージェント記述言語。Google ADK のエージェントを JSON で書き、jin check の診断で直し、jin build / jin run で動かすまでの手順を規定する。Triggers on `.jin` files, "jin", "陣", "魔法陣", or requests to build a Google ADK agent declaratively.
---

# Jin(陣) の書き方

`.jin` は Google ADK 上の LLM エージェントを**魔法陣として描けるモデル**として書く JSON である。
人間は視覚エディタで書き、LLM（あなた）は**テキストを直接書いて診断で直す**。

**テキストは人間が読まない。** 整形の好みで悩まない。`jin fmt` が正準形に直す。

## 手順（この順に行う）

1. **`reference/jin.schema.json` と `reference/model.md` を読む。** 記憶で書かない。
   キー名・enum・上限値はそこにしか無い
2. `.jin` を書く
3. **`jin check --json <file>`** を走らせる
4. 診断が出たら `hint` を**そのまま**使って直す。hint は「近い名前: Summarizer」のように
   具体値で書いてある。3 に戻る
5. `jin fmt <file>` で正準形にする
6. `jin build <file> --out <dir>` で ADK プロジェクトを生成する
7. `jin run <file> "<prompt>" --model fake` で疎通を見る（**ネットワークに出ない**）
8. 必要なら `jin render <file> -o out.svg` で図を確認する

## 最小の例

核（`core`）を持つ陣が 1 つ。これが最小の有効な `.jin` である。

```json
{
  "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
  "version": 1,
  "root": "Answerer",
  "circles": [
    {
      "name": "Answerer",
      "core": "gemini-2.5-flash",
      "instruction": {
        "rune": "質問に日本語で答える。答えは {answer} に入れる"
      },
      "state": [
        {
          "name": "answer",
          "type": "string",
          "out": true
        }
      ]
    }
  ]
}
```

## 流れを持つ例

`flow` を持つ陣は**核を持たない**（`core` と `flow` は排他・JIN022）。
`steps` は他の陣の名前である。

```json
{
  "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
  "version": 1,
  "root": "Pipeline",
  "circles": [
    {
      "name": "Pipeline",
      "flow": {
        "kind": "sequence",
        "steps": [
          "Drafter",
          "Reviewer"
        ]
      }
    },
    {
      "name": "Drafter",
      "core": "gemini-2.5-flash",
      "instruction": {
        "rune": "下書きを書く"
      }
    },
    {
      "name": "Reviewer",
      "core": "gemini-2.5-flash",
      "instruction": {
        "rune": "下書きを直す"
      }
    }
  ]
}
```

仕様の全体は `reference/model.md` にある。**例をこれ以上増やさない**。
迷ったら reference を読む。

## つまずきやすいところ

- **名前が ID である。** circle 名・tool 名・state 名は参照の鍵で、変えると参照も直す必要がある。
  LSP の rename（エディタ / Claude Code の rename）は参照を全部追随させる
- `flow.max` は ADK では `max_iterations` になる。`.jin` 側では `max` と書く
- `instruction.rune` の `{key}` は state のキーを指す。`{{` と `}}` は文字通りの波括弧
- `tools[].name` は**静的検証と描画にだけ**使う。LLM に見える名前は ADK 側で決まる
- `jin check --resolve` と `jin run` は `tools[].ref` が指す Python モジュールを
  **実際に import する**（＝そのコードを実行する）。**中身を確認していない `.jin` に使わない**

## 診断コードの読み方

`jin check --json` の出力は要件書 §5 の形で、`code` / `message` / `hint` / `range` を持つ。
よく出るもの:

| コード | 意味 | 直し方 |
|---|---|---|
| JIN001 | JSON の構文エラー | `range` の位置を見る |
| JIN002 | スキーマ違反（未知のキー・型違い） | hint に「許されるキー」が並ぶ |
| JIN011 | 未解決の参照 | hint の「近い名前」に置き換える |
| JIN020 | `tools` / `state` が 12 を超えた | サブ陣に抽出する（codeAction がある） |
| JIN022 | `core` と `flow` の両立、または両方欠落 | どちらか一方にする |
| JIN030 | `loop` に `max` も `exit` も無い | `max: 5` を足す |
| JIN060 | `root` が存在しない陣を指す | hint の候補に置き換える |

段は **JSON 構文 → スキーマ → 意味** の順で、前段が通らなければ後段は出ない。
JIN001 を直すと別のエラーが出てくるのは正常である。
