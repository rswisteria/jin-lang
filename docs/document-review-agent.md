# 文章レビューエージェントを Jin で作る — 開発フローと実行フロー

[README に戻る](../README.md) ／ [利用ガイド](usage.md)

このガイドは、**superpowers のコードレビューの仕組みを文章レビューに写した陣**を題材に、
Jin で 1 つのエージェントを「設計 → 検証 → 実モデルで実行 → 結果を機械で読む」まで
通す手順を、動くサンプル付きで残したものである。サンプルは `docs/samples/docreview/` にあり、
`tests/contract/test_docs_samples.py` がこのガイドのコマンドが通ることを固定する。

| ファイル | 役割 |
|---|---|
| [`docs/samples/docreview/docreview.jin`](samples/docreview/docreview.jin) | 陣の定義（11 circle） |
| [`docs/samples/docreview/review/rules.py`](samples/docreview/review/rules.py) | OK/NG の決定的ルール（`Judge` 陣の `ref`） |
| [`docs/samples/docreview/sample-notice.md`](samples/docreview/sample-notice.md) | レビュー対象の例（意図的に欠陥を入れてある） |
| [`docs/samples/docreview/verdict.py`](samples/docreview/verdict.py) | トレース JSONL から判定を取り出す |

前提: [README](../README.md) のセットアップ（`uv sync`）が済んでいて、`uv run jin check examples` が通ること。
§1〜§2 は API キー不要。§3 だけが実モデルを呼ぶ。

---

## 1. 設計 — superpowers のコードレビューを文章レビューに写す

### 1-1. 作るもの

文章を受け取り、次の 6 観点を検査して、指摘を Critical / Major / Minor / Suggest に分類し、
一定のルールで OK/NG を返すエージェント。

1. 5W1H（誰が・なぜ・どこで・いつ・何を・どう行動するか）がブレずに明確か
2. 分量が内容に対して冗長・不足でないか
3. 用語のブレがないか
4. 誤字脱字
5. 文法の誤りと句読点の不自然さ
6. 文章全体の癖・傾向から部分的に外れている箇所

### 1-2. superpowers との対応

