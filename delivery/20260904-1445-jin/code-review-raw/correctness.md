# Stage 5 review: correctness — 実装ラウンド 1（Jin Phase 0+1）

## Summary

- finding 総数: **33 件**
- confidence 90 以上: **25 件**
- 内訳: A（意味オペレーション）5 件 / B（意味検査）8 件 / C（パーサ・位置情報）3 件 / D（正準形・CLI）4 件 / E（テストの質）5 件 / F（delivery 成果物）2 件 / S（docs/spec 仕様書自体）6 件
- severity 内訳: high 8 / medium 12 / low 13
- `docs/spec/` の仕様書自体の誤り: **あり** — S-1（ops.md）/ S-2（diagnostics.md）/ S-3（model.md）/ S-4（model.md）/ S-5（model.md × adk-mapping.md）/ S-6（layout.md）
- 作業ツリーへの変更: **残していない**（検証スクリプトは全て `/Users/toyota/.claude/jobs/8b3a6b62/tmp/` 配下。`find . -newermt "-90 minutes"` でリポジトリ内の変更 0 件を確認済み）

### レビュー条件

- 対象状態: main（f6a37e0 + 未コミットの実装ラウンド 1 成果物）
- テスト実行結果: **225 passed in 2.59s**（`.venv/bin/python -m pytest -p no:cacheprovider`）。全 finding は「テストが緑の状態で」検出したもの
- 判断材料: 差分コード・生成物・`delivery/` 成果物のみ。実装者の rationale は未検証の主張として扱った
- 再現スクリプト: `/Users/toyota/.claude/jobs/8b3a6b62/tmp/probe1.py` 〜 `probe5.py`、`crlf.jin`、`surrogate.jin`（親の再現用に残置）

### 修正の優先順位（提案）

1. **A-3**（pointer セグメント未検証 → 別配列を破壊）と **A-1 / A-2**（undo が戻らない）。Phase 4 / 5 が乗る土台なので Phase 2 前に潰すのが安い
2. **C-1**（構文エラーメッセージが常に「入力の終わり」・hint が lark 終端名）。要件書 成功条件 3「診断だけで直しきれる」に直撃
3. **D-1 / D-2**（fmt の未捕捉クラッシュと CRLF 素通り）
4. **S-1 / S-2 / S-3**（正典側の欠落。Phase 2〜6 が参照するので早い方がよい）
5. **A-5 のコメント矛盾**（`ops.py:405`）と **B-1 のメッセージ** — 1 行修正
6. **E-1〜E-5** のテスト補強

---

## A. 意味オペレーション（ops.py）— 逆オペレーションの契約違反

プロジェクト自身の合格基準は `packages/jin-core/tests/test_ops.py:54-61` の `check()`、すなわち
「逆 op を当てたら正準形テキストがバイト一致で戻る」。A-1 / A-2 はその基準を満たさない。

```
A-1 [high / confidence 100] toggleAwait の逆オペレーションが配列順を復元しない
packages/jin-core/src/jin_core/ops.py:335-344
await から要素を remove し、逆 op では append するため末尾に移動する。
await: ["t1","t2","t3"] に対し toggleAwait "t1" → 逆 op で ["t2","t3","t1"]。
要件書 §2.2「配列順が描画順（12 時から時計回り）」なので、undo で魔法陣の見た目が変わる。
再現: probe1.py → after undo: ['t2','t3','t1'] / byte equal: False
テストが素通りする理由: test_ops.py:252-263 の await が 1 要素しかなく、順序の劣化が起きない
```

```
A-2 [high / confidence 100] setGuard / toggleAwait が boundary を新規作成し、逆 op で消さない
packages/jin-core/src/jin_core/ops.py:161-168（_boundary が副作用で circle["boundary"] を生やす）
packages/jin-core/src/jin_core/ops.py:303-319（setGuard）/ :335-344（toggleAwait）
boundary を持たない circle に setGuard（追加）または toggleAwait を当て、逆 op を当てると
モデルは boundary=Boundary() のまま残り、正準形出力に "boundary": {} が増える。
ファイル→モデル→ファイルのバイト同一（要件書 成功条件 5）が undo 経路で崩れる。
再現: probe2.py → 両 op で restored bytes equal: False（差分は "boundary": {} の 1 行）
テストが素通りする理由: test_ops.py:223-249, 252-263 の fixture circle が最初から boundary を持つ
```

