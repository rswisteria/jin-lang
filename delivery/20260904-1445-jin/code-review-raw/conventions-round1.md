# 再レビュー（修正ラウンド 1）— conventions

実施: 2026-09-04 / 対象: ワーキングツリー（実装一式は依然 untracked、HEAD は `f6a37e0 first commit`）
判断材料: コード・生成物・実測のみ。実装者の報告・コメント・rationale は未検証の主張として扱い、
主張が載っている箇所は**独立に再現**して裏を取った。

## Summary

- **確認対象: 5 件（A-1 / A-2 / A-3 / C-1 / G-1）**
- **defect-gone: 5 件 / 未消滅: 0 件 / 判定不能: 0 件**

- **命名の三者一致（コード・仕様書・テスト）: 全系統で一致を再確認**
  - 診断コード: `diagnostics.py` の `CANONICAL_CODES` 12 件 + `PROPOSED_CODES` 2 件 ＝ `diagnostics.md` §2/§3 の machine ブロック ＝ `packages/*/src` の emit 箇所 14 件 ＝ fixture のコード集合 14 件。要件書 §2.4 の 12 件は正典側と完全一致。
  - 意味オペレーション: `ops.OPERATIONS` 19 件 ＝ `ops.md` の `ops-list` 19 件 ＝ 要件書 §6.3 の 19 件（ソート済み集合が三者で一致）。
  - `data-jin-kind`: `layout.md` の `data-jin-kinds` 9 値 ＝ 要件書 §2.5 の 9 値。
  - JSON キー語彙: `adk-mapping.md` の `adk-vocabulary` が 12 行（要件書 §2.1 と同数）。
  - `model.md` の 4 表（`root-keys` / `circle-keys` / `tool-kinds` / `guard-on-values`）を `model.py` と手で再突合し、**キー名も定義順も一致**することを確認（`JinFile` / `Circle` / `Tool` 判別共用体 / `GuardOn` / `Boundary`）。修正で `model.py` に変更が入っているが、ドリフトは発生していない。

- **docs/spec の S-1〜S-6 修正の妥当性: 妥当（conventions 観点で確認できた範囲では正しい）**
  - S-1: `ops.md` §1 に「逆適用の結果は順適用前の正準形とバイト一致する。配列要素の**位置**も、順オペレーションが副次的に作った**入れ物**も元に戻す」が追記され、§2.1 に新規 machine ブロック `ops-restore-conditions`（`toggleAwait`→`index` / `toggleAwait`→`pruneBoundary` / `setGuard`→`pruneBoundary`）が置かれた。§2 の逆オペレーション欄も `toggleAwait` / `setGuard` の 2 行が §2.1 を参照する形に更新済み。**§1 の主張と §2/§2.1 の内容が整合している**。`ops.py` 側にも `index` / `pruneBoundary` が実在（`ops.py:163, 216, 361, 401, 418`）。
  - S-2 の星形多角形（`layout.md` §2.1）: 定義 `k = max{ j : 1 <= j < n/2 かつ gcd(n, j) == 1 }` と例示 n=5→2 / 6→1 / 7→3 / 8→3 / 9→4 を手計算で全件検証し、**全て正しい**。従来誤っていた n=6 の根拠説明も「`j = 3` は `2*3 < 6` が偽なので探索範囲に入らない。`gcd(6,2)=2` なので `j=2` が落ち、残る最大は `j=1`」と正しい説明に置き換わった。整数演算 `2*j < n` は `j < n/2` と等価で、浮動小数点比較を避ける指定も妥当。

- **diagnostics.md の正典表／追加提案表の分離維持: 維持されている（統合されていない）**
  - `docs/spec/diagnostics.md:35` `## 2. 正典コード（要件書 §2.4 の 12 件）`（machine ブロック `diagnostics-canonical`・12 行）と `:61` `## 3. 追加提案コード（ADR-007 / DP-JIN-SEMANTIC-GAPS-01・**人間承認待ち**）`（machine ブロック `diagnostics-proposed`・JIN012 / JIN013 の 2 行）は**別見出し・別ブロック**のまま。
  - 要件書 §2.4 は**未編集**（`git diff jin-requirements.md` が空、`git status` にも現れない）。写しの `docs/superpowers/specs/2026-09-04-jin-overview.md` も同様。`test_requirements_copies_are_identical` を含む spec 突合 50 件が緑。

