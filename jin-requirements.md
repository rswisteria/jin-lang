# Jin(陣)— 魔法陣型エージェント記述言語 要件定義

> 状態: ドラフト v0.2 / 2026-09-04
> 用途: Claude Code に実装させるための上位要件。superpowers の brainstorming → spec → writing-plans の入力として使う。
> 配置先の推奨: `docs/superpowers/specs/2026-09-04-jin-overview.md`
> v0.1 からの変更: テキスト表現を人間可読な DSL から JSON に変更。視覚エディタ/デバッガを正式スコープに含め、LSP をその言語サービス基盤として再定義。未決事項は全て決定済み(§10)。

---

## 0. 目的・スコープ・非目標

### 設計前提

- **テキストは人間が読まない。** `.jin` ファイルはモデルの永続化形式であり、視覚エディタと LLM の共通交換形式である
- 人間は視覚エディタ/デバッグツールで書く。LLM(Claude Code)は LSP の診断を頼りにテキストを書く
- 視覚表現(魔法陣 SVG)はモデルからの純関数。レイアウト情報はファイルに保存しない
- **レンダラは 1 つだけ**(Python)。エディタは LSP から SVG を受け取って表示し、独自に描画しない。描画のズレをゼロにするため

### 目的

Google ADK 上の LLM エージェントを、同心円と幾何学図形(魔法陣)として決定的に描画されるモデルとして記述・編集・実行・デバッグできるようにする。

### 成功条件

1. `.jin` 1 つから `adk run` / `adk web` で動く ADK プロジェクトが生成される
2. 同じ `.jin` から常に同じ SVG が生成される(スナップショットテストで担保)
3. Claude Code が `.jin` を書くとき、JSON Schema と `jin check --json` / LSP 診断の出力だけで構文・意味エラーを修正しきれる
4. LSP が Claude Code プラグインとして配布され、`.jin` を開くと診断・定義ジャンプが効く
5. 視覚エディタで行った編集がファイルに反映され、そのファイルを開き直すと同じ状態に戻る(モデル→ファイル→モデルが同一、ファイル→モデル→ファイルがバイト同一)
6. `jin run --trace` の出力をエディタで読み込み、魔法陣上でイベントを追える

### 非目標(v1 では作らない)

- 人間可読な独自 DSL(v0.1 の `circle Researcher { ... }` 構文は廃止)
- LangChain / LangGraph ターゲット
- 汎用計算(式、条件分岐、関数定義)。ツール実装は Python 側に置き、Jin からは参照するだけ
- 複数ファイルの `import`(v1.1 で検討)
- 実行中のライブストリーミング表示(v1 はトレースの事後リプレイまで)

---

## 1. 全体アーキテクチャ

### 1.1 技術選定

| 領域 | 選定 | 理由 |
|---|---|---|
| 永続化形式 | JSON(UTF-8、正準形)+ JSON Schema draft 2020-12 | LLM が最も安定して書ける。既存の JSON ツールがそのまま使える。エディタとの往復が無損失(コメント・整形の保存問題がない) |
| 意味モデル | Pydantic v2。JSON Schema は Pydantic から生成してリポジトリにコミット(CI でドリフト検出) | モデル定義が唯一の真実 |
| パーサ | Lark の JSON 文法(位置情報付き) | LSP の診断に行・列が要る。標準 `json` は位置を持たない |
| 言語 | Python 3.12+、`uv` ワークスペース | ADK Python がターゲット。バリデータ・コンパイラ・レンダラ・LSP を同一プロセスで共有 |
| コード生成 | Jinja2 + `ruff format` 後処理 | 生成物が diff できる |
| SVG | 標準ライブラリで文字列生成 | 決定性の担保が容易 |
| LSP | pygls(stdio と WebSocket の両トランスポート) | stdio は Claude Code / VS Code 向け、WebSocket はブラウザのエディタ向け。同一サーバ |
| CLI | typer | |
| エディタ | React + TypeScript(Vite)、SVG は LSP から取得 | 描画は Python レンダラに一本化。エディタはヒットテストとフォームだけを持つ |
| テスト | pytest、syrupy、pytest-lsp、Playwright(エディタのスモークのみ) | |
| ターゲット | `google-adk` 2.x 系(メジャーを固定) | |

