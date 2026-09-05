# Stage 5 review — conventions（Phase 2 / jin-adk）

- 対象: ブランチ `feat/jin-phase2-adk` の未コミット作業ツリー（`git status --short` の全変更 + untracked）
- 方法: 実ツリーは変更せず、`scratchpad/review-conventions/` の隔離コピーで実行・変異
- レビュア: review-conventions-p2（general-purpose）／ 2026-09-05
- 結論: **DONE_WITH_CONCERNS**（finding 29 件。confidence ≥ 80 が 9 件、うち規約違反として修正を勧めるもの 7 件）

## 0. 実測した事実（finding の前提）

| 検査 | 結果 | 再現 |
|---|---|---|
| 全テスト | **696 tests / failures 0 / errors 0**（junit）、2 snapshots passed | `python -m pytest -p no:cacheprovider --junitxml=junit.xml` |
| ruff | `All checks passed!` / `58 files already formatted` | `ruff check . && ruff format --check .` |
| import-linter | `Contracts: 3 kept, 0 broken` | `lint-imports` |
| 要件書の写し | `jin-requirements.md` と `docs/superpowers/specs/2026-09-04-jin-overview.md` は `diff -q` で同一。`tests/spec/test_spec_consistency.py` の第 0 テストも通る | `diff -q` |
| 機械可読ブロック | `trace-kinds` / `build-errors`（adk-mapping.md）、`flow-exit-equality`（model.md）の 3 ブロックが `test_spec_consistency.py` の Phase 2 テストと突合されている | pytest |
| 診断コード | `docs/spec/diagnostics.md` は無変更。`jin_adk` に新規 `JINxxx` は無い（コメントで JIN012 / JIN060 を参照するのみ） | `grep -rn "JIN0" packages/jin-adk/src` |
| パッケージ追加チェックリスト 6 項目 | `[project].dependencies` / `[tool.uv.sources]` / `root_packages` / `layers` / forbidden `source_modules` / `packages/jin-adk/tests/__init__.py` すべて済み。`test_packaging_contract.py` 通過 | pytest |
| CLAUDE.md / README の開発コマンド | `jin build examples/researcher/researcher.jin --out …` EXIT 0（3 ファイル）／ `PYTHONPATH=tests/fixtures/stubs jin run examples/pipeline/pipeline.jin "go" --model fake --trace …` EXIT 0（11 行・全行 pointer 非 null）／ `uv run python delivery/…/phase2-mutations/mutate_p2.py` **31/31 mutations caught**（隔離コピーで `uv run`・EXIT 0・対象ファイルは復元済み） | 本文 §0 のコマンド |
| build-errors fixture | `jin check tests/fixtures/build-errors` → 14 ファイル / error 0 / warning 0。`jin fmt --check` EXIT 0（正準形） | 同 |
| `guard:` 検査が jin_adk 側にも効くか | 変異 4 件すべて赤（下表） | 下表 |

`guard:` 検査の変異（隔離コピー・`pytest packages/jin-cli/tests/test_cli.py -k guard_claims`）:

| 変異 | 期待 | 実測 |
|---|---|---|
| `build.py` の `guard: _open_for_write -> os.O_EXCL` を `-> os` に | GuardTokenTooLoose | `GuardTokenTooLoose: guard: のトークン 'os' が裸の名前` |
| 同じ行を `-> os.O_APPEND`（嘘の名指し） | 赤 | `AssertionError: _open_for_write に os.O_APPEND が無いのに guard: がそこを名指ししている` |
| `main.py` の `sys.path.insert(0, cwd)` を `pass` に（主張は残す） | 赤 | `FAILED …test_guard_claims_point_at_real_guards[jin_cli.main]` |
| `runtime.py` の `tempfile.mkdtemp` を `tempfile.mktemp` に（主張は残す） | 赤 | `FAILED …test_guard_claims_point_at_real_guards[jin_adk.runtime]` |