- **突合テストの劣化（脆い正規表現化）: docs/spec 側は劣化なし。ただし新規テスト側に軽い後退あり**
  - `docs/spec/*.md` の定型は保たれている。machine-readable マーカーは 17→18 に増え（`ops-restore-conditions` を新設）、テストに消費されるマーカーは **9→12** に増えた（`ops-restore-conditions` / `rename-cascade` / `upstream-rule` が新たに消費される）。表の書式・見出し階層は不変。
  - 要件書側パーサ（`test_spec_consistency.py:87-121` の `req_ops` / `req_ring_radii` / `req_data_jin_kinds` / `section`）は**round 1 から一字も変わっていない**。D-3 で挙げた脆さは残っているが、fix-later 扱いなので対象外であり、**悪化はしていない**。
  - 一方、S-1〜S-6 用に追加された新規テストの一部が、machine ブロックではなく**日本語の散文への部分文字列 assert** に依存している（新規欠陥 N-2 として後述）。

- **修正が入れた新規欠陥: 3 件**（いずれも low、fix-now 相当ではない）

- **作業ツリーへの変更: 残していない**
  - 再現のため (a) `packages/jin-cli/tests/test_model.py` の一時作成、(b) `packages/jin-adk/` 一式の一時作成、(c) `pyproject.toml` の `root_packages` 一時改変 を行ったが、いずれも削除・復元済み。`__pycache__` も除去。`git status --short` が再レビュー開始時と同一であること、`root_packages = ["jin_core", "jin_cli"]`（`pyproject.toml:52`）に戻っていること、`packages/` の中身が `jin-cli` / `jin-core` の 2 つだけであることを確認した。
  - 最終状態で `uv run pytest` 442 件が緑、`uv run ruff check .` / `ruff format --check .` が緑（40 files already formatted）、`uv run lint-imports` が 3 contracts kept / 0 broken。

---

## finding 別の判定