### 1.2 リポジトリ構成

```
jin/
  pyproject.toml                  # uv workspace root
  schemas/jin.schema.json         # Pydantic から生成。コミットする
  docs/
    spec/
      model.md                    # モデル仕様(意味論とキーの説明。LLM の参照資料)
      adk-mapping.md              # Jin 要素 → ADK クラスの対応表
      layout.md                   # 決定的レイアウト規則と data-jin 属性の契約
      diagnostics.md              # エラーコード一覧(JINxxx)
      ops.md                      # 意味編集オペレーションの一覧(エディタ/LSP 共通)
    superpowers/specs/
    superpowers/plans/
  packages/
    jin-core/     src/jin_core/   # model, parser(位置付き), semantic, diagnostics, canonical, ops
    jin-adk/      src/jin_adk/    # codegen, templates/, runtime(run/trace/FakeLlm)
    jin-render/   src/jin_render/ # layout, svg, ornament, trace overlay
    jin-lsp/      src/jin_lsp/    # server, features/, custom requests
    jin-cli/      src/jin_cli/    # main.py
  apps/
    editor/                       # 視覚エディタ/デバッガ(Phase 5–6)
  plugins/
    claude-code/jin/              # Claude Code プラグイン(.lsp.json, skills/, hooks/)
  examples/
    researcher/researcher.jin
    pipeline/pipeline.jin
```

依存は一方向: `jin-core` ← `jin-adk` / `jin-render` ← `jin-lsp` / `jin-cli`。`jin-core` は ADK に依存しない。`apps/editor` は LSP にしか依存しない(Python パッケージを直接 import しない)。

---

## 2. モデルとシリアライズ形式

### 2.1 語彙と ADK 対応

| Jin(JSON キー) | 意味 | ADK 対応 | 描画 |
|---|---|---|---|
| `circles[]` | エージェント/プログラム単位 | `LlmAgent` または workflow agent | 陣(同心円) |
| `core` | モデル | `LlmAgent.model` | 核(中心) |
| `instruction.rune` | 指示テキスト | `LlmAgent.instruction`(`{state_key}` テンプレートは透過) | 指示環(環に沿う文字列) |
| `tools[]`(kind: tool / builtin / summon) | ツール | `FunctionTool` / 組み込み / `AgentTool` | 道具環の紋。核から放射線 |
| `delegate[]` | サブ陣への委譲(LLM が transfer) | `LlmAgent.sub_agents` | 境界環内側の小円、核と破線 |
| `state[]`(`out`) | セッション状態 | `session.state` / `output_key` | 記憶環の四角 |
| `flow.kind = sequence` | 直列 | `SequentialAgent` | 開いた弦列 |
| `flow.kind = parallel` | 並列 | `ParallelAgent` | 弦なし対称配置 |
| `flow.kind = loop` | ループ | `LoopAgent` + 終了判定エージェント | 閉じた多角形/星形 |
| `boundary.guards[]` | コールバック | `before_/after_{agent,model,tool}_callback` | 境界環の刻印 |
| `boundary.await[]` | 人の介入点 | `LongRunningFunctionTool` | 境界環の欠け |
| `root` | エントリポイント | 生成モジュールの `root_agent` | 最外の陣 |

circle は 2 種類。**核あり**(`core` を持つ → `LlmAgent`)と **核なし**(`flow` だけ → workflow agent)。両方持つ/両方無いのはエラー(JIN022)。

### 2.2 ファイル形式

拡張子は `.jin`、中身は JSON。`.json` にしないのは Claude Code の LSP ルーティングが拡張子単位で、`.json` を奪うと他の JSON ファイルと衝突するため。エディタ側は `.jin` を JSON 言語として扱う設定を持つ。

