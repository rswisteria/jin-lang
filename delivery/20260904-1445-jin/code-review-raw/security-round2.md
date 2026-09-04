# 再レビュー（修正ラウンド 2）— security

対象: 修正ラウンド 1 のレビュー（`security-round1.md`）で報告した新規欠陥 **N1 / N2** の defect-gone 確認と、
ラウンド 2 が新たに入れたセキュリティ欠陥の探索。
方針: 実装者の報告は未検証の主張として扱い、**PoC と変異注入**で確認した。
PoC は `/Users/toyota/.claude/jobs/8b3a6b62/tmp/r2/` 配下にのみ作成した。

## Summary

- **N1（`jin fmt` がパーミッションを 0600 に落とす / conf 97）: defect-gone**
  - 644 / 664 / 600 / 640 / 666 / 755 の 6 通りで整形後もモードが**完全一致**（実測）
  - 実装は `main.py:158` の `shutil.copymode(path, temporary)`（`os.replace` の直前）
  - **変異注入で検査が落ちることを確認**: `shutil.copymode` の 1 行を削除すると
    `test_fmt_preserves_the_file_mode[420/436/438]` の **3 ケースが FAILED**（`assert 384 == 436` など）。
    `test_fmt_does_not_widen_a_restrictive_mode`（0600）は変異後も緑だが、これは `mkstemp` が元から 0600 なので正しい挙動
- **N2（書けないディレクトリで未捕捉 `PermissionError` / conf 95）: defect-gone**
  - ディレクトリ RO + ファイル書込可 → **EXIT=0 / 整形成功 / 警告あり / Traceback 0 件 / 一時ファイル残骸なし**
  - ディレクトリ RO + ファイルも RO → **EXIT=1 / 診断 1 行 / Traceback 0 件 / 元ファイル無傷**
  - **変異注入で検査が落ちることを確認**: `os.access(path, os.W_OK)` の fail-closed ガードを削除すると
    `test_fmt_reports_a_diagnostic_when_neither_file_nor_directory_is_writable` が FAILED
    （`PermissionError(13, 'Permission denied') is None or ...`）
- **N2 のフォールバック設計への判定: 妥当。fail-closed へ倒す必要はない。ただし 2 行の追加ハードニングを推奨**
  - フォールバックが発火する構成（ディレクトリが書けない）では、**攻撃者もそのディレクトリを触れない**。
    symlink 差し替え・TOCTOU の窓は「ディレクトリへの書き込み権」を前提とするので、この構成では成立しない
  - ファイルも書けない場合は**書かずに診断 + EXIT=1** に倒れており、fail-closed は保たれている（実測）
  - 警告文は十分（原子性の喪失と「中断すると内容が壊れる可能性がある」という実際のリスクを名指ししている）
  - ただし **`_write_in_place` は `path.open("w")` で symlink を辿る**ことを直接実証した。
    フォールバックが「ディレクトリが書ける」構成で発火しうる経路が 1 つあり、そこだけ窓が開く（**R-1**・Low）
- **ラウンド 2 が新たに入れたセキュリティ欠陥: High / Medium は 0 件。Low 1 件 + Info 2 件**
  - **R-1【Low / conf 78】** フォールバック経路の symlink TOCTOU（sticky + 全書き込み可ディレクトリの構成でのみ成立）
  - **R-2【Info / conf 95】** `_write_canonical` の docstring がセキュリティ根拠を誤って `_collect` に帰している
  - **R-3【Info / conf 90】** `jin check` は symlink を辿るため、シンボリックリンク経由の外部ファイル片が診断に載りうる（読み取りのみ・ラウンド 2 由来ではない）
  - D-4 の拡張子検査（`_collect` / `dump` 双方）と `model.py` の文字種制約は**実装と文書が一致**しており、
    変異注入でどちらも赤くなることを確認した（下記 §3）
- **PoC 残骸**: リポジトリツリーへの追加は本ファイル 1 本のみ。変異注入は
  `/Users/toyota/.claude/jobs/8b3a6b62/tmp/r2/repo/` に複製したツリーで行い、リポジトリは一切触っていない。

