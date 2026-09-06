# 決定整合性チェック（decision-conformance-check）

実行日時: 2026-09-04T07:25+00:00（ラウンド 1）/ 2026-09-05T10:30+00:00（ラウンド 2・Phase 2 追記）/ **2026-09-06T01:10+00:00（ラウンド 3・Phase 3 追記）** / 対象: `delivery/20260904-1445-jin/{requirements.json, design.yaml, implementation-plan.json}`
実装ラウンド: **1 / 5（Jin Phase 0 + Phase 1）→ 2 / 5（Jin Phase 2・jin-adk）→ 3 / 5（Jin Phase 3・jin-render）**

> **ラウンド 2（Phase 2）の追記方針**: ラウンド 1 が `out_of_scope` にした行のうち Phase 2 で実装対象になった
> DP-COMMON-14（トレース行）/ DP-COMMON-15 / DP-JIN-CODEGEN-RUNTIME-01 / DP-JIN-TRACE-POINTER-01 を
> 同じ表の中で **constraint 1 行ずつ**に分解して reflected / not_reflected へ潰した（行頭に「**P2**」）。
> ラウンド 1 の判定（`out_of_scope` 4 行）はそのまま残し、その直下に P2 行を並べる（修正ラウンド 1 で復元・F-V-P2-007）。

> **ラウンド 3（Phase 3）の追記方針**: 同じ規律で、Phase 3 で実装対象になった DP-JIN-SVG-DETERMINISM-01 と
> DP-COMMON-07（SVG はキャッシュしない / 純関数）を **constraint 1 行ずつ**に分解して潰した（行頭に「**P3**」）。
> 既存の行は 1 つも消していない。Phase 3 で新たに値を確定した実装判断は §2.24 に並べた。

> **本ラウンドの照合範囲**: `decision_record[]` は requirements.json 3 件 + design.yaml 17 件の計 20 件。
> このうち Jin Phase 0 / Phase 1 のコードに触れる DP だけを `reflected` / `not_reflected` で判定し、
> Phase 2 以降でしか実装対象が現れない DP は **`out_of_scope`**（本ラウンドで実装しないので照合対象外）とした。
> `unknown`（反映箇所を特定できない）とは区別している。後続ラウンドの implementer が
> 同じ表に追記して `out_of_scope` を潰していくこと。

## 1. 対照表