```
A-3 [high / confidence 100] moveTool / setState / removeGuard が pointer の経路セグメントを検証せず別の配列を書き換える
packages/jin-core/src/jin_core/ops.py:264-274（moveTool）/ :277-292（setState）/ :322-332（removeGuard）
いずれも _circle_index(op, N) で深さしか見ておらず tokens[2] を確認していない。実測:
  - moveTool に /circles/0/state/1 → tools が並べ替わる（['t1','t2'] → ['t2','t1']）
  - setState に /circles/0/tools/0 → state[0] が書き換わる
  - removeGuard に /circles/0/xxx/yyy/0 → guards[0] が消える
対照的に _add_to_list:221-238 / _remove_from_list:241-261 / _set_guard:303-309 は tokens[2] を検証している。
エディタ（Phase 5）がドラッグで pointer を組み立てるので実害が出る経路。
再現: probe5.py（親も独立に再現済み）
テストが素通りする理由: 経路セグメントが誤った pointer を渡すテストが 0 件
```

```
A-4 [low / confidence 95] _rename の深さ検査が空振り
packages/jin-core/src/jin_core/ops.py:365
circle_index = _circle_index(op, len(tokens)) と期待深さに実際の長さを渡しているため
len(tokens) != expected_depth の分岐が永久に偽。後続の if len(tokens) == 2 / 4 で
結果的に守られてはいるが、検査として機能していない。
```

```
A-5 [medium / confidence 100（挙動）] rename（state）が可視範囲を無視して全 circle の rune を書き換える
packages/jin-core/src/jin_core/ops.py:397-415（rune 置換 :412-414 / flow.exit.key 置換 :409-411）
examples/pipeline/pipeline.jin と同じ形（Drafter と Rewriter がどちらも draft を持つ）で確認:
/circles/1/state/0 を draft → draft2 にすると、無関係な circle B の rune {draft} まで
{draft2} に書き換わる。B は自分の draft を持ったままなので、rename 後に jin check を
通しても診断は 1 件も出ない（B からは上流の draft2 が可視のため）。静かな意味変化。
再現: probe3.py → B の rune が "unrelated {draft2} here" になる
補足 1: この全 circle 置換は docs/spec/ops.md §3 に「可視範囲に絞らない」と根拠つきで明記されている（設計判断として文書化済み・S-1 とは別）
補足 2: ただしコードのコメント ops.py:405 は「その state が見える circle の rune 内 {key} を追随させる」と書いており、実装とも ops.md とも矛盾している。ここは明確な誤り
補足 3: flow.exit.key も同様に、同名なら無関係な flow の exit まで書き換わる
```

---

## B. 意味検査（semantic.py）

```
B-1 [medium / confidence 100] JIN013 が「同じ親が 2 回参照した」ケースを多重親として誤報
packages/jin-core/src/jin_core/semantic.py:88-104（_build_graph が出現ごとに親子辺を append・重複排除なし）
packages/jin-core/src/jin_core/semantic.py:409-419（JIN013 の emit）
flow.steps: ["A","A"] で「circle 'A' が 2 個の親を持っています: P / P」というメッセージが出る。
同じ親が 2 回出るのは自己矛盾したメッセージで、hint（「1 つだけ残し、他は summon に変えて
ください」）も的外れ。steps:["A"] + delegate:["A"] の組み合わせでも同じ。
ADK 的に不正であること自体は正しいので「検出は妥当・コードとメッセージが不適切」。
再現: probe4.py の dup-step ケース
```

```
B-2 [medium / confidence 95] flow.exit.key の未解決参照に診断が無い
packages/jin-core/src/jin_core/semantic.py:284-385（flow.exit の key を検査するコードが存在しない）
{"kind":"loop","steps":["B"],"exit":{"key":"zzz","equals":true}} で zzz がどの circle の
state にも無くても診断 0 件。要件書 §2.4 JIN011 は「未解決の参照」を扱い、
docs/spec/model.md §3.4 は exit.key を「比較する state key」と定義している。
しかも ops.py:409-411 の rename は exit.key を参照として追随させているので、
システム内で「参照かどうか」の扱いが一貫していない。
再現: probe5.py 系 → exit key not a state -> []
```