注: 途中 1 回だけ `test_run_adds_cwd_to_sys_path` が落ちたが、隔離コピー内で `mutate_p2.py`（`CLI-no-cwd` 変異が `main.py` を書き換える）を並走させていたためで、直列に再実行した結果が上の 696 / 0 である。

## 1. Findings

書式: `ID | confidence | 場所 | 規約の出典 | 内容 | 修正案`

### 1.1 confidence ≥ 80

**F-V-P2-001** | 90 | `tests/contract/test_packaging_contract.py:178-212`（`test_the_only_module_importing_importlib_is_the_cli_resolver`） | DP-REVIEW-JIN-007（テスト名と守備範囲の一致）
テスト名は「importlib を使う唯一のモジュールは CLI の resolver」と言うが、期待値は `runtime.py` と `resolver.py` の 2 件になった。docstring は更新済みで名前だけが嘘になっている。
修正案: `test_importlib_is_confined_to_the_cli_resolver_and_jin_run` などへ改名。

**F-V-P2-002** | 85 | `packages/jin-cli/tests/test_cli.py:39`（`test_help_lists_only_phase1_commands`） | DP-REVIEW-JIN-007
`--help` に build / run が出るようになったので「only phase1」は偽。中身は 4 コマンドの存在確認だけで「only」も検査していない。
修正案: `test_help_lists_phase1_commands` へ改名（Phase 2 分は `test_build_run.py::test_help_lists_phase2_commands` が持つ）。

**F-V-P2-003** | 85 | `CLAUDE.md:24`（依存図）/ `CLAUDE.md:142-143` / `pyproject.toml` forbidden 契約「ref の解決実装（任意コード実行）は jin_cli に閉じる」 | CLAUDE.md「パッケージ境界」「`--resolve` と `jin run` の危険性」/ design.yaml `dependency_direction.rules` 5 行目
既存の一文「Phase 4 の `jin-lsp` は `jin_core` にしか依存しないので、ws で公開されるコードパスからこの実装へ到達できない」は、依存図（`jin-adk ← jin-lsp` を許す）と design.yaml rule 5（jin-lsp は jin-core / jin-adk / jin-render に依存する）に反する。Phase 2 で任意コード実行経路 `jin_adk.runtime.run_model` が jin_adk に入ったため、この矛盾が今ラウンドで実害になった。forbidden 契約の `forbidden_modules` は `jin_cli.resolver` だけで、契約名「任意コード実行は jin_cli に閉じる」も現状（`jin_adk.runtime` にもある）を表していない。Phase 2 追記部分（CLAUDE.md:129-135）は「実装は runtime.py だけにある（jin_core には置かない）」と正しく書いているので、142-143 行の隔離主張との整合を取っていない。
修正案: (a) CLAUDE.md 142-143 を「`jin_core` / `jin_adk.runtime` を ws 公開パスから import しない（Phase 4 の契約で機械化する）」に直す。(b) forbidden 契約を「任意コード実行の実装は `jin_cli.resolver` と `jin_adk.runtime` に閉じる」に改名し、Phase 4 で `jin_lsp` → `jin_adk.runtime` を forbidden に加える旨を `phase2-handoff.md` / Issue #5 に申し送る。

**F-V-P2-004** | 80 | `packages/jin-cli/tests/test_cli.py:761-792`（`guarded_modules` / `test_guard_claims_point_at_real_guards`） | ADR-003（`packages/<pkg>/tests/` はそのパッケージ単体、横断は `tests/contract/`）/ CLAUDE.md「テスト配置」
jin_adk の 3 モジュールに対する `guard:` 検査が **jin-cli のパッケージテスト**に置かれている。検査自体は効いている（§0 の変異 4 件）が、配置が ADR-003 に反し、`uv run pytest packages/jin-adk/tests` だけを回すと jin_adk の安全宣言が検査されない。
修正案: `GUARD_CLAIM` / `_guard_satisfied` / `guarded_modules` を `tests/contract/test_guard_claims.py` へ移し、`packages/*/src` を走査して `guard:` を含む全モジュールを自動で対象にする（列挙をやめると W-03 型の漏れも防げる）。

