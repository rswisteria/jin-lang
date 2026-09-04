# 決定整合性チェック（decision-conformance-check）

実行日時: 2026-09-04T07:25+00:00 / 対象: `delivery/20260904-1445-jin/{requirements.json, design.yaml, implementation-plan.json}`
実装ラウンド: **1 / 5（Jin Phase 0 + Phase 1）**

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
| DP-COMMON-14 | トレース JSONL は要件書 §3.4 のスキーマに従う成果物であり、ログとして扱わない | scope | 構造化 | **out_of_scope** | トレースは Phase 2 |
| DP-COMMON-14 | ログレベル・フォーマット・ローテーションの方針は本判断では確定しない。実装 Phase 4 で決定し根拠を残す | condition | 構造化 | **out_of_scope** | Phase 4 で確定する。本ラウンドでは決めていない（勝手に先取りしていないことが遵守） |
| DP-COMMON-07 | last-good モデルの保持は jin-lsp のドキュメント管理層 1 箇所に閉じ込める | scope | 構造化 | **reflected（先取りしない形で）** | `jin_core` にキャッシュ層を一切置いていない。`check_text` は毎回フル再計算する純関数（`check.py:164-197` の `check_text`）。保持は Phase 4 の jin-lsp が持つ |
| DP-COMMON-07 | `jin_core` / `jin_render` はキャッシュの存在を知らない純関数のままとし、内部に状態を持たない | scope | 構造化 | **reflected（修正ラウンド 1 で成立させた）** | 修正ラウンド 1 より前は `resolve=True` のとき `jin_core.semantic._import_ref` が `importlib.import_module` を呼び、`sys.modules` というプロセス全体の可変状態を書き換えていた（同じ入力で 2 回目が別の結果になりうる = 純関数ではない）。security review S14 の指摘どおり、当時の「reflected」は**実態と乖離していた**。現在は import 実装を `jin_cli.resolver.ImportResolver` へ移し、`jin_core` は `RefResolver` プロトコルを受け取るだけになった（`jin_core/resolver.py`）。`jin_core` にモジュールレベルの可変状態は無く、モジュール定数は `parser._PARSER`（Lark の文法オブジェクト・不変）と各種の定数辞書のみ |
| DP-COMMON-07 | SVG はキャッシュしない | scope | 構造化 | **out_of_scope** | jin-render は Phase 3 |
| DP-COMMON-15 | `.env.example` のキー名は実装 Stage 1 の実測に委ねる / 推測で書かない / 実測できなければコメントのみ | condition, prohibition | 構造化 | **out_of_scope** | `.env.example` を出すのは `jin build`（Phase 2 / FR-ADK-001）。本ラウンドで `.env.example` は生成していない（実測: `find . -path ./.venv -prune -o -name '.env*' -print` → 0 件）。**キー名を推測で書いていない**という禁止事項は遵守 |
| DP-COMMON-16 / 17 / 18 / 19 / 20 | エディタ側の各制約（選択の 3 つ組保持 / JSON-RPC ラッパ / SPA 構成 / 5 状態 / テスト 2 層） | 各種 | 構造化 | **out_of_scope** | `apps/editor` は Phase 5–6 |
| DP-JIN-CODEGEN-RUNTIME-01 | FakeLlm を生成物に埋め込まない / 生成物は jin を import しない / StateCheckAgent 重複の扱いは Phase 2 で決定 / 再生成が必要な旨を明示 | 各種 | 構造化 | **out_of_scope** | jin-adk は Phase 2 |
| DP-JIN-TRACE-POINTER-01 | 対応表を生成物に埋め込まない / 引けないイベントは pointer を null にする / 単体 adk run では pointer が付かない旨を明示 | 各種 | 構造化 | **out_of_scope** | Phase 2 |
| DP-JIN-SVG-DETERMINISM-01 | 丸め桁数は Phase 3 で決定し根拠を `docs/spec/layout.md` に残す / 推測値を固定しない / 決定性テストは別プロセス 2 回 / 星形 {n/k} の k を Phase 0 の layout.md で一意に明文化 / 座標は丸め関数 1 本を通す | 各種 | 構造化 | **一部 reflected・残りは out_of_scope** | **Phase 0 の担当分は本ラウンドで実施**: 星形 {n/k} の k の決め方を `docs/spec/layout.md` §2.1 で `k = max{ j : 1 <= j < n/2 かつ gcd(n, j) == 1 }` として一意に明文化した。**丸め桁数は書いていない**（Phase 3 で決める旨を layout.md §4 に明記・推測値を固定しない禁止事項を遵守）。丸め関数と決定性テストは Phase 3 |
| DP-JIN-EDITOR-PROTOCOL-01 | `jin/open` / `jin/save` は仮称であり Phase 0 の `docs/spec/ops.md` 執筆時に人間承認を得て確定する / ws モードのエディタだけが使う / ファイル I/O 失敗はプロトコルエラー / 逆オペレーションの扱いは Phase 4 | 各種 | 構造化 | **reflected（Phase 0 担当分）** | `docs/spec/ops.md` §5 に「リクエスト名は仮称であり人間承認を要するため §2 の 19 件の表に含めていない」と明記。19 件の表を勝手に 21 件にしていない |
| DP-JIN-PHASE-SCOPE-01（requirements.json） | 本ランのスコープは Phase 0〜6 | — | 構造化 | **reflected** | 本ラウンドは Phase 0 + 1。Phase 2 以降は後続ラウンドの implementer が担当（親の指示どおり着手していない） |
| DP-JIN-EDITOR-UX-01 / DP-JIN-DISTRIBUTION-01（requirements.json） | エディタ最小 UI / 配布元 | — | 構造化 | **out_of_scope** | Phase 5 / 配布は本ラウンドの対象外 |