| DP ID | 制約 | kind | 出所 | 判定 | 反映箇所 / 備考 |
|---|---|---|---|---|---|
| DP-COMMON-09 | 横断契約テストの置き場は `tests/contract/` とする。パッケージ横断 fixture の共有方法は実装 Stage で決め、根拠を残す | condition | 構造化 | **reflected** | `tests/contract/`（4 ファイル）。fixture 共有方法は `tests/conftest.py:1-22` の docstring に決定と根拠を記載（リポジトリ直下 conftest + 単一 pytest rootdir）。`pyproject.toml:32` の `testpaths` |
| DP-COMMON-09 | テストはネットワークアクセスと API キーを一切必要としない（NFR-TEST-001） | scope | 構造化 | **reflected** | 全 225 テストがネットワーク接続なしで通る。外部通信するコードは `jin_core.semantic._import_ref`（`--resolve` 時のローカル import のみ）だけで、HTTP クライアントを一切 import していない（`packages/jin-core/src/jin_core/semantic.py:212` の `_import_ref` のみ） |
| DP-COMMON-11 | `design.yaml architecture.dependency_direction.rules` の 8 行を契約の正本とし、検査ツールを差し替えても契約は動かさない | scope | 構造化 | **reflected** | `tests/contract/test_dependency_direction.py:1-12` の docstring で正本を明記。`CLAUDE.md`「パッケージ境界」節でも同じ参照 |
| DP-COMMON-11 | CI は jin-core → google-adk と apps/editor → Python パッケージの 2 本を必ず落とすこと | condition | 構造化 | **部分 reflected** | 1 本目（jin-core → google-adk）は `pyproject.toml:56-60` の forbidden contract で担保し、**違反を注入して実際に BROKEN になることを実測**（`tests/contract/test_dependency_direction.py:76-104`。実測ログ: `no adk BROKEN` / `jin_core.canonical -> google (l.1)` / exit 1）。CI は `.github/workflows/ci.yml:23`（`uv run lint-imports`）。2 本目（apps/editor）は **apps/editor がまだ存在しないため未対応**。隠さないよう `test_editor_contract_is_not_yet_enforced` が「apps/editor ができたらこのテストが赤くなる」形で固定してある |
| DP-COMMON-11 | apps/editor は Python パッケージを直接 import しない（LSP プロトコルにのみ依存する） | scope | 構造化 | **out_of_scope** | apps/editor は Phase 5。本ラウンドの成果物に無い |
| DP-JIN-CANONICAL-01 | §2.3 の 5 規則は canonical writer 1 箇所にのみ実装し、Pydantic 設定と後処理へ分散させない | scope | 構造化 | **reflected** | `packages/jin-core/src/jin_core/canonical.py` が唯一の実装箇所。`model_dump` / `model_dump_json` を使っていない（`grep -n "model_dump" packages/jin-core/src/jin_core/canonical.py` の 2 ヒットはいずれも docstring の記述で、コードには 1 つも無い）。`ops.py` は編集用に `model_dump` を使うが正準形の出力経路ではない |
| DP-JIN-CANONICAL-01 | Pydantic のモデル定義変更に writer が追随することをテストで担保する（往復無損失と `fmt(fmt(x)) == fmt(x)`） | condition | 構造化 | **reflected** | writer は `type(model).model_fields` を走査するだけでキー名も順序もハードコードしない（`canonical.py:91-99` の `_members`）。追随の担保は `packages/jin-core/tests/test_model.py::test_field_order_matches_spec` と `tests/contract/test_canonical_contract.py::test_rule2_key_order_is_schema_definition_order`（モデル定義から期待値を導出する）+ 冪等性・意味保存の各テスト |
| DP-JIN-CANONICAL-01 | JSON エスケープ処理を自前で書くことによるバグリスクを、非 ASCII・制御文字・サロゲートペアの fixture で必ず検証する | condition | 構造化 | **reflected** | `packages/jin-core/tests/test_canonical.py` の `test_non_ascii_is_not_escaped` / `test_control_characters_are_escaped`（U+0001・U+001F を含む）/ `test_surrogate_pair_survives_roundtrip`（U+20BB7・U+1F409）/ `test_del_and_latin1_are_not_escaped`（U+007F・U+00E9）。**注記**: 独立した `.jin` ファイルの fixture ではなくテスト内リテラルで与えている。制約は「fixture で検証する」であり検証手段の形式までは指定していないが、ファイル fixture を望むならレビューで指摘されたい |
| DP-JIN-POINTER-RANGE-01 | `schemas/jin.schema.json` は外部 JSON ツールと LLM 向けの公開契約であり、内部検証には使わない | scope | 構造化 | **reflected** | 内部検証は Pydantic のみ（`packages/jin-core/src/jin_core/check.py:139-161` の `_schema_diagnostics`）。`jsonschema` ライブラリは依存に入っていない（`grep -c jsonschema packages/jin-core/pyproject.toml pyproject.toml` → 0 / 0）。schema を読むのは `jin schema` の出力と CI のドリフト検出だけ |
| DP-JIN-POINTER-RANGE-01 | JIN002 の検出器は Pydantic に一本化する。同じ違反に複数のメッセージ形式を生む検証器を併用しない | scope | 構造化 | **reflected** | `check.py:139-161` の `_schema_diagnostics` が唯一の JIN002 生成箇所。同一 `(pointer, error_type)` の重複も除去している |
| DP-JIN-POINTER-RANGE-01 | loc → pointer の変換規則を判別共用体（`tools[].kind`）・Optional・エイリアスについて網羅的にテストする | condition | 構造化 | **reflected** | `tests/contract/test_pointer_contract.py::test_loc_to_pointer_handles_union_tag_optional_and_alias` が 6 ケース（`$schema` エイリアス / `await` 予約語エイリアス / summon 判別タグ / Optional の `flow.max` / 配列添字 / ルート）。`test_loc_to_pointer_for_missing_key_points_at_the_missing_child` が必須キー欠落の経路 |
| DP-JIN-SEMANTIC-GAPS-01 | **新規 JIN 診断コードの採番値は本判断では確定しない。空き番号への採番は Phase 0 の `docs/spec/diagnostics.md` 執筆時に決定し根拠を残す** | condition | 構造化 | **reflected（本ラウンドで値を確定）** | **JIN012 = 循環参照 / JIN013 = 多重親**。根拠は `docs/spec/diagnostics.md` §3.1（§2 の要約は下の §2 参照）。実装は `packages/jin-core/src/jin_core/semantic.py:396-420`、コード表は `diagnostics.py:PROPOSED_CODES` |
| DP-JIN-SEMANTIC-GAPS-01 | 本判断で具体的なコード番号を成果物に書かない（T-002・要件書に無い値を捏造しない） | prohibition | 構造化 | **reflected** | design.yaml / ADR-007 には番号が書かれていない（実測: ADR-007 で 0 ヒット / design.yaml でも 0 ヒット）。番号は Phase 0 の仕様書執筆時に本ラウンドで初めて決めた |
| DP-JIN-SEMANTIC-GAPS-01 | 要件書 §2.4 の診断コード表への追加であり、仕様変更として人間の承認を要する | condition | 構造化 | **reflected（承認は未取得・明示済み）** | `docs/spec/diagnostics.md` §3 が正典表（12 件）と**別の表**として分離され、冒頭に「⚠️ まだ人間が承認していない」と明記。`tests/spec/test_spec_consistency.py::test_diagnostics_proposed_codes_are_exactly_two` が 2 件に固定。承認要求は本ラウンドの確認要求ブロック（`implementation-notes.md` §確認要求）で親へ返した |
| DP-JIN-SEMANTIC-GAPS-01 | 追加後は `docs/spec/diagnostics.md` と `schemas/jin.schema.json` の整合を取り直すこと | condition | 構造化 | **reflected** | JIN012 / JIN013 は**意味検査の診断**であり JSON Schema の語彙を変えない（スキーマは構造の契約で、参照グラフの性質は表現できない）。したがって `schemas/jin.schema.json` に変更は不要。この判断自体を `docs/spec/diagnostics.md` §1 の「段 3」定義に明記している |
| DP-COMMON-14 | stdio モードでは stdout に JSON-RPC 以外のいかなる出力も行わない | scope | 構造化 | **out_of_scope** | LSP は Phase 4。本ラウンドに stdio トランスポートは無い |
| DP-COMMON-14 | トレース JSONL は要件書 §3.4 のスキーマに従う成果物であり、ログとして扱わない | scope | 構造化 | **out_of_scope**（ラウンド 1 の判定・記録として残す。直下の **P2** 行で潰した） | トレースは Phase 2 |
| **P2** DP-COMMON-14 | トレース JSONL は要件書 §3.4 のスキーマに従う成果物であり、ログとして扱わない | scope | 構造化 | **reflected** | `packages/jin-adk/src/jin_adk/trace.py:35-38`（`TRACE_FIELDS` / `KINDS` = §3.4）。JSONL は `--trace` 指定時だけ `TraceWriter(sink=...)` が書く（`trace.py:236-262`）。ログ（ADK の logging・pointer 未解決の理由・件数）は `jin_cli/main.py` の `run` が **stderr** へ（`err=True`）。stdout は 1 行 1 イベントの人間向け表示で JSONL とは別物。`tests/spec/test_spec_consistency.py::test_trace_kinds_table_matches_the_implementation` が §3.4 の 5 種と一致することを固定 |
| DP-COMMON-14 | ログレベル・フォーマット・ローテーションの方針は本判断では確定しない。実装 Phase 4 で決定し根拠を残す | condition | 構造化 | **out_of_scope** | Phase 4 で確定する。本ラウンドでは決めていない（勝手に先取りしていないことが遵守） |
| DP-COMMON-07 | last-good モデルの保持は jin-lsp のドキュメント管理層 1 箇所に閉じ込める | scope | 構造化 | **reflected（先取りしない形で）** | `jin_core` にキャッシュ層を一切置いていない。`check_text` は毎回フル再計算する純関数（`check.py:164-197` の `check_text`）。保持は Phase 4 の jin-lsp が持つ |
| DP-COMMON-07 | `jin_core` / `jin_render` はキャッシュの存在を知らない純関数のままとし、内部に状態を持たない | scope | 構造化 | **reflected（修正ラウンド 1 で成立させた）** | 修正ラウンド 1 より前は `resolve=True` のとき `jin_core.semantic._import_ref` が `importlib.import_module` を呼び、`sys.modules` というプロセス全体の可変状態を書き換えていた（同じ入力で 2 回目が別の結果になりうる = 純関数ではない）。security review S14 の指摘どおり、当時の「reflected」は**実態と乖離していた**。現在は import 実装を `jin_cli.resolver.ImportResolver` へ移し、`jin_core` は `RefResolver` プロトコルを受け取るだけになった（`jin_core/resolver.py`）。`jin_core` にモジュールレベルの可変状態は無く、モジュール定数は `parser._PARSER`（Lark の文法オブジェクト・不変）と各種の定数辞書のみ |
| DP-COMMON-07 | SVG はキャッシュしない | scope | 構造化 | **out_of_scope**（ラウンド 1 の判定・記録として残す。直下の **P3** 行で潰した） | jin-render は Phase 3 |
| **P3** DP-COMMON-07 | SVG はキャッシュしない | scope | 構造化 | **reflected** | `jin_render` にキャッシュ層が無い。`render` は毎回フル計算する（`packages/jin-render/src/jin_render/layout.py` の `render`）。`functools.lru_cache` / `cache` を 1 箇所も使っていない（実測 2026-09-06: `grep -rn "lru_cache\|functools" packages/jin-render/src` → 0 件） |
| **P3** DP-COMMON-07 | `jin_core` / `jin_render` はキャッシュの存在を知らない純関数のままとし、内部に状態を持たない | scope | 構造化 | **reflected** | `jin_render` にモジュールレベルの可変状態は無い（定数と `dataclass` だけ）。組み立て器 `_Builder`（`<textPath>` の id 連番を持つ）は `render` の呼び出しごとに生成される局所オブジェクト。ファイルも読まない（`open` / `Path` を import していない・要件書 §4）。動的 import も無い（`tests/contract/test_packaging_contract.py::test_dynamic_imports_are_confined_to_the_cli_resolver_and_jin_run` が 2 モジュール厳密一致で固定） |
| DP-COMMON-15 | `.env.example` のキー名は実装 Stage 1 の実測に委ねる / 推測で書かない / 実測できなければコメントのみ | condition, prohibition | 構造化 | **out_of_scope**（ラウンド 1 の判定・記録として残す。直下の **P2** 行で潰した） | `.env.example` を出すのは `jin build`（Phase 2 / FR-ADK-001）。本ラウンドで `.env.example` は生成していない（実測: `find . -path ./.venv -prune -o -name '.env*' -print` → 0 件）。**キー名を推測で書いていない**という禁止事項は遵守 |
| **P2** DP-COMMON-15 | `.env.example` のキー名は本判断では確定しない。実装 Stage 1 で google-adk 2.8.0 が読む環境変数名を実測し、その実測値のみをテンプレートに固定する | condition | 構造化 | **reflected（値を確定・§2.13）** | 実測した 4 キーだけを `packages/jin-adk/src/jin_adk/codegen.py` の `_env_example`（`GOOGLE_GENAI_USE_ENTERPRISE` / `GOOGLE_API_KEY` / `GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION`）に固定。出典（file:line）を `.env.example` 本文にも書く。`packages/jin-adk/tests/test_codegen.py::test_env_example_lists_only_measured_keys` が集合一致を固定 |
| **P2** DP-COMMON-15 | 推測・記憶・一般論に基づくキー名を `.env.example` に書かない（T-002） | prohibition | 構造化 | **reflected** | 4 キーはすべて site-packages の grep / 読解に出典がある（§2.13 の表）。`GEMINI_API_KEY`（google-genai が読む）は **書いていない**: `adk create` が書かないキーであり、`GOOGLE_API_KEY` が優先されるため（`_api_client.py:136-140`）。コメントで読み手の出典だけ示した |
| **P2** DP-COMMON-15 | 実測できなかった場合は `.env.example` をコメントのみで生成し、`docs/pending-decisions.md` に残す | condition | 構造化 | **reflected（該当なし）** | 実測できたので pending 起票は不要。条件分岐は発生していない |
| **P2** DP-COMMON-15 | テストは `.env` / API キー / ネットワークを必要としない（NFR-TEST-001） | scope | 構造化 | **reflected** | Phase 2 の全テスト（jin-adk 130 件 / CLI 29 件 / 契約 3 件）は `FakeLlm`（`jin_adk/fake_llm.py`）で動き、`.env` を読まない。`test_fake_llm.py::test_fake_llm_never_imports_a_network_client` が HTTP クライアントの import が無いことを固定。実測: `uv run pytest` はネットワーク無しで 695 passed（修正ラウンド 1 後は 770 passed・jin-adk 178 / CLI 42 / 契約 4 + guard 21） |
| DP-COMMON-16 / 17 / 18 / 19 / 20 | エディタ側の各制約（選択の 3 つ組保持 / JSON-RPC ラッパ / SPA 構成 / 5 状態 / テスト 2 層） | 各種 | 構造化 | **out_of_scope** | `apps/editor` は Phase 5–6 |
| DP-JIN-CODEGEN-RUNTIME-01 | FakeLlm を生成物に埋め込まない / 生成物は jin を import しない / StateCheckAgent 重複の扱いは Phase 2 で決定 / 再生成が必要な旨を明示 | 各種 | 構造化 | **out_of_scope**（ラウンド 1 の判定・記録として残す。直下の **P2** 行で潰した） | jin-adk は Phase 2 |
| **P2** DP-JIN-CODEGEN-RUNTIME-01 | FakeLlm は生成物に埋め込まず jin_adk 側に置く（生成された agent.py に FakeLlm は現れない） | scope | 構造化 | **reflected** | FakeLlm は `packages/jin-adk/src/jin_adk/fake_llm.py` だけ。差し替えは実行時に `jin_adk/runtime.py:134-141` の `swap_models` が agent 木を走査して行う。`test_codegen.py::test_generated_code_does_not_mention_fake_llm` がスナップショット対象 2 本で固定。変異 `RUN-no-agenttool-swap` で赤を実測 |
| **P2** DP-JIN-CODEGEN-RUNTIME-01 | 生成された agent.py は jin パッケージを一切 import しない | scope | 構造化 | **reflected** | テンプレート `packages/jin-adk/src/jin_adk/templates/agent.py.j2` の import は `google.adk.*` / `json` / `collections.abc` と `.jin` の `ref` だけ。`test_codegen.py::test_generated_code_does_not_import_jin` が AST で固定 |
| **P2** DP-JIN-CODEGEN-RUNTIME-01 | flow.exit を持つ circle が複数ある場合の StateCheckAgent 重複定義の扱いは Phase 2 で決定し根拠を残す | condition | 構造化 | **reflected（値を確定・§2.20）** | **1 ファイルに 1 クラス定義、loop ごとにインスタンス**（`<circle 名>_exit_check`）。`codegen.py` の `generate` は `has_exit` で定義を 1 回だけ出し、`_emit_checker` が loop ごとに出す。`test_codegen.py::test_state_check_agent_is_embedded_once_and_instantiated_per_loop` が固定。根拠は `docs/spec/adk-mapping.md` §2.3 |
| **P2** DP-JIN-CODEGEN-RUNTIME-01 | StateCheckAgent の実装変更は既存の生成物に反映されないため、再生成が必要である旨を生成物のヘッダまたは README に明示する | condition | 構造化 | **reflected** | 生成物ヘッダ（`codegen.py` `_header`）の「StateCheckAgent（flow.exit）は生成時に埋め込まれたコピーで … `jin build` で再生成すること（ADR-008）」。`test_codegen.py::test_header_states_regeneration_and_pointer_limits` が文言を固定（変異 `ADR8-header` で赤を実測） |
| DP-JIN-TRACE-POINTER-01 | 対応表を生成物に埋め込まない / 引けないイベントは pointer を null にする / 単体 adk run では pointer が付かない旨を明示 | 各種 | 構造化 | **out_of_scope**（ラウンド 1 の判定・記録として残す。直下の **P2** 行で潰した） | Phase 2 |
| **P2** DP-JIN-TRACE-POINTER-01 | 対応表を生成物（agent.py）に埋め込まない。生成コードは Jin を知らないままとする | scope | 構造化 | **reflected** | 対応表は `codegen.py` の `PointerMap`（`GeneratedProject.pointers`）として生成物とは別のオブジェクト。実行時は `trace.py` の `RuntimeTable` が引く。`test_codegen.py::test_pointer_map_is_not_embedded_in_the_generated_code`（`/circles/` が agent.py に無い）で固定 |
| **P2** DP-JIN-TRACE-POINTER-01 | 引けなかったイベントは pointer を null にして黙って落とさず、対応不能であることを明示する（NFR-FAIL-001） | condition | 構造化 | **reflected** | `trace.py:108-143` の各 lookup が None を返しつつ `RuntimeTable.unresolved` に理由を積む。行は落とさない（`classify` は必ず行を返す）。CLI は `jin_cli/main.py` `run` の末尾で理由を stderr に出す。`test_trace.py::test_unknown_author_gets_a_null_pointer_not_a_dropped_row` / `::test_unknown_tool_name_gets_a_null_pointer` / `::test_duplicate_tool_names_inside_one_agent_are_reported_as_unresolvable`。変異 `TRACE-drop-unknown` / `TRACE-dup-first-wins` で赤を実測 |
| **P2** DP-JIN-TRACE-POINTER-01 | 生成物を jin run を経由せず単体で adk run した場合はトレースの pointer が付かない。この制約をドキュメントに明示する | scope | 構造化 | **reflected** | 生成物ヘッダ（`_header`）/ `docs/spec/adk-mapping.md` §2.4 / `README.md` の 3 箇所。ヘッダは `test_header_states_regeneration_and_pointer_limits` が固定（変異 `ADR9-header` で赤を実測） |
| DP-JIN-SVG-DETERMINISM-01 | 丸め桁数は Phase 3 で決定し根拠を `docs/spec/layout.md` に残す / 推測値を固定しない / 決定性テストは別プロセス 2 回 / 星形 {n/k} の k を Phase 0 の layout.md で一意に明文化 / 座標は丸め関数 1 本を通す | 各種 | 構造化 | **一部 reflected・残りは out_of_scope** | （ラウンド 1 の判定・記録として残す。直下の **P3** 行で潰した）**Phase 0 の担当分はラウンド 1 で実施**: 星形 {n/k} の k の決め方を `docs/spec/layout.md` §2.1 で `k = max{ j : 1 <= j < n/2 かつ gcd(n, j) == 1 }` として一意に明文化した。**丸め桁数は書いていない**（Phase 3 で決める旨を layout.md §4 に明記・推測値を固定しない禁止事項を遵守）。丸め関数と決定性テストは Phase 3 |
| **P3** DP-JIN-SVG-DETERMINISM-01 | 座標を SVG に書き出す経路は必ず丸め関数 1 本を通す（素の float 文字列化を混在させない） | scope | 構造化 | **reflected** | `jin_render.svg.fmt_coord` が唯一の書き出し口。`guard: fmt_coord -> format(value,_COORD_FORMAT)` で主張し `tests/contract/test_guard_claims.py` が固定。SVG 側は `test_layout.py::test_all_geometry_numbers_are_written_with_three_decimals` が「幾何・体裁属性の数値がすべて 3 桁で終わる」ことを正規表現で見る。変異 `DET-plain-str` / `DET-repr` で赤を実測 |
| **P3** DP-JIN-SVG-DETERMINISM-01 | 丸め桁数の具体値は実装 Phase 3 で決定し、根拠を `docs/spec/layout.md` に残す | condition | 構造化 | **reflected（値を確定・§2.24.1）** | **3 桁固定小数**。根拠は `docs/spec/layout.md` §4 と本書 §2.24.1 の両方（仕様側とコード側は同じ欠陥・片方だけ直さない）。根拠は (a) px 換算後の解像度（1000 px 角・正規化 1.0 = 400 px。0.001 px は 4 倍 DPR でも 1 デバイスピクセルの 1/4000）と (b) 浮動小数の末尾ノイズ（最大座標 1000 px の 1 ULP は約 1.1e-13 px で丸めの刻みの 10 桁下）の 2 点を実測で示した。`test_svg.py::test_rounding_step_is_far_above_the_float_noise`。変異 `DET-two-decimals` で赤を実測 |
| **P3** DP-JIN-SVG-DETERMINISM-01 | 推測に基づく丸め桁数を成果物に固定しない（T-002） | prohibition | 構造化 | **reflected** | ラウンド 1 は桁数を書かず「Phase 3 で決める」とだけ残した（当時の判定どおり）。ラウンド 3 で上の 2 点を実測してから確定させ、layout.md §6 の表に「実装で確定した値であり要件値ではない」と明記した |
| **P3** DP-JIN-SVG-DETERMINISM-01 | 決定性テストは同一プロセス内 2 回ではなく、異なる `PYTHONHASHSEED` の別プロセス 2 回で行う | condition | 構造化 | **reflected** | `packages/jin-render/tests/test_determinism.py::test_two_processes_with_different_hash_seeds_agree`（seed 0 と 4242 の `subprocess` 2 本・examples 2 本）と `::test_a_trace_overlay_is_also_hash_seed_independent`（overlay も別に固定）。同一プロセス内 2 回（要件書 §9）は `::test_two_renders_in_one_process_are_byte_identical` として**別のテスト**に置いた。変異 `ORN-builtin-hash`（`hash()` に置換）で赤を実測 |
| **P3** DP-JIN-SVG-DETERMINISM-01 | 星形多角形 {n/k} の k の選択規則を一意に定める（ラウンド 1 で layout.md §2.1 に明文化済み）を実装が守る | condition | 構造化 | **reflected** | `jin_render.geometry.star_step` が `max{ j : 1 <= j < n/2 かつ gcd(n, j) == 1 }` を整数演算（`2*j < n`）だけで実装。描画側の辺の接続まで `test_layout.py::test_loop_edges_follow_the_star_polygon` が n=5 / 6 / 8 で固定する（`n // 2` は n=5 / 7 / 9 では偶然一致するので、割れる n を選んだ）。変異 `STAR-n-half` / `STAR-always-one` / `STAR-reversed` で赤を実測 |
| DP-JIN-EDITOR-PROTOCOL-01 | `jin/open` / `jin/save` は仮称であり Phase 0 の `docs/spec/ops.md` 執筆時に人間承認を得て確定する / ws モードのエディタだけが使う / ファイル I/O 失敗はプロトコルエラー / 逆オペレーションの扱いは Phase 4 | 各種 | 構造化 | **reflected（Phase 0 担当分）** | `docs/spec/ops.md` §5 に「リクエスト名は仮称であり人間承認を要するため §2 の 19 件の表に含めていない」と明記。19 件の表を勝手に 21 件にしていない |
| DP-JIN-PHASE-SCOPE-01（requirements.json） | 本ランのスコープは Phase 0〜6 | — | 構造化 | **reflected** | 本ラウンドは Phase 0 + 1。Phase 2 以降は後続ラウンドの implementer が担当（親の指示どおり着手していない） |
| DP-JIN-EDITOR-UX-01 / DP-JIN-DISTRIBUTION-01（requirements.json） | エディタ最小 UI / 配布元 | — | 構造化 | **out_of_scope** | Phase 5 / 配布は本ラウンドの対象外 |