**F-V-P2-006** | 85 | `delivery/20260904-1445-jin/implementation-plan.json` | 実装台帳「implementation-plan.json は全回で 1 ファイル共有・extend」/ 親の指示（申告した 5 キー以外は書き換えない）
`git diff` で確認した結果:
- 申告外の**書き換え**: `verification_status.review_status_note`（旧「Phase 0+1 のスコープ…Phase 2〜6 は未着手」→ 新「Phase 0〜2 のスコープ…」）。1 キー。
- 申告済みだが**記録が消えた**もの: `round.jin_phases` `[0,1]` → `[2]`、`milestones` の「Phase 2 以降: 別ラウンドの implementer が担当（未着手）」行の削除、`scope_labels` から `pipeline-verified` の除去、`layers.pipeline_e2e` `passed` → `not_run`。main の Phase 0+1 が pipeline_e2e を通した事実は `evidence[]` の文字列にしか残らない。
- 追記のみ（extend 準拠）: `$comment` / `test_plan` / `note` / `dependencies` / `decision_record` / `skill_plan` / `tasks` / `evidence` / `open_questions` / 末尾改行。
修正案: `review_status_note` を申告に加えるか旧文を残して追記形にする。`scope_labels` は `pipeline-verified(phase0-1)` のように残し、`note` に「Phase 0+1 は main で pipeline passed、Phase 2 は not_run」を書く（今は `note` 末尾に書いてあるが `layers` と `scope_labels` の値からは読めない）。

**F-V-P2-007** | 80 | `delivery/20260904-1445-jin/decision-conformance.md` 冒頭の追記方針と表本体 | 成果物の追記規律（extend）
冒頭に「ラウンド 1 の判定は**そのまま残す**」と書きながら、ラウンド 1 の `out_of_scope` 4 行（DP-COMMON-14 / DP-COMMON-15 / DP-JIN-CODEGEN-RUNTIME-01 / DP-JIN-TRACE-POINTER-01）は削除され、`**P2**` 行に置き換わっている（`git diff` の `-` 行）。判定サマリはラウンド 1 の数字を残しているので、表と方針文が食い違う。
修正案: 4 行を復元し、その直下に P2 行を並べる（または方針文を「out_of_scope 行は P2 行に分解して置き換えた」に直す）。

**F-V-P2-010** | 80 | `docs/spec/adk-mapping.md` §3.1（`fixture は …（各 1 件…）`・`flow_circle_with_*` 行）/ `tests/fixtures/build-errors/` / `packages/jin-adk/src/jin_adk/codegen.py:491-535`（`_validate_flow_circle`） | adk-mapping.md §3.1 自身の「各 1 件」/ CLAUDE.md「`tests/fixtures/build-errors/*.jin` — jin check は通るが jin build が落とす構造」
§3.1 の flow circle 行は `tools` / `instruction` / `delegate` / `out: true` / `before_model 系 guard` / `await` の 6 構造を 1 行に束ね、fixture は 3 つ（tools / out_state / model_guard）。`instruction` / `delegate` / `await` の 3 経路には fixture も単体テストも無い（`grep -n "def test_.*flow" packages/jin-adk/tests/test_codegen.py` → 0 件。隔離コピーでの直接呼び出しでは 3 経路とも `BuildError` になることは確認した）。「各 1 件」の自己宣言と、Phase 1 の「診断コードごとに fixture ちょうど 1 つ」の規律に対して薄い。
修正案: `flow_circle_with_instruction` / `flow_circle_with_delegate` / `flow_circle_with_await` の fixture を足して行を分ける（`test_build_error_table_covers_every_fixture` が自動で拾う）。

