# 再レビュー（修正ラウンド 2）— wiring

実測日: 2026-09-04 / レビュアー: rv1-wiring
基準状態: `uv run pytest` **491 passed** / `lint-imports` **3 contracts kept** / `.venv` = Python 3.14.6

**実装者・親の報告は一切採用していない。** 判定はすべて下記の実行結果に基づく。
破壊的な変異は原則として**リポジトリの隔離コピー**（`$CLAUDE_JOB_DIR/tmp/r2copy`）で行い、
実物のツリーには一切書き込んでいない（後述の復旧欄を参照）。
コピーは作成直後に `491 passed` で実物と一致することを確認してから使った。
CI の実挙動は、ピン留めされた **uv 0.12.9** の実バイナリで再現した。

## Summary

- **確認対象: 3 件（W-05 残件 / N-01 / N-02）**
- **判定: defect-gone 3 件 / 未消滅 0 件 / 判定不能 0 件**
  - **W-05 残件 → defect-gone。** 親の検証（チェッカー関数の無力化）は経路の検証ではなかったが、
    **実パッケージを作って実 `pyproject.toml` 経由で確認した結果も defect-gone**。
    `packages/jin-adk` / `packages/jin-render` をチェックリスト 6 項目すべて満たして作り、
    layers だけを**素朴な直列**にしたところ
    `test_layers_contract_keeps_sibling_packages_in_one_element` が名指しで赤くなった。
    さらに実 `pyproject.toml` の contract で `lint-imports` を走らせ、
    素朴な直列では片方向しか報告されず `|` 区切りでは両方向が報告されることを end-to-end で確認した。
  - **N-01 → defect-gone。** `--frozen` を戻す / `version:` を消す / `run: |` ブロックに `--frozen` を隠す /
    `UV_FROZEN` を env に置く / ステップを減らす、の 5 変異すべてが正しい名前のテストで赤くなる。
    加えて**走査関数 `uv_commands` 自体を無力化する変異**も 4 本のテストが同時に捕まえた。
  - **N-02 → defect-gone。** `packages/jin-core/tests` を消すと **SKIPPED ではなく 3 本 FAILED**。
    allowlist で免除しても `test_the_allowlist_is_empty` が赤くなるので、免除の門が隠れない。
- **ラウンド 2 が新たに入れた配線の欠陥: 0 件。**
  回避経路を 3 通り（inline env 前置 / `sh -c` 入れ子 / step レベル env）試したが**すべて捕捉された**。
  欠陥ではないが申し送るべき観察を 3 件、末尾の「残る観察」に記す（いずれも severity low）。
- **作業ツリー復旧**: `uv.lock` は**レビュー開始時とバイト一致**（`diff -q` OK / md5 `1fcc8e35b7d9f77ef84c3d5ec73a4903`）。
  実物のツリーへの書き込みは本ラウンドでは 1 件も行っていない（本報告書の追加のみ）。
  `packages/` は `jin-cli` / `jin-core` の 2 件、`lint-imports` 3 kept、
  `jin check examples` / `jin fmt --check examples` / スキーマドリフト比較すべて rc=0。
  `uv run pytest` は **5 回連続で 491 passed**。

  なお**検証中の一時期、実物のツリーが赤かった**（`test_check_reports_a_bom_file` /
  `test_utf8_bom_is_reported_with_a_specific_message` / `test_lone_surrogate_is_rejected_by_the_writer`、
  最大 4 failed / 487 passed）。これは私の操作ではなく（私は実物へ書き込んでいない）、
  BOM / サロゲート処理の編集が同じツリーで進行していた時間帯と一致する。
  その後 5 回連続 491 passed に収束したため、フレーキーではなく**並行編集の途中経過**と判断する。
  wiring 観点の欠陥としては報告しない。

---

## finding 別の判定

