# 再レビュー（修正ラウンド 3）— security

対象: 修正ラウンド 2 のレビュー（`security-round2.md`）で報告した **R-1 / R-2** の defect-gone 確認、
親から提示された 5 点の妥当性判定、ラウンド 3 の新規欠陥探索。
方針: 実装者の報告は未検証の主張として扱い、**PoC と 6 種の変異注入**で確認した。
PoC と変異注入は `/Users/toyota/.claude/jobs/8b3a6b62/tmp/r3/` 配下にのみ作成した。

**検証対象のスナップショット**: `packages/jin-cli/src/jin_cli/main.py`
sha256 `a2470e024b9d7040fa07edd7e859a1554627e29e83c8acfc3fe94151ab38a245`
（検証開始時と終了時の両方で実ツリーと一致することを確認済み。→ §5 の注意も参照）

## Summary

- **R-1（フォールバック経路の symlink TOCTOU / conf 78）: defect-gone**
  - `_write_in_place`（`main.py:165`）が `os.open(path, O_WRONLY|O_TRUNC|O_CREAT|os.O_NOFOLLOW, 0o666)` になり、
    `ELOOP` を `SymlinkWriteRefused` に変換している。**`getattr` による握り潰しは無い**（実コードを確認）
  - ラウンド 2 の PoC（`swapped.jin -> ../out/victim.txt` に `_write_in_place` を直接呼ぶ）を再実行 →
    **`SymlinkWriteRefused` で拒否 / `victim.txt` は `ORIGINAL` のまま / `swapped.jin` は symlink のまま**
  - **変異注入 6 種すべてが名指しで赤くなることを確認**（下記）
- **R-2（安全宣言が実装と乖離）: defect-gone。しかも再発防止まで機械化されている**
  - `_write_canonical` の docstring が訂正され、防御の本体が下位 2 つであることを明記
  - `test_collect_does_not_filter_symlinks` が「`_collect` にガードが無い」ことを**逆向きに固定**
  - `guard: <関数名> -> <トークン>` 記法 + `test_guard_claims_point_at_real_guards` が
    **AST から docstring を外した実コード**に対して主張を検証する。
    さらに `test_guard_claim_check_looks_at_code_not_at_the_claim_itself` が
    「主張の文言そのものを見て通ってしまう」実装ミスを固定している
- **親提示の 5 点への判定**: 4 点は妥当。**1 点（点 3 の理由づけ）は再現しなかった**（結論は同じ・§3 を参照）
- **`guard:` 記法（親からの追加依頼）の判定: 妥当。§2-bis に詳述**
  - (1) 嘘を捕まえる。`ast.unparse` の docstring 剥がしを無効化した変異 **E-D** で 2 本とも赤くなる
  - (2) 抜け道は 3 つ在る（**E-A** 散文の嘘 / **E-B** 緩いトークン / **E-C** 無関係な関数の名指し）が、
    いずれも**実際の防御は無効化しない**。緩和策の強度の上限であって欠陥ではない。E-B だけは 1 行で塞げる（U-1）
  - (3) 2 案目（実装依存の主張を消す）を採らなかった理由は妥当。情報を残すことと腐りを機械で検出することが
    セットになっているので筋が通っている
- **ラウンド 3 が新たに入れたセキュリティ欠陥: High / Medium は 0 件。Low 1 件 + Info 1 件**
  - **T-1【Low / conf 90】** `_write_atomically` / `_write_canonical` が `PermissionError` **以外**の
    `OSError`（`FileNotFoundError` / `ENOSPC` など）を素で外へ投げ、`fmt` は `WriteRefused` しか
    捕まえないため未捕捉トレースバックになる（S5 / N2 と同じ欠陥型の 3 度目の出現）
  - **U-1【Info / conf 95】** `guard:` 検査が素の部分文字列一致なので、`os` / `path` のような
    緩いトークンで通る（セキュリティ欠陥ではない。AST 照合にすれば 1 行相当で塞げる）
- **PoC 残骸**: リポジトリツリーへの追加は本ファイル 1 本のみ。変異注入は
  `/Users/toyota/.claude/jobs/8b3a6b62/tmp/r3/snap/` の複製ツリーで行い、実ツリーは一切触っていない
  （終了時のハッシュ一致で確認）。

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

`PWNED*` / `evil*.py` / `pwn.jin` / `esc*.jin` / `swapped.jin` / `victim.txt` / `*.tmp` は `find` で **0 件**。