**F-V-P2-011** | 80（cross-cutting: correctness と重複） | `packages/jin-adk/src/jin_adk/codegen.py:798`（`tool_imports.add(tool.builtin)`）/ `_plan_imports` / adk-mapping.md §3.1 `reserved_name_collision` 行 | NFR-FAIL-001「黙って落とさない」/ §3.1 の一覧
`builtin` 名は `from google.adk.tools import <名>` として束縛されるが、`ref` と違って `taken`（circle 名・予約名）との衝突検査を通らない。circle 名 `google_search` と builtin `google_search` を同居させると `BuildError` にならず、生成物では `google_search = LlmAgent(...)` が import を上書きし `tools=[google_search]` が agent を指す（隔離コピーで実測。生成物抜粋: `from google.adk.tools import google_search` の直後に `google_search = LlmAgent(` … `tools=[ google_search, ]`）。§3.1 の「生成コードの名前と衝突」行がこのケースを含んでいない。
修正案: `_validate` で builtin 名を `taken` に入れ、circle 名 / ref 束縛名との衝突を `BuildError`（hint: 別名の circle にする）にする。fixture `builtin_name_collision` を足し §3.1 に 1 行追加。

**F-V-P2-014** | 85 | `pyproject.toml [tool.ruff]`（`select` 未指定 = 既定 E4/E7/E9/F）/ `packages/jin-adk/src/jin_adk/codegen.py:211`（`# noqa: PLR0124`）/ `packages/jin-cli/src/jin_cli/resolver.py:43`（`# noqa: BLE001`・Phase 1 由来） | DP-REVIEW-JIN-002（ruff が実質未検査）
Phase 2 でも `select` は既定のまま。新規コードに有効化されていない規則の `noqa` が書かれ、`ruff check --select RUF100 packages` が `Unused noqa directive (non-enabled: PLR0124)` / `(non-enabled: BLE001)` の 2 件を報告する。参考: `ruff check --select ALL --statistics packages/jin-adk/src` は E501 21 件、PLC0415 4 件、C901 1 件などを出す（規則を選ぶ判断材料）。
修正案: DP-REVIEW-JIN-002 を決める（少なくとも `select = ["E","F","I","B","UP","RUF"]` 程度 + `RUF100`）。決めないなら死んだ `noqa` を消す。

### 1.2 confidence 60〜79

**F-V-P2-005** | 75 | `packages/jin-cli/src/jin_cli/main.py:648-650`（`run` 内コメント「上書きはするが、リンクは辿らない」） | CLAUDE.md「安全主張は `guard:` 記法で書く」/ Phase 0+1 の U-1 E-A 型
`--trace` の出力先を `O_NOFOLLOW` で開く主張が散文コメントで、`run` の `guard:` は `sys.path.insert` の 1 件だけ。Phase 1 の fmt は同種の主張を `guard: _write_in_place -> os.O_NOFOLLOW` で固定している。変異 `CLI-trace-follow-symlink` は挙動を見るが、主張と実装の乖離検査は掛かっていない。
修正案: モジュール docstring と `run` docstring に `guard: run -> os.O_NOFOLLOW` を追加。

**F-V-P2-008** | 75 | `delivery/20260904-1445-jin/version-matrix.md` §8.3 #15 | T-002（実測と称するものは実測であること）
「`result.output` は stdout のみ。Phase 2 の CLI テストは `result.output` で stdout を見る」は誤り。隔離コピーで `CliRunner().invoke(app, ["build", <two_out_states>, …])` を実行すると `"hint:" in result.output` = True / `result.stdout` = False / `result.stderr` = True（click 8.5.0 / typer 0.27.2）。`test_build_run.py` の `"hint:" in result.output` / `"--force" in result.output` / `"JIN060" in result.output` は stderr の文言を `output` 経由で読んで通っている。
修正案: #15 を「`result.output` は stdout+stderr の混在。stdout だけは `result.stdout`」に直し、対処欄を実態（stderr 文言も `output` で検査している）に合わせる。