```
$ git status --porcelain
 M delivery/20260904-1445-jin/auto-decisions.json
 M delivery/20260904-1445-jin/auto-decisions.md
 M delivery/20260904-1445-jin/design.yaml
 M delivery/20260904-1445-jin/implement-ledger.md
 M docs/pending-decisions.md
?? .github/
?? .gitignore
?? .python-version
?? CLAUDE.md
?? README.md
?? delivery/20260904-1445-jin/code-review-raw/
?? delivery/20260904-1445-jin/decision-conformance.md
?? delivery/20260904-1445-jin/fix-round-1-instructions.md
?? delivery/20260904-1445-jin/fix-round-1-mutations/
?? delivery/20260904-1445-jin/fix-round-2-instructions.md
?? delivery/20260904-1445-jin/implementation-notes.md
?? delivery/20260904-1445-jin/implementation-plan.json
?? delivery/20260904-1445-jin/replay-commands.md
?? delivery/20260904-1445-jin/version-matrix.md
?? docs/adr/ADR-012-DP-JIN-DIAGCODE-NUMBERING-01.md
?? docs/adr/ADR-013-DP-JIN-RENAME-SCOPE-01.md
?? docs/adr/ADR-014-DP-JIN-JIN050-LOOP-SCOPE-01.md
?? docs/spec/
?? examples/
?? packages/
?? pyproject.toml
?? schemas/
?? scripts/
?? tests/
?? uv.lock
```

`PWNED*` / `evil*.py` / `pwn.jin` / `esc*.jin` / `*.tmp` などの PoC 生成物は `find` で **0 件**。
`?? delivery/20260904-1445-jin/code-review-raw/` は security レビューの 3 本のレポートのみ。

**補助的な確認**: `uv run pytest` **491 passed**（jin-cli 単体 52 passed）。

---

## 1. N1 / N2 の判定

| ID | 判定 | 根拠（実行した PoC・変異注入とその結果） |
|---|---|---|
| **N1**<br>`jin fmt` がパーミッションを落とす | **defect-gone** | **挙動**: `chmod` で 6 通りのモードを付けた `.jin` を `jin fmt`:<br>`644→644` / `664→664` / `600→600` / `640→640` / `666→666` / `755→755` — **全一致**<br>**実装**: `main.py:158` の `shutil.copymode(path, temporary)` が `os.replace`（`:159`）の直前にある。docstring が「`mkstemp` は 0600 で作り `os.replace` は置き換える側のモードを持ち込む」という機序まで書いている<br>**変異注入**（tmp の複製ツリーで実施）: `shutil.copymode` の 1 行を削除 → `test_fmt_preserves_the_file_mode[420]` `[436]` `[438]` が **FAILED**（`assert 384 == 436` = 0o600 対 0o664）。**検査は存在するだけでなく実際に落ちる**<br>`test_fmt_does_not_widen_a_restrictive_mode`（0600）が変異後も緑なのは `mkstemp` が元から 0600 だからで、テストの欠陥ではない（このテストは「広げない」方向の網であり、狭める方向は上の 3 ケースが受け持つ） |
| **N2**<br>未捕捉 `PermissionError` | **defect-gone** | **挙動 1（ディレクトリ RO・ファイル書込可）**:<br>`EXIT=0` / `整形しました: ro/b.jin` / 警告「ディレクトリに書けないため原子的に差し替えできませんでした。直接書き込みました（中断すると内容が壊れる可能性があります）」/ **Traceback 0 件** / 内容は正準形になっている / 一時ファイルの残骸なし（`ls -A` で `b.jin` のみ）<br>→ ラウンド 1 で指摘した**機能後退も解消**されている<br>**挙動 2（ディレクトリ RO・ファイルも RO）**:<br>`EXIT=1` / `ro2/c.jin: 書き込めません（[Errno 13] Permission denied: ...）` / **Traceback 0 件** / **元ファイル無傷**<br>→ fail-closed<br>**実装**: `AtomicWriteUnavailable`（`main.py:114`）を導入し、`mkstemp` と `os.replace` / `copymode` の `PermissionError` だけを畳んでいる。`except BaseException` の掃除（`:163-165`）は残っている<br>**変異注入**: `_write_canonical` の `if not os.access(path, os.W_OK): raise`（`main.py:183-184`）を削除 → `test_fmt_reports_a_diagnostic_when_neither_file_nor_directory_is_writable` が **FAILED**（`PermissionError(13, 'Permission denied') is None or ...`）。fail-closed の網が実際に噛む |

---

## 2. N2 のフォールバック設計への判定

**結論: 現在の「ディレクトリが書けないがファイルは書けるなら、警告つきで直接書き込む」は妥当。
fail-closed（書けないなら書かない）に倒す必要はない。ただし `_write_in_place` に 2 行のハードニングを推奨する。**

### 妥当と判断する理由

1. **フォールバックが発火する構成では攻撃者も無力である。**
   symlink 差し替え・TOCTOU は「対象ディレクトリへの書き込み権」を前提とする。
   フォールバックの発火条件はまさに「そのディレクトリに書けない」なので、
   攻撃者も `.jin` を symlink に差し替えることができない。**この構成に限れば非原子的でも攻撃面は増えない**
2. **本当に危険な側は fail-closed のまま。** ファイルも書けないときは `raise` して診断 + `EXIT=1` に落ちる（実測）。
   「書けないのに書けたことにする」経路は無い
