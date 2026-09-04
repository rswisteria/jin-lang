# 再レビュー（修正ラウンド 2）— correctness

## Summary

- 確認対象: **7 項目**（未消滅 4 件 D-4 / E-1 / E-2 / E-3 + 部分消滅 1 件 E-5 の残り 2 項目 + 新規欠陥 N-2 / N-3）
- 判定: **defect-gone 7 / 未消滅 0 / 判定不能 0**
- 修正が入れた新規欠陥: **0 件**（機能面）。ただしテスト側に**軽微な指摘 2 件**（R2-1 / R2-2、いずれも low・機能には影響しない）
- 追加テストの質: **問題なし**。独立ミューテーション 12 本すべて検出。AST 走査で常に真の assert は 2 件（1 件は R2-1、1 件はラウンド 1 から既知）
- 作業ツリー: **復旧済み**（491 passed / `jin schema` バイト一致 / tracked 差分はレビュー開始時と同一）

### 検証条件

- テスト実行: **491 passed in 3.76s**（`.venv/bin/python -m pytest -p no:cacheprovider -o addopts="" -q`）
- 実装者の報告は判断材料にしていない。**親から渡された期待も含めて**すべて実行結果で確かめた
  （結果として親の期待 1 件が実測と食い違ったので R2-2 に記した）
- 確定事項（A-5 → ADR-013 / B-4 → ADR-014 / JIN012・JIN013 の正典表と提案表の分離）は
  前提として扱い、覆していない。分離の維持は再確認済み（下記）

---

## 対象 7 項目の判定

| ID | 判定 | 根拠（実行したコマンド・確認したコード） |
|---|---|---|
| **D-4** | **defect-gone** | `jin check README.md` / `jin dump README.md` とも `'.jin' ではありません: README.md（Jin が読むのは拡張子 .jin のファイルだけです）` で **EXIT=2**。正常な `.jin` と `jin check examples`（ディレクトリ走査）は従来どおり exit 0。検査は 2 箇所に入っている（`main.py:69` の `_collect` と `main.py:313` の `dump` 専用経路）。ミューテーション: `_collect` 側を外すと `test_named_non_jin_file_is_rejected[check]` / `[fmt]` が赤、`dump` 側を外すと `test_dump_rejects_a_non_jin_file` が赤 |
| **E-1** | **defect-gone** | `test_rule1_indent_is_two_spaces` が `assert indent == depth * 2` に強化され、`assert INDENT == "  "` と `assert checked > 0` が付いた。**深さは括弧の開閉から求めており（`_lines_with_depth`）、インデント幅から逆算していないので循環していない**。ミューテーション `INDENT` を 4 スペースへ → **9 テストが赤**（うち本件の当該テストを含む）。※ 親の期待とは別のテストが捕まえている点は R2-2 参照 |
| **E-2** | **defect-gone** | 空虚だった `\\u00[2-9a-f][0-9a-f]` が「現れる `\uXXXX` はすべて U+0020 未満である」という writer の出力集合に触れる形に置き換わり、`test_rule5_escapes_only_control_characters` が `encode_string` を直接呼んで `codes == [0x01, 0x1F]` を固定する。**両方向で効く**: 非 ASCII もエスケープする変異 → 10 テスト赤（新旧両テストを含む）、制御文字をエスケープしない変異 → 2 テスト赤 |
| **E-3** | **defect-gone** | `@pytest.mark.parametrize(("written_value", "should_be_dropped"), [(False, True), (True, False)])` の 2 値になり、既定値は消え、既定でない `out: true` は残ることを別々に固定している。ミューテーション「既定でない値まで省く」→ **50 テスト赤**（うち `test_rule7_roundtrip_drops_explicit_defaults[True-False]` を含む）。両方の脚が実際に通っていることを確認 |
| **E-5 (a) BOM** | **defect-gone** | fixture `tests/fixtures/errors/JIN001_utf8_bom.jin` が実バイト `EF BB BF` で始まる（188 バイト）。**19 fixture すべてが対応コードをちょうど 1 つだけ出す**ことを再検査（不一致 0）。診断は `1:1 error JIN001: 先頭に BOM（U+FEFF）があります` / hint `期待: BOM なしの UTF-8。エディタの保存設定を「UTF-8（BOM なし）」にしてください`。`jin fmt` は exit 1 で **BOM を残したままファイルを書き換えない**（頼まれていないバイト変更をしない）。文字列**中**の U+FEFF は普通の文字として通る。ミューテーション「先頭 BOM 検出を外す」→ 2 テスト赤 |
| **E-5 (b) rename → flow.steps** | **defect-gone** | `ops.py:452` の `flow["steps"] = [...]` を `pass` にする変異で `test_rename_circle_follows_flow_steps` と `test_rename_circle_follows_summon` の **2 件が赤**（ラウンド 1 では 442 件全緑だった）。親の報告と一致 |
| **N-2** | **defect-gone** | `model.md` §3.6（`machine-readable: string-constraints`）を**実装と 1 フィールドずつ突き合わせて検証**した（下記の表）。18 フィールドすべてで、長さ上限ちょうどは通り +1 で JIN002、識別子は改行を拒否・自由記述は改行を許容、ESC と孤立サロゲートは全種別で拒否。§7 には「受理範囲との関係」の注記が入り、writer 規則がモデルの受理範囲より広い理由（`dumps` を検証なしで直接呼ぶ経路のため）と、**writer も孤立サロゲートだけは明示的に拒む**ことが書かれている。この最後の主張も実測で真（`encode_string("a\ud800b")` → `ValueError: JSON 文字列に孤立サロゲート U+D800 が含まれています`）。ミューテーション 4 本すべて検出 |
| **N-3** | **defect-gone** | `model.md` §3.7（`machine-readable: schema-gaps`）の 5 行すべてが実在する検出手段に対応することを確認（下記）。**捏造が無いこと**も現物で確認: 生成スキーマの検証キーワードは `anyOf / oneOf / const / enum / maxLength / minimum` だけで、`pattern` / `if` / `then` / `allOf` / `dependentSchemas` は 1 つも無い |