| ID | 判定 | 根拠（実行したコマンドと出力） |
|---|---|---|
| **W-05 残件** 兄弟の同居を強制する検査が無い | **defect-gone** | **(1) 実パッケージでの経路検証（親の変異では未検証だった部分）** — 隔離コピーに `packages/jin-adk` / `packages/jin-render` を CLAUDE.md のチェックリスト 6 項目すべて（`dependencies` / `tool.uv.sources` / `root_packages` / layers / resolver 契約の `source_modules` / `tests/__init__.py`）を満たして作成し、**layers だけを素朴な直列** `["jin_cli","jin_adk","jin_render","jin_core"]` にした。<br>→ `FAILED tests/contract/test_packaging_contract.py::test_layers_contract_keeps_sibling_packages_in_one_element`<br>メッセージ: `[(frozenset({'jin_adk','jin_render'}), "['jin_adk', 'jin_render'] が別々の layer 要素にある（'A \| B' と 1 要素に並べること）")]`<br>**(2) 実 pyproject 経由の import-linter end-to-end** — 兄弟間の相互 import を両方向に仕込み、実 `[tool.importlinter]` で `lint-imports` を実行:<br>・素朴な直列 → `Contracts: 2 kept, 1 broken` / 報告は `jin_render.uses_adk -> jin_adk` の**1 件のみ**（`jin_adk → jin_render` は静かに許される）<br>・`layers = ["jin_cli","jin_adk \| jin_render","jin_core"]` に直す → 報告が `jin_adk.uses_render -> jin_render` と `jin_render.uses_adk -> jin_adk` の**2 件**に増える<br>**(3) 正しい形に直せば緑に戻る** — `\|` 区切りにした状態で `pytest tests/contract/test_packaging_contract.py` → 全緑（FAILED なし）。<br>検査は design.yaml の `dependency_direction.rules` を正本として読み（`test_design_yaml_declares_exactly_one_sibling_pair` が抽出結果 `{frozenset({'jin_adk','jin_render'})}` を固定）、ワイルドカード行 `jin-core は他の jin-* パッケージに依存しない` を具体名と誤読しないことも別テストで固定されている。design.yaml 側の `rules:` 行は**ファイル内に 1 つだけ**（140 行目）で、パーサが別ブロックを掴む余地は現状無い（`grep -n '^\s*rules:\s*$'` で確認）。 |
| **N-01** `UV_LOCKED` が `--frozen` に打ち消されている | **defect-gone** | ci.yml は `run: uv sync`（`--frozen` 削除・:57）+ `setup-uv` に `version: "0.12.9"`（:40）。<br>**ci.yml 変異テスト（隔離コピー・毎回 `pytest tests/contract/test_ci_contract.py`）**:<br><br>| 変異 | rc | 赤くなったテスト |<br>|---|---|---|<br>| `run: uv sync` → `uv sync --frozen` | 1 | `test_no_uv_command_defeats_uv_locked` / `test_the_sync_step_actually_verifies_the_lock` |<br>| `version: "0.12.9"` を削除 | 1 | `test_uv_version_is_pinned` |<br>| `run: \|` ブロックに `uv sync --frozen` を混入 | 1 | `test_no_uv_command_defeats_uv_locked` / `test_the_sync_step_actually_verifies_the_lock` |<br>| job env に `UV_FROZEN: "1"` を追加 | 1 | `test_uv_frozen_is_not_set_anywhere` |<br>| ステップを 2 つ削除（走査件数を下げる） | 1 | `test_the_uv_command_scanner_does_not_silently_shrink` |<br>| 無変異 | 0 | — |<br><br>**走査関数自体の無力化も捕捉される** — `uv_commands` の先頭に `return []` を挿入し、同時に ci.yml へ `--frozen` を戻す（= 検査が緑のまま欠陥を見逃す最悪ケース）→ `test_no_uv_command_defeats_uv_locked` / `test_the_uv_command_scanner_does_not_silently_shrink` / `test_the_uv_command_scanner_reads_multiline_run_blocks` / `test_the_sync_step_actually_verifies_the_lock` の **4 本が同時に赤**。**「検査が存在する ≠ 検査が落ちる」は脱している。**<br>**CI 全ステップの実挙動**（uv 0.12.9 実バイナリ + `UV_LOCKED=1`、`UV_PROJECT_ENVIRONMENT` を別ディレクトリへ逃がして実物の `.venv` は不使用）: 9 ステップすべて **rc=0**、`uv.lock` は最後まで `same`、**Sync ステップに警告は 1 件も出ない**（ラウンド 1 で出ていた `Ignoring UV_LOCKED because --frozen was provided` が消えた）。<br>**ci.yml のコメントに書かれた実測主張も独立に検証した**: `curl https://raw.githubusercontent.com/astral-sh/setup-uv/v5/action.yml` の `inputs:` は `version / pyproject-file / uv-file / python-version / checksum / github-token / enable-cache / cache-dependency-glob / cache-suffix / cache-local-path / prune-cache / ignore-nothing-to-cache / ignore-empty-workdir / tool-dir / tool-bin-dir` の 15 件で、**`version` は存在し `python-version-file` は存在しない**（`grep -c python-version-file` = 0）。コメントの主張は正確。 |
| **N-02** `tests/` 無しのパッケージが skip で素通り | **defect-gone** | `PACKAGES_WITHOUT_TESTS` を空 `frozenset()` の allowlist にし、非該当は失敗させる設計（test_packaging_contract.py:55-87）。<br>**(1) `packages/jin-core/tests` を削除**（隔離コピー）→ **SKIPPED は 0 件、FAILED 3 本**:<br>・`test_every_package_has_tests[jin-core]` … `jin-core に tests/ が無い。テストを書くか、理由つきで PACKAGES_WITHOUT_TESTS へ明示的に載せること`<br>・`test_every_package_test_directory_is_collected[jin-core]`<br>・`test_every_package_test_directory_is_a_package[jin-core]`<br>**(2) allowlist に `jin-core` を足して免除** → 上の 3 本は SKIPPED になるが、**`test_the_allowlist_is_empty` が赤**（進捗行 `..sF..s.s...`）。免除は静かに通らない。<br>**(3) allowlist に存在しないパッケージ名 `jin-ghost` を残す** → `test_the_allowlist_is_empty` と `test_the_allowlist_has_no_dead_entries` の 2 本が赤。死んだ免除が残らない。<br>N-02 で指摘した「W-03 で塞いだ状態に別経路で到達できる」穴は塞がれている。 |

