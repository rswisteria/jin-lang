# Jin 要素 → ADK クラス対応（adk-mapping.md）

> 正典。要件書 `jin-requirements.md` §2.1 / §3 の実装仕様。
> 対象ランタイムは **google-adk 2.8.0**（`delivery/20260904-1445-jin/adk-api-probe.md` の実測でピン留め）。
> 生成コードの引数名はこの実測に固定する。記憶で書き換えない。

## 0. この文書の読み方（機械可読の約束）

`tests/spec/test_spec_consistency.py` が §1 の表の「Jin キー」列を要件書 §2.1 の対応表と突合する。
表の書式（`<!-- machine-readable: adk-vocabulary -->` マーカー直後の Markdown 表、1 列目が Jin キー）を変えない。

## 1. 語彙対応表（要件書 §2.1）

<!-- machine-readable: adk-vocabulary -->

| Jin キー | 意味 | ADK 対応 | 描画 |
|---|---|---|---|
| `circles[]` | エージェント/プログラム単位 | `LlmAgent` または workflow agent | 陣（同心円） |
| `core` | モデル | `LlmAgent.model` | 核（中心） |
| `instruction.rune` | 指示テキスト | `LlmAgent.instruction`（`{state_key}` テンプレートは透過） | 指示環（環に沿う文字列） |
| `tools[]` | ツール（kind: tool / builtin / summon） | `FunctionTool` / 組み込み / `AgentTool` | 道具環の紋。核から放射線 |
| `delegate[]` | サブ陣への委譲（LLM が transfer） | `LlmAgent.sub_agents` | 境界環内側の小円、核と破線 |
| `state[]` | セッション状態（`out`） | `session.state` / `output_key` | 記憶環の四角 |
| `flow.kind = sequence` | 直列 | `SequentialAgent` | 開いた弦列 |
| `flow.kind = parallel` | 並列 | `ParallelAgent` | 弦なし対称配置 |
| `flow.kind = loop` | ループ | `LoopAgent` + 終了判定エージェント | 閉じた多角形/星形 |
| `boundary.guards[]` | コールバック | `before_/after_{agent,model,tool}_callback` | 境界環の刻印 |
| `boundary.await[]` | 人の介入点 | `LongRunningFunctionTool` | 境界環の欠け |
| `root` | エントリポイント | 生成モジュールの `root_agent` | 最外の陣 |

<!-- /machine-readable -->

> **注記（design.yaml との差異）**: `delivery/20260904-1445-jin/design.yaml` の
> `implementation_phases.items[0].verification.machine` は本表を「§2.1 対応表の 11 行」と書いているが、
> 要件書 §2.1 の表と `requirements.json` の `FR-MODEL-002.vocabulary[]` はいずれも **12 行**である
> （実測: `grep -c` で 12）。上流 2 系統が一致しているため本表は 12 行とし、
> design.yaml 側の件数を転記誤りとして親へ確認要求を返した。

## 2. 実測 API（google-adk 2.8.0）

Phase 2（`jin-adk`）のテンプレートはこの実測値に固定する。本ラウンド（Phase 0/1）では生成コードを書かない。

### 2.1 エージェントクラス

| クラス | Jin 側の条件 | 主な引数（実測で存在を確認したもの） |
|---|---|---|
| `LlmAgent` | circle が `core` を持つ | `name` / `model` / `description` / `instruction` / `tools` / `sub_agents` / `output_key` / `before_agent_callback` / `after_agent_callback` / `before_model_callback` / `after_model_callback` / `before_tool_callback` / `after_tool_callback` |
| `SequentialAgent` | `flow.kind = sequence` | `name` / `sub_agents` / `description` |
| `ParallelAgent` | `flow.kind = parallel` | `name` / `sub_agents` / `description` |
| `LoopAgent` | `flow.kind = loop` | 上記に加えて **`max_iterations`** |

**`flow.max` は `LoopAgent(max_iterations=...)` にマップする。`max` という引数名は存在しない。**

### 2.2 ツール

| Jin | ADK | 実測シグネチャ |
|---|---|---|
| `tools[kind=tool]` | `FunctionTool` | `FunctionTool(func, *, require_confirmation=False)` |
| `tools[kind=tool]` かつ `boundary.await` に含まれる | `LongRunningFunctionTool` | `LongRunningFunctionTool(func)` |
| `tools[kind=summon]` | `AgentTool` | `AgentTool(agent, skip_summarization=False, *, include_plugins=True, propagate_grounding_metadata=False)` |
| `tools[kind=builtin]` | 組み込みインスタンス | `google.adk.tools.google_search` は `GoogleSearchTool` の**インスタンス**。クラスではないのでそのまま `tools=[...]` に置く |

### 2.3 flow.exit

`BaseAgent` を継承した判定エージェント（`StateCheckAgent`）を生成し、条件成立時に
`EventActions(escalate=True)` を返す。`LoopAgent.sub_agents` の末尾に置く。
`BaseAgent._run_async_impl(self, ctx) -> AsyncGenerator[Event, None]` を override する（実測）。

DP-JIN-CODEGEN-RUNTIME-01（案 A・ai_provisional）により、`StateCheckAgent` のクラス本体は
生成物 `agent.py` に毎回埋め込む（生成物が自己完結し、`jin` パッケージを import しない）。

### 2.4 実行とトレース

- `Runner` は**全キーワード引数**。`session_service` が必須（実測）
- トレース JSONL の `agent` は `Event.author`、`ts` は `Event.timestamp` から取る。
  `{ seq, ts, agent, kind, name, pointer, input, output }` は **Jin 側で組み立てる派生スキーマ**であり、
  ADK の `Event` をそのまま書くのではない

## 3. Jin で表現できない ADK 機能

`planner` / `output_schema` / `MCPToolset` / `code_executor` などは v1 では生成しない。
**ADK に対応物のない Jin 構造はコンパイル時エラーとする。黙って落とさない**（NFR-FAIL-001）。

## 4. 本ラウンドでの実装状況

Phase 0 / Phase 1 では `jin-core` と `jin-cli`（check / fmt / schema / dump）のみを実装した。
本文書の §2 / §3 は Phase 2（`jin-adk`）の実装契約であり、コードはまだ存在しない。
`jin_core` は `google.adk` を import しない（import-linter の `forbidden` 契約で CI が落とす・ADR-004）。

## 5. 表現できるが v1 で落とす構造

| Jin の構造 | 扱い |
|---|---|
| 1 circle に `out: true` の state が 2 件以上 | `LlmAgent.output_key` が単一値のため Phase 2 のコード生成時エラー。診断コードは増やさない（`docs/spec/model.md` §3.3） |
| `core` と `flow` の両立 / 両方欠落 | JIN022（Phase 1 の意味検査で落ちる） |