**補助的な確認**: `uv run pytest` **498 passed**（jin-cli 単体 59 passed）/ `ruff check` exit 0 /
`lint-imports` exit 0（3 contracts kept）。

---

## 1. R-1 / R-2 の判定

| ID | 判定 | 根拠 |
|---|---|---|
| **R-1**<br>フォールバック経路の symlink TOCTOU | **defect-gone** | **挙動**: ラウンド 2 の PoC を実ツリーに対して再実行 →<br>`例外: SymlinkWriteRefused シンボリックリンクなので書き込みを拒みました` / `victim.txt: ORIGINAL` / `swapped.jin はまだ symlink か: True`<br>（ラウンド 2 では `victim.txt: WRITTEN-THROUGH-SYMLINK` になっていた）<br>**実装**: `main.py:165` に `os.O_NOFOLLOW` が実コードとして在る。`ELOOP` だけを `SymlinkWriteRefused` に変換し、それ以外の `OSError` は基底 `WriteRefused` に落とす（`main.py:166-173`）<br>**握り潰しなし**: `getattr(os, "O_NOFOLLOW", 0)` は使っていない。しかもこの握り潰しパターン自体が変異 M2 で赤くなる<br>**e2e**: `proj/swapped.jin -> ../out/victim.txt` を置いて `jin fmt proj` → EXIT=0 /「シンボリックリンクなので整形しません」/ `victim: ORIGINAL` / symlink のまま |
| **R-2**<br>安全宣言が実装と乖離 | **defect-gone（再発防止まで機械化）** | `_write_canonical` の docstring（`main.py:225-246`）が「**`_collect` はシンボリックリンクを弾かない**」「事前判定は防御ではない」と訂正され、防御の本体を下位 2 つに名指ししている<br>`test_collect_does_not_filter_symlinks` が「ガードが無い」ことを逆向きに固定（変異 M5 で赤くなる）<br>`guard:` 記法と 2 本のメタテストが「主張が実コードに対応すること」を機械で固定（変異 M6 で赤くなる）<br>`fmt` 本体のガードのコメント（`main.py:317-325`）に「この判定は利便性であって防御の本体ではない／外してもリンク先は書き換わらない」＋固定しているテスト名まで書いてある |

### 変異注入の結果（`tmp/r3/snap/` の複製ツリーで実施・終了時にハッシュ一致を確認）

| # | 変異 | 赤くなったテスト |
|---|---|---|
| M1 | `\| os.O_NOFOLLOW` を除去 | `test_write_in_place_refuses_a_symlink`（DID NOT RAISE）/ `test_fmt_does_not_write_through_a_symlink_on_the_fallback_path`（リンク先が書き換わった）/ `test_guard_claims_point_at_real_guards` / `test_guard_claim_check_looks_at_code_not_at_the_claim_itself` — **4 件** |
| M2 | `os.O_NOFOLLOW` → `getattr(os, "O_NOFOLLOW_X", 0)`（実装者が docstring で名指しした握り潰しパターン） | **同じ 4 件**。握り潰しは「トークンが実コードに無い」ので guard 主張テストにも掛かる |
| M3 | `fmt` の `if path.is_symlink():` → `if False:` | `test_fmt_does_not_follow_symlinks`（**「シンボリックリンクなので整形しません」という上位ガード固有の文言**を見るよう厳しくなっている）/ `test_guard_claims_point_at_real_guards` — **2 件** |
| M4 | `_write_atomically` の `lstat` 判定を削除 | `test_write_atomically_refuses_a_symlink`（DID NOT RAISE）— **1 件** |
| M5 | `_collect` に symlink フィルタを追加（安全宣言の逆向き） | `test_collect_does_not_filter_symlinks` — **1 件** |
| M6 | `guard:` の名指しだけ嘘にする（実コードは無傷） | `test_guard_claims_point_at_real_guards`（`_collect に os.O_NOFOLLOW が無いのに guard: がそこを名指ししている`）— **1 件** |

親の報告（M1 で 2 件 / M3 で 1 件）より広く赤くなる。**「検査が存在する ≠ 検査が落ちる」は解消されている。**

---

## 2. 親提示の 5 点への判定

### 点 1: 各層を別テストで分離したことは十分か → **十分**

