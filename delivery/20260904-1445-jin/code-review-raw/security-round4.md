# 再レビュー（修正ラウンド 4・最終）— security

対象: **T-1 / U-1 / 点 3 の訂正 / ruff** の defect-gone 確認、**変異ハーネスの偽 green** が
私自身の過去の結論に影響していないかの検証、ラウンド 4 の新規欠陥探索。
方針: 実装者の報告は未検証の主張として扱い、**キャッシュ無効化つきの変異ハーネスで 20 種の変異注入**と
**API / CLI 双方の PoC** で確認した。作業は `/Users/toyota/.claude/jobs/8b3a6b62/tmp/r4/` 配下のみ。

**検証対象のスナップショット**: `packages/jin-cli/src/jin_cli/main.py`
sha256 `50a4c21982db34546b48…`（内容は 19:57:47 以降変化なし。ポーリングで 30 秒以上の安定を確認してから複製）

## Summary

- **T-1（`PermissionError` 以外の `OSError` が未捕捉トレースバック）: defect-gone**
  - API PoC 4 種・CLI PoC 5 種・変異 5 種すべてで確認。`_classify_write_failure`（`main.py:163`）が
    型として閉じており、**退避可能なのは `PermissionError` のときだけ**という不変条件も機械で固定されている
- **U-1（`guard:` の緩いトークンが素通り）: defect-gone**
  - `guard: fmt -> os` / `guard: fmt -> path` はいずれも **`GuardTokenTooLoose` で赤**（前回は素通りしていた）
  - `_guard_satisfied` は AST どうしの突き合わせに加え、**裸の名前を主張として認めない**／
    **外側の属性参照の土台（`a.b.c` の `a.b`）を数えない**という 2 つの縛りを入れている。私の指摘より厳しい
- **点 3 の訂正: 実態と一致。しかも機械で固定されている**
  - `decision-conformance.md` §2.11.1 が「配置ではなく `Path.is_symlink` を使っていることが効いている
    （reviewer が実測で反証・4 failed）」と訂正。私の反証内容と一致する
  - `guard: _write_atomically -> Path(path).is_symlink` を追加し、変異 **B5(P3-islink)** で 3 件赤くなることを確認
- **ruff: 緑**（`ruff check` EXIT=0 / `ruff format --check` 40 files / PYI034 は解消）。
  `lint-imports` 3 kept / `jin check`・`jin fmt --check` EXIT=0
- **ハーネス偽 green の影響範囲: 私の過去の結論には影響しない（理由は §1）**
  - 機構そのものは**独立に再現した**（キャッシュ有効だと同一サイズ・同一秒の 3 版が全部 `XXXX`、無効だと `AAAA/BBBB/CCCC`）
  - 私が報告した**赤はすべて赤のまま**。偽 green は赤→緑にしか転ばないので、赤の結論は原理的に影響を受けない
  - 私が報告した**緑は 4 件（E-A / E-B / E-B2 / E-C）**で、うち E-A / E-C は今回キャッシュ無効化で再実測して緑を再確認、
    E-B / E-B2 は U-1 の修正によって現在は赤（＝当時の緑が本物だった証拠）
  - 抜き取り検証（R-1 系 5 / R-2 系 5 / T-1 系 5 / P3-islink）は**全件赤**を再確認した
- **ラウンド 4 が新たに入れたセキュリティ欠陥: High / Medium は 0 件。Low 1 件**
  - **V-1【Low / conf 92】** 退避路の書き込みが途中で失敗するとファイルが 0 バイトになるのに、
    出力が「書き込めません」「診断を先に直してください」で**内容が失われたことを伝えない**
- **PoC 残骸**: リポジトリツリーへの追加は本ファイル 1 本のみ。変異注入は `tmp/r4/` の複製ツリーで実施。

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
?? delivery/20260904-1445-jin/code-review-report.md
?? delivery/20260904-1445-jin/decision-conformance.md
?? delivery/20260904-1445-jin/fix-round-1-instructions.md
?? delivery/20260904-1445-jin/fix-round-1-mutations/
?? delivery/20260904-1445-jin/fix-round-2-instructions.md
?? delivery/20260904-1445-jin/implementation-notes.md
?? delivery/20260904-1445-jin/implementation-plan.json
?? delivery/20260904-1445-jin/phase2-handoff.md
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

