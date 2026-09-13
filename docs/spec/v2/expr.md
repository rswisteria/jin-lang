# Jin v2 葉の式(expr.md)

> 正典。設計書 §3.3 の実装仕様。実装は Phase 1 の `jin_core.v2.expr`(Lark 文法 + 型検査)。
> 式は `.jin` の JSON 文字列の中に**テキスト**として置かれる唯一の部分である。
> 制御構造はここに入れない(それは `model.md` §3.4 のステップ)。

## 1. 文法(EBNF)

実装は `packages/jin-core/src/jin_core/v2/expr.py` の `JIN_EXPR_GRAMMAR`(インラインの Lark 文法、LALR、位置伝播)。
`.lark` ファイルは無い(v1 の JSON 文法と同じ流儀)。

<!-- machine-readable: expr-grammar -->

```
expr    := or
or      := and ("or" and)*
and     := not ("and" not)*
not     := "not" not | cmp
cmp     := add (("==" | "!=" | "<" | "<=" | ">" | ">=") add)?
add     := mul (("+" | "-" | "++") mul)*
mul     := unary (("*" | "/" | "%") unary)*
unary   := "-" unary | postfix
postfix := primary ("." NAME | "[" expr "]" | "(" args ")")*
args    := (expr ("," expr)*)?
primary := NUMBER | STRING | "true" | "false" | NAME
         | "(" expr ")"
         | NAME "{" (NAME ":" expr ("," NAME ":" expr)*)? "}"
         | "[" args "]"
NAME    := /[A-Za-z_][A-Za-z0-9_]*/
NUMBER  := /[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?/
STRING  := /"([^"\\\x00-\x1f]|\\["\\\/bfnrt]|\\u[0-9a-fA-F]{4})*"/
```

<!-- /machine-readable -->

- 空白は `" "` / `\t` のみ(改行は JSON 文字列の中では `\n` になるが、式には入れない。入っていれば JIN201)
- `cmp` は**連鎖しない**(`a < b < c` は JIN201)
- 予約語: `and` / `or` / `not` / `true` / `false`。識別子に使えない
- 文字列は `"…"` のみ。エスケープ集合は JSON と同じ。**式が JSON 文字列の中にある**ので、`.jin` 上では `"\"RETRY\""` のように二重にエスケープされる。エディタの式欄は 1 段外した形(`"RETRY"`)を見せる
- 末尾のカンマは不可(`[1, 2,]` は JIN201)

## 2. 演算子の型規則

| 演算子 | 左 | 右 | 結果 | 備考 |
|---|---|---|---|---|
| `or` / `and` | bool | bool | bool | 短絡評価。右辺は必要なときだけ評価する(ホスト能力の副作用もその順) |
| `not` | — | bool | bool | |
| `==` / `!=` | num / bool / str | 同型 | bool | list / 型紙は不可(JIN202) |
| `<` `<=` `>` `>=` | num | num | bool | str の比較は無い(v2.1 で `cmp(a, b)` を検討) |
| `+` `-` `*` `/` `%` | num | num | num | `/` は常に浮動小数。`%` は `a - floor(a / b) * b`(結果の符号は `b` に従う) |
| `++` | str | str | str | 連結。`num` を繋ぐには `str(x)` |
| 単項 `-` | — | num | num | |
| `.NAME` | 型紙 | — | 欄の型 | 欄が無ければ JIN203。`陣名.key` は §3.2 |
| `[expr]` | `list<T>` | num | `T` | 添字は `floor` して 0 始まり。範囲外は**実行時エラー**(トレースに `error` 行。runtime.md §5) |
| `(args)` | 呼び出し可能なもの | — | 戻り値の型 | §4 |
| `NAME{…}` | 型紙コンストラクタ | — | 型紙 | 全欄必須・余分な欄は JIN202 |
| `[a, b]` | list リテラル | — | `list<T>` | 要素は同型(JIN202)。空 `[]` は文脈の型から決まる(`let` に `type` が無ければ JIN202) |

`0 / 0` は NaN、`1 / 0` は inf(IEEE 754 のまま。Lua と wasm で同じ)。NaN の `==` は偽。

## 3. 識別子の解決

### 3.1 解決順