**判定サマリ（ラウンド 1）**: reflected 14 / 部分 reflected 1 / not_reflected 0 / unknown 0 / out_of_scope 13
→ **PASS**（`not_reflected` と `unknown` はゼロ。「部分 reflected」1 件は apps/editor 未存在が理由で、
未対応であることをテストで可視化してある）

**判定サマリ（ラウンド 2・Phase 2 追記分）**: ラウンド 1 の `out_of_scope` 4 行を 12 の constraint 行へ分解し、
reflected 12（うち値を確定 2）/ not_reflected 0 / unknown 0。残る `out_of_scope` は Phase 3〜6 の行
（DP-COMMON-11 の apps/editor / DP-COMMON-14 の stdio・ログ方針 / DP-COMMON-07 の SVG / DP-COMMON-16〜20 /
DP-JIN-SVG-DETERMINISM-01 の Phase 3 分 / DP-JIN-EDITOR-UX-01 / DP-JIN-DISTRIBUTION-01）→ **PASS**

## 2. 本ラウンドで**値を確定した**実装判断（親からの明示指示）

design.yaml の `constraints[]` が「実装時に決定し根拠を残す」としていた値。ここが本ファイルの主目的である。

### 2.1 新規 JIN 診断コードの採番（DP-JIN-SEMANTIC-GAPS-01）

| 決めた値 | 内容 |
|---|---|
| **JIN012** | 参照が循環している（`summon` / `delegate` / `flow.steps` の有向グラフに閉路がある）・error |
| **JIN013** | circle が複数の親を持つ（`flow.steps` / `delegate` からの親子辺の入次数が 2 以上）・error |

**根拠**（`docs/spec/diagnostics.md` §3.1 が正本）:

要件書 §2.4 のコードは 10 の位で関心事がブロック化されている。

| ブロック | 関心事 | 既使用 |
|---|---|---|
| 00x | 入力そのものの妥当性 | JIN001, JIN002 |
| **01x** | **名前と参照の整合性** | JIN010（重複）, JIN011（未解決の参照） |
| 02x | circle 単体の形 | JIN020, JIN022 |
| 03x | flow 自身の妥当性 | JIN030, JIN031 |
| 04x | 外部（Python）への解決 | JIN040 |
| 05x | rune 内テンプレート | JIN050 |
| 06x | root | JIN060 |
| 07x | await | JIN070 |

追加する 2 件はどちらも「circle 名で張られた**参照グラフ全体**の整合性」であり、01x の関心事に一致する。
01x の空き番号は JIN012〜JIN019 なので若い順に採った。

03x（flow）に採らなかった理由: **多重親は `delegate` でも起きる**（flow ではない）。循環参照も `summon` を含む。
flow ブロックに置くと「10 の位 = 関心事」という既存の並びが崩れる。

**未承認であることの扱い**: `docs/spec/diagnostics.md` は正典表（§2・12 件）と追加提案表（§3・2 件）を
**別の表**に分け、§3 の冒頭に「まだ人間が承認していない」と明記した。
これにより design.yaml Phase 0 の machine 条件「§2.4 の 12 件と過不足なく一致」と
DP-JIN-SEMANTIC-GAPS-01 の「2 件追加採番」を両立させている。

> **その後（2026-09-04・Issue #2）**: `DP-JIN-DIAGCODE-NUMBERING-01` が人間承認され（ADR-012 が accepted）、
> 2 件は §2 の正典表へ統合された。要件書 §2.4 は 14 行、`diagnostics.md` の表は §2 の 1 つだけ、
> design.yaml Phase 0 の machine 条件も「14 件」に更新済み。上の記述は統合前の状態の記録である。

### 2.2 診断の行・列の基点（DP-JIN-POINTER-RANGE-01 / `lsp-api-probe.md` §3 の指摘）

| 項目 | 決めた値 |
|---|---|
| `range.start.line` / `range.end.line` | **1 始まり** |
| `range.start.col` / `range.end.col` | **1 始まり** |
| `range.end` の含み方 | **排他** |
| 列の数え方 | **Unicode コードポイント単位** |

**根拠**（`docs/spec/diagnostics.md` §5.1 が正本）:

1. 要件書 §5 のフィールド名は `col` であり、LSP の `Position` は `character`（`lsp-api-probe.md` §1 の実測）。
   名前を変えている以上、LSP の座標をそのまま載せる意図ではないと読むのが素直
2. **lark がネイティブに 1 始まり**。本ラウンドで再実測した（`'{"a": "xy"}'` の `"a"` が L1C2-L1C5）。
   パーサの値をそのまま使えば変換の抜け漏れによるオフバイワンが構造的に起きない
3. `jin check` は人と LLM が直接読む出力であり、ruff / mypy / gcc など既存ツールの慣行が 1 始まり
4. `range.end` を排他にしたのは lark の `end_column` が排他だから（実測: 2 文字の `22` が C22-C24）

**変換を 1 箇所に閉じ込める**（`lsp-api-probe.md` §3 の要求）:
`jin_core` は LSP を知らない。LSP への変換は Phase 4 の `jin-lsp` の位置変換モジュール 1 本だけが行う。
そこで行う変換は 2 つあり、どちらも `docs/spec/diagnostics.md` §5.1 の表に明記した:

| 変換 | 内容 |
|---|---|
| 基点 | `line - 1` / `col - 1` |
| 列の単位 | Unicode コードポイント → **UTF-16 コードユニット**（pygls の `PositionCodec` を使う） |

列の単位変換は**日本語の rune を含む `.jin`（本案件の examples がまさにそれ）で実際に効く**。
`lsp-api-probe.md` は基点の差だけを指摘していたが、UTF-16 換算も同じ 1 箇所で扱う必要があるため併記した。

### 2.3 パッケージ横断 fixture の共有方法（DP-COMMON-09）

| 決めた値 | 内容 |
|---|---|
| 共有方法 | **リポジトリ直下の `tests/conftest.py` に置き、pytest の rootdir を 1 つに保つ** |

**根拠**（`tests/conftest.py` の docstring が正本）:

- 共有 fixture が要るのは `tests/spec/` と `tests/contract/` だけで、どちらもリポジトリ直下 `tests/` の下にある。
  各パッケージのテストは自分のパッケージしか見ないので共有を必要としない
- pytest プラグインを作って配布するより conftest.py 1 本のほうが依存が増えず追跡しやすい
- `pyproject.toml` の `testpaths` に 3 ディレクトリを並べ、`uv run pytest` 1 発で全部通す（FR-TEST-001）

### 2.4 診断コードの優先順位（要件書 §2.4 の内部矛盾への対処・本ラウンドで新たに必要になった判断）

要件書 §2.4 の JIN011 行は「未解決の参照（summon / delegate / **steps** / **await** / **`{key}`**）」と書くが、
`steps` / `await` / `{key}` にはそれぞれ **JIN031 / JIN070 / JIN050** という専用コードが同じ表に存在する。
要件書 §9 の「fixture は対応コードを 1 つだけ出す」を成立させるには、どちらを出すか決めなければならない。

**決めた規則**: **より具体的なコードが勝つ**。`docs/spec/diagnostics.md` §4 の表が正本。
結果として JIN011 の実効的な守備範囲は `summon` と `delegate` の 2 種になる。

これは要件書に書かれていない判断なので、レビューで人間の確認を得たい（`implementation-notes.md` の確認要求ブロック）。

### 2.5 JIN050 の「上流」の定義（要件書に定義が無い・本ラウンドで新たに必要になった判断）

要件書 §2.4 は「自 circle または flow **上流** circle の state」としか書いていない。実装には厳密な定義が要る。

**決めた規則**（`docs/spec/model.md` §5 の表が正本）:

| 位置関係 | 上流に含めるか | 根拠 |
|---|---|---|
| 自 circle の `state[]` | 含める | 自分で宣言した key |
| 祖先が `sequence` のとき、自分の枝より前の兄弟枝の部分木 | 含める | 直列なので必ず先に実行される |
| 祖先が `loop` のとき、すべての兄弟枝の部分木 | 含める | 反復するため 2 周目以降はどの兄弟も先に実行されうる |
| 祖先が `parallel` のとき、兄弟枝 | 含めない | 実行順序の保証がない |
| `delegate` の親 circle の `state[]` | 含める（親 → 子のみ） | 親が動いてから transfer される |
| `summon`（AgentTool）の呼び出し元 | 含めない | AgentTool は独立した呼び出しで state 可視性を Jin は保証しない |

この定義でないと要件書 §2.2 の `pipeline.jin` が通らない（`Critic` の `{draft}` は
`Refine` の外・`Pipeline` の前段 `Drafter` が出す）。examples が通ることが定義の妥当性の一次証拠になっている。

### 2.6 `tools[].name` を builtin でも必須にした（要件書の例からの明確化）

要件書 §2.2 の `builtin` の例は `{ "kind": "builtin", "builtin": "google_search" }` で `name` を書いていないが、
`name` は circle 内一意の ID として `boundary.await` / 意味オペレーション `moveTool` / JSON Pointer の安定性に使われる。
3 種すべてで `name` を必須にした（`docs/spec/model.md` §3.2）。**要件書の例の書き方と食い違う点**なので
レビューで確認したい（`implementation-notes.md` の確認要求ブロック）。

### 2.7 文字列の長さ制限と文字種制限（DP-JIN-STRLIMIT-01 / 修正ラウンド 1・security review S13）

要件書は `.jin` の文字列に**長さも文字種も規定していない**。制限が無いことが S6（端末表示の偽装）/
S3（編集距離の計算量）/ D-1（孤立サロゲートで `jin fmt` がクラッシュ）の共通の根なので、
本ラウンドで値を決めた。**値は要件書に無いので、以下が決定と根拠である。**