```
B-3 [medium / confidence 95] max / exit が sequence・parallel でも黙って通る
packages/jin-core/src/jin_core/semantic.py:320-336
kind == "loop" のときしか max/exit を見ておらず、schemas/jin.schema.json の Flow にも制約が無い。
docs/spec/model.md §3.4 は「max: loop のみ」「exit: loop のみ」と明記しているが、Phase 1 の
どの層も拒否しない。Phase 2 で ADK に渡す先が無いまま静かに落ちる形になり、要件書 §3.3
「ADK に対応物のない Jin 構造はコンパイル時エラー。黙って落とさない」に触れる。
再現: sequence に max:3 / exit:{key,equals} を付けても診断 0 件
テストが素通りする理由: loop 以外の flow に max/exit を付けた fixture が存在しない
```

```
B-4 [low / confidence 90] JIN050 の loop 規則が「1 周目に存在しない値」を許す
packages/jin-core/src/jin_core/semantic.py:196-200
loop の祖先を辿るとき自分以外の全 step の部分木を可視にするため、loop steps:["X","Y"] で
X の rune が Y の out state を参照しても診断が出ない。1 周目には未定義の値。
docs/spec/model.md §5 の表「祖先が loop のとき、すべての兄弟枝の部分木を含める」に
準拠しているので実装バグではない。仕様上のリスクとして報告する。
再現: probe4.py の loop-later ケース → 診断 0 件
```

```
B-5 [low / confidence 80] 親が複数あるとき最初の親しか辿らない
packages/jin-core/src/jin_core/semantic.py:186
parent_name = candidates[0] で 1 本目の親経由の可視範囲しか計算しない。多重親は JIN013（error）
になるので実害は限定的だが、同一実行内で JIN050 が偽陽性を出しうる
（2 本目の親経由なら可視だった state key が「見えない」と報告される）。
```

```
B-6 [low / confidence 85] _find_cycle が再帰・_visible_state_keys が O(n^2)
packages/jin-core/src/jin_core/semantic.py:117-130 / :171-209
前者は再帰 DFS で、病的に深い連鎖では RecursionError が未捕捉のまま jin check に抜ける。
後者は circle ごとに _parents_of と _subtree_states を丸ごと再構築する。
要件書 §6.4「1000 行以下で診断 1 秒以内」には届くが構造的な弱点。
```

```
B-7 [low / confidence 70] _subtree_states のキャッシュが循環時に走査順依存
packages/jin-core/src/jin_core/semantic.py:154-166
cache への書き込みはトップレベル呼び出し（seen が空）のときだけだが、読み出しはネストからも
行う。閉路があるとどの circle を先に walk したかで結果が変わりうる。
閉路時は JIN012 が別途 error になるので実害は小さい。
```

```
B-8 [low / confidence 95] rune の {a}} が state key 参照として認識されない
packages/jin-core/src/jin_core/semantic.py:27（_RUNE_KEY の否定先読み）
docs/spec/model.md §3.1 の規則は「{{ と }} はリテラルのエスケープ、それ以外の { } で囲まれた
識別子は state key 参照」。この規則では {a}} は「参照 a + リテラル }」だが、実装は
否定先読み (?!\}) で丸ごと弾き [] を返す。未解決 key が JIN050 をすり抜ける穴。
再現: rune_keys('{a}}') -> []（'{a}' -> ['a'] / '{{a}}' -> [] は正しい）
テストが素通りする理由: rune のエスケープ境界を突くテストが 1 件も無い
```

---

## C. パーサ・位置情報（parser.py / pointer.py）

