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

## Phase 2 実装ラウンドでの追加実測（impl-p2・2026-09-05・google-adk 2.8.0 / Python 3.14.7）

隔離 venv（`scratchpad/adkprobe/v`）と本リポジトリの `.venv`（`uv sync` で 2.8.0 を実インストール）で実行した結果。

| 項目 | 実測結果 | 出典（site-packages 内） |
|---|---|---|
| `output_key` に入る型 | LLM の応答テキストを **str** で `state_delta[output_key]` に入れる（`{'approved': 'true'}`）。`output_schema` 無しでは JSON にしない | `google/adk/agents/llm_agent.py:1005-1045` |
| `instruction` の `{key}` が未設定 | `KeyError: Context variable not found` で **実行が落ちる**（`examples/researcher` の `{findings}` は初回に未設定） | `google/adk/utils/instructions_utils.py:174` |
| `{key}` の値が `None` | 空文字で描画される | 同 `:161-163` |
| `instruction` のテンプレート正規表現 | `_TEMPLATE_VAR_PATTERN = r'{+[^{}]*}+'`。`{{lit}}` → 変数 `lit`（**エスケープではない**）、`{draft}}` → `D1`（末尾の `}` も消費）、`{opt?}` → 省略可能（未設定なら空文字）、`{not a key}` / `{{ }}` → 素通し、`{artifact.x}` / `{app:key}` → 別種の参照 | 同 `:41` / `:145-176` / `:238-262` |
| `LoopAgent` + escalate | サブエージェントが `EventActions(escalate=True)` を返すとその周で止まる。返さなければ `max_iterations` まで回る（`critic=true` で 1 周、`critic=no` で 3 周を実測） | `google/adk/agents/loop_agent.py:116` |
| `BaseAgent.name` の検証 | `isidentifier()` 必須（`"Re searcher"` / `"1abc"` は拒否、`"日本語"` は通る）。`"user"` は予約 | `google/adk/agents/base_agent.py:648-662` |
| `FunctionTool.name` | `func.__name__`（lambda は `<lambda>`）。`LongRunningFunctionTool` も同じ。`AgentTool.name` はサブ agent 名。`google_search.name == "google_search"` | 実行結果 |
| callback にリスト | `before_model_callback=[cb1, cb2]` を受け付ける（型は `Callable | list[Callable] | None`） | `llm_agent.py:76-136` |
| `LlmAgent.model` の差し替え | 構築後に `agent.model = FakeLlm()` を代入でき、`canonical_model` もそれを返す | 実行結果 |
| 同名 sub_agents / 二重の親 | 同名は警告のみで通る（Jin は JIN010 で先に落とす）。同じ agent を 2 親に付けると `ValueError`（JIN013 が先に落とす） | 実行結果 |
| `google.adk.tools` の公開名 | `__all__` の各名を `__getattr__` で遅延 import する。`MCPToolset` は任意依存 `mcp` が無いと `ModuleNotFoundError`。ツールインスタンス: `google_search` / `url_context` / `load_memory` / `load_artifacts` / `preload_memory` / `enterprise_web_search` / `google_maps_grounding` / `get_user_choice` / `request_input`。関数: `exit_loop` / `transfer_to_agent` | `google/adk/tools/__init__.py:60-140` |
| `Event.timestamp` | float（epoch 秒） | 実行結果 |
| `SequentialAgent` / `LoopAgent` | **`DeprecationWarning: ... deprecated in favor of Workflow`** が構築時に出る（2.8.0）。動作はする。`Workflow cannot yet be used as an LlmAgent sub-agent` | 実行時警告 |
| `.env` の読み方 | `adk run` は `<parent>/<agent_name>` から親へ辿って最初の `.env` を読む（`<out>/.env` で効く） | `google/adk/cli/utils/envs.py:53-74` |
| `.env` のキー（書く側） | `adk create` が書くのは `GOOGLE_GENAI_USE_ENTERPRISE` / `GOOGLE_API_KEY` / `GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION` | `google/adk/cli/cli_create.py:127-135` |
| `.env` のキー（読む側） | `GOOGLE_API_KEY` / `GEMINI_API_KEY`（`google/genai/_api_client.py:136-137`）、`GOOGLE_GENAI_USE_ENTERPRISE`（旧 `GOOGLE_GENAI_USE_VERTEXAI` は deprecated・`google/adk/utils/env_utils.py:63-79`）、`GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION`（`google/adk` 内の `environ.get` 多数） | grep 結果 |
| `Runner.run_async` | `run_async(*, user_id, session_id, invocation_id=None, new_message=None, state_delta=None, run_config=None, yield_user_message=False)`。`InMemorySessionService.create_session(*, app_name, user_id, state=None, session_id=None)` は **async** | `inspect.signature` |