| 対象 | 値 | 根拠 |
|---|---|---|
| 識別子（`name` / `core` / `ref` / `builtin` / `circle` / `type` / `steps[]` / `delegate[]` / `await[]` / `exit.key` / `guards[].ref` / `root`）の最大長 | **128** | ADK の agent 名・tool 名は LLM のツール定義へそのまま載る。実在する例は最長でも 40 文字程度で、128 は約 3 倍の余裕がある。同時に編集距離の 1 対比較を 128×128 = 16 KiB 以内に抑える（S3） |
| 自由記述（`instruction.rune` / `description`）の最大長 | **65536**（64 KiB） | 要件書 §2.4 が circle あたりの要素数を 12 に制限しているのに対し、rune 1 本の長さは無制限だった。LLM への instruction として現実的な上限として 64 KiB を採る（Gemini の入力トークン上限より十分小さい） |
| `$schema` の最大長 | **2048** | URL の慣用上限 |
| 制御文字（C0 / U+007F / C1） | **識別子では全面禁止。自由記述では `\n` `\r` `\t` のみ許可** | 診断の 1 行は `file:line:col: severity CODE: message` の形なので、名前に改行が入ると偽の診断行を作れ、ESC が入ると既存の表示を消せる（S6）。改行は rune の本文に必要なので自由記述だけ許す |
| 孤立サロゲート（U+D800〜U+DFFF） | **全面禁止** | UTF-8 に符号化できず `jin fmt` の書き出しが `UnicodeEncodeError` で落ちる（D-1）。段 2 で JIN002 として弾く |

実装は `packages/jin-core/src/jin_core/model.py` の `MAX_IDENT_LENGTH` / `MAX_TEXT_LENGTH` /
`MAX_URL_LENGTH` と `_reject_bad_chars`。テストは `packages/jin-core/tests/test_model.py`。

**これは `.jin` 言語の受理範囲を狭める仕様変更**なので、人間の承認を求める（`implementation-notes.md` §6 の確認要求ブロック **Q-JIN-IMPL-09**）。

### 2.8 入れ子の深さ上限（DP-JIN-DEPTHLIMIT-01 / 修正ラウンド 1・security review S4）

| 対象 | 値 | 根拠 |
|---|---|---|
| JSON の値の入れ子の最大段数 | **64** | 妥当な `.jin` の最大の深さは 7 段（`/circles/N/boundary/guards/M/on`）。64 は約 9 倍の余裕がある。上限を置かないと `parser._walk` の再帰が Python の再帰上限（実測: 1000 段で `RecursionError`）に当たり、診断ではなくトレースバックが表に出る |

超過は JIN001（段 1・構文）として位置つきで返す。実装は `jin_core/parser.py` の `MAX_NESTING_DEPTH`。
**これも受理範囲の縮小**なので承認を求める（`implementation-notes.md` §6 の **Q-JIN-IMPL-10**。同じ Q に重複キーの JIN001 化も含めた）。
`semantic._find_cycle` と `semantic._subtree_states` は上限ではなく**再帰の除去**（明示スタック / Tarjan SCC）で対処した。
グラフの大きさは `.jin` の正当な内容で決まるため、上限を置くと正当なファイルを弾いてしまうからである。

### 2.9 候補名ヒントの上限（DP-JIN-HINTLIMIT-01 / 修正ラウンド 1・security review S3）

| 対象 | 値 | 根拠 |
|---|---|---|
| `close_names` が編集距離を計算する候補数 | **500** | Phase 4 の LSP は打鍵ごとに `check_text` を呼ぶ。候補が 500 を超えるファイルで「近い名前」を全探索する価値は無く、上位 3 件を出すには十分 |
| 1 回の `analyze` 全体での編集距離の計算回数（`MAX_DISTANCE_COMPUTATIONS`） | **20000** | 候補数の上限だけでは「診断件数 × 候補数」で二次的に効く（実測: 600 circle 全件未解決で 30 万回・6.2 秒）。20000 回は 128 文字以下の名前で 0.2 秒程度に収まり、LSP の対話性を保てる |
| hint に列挙する名前の件数 | **10**（超過分は「他 N 件」） | 診断 1 件の hint が数百行になると端末でもエディタでも読めない |

実測（1200 circle・全 delegate 未解決の最悪形。`check_text` 1 回の所要）:

| 状態 | 所要 |
|---|---|
| 修正前相当（候補数上限なし・打ち切りなし・予算なし） | 15.75 秒 |
| 候補数上限 500 + banded 早期打ち切りのみ | 3.76 秒 |
| さらに `DistanceBudget`（本実装） | **0.20 秒** |

参考（600 circle の場合）: 修正前 6.2 秒（編集距離 30 万回）→ 本実装 0.17 秒（2 万回）。

予算を使い切ったあとは hint が「近い名前: …」から「定義済みの circle: …」へ**決定的に**退化する。
**診断の件数・コード・位置は 1 件も変わらない**（`test_distance_budget_degrades_hints_deterministically` /
`test_large_document_diagnostics_are_reproducible`）。消費は文書順なので同じ入力なら常に同じ出力になる（NFR-DET-002）。

### 2.10 CI の Python バージョン固定（修正ラウンド 1・wiring review W-06）

**暫定である。** 確認要求 **Q-JIN-IMPL-06**（開発 Python バージョンの確定）は未回答であり、
`auto-decisions.md` にも裁定が無い。AI が「望ましいバージョン」を決めるべき論点ではないので、
本ラウンドでは**事実だけを固定**した。

- `.python-version` = `3.14` — **本ラウンドの 432 テストを実際に通した処理系**（実測 3.14.6）。
  値の意味は「検証に使った処理系」であって「推奨バージョン」ではない
- CI は uv が `.python-version` をネイティブに読むことでこれに従う（runner の既定に依存しない）。**実測（2026-09-04）: `astral-sh/setup-uv@v5` の action.yml が持つ入力は `python-version` であり `python-version-file` は存在しない**（`curl -s https://raw.githubusercontent.com/astral-sh/setup-uv/v5/action.yml`）。存在しない入力を渡しても Actions は警告するだけで失敗しないため、版は `.python-version` 1 箇所だけに置いた
- `pyproject.toml` の `requires-python = ">=3.12"`（対応範囲の下限）と ruff の `target-version = "py312"` は変えていない
- design.yaml の記録は 3.13.1 で、実 venv（3.14.6）と食い違っている。**この不一致は Q-JIN-IMPL-06 の回答で解消する**

### 2.11 原子的に書けないときの `jin fmt` の扱い（修正ラウンド 2・security review N2）

`tempfile.mkstemp` と `os.replace` は**ファイルではなくディレクトリ**の書き込み権を要求する。
修正ラウンド 1 で原子的書き込み（S11）を入れた結果、**読み取り専用ディレクトリの中にある
書き込み可能なファイル**が整形できなくなった（`PermissionError` が素通りしてトレースバック）。
これはラウンド 1 より前は動いていたケースであり、機能後退である。

決めたこと:

| 状況 | 挙動 | 根拠 |
|---|---|---|
| ディレクトリもファイルも書ける | 一時ファイル + `os.replace`（原子的） | 既定。書き込み中に落ちても切り詰めたファイルを残さない（S11） |
| ディレクトリは書けないがファイルは書ける | **直接書き込みへ退避し、stderr に警告を出す** | 原子性は「あると良い」もので、書けるファイルを整形できないことのほうが害が大きい。**黙って落とさない**（NFR-FAIL-001）ので警告は必須 |
| ファイルも書けない | 診断として報告し exit 1 | トレースバックを表に出さない（S5 と同じ経路） |

警告文: `<path>: ディレクトリに書けないため原子的に差し替えできませんでした。直接書き込みました（中断すると内容が壊れる可能性があります）: <理由>`

同時に、`os.replace` の前に `shutil.copymode` を入れて**元ファイルのパーミッションを引き継ぐ**
ようにした（security review N1）。`mkstemp` は 0600 で作るので、コピーしないと
`-rw-rw-r--` が `-rw-------` に落ちる。git は実行ビット以外のモードを追跡しないので差分にも出ない。

`shutil.copymode` は `st_mode & 0o7777` 全ビットを引き継ぐため setuid / setgid / sticky も残る。
setuid の付いた `.jin` は想定外だが、引き継ぎは**元より権限を広げない**（元が持っていたビットを
そのまま戻すだけ）ので、ここでビットを落とすより安全側に倒れる。

> **修正ラウンド 3 で訂正（security review R-2）**。ラウンド 2 のここには
> 「`_collect` が `fmt` に届く前にシンボリックリンクを弾いている（S12）ので、
> リンク先へ直接書き込む経路は無い」と書いていた。**これは誤り**である。
> `_collect` にシンボリックリンクのフィルタは無い（`test_collect_does_not_filter_symlinks`
> で固定した）。実際の事前判定は `fmt` 本体の 1 箇所だけで、判定と書き込みの間には
> 窓がある（TOCTOU）。退避路の `os.access` もリンクを辿るので防御にならない。
> **誤りの向きが危険側**（この記述を信じて `fmt` のガードを外すと窓が常時開く）だった。

正しい防御の所在（ラウンド 3 で構造化。どちらも競合しない）:

| 経路 | 防御 | 性質 |
|---|---|---|
| `_write_in_place`（退避路） | `os.open(..., os.O_NOFOLLOW)` → `ELOOP` を `SymlinkWriteRefused` に | **カーネルが拒む**。判定と書き込みの間に窓が無い |
| `_write_atomically`（既定） | `mkstemp` は `O_CREAT \| O_EXCL` で辿らず、`os.replace` は**リンクの実体**を置き換える | リンク先には原理的に触れない |
| `fmt` 本体の `is_symlink()` | 整形せず飛ばして知らせる（S12 の利便性） | TOCTOU あり。**外しても上の 2 つで守られる** |

実測（`os.replace` 直前の `lstat` 判定を外した状態で `_write_atomically` を直接呼ぶ）:
リンク先 `victim.jin` の中身は `'元の中身\n'` のまま、`swapped.jin` は通常ファイルに化けた。
**境界越えは起きず、残るのは「リンクが通常ファイルに化ける」ことだけ**である。これは
S12 の方針違反なので `os.replace` の直前で拒む（この判定は競合しうるが、負けても
起きるのはリンクの置き換えだけで、リンク先が書き換わることはない）。

`getattr(os, "O_NOFOLLOW", 0)` のような握り潰しはしない。未対応環境で 0 に落ちると
防御が黙って消えるため（本プロジェクトは macOS / Linux。`ELOOP` は両方で確認済み）。

**退避してよいのは `PermissionError` のときだけ**（修正ラウンド 4・security review T-1）。
容量不足（`ENOSPC`）や「書く直前に消えた」（`ENOENT`）で退避すると、`_write_in_place` が
`O_TRUNC` で**元の内容を消してから**同じ理由で失敗しうる。退避が被害を広げる側の失敗は
退避させず、診断にして exit 1 で終わる。分類は `_classify_write_failure`。

`PermissionError` 以外の `OSError` は素通しにしない（S5 → N2 → T-1 と 3 度出た同型の欠陥）。
`fmt` は `WriteRefused` しか捕まえないので、素通しは未捕捉トレースバックを意味する。
`errno` は `_WRITE_ERRNO_HINTS` で利用者向けの言葉に変える（表に無い `errno` は
`strerror` をそのまま出す。捏造しない）。`except BaseException` は後始末をして
**再送出するだけ**で、`KeyboardInterrupt` / `SystemExit` は従来どおり伝播する（S2 の教訓）。

### 2.11.1 `Path.is_symlink` を使うこと自体が意味を持つ（修正ラウンド 4・点 3 の訂正）

修正ラウンド 3 で私は「`lstat` 判定を `mkstemp` の**後ろ**に置いたのは、前に置くと
退避路へ到達する前に発火して `O_NOFOLLOW` を消す変異が赤くならなくなるため」と説明したが、
**reviewer が実測でこれを反証した**（前へ移しても変異は赤いまま・4 failed）。

効いているのは配置ではなく、`_write_atomically` が **`Path(...).is_symlink` を使っていること**である。
退避路の回帰テストは `monkeypatch.setattr(Path, "is_symlink", ...)` で `Path.is_symlink` を
丸ごと殺し、`_write_in_place` の `O_NOFOLLOW` だけが残った状態を作る。ここを
`os.path.islink()` に書き換えると monkeypatch が効かなくなり、**変異が捕まらなくなる**。

配置の判断自体は妥当なので変更していないが、理由づけを実態に合わせて訂正し、
`guard: _write_atomically -> Path(path).is_symlink` として機械で固定した
（変異 `P3-islink` で赤くなることを実測）。

### 2.11.2 失敗の伝え方を 3 つに分ける（修正ラウンド 5・security review V-1）

T-1 の修正で堅牢性は上がったが、**伝達が静かで誤解を招く方向に一歩下がっていた**。
退避路の書き込みが途中で失敗するとファイルは 0 バイトになるのに、出る文言は
「書き込めません」「整形できませんでした（診断を先に直してください）」で、
**内容が失われたこと**も**やるべきこと**も伝えていなかった（CLI 経由で再現済み）。

