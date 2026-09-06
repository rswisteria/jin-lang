# Stage 5 再レビュー: security — Phase 3 (jin-render) 修正ラウンド 1

入力: 前回 finding `code-review-raw/security-p3.md`（F-S-P3-001〜013）、指示書 `phase3-fix-round-1-instructions.md`、
`implementation-notes.md` P3-R1（R1.1 / R1.2 / R1.6）、`decision-conformance.md` P3 行・§2.24.1a / §2.24.1b、
`design.yaml` の `DP-JIN-SVG-DETERMINISM-01` / `DP-COMMON-07` constraints。判断材料は差分コード・生成物・テスト・仕様と、
下記の隔離コピー上の実測だけ（実装者の報告は未検証の主張として扱った）。

## 実測した環境・コマンド（隔離コピーのパス・件数）

- 隔離コピー: `/home/wisteria/.claude/jobs/e2bcfe94/tmp/rereview-security/`（worktree を `cp -r`・`__pycache__` 削除・
  `PYTHONDONTWRITEBYTECODE=1`・`TMPDIR` は job tmp）。`PYTHONPATH` にコピーの `packages/*/src` を並べ、
  `jin_render` / `jin_cli` / `jin_core` / `jin_adk` の `__file__` がコピー側であることを起動時に印字して確認。
  **実ツリーは 1 バイトも変更していない**（`git status --short` の新規エントリは本ファイルのみ。` M` / `??` の他項目は
  実装者・他エージェントのもの）。
- baseline（コピー）: `packages/jin-render/tests` + `jin-cli/tests/test_render.py` + `tests/contract/test_render_contract.py` +
  `test_guard_claims.py` = 全緑（`mutate_p3.py` の baseline 表示で **296 passed**）。
- 実装者の変異スクリプトをコピー上で実行（`delivery/.../phase3-mutations/mutate_p3.py`、`ROOT` は自身の位置から解決するので
  コピーの木を変異する）: baseline green・**59/59 caught**・`CLI-follow-symlink-upfront-only` だけ宣言どおり GREEN。
- 追加変異 12 本（`/home/wisteria/.claude/jobs/e2bcfe94/tmp/sec2/mutate_mine.py`。復元後にバイト一致を assert）: 下の表。
- 悪性入力（すべて `/home/wisteria/.claude/jobs/e2bcfe94/tmp/sec2/`）: `make_traces.py`（33 本の JSONL）、`probe_cli.sh`（CLI 50 ケース）、
  `probe_misc.sh`（ref import・hardlink・EPIPE・umask 4 値・fifo・symlink 親・dangling）、`probe_lib.py`（ライブラリ経路: `brief` の再帰・
  `xml_chars` の保存性・`is_ancestor_or_same` の端・巨大 pointer のメモリ・20 万行）、`e2e_u2028.sh`（`core` に U+2028 を含む `.jin` →
  `jin run --model fake --trace` → `jin render --trace`）。
- 子プロセスがコピーを使うことの確認: `_write_stdout_bytes` の `buffer = None` 変異で `test_render_contract.py::
  test_stdout_is_utf8_even_when_the_locale_cannot_encode_the_rune` が RED になった（`JIN = Path(sys.executable).parent / "jin"` は
  worktree の venv だが、`child_env` が `PYTHONPATH` を前置するのでコピーの `jin_cli` が先に解決される）。

## 前回 finding の判定（F-S-P3-001〜013）

