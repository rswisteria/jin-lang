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

Phase 2（`jin-adk`）のテンプレート（`packages/jin-adk/src/jin_adk/templates/agent.py.j2`）はこの実測値に固定する。

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

LLM に見えるツール名は `.jin` の `tools[].name` ではなく **ADK 上の名前**（`kind: tool` → `FunctionTool.name == func.__name__`、
`builtin` → その名、`summon` → circle 名・実測）。`tools[].name` は静的検証と描画にだけ使う（要件書 §3.3）。
同じ circle の中で ADK 上の名前が重なる構造は §3.1 のコンパイル時エラー（ADK 2.8.0 は警告だけで後勝ちにし、片方が呼べなくなる）。

### 2.3 flow.exit

`BaseAgent` を継承した判定エージェント（`StateCheckAgent`）を生成し、条件成立時に
`EventActions(escalate=True)` を返す。`LoopAgent.sub_agents` の末尾に置く。
`BaseAgent._run_async_impl(self, ctx) -> AsyncGenerator[Event, None]` を override する（実測）。

DP-JIN-CODEGEN-RUNTIME-01（案 A・人間承認済み・ADR-008）により、`StateCheckAgent` のクラス本体は
生成物 `agent.py` に毎回埋め込む（生成物が自己完結し、`jin` パッケージを import しない）。

- **重複の扱い**（ADR-008 の condition・Phase 2 で決定）: `flow.exit` を持つ loop circle が複数あっても
  クラス定義は **1 ファイルに 1 回**、インスタンスは loop ごとに `<circle 名>_exit_check` という名前で作る。
  毎回クラスを展開すると同名クラスの再定義になり diff しにくい（NFR-GEN-001）。1 定義に集約しても
  生成物の自己完結性は変わらない
- 判定エージェントの名前 `<circle 名>_exit_check` が既存の circle 名と衝突したらコンパイル時エラー（§3.1）
- 生成物のヘッダに「StateCheckAgent はコピーであり jin 側の変更は反映されない。`jin build` で再生成すること」を書く
- 等値比較の規則は `docs/spec/model.md` §3.4（`output_key` は LLM の応答を **str** で入れるため、
  JSON として読んでから同じ型で比べる）。実装は生成物内の `_state_matches`

### 2.4 実行とトレース

- `Runner` は**全キーワード引数**。`session_service` が必須（実測）
- トレース JSONL の `agent` は `Event.author`、`ts` は `Event.timestamp`（epoch 秒・float）から取る。
  `{ seq, ts, agent, kind, name, pointer, input, output }` は **Jin 側で組み立てる派生スキーマ**であり、
  ADK の `Event` をそのまま書くのではない。実装は `jin_adk.trace`
- `pointer` は ADR-009（DP-JIN-TRACE-POINTER-01 案 B）: コード生成時に作る対応表
  （ADK の agent 名 / `tools[]` の添字 / `delegate[]` / `flow.exit` → JSON Pointer）を実行時に引く。
  対応表は生成物に埋め込まない。**引けなかった行は `pointer: null` にして残し、理由を stderr に出す**
  （黙って落とさない）。生成物を `jin run` を経由せず `adk run` で単体実行したときは pointer は付かない

<!-- machine-readable: trace-kinds -->

| kind | いつ | `name` | `pointer` | `input` / `output` |
|---|---|---|---|---|
| `model` | テキスト part（`partial` でない）。`function_call` と同居するときも出す（順序は text → tool）。part の無い event も `model`。`Event.error_code` / `error_message` を持つ event は `output` = `{"error_code", "error_message"}`（空応答の正常終了に見せない） | `core` のモデル文字列 | `/circles/i/core` | `output` = 応答テキスト（失敗時は error の辞書） |
| `tool` | `function_call` / `function_response` の part（1 part = 1 行）。**`transfer_to_agent` の `function_call` は行にしない**（下の `transfer` 行が応答側で出る） | ADK のツール名（`FunctionTool.name == func.__name__`） | `/circles/i/tools/j` | 呼び出し行は `input` = 引数、応答行は `output` = 戻り値 |
| `transfer` | `actions.transfer_to_agent`。ADK の transfer は「model が `transfer_to_agent(agent_name=…)` を `function_call`」→「その `function_response` event に `actions.transfer_to_agent` が立つ」の 2 event で、行にするのは**後者だけ**。**同じ event に同居する他ツールの応答行は残す**（LLM が 1 ターンで `web_search` と transfer を並列に呼ぶと応答は 1 event にまとまる。行順は `tool` → `transfer`。transfer 自身の `function_response` は行にしない・F-C-P2-101） | 転送先 agent 名 | `/circles/i/delegate/k` | `input` = `{"to": 転送先}` |
| `escalate` | `StateCheckAgent` の判定イベント（一致しなかった回も含む） | loop circle 名 | `/circles/i/flow/exit` | `input` = `{key, expected}` / `output` = `{actual, matched}` |
| `escalate` | StateCheckAgent 以外が立てた `actions.escalate`（`exit_loop` builtin など）。同じ event の `tool` 行の**後**に足す（tool 行は消えない） | author（escalate した agent 名） | `/circles/i` | `input` / `output` = null |
| `final` | 実行全体の**最後**の行が `model` だったとき、その行を `final` に付け替える（`output` が error の辞書なら失敗で終わった行） | `model` と同じ | `model` と同じ | `model` と同じ |