| ID | 判定 | 根拠 |
|---|---|---|
| **A-1** | **defect-gone** | 二重に手当てされている。(1) `packages/jin-core/tests/__init__.py` と `packages/jin-cli/tests/__init__.py` が実在（同一 docstring で理由を明記）、(2) `pyproject.toml:39` `addopts = "-q --import-mode=importlib"`。**独立に再現**: `packages/jin-core/tests/test_model.py` を `packages/jin-cli/tests/` へコピーして `uv run pytest` を実行 → `Interrupted` にならず **466 件が全て通過**（通常時 442 + 重複した 24）。round 1 で観測した `import file mismatch` は再現しない。契約テスト `test_every_package_test_directory_is_a_package`（`test_packaging_contract.py:70-79`）と `test_import_mode_is_importlib`（`:82-85`）が両方の手当てを機械で固定している。 |
| **A-2** | **defect-gone** | 5 箇所のうち `testpaths` は**列挙そのものが消えた**（`pyproject.toml:35` `testpaths = ["tests", "packages"]`）。残る 4 箇所は `tests/contract/test_packaging_contract.py` がディスク上の `packages/*/` を正として突き合わせる。**独立に再現**（実在しない `packages/jin-adk/` を作って mutation）: 第 1 波で 4 件が**名指しで**赤 —— `test_every_package_test_directory_is_a_package[jin-adk]`（`__init__.py` 欠落）/ `test_every_package_is_a_root_package[jin-adk]`（`root_packages` 欠落）/ `test_every_package_appears_in_the_layers_contract[jin-adk]`（layers 欠落）/ `test_every_package_is_declared_in_the_workspace[jin-adk]`（`[project].dependencies` と `[tool.uv.sources]` の両方を 1 テストで検査）。`root_packages` に足した第 2 波で `test_resolver_isolation_contract_covers_every_package_but_the_cli` が「resolver 隔離契約の source_modules に {'jin_adk'} が無い」で赤くなる。`testpaths` の網羅は `test_every_package_test_directory_is_collected` が緑で通ることで確認（列挙をやめたので追記不要）。**CLAUDE.md にチェックリストも書かれた**（`CLAUDE.md:39-54`「パッケージを足すときのチェックリスト」6 項目）。その存在は `test_claude_md_has_the_package_addition_checklist`（`test_packaging_contract.py:185-201`）が 6 項目の文字列を名指しで検査する。 |
| **A-3** | **defect-gone** | 2 点とも解消。(1) A-1 が消えたので、Phase 2 で「テストが 1 件も走らない」状態にはならない —— jin-adk mutation でも collection は止まらず、赤くなったのは名指しの 5 件だけだった。(2) トリップワイヤ `test_later_packages_do_not_exist_yet`（`test_dependency_direction.py:198`）の docstring が「直すのは**この 1 行ではなく** `CLAUDE.md` の『パッケージを足すときのチェックリスト』の 6 項目である」と 6 項目を列挙し、抜けは `test_packaging_contract.py` が落とすと明記している。mutation 時の失敗出力にこの docstring が丸ごと出ることを実測で確認した。docstring の内容は `test_the_tripwire_points_at_the_checklist`（`test_packaging_contract.py:204-210`）が機械で固定する。 |
| **C-1** | **defect-gone** | `version-matrix.md:77` が「JSON 文法は `packages/jin-core/src/jin_core/parser.py` のインライン定数 `JIN_JSON_GRAMMAR` として自作した（`.lark` ファイルは作っていない。wheel への `force-include` 設定が不要になるため）」に訂正済み。**独立に検証**: `find packages -name "*.lark"` は 0 件、`parser.py:33` に `JIN_JSON_GRAMMAR = r"""` が実在。記述と実装が一致した。存在しないパス `jin_core/grammar/jin_json.lark` はリポジトリ内のどこにも残っていない。 |
| **G-1** | **defect-gone** | `.python-version`（内容 `3.14`）が新設され、gitignore 対象外なのでコミットされる。**独立に検証**: `.venv` の実測が 3.14.6 で `.python-version` の 3.14 系と整合。CI（`ci.yml:30-41`）は `setup-uv` に版を渡さず uv のネイティブな `.python-version` 読み取りに一本化し、`uv run python -c "import sys; print(sys.version)"` で実際に使った版をログへ残す。**実装者の「setup-uv@v5 に `python-version-file` 入力は存在しない」という主張を独立に再現**（`curl` で v5 の `action.yml` を取得 → inputs は `version` / `pyproject-file` / `uv-file` / `python-version` / `checksum` / … で、`python-version` は有り・`python-version-file` は**無し**）。この決定は `tests/contract/test_ci_contract.py` の 4 テスト（`test_python_version_file_exists_and_is_used` / `test_ci_does_not_pass_a_nonexistent_input_to_setup_uv` / `test_ci_does_not_hardcode_a_python_version` / `test_pinned_python_satisfies_requires_python`）が機械で守る。<br>なお round 1 で併記した「`ruff target-version = "py312"` を消して `requires-python` から推論させる」という副次的な提案は**取り下げる**。`requires-python = ">=3.12"` から推論される値は `py312` そのもので、ruff の `target-version` は「サポートする最小版」を指すのが正しい使い方なので、`py312` の明示は現状で正しい。G-1 の本体（実行版がどこにも固定されていないこと）は解消した。 |

---

## 修正が入れた新規欠陥（3 件・いずれも low）

### N-1 [severity: low / confidence: 70] `test_the_only_module_importing_importlib_is_the_cli_resolver` が Phase 2 で必ず赤くなるが、そのときの直し方が書かれていない

`tests/contract/test_packaging_contract.py:132-142` は全パッケージの `src/` を走査し、`importlib` を import している行を持つファイルの一覧が
**厳密に** `["packages/jin-cli/src/jin_cli/resolver.py"]` と等しいことを assert する。

要件書 §3.4（`jin-requirements.md:300`）は `jin run` を「生成コードを一時ディレクトリに書き出して **import** し、`Runner` + `InMemorySessionService` で実行」と定めている。つまり **Phase 2 の `jin-adk` は importlib（相当）を必ず使う**ので、このテストは Phase 2 で確実に赤くなる。

問題は、docstring が「S1 の生の検査（import-linter を差し替えても残る網）」としか書いておらず、**セキュリティ不変条件として読める**点。A-3 のトリップワイヤが「直すのはこの 1 行ではなくチェックリストの 6 項目」と明示しているのと対照的に、こちらは期待値リストを直してよいのか、それとも jin-adk の import を jin_cli 経由に回すべきなのか（＝依存方向を逆転させる誤った修正）が読み取れない。A-3 と同じ形で docstring に「Phase 2 で `jin_adk` が生成コードを import するようになったら期待値に足す。ただし `jin_lsp` は足さない（ws で外に出るため）」と書けば解消する。

