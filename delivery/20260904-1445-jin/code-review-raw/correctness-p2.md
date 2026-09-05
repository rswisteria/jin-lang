# Stage 5 review — correctness（Phase 2 / jin-adk）

- 対象: ブランチ `feat/jin-phase2-adk` の未コミット作業ツリー（`git status --short` の全変更 + untracked）。
  中心は `packages/jin-adk/src/jin_adk/{codegen,build,runtime,trace,fake_llm}.py`、`templates/agent.py.j2`、
  `packages/jin-cli/src/jin_cli/main.py` の `build` / `run`、テスト一式、`docs/spec/{adk-mapping,model}.md`
- 正典: `jin-requirements.md` §2.1 / §3 / §9、`docs/spec/adk-mapping.md`、`delivery/20260904-1445-jin/adk-api-probe.md`、
  google-adk 2.8.0 の site-packages 実物（`.venv/lib/python3.14/site-packages/google/adk/`）
- 方法:
  1. 全ソース・テスト・fixture・仕様を読み、`jin_core/model.py` の全フィールドを列挙して ADK への対応と「黙って落ちる」経路を確認
  2. 疑った点は隔離コピー（`scratchpad/review-correctness/`・`git ls-files` で複製・`PYTHONPATH` でコピー側を優先）で
     `generate` → `load_generated` → `run_model(FakeLlm)` を実際に走らせて確認。実験スクリプトは同ディレクトリの
     `exp1_collisions.py` / `exp2_trace.py` / `exp3_misc.py`
  3. 変異検証: 同コピーの実装に 1 件ずつ変異を入れて **全スイート**を回す（`mutate.py`・下表）。
     素の状態の全スイート: **exit 0（全 passed・syrupy 2 snapshots passed）**。件数は末尾の表を参照
  4. 実ツリーは一切変更していない（本ファイルの追加のみ）
- 自己申告（implementation-notes P2 節 / decision-conformance §2.13〜§2.21・phase2-mutations 31/31）は読んだが根拠にしていない。
  実装者のハーネスは「自分が守ったつもりの箇所」を狙っており、本レビューは examples に**無い**構造
  （delegate / builtin / 同名 ref / 同種 guard 複数 / AgentTool 経由の子 / exit_loop）を中心に見た

confidence の基準: 100 = 実測で直接確認、75 = 実際に踏むと確認済み（間接）、それ未満は読解のみ。

## 上位 5 件（親のトリアージ用）

| ID | 要旨 | conf |
|---|---|---|
| F-C-P2-001 | `ref` の callable 名が `builtin` 名と同じだと、生成コードの import が builtin を**黙って**上書きし、利用者関数が builtin の位置に入る | 100 |
| F-C-P2-002 | 1 circle 内の 2 つの `tool` が同じ ADK ツール名（同一 ref の二重宣言・別モジュール同名 callable）になると ADK が片方を shadow して呼べなくなるが `jin build` は成功する。既存テストはこの壊れた生成を「正しい」と固定している | 100 |
| F-C-P2-004 | `delegate` の transfer が、`transfer_to_agent` の function_call を `kind: tool / pointer: null` で記録し stderr に「pointer を解決できませんでした」を出す。引ける経路で「引けない」と報告している | 100 |
| F-C-P2-003 | circle 名が `builtin` 名と同じでも `BuildError` にならず、`jin build` が import 不能な生成物を書く（NFR-FAIL-001 の「コンパイル時エラー」ではない） | 100 |
| F-C-P2-011 | `RuntimeTable.bind_tools` の添字対応を「常に tools[0]」に壊しても全スイートが緑。tools[1..] の pointer が間違っていても検出できない | 100 |

---

## 1. バグ・論理誤り（実測済み）

### F-C-P2-001 — `ref` の callable 名が builtin 名と衝突すると builtin が黙って置き換わる
- confidence: **100**
- 場所: `packages/jin-adk/src/jin_adk/codegen.py:391`（`_plan_imports` の `needs_alias`。`taken` に builtin 名が入っていない）、
  `templates/agent.py.j2:12-22`（`:13` の `from google.adk.tools import …` を `:18-` の ref import より**前**に出す）、`codegen.py:537`（`_validate_core_circle`・衝突検査なし）