`jin fmt` の失敗を 3 つに分けた。要約行も別々に出す。

| 状況 | 元の内容 | 要約行 | 利用者がやること |
|---|---|---|---|
| 診断 / 正準形にできない | 無傷 | 整形できませんでした（診断を先に直してください） | `.jin` を直す |
| 書き始める前に失敗（権限 / 容量 / リンク） | **無傷** | 書き込めませんでした（ファイルの内容は元のままです） | 環境を直して再実行 |
| 書き始めたあとに失敗（退避路のみ） | **失われた** | 書き込みの途中で失敗し、ファイルの内容が失われました。バックアップから復元してください | **復元** |

3 つ目は専用の例外 `ContentLostOnWrite` で表す。`_write_in_place` は `O_TRUNC` で開くので、
**開けた時点で元の内容は消えている**。開く前に落ちた場合（`ELOOP` / 権限）は無傷なので、
同じ文言にしてはいけない（無傷のファイルまで復元させることになる）。

あわせて例外の文言からパスを外した。表示側（`fmt`）がパスを付けるので二重に出ていた。

この退避（原子性を諦めて書く）は要件書に規定が無い挙動変更なので、
implementation-notes.md §6 の **Q-JIN-IMPL-11** として人間の確認に上げてある。

### 2.12 CI の uv バージョン固定（修正ラウンド 2・wiring review N-01）

`.github/workflows/ci.yml` の `Sync dependencies` が `uv sync --frozen` だったため、
job env の `UV_LOCKED` が**打ち消されていた**。実測（2026-09-04・同一リポジトリ）:

| コマンド | uv 0.7.8 | uv 0.12.9 |
|---|---|---|
| `UV_LOCKED=1 uv sync --frozen`（clean） | **EXIT=2**（`the argument '--frozen' cannot be used with '--locked'`） | **EXIT=0**（`warning: Ignoring UV_LOCKED because --frozen was provided`） |
| `UV_LOCKED=1 uv sync --frozen`（stale） | EXIT=2 | **EXIT=0**（stale なのに通る） |
| `UV_LOCKED=1 uv sync`（clean） | EXIT=0 | EXIT=0 |
| `UV_LOCKED=1 uv sync`（stale） | EXIT=2 | EXIT=1 |

**どちらの版でも `--frozen` 付きでは lock を検証していない。** `--frozen` を外した。

`setup-uv@v5` に `version: "0.12.9"` を明示した。**値の根拠**:

- 版を固定しないと、入る uv によって上表の左列（クリーンでも無条件失敗）に転ぶ
- 0.12.9（2026-09-01 リリース）は wiring reviewer が隔離コピーで検証済みで、
  本ラウンドでも同じバイナリで再確認した:
  `uv lock --check` **EXIT=0** / `UV_LOCKED=1 uv sync`（clean）**EXIT=0** /（stale）**EXIT=1**
- コミット済みの `uv.lock` は uv 0.7.8 が作ったものだが、0.12.9 でも `uv lock --check` が
  EXIT=0 なので `UV_LOCKED` 下で毎回赤になることはない（この確認が申し送りの要件だった）
- `version:` は `astral-sh/setup-uv@v5` の action.yml に**実在する入力**である（実測で確認）

- 版を固定しても W-06（`.python-version` で Python を選ぶ）は壊れない。隔離コピーで
  `uv 0.12.9 sync` → `uv run python -c "sys.version_info"` を実行し、
  `.python-version` の `3.14` から **Python 3.14.6** が選ばれることを実測した
  （`setup-uv` の `python-version` 入力は使っていない）

**AI の好みで選んだ版ではない**。「reviewer と実装者の両方が同じ 2 コマンドの EXIT=0 を実測した版」
という事実に基づく。別の版へ上げるときは同じ 2 コマンドを通してから確定すること。

固定値の保守手順は人間に確認を上げてある（implementation-notes.md §6 の **Q-JIN-IMPL-12**）。
契約テスト `test_uv_version_is_pinned` が固定しているのは「`version:` があり `latest` ではない」
ことだけで、特定の版番号は固定していない。**版を上げてもテストは緑のまま通る**ので、
上げるときは上の 2 コマンドの再実測が人間側の責務になる。

### 2.13 `.env.example` のキー名（DP-COMMON-15・ラウンド 2 で値を確定）

| 決めた値 | 出典（google-adk 2.8.0 / google-genai の site-packages・2026-09-05 実測） |
|---|---|
| `GOOGLE_GENAI_USE_ENTERPRISE`（`0` / `1`） | 書く側: `google/adk/cli/cli_create.py:127-129`。読む側: `google/adk/utils/env_utils.py:63-79`（`GOOGLE_GENAI_USE_VERTEXAI` は deprecated と警告） |
| `GOOGLE_API_KEY` | 書く側: `cli_create.py:131`。読む側: `google/genai/_api_client.py:136`（`GEMINI_API_KEY` と両方あれば `GOOGLE_API_KEY` 優先・`:137-140`） |
| `GOOGLE_CLOUD_PROJECT` | 書く側: `cli_create.py:133`。読む側: `google/adk` 内 `environ.get("GOOGLE_CLOUD_PROJECT")` 9 箇所（grep） |
| `GOOGLE_CLOUD_LOCATION` | 書く側: `cli_create.py:135`。読む側: 同 8 箇所 |

配置: Gemini API 用の 2 行（`GOOGLE_GENAI_USE_ENTERPRISE=0` / `GOOGLE_API_KEY=`）を有効行、Vertex 用の 3 行をコメント行にした。
これは `adk create` が「API キーなら `USE_ENTERPRISE=0` + `GOOGLE_API_KEY`、Vertex なら `USE_ENTERPRISE=1` + project + location」と
書き分ける実装（`cli_create.py:126-135`）をそのまま写したもの。`.env` の読み方（`<out>/<root_name>` から親へ辿る・
`google/adk/cli/utils/envs.py:53-74`）から、要件書 §3.1 の `<out>/.env.example` の位置で効くことも確認した。

### 2.14 `flow.exit` の等値比較（DP-JIN-CODEGEN-RUNTIME-01 の派生・要件書に規定が無い）

実測: `LlmAgent.output_key` は LLM の応答テキストを **str** で `session.state` に入れる（`llm_agent.py:1005-1045`・
`{'approved': 'true'}`）。`equals: true` を `state["approved"] == True` で比べても成立しない。

決めた規則（`docs/spec/model.md` §3.4 の `flow-exit-equality` 表 / 実装は生成物内 `_state_matches` の 1 箇所）:
文字列は前後の空白を除き、`equals` が str なら文字列比較、bool / number なら **JSON として読んで同じ JSON 型で比較**
（`"true"` = `true`、`"3.0"` = `3`。`"True"` / `"1"` は `true` に一致しない）。JSON として読めない文字列は不一致。
文字列以外の値（ツールが state に入れた bool / number）は型を保ったまま比較。

根拠: (a) `output_key` に入るのは常に文字列なので「文字列を JSON として読む」しか型を回復する手段が無い、
(b) `"True"` / `"1"` を true に寄せる緩い規則は「LLM が何を返せば終わるか」を曖昧にし、`.jin` の `equals` の型が意味を失う、
(c) 厳密に JSON 型で比べれば `equals` の 4 型（bool / int / float / str）それぞれに一致・不一致の例を機械で固定できる
（`test_runtime.py::test_state_matches_semantics` 16 ケース）。**要件書に規定が無い値**なので人間確認を
`implementation-notes.md` Phase 2 節の HANDOFF（Q-JIN-P2-02・non-blocking）に載せた。

### 2.15 `research.*` スタブの供給方法（Issue #3 の罠 1）

`examples/researcher/researcher.jin` の `ref`（`research.tools:web_search` など）はリポジトリに実体が無い。
examples の `ref` は書き換えず、`tests/fixtures/stubs/research/{__init__,tools,guards}.py` を作り、テストが
`sys.path`（in-process: `monkeypatch.syspath_prepend`）/ `PYTHONPATH`（実バイナリ: `tests/contract/test_cli_contract.py`）で
供給する。スタブは import されるだけでは何もしない（副作用なし・ネットワークなし）。本物の `jin run` は利用者の
cwd / `PYTHONPATH` の `research.*` を import する（`docs/spec/adk-mapping.md` §6・README）。

### 2.16 import-linter の `layers`（Issue #3 の罠 5）

`"jin_adk | jin_render"` は import-linter 2.14 で `Missing layer 'jin_render': module jin_render does not exist.` EXIT 1 になる
（`scratchpad/lintprobe` で実測・`version-matrix.md` §8.3 #14）。Phase 2 は `["jin_cli", "jin_adk", "jin_core"]` と書き、
Phase 3 で `|` 結合する旨を `pyproject.toml` のコメントに残した。契約テスト
`test_layers_contract_keeps_sibling_packages_in_one_element` は「片方しか無いペア」を素通しにするので緑（設計どおり）。
`lint-imports` は `Analyzed 50 files, 139 dependencies` / 3 kept（骨格 `jin_adk/__init__.py` だけの時点で 36 files だったので、Phase 1 末は 35 files。jin_adk の 7 モジュール + 生成テンプレート読込で 14 files 増）。

### 2.17 `jin build` は ruff format を後処理で実行しない（Issue #3 の罠 4）

テンプレートの出力を最初から整形済みの形（4 スペース / 1 引数 1 行 / 複数行 rune は暗黙連結）にし、
後処理を置かない。理由: (a) ruff を runtime 依存に足すと `jin-adk` を入れる全環境に ruff が要る、
(b) ruff の implicit-concat 結合で複数行 rune の可読な形が 1 行に畳まれ、diff しやすさ（NFR-GEN-001）が落ちる、
(c) 生成物の安定性はスナップショット（syrupy）と別プロセス・別 `PYTHONHASHSEED` のバイト一致
（`tests/contract/test_cli_contract.py::test_build_output_is_byte_identical_across_processes_with_different_hash_seeds`）で
担保できる。よって `jin-adk` の runtime 依存は `google-adk` / `jinja2` / `jin-core` の 3 つだけ。

### 2.18 `jin run` は宣言済み state を `None` で seed する（実測に基づく）

実測: `instruction` の `{key}` が session.state に無いと ADK 2.8.0 は `KeyError` で実行を落とす
（`instructions_utils.py:174`）。`examples/researcher` の `{findings}` は自分の `output_key` なので初回は必ず未設定。
machine 条件 5（`jin run --model fake` が examples 2 本で exit 0）に直撃するので、`jin run` は `.jin` が宣言した
全 circle の `state[].name` を `None`（ADK は空文字で描画・実測）で seed する（`runtime.py:158-159`）。
**生成物を `adk run` で単体実行したときには効かない**（human_only の観点として `implementation-notes.md` に明記。
HANDOFF Q-JIN-P2-01）。

### 2.19 `jin run` は cwd を `sys.path` の末尾に足す（修正ラウンド 1 で先頭 → 末尾へ。DP-IMPL-JIN-P2-SYSPATH-01 → **修正ラウンド 2 で import 窓へ**・下の注記）

console script は cwd を `sys.path` に含めないため、`jin run examples/...` を直接叩くと `research` が見つからない
（`PYTHONPATH` を渡せば動く）。`adk run` と同じ「カレントディレクトリのモジュールを import できる」体験にするため
`jin_cli/main.py` の `run` が `sys.path.insert(0, os.getcwd())` する（`guard: run -> sys.path.insert`）。
`jin run` は元々任意コード実行であり、cwd の追加が攻撃面を広げるわけではない（同じ相手が `ref` を書く）。
`test_build_run.py::test_run_adds_cwd_to_sys_path` が固定。

