# Jin(陣)

魔法陣型エージェント記述言語。`.jin`（JSON）1 本から Google ADK のエージェントを組み立て、
同じファイルを魔法陣として決定的に描画する。

現在の実装範囲は **Phase 0（仕様書と examples）・Phase 1（`jin-core` + `jin-cli`）・
Phase 2（`jin-adk`: build / run / trace / FakeLlm）**。全体像と残りの Phase は `jin-requirements.md` と `CLAUDE.md` を参照。

## 使う

```bash
uv sync
uv run jin check examples          # 診断（error があれば exit 1）
uv run jin check --json a.jin      # LSP Diagnostic と 1:1 の JSON
uv run jin fmt --check examples    # 正準形かどうか
uv run jin schema                  # JSON Schema を標準出力へ
uv run jin dump examples/researcher/researcher.jin   # モデル + pointer→range 対応表
uv run jin build examples/pipeline/pipeline.jin --out /tmp/out   # ADK プロジェクト（/tmp/out/Pipeline/ + .env.example）
uv run jin run examples/pipeline/pipeline.jin "go" --model fake --trace /tmp/t.jsonl   # FakeLlm で実行・トレース（0600）
```

生成物と `adk run` の関係:

- `examples/pipeline` の生成物は `ref` を持たず、`jin run --model fake` での完走を実測している。実モデルでの `adk run /tmp/out/Pipeline` /
  `adk web /tmp/out`（API キーは `/tmp/out/.env`）は human_only で**未実施**（`delivery/20260904-1445-jin/implementation-notes.md` P2-5.4）
- `examples/researcher` の生成物は **`adk run` 単体では動かない**（2 つの理由・要件書 §3.1「そのまま動く」は
  researcher では未達 = HANDOFF Q-JIN-P2-01・人間判断待ち）: `ref` が指す `research.tools` / `research.guards` は
  このリポジトリに実体が無い（テストは `tests/fixtures/stubs/` のスタブを `PYTHONPATH` で渡す）。さらに指示文が
  自分の出力 `{findings}` を参照しているため、初回ターンで ADK が `KeyError`（未設定の state 参照）を出す。
  `jin run` は宣言済みの state を空で初期化してから実行するので通る（`docs/spec/adk-mapping.md` §6）
- トレースの `pointer` は `jin run` が付ける。`adk run` で単体実行しても Jin の pointer は付かない

### `jin check --resolve` は任意コードを実行する

`--resolve` を付けると、`.jin` の `ref`（`module.path:callable`）が指すモジュールを**実際に import** して
JIN040 を判定する。Python の import は**そのモジュールのトップレベルを実行する**ので、
`--resolve` は `.jin` を書いた相手に、このプロセスの権限で**任意のコードを実行させる**ことになる。

**中身を確認した `.jin` にだけ使うこと。** 受け取ったファイル・自動生成されたファイルには使わない。
`--resolve` を付けなければ import は一切行われない（JIN040 が出ないだけで他の診断は全部出る）。

### `jin run` も任意コードを実行する

`jin run` は生成コードを一時ディレクトリに書いて import する。生成コードは `ref` のモジュールを
import するので、`--resolve` と同じく**任意コード実行**である（`--model fake` はモデル呼び出しを
ネットワークに出さないだけ）。`ref` はカレントディレクトリと `PYTHONPATH` から解決する。cwd は**生成コードの import の間だけ**
`sys.path` の末尾に足し、import が終わったら外す（エージェントの実行中は cwd を見ない）。
**import の間は cwd のモジュールも実行されうる**（`ref` 先と、`builtin` が遅延 import する未インストールの名前）。
信頼しないディレクトリを cwd にして `jin run` しないこと。`ref` 先の関数が実行時に遅延 import する名前は cwd から
解決できないので `PYTHONPATH` で渡すこと。`.jin` のファイル名に改行・制御文字・不正な UTF-8 バイトが
含まれる場合は exit 2 で拒む。

## 構成

```
schemas/jin.schema.json   Pydantic から生成した JSON Schema（正典・コミットする）
docs/spec/                モデル / ADK 対応 / レイアウト / 診断 / オペレーションの仕様
examples/                 researcher.jin と pipeline.jin（正準形）
packages/jin-core/        意味モデル・位置付きパーサ・意味検査・診断・正準形・意味オペレーション
packages/jin-adk/         ADK コード生成（Jinja2）/ 書き出し / 実行 / トレース / FakeLlm
packages/jin-cli/         CLI（check / fmt / schema / dump / build / run）
tests/                    spec 突合 / 横断契約 / 診断コードの fixture
```