- 何が起きるか: `builtin: google_search` と `ref: mytools:google_search` を同じファイルに書くと
  ```python
  from google.adk.tools import FunctionTool, google_search
  from mytools import google_search          # ← builtin を上書き
  root_agent = LlmAgent(..., tools=[google_search, FunctionTool(google_search)])
  ```
  が生成され、`tools[0]` は `GoogleSearchTool` ではなく利用者の `function` になる。`BuildError` も警告も出ない
  （`.jin` の意図と違う道具で動く。NFR-FAIL-001「黙って落とさない」違反）
- 再現（`exp1_collisions.py` 1b）:
  ```
  1b generate: OK (BuildError なし)
      from google.adk.tools import FunctionTool, google_search
      from mytools import google_search
      root_agent = LlmAgent(name="Root", model="m", tools=[google_search, FunctionTool(google_search)])
  AttributeError: 'function' object has no attribute 'name'   # tools[0] が function になっている
  ```
- 修正案: `generate` で builtin 名の集合を `taken` に足す（`_plan_imports(model, taken | builtin_names)` → 同名 ref は
  `<module>__<attr>` に別名化される）。加えて circle 名 vs builtin 名は F-C-P2-003 の検査で落とす

### F-C-P2-002 — 同じ ADK ツール名になる `tool` が 1 circle に 2 つあっても `jin build` が通り、片方が呼べない
- confidence: **100**
- 場所: `codegen.py:537-562`（`_validate_core_circle`・ADK 側のツール名 = `func.__name__` の重複を見ていない）、
  `packages/jin-adk/tests/test_codegen.py::test_same_callable_name_from_two_modules_gets_aliased`（壊れた生成を正として固定）
- 何が起きるか: (a) 同じ `ref` を 2 つの `tools[].name` で宣言（JIN010 は Jin 側の `name` しか見ない）、
  (b) `pkg_a.tools:run` と `pkg_b.tools:run`（import は別名化されるが `FunctionTool.name` はどちらも `run`）。
  ADK 2.8.0 は構築時に `WARNING:root:Duplicate tool name 'run': the previously registered tool is shadowed and can no longer be called.`
  を**ログに出すだけ**で通し、後勝ちのツールだけが呼ばれる。`jin build` は exit 0 で生成物を書く
- 再現（`exp3_misc.py` 3a と追加実験）:
  ```
  WARNING:root:Duplicate tool name 'run': the previously registered tool is shadowed ...
     tool run None {'x': '1'} None
     tool run None None {'result': 'B:1'}     # pkg_a の run は呼ばれない
     unresolved: ["agent 'R' に同名の ADK ツール 'run' が 2 つ以上あり、どの tools[] か決められない"]
  ```
  `jin run` の stderr は「pointer が決められない」と言うが、実際の問題は「片方が呼べない」であり、文言も誤解を招く
- 修正案: `_validate_core_circle` で「ADK 上のツール名」（`kind: tool` → `ref` の callable 名、`builtin` → その名前、
  `summon` → circle 名）を circle 内で集計し、重複したら `BuildError`（pointer は 2 つ目の `tools[j]`、hint は
  「callable 名が ADK のツール名になる。別名の関数に包むか 1 つにまとめる」）。上記テストは「別名 import される」から
  「BuildError になる」へ書き換える。`docs/spec/adk-mapping.md` §3.1 の表にも行を足す（仕様側にもこの規則が無い）
- 関連: `trace.py` `RuntimeTable.bind_tools` の「同名は None」経路は、この BuildError を入れると到達不能になる

### F-C-P2-003 — circle 名が builtin 名と同じでも `BuildError` にならず、生成物が import できない
- confidence: **100**
- 場所: `codegen.py:299-331`（`_check_identifier`。`:324` の `RESERVED_NAMES` 判定に builtin 名が無い）
- 何が起きるか: circle `google_search` を定義し別 circle が `builtin: google_search` を使うと
  `from google.adk.tools import google_search` の後で `google_search = LlmAgent(...)` が代入され、`tools=[google_search]`
  が LlmAgent を指す。`generate` は成功し `jin build` は 3 ファイルを書く。`adk run` / `jin run` で初めて
  `ValidationError: Agent 'google_search' cannot be wrapped as a NodeTool` で落ちる（ADK の文言で、Jin の pointer も hint も無い）
- 再現（`exp1_collisions.py` 1a）:
  ```
  1a generate: OK (BuildError なし)
  1a import failed: RunError 生成コードの import に失敗しました（ValidationError: ... Agent 'google_search' cannot be wrapped as a NodeTool ...
  ```