```json
{
  "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
  "version": 1,
  "root": "Researcher",
  "circles": [
    {
      "name": "Researcher",
      "core": "gemini-2.5-flash",
      "description": "調査と要約を行う",
      "instruction": {
        "rune": "あなたは慎重な調査アシスタントです。\n出典を必ず示し、公開前に人間の確認を求めてください。\nこれまでの知見: {findings}"
      },
      "tools": [
        { "name": "search",    "kind": "tool",   "ref": "research.tools:web_search" },
        { "name": "fetch",     "kind": "tool",   "ref": "research.tools:fetch_page" },
        { "name": "summarize", "kind": "summon", "circle": "Summarizer" },
        { "name": "publish",   "kind": "tool",   "ref": "research.tools:publish" }
      ],
      "state": [
        { "name": "query",    "type": "str" },
        { "name": "findings", "type": "str", "out": true }
      ],
      "boundary": {
        "guards": [
          { "on": "before_model", "ref": "research.guards:pii_filter" },
          { "on": "before_tool",  "ref": "research.guards:audit_log" }
        ],
        "await": ["publish"]
      }
    },
    {
      "name": "Summarizer",
      "core": "gemini-2.5-flash",
      "instruction": { "rune": "与えられた本文を 200 字で要約する" },
      "state": [ { "name": "summary", "type": "str", "out": true } ]
    }
  ]
}
```

```json
{
  "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
  "version": 1,
  "root": "Pipeline",
  "circles": [
    { "name": "Pipeline", "flow": { "kind": "sequence", "steps": ["Drafter", "Reviewer", "Refine"] } },
    { "name": "Refine",   "flow": { "kind": "loop", "steps": ["Critic", "Rewriter"], "max": 3,
                                    "exit": { "key": "approved", "equals": true } } },
    { "name": "Drafter",  "core": "gemini-2.5-flash", "instruction": { "rune": "下書きを書く" },
      "state": [ { "name": "draft", "type": "str", "out": true } ] },
    { "name": "Reviewer", "core": "gemini-2.5-flash", "instruction": { "rune": "{draft} をレビューする" },
      "state": [ { "name": "review", "type": "str", "out": true } ] },
    { "name": "Critic",   "core": "gemini-2.5-flash", "instruction": { "rune": "{draft} を批評し、十分なら approved=true" },
      "state": [ { "name": "approved", "type": "bool", "out": true } ] },
    { "name": "Rewriter", "core": "gemini-2.5-flash", "instruction": { "rune": "{review} を踏まえて {draft} を書き直す" },
      "state": [ { "name": "draft", "type": "str", "out": true } ] }
  ]
}
```

形式上の決定事項:

- 順序を持つものは配列(`circles`、`tools`、`state`、`steps`、`guards`、`await`)。配列順が描画順(12 時から時計回り)になる
- 名前が ID。`name` は circle ではファイル内一意、tools/state では circle 内一意。参照は名前で行い、rename は参照を追随させる意味オペレーション(§6.3)として提供する
- Python 参照は `module.path:callable` 形式のみ。インライン Python は不可
- `tools[].kind` は `tool | builtin | summon` の判別共用体。`builtin` は `{ "kind": "builtin", "builtin": "google_search" }`
- `flow.steps` は circle 名のみ。`flow.exit` は `{ "key", "equals" }` のみ(v1)
- `guards[].on` は `before_agent | after_agent | before_model | after_model | before_tool | after_tool`
- 未知のキーはスキーマ違反(`additionalProperties: false`)。将来拡張は `version` を上げる

### 2.3 正準形(canonical form)

`model → text` は関数であり、`jin fmt` と エディタの保存は同じバイト列を出す。

- 2 スペースインデント、キー順はスキーマ定義順、配列は宣言順を保持、末尾改行、非 ASCII はエスケープしない
- `$schema` と `version` は先頭固定
- 省略可能なキーは、値が既定値のときは出力しない(`"out": false` は書かない)
- 冪等: `fmt(fmt(x)) == fmt(x)`。意味保存: `model(fmt(x)) == model(x)`

### 2.4 静的意味制約(=美的制約)

