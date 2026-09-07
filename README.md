# Jin(陣)

魔法陣型エージェント記述言語。`.jin`（JSON）1 本から Google ADK のエージェントを組み立て、
同じファイルを魔法陣として決定的に描画する。

現在の実装範囲は **Phase 0（仕様書と examples）・Phase 1（`jin-core` + `jin-cli`）・
Phase 2（`jin-adk`: build / run / trace / FakeLlm）・Phase 3（`jin-render`: render / focus / trace overlay）・
Phase 4（`jin-lsp`: stdio + WebSocket + Claude Code プラグイン）**。
残りは Phase 5–6（`apps/editor`）。全体像は `jin-requirements.md` と `CLAUDE.md` を参照。

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
uv run jin render examples/researcher/researcher.jin -o /tmp/r.svg    # 魔法陣 SVG（-o 無しは標準出力）
uv run jin lsp                     # LSP サーバ（stdio）
uv run jin editor examples/researcher/researcher.jin   # 視覚エディタ（要 apps/editor の pnpm build）
```

### `jin render` — 魔法陣 SVG

```bash
uv run jin render <file>                       # 標準出力へ
uv run jin render <file> -o out.svg            # ファイルへ（既存は --force なしでは上書きしない）
uv run jin render <file> --focus Summarizer    # 展開する circle を切り替える（既定は root）
uv run jin render <file> --trace t.jsonl --upto 5   # jin run --trace の出力を重ねる
```

- **同じ `.jin` からは常にバイト単位で同じ SVG が出る**（NFR-DET-001）。座標は丸め関数 1 本
  （3 桁固定小数）を通り、装飾は `instruction.rune` の SHA-256 から決まる。乱数・時刻・
  辞書順序に依存しないので、`PYTHONHASHSEED` を変えても出力は変わらない
- 描画されたすべての要素が `data-jin`（JSON Pointer）と `data-jin-kind`（9 種）を持つ。
  エディタはこの属性でヒットテストする（`docs/spec/layout.md` §3）
- `--trace` は `jin run --trace` が書いた JSONL を読み、`--upto` までに発火した要素を朱色で強調し、
  境界環の外側にイベント数ぶんの点を並べる。`--upto` を増やすと強調は**増えるだけ**（減らない）
- 入れ子の展開は**深さ 1 まで**。それ以下と、解決できない参照は点になる（`docs/spec/layout.md` §2 / §5）
- `-o` の親ディレクトリは**作らない**（無ければ拒む）。`jin build --out` は木を作るが、`jin render -o` は 1 ファイルを書くだけなので、打ち間違えたパスの下にディレクトリを生やさない
- `jin check` に error があるファイルは描かない（`jin build` / `jin run` と同じ規律）
- **`jin render` は任意コードを実行しない。** `ref` を import せず、入力は意味モデルとトレース JSONL だけである

生成物と `adk run` の関係:

- `examples/pipeline` の生成物は `ref` を持たず、`jin run --model fake` での完走を実測している。実モデルでの `adk run /tmp/out/Pipeline` /
  `adk web /tmp/out`（API キーは `/tmp/out/.env`）は human_only で**未実施**（`delivery/20260904-1445-jin/implementation-notes.md` P2-5.4）
- `examples/researcher` の生成物は **`adk run` 単体では動かない**（2 つの理由・要件書 §3.1「そのまま動く」は
  researcher では未達 = HANDOFF Q-JIN-P2-01・人間判断待ち）: `ref` が指す `research.tools` / `research.guards` は
  このリポジトリに実体が無い（テストは `tests/fixtures/stubs/` のスタブを `PYTHONPATH` で渡す）。さらに指示文が
  自分の出力 `{findings}` を参照しているため、初回ターンで ADK が `KeyError`（未設定の state 参照）を出す。
  `jin run` は宣言済みの state を空で初期化してから実行するので通る（`docs/spec/adk-mapping.md` §6）
- トレースの `pointer` は `jin run` が付ける。`adk run` で単体実行しても Jin の pointer は付かない

### `jin lsp` — 言語サーバ

```bash
uv run jin lsp                              # stdio（Claude Code / VS Code 向け・既定）
uv run jin lsp --ws 8765                    # WebSocket（ブラウザのエディタ向け）
uv run jin lsp --ws 8765 --root ./workspace # jin/open と jin/save を ./workspace 配下の .jin に限って許す
```

**stdio と WebSocket でサーバ実装は同一**である（要件書 §6.1）。提供する機能:

| 種類 | 内容 |
|---|---|
| 標準 | diagnostics / completion / definition / references / hover / documentSymbol / formatting / rename / codeAction |
| 独自 | `jin/model` / `jin/renderSvg` / `jin/applyOps` / `jin/ops`（要件書 §6.3） |
| ws 専用 | `jin/open` / `jin/save`（ADR-011。ブラウザにはファイルシステムが無いため） |

- **formatting の出力は `jin fmt` と、`jin/renderSvg` の出力は `jin render` とバイト一致する。**
  どちらも `jin_core` / `jin_render` の同じ関数を呼ぶだけで、LSP 側は位置変換とプロトコル露出しか持たない
- 診断は **JSON 構文 → スキーマ → 意味**の順に段階的に出る。前段が通らなければ後段は出ない
- **JSON 構文エラー中も hover と `jin/renderSvg` は直前の正常なモデルで答える**（応答の `stale` が真になる）
- 打鍵は 150 ms デバウンスして古い要求をキャンセルする。ファイルを開いた瞬間の診断は待たない

### `jin lsp --ws` はローカルに口を開ける

WebSocket にはブラウザの same-origin 制限が無い。**開いている任意のページが `ws://127.0.0.1:PORT` へ
繋いでリクエストを打てる。** ファイルを読み書きする `jin/open` / `jin/save` はそのため 4 段で閉じてある:

