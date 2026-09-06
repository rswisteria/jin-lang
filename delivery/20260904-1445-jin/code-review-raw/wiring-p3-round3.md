# Stage 5 最終確認: wiring — Phase 3 (jin-render) 修正ラウンド 3

レビュア: rereview-p3-r3-wiring-security（wiring と security を 1 本で担当・範囲限定）/ 2026-09-06 /
対象ブランチ `feat/jin-phase3-render`（worktree `.claude/worktrees/jin-phase3-6`・ベース origin/main `32c215e`）。
入力: `code-review-raw/wiring-p3-round2.md`（F-W-P3-201〜205）/ `phase3-fix-round-3-instructions.md` / `implementation-notes.md` P3-R3 /
`decision-conformance.md` P3 行（§2.24.1c）。security 側の判定は `security-p3-round3.md`。
worktree に書いたのはこの 2 ファイルだけ。レビュー中に `delivery/20260904-1445-jin/code-review-report.md` が
unmodified → ` M` に変わったが、これは他エージェント（親）の書き込みで本レビューは触っていない。

## 実測した環境・コマンド（隔離コピーのパス・件数）

| 項目 | 実測 |
|---|---|
| 隔離コピー | `/home/wisteria/.claude/jobs/e2bcfe94/tmp/rereview3-ws/tree/`（`.git` / `.venv` / `__pycache__` / `.pytest_cache` / `.claude` を除いて rsync。`PYTHONDONTWRITEBYTECODE=1`・`TMPDIR` はコピー内 `mtmp/`・`-p no:cacheprovider`） |
| import 先の確認 | `jin_cli` / `jin_render` / `jin_core` / `jin_adk` の `__file__` が 4 つともコピー側（`full_suite.sh` が毎回印字）。変異ハーネスの `imports from:` もコピー内 `mtmp/jin-mutate-p3-*` |
| スクリプト | `full_suite.sh` / `run_mutate.sh` / `stdout_probe.sh`（14 通り）/ `mine_mutate.py`（M1〜M5）。いずれも `/home/wisteria/.claude/jobs/e2bcfe94/tmp/rereview3-ws/` |
| `UV_LOCKED=1 uv sync`（worktree） | EXIT 0（Resolved 79 / Checked 76・lock 更新なし。`uv.lock` の差分は origin/main 比の +16 行 = jin-render 追加分で R2 と同じ） |
| `uv run lint-imports`（worktree） | **3 kept / 0 broken** |
| `uv run pytest packages/jin-render/tests`（worktree・単独） | **308 passed**（4 snapshots） |
| `uv run pytest packages/jin-cli/tests`（worktree・単独） | **174 passed** / 18 warnings |
| 全スイート（隔離コピー） | **1201 passed**, 68 warnings, 6 snapshots（notes R3.0 / R3.3 と一致） |
| `mutate_p3.py` 全件（隔離コピーから起動） | baseline green（394 passed）・**75/75 caught**・SKIP 0・rc 0・期待 GREEN 2 本（`CLI-follow-symlink-upfront-only` = 「二層目が守る」/ `STAR-pre-fix-star-shape-stays` = 「主張そのもの（…）」と**印字理由が分かれている**）・`mtmp/` と `/tmp` に `jin-mutate-p3-*` / `jin-run-*` の残骸 0・終了後の `diff -rq` でコピーの `packages/` `tests/` は worktree とバイト一致 |
| CI（`.github/workflows/ci.yml`） | origin/main と差分なし。R3 で足した `preexec_fn` テストは `skipif(not hasattr(os, "fork"))` 付きで Linux runner で成立。**追加が要るステップは無い** |

`stdout_probe.sh`（worktree の editable install に対して読み取りのみ。コードはコピーとバイト同一）:

| # | コマンド | rc | stderr |
|---|---|---|---|
| 1 | `jin render P -o out.svg --force > /dev/full` | **1** | 1 行「標準出力に書けません（No space left on device）」。Traceback 0・`Exception ignored` 0。**SVG は書けている**（6635 B） |
| 2 | `jin build R --out D --force > /dev/full` | **1** | 同じ 1 行。生成物は書けている |
| 3 | `jin render P -o out.svg --force >&-`（fd 1 閉） | 0 | 無言。ファイルは書けている（R2 と同じ。下の「確認できた」） |
| 4 | `jin build … >&-` | 0 | 無言。生成物は書けている |
| 5 | `jin render P >&-` | **1** | 1 行「標準出力が閉じています」 |
| 6 | `jin render P > /dev/full 2> /dev/full` | 120 | （F-S-P3-203・記録のみ・R2 と同じ） |
| 7 | `jin render P -o out.svg --force > /dev/full 2> /dev/full` | 120 | 同上（成功文言側も同じ形） |
| 8 | `jin dump P` / `jin schema` / `jin check <errors> --json` / `jin check <errors>` を `> /dev/full` | 120 | Phase 1 のまま（トレースバック）。**B-3 のヘルパはこれらに到達しない**（`_echo_or_exit` の呼び出し元は `main.py:691` build と `:1101` render の 2 つだけ・grep） |
| 8b | `jin check P --json` / `jin dump P` / `jin schema` を通常のファイルへ | 0 | 3 B / 12198 B / 9020 B。`jin schema` の出力は `schemas/jin.schema.json` と `cmp` 一致。**巻き込み無し** |
| 9 | `jin render P -o link.svg --force`（link は symlink） | 1 | 「シンボリックリンクなので書き込みを拒みました: <link のフルパス>」・**パスは 1 回**・リンク先は無傷 |
| 10 | 診断ありの fixture / `--focus nope` / `-o nodir/x.svg` / `-o 既存（--force 無し）` を `> /dev/full` | 2 / 2 / 1 / 1 | Traceback 0。**fail-open 0** |
| 11 | `PYTHONDEVMODE=1 jin render P -o … > /dev/full` | 1 | `ResourceWarning` 1 行（F-W-P3-203・記録のみ・R2 と同じ） |
| 12 | `jin render <0.9 MB の loop n=3000> \| head -c 1`（EPIPE） | **1** | 1 行「標準出力に書けません（Broken pipe）」（F-S-P3-204 と同じ。researcher.jin 6 KB ではパイプバッファに収まり EPIPE にならない = rc 0・stderr 0 行で、これは正常） |
| 13 | `jin build R --out 既存（--force 無し）> /dev/full` | 1 | 拒否文言 1 行。拒否経路は stdout に依らない |
| 14 | `jin render P > a.svg` と `jin render P -o b.svg` | — | `cmp` 一致（6635 B）。R3 後もバイト同一 |

再レビュー変異（`mine_mutate.py`・隔離コピー・すべて復元後にバイト一致を assert。baseline = `packages/jin-cli/tests` + `tests/contract` **339 passed**）:

| 変異 | 回したテスト | 結果 | 判定 |
|---|---|---|---|
| **M1**: `build` の成功文言 `_echo_or_exit(...)` → `typer.echo(...)` | `packages/jin-cli/tests` + `tests/contract` 全部 | **339 passed・緑のまま** | **F-W-P3-301** |
| M2: `_fail_on_stdout` の `os.devnull` 差し替え 4 行を削除 | `-k full_stdout` | **2 failed**（`-o` 無し / 成功文言の両テスト） | RED。成功文言の経路も差し替えに依存している（exit 120 に化ける）ことの実証 |
| M3: `_echo_or_exit` の `except OSError` を `pass` に（握り潰し） | `-k full_stdout_on_the_success_message` | **1 failed** | RED（B-3 のテストは rc == 1 まで見る。握り潰すと終了時 flush で 120） |
| M4: `render` の `SymlinkWriteRefused` ハンドラから `raise typer.Exit(1)` を外す（成功文言へ落ちる） | `-k symlinked_output_is_refused` | **1 failed** | RED（fail-open は exit_code == 1 の assert が捕まえる） |
| M5: `sys.stdout is None` 分岐の文言を変える | `-k closed_stdout` | **1 failed** | RED（B-4 のテストは文言まで見る） |

`mutate_p3.py` 側の該当分（75/75 の中）: `CLI-success-message-raw-echo` RED（1 failed・render 側）/ `CLI-no-closed-stdout-branch` RED（1 failed。`if False:` にすると
`getattr(None, "buffer", None)` → `sys.stdout.write` の `AttributeError` トレースバックになり、文言と `Traceback` 不在の両 assert が落ちる）/
`CLI-symlink-message-without-path` RED（1 failed。`before` に直前のコメント行を含めて一層目だけを狙っている = R3.2 の 2 の記述どおり）/
`CLI-stdout-oserror-traceback` / `CLI-build-success-unsafe` / `CLI-follow-symlink-*` は `before` が現行コードに追従して SKIP 0（R3.2 の 4）。