| コード | 重大度 | 内容 | 修正ヒント |
|---|---|---|---|
| JIN001 | error | JSON 構文エラー | 位置と期待トークン |
| JIN002 | error | スキーマ違反(必須キー欠落・未知キー・型不一致・enum 外) | JSON Pointer と許容値 |
| JIN010 | error | 名前の重複(circle/tool/state) | |
| JIN011 | error | 未解決の参照(summon / delegate / steps / await / `{key}`) | 候補名を提示(編集距離) |
| JIN020 | error | `tools` または `state` が 12 を超えた | 「サブ陣に抽出」のコードアクション |
| JIN022 | error | `core` と `flow` の両立、または両方欠落 | |
| JIN030 | error | `flow.kind = loop` に `max` も `exit` もない | `max: 5` を追加 |
| JIN031 | error | `flow.steps` の要素が circle でない | |
| JIN040 | warning | Python 参照が import できない(`--resolve` 指定時のみ) | |
| JIN050 | error | rune 内 `{key}` が自 circle または flow 上流 circle の state に無い | |
| JIN060 | error | `root` が存在しない circle を指す | |
| JIN070 | warning | `await` 対象が `tools` に無い | |

各コードに fixture を 1 つ以上持つ(§8)。

### 2.5 決定的レイアウト仕様(`docs/spec/layout.md`)

- 正方形キャンバス。半径 R=1 の正規化座標で計算し、最後に px へ変換
- 環の半径は固定: instruction 0.35、tools 0.55、state 0.75、boundary 0.95。存在しない環は描かず、半径も詰めない
- 紋は 12 時位置から時計回り、配列順、等角配置
- 核 → tools の各紋へ放射線。`summon` は紋を入れ子の小陣として描く(深さ 1 まで展開、以下は点)
- `delegate` は境界環の内側に小円を並べ、核と破線で結ぶ
- `sequence` = 開いた弦列(矢印)、`parallel` = 弦なし対称配置、`loop` = 閉じた多角形。n ≥ 5 の loop は星形多角形 {n/k}(k は n/2 未満の最大の互いに素な整数)で描き、辺の順を訪問順に一致させる
- `await` の紋の角度に、境界環の欠けを作る
- 装飾(小点・飾り)は `instruction.rune` の SHA-256 から決定的に生成する(識別紋章)
- rune は instruction 環に沿った `<textPath>`。v1 は可読フォント、グリフフォントは v2
- 白黒 2 値 + 強調 1 色(トレース時のみ)。`<style>` 不使用、属性で完結

**data-jin 属性の契約(エディタとの接点):** 描画された全ての要素は `data-jin="<JSON Pointer>"`(例 `/circles/0/tools/2`)と `data-jin-kind="circle|core|rune|tool|state|flow-edge|guard|await|delegate"` を持つ。エディタはこの属性でヒットテストと選択を行う。ポインタはファイル内の位置とレンダリングとを結ぶ唯一の鍵であり、`jin/model` が返す pointer→range 対応表と一致すること。

---

## 3. ADK コンパイル要件(`jin-adk`)

### 3.1 出力形式

`jin build <file> --out <dir>` は ADK CLI の規約に従う Python プロジェクトを生成する。

```
<out>/
  <root_name>/
    __init__.py         # from .agent import root_agent
    agent.py            # 生成物。root_agent を公開
  .env.example
```

`adk run <out>/<root_name>` と `adk web <out>` でそのまま動くこと。

### 3.2 生成コードの形(researcher.jin)

```python
# generated by jin — do not edit
from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool, LongRunningFunctionTool
from google.adk.tools.agent_tool import AgentTool

from research.tools import web_search, fetch_page, publish
from research.guards import pii_filter, audit_log

Summarizer = LlmAgent(
    name="Summarizer",
    model="gemini-2.5-flash",
    instruction="与えられた本文を 200 字で要約する",
    output_key="summary",
)

root_agent = LlmAgent(
    name="Researcher",
    model="gemini-2.5-flash",
    description="調査と要約を行う",
    instruction="""あなたは慎重な調査アシスタントです。
出典を必ず示し、公開前に人間の確認を求めてください。
これまでの知見: {findings}""",
    tools=[
        FunctionTool(web_search),
        FunctionTool(fetch_page),
        AgentTool(agent=Summarizer),
        LongRunningFunctionTool(publish),
    ],
    before_model_callback=pii_filter,
    before_tool_callback=audit_log,
    output_key="findings",
)
```

