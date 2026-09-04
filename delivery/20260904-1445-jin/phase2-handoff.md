# Jin Phase 2（jin-adk）への申し送り

作成: 親（team-lead）／ 2026-09-04
根拠: 実装ラウンド 1 の Stage 5 レビュー（4 観点・86 件）と 3 度の修正ラウンドで実測された事項。
**Phase 2 の implementer 起動プロンプトにこのファイルのパスを必ず渡すこと。**

## 0. Phase 2 のスコープ（design.yaml `implementation_phases.items[2]`）

成果物: `packages/jin-adk` と `packages/jin-cli`（`build` / `run` を追加）
完了条件（machine）は design.yaml の `verification.machine` を **verbatim** で満たす。
`human_only`（実 `adk run` での疎通）は **`not_run`** として PR レビューへ送る。実施済みと書かない。

## 1. Phase 2 で**必ず赤くなる**テストと、その正しい直し方

### 1.1 `test_the_only_module_importing_importlib_is_the_cli_resolver`

`tests/contract/test_packaging_contract.py`。`assert offenders == [...]` の**厳密一致**。

要件書 §3.4 が `jin run` を「生成コードを一時ディレクトリに書き出して import」と定めているため、
`jin_adk` は importlib を使う。**赤くなるのが正常。**

- **正しい修正**: `expected` に `packages/jin-adk/src/jin_adk/<module>.py` を**足して通す**
- **やってはいけない修正**: `jin_adk` の import を `jin_cli` 経由に回す（依存方向の逆転）／
  テストごと削除する／アサーションを `>=` に緩める
- **`jin_lsp` と `jin_core` は Phase 4 以降も足してはならない**（S1 の構造的担保が崩れる）

この意図は親が docstring に明記済み（conventions N-1 の対処）。

### 1.2 `test_later_packages_do_not_exist_yet[jin_adk]`

`packages/jin-adk` が現れた瞬間に赤くなる意図的なトリップワイヤ。
**このテストのメッセージに従い、下記 §2 の 5 箇所を同時に直すこと。**

## 2. パッケージ追加時に同時に直す 5 箇所（wiring W-03 / conventions A-2）

`pyproject.toml` にパッケージ一覧が複数箇所ある。**`testpaths` は `["tests", "packages"]` 相当で
追随不要になっているが、他は列挙が必要**。新設の `tests/contract/test_packaging_contract.py` が
ディスク上の `packages/*/pyproject.toml` を列挙して網羅を機械で確認するので、漏れると名指しで赤くなる。

1. `[project] dependencies`
2. `[tool.uv.sources]`
3. `[tool.importlinter] root_packages` — 漏れると **import-linter の解析対象外**になり
   `Analyzed N files` が増えない（＝契約が黙って効かなくなる）
4. `[tool.importlinter.contracts]` の `layers` — **§3 を参照**
5. resolver 隔離契約の `source_modules` — `test_resolver_isolation_contract_covers_every_package_but_the_cli` が強制

`CLAUDE.md` にもチェックリストがある。

## 3. **layers は素朴な直列に書かないこと**（wiring W-05・実測済み）

design.yaml `architecture.dependency_direction` のルール 3・4 は
**`jin-adk` と `jin-render` を互いに独立な兄弟**と定義している。

wiring reviewer が隔離ツリーで実測した結果:

| 書き方 | `lint-imports` の挙動 |
|---|---|
| `["jin_cli", "jin_lsp", "jin_adk \| jin_render", "jin_core"]` | `jin_adk→jin_render` と `jin_render→jin_adk` の**両方**を BROKEN（**正しい**） |
| `["jin_cli", "jin_adk", "jin_render", "jin_core"]`（素朴な直列） | `jin_render→jin_adk` **だけ**を BROKEN。`jin_adk→jin_render` を**静かに許す** |

**`test_layers_contract_keeps_sibling_packages_in_one_element` が素朴な直列を名指しで拒む**
（design.yaml のルールから独立ペアを読む実装。修正ラウンド 2 で追加・wiring が実パッケージで end-to-end 検証済み）。

あわせて **design.yaml のルール「jin-render は google-adk に依存しない」** を機械で担保するには、
forbidden 契約の `source_modules`（現在 `["jin_core"]`）を Phase 3 で広げる必要がある。

## 4. ADK の実 API は**記憶で書かない**

正本: `delivery/20260904-1445-jin/adk-api-probe.md`（google-adk **2.8.0** を隔離 venv に実インストールして
introspection した結果）。要件書 §3.2 の生成コードはそのまま成立するが、次の差異がある。

