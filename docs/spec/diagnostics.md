# 診断コード一覧（diagnostics.md）

> 正典。要件書 `jin-requirements.md` §2.4 / §5 の実装仕様。
> 診断メッセージは「何が悪いか + どう直すか」を必ず含める。`hint` は LLM がそのまま編集に使うので**具体値**にする（NFR-LLM-001）。

## 0. この文書の読み方（機械可読の約束）

`tests/spec/test_spec_consistency.py` が
§2 の表（正典コード）が要件書 §2.4 の 12 件と**過不足なく一致**すること、
§3 の表（追加提案コード）が `{JIN012, JIN013}` であることを検証する。
`<!-- machine-readable: ... -->` マーカー付きブロックの書式を変えない。

**正典コードと追加提案コードを 1 つの表に混ぜてはならない。** design.yaml の Phase 0 machine 条件が
「§2.4 の 12 件と過不足なく一致」を要求する一方、DP-JIN-SEMANTIC-GAPS-01 が本文書での 2 件追加採番を
要求しており、両立させるために表を分けている。

## 1. 診断の実行段階（パイプライン）

<!-- machine-readable: diagnostic-stages -->

| 段 | 名前 | 出しうるコード | 前段が失敗したら |
|---|---|---|---|
| 1 | JSON 構文 | JIN001 | — |
| 2 | スキーマ | JIN002 | 段 1 に error があれば実行しない |
| 3 | 意味 | JIN010 / JIN011 / JIN012 / JIN013 / JIN020 / JIN022 / JIN030 / JIN031 / JIN040 / JIN050 / JIN060 / JIN070 | 段 2 に error があれば実行しない |

<!-- /machine-readable -->

段 3 の中では全チェックを実行し、検出した診断をすべて返す（1 件目で止めない）。

JIN002 の検出器は **Pydantic に一本化**する（ADR-006 / DP-JIN-POINTER-RANGE-01）。
`schemas/jin.schema.json` は外部 JSON ツールと LLM 向けの公開契約であり、内部検証には使わない。
同じ違反に複数のメッセージ形式を生む検証器を併用しない。

## 2. 正典コード（要件書 §2.4 の 12 件）

<!-- machine-readable: diagnostics-canonical -->

| コード | 重大度 | 内容 | 修正ヒント |
|---|---|---|---|
| JIN001 | error | JSON 構文エラー | 位置と期待トークン |
| JIN002 | error | スキーマ違反（必須キー欠落・未知キー・型不一致・enum 外） | JSON Pointer と許容値 |
| JIN010 | error | 名前の重複（circle/tool/state） | 重複した名前と、その名前を持つ 2 つ目の要素の pointer |
| JIN011 | error | 未解決の参照（summon / delegate） | 候補名を提示（編集距離） |
| JIN020 | error | `tools` または `state` が 12 を超えた | 「サブ陣に抽出」のコードアクション |
| JIN022 | error | `core` と `flow` の両立、または両方欠落 | どちらを消す／足すか |
| JIN030 | error | `flow.kind = loop` に `max` も `exit` もない | `max: 5` を追加 |
| JIN031 | error | `flow.steps` の要素が circle でない | 候補名を提示（編集距離） |
| JIN040 | warning | Python 参照が import できない（`--resolve` 指定時のみ） | import に失敗した理由 |
| JIN050 | error | rune 内 `{key}` が自 circle または flow 上流 circle の state に無い | 可視な state key の一覧 |
| JIN060 | error | `root` が存在しない circle を指す | 候補名を提示（編集距離） |
| JIN070 | warning | `await` 対象が `tools` に無い | 自 circle の tool 名の一覧 |

<!-- /machine-readable -->

JIN002（スキーマ違反）が段 2 で拾う範囲には、`docs/spec/model.md` §3.6 の**文字列の制約**
（長さ上限・制御文字・孤立サロゲート）と §3.4 の **`max` / `exit` の loop 限定**が含まれる。
どちらも `schemas/jin.schema.json` には現れない（同 §3.7）。

要件書 §2.4 の JIN011 行は「未解決の参照（summon / delegate / steps / await / `{key}`）」と
5 種を括弧で列挙しているが、`steps` / `await` / `{key}` にはそれぞれ JIN031 / JIN070 / JIN050 という
**専用のコードが同じ表に存在する**。要件書 §9 の「fixture は対応コードを 1 つだけ出す」を成立させるため、
§4 の優先順位表で「専用コードが勝つ」と規定した。本表の JIN011 の「内容」列はその結論を反映している。