1. 局所(`params` / `let` / `loop.name`)
2. 自陣の `state[].name`
3. `sigils[].name`(`.member` が続くとき。名前空間として)
4. `circles[].name`(`.key` が続くとき。公開 state として)
5. `forms[].name` と `Pointer`(`{` が続くとき。コンストラクタとして)
6. 純関数(§4.1)

同じ名前が 2 つの層にあることは JIN010 で先に落ちる(局所と state、陣名と型紙名)。純関数の名前を state や局所に使うことは**できる**(その手順では純関数が隠れる。警告は出さない)。

### 3.2 `陣名.key`

他の陣の `out: true` の state を**読む**。`out: false` は JIN203(hint に `out: true` を提案)。自陣を `自陣名.key` で指すことは JIN203(自陣は裸の名前で指す)。値は**この tick の開始時点**の値(runtime.md §2 の二重バッファ)。核なし陣に state は無いので `Game.x` は JIN203。

### 3.3 `sigil.member`

`kind: host` の sigil を `名前.メンバ` で使う。メンバは `abilities.md` のカタログ。戻り値を持つメンバは式の中で呼べ、持たないメンバは `cast` からしか呼べない(式の中に書くと JIN202)。`kind: summon` の sigil は `cast` からしか使えず、式の中では JIN202(戻り値があっても。理由: summon 先の手順の副作用の順序を `cast` の並びで見えるようにするため)。

## 4. 呼び出し

### 4.1 純関数(宣言なしで使える)

<!-- machine-readable: pure-functions -->

| 名前 | 引数 | 戻り | 意味 |
|---|---|---|---|
| `abs` | num | num | 絶対値 |
| `min` | num, num | num | 小さい方 |
| `max` | num, num | num | 大きい方 |
| `floor` | num | num | 切り捨て |
| `ceil` | num | num | 切り上げ |
| `round` | num | num | 四捨五入(`.5` は偶数へ。Lua / JS / Python で一致させるため `floor(x + 0.5)` は使わない) |
| `sqrt` | num | num | 平方根 |
| `sin` | num | num | ラジアン |
| `cos` | num | num | ラジアン |
| `atan2` | num, num | num | `atan2(y, x)` |
| `clamp` | num, num, num | num | `clamp(x, lo, hi)` |
| `len` | list / str | num | 要素数 / コードポイント数 |
| `str` | num / bool / str | str | 文字列化。`num` は整数値なら `"3"`、それ以外は最短の往復可能表現(`%.17g` を短縮。runtime.md §6) |
| `sub` | str, num, num | str | `sub(s, i, n)`: 0 始まり `i` から `n` コードポイント |
| `contains` | list<T>, T | bool | `T` は num / bool / str のみ |
| `num` | str | num | `str` の逆(v2.1)。受けるのは `str()` が出す形と JSON の数値の形(`-?[0-9]+(.[0-9]+)?([eE][-+]?[0-9]+)?`)だけで、それ以外(空文字・前後の空白・`0x10`・`inf`・`nan`)は **0**。`storage.get` の文字列を数に戻す用 |

<!-- /machine-readable -->

引数の数と型が合わなければ JIN202。

### 4.2 組み込み effect(`cast` からだけ)

| 名前 | 引数 | 意味 |
|---|---|---|
| `push` | list<T>, T | 末尾に追加 |
| `removeAt` | list<T>, num | 添字の要素を除く(範囲外は実行時エラー) |
| `clear` | list<T> | 空にする |

### 4.3 手順・summon・ホスト能力

`cast` の `target` として。詳細は `model.md` §3.4 と `abilities.md`。

## 5. 型推論

- `let` の `type` が無ければ `expr` の型。`expr` が空 list リテラルなら JIN202(`type` を書く)
- `loop.each` の `name` は `in` の要素型
- `loop.count` の `name` は num
- `cast … into` は戻り値の型と代入先の型を照合(JIN202)。戻り値の無い target に `into` は JIN202

## 6. 位置

式の構文木の各ノードは、式文字列内の**コードポイント**の開始・終了(end 排他)を持つ。診断は「式を持つキーの pointer」+「式内の区間」で出し、LSP へは JSON 文字列リテラル内の位置(エスケープ換算後)を UTF-16 に変換して渡す(v1 と同じく変換は `jin_lsp.positions` だけが行う)。

## 7. 決定性の保証