## 前回 finding の判定（F-W-P3-201〜205）

| finding | 判定 | 根拠（実測） |
|---|---|---|
| F-W-P3-201 `-o` の成功文言が rich トレースバック + exit 120 | **defect-gone（render 側）・部分残存（build 側の固定）** | probe 1 / 2 とも **1 行 + exit 1・Traceback 0**。共通ヘルパは `_echo_or_exit`（`main.py:924`）→ `_fail_on_stdout`（`:938`）の 1 箇所で、`_write_stdout_bytes`（`:956`）も同じ `_fail_on_stdout` に集約された（指示「同型・1 箇所のヘルパで」を満たす）。呼び出し元は `:691`（build・`for path in written` の中）と `:1101`（render）の 2 つだけ。**ただし build 側にはテストも変異も無い**（M1 緑 → F-W-P3-301） |
| F-W-P3-202 `sys.stdout is None` 分岐にテスト無し | **defect-gone** | `test_a_closed_stdout_is_one_line_not_a_traceback`（`test_render.py:492-511`）が `preexec_fn=lambda: os.close(1)` で fd 1 を**インタプリタ起動前に**閉じる（R2 で指摘した唯一の作り方）。probe 5 と同じ 1 行 + exit 1 を assert。ハーネス `CLI-no-closed-stdout-branch`（`if False:`）RED・M5（文言）RED。`subprocess.run(stderr=PIPE, preexec_fn=…)` は `_posixsubprocess` が dup2 の後に `preexec_fn` を呼ぶので stderr のパイプは生きる（テストが通っていることが証拠） |
| F-W-P3-203 devnull のファイルオブジェクトが閉じられない | **記録のみ（妥当）** | probe 11 で `ResourceWarning` 1 行を再確認。指示書 C 節「記録のみで可」。終了直前の 1 fd |
| F-W-P3-204 期待 GREEN の印字理由 | **defect-gone** | `EXPECT_GREEN_REASON: dict[str, str]`（`mutate_p3.py:776`）に 2 種類の理由、`EXPECT_GREEN = set(EXPECT_GREEN_REASON)` で集合を畳む（片方だけに足す事故を防ぐ）。実行出力で `STAR-pre-fix-star-shape-stays GREEN (expected: 主張そのもの（星形テストは配置の恒等化では落ちない）)` と印字されることを実測 |
| F-W-P3-205 notes の `ADR-021` | **defect-gone** | `implementation-notes.md:1501` が「ADR-022（起票時は ADR-021）」。`implementation-plan.json` / `auto-decisions.json` / `docs/adr` に `ADR-021` の残存 0（grep） |

## 親の問い: B-3 の共通ヘルパは `jin check --json` / `jin dump` / `jin schema` の stdout を巻き込んでいないか

**巻き込んでいない。** `_echo_or_exit` / `_fail_on_stdout` / `_write_stdout_bytes` の呼び出し元は `build`（`:691`）と `render`（`:1089` / `:1101`）だけ（grep で `def` 以外の出現はこの 3 つ）。
`check` は `typer.echo`（`:495` / `:498`）、`dump` は `typer.echo(json.dumps(...))`（`:643`）、`schema` は `sys.stdout.write`（`:616`）のままで、
probe 8 の `> /dev/full` は Phase 1 と同じ rc 120（悪化も改善もしていない）、probe 8b の通常出力はバイト数・内容とも正常（`schema` はコミット済みスキーマと `cmp` 一致）。
`sys.stdout` の `os.devnull` 差し替えは `except OSError` の中でだけ起き、その直後に `typer.Exit(1)` を投げるので、他のコマンドの出力へ影響する経路は無い。

## fail-open（exit 0 になる誤り経路）の再確認

**0 件。** probe 10 の 4 通り（診断あり / 未定義 focus / 親ディレクトリ無し / 既存で `--force` 無し）はすべて非 0・Traceback 無し。
M3（成功文言の `OSError` を握り潰す）と M4（symlink ハンドラの `Exit(1)` を外して成功文言へ落とす）はどちらもテストが RED で、fail-open を作る変異は捕まる。
probe 3 / 4（fd 1 が閉じた状態で `-o` / `build`）の rc 0 は「成功文言が黙って捨てられる」だけで、成果物は書けていてバイト同一（probe 14）。
R2 でも同じ観測を記録済み。**欠陥ではない**が、`-o` 無しの render（rc 1）とは非対称なので下の「確認できた」に残す。