---

## N-2 の検証: §3.6 の表 vs `model.py:40-81`

各フィールドに対して「制御文字（改行）」「ESC」「孤立サロゲート」「上限ちょうど」「上限 +1」の
5 パターンを流し、表の記述どおりかを判定した（`/Users/toyota/.claude/jobs/8b3a6b62/tmp/n2.py`）。

| 種別 | 検査したフィールド | 結果 |
|---|---|---|
| 識別子（改行不可・128） | `root` / `circles[].name` / `core` / `tools[].name` / `tools[].ref` / `tools[].builtin` / `tools[].circle` / `state[].name` / `state[].type` / `flow.steps[]` / `flow.exit.key` / `delegate[]` / `boundary.await[]` / `guards[].ref` | **14 件すべて OK** |
| 自由記述（改行可・65536） | `description` / `instruction.rune` / `flow.exit.equals`（文字列のとき） | **3 件すべて OK** |
| URL（改行不可・2048） | `$schema` | **OK** |

表に載っていない文字列フィールドが無いことは `test_string_constraints_table_lists_every_string_field` が
Pydantic モデルを走査して機械的に担保している（`Circle` に未記載の文字列フィールドを足す変異で赤くなることを確認）。

上限値そのものは `test_string_constraints_table_matches_the_implementation` が
`MAX_IDENT_LENGTH` / `MAX_TEXT_LENGTH` / `MAX_URL_LENGTH` を **import して**表と比べているので、
値をずらす変異（128 → 256）で赤くなる（実測）。ドリフトしようがない結び方になっている。

---

## N-3 の検証: §3.7 の各行が実在する検出手段に対応するか

| §3.7 の行 | 主張 | 実測 |
|---|---|---|
| §3.6 の文字種（制御文字・孤立サロゲート） | JIN002 / 段 2 | **一致**（上表 18 フィールドで確認） |
| `max` / `exit` は `kind: loop` のときだけ | JIN002 / 段 2 | **一致**（fixture `JIN002_max_on_sequence.jin` が JIN002 を 1 件だけ出す） |
| 同一オブジェクト内のキーの重複 | JIN001 / 段 1 | **一致**（fixture `JIN001_duplicate_key.jin`） |
| 入れ子の深さ上限（64 段） | JIN001 / 段 1 | **一致**（深さ 64 は段 1 を通過し段 2 へ、深さ 65 で `JIN001: 入れ子が深すぎます（上限 64 段）`） |
| 名前の一意性・参照の解決・要素数・rune の `{key}` | JIN010〜JIN070 の 12 コード / 段 3 | **一致**（12 コードすべてが `ALL_CODES` に実在し、19 fixture が全コードを網羅） |