コンストラクタの引数名は、実装時にインストールした `google-adk` のバージョンで検証してテンプレートに固定する(バージョンをピン留めし、CI で import テストを走らせる)。

### 3.3 マッピング規則

- `flow.exit` は `BaseAgent` を継承した判定エージェント(`StateCheckAgent`)を生成し、条件成立時に `EventActions(escalate=True)` を返す。LoopAgent の sub_agents 末尾に置く
- `state[]` のうち `out: true` だけが `output_key` になる。他は静的検証(JIN050)とエディタ表示のための宣言
- `guards[].on` をそのままコールバック引数名に対応させる。同種が複数あればリストで渡す
- Jin で表現できない ADK 機能(planner、output_schema、MCPToolset など)は v1 では生成しない。ADK に対応物のない Jin 構造はコンパイル時エラー。黙って落とさない

### 3.4 実行とトレース

- `jin run <file> "<prompt>" [--session <id>] [--trace out.jsonl] [--model fake]` は生成コードを一時ディレクトリに書き出して import し、`Runner` + `InMemorySessionService` で実行、イベントを標準出力に流す
- `--trace` は ADK の Event を 1 行 1 JSON で保存する。スキーマ: `{ "seq", "ts", "agent", "kind": "model|tool|transfer|escalate|final", "name", "pointer", "input", "output" }`。`pointer` は発火した要素の JSON Pointer(レンダラの `data-jin` と同じ鍵)
- `--model fake` は `BaseLlm` を継承した `FakeLlm`(固定応答)に差し替える。テストではネットワークに出ない

---

## 4. レンダラ要件(`jin-render`)

- 入力は意味モデル。ファイルを直接読まない
- 出力は単一 SVG 文字列。同じ入力 → バイト単位で同一(乱数・時刻・辞書順序に依存しない)
- 全要素に `data-jin` / `data-jin-kind` を付与(§2.5)
- `trace`(イベント配列)と `upto`(seq)を渡すと、`upto` までに発火した要素を強調色でオーバーレイし、境界環の外側にイベント数ぶんの点を並べる
- `focus`(circle 名)で入れ子の展開対象を切り替える
- CLI の `jin render` と LSP の `jin/renderSvg` は同じ関数を呼び、同じ出力を返す

---

## 5. CLI 要件(`jin-cli`)

| コマンド | 役割 | 備考 |
|---|---|---|
| `jin check [paths] [--json] [--resolve]` | 診断(JSON 構文・スキーマ・意味) | error があれば exit 1 |
| `jin fmt [paths] [--check]` | 正準形へ正規化 | `--check` は差分があれば exit 1 |
| `jin schema` | JSON Schema を標準出力 | LLM やエディタが取得する |
| `jin dump <file>` | モデル JSON + pointer→range 対応表 | |
| `jin build <file> --out <dir>` | ADK プロジェクト生成 | |
| `jin run <file> "<prompt>"` | 実行 | §3.4 |
| `jin render <file> [-o out.svg] [--trace t.jsonl] [--upto N] [--focus name]` | SVG 出力 | |
| `jin lsp [--stdio \| --ws PORT]` | LSP サーバ起動 | 既定は stdio |
| `jin editor [file]` | LSP(ws)を起動し、エディタを配信してブラウザを開く | Phase 5 |

診断の JSON 形式(LSP Diagnostic と 1:1):

```json
{"file": "a.jin", "pointer": "/circles/0/tools/2/circle",
 "range": {"start": {"line": 12, "col": 40}, "end": {"line": 12, "col": 52}},
 "code": "JIN011", "severity": "error",
 "message": "circle 'Summarizr' は定義されていません",
 "hint": "近い名前: Summarizer"}
```

メッセージは「何が悪いか + どう直すか」を必ず含める。LLM は hint をそのまま編集に使うので、hint は具体的な値にする。

---

## 6. LSP 要件(`jin-lsp`)— 言語サービスの唯一の入口

