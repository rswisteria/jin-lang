# 再レビュー（修正ラウンド 1）— correctness

## Summary

- 確認対象: **25 件**（`correctness.md` の finding 33 件のうち confidence 90 以上）
- defect-gone: **20 件** / 部分消滅: **1 件**（E-5）/ 未消滅: **4 件**（D-4 / E-1 / E-2 / E-3）/ 判定不能: **0 件**
- 修正が入れた新規欠陥: **3 件**（N-1 high / N-2 medium / N-3 low）
- 追加テストの質: **問題なし**（懸念は E-1 / E-2 / E-3 の据え置きと、E-5 の残り 2 つの穴のみ。独立ミューテーション 18 本中、意味のある 16 本で 15 本が検出された）

### 検証条件

- テスト実行: **442 passed in 3.63s**（`.venv/bin/python -m pytest -p no:cacheprovider -o addopts="" -q`）
- 修正前の再現手順（`probe1.py` 〜 `probe5.py` / `crlf.jin` / `surrogate.jin`）をそのまま再実行し、
  加えて独立の回帰プローブ（`re1.py` / `re2.py` / `re3.py`）とミューテーションテスト
  （`mutate_review.py` / `mutate2_review.py`）を新規に書いて実施した
- 実装者の報告・コメント・rationale は判断材料にしていない。判定はすべて実行結果とコードによる
- 親から確定として渡された 3 点（A-5 は ADR-013 でコメントのみ修正 / B-4 は ADR-014 で仕様維持＋テスト新設 /
  S-2 は JIN012・JIN013 の正典表統合を行わない）は前提として扱い、覆していない

---

## finding 別の判定