```
C-1 [high / confidence 100] 字句レベルのエラーで常に「入力の終わり」と誤報し、hint が lark の終端名
packages/jin-core/src/jin_core/parser.py:174-186（特に :178 getattr(exc,"token",None)）
lark の UnexpectedCharacters には .token が無く .char を持つ。よって found が
"入力の終わり" に落ち、ファイル途中の不正文字でも「入力の終わり はここに置けません」と出る。
hint も「期待: FALSE, LBRACE, LSQB, NULL, NUMBER, STRING, TRUE」と lark の終端名そのままで、
要件書 §5「hint は LLM がそのまま編集に使うので具体的な値にする」を満たしていない。
再現: 4 例すべてで message が「入力の終わり はここに置けません」（位置自体は正しい）
  parse_text('{"a": @}')            -> 入力の終わり / 期待: FALSE, LBRACE, LSQB, NULL, NUMBER, STRING, TRUE
  parse_text('{"a": "x}')           -> 同上（未終端文字列）
  parse_text(BOM + '{"a": 1}')      -> 同上（UTF-8 BOM 付きファイル。BOM は read_text で除去されない）
  parse_text('{"a": 1} trailing')   -> 入力の終わり / 期待: COMMA, RBRACE, RSQB
テストが素通りする理由: test_parser.py:138-144 は {"a": }（UnexpectedToken 経路）だけを通す。
  UnexpectedCharacters 経路はテスト 0 件
```

```
C-2 [medium / confidence 100] JSON の重複キーが黙って後勝ちになり、位置情報が失われる
packages/jin-core/src/jin_core/parser.py:149-159
{"a":1,"a":2} が値 {"a":2}、pointer 表も /a が 1 件だけ（先に出たキーの range は上書きで消滅）。
診断は 0 件。docs/spec/model.md §6 は「表の pointer 集合はソースに実在するキー・要素」と
書いているが、実在する 2 つ目のキーの位置が失われている。jin fmt を通すと片方が静かに消える。
再現: probe5.py → dup keys -> {'a': 2} / ranges: ['', '/a']
テストが素通りする理由: 重複キーの fixture / テストが 0 件
```

```
C-3 [low / confidence 70] resolve_pointer が宣言外の ValueError を投げうる
packages/jin-core/src/jin_core/pointer.py:55-57
token.lstrip("-").isdigit() は "--1" を通し、続く int("--1") が ValueError。
docstring は KeyError / IndexError しか宣言していない。pointer_exists は握るが
resolve_pointer の直呼び（main.py:161 経由の利用など）では漏れる。
```

### C-4（確認済み・問題なし）

- `meta.empty` は `parser.py:120` で参照前に確認している（lsp-api-probe.md §3 の指摘に対応済み）
- lark の 1 始まり・`end` 排他・コードポイント単位カラムは `test_parser.py:65-94` で実測検証済み
- `loc → pointer` の変換は判別共用体タグ / alias（`$schema` / `await`）/ Optional / 欠落キーについて
  `tests/contract/test_pointer_contract.py:100-133` で網羅されており、追加で試した組み合わせでも破綻しなかった
- JSON Pointer のエスケープ（`~0` / `~1`）、配列インデックス、ネストの扱いはいずれも正しい

---

## D. 正準形（canonical.py）と CLI（main.py）

```
D-1 [high / confidence 100] jin fmt がロンサロゲートを含むファイルで未捕捉クラッシュ
packages/jin-core/src/jin_core/canonical.py:50-63（encode_string）
packages/jin-cli/src/jin_cli/main.py:127（write_text(encoding="utf-8")）
encode_string は単独サロゲート（U+D800 など）をそのまま出力し、write_text が例外を投げる。
診断ではなく UnicodeEncodeError のトレースバックが端末に出る。jin check は診断 0 件で
通るので、check → fmt の順で使うと突然落ちる。
（Python の json.loads は "\ud800" というエスケープを受け付けるので、この入力は現実に作れる）
再現: .venv/bin/jin fmt /Users/toyota/.claude/jobs/8b3a6b62/tmp/surrogate.jin
      → UnicodeEncodeError: 'utf-8' codec can't encode character '\ud800' in position 133
テストが素通りする理由: test_canonical.py:90-96 はサロゲート「ペア」（正当な BMP 外文字）
  しか見ておらず、単独サロゲートのテストは 0 件
```

```
D-2 [high / confidence 100] CRLF ファイルが「正準形である」と判定される
packages/jin-cli/src/jin_cli/main.py:122-123（read_text の改行正規化）/ :127（write_text）
read_text が CRLF を LF に畳むため CRLF のファイルは canonical == current となり
fmt --check が exit 0。バイト列は正準形ではない。要件書 §2.3 と成功条件 5 の
「バイト同一」をこの 1 経路が骨抜きにする。write 側も Windows で LF が CRLF に変換されるので、
同じ入力から OS 依存で別バイト列が出る。
再現: .venv/bin/jin fmt --check /Users/toyota/.claude/jobs/8b3a6b62/tmp/crlf.jin → exit 0
      （中身は examples/researcher/researcher.jin を CRLF 化しただけのもの）
テストが素通りする理由: 改行コードを変えた fixture が 0 件
```

