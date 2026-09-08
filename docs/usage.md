# Jin 詳細ガイド

[README に戻る](../README.md)

## このガイドについて

README のセットアップ（`uv sync` とエディタのビルド）を終えた人が、サンプルを動かし、自分の陣を書き、
プロダクトへ組み込むまでを扱います。読者に想定しているのは、JSON と Python のコマンドラインに
抵抗がない Web エンジニアです。Google ADK の知識は前提にしません。

**1〜6 章は最初に順に読んでください。** 7 章以降は、必要になったときに引く参照部です。
コマンドとパスは、特記がない限りリポジトリのルートを基準にしています。

| | 章 | 読むタイミング |
|---|---|---|
| 通読 | 1. サンプルを動かす | 最初 |
| 通読 | 2. 自分の陣を書く | 最初 |
| 通読 | 3. 魔法陣の語彙 | 最初 |
| 通読 | 4. 実行を追いかける | 最初 |
| 通読 | 5. プロダクトへ組み込む | 最初 |
| 通読 | 6. 安全上の注意 | **最初（読み飛ばさない）** |
| 参照 | 7. コマンド逆引き | 手が止まったとき |
| 参照 | 8. エディタと言語サーバの詳細 | 開発環境を整えるとき |
| 参照 | 9. サンプル 3 本 | 書き方に迷ったとき |
| 参照 | 10. 用語集 / 11. リポジトリの構成 / 12. さらに詳しく | 随時 |

---

## 1. サンプルを動かす — API キーなしで魔法陣が出る

まずは動くものを見ます。ここで使う 3 つのコマンドは、どれもモデルを呼ばないので API キーが要りません。

### 1-1. 魔法陣を SVG に描く

```bash
uv run jin render examples/pipeline/pipeline.jin -o /tmp/pipeline.svg
```

`.jin` を読んで SVG を 1 枚書き出します。ブラウザで開くと、陣（同心円）が並んだ図が出ます。
`-o` を省くと標準出力へ流れます。

同じ `.jin` からは、いつ・どの環境で実行しても**バイト単位で同じ SVG** が出ます。
乱数も時刻も使わないので、生成した SVG をリポジトリに置いて差分をレビューできます。

### 1-2. ブラウザで開いて触る

```bash
uv run jin editor examples/pipeline/pipeline.jin
```

ブラウザが開き、魔法陣が表示されます。要素をクリックして選ぶと右のプロパティパネルに値が出て、
編集して「保存」を押すと `.jin` に書き戻ります。終了は `Ctrl+C` です。

初回は `apps/editor` のビルドが要ります（README の手順）。ビルドしていないとエディタは起動しません。
ブラウザが自動で開かない場合は `--no-browser` を付け、ターミナルに出た URL を自分で開いてください。

### 1-3. エージェントとして実行する

```bash
uv run jin run examples/pipeline/pipeline.jin "go" --model fake
```

`--model fake` は、モデル呼び出しを固定応答（`fake-response`）に差し替えるオプションです。
ネットワークにも API キーにも触れずに、陣のつながり方だけを確かめられます。
上のコマンドは 11 個のイベントを出して終わります。