> **修正ラウンド 1 の注記（F-S-P2-003）**: 上の「攻撃面を広げるわけではない（同じ相手が `ref` を書く）」は**不正確**だった。
> `ref` を 1 つも持たない `.jin` でも、ADK が実行中に遅延 import する名前（`authlib` / `requests` …）が cwd にあれば実行される
> （security reviewer の実測。`pipeline.jin` + cwd の `authlib/__init__.py`）。`.jin` 作者と cwd の支配者は別人でありうる。
> **撤回**: 「攻撃面を広げるわけではない（同じ相手が `ref` を書く）」は撤回する。
>
> **決定（DP-IMPL-JIN-P2-SYSPATH-01・auto-decider の再判断・`implementation-plan.json` の decision_record）**: `sys.path.append(cwd)`
> （末尾）。site-packages にある名前（`authlib` / `requests` / `google.*` …）は本物が先に解決され、cwd で解決されるのは
> 「どこにも無い名前」= `research.*` のような `ref` 先だけになる。`jin_cli/main.py` の `run` が行い（`hazard: run -> sys.path.append`）、
> `run_model` は触らない。
>
> **残存（明記）**: ADK が任意依存として遅延 import する**未インストール**の名前（`mcp` など。`_resolve_builtin` が不正な
> `builtin` 名を受けたとき `__all__` の全名を `getattr` する経路は `generate()` 内 = cwd 追加後に踏む）は、末尾でも cwd から
> 解決される。したがって「信頼しないディレクトリを cwd にして `jin run` しない」という利用者向けの防御線は末尾にしても必要で、
> CLAUDE.md / README / adk-mapping.md §6 に残す。
>
> 固定: `test_build_run.py::test_run_adds_cwd_to_sys_path`（含まれる・先頭ではない）/ `tests/contract/test_cli_contract.py::test_cwd_cannot_shadow_an_installed_package_in_a_real_process`
> （cwd の `authlib/__init__.py` が走らない = F-S-P2-003 の再現入力）。変異 `CLI-no-cwd` / `CLI-cwd-first`。
>
> **修正ラウンド 2 の注記（F-S-P2-101・DP-IMPL-JIN-P2-SYSPATH-01 の再々判断・2026-09-05）**: `append` でも足りなかった。
> google-adk 2.8.0 は LLM 要求のたびに**未インストール**の任意依存（`anthropic` / `openai` / `a2a` / `bcrypt` / `simplejson` /
> `chardet` / `socks`）を遅延 import しようとする（`google/adk/models/contents.py` → `anthropic_llm.py`・`ImportError` は握りつぶす）ので、
> `ref` を持たない `pipeline.jin` でも cwd の `anthropic/__init__.py` が Runner 実行中に走る（reviewer の実測・末尾でも）。
> 経緯: `insert(0)`（ラウンド 2）→ `append`（修正ラウンド 1）→ **import 窓**（修正ラウンド 2）。
>
> **決定（chosen）**: cwd を**生成モジュール（`agent.py`）の import の間だけ** `sys.path` の末尾に足し、import が終わったら
> （例外時も）`finally` で必ず取り除く。`jin_adk.runtime.load_generated` / `run_model_async` / `run_model` が `extra_sys_path` を受け、
> `_sys_path_window` が `_import_agent_module` の前に append・`finally` で remove する（元から `sys.path` にある値は足さないし
> 取り除かない）。CLI の `run` は `[os.getcwd()]` を渡すだけで `sys.path` を触らない。`jin build` / `jin check --resolve` / `jin_core` も触らない。
> `hazard: _sys_path_window -> sys.path.append` / `guard: _sys_path_window -> sys.path.remove`（`main.py` の `hazard: run -> sys.path.append` は消えた）。
>
> **「攻撃面を広げない（同じ相手が `ref` を書く）」の書き直し**: この主張は **import 窓の中に限って**成り立つ。窓の中で cwd から解決されるのは
> `ref` 先と、`builtin` を import するときに `google.adk.tools` が遅延 import する未インストール名（`mcp` など）であり、どちらも
> `.jin` 作者が書く `ref` / `builtin` に由来する。Runner 実行中は cwd が `sys.path` に無いので、`.jin` 作者と無関係に ADK が
> 遅延 import する名前は cwd から解決されない。
>
> **残存（明記）**: (1) import 窓の間は cwd のモジュール（`ref` 先・`builtin` の遅延 import 先）がこのプロセスの権限で実行される。
> 「信頼しないディレクトリを cwd にして `jin run` しない」「`jin run` は自分が中身を確認した `.jin` にだけ使う」（CLAUDE.md に
> `jin run` を名指し）は維持。(2) `ref` 先のモジュールが自分の関数の中で**実行時に**遅延 import する名前は cwd から解決できない
> （`PYTHONPATH` に委ねる。CLAUDE.md / README / adk-mapping.md §6 に明記）。
>
> 固定: `test_build_run.py::test_run_adds_cwd_to_sys_path`（**import 中は `research.*` を解決でき、実行後は cwd が `sys.path` に含まれない**。
> `_import_agent_module` を包んで窓の中の `sys.path` を観測）/ `test_runtime.py::test_extra_sys_path_is_present_only_during_the_import`
> （`yield` 時点で無い・元からある値は触らない・import 失敗でも外す）/ `tests/contract/test_cli_contract.py::
> test_cwd_cannot_supply_an_uninstalled_optional_dependency_during_the_run`（**`anthropic/` 版・別プロセス**。`anthropic` が
> 未インストールであること（skipif）と ADK が実行中に `anthropic` を遅延 import することに依存する = F-W-P2-102 の明記）。
> 変異 `CLI-no-cwd`（`extra_sys_path=[]`）/ `RUN-cwd-stays-after-import`（`finally` の remove を消す → 3 件赤・`anthropic` 版を含む）/
> `RUN-cwd-first`（`insert(0)`）。旧 `CLI-cwd-first` は `RUN-cwd-first` に移した。
> （修正ラウンド 3・F-V-P2-204: `test_run_adds_cwd_to_sys_path` は `test_cwd_is_on_sys_path_only_while_importing_the_generated_module` に改名。上の記述は改名前の名前）`authlib` 版の契約テストは「インストール済み名は
> 窓の中でも本物が先」の記録として残す（`RUN-cwd-stays-after-import` には反応しない・docstring に明記）。

### 2.20 StateCheckAgent の重複（ADR-008 の condition）

1 ファイルに 1 クラス定義 + loop ごとにインスタンス（§1 の表参照）。毎回展開する案を採らなかった理由: 同名クラスの
再定義は Python では合法だが、生成物の diff（NFR-GEN-001）で「どの定義が生きているか」が読みにくい。1 定義にしても
生成物の自己完結性（ADR-008 案 A の趣旨）は変わらない。

### 2.21 トレースの `final` と `escalate` の定義（要件書 §3.4 の enum を埋めた）

要件書は kind の 5 種を列挙するだけで判定規則を書いていない。`docs/spec/adk-mapping.md` §2.4 の `trace-kinds` 表に決めた:
`final` は実行全体の最後の行が `model` だったときだけその行を付け替える（`TraceWriter` の 1 行遅延）。
`escalate` は StateCheckAgent の判定イベントを**一致しなかった回も**含む（`output.matched` で区別）。
ストリーミングの `partial` イベントは行にしない。`tests/spec/...::test_trace_kinds_table_matches_the_implementation` が
表と実装の集合一致を固定。人間の期待と違いうるので HANDOFF Q-JIN-P2-05 に載せた。

### 2.22 トレース JSONL は 0600 で作る（修正ラウンド 1・F-S-P2-008）

`--trace` の出力にはツール引数・state の実値・モデル出力が入る。DP-COMMON-14 の axis「秘密情報（プロンプト・モデル出力）の扱い」に
照らし、既定を所有者のみ（`0o600`）にして、緩めるのは利用者の `chmod` に委ねる。`jin build` の生成物（コード・共有前提）が 0644 なのとは
性質が違う。~~既存ファイルへ書く場合はモードを変えない（`O_CREAT` の mode は新規作成時にだけ効く）。~~
**修正ラウンド 2（F-C-P2-103）で変更**: 既存ファイルでも `os.fchmod(fd, 0o600)` で所有者のみに絞る。前回 0644 で作った
（ラウンド 0 の生成物など）トレースを指定し直すと今回のツール引数・state が world-readable のまま書かれ、「0600 で作る」が
新規作成時にしか成り立たなかった。利用者が名指しした先でも中身の性質は同じなので安全側に倒す（緩めるのは利用者の `chmod`）。
`guard: _open_trace -> os.fchmod`。
`test_build_run.py::test_trace_file_is_created_owner_only` / `::test_existing_trace_file_is_made_owner_only` /
変異 `CLI-trace-world-readable`（`fchmod` の mode を 0644 に → 両テスト赤）/ `CLI-trace-keep-existing-mode`（`fchmod` を消す → 既存版が赤）。

### 2.23 修正ラウンド 1 で決めた挙動（レビュー finding への回答・人間判断は不要と判断した根拠つき）

| 論点 | 決めた挙動 | 根拠 |
|---|---|---|
| circle 名の NFKC（F-S-P2-002） | 正規形でない名前は **拒む**（正規化して通さない） | 正規化して通すと `.jin` の名前と ADK の agent 名・生成コードの変数名がずれ、トレースの `agent` と `.jin` が一致しなくなる。拒めば書き手が直すだけ |
| `ref` の callable 名が builtin 名と同じ（F-C-P2-001） | builtin 名を `taken` に入れて **別名 import**。同じ circle 内なら ADK ツール名の重複として BuildError | 別 circle なら実害が無い（ADK のツール名は agent ごと）。同 circle は `FunctionTool.name == func.__name__` で衝突するので生成しない |
| ADK ツール名の重複（F-C-P2-002） | circle 内で `kind: tool` → callable 名 / `builtin` → 名 / `summon` → circle 名 を集計し BuildError | ADK 2.8.0 は警告だけで後勝ち（片方が呼べない）。黙って生成しない（NFR-FAIL-001）。実行時の `func.__name__` は別途 `bind_tools` が null にする |
| root に親（F-C-P2-016） | `generate` の BuildError（参照側 pointer）。`jin check` の診断化は DP-REVIEW-JIN-P2-001 | 診断コードは増やせない（要件書 §2.4 の変更） |
| transfer の 2 event（F-C-P2-004） | function_call 側は**行にしない**。応答側の `transfer` 行だけ | 呼び出しと応答が同じ意味（転送）で、`tool` 行にすると `.jin` に無いツール名の null pointer になる |
| `actions.escalate`（F-C-P2-005） | tool 行を残し、その後に `escalate`（name = author / pointer = `/circles/i`）を足す | 1 part = 1 行の原則を保つ。checker 由来（`/circles/i/flow/exit`）とは表で 2 行に分けた |
| text + function_call（F-C-P2-007） | `model` 行 → `tool` 行の順で両方出す | テキストを捨てない |
| error event（F-C-P2-021） | `model` 行の `output` を `{"error_code", "error_message"}` にする | 空応答の正常終了に見せない。最後の行なら `final` に付け替わるが output の形で区別できる |
| `equals` の空白（F-C-P2-008） | 両辺 strip（対称） | DP-IMPL-JIN-P2-EXITEQ-01 の chosen「文字列は前後の空白を除き」の範囲内。表の `"yes"` = `" yes "` を対称に読む |
| `run_model_async`（F-C-P2-019） | 公開。CLI だけが `asyncio.run` する。同期の `run_model` はループ無しの呼び出し側（テスト）用に残す | Phase 4 の pygls から呼べる形 |
| ファイル名の入口検査（F-S-P2-001 / 005 / 016） | 制御文字 / U+2028 / U+2029 / 孤立サロゲートを含む名前は exit 2。ヘッダは `py_literal` を通す（二重） | `.jin` 本文と同じ規律（JIN002 が本文に対して行っていること）をファイル名にも適用 |

### 2.24 ラウンド 3（Phase 3）で**値を確定した**実装判断

要件書 §2.5 と `docs/spec/layout.md` §1〜§2 は環半径・配置角・k の規則までしか決めていない。以下は
**Phase 3 の実装で確定した値**であり、**要件値ではない**。全件が `docs/spec/layout.md` §6 の表にも
同じ根拠で書いてある（仕様側とコード側の片方だけを直さないため）。

#### 2.24.1 丸め桁数 = 3 桁固定小数（DP-JIN-SVG-DETERMINISM-01 の condition）

`format(x, ".3f")`。末尾ゼロを落とさない（落とすと「数値がすべて 3 桁で終わる」検査が成立しない）。
`-0.0` は `0.0` に正規化する（`cos(90°)` 級の微小値の符号は libm で揺れ、`-0.000` と `0.000` の差が
開発機と CI でスナップショットをずらす）。根拠 2 点:

1. **px 換算後の解像度に対して十分**: キャンバスは 1000 px 角、正規化 1.0 が 400 px。刻み 0.001 px は
   devicePixelRatio 4 で描いても 1 デバイスピクセルの 1/4000。
2. **桁を増やすと末尾ノイズがプロセス間で揺れる**: 最大座標は 1000 px（キャンバスの縁）で、
   倍精度の 1 ULP は約 1.1e-13 px。libm の `sin` / `cos` が環境ごとに 1 ULP 違ってもこの差は刻み 1e-3 の 10 桁下で
   境界をまたがないが、10 桁以上に増やすとそのままバイト列に出る。
   `test_svg.py::test_rounding_step_is_far_above_the_float_noise` が数値でこれを固定する。