- 修正案: `_validate` で「使われている builtin 名」と「ref の束縛名」を circle 名と突き合わせて `BuildError`（circle 名側を指す）

### F-C-P2-004 — delegate の transfer が `tool / pointer: null` の余計な行と stderr の苦情を出す
- confidence: **100**
- 場所: `packages/jin-adk/src/jin_adk/trace.py:202-215`（`classify` の function_call 走査が `transfer_to_agent` を普通のツールとして扱う）、
  `trace.py:124-129`（`RuntimeTable.tool` が `_note` で unresolved に積む）
- 何が起きるか: ADK は transfer を「model が `transfer_to_agent(agent_name=…)` を function_call」→「その function_response の
  `actions.transfer_to_agent` が立つ」の 2 event で表す。前者が `kind: tool / name: transfer_to_agent / pointer: null` になり、
  `jin run` は exit 0 のまま stderr に `pointer を解決できませんでした: agent 'Boss' のツール 'transfer_to_agent' は .jin に無い`
  を出す。examples に `delegate` が無いので `test_run_with_fake_model_completes_and_writes_a_valid_trace` の
  「pointer が全部 non-null」「stderr に苦情が無い」の両方が delegate を持つ `.jin` では成立しない
- 再現（実ツリーの editable install で `jin run` を CliRunner 経由・台本 FakeLlm）:
  ```
  [1] Boss tool transfer_to_agent (pointer: null) {"agent_name": "Worker"}
  [2] Boss transfer Worker /circles/0/delegate/0 {"to": "Worker"}
  [3] Worker final gemini-2.5-flash /circles/1/core done
  pointer を解決できませんでした: agent 'Boss' のツール 'transfer_to_agent' は .jin に無い（pointer: null）
  ```
- 修正案: `classify` の function_call ループで `call.name == "transfer_to_agent"` を `kind: transfer`（pointer は
  `table.delegate(author, args["agent_name"])`、`input={"to": …}`）にするか、その function_call を行にしない
  （応答側の `transfer` 行が既にある）。どちらにするかは `docs/spec/adk-mapping.md` §2.4 の `transfer` 行に書く。
  少なくとも unresolved に積まない。`tests/test_runtime.py` に delegate を持つモデルの end-to-end を足す

### F-C-P2-005 — `exit_loop` builtin の応答行が消え、`escalate` 行の `name` / `pointer` が仕様表と違う
- confidence: **100**（挙動）/ 仕様との食い違いは両方を指摘
- 場所: `trace.py:182-185`（`classify` が `if actions.escalate:` を function_response 走査 `:216` より先に評価）、
  `docs/spec/adk-mapping.md` §2.4 `trace-kinds` 表の `escalate` 行（`name` = loop circle 名 / `pointer` = `/circles/i/flow/exit` と一本で書いてある）
- 何が起きるか: loop 内の LlmAgent が `builtin: exit_loop` を呼ぶと、function_response event に `actions.escalate=True` が付くので
  `tool` の応答行（`output`）が出ず、代わりに `escalate / name=<LlmAgent 名> / pointer=/circles/i / input=null / output=null` になる。
  仕様表は `name` を「loop circle 名」、`pointer` を `/circles/i/flow/exit` と定めているが、コードの非 checker 経路は author と circle pointer を入れる
- 再現（`exp2_trace.py` 2b / 2e）:
  ```
  {"seq": 1, "agent": "A", "kind": "tool", "name": "exit_loop", "pointer": "/circles/1/tools/0", "input": {}, "output": null}
  {"seq": 2, "agent": "A", "kind": "escalate", "name": "A", "pointer": "/circles/1", "input": null, "output": null}
  2e non-checker escalate: [('escalate', 'Researcher', '/circles/0')]
  ```
- 修正案: 仕様側で「checker 以外の escalate は `name` = author / `pointer` = `/circles/i`」を明記するか、コード側で
  function_response が同居する event は tool 行 + escalate 行の両方を出す（1 part = 1 行の原則に合う）。
  現状は spec と code のどちらとも一致しない状態