> **`jin run` は `.jin` に書かれた Python モジュールを import します。**
> import はそのモジュールを実行することなので、中身を確認していない `.jin` には使わないでください。
> `--model fake` でもこれは変わりません。詳しくは [6 章](#6-安全上の注意--任意コードを実行するコマンドがある)。

---

## 2. 自分の陣を書く — `jin check` が通れば動く

`.jin` は JSON です。エディタで組み立てても、テキストエディタで直接書いても構いません。
ここではいちばん小さい陣を手で書いて、動くまでの一巡を確認します。

### 2-1. 1 つの陣を書く

`hello.jin` として保存します。

```json
{
  "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
  "version": 1,
  "root": "Greeter",
  "circles": [
    {
      "name": "Greeter",
      "core": "gemini-2.5-flash",
      "description": "あいさつを返す陣",
      "instruction": { "rune": "利用者にあいさつを返す。" },
      "state": [{ "name": "greeting", "type": "string", "out": true }]
    }
  ]
}
```

`circles` が陣の配列、`root` がエントリポイントの陣の名前です。`core` にモデル名を書くと
その陣は LLM エージェントになり、`instruction.rune` がそのままシステム指示になります。

### 2-2. 診断で直す

```bash
uv run jin check hello.jin
```

`.jin` を JSON 構文 → スキーマ → 意味の順に検査します。error が 1 件でもあれば exit 1 なので、
CI にそのまま置けます。指摘は行と列と診断コードつきで出ます。

```
hello.jin:4:11: error JIN060: root が指す circle 'Greetr' は定義されていません
  hint: 近い名前: Greeter
  pointer: /root
```

`--json` を付けると、エディタや LSP が受け取るのと同じ形の JSON で出ます。

### 2-3. 正準形に整える

```bash
uv run jin fmt hello.jin
```

キーの並び順とインデントを正準形（このプロジェクトで唯一正しい書式）に揃えます。
`--check` を付けると書き換えずに差分の有無だけを見て、ずれていれば exit 1 になります。
エディタの「保存」も同じ正準形を書くので、手書きとエディタが交互でも差分が暴れません。

### 2-4. 動かす

```bash
uv run jin run hello.jin "こんにちは" --model fake
```

1 イベント出て終われば通っています。実際のモデルで動かすときは `--model` を外し、
`core` に書いたモデルの API キーを環境変数で渡してください。

---

## 3. 魔法陣の語彙 — JSON のキーと図と ADK は 1 対 1 で対応する

Jin の用語（陣・核・紋…）は飾りではなく、JSON のキーと ADK のクラスに機械的に対応しています。
図の中で見えているものが、そのまま JSON のどこで、実行時に何になるかは次の表で引けます。

| JSON のキー | 図に出るもの | 意味 | ADK 対応 |
|---|---|---|---|
| `circles[]` | 陣（同心円） | エージェント 1 個、またはその入れ物 | `LlmAgent` / workflow agent |
| `core` | 核（中心） | 使うモデル | `LlmAgent.model` |
| `instruction.rune` | 指示環の文字列 | 指示テキスト | `LlmAgent.instruction` |
| `tools[]` | 道具環の紋 | ツール（`tool` / `builtin` / `summon`） | `FunctionTool` / 組み込み / `AgentTool` |
| `delegate[]` | 境界環内側の小円と破線 | 他の陣への委譲 | `LlmAgent.sub_agents` |
| `state[]` | 記憶環の四角 | セッション状態の宣言 | `session.state` / `output_key` |
| `flow.kind = sequence` | 開いた弦列 | 順番に実行 | `SequentialAgent` |
| `flow.kind = parallel` | 弦なしの対称配置 | 並列に実行 | `ParallelAgent` |
| `flow.kind = loop` | 閉じた多角形 | 繰り返す | `LoopAgent` |
| `boundary.guards[]` | 境界環の刻印 | 前後に挟むコールバック | `before_/after_*_callback` |
| `boundary.await[]` | 境界環の欠け | 人の介入を待つ点 | `LongRunningFunctionTool` |
| `root` | 最外の陣 | エントリポイント | `root_agent` |

陣は 2 種類あります。`core` を持つ陣（**核あり**）は LLM エージェントで、`flow` だけを持つ陣（**核なし**）は
他の陣を順次・並列・繰り返しで束ねる制御構造です。両方持つ、あるいは両方持たないのは診断エラーです。

キーの全一覧と細かい規則は [`docs/spec/model.md`](spec/model.md)、ADK 側の引数まで含む対応は
[`docs/spec/adk-mapping.md`](spec/adk-mapping.md) にあります。
`uv run jin schema` で JSON Schema を取り出せば、手元のエディタで補完も効きます。

---

## 4. 実行を追いかける — トレースを図に重ねる

どの陣がどの順で動いたかは、実行の記録（トレース）を魔法陣に重ねて確認します。

### 4-1. トレースを取る

```bash
uv run jin run examples/pipeline/pipeline.jin "go" --model fake --trace /tmp/t.jsonl
```

`--trace` を付けると、1 イベント 1 行の JSONL が書かれます（パーミッション 0600）。
各行には発火した要素の JSON Pointer が入っていて、これが図と結びつく鍵になります。

### 4-2. エディタで再生する

`jin editor` を開き、ツールバーの「デバッグ（トレースリプレイ）」に切り替えます。
できることは 2 つです。

- **その場で走らせる。** 「実行（最初の利用者メッセージ）」にメッセージを入れて「fake モデルで実行」を押すと、
  イベントが流れてきます。走るのは**ディスク上のファイル**なので、編集した内容を反映するには
  先に「保存」を押してください（実行が自動で保存することはありません）
- **記録したファイルを読む。** 「トレース（`jin run --trace` の JSONL）」で手元の JSONL を選びます

どちらの場合も、タイムラインのスクラバを動かすと、その位置までに発火した要素が図の上で朱色に光ります。
イベントを選べば入出力がそのまま出ます。要素を選んで絞り込めば、その紋で発火した行だけを追えます。
編集モードとは同じ図・同じ選択を共有していて、編集してもトレースは消えません。

### 4-3. `--model fake` で光らないもの

`FakeLlm` は固定文字列を返すだけで関数呼び出しを行いません。そのため**核と `flow.exit` しか光りません**。
紋（ツール呼び出し）・護符・保留・委譲が発火する様子は、実際のモデルでないと確認できません。
逆に言えば、陣の並びと制御構造の検証は API キーなしで最後まで通せます。

CLI だけで重ねることもできます。

```bash
uv run jin render examples/pipeline/pipeline.jin --trace /tmp/t.jsonl --upto 5 -o /tmp/at5.svg
```

`--upto` を増やすと光る要素は増えるだけで、減ることはありません。

---

## 5. プロダクトへ組み込む — `jin build` が ADK プロジェクトを書き出す

ここまでは `jin run` で動かしてきましたが、実際のプロダクトに載せるときは
Python のプロジェクトとして書き出し、ADK の標準的な起動方法（`adk run` / `adk web`）に乗せます。

```bash
uv run jin build examples/pipeline/pipeline.jin --out /tmp/out
```

`<out>/<root の陣名>/agent.py` と `__init__.py`、それに `<out>/.env.example` が出ます。
`.env.example` には ADK が読む環境変数の名前（Gemini API なら `GOOGLE_API_KEY` と
`GOOGLE_GENAI_USE_ENTERPRISE`、Vertex AI なら `GOOGLE_CLOUD_PROJECT` 系）が書かれているので、
これを `.env` にコピーして値を入れれば `adk run <out>/<陣名>` や `adk web <out>` が使えます。

**生成コードは編集しないでください。** `.jin` を直して再生成するのが正しい直し方です。

つまずきやすい点を 2 つ。

- **`ref` を持つ `.jin` の生成物は、`adk run` 単体では動かないことがあります。**
  `examples/researcher` がそうで、理由は 2 つあります。`ref` が指す `research.tools` /
  `research.guards` はこのリポジトリに実体がないこと（テストは `tests/fixtures/stubs/` の
  スタブを `PYTHONPATH` で渡しています）。もう 1 つは、指示文が自分の出力 `{findings}` を
  参照しているため、初回ターンで ADK が未設定の state 参照として `KeyError` を出すことです。
  `jin run` は宣言済みの state を空で初期化してから実行するので通ります
- **トレースの JSON Pointer を付けるのは `jin run` です。** 生成物を `adk run` で単体実行しても、
  図と結びつく pointer は付きません

---

## 6. 安全上の注意 — 任意コードを実行するコマンドがある

Jin のいくつかのコマンドは、`.jin` に書かれた `ref`（`module.path:callable`）のモジュールを
**実際に import します**。Python の import はそのモジュールのトップレベルを実行するので、これは
`.jin` を書いた相手に、あなたの権限で任意のコードを実行させることと同じです。

**原則: 中身を自分で確認した `.jin` にだけ使う。** 人から受け取ったファイル、CI が自動取得したファイル、
LLM が生成したファイルには使わないでください。

| コマンド | 何が起きるか | 守ること |
|---|---|---|
| `jin check --resolve` | `ref` のモジュールを import して JIN040 を判定する | `--resolve` を付けなければ import は一切起きない。他の診断は全部出る |
| `jin run` | 生成コードを一時ディレクトリに書いて import し、その生成コードが `ref` を import する | `--model fake` でも import は起きる。信頼しないディレクトリを作業ディレクトリにして実行しない |
| `jin lsp --ws PORT` | ローカルに WebSocket を開く。同時に開いている任意の Web ページから接続できる | ファイル読み書き（`jin/open` / `jin/save`）は `--root` を明示したときだけ有効になる |
| `jin editor <file>` | 上の ws に加えて、ブラウザから実行を起こす口（`POST /run`）も開く | 信頼しないディレクトリの `.jin` を開かない |

### それぞれの防御と、残っているリスク

`jin check --resolve` の import は `ref` 1 件ごとに子プロセスで行い、30 秒でタイムアウトします。
1 つ目のファイルの `ref` が診断器を差し替えて 2 つ目の診断を消す、といったファイル間の汚染は
親プロセスに及びません。ハングもタイムアウトも JIN040 として報告されます。ただし
**子プロセスはあなたと同じ権限で走る**ので、任意コード実行そのものが消えるわけではありません。

`jin run` は、作業ディレクトリを `sys.path` に足すのを**生成コードの import の間だけ**に限り、
終わったら必ず外します。エージェントの実行中は作業ディレクトリを見ません。それでも import の窓の間は、
作業ディレクトリのモジュールが実行されうる点は残ります。`ref` 先の関数が実行時に遅延 import する名前は
作業ディレクトリからは解決できないので、`PYTHONPATH` で渡してください。

`jin lsp --ws` の `jin/open` / `jin/save` は 4 段で閉じてあります。既定で無効（`--root` が要る）、
起動トークンの一致、`--root` 配下の `.jin` に限定、書き先が symlink なら拒否。
残っているのは Origin ヘッダを見ていない点です。

`jin editor` は `--root` を書かせずに同じ ws を開きます（範囲は対象ファイルの親ディレクトリだけ）。
起動トークンは URL のフラグメント（`#token=`）で渡すので、HTTP 要求にも `Referer` にも載らず、
静的配信のアクセスログにも出ません（ブラウザの履歴には残ります）。実行の口は Origin 検査・
カスタムヘッダ `X-Jin-Token` の一致・対象ファイルの固定・同時 1 本で閉じています。
それでも**トークンを握った攻撃者は、悪意ある `ref` の書き込みから実行までを自力で完結できます**。

根拠と設計の詳細は [`docs/spec/ops.md`](spec/ops.md) §5.1 / §5.2 にあります。

---

## 7. コマンド逆引き

| したいこと | コマンド |
|---|---|
| 書いた `.jin` が正しいか見たい | `uv run jin check <file>` |
| 診断を機械で読みたい | `uv run jin check --json <file>` |
| `ref` の実在まで確かめたい（**任意コード実行**） | `uv run jin check --resolve <file>` |
| 書式を揃えたい | `uv run jin fmt <file>` |
| CI で書式のずれを落としたい | `uv run jin fmt --check <dir>` |
| JSON Schema が欲しい | `uv run jin schema` |
| パーサが読んだ中身を見たい | `uv run jin dump <file>` |
| 魔法陣を画像にしたい | `uv run jin render <file> -o out.svg` |
| 別の陣を展開して描きたい | `uv run jin render <file> --focus <陣名>` |
| 動かしてみたい（モデルなし） | `uv run jin run <file> "<最初のメッセージ>" --model fake` |
| 実行の記録を残したい | `uv run jin run <file> "<msg>" --trace t.jsonl` |
| ADK プロジェクトを書き出したい | `uv run jin build <file> --out <dir>` |
| ブラウザで編集したい | `uv run jin editor <file>` |
| 言語サーバを起動したい | `uv run jin lsp` |

`check` と `fmt` はディレクトリも受け取ります（`uv run jin check examples`）。
ディレクトリを渡したときの走査は symlink を対象にしません。名指しで渡したファイルは symlink でも読みます。
各コマンドのオプション全体は `uv run jin <コマンド> --help` で出ます。

### `jin render` の細かい挙動

- 入れ子の陣の展開は**深さ 1 まで**。それより深いものと、解決できない参照は点になります
- `-o` の親ディレクトリは**作りません**。存在しないパスを渡すと拒みます（打ち間違いでディレクトリを生やさないため）
- `-o` の先に既存ファイルがあれば `--force` なしでは上書きしません
- `jin check` に error が出るファイルは描きません
- `ref` を import しません。入力は `.jin` とトレース JSONL だけです

---

## 8. エディタと言語サーバの詳細

1 章と 4 章で使ったエディタが裏で何をしているかを説明します。
自分のエディタに Jin を組み込みたい場合も、ここが入口になります。

### 8-1. エディタが薄い理由

エディタは**1 本の線も描きません**。SVG は言語サーバの `jin/renderSvg` から受け取り、要素に付いている
`data-jin` 属性（JSON Pointer）でクリック位置を判定するだけです。プロパティパネルの入力欄も
`schemas/jin.schema.json` から生成していて、欄の名前はどこにも手書きされていません。

エディタは独自のモデルを持ちません。**ファイルが唯一の状態で**、編集はすべてサーバへ往復します。
undo / redo もサーバが返した逆操作を積んでいるだけです。だから手で `.jin` を編集しても食い違いません。

構文エラーの間は、図を消さずに**「直前の正常な版を表示しています」と画面に明示します**。
黙って古い図を出すことはしません。

### 8-2. `jin lsp` が提供するもの

```bash
uv run jin lsp                              # stdio（Claude Code / VS Code 向け・既定）
uv run jin lsp --ws 8765                    # WebSocket（ブラウザのエディタ向け）
uv run jin lsp --ws 8765 --root ./workspace # ファイル読み書きを ./workspace 配下に限って許す
```

stdio と WebSocket でサーバの実装は同一です。

| 種類 | 内容 |
|---|---|
| 標準 | diagnostics / completion / definition / references / hover / documentSymbol / formatting / rename / codeAction |
| 独自 | `jin/model` / `jin/renderSvg` / `jin/applyOps` / `jin/ops` |
| ws 専用 | `jin/open` / `jin/save`（ブラウザにはファイルシステムがないため） |

- formatting の出力は `jin fmt` と、`jin/renderSvg` の出力は `jin render` と**バイト一致します**。
  どちらも同じ関数を呼んでいて、LSP 側は位置の変換とプロトコルの露出しか持ちません
- 診断は JSON 構文 → スキーマ → 意味の順に段階的に出ます。前段が通らなければ後段は出ません
- 構文エラーの最中でも、hover と `jin/renderSvg` は直前の正常なモデルで答えます（応答に `stale` が立ちます）
- 打鍵は 150 ms デバウンスして古い要求をキャンセルします。ファイルを開いた瞬間の診断は待ちません
- **hover は `ref` の docstring を出しません。** 出すには `ref` を import する必要があり、
  カーソルを合わせるたびに任意コード実行になるためです

### 8-3. Claude Code プラグイン

`plugins/claude-code/jin/` を導入すると、Claude Code で `.jin` の診断と定義ジャンプが効きます。
`jin` コマンドが PATH にあることが前提です（`uv run jin` は PATH に入らないので、プラグインから
使うには別途通してください）。導入手順はプラグインの
[README](../plugins/claude-code/jin/README.md) にあります。

同梱の `skills/jin-lang/reference/` は `docs/spec/model.md` と `schemas/jin.schema.json` の**コピー**です。
手で編集せず、`uv run python scripts/sync_plugin_reference.py` で同期してください。

---

## 9. サンプル 3 本

| ファイル | 形 | 何が見えるか |
|---|---|---|
| `examples/researcher/researcher.jin` | 核あり 2 陣（77 行） | 紋・記憶・護符・保留・`summon` |
| `examples/pipeline/pipeline.jin` | 核なし + 入れ子 flow 6 陣（89 行） | 弦・矢印・脱出の菱形 |
| `examples/showcase/showcase.jin` | flow の陣 + 中身の濃い陣 5 陣（131 行） | 図に出る要素 9 種すべて |

`researcher` と `pipeline` は要件書に掲載されているサンプルです。`showcase` は
エディタを一通り触るために置いたもので、この 1 本だけが 9 種すべてを既定の表示で描きます
（`researcher` は `summon`、`pipeline` は `flow` で、2 本合わせても `delegate` が出ないためです）。

```bash
uv run jin editor examples/showcase/showcase.jin      # 9 種すべてをクリックできる
PYTHONPATH=tests/fixtures/stubs uv run jin run examples/showcase/showcase.jin "go" \
  --model fake --trace /tmp/sc.jsonl                  # 9 イベント
```

- **`jin run` にだけ `PYTHONPATH=tests/fixtures/stubs` が要ります。** `ref` が指す `research.*` は
  スタブだからです。`check` / `render` / `editor` は `ref` を import しないので不要です
- オーバーレイの点の密度は `flow.max` で変わります。`Showcase.flow.max` を 3 から 16 にすると
  イベントは 9 から 48 に増え、点は総行数ぶん境界環に並びます
- `builtin` の紋は `exit_loop` にしてあります。`google_search` は Gemini 以外のモデルを拒むので
  `--model fake` では落ちますし、委譲と同じ陣にも置けません

---

## 10. 用語集

| 語 | 対応する JSON | 意味 |
|---|---|---|
| 陣 | `circles[]` の 1 要素 | エージェント 1 個、または他の陣を束ねる制御構造 |
| 核 | `core` | その陣が使うモデル。核があれば LLM エージェント |
| 紋 | `tools[]` の 1 要素 | ツール。関数（`tool`）・組み込み（`builtin`）・他の陣の呼び出し（`summon`）の 3 種 |
| 記憶 | `state[]` | セッション状態の宣言。`out: true` のものが出力先になる |
| 弦 | `flow.steps` の連結 | 順次・並列・繰り返しのつながり |
| 境界環 | `boundary` | 陣の外周。護符と保留が置かれる |
| 護符 | `boundary.guards[]` | 実行の前後に挟むコールバック |
| 保留 | `boundary.await[]` | 人の介入を待つ点 |
| 委譲 | `delegate[]` | 別の陣へ処理を渡すこと。判断するのは LLM |
| 正準形 | — | `jin fmt` が出力する唯一正しい書式。エディタの保存もこの形 |
| トレース | `--trace` の JSONL | 実行イベントの記録。1 行 1 イベント、JSON Pointer つき |

---

## 11. リポジトリの構成

```
schemas/jin.schema.json   Pydantic から生成した JSON Schema（正典・コミットする）
docs/spec/                モデル / ADK 対応 / レイアウト / 診断 / オペレーションの仕様
examples/                 researcher.jin / pipeline.jin / showcase.jin（正準形）
packages/jin-core/        意味モデル・位置付きパーサ・意味検査・診断・正準形・意味オペレーション
packages/jin-adk/         ADK コード生成（Jinja2）/ 書き出し / 実行 / トレース / FakeLlm
packages/jin-render/      決定的レイアウト / SVG 文字列生成 / 装飾 / trace overlay
packages/jin-lsp/         LSP サーバ（stdio + WebSocket）/ 標準機能 / 独自リクエスト
packages/jin-cli/         CLI（check / fmt / schema / dump / build / run / render / lsp / editor）
apps/editor/              視覚エディタ（Vite + React + TS）。Python パッケージを import しない
plugins/claude-code/jin/  Claude Code プラグイン（.lsp.json / skills / hooks）
tests/                    spec 突合 / 横断契約 / 診断コードの fixture
```

---

## 12. さらに詳しく / 困ったとき

仕様の正典は次のとおりです。本ガイドと食い違った場合はこちらが優先します。

| 知りたいこと | 読むもの |
|---|---|
| `.jin` に書けるキーの全一覧 | [`docs/spec/model.md`](spec/model.md) |
| ADK のどのクラスの何になるか | [`docs/spec/adk-mapping.md`](spec/adk-mapping.md) |
| 診断コード（JINxxx）の一覧 | [`docs/spec/diagnostics.md`](spec/diagnostics.md) |
| 図の座標と `data-jin` 属性の規則 | [`docs/spec/layout.md`](spec/layout.md) |
| エディタの編集操作と ws の防御 | [`docs/spec/ops.md`](spec/ops.md) |
| 上位要件と設計判断の背景 | [`jin-requirements.md`](../jin-requirements.md) / [`docs/adr/`](adr/) |

このガイドで解決しない疑問や、手順が古くなっている箇所は
[GitHub Issues](https://github.com/rswisteria/jin-lang/issues) へ寄せてください。

Phase 7（ライブ実行 / `import` / MCP / VS Code 拡張）は要件書で「任意」とされており、未実装です。