```
D-3 [low / confidence 85] 公開スキーマと Pydantic strict の乖離
schemas/jin.schema.json（Flow.max = {"type":"integer","minimum":1}）
packages/jin-core/src/jin_core/model.py:41（model_config strict=True）
JSON Schema draft 2020-12 では 1.0 も integer に一致するが strict=True は拒否する。
$schema を頼りに外部ツールや LLM が検証して通したファイルが jin check で JIN002 になる。
要件書 成功条件 3（Schema と診断だけで直しきれる）に対する小さな穴。
```

```
D-4 [low / confidence 90] _collect が .jin 以外のファイルも受け取る
packages/jin-cli/src/jin_cli/main.py:45-47
ディレクトリ指定時は *.jin に絞るが、ファイル直接指定は拡張子を問わず check_file に渡す。
README.md を渡すと JIN001 になる。害は小さいが挙動が非対称。
```

### D-5（確認済み・問題なし）

- 正準形の 4 規則（2 スペース / スキーマ定義順 / 非 ASCII 非エスケープ / 末尾改行）と
  「省略可能キーが既定値なら出力しない」はすべて実測で成立
- 冪等 `fmt(fmt(x)) == fmt(x)` と意味保存 `model(fmt(x)) == model(x)` は全 formattable 文書で成立
  （`tests/contract/test_canonical_contract.py:47-63`）
- `examples/*.jin` は手書きのまま `dumps(model)` とバイト一致（`test_canonical.py:160-165`）
- 段階制御（JIN001 で段 2 を出さない / JIN002 で段 3 を出さない）は `check.py:168-197` で正しく実装され、
  `test_check.py:82-96` で検証されている
- fixture 14 件が「対応コードをちょうど 1 つ」出すことも実測確認済み

---

## E. テストの質

```
E-1 [medium / confidence 95] インデント検査が実質的に無効
tests/contract/test_canonical_contract.py:86-92
インデント幅が偶数であることしか見ていないので、4 スペースインデントに変えても緑のまま。
ネスト深さ × 2 と突き合わせる必要がある。
```

```
E-2 [medium / confidence 95] 非 ASCII 非エスケープ検査の正規表現が死んでいる
tests/contract/test_canonical_contract.py:144-148
正規表現 \\u00[2-9a-f][0-9a-f] は、encode_string が実際に出しうるエスケープ表記
（U+0000 〜 U+001F すなわち "\\u0000" 〜 "\\u001f"。文字クラス [2-9a-f] が 0 と 1 を除いている）に
決して一致しない。生きているのは 2 行目の "\\u3" not in text だけで、これも CJK の一部しか見ない。
```

```
E-3 [low / confidence 100] parametrize が 1 値のみで無意味
tests/contract/test_canonical_contract.py:178-197
@pytest.mark.parametrize("explicit_default", [False]) の 1 値。True を足すとアサーションが
成立しないので、パラメタ化の体裁だけが残っている。
```

```
E-4 [low / confidence 85] test_apply_ops_is_atomic_on_failure が現状ほぼトートロジー
packages/jin-core/tests/test_ops.py:386-396
ops は _plain() で毎回コピーを作る純関数なので、呼び出し元のモデルが変わらないのは自明。
ただし将来 in-place 実装に変わったときのガードにはなるので、削除ではなく意図をコメントに残すのが妥当。
```

```
E-5 [high / confidence 100] 構造的に未カバーな領域（テスト 0 件の穴）
- UnexpectedCharacters 経路（C-1）
- boundary を持たない circle への setGuard / toggleAwait（A-2）
- 複数要素 await に対する toggleAwait（A-1）
- op の pointer 経路セグメント誤り（A-3）
- CRLF / BOM / 単独サロゲート（C-1, D-1, D-2）
- 重複 JSON キー（C-2）
- rune のエスケープ境界 {a}} / {{a}（B-8）
- loop 以外の flow に max / exit を付けたケース（B-3）
- rename circle 後に flow.steps が追随することの検証
  （test_ops.py:276-282 は delegate と summon しか見ておらず、flow を持つ circle が sample() に無い）
```