CLI・Claude Code・VS Code・視覚エディタの全てが、`jin_core` の同じ関数を LSP 経由で使う。LSP 固有のロジックは位置変換とプロトコル露出だけに限定する。

### 6.1 トランスポート

- stdio: Claude Code プラグイン、VS Code
- WebSocket(`jin lsp --ws PORT`): ブラウザのエディタ。同一サーバ実装

### 6.2 標準機能(v1)

| 機能 | 内容 |
|---|---|
| diagnostics | open / change / save で再計算。JSON 構文 → スキーマ → 意味の順で、前段が通らなければ後段は出さない |
| completion | スキーマ由来のキー、enum 値、参照名(`circle` / `steps` / `delegate` / `await` の位置で circle 名・tool 名)、rune 内 `{` の後で state key |
| hover | 要素 → ADK クラス名と生成される引数、rune の全文、Python 参照の docstring(`--resolve` 相当) |
| definition / references | circle 参照、state key 参照 |
| documentSymbol | circle > tools / state / flow の階層 |
| formatting | 正準形(`jin fmt` と同一) |
| rename | circle / tool / state。参照を全て追随 |
| codeAction | JIN011 → 名前置換、JIN020 → 選択要素をサブ陣に抽出、JIN030 → `max: 5` 追加。加えて §6.3 の全オペレーションを command として露出 |

### 6.3 独自リクエスト(エディタ API)

| リクエスト | 内容 |
|---|---|
| `jin/model` | 現在のドキュメントのモデル JSON と pointer→range 対応表 |
| `jin/renderSvg` | `{ uri, focus?, trace?, upto? }` → SVG 文字列 |
| `jin/applyOps` | 意味オペレーション列 → サーバがモデルを更新し、正準形テキストとの差分を `workspace/applyEdit` で適用。結果として新モデルと診断を返す |
| `jin/ops` | 利用可能なオペレーションの一覧(`docs/spec/ops.md` と同内容) |

オペレーション(v1): `addCircle`、`removeCircle`、`setCore`、`setDescription`、`setRune`、`addTool`、`removeTool`、`moveTool`(配列内の順序変更 = 角度変更)、`addState`、`removeState`、`setState`、`setFlow`、`addDelegate`、`removeDelegate`、`setGuard`、`removeGuard`、`toggleAwait`、`setRoot`、`rename`。各オペレーションは JSON Pointer で対象を指定し、失敗時は診断コードで理由を返す。undo/redo はクライアント側がオペレーションの逆を保持する(サーバは各オペレーションの逆オペレーションを応答に含める)。

### 6.4 動作要件

- 起動は `jin lsp`。`uv tool install` した `jin` コマンドがあればそれだけで動く
- 1000 行以下のファイルで診断 1 秒以内
- JSON 構文エラー中も、直前の正常なモデルで hover / renderSvg を提供する(エラー回復)

---

## 7. 視覚エディタ/デバッガ要件(`apps/editor/`)

人間の主要インターフェース。**ファイルが唯一の状態**であり、エディタは LSP の返すモデルと SVG を表示するだけで、独自のモデル状態を持たない。

### 7.1 編集モード

- 表示: `jin/renderSvg` の SVG をそのまま埋め込み、`data-jin` でヒットテスト。選択要素をハイライト
- プロパティパネル: 選択要素の種類に応じたフォーム。フォームは JSON Schema から生成する(手書きのフォーム定義を持たない)
- 操作はすべて `jin/applyOps` 経由。ドラッグで紋を環上で並べ替える → `moveTool`。核をクリック → `setCore`。環の空き位置をクリック → `addTool` / `addState`。circle 同士を結ぶ → `addDelegate` または `summon` ツール追加
- 診断は SVG 上の該当要素にバッジで表示し、クリックで hint を出す。codeAction を実行できる
- 入れ子の小陣をダブルクリックで `focus` を切り替える
- undo / redo(§6.3)

### 7.2 デバッグモード(トレースリプレイ)

- `jin run --trace` の JSONL を読み込み、タイムラインスクラバで `upto` を動かす。各位置で `jin/renderSvg` を `trace + upto` 付きで呼び、オーバーレイを表示
- 選択イベントの詳細パネル: モデル入出力、ツール引数と結果、transfer 先、escalate
- 「この紋で発火したイベントだけ」のフィルタ(`pointer` 一致)
- ライブ実行(WebSocket で `jin run` からストリーム)は v1.1