**F-V-P2-009** | 75 | `docs/spec/adk-mapping.md` §2.4 `trace-kinds` の `escalate` 行 / `packages/jin-adk/src/jin_adk/trace.py:182-185` / `tests/spec/test_spec_consistency.py::test_trace_kinds_table_matches_the_implementation` | 仕様と実装の一致（正典は adk-mapping.md）
表は `escalate` の pointer を `/circles/i/flow/exit`、name を「loop circle 名」と定めるが、実装は StateCheckAgent 以外の `actions.escalate`（ツールや guard が立てた場合）を pointer `/circles/i`（`agent_pointer`）、name = author で出す。`trace.py` のモジュール docstring は「（checker のとき）」と限定しており、仕様表の方が実装より狭い。spec テストは kind の集合しか照合しない。
修正案: 表の `escalate` 行を「checker 由来」と「`actions.escalate` 由来（pointer `/circles/i`・name = author）」の 2 行に分け、spec テストで pointer 列の形も照合する。

**F-V-P2-012** | 70 | `README.md:22-29` / `jin-requirements.md:252`（§3.1「そのまま動くこと」） | 要件書 §3.1 / README の主張と実装の一致
README は「`adk run out/Researcher` … でそのまま動く」と書いた 5 行後に「`adk run` で単体実行すると初回ターンで ADK が `KeyError`」と書いており自己矛盾。要件書 §3.1 の「そのまま動くこと」は examples/researcher では満たされていない（HANDOFF Q-JIN-P2-01 として起票済み・非ブロッキング）。
修正案: README を「pipeline は `adk run` で動く。researcher は `{findings}` の初回未設定で落ちる（Q-JIN-P2-01・`jin run` は state seed で回避）」の形にし「そのまま動く」を落とす。要件書側は Q-JIN-P2-01 の結論待ちである旨を `docs/pending-decisions.md` に残す。

**F-V-P2-013** | 70 | `CLAUDE.md:130-132`（「`jin run` は … `sys.path` の先頭に cwd を足す。実装は `packages/jin-adk/src/jin_adk/runtime.py` だけにある」） | CLAUDE.md の記述と実装の一致
`sys.path.insert` があるのは `packages/jin-cli/src/jin_cli/main.py:643-644` で、`runtime.py:79` は「`sys.path` は触らない」と明記している。文の並びから cwd 追加も runtime にあると読める。ライブラリとして `run_model` を呼ぶ側は cwd 解決を得られない、という境界も CLAUDE.md からは読めない。
修正案: 「cwd の追加は CLI（`jin_cli/main.py` の `run`）が行う。`jin_adk.runtime.run_model` は `sys.path` を触らない」と分けて書く。

**F-V-P2-017** | 60 | `packages/jin-adk/src/jin_adk/runtime.py:225`（`RunError("実行に失敗しました（…）")`）/ `packages/jin-cli/src/jin_cli/main.py:654`（「トレースを開けません（strerror）」） | 要件書 §5「メッセージは『何が悪いか + どう直すか』を必ず含める」
`BuildError` / `WriteRefused` / import 失敗の `RunError` は hint を持つが、実行時の `RunError` と `--trace` の open 失敗は「何が悪いか」だけ。
修正案: 実行失敗には「`--trace` で直前のイベントを確認 / ref の関数の例外なら関数側を直す」等、open 失敗には「親ディレクトリの有無・権限・リンクでないこと」を添える。

**F-V-P2-019** | 65 | `packages/jin-adk/tests/test_trace.py:43`（`assert "unresolved" in rows[0].name or rows[0].name == "Stranger"`） | テストの非空虚性（Phase 0+1 の変異検証の規律）
`or` の右辺が常に成り立つので左辺は検査されていない。実装（`core_pointer` の fallback）は name = author なので右辺だけが真。
修正案: `assert rows[0].name == "Stranger"` に絞る。