### F-C-P2-006 — AgentTool（`summon`）経由で動く子 agent のイベントがトレースに一切出ない
- confidence: **100**（挙動）
- 場所: `trace.py` / `runtime.py`（ADK の `AgentTool.run_async` が内部 `Runner` で子を回し、外側の `run_async` には
  function_response しか流さない・`google/adk/tools/agent_tool.py:264`）、`docs/spec/adk-mapping.md` §2.4 / §6（言及なし）
- 何が起きるか: researcher で Summarizer を summon すると、行は `tool Summarizer`（呼び出し）/ `tool Summarizer`（応答）/
  親の `final` だけ。Summarizer の `model` 行・pointer `/circles/1/core` は永遠に出ず、子の中でのツール呼び出しも見えない。
  `swap_models` は子に届いている（FakeLlm で完走）ので実行は正しいが、要件書 §3.4「イベントを標準出力に流す」の観点では
  summon 先が黒箱になる。これは ADK の仕様であり Jin 側で直せるかは別だが、**仕様書に書かれていない**
- 再現（`exp2_trace.py` 2c）:
  ```
  {"agent": "Researcher", "kind": "tool", "name": "Summarizer", "pointer": "/circles/0/tools/2", "input": {"request": "sum this"}}
  {"agent": "Researcher", "kind": "tool", "name": "Summarizer", "pointer": "/circles/0/tools/2", "output": {"result": "done"}}
  {"agent": "Researcher", "kind": "final", ...}
  ```
- 修正案: `docs/spec/adk-mapping.md` §2.4 に「summon 先の内部イベントは行にならない（ADK 2.8.0 の AgentTool は内部 Runner で
  実行し外へ event を出さない）」を明記。将来 Phase 3 の trace overlay で summon 先の陣が常に「未発火」に見えることを設計側に伝える

### F-C-P2-007 — text と function_call が同居する event で text が黙って捨てられる
- confidence: **100**
- 場所: `trace.py:230-231`（`classify` の `if rows: return rows`）
- 何が起きるか: Gemini は「検索します」+ `function_call` を 1 応答で返すことが普通にある。その event は `tool` 行だけになり、
  モデルのテキストは行にもならず `output` にも残らない。FakeLlm は 1 part しか返さないのでテストでは踏まない
- 再現（`exp2_trace.py` 2d）: parts = [text "I will search", function_call web_search] → 出力は `tool` 1 行のみ
- 修正案: text part があれば `model` 行も出す（順序は text → tool）。仕様 §2.4 の `model` 行「LLM のテキスト応答」に
  「function_call と同居するときも出す」を追記

### F-C-P2-008 — `equals` 文字列の前後空白は永遠に一致しない（仕様表は対称に読める）
- confidence: **100**
- 場所: `templates/agent.py.j2:41`（`_state_matches` の `text == expected`。`expected` は strip しない）、
  `docs/spec/model.md` §3.4 `flow-exit-equality` 表 string 行「前後の空白を除いて文字列どうしを比較（`"yes"` = `" yes "`）」
- 何が起きるか: `.jin` に `equals: " yes"` と書くと state 側が strip されるので `" yes"` にも `"yes"` にも一致しない
- 再現（`exp2_trace.py` 2f）: `_state_matches(' yes', ' yes') = False`
- 修正案: 仕様を「state 側だけ strip する（`equals` は書いたまま）」と明記するか、実装で `expected.strip()` も行う。
  どちらでも `test_state_matches_semantics` に `(" yes", "yes")` 系のケースを足す

### F-C-P2-009 — `jin run --trace` は BuildError で落ちても既存トレースを空にする
- confidence: **100**
- 場所: `packages/jin-cli/src/jin_cli/main.py:650`（`run` が `O_TRUNC` で開いてから `:657` で `run_model` を呼び、`generate` はその中）
- 何が起きるか: `jin run bad.jin "go" --trace t.jsonl` が §3.1 の BuildError で exit 1 になっても `t.jsonl` は 0 バイトになる
- 再現（`exp3_misc.py` 3e）: `exit 1 | trace bytes after failed run: b''`
- 修正案: `generate` を CLI 側で先に呼んで BuildError を出し切ってからトレースを開く（`run_model` に `project` を渡す形にする）か、
  一時ファイルに書いて成功時に rename する

## 2. テストの穴（変異検証で緑のまま）

