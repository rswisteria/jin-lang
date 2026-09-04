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

`jin-adk` のテンプレートはこの実測値に固定してある。実物との一致は
`packages/jin-adk/tests/test_adk_surface.py` が毎回確かめる（記憶で書き換えない）。

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

`builtin` に書ける名前は `google.adk.tools` が**インスタンスとして**公開している 9 個（実測）:
`enterprise_web_search` / `get_user_choice` / `google_maps_grounding` / `google_search` /
`load_artifacts` / `load_memory` / `preload_memory` / `request_input` / `url_context`。
列挙の正本は `jin_adk.codegen.BUILTIN_TOOLS` で、実物との一致は
`test_builtin_tools_constant_matches_what_adk_actually_exports` が落とす。
ここに無い `builtin` はコンパイル時エラー（§4.4）。

### 2.3 flow.exit

`BaseAgent` を継承した判定エージェント（`StateCheckAgent`）を生成し、条件成立時に
`EventActions(escalate=True)` を返す。`LoopAgent.sub_agents` の末尾に置く。
`BaseAgent._run_async_impl(self, ctx) -> AsyncGenerator[Event, None]` を override する（実測）。

DP-JIN-CODEGEN-RUNTIME-01（案 A・**人間承認済み**・ADR-008）により、`StateCheckAgent` のクラス本体は
生成物 `agent.py` に毎回埋め込む（生成物が自己完結し、`jin` パッケージを import しない）。
`FakeLlm` は生成物には現れず `jin_adk.fake_llm` に置く。

### 2.4 実行とトレース

- `Runner` は**全キーワード引数**。`session_service` が必須（実測）
- トレース JSONL の `agent` は `Event.author`、`ts` は `Event.timestamp` から取る。
  `{ seq, ts, agent, kind, name, pointer, input, output }` は **Jin 側で組み立てる派生スキーマ**であり、
  ADK の `Event` をそのまま書くのではない。各キーの詳細は §4.3

## 3. Jin で表現できない ADK 機能

`planner` / `output_schema` / `MCPToolset` / `code_executor` などは v1 では生成しない。
**ADK に対応物のない Jin 構造はコンパイル時エラーとする。黙って落とさない**（NFR-FAIL-001）。

## 4. 実装状況

Phase 2 で `packages/jin-adk` を実装した。§2 / §3 は実装契約であり、
**`packages/jin-adk/tests/test_adk_surface.py` が実物の google-adk 2.8.0 に対して assert する**
（この文書が版に取り残されたら、そのテストが赤くなる）。

`jin_core` は `google.adk` を import しない（import-linter の `forbidden` 契約で CI が落とす・ADR-004）。
`jin_adk` の中でも `google.adk` を import するのは実行系（`fake_llm` / `loader` / `run`）だけで、
コード生成（`codegen` / `project`）はテキストしか作らない。

### 4.1 モジュールの分担

| モジュール | 役割 |
|---|---|
| `jin_adk.codegen` | 意味モデル → `agent.py` / `__init__.py` / `.env.example` のソースと pointer 対応表 |
| `jin_adk.project` | 要件書 §3.1 の 3 ファイルを書き出す（**ちょうど 3 つ**。対応表は書き出さない） |
| `jin_adk.pointers` | ADR-009 の対応表（ADK 識別子 → JSON Pointer） |
| `jin_adk.loader` | 生成モジュールの import（`importlib` を使うのはここだけ） |
| `jin_adk.fake_llm` | `--model fake` の差し替え（**生成物には現れない**・ADR-008） |
| `jin_adk.trace` | §3.4 の派生スキーマ組み立てと JSONL 書き出し |
| `jin_adk.run` | `Runner` + `InMemorySessionService` での実行 |

### 4.2 `.env.example`（要件書 §3.1）