---

## ラウンド 2 が新たに入れた配線の欠陥

**0 件。**

回避経路を能動的に探索した結果（隔離コピー・ci.yml 変異）、次の 3 通りは**いずれも捕捉された**:

| 回避の試み | 結果 | 捕まえたテスト |
|---|---|---|
| `run: UV_FROZEN=1 uv sync`（inline env 前置。`uv_commands` は `uv ` で始まらないので拾わない） | rc=1 | `test_the_uv_command_scanner_does_not_silently_shrink` / `test_the_sync_step_actually_verifies_the_lock` |
| `run: sh -c "uv sync --frozen"`（走査関数の docstring が「原理的に見つけられない」と明記している入れ子） | rc=1 | 同上 |
| step レベルの `env: UV_FROZEN: "1"` | rc=1 | `test_uv_frozen_is_not_set_anywhere` |

**設計として良い点**: 走査関数が拾えない書き方は、いずれも「拾える `uv` コマンドが 1 つ減る」形になるため、
`MINIMUM_UV_COMMANDS`（下限 9・現在ちょうど 9 件）と
`test_the_sync_step_actually_verifies_the_lock`（`uv sync` が 1 件も見つからなければ失敗）が
**docstring が自認している盲点を実効的に塞いでいる**。
走査の限界を認めたうえで、限界に落ちたことを別の不変量で検知する構造になっている。

---