| finding | 判定 | 実測 |
|---|---|---|
| F-S-P3-001 巨大整数 / 深い入れ子でトレースバック | **defect-gone** | 5000 桁 seq → `:1: JSON として読めません（Exceeds the limit (4300 digits)…）` exit 2。10 万段 → `:1: JSON の入れ子が深すぎます` exit 2。4000 桁（`json.loads` は通る）→ `seq が 1..9223372036854775807 の外です: 999…（80 文字）…` exit 2。`2^63` 拒否・`2^63-1` 受理・`data-jin-seq` は最長 19 桁。変異 `valueerror-narrow`（`except json.JSONDecodeError` に狭める）RED・`TRACE-no-recursion-guard` RED |
| F-S-P3-002 pointer prefix の二次メモリ | **defect-gone** | ライブラリ経路 n=50 000 / 500 000 / 5 000 000 セグメント（10 MB の pointer）で time 0.001 s・maxrss 35→37→55 MB（前回 50 000 で 2.4 GB）。CLI 経路 1 MB pointer 0.82 s / 106 MB。`pointer_prefixes` は消滅（grep 0 件）。祖先一致は当たる（`/circles/0` が fired） |
| F-S-P3-003 `splitlines()` と writer の不整合 | **defect-gone（端到端で確認）** | `core` を `"gemini-2.5-flash<U+2028>x"` にした `.jin` → `jin check` error 0 → `jin run --model fake --trace` exit 0・11 行・raw U+2028 を含む行 1 → 同じファイルを `jin render --trace` **exit 0**（fired 5・点 11・`--upto 3` も exit 0）。単発の `output` U+2028 行も exit 0。CR のみ区切りは `Extra data` exit 2（受理しなくなった）。CRLF・`\r\r\n` は受理。変異 `TRACE-splitlines` RED |
| F-S-P3-004 umask 無視の 0644 | **defect-gone** | 実プロセスで umask 022 / 002 / 077 / 027 → `jin render -o` 644 / 644 / 600 / 640、`jin build` も同値。`--force` は既存 600 を保つ。変異 `CLI-ignore-umask` / `CLI-new-file-0600` RED。決定記録 §2.24.1a とコード一致 |
| F-S-P3-005 U+FFFE / U+FFFF で ill-formed | **defect-gone** | `xml_chars` が U+FFFE / U+FFFF / C0 / 孤立サロゲートを U+FFFD に置換。保存性: `\t\n\r`・U+0085・U+FDD0・U+FFFD・U+D7FF・U+E000・U+10FFFF・U+1FFFE・ZWJ 絵文字・CJK・DEL はそのまま、いずれも `ET.fromstring` で parse 可。変異 `ESC-xml-chars-passthrough` / `xml-drop-nonbmp` / `xml-keep-surrogates` RED。layout.md §3 に明記 |
| F-S-P3-006 `except UnicodeDecodeError` 枝が未固定 | **defect-gone** | 枝の削除変異 `UDE-branch-removed` → `test_a_trace_that_is_not_utf8_exits_two` RED（前回は 24 passed のまま） |
| F-S-P3-007 負の seq を受理 | **defect-gone** | `seq: -5` / `0` → exit 2。`2^63` 上限も同じ 1 条件。layout.md §7.5 に範囲と根拠。変異 `OVL-accept-seq-zero` RED |
| F-S-P3-008 `!r` の長さ無制限 | **defect-gone** | `seq: {"secret": "S"×200}` → 80 文字 + `…`。`repr` なので `'\x1b[31mRED\x07'` / `'a b'` はエスケープ表記で出る（`od -c` で raw ESC / U+2028 なし）。入れ子 990 / 3000 段の list seq でも `RecursionError` にならず 104 文字。変異 `brief-no-truncate` RED |
| F-S-P3-009 成功メッセージが `_safe` 無し | **defect-gone** | `-o` 名に ESC / U+2028 → stdout に raw バイトなし（`od -c`） |
| F-S-P3-010 stdout のエンコーディングで落ちる | **defect-gone** | `PYTHONIOENCODING=ascii jin render researcher.jin` → exit 0・5822 B・`-o` とバイト同一。変異 `CLI-stdout-locale` / `stdout-buffer-none` RED（別プロセスのテスト） |
| F-S-P3-011 全読み + `splitlines` の 2 重コピー | **部分残存（記録妥当）** | ストリーム読みに変わった。20 万行 3.0 s / 531 MB（前回 2.9 s / 512 MB。出力 29 MB が支配的）。ただし **1 行は丸ごと実体化**する: 20 MB の 1 行 → 0.86 s / 161 MB（約 8 倍）、`--trace /dev/zero` は 20 s で timeout（終わらない）。R1.2-6 が上限を置かない理由を明記しており、判断として妥当。残存は F-S-P3-102 に記録 |
| F-S-P3-012 親ディレクトリ不在の文言 | **defect-gone** | `-o nope/x.svg` → `出力先のディレクトリがありません: …/nope` exit 1・ディレクトリは作られない。変異 `CLI-create-parent` RED |
| F-S-P3-013 `exists()` の二重判定の窓 | **記録のみ・妥当**（文言に誤り→下の不一致 3） | 窓で通常ファイルが現れれば `--force` 無しでも `os.replace` で上書きされる（同一ユーザーのローカル競合のみ・境界越えではない）。hardlink の `-o`（入力の複製と同 inode）→ ディレクトリエントリだけ差し替わり複製側は無傷であることを実測 |