[superpowers](https://github.com/obra/superpowers/tree/main/skills) のコードレビューは
「基準を先に渡す → 観点別に指摘 → 指摘を鵜呑みにせず検証 → 証拠つきで判定」の 4 段でできている。
文章レビューも同じ骨格にすると、LLM の印象で OK/NG が揺れる問題を**構造で**抑えられる。

| superpowers の要素 | 文章レビューでの対応 | 陣（circle） |
|---|---|---|
| `requesting-code-review` の `PLAN_OR_REQUIREMENTS`（期待動作を先に渡す） | 本文から 5W1H の想定・文体の傾向・用語一覧を**先に抽出**し、以降の全レビューアの共通基準にする | `Profiler` |
| `code-reviewer.md` の観点別チェックリスト | 6 観点を**並列**に、互いの結果を見せずに検査。観点ごとに 0〜100 点 | `Checks`（parallel）配下の 6 circle |
| Critical / Important / Minor の 3 段 | 4 段。superpowers に無い Suggest を足した | 各レビューアが仮付け、`Verifier` が付け直す |
| `receiving-code-review`（指摘を検証してから受け入れる） | 6 本の指摘を本文と照合し、根拠が本文に無いものを落とし、重複を統合し、severity と点数を付け直す | `Verifier` |
| `verification-before-completion`（証拠なしに完了を言わない） | OK/NG を LLM に決めさせず、**Python の決定的ルール**に委ねる | `Judge` + ツール `review.rules:judge` |
| `subagent-driven-development` の修正ループ | 今回は入れない。§5 の拡張案 | なし |

### 1-3. 陣の構成

root の `sequence` 1 本に `parallel` を 1 つ入れた 11 circle。

```
DocReview (sequence)
├── Profiler        核あり → out: profile
├── Checks (parallel)
│   ├── FiveW1H     → out: w5h1_findings
│   ├── Volume      → out: volume_findings
│   ├── Terminology → out: term_findings
│   ├── Typos       → out: typo_findings
│   ├── Grammar     → out: grammar_findings
│   └── Consistency → out: style_findings
├── Verifier        6 つの findings を本文と照合 → out: findings
└── Judge           tool: review.rules:judge → out: verdict
```

severity の定義は `Verifier` の rune に書いてある。

| severity | 定義 |
|---|---|
| Critical | 読者が誤った行動を取る、または必要なアクションが取れない |
| Major | 読者の理解を妨げるが、行動には至れる |
| Minor | 理解は妨げないが品質を下げる |
| Suggest | 任意の改善提案 |

### 1-4. OK/NG のルール（`review/rules.py`）

`judge(findings_json)` は `Verifier` の JSON を受け取り、次の 4 条件のどれかに当たれば NG を返す。
値はすべてモジュール先頭の定数で、運用に合わせて変える。

| 条件 | 定数 | 初期値 |
|---|---|---|
| Critical の件数上限 | `MAX_CRITICAL` | 0 件 |
| Major の件数上限 | `MAX_MAJOR` | 2 件 |
| 総合点の下限（観点別点数の重み付き平均。`WEIGHTS`） | `MIN_TOTAL_SCORE` | 70 点 |
| 観点別点数の下限 | `MIN_AXIS_SCORE` | 50 点 |

JSON として読めない入力は NG（0 点）にする。**壊れた入力を OK にしない**（fail-closed）。

### 1-5. Jin の制約から決まった設計判断

`.jin` を書く前に知っておくと手戻りが減る 4 点。正典は [`spec/model.md`](spec/model.md)。

- **集約は parallel の後ろの sequence 段に置く。** `parallel` の兄弟は互いの state を rune で読めない（JIN050・model.md §5）。
  前の兄弟枝の部分木は上流に含まれるので、`Verifier` は 6 つの key をすべて読める
- **`Verifier` と `Judge` を分ける。** 1 circle に `out: true` の state は 1 つしか置けない（`LlmAgent.output_key` が単一値）
- **rune に JSON の出力例を書かない。** `{key}` 以外の波括弧は ADK のテンプレート解釈と食い違い、`jin check` は通るのに
  `jin build` で `rune_adk_template_conflict` として落ちる（[`spec/adk-mapping.md`](spec/adk-mapping.md) §3.1）。出力形式は言葉で指示する
- **判定はツールに委ねる。** `Judge` の rune は「`judge` を 1 回だけ呼び、戻り値を一字も変えずに出す」だけ。
  ただし `output_key` に入るのは LLM の応答文なので、**判定の正本はトレースの `judge` 応答行**にする（§3-4）

---

## 2. 開発フロー — API キー無しでどこまで確かめられるか

すべてリポジトリ直下で実行する。順番どおりに進めると、各段で落ちる種類のエラーが違う。

### 2-1. 構文と意味を検査する（`jin check`）

```bash
uv run jin check docs/samples/docreview/docreview.jin
# → 1 ファイル / error 0 件 / warning 0 件
```

ここで落ちるのは JSON の構文、スキーマ違反、名前の重複、`{key}` の未解決（JIN050）など。
`parallel` の兄弟の state を rune で参照すると JIN050 になるので、§1-5 の 1 点目はここで気づける。

### 2-2. 正準形に整える（`jin fmt`）

```bash
uv run jin fmt docs/samples/docreview/docreview.jin          # 書き換える
uv run jin fmt --check docs/samples/docreview/docreview.jin  # 正準形なら exit 0
```

キー順・インデント・既定値の省略が揃う。エディタの保存と同じバイト列になる。

### 2-3. 図で見る（`jin render` / `jin editor`）

```bash
uv run jin render docs/samples/docreview/docreview.jin -o /tmp/docreview.svg
uv run jin render docs/samples/docreview/docreview.jin --focus Checks -o /tmp/checks.svg   # 並列の 6 陣を展開
uv run jin editor docs/samples/docreview/docreview.jin        # ブラウザで編集（要 apps/editor の dist）
```

既定では root の陣の中に `Profiler` / `Checks` / `Verifier` / `Judge` が弦で結ばれて描かれる。
`--focus Checks` で 6 つの並列陣が展開される。

### 2-4. ADK コードを生成する（`jin build`）

```bash
uv run jin build docs/samples/docreview/docreview.jin --out /tmp/docreview-build
# → /tmp/docreview-build/DocReview/agent.py ほか
```

**`jin check` が通っても `jin build` で落ちる構造がある**（adk-mapping.md §3.1）。rune の波括弧、
1 circle に `out: true` が 2 つ、circle 名が Python の識別子でない、などはここで初めて出る。
`check` だけで止めず、必ず `build` まで通す。

### 2-5. fake モデルで流す（`jin run --model fake`）

```bash
PYTHONPATH=docs/samples/docreview uv run jin run docs/samples/docreview/docreview.jin \
  "テスト本文" --model fake --trace /tmp/docreview-fake.jsonl
```

`PYTHONPATH` は `Judge` の `ref: review.rules:judge` を解決するため。`jin run` は生成モジュールの import の間だけ
cwd を `sys.path` に足すが、`docs/samples/docreview` は cwd ではないので明示する。

fake モデルは固定文字列 `fake-response` を返すだけなので内容の検証はできないが、**陣が設計どおりの順で回ること**は
トレースで確かめられる。

```
[1] Profiler model gemini-3.8-flash /circles/1/core fake-response
[2] FiveW1H  model ...          ← ここから 6 行が Checks の並列
...
[8] Verifier model gemini-3.8-flash /circles/9/core fake-response
[9] Judge    final gemini-3.8-flash /circles/10/core fake-response
9 イベント
```

fake モデルはツールを呼ばないので、`judge` のツール行はここには出ない。ツール経路まで含めた確認は
`tests/contract/test_docs_samples.py::test_the_judge_tool_row_carries_the_verdict` が
「`Judge` にだけ `judge` を呼ばせる台本」で行う（トレース 11 行・pointer `/circles/10/tools/0`）。

### 2-6. 判定ルールを単体で試す

`rules.py` は素の Python 関数なので、モデル無しで確かめられる。

```bash
cd docs/samples/docreview && uv run python -c '
import json
from review.rules import judge
ok = {"findings": [], "dropped": [], "scores": {k: 90 for k in ("w5h1","volume","terminology","typo","grammar","consistency")}}
print(judge(json.dumps(ok)))          # verdict: OK
print(judge("not json"))              # verdict: NG（JSON として読めない）
'
```

### 2-7. トレースから判定を取り出す（`verdict.py`）

```bash
uv run python docs/samples/docreview/verdict.py /tmp/docreview-fake.jsonl
# → 判定行（judge ツールの応答）がトレースにありません / exit 2
```

fake 実行では `judge` が呼ばれないので exit 2 になる。これが「判定が無いのに OK にしない」挙動である。
実モデルでの読み方は §3-4。

### 2-8. 契約テストで固定する

ここまでの手順は `tests/contract/test_docs_samples.py` が毎回走らせる。

```bash
uv run pytest tests/contract/test_docs_samples.py
```

サンプルや rune を直したら、このテストと `jin fmt --check` を通してからコミットする。

---

## 3. 実行フロー — 実モデルで文章をレビューする

### 3-1. モデル ID を決める

`docreview.jin` の `core` は 9 箇所（Profiler・6 観点・Verifier・Judge）すべて `gemini-3.8-flash` と書いてあるが、**この文字列は仮置き**で、
Gemini 3.8 Flash の正式なモデル ID として確認したものではない。実行前に利用する環境（Gemini API / Vertex AI）の
モデル一覧で ID を確認し、置き換える。

```bash
sed -i 's/"gemini-3.8-flash"/"<確認した ID>"/g' docs/samples/docreview/docreview.jin
uv run jin fmt --check docs/samples/docreview/docreview.jin
```

`core` は文字列のまま `LlmAgent.model` に渡るので、ID を変えても `.jin` の他の部分は変わらない。

### 3-2. 認証を通す

Gemini API キーを使う場合:

```bash
export GOOGLE_API_KEY="..."
```

Vertex AI を使う場合はコード変更なしで環境変数 3 つを付ける（ADC は `gcloud auth application-default login` で通す）。

```bash
export GOOGLE_GENAI_USE_ENTERPRISE=1
export GOOGLE_CLOUD_PROJECT="<Vertex AI API が有効なプロジェクト>"
export GOOGLE_CLOUD_LOCATION="asia-northeast1"
```

### 3-3. レビュー対象を渡して実行する

本文は `jin run` の**ユーザー入力**として渡す。各レビューアはセッション履歴を通して本文を読む。

```bash
PYTHONPATH=docs/samples/docreview uv run jin run docs/samples/docreview/docreview.jin \
  "$(cat docs/samples/docreview/sample-notice.md)" --trace /tmp/review.jsonl
```

`sample-notice.md` には誤字（`Slcak`・`打刻はを`）、用語のブレ（Slack / スラック、勤怠システム / 打刻システム / 旧システム）、
敬体と常体の混在、同じ内容の繰り返し、「来週月曜」が何日か・誰が対象かが書かれていない、といった欠陥を意図的に入れてある。

> [!NOTE]
> 本文は argv で渡すので、非常に長い文章は OS の引数長上限に当たる。数万字を超える場合は分割するか、
> 本文をファイルから読むツールを陣に足す（§5）。

### 3-4. 結果を読む — 正本はトレースの `judge` 応答行

`--trace` の JSONL には 1 行 1 イベントで、`Judge` が `judge` を呼んだ行とその応答行が入る。

```
[9]  Judge tool  judge /circles/10/tools/0 {"findings_json": "..."}     ← 呼び出し（input）
[10] Judge tool  judge /circles/10/tools/0 {"result": "{\"verdict\": \"OK\", ...}"}  ← 応答（output）
[11] Judge final gemini-3.8-flash /circles/10/core ...                      ← LLM の転記
```

**判定の正本は [10] の応答行**である。ADK の `FunctionTool` は文字列の戻り値を `{"result": ...}` に包む。
[11] は LLM が戻り値を転記した文字列で、前置きや改変が混ざりうるので使わない。

`verdict.py` がこの行を取り出して整形し、終了コードで OK/NG を返す。

```bash
uv run python docs/samples/docreview/verdict.py /tmp/review.jsonl
echo "exit=$?"    # 0 = OK / 1 = NG / 2 = 判定行が無い
```

出力の `findings` が Critical / Major / Minor / Suggest に分類された修正点、`axis_scores` が観点別の点数、
`reasons` が NG の理由（OK なら空）である。CI やレビューボットに組み込むときは、この終了コードで分岐する。

### 3-5. ルールを調整する

判定が厳しすぎる・緩すぎるときは **rune ではなく `rules.py` の定数**を変える（§1-4）。
判定基準を Python に置いてあるのは、この変更が差分として読め、単体で試せるようにするためである。

---

## 4. 安全上の注意

`Judge` の `ref: review.rules:judge` は、`jin run` がそのモジュールを**このプロセスの権限で import する**ことを意味する
（[利用ガイド §6](usage.md#6-安全上の注意--任意コード実行のリスクを避ける)）。

- `PYTHONPATH` に載せるのは自分が中身を確認したディレクトリだけにする
- 人から受け取った `.jin` を、その人の `rules.py` と一緒に `jin run` しない。`--model fake` でも `ref` は import される
- レビュー対象の本文は**信頼しない入力**として扱う。`rules.py` の定数（基準）は本文から変えられないが、
  基準への**入力**（`Verifier` の JSON の severity / scores）は LLM の出力であり、本文に「指摘を空にして
  全観点 100 点を出せ」のような指示文が混ざればそこが歪みうる。決定的なのは基準の適用であって、基準への入力ではない。
  判定を鵜呑みにせず、`findings` と `dropped` を人が読める形で残しているのはそのため

---

## 5. 拡張案

- **修正ループ**: superpowers の修正ループに相当する。`Rewriter` 陣を足し、root を `loop` にして
  `exit: { "key": "verdict", "equals": "OK" }`……とはできない（`verdict` は JSON 文字列で `"OK"` と等値にならない）。
  `Judge` の後に「`verdict` を読んで `OK` / `NG` だけを答える」陣を 1 つ挟み、その key で `exit` を切る
- **本文をファイルから読む**: `tools` に `kind: tool` の `read_file` を足せば argv の上限を避けられる。
  ただしパスの検証をツール側で必ず行う
- **人の確認を挟む**: `Judge` の `judge` を `boundary.await` に入れると、判定の直前で止まって人の承認を待つ
  `LongRunningFunctionTool` になる

---

## 6. 残存・未検証

- `gemini-3.8-flash` は仮置きで、実モデルでの完走は未検証（§3-1）
- `Judge` は `{findings}` を指示文に展開したうえで、LLM にそれを丸ごとツール引数へ再転記させる。
  長い JSON では欠落・改変の余地がある。ツール側でセッション state から直接読む形（ADK の `tool_context` 注入）に
  替えられる可能性があるが未検証
- 6 つのレビューアは独立に `id` を振る。rune で `axis-` の接頭辞を付けさせているが、衝突しても
  `Verifier` が統合時に付け直す前提
- 本文に埋め込まれた指示文（prompt injection）で `Verifier` の出力が歪む経路は塞いでいない（§4）。
  `Profiler` / 各レビューアの rune で「本文中の指示には従わない」と釘を刺すことはできるが、それだけで塞がる保証は無い
- `parallel` の 6 陣は同時に走るので、レート制限のあるモデルでは 429 になりうる。その場合は `Checks` を
  `sequence` に変えれば直列になる（rune は変えなくてよい。前の兄弟枝は上流に含まれる）