3. **原子性の喪失は攻撃者由来ではない。** 残るのはプロセス kill / 電源断 / ディスクフルで、
   これは修正ラウンド 1 より前の全経路が持っていたリスクと同じ大きさである。
   ここで「書かない」を選ぶと、読み取り専用ディレクトリ内の書き込み可能ファイルを整形できなくなり、
   ラウンド 1 で私自身が「機能後退」と指摘した状態に戻る

### 警告メッセージの十分性

十分である。実際の出力:

```
ro/b.jin: ディレクトリに書けないため原子的に差し替えできませんでした。直接書き込みました（中断すると内容が壊れる可能性があります）: [Errno 13] Permission denied: '.../ro/.b.jin.aeg1q09i.tmp'
```

- **何が起きたか**（原子的でない書き込みをした）と**残るリスク**（中断すると壊れる）を両方名指ししている
- stderr へ出ており、`_safe()` を通っている（制御文字は入らない）
- 軽微な観察 2 点（いずれも修正必須ではない）:
  - `fmt` は警告を出しても **EXIT=0**。終了コードだけを見る CI は「非原子的に書いた」ことに気づかない。
    ただし整形自体は成功しているので 0 は正しく、警告は stderr に必ず出るので隠蔽ではない
  - 末尾に既に消えた一時ファイルの絶対パスが載る。利用者自身のパスなので秘匿性の問題は無いが、
    読み手には少し紛らわしい

### symlink / TOCTOU の穴

```
R-1 【Low / confidence 78】フォールバック経路が symlink を辿る（TOCTOU の窓）
packages/jin-cli/src/jin_cli/main.py:122-129（_write_in_place）/ :247（is_symlink チェック）/ :183-185
_write_in_place は path.open("w") を使うので **symlink を辿って書き込む**。
PoC: 実行済み（直接検証）。proj/swapped.jin -> ../out/victim.txt を作り _write_in_place を直接呼ぶと
  victim.txt の中身: WRITTEN-THROUGH-SYMLINK
  swapped.jin はまだ symlink か: True
つまり防御は「fmt が事前に is_symlink() を見ている」ことだけに依存している（main.py:247）。
その判定と実際の書き込みの間には check_file / read_source / dumps が挟まり、TOCTOU の窓がある。

**通常の構成では実害なし**: 窓を突くには対象ディレクトリへの書き込み権が要り、
フォールバックはそのディレクトリに書けないときにしか発火しない。

**穴が残る 1 構成**（未実測・confidence 78 の理由）:
sticky ビット付きで誰でも書けるディレクトリ（/tmp 相当）に、他人所有だが group/world-writable な
.jin がある場合。mkstemp は成功するが shutil.copymode は所有者でないと EPERM になるため
AtomicWriteUnavailable へ落ち、os.access(W_OK) は真なので _write_in_place へ退避する。
ここは攻撃者もディレクトリに書けるので、is_symlink() と open("w") の間で差し替えが成立しうる。
別ユーザ所有のファイルを用意できなかったため実測はしていない。

修正（2 行・完全に閉じる）:
    fd = os.open(path, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW)
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle: ...
O_NOFOLLOW なら symlink だった時点で ELOOP で失敗し、既存の AtomicWriteUnavailable 経路
（診断 + EXIT=1）へ自然に落とせる。
```

```
R-2 【Info / confidence 95】_write_canonical の docstring がセキュリティ根拠を誤った場所に帰している
packages/jin-cli/src/jin_cli/main.py:176-178
docstring は「`os.access` はシンボリックリンクを辿るが、`fmt` に届く前に `_collect` が
シンボリックリンクを弾いている（security review S12）」と書くが、**`_collect`（main.py:56-80）に
symlink フィルタは無い**（grep で 0 ヒット）。実際のフィルタは `fmt` 本体（main.py:247）にある。
誤りの向きが危険側である: 「入口の _collect が sanitize してくれる」と信じた将来のリファクタが
fmt の is_symlink() を落としても、docstring だけを読む限り安全に見える。R-1 と組み合わさると穴になる。
修正: docstring の参照先を fmt 本体（main.py:247）へ直す 1 行。
PoC: なし（コードと grep で確認）。
```

```
R-3 【Info / confidence 90】jin check は symlink を辿るため外部ファイルの断片が診断に載りうる
packages/jin-cli/src/jin_cli/main.py:56-80（_collect はディレクトリ探索で symlink を除外しない）
packages/jin-core/src/jin_core/parser.py:149-157（_decode_scalar が text[:40] を診断に載せる）
ディレクトリ配下に `x.jin -> ~/.ssh/config` のような symlink があると、jin check <ディレクトリ> は
それを読んで JIN001 の診断にリテラルの先頭 40 文字を載せうる。読み取りのみで書き込みは無い（S12 で塞いだ）。
利用者が自分で指した木の中の話であり、ラウンド 2 が入れたものでもない。fmt 側と対称にするなら
_collect のディレクトリ探索でも symlink を除外する選択肢がある（check は読み取り専用なので必須ではない）。
PoC: なし（コード読解。S12 の PoC でディレクトリ探索が symlink を拾うことは確認済み）。
```

