# 再レビュー（修正ラウンド 1）— security

対象: `delivery/20260904-1445-jin/code-review-raw/security.md` の confidence 90 以上 14 件（S1〜S6, S8〜S14, S19）
方針: 実装者の報告・コメント・rationale は未検証の主張として扱い、**PoC が通らなくなったこと**をこの場で実行して確認した。
PoC は `/Users/toyota/.claude/jobs/8b3a6b62/tmp/r1/` 配下にのみ作成した。

## Summary

- **確認対象: 14 件**（confidence 90 以上）
- **defect-gone: 14 件 / 未消滅: 0 件 / 判定不能: 0 件**
  - うち **完全に消滅: 12 件**（S1, S2, S4, S5, S6, S8, S9, S10, S12, S13, S14, S19）
  - うち **元の PoC は再現しないが残存リスクあり: 2 件**（S3・S11）
- **S1 の contract が実際に噛むか: 噛む（実測で確認）。しかも二重の網になっている**
  - `jin_core` に `from jin_cli.resolver import ImportResolver` を注入 → `lint-imports` が
    「ref の解決実装（任意コード実行）は jin_cli に閉じる」を **BROKEN** と報告し **exit 1**（復元後は exit 0）
  - `jin_core` に `import importlib` を直書き（`jin_cli` を経由しない迂回）→ import-linter は**捕まえないが**、
    `tests/contract/test_packaging_contract.py::test_the_only_module_importing_importlib_is_the_cli_resolver` が **FAILED**
  - 将来 `jin_lsp` を足して `source_modules` への追加を忘れたシナリオを再現 →
    `test_resolver_isolation_contract_covers_every_package_but_the_cli` が
    「resolver 隔離契約の source_modules に {'jin_lsp'} が無い」と**名指しで FAILED**。
    さらにこの取りこぼし状態でも layers 契約が `jin_lsp -> jin_cli.resolver` を BROKEN にする（exit 1）
  - → **コメントでの約束ではなく、機械で落ちる**。私の提案どおりに実装されている
- **修正が入れた新規欠陥: 2 件**（いずれも S11 の原子的書き込みの実装に由来。詳細は §3）
  - **N1【Medium】`jin fmt` がファイルのパーミッションを 0600 に落とす**
  - **N2【Medium】書き込めないディレクトリで未捕捉 `PermissionError` のトレースバック（S5 の欠陥型の再導入）**
- **`os._exit(0)` の残存に対する判定: 親の判断に同意（fix-now への格上げは不要）。ただし別プロセス化は Phase 4 の着手前提（fix-next）に据えるべき**
  - 同意の理由: `os._exit` に到達した時点で攻撃者のコードは既に同一プロセスで実行中であり、`os._exit` は
    「既に持っている能力の一部」に過ぎない。より強い手（`jin_core.check.analyze` の差し替え、ファイル書き込み、
    外部送信）が同じ位置から可能で、権限境界は 1 つも越えていない
  - ただし**格上げの根拠になりうる追加被害を 1 つ実測した**（§4）。`os._exit` 単独ではなく
    「同一プロセスで import する」設計そのものに由来する
- **PoC 残骸**: リポジトリツリーへの追加は本ファイル 1 本のみ。`git status --porcelain`:

```
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

`PWNED.txt` / `evil*.py` / `pwn.jin` / `exit.jin` などの PoC 生成物は `find` で 0 件。
`?? delivery/20260904-1445-jin/code-review-raw/` は本ファイルと前回のレポートのみ。
契約テストの検証では**リポジトリを一切触らず**、`/Users/toyota/.claude/jobs/8b3a6b62/tmp/r1/repo/` に
`pyproject.toml` + `packages/` + `tests/` を複製して注入・実行した。

**補助的な確認**: `uv run pytest` 全件 pass（442 件）、`jin check examples` exit 0、`jin fmt --check examples` exit 0。

---

## 1. finding 別の判定

| ID | 判定 | 根拠（実行した PoC とその結果） |
|---|---|---|
| **S1**<br>`--resolve` の任意コード実行 | **defect-gone（構造的隔離として達成）** | ACE 自体は `jin check --resolve` の経路に**設計として残る**（PoC 再現: `PYTHONPATH=. jin check --resolve pwn.jin` で `PWNED.txt` が生成される）。修正の主旨は「隔離」であり、そこは達成:<br>① `jin_core` 単体の `check_text(src, file)`（resolver 省略）と `check_text(..., resolver=NullResolver())` のどちらでも **`PWNED.txt` は生成されない**（実行済み）<br>② `pkgutil` で `jin_core` の全モジュールを列挙 → `resolver` は Protocol と `NullResolver` のみで `importlib` を持たない<br>③ import-linter 3 契約すべて KEPT。違反注入で BROKEN（下記 §2）<br>④ `--resolve` 無しでは import が起きないことを実測（`PWNED.txt` 不在） |
| **S2**<br>`SystemExit` による fail-open | **defect-gone** | `ref` 先モジュールのトップレベルに `sys.exit(0)` / `sys.exit(3)` を置き、同一ファイルに本物の JIN060 を併記:<br>・`sys.exit(0)` → **EXIT=1**、JIN060 が出力され JIN040 warning に `SystemExit: 0` が可視化<br>・`sys.exit(3)` → **EXIT=1**、同上（`SystemExit: 3`）<br>・`raise KeyboardInterrupt` → **EXIT=130**（正しく伝播。握り潰していない）<br>・`os._exit(0)` → EXIT=0・出力ゼロ（**残存**。§4 で判定） |
| **S3**<br>編集距離の DoS | **defect-gone（部分・残存リスクあり）** | 元の PoC（88 KB で 107.82 秒）は再現しない。計測（`check_text` 直呼び）:<br>・circle 200 / 名前長 200（元の最悪ケース）→ **0.01 s**（名前長 128 の上限で JIN002 として弾かれる）<br>・circle 400 / 名前長 128 / 115 KB → **8.24 s**<br>・circle 800 / 230 KB → **8.26 s**<br>・circle 1500 / 431 KB → **8.30 s**<br>・circle 3000 / 861 KB → **8.44 s**<br>→ `MAX_DISTANCE_COMPUTATIONS = 20000` の総予算（`semantic.py:41`）が効き、**入力サイズに対して平坦**になった。二次爆発は消滅。<br>**残存**: 最悪 8.4 秒という定数が残る。`check_text` は Phase 4 の LSP が打鍵ごとに呼ぶ経路なので、8.4 秒はそのままでは使えない。§5 に是正案 |
| **S4**<br>未捕捉 `RecursionError` | **defect-gone** | ・`[` × 2000 → `JIN001: 入れ子が深すぎます（上限 64 段）` / **EXIT=1** / トレースバック 0 件<br>・`[` × 20000 → 同上<br>・circle 3000 の数珠つなぎ（`flow.steps`）→ **EXIT=0**、`RecursionError` なし<br>・circle 20000 の数珠つなぎ（`delegate`）→ **EXIT=0**、`RecursionError` なし（`_find_cycle` / `_subtree_states` の反復化を確認）<br>・`--json` 経路でも同様に落ちない |
| **S5**<br>例外の素通り・情報開示 | **defect-gone** | ・非 UTF-8 ファイル → `JIN001: UTF-8 として読めません（位置 0: invalid start byte）` / EXIT=1<br>・`jin dump` にディレクトリ → `adir: 読み込めません（IsADirectoryError: Is a directory）` / EXIT=2<br>・`jin fmt` に非 UTF-8 → JIN001 / EXIT=1<br>・上記いずれも **`Traceback` の出現数 0**<br>・`pretty_exceptions_show_locals=False`（`main.py:41`）を確認。N2 のトレースバックにも locals は出ない |
| **S6**<br>ANSI / 偽診断行インジェクション | **defect-gone（二重防御）** | `root` に `ESC[2J` + `ESC]0;pwned` + BEL + 改行 + 偽診断行を仕込んで `jin check`:<br>・段 2 で `JIN002: 制御文字 U+001B は使えません` として**拒否**される（`model.py:49-66`）<br>・出力に含まれる制御バイト（改行以外）を数えると **0 バイト**（`tr -cd` で実測）<br>・hint に載る値は Python の `repr` で `'\x1b[2J...\nfake.jin:1:1: error JIN999: injected'` と 1 行に潰れ、行頭に偽診断行が現れない<br>・`_safe()` 単体: `'a\x1b[2Jb\nc\x7fd\x9ae'` → `'a\\u001b[2Jb\\u000ac\\u007fd\\u009ae'`（C0 / DEL / C1 と改行を網羅） |
| **S8**<br>`rename` の置換テンプレート注入 | **defect-gone** | `apply_op(rename, /circles/0/state/0, value=...)`:<br>・`x\g<0>y` → state 名 `'x\g<0>y'` / rune `'hello {x\g<0>y} world'`（**リテラル置換。両者が一致**）<br>・`b\1c` → 例外なしでリテラル置換（旧: 未捕捉 `re.PatternError`）<br>・`q\qz` → 同上（旧: 未捕捉 `re.PatternError`）<br>・`n\n` → 同上 |
| **S9**<br>`rename` の範囲外 index | **defect-gone** | `/circles/99` / `/circles/9999999999` / `/circles/0/tools/99` / `/circles/0/state/99` の 4 通りすべて **`OpError JIN002`**（旧: 未捕捉 `IndexError`） |
| **S10**<br>`isdigit()` と `int()` の不一致 | **defect-gone** | `resolve_pointer`: `/a/²` `/a/--1` `/a/٣` `/a/⁵` `/a/01` `/a/+1` の 6 通りすべて **`KeyError`**（docstring の契約どおり。旧: `ValueError` / `IndexError` で 3 と解釈）<br>`apply_op`: `/circles/²` `/circles/٣` `/circles/--1` `/circles/01` の 4 通りすべて **`OpError JIN002`**（旧: 未捕捉 `ValueError`）<br>先頭ゼロ・符号も弾いており RFC 6901 として旧実装より厳密 |
| **S11**<br>非原子的な書き戻し | **defect-gone（原子性は達成・ただし新規欠陥 2 件を導入）** | `main.py:100-117` の `_write_atomically` が `tempfile.mkstemp(dir=path.parent)` → `os.replace` になっている。`newline=""` で LF 固定も担保。失敗時に一時ファイルを消す `except BaseException` あり。<br>実測: `jin fmt` 後に一時ファイルの残骸なし、書き込み失敗時に**元ファイルは無傷**。<br>**ただし §3 の N1 / N2 を導入している** |
| **S12**<br>symlink 経由の外部書き込み | **defect-gone** | `proj/link.jin -> ../outside/secret.jin` を置いて:<br>・`jin fmt proj`（ディレクトリ指定）→ `シンボリックリンクなので整形しません: sl/proj/link.jin` / EXIT=0 / **`outside/secret.jin` は無傷**<br>・`jin fmt proj/link.jin`（直接指定）→ 同じくスキップ / 無傷<br>（軽微な観察: symlink しか無いディレクトリでも `fmt --check` は EXIT=0。スキップは stderr に必ず出るので隠蔽ではない） |
| **S13**<br>文字種・長さ制約の欠如 | **defect-gone（誤検知なし）** | `model.py:18-84` に `Ident`（128 字・制御文字と孤立サロゲート禁止）/ `Text`（65536 字・改行タブのみ許可）/ `Url`（2048 字）を導入。**正当な `.jin` を誤って拒否していないことを 14 ケースで確認**:<br>日本語 circle 名 / 日本語 rune（改行・タブ入り）/ 絵文字名 / `description` の改行 / `name` 128 字ちょうど / `rune` 65536 字ちょうど / `$schema` 2048 字 / ドット付き `ref` / 日本語の `state.type` / 文字列の `flow.exit.equals` / NBSP(U+00A0) 入りの名前 → **すべて診断ゼロ**<br>境界の外（`name` 129 字 / `rune` 65537 字）だけが JIN002 になる<br>`jin check examples` EXIT=0 / `jin fmt --check examples` EXIT=0 / 全 442 テスト pass |
| **S14**<br>対照表の「reflected」が実態と乖離 | **defect-gone（実装が変わり、記述も正確）** | `decision-conformance.md:35` が **reflected（修正ラウンド 1 で成立させた）** に書き換わり、「修正前は `sys.modules` を書き換えていたので純関数ではなかった / security review S14 の指摘どおり当時の reflected は実態と乖離していた」と**誤りを明示**したうえで、現在の根拠（`ImportResolver` を `jin_cli` へ移動）を書いている。<br>記述の裏取り: `jin_core` に `importlib` が 1 箇所も無いことを契約テストで機械的に担保（§2）。`check_text` を resolver 省略で 2 回呼んでも `sys.modules` は変わらない。**記述は実態に合っている**<br>（精度上の細注: `jin_core.check_text(..., resolver=ImportResolver())` と**呼び出し側が渡せば**その呼び出し中は `sys.modules` が変わる。「`jin_core` に可変状態は無い」は正しいが、「`check_text` は純関数」は注入された resolver 次第。記述は前者の表現になっており誤りではない） |
| **S19**<br>ACE の警告がドキュメントに無い | **defect-gone** | ・`README.md:20-27` に「`jin check --resolve` は任意コードを実行する」節が新設。「中身を確認した `.jin` にだけ使うこと」「受け取ったファイル・自動生成されたファイルには使わない」まで明記<br>・`CLAUDE.md:99-111` に「`--resolve` の危険性（jin check）」節。隔離の実装位置（`jin_cli/resolver.py`）と import-linter による機械的担保にも言及<br>・`main.py:128-132` の CLI ヘルプにも【危険】表記 |

---

## 2. S1 の構造的担保の検証（詳細）

リポジトリを一切変更せず、`pyproject.toml` + `packages/` + `tests/` を tmp へ複製して注入した。

**ベースライン（無傷の複製）**

```
jin レイヤは一方向（jin_core が最下層）                KEPT
jin_core は google-adk に依存しない                    KEPT
ref の解決実装（任意コード実行）は jin_cli に閉じる    KEPT
Contracts: 3 kept, 0 broken.   （exit 0）
```

**注入 1: `jin_core/semantic.py` の先頭に `from jin_cli.resolver import ImportResolver`**

```
Broken contracts
  jin レイヤは一方向（jin_core が最下層）
    jin_core.semantic -> jin_cli.resolver (l.1)
  ref の解決実装（任意コード実行）は jin_cli に閉じる
    jin_core is not allowed to import jin_cli.resolver:
    jin_core.semantic -> jin_cli.resolver (l.1)
exit 1
```

→ **狙いの契約が名指しで BROKEN になる。** 復元すると exit 0 に戻ることも確認した。

**注入 2: `jin_core/semantic.py` の先頭に `import importlib`（`jin_cli` を経由しない迂回）**

```
lint-imports exit 0   ← import-linter だけでは捕まえられない
pytest tests/contract/test_packaging_contract.py
  FAILED ::test_the_only_module_importing_importlib_is_the_cli_resolver
    AssertionError: assert ['packages/jin-core/src/jin_core/semantic.py', ...] == ['packages/jin-cli/src/jin_cli/resolver.py']
```

→ 契約の穴（「`jin_cli` を経由せず自前で `importlib` を書く」）は**生の grep テストが塞いでいる**。二重の網。

**注入 3: 将来の `jin_lsp` を模した新パッケージを足し、`root_packages` / `layers` / workspace には登録するが resolver 隔離契約の `source_modules` には足し忘れる**

```
FAILED ::test_resolver_isolation_contract_covers_every_package_but_the_cli
  AssertionError: resolver 隔離契約の source_modules に {'jin_lsp'} が無い
```

さらに、その足し忘れ状態のまま `jin_lsp/server.py` が `from jin_cli.resolver import ImportResolver` を書いても、
layers 契約が `jin レイヤは一方向 BROKEN` を出して **exit 1**（`Contracts: 2 kept, 1 broken.`）。

→ **Phase 4 の実装者が設定を落としても、ws サーバから ACE へ到達する変更は 2 つの独立した網のどちらかで必ず赤くなる。**

---

## 3. 修正が入れた新規欠陥（2 件）

いずれも S11（原子的書き込み）の実装 `packages/jin-cli/src/jin_cli/main.py:100-117` に由来する。

```
N1 【Medium / confidence 97】jin fmt がファイルのパーミッションを 0600 に落とす
packages/jin-cli/src/jin_cli/main.py:108-114（tempfile.mkstemp → os.replace）
tempfile.mkstemp は 0600 でファイルを作る。os.replace は「置き換える側」のモードを引き継ぐので、
整形後のファイルは元のモードではなく 0600 になる。ACL / xattr も落ちる。
PoC: 実行済み。
  整形前: -rw-rw-r--  (664)
  jin fmt p/a.jin  → 「整形しました」/ EXIT=0
  整形後: -rw-------  (600)
共有リポジトリや CI のチェックアウトで group / other の読み取りビットが**黙って**外れる。
git は 実行ビット以外のモードを追跡しないので diff にも出ない。
修正: os.replace の前に shutil.copymode(path, temporary)
      （または os.chmod(temporary, path.stat().st_mode & 0o7777)）。
      対象が存在しない新規作成のときは umask に従う。
```

```
N2 【Medium / confidence 95】書き込めないディレクトリで未捕捉 PermissionError（S5 の欠陥型の再導入）
packages/jin-cli/src/jin_cli/main.py:108（mkstemp）/ :201（呼び出し側に try が無い）
mkstemp は「ファイル」ではなく「ディレクトリ」への書き込み権を要求する。
書き込めないディレクトリにある整形対象を fmt すると PermissionError がそのまま抜け、
rich のトレースバック（絶対パス + ソース断片）が出る。S5 で塞いだのと同じ欠陥型が別の場所に復活している。
PoC: 実行済み。chmod 555 のディレクトリ内の .jin を jin fmt →
  EXIT=1、出力に Traceback / PermissionError / Permission denied / _write_atomically / mkstemp。
  locals は出ない（S5 の pretty_exceptions_show_locals=False は効いている）。元ファイルは無傷。
機能面の後退も伴う: 修正前の write_text は「ファイルさえ書ければ」整形できたが、
現在はディレクトリの書き込み権も必要になった（読み取り専用ディレクトリ内の書き込み可能ファイルを整形できない）。
修正: _write_atomically を OSError で包み、JinReadError と同様に「整形できませんでした」の
      診断メッセージ + exit 2 に落とす。ディレクトリ権限が要る旨をエラー文に書く。
```

**回帰として確認したが問題が無かった点**

- S13 の文字種・長さ制約は**正当な `.jin` を 1 件も誤って拒否していない**（14 ケース。§1 の S13 行）
- `_write_atomically` の一時ファイル名は `.<name>.XXXXXX.tmp` で `*.jin` に一致しないため、
  `_collect` の `rglob("*.jin")` が拾って二重処理する事故は起きない
- 書き込み失敗時に元ファイルが壊れないこと（原子性そのもの）は実測で確認した
- 全 442 テスト pass / `jin check examples` / `jin fmt --check examples` いずれも exit 0

---

## 4. `os._exit(0)` の残存に対する判定

**結論: 親の暫定判断に同意する。fix-now への格上げは不要。ただし別プロセス化は「Phase 4 に入る前に済ませる」fix-next に据えるべき。**

### 同意の根拠

`os._exit` に到達した時点で、攻撃者のモジュールは既に同一プロセスで実行されている（= S1 の任意コード実行が成立済み）。
その位置から `os._exit` より強い手が同じコストで打てる:

- `jin_core.check.check_text` / `jin_core.semantic.analyze` の差し替え
- 任意のファイル読み書き、外部送信
- `sys.exit` を経由しない任意の終了

したがって `os._exit` は**新しい能力を 1 つも与えていない**。権限境界も越えていない。
`--resolve` は既定オフで、README / CLAUDE.md / CLI ヘルプの 3 箇所に危険性が明記された（S19）。
「攻撃者制御のモジュールが `sys.path` に載っている」状態はそれ自体が前提条件として重い。

### ただし fix-next に据えるべき根拠（実測した追加被害）

`os._exit` 単独ではなく「**同一プロセスで import する**」という設計に由来する被害が 1 つある。
**1 つの悪意ある `ref` が、同じ実行内の「他のファイル」の診断結果を偽装できる。**

PoC（実行済み）: `multi/` に 2 ファイルを置く。
`a_bad.jin` は `ref: "z_evil:f"`、`z_evil.py` はトップレベルで `jin_core.semantic.analyze` を空関数に差し替える。
`b_victim.jin` は `root` が存在しない circle を指す（本来 JIN060 error）。

```
--- --resolve なし ---
multi/b_victim.jin:1:35: error JIN060: root が指す circle 'DOES_NOT_EXIST' は定義されていません
2 ファイル / error 1 件 / warning 0 件

--- --resolve あり ---
a_bad.jin:1:114: warning JIN040: Python 参照 'z_evil:f' を解決できません
2 ファイル / error 0 件 / warning 1 件      ← b_victim.jin の JIN060 が消えた・EXIT=0
```

これは「攻撃者は既にプロセスを掌握している」で説明はつくが、**運用者の心的モデル
（この実行は N ファイルを検査した）を偽装する**点で `os._exit` より実害が大きい。
`jin check --resolve <ディレクトリ>` を検証ゲートとして使う運用があれば、
1 ファイルの汚染で全ファイルが緑になる。

同じ設計に由来する未対処が 2 つある:

1. **タイムアウトが無い。** `ref` 先モジュールのトップレベルが `while True:` なら
   `jin check --resolve` は永久にハングする（`ImportResolver.resolve` に時間制限が無い）
2. **`sys.modules` の汚染が実行の最後まで残る。** 1 ファイル目の import が 2 ファイル目以降に影響する

### 具体的な線引きの提案

**別プロセス化（`subprocess` + タイムアウト + 使い捨て）を、次のいずれかを行う前の必須条件にする:**

- `--resolve` を CI / 自動化に載せる（現在の `ci.yml` は使っていない。この状態を維持するなら急がなくてよい）
- `jin check --resolve` を「複数ファイルの検証ゲート」として文書化・推奨する
- Phase 2（`jin build` / `jin run`）や Phase 4（LSP）が長寿命プロセスで参照解決を再利用する

逆に、上記のいずれも行わない限りは現状（既定オフ + 3 箇所の警告 + 構造的隔離）で釣り合っている。

---

## 5. 残存事項（fix-now ではないが記録）

| 項目 | 内容 |
|---|---|
| **S3 の残り** | 最悪 8.4 秒の定数が残る（circle 数によらず平坦）。Phase 4 の LSP は打鍵ごとに `check_text` を呼ぶので、そのままでは使えない。案: ①`MAX_DISTANCE_COMPUTATIONS` を LSP 経路だけ小さくする（例 2000 → 実測 0.8 秒相当）②入力バイト数で予算を段階的に絞る ③`_name_hint` を診断本体から切り離し、`codeAction` / `hover` の遅延計算にする（LSP なら hint は必須ではない） |
| **入力サイズの上限が無い** | 前回 S7（confidence 88・今回の対象外）。861 KB の `.jin` が通る。ws で document を受ける Phase 4 では別途上限が要る |
| **`--resolve` のタイムアウト無し** | §4 の 1。ハングする |
| **`fmt --check` と symlink** | symlink しか無いディレクトリでも exit 0。スキップは stderr に必ず出るので隠蔽ではないが、CI で `fmt --check` を門にする場合は「1 件も検査しなかった」を検出できない |