## Findings（修正が持ち込んだ・残した新規欠陥）

### F-W-P3-301 [confidence 70] B-3 の build 側（`jin build … > /dev/full`）にテストも変異も無い（挙動は正しい・固定だけが欠けている）
- 場所: `packages/jin-cli/src/jin_cli/main.py:690-691`（`for path in written: _echo_or_exit(...)`）。テスト: `packages/jin-cli/tests/test_build_run.py`（`/dev/full` を向けるテスト無し・grep 0）。
  変異: `mutate_p3.py:630` `CLI-success-message-raw-echo` は **render の `:1101` だけ**を置換する
- 内容: 指示書 B-3 は「`build` の成功文言も同じ（同型・1 箇所のヘルパで）。テスト: `/dev/full` に stdout を向けて exit 1」。ヘルパの共通化は実物どおり（probe 2 で rc 1・1 行）だが、
  build 側の `_echo_or_exit` を `typer.echo` に戻す **M1 が `packages/jin-cli/tests` + `tests/contract` 339 passed で緑のまま**。build の成功文言が exit 120 に退行しても気づかない。
  notes R3.1 B-3 行は固定テストとして render 側 1 本だけを挙げており、記録上も build 側の固定は主張していない（記録と実物の不一致ではないが、指示の半分が未固定）
- 変異検証: M1 GREEN（上表）。対照: render 側の `CLI-success-message-raw-echo` は RED
- 提案: `test_build_run.py` に `test_a_full_stdout_on_the_build_success_message_is_one_line_not_a_traceback`（`/dev/full`・`skipif` 付き・生成物 3 ファイルが出来ていることも見る）を 1 本、
  `mutate_p3.py` に `CLI-build-success-raw-echo`（`:691` の置換）を 1 件。どちらも既存の render 側の写しで足りる

### F-W-P3-302 [confidence 35] notes R3.3「`decision_record` は 22 件のまま」は実物 23 件と食い違う
- 場所: `implementation-notes.md:1733`（R3.3）。同じ数字が R2 側 `:1619` にもある。実物: `implementation-plan.json` の `decision_record` は **23 要素**（`json.load` で計測。origin/main 17 + P3 の 6 = ROUNDING / ACCENT-COLOR / OVERLAY-REFERENT / SVG-ROOT-CONTRACT / RENDER-ON-ERROR / LOOP-STAR-ORDER）
- 内容: 件数の不一致は確認できた。「バイト単位で不変」の主張は R2 時点のスナップショットが無いので**未検証**（偽とは言えない）。R3 の変更が `undecided[]` / `undecided_details[]` への `DP-REVIEW-JIN-P3-001` 追加だけであること自体は
  `undecided` の末尾 3 要素（`DP-REVIEW-JIN-P2-001` / `P2-002` / `P3-001`）と `undecided_details` の新規エントリで整合
- 提案: 記録のみ。数字を 23 に直す（あるいは親が R2 時点の値を確認して片方に揃える）

## 変異で緑のままだったテスト（偽 green の候補）

| 変異 | 回したテスト | 結果 | 対応 |
|---|---|---|---|
| M1: build の成功文言を生の `typer.echo` に | `packages/jin-cli/tests` + `tests/contract` | 339 passed | F-W-P3-301（挙動は正しい・固定が無い） |

赤くなった対照: M2 / M3 / M4 / M5・`mutate_p3.py` 73 RED + 2 期待 GREEN。

## 確認できた（finding にしない）

- probe 3 / 4: fd 1 が閉じた状態の `-o` / `build` は rc 0 で無言（click の `echo` は `sys.stdout is None` なら黙って戻る）。成果物は書けていてバイト同一。fail-open ではない。
  `-o` 無しの render が rc 1 なのと非対称だが、成果物が stdout の側だけが失敗として正しい。R2 と同じ観測
