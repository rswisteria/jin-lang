# ADK / 依存ライブラリ 実測プローブ（親セッション実施・2026-09-04）

取得方法: PyPI JSON API + `uv venv` 隔離環境への実インストール後の `inspect` / Pydantic `model_fields` 走査。
学習知識ではなく**実機の introspection 結果**。実装 Stage 1 の `tech-version-check` の一次証拠として使うこと。

## PyPI 最新安定版（2026-09-04 取得）

| パッケージ | 最新版 | requires_python | 備考 |
|---|---|---|---|
| google-adk | 2.8.0 | >=3.10 | 要件書 §1.1「2.x 系」を満たす |
| pygls | 2.1.1 | >=3.9 | |
| lark | 1.3.1 | >=3.8 | |
| pydantic | 2.13.5 | >=3.9 | v2 系 |
| typer | 0.27.2 | >=3.10 | |
| jinja2 | 3.1.6 | >=3.7 | |
| syrupy | 6.0.0 | >=3.10 | |
| pytest-lsp | 1.0.1 | >=3.10 | |

ローカル実行環境: Python 3.13.1 / uv 0.7.8 / Node v22.12.0 / pnpm 10.15.1。

## google-adk 2.8.0 実測 API（要件書 §3.2 の生成コード検証）

インストール済み 2.8.0 に対する実測。**テンプレートはこの実測値に固定すること**（記憶で書かない）。

### エージェントクラスの受け付けるフィールド

- `LlmAgent`: `after_agent_callback` / `after_model_callback` / `after_tool_callback` / `before_agent_callback` / `before_model_callback` / `before_tool_callback` / `code_executor` / `description` / `disallow_transfer_to_parent` / `disallow_transfer_to_peers` / `generate_content_config` / `global_instruction` / `include_contents` / `input_schema` / `instruction` / `mode` / `model` / `name` / `on_model_error_callback` / `on_tool_error_callback` / `output_key` / `output_schema` / `parallel_worker` / `parent_agent` / `planner` / `rerun_on_resume` / `retry_config` / `state_schema` / `static_instruction` / `sub_agents` / `timeout` / `wait_for_output`
- `SequentialAgent` / `ParallelAgent`: `after_agent_callback` / `before_agent_callback` / `description` / `input_schema` / `name` / `output_schema` / `parent_agent` / `rerun_on_resume` / `retry_config` / `state_schema` / `sub_agents` / `timeout` / `wait_for_output`
- `LoopAgent`: 上記に加えて **`max_iterations`**（`max` ではない）

→ 要件書 §3.2 が使う `name` / `model` / `description` / `instruction` / `tools` / `before_model_callback` / `before_tool_callback` / `output_key` / `sub_agents` はすべて存在する。`flow.max` は `LoopAgent(max_iterations=...)` へマップする。

### ツール

```
FunctionTool.__init__(self, func: Callable[..., Any], *, require_confirmation: bool | Callable[..., bool] = False)
LongRunningFunctionTool.__init__(self, func: Callable)
AgentTool.__init__(self, agent: BaseAgent, skip_summarization: bool = False, *, include_plugins: bool = True, propagate_grounding_metadata: bool = False)
```

- `google.adk.tools.google_search` は `GoogleSearchTool` のインスタンス（クラスではない）。`builtin` はインスタンスをそのまま `tools=[...]` に置く。
- `AgentTool` は `agent=` 位置/キーワード両可。要件書 §3.2 の `AgentTool(agent=Summarizer)` は妥当。

### 実行・トレース

```
Runner.__init__(self, *, app=None, app_name=None, agent=None, node=None, plugins=None,
                artifact_service=None, session_service: BaseSessionService,
                memory_service=None, credential_service=None,
                plugin_close_timeout=5.0, auto_create_session=False)
```

- **`Runner` は全キーワード引数**。`session_service` は必須。`agent` と `app_name` を渡す形が §3.4 の用途に合う。
- `InMemorySessionService` は `google.adk.sessions` から import 可。
- `EventActions` のフィールドに **`escalate`** / `transfer_to_agent` / `state_delta` が存在 → §3.3 の `StateCheckAgent` が `EventActions(escalate=True)` を返す設計は成立する。
- `Event` の主なフィールド: `actions` / `author` / `branch` / `content` / `custom_metadata` / `error_code` / `error_message` / `id` / `invocation_id` / `long_running_tool_ids` / `partial` / `timestamp` / `turn_complete` / `usage_metadata` ほか。
  → §3.4 のトレース JSONL（`seq` / `ts` / `agent` / `kind` / `name` / `pointer` / `input` / `output`）は **Jin 側で組み立てる派生スキーマ**であり、ADK Event をそのまま書くのではない。`agent` は `Event.author`、`ts` は `Event.timestamp` から取る。
- `BaseAgent._run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]` → `StateCheckAgent` はこれを override する。
- `BaseLlm.generate_content_async(self, llm_request: LlmRequest, stream: bool = False) -> AsyncGenerator[LlmResponse, None]` → `FakeLlm` はこれを override する。`supported_models` も存在。