### E-6（確認済み・良い）

- `tests/contract/test_dependency_direction.py:76-104` は違反（`import google.adk`）を注入して
  import-linter が実際に落ちることを確認しており、「宣言だけ」になっていない
- `tests/contract/test_cli_contract.py:53-64` は `PYTHONHASHSEED` を変えた別プロセス 2 回で
  `jin dump` の安定性を見ており、同一プロセス比較の偽 green を避けている
- `tests/spec/test_spec_consistency.py` は期待値を実装から写さず上位文書（要件書）から抽出しており妥当
- `test_canonical_contract.py:29-40` は「fmt できない fixture の除外集合が正確に {JIN001, JIN002}」を
  固定しており、後から除外集合を膨らませて冪等性検査を骨抜きにできないようにしている

---

## F. delivery 成果物の不整合

```
F-1 [low / confidence 100] version-matrix.md が存在しないファイルを参照
delivery/20260904-1445-jin/version-matrix.md §5 表 4 行目
「jin_core/grammar/jin_json.lark を自作した」とあるが、そのファイルは存在しない。
文法は packages/jin-core/src/jin_core/parser.py:33-50 のインライン文字列 JIN_JSON_GRAMMAR。
```

```
F-2 [medium / confidence 60] 一次証拠（adk-api-probe.md）の内部矛盾
delivery/20260904-1445-jin/adk-api-probe.md「エージェントクラスの受け付けるフィールド」
LlmAgent の列挙に tools が無い（アルファベット順で timeout と wait_for_output の間が空）。
にもかかわらず直後の結論行と docs/spec/adk-mapping.md §2.1（「実測で存在を確認したもの」）は
tools を実測確認済みとして扱っている。実際の ADK には存在するはずなので転記漏れの可能性が
高いが、Phase 2 のテンプレートは「記憶で書かない」方針なのでこの 1 項目だけ根拠が空。
```

### F-3（確認済み・問題なし）— 依存バージョン

`.venv` 実測: pydantic 2.13.5 / lark 1.3.1 / typer 0.27.2 / pytest 9.1.1 / ruff 0.16.6 /
import-linter 2.14 / hatchling。`pyproject.toml` の宣言レンジ（`>=2.13,<3` 等）とすべて一致し、
**存在しないバージョン指定は 1 件も無い**。GitHub Actions の `uses:` 版が未検証である点は
version-matrix.md §5 行 10 で自己申告済み。

---

## S. docs/spec/ 仕様書自体の誤り（正典側の欠陥）

5 本（model.md / adk-mapping.md / layout.md / diagnostics.md / ops.md）を全文読んで検出した 6 件。
後続 Phase 2〜6 が参照する正典なので、実装バグとは別枠で立てる。

```
S-1 [high / confidence 90] ops.md の逆オペレーション表が「復元不能な逆 op」を追認している
docs/spec/ops.md §2 表の toggleAwait 行・setGuard 行
- toggleAwait の逆を「toggleAwait（同じ tool 名）」とだけ書いており、配列順が戻らないこと
  （A-1）を仕様として許してしまっている。要件書 §2.2 は配列順を描画順と定めている
- setGuard の逆を「removeGuard」とだけ書いており、boundary を新規作成したケースで
  boundary を消す責務が仕様に無い（A-2）
同 §1 は「クライアントが逆オペレーション列を保持して undo する」と書いており、
復元がバイト単位で成立しないと undo が壊れる。表の 2 行に復元条件を書き足す必要がある。
```

```
S-2 [medium / confidence 90] diagnostics.md の優先順位表に flow.exit.key が無い
docs/spec/diagnostics.md §4（machine-readable: diagnostic-precedence の表 6 行）
summon / delegate / steps / root / await / rune の {key} は列挙されているが、
flow.exit.key への state key 参照がどのコードの守備範囲かどこにも書かれていない。
結果として実装にも検査が無い（B-2）。一方 ops.py:409-411 の rename は exit.key を
参照として追随させているので、システム内で「参照かどうか」の扱いが一貫していない。
```