ラウンド 2 では `test_fmt_does_not_follow_symlinks` が `assert "シンボリックリンク" in output` だったため、
下位ガードが同じ語を出す状態になると上位ガードの変異で緑のままになる。現在は
「**シンボリックリンクなので整形しません**」という**上位ガード固有の文言**を見ており、
M3 で実際に赤くなることを確認した（`assert 'シンボリックリンクなので整形しません: ...'`）。

3 層が独立に固定されていることを変異で確認した:

| 層 | 固定しているテスト | 変異 | 結果 |
|---|---|---|---|
| 上位（利便性） | `test_fmt_does_not_follow_symlinks` | M3 | 赤 |
| 下位 A（退避路） | `test_write_in_place_refuses_a_symlink` / `..._on_the_fallback_path` | M1 / M2 | 赤 |
| 下位 B（原子的経路） | `test_write_atomically_refuses_a_symlink` | M4 | 赤 |

どの 1 層を殺しても、その層だけが名指しで赤くなる。層をまたいだ「取りこぼし」は無い。

### 点 2: `_write_atomically` に境界越えの窓は無いという分析 → **正しい。独立に実証した**

実装者の根拠（`mkstemp` は `O_CREAT|O_EXCL` でリンクを辿らない / `os.replace` はリンクの実体を置き換える）を
**自分で書いた等価コード**（lstat ガードだけを外した `_write_atomically`）で検証した:

```
victim.txt         : ORIGINAL          ← リンク先は書き換わっていない
swapped.jin symlink: False             ← リンクが通常ファイルに化けただけ
swapped.jin 中身   : WRITTEN
残骸               : ['swapped.jin']   ← 一時ファイルも残らない
```

**分析は正しい。** `os.replace(temporary, path)` は `path` という**名前**を差し替える `rename(2)` であり、
リンク先の inode には触れない。したがって R-1 が問題にした「対象ディレクトリの外が書き換わる」は
この経路では起こりえない。残るのが「リンクが通常ファイルに化ける」だけ、という切り分けも正しく、
それを S12 の方針違反として `lstat` で拒む判断も妥当である（M4 で固定されている）。

### 点 3: `lstat` を `mkstemp` の後ろに置いた理由 → **配置の判断は妥当。ただし理由づけは再現しなかった**

**配置そのものは妥当**である。この判定が競合に負けても起きるのは「リンクの置き換え」だけで、
リンク先が書き換わらないことは点 2 で実証済みだから、`mkstemp` の前でも後ろでもセキュリティ性質は変わらない。
一時ファイルが 1 つ余計に作られて消えるだけで、残骸も出ない（M4 の観察）。

**ただし「前に置くと `O_NOFOLLOW` を消す変異が赤くならなくなる」という理由は、私の手元では再現しなかった。**
実際に `lstat` 判定を `mkstemp` の前へ移し、**同時に** `| os.O_NOFOLLOW` を外す変異を作って走らせた結果:

```
FAILED test_write_in_place_refuses_a_symlink - Failed: DID NOT RAISE SymlinkWriteRefused
FAILED test_fmt_does_not_write_through_a_symlink_on_the_fallback_path - AssertionError: リンク先が書き換わった
4 failed, 55 passed
```

→ **前に置いても変異は赤くなる。**

理由: `test_fmt_does_not_write_through_a_symlink_on_the_fallback_path` は
`monkeypatch.setattr(Path, "is_symlink", lambda self: False)` で `Path.is_symlink` を**丸ごと**殺している。
`_write_atomically` のガードも `Path(path).is_symlink()` を使っているので、
**配置に関係なく**この monkeypatch で無効化され、必ず退避路まで到達する。
配置ではなく「ガードが monkeypatch と同じ呼び出し（`Path.is_symlink`）を使っていること」が効いている。

**実務上の影響**: 結論（現在の配置でよい）は変わらないが、**理由の記述が実際の機序とずれている**。
将来この `lstat` を `os.path.islink()` や `os.lstat()` に書き換えると、monkeypatch が効かなくなって
退避路のテストが手前で止まり、`O_NOFOLLOW` の変異を捕まえられなくなる。
docstring / コメントの理由づけを「配置」ではなく「`Path.is_symlink` を使っていること」に直すことを推奨する
（コード変更は不要・1〜2 行の記述修正）。

### 点 4: `decision-conformance.md` §2.11 の訂正 → **妥当**

