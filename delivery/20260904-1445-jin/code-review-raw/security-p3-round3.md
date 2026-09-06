# Stage 5 最終確認: security — Phase 3 (jin-render) 修正ラウンド 3

レビュア: rereview-p3-r3-wiring-security（wiring と security を 1 本で担当・範囲限定）/ 2026-09-06。
入力: `code-review-raw/security-p3-round2.md`（F-S-P3-201〜205）/ `phase3-fix-round-3-instructions.md` / `implementation-notes.md` P3-R3 /
`decision-conformance.md` P3 行。環境・ゲート・プローブ・変異の実測値は `wiring-p3-round3.md` の「実測した環境・コマンド」節と共通
（同じ隔離コピー `/home/wisteria/.claude/jobs/e2bcfe94/tmp/rereview3-ws/tree/`・同じスクリプト）。ここでは security の判定だけを書く。
worktree に書いたのは wiring / security の round3 ファイル 2 つだけ。実装者の報告は未検証の主張として扱い、判断材料は差分コード・テスト・プローブ・変異の実測だけ。

## 実測した環境・コマンド（隔離コピーのパス・件数）

`wiring-p3-round3.md` と同じ: `UV_LOCKED=1 uv sync` クリーン / `lint-imports` 3 kept / `packages/jin-render/tests` 308 passed / `packages/jin-cli/tests` 174 passed /
全スイート（隔離コピー）1201 passed / `mutate_p3.py` 75/75 caught・SKIP 0・残骸 0・コピー不変 / `stdout_probe.sh` 14 通り / `mine_mutate.py` M1〜M5。
security の観点で追加した実測: probe 12 を **0.9 MB の SVG**（R2 security の `bign/flow-loop-3000-rich.jin`）で回し直して EPIPE を実際に起こした（researcher.jin 6 KB ではパイプバッファに収まり EPIPE にならない）。

## 前回 finding の判定（F-S-P3-201〜205）

| finding | 判定 | 実測 |
|---|---|---|
| F-S-P3-201 事前判定のシンボリックリンク拒否文言からパスが消えた | **defect-gone** | `main.py:1006` `raise SymlinkWriteRefused(f"シンボリックリンクなので書き込みを拒みました: {path}")`（二層目 `:420` と同じ `path: 理由` の形）。`render` 側（`:1093-1097`）は前置しないままなので、どちらの層が発火してもパスは **1 回**。probe 9: stderr「…拒みました: <link のフルパス>」・パス出現 1 回・リンク先無傷・rc 1。テスト `test_a_symlinked_output_is_refused`（`test_render.py:101-116`）は `str(link) in result.output` と `count(str(link)) == 1` を assert。ハーネス `CLI-symlink-message-without-path`（一層目だけを狙う。R3.2 の 2）RED。M4（ハンドラの `Exit(1)` を外す = 成功文言へ落ちる fail-open）RED。`fmt`（`:590`）/ ディレクトリ拒否 / 既存拒否と規律が揃った |
| F-S-P3-202 `sys.stdout is None` 分岐にテスト無し | **defect-gone** | `test_a_closed_stdout_is_one_line_not_a_traceback`（`preexec_fn=lambda: os.close(1)`・`skipif(not hasattr(os, "fork"))`）。ハーネス `CLI-no-closed-stdout-branch`（`if False:`）RED = R2 で実測した `AttributeError` トレースバック（26 行）への回帰を捕まえる。M5（文言変更）RED。probe 5: 1 行「標準出力が閉じています」rc 1 |
| F-S-P3-203 stdout と stderr が両方書けないと exit 120 | **記録のみ（妥当）** | probe 6 / 7 とも rc 120（R2 と同じ。成功文言の経路も同じ形）。非 0 で fail-open ではない。指示書 C 節「記録のみで可」。notes R3.2 の 5 に記載 |
| F-S-P3-204 EPIPE が「1 行 + exit 1」 | **記録のみ（妥当）** | 0.9 MB の SVG を `\| head -c 1` → stderr **1 行**「標準出力に書けません（Broken pipe）」rc **1**（R2 と同じ）。R3 の `_fail_on_stdout` への集約で挙動は変わっていない |
| F-S-P3-205 `guard: _write_svg -> _write_atomically(...)` は存在検査 | **記録のみ（妥当）** | 記法の性質（Phase 2 から）。R3 で `_write_svg` の書き込み経路は変わっていない（`:1017` の 1 呼び出し）。歯は R2 と同じ umask パラメータのテスト |

**確認できた防御（finding にしない）**:

- `_echo_or_exit`（`main.py:924`）/ `_fail_on_stdout`（`:938`）/ `_write_stdout_bytes`（`:956`）の呼び出し元は `build`（`:691`）と `render`（`:1089` / `:1101`）だけ。
  `sys.stdout` の `os.devnull` 差し替えは `except OSError` の中でだけ起き、直後に `typer.Exit(1)`。`jin check --json` / `jin dump` / `jin schema` は到達しない
  （probe 8 は Phase 1 と同じ rc 120・probe 8b の通常出力は正常で `schema` はコミット済みスキーマと `cmp` 一致）。**stderr の診断や他コマンドの stdout を黙らせる方向には効いていない**