**F-V-P2-020** | 65 | `CLAUDE.md:52`（チェックリスト 4「兄弟は 1 要素に `"jin_adk | jin_render"` と `|` 区切りで書く」） | CLAUDE.md の記述と実装の一致
Phase 2 で実測された罠（存在しないパッケージを `|` で並べると import-linter 2.14 が `Missing layer` で EXIT 1）は `pyproject.toml` のコメントと version-matrix #14 にしかなく、次の実装者が最初に読む CLAUDE.md のチェックリストは「`|` で書け」とだけ言う。Phase 3 で jin_render を足す人は 4 を読んで pyproject を開くので致命ではないが、CLAUDE.md 単体では誤誘導。
修正案: 4 に「兄弟が**まだ存在しない**間は単独で書き、2 つ目を足すときに `|` に直す（`Missing layer` で落ちる）」を 1 文足す。

**F-V-P2-021** | 60 | `tests/contract/test_adk_version_contract.py::test_jin_adk_does_not_import_jin_cli_or_later_packages` | ADR-003 / DP-REVIEW-JIN-007（ファイル名と守備範囲）
ファイル名は「ADK 版の契約」だが 3 本目は依存方向テストで、`tests/contract/test_dependency_direction.py::test_jin_core_does_not_import_jin_cli` と同型。版契約 2 本の置き場としては `tests/contract/` で正しい（uv.lock ↔ jin_adk 定数 ↔ delivery 文書の横断）。
修正案: 3 本目を `test_dependency_direction.py` へ移して `jin_core` 版と parametrize で統合。

**F-V-P2-023** | 60 | `packages/jin-cli/src/jin_cli/main.py:105-114, 505-514, 545-552` | 重複排除（同じ文言「ファイルがありません」「'.jin' ではありません」が 3 箇所）
`_load_model_or_exit` が check / dump の事前検査を 3 つ目のコピーとして持つ。文言を変えるとき 3 箇所を同時に直す必要がある。
修正案: `_require_jin_file(path) -> None` に抽出して 3 箇所から呼ぶ。

**F-V-P2-015** | 60 | `packages/jin-adk/src/jin_adk/templates/agent.py.j2`（`class StateCheckAgent` の直後 / `_state_matches` の注釈） | NFR-GEN-001（diff しやすい生成物）/ CLAUDE.md「生成コードはテンプレートを直す」
リポジトリの ruff 設定で生成物を整形すると差分が出る。隔離コピーで `ruff format --diff --line-length 100 out_tmp2/Pipeline/agent.py` → `class StateCheckAgent` と最初の `Drafter = LlmAgent(` の間に空行 1 本追加（`1 file would be reformatted`。researcher は `already formatted`）。同コピーの `pyproject.toml` を拾った状態で `ruff check out_tmp2/Pipeline/agent.py` → `PYI041 Use float instead of int | float`（`expected: bool | int | float | str`）1 件。生成物を利用者が自分の ruff にかけると毎回 diff が出る。
修正案: テンプレートで `has_exit` のとき blocks の前に空行を 2 本にする。`PYI041` は `FlowExit.equals` の型（bool | integer | number | string）を写した注釈なので、直すなら `bool | float | str` にしてコメントで model.md §3.4 を参照。

### 1.3 confidence < 60

**F-V-P2-016** | 55 | `packages/jin-adk/src/jin_adk/codegen.py:710`（`.env.example` ヘッダ「# generated by jin — .env.example」） | `# generated by jin — do not edit` ヘッダの契約（要件書 §3.2）
`agent.py` / `__init__.py` は「do not edit」付き、`.env.example` は無し。`.env` へコピーして編集する前提なら妥当だが、その意図はどこにも書かれておらず、ヘッダを検査するテストも `agent.py`（`test_header_states_…`）と `__init__.py`（`startswith("# generated by jin")`）だけ。
修正案: `.env.example` のヘッダ行を「コピーして `.env` を作る（このファイル自体は再生成される）」と明示し、3 ファイルのヘッダ規約を `test_build.py` で 1 つのテストに固定。