| ID | 判定 | 根拠（実行したコマンド・確認したコード） |
|---|---|---|
| A-1 | **defect-gone** | `probe1.py` 再実行 → `after undo: ['t1','t2','t3']` / `byte equal: True`（修正前は `['t2','t3','t1']` / False）。`ops.py` の `_toggle_await` が逆 op に `index` を載せる。`re2.py` 回帰 3 で await 3 要素の先頭・中央・末尾すべて復元。ミューテーション「`inverse["index"] = position` を落とす」→ **検出** |
| A-2 | **defect-gone** | `probe2.py` 再実行 → setGuard / toggleAwait とも `restored bytes equal: True`（修正前は False、差分は `"boundary": {}`）。`ops.py` の `_boundary` が `created` を返し、逆 op に `pruneBoundary` を載せる。`re2.py` 回帰 1 で「元から書かれていた `"boundary": {}` は prune しない」ことも確認。ミューテーション「`_prune_boundary` を常に return」→ **検出** |
| A-3 | **defect-gone** | `probe5.py` 再実行 → 3 件とも `OpError JIN002`（例: `pointer '/circles/0/state/1' の 3 段目は 'tools' である必要があります（実際: 'state'）`）。`ops.py` に `_require_segment` が新設され、`moveTool` / `setState` / `removeGuard` / `setGuard` が呼ぶ。ミューテーション「`_require_segment` を無効化」→ **検出** |
| A-4 | **defect-gone** | `re1.py` → `/circles/0/tools/0/name`・`/circles/0/boundary/guards/0`・`/circles` のいずれも `OpError JIN002`。`ops.py` の `_rename` が各分岐で `_circle_index(doc, op, 2)` / `(..., 4)` とリテラルの期待深さを渡す。ミューテーション「circle 分岐の深さ条件を緩める」→ **検出** |
| A-5 | **defect-gone**（ADR-013 の範囲で） | 決定どおり実装と `ops.md` は不変。`probe3.py` の挙動（全 circle の rune を書き換える）は変わっていない。確認対象のコメントは「**全 circle** の rune 内 `{key}` を追随させる。可視範囲には絞らない（docs/spec/ops.md §3 / ADR-013 DP-JIN-RENAME-SCOPE-01 案 (a)）」に修正済みで、実装とも仕様とも整合する |
| B-1 | **defect-gone** | `probe4.py` 再実行 → `circle 'A' が親 'P' から 2 回参照されています`（修正前は `2 個の親を持っています: P / P`）。`re3.py` で 3 回参照は「3 回参照されています」、別々の親は従来どおり `2 個の親を持っています: F / S`。hint も分岐している。新 fixture `JIN013_same_parent_twice.jin` が 1 コードだけ出す。ミューテーション「同一親分岐を消す」→ **検出** |
| B-2 | **defect-gone** | `re1.py` → 未解決の `exit.key` に `JIN011`（pointer `/circles/0/flow/exit/key`）。`re3.py` で孫 circle が産む key は通り、無関係な circle の同名 key は落ちる。新 fixture `JIN011_exit_key_unresolved.jin`。`diagnostics.md` §4 の優先順位表にも行が追加された（S-2 参照）。ミューテーション「exit.key 検査を無効化」→ **検出** |
| B-3 | **defect-gone** | `re1.py` → sequence に `max` / parallel に `exit` はいずれも `JIN002`（段 2 で停止）。`model.py` の `@model_validator(mode="after") _max_and_exit_are_loop_only`。loop の `max` は通る。新 fixture `JIN002_max_on_sequence.jin`。ミューテーション「バリデータを無効化」→ **検出**。※ 公開スキーマ側の残存は N-3 |
| B-4 | **defect-gone**（ADR-014 の制約充足） | 仕様（`model.md` §5）は不変で、`probe4.py` の `loop-later` も従来どおり診断 0 件。課された制約「loop の兄弟枝可視性を固定するテストの新設」は `packages/jin-core/tests/test_semantic.py:177-220` で満たされている。**トートロジーではない**: 同一形状で loop は `codes(text) == []`、sequence は `== ["JIN050"]`、parallel は `== ["JIN050"]` と 3 者を差分で固定している。ミューテーション「loop 分岐を parallel と同じ扱いにする」→ **検出** |
| B-8 | **defect-gone** | `re1.py` → `rune_keys('{a}}') == ['a']`（修正前は `[]`）。`{{a}}` は `[]`、`{{a}` は `[]` のまま正しい。実装は正規表現から手書きスキャナ `rune_key_spans` に置き換わり、`rune_keys` と `replace_rune_key` が同じ 1 箇所を通る。ミューテーション「旧否定先読み相当に戻す」→ **検出** |
| C-1 | **defect-gone** | `re1.py` で 5 例を再実行。`{"a": @}` は `'@' はここに置けません`、末尾ゴミは `'t' はここに置けません`、BOM 付きは当該文字を指す（修正前は全部「入力の終わり」）。hint も `期待: false, '{', '[', null, 数値, 文字列, true` と JSON レベルの語彙に翻訳され、lark の終端名（LBRACE / LSQB 等）が出なくなった。`parser.py` が `.token` と `.char` の両方を見る。ミューテーション「`.char` 経路を無効化」→ **検出** |
| C-2 | **defect-gone** | `probe5.py` 再実行 → `JinSyntaxError: キー 'a' が同じオブジェクト内で 2 回現れています`。`re3.py` でネストしたオブジェクトでも検出し、配列内の同名キー（別オブジェクト）は正しく通す。range は 2 つ目のキーを指し、hint に 1 つ目の行・列を出す。新 fixture `JIN001_duplicate_key.jin`。ミューテーション「重複検出を無効化」→ **検出** |
| D-1 | **defect-gone** | `surrogate.jin` を作り直して `jin check` / `jin fmt` を実行 → いずれも `JIN002 スキーマ違反（/circles/0/description）: Input should be a valid string`（段 2 で停止）。`fmt` は exit 1 でファイルを触らない（111 バイトのまま）。`model.py` の `_reject_bad_chars` が孤立サロゲートを弾く。**副次確認**: 修正前の `write_text` は書き込み途中で落ちてファイルを 0 バイトに切り詰めていた（今回 `surrogate.jin` が 0 バイトになっていたのがその痕跡）。現在は `_write_atomically` により切り詰めが起きない |
| D-2 | **defect-gone** | CRLF 化した `researcher.jin` に `jin fmt --check` → `差分あり` / exit 1（修正前は exit 0）。`jin fmt` 実行後にファイルは LF になる。`check.py` が `path.open(..., newline="")` で読む。CRLF ファイルの診断位置が LF 版と一致することも確認（どちらも line 4 / col 11-22）。ミューテーション「`newline=""` を外す」→ **検出** |
| D-4 | **未消滅** | `main.py` の `_collect` は修正前とバイト単位で同一（`elif path.exists(): found.append(path)`）。`jin check README.md` は今も `.md` を読んで `JIN001` を出す。severity low だが fix-now バケットで手が入っていない |
| E-1 | **未消滅** | `tests/contract/test_canonical_contract.py` は 197 行で修正前と同一。当該アサーション（86-92 行）は今も「インデント幅が偶数」しか見ておらず、4 スペースにしても**このテストは通る**。ただし `INDENT` を 4 スペースにするミューテーションは `test_canonical.py::test_two_space_indent_and_trailing_newline` / `test_examples_are_already_canonical` / `test_cli.py::test_fmt_rewrites_non_canonical_file` が検出した。**リスクは修正ラウンド以前から存在する別テストが覆っているが、指摘したアサーション自体は修正されていない** |
| E-2 | **未消滅** | 同ファイル 144-148 行も同一。正規表現 `\\u00[2-9a-f][0-9a-f]` は `encode_string` が実際に出しうるエスケープ（U+0000 〜 U+001F、すなわち 3 文字目が 0 か 1）に依然一致しない。非 ASCII をエスケープするミューテーションは `test_canonical.py::test_non_ascii_is_not_escaped` 等が検出したのでリスクは覆われている。アサーション自体は未修正 |
| E-3 | **未消滅** | `tests/contract/test_canonical_contract.py:178` は `@pytest.mark.parametrize("explicit_default", [False])` のまま。1 値のみのパラメタ化で意味を持たない |
| E-5 | **部分消滅（8 項目中 6 項目が解消）** | 解消: UnexpectedCharacters 経路 / boundary 無し circle への setGuard・toggleAwait / 複数要素 await の toggleAwait / op の pointer 経路セグメント誤り / CRLF / 重複 JSON キー / rune のエスケープ境界 / loop 以外の flow の max・exit（いずれも新テストか新 fixture があり、対応するミューテーションが検出された）。**残る穴 2 件**: (1) **BOM のテストが 0 件**（`grep -rn "feff|BOM" tests packages/*/tests` が 0 ヒット。C-1 の修正で挙動は良くなったが固定されていない）。(2) **rename(circle) が `flow.steps` を追随することの検証が無い** — `ops.py` の `flow["steps"] = [new_name if s == old else s ...]` を `pass` に差し替えても **442 テスト全部が緑のまま通る**。`test_rename_circle_follows_all_references` は今も delegate と summon しか見ておらず、`sample()` に flow を持つ circle が無い |
| F-1 | **defect-gone** | `version-matrix.md` §5 行 4 が「JSON 文法は `packages/jin-core/src/jin_core/parser.py` のインライン定数 `JIN_JSON_GRAMMAR` として自作した（`.lark` ファイルは作っていない）」に修正済み。存在しないファイルへの参照は消えた |
| S-1 | **defect-gone** | `ops.md` §1 に「逆オペレーションを当てた結果は、順オペレーションを当てる前の正準形テキストとバイト一致する」が明記され、新設の **§2.1「逆オペレーションが復元しなければならないもの」** 表が toggleAwait（外す）→ `index`、toggleAwait（付ける）/ setGuard（追加）→ `pruneBoundary` を規定。§2 の該当 2 行も「+ 復元条件 §2.1」を参照する |
| S-2 | **defect-gone** | `diagnostics.md` §4 の `diagnostic-precedence` 表に「`flow.exit.key` が可視な state に無い → JIN011」の行が追加された。親の確定どおり §2 の正典表は 12 行のまま、JIN012 / JIN013 は §3 の追加提案表に「人間承認待ち」の警告つきで残っている（統合されていない） |
| S-3 | **defect-gone** | `model.md:115` に「`max` / `exit` を `sequence` / `parallel` に書くのは**スキーマ違反**であり、**段 2 で JIN002 として落とす**」が追記され、落とす段が明記された。実装（B-3）と一致する |
| S-4 | **defect-gone** | `model.md` §6 に「**1 つの pointer は 1 つの値だけを指す**。RFC 8259 は重複キーの扱いを未定義にしているが、Jin は重複キーを段 1 の構文エラー（JIN001）として落とす」が追記され、C-2 の実装と整合した |
| S-6 | **defect-gone** | `layout.md:55` が「例: n=5 → k=2（{5/2}）、n=6 → k=1、n=7 → k=3、n=8 → k=3、n=9 → k=4」に修正され、57 行目に「n=6 の内訳: `2*j < 6` を満たす候補は `j = 1, 2` だけである（`j = 3` は `2*3 < 6` が偽…）」と探索範囲の説明が追加された |

