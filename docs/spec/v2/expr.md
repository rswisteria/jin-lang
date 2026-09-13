# Jin v2 葉の式(expr.md)

> 正典。設計書 §3.3 の実装仕様。実装は Phase 1 の `jin_core.v2.expr`(Lark 文法 + 型検査)。
> 式は `.jin` の JSON 文字列の中に**テキスト**として置かれる唯一の部分である。
> 制御構造はここに入れない(それは `model.md` §3.4 のステップ)。

## 1. 文法(EBNF)

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
