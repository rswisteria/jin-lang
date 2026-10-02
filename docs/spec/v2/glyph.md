# 陣書き(glyph)の視覚文法(glyph.md)

> 正典。上位設計は `docs/superpowers/specs/2026-10-03-jin-glyph-design.md`(以下「設計書」)。
> 画像(紙の魔法陣の写真・Jin が描いた PNG)を `.jin` と並ぶ **2 つ目の直列化**として読み書きするための語彙・欄の順・順序・
> 場面グラフを定める。実装との一致は `tests/spec/test_glyph_spec_consistency.py` が見る(`<!-- machine-readable: … -->` の書式を変えない)。
> 語彙と欄の順の実装は `jin_core.v2.glyph`(レンダラと読み取りの両方が import する純データ)、場面グラフは `jin_glyph.scene`。

## 0. 位置づけ

- `.jin`(JSON)と `jin_core.v2.model` が正本のまま。画像は `.jin` と往復する別の書き方で、実行系・LSP・エディタは変わらない
- 契約は「Jin が描いた画像を読むと元の `.jin` とバイト一致」(設計書 §5)。手描きは `jin check` を通ればよい
- 段階(設計書 §6): **S0 / S1(この文書)まで済み**。完全陣のレンダラ(S2)・決定的デコーダと構文解析器(S3)・Claude 認識器(S4)は後続

## 1. 三層の語彙

| 層 | 担うもの | どこに現れるか |
|---|---|---|
| 構造紋 | 陣・環・ステップ 11 種・委譲・flow | `docs/spec/v2/layout.md` §2 / §3 の図形をそのまま使う |
| 式紋(36 字) | 演算子・括弧・区切り・文字列の括り・エスケープ・真偽・型・欄の区切り・銘環の継ぎ | 銘帯のどこにでも |
| 判別の紋(21 字) | loop / wait / sigil / asset / flow の種別、`on` の event、省略できる欄の印 | **決まった枠**(`slot`)だけ。読み手は枠ごとに 2〜5 個の候補から選ぶ |
| ラテン層 | 名前・数値リテラル・文字列の中身(日本語を含む) | 普通の文字。1 字 1 升 |

式紋の設計規則(設計書 §1.1): ラテン文字・数字に似せない / 対になるもの(括弧・`<` と `>` など)は鏡像 / 1 字 3 画以内。
字形は 1 升 = `viewBox="0 0 100 100"` の線で、`docs/spec/v2/glyphs/<id>.svg` に置く。**字形の形は人の承認済み(2026-10-03)**。
S0 の手描き認識の実測(§7)で読めない字が出たときだけ描き直す(id とトークンは確定しており、字形を描き直しても変わらない)。

## 2. 紋の表

`トークン` は、式紋では式の字句(式紋を ASCII に写すときの文字列。`quote_l` / `quote_r` / `esc` / 型 / `sep` / `cont` は式の字句ではなく
`jin_core.v2.glyph.EXPR_TOKEN_OF` に入らない)、判別の紋では枠の値(モデルの Literal など)。

<!-- machine-readable: glyph-table -->