**副次の決定**: SVG の楕円弧コマンド `A` は使わない。`A` の large-arc-flag / sweep-flag は「0」か「1」の
1 文字でなければならず（SVG の文法）、`0.000` は文法違反になる。円弧は 90 度以下の 3 次ベジェへ分割して
描く（`jin_render.geometry.arc_segments`・制御点係数 `4/3 * tan(θ/4)`）。同じ理由で入れ子の小陣に
`transform` を使わない（`transform` の中の数値も丸めを通す必要があり、書き出し経路が 2 本になる）。

#### 2.24.1a 修正ラウンド 1 で覆った判断（Phase 3 Stage 5 レビュー）

| 項目 | ラウンド 0 の判断 | ラウンド 1 の判断 | 理由 |
|---|---|---|---|
| `jin render -o` の新規ファイルのモード | `0o644` 固定（umask を無視） | `0o644 & ~umask` | `jin build` は `os.open(name, O_CREAT \| O_EXCL, 0o644)` で作り、カーネルが umask を引く。「`jin build` にそろえる」と書きながら実効モードがそろっていなかった。umask 0o077 の利用者の SVG だけが group / other に読めていた（F-S-P3-004 / F-V-P3-015）。実装は `jin_cli.main._new_file_mode` |
| `loop` の節の配置と辺 | 節 j を角位置 j に置き、辺は `j → (j+k) mod n` | 節 j を角位置 `(j*k) mod n` に置き、辺は `j → (j+1) mod n` | 見た目の星形は同じだが、矢じりが実行順を指さなかった（要件書 §2.5「辺の順を訪問順に一致させる」）。`gcd(n,k)=1` で写像が全単射なので両立する（F-C-P3-002・HANDOFF DP-IMPL-JIN-P3-LOOP-STAR-ORDER-01） |
| `summon` の紋 | wrapper の `<g>` に pointer を載せるだけ | 外枠の円を wrapper 直下に描く | `<g>` の朱は入れ子 `<g>` の `stroke="#000000"` に断たれ、layout.md §7.2 が言う「外枠が強調される」ものが描画に無かった（F-C-P3-003） |
| 放射線・弦の終端 | `NESTED_SCALE * RING_BOUNDARY` 固定 | 入れ子が実際に届く半径から導く | 境界の無い小陣（指示環 0.35 まで）で線が浮いていた（F-C-P3-005） |

#### 2.24.1c flow の節の縮尺は兄弟の数から決まる（Phase 3 修正ラウンド 2）

`NESTED_SCALE`（0.28）は**上限**であって固定値ではない。flow の節を道具環と同じ 0.55 に
等間隔で置くと、隣り合う節の中心距離は `2 * 0.55 * sin(pi / n)` になる。節の外枠がこの
半分を超えると弦が 1 本も描かれず、訪問順を示す矢印がモデルの大きさで**黙って消える**
（F-C-P3-101。examples 同型の中身で n >= 7、最大の中身では n >= 6 で消えていた）。

節の外枠を `r <= 0.55 * sin(pi / n) - (ARROW_HEAD + ε)`（`ARROW_HEAD = 0.05`, `ε = 0.01`）に
収め、超える分は**外枠・中身・隙間を同じ係数で**縮める。要件書 §2.5 の `sequence` は
「開いた弦列(矢印)」で例外を許していないので、弦を消す側ではなく節を縮める側を採った。
n >= 20 では上限が点の半径 0.03 を下回るので点に落とす（n = 19 はまだ小陣）。そのあとの
境界は 2 つある: **n >= 32** で弦の本体が矢じりより短くなり（弦は描かれる）、**n >= 58** で
弦そのものが消える（R2 に「n >= 32 で消える」と書いたのは 2 つの条件の混同・F-C-P3-205）。
式と境界の実測値は `docs/spec/layout.md` §6。機械固定は
`test_layout.py::test_every_flow_chord_is_drawn_whatever_the_node_count`（n=3..12 × 中身 3 種 ×
sequence / loop）と `test_the_chord_gap_matches_the_drawn_node`。変異 `FLOW-node-scale-fixed` /
`FLOW-no-node-limit` / `FLOW-extent-no-limit` / `FLOW-point-fallback-off` で赤を実測。

道具環の `summon` 紋にはこの縮小を適用していない（弦を持たないため）。その結果として
n >= 6（最大の中身）/ n >= 7（examples 同型）で隣の紋と重なる既知の制約があり、扱いは
**`DP-REVIEW-JIN-P3-001`** として未決（fix-later・判断期限は Phase 5 のエディタ着手前）。

#### 2.24.1b XML 1.0 `Char` の外の文字（Phase 3 修正ラウンド 1）

`jin_render.svg.xml_chars` が XML 1.0 の `Char` に無い符号位置を U+FFFD へ置き換える。
`jin_core` は C0 / C1 / DEL / 孤立サロゲートを既に拒むが、**非文字 U+FFFE / U+FFFF は通す**ので、
そのまま書くと `xml.etree` が SVG 全体を拒む（F-S-P3-005）。**`jin_core` の検証は変えない**
（診断コードを増やさない・CLAUDE.md）。これは描画側の出力契約である。

#### 2.24.2 強調色 = `#cc0000`（要件値ではない）

要件書 §2.5 は「白黒 2 値 + 強調 1 色（トレース時のみ）」としか書いておらず、色の値は無い。
魔法陣の朱墨に倣って朱を採り、**白地に対する輝度コントラスト比 5.9:1 / 黒線に対して 3.6:1** で
白黒どちらの隣でも見分けられることを条件にした。`<style>` を使わず属性で完結させる（要件書 §2.5）ので、
線で描く要素は `stroke`、文字と塗り潰しの点は `fill` を差し替える。
**人間の好みが割れうる値**なので HANDOFF `DP-IMPL-JIN-P3-ACCENT-COLOR-01` に載せた。

#### 2.24.3 キャンバス・要素の大きさ・配置（要件書に無い値）

`docs/spec/layout.md` §6 の表が正本（キャンバス 1000 px 角 / 正規化 1.0 = 400 px / 核 0.12 /
紋 0.06 / state 0.05 / 刻印 0.12 / `await` の欠け 16 度 / `delegate` 0.05・環 0.82 / 入れ子の縮尺 **上限** 0.28（flow の節は §2.24.1c で兄弟間隔まで縮む・n >= 20 なら点） /
深さ 2 の点 0.03 / `flow.steps` の節は 0.55 / 矢じり 0.05 / `flow.exit` の印は中心の菱形 0.05 /
rune のフォント 0.05・43 文字で切り詰め / トレースの点は環 1.10・半径 0.025）。
決め方（境界環をはみ出さない・12 個並べても重ならない・欠けと分かる …）も同じ表に書いた。

#### 2.24.4 `data-jin` 契約の解釈（`<svg>` と `<defs>` を対象外にする）

要件書 §2.5 は「描画された全ての要素」と書いている。`<svg>` は**文書そのもの**であって描画された要素では
なく、`data-jin-kind` の 9 種のどれにも当たらない。`<defs>` の中身（`<textPath>` が参照する経路）は
それ自体が描かれない。したがって両者を契約の対象外とし、テストは「`<svg>` と `<defs>` 配下を除く全要素」で
回す。**10 種目の kind を作らない**ための解釈である。同じ理由で背景の塗り（`<rect>`）を置かない
（置くと `data-jin` を持たない描画要素ができる）。HANDOFF `DP-IMPL-JIN-P3-SVG-ROOT-CONTRACT-01`。

追加属性（`data-jin-ref` / `data-jin-fired` / `data-jin-seq` / `data-jin-root`）は契約に反しない。
契約は「2 属性を持つこと」であって「2 属性しか持たないこと」ではない（layout.md §3.1）。

#### 2.24.5 trace overlay の強調規則（祖先一致と referent 規則）

pointer を末尾から削りながら「`data-jin` の完全一致」または「`data-jin-ref` の一致」を探し、
最初に見つかった段で止める（layout.md §7.1）。referent 規則が無いと、focus=root のとき下位 circle の
`model` 行（`/circles/4/core` など）が**何も強調しない**。参照を表す要素の `data-jin` は編集の hit-test
のために参照側でなければならないからである。HANDOFF `DP-IMPL-JIN-P3-OVERLAY-REFERENT-01`。
検出は `tests/contract/test_render_contract.py::test_every_live_pointer_resolves_at_the_root_focus`
（`jin run --model fake` を実際に回した 11 行の全 pointer が root 焦点で解決する）。
変異 `OVL-exact-only` / `OVL-no-referent` / `OVL-no-ref-attribute` で赤を実測。

#### 2.24.6 壊れたモデルの描き方（layout.md §5）

`jin_render.render` は schema を通る `JinFile` なら例外を投げない（Phase 4 の `jin/renderSvg` が
直前の正常モデルで応答するため・NFR-AVAIL-001）。未解決の参照は破線の点、`root` 未解決は `circles[0]` +
`data-jin-root="unresolved"`、`circles` が空なら空キャンバス、JIN070 の `await` は 12 時に破線の刻印。
`tests/fixtures/errors/JIN0*.jin` のうちモデルになる 14 本（全 19 本中。JIN001 / JIN002 はモデルにならない）を parametrize で回す。
`--force` 等で「error があっても図を出す」選択肢は Phase 3 では足さない（HANDOFF
`DP-IMPL-JIN-P3-RENDER-ON-ERROR-01`。CLI は `jin build` / `jin run` と同じく exit 1 で拒む）。

#### 2.24.7 SVG スナップショットは正規化しない

design.yaml の machine 条件 1 は「（正規化後）が安定」と書いているが、`render` の出力は既にバイト単位で
決定的である（machine 2 / 7 を別テストで固定済み）。正規化を挟むと「正規化で消える差分」（座標の桁揺れ・
属性順の入れ替わり・要素順の変化）が検出できなくなる。どれも意味のある回帰なので**素のバイト列**で比較する。

## 3. `DP-CONFORMANCE-FAIL` の起票

`not_reflected` / `unknown` は **0 件**のため起票なし。
「部分 reflected」1 件（DP-COMMON-11 の apps/editor 側）は未着手 Phase の話であり制約違反ではないので、
`docs/pending-decisions.md` への起票ではなくテストによる可視化（`test_editor_contract_is_not_yet_enforced`）で扱った。

## 4. Stage 5 security 軸 reviewer への引き渡し

> **修正ラウンド 1**: §4.1 の表は F-S-P2-015 が指摘した「主張と実装の食い違い」（`source_name` / NFKC / cwd / `UnicodeEncodeError` 経路）を直したうえで更新した。`guard:` 記法の検査は `tests/contract/test_guard_claims.py` に移り、`packages/*/src` を走査する（列挙しない）。危険な操作の所在は `hazard:` タグ（F-S-P2-010）。

design.yaml `review_policy.review_axes_note` が挙げる security 3 観点のうち、本ラウンドに存在するのは
**(3) `--resolve` 指定時の Python 参照 import が任意モジュールを実行しうる点**だけである。

**修正ラウンド 1 で構造的に対処した（S1 / S2 / S19）。**

- 実装箇所は `packages/jin-cli/src/jin_cli/resolver.py` の `ImportResolver` **だけ**。
  `jin_core` は `jin_core/resolver.py` の `RefResolver` プロトコルしか知らず、import を一切行わない。
  Phase 4 の `jin-lsp` は `jin_core` にしか依存しないので、ws で公開されるコードパスから到達できない
- この隔離は import-linter の forbidden contract
  「ref の解決実装（任意コード実行）は jin_cli に閉じる」で機械的に落とす（`pyproject.toml`）。
  違反注入テスト（`tests/contract/test_dependency_direction.py`）で実効性も確認済み
- 既定は **オフ**（`--resolve` を明示したときだけ動く）。`jin check` の既定経路では import しない
- import は `KeyboardInterrupt` 以外の `BaseException` を捕まえる。`except Exception` では
  import 先の `sys.exit(0)` が投げる `SystemExit` を取りこぼし、`jin check --resolve` が
  **診断ゼロ・exit 0** で終わっていた（S2 / fail-open）
- 警告文は `README.md`（専用の節）/ `CLAUDE.md`（専用の節）/ CLI ヘルプの 3 箇所に書いた（S19）

(1) `jin run` の一時ディレクトリと (2) LSP の ws bind はいずれも Phase 2 / Phase 4 で、本ラウンドにコードが無い。

### 4.1 ラウンド 2（Phase 2）で新たに存在する観点 (1): `jin run` の経路