**F-V-P2-018** | 55 | `packages/jin-cli/src/jin_cli/main.py:599-603`（`_format_row` の `120` / `117`） | CLAUDE.md「具体値（しきい値）を推測で置かない。根拠を残す」
stdout 表示の切り詰め幅がマジックナンバー。
修正案: `_ROW_PREVIEW_CHARS = 120` を定数化し、根拠（端末幅 / 要件書に無いので表示都合）をコメントに残す。

**F-V-P2-022** | 55 | `packages/jin-adk/src/jin_adk/build.py:41` と `packages/jin-cli/src/jin_cli/main.py` の同名 `WriteRefused`（`BuildWriteRefused` として別名 import） | 命名（version-matrix #16 が罠として記録）
同名クラスが 2 パッケージにあり、片方を別名で取り込む運用。次に `jin_adk.build` から別の名前を import するときも同じ罠を踏む。
修正案: jin_adk 側を `ProjectWriteRefused`（または `GeneratedProjectRefused`）に改名し別名 import を消す。

**F-V-P2-024** | 55 | `CLAUDE.md:132-133`（「`.jin` 由来の文字列は `jin_adk.codegen.py_literal` で必ず Python リテラルにしてからテンプレートへ渡す」） | CLAUDE.md の記述と実装の一致
`builtin` 名（識別子として `from google.adk.tools import <名>` / `tools=[<名>]`）、`ref` のモジュールパス（`from <module> import`）、`flow.max`（整数）は `py_literal` を通らず、検査（`isidentifier` / `check_ref_format` / Pydantic の型）を通した生値で埋め込まれる。codegen の docstring は「識別子として埋め込むものは検査済みのみ」と正しく分けている。
修正案: CLAUDE.md を「文字列**値**は `py_literal`、識別子は検査済みのものだけ」に直す。

**F-V-P2-026** | 50 | `packages/jin-adk/src/jin_adk/codegen.py:527-535` | 日本語文言の一貫性（何が悪いかを名指しする）
「flow circle に await がありますが、workflow agent は **tools** を持てません」は原因の名指しがずれている（await は tools を包む指定であることが読み手に伝わらない）。
修正案: 「await は tools の関数を LongRunningFunctionTool に包む指定で、tools を持てない workflow agent には書けません」。

**F-V-P2-025** | 50 | `docs/spec/model.md` §3.1（`{{` / `}}` は Jin 側のエスケープ規則）と同節末尾「ADK へは渡せない」 | 仕様の自己整合 / HANDOFF の網羅
Jin のエスケープ規則は `jin check`（JIN050）にだけ残り、`{{` を含む rune はすべて `jin build` で落ちるので、規則を使う `.jin` は存在できない。仕様変更（規則の撤廃 or ADK と同じ規則へ）は人間承認事項だが Q-JIN-P2-01〜05 に含まれていない。
修正案: Q-JIN-P2-06「model.md §3.1 のエスケープ規則を撤廃するか」を HANDOFF に追加し `docs/pending-decisions.md` に起票。

**F-V-P2-027** | 45 | `packages/jin-cli/tests/test_build_run.py:112` / `packages/jin-adk/tests/test_codegen.py:219,375` / `packages/jin-adk/tests/test_runtime.py:48` | CLAUDE.md「正準形の規則は `jin_core.canonical` の 1 箇所にだけ実装する」
pointer 解決用の文書を `model.model_dump_json(by_alias=True, exclude_defaults=True)` で 4 回組み立てている。`exclude_defaults` の扱いは正準形の規則（model.md「`out: false` は既定値なので正準形では出力しない」）と同じ判断を Pydantic 引数で再実装している形で、規則が変わるとテストが黙ってずれる。
修正案: `json.loads(jin_core.canonical.dumps(model))` を使う共通ヘルパ（`tests/conftest.py` か各パッケージ tests）に寄せる。