**確認できた防御（finding にしない）**: `jin render` は `ref` を import しない（マーカー方式: cwd と `PYTHONPATH` に `evil_mod.py`、
`render -o` でマーカー無し、positive control の `jin check --resolve` でマーカー生成）。悪性 rune の `<script` は出力 0 件。`-o` が
シンボリックリンク（実体あり / dangling）→ 拒否・リンク先は作られない。`-o` が入力そのもの → `--force` でも拒否。`-o /dev/null --force`
→ `Permission denied` exit 1（`mkstemp` が `/dev` に書けない）。`-o` の親がディレクトリへのシンボリックリンク → 通る（正当）。`--trace`
が dangling symlink / ディレクトリ → exit 2。`--focus` の ESC → stderr に raw ESC なし。EPIPE（29 MB を `| head -c 1`）→ click が
`errno.EPIPE` を捕まえて **exit 1・トレースバック無し**。`is_ancestor_or_same("/circles/1", "/circles/10/core")` は False、
`"/circles/1x"` False、`"/"` はどこにも当たらない、`""` は等価のときだけ True（`data-jin=""` の要素は無い・`pointer: ""` の行は何も強調しない）。
`guard:` 主張 7 本（`_write_svg` 1・`svg.py` 6）は `test_guard_claims.py` がコピー上で緑・実コードと一致。決定記録 P3 行
（`_new_file_mode` = `0o644 & ~umask`・`xml_chars`・キャッシュ無し・動的 import 無し）はコードと一致。

## Findings（修正が持ち込んだ・残した新規欠陥）

### F-S-P3-101 [confidence 70] `_write_svg` の docstring「事前 5 条件は文言のための早期判定であって防御ではない」は、入力 `.jin` 上書き拒否には当たらない（`guard:` 主張と実装の不一致）
- 場所: `packages/jin-cli/src/jin_cli/main.py:934-961`（`_write_svg` docstring と `path.resolve() == source.resolve()`）
- 内容: B-6 の修正で「シンボリックリンク / ディレクトリ / 親が無い / **入力そのもの** / 既存」の 5 条件を一括して
  「ここを消しても安全性は変わらず、変わるのはメッセージだけ」と書いた。前 4 つは実測どおり（消しても `mkstemp` / `os.replace` /
  `is_symlink` 二層目が fail-closed）だが、**入力 `.jin` の上書き拒否はこの 1 行だけが守っている**: `_write_atomically(allow_create=True)`
  は存在するファイルを `copymode` → `os.replace` で置き換えるので、この条件を消すと `-o <入力.jin> --force` が入力を SVG で潰す。
  実装者自身の変異 `CLI-overwrite-the-input`（この条件を `if False` に）が RED になることが、この条件が**実効防御**である証拠。
  データ消失の防御を「防御ではない」と記録すると、次に docstring を信じて整理した人が消す。
- 変異検証: `CLI-overwrite-the-input` RED（mutate_p3・コピー上で再実測）
- 提案: docstring を「4 条件は文言のため。**入力の上書き拒否だけは実効防御**（`_write_atomically` は既存ファイルを置き換える）」に分け、
  `guard: _write_svg -> source.resolve` を足して `test_guard_claims.py` で固定する

### F-S-P3-102 [confidence 45] `_read_trace_rows` は 1 行を丸ごと実体化し、行長に上限が無い（`/dev/zero` は終わらない）
- 場所: `packages/jin-cli/src/jin_cli/main.py:879-881`（`for number, raw in enumerate(handle, start=1)`）
- 内容: ストリーム読みで「行 1 本 + 受理 dict」が常駐（R1.1 A-1 / F-S-P3-011 の主張）は正しいが、その「行 1 本」に上限が無い。
  実測: 20 MB の 1 行（`output` に 2 千万文字）→ 0.86 s / maxrss 161 MB（行長の約 8 倍: decode バッファ + `raw` + `removesuffix` の
  コピー 2 回 + `json.loads` 結果）。`--trace /dev/zero`（改行が来ない）→ 20 s timeout・終了しない。fifo も同じ。
  R1.2-6 は「閾値の根拠が無いまま置かない（CLAUDE.md）」と理由を書いており、`--trace` は利用者自身が名指しするファイルなので判断は妥当。
  残存として記録する（Phase 6 のエディタが同じ reader を再利用するなら再評価）。
- 提案: 記録のみ。上限を置くなら「`jin run` が書く 1 行の上限（モデル出力長）」から根拠を導く