### N-2 [severity: low / confidence: 65] 新規の spec 突合テストが machine ブロックではなく日本語の散文への部分文字列 assert に依存している

`docs/spec/*.md` は §0 で「機械が読む表・箇条書きは machine-readable マーカーで囲む」と自ら約束しており、既存テストはその約束に従っている。しかし S-1〜S-6 用に追加されたテストの一部は、マーカーの外の散文を部分文字列で見ている:

| テスト | 行 | 依存している文字列 |
|---|---|---|
| `test_ops_declare_the_restore_contract` | `test_spec_consistency.py:313` | `"バイト一致" in text`（`ops.md` 全文のどこかにあればよい） |
| `test_ops_list_mentions_the_restore_conditions` | `:342-343` | `"§2.1"`（節番号のリテラル。節を繰り上げると落ちる） |
| `test_model_says_where_loop_only_keys_are_rejected` | `:379` | `"段 2"`（全角スペース有無・「第 2 段」等の言い換えで落ちる） |
| `test_model_states_that_a_pointer_denotes_one_value` | `:404` | `"重複キー"` |
| `test_rune_escape_claim_is_marked_unverified_without_probe_evidence` | `:423` | `re.search(r"\{\{.*\}\}\|エスケープ", probe)` |

最後の 1 件がとくに緩い。`adk-api-probe.md` に**「エスケープ」という語が 1 度でも現れると**「実測の証拠が入った」と判定して `pytest.fail` する。現在この語の出現数は 0 なので緑だが、無関係な一文が入るだけで誤発火する。判定を「実測の証拠がある」に近づけるなら、probe 側に `<!-- machine-readable: rune-escape-probe -->` のような明示マーカーを置いて、その有無で分岐するのが本プロジェクトの規約に沿う。

`test_every_reference_in_rename_cascade_has_a_diagnostic_rule`（`:354-372`）も、優先順位表の 1 列目を `" / "` で連結した 1 本の文字列に対する `in` 判定なので、行をまたいだ偶然の一致で通りうる。

いずれも「テストが無いよりは遥かに良い」水準であり、S-1〜S-6 の再発防止としては機能する。指摘は**規約の一貫性**（マーカー方式で統一する）についてのもの。

### N-3 [severity: low / confidence: 55] CLAUDE.md チェックリスト項目 5 の前半（google-adk 契約）だけ機械検査が無く、しかも全パッケージに当てはまらない

`CLAUDE.md:49-50` の項目 5 は forbidden 契約について「『google-adk に依存しない』『resolver は jin_cli に閉じる』の**対象に加える**（`jin_cli` 自身は後者の対象外）」と書く。

jin-adk mutation の実測では、後者（resolver）は `test_resolver_isolation_contract_covers_every_package_but_the_cli` が確かに赤くなったが、**前者（google-adk）を検査するテストは存在しない**（第 1 波・第 2 波いずれでも赤にならなかった）。

さらに、前者は文言どおりに実行すると**誤り**になる。design.yaml `architecture.dependency_direction.rules` のルール 2 が禁じているのは jin-core（と Phase 3 の jin-render）であり、`jin-adk` は ADK 語彙が現れてよい唯一のパッケージなので `source_modules` に加えてはいけない。`pyproject.toml:73-74` のコメントは「jin_render も ADK に依存してはいけない。Phase 3 で jin_render を作ったら source_modules に足すこと」と**正しく限定**しているので、CLAUDE.md 側の書き方だけが緩い。項目 5 を「resolver 契約には全パッケージを足す。google-adk 契約は jin-render のときだけ足す（jin-adk は対象外）」と書き分ければ解消する。

---

## 参考: 今回の対象外（fix-later のまま残っている round 1 の finding）

回帰していないことだけ確認した。C-2（`extend-exclude` が `jin-requirements.md` を除外せず `docs/` のコピーだけ除外する非対称・`pyproject.toml:47`）、C-4（README の `a.jin`・現 `README.md:14`）、E-1（言語指定の無いコードフェンス 3 箇所・`CLAUDE.md:23` / `README.md:31` / `docs/spec/layout.md:45`）、D-3（要件書側パーサの脆さ）、D-2 の残り（マーカー 18 個中 6 個が未消費: `canonical-rules` / `circle-keys` / `guard-on-values` / `reference-edges` / `root-keys` / `tool-kinds`）はいずれも round 1 と同じ状態か、D-2 のように**改善方向**にある。B-1（syrupy 未導入）も変化なし。