1. **既定で無効。** `--root <ディレクトリ>` を明示したときだけ有効になる
2. **起動トークン。** 起動時に生成して stderr へ出す。リクエストの `token` で毎回示す
3. **場所と種類。** `--root` の実体の配下にある `.jin` だけ
4. **symlink 拒否。** 書き先そのものが symlink なら拒む

残存: Origin ヘッダは見ていない（pygls が `start_ws` でサーバ生成オプションを露出しないため）。
詳細と根拠は `docs/spec/ops.md` §5.1。

**hover は `ref` の docstring を出さない。** 出すには `ref` のモジュールを import する必要があり、
hover のたびに任意コード実行になるためである（要件書 §6.2 からの意図的な逸脱）。

### `jin editor` — 視覚エディタ（編集モード）

```bash
cd apps/editor && pnpm install && pnpm build   # 初回だけ。jin editor が配る dist を作る
uv run jin editor path/to/a.jin                # ブラウザが開く
uv run jin editor path/to/a.jin --no-browser   # URL を stderr に出すだけ
```

魔法陣をクリックして要素を選び、プロパティパネルで編集する。**エディタは 1 本の線も描かない** —
SVG は `jin/renderSvg` から受け取り、`data-jin` でヒットテストするだけである。
**ファイルが唯一の状態**で、エディタは独自のモデルを持たない: 編集はすべて `jin/applyOps` を
往復し、保存は正準形（`jin fmt` の出力とバイト一致）を書く。
プロパティパネルの欄は `schemas/jin.schema.json` から生成する（手書きのフォーム定義を持たない）。

構文エラー中は**「直前の正常な版を表示しています」と画面に明示する**（黙って古い図を出さない）。
デバッグモード（トレースリプレイ）は Phase 6。

### `jin editor` も `jin lsp --ws --root` と同じ口を開ける

`jin editor` は `--root` を書かせずに ws の待ち受けを開く。root は**対象ファイルの親
ディレクトリだけ**で、防御は下の 4 段と同じ。起動トークンは URL の**フラグメント**
（`#token=`）で渡す — フラグメントは HTTP 要求にも `Referer` にも載らないので、
静的配信のアクセスログにも出ない（残存: ブラウザの履歴には残り、同じページの JS からは読める）。

**信頼しないディレクトリの `.jin` を `jin editor` で開かないこと。**

### Claude Code プラグイン

`plugins/claude-code/jin/` を入れると `.jin` の診断・定義ジャンプが Claude Code で効く（要件書 §8）。

```bash
uv tool install jin-cli   # jin コマンドが PATH に要る
```

`skills/jin-lang/reference/` は `docs/spec/model.md` と `schemas/jin.schema.json` の**コピー**で、
`uv run python scripts/sync_plugin_reference.py` が同期する（手で編集しない）。
CI が `--check` でずれを落とし、`claude plugin validate --strict` も走らせる。

### `jin check --resolve` は任意コードを実行する

`--resolve` を付けると、`.jin` の `ref`（`module.path:callable`）が指すモジュールを**実際に import** して
JIN040 を判定する。Python の import は**そのモジュールのトップレベルを実行する**ので、
`--resolve` は `.jin` を書いた相手に、このプロセスの権限で**任意のコードを実行させる**ことになる。

**中身を確認した `.jin` にだけ使うこと。** 受け取ったファイル・自動生成されたファイルには使わない。
`--resolve` を付けなければ import は一切行われない（JIN040 が出ないだけで他の診断は全部出る）。

import は `ref` 1 件ごとに**子プロセス**（`python -P -m jin_cli.resolver <ref>`）で行い、**30 秒**で
タイムアウトする（ADR-018）。1 ファイル目の `ref` が診断器を差し替えて 2 ファイル目の診断を消す、
といったファイル間の汚染は親プロセスに及ばず、ハングは JIN040 として報告される。ただし**子は同じ権限で
走る**ので、任意コード実行そのものが無くなるわけではない。`ref` は `PYTHONPATH` から解決する
（cwd は見ない）。

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
packages/jin-render/      決定的レイアウト / SVG 文字列生成 / 装飾 / trace overlay
packages/jin-lsp/         LSP サーバ（stdio + WebSocket）/ 標準機能 / 独自リクエスト
packages/jin-cli/         CLI（check / fmt / schema / dump / build / run / render / lsp / editor）
apps/editor/              視覚エディタ（Vite + React + TS）。Python パッケージを import しない
plugins/claude-code/jin/  Claude Code プラグイン（.lsp.json / skills / hooks）
tests/                    spec 突合 / 横断契約 / 診断コードの fixture
```