---

## 修正が入れた新規欠陥

```
N-1 [high / confidence 100] jin fmt がファイルのパーミッションを 0600 に落とす
packages/jin-cli/src/jin_cli/main.py:100-118（_write_atomically）
tempfile.mkstemp は 0600 でファイルを作り、os.replace は一時ファイルの mode をそのまま
持ち込む。修正前の write_text は既存 inode を truncate していたので mode が保存されていた。
実測: fmt 前 644 -> fmt 後 600 / fmt 前 664 -> fmt 後 600。
差分が無いファイル（書き換えが起きない場合）は 644 のまま。
共有チェックアウトや CI・配布アーカイブで group / other の読み取りが黙って失われる。
再現:
  cp examples/pipeline/pipeline.jin /tmp/m.jin && chmod 644 /tmp/m.jin
  # 正準形から 1 文字ずらしてから
  jin fmt /tmp/m.jin && stat -f "%Lp" /tmp/m.jin   # -> 600
修正案: os.replace の直前に、対象が存在するときだけ
  os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
テストが素通りする理由: fmt の書き込み後に mode を検査するテストが 0 件
補足（問題なし）: シンボリックリンクは jin fmt が「シンボリックリンクなので整形しません」で
  明示的に拒否するため、リンクが実体ファイルに置き換わる問題は起きない（実測確認済み）
```