security reviewer に見てほしい箇所（すべて `guard:` 記法で主張を固定し、変異ハーネス
`delivery/20260904-1445-jin/phase2-mutations/mutate_p2.py` で赤を実測済み。修正ラウンド 1 で隔離コピー上の変異に改め、59 件）:

| 論点 | 実装 | 固定するテスト | 変異 |
|---|---|---|---|
| 一時ディレクトリのパーミッション | `jin_adk/runtime.py` `load_generated`: `tempfile.mkdtemp`（0700）+ `finally` で `shutil.rmtree` | `test_runtime.py::test_load_generated_cleans_up_its_temporary_directory`（0700 を stat で確認）/ `test_build_run.py::test_run_cleans_up_the_temporary_directory` | `RUN-plain-mkdir` / `RUN-no-cleanup` |
| `.jin` 由来の文字列が Python 式へ流れない | `jin_adk/codegen.py` `py_literal`（`json.dumps` + U+2028/2029/C1 のエスケープ）を全文字列に適用。識別子は `isidentifier()` + 予約語 + 予約名の検査。`ref` は `check_ref_format` | `test_codegen.py::test_py_literal_roundtrips`（10 種の悪い文字列）/ `::test_jin_strings_cannot_inject_statements`（生成物の AST が import と代入だけ）/ `::test_equals_of_every_json_type_is_rendered_as_a_python_literal` | `ESC-no-escape` / `ESC-repr` / `FAIL-ref-format` |
| import 中の `SystemExit` を成功扱いにしない（Phase 1 の S2 と同型） | `runtime.py` `_import_agent_module`: `KeyboardInterrupt` 以外の `BaseException` を `RunError` へ | `test_runtime.py::test_system_exit_in_generated_code_import_is_not_swallowed` | `RUN-swallow-systemexit` |
| **修正ラウンド 3**: ツール由来の `asyncio.CancelledError` も成功扱いにしない（F-S-P2-201 Medium / 202。round 0 から在った穴: root が LlmAgent のとき ADK `_cleanup_root_task` が root の cancel を warning で握って正常復帰し exit 0・「1 イベント」に見える） | `runtime._run_async` が function_call の id と `Event.long_running_tool_ids` を集め、`_unanswered`（応答の無い呼び出しのうち `await` の pause でないもの）があれば `RunError`。Runner から出た `CancelledError` は `asyncio.current_task().cancelling()` が 0 なら `RunError`、1（shutdown / 外からの cancel）なら再送出。CLI `run` / 同期 `run_model` に保険の `except CancelledError` → 1 行・exit 1 | `test_runtime.py::test_tool_cancelled_error_is_a_run_error_not_a_success[llm/sequence]` / `::test_await_pause_is_not_mistaken_for_a_missing_tool_response`（誤検知しない）/ `test_build_run.py::test_tool_cancelled_error_is_a_failure[llm/sequence]` / `::test_await_pause_still_exits_zero` / `::test_cli_turns_a_stray_cancelled_error_into_one_line` / `tests/contract/test_cli_contract.py::test_tool_failures_are_exit_1_without_a_traceback_in_a_real_process[cancel]`（実プロセス） | `RUN-ignore-unanswered-tool` / `RUN-await-pause-as-failure` / `RUN-cancelled-passthrough` / `CLI-cancelled-traceback` |
| **実行中**（ツール関数の中）の `sys.exit(0)` も成功扱いにしない（**修正ラウンド 1 の回帰 F-S-P2-102**: `asyncio.run` を CLI へ出した結果、asyncio が `SystemExit` をループの外へ再送出し exit 0 になっていた） | `run_model_async` は `SystemExit` を捕まえられない（届くのは `CancelledError`。これを `RunError` にすると shutdown 中の未処理例外としてトレースバックが漏れるので再送出）。`asyncio.run` を呼ぶ側が包む: CLI `run` の `except SystemExit` → `実行に失敗しました（SystemExit: <code>）` / exit 1、同期 `run_model` → `RunError`。`SystemExit` は裸の名前なので `guard:` では主張できず、テストと変異で固定 | `test_build_run.py::test_tool_sys_exit_at_runtime_is_a_failure`（exit 1・stderr に `SystemExit`・Traceback 無し）/ `test_runtime.py::test_system_exit_in_a_tool_at_runtime_is_a_run_error`（`RunError`・一時ディレクトリを残さない・asyncio ロガーに ERROR 無し） | `RUN-swallow-systemexit-at-runtime`（CLI）/ `RUN-swallow-systemexit-in-run_model` / `RUN-cancelled-to-runerror` |
| `jin build` が既存ファイルを黙って上書きしない / `<out>` の外へ書かない / リンクを辿らない | `jin_adk/build.py`: `dir_fd` 相対の `mkdir` / `open`、`O_CREAT \| O_EXCL`（`--force` は既存を `O_TRUNC` **なし**で開き、3 つとも開けたあとに `os.ftruncate`。open 時に切り詰めると 3 つ目で拒まれたとき前 2 つが 0 バイトで残る・Phase 1 V-1 と同型）、`O_NOFOLLOW`、`root_name` の再検査、拒否時に**今作ったものだけ**片付け（既存は無傷） **→ 修正ラウンド 2（F-S-P2-104）で `ftruncate` をやめた（次の行）** | `test_build.py` 18 件（`root_name` の `../escape` 7 種 / symlink 2 種 / 部分失敗） | `BUILD-*` 8 件（うち 2 件は二層防御の「片方だけ消しても緑」を明示） |
| **修正ラウンド 2**: `--force` の書き込み失敗（`ftruncate` 後の `os.write` が ENOSPC）で既存 `agent.py` が 0 バイトになる（F-S-P2-104） | `build.py`: `--force` でも既存ファイルを**開かない**。同じディレクトリに `.<name>.jin-tmp` を `O_EXCL \| O_NOFOLLOW` で作って全部書き、3 つとも書けたあとに `os.replace(src_dir_fd=, dst_dir_fd=)` で差し替える（`_move_into_place`）。失敗時は一時ファイルと今作ったものだけ片付ける。既存がリンクなら `lstat` で拒む（`os.replace` はリンク自体を置き換えるので、リンク先は元々守られる）。残骸 `.jin-tmp` があれば拒む。`guard: _move_into_place -> os.replace` / `guard: _open_for_write -> stat.S_ISLNK`（`write_project -> os.ftruncate` は消えた） | `test_build.py::test_force_write_failure_keeps_the_existing_files_intact`（2 回目の `os.write` を ENOSPC・既存 3 ファイルのバイト列不変・残骸なし）/ `::test_force_succeeds_by_replacing_through_a_temporary_file` / `::test_leftover_temporary_file_is_refused_not_overwritten` / `::test_refuses_to_write_through_a_symlinked_file_even_with_force` | `BUILD-replace-early`（ファイルごとに即差し替え）/ `BUILD-truncate-in-place`（旧方式に戻す）/ `BUILD-follow-symlink`（`lstat` 判定を消す） |
| **修正ラウンド 2**: テンプレートが使う組み込み名（`str` / `isinstance` / `ValueError` / `json` …）を circle 名にすると実行時 `TypeError`（F-S-P2-103） | `codegen.RESERVED_NAMES` に `isinstance` / `str` / `bool` / `int` / `float` / `ValueError` / `object` を追加。列挙の漏れは生成物の AST から機械で検出 | `test_codegen.py::test_reserved_names_cover_every_free_name_the_template_uses`（`_state_matches` / `StateCheckAgent` が外側に解決する名前 ⊆ `RESERVED_NAMES`・非空虚）/ `::test_reserved_generated_name_is_rejected[str/isinstance/ValueError/json]` | `FAIL-skip-validate`（既存） |
| `--trace` の出力先 | `jin_cli/main.py` `_open_trace`: `O_NOFOLLOW` / **0600** / `O_TRUNC` 無しで開き、`_LazyTruncateSink._truncate` が最初の行の直前に `os.ftruncate`（`generate()` が通ってから開く・`BuildError` / `RunError` で前回のトレースを 0 バイトにしない・F-S-P2-006 / 008） | `test_build_run.py::test_run_does_not_follow_a_symlinked_trace_target` / `::test_failed_run_does_not_empty_an_existing_trace` / `::test_successful_run_replaces_the_previous_trace` / `::test_trace_file_is_created_owner_only` | `CLI-trace-follow-symlink` / `CLI-trace-truncate-on-open` / `CLI-trace-world-readable` |
| `.jin` の**ファイル名**（`source_name`）が生成コードへ流れる（F-S-P2-001） | `codegen._header` が `py_literal(source_name)` を通す（改行入りの名前がコメントを文にしない）。`_EXTRA_ESCAPES` に孤立サロゲートも加えた（F-S-P2-005） | `test_codegen.py::test_source_name_cannot_inject_statements`（AST body の種類を固定）/ `::test_py_literal_roundtrips`（サロゲート・U+2028） | `ESC-header-raw-source-name` / `ESC-surrogate-passthrough` |
| ファイル名の入口検査（F-S-P2-001 / 005 / 016） | `jin_cli/main.py` `_require_jin_file`: `_has_unsafe_chars(file.name)`（制御文字 / U+2028 / U+2029 / 孤立サロゲート）なら exit 2。表示は `_safe`（同じ集合を置換） | `test_build_run.py::test_unsafe_file_names_are_rejected_at_the_entry` | `CLI-filename-unchecked` / `CLI-safe-narrow` |
| 識別子の NFKC（F-S-P2-002） | `codegen._check_identifier` / `build._check_root_name`: `unicodedata.normalize("NFKC", name) != name` を拒む | `test_codegen.py::test_non_nfkc_circle_name_is_rejected` / `::test_generated_assignments_bind_each_name_exactly_once` / `test_build.py::test_root_name_is_validated_again_before_touching_the_filesystem[ｒｏｏｔ＿ａｇｅｎｔ]` | `FAIL-no-nfkc` / `BUILD-root-not-nfkc` |
| encode を open より前に（F-S-P2-005）/ `WriteRefused` 以外でも片付ける（F-C-P2-020）/ `OSError` を包む（F-S-P2-004）/ `<out>` のリンク（F-S-P2-007） | `build.write_project`: `text.encode("utf-8")` → open → `ftruncate` → `os.write` の順。片付けは `except BaseException`。`_open_out_dir` が `O_NOFOLLOW` と `WriteRefused` | `test_build.py::test_unencodable_content_is_refused_before_any_file_is_touched` / `::test_write_failure_after_open_cleans_up_only_what_it_created` / `::test_out_that_is_a_regular_file_is_refused_without_a_traceback` / `::test_out_itself_is_not_followed_when_it_is_a_symlink` / `::test_over_long_root_name_is_refused_not_a_traceback` | `BUILD-encode-late` / `BUILD-cleanup-only-on-refusal` / `BUILD-oserror-traceback` / `BUILD-follow-out-symlink` |
| `jin run` が cwd を `sys.path` に足す（§2.19） | `run` の `sys.path.append(cwd)`（末尾・DP-IMPL-JIN-P2-SYSPATH-01。記法は `hazard:`・F-S-P2-010）。未インストールの遅延 import 名は末尾でも cwd から解決される残存あり **→ 修正ラウンド 2 で差し替え（次の行）** | `::test_run_adds_cwd_to_sys_path` / `tests/contract/test_cli_contract.py::test_cwd_cannot_shadow_an_installed_package_in_a_real_process` | `CLI-no-cwd` / `CLI-cwd-first` |
| **修正ラウンド 2**: cwd は生成モジュールの import の間だけ（§2.19 の再々判断・F-S-P2-101） | `jin_adk/runtime.py` `_sys_path_window`: `extra_sys_path` を import の前に append・`finally` で remove（`hazard: _sys_path_window -> sys.path.append` / `guard: _sys_path_window -> sys.path.remove`）。CLI は `extra_sys_path=[os.getcwd()]` を渡すだけ。Runner 実行中は cwd が無い | `::test_run_adds_cwd_to_sys_path`（import 中は解決でき、実行後は含まれない）/ `test_runtime.py::test_extra_sys_path_is_present_only_during_the_import` / `tests/contract/test_cli_contract.py::test_cwd_cannot_supply_an_uninstalled_optional_dependency_during_the_run`（`anthropic/`・別プロセス） | `CLI-no-cwd` / `RUN-cwd-stays-after-import` / `RUN-cwd-first` |
| `--model` は `fake` 以外を拒む | `run` 冒頭 | `::test_run_rejects_other_model_values` | `CLI-accept-any-model` |

`importlib` を使う実装は `jin_cli/resolver.py` と `jin_adk/runtime.py` の 2 つだけ
（`test_the_only_module_importing_importlib_is_the_cli_resolver` が厳密一致）。`jin_core` には無い。