## 3. 追加提案コード（ADR-007 / DP-JIN-SEMANTIC-GAPS-01・**人間承認待ち**）

> ⚠️ **これは要件書 §2.4 への追加提案であり、まだ人間が承認していない**（DP-JIN-SEMANTIC-GAPS-01 は
> `ai_provisional` / `pending_human_review`。同 DP の `constraints[]` に「要件書 §2.4 の診断コード表への追加であり、
> 仕様変更として人間の承認を要する」と明記されている）。PR レビューで承認されるまで暫定である。

<!-- machine-readable: diagnostics-proposed -->

| コード | 重大度 | 内容 | 修正ヒント |
|---|---|---|---|
| JIN012 | error | 参照が循環している（summon / delegate / flow.steps の有向グラフに閉路がある） | 閉路を構成する circle 名の並び |
| JIN013 | error | circle が複数の親を持つ（`flow.steps` / `delegate` からの親子辺の入次数が 2 以上） | 親になっている circle 名の一覧 |

<!-- /machine-readable -->

### 3.1 採番の根拠（DP-JIN-SEMANTIC-GAPS-01 の限定句「空き番号への採番は本文書で決定し根拠を残す」への回答）

要件書 §2.4 のコードは **10 の位で関心事がブロック化**されている:

| ブロック | 関心事 | 既存 |
|---|---|---|
| 00x | 入力そのものの妥当性（構文・スキーマ） | JIN001, JIN002 |
| 01x | **名前と参照の整合性** | JIN010（名前の重複）, JIN011（未解決の参照） |
| 02x | circle 単体の形（要素数・核と flow の排他） | JIN020, JIN022 |
| 03x | flow 自身の妥当性 | JIN030, JIN031 |
| 04x | 外部（Python）への解決 | JIN040 |
| 05x | rune 内テンプレート | JIN050 |
| 06x | root | JIN060 |
| 07x | await | JIN070 |

追加する 2 件はいずれも「circle 名で張られた**参照グラフ全体の整合性**」の問題である。

- **循環参照**は「解決はできるが参照関係が閉じている」状態であり、JIN011（解決できない）の隣に置くのが自然
- **多重親**は「同じ circle が 2 箇所から親子辺で参照されている」状態であり、これも参照グラフの性質

よって **01x ブロックの空き番号**に採る。01x の既使用は JIN010 / JIN011 のみで JIN012〜JIN019 が空いている。
若い順に **JIN012 = 循環参照**、**JIN013 = 多重親** とした。

03x（flow）に採らなかった理由: 多重親は `delegate`（flow ではない）でも起きるため、
flow ブロックに置くと関心事の対応が崩れる。循環参照も `summon` を含むため同様。

## 4. コードの優先順位（同じ違反に複数のコードが該当しうる場合）

**より具体的なコードが勝つ。** 1 つの違反に対して 1 つのコードだけを出す。

<!-- machine-readable: diagnostic-precedence -->

| 状況 | 出すコード | 出さないコード |
|---|---|---|
| `flow.steps[]` の要素が既知の circle 名でない | JIN031 | JIN011 |
| `root` が既知の circle 名でない | JIN060 | JIN011 |
| `boundary.await[]` の要素が自 circle の tool 名に無い | JIN070 | JIN011 |
| rune 内 `{key}` が可視な state に無い | JIN050 | JIN011 |
| `tools[kind=summon].circle` が既知の circle 名でない | JIN011 | — |
| `delegate[]` の要素が既知の circle 名でない | JIN011 | — |
| `flow.exit.key` が可視な state に無い | JIN011 | — |

<!-- /machine-readable -->

これにより JIN011 の実効的な守備範囲は **summon / delegate / `flow.exit.key` の 3 種**になる。

`flow.exit.key` を JIN011 に入れる根拠: `docs/spec/ops.md` §3 の `rename` は `flow.exit.key` を
**state 名の参照**として追随させている。追随させる以上、解決できないときに黙るのは一貫しない。
JIN030（loop に `max` も `exit` も無い）は有無しか見ないので、この違反を拾えない。
`exit.key` の可視範囲は「自 circle から見える state（`docs/spec/model.md` §5）+ `steps[]` 各要素の部分木の state」。
loop 本体が作る state を終了条件に使うのが通常の書き方だからである。