<!-- /machine-readable -->

- `seq` は 1 始まりの連番。ストリーミングの部分応答（`Event.partial`）は行にしない（確定イベントと二重になる）
- 実行全体の最後が `escalate`（loop の終了判定）や `tool` のときは `final` 行は無い
- **summon（`AgentTool`）先の内部イベントは行にならない**（ADK 2.8.0 の `AgentTool.run_async` は内部 `Runner` で子を回し、
  外側には `function_response` しか流さない・`google/adk/tools/agent_tool.py`）。summon 先の `model` 行・pointer `/circles/i/core`・
  子の中のツール呼び出しはトレースに現れない。Phase 3 の trace overlay では summon 先の陣が常に「未発火」に見える（`phase2-handoff.md` §6）
- 表の pointer 列は `jin_adk.trace.KIND_POINTERS` と一致する（`tests/spec/test_spec_consistency.py` が kind ごとに突合）

## 3. Jin で表現できない ADK 機能

`planner` / `output_schema` / `MCPToolset` / `code_executor` などは v1 では生成しない。
**ADK に対応物のない Jin 構造はコンパイル時エラーとする。黙って落とさない**（NFR-FAIL-001）。

### 3.1 コンパイル時エラーの一覧（`jin build` / `jin run` の `BuildError`）

`jin check` を通ったモデルに対して、コード生成時に落とすもの。診断コードは増やさない
（`CLAUDE.md` / ADR-012）。exit 1 で「何が悪いか + どう直すか（hint）+ pointer」を出す。
fixture は `tests/fixtures/build-errors/`（各 1 件・`jin check` は通り `generate` は落ちる）。

<!-- machine-readable: build-errors -->