### F-C-P2-010 — 同種 `guards[].on` 複数 → リスト（要件書 §3.3）を検証するテストが無い
- confidence: **100**（M2 全スイート緑）
- 場所: `codegen.py:669`（`_callback_lines`）、`packages/jin-adk/tests/test_codegen.py` / `test_runtime.py`
- `value = names[0]`（2 つ目以降を捨てる）に壊しても全スイート緑。要件書 §3.3「同種が複数あればリストで渡す」の明文要件が固定されていない。
  実装自体は正しい（`exp3_misc.py` 3d: `before_model_callback = [pii_filter, audit_log]`）
- 修正案: `test_runtime.py` に同種 guard 2 件のモデルを import して `before_model_callback == [f, g]` を見るテストを足す

### F-C-P2-011 — `RuntimeTable.bind_tools` の添字対応が壊れても緑
- confidence: **100**（M3 緑）
- 場所: `trace.py:101`（`bind_tools`）、`packages/jin-adk/tests/test_runtime.py::test_tool_call_rows_point_at_the_tool_element`（添字 0 の `web_search` しか見ない）
- `entry.tools[j]` → `entry.tools[0]` に壊しても全スイート緑。`fetch_page`（tools/1）や `publish`（tools/3）を呼ぶ台本があれば赤になる
- 修正案: 台本を `FakeToolCall(name="publish")` にして `/circles/0/tools/3` を確認するケースを足す

### F-C-P2-012 — `_state_matches` の「bool を数値に一致させない」枝に該当ケースが無い
- confidence: **100**（M1 は snapshot だけが赤。snapshot を除いた `test_runtime.py` + `test_build_run.py` は 62 passed）
- 場所: `templates/agent.py.j2:49`（`_state_matches` の数値枝）、`test_runtime.py::test_state_matches_semantics`
- `and not isinstance(value, bool)` を消すと `(1, "true")` / `(0, "false")` が一致するようになるが、16 ケースにこの組は無い
  （`(3, "true", False)` は `True == 3` が偽なので枝を通らなくても不一致）。snapshot はテンプレート文字列の変化を拾うだけで、
  最初から欠けていた場合は検出しない
- 修正案: `(1, "true", False)` と `(0, "false", False)` を parametrize に足す

### F-C-P2-013 — flow circle の `instruction` / `delegate` 検査に fixture が無い（仕様表には列挙されている）
- confidence: **100**（M21 / M22 とも全スイート緑）
- 場所: `codegen.py:502`（instruction）/ `:508`（delegate）/ `:529`（await・到達不能）、`tests/fixtures/build-errors/`（`flow_circle_with_{tools,out_state,model_guard}` の 3 つだけ）、
  `docs/spec/adk-mapping.md` §3.1 の表（`instruction` / `delegate` / `await` も書いてある）、
  `tests/spec/test_spec_consistency.py::test_build_error_table_covers_every_fixture`（token 抽出なので構造の網羅は見ていない）
- 補足: `_validate_flow_circle` の `await` 枝は到達不能。flow circle は `tools` を持てず、`await` が `tools` に無ければ JIN070 で
  `jin check` が先に落ちる。到達不能な枝は消すか、到達不能である旨を書く

### F-C-P2-014 — `ts` が `Event.timestamp` 由来であることを固定するテストが無い
- confidence: **100**（M34 全スイート緑）
- 場所: `trace.py:164`、`docs/spec/adk-mapping.md` §2.4「`ts` は `Event.timestamp`」
- `ts = 0.0` に壊しても、テストは `isinstance(ts, float)` しか見ない

### F-C-P2-015 — flow circle の `description` / `delegate` 2 件以上の順序を固定するテストが無い
- confidence: **100**（M47 / M48 とも全スイート緑）
- examples の flow circle に `description` が無く、`delegate` は examples に存在しない。`sub_agents` を逆順に壊すと
  `PointerMap.delegate` の添字と実体がずれ、`transfer` の pointer が別の delegate を指す

## 3. 仕様とコードの食い違い・仕様の穴

### F-C-P2-016 — root が別 circle の子になれる（親付き root を黙って許す）
- confidence: **90**
- 場所: `jin_core/semantic.py`（root の入次数を見ない）、`codegen.py` `generate`（`root_agent.parent_agent = B` になる）
- `root: A`、`B.flow.steps = ["A"]` は `jin check` を通り（`exp3_misc.py` 3b: `ok=True []`）、生成物は `B = SequentialAgent(sub_agents=[root_agent])`
  を root_agent の後に出す。`jin run` は A だけを走らせ B は使われない。JIN012（循環）にも JIN013（多重親）にも当たらないため
  「書いたが効かない circle」が黙って残る（NFR-FAIL-001 の精神）。Phase 1 の範囲かもしれないが、Phase 2 で初めて実害（ADK が root に parent を付ける）が出る