訂正が「打ち消し」ではなく「旧記述を引用したうえで誤りと正しい防御位置を表で示す」形になっている点は、
S14（DP-COMMON-07 の訂正）と同じ扱いで一貫している。誤りを消さずに残す形は、
後から読む人が「なぜこの記述になったか」を追えるので適切である。
なお `tests/spec/test_spec_consistency.py::test_decision_conformance_does_not_claim_jin_core_imports` のように
成果物の記述自体を機械で固定するテストが別途あり、同種の嘘が増えにくい構造になっている。

### 点 5: R-2 の再発防止（安全宣言の機械固定）→ **実際に再発を防ぐ。今回の一連の対処で最も価値が高い**

3 つが揃っている点を評価する:

1. **`test_collect_does_not_filter_symlinks`**: 「どこにガードが無いか」を固定する。
   M5（`_collect` にフィルタを足す）で赤くなることを確認。**逆向きの固定**は珍しく、有効である
2. **`guard:` 記法 + `test_guard_claims_point_at_real_guards`**: 主張の名指し先に
   トークンが**実コードとして**在ることを AST で検証する。M6（主張だけ嘘にする）で赤くなる
3. **`test_guard_claim_check_looks_at_code_not_at_the_claim_itself`**: 検査自体が
   「docstring の文言を見て通ってしまう」実装ミスを固定する。
   `MINIMUM_GUARD_CLAIMS = 4` で「走査が壊れて 0 件」も塞いでいる

さらに、**将来ガードを外す人が実際に読む場所**（`fmt` 本体のガードの直上コメント・`main.py:317-325`）に
「この判定は利便性であって防御の本体ではない／外してもリンク先は書き換わらない」＋固定しているテスト名を
書いてある。docstring を直しただけの対処と違い、**外そうとした人の目の前に根拠が出る**。

R-2 の本質は「安全宣言が実装から独立に書けてしまう」ことだった。それを実コードに結び付けて
機械で落とす仕組みにしたので、**同型の再発は防げる**と判断する。

---

## 2-bis. `guard:` 記法の追加判定（親からの追加依頼 3 点）

`main.py` の `guard:` 行は現在 **7 箇所**（`:25` は記法の説明で、正規表現が `<関数名>` に当たらないため主張として集計されない）。
検証は `tmp/r3/snap2/` の複製ツリーで行い、終了時に実ツリーとのハッシュ一致を確認した。

### (1) この検査は本当に嘘を捕まえるか → **捕まえる。docstring 剥がしも正しく効いている**

要点は `guard: _write_in_place -> os.O_NOFOLLOW` という**文字列が docstring 自身にも在る**ことで、
関数のソースを丸ごと見る実装だと嘘を 1 件も検出できない。これを直接変異で確認した。

**変異 E-D**: `_function_code_without_docstring` の `body = body[1:]`（docstring を落とす行）を無効化し、
**同時に** `guard:` の名指し 3 件をすべて R-2 の元の嘘（`_collect -> ...`）に書き戻す:

```
FAILED test_guard_claims_point_at_real_guards
  - AssertionError: _collect に os.O_NOFOLLOW が無いのに guard: がそこを名指ししている
FAILED test_guard_claim_check_looks_at_code_not_at_the_claim_itself
  - AssertionError: docstring が落ちていない（主張の自己参照で通ってしまう）
```

→ **2 本とも赤くなる。** 1 本目は嘘そのものを、2 本目は「検査が自己参照で通ってしまう実装ミス」を捕まえている。
`ast.unparse` はコメントも落とすので、コメント側に書いた `guard:` 行（`main.py:322-323`）も
自己参照で通ることはない。**この設計は正しい。**

なお本レビュー §1 の変異 M6（`guard:` の名指しだけを嘘にし、実コードは無傷）でも
`test_guard_claims_point_at_real_guards` が単独で赤くなることを確認済みである。

### (2) 記法の抜け道 → **3 つ在る。いずれも実害は「誤った記述が残せる」まで**