**テスト件数の食い違い（記録）**: 親の報告は 505 だが、私の実測は 19:49 時点で 505、19:57 時点で **518**。
19:49〜19:59 のあいだにツリーが動いていた（`main.py` の mtime が観測時刻と同一だった）。
本レポートは 19:57:47 以降で安定した `50a4c219…` に対するもので、その状態で **518 passed**。

---

## 1. 変異ハーネスの偽 green — 私自身の検証への影響

### 1.1 機構を独立に再現した

`.pyc` の無効化判定は「元ファイルの mtime（秒）+ サイズ」なので、同一サイズの版が同じ秒に書かれると
2 本目以降が 1 本目のバイトコードで走る。手元で再現した:

```
# キャッシュ有効（既定）
f() = XXXX
f() = XXXX      ← 中身は YYYY に書き換えたのに古いバイトコードが走っている
f() = XXXX      ← 同上（ZZZZ）

# PYTHONDONTWRITEBYTECODE=1
f() = AAAA
f() = BBBB
f() = CCCC
```

**実在する機構である。** 実装者の報告と親の再現は正しい。

### 1.2 私の結論への影響: 無い

理由を 3 つに分けて示す。

**(a) 偽 green は赤→緑にしか転ばない。** 私が「この変異で赤くなった」と報告した結論は、
古いバイトコードで走ったとしても赤くはならない（古い＝無傷のコードなら緑になる）。
したがって私の**赤の報告はすべて原理的に安全**である。

**(b) 私が緑と報告したのは 4 件だけで、いずれも今回再確認した。**

| 私の緑の結論 | 今回（キャッシュ無効）の結果 | 判定 |
|---|---|---|
| E-A（`guard:` を書かず散文で嘘） | **D3-prose-lie: 79 passed（緑）** | 当時の緑は本物 |
| E-C（実在するが無関係な関数の名指し） | **D4-unrelated-function: 79 passed（緑）** | 当時の緑は本物 |
| E-B（`guard: fmt -> os`） | **D1: 赤（`GuardTokenTooLoose`）** | 当時は緑（＝U-1 の欠陥が実在した）。今は修正で赤 |
| E-B2（`guard: fmt -> path`） | **D2: 赤（同上）** | 同上 |

E-B / E-B2 が「当時は緑・今は赤」なのは、**私の指摘（U-1）を受けて実装者が塞いだから**である。
仮に当時の緑が偽 green だったなら、修正前から赤だったはずで、U-1 という指摘自体が成立しない。
現に実装者は `_guard_satisfied` を新設して塞いでおり、当時の緑が本物だったことの裏付けになっている。

**(c) 条件そのものにも当たっていない。** 私の変異はすべて `restore()`（原本の書き戻し）を挟んでおり、
各変異は直前の版とサイズが異なる（`| os.O_NOFOLLOW` の除去 -16 / `getattr` 化 +17 /
`if path.is_symlink():` → `if False:` -13 / `_write_in_place` → `_collect` -8 など）。
`.pyc` はサイズ差で無効化される。とはいえ**これは事後の推論なので、依拠せず全件を実測し直した**（§2）。

### 1.3 抜き取り検証（親からの依頼）

「全 80 件を修正版ハーネスで再実測し、過去に赤と報告した件はすべて赤を再確認した」という主張の裏を取った。
**依頼された 4 系統（R-1 系 5 / R-2 系 5 / T-1 系 5 / P3-islink）を私のハーネスで独立に流し、全件赤を確認した。**
私のハーネスは毎回 `__pycache__` を削除し、`PYTHONDONTWRITEBYTECODE=1` で走らせている。

---

## 2. 変異注入 20 種の結果（すべてキャッシュ無効化つき）

baseline: `79 passed`（`packages/jin-cli/tests`）

### R-1 系（5 件・全部赤）