```
N-2 [medium / confidence 95] 新設した文字種バリデーションが docs/spec/model.md に載っておらず、§7 の記述と矛盾する
packages/jin-core/src/jin_core/model.py:40-81（_reject_bad_chars / _validate_ident / _validate_text / Ident / Text）
docs/spec/model.md:226-229（§7 のエスケープ規則）
修正ラウンドで、Ident（name / ref / root など）は制御文字を一切許さず、Text（rune / description）は
改行・復帰・タブだけを許し、DEL（U+007F）・C1（U+0080-U+009F）・孤立サロゲートを段 2 の
JIN002 で弾くようになった。この制約は model.md にも diagnostics.md にも書かれていない
（grep で該当記述 0 件）。さらに model.md §7 は今も
  「制御文字のうち \b \f \n \r \t は 2 文字表記、それ以外は \uXXXX。
   U+007F（DEL）および U+0080 以上はエスケープしない」
と、**モデルが受け付けなくなった文字の書き出し規則**を正典として書いている。
model.md は Phase 2〜6 と LLM が参照する正典なので、実装と食い違ったまま残すと後段が誤読する。
再現: grep -n "制御文字|孤立サロゲート" docs/spec/*.md -> model.md:228 の 1 行だけ（§7 の旧記述）
修正案: §3 の表か §1 に「使える文字」の節を足し、§7 の到達不能になった記述を
  「段 2 で弾かれるのでここには来ない」と整理する
```