| # | 抜け道 | 結果 | 実害 |
|---|---|---|---|
| **E-A** | `guard:` 行を書かず、**散文で嘘を書く**（`_write_canonical` の docstring に「シンボリックリンクは `_collect` が入口で弾いているので安全である」を追記） | **3 passed（素通り）** | R-2 とまったく同じ嘘が、記法を使わなければ今も書ける |
| **E-B** | **トークンを緩い語にする**（`guard: fmt -> os` / `guard: fmt -> path`） | **どちらも 3 passed（素通り）** | 検査は `token in code` の**素の部分文字列一致**。`os` は `fmt` の `diagnostic` の中の "os" に当たって通る（実測で確認）。`path` のような無意味な語でも通る |
| **E-C** | **実在するが無関係な関数を名指しする**（`guard: _write_atomically -> os.replace` → `guard: _write_canonical -> os.access`） | **3 passed（素通り）** | `_write_canonical` は実際に `os.access` を含むので通る。しかし `os.access` は**防御ではない**（同じ docstring が「`os.access` もリンクを辿るのでこの関数の判定は防御ではない」と明記している）。つまり「実在するトークン × 実在する関数」の組み合わせで、意味的に真逆の主張が通る |

**判定**: 3 つとも**実際の防御を無効化しない**。無効化する変異（M1〜M5）はすべて挙動テストで赤くなることを確認済みで、
`guard:` 検査はその上に載る「記述の腐り検出」に過ぎない。したがってこれは**セキュリティ欠陥ではなく、
緩和策の強度の上限**である。仕組みの目的（R-2 の再発防止）は E-D で担保されており、達成されている。

ただし E-B は 1 行で塞げるので、機会があれば直す価値がある（下記 U-1）。E-A と E-C は
「主張は任意であり、意味の正しさは機械では検証できない」という性質そのものなので、
機械的な対処は無い。**それでよい**と判断する — R-2 の具体的な嘘そのものは
`test_collect_does_not_filter_symlinks` が別途固定しており、二重になっている。

### (3) 2 案目（実装依存の主張を消す）を採らなかった判断 → **妥当**

R-2 の実害は「docstring を読んだ人が `_collect` が守ってくれると信じ、`fmt` のガードを外す」ことだった。
2 案目（`_write_in_place` 自身の `O_NOFOLLOW` だけを根拠にし、他所の実装への言及を消す）を採ると、
docstring は「真だが何も伝えない」ものになり、**まさにその誤解を防ぐための情報が消える**。
実装者の理由づけはこの点を正しく捉えている。

補足として、2 案目を退けたことの代償（実装依存の主張は時間とともに腐る）を、
`guard:` 記法がちょうど埋めている。**「情報を残す」と「腐りを機械で検出する」がセットになっているので、
組み合わせとして筋が通っている。** 片方だけなら妥当ではなかった。

---

## 3. ラウンド 3 の新規欠陥

```
T-1 【Low / confidence 90】PermissionError 以外の OSError が未捕捉トレースバックになる
packages/jin-cli/src/jin_cli/main.py:216-222（_write_atomically の except 節）
packages/jin-cli/src/jin_cli/main.py:247-256（_write_canonical）/ :293-301（fmt の except WriteRefused）
_write_atomically は PermissionError だけを AtomicWriteUnavailable に畳み、
それ以外は `except BaseException: unlink; raise` で**素のまま**外へ投げる。
_write_canonical も AtomicWriteUnavailable しか受けず、fmt は WriteRefused しか捕まえない。
したがって次はトレースバックになる（S5 / N2 と同じ欠陥型の 3 度目の出現）:
  - 書き込み直前にファイルが消えた（FileNotFoundError）— エディタ / LSP との競合で起きうる窓
  - ディスクフル（OSError: ENOSPC）— handle.write が投げる
  - shutil.copymode の対象が壊れた symlink（FileNotFoundError）

PoC: 実行済み（API 層で決定的に再現）。read_source と書き込みの間でファイルが消えた状況を作ると
  _write_canonical : **WriteRefused ではない** FileNotFoundError: [Errno 2] ... 'p3/gone.jin'
  _write_atomically: **WriteRefused ではない** FileNotFoundError: [Errno 2] ... 'p3/gone.jin'
（一時ファイルの後始末は正しく動いており、残骸は 0 件）

**Low とした理由（T-1）**: fmt は check_file → read_source → 書き込みの順に進むので、
CLI から決定的に踏む経路は無く、競合かディスクフルが要る。情報開示も S5 の対策
（pretty_exceptions_show_locals=False）が効いていてローカル変数は出ない。
**ただし Phase 4 の LSP では現実的な頻度になる**（エディタがファイルを消す / 名前を変える）。

**確認したが問題が無かった隣接ケース**: macOS の immutable フラグ（chflags uchg）を立てた .jin を
jin fmt すると os.replace が EPERM → AtomicWriteUnavailable → os.access は真 → _write_in_place の
os.open が EPERM（ELOOP ではない）→ 基底 WriteRefused → fmt が診断化。実測:
  EXIT=1 / 「p4/imm.jin: 書き込めません（[Errno 1] Operation not permitted: ...）」/ Traceback 0 件 / 残骸なし
→ 非 ELOOP 分岐は設計どおり動いている。T-1 は _write_atomically 側の except 節だけの問題である。

修正（1 行）: _write_atomically の `except PermissionError` を `except OSError` に広げるか、
`except BaseException` の直前に `except OSError as exc: unlink; raise WriteRefused(...) from exc` を足す。
そうすれば fmt の既存の `except WriteRefused` がそのまま診断化する。
```

