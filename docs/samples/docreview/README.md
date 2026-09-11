# 文章レビューエージェント（DocReview サンプル）

Web サイトの告知文、技術記事、社内周知などの文章を多角的に検査し、重大な不備や誤字・用語ブレを検出して厳格に合否判定（OK / NG）を下すマルチエージェントシステムの動くサンプルコード集です。

設計思想、詳細な解説、各ステップの内部動作については、解説ドキュメント [**文章レビューエージェントを Jin で作る — 実践開発・実行ガイド**](../../document-review-agent.md) を参照してください。

---

## 含まれるファイル一覧

| ファイル | 役割 | 入出力・補足 |
|---|---|---|
| [`docreview.jin`](docreview.jin) | **エージェント陣の定義** | 11 個の Circle（エージェント）で構成。<br>Profiler（基準抽出）→ 6 観点並列検査 → Verifier（指摘検証）→ Judge（判定） |
| [`review/rules.py`](review/rules.py) | **合否判定の決定的ルール** | Python の純関数 `decide()` と ADK 連携関数 `judge()`。<br>LLM に合否を委ねず、プログラムで厳格に判定します |
| [`sample-notice.md`](sample-notice.md) | **レビュー対象のサンプル文章** | 勤怠システム切り替えの社内周知。<br>意図的に誤字（`Slcak`）、用語ブレ（Slack/スラック）、前提矛盾、5W1H の不足を含めてあります |
| [`verdict.py`](verdict.py) | **判定抽出スクリプト** | 実行トレース（JSONL）から最終判定を取り出す CLI。<br>終了コード（0: OK / 1: NG / 2: 判定不能）で結果を返します |
| [`trace-gemini-3.8-flash.jsonl`](trace-gemini-3.8-flash.jsonl) | **実際の実行トレースログ** | Gemini 3.8 Flash（Vertex AI `global`）で `sample-notice.md` を流した実記録。<br>API キー無しで判定の抽出を即座に試せます（結果: NG・63 点） |

---

## クイックスタート

すべてのコマンドはリポジトリのルートディレクトリで実行します。

### 1. 同梱トレースから判定を取り出す（API キー不要・所要時間 1 秒）

実モデルの実行ログから、判定スクリプトがどのように結果を取り出すかをすぐに確認できます。

```bash
uv run python docs/samples/docreview/verdict.py docs/samples/docreview/trace-gemini-3.8-flash.jsonl
echo "終了コード: $?"  # 1 = NG（不合格）
```

仕込まれた誤字や「旧システム停止と勤怠締めの矛盾」が検出され、NG（63 点）と判定された JSON が出力されます。

### 2. fake モデルでパイプラインを空回しする（API キー不要）

構文チェックとモック実行を行い、11 個のエージェントが設計通りの順序（順次・並列）で処理を巡ることを確認します。

```bash
# 構文・意味の静的検査
uv run jin check docs/samples/docreview/docreview.jin

# fake モデルで実行（固定のダミー応答でパイプラインを一周させる）
PYTHONPATH=docs/samples/docreview uv run jin run docs/samples/docreview/docreview.jin \
  "テスト用の文章です" --model fake --trace /tmp/docreview-fake.jsonl
```

### 3. ビジュアルエディタで確認する（API キー不要）

ブラウザ上で魔法陣の構成や、トレースのイベントリプレイを確認できます。

```bash
uv run jin editor docs/samples/docreview/docreview.jin
```

エディタの「デバッグ」タブで `trace-gemini-3.8-flash.jsonl` を読み込むと、各エージェントの入出力やハイライト表示を確認できます。

### 4. 実モデルで文章をレビューする（要 API キー / Vertex AI 認証）

Gemini API キー、または Vertex AI の認証を設定して実行します。

```bash
# Gemini API の場合
export GOOGLE_API_KEY="your-api-key"

# レビュー対象の文章を渡して実行
PYTHONPATH=docs/samples/docreview uv run jin run docs/samples/docreview/docreview.jin \
  "$(cat docs/samples/docreview/sample-notice.md)" --trace /tmp/review.jsonl

# 判定結果を取り出す
uv run python docs/samples/docreview/verdict.py /tmp/review.jsonl
```

---

## 自動テスト（契約テスト）

このサンプルの整合性（構文チェック、ビルド、fake 実行、判定ルール、実トレースの読み出し）は、CI および以下の契約テストで常時検証されています。

```bash
uv run pytest tests/contract/test_docs_samples.py
```