### 7.3 起動

`jin editor [file]` が LSP(ws)を起動し、ビルド済みエディタを配信してブラウザを開く。エディタ単体のサーバは持たない。

---

## 8. Claude Code 連携要件(`plugins/claude-code/jin/`)

```
plugins/claude-code/jin/
  .claude-plugin/plugin.json
  .lsp.json
  skills/jin-lang/SKILL.md
  skills/jin-lang/reference/model.md        # docs/spec/model.md のコピー(ビルドで同期)
  skills/jin-lang/reference/jin.schema.json  # schemas/ のコピー(ビルドで同期)
  hooks/hooks.json
  README.md
```

- `.lsp.json`:
  ```json
  { "jin": { "command": "jin", "args": ["lsp"], "extensionToLanguage": { ".jin": "jin" } } }
  ```
- `skills/jin-lang/SKILL.md`: 手順を規定する。「`reference/jin.schema.json` と `model.md` を読む → `.jin` を書く → `jin check --json` → hint に従って修正 → `jin fmt` → `jin build` → `jin run --model fake` で疎通 → 必要なら `jin render` で SVG を確認」。例は 2 つだけ載せ、仕様は reference を参照させる
- `hooks/hooks.json`: `PostToolUse`(Write / Edit で `.jin` を触ったとき)に `jin check --json` を走らせ、error があれば結果を返す。`SessionStart` で `jin --version` を確認し、無ければインストール手順を出す
- 配布は社内 `ai-delivery` マーケットプレイスに `git-subdir` ソースで登録する(stable / beta のチャネル運用に乗せる)
- 注記: 現状の Claude Code の LSP 連携は診断・定義ジャンプ・参照などの読み取り系が中心で、`jin/applyOps` のような独自リクエストをモデル側から呼ぶ経路はない。LLM はテキストを直接編集し、診断で修正するのが v1 の前提。意味オペレーションを LLM からも使わせたくなった場合は、同じ `jin_core.ops` を MCP サーバとして露出する(v1.1 候補)
- リポジトリ直下の `CLAUDE.md` には、パッケージ境界、`uv run pytest` の実行方法、`schemas/jin.schema.json` と `docs/spec/*.md` が正典であること、生成コードは編集しないことを書く

---

## 9. テスト要件

| 対象 | 方法 |
|---|---|
| スキーマ | Pydantic から生成した schema がコミット済みのものと一致(CI)。`examples/**/*.jin` が全て validate を通る |
| 診断 | `tests/fixtures/errors/JINxxx_*.jin` が対応コードを 1 つだけ出す |
| 正準形 | 冪等性、意味保存、エディタ保存と `jin fmt` の出力がバイト一致 |
| モデル | `jin dump` の JSON スナップショット |
| オペレーション | 各オペレーションについて `applyOps → 再パース → 期待モデル` と `逆オペレーションで元に戻る` |
| コード生成 | 生成 `agent.py` のスナップショット + 生成モジュールを import して ADK オブジェクト木を検証(`tools` の型、`sub_agents` の名前、callback の同一性)。モデル呼び出しはしない |
| 実行 | `FakeLlm` で `jin run` が最後まで通る。トレース JSONL のスキーマ検証と `pointer` の解決 |
| レンダラ | SVG スナップショット(正規化後)。同一入力 2 回で完全一致。全要素に `data-jin` があり、pointer がモデルに解決できる |
| LSP | pytest-lsp で initialize → didOpen → publishDiagnostics、completion、definition、formatting、`jin/renderSvg`、`jin/applyOps` の各ラウンドトリップ。stdio と ws 両方 |
| エディタ | Playwright スモーク: 開く → 紋を追加 → 保存 → ファイルが期待の正準形になる |
| プラグイン | `claude plugin validate` を CI で実行 |

全て `uv run pytest`(エディタは `pnpm test`)で通ること。ネットワーク・API キー不要。

---

