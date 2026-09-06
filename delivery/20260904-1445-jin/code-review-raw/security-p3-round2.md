# Stage 5 再レビュー: security — Phase 3 (jin-render) 修正ラウンド 2

入力: 前回 finding `code-review-raw/security-p3-round1.md`（F-S-P3-101〜106）、指示書 `phase3-fix-round-2-instructions.md`、
`implementation-notes.md` P3-R2（R2.1 / R2.2）、`decision-conformance.md` P3 行・§2.24.1c、`design.yaml` の
`DP-JIN-SVG-DETERMINISM-01` / `DP-COMMON-07` constraints。判断材料は差分コード・生成物・テスト・仕様と、下記の隔離コピー上の
実測だけ（実装者の報告は未検証の主張として扱った）。

## 実測した環境・コマンド（隔離コピーのパス・件数）

- 隔離コピー: `/home/wisteria/.claude/jobs/e2bcfe94/tmp/rereview2-security/`（worktree を `cp -r`・`.git` と `__pycache__` を削除・
  `PYTHONDONTWRITEBYTECODE=1`・`TMPDIR` は job tmp）。`PYTHONPATH` にコピーの `packages/*/src` を並べ、`jin_cli` / `jin_render` の
  `__file__` がコピー側であることを起動時に印字して確認。**実ツリーは 1 バイトも変更していない**（`git status --short` の新規エントリは
  本ファイルのみ。` M` / `??` の他項目は実装者・他エージェントのもの）。
- 子プロセス（`Path(sys.executable).parent / "jin"`）がコピーを読んでいる証拠: コピー上で `except OSError` を `except ZeroDivisionError`
  に変えると `test_a_full_stdout_is_one_line_not_a_traceback` が **RED**（exit 120 のトレースバック）。
- baseline（コピー）: `packages/jin-render/tests` + `jin-cli/tests/test_render.py` + `tests/contract/test_render_contract.py` +
  `test_guard_claims.py` = **383 passed**（実装者の R2.3「変異 baseline 383 passed」と一致）。
- 追加変異 **14 種**（テスト対象を変えた再実行を含めて 18 回。`/home/wisteria/.claude/jobs/e2bcfe94/tmp/sec3/{mutate_mine.py,
  guard_only.py,step3.py}`。復元後にバイト一致を assert）: 下の表。
- 例外: `probe_epipe.sh` / `probe_symlink.sh` / `bign_w.sh` の 3 本は、コピー上で変異を回している間の競合を避けるため
  **worktree の editable install に対して読み取りのみ**で実行した（コードはコピーとバイト同一・worktree は変更しない）。
- 悪性入力・環境（`/home/wisteria/.claude/jobs/e2bcfe94/tmp/sec3/`）: `probe_stdout.sh`（`/dev/full` / fd 1 閉 / stdout+stderr とも
  `/dev/full` / EPIPE 小出力 / `check --json > /dev/full` / `-o /dev/full` / `PYTHONIOENCODING=ascii`）、`probe_epipe.sh`（0.9 MB の
  SVG を `| head -c 1`・FIFO を `-o` に `--force` 無し）、`probe_symlink.sh`（`-o` がリンク / dangling / 既存・`fmt` との文言比較）、
  `bign.py`（`flow.steps` を n = 31 / 32 / 57 / 58 / 100 / 1000 / 3000 / 10000 個・全部別 circle・sequence と loop。`check_text` と
  `render` を分けて計測）。

## 前回 finding の判定（F-S-P3-101〜106）