```
S-3 [medium / confidence 90] model.md の「max / exit は loop のみ」がどこでも強制されない
docs/spec/model.md §3.4 の Flow 表
「max: loop のみ」「exit: loop のみ」と制約を書いているが、この制約をどの段（schema /
意味検査 / Phase 2 codegen）で落とすかの記述が無い。実装も落とさない（B-3）。
同 §3.3 の「out: true が 2 件以上」は「Phase 2 のコード生成時エラー」と落とす場所を
明記しているので、同じ扱いをこちらにも書くべき。
```

```
S-4 [medium / confidence 95] model.md の pointer 表の網羅性の主張が重複キーで崩れる
docs/spec/model.md §6
「pointer→range 対応表はソーステキストから作る。したがって表の pointer 集合は
『ソースに実在するキー・要素』」と書いているが、同一オブジェクト内の重複キーでは
先に出たキーの位置が失われる（C-2）。重複キーを禁じる（診断を出す）か、
本文の主張を弱めるかのどちらかが要る。
```

```
S-5 [medium / confidence 75] rune の {{ }} エスケープ規約と「ADK へ透過」が両立しない
docs/spec/model.md §3.1 と docs/spec/adk-mapping.md §1（instruction.rune の行）
model.md は「{{ と }} はリテラルのエスケープとして扱う」と Jin 独自の規約を定めている。
一方 adk-mapping.md は rune を「LlmAgent.instruction（{state_key} テンプレートは透過）」
＝ ADK へそのまま渡すと書いている。ADK 側に同じ {{ }} エスケープがある証拠は
adk-api-probe.md に無い。透過なら {{findings}} は実行時に ADK 側の解釈に晒される。
Phase 2 で「Jin 側でアンエスケープしてから渡す」のか「透過のまま」なのかを決める必要がある。
```

```
S-6 [low / confidence 95] layout.md の星形多角形の例の根拠説明が誤り
docs/spec/layout.md:55
「n=6 → k=1（2 と 3 は gcd≠1）」とあるが、j=3 はそもそも探索範囲外
（同 :49 の判定 2*j < n で 2*3 < 6 は偽）。結論の k=1 は正しく、n=5/7/8/9 の例も
すべて正しい（検算済み）。根拠の説明だけが誤っている。
Phase 3 の実装者が j の上限を「n/2 以下」と読み違える余地がある。
```

### S-7（確認済み・問題なし）— docs/spec で確認して正しかった箇所

- `layout.md` の角度式 `theta_i = -90° + 360°*i/n`（SVG は y 軸下向きなので (cos, sin) をそのまま
  使えば時計回り、-90° が 12 時）は正しい
- `layout.md` の環半径 4 種と `data-jin-kind` 9 種は要件書 §2.5 と一致
- `layout.md` §2.1 の k の決め方 `k = max{ j : 1 <= j < n/2, gcd(n,j)==1 }` は n=5→2 / 7→3 /
  8→3 / 9→4 が全て正しい（S-6 は n=6 の説明文だけの誤り）
- `diagnostics.md` §4 の「専用コードが勝つ」優先順位規定は、要件書 §2.4 の JIN011 行と
  §9「fixture は対応コードを 1 つだけ出す」を両立させる読み方として妥当
- `diagnostics.md` §3.1 の JIN012 / JIN013 の採番根拠（10 の位のブロック構造）は筋が通っている
- `model.md` §4 の「summon は親子辺ではない（AgentTool は parent_agent を設定しない）」は
  adk-api-probe.md の実測と整合

---

## 補足: 診断コードの検出ロジック検証結果（要件書 §2.4 との突合）

親の依頼にあった重点項目について、実測した結果を明示する。