## 10. 決定事項

v0.1 の未決事項は全て既定案で確定。v0.2 で追加した決定を含めて列挙する。

| # | 論点 | 決定 |
|---|---|---|
| 1 | 言語名・拡張子・CLI 名 | Jin / `.jin`(中身は JSON)/ `jin` |
| 2 | テキスト表現 | JSON + JSON Schema。人間可読性は要件にしない |
| 3 | ツール定義 | Python 参照(`module:callable`)のみ |
| 4 | Gemini 以外のモデル | `core` の文字列をそのまま `model` に渡す。LiteLLM ラッパーは v1.1 |
| 5 | loop の終了判定 | state の等値比較のみ。LLM 判定は v2 |
| 6 | 複数ファイル | v1 は単一ファイル。`import` は v1.1 |
| 7 | ADK YAML Agent Config | 見送り(callback を表現できない) |
| 8 | 配布 | `uv tool install` を社内 git から。Claude Code プラグインは ai-delivery 経由 |
| 9 | レンダラ | Python 1 本。エディタは LSP から SVG を受け取る |
| 10 | エディタの状態管理 | ファイルが唯一の状態。編集は全て `jin/applyOps` |
| 11 | 要素の識別 | 名前を ID とし、rename は参照追随の意味オペレーション。位置の鍵は JSON Pointer |

---

## 11. 実装フェーズ(Claude Code への発注単位)

各フェーズを独立した spec → plan → 実装のサイクルにする。フェーズの成果物はそれ単体で動作・テスト可能であること。

| Phase | 内容 | 完了条件 |
|---|---|---|
| 0 | `docs/spec/model.md`、`adk-mapping.md`、`layout.md`、`diagnostics.md`、`ops.md` と `examples/` 2 本(手書き JSON) | 仕様に自己矛盾がない。§2.2 の例が仕様どおりに読める |
| 1 | `jin-core`(Pydantic モデル、schema 生成、位置付きパーサ、意味検査、正準形、ops)+ `jin-cli`(check / fmt / schema / dump) | §2.4 の全コードに fixture があり、examples が通る。schema がコミットされる |
| 2 | `jin-adk`(build / run / trace / FakeLlm) | examples 両方が `adk run` で動く。トレースに `pointer` が入る |
| 3 | `jin-render`(render / focus / trace overlay、`data-jin` 付与) | SVG スナップショットが安定。全要素に pointer がある |
| 4 | `jin-lsp`(stdio + ws、標準機能、独自リクエスト)+ Claude Code プラグイン | Claude Code で `.jin` の診断・定義ジャンプが効く。pytest-lsp が通る |
| 5 | エディタ 編集モード | 開く → 編集 → 保存の往復がバイト一致。Playwright スモークが通る |
| 6 | エディタ デバッグモード(トレースリプレイ) | `run --trace` → エディタで読み込み → スクラブでオーバーレイ |
| 7 | v1.1 候補: ライブ実行、`import`、MCP による ops 露出、VS Code 拡張 | 任意 |

Phase 1 は brainstorming で「jin-core 単体」に絞ること。Phase 0 の仕様書を先に承認してから Phase 1 に入る。Phase 5 は Xtone の UI/UX の知見を入れる工程なので、brainstorming の段階でデザイナーを巻き込む前提でよい。

---

## 12. Claude Code への渡し方

1. 空リポジトリを作り、この文書を `docs/superpowers/specs/2026-09-04-jin-overview.md` に置いてコミット
2. Claude Code を起動し、次のように依頼する:

   > `docs/superpowers/specs/2026-09-04-jin-overview.md` を読んでください。これは複数フェーズのプロジェクトの上位要件で、§10 の決定事項は確定済みです。まず Phase 0(仕様書と examples)だけを対象に brainstorming してください。spec が承認されたら writing-plans に進んでください。

3. brainstorming は architectural に分類され質問が来るが、§10 が確定済みなので大半は不要。答える必要があるのは主に命名と細部
4. Phase ごとに 2〜3 を繰り返す。plan の実行は subagent-driven を推奨(パッケージ境界が明確なので独立タスクに分けやすい)