| finding | 判定 | 実測 |
|---|---|---|
| F-S-P3-101 `_write_svg` docstring が入力上書き拒否を「防御ではない」と記録 | **defect-gone** | docstring が「文言のための 4 条件」と「実効防御 1 条件」に分かれ、`guard: _write_svg -> path.resolve()==source.resolve()` が付いた。`test_guard_claims` はコピー上で緑。実装者の変異 `CLI-overwrite-the-input`（`if False:`）→ **guard テスト RED**（`_write_svg に path.resolve()==source.resolve() が無い`）かつ `test_writing_over_the_input_jin_is_refused` RED。トークンを残して防御だけ殺す変異（`… == source.resolve() and False:`）→ guard テスト **GREEN**・render テスト **RED**（`assert 0 == 1`）。つまり歯は render テスト、`guard:` は所在の表示（記法の設計どおり）。「4 条件は文言のため」も再確認: `is_dir` 判定を消して `-o <dir> --force` → 二層目で **exit 1**（落ちたのは文言の assert だけ） |
| F-S-P3-102 1 行長の上限なし | **記録のみ・妥当**（R2.2-6） | 前回と同じ判断。閾値の根拠が無い値を置かない（CLAUDE.md）。変更なし |
| F-S-P3-103 `_write_stdout_bytes` の EPIPE 以外の `OSError` / `sys.stdout is None` | **defect-gone（残存 2 点は下の F-S-P3-202 / 203）** | `jin render researcher.jin > /dev/full` → stderr **ちょうど 1 行**「標準出力に書けません（No space left on device）」exit **1**。「Exception ignored」も出ない（観測上。`sys.__stdout__` 側の終了時 flush が何をしているかは実測していない）。`>&-`（fd 1 閉）→ 1 行「標準出力が閉じています」exit 1。`PYTHONIOENCODING=ascii > /dev/full` → 同じ 1 行 exit 1。0.9 MB の SVG を `\| head -c 1`（EPIPE）→ 1 行「標準出力に書けません（Broken pipe）」exit 1。`os.devnull` 差し替えを外す変異 → exit **120** で RED（実装者の主張どおり）。**差し替えの影響範囲**: `_write_stdout_bytes` の唯一の呼び出し元は `render` の `out is None` 経路で、差し替えの直後に `typer.Exit(1)` を投げる。stderr は触らない。`jin check --json` はこの関数を通らない（`check --json > /dev/full` は Phase 1 のままトレースバック exit 120・**今回の範囲外の既存挙動**）。fail-open にはならない |
| F-S-P3-104 FIFO + `--force` | **記録のみ・妥当**（R2.2-7） | `mkfifo out.svg; jin render x.jin -o out.svg`（`--force` 無し）→「既にあります」exit 1・FIFO は無傷。`--force` 明示時だけ差し替わる（前回実測）。境界越えではない |
| F-S-P3-105 umask 復元のテスト無し | **defect-gone** | `test_reading_the_umask_restores_it` が追加。復元行を消す変異 → **RED**（`assert 0 == 23`）かつ `test_guard_claims` も RED（トークン消失）。復元後に `os.umask(0)` を足す変異（トークンは残る）→ guard **GREEN**・umask テスト **RED**。歯がある |
| F-S-P3-106 `--upto` 負数の全桁表示 | **defect-gone** | `--upto -1…（1000 桁）` → stderr 300 文字未満（テスト）・`brief` を外す変異 → RED（1027 文字）。R2.2-10「4300 桁で `int()` が先に落ちる」は正しい |

**確認できた防御（finding にしない）**: `_new_file_mode` の `guard: -> os.umask(mask)` は実コードの 2 行目の呼び出しに一致し、
復元の挙動はテストが固定。`svg.py` の 6 主張（`fmt_coord -> format(value,_COORD_FORMAT)` / `float(text)==0.0` /
`attr_value` / `text_value` の `xml_chars` と `escape`）はいずれも関数本体の実コードに一致し、`xml_chars` は出力へ流れる唯一の
`.jin` 由来テキスト（rune）を通る実効ガード。`jin_render` に `functools` / `lru_cache` / モジュール可変状態 / `open` / `Path` /
動的 import は無い（DP-COMMON-07 の P3 行と一致）。座標の書き出しは `fmt_coord` のみ（`str(row.seq)` は検証済み整数、
`repr(value)` は `brief` のエラー文言用で SVG には流れない）。decision-conformance §2.24.1c の式・境界（n >= 20 で点）は
コードの `_flow_node_limit` / `_reference_size` と一致（`0.55*sin(pi/n) - 0.06 < 0.03` ⇔ n >= 20）。

## Findings（修正が持ち込んだ・残した新規欠陥）