```
U-1 【Info / confidence 95】guard: の検査が素の部分文字列一致なので、緩いトークンで通ってしまう
packages/jin-cli/tests/test_cli.py:727 付近（test_guard_claims_point_at_real_guards の `assert token in code`）
`token in code` は unparse 済みソースに対する素の部分文字列一致なので、
意味を持たない語でも通る。PoC: 実行済み（複製ツリー）。
  guard: fmt -> os   → 素通り（`diagnostic` の中の "os" に当たっている。実測で確認）
  guard: fmt -> path → 素通り
セキュリティ欠陥ではない（実際の防御は挙動テスト M1〜M5 が固定している）。
「主張の腐り検出」という仕組みの強度の話であり、Info とした。

修正（1 行相当）: 部分文字列一致ではなく AST で照合する。
`ast.walk` して `ast.Attribute` / `ast.Call` / `ast.Name` を `ast.unparse` し、
その集合にトークンが**完全一致**で在ることを見れば `os` / `path` は落ちる
（`os.O_NOFOLLOW` / `os.replace` / `is_symlink` はいずれも属性・名前として実在するので現状の 7 件は通る）。
なお E-A（guard: 行を書かず散文で嘘を書く）と E-C（実在するが無関係な関数を名指しする）は
機械的に塞げない性質のもので、対処不要と判断した（§2-bis (2)）。
```

---

## 4. その他の確認

- **`lint-imports` 3 contracts kept / exit 0**（S1 の隔離契約は生きている）
- **`ruff check` exit 0 / `ruff format --check` 差分なし**
- **全 498 テスト pass**
- `fmt` の例外ハンドラが `AtomicWriteUnavailable` から**基底 `WriteRefused`** に広がっており、
  `SymlinkWriteRefused` も同じ診断経路に乗る（e2e で確認済み）
- `_write_atomically` の `shutil.copymode` は `lstat` 判定より前にあるためリンクを辿って
  **リンク先のモード**を読むが、直後に拒否して一時ファイルを消すので実害は無い
  （ただし T-1 の「壊れた symlink で FileNotFoundError」の発生源はここ）

---

## 5. 検証中に観測した注意点（欠陥ではないが記録）

本レビューの最中、**実ツリーの `main.py` が一度変化した**。
最初の読み取りでは 165 行目が

```python
descriptor = os.open(path, os.O_WRONLY | os.O_TRUNC | os.O_CREAT | getattr(os, "O_NOFOLLOW_X", 0), 0o666)
```

（`O_NOFOLLOW_X` は存在しない属性なので `getattr` が **0** を返し、`O_NOFOLLOW` が付かない = R-1 の防御が消えた状態）
になっており、その後の読み取りでは正しい `os.O_NOFOLLOW` に戻っていた。**変異注入の実行中に読んだもの**と考えられる。

**原因は判明している**: `impl-p01` が R-2 の「安全宣言の機械固定」を実ツリーで作業中で、その着地過程だった
（親が確認済み・完了報告 19:40）。テスト件数の揺れ（496 → 497 → 498）と一時的な `2 failed` も同じ理由である。
本レビューの変異注入は一貫して `tmp/r3/snap/` と `tmp/r3/snap2/` の複製ツリーで行っており、実ツリーには触れていない。

- **成果物としての判定には影響しない**。本レポートの全結論は `main.py` sha256 `a2470e02…` に対するもので、
  このハッシュは `impl-p01` の完了（19:40:39）後の最終状態と一致している（検証の開始時・終了時の両方で確認）