### F-S-P3-103 [confidence 40] `_write_stdout_bytes` が EPIPE 以外の `OSError` と `sys.stdout is None` でトレースバックになる
- 場所: `packages/jin-cli/src/jin_cli/main.py:919-931`
- 内容 / 再現: `jin render researcher.jin > /dev/full` → `buffer.flush()` の `OSError: [Errno 28] No space left on device` が素通しで
  typer のトレースバック・exit 120。`jin render researcher.jin >&-`（fd 1 が閉じている）→ Python が `sys.stdout = None` にするので
  `getattr(None, "buffer", None)` → `sys.stdout.write` で `AttributeError` トレースバック exit 1。どちらも fail-closed。
  **回帰ではない**（旧 `sys.stdout.write(svg)` も同じ経路で落ちた）。EPIPE は click が捕まえて exit 1（実測）。
  同じコマンドの `-o` 側は `_classify_write_failure` で一文にしているので規律が揃っていない。
- 提案: `except OSError as exc: typer.echo(_describe_write_failure(exc), err=True); raise typer.Exit(1)`。`sys.stdout is None` は
  「標準出力が閉じています」で exit 1

### F-S-P3-104 [confidence 35] `-o` が FIFO のとき `--force` で黙って通常ファイルに置き換わる（exit 0）
- 場所: `packages/jin-cli/src/jin_cli/main.py:949-960`（`is_symlink` / `is_dir` だけを見る）
- 内容 / 再現: `mkfifo out.svg; jin render x.jin -o out.svg --force` → `書き出しました` exit 0、`out.svg` は `-rw-r--r--` の通常ファイル。
  `os.replace` がディレクトリエントリを差し替えるので境界越えではないが、`--force` の意味（「既存ファイルを上書き」）を超えて
  特殊ファイルの種類が変わる。`fmt` の `_write_atomically` も同じ性質（`.jin` が FIFO の状況は想定外）。
- 提案: `path.exists() and not path.is_file()` を「通常ファイルではありません」で拒む（1 行）。優先度は低い

### F-S-P3-105 [confidence 30] `_new_file_mode` の `os.umask` 往復は復元を固定するテストが無い
- 場所: `packages/jin-cli/src/jin_cli/main.py:344-346`
- 内容: 復元行（`os.umask(mask)`）を消す変異が `test_render.py` 全体で GREEN。CLI は書き出し 1 回でプロセスが終わるので実害は無く、
  `os.umask` は例外を投げないので try/finally の要も無い。ただし `_write_atomically` をライブラリとして複数回呼ぶ将来（Phase 4 で
  `jin/save` が使うなら）umask 0 のまま以降のファイルが作られる。R1.6-3 の「往復の是非」への回答: 単スレッド CLI では妥当。
- 提案: `test_the_output_file_is_created_with_the_generated_file_mode` の末尾で `os.umask(mask) == mask`（呼び出し後に umask が
  変わっていない）を 1 行 assert する

### F-S-P3-106 [confidence 25] `--upto` の負数エラーが 4000 桁の指定値をそのまま stderr に出す
- 場所: `packages/jin-cli/src/jin_cli/main.py:999`
- 内容: `--upto -999…（4000 桁）` → 4 KB の 1 行。5000 桁は click の `int()` が先に拒む（exit 2・Usage 表示）。利用者自身の引数なので
  影響は表示だけ。`brief()` と同じ 80 文字切りで揃えられる。情報

## 変異で緑のままだったテスト（偽 green の候補）

| 変異（追加分・`mutate_mine.py`） | 対象 | 結果 | 評価 |
|---|---|---|---|
| `newline="\n"` を外す（universal newlines） | `test_render.py` 全体 | **GREEN** | `\r` のみ区切りのファイルが再び受理される（現状は `Extra data` exit 2）。writer は書かないので低。CR のみを拒む fixture が無い |
| `os.umask(mask)`（復元）を消す | `test_render.py` 全体 | **GREEN** | F-S-P3-105 |
| `SEQ_MAX = 2**63`（+1） | `test_overlay.py` + `test_render.py` `-k seq` | **GREEN** | テストが `SEQ_MAX` を記号で参照するので値が動いても追随する。layout.md §7.5 の「`2^63 - 1`」とコードを結ぶ検査が無い（仕様値の固定漏れ） |
| `parent.is_dir()` → `parent.exists()` | `test_render.py` 全体 | **GREEN** | 親が通常ファイルのとき `mkstemp` が `ENOTDIR` で拒む（fail-closed・文言のみ） |
| `len(candidate) < len(pointer)` を落とす | `test_overlay.py -k ancestor` | GREEN | 等価は先に `return True`、長い candidate は `startswith` が False なので**冗長な条件**。偽 green ではない |
| 実装者の 59 変異 | `mutate_p3.py` | 59/59 RED（1 本は宣言どおり GREEN） | 前回指摘の F-S-P3-006 に対応する `UDE-branch-removed` は mutate_p3 に無いが、私の変異で RED を確認 |