| 変異 | 赤くなったテスト |
|---|---|
| **A1** `\| os.O_NOFOLLOW` を除去 | `test_write_in_place_refuses_a_symlink` / `..._on_the_fallback_path`（リンク先が書き換わった）/ `test_guard_claims_point_at_real_guards` / `test_guard_claim_check_looks_at_code_not_at_the_claim_itself` / `test_a_real_guard_is_accepted[_write_in_place-os.O_NOFOLLOW]` — **5 件** |
| **A2** `getattr(os, "O_NOFOLLOW_X", 0)` に握り潰す | **同じ 5 件** |
| **A3** `fmt` の事前 `is_symlink()` を無効化 | `test_fmt_does_not_follow_symlinks` / `test_guard_claims_point_at_real_guards` / `test_a_real_guard_is_accepted[fmt-path.is_symlink]` — **3 件** |
| **A4** `_write_atomically` の lstat 判定を削除 | `test_write_atomically_refuses_a_symlink` / guard 主張 2 件 — **3 件** |
| **A5** `ELOOP` 分岐を潰す（`if False:`） | `test_write_in_place_refuses_a_symlink` / `..._on_the_fallback_path` — **2 件** |

A5 は「`SymlinkWriteRefused` へ変換する分岐」そのものを殺す変異で、私が今回追加したもの。**これも赤くなる。**

### R-2 系（5 件・全部赤）

| 変異 | 赤くなったテスト |
|---|---|
| **B1** `_collect` に symlink フィルタを足す | `test_collect_does_not_filter_symlinks` |
| **B2** `guard:` の名指しを嘘にする | `test_guard_claims_point_at_real_guards` |
| **B3** docstring 剥がしを無効化 | `test_guard_claim_check_looks_at_code_not_at_the_claim_itself`（`docstring が落ちていない`） |
| **B4** `guard:` 行を全部消す | `test_guard_claims_point_at_real_guards`（`guard: の主張が少なすぎる`）— `MINIMUM_GUARD_CLAIMS` が効いている |
| **B5** `Path(path).is_symlink()` → `os.path.islink(path)`（**P3-islink**） | `test_fmt_does_not_write_through_a_symlink_without_the_upfront_guard`（`assert not True`）/ guard 主張 2 件 — **3 件** |

**B5 が点 3 の訂正の核心**である。`os.path.islink` に書き換えると monkeypatch が効かなくなり、
退避路のテストが手前で止まる（＝`O_NOFOLLOW` の変異を捕まえられなくなる）という私の指摘どおりの挙動が、
テストで赤として現れる。**理由づけの訂正が機械で固定されている。**

### T-1 系（5 件・全部赤）

| 変異 | 赤くなったテスト |
|---|---|
| **C1** `mkstemp` の `OSError` を素通しに戻す | `..._falls_back_to_in_place_write_in_a_read_only_directory` / `..._when_neither_file_nor_directory_is_writable` / `..._on_the_fallback_path` / `test_fmt_reports_a_diagnostic_when_mkstemp_fails[28/30/5]` — **6 件** |
| **C2** `os.replace` 側の `OSError` を素通しに戻す | `test_fmt_reports_a_diagnostic_when_the_file_disappears_before_the_replace` |
| **C3** `_write_in_place` の書き込み中 `OSError` ハンドラを削除 | `test_write_in_place_reports_a_diagnostic_when_the_write_itself_fails`（`OSError: [Errno 28]` が素で出る） |
| **C4** 何でも退避可能にする（`isinstance(exc, PermissionError)` → `True`） | `test_fmt_keeps_the_original_when_the_replace_fails` / `test_fmt_reports_a_diagnostic_when_mkstemp_fails[28/30/5]` / **`test_a_full_disk_does_not_fall_back_to_a_truncating_write`（容量不足なのに直接書き込みへ退避した）** / `..._when_the_file_disappears_before_the_replace` — **6 件** |
| **C5** `except BaseException` の一時ファイル後始末を削除 | `test_write_atomically_refuses_a_symlink` / `test_keyboard_interrupt_still_propagates_from_the_atomic_write`（`一時ファイルが残った`） |

**C4 が最も重要**である。実装者が新設した「退避可能なのは `PermissionError` のときだけ」という不変条件が、
`test_a_full_disk_does_not_fall_back_to_a_truncating_write` によって**名指しで固定されている**。
私が提案した `except OSError` への単純拡張だとこの不変条件を壊すので、実装者の設計のほうが正しい。

### U-1 系（4 件・2 赤 2 緑）