| fixture | 構造 | 理由（ADK 2.8.0 実測） |
|---|---|---|
| `two_out_states` | 1 circle に `out: true` の state が 2 件 | `LlmAgent.output_key` は単一値（§5） |
| `circle_name_not_identifier` | circle 名が Python の識別子でない | `BaseAgent.name` は `isidentifier()` を要求（`base_agent.py:651`） |
| `circle_name_user` | circle 名が `user` | ADK が利用者入力用に予約（同 `:658`） |
| `circle_name_keyword` | circle 名が Python の予約語（`class` など） | 生成コードの変数名になる。`isidentifier()` は通るが SyntaxError |
| `reserved_name_collision` | circle 名が生成コードの名前（`LlmAgent` / `root_agent` …）または生成コードが参照する**組み込み名**（`str` / `isinstance` / `ValueError` / `json` …）と同じ | 変数の上書き。組み込み名は `_state_matches` / `StateCheckAgent` が実行時に `TypeError` になる（`jin_adk.codegen.RESERVED_NAMES`） |
| `circle_name_not_nfkc` | circle 名が NFKC 正規形でない（全角 `ｒｏｏｔ＿ａｇｅｎｔ` など） | Python は識別子を NFKC 正規化して束縛する（PEP 3131）。`isidentifier()` は通るが `root_agent` と同じ変数になり、予約名検査を迂回して root を乗っ取れる |
| `builtin_name_collision` | circle 名が `builtin` の名前（`google_search` など）と同じ | `from google.adk.tools import google_search` を `google_search = LlmAgent(...)` が上書きし、`tools=[google_search]` が agent を指す |
| `adk_tool_name_duplicate` | 1 circle の `tools[]` が ADK 上で同じ名前になる（`pkg_a:run` と `pkg_b:run`、`ref` の callable 名と同名の `builtin` …） | ADK 2.8.0 は `Duplicate tool name` を警告するだけで後勝ちにし、片方が呼べない。import の別名化では防げない（`FunctionTool.name == func.__name__`）。**残存（実行時）**: `ref` 先モジュールが `search_again = web_search` のような**別名束縛**をしていると attribute 名は違うので `jin build` は通り、実行時に ADK 上で同名になる。`jin run` はその tool 行の pointer を null にし、stderr に「同名の ADK ツール … 片方が呼べません」を出す（`RuntimeTable.bind_tools`・F-C-P2-002） |
| `root_has_parent` | root circle が別 circle の `flow.steps` / `delegate` / `summon` に現れる | `root_agent.parent_agent` に別の agent が付き、その親は `jin run` で一度も使われない（`jin check` は root の入次数を見ない。診断化は DP-REVIEW-JIN-P2-001 として未決） |
| `exit_checker_name_collision` | `<loop 名>_exit_check` という circle がある | StateCheckAgent の名前と衝突 |
| `builtin_unknown` / `builtin_is_a_class` | `builtin` が `google.adk.tools` のツールインスタンス / 関数でない | `from google.adk.tools import <名>` できない |
| `ref_malformed` | `ref` が `module.path:callable` 形式でない | import 文に流せない（`jin check` は `--resolve` 時しか形式を見ない） |
| `await_on_summon` | `boundary.await` が `summon` / `builtin` を指す | `LongRunningFunctionTool(func)` は関数しか包めない |
| `flow_circle_with_tools` / `..._with_instruction` / `..._with_delegate` / `..._with_out_state` / `..._with_model_guard` | flow circle に `tools` / `instruction` / `delegate` / `out: true` / `before_model` 系 guard | workflow agent は `name` / `description` / `sub_agents` / `before_agent` / `after_agent` しか持てない |
| `rune_adk_template_conflict` | `instruction.rune` に `{{lit}}` / `{a}}` / `{key?}` / `{artifact.x}` / `{app:key}` | ADK 2.8.0 のテンプレート解釈が Jin の読みと食い違う（`docs/spec/model.md` §3.1） |

<!-- /machine-readable -->

flow circle の `boundary.await` は `jin check` が JIN070 で先に落とす（flow circle は `tools` を持てず、`await` は `tools` に無い）ので
fixture は無い。`_validate_flow_circle` の `await` 枝は `JinFile.model_validate` を直接呼ぶ経路（ライブラリ利用）の防御として残す。

`source_name`（`jin build` / `jin run` が渡す `.jin` の**ファイル名**）は `.jin` 本文の検査を通らないため、ヘッダには
`py_literal` を通した 1 行のリテラルとして載せる（改行入りの名前がコメントを文にしない）。CLI は制御文字・不正 UTF-8 バイトを
含むファイル名を入口で exit 2 にする（`jin_cli.main._require_jin_file`）。

## 4. 実装状況

Phase 2 で `jin-adk`（`codegen` / `build` / `runtime` / `trace` / `fake_llm`）と
`jin build` / `jin run` を実装した。生成コードのテンプレートは
`packages/jin-adk/src/jin_adk/templates/agent.py.j2`、スナップショットは
`packages/jin-adk/tests/__snapshots__/`。
`jin_core` は `google.adk` を import しない（import-linter の `forbidden` 契約で CI が落とす・ADR-004）。

## 5. 表現できるが v1 で落とす構造

| Jin の構造 | 扱い |
|---|---|
| 1 circle に `out: true` の state が 2 件以上 | `LlmAgent.output_key` が単一値のため Phase 2 のコード生成時エラー。診断コードは増やさない（`CLAUDE.md` / ADR-012） |
| `core` と `flow` の両立 / 両方欠落 | JIN022（Phase 1 の意味検査で落ちる） |
| §3.1 の各行 | Phase 2 のコード生成時エラー（`BuildError`） |

## 6. `jin run` の意味論（要件書 §3.4）

`jin run <file> "<prompt>" [--session <id>] [--trace out.jsonl] [--model fake]`