- 修正案: `jin check` で「root は親を持てない」を診断（既存コードの流用）にするか、`generate` で `BuildError`

### F-C-P2-017 — `--session <id>` に観測できる効果が無い
- confidence: **100**
- 場所: `main.py` `run`、`runtime.py` `_run_async`（毎回新しい `InMemorySessionService`）
- 同じ `--session` で 2 回走らせても state は引き継がれない（`exp3_misc.py` 3h: run2 の `draft = v2`、run1 の `v1` は消える）。
  要件書 §3.4 はオプションの存在しか書いていないので誤りではないが、利用者は「セッションを続ける」と読む。
  `docs/spec/adk-mapping.md` §6 に「ID はラベルであり永続化しない」を書くか、Phase 2 の範囲外なら help 文で明示する

### F-C-P2-018 — `trace-kinds` 表の `transfer` / `escalate` 行が ADK の 2 event 構造を書いていない
- confidence: **100**（F-C-P2-004 / 005 の仕様側）
- `docs/spec/adk-mapping.md` §2.4: transfer は「model の function_call → response の `actions.transfer_to_agent`」の 2 event、
  escalate は「function_response に `actions.escalate` が乗る（exit_loop）」と「StateCheckAgent の判定 event」の 2 種があり、
  表はどちらも 1 行に潰している。実装が「どちらの event を行にするか」を決めているのに仕様に無い

## 4. 読解のみ（低・確信度は控えめ）

### F-C-P2-019 — `run_model` は稼働中のイベントループから呼べない
- confidence: **80**
- `runtime.py:211` の `run_model` が `asyncio.run` を使う。Phase 4 の `jin-lsp`（pygls は asyncio）や notebook から呼ぶと
  `RuntimeError: asyncio.run() cannot be called from a running event loop` → `except BaseException` で
  「実行に失敗しました（RuntimeError: …）」に化けて原因が読めない。async 版（`run_model_async`）を公開し CLI だけが `asyncio.run` する形が安全

### F-C-P2-020 — `write_project` の「中途半端に残さない」は `WriteRefused` の経路だけ
- confidence: **90**
- `build.py:177` `write_project`: 3 つ開いたあとの `handle.write` が `OSError`（ENOSPC 等）を投げると片付けが走らず、
  `--force` なら既存ファイルは `ftruncate` 済みで空のまま残る。docstring の主張より弱い。低頻度なので低

### F-C-P2-021 — `classify` は model error event を空の `model` 行にする
- confidence: **80**
- `Event.error_code` / `error_message`（probe に列挙あり）を見ないので、モデル呼び出し失敗は `output: ""` の `model`（最終なら `final`）行になり、
  失敗が「空応答で正常終了」に見える。Runner が例外を投げる経路は `RunError` になるが、event として返る失敗は黙る

### F-C-P2-022 — `_builtin_tool` は `BaseToolset` インスタンスも通すが、その先の tool 名は pointer に結べない
- confidence: **60**
- `codegen.py:425` `_builtin_tool` は `isinstance(obj, (BaseTool, BaseToolset))` を許す。`google.adk.tools.__all__` に toolset の**インスタンス**は
  2.8.0 では見当たらなかったので現状は実害なし。`runtime._tool_name` はクラス名を返すので、将来 toolset が来たら展開後のツール名と一致せず null になる

### F-C-P2-023 — `Circle.state[].type` と `tools[].name`（tool / builtin）は生成に一切使われない
- confidence: **100**（設計どおり・要件書 §3.2 の例と一致）
- `jin_core/model.py` の全フィールド走査の結果。黙って捨てているフィールドはこの 2 つだけで、どちらも要件書 §3.3 が「静的検証と表示用」と定めている。
  LLM に見えるツール名が `.jin` の `name` ではなく `func.__name__` になる点は `trace.py` の docstring にしか書かれていないので、
  `docs/spec/adk-mapping.md` §2.2 に一文足すとよい