| 変異 | 結果 |
|---|---|
| **D1** `guard: fmt -> os` | **赤**（`GuardTokenTooLoose: guard: のトークン 'os' が裸の名前`） |
| **D2** `guard: fmt -> path` | **赤**（同上） |
| **D3** 散文の嘘（E-A） | 緑（**対処しない判断どおり**） |
| **D4** 無関係な関数の名指し（E-C） | 緑（**同上**） |

---

## 3. T-1 の defect-gone 確認（挙動）

### 3.1 API 層

```
=== 各失敗が WriteRefused 系に畳まれるか ===
  書き込み直前に消えた（_write_atomically）: WriteRefused -> gone.jin: 書き込む直前にファイルが消えました（No such file or directory）
  書き込み直前に消えた（_write_canonical）: WriteRefused -> 同上
=== 容量不足で「退避可能」にしていないか ===
  ENOSPC: WriteRefused / 退避可能か=False / 中身無傷=True
  メッセージ: ensp.jin: ディスクの空き容量がありません（No space left on device）
=== 表に無い errno は strerror をそのまま出す（捏造しない） ===
  errno=28: ディスクの空き容量がありません（No space left on device）
  errno=2:  書き込む直前にファイルが消えました（No such file or directory）
  errno=20: Not a directory        ← 表に無いので strerror のまま
  errno=99: Weird made up          ← 同上（言葉を作っていない）
=== KeyboardInterrupt ===
  正しく伝播 / 一時ファイルの残骸なし
```

前回（ラウンド 3）は `_write_canonical` / `_write_atomically` とも **`WriteRefused ではない FileNotFoundError`** だった。
**同型の欠陥（S5 → N2 → T-1）は型として閉じられている。**

### 3.2 CLI 層（回帰含む）

| ケース | 結果 |
|---|---|
| N2: ディレクトリ RO + ファイル書込可 | EXIT=0 / 整形成功 / 警告あり / **Traceback 0** |
| N2: 両方 RO | EXIT=1 / `ro2/b.jin: 書き込めません（Permission denied）` / **Traceback 0** / 元ファイル無傷 |
| N1: パーミッション保持 | `664 -> 664` |
| S12 / R-1: symlink の e2e | EXIT=0 /「シンボリックリンクなので整形しません」/ `victim=ORIGINAL` / symlink のまま |

### 3.3 新しい穴を作っていないか

- `fmt` の例外ハンドラは基底 `WriteRefused` を捕まえるので、`AtomicWriteUnavailable` /
  `SymlinkWriteRefused` / 基底のすべてが診断経路に乗る（実測で Traceback 0）
- 退避判定は `AtomicWriteUnavailable`（= `PermissionError` 由来）にしか反応しない。
  容量不足・消失・読み取り専用 FS では退避しない（C4 の変異で固定）
- `PermissionError` で退避したあと `_write_in_place` の `os.open` が EACCES で失敗しても、
  `O_TRUNC` は open が成功して初めて効くので**元ファイルは壊れない**（`test_fmt_keeps_the_original_when_the_replace_fails` が固定）
- `_write_in_place` は `O_CREAT` を持つので存在しないパスを作りうるが、`_write_canonical` が
  手前で `os.access(path, os.W_OK)` を見るため、消えたファイルに対して退避路へ入ることはない（CLI から到達不能）
- **ただし 1 件だけ伝達の穴がある（V-1）**

---

## 4. ラウンド 4 の新規欠陥