- 途中で観測した状態は**私の変異 M2 と同一**であり、そこで 4 件のテストが赤くなることも確認済みなので、
  仮にその状態でコミットされても CI が止める
- 記録として残す理由: **コミット直前に `git diff` で `main.py:165` を目視確認することを勧める**。
  作業中のツリーを別のプロセスが検証する構成では、中間状態が「防御が黙って消える」形に見える瞬間がある
  （まさに実装者が docstring で警戒していた失敗モードと同じ見え方になる）。
  今回はレビューと実装の時間帯が重なったことが原因で、実装側の不具合ではない

### 5.2 レポート提出時点（19:49）でツリーがさらに動いている

本レポートを書き終える直前に再確認したところ、実ツリーは**親が「安定」と示した状態からさらに変化していた**。

| 項目 | 本レポートが判定した状態 | 19:49 時点の実ツリー |
|---|---|---|
| `main.py` sha256 | `a2470e02…` | `ea47116c…`（mtime 19:49:06 = 確認時刻と同一） |
| テスト件数 | 498 passed | 505 passed |
| `ruff check` | exit 0 | **exit 1**（`PYI034` / `packages/jin-cli/tests/test_cli.py:874` の `def __enter__(self) -> Exploding:` は `Self` を返すべき） |
| `guard:` 行 | 7 | 10 |

`main.py` に `_classify_write_failure`（docstring に「security review T-1」と明記）が追加されており、
**本レポートの T-1 の修正が進行中**と見られる。設計の方向は妥当に見える
（「`PermissionError` だけを退避可能とする。容量不足や『書く直前に消えた』で退避すると
`_write_in_place` の `O_TRUNC` が元の内容を消してから同じ理由で失敗しうる」という切り分けは、
私が提案した `except OSError` への単純な拡張より正しい）。

**扱い**:

- **本レポートの全判定は `a2470e02…` / 498 passed に対するもの**であり、親が「この状態でレビューしてほしい」と
  指定した状態と一致している。以降の変更は判定対象外
- ただし **19:49 時点の `ruff check` は赤い**。`.github/workflows/ci.yml:27` が `uv run ruff check .` を
  走らせるので、この状態でコミットすると CI が落ちる。作業途中の中間状態と考えられるが、
  **コミット前に `ruff check` が緑であることを必ず確認すること**
- T-1 の修正が着地したら、その状態に対して改めて defect-gone を確認できる（依頼があれば実施する）

---

## 6. 対象外として扱った項目

親の指示どおり、次は本レビューの判定対象から外した。

| 項目 | 状態 |
|---|---|
| `DP-JIN-RESOLVE-ISOLATION-01`（`--resolve` の別プロセス化 / ファイル間汚染） | 判断待ち。Phase 4 着手前がデッドラインという線引きに異論なし |
| `DP-REVIEW-JIN-001`（= R-3。`jin check` の symlink 追従） | fix-later として起票済み |
| S3 残存（最悪 8.4 秒）= `DP-REVIEW-JIN-008` | Phase 4 送り |
| `os._exit(0)` 残存 | 前回の判定（fix-now 不要）を維持 |

---

## 7. 結論

**security 観点から Phase 0+1 のコミットに反対しない。**

confidence 90 以上で報告した全 14 件（S1〜S6, S8〜S14, S19）と、修正が入れた新規欠陥 2 件（N1 / N2）、
さらに R-1 / R-2 まで、すべて defect-gone を PoC で確認した。
残るのは fix-later / Phase 4 送りとして起票済みの 4 件と、本ラウンドで見つけた
**T-1（Low）** と **U-1（Info）** だけである。

T-1 は 1 行で直せるうえ Phase 4 の LSP で必ず効いてくるので、**Phase 2 に入る前に片付けることを推奨する**が、
コミットの前提条件にするほどではない（CLI から決定的に踏む経路が無いため）。
U-1 は仕組みの強度の話でセキュリティ欠陥ではないので、いつ直してもよい。

**特筆すべき点**: `guard:` 記法とその 2 本のメタテストは、本案件で私が繰り返し指摘してきた
「検査が存在する ≠ 検査が落ちる」への回答として、この 3 ラウンドで最も価値の高い成果である。
S12 のテストが変異で緑のままだった事実を実装者が**自分で見つけて報告した**ことも含め、
Phase 2 以降でも同じ検証の仕方（挙動テスト + 変異注入 + 主張の機械固定）を続けることを勧める。