RED を確認した追加変異: `UDE-branch-removed` / `valueerror-narrow` / `stdout-buffer-none` / `xml-drop-nonbmp` / `xml-keep-surrogates` /
`brief-no-truncate` / `ancestor-empty-candidate`。

## 実装者の記録（notes / conformance / plan / layout.md）と実物の不一致

1. **`_write_svg` docstring（B-6）**「5 条件を消しても安全性は変わらない」 ↔ 入力上書き拒否は実効防御（F-S-P3-101。実装者自身の変異が RED）。
2. **R1.2-3**「`core` の U+2028 は `Ident` の検証を通してもトレースの `name` に載る経路が無い」 ↔ コピー上の端到端で `core` に U+2028 を
   含む `.jin` の `jin run --model fake --trace` が **raw U+2028 を含む行を 1 本書いた**（前回レビューと同じ再現）。結論（`output` に置いた
   テストで足りる・reader の修正は区切り文字全般に効く）は妥当だが、根拠の記述が事実と逆。同じ段落の「`--model fake` でも `name` は
   `.jin` の `core` そのもの」とも自己矛盾している。
3. **R1.2-9**「負けても起きるのは『`--force` 無しで上書き』ではなく `os.replace`」 ↔ 窓で**通常ファイル**が現れた場合は `os.replace` が
   それを置き換えるので「`--force` 無しで上書き」そのものが起きる（同一ユーザーのローカル競合・境界越えではない）。記録のみの判断は妥当、
   文言が不正確。
4. **R1.1 A-3 の固定テスト**「`test_a_huge_pointer_does_not_blow_up_memory_or_time`」 ↔ 指示書は「1 秒以内・メモリが膨らまない」を求めたが、
   テストは `time.monotonic()` だけを見る（メモリは未計測）。実測 maxrss は平坦（35→55 MB @ 10 MB pointer）なので記録のみ。
5. **layout.md §7.5「`1 <= seq <= 2^63 - 1`」** ↔ コードは `SEQ_MAX = 2**63 - 1` で一致するが、値を結ぶテストが無い（上の偽 green 表）。
6. decision-conformance §2.24.1a / §2.24.1b・design.yaml の `DP-JIN-SVG-DETERMINISM-01` / `DP-COMMON-07` constraints: 記載とコードの
   不一致なし（丸め 1 本 = `fmt_coord`・別プロセス 2 回・キャッシュ無し・`jin_render` に `open` / `Path` / 動的 import 無し）。

## R1.2（指示と違えた判断 9 件）の評価

1. `0o644 & ~umask`（`0o666` でなく）: **妥当**。umask 022 / 002 / 077 / 027 で `jin render -o` と `jin build` の実効モードが全部一致（実測）。
2. `sys.stdout.buffer` 書き出し（1 行 exit 1 で包まず）: **妥当**。`PYTHONIOENCODING=ascii` で exit 0・`-o` とバイト同一。ただし EPIPE 以外の
   `OSError` は未処理（F-S-P3-103・回帰ではない）。
3. 端到端を `core` でなく `output` に: **結論は妥当・根拠は誤り**（不一致 2）。
4. U+000B / U+000C を対象外: **妥当**。`json.dumps` は 0x20 未満を必ず `\u00XX` に逃がす。
5. `xml_chars` の新規に閉じた穴は U+FFFE / U+FFFF のみ: **妥当**。`jin_core.model._reject_bad_chars` が C0 / DEL / C1 / サロゲートを拒むことを
   コードで確認。置換は広すぎない（保存性の実測 11 種）。
6. `--trace` に上限を付けない: **妥当（残存を記録）**。F-S-P3-102。
7. `pointer_prefixes("/")` は関数ごと消滅: **妥当**（grep 0 件）。
8. `implementation-plan.json` の `$comment`: security の対象外（衝突回避の理由は筋が通る）。
9. F-S-P3-013 記録のみ: **妥当だが文言不正確**（不一致 3）。

## 総括

前回 13 件のうち **defect-gone 11・部分残存 1（F-S-P3-011・判断妥当）・記録のみ 1（F-S-P3-013・妥当）**。fail-open（exit 0 になる誤り経路）は
見つからなかった。新規は 6 件（confidence 90 以上は 0）で、修正に伴う唯一の実質的な問題は F-S-P3-101（防御を「防御ではない」と記録した
docstring / `guard:` の欠落）。