| id | 層 | トークン | 枠 | 字形 |
|---|---|---|---|---|
| `add` | expr | `+` | — | ![add](glyphs/add.svg) |
| `sub` | expr | `-` | — | ![sub](glyphs/sub.svg) |
| `mul` | expr | `*` | — | ![mul](glyphs/mul.svg) |
| `div` | expr | `/` | — | ![div](glyphs/div.svg) |
| `mod` | expr | `%` | — | ![mod](glyphs/mod.svg) |
| `cat` | expr | `++` | — | ![cat](glyphs/cat.svg) |
| `eq` | expr | `==` | — | ![eq](glyphs/eq.svg) |
| `ne` | expr | `!=` | — | ![ne](glyphs/ne.svg) |
| `lt` | expr | `<` | — | ![lt](glyphs/lt.svg) |
| `le` | expr | `<=` | — | ![le](glyphs/le.svg) |
| `gt` | expr | `>` | — | ![gt](glyphs/gt.svg) |
| `ge` | expr | `>=` | — | ![ge](glyphs/ge.svg) |
| `and` | expr | `and` | — | ![and](glyphs/and.svg) |
| `or` | expr | `or` | — | ![or](glyphs/or.svg) |
| `not` | expr | `not` | — | ![not](glyphs/not.svg) |
| `paren_l` | expr | `(` | — | ![paren_l](glyphs/paren_l.svg) |
| `paren_r` | expr | `)` | — | ![paren_r](glyphs/paren_r.svg) |
| `brack_l` | expr | `[` | — | ![brack_l](glyphs/brack_l.svg) |
| `brack_r` | expr | `]` | — | ![brack_r](glyphs/brack_r.svg) |
| `brace_l` | expr | `{` | — | ![brace_l](glyphs/brace_l.svg) |
| `brace_r` | expr | `}` | — | ![brace_r](glyphs/brace_r.svg) |
| `comma` | expr | `,` | — | ![comma](glyphs/comma.svg) |
| `colon` | expr | `:` | — | ![colon](glyphs/colon.svg) |
| `dot` | expr | `.` | — | ![dot](glyphs/dot.svg) |
| `quote_l` | expr | `"` | — | ![quote_l](glyphs/quote_l.svg) |
| `quote_r` | expr | `"` | — | ![quote_r](glyphs/quote_r.svg) |
| `esc` | expr | `\` | — | ![esc](glyphs/esc.svg) |
| `true` | expr | `true` | — | ![true](glyphs/true.svg) |
| `false` | expr | `false` | — | ![false](glyphs/false.svg) |
| `t_num` | expr | `num` | — | ![t_num](glyphs/t_num.svg) |
| `t_bool` | expr | `bool` | — | ![t_bool](glyphs/t_bool.svg) |
| `t_str` | expr | `str` | — | ![t_str](glyphs/t_str.svg) |
| `t_list_l` | expr | `list<` | — | ![t_list_l](glyphs/t_list_l.svg) |
| `t_list_r` | expr | `>` | — | ![t_list_r](glyphs/t_list_r.svg) |
| `sep` | expr | `<sep>` | — | ![sep](glyphs/sep.svg) |
| `cont` | expr | `<cont>` | — | ![cont](glyphs/cont.svg) |
| `loop_each` | disc | `each` | `loop` | ![loop_each](glyphs/loop_each.svg) |
| `loop_while` | disc | `while` | `loop` | ![loop_while](glyphs/loop_while.svg) |
| `loop_count` | disc | `count` | `loop` | ![loop_count](glyphs/loop_count.svg) |
| `wait_ticks` | disc | `ticks` | `wait` | ![wait_ticks](glyphs/wait_ticks.svg) |
| `wait_until` | disc | `until` | `wait` | ![wait_until](glyphs/wait_until.svg) |
| `sigil_host` | disc | `host` | `sigil` | ![sigil_host](glyphs/sigil_host.svg) |
| `sigil_summon` | disc | `summon` | `sigil` | ![sigil_summon](glyphs/sigil_summon.svg) |
| `sigil_agent` | disc | `agent` | `sigil` | ![sigil_agent](glyphs/sigil_agent.svg) |
| `asset_sprite` | disc | `sprite` | `asset` | ![asset_sprite](glyphs/asset_sprite.svg) |
| `asset_sound` | disc | `sound` | `asset` | ![asset_sound](glyphs/asset_sound.svg) |
| `flow_sequence` | disc | `sequence` | `flow` | ![flow_sequence](glyphs/flow_sequence.svg) |
| `flow_parallel` | disc | `parallel` | `flow` | ![flow_parallel](glyphs/flow_parallel.svg) |
| `flow_loop` | disc | `loop` | `flow` | ![flow_loop](glyphs/flow_loop.svg) |
| `event_tick` | disc | `tick` | `event` | ![event_tick](glyphs/event_tick.svg) |
| `event_key` | disc | `key` | `event` | ![event_key](glyphs/event_key.svg) |
| `event_pointer` | disc | `pointer` | `event` | ![event_pointer](glyphs/event_pointer.svg) |
| `event_message` | disc | `message` | `event` | ![event_message](glyphs/event_message.svg) |
| `event_exit` | disc | `exit` | `event` | ![event_exit](glyphs/event_exit.svg) |
| `mark_into` | disc | `into` | `optional` | ![mark_into](glyphs/mark_into.svg) |
| `mark_name` | disc | `name` | `optional` | ![mark_name](glyphs/mark_name.svg) |
| `mark_message` | disc | `message` | `optional` | ![mark_message](glyphs/mark_message.svg) |

<!-- /machine-readable -->

## 3. 銘帯と欄の順

すべての図形は脇に**銘帯**(環に沿った字の帯)を持ち、欄を次の順に、欄の区切りの紋 `sep` で区切って書く。並びは
「**現れる欄をこの順に書く**」の意味で、種別ごとに現れる欄が違うもの(sigil・wait・陣の核)は現れない欄を飛ばす。
省略できる欄(`cast` の `into`・`loop count` の `name`・`guard` の `message`)は判別の紋(枠 `optional`)を欄の頭に置いて示し、
`wait` の `ticks` / `until` は枠 `wait` の紋で示す。`return` の `expr` は唯一の欄なので、銘帯が空かどうかで有無が決まる。
`params` / `args` / 型紙の `fields` のような並びは、要素の間に式紋 `comma` を置く。

<!-- machine-readable: field-order -->

| 図形 | 欄の並び |
|---|---|
| `frame` | `$schema`・`width`・`height`・`fps`・`seed` |
| `form` | `name`・`fields` |
| `circle` | `name`・`core`・`flow.kind`・`flow.exit` |
| `state` | `name`・`type`・`init` |
| `sigil` | `name`・`kind`・`host`・`circle`・`rite`・`file` |
| `asset` | `name`・`kind`・`path` |
| `rite` | `name`・`params`・`returns` |
| `step.set` | `target`・`expr` |
| `step.let` | `name`・`type`・`expr` |
| `step.cast` | `target`・`args`・`into` |
| `step.if` | `cond` |
| `step.loop` | `kind` |
| `step.break` | — |
| `step.wait` | `ticks`・`until` |
| `step.emit` | `circle`・`message`・`args` |
| `step.return` | `expr` |
| `step.finish` | — |
| `step.transfer` | `circle` |
| `on` | `event`・`rite` |
| `guard` | `assert`・`message` |
| `delegate` | `circle` |
| `description` | `description` |

<!-- /machine-readable -->

`step.loop` は種別の紋(枠 `loop`)の後に、種別ごとの次の並びが続く(`count` の `name` は印の紋 `mark_name` 付き):

<!-- machine-readable: loop-fields -->

| 種別 | 欄の並び |
|---|---|
| `each` | `name`・`in` |
| `while` | `cond` |
| `count` | `times`・`name` |

<!-- /machine-readable -->

銘文の書き方(設計書 §1.2):

- 式は `expr` 文法と同じ並び(中置)でトークンを 1 つずつ書く。名前と数はラテン文字で 1 字 1 升、演算子・括弧・区切りは式紋で 1 升
- 読み取りは「銘文 → トークン列 → 式紋を ASCII に写す → `jin_core.v2.expr.parse_expr`」。往復の一致は `canonical.dumps` の正準化が保証する
- 文字列は `quote_l` … `quote_r` で挟み、中身は文字のまま。升に描けない文字は `esc` + ラテン文字 1 字で書く(表は `jin_core.v2.glyph.ESCAPE_LETTERS`):
  `"` → `"`、`\` → `\`、改行 → `n`、タブ → `t`、CR → `r`、BS → `b`、FF → `f`、**空白 → `s`**(空白の升は空の升と見分けられないため。
  JSON のエスケープには無い、視覚層だけの規則)。その他の制御文字は `esc` + `u` + 16 進 4 桁
- 文字列の欄(`description` / `message` / `path` / `file` / `host`)も同じ書き方で括る
- 型は型紋(`t_num` `t_bool` `t_str`)、`list<T>` は `t_list_l` T `t_list_r`、型紙名はラテン文字
- 数は `str(x)` の書式(runtime.md §6)。額縁の `$schema` は正典の印(標準の URL なら印だけ、他の値なら全文を銘帯に)

## 4. 始まりの印と順序

- 各環の 12 時に**始まりの印**(構造紋。名前は `start`。式紋・判別の紋の表には入れない)を置き、要素の配列順はそこから**時計回り**
- 入れ子のブロック(`then` / `else` / `loop.steps`)は親の弧の中で時計回り(layout.md §3 と同じ)
- 陣の並び(`circles[]`)・手順の並び(`rites[]`)は第 1 / 第 2 軌道の始まりの印から時計回り(設計書 §2.2)
- 始まりの印が無い環は JIN301(`docs/spec/v2/diagnostics.md` §5)

## 5. 場面グラフ(`.jinscene.json`)

認識器と構文解析器の間の唯一の契約。schema は `schemas/jin-scene.schema.json`(`jin_glyph.scene.JinScene` から
`scripts/generate_schema.py` が生成する。手で編集しない)。形の例は設計書 §3.2。

- `cells[].t` は `latin`(`v` は**ちょうど 1 コードポイント**。名前や数は升ごとに 1 字ずつ並ぶ。0 字・2 字以上は検証エラー)か
  `glyph`(`v` は §2 の id。それ以外は検証エラー)
- `unsure` は迷ったときの他の候補、`box` は画像上の升の矩形(画素)
- 写真の隣に `<写真名>.jinscene.json` として保存し、`image.sha256` が一致すれば認識を呼び直さない(設計書 §3.2)

## 6. 診断

絵の文法の誤りは JIN301〜306(`docs/spec/v2/diagnostics.md` §5)。画像を入力にしたときは JIN3xx も JIN2xx も `.jinscene.json` に対して出し、
画像上の位置はその pointer の `box` から引く。

## 7. S0 の実測(手描き認識の spike)

- 道具は `delivery/20260904-1445-jin/glyph-spike/`(使い捨て。試作の紋・升目シートと写し書きの手本・認識と採点のスクリプト)
- 合格線: 認識後の手直しが**升数の 2% 以内**(fib 75 升・clicker 464 升。設計書 §9 #17)
- 結果は `delivery/20260904-1445-jin/glyph-recognition-probe.md` に残し、ここに要約する。**2026-10-03 時点で未計測**(撮影と API の認証待ち)
