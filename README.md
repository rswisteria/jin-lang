# Jin(陣)

魔法陣型エージェント記述言語。`.jin`（JSON）1 本から Google ADK のエージェントを組み立て、
同じファイルを魔法陣として決定的に描画する。

現在の実装範囲は **Phase 0（仕様書と examples）／ Phase 1（`jin-core` + `jin-cli`）／
Phase 2（`jin-adk`: ADK プロジェクト生成・実行・トレース）**。
全体像と残りの Phase は `jin-requirements.md` と `CLAUDE.md` を参照。

## 使う

```bash
uv sync
uv run jin check examples          # 診断（error があれば exit 1）
uv run jin check --json a.jin      # LSP Diagnostic と 1:1 の JSON
uv run jin fmt --check examples    # 正準形かどうか
uv run jin schema                  # JSON Schema を標準出力へ
uv run jin dump examples/researcher/researcher.jin   # モデル + pointer→range 対応表

# Phase 2
uv run jin build examples/researcher/researcher.jin --out out   # ADK プロジェクトを生成
uv run jin run examples/pipeline/pipeline.jin "書いて" --model fake --trace t.jsonl
```

`jin build` の出力は `adk run out/<root 名>` / `adk web out` にそのまま載る
（`out/.env.example` を `out/.env` にコピーして値を入れる）。**生成コードは編集しない。**
直すのは `.jin` のほうで、`jin build` をやり直す。

### `jin check --resolve` は任意コードを実行する

`--resolve` を付けると、`.jin` の `ref`（`module.path:callable`）が指すモジュールを**実際に import** して
JIN040 を判定する。Python の import は**そのモジュールのトップレベルを実行する**ので、
`--resolve` は `.jin` を書いた相手に、このプロセスの権限で**任意のコードを実行させる**ことになる。

**中身を確認した `.jin` にだけ使うこと。** 受け取ったファイル・自動生成されたファイルには使わない。
`--resolve` を付けなければ import は一切行われない（JIN040 が出ないだけで他の診断は全部出る）。

### `jin run` も任意コードを実行する

`jin run` は `.jin` から生成したコードを一時ディレクトリへ書き出して import する（要件書 §3.4）。
生成コードは `ref` が指すモジュールを import するので、`--resolve` と**同じ危険性**がある。
違いは「`jin run` は実行するためのコマンドなので、それが目的である」ことだけ。
出どころの分からない `.jin` には使わないこと。**`--model fake` はモデル呼び出しを止めるだけで、
`ref` の import は止めない。**

## 構成

```
schemas/jin.schema.json   Pydantic から生成した JSON Schema（正典・コミットする）
docs/spec/                モデル / ADK 対応 / レイアウト / 診断 / オペレーションの仕様
examples/                 researcher.jin と pipeline.jin（正準形）
packages/jin-core/        意味モデル・位置付きパーサ・意味検査・診断・正準形・意味オペレーション
packages/jin-adk/         ADK コンパイラ（build / run / trace / FakeLlm）。ADK の語彙が現れる唯一の場所
packages/jin-cli/         CLI（check / fmt / schema / dump / build / run）
tests/                    spec 突合 / 横断契約 / 診断コードの fixture
```