**判定サマリ**: reflected 14 / 部分 reflected 1 / not_reflected 0 / unknown 0 / out_of_scope 13
→ **PASS**（`not_reflected` と `unknown` はゼロ。「部分 reflected」1 件は apps/editor 未存在が理由で、
未対応であることをテストで可視化してある）

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

### 2.13 `.env.example` のキー名（DP-COMMON-15 / 実装ラウンド 2・Phase 2）

DP-COMMON-15 の決定内容は「**実装 Stage 1 の実測に委ね、実測できなければコメントのみで生成する**」
（人間承認済み）。**実測できた**ので、コメントのみではなく次の 4 キーを出す。

| キー | 根拠（google-adk 2.8.0 のソースを実測） |
|---|---|
| `GOOGLE_GENAI_USE_ENTERPRISE` | `google/adk/cli/cli_create.py` L127/L129 — `adk create` が `.env` の 1 行目に書く（1=Vertex AI / 0=Gemini API）。`google/adk/agents/_managed_agent.py` L189-190 が「`GOOGLE_GENAI_USE_ENTERPRISE` または**旧称の** `GOOGLE_GENAI_USE_VERTEXAI`」と書いており、現行名はこちら |
| `GOOGLE_API_KEY` | `cli_create.py` L131 が書き、`google/genai/_api_client.py` L136 が実際に読む（`GEMINI_API_KEY` より優先。L130 の docstring に明記） |
| `GOOGLE_CLOUD_PROJECT` | `cli_create.py` L132 / `_api_client.py` L714 |
| `GOOGLE_CLOUD_LOCATION` | `cli_create.py` L133 / `_api_client.py` L715 |

**推測で足したキーは無い。** `GEMINI_API_KEY` は `GOOGLE_API_KEY` の別名にすぎず（同 L137-140 が
「両方あれば `GOOGLE_API_KEY` を使う」と警告する）、雛形に 2 通りの書き方を並べると
どちらが効くのか分からなくなるので載せない。

置き場所も実測に合わせた。`google/adk/cli/utils/envs.py` の `_walk_to_root_until_found` は
`<out>/<root_name>` から**上へ辿って**最初に見つけた `.env` を読むので、要件書 §3.1 のとおり
`<out>/.env.example` に置けば `<out>/.env` にコピーするだけで効く。

値は入れない（`GOOGLE_GENAI_USE_ENTERPRISE=0` の既定だけ置く）。雛形は秘密を書く場所ではない。

検査: `packages/jin-adk/tests/test_project.py`

- `test_env_example_has_exactly_the_measured_keys` — キーと**その並び**を固定
- `test_every_env_key_is_actually_read_by_the_installed_adk` — 4 キーが実物の
  google-adk / google-genai のソースに**実在する**ことを毎回確かめる（捏造の検出）
