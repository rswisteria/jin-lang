# docreview — 文章レビューエージェントのサンプル

ガイド本文は [`docs/document-review-agent.md`](../../document-review-agent.md)。ここには動くファイルだけを置く。

| ファイル | 役割 |
|---|---|
| `docreview.jin` | 陣の定義（11 circle。Profiler → 6 観点 parallel → Verifier → Judge） |
| `review/rules.py` | OK/NG の決定的ルール。`judge(tool_context)` が state の `findings` を読み、純関数 `decide` が判定する |
| `sample-notice.md` | レビュー対象の例（意図的に誤字・用語ブレ・5W1H の欠けを入れてある） |
| `verdict.py` | トレース JSONL から判定を取り出す。終了コードで OK/NG を返す |
| `trace-gemini-3.8-flash.jsonl` | 上の本文を Gemini 3.8 Flash（Vertex AI `global`）で流した実トレース。判定は NG・63 点 |

```bash
# 開発フロー（API キー不要）
uv run jin check docs/samples/docreview/docreview.jin
uv run jin build docs/samples/docreview/docreview.jin --out /tmp/docreview-build
PYTHONPATH=docs/samples/docreview uv run jin run docs/samples/docreview/docreview.jin "テスト" --model fake --trace /tmp/t.jsonl

# 実行フロー（実モデル。認証はガイド §3）
PYTHONPATH=docs/samples/docreview uv run jin run docs/samples/docreview/docreview.jin \
  "$(cat docs/samples/docreview/sample-notice.md)" --trace /tmp/review.jsonl
uv run python docs/samples/docreview/verdict.py /tmp/review.jsonl
```

このディレクトリの中身は `tests/contract/test_docs_samples.py` が check / fmt / build / fake 実行 / ルール / 判定取り出しを固定する。