- `_fail_on_stdout` の文言は `exc.strerror or exc`（OS の文言）。`.jin` 由来の値・ファイル名は流れない。成功文言は `_safe(str(out))` を通したまま（`CLI-build-success-unsafe` RED・75/75 の中）
- fail-open 0: probe 10 の 4 通り（診断あり / 未定義 focus / 親無し / 既存で `--force` 無し）は非 0・Traceback 無し。M3（成功文言の `OSError` を握り潰す）は rc 120 になりテスト RED、
  M4（symlink 拒否の後に `Exit(1)` を外す）はテスト RED。probe 3 / 4（fd 1 閉で `-o` / `build`）の rc 0 は成果物が書けた後に成功文言だけが捨てられる形で、成果物はバイト同一（probe 14）。欠陥ではない
- M2（devnull 差し替えを外す）は `-o` 無し / 成功文言の**両テスト**が RED（exit 120 へ化ける）。成功文言側も差し替えに依存していることの実証で、R2 の「干渉しない」判定も維持
- `jin_render` 側は R3 で `layout.py` のコメント 1 行と `svg.py` 無変更（`git diff` で確認）。`xml_chars` / `fmt_coord` / `attr_value` / `text_value` の 6 主張は R2 と同じ実コードに一致し、
  `functools` / `open` / `Path` / 動的 import は無い（DP-COMMON-07 の P3 行のまま）。snapshot 4 本・examples 2 本の SVG はバイト不変
- A-3 の `model.md §3.3` 誤引用: `packages/` と `docs/` で残存 0（`layout.md:201` の「採番の規律ではない」は否定文で誤引用ではない）
- `lint-imports` 3 kept: `jin_render` が `google-adk` に依存しない契約・任意コード実行が `jin_cli.resolver` / `jin_adk.runtime` に閉じる契約とも R3 で不変

## Findings（修正が持ち込んだ・残した新規欠陥）

security 観点の新規欠陥は **0 件**。関連する固定の欠けは wiring 側に 1 件:

- **F-W-P3-301**（`wiring-p3-round3.md`・confidence 70）: `jin build … > /dev/full` の成功文言は 1 行 + exit 1 に直っている（probe 2）が、build 側の `_echo_or_exit` を生の `typer.echo` に戻す
  変異 M1 が `packages/jin-cli/tests` + `tests/contract` 339 passed で緑のまま。security 的には fail-open ではなく（退行しても exit 120）情報漏えいでもないので、ここでは重複起票しない。

## 変異で緑のままだったテスト（偽 green の候補）

| 変異 | 対象 | 結果 | 評価 |
|---|---|---|---|
| M1: build の成功文言を生 `typer.echo` に | `packages/jin-cli/tests` + `tests/contract` | GREEN（339 passed） | F-W-P3-301（wiring）。退行しても exit 120 で fail-open にはならない |

RED を確認した追加変異: M2（devnull 差し替え無し → 2 failed）/ M3（`OSError` 握り潰し → 1 failed）/ M4（symlink 拒否後に成功文言へ落ちる → 1 failed）/ M5（閉じた stdout の文言 → 1 failed）。
`mutate_p3.py` の security 分（`CLI-umask-not-restored` / `CLI-stdout-oserror-traceback` / `CLI-upto-raw-value` / `CLI-overwrite-the-input` / `CLI-build-success-unsafe` / `CLI-symlink-message-without-path` /
`CLI-success-message-raw-echo` / `CLI-no-closed-stdout-branch`）はすべて RED。

## 実装者の記録（notes / conformance / plan / layout.md）と実物の不一致

1. R3.1 A-1「一層目の文言にパスを戻す・どちらの層でもパスは 1 回」↔ 実物一致（probe 9・テスト・`main.py:1006` / `:1093-1097`）。
2. R3.1 B-4「`preexec_fn` で fd 1 を閉じる」↔ 実物一致（`test_render.py:492-511`）。
3. R3.2 の 5「F-S-P3-203〜205 記録のみ」↔ 挙動は R2 から不変（probe 6 / 7 / 12）。妥当。
4. `decision-conformance.md` P3 行（`_new_file_mode` / `xml_chars` / キャッシュ無し / §2.24.1c の式と境界 n>=20・n>=32・n>=58 / `DP-REVIEW-JIN-P3-001` の未決記載）↔ コード・`layout.md:268-270` と一致。
5. `decision_record` 22 件 ↔ 23 件（wiring F-W-P3-302・記録のみ。security への影響無し）。

## R3.2（指示と違えた判断 6 件）の 1 行評価

1. 指示に無い変更 2 つ（モジュール docstring の 4+1 化 / n=19,20 param）: security 的に妥当。前者は**安全主張と実装の食い違い**を消す方向で、`test_guard_claims` は緑のまま（`guard:` 行は不変）。
2. `CLI-symlink-message-without-path` の的を一層目に直した: 妥当。二層目（`_write_atomically`）の文言は R2 から不変で、変異は一層目の退行だけを見る。
3. `FLOW-point-fallback-off` に n=19/20 を足した: security 対象外。RED を再実測。
4. B-3 で 4 本 SKIP → 追従: 妥当。`CLI-stdout-oserror-traceback`（`except OSError` を潰す）が RED のままであることを確認。
5. 記録のみ 4 件: 妥当（上表）。
6. `DP-REVIEW-JIN-P3-001` はコードを変えない: 妥当。紋の重なりは描画の重なりで境界越えではない（R2 と同じ判断）。

## 総括

前回 5 件: **defect-gone 2（201 / 202）・記録のみ 3（203 / 204 / 205・いずれも妥当）**。security 観点の新規欠陥 **0 件**（confidence 90 以上 0）。
fail-open 0・B-3 のヘルパは `check --json` / `dump` / `schema` を巻き込んでいない・`.jin` 由来の値が新しく出力へ流れる経路は無い。