- `_echo_or_exit` は `build` の `for path in written` の中で呼ばれる。最初の 1 行で `OSError` になると残りのパスの文言は出ないが、生成物はすべて書けた後なので実害は無い（読解）
- `_fail_on_stdout` の文言 `exc.strerror or exc` は OS の文言で、`.jin` 由来の値は流れない
- R3 の 3 本の別プロセステストは `Path(sys.executable).parent / "jin"` で venv の `jin` を呼ぶ（R2 の `/dev/full` テストと同じ形）。隔離コピーで `PYTHONPATH` を前置すると子プロセスもコピーを読むことは、コピー上の M2〜M5 が RED になったことで実証

## 実装者の記録（notes / conformance / plan / layout.md）と実物の不一致

- **一致を確認**: R3.0 / R3.3 の数値（1201 passed・68 warnings・6 snapshots・75/75・SKIP 0・baseline 394・3 kept・Checked 76）/ R3.1 B-3（`_echo_or_exit` + `_fail_on_stdout`・render 側テスト名・変異名）/
  B-4（テスト名・`preexec_fn`・変異名）/ A-1（`main.py:1006` の文言・テストの `str(link) in` と `count == 1`・変異名）/ F-W-P3-204（`EXPECT_GREEN_REASON`）/ F-W-P3-205（ADR-022 表記）/
  A-3（`codegen.py:27,73` と `adk-mapping.md:124,168` が「`CLAUDE.md` / ADR-012」。`model.md §3.3` の残存は `layout.md:201` の「採番の規律ではない」という**否定文だけ**で、これは誤引用ではない）/
  B-1（`implementation-plan.json:1856` `undecided[]`・`:2383` `undecided_details[]` に `DP-REVIEW-JIN-P3-001`・`layout.md:215,281`・`decision-conformance.md:621`・`docs/pending-decisions.md:24`。コード差分無し）/
  B-2（`layout.md:268-270` の 3 段表 n<=31 / 32〜57 / n>=58 と `decision-conformance.md:612-613`。式 `2*0.55*sin(pi/n) - 0.06 >= 0.05` ⇔ n<=31、`2*0.55*sin(pi/n) <= 0.06` ⇔ n>=58 を手計算で確認）/
  R3.2 の 1（`main.py:56-60` のモジュール docstring が 4 + 1 の形）。
- **不一致**: F-W-P3-302（`decision_record` 22 ↔ 23）。

## R3.2（指示と違えた判断 6 件）の 1 行評価

1. **指示に無い変更 2 つ**（モジュール docstring の 4+1 化 / n=19,20 param + `FLOW-point-fallback-off`）: 妥当。前者は A-1 で触る段落の安全主張の整合、後者は「変異が緑ならテストを足す」の規律どおり。どちらも描画・CLI の挙動を変えない（snapshot 4 本不変・probe 14 バイト同一）。
2. **`CLI-symlink-message-without-path` が最初 GREEN（的が二層目）**: 妥当。`before` に直前コメント行を含めて一意化（`mutate_p3.py:618-628`）。ハーネスで RED を再実測。
3. **`FLOW-point-fallback-off` が最初 GREEN → n=19/20 を足した**: 妥当。ハーネスで 1 failed を再実測。境界 n=20 は `decision-conformance.md:611` と一致。
4. **B-3 で 4 本が SKIP → `before` を追従して SKIP 0**: 妥当。実行出力で SKIP 0・4 本とも RED。
5. **F-S-P3-203〜205 / F-W-P3-203 記録のみ**: 妥当（指示書 C 節どおり）。probe 6 / 7 / 11 / 12 で挙動が R2 と変わっていないことを再確認。
6. **`DP-REVIEW-JIN-P3-001` はコードを変えない**: 妥当。`layout.py` の差分は `_reference` 内コメント 1 行だけ（R3.1 C 表）で、描画は不変（snapshot 4 本・examples 2 本の SVG バイト同一）。判断期限が `undecided_details` の `note` に書かれている。

## 総合

前回 5 件: **defect-gone 4（201 render 側 / 202 / 204 / 205）・記録のみ 1（203・妥当）**。201 は build 側の固定が欠けて部分残存（F-W-P3-301・confidence 70）。
新規 2 件（confidence 90 以上 **0 件**）。ゲート全緑（308 / 174 / 1201 / 3 kept / 75-75 / SKIP 0 / 残骸 0 / コピー不変）・fail-open 0・共通ヘルパの巻き込み無し・CI 追加ステップ不要。