`test_schema_gaps_are_consistent_with_the_diagnostic_tables` が表中の `JINxxx` を `ALL_CODES` と
突き合わせ、`test_generated_schema_really_lacks_the_conditional_constraints` が
「スキーマに `if` / `allOf` が無い」「`maxLength` を持つプロパティに `pattern` が無い」を現物で確認している。
**「表現できないものを表現できているかのように書かない」という方針が、テストで固定されている**。

### 確定事項の維持

- 要件書 `jin-requirements.md` §2.4 は **12 行のまま未編集**（tracked 差分なし）
- `diagnostics.md` は §2 正典表 12 行 / §3 追加提案表 2 行（JIN012・JIN013）で分離を維持し、
  「まだ人間が承認していない」の警告も残っている
- A-5（`ops.py` のコメントのみ修正・挙動不変）、B-4（現仕様維持 + 兄弟枝可視性テスト）も変更なし

---

## 独立ミューテーションテスト（ラウンド 2 分）

| ミューテーション | 結果 | 赤くなったテスト |
|---|---|---|
| `INDENT` を 4 スペースへ（E-1） | 検出 | 9 件（`test_rule1_indent_is_two_spaces` 他） |
| 非 ASCII もエスケープする（E-2） | 検出 | 10 件（`test_rule5_non_ascii_is_not_escaped` / `test_rule5_escapes_only_control_characters` 他） |
| 制御文字をエスケープしない（E-2 逆方向） | 検出 | 2 件 |
| 既定でない値まで省く（E-3） | 検出 | 50 件（`...[True-False]` を含む） |
| `rename` が `flow.steps` を追随しない（E-5b） | 検出 | 2 件 |
| 先頭 BOM の検出を外す（E-5a） | 検出 | 2 件 |
| `_collect` の拡張子検査を外す（D-4） | 検出 | 2 件 |
| `dump` の拡張子検査を外す（D-4） | 検出 | 1 件 |
| `MAX_IDENT_LENGTH` を 128 → 256（N-2） | 検出 | 4 件 |
| 表に無い文字列フィールドを `Circle` に足す（N-2） | 検出 | 5 件 |
| 識別子でも改行を許す（N-2 の 4 列目） | 検出 | 2 件（`test_identifiers_reject_every_control_character`） |
| writer の孤立サロゲート拒否を外す（§7 の主張） | 検出 | 1 件 |

**12 本すべて検出。見逃し 0。**

### 回帰確認（ラウンド 1 のプローブ再実行）

- `toggleAwait` の逆 op が await 3 要素の先頭・中央・末尾すべてでバイト一致復元
- 明示的な `"boundary": {}` が prune されない / guards が残るうちは畳まれない
- `moveTool` の src × dst 全 9 通りで復元
- 19 fixture すべてが対応コードをちょうど 1 つ
- `jin check examples` / `jin fmt --check examples` exit 0、`jin schema` はコミット済みファイルとバイト一致
- CRLF ファイルに `jin fmt --check` が exit 1

### トートロジー走査（491 テスト全体・AST）

常に真になる assert は **2 件のみ**。いずれも機能検査を弱めてはいない（下記 R2-1 / 既知の 1 件）。
新テストの期待値は実装の出力を写したものではなく、リテラル（`codes == [0x01, 0x1F]`、
`limits == {識別子: MAX_IDENT_LENGTH, ...}`）または import した定数との突合で書かれている。

---

## 軽微な指摘（機能欠陥ではない・いずれも low）

```
R2-1 [low / confidence 100] E-2 の修正で常に真の assert が 1 つ入った
tests/contract/test_canonical_contract.py:226
test_rule5_non_ascii_is_not_escaped の末尾が `assert checked >= 0`。
checked は加算のみのカウンタなので常に真で、何も守っていない。
同じファイルの test_rule1_indent_is_two_spaces は `assert checked > 0` を使っており不揃い。
意図は「検査対象が 0 件のまま緑にならないこと」だと読めるので `> 0` が正しい。
ただし本テストには別途 `assert non_ascii, "非 ASCII を含む正準形が 1 件も無い..."` があり、
「空振りで緑になる」ことは実質防げているので、実害はない。
```