## 残る観察（欠陥ではない・severity low・記録のみ）

### O-1 走査件数の下限は「下げてよい」と docstring が案内している（N-02 の allowlist と非対称）
`test_ci_contract.py:163-173` の docstring は「ステップを減らしたなら、この定数も一緒に下げること」と書いている。
N-02 の allowlist には `test_the_allowlist_is_empty` という**見える門**が付いたのに対し、
`MINIMUM_UV_COMMANDS` を下げる操作にはそれが無い。現在値 9 は実測の 9 件とちょうど同じで余裕が無いので
誤って下げにくい形ではあるが、対称にするなら定数の変更を可視化する 1 本があってもよい。

### O-2 テストスイートが日付入りの delivery 成果物パスに依存している
`test_packaging_contract.py:283` が `delivery/20260904-1445-jin/design.yaml` を直接指している。
W-05 の検査（4 本）はこのファイルが読めることが前提で、delivery ディレクトリはラン単位の成果物なので、
アーカイブ・リネーム時にテストが壊れる。契約の正本を design.yaml に置く方針（ADR-004 / CLAUDE.md）
そのものは妥当なので、壊れ方は「loud に落ちる」で安全側。将来 `docs/` 配下など安定した場所へ
契約の正本を移すなら、この定数も一緒に動かすこと。なお design.yaml は git 追跡下にあり CI でも読める。

### O-3 `independence_violations` は片方のパッケージしか宣言に無いとき検査を飛ばす
`test_packaging_contract.py:356-358` は、兄弟ペアの片方だけが `layers` に現れる場合 `len(indexes) < 2` で
スキップする。Phase 2（jin_adk のみ追加・jin_render は Phase 3）の期間は W-05 の検査が実質無効になる。
ただしその期間は「片方しか存在しない」ので実害が無く、存在するパッケージの層への載せ忘れは
`test_every_package_appears_in_the_layers_contract` が別に捕まえる。組み合わせで穴は無い。

### O-4（記録）検証中に実物のツリーが一時的に赤かった
`test_check_reports_a_bom_file` / `test_utf8_bom_is_reported_with_a_specific_message` /
`test_lone_surrogate_is_rejected_by_the_writer` が数分間だけ落ちていた（最大 4 failed / 487 passed）。
私は実物へ書き込んでいないので原因は並行作業。その後 **5 回連続で 491 passed** に収束したため、
フレーキーではなく編集の途中経過と判断した。wiring の欠陥としては計上しない。

---

## 復旧の記録

| 対象 | 状態 |
|---|---|
| `uv.lock` | **レビュー開始時とバイト一致**（`diff -q` OK / md5 `1fcc8e35b7d9f77ef84c3d5ec73a4903`） |
| `pyproject.toml` / `.github/workflows/ci.yml` / `tests/**` / `.python-version` | **実物は未変更**（全変異は隔離コピー内でのみ実施） |
| `packages/` | `jin-cli` / `jin-core` の 2 件。実験用の `jin-adk` / `jin-render` は隔離コピー側にのみ作成し、コピーごと削除済み |
| `.venv` | 未再作成（uv 0.12.9 の検証は `UV_PROJECT_ENVIRONMENT` を別ディレクトリへ逃がし、検証後に削除） |
| 隔離コピー | `$CLAUDE_JOB_DIR/tmp/r2copy` / `tmp/tv2` ともに削除済み |
| フルスイート | `uv run pytest` **491 passed**（5 回連続） |
| `lint-imports` | **3 contracts kept, 0 broken** |
| `jin check examples` / `jin fmt --check examples` / スキーマドリフト比較 | いずれも rc=0 |
| 保持している資材 | `tmp/ul_r2.bak`（本ラウンド開始時の uv.lock）/ `tmp/ul2.bak`・`tmp/ul_now.bak`（ラウンド 1 の記録）/ `tmp/uv-aarch64-apple-darwin/uv`（0.12.9・darwin arm64） |