### F-S-P3-201 [confidence 85] 事前判定のシンボリックリンク拒否メッセージからパスが消えた（F-V-P3-104 の修正の行き過ぎ）
- 場所: `packages/jin-cli/src/jin_cli/main.py:981`（`raise SymlinkWriteRefused("シンボリックリンクなので書き込みを拒みました")`）と
  `main.py:1068-1071`（`render` が `SymlinkWriteRefused` だけ `out` を前置しない）
- 内容 / 再現: `jin render pipeline.jin -o link.svg --force` → stderr は「シンボリックリンクなので書き込みを拒みました」**だけ**。
  どのファイルが拒まれたか分からない。F-V-P3-104 は「二層目（`_write_atomically`・文言にパスを含む）が発火したときパスが 2 回出る」
  だったが、修正は「`render` 側で前置しない」を**両方の層**に当てたので、通常経路（事前判定）ではパスが 0 回になった。
  同じコマンドの他の拒否（「既にあります」「ディレクトリがありません」）と `fmt` のリンク拒否（「…整形しません: <path>」）はパスを
  出しており、規律が揃っていない。複数ファイルをスクリプトで回す利用者は失敗したファイルを特定できない。
- 変異検証: `test_a_symlinked_output_is_refused` は `"シンボリックリンク" in result.output` しか見ないので緑のまま（偽 green）
- 提案: 事前判定の文言にパスを入れる（`f"シンボリックリンクなので書き込みを拒みました: {path}"`）か、`render` 側で
  「文言にパスが無いときだけ前置」にする。テストに `str(link) in result.output` を 1 行足す

### F-S-P3-202 [confidence 40] `sys.stdout is None`（fd 1 が閉じている）の枝を固定するテストが無い
- 場所: `packages/jin-cli/src/jin_cli/main.py:928-931`
- 内容: 枝を丸ごと消す変異が `test_render.py` 全体で **GREEN**。消した状態で `jin render x.jin >&-` を実測すると
  `AttributeError: 'NoneType' object has no attribute 'write'` の typer トレースバック（26 行）exit 1。fail-closed なので実害は無いが、
  F-S-P3-103 の半分（「1 行 exit 1」）が回帰しても気づかない。
- 提案: `/dev/full` のテストと同じ別プロセス方式で `preexec_fn=lambda: os.close(1)`（または `stdout=None` で fd を閉じた `Popen`）→
  「標準出力が閉じています」1 行・exit 1 を assert

### F-S-P3-203 [confidence 30] stdout と stderr が両方書けないと exit 1 が 120 になる
- 場所: `packages/jin-cli/src/jin_cli/main.py:938-949`
- 内容 / 再現: `jin render researcher.jin > /dev/full 2> /dev/full` → exit **120**。stderr への `typer.echo` が `OSError` で失敗し
  握り潰されるのは意図どおり。120 はインタプリタ終了時の標準ストリーム flush 失敗のコードなので、stderr 側の flush が
  再失敗していると考えられる（観測は exit 120 のみ・機構は未実測）。非 0 なので fail-open ではない。「1 行 exit 1」の主張が成り立たない状況が 1 つ残る。記録のみで足りる
- 提案: 記録のみ。揃えるなら stderr が書けなかったときも `sys.stderr` を `os.devnull` に差し替える（1 行）

### F-S-P3-204 [confidence 25] EPIPE の挙動が「黙って exit 1」から「1 行 + exit 1」に変わった
- 場所: `packages/jin-cli/src/jin_cli/main.py:938`
- 内容: 前回は click が `errno.EPIPE` を捕まえて無言で exit 1 だった。今は `except OSError` が先に捕まえるので
  `jin render big.jin | head -c 1` が stderr に「標準出力に書けません（Broken pipe）」を出す。`-o` 側の規律と揃っており、
  非 0 のままなので欠陥ではない。パイプで途中まで読む用途（`| head`）ではノイズになる。情報として記録
- 提案: 記録のみ。抑えたいなら `exc.errno == errno.EPIPE` のときだけ文言を省く