```
R2-2 [low / confidence 100] test_rule1_detects_a_wider_indent_unit は INDENT の変異を検出しない
tests/contract/test_canonical_contract.py:135-150
親からの依頼文には「INDENT を 4 スペースに変える変異で test_rule1_detects_a_wider_indent_unit が
赤くなるか」とあったが、**実測では赤くならない**（赤くなる 9 件に含まれない）。
理由: このテストは dumps() の出力を取ってから自前で「既存インデントを 2 倍にした」テキストを
組み立て、その自作テキストに対して検査ロジックが差を見つけることだけを見ている。
INDENT が 4 になれば widened は 8 になり、depth*2 との差は依然として出るので通ってしまう。
E-1 の実効的なガードは強化された test_rule1_indent_is_two_spaces（`indent == depth * 2` と
`assert INDENT == "  "`）であり、そちらは確かに赤くなる。
よって **E-1 は defect-gone** で、本項はテストの名前が示唆する保護と実際の守備範囲のずれ。
検査ロジック自体の自己検証としては有効なので、削除ではなく名前かコメントの調整で足りる。
```

### 参考（欠陥ではない観察）

- **`.JIN`（大文字拡張子）と拡張子なしのファイルは D-4 の検査で拒否される。** `path.suffix != ".jin"`
  の厳密比較による。`model.md` §1 が拡張子を `.jin` と定めており、メッセージも具体的なので
  仕様どおりの挙動と判断した。大文字小文字を許すかは仕様判断であり、実装の誤りではない
- **§3.6 の表の 4 列目「許す制御文字」だけは、表と実装を直接結ぶテストが無い**（上限値と
  フィールド網羅は結ばれている）。ただし挙動側は `test_identifiers_reject_every_control_character` が
  固定しており、`allow_whitespace` をずらす変異は検出される。表と挙動の対応は今回手作業で
  18 フィールド分を確認済みで一致していた
- **§3.7 の「形と `maxLength` しか表現しない」という散文は厳密には少し狭い**。生成スキーマには
  `minimum: 1`（`Flow.max` の `ge=1`）と `const` / `enum` も出ている。表の 5 行の内容は正しいので
  実害は無いが、散文を直すなら「形と長さ・数値範囲・列挙まで」が正確

---

## 作業ツリーへの変更

**残していない。**

ミューテーションのため `canonical.py` / `model.py` / `parser.py` / `ops.py` / `main.py` を
一時的に書き換えたが、すべてハーネスの `finally` とバックアップからの `cp` で復元した。

- ミューテーション痕跡の grep（`if False:` / `elif False:` / 4 スペースの `INDENT` /
  `MAX_IDENT_LENGTH = 256` / `undocumented_note`）が **0 ヒット**
- `_validate_ident` が改行を拒否することを実行して確認（変異が残っていないことの直接確認）
- **491 passed**（修正ラウンド完了直後と同数・同結果）
- `jin schema` がコミット済み `schemas/jin.schema.json` とバイト一致
- `jin check examples` / `jin fmt --check examples` がともに exit 0
- `git status` の tracked 変更は `delivery/.../auto-decisions.json` / `auto-decisions.md` /
  `design.yaml` / `implement-ledger.md` と `docs/pending-decisions.md` の 5 件のみで、
  本レビュー開始時点と同一

新規作成は本ファイルのみ。検証スクリプトは `/Users/toyota/.claude/jobs/8b3a6b62/tmp/` 配下
（`n2.py` / `mut_r2.py` / `mut_r2b.py`、およびラウンド 1 の `re1.py` 〜 `re3.py` / `probe1.py` 〜 `probe5.py`）。

---

## 申し送り

correctness 観点で **fix-now バケットに残る項目は無い**。R2-1 / R2-2 は次の機会でよい程度の
軽微なもので、いずれも「テストが緑になる条件」を緩めていない。

fix-later として据え置かれている B-5 / B-6 / B-7 / C-3 / D-3（および N-3 の残余としての
公開スキーマと `jin check` の乖離）は今回も対象外であり、未修正のままで正常である。