```
N-3 [low / confidence 90] 公開スキーマが新しい制約を表現しない（元 finding D-3 の拡大）
schemas/jin.schema.json
maxLength（Ident 128 / Text 65536 / URL 2048）は JSON Schema に出力されている
（実測: Circle.name に maxLength: 128、Instruction.rune に maxLength: 65536）が、
次の 2 つは出ていない:
  - N-2 の文字種制約（AfterValidator なのでスキーマに落ちない）
  - B-3 の「max / exit は loop のみ」（model_validator なのでスキーマに落ちない。
    実測: $defs.Flow のキーは additionalProperties / properties / required / title / type
    だけで、if / then / allOf / dependentSchemas は無い）
$schema を頼りに外部ツールや LLM が検証して通した .jin が jin check で JIN002 になる。
要件書 成功条件 3（Schema と診断だけで直しきれる）に対する穴で、元 finding D-3（fix-later）と同種。
B-3 自体は jin check 側で解消しているので、これは残余として報告する。
```

---

## 追加テストの質（独立ミューテーションテストによる評価）

修正が「テストを増やしただけ」でないことを確かめるため、**レビュー側で独自に**修正箇所を 1 つずつ
差し戻して 442 テストが落ちるかを見た（`mutate_review.py` / `mutate2_review.py`。適用 → pytest →
`finally` で復元）。

| ミューテーション | 結果 |
|---|---|
| `_require_segment` を無効化（A-3） | 検出 |
| `toggleAwait` の逆 op から `index` を落とす（A-1） | 検出 |
| `_prune_boundary` を常に return（A-2） | 検出 |
| `rename(circle)` の深さ条件を緩める（A-4） | 検出 |
| JIN013 の同一親分岐を消す（B-1） | 検出 |
| `flow.exit.key` 検査を無効化（B-2） | 検出 |
| rune の `{a}}` 対応を旧実装に戻す（B-8） | 検出 |
| Flow の `model_validator` を無効化（B-3） | 検出 |
| lark の `.char` 経路を無効化（C-1） | 検出 |
| 重複キー検出を無効化（C-2） | 検出 |
| `newline=""` を外す（D-2） | 検出 |
| 正準形のインデントを 4 スペースへ | 検出 |
| 正準形が非 ASCII をエスケープするように | 検出 |
| 正準形の既定値省略をやめる | 検出 |
| JIN050 の loop 分岐を parallel と同じ扱いに（B-4 / ADR-014） | 検出 |
| **`rename(circle)` が `flow.steps` を追随しないように** | **見逃し（442 全部緑）** |
| `rename` の tools 分岐条件を `>= 4` に緩める | 見逃し（**振る舞いが変わらないので正常**。分岐内の `_circle_index(doc, op, 4)` が引き続き弾く） |
| A-4 のエラーメッセージ文言だけを変える | 見逃し（**文言を検査するテストが無いだけで正常**。振る舞いを変えるミューテーションでは検出された） |

意味のある 16 本のうち **15 本が検出、見逃しは 1 本**（E-5 に計上した rename から `flow.steps` への追随）。

### トートロジー・自明に真になる assert の走査

- AST 走査（同一式どうしの比較・定数 assert）で引っかかったのは **1 件のみ**:
  `packages/jin-cli/tests/test_cli.py:173` の `run("dump", path).output == run("dump", path).output`。
  これは修正ラウンド以前から存在し、同一プロセス内の比較なので辞書順序依存を検出できない。
  ただし `tests/contract/test_cli_contract.py` に `PYTHONHASHSEED` を変えた別プロセス 2 回の
  強いテストがあるので実害は無い。
- `assert ... is not None` は 15 箇所あるが、すべて型の絞り込みで直後に実質的な検査が続く。
- 新テストの期待値は**実装の出力を写したものではなく、リテラルの期待値**で書かれている。
  例: `test_toggle_await_inverse_restores_the_original_order` は `["t1","t2","t3"]` を直書きし、
  さらに事前に捕っておいた `original` とのバイト比較で締めている。
  `test_an_explicitly_written_empty_boundary_is_not_pruned` は「作っていない `{}` は消さない」という
  逆側のケースを固定していて、`pruneBoundary` の判定が「空かどうか」ではなく「作ったかどうか」で
  あることを検査している。