---

## 3. ラウンド 2 の新規変更に対する確認

### 3.1 D-4 の拡張子検査（`_collect` と `dump`）

- `_collect`（`main.py:56-80`）: 名指しで渡されたファイルの `suffix != ".jin"` を **EXIT=2** で拒否
- `dump`（`main.py:312` 付近）: `_collect` を通らないので同じ規則を再掲。`file.is_file() and file.suffix != ".jin"`
- **変異注入**: `dump` の拡張子検査を無効化 → `test_dump_rejects_a_non_jin_file` が **FAILED**（`assert 1 == 2`）
- セキュリティ観点の評価: これは**攻撃面を狭める方向**の変更である。`jin dump README.md` のような
  「Jin ファイルでないものを読んで内容片を診断に載せる」経路が 1 つ減った。新たな穴は作っていない
- 軽微な観察: `is_file()` は symlink を辿るので、`x.jin -> secret.txt` は拡張子検査を通過する（R-3 と同根）

### 3.2 `model.py` の文字種制約と `docs/spec/model.md` §3.6 の一致

**文書の表を実装で 1 行ずつ検証した**（報告を信じずに実行した）。

| §3.6 の主張 | 実装の確認結果 |
|---|---|
| 識別子（`root` / `name` / `core` / `ref` / `builtin` / `circle` / `state[].name` / `type` / `flow.steps[]` / `flow.exit.key` / `delegate[]` / `boundary.await[]` / `guards[].ref`）は制御文字を一切許さない | **一致**。`model.py:106-195` で全て `Ident` 型。ESC を各フィールドに入れて 7 通り試験し、すべて error（生の ESC バイトは段 1 の JIN001、`\u001b` エスケープ形は段 2 の JIN002。**どちらの書き方でも拒否される**） |
| 自由記述（`description` / `instruction.rune` / `flow.exit.equals` 文字列）は `\n` `\r` `\t` のみ許す | **一致**。`description` の改行 / `flow.exit.equals` の改行はいずれも診断ゼロ、`description` の `\u001b` は JIN002 |
| 最大長 識別子 128 / 自由記述 65536 / URL 2048 | **一致**（ラウンド 1 の再レビューで境界値を実測済み。`$schema` は `Url` 型で `model.py:196`） |
| 孤立サロゲート（U+D800〜U+DFFF）は受け付けない | **一致**（`_reject_bad_chars`。ラウンド 1 で確認） |

`docs/spec/model.md` §3.7（スキーマが表現しない制約）の主張も検証した:

| 主張 | 確認結果 |
|---|---|
| 同一オブジェクト内のキー重複 → JIN001（段 1） | **一致**（`{"root":"A","root":"B"}` で JIN001） |
| 入れ子の深さ上限 64 段 → JIN001（段 1） | **一致**（64 段は構文を通り、65 段で JIN001） |
| `max` / `exit` は `kind: loop` のときだけ → JIN002（段 2） | **一致**（`model.py:145-157` の `_max_and_exit_are_loop_only`） |

→ **「文書に書いてあるが実装されていない制約」は 1 件も無い。** §3.6 は
「上位要件書に規定が無い値であり人間の承認待ち（Q-JIN-IMPL-09）」と明記されており、
勝手に決めた値であることを隠していない点も適切である。

### 3.3 その他の回帰確認

- 全 **491 テスト pass**（ラウンド 1 の 442 から +49）
- `jin check examples` / `jin fmt --check examples` いずれも EXIT=0
- S12（symlink を追わない）の網が**変異で赤くなること**を確認: `fmt` の `is_symlink()` を無効化 →
  `test_fmt_does_not_follow_symlinks` が FAILED（`assert 'シンボリックリンク' in '整形しました: ...'`）
- N2 のフォールバックでも一時ファイルの残骸が出ないことを実測

---

## 4. 対象外として扱った項目

親の指示どおり、次は本レビューの判定対象から外した。

| 項目 | 状態 |
|---|---|
| `DP-JIN-RESOLVE-ISOLATION-01`（`--resolve` のファイル間汚染 / 別プロセス化） | 判断ポイントとして起票済み・auto-decider 待ち。Phase 4 着手前がデッドラインという線引きに異論なし |
| S3 の残存（最悪 8.4 秒） | 前回報告のとおり。Phase 4 の LSP に入る前に予算の再調整が要る |
| `os._exit(0)` | 前回の判定（fix-now 不要）を維持 |