### F-S-P3-205 [confidence 30] `guard: _write_svg -> _write_atomically(path,text,allow_create=True)` は到達不能コードでも満たされる（記法の限界の確認）
- 場所: `packages/jin-cli/src/jin_cli/main.py:978` と `tests/contract/test_guard_claims.py::_guard_satisfied`
- 内容: `_write_svg` の末尾を `path.write_text(...)` + `return` にして元の呼び出しを**到達不能のまま残す**変異 → `test_guard_claims`
  は **GREEN**（存在検査なので設計どおり）。歯は `test_the_output_file_is_created_with_the_generated_file_mode[2]`（umask 0o002 で
  `write_text` が 0o664 になる）が担い **RED**。ただし「tmp + `os.replace` で原子的に書く」こと自体を見るテストは無く、
  umask のパラメータが偶然捕まえている。Phase 2 から続く記法の性質で新規欠陥ではない
- 提案: 記録のみ。`_write_svg` の書き込み経路を固定するなら `monkeypatch.setattr(main, "_write_atomically", ...)` で
  呼ばれることを直接 assert する 1 本

### B-1（極端な n）— finding にしない
- `render` は n に線形: n = 3000 → 0.04 s（loop・SVG 0.9 MB）、n = 10000 → **0.15 s**（loop・SVG 3.0 MB）。maxrss 306 MB は
  `jin_core.check_text` 側（loop n = 10000 で **17.75 s**・sequence 8.79 s。`semantic.py:387-392` の `steps.index` などで概ね二乗）。
  これは Phase 1 の性質で今回の差分ではない（事実として記す）。`star_step(n)` の `range(1, n)` 走査も n = 10000 で問題無し。
- 弦の本数: sequence n = 31 → 30 本、**n = 32 → 31 本**、n = 57 → 56 本、**n = 58 → 0 本**、n = 100 → 0 本。loop は n = 100 /
  10000 でも全本描かれる（星形の弦は隣接より長い）。layout.md §6「n >= 32 では弦がまた消えうる」は「消えうる」なので偽ではないが、
  実際に消える境界は `1.1 * sin(pi/n) <= 0.06` ⇔ **n >= 58** で、31 という数字は「本体 ≥ 矢じり」の境界（下の不一致 2）

## 変異で緑のままだったテスト（偽 green の候補）

| 変異（追加分） | 対象 | 結果 | 評価 |
|---|---|---|---|
| `sys.stdout is None` の枝を削除 | `test_render.py` 全体 | **GREEN** | F-S-P3-202（fail-closed だがトレースバック） |
| `SymlinkWriteRefused` 事前判定の文言にパスが無い（現状） | `test_a_symlinked_output_is_refused` | GREEN（現状で通る） | F-S-P3-201。部分文字列 assert だけ |
| `_write_atomically` 呼び出しを到達不能にして `write_text` | `test_guard_claims` | **GREEN**（render テストは RED） | F-S-P3-205。記法の限界 |
| `path.resolve() == source.resolve() and False` | `test_guard_claims` | **GREEN**（render テストは RED） | 設計どおり。歯は render テスト |
| 復元後に `os.umask(0)` を追加 | `test_guard_claims` | **GREEN**（umask テストは RED） | 設計どおり |

RED を確認した追加変異: `stdout-oserror-narrow` / `stdout-no-devnull-swap`（exit 120）/ `overwrite-input-token-kept` /
`overwrite-input-if-False`（guard も RED）/ `umask-not-restored`（guard も RED）/ `umask-token-kept-but-broken` /
`no-is-dir-precheck`（文言のみ・exit 1 は保たれる）/ `flow-scale-fixed` / `flow-no-point-floor` / `flow-shrink-frame-only` /
`upto-raw` / `write_text-bypass`。

## 実装者の記録（notes / conformance / plan / layout.md）と実物の不一致

1. **R2.1 C「F-V-P3-104: 競合時にパスが 2 回出るのをやめた」** ↔ 通常経路（事前判定）でパスが **0 回**になった（F-S-P3-201）。
2. **layout.md §6「点でも弦の本体が矢じり以上に保てるのは n <= 31 まで … n >= 32 では弦がまた消えうる」** ↔ 弦そのものが消えるのは
   sequence で **n >= 58**（`_arrow_d` は `length <= gap_start + gap_end` でしか `None` を返さず、矢じり長は条件に無い）。32〜57 では
   弦は描かれるが本体が矢じりより短い。「消えうる」は偽ではないが、境界の数字が別の条件のもの。loop は消えない。1 文の訂正で足りる。