- ADR-014 の新テストは差分テストとして成立している（同一形状で loop = 診断なし / sequence =
  JIN050 / parallel = JIN050）。実装をなぞった期待値ではない。

### 回帰確認（新規に書いたプローブ）

- `moveTool` の src と dst の全 9 通りで逆 op がバイト一致復元（`re2.py`）
- 3 オペレーション列 → 逆 op 列で元の正準形へ復帰、undo -> redo -> undo も安定
- 元から `"boundary": {}` が書かれたファイルで toggleAwait の逆 op が `{}` を消さない
- guards が残っているうちは `boundary` が畳まれない
- fixture 18 件すべてが対応コードをちょうど 1 つだけ出す（新 fixture 4 件を含む）
- examples 2 本は診断 0 件、`jin fmt --check examples` exit 0、`jin schema` はコミット済み
  `schemas/jin.schema.json` とバイト一致
- CRLF ファイルの診断位置が LF 版と完全一致（line 4 / col 11-22）
- `jin check --resolve` は `check_file` のシグネチャ変更（`resolve` → `resolver` / 新 `resolver.py`）後も
  JIN040 を正しく出す

---

## 作業ツリーへの変更

**残していない。**

ミューテーションテストのため `ops.py` / `semantic.py` / `model.py` / `parser.py` / `check.py` /
`canonical.py` / `main.py` を一時的に書き換えたが、いずれもハーネスの `finally` とバックアップからの
`cp` で復元した。復元の証拠:

- ミューテーション痕跡の grep（`if False:` / `RENAME-UNREACHABLE` / 4 スペースの `INDENT` など）が **0 ヒット**
- `diff` で `canonical.py` と `ops.py` がバックアップと一致
- **442 passed**（修正ラウンド完了直後と同数・同結果）
- `jin schema` がコミット済み `schemas/jin.schema.json` とバイト一致
- `jin check examples` / `jin fmt --check examples` がともに exit 0
- `git status` の tracked 変更は `delivery/.../auto-decisions.json` / `auto-decisions.md` /
  `design.yaml` / `implement-ledger.md` と `docs/pending-decisions.md` の 5 件のみで、
  これは修正ラウンドの成果物であり本レビュー開始時点と同一

新規に作成したのは本ファイル（`code-review-raw/correctness-round1.md`）だけ。検証スクリプトと
一時ファイルは `/Users/toyota/.claude/jobs/8b3a6b62/tmp/` 配下（`re1.py` / `re2.py` / `re3.py` /
`mutate_review.py` / `mutate2_review.py` / `crlf2.jin` / `surrogate.jin`）に置いた。`/tmp/jinre` と
`/tmp/jinsym` は検証後に削除済み。

なお前ラウンドの `surrogate.jin` は**開始時点で 0 バイトになっていた**。これは前回 D-1 を再現した
ときに旧 `write_text` が書き込み途中で落ちてファイルを切り詰めた痕跡であり、D-1 が
「クラッシュするだけでなくファイルを破壊していた」ことの追加証拠になる。現在は `_write_atomically`
により切り詰めは起きない（同ファイルを作り直して確認済み）。

---

## 次ラウンドへの申し送り（優先順）

1. **N-1** — `jin fmt` のパーミッション保存。1 行（`os.chmod`）で直る割に影響が広い
2. **E-5 の残り 2 件** — rename(circle) が `flow.steps` を追随することのテスト（現状ミューテーションが
   素通りする実質未検証の経路）と、BOM の fixture
3. **N-2** — `model.md` に文字種制約を書く / §7 の到達不能な記述を整理する
4. **D-4 / E-1 / E-2 / E-3** — いずれも low。E-1 / E-2 は「弱いアサーションを強い形に書き直す」だけ
5. **N-3** — 公開スキーマと `jin check` の乖離（元 D-3 と束ねて扱うのが妥当）