1. `jin check` と同じ診断を行い、error があれば exit 1
2. §3.1 の検査を通してコードを生成し、`tempfile.mkdtemp`（所有者だけが読める 0700）に書く
3. `agent.py` を一意なモジュール名で import する。**これは任意コード実行である**（生成コードが
   `ref` のモジュールを import する）。`jin run` は `research.tools` のような `ref` を
   カレントディレクトリから解決できるよう、**cwd をこの import の間だけ `sys.path` の末尾に足し、import が
   終わったら（例外時も）必ず外す**（console script は cwd を含めないため。CLI `jin_cli.main.run` が
   `run_model_async(extra_sys_path=[cwd])` で頼み、`jin_adk.runtime._sys_path_window` が足して外す。CLI 自身は
   `sys.path` を触らない。DP-IMPL-JIN-P2-SYSPATH-01 の再々判断）。末尾なので site-packages にある名前は本物が先に
   解決され、手順 6 の Runner 実行中は cwd が `sys.path` に無い（ADK が LLM 要求のたびに遅延 import する未インストールの
   任意依存 `anthropic` などを cwd から解決させない・F-S-P2-101）。**残存**: import の間は cwd のモジュール（`ref` 先・
   `builtin` の遅延 import 先 `mcp` など）が実行されるので、信頼しないディレクトリを cwd にして `jin run` しない。
   `ref` 先の関数が実行時に遅延 import する名前は cwd から解決できない（`PYTHONPATH` に委ねる）
4. `--model fake` のときは agent 木（`sub_agents` / `AgentTool.agent`）を走査し、全 `LlmAgent.model` を
   `jin_adk.fake_llm.FakeLlm`（固定応答 `fake-response`・ネットワーク不要）に差し替える。
   `StateCheckAgent` は触らない。`--model` に指定できるのは `fake` だけ（実モデルは `.jin` の `core`）
5. `.jin` が宣言した全 circle の `state[].name` を **`None` で seed** して `InMemorySessionService` の
   セッションを作る。実測（google-adk 2.8.0）: `instruction` の `{key}` が `session.state` に無いと
   ADK は `KeyError` を投げて実行が落ちる（`google/adk/utils/instructions_utils.py:174`）。
   `examples/researcher` の `{findings}` は自分の `output_key` なので初回は必ず未設定になる。
   ADK は `None` を空文字で描画する（実測）。**これは `jin run` の挙動であり、生成物を `adk run` で
   単体実行したときには効かない**（未設定 key を参照する rune は `adk run` では KeyError になる）
6. `Runner(agent=root_agent, app_name=<root 名>, session_service=...)` で実行し、イベントを
   §2.4 の行にして stdout（1 行 1 イベント）と `--trace`（JSONL）に流す。`--session <id>` は表示用の
   **ラベル**であり、`InMemorySessionService` は実行ごとに新しく作る（同じ ID を渡しても前回の state は
   引き継がれない。永続化は v1 の範囲外）。summon 先の内部イベントは §2.4 のとおり行にならない
7. `--trace` は生成（手順 2）が通ってから開き、最初の行を書く直前に切り詰める（`BuildError` / `RunError` で
   前回のトレースを 0 バイトにしない）。ツール引数・state の実値・モデル出力を含む成果物なので **0600** にする
   （新規は `O_CREAT` の mode、**既存ファイルでも `os.fchmod` で 0600 に絞る**。前回 0644 で作ったファイルを指定し直しても
   world-readable のまま書かない・F-C-P2-103）
   （`decision-conformance.md` §2.22）。リンクは辿らない
8. 終了時に一時ディレクトリを必ず消す（消せなければ stderr に 1 行）。生成コードの import 中・実行中の例外は
   `KeyboardInterrupt` 以外の `BaseException`（`sys.exit()` を含む）まで捕まえて exit 1 にする。
   ただし**実行中**（ツール関数の中）の `sys.exit()` は asyncio が `SystemExit` をタスクの結果にせず
   ループの外へ再送出するので、`run_model_async` では捕まえられない（届くのは `CancelledError`）。
   `asyncio.run` を呼ぶ側（CLI の `run`・同期 `run_model`・Phase 4 の pygls）が `except SystemExit` で包み、
   `実行に失敗しました（SystemExit: <code>）` を stderr に出して exit 1 にする（トレースバック無し・F-S-P2-102）。
   ツール関数の `asyncio.CancelledError` も成功扱いにしない（F-S-P2-201 / 202）: root が LlmAgent のとき ADK は root の
   cancel を握って正常復帰するので、Runner 完走後に**応答の無い function_call**（`boundary.await` の long-running な
   pause = `Event.long_running_tool_ids` は除く）があれば exit 1。workflow agent 配下では `CancelledError` が Runner から
   出てくるので、`Task.cancelling()` が 0（外からのキャンセルでない）なら exit 1・1 行