### F-C-P2-024 — `test_unknown_author_gets_a_null_pointer_not_a_dropped_row` の `name` 検査が緩い
- confidence: **100**
- `packages/jin-adk/tests/test_trace.py:43` `assert "unresolved" in rows[0].name or rows[0].name == "Stranger"`: 実装は後者しか返さないので前者は空虚。`== "Stranger"` に絞る

---

## 変異検証の表（隔離コピー・全スイート・`-x`）

素の状態: `696 passed in 19.18s`（`pytest -p no:cacheprovider --no-header -W ignore`・`addopts` の `-q` と重ねると `-qq` になり
件数行が消えるので `-q` は付けない）。ハーネス: `scratchpad/review-correctness/mutate.py`（1 変異ずつ入れて全スイート→復元。
最後に `diff -q` で実ツリーと一致することを確認済み）。

| # | 対象 | 注入した変異 | 結果 |
|---|---|---|---|
| M1 | `agent.py.j2` `_state_matches` | `and not isinstance(value, bool)` を削除 | **RED**（`test_generated_agent_py_snapshot[pipeline]` のみ）。snapshot を除いて `test_runtime.py` + `test_build_run.py` を回すと **62 passed（緑）** → 意味論のテストは枝を見ていない（F-C-P2-012） |
| M2 | `codegen._callback_lines` | `value = names[0]`（同種複数の 2 つ目以降を捨てる） | **GREEN**（696 全部通る）→ F-C-P2-010 |
| M3 | `trace.RuntimeTable.bind_tools` | `entry.tools[j]` → `entry.tools[0]` | **GREEN** → F-C-P2-011 |
| M4 | `codegen.generate`（対照） | `checker_var` を `sub_agents` 末尾に足さない | **RED**（snapshot に加え、snapshot を外しても `test_swap_models_*` / `test_pipeline_trace_kinds_and_final` / `test_loop_exits_early_*` / `test_loop_runs_to_max_*` の 4 件が赤） |
| M5 | `runtime._declared_state`（対照） | `{}` を返す | **RED**（`test_run_with_fake_llm_completes_and_every_pointer_resolves[researcher]`） |
| M7 | `trace.classify`（対照） | function_response の `output` を `None` にする | **RED**（`test_tool_call_rows_point_at_the_tool_element`） |
| M12 | `codegen._dependency_order` | summon 先を辿らない | **RED**（researcher の Summarizer が root_agent の後に出て import が落ちる） |
| M17 | `codegen._plan_imports` | circle 名との衝突で別名にしない | **RED**（`test_ref_colliding_with_a_circle_name_gets_aliased`） |
| M21 | `codegen._validate_flow_circle` | `instruction` の検査を無効化 | **GREEN** → F-C-P2-013 |
| M22 | `codegen._validate_flow_circle` | `delegate` の検査を無効化 | **GREEN** → F-C-P2-013 |
| M25 | `trace.classify`（対照） | transfer の pointer を agent pointer にする | **RED**（`test_transfer_points_at_the_delegate_entry`） |
| M34 | `trace.classify` | `ts = 0.0`（`Event.timestamp` を使わない） | **GREEN** → F-C-P2-014 |
| M47 | `codegen._emit_workflow_agent` | flow circle の `description` を落とす | **GREEN** → F-C-P2-015 |
| M48 | `codegen._emit_llm_agent` | `sub_agents` を逆順にする（PointerMap の添字とずれる） | **GREEN** → F-C-P2-015 |
| M50 | `agent.py.j2` `_state_matches` | `text == expected.strip()`（`equals` 側も strip する挙動変更） | **RED**（snapshot のみ）。snapshot を除くと `test_runtime.py` **33 passed（緑）** → `equals` の空白を見るテストが無い（F-C-P2-008） |

対照 6 件（M4 / M5 / M7 / M12 / M17 / M25）が赤くなっているので、ハーネス自体は効いている。
緑のまま生き残った 7 件（M2 / M3 / M21 / M22 / M34 / M47 / M48）と、snapshot だけが守っている 2 件（M1 / M50）が上記の finding。
`mutate.py` に残っている M49 は置換結果が元のコードと等価（変異として無効）だったので表から除いた。

## 確認済み・問題なし（親の観点のうち finding にならなかったもの）