## 5. 診断 JSON の形式（要件書 §5 / FR-CLI-002）

```json
{"file": "a.jin", "pointer": "/circles/0/tools/2/circle",
 "range": {"start": {"line": 12, "col": 40}, "end": {"line": 12, "col": 52}},
 "code": "JIN011", "severity": "error",
 "message": "circle 'Summarizr' は定義されていません",
 "hint": "近い名前: Summarizer"}
```

`jin check --json` は上記オブジェクトの配列を stdout に出す。error が 1 件以上あれば exit 1。

### 5.1 行・列の基点（DP-JIN-POINTER-RANGE-01 の追加確定値）

要件書 §5 の例は `{"line": 12, "col": 40}` と書いているだけで**基点を規定していない**。
`lsp-api-probe.md` §3 が「lark は 1 始まり / LSP は 0 始まり。どちらを採るか実装時に決めて根拠を残すこと」と
指摘している。本文書で次のとおり確定させる。

<!-- machine-readable: position-base -->

| 項目 | 決定 |
|---|---|
| `range.start.line` / `range.end.line` の基点 | **1 始まり** |
| `range.start.col` / `range.end.col` の基点 | **1 始まり** |
| `range.end` の含み方 | **排他**（end は「最後の文字の次」を指す） |
| 列の数え方 | **Unicode コードポイント単位** |

<!-- /machine-readable -->

根拠:

1. **フィールド名が LSP と違う。** 要件書は `col` と書いており、LSP の `Position` は `character` である
   （`lsp-api-probe.md` §1 で実測）。名前を変えている以上、LSP の座標をそのまま載せる意図ではなく
   Jin 固有の表現とみなすのが素直な読み方である
2. **lark がネイティブに 1 始まり**（実測: `'{"a": "xy"}'` の `"a"` が `L1C2-L1C5`）。
   パーサの値をそのまま使えば、変換の抜け漏れによるオフバイワンが構造的に起きない
3. **`jin check` は人と LLM が直接読む出力**である。ruff / mypy / gcc など既存のコンパイラ・リンタの
   慣行が 1 始まりであり、`a.jin:12:40` の形で読んだときに驚きがない
4. `range.end` を排他にしたのは lark の `end_column` が排他だから（実測: 2 文字の `22` が `C22-C24`）。
   ここも変換しないことでズレを作らない

**LSP への変換は `jin-lsp` の 1 箇所に閉じ込める**（Phase 4 で `jin_lsp` に位置変換モジュールを作る）。
そこで行う変換は 2 つある。どちらも `jin_core` は関知しない:

| 変換 | 内容 |
|---|---|
| 基点 | `line - 1` / `col - 1`（1 始まり → 0 始まり） |
| 列の単位 | Unicode コードポイント → **UTF-16 コードユニット**（LSP の既定。pygls の `PositionCodec` を使う） |

列の単位変換は日本語の rune を含む `.jin`（本案件の examples がまさにそれ）で実際に効くため、
Phase 4 で必ず実施すること。`jin_core` 側は一貫してコードポイント単位で数える。

## 6. fixture

`tests/fixtures/errors/JINxxx_*.jin` に各コード 1 つ以上。**そのファイルは対応コードをちょうど 1 つだけ出す**。

- JIN040 は `--resolve` を付けたときだけ出る。よって `JIN040_*.jin` のみ `--resolve` 付きで検査し、
  他の fixture は `--resolve` なしで検査する（付けると Python 参照が解決できず JIN040 が混入して
  「1 つだけ」が壊れるため）
- 意味段（段 3）の fixture は**スキーマとして妥当**でなければならない。段 2 で止まると段 3 が動かないため
- `JIN001_*` / `JIN002_*` はモデルにならないので `jin fmt` の対象外である。冪等性・意味保存の検査からは
  この 2 つを除外し、除外集合が正確に `{JIN001, JIN002}` であることをテストで固定する

## 7. 本ラウンドでの実装状況

段 1〜3 の全コード（正典 12 + 追加提案 2）を `jin_core.diagnostics` / `jin_core.semantic` に実装済み。
`jin check` / `jin check --json` / `jin check --resolve` が動作する。