- `test_env_example_has_no_values` — 雛形に値を書かない

### 2.14 Python を 3.13 に固定（実装ラウンド 2・Phase 2）

`.python-version` を `3.14` から **`3.13`** に下げた。**google-adk 2.8.0 が Python 3.14 で import できない**。

実測（2026-09-04・同一マシン・隔離 venv 2 つ）:

| Python | `from google.adk.agents import LlmAgent` |
|---|---|
| 3.14.0rc2 | **失敗**（`google/genai/types.py` の `PartMediaResolution` 定義中に `pydantic/_internal/_typing_extra.py` `eval_type_backport` が `AssertionError`。原因は `typing._eval_type() got an unexpected keyword argument 'prefer_fwd_module'`） |
| 3.13.12 | 成功 |

- pydantic は 2026-09-04 時点で **2.13.5 が最新**（PyPI 実測）。3.14 対応の新しい版は無い
- 3.14 は当時 `.python-version` の `3.14` から **3.14.0rc2**（リリース候補）が選ばれていた。
  安定版に固定するという W-06 の趣旨からも 3.13 のほうが妥当
- design.yaml Phase 2 の machine 条件「google-adk 2.8.0 に対する生成モジュールの import テストが
  通る（NFR-VER-001）」は 3.14 では**原理的に満たせない**

`requires-python = ">=3.12"` は変えていない（3.13 はその範囲内）。上げ直すときは、上の 1 行
（`from google.adk.agents import LlmAgent`）を実際に通してから確定すること。
`packages/jin-adk/tests/test_adk_surface.py::test_the_installed_adk_is_the_pinned_version` が
入っている google-adk の版を固定しているので、版と Python の組を変えるときは同時に見直す。

### 2.15 `builtin` に許す名前（Phase 2 で新たに必要になった判断）

要件書 §2.2 は `builtin` の例として `google_search` しか挙げておらず、許容集合を定めていない。
`google.adk.tools` が**インスタンスとして**公開しているツール（= `tools=[...]` にそのまま置けるもの）を
実測して、その 9 個を許容集合とした:
`enterprise_web_search` / `get_user_choice` / `google_maps_grounding` / `google_search` /
`load_artifacts` / `load_memory` / `preload_memory` / `request_input` / `url_context`。

**列挙は `jin_adk.codegen.BUILTIN_TOOLS` の 1 箇所**にあり、
`packages/jin-adk/tests/test_adk_surface.py::test_builtin_tools_constant_matches_what_adk_actually_exports`
が実物の `google.adk.tools` と突き合わせる。ADK が増減したら赤くなるので、記憶で足したり消したりできない。

ここに無い `builtin` は**コンパイル時エラー**にする（NFR-FAIL-001「黙って落とさない」）。

### 2.16 生成コードの変数名が衝突したときの別名（Phase 2 で新たに必要になった判断）

要件書 §3.2 の生成例は `from research.tools import web_search, fetch_page, publish` と
**素の名前**で import する。しかし `ref` の callable 名は別モジュール間で重複しうるし、
circle 名や ADK の import 名（`FunctionTool` など）ともぶつかりうる。

- ぶつからない限り §3.2 のとおり素の名前を使う（examples の生成物は要件書の見た目のまま）
- ぶつかったときだけ `beta.tools:run` → `beta_tools__run` のようにモジュール修飾の別名を付ける
- **黙って 1 つに潰さない**（潰すと別の関数が呼ばれる）

root 以外の circle が `root_agent` という名前だった場合と、`flow.exit` の判定エージェント名
（`<circle 名>__exit`）が既存の circle 名とぶつかった場合は、別名にせず**コンパイル時エラー**にする。
生成コードの中の名前と `.jin` の名前が食い違うと、生成物を読んだ人が混乱するため。

## 3. `DP-CONFORMANCE-FAIL` の起票

`not_reflected` / `unknown` は **0 件**のため起票なし。
「部分 reflected」1 件（DP-COMMON-11 の apps/editor 側）は未着手 Phase の話であり制約違反ではないので、
`docs/pending-decisions.md` への起票ではなくテストによる可視化（`test_editor_contract_is_not_yet_enforced`）で扱った。

## 4. Stage 5 security 軸 reviewer への引き渡し

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