- **§2.1 表 12 行の対応**: `circles[]` → `LlmAgent` / workflow agent、`core` → `model`、`instruction.rune` → `instruction`（複数行は暗黙連結・`py_text_block`）、
  `tools[]` → `FunctionTool` / builtin インスタンス / `AgentTool(agent=)`、`delegate[]` → `sub_agents`（順序と `PointerMap.delegate` の添字が一致・3g）、
  `state[].out` → `output_key`、`flow.kind` 3 種 → `_FLOW_CLASS`、`flow.max` → `max_iterations`、`flow.exit` → `StateCheckAgent` を `sub_agents` 末尾（M4 で実効性確認）、
  `guards[].on` 6 種 → `_CALLBACK_KWARG` は probe の LlmAgent フィールド名と 1:1、同種複数はリスト（3d 実測）、`await[]` → `LongRunningFunctionTool`、`root` → `root_agent`
- **`ref` の形式**: 相対（先頭 `.`）・attr がドット付き・`;` 混入は `check_ref_format` の正規表現で拒否 → `BuildError`（`ref_malformed` fixture と同経路）。
  ドット多段の module は `from a.b.c import f` になる。同名 callable の別モジュール → 別名 import（ただし F-C-P2-002）
- **circle の定義順**: `_dependency_order` は steps / delegate / summon の 3 辺を post-order で辿り、参照先が先に定義される（M12 で実効性確認）。
  循環は JIN012、多重親は JIN013 が `jin check` で先に落とす（`semantic.py:602-637`）
- **`out: true` 2 件**: `two_out_states` fixture → `BuildError`（pointer は 2 つ目の state）
- **`_state_matches` 16 ケース**: 実装は `docs/spec/model.md` §3.4 の表どおり（`"true"`=true / `"True"`≠true / `"3.0"`=3 / `"true"`≠3 / `'"3"'`≠3）。
  `json.loads` の失敗は `ValueError` 系で捕まる。NaN は `.jin` の字句（`SIGNED_NUMBER`）で JIN001 になるので `py_value` の NaN 分岐には到達しない
- **StateCheckAgent**: `ctx.session.state.get(key)` は同一 invocation 内の `state_delta` を反映する（`test_loop_exits_early_*` が実証）。
  `EventActions(escalate=matched)` を `LoopAgent` が `loop_agent.py:116` で見て抜ける
- **trace**: `partial` の skip、`seq` の 1 始まり連番、`final` の 1 行遅延、`ts` の型、checker 行の `name` = loop 名 / `pointer` = `/circles/i/flow/exit` は実装どおり
- **runtime**: `swap_models` は `sub_agents` と `AgentTool.agent` の両方を辿る（researcher / pipeline で実測）、`sys.modules` の後始末、`mkdtemp` 0700 と `rmtree`、
  import 中の `SystemExit` を `RunError` にする経路はテストが固定し、実装者ハーネスでも赤を確認済み
- **FakeLlm**: `BaseLlm` の abstractmethod は `generate_content_async` の 1 つだけ（`models/base_llm.py:131`）。`supported_models` / `model="fake"` / `PrivateAttr` の状態は契約どおり
- **CLI**: `build` / `run` の exit code（0 / 1 / 2）、`--force`、`--model` の `fake` 限定、`--trace` の `O_NOFOLLOW`、`sys.path` への cwd 追加は `test_build_run.py` の 15 件が固定

## 実測した ADK API（存在しない API / 引数名は無かった）

`LlmAgent(name/model/description/instruction/tools/sub_agents/output_key/{before,after}_{agent,model,tool}_callback)`、
`SequentialAgent/ParallelAgent/LoopAgent(name/description/sub_agents)`、`LoopAgent(max_iterations=)`、
`FunctionTool(func)` / `LongRunningFunctionTool(func)` / `AgentTool(agent=)`、`BaseAgent._run_async_impl(ctx)`、
`EventActions(escalate=, transfer_to_agent=)`、`Event.timestamp / partial / custom_metadata / get_function_calls / get_function_responses`
（後 2 つは `LlmResponse` 由来・`models/llm_response.py:196,205`）、`Runner(agent=, app_name=, session_service=)`、
`InMemorySessionService.create_session(app_name=, user_id=, session_id=, state=)`（async）、`BaseLlm.generate_content_async(llm_request, stream)` /
`supported_models` は 2.8.0 の実物と一致。`_adk_is_valid_state_name` は `instructions_utils._is_valid_state_name`（`:238-262`）と同値
（ADK 側も `.strip()` してから判定するので `{ a }` を衝突とみなす実装は正しい）。