| コード | 検出条件の妥当性 | 備考 |
|---|---|---|
| JIN011 | 妥当 | 守備範囲を summon / delegate に絞る設計は diagnostics.md §4 で明文化済み |
| JIN020 | 妥当 | `> MAX_ELEMENTS`（13 個目で発火）で「12 を超えた」どおり。tools / state 両方 |
| JIN022 | 妥当 | 両立・両欠落とも検出。メッセージと hint も具体的 |
| JIN030 | 妥当 | `max is None and exit is None` で正しい |
| JIN050 | 条件付きで妥当 | 「上流」の解釈は model.md §5 の表に準拠。loop 全兄弟可視は B-4 のリスク、`{a}}` は B-8 の穴 |
| JIN060 | 妥当 | 編集距離 hint も機能（`Researchr` → `Researcher`） |
| JIN070 | 妥当 | boundary がある circle のみ検査。tool 名一覧を hint に出す |
| JIN012 | 妥当 | 自己参照（A→A）/ 間接循環（A→B→C→A）/ summon 経路 / delegate 経路すべて検出。非循環の深いネストで誤検出なし |
| JIN013 | 検出は妥当・メッセージが不適切 | B-1 |

`--resolve` 付きで JIN020 / JIN070 の fixture に JIN040 が追加で出る件は、
`test_check.py:43` が非 JIN040 fixture を `resolve=False` で検査する設計と
`diagnostics.md §6` の明記どおりであり、**問題なし**と判断した。

パーサのエラー回復（要件書 §6.4「構文エラー中も直前の正常なモデルで hover / renderSvg を返す」）は
Phase 4 の LSP 側キャッシュの責務であり、Phase 1 に未実装なのは範囲どおり。

---

## 親からの追加質問への回答

### Q1. docs/spec/ の仕様書 5 本自体の誤り

**あり。6 件（S-1 〜 S-6）。** 上記 S 節に記載。重要度順に S-1（ops.md・逆オペレーションの復元条件が
仕様から欠落）、S-2（diagnostics.md・flow.exit.key の担当コードが未規定）、S-3（model.md・
max/exit の loop 限定をどこで落とすか未規定）。

### Q2. 「全 235 テスト」の根拠 — 私の誤りです。正しくは 225 件

**235 は数え間違いです。** 実測は親の数値どおり **225 passed**
（`.venv/bin/python -m pytest -p no:cacheprovider` → `225 passed in 2.59s`）。

原因: セッション冒頭で `pytest -q` を `tail -20` にパイプしたため、`addopts = "-q"` の出力から
サマリ行が切れ、ANSI 制御文字混じりのドットを目視で概算した。根拠のある数値ではない。

**テストは 1 件も追加していない。作業ツリーは無変更。**

- `find . -newermt "-90 minutes" -type f`（`.venv` / `.git` / `__pycache__` / 各種キャッシュを除外）の
  結果は**空**。リポジトリ内のファイルは 1 つも触っていない
- 書き込みはすべて `/Users/toyota/.claude/jobs/8b3a6b62/tmp/` 配下
  （`probe1.py`〜`probe5.py`、`crlf.jin`、`surrogate.jin`）。`jin fmt` を実行したのもこの tmp 配下のみ
- 副作用として `.pytest_cache/` と `.import_linter_cache/` が更新されたが、
  どちらもセッション開始時点で既に存在し `.gitignore` 対象
- 念のため: 現在 `git status` が `delivery/…/design.yaml` の変更と多数の untracked を示しているが、
  これらは私の作業前から存在する実装ラウンドの成果物である
  （セッション開始時に渡された `(clean)` というスナップショットのほうが実態と食い違っている）
- 本レポートファイル（`delivery/20260904-1445-jin/code-review-raw/correctness.md`）のみ、
  親の指示により新規作成した

### 再現スクリプトの対応表

| finding | 再現ファイル |
|---|---|
| A-1 | `/Users/toyota/.claude/jobs/8b3a6b62/tmp/probe1.py` |
| A-2 | `/Users/toyota/.claude/jobs/8b3a6b62/tmp/probe2.py` |
| A-5 | `/Users/toyota/.claude/jobs/8b3a6b62/tmp/probe3.py` |
| B-1 / B-4 | `/Users/toyota/.claude/jobs/8b3a6b62/tmp/probe4.py` |
| A-3 / C-2 / D-1 | `/Users/toyota/.claude/jobs/8b3a6b62/tmp/probe5.py` |
| D-1（CLI 経由） | `.venv/bin/jin fmt /Users/toyota/.claude/jobs/8b3a6b62/tmp/surrogate.jin` |
| D-2 | `.venv/bin/jin fmt --check /Users/toyota/.claude/jobs/8b3a6b62/tmp/crlf.jin` |