3. **R2.1 C「F-S-P3-103 … 1 行 + exit 1」** ↔ stdout と stderr が両方書けない場合だけ exit 120（F-S-P3-203）。主張の範囲外の状況で、記録のみ。
4. decision-conformance P3 行（`_new_file_mode` = `0o644 & ~umask` / `xml_chars` / キャッシュ無し / §2.24.1c の式と n >= 20）・
   design.yaml の `DP-JIN-SVG-DETERMINISM-01` / `DP-COMMON-07` constraints: 記載とコードの不一致なし。
5. R2.0「C 節 20 項目のうち 15 を直し 5 を記録のみ」: security 分（101 / 103 / 105 / 106 = 直した、102 / 104 = 記録のみ）は実物と一致。

## R2.2（指示と違えた判断 / 直さなかったもの 12 件）の評価

1. Phase 2 に残る `model.md §3.3` 誤引用 3 箇所を触らない: security 対象外。範囲を広げない判断は筋が通る（Phase 4 前に親が判断）。
2. `FLOW-no-node-limit` が最初 GREEN → テストを足した: **妥当**。半径を決める場所が 1 本（`_reference_size`）になったことを実測。
3. 道具環の紋（summon）に縮小を適用しない: **妥当**（弦が無い）。`tools` 12 個での紋の重なりは描画の重なりであり境界越えではない。別件。
4. n >= 32 で弦が消えうるのを仕様として許容: 判断は妥当だが**数字が違う**（実際に消えるのは sequence n >= 58・不一致 2）。
   幾何の限界であることと診断コードを増やさないことは CLAUDE.md と整合。
5. F-C-P3-103（Unicode 空白だけの行）記録のみ: security 的には受理側が広い方向で fail-open ではない。妥当。
6. F-S-P3-102 記録のみ: **妥当**（前回と同じ）。
7. F-S-P3-104 記録のみ: **妥当**。`--force` 無しでは拒むことを実測。
8. F-W-P3-103（tests の動的 import は網の外）記録のみ: **妥当**。契約の対象は `src/`。
9. F-V-P3-104 にテスト無し・読解で確認: 競合窓の再現不能は正しいが、**読解で見落とした副作用**が F-S-P3-201（通常経路でパスが消える）。
   既存テストが部分文字列 assert なので緑のまま。
10. `--upto` は 4300 桁未満しか届かない: **正しい**（`int()` の `ValueError` → typer の Invalid value・exit 2）。
11. 記録のみ 5 件の数え方: 一致。
12. `EXPECT_GREEN` 2 本目: GREEN を主張として使う規律の緩み。correctness の論点なので 1 行だけ: 「GREEN が主張そのもの」の説明は
    エントリのコメントにあり、`CLI-follow-symlink-upfront-only` と同型。

## 実装者の変異ハーネス（`mutate_p3.py`・コピー上で再実行）

`ROOT` は自身の位置から解決するのでコピーの木を変異する（起動時の `jin_render.__file__` 印字で確認）。結果: baseline green
（383 passed）・**70/70 caught**（RED expected 68 + GREEN expected 2 = `CLI-follow-symlink-upfront-only` /
`STAR-pre-fix-star-shape-stays`）。R2.3 の記載と一致。security 分の新規 5 本（`CLI-umask-not-restored` /
`CLI-stdout-oserror-traceback` / `CLI-upto-raw-value` / `CLI-overwrite-the-input` / `CLI-build-success-unsafe`）はいずれも RED。

## 総括

前回 6 件のうち **defect-gone 4（101 / 103 / 105 / 106）・記録のみ 2（102 / 104・いずれも妥当）**。F-S-P3-103 の `os.devnull`
差し替えは `render` の stdout 経路の末尾（直後に exit 1）にだけ効き、stderr の診断や `jin check --json` を黙らせる方向には
効いていない。fail-open（exit 0 になる誤り経路）は見つからなかった。新規は 5 件（confidence 90 以上は 0）で、修正が持ち込んだ
実質的な問題は F-S-P3-201（事前判定のリンク拒否からパスが消えた）だけ。