- **`flow.max` → `LoopAgent(max_iterations=...)`**（`max` ではない）
- `google.adk.tools.google_search` は `GoogleSearchTool` の**インスタンス**（クラスではない）
- `Runner` は**全キーワード引数**で `session_service` が必須
- トレース JSONL（§3.4 の `seq`/`ts`/`agent`/`kind`/`name`/`pointer`/`input`/`output`）は
  **ADK Event そのものではなく Jin 側の派生スキーマ**。`agent` は `Event.author`、`ts` は `Event.timestamp` から取る
- `EventActions.escalate` は実在するので §3.3 の `StateCheckAgent` 設計は成立する
- `BaseAgent._run_async_impl(ctx) -> AsyncGenerator[Event, None]` / `BaseLlm.generate_content_async(llm_request, stream=False)`

確定済みの実装方式（覆さない）: **ADR-008 / DP-JIN-CODEGEN-RUNTIME-01** = `StateCheckAgent` のクラス本体を
`agent.py` に毎回埋め込む（生成物が自己完結）+ `FakeLlm` は `jin_adk` 側。
**ADR-009 / DP-JIN-TRACE-POINTER-01** = コード生成時に ADK 識別子 → JSON Pointer の対応表を作り実行時に引く。

## 5. 未確定のまま残している値（Phase 2 で決めるなら根拠を残す）

- **`.env.example` のキー名**（`DP-COMMON-15` / ADR 無し）: 「実装 Stage 1 の実測に委ね、実測できなければ
  コメントのみで生成する」が決定内容。**推測で埋めない。** google-adk 2.8.0 から実測すること。
- 値を確定したら **`decision-conformance.md` に根拠を書く**（ラウンド 1 で JIN012/JIN013 の採番と
  行・列の基点をそうしたのと同じ手続き）。

## 6. 判断ポイント（実装者が決めてはならない）

- **`DP-JIN-RESOLVE-ISOLATION-01`**（未決）: `--resolve` が同一プロセスで import するため、
  **1 ファイル目の `ref` が `jin_core.semantic.analyze` を差し替えると 2 ファイル目の本物の JIN060 が消え、
  「2 ファイル / error 0 件」exit 0 になる**（親が実測）。判断期限は **Phase 4 着手前**。
  Phase 2 では実装しないこと。
- **`DP-REVIEW-JIN-008`**（fix-later）: `check_text` が最悪 8.4 秒。**Phase 4 の LSP は打鍵ごとに呼ぶ**ので
  要件書 §6.4「1000 行以下で診断 1 秒以内」を Phase 4 で実測すること。Phase 2 では対象外。

## 7. 運用（親から reviewer / implementer への指示に含める）

- **reviewer には隔離コピーでの変異検証を明示指示する。** 本ランでは implementer と reviewer が
  同一ワーキングツリーを共有しており、編集の着地前にテストが走って「一時的な赤」が 2 度発生した
  （O-4 と 19:38 の件）。どちらも欠陥ではなかった。
- **`DP-REVIEW-JIN-005`**: 契約テストが `delivery/20260904-1445-jin/design.yaml` を直接指している。
  次のランで別タイムスタンプのランディレクトリが切られると壊れる。**直すときはパスのハードコードし直しではなく、
  ランディレクトリを解決する形に変えること**（`delivery/` を走査して辞書順最新の `*-jin` を選ぶ）。
- 検証資材（wiring reviewer が保持）: `tmp/uv-aarch64-apple-darwin/uv`（CI がピンした 0.12.9 と同一）、
  各ラウンドの `uv.lock` スナップショット。

## 8. この工程で得た、Phase 2 でも守るべき原則

1. **テストが緑であることは品質の証拠にならない。** ラウンド 1 は 225 件緑の状態で 86 件の finding が出た。
2. **修正の完了は同一観点の reviewer による再レビューで確定する。** 実装者の「直しました」は根拠にしない。
   実際、修正が新たな欠陥を 7 件持ち込んだ。
3. **「検査が存在する」と「検査が落ちる」は別。** 実装を壊してテストが赤くなることを確認する。
   本ランで偽緑だった検査: `rename` の参照追随 / 依存方向の兄弟制約 / CI の lock 検証 /
   symlink の事前ガード / import-linter の自己テスト。
4. **仕様側とコード側は同じ欠陥。** 片方だけ直すと矛盾が残る（S-1↔A-1/A-2 ほか 4 組）。
5. **コメントの安全宣言は機械で固定できる。** `guard: <関数名> -> <トークン>` 記法とその検査テストが
   `packages/jin-cli/` にある。新しい防御を入れたら同じ形で主張を固定すること。