```
V-1 【Low / confidence 92】退避路の書き込みが途中で失敗するとファイルが 0 バイトになるが、
                            その事実が利用者に伝わらない（むしろ誤解させる文言になる）
packages/jin-cli/src/jin_cli/main.py:215-219（_write_in_place の書き込み中 OSError ハンドラ）
packages/jin-cli/src/jin_cli/main.py:391-398（fmt の except WriteRefused と要約行）

退避路（非原子的な直接書き込み）に入ったあと `handle.write` が失敗すると、`O_TRUNC` により
**元の内容は既に消えている**。実装者もそれを認識しており、docstring に
「ここまで来ると元の内容は `O_TRUNC` で既に消えているので、**必ず**利用者に知らせる」と書いてある。
しかし**実際に出る文言はそれを伝えていない**。

PoC: 実行済み（CLI 経由・決定的）。ディレクトリを 0o555 にして退避路へ入れ、
os.fdopen が返すハンドルの write を ENOSPC で失敗させる:

  exit: 1
  w/a.jin: 書き込めません（w/a.jin: ディスクの空き容量がありません（No space left on device））
  整形できませんでした（診断を先に直してください）: 1 件
  Traceback: False
  整形後のファイルの中身の長さ: 0 バイト   ← 元の内容は失われている

問題は 3 つ:
  1. 「書き込めません」は「何も書かれなかった」と読める。実際は**書き始めて壊れた**
  2. 要約行「整形できませんでした（診断を先に直してください）」は write 失敗には当てはまらない。
     利用者を「.jin の中身を直せばよい」と誤導する（直すべきはディスクであり、
     やるべきことは**バックアップからの復元**）
  3. パスが二重に出る（`w/a.jin: 書き込めません（w/a.jin: ...）`）— 表示上の瑕疵

**ラウンド 4 由来である**: このハンドラ自体が T-1 の修正で新設された。ラウンド 3 までは同じ状況で
未捕捉トレースバックになっており、少なくとも「ただ事ではない」ことは伝わっていた。
堅牢性は明確に上がったが、**伝達は静かで誤解を招く方向に一歩下がった**。

**Low とした理由**: 発火には「退避路に入る（ディレクトリが書けない）」かつ「書き込み中に失敗する
（容量不足 / I/O エラー）」の同時成立が要る。攻撃者が作れる状況ではない。
既存テスト `test_write_in_place_reports_a_diagnostic_when_the_write_itself_fails` は
例外型と errno の文言しか見ておらず、**「内容が失われたことを伝えるか」は固定していない**。

修正（文言のみ・2 行程度）:
  - `_write_in_place` の OSError ハンドラのメッセージに
    「原子的でない書き込みの途中で失敗したため、ファイルの内容が失われています。
      バックアップから復元してください」を足す
  - `fmt` の要約行を、診断由来の失敗と書き込み失敗で出し分ける
    （「診断を先に直してください」を書き込み失敗に付けない）
  - あわせてメッセージのパス二重出力を解消する
```

---

## 5. 対象外として扱った項目

| 項目 | 状態 |
|---|---|
| `DP-JIN-RESOLVE-ISOLATION-01`（`--resolve` の別プロセス化 / ファイル間汚染） | 判断待ち。Phase 4 着手前がデッドライン |
| `DP-REVIEW-JIN-001`（= R-3。`jin check` の symlink 追従） | fix-later として起票済み |
| `DP-REVIEW-JIN-008`（= S3 の残存・最悪 8.4 秒） | Phase 4 送り |
| `os._exit(0)` 残存 | fix-now 不要の判定を維持 |
| E-A / E-C（`guard:` 記法の残る抜け道） | 機械的に塞げない性質。対処不要の判定を維持 |

---

## 6. 結論

**security 観点から Phase 0+1 のコミットに賛成する。**

4 ラウンドを通じて報告した全件の内訳:

| 分類 | 件数 | 状態 |
|---|---|---|
| confidence 90 以上の初回指摘（S1〜S6, S8〜S14, S19） | 14 | **全件 defect-gone** |
| 修正が入れた新規欠陥（N1 / N2 / R-1 / R-2 / T-1 / U-1） | 6 | **全件 defect-gone** |
| 本ラウンドの新規（V-1） | 1 | Low・文言のみ・未修正 |
| fix-later / Phase 4 送り（起票済み） | 4 | 対象外 |

**V-1 はコミットの前提条件にしない。** 攻撃者が作れる状況ではなく、修正は文言だけで、
堅牢性そのものは T-1 の修正で明確に改善している。ただし
「壊れたことを黙っている」タイプなので、**Phase 2 に入る前に文言を直すことを勧める**。

最後に方法論について 1 点。今回の `.pyc` 偽 green は、**実装者が自分の検証機構の欠陥を自分で見つけて
報告した**ものである。これは私が本案件で繰り返し指摘してきた「検査が存在する ≠ 検査が落ちる」を、
検査そのものに適用した例にあたる。Phase 2 以降も、
**挙動テスト + 変異注入（キャッシュ無効化つき）+ 主張の機械固定**の 3 点セットを続けることを勧める。