**F-V-P2-028** | 40 | `docs/spec/adk-mapping.md` §5 | 文書の重複
「1 circle に `out: true` が 2 件以上」行と「§3.1 の各行」行が同じことを 2 度言う（前者は §3.1 の `two_out_states` 行に含まれる）。
修正案: 前者を削除し §3.1 に一本化。

**F-V-P2-029** | 40 | `.gitignore` / `README.md:18-19` | 開発コマンド例の後始末
README の例は `out/` と `t.jsonl` をリポジトリ直下に作るが `.gitignore` に無い（`git status` に出る）。
修正案: `.gitignore` に `out/` と `*.jsonl` を足すか、例の出力先を `/tmp` にする（CLAUDE.md の例は `/tmp` を使っており不揃い）。

## 2. 観点ごとの確認結果（finding にならなかったもの）

- CLAUDE.md の Phase 2 追記: 実装の進み具合表 / 未定義コマンド 3 つ / `TARGET_ADK_VERSION` と版契約テスト / スナップショット更新手順 / fixture の置き場 / `jin run` の危険性 — いずれも実装と一致（例外は F-V-P2-003 / 013 / 020 / 024）。
- `docs/spec/*.md` の機械可読マーカー: 3 ブロックとも `<!-- machine-readable: … -->` / `<!-- /machine-readable -->` で閉じ、`machine_block()` で取れる。`build-errors` 表と fixture 14 件は過不足なし。
- 生成物の正準性: `jin fmt` は `.jin` の規則であり Python 生成物には及ばない。生成物は同一入力・別プロセス（`PYTHONHASHSEED` 0 / 12345）でバイト一致（`test_cli_contract.py`）。`jin_core.canonical` の規則は実装側へ分散していない（テスト側の 1 件は F-V-P2-027）。
- `guard:` 記法: `jin_adk/{build,runtime,codegen}.py` は記法どおり（`<関数名> -> <属性参照|呼び出し>`）。散文だけの安全宣言は F-V-P2-005 の 1 件。
- 命名: `EXIT_CHECKER_SUFFIX` / `RESERVED_NAMES` / `PointerMap` / `RuntimeTable` / `TraceWriter` / `FakeToolCall` は守備範囲と一致。モジュール名は CLAUDE.md の記述と一致。
- delivery 成果物: `adk-api-probe.md` / `implement-ledger.md` / `replay-commands.md` / `version-matrix.md` は追記のみ（削除行なし）。`implementation-notes.md` は Phase 2 節の追記のみ。`phase2-mutations/` は再現可能（§0）。
- 日本語文言: 「シンボリックリンクなので書き込みを拒みました」「既にあります。上書きするなら --force を付けてください」は Phase 1 と同じ言い回し。

## 3. 上位 5 件

1. F-V-P2-003 — CLAUDE.md の jin-lsp 隔離主張が依存図・design.yaml・Phase 2 の実装と矛盾（Phase 4 の安全境界に直結）
2. F-V-P2-011 — builtin 名と circle 名の衝突を検出せず生成物が黙って壊れる（NFR-FAIL-001・cross-cutting）
3. F-V-P2-006 / 007 — delivery 成果物の extend 規律（未申告の書き換え 1 キー・消えた記録・方針文と表の食い違い）
4. F-V-P2-004 / 005 — `guard:` 検査の配置（ADR-003）と `run` の散文安全宣言
5. F-V-P2-001 / 002 / 014 — テスト名の嘘 2 件と、ruff 既定 select のまま死んだ `noqa` が増えた点（DP-REVIEW-JIN-002）

DONE_WITH_CONCERNS