google-adk 2.8.0 の実測で決めた 4 キーを出す（DP-COMMON-15 /
`delivery/20260904-1445-jin/decision-conformance.md` §2.13）:
`GOOGLE_GENAI_USE_ENTERPRISE` / `GOOGLE_API_KEY` / `GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION`。
**推測で足さない。** 値は入れない。

### 4.3 トレース 1 行のスキーマ（要件書 §3.4 の具体化）

| キー | 値 | ADK 側の出どころ |
|---|---|---|
| `seq` | 1 から連番（行ごと・1 イベントが複数行になりうる） | Jin 側で採番 |
| `ts` | ISO 8601 の UTC 文字列 | `Event.timestamp`（epoch 秒）を変換。値が無ければ空文字（捏造しない） |
| `agent` | 発火したエージェント名 | `Event.author` |
| `kind` | `model` / `tool` / `transfer` / `escalate` / `final` | 下表 |
| `name` | 発火した要素の名前 | `kind` ごとに下表 |
| `pointer` | JSON Pointer（レンダラの `data-jin` と同じ鍵） | ADR-009 の対応表を引く |
| `input` | 入力（無ければ `null`） | function_call の `args` |
| `output` | 出力（無ければ `null`） | テキスト / function_response の `response` |

| `kind` | 出る条件 | `name` | `pointer` |
|---|---|---|---|
| `model` | `content.parts` にテキストがある | circle の `core`（モデル ID） | `/circles/<i>/core` |
| `tool` | `parts` に function_call / function_response がある | tool 名 | `/circles/<i>/tools/<j>` |
| `transfer` | `actions.transfer_to_agent` | 転送先エージェント名 | `/circles/<i>/delegate/<k>` |
| `escalate` | `actions.escalate` | 判定エージェント名 | `/circles/<i>/flow/exit` |
| `final` | 最終応答（`Event.is_final_response()`）かつテキストがある | エージェント名 | `/circles/<i>` |

対応表に無いエージェントの行では `pointer` を**空文字**にする。
別の要素の pointer を当てるとエディタが無関係な場所を光らせるため。

### 4.4 生成コードに写せない構造

意味検査（`jin check`）を診断 0 件で通っても、ADK に写せない構造は残る。
`jin_adk.errors.CompileError` として**コンパイル時に落とす**（NFR-FAIL-001「黙って落とさない」）。
fixture は `packages/jin-adk/tests/fixtures/adk-gaps/*.jin`（**全部 `jin check` は通る**）。

| 構造 | 理由（実測） |
|---|---|
| circle 名が Python の識別子でない / Python の予約語 / `user` | `BaseAgent.validate_name` が `str.isidentifier()` を要求し `user` を拒む。予約語は ADK は通すが**生成コードが構文エラー**になる |
| 1 circle に `out: true` の state が 2 件以上 | `LlmAgent.output_key` は単一値 |
| 核なし circle に `instruction` / `tools` / `delegate` / `out: true` の state | workflow agent の `model_fields` に無い（`sub_agents` は `flow.steps` が使う） |
| 核なし circle に `before_model` / `after_model` / `before_tool` / `after_tool` の guard | workflow agent が持つのは `before_agent` / `after_agent` だけ |
| `ref` が `module.path:callable` の形でない | import 文を作れない |
| `builtin` が §2.2 の実測集合に無い | そんな組み込みツールが無い |
| `await` 対象が `kind: tool` でない | `LongRunningFunctionTool` は関数を要求する |
| root 以外の circle 名が `root_agent` / `<circle 名>__exit` の衝突 | 生成コード上の名前が衝突する |

## 5. 表現できるが v1 で落とす構造

| Jin の構造 | 扱い |
|---|---|
| 1 circle に `out: true` の state が 2 件以上 | `LlmAgent.output_key` が単一値のためコード生成時エラー。診断コードは増やさない（`docs/spec/model.md` §3.3）。ほかの写せない構造は §4.4 |
| `core` と `flow` の両立 / 両方欠落 | JIN022（Phase 1 の意味検査で落ちる） |