式の評価は左から右、短絡評価。ホスト能力の副作用(表示リストへの追記、乱数の状態遷移)は評価順で起きる。同じ式・同じ状態・同じ入力なら、Lua(Wasmoon)と Lua(lupa)で同じ値になる(浮動小数は IEEE 754 倍精度、`sin` / `cos` / `sqrt` は libm 由来なので**両ホストで同じ libm を使うこと**は保証しない。パリティテストは `sin` / `cos` の結果を `frame` 行に載せる例を含めず、`str` の丸めで吸収する。設計書 §10 の「パリティ」の注記)。

## 8. 正準形(v2.1)

`jin fmt` / `jin/save` / `jin/applyOps` の応答(いずれも `jin_core.canonical.dumps`)は、式の欄を **AST から書き戻した正準形**にする(設計書 §11 #48。v2 では文字列のまま保存していた・§11 #15)。同じ AST は同じ文字列になり、その文字列を読み戻すと同じ AST(位置を除く)になる。実装は `jin_core.v2.expr.unparse`(印字器)と `canonical_expr`(読めない式は元のまま)。

対象は **schema の印 `x-jin-expr` を持つ欄すべて**(`init` / `expr` / `cond` / `args[]` / `into` / `assert` / `exit` / `ticks` / `until` / `times` / `in` / `target`。`jin_core.v2.model.expr_fields` が印から引くので名前は書き写さない)。`cast.target` は名前の欄だが同じ印を持つので同じ規則で書き戻す(`canvas . rect` → `canvas.rect`。check は名前の形を要求するので整形前は JIN202、整形後は通る。**整形が消す診断はこれだけ**)。

規則:

1. **空白**: 二項演算子(`or` / `and` / `==` … / `+` / `++` / `*` …)の両側に半角スペース 1 つ。`,` と `:` の後ろに 1 つ。`not` の後ろに 1 つ。それ以外に空白を置かない(`f(a, b)` / `xs[i]` / `a.b` / `Ball{x: 1, y: 2}` / `[1, 2]` / `-x`)。先頭・末尾の空白とタブは消える
2. **括弧**: 優先順位と結合で**必要なときだけ**(利用者の冗長な括弧は消える。`(a and b) or c` → `a and b or c`、`((n))` → `n`)。左結合の二項演算子は、左の被演算子が同順位なら付けず、右なら付ける(`a - (b - c)` は残り、`(a - b) - c` は `a - b - c`)。`cmp` は連鎖しないので両側とも `cmp` なら付ける(`(a < b) == c`)。`not` の被演算子が `and` / `or`、単項 `-` の被演算子が二項式なら付ける。`-(-x)` は読みやすさのため付ける(`--x` と書いても `-(-x)`)。後置(`.` / `[]` / `()`)の対象が一次式・後置でなければ付ける(`(-a).x` / `(a + b)[0]`)
3. **数値**: runtime.md §6 の `str(x)` と同じ書式。整数値(`|x| < 2^53`)は整数(`1e3` → `1000`、`1.50` → `1.5`、`007` → `7`)、それ以外は最短の往復可能表現を Python の `repr(float)` の配置で(`0.1` / `1e-05` / `1e+21`)。文法の NUMBER に読み戻せる。溢れた字面(`1e999` = inf)は書けないので**元のまま**
4. **文字列**: JSON の最小エスケープ(`jin_core.canonical.encode_string` と同じ。`"A\/"` → `"A/"`。非 ASCII はそのまま)
5. `true` / `false` はそのまま
6. **読めない式は変えない**: 構文エラー(JIN201)の式は 1 文字も動かさない(入力を失わない。診断は `jin check` が出す)

決めた理由(設計書 §2.4 が保留した「diff の安定性」と「LLM の書きやすさ」のトレードオフ): 打ち方の揺れ(空白・冗長な括弧・`1.50`)が diff に出ないことと、LLM や人が雑に書いた式が保存で一意の形に落ちることは同じ機構で両立する。読めない式を保つので、整形が入力を壊すことはない。証拠は `packages/jin-core/tests/test_v2_canonical.py`(字面の規則・ランダムな AST 3000 本の往復と冪等)、`tests/contract/test_canonical_contract_v2.py`(examples-v2 と fixture の冪等と式の AST 保存・`tests/fixtures/canonical/v2/messy.jin` → `messy.expected.jin` のバイト一致)、`packages/jin-wasm/tests/test_prelude.py`(数値の書式が `str(x)` と一致)。
