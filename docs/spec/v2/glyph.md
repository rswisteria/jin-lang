# 陣書き(glyph)の視覚文法(glyph.md)

> 正典。上位設計は `docs/superpowers/specs/2026-10-03-jin-glyph-design.md`(以下「設計書」)。
> 画像(紙の魔法陣の写真・Jin が描いた PNG)を `.jin` と並ぶ **2 つ目の直列化**として読み書きするための語彙・欄の順・順序・
> 場面グラフを定める。実装との一致は `tests/spec/test_glyph_spec_consistency.py` が見る(`<!-- machine-readable: … -->` の書式を変えない)。
> 語彙と欄の順の実装は `jin_core.v2.glyph`(レンダラと読み取りの両方が import する純データ)、場面グラフは `jin_glyph.scene`。

## 0. 位置づけ

- `.jin`(JSON)と `jin_core.v2.model` が正本のまま。画像は `.jin` と往復する別の書き方で、実行系・LSP・エディタは変わらない
- 契約は「Jin が描いた画像を読むと元の `.jin` とバイト一致」(設計書 §5)。手描きは `jin check` を通ればよい
- 段階(設計書 §6): S1(この文書)・S2(§8)・S3(§9)・S4(§10・撮影の実測は未)・S5(§11)・S6(§12・撮影の実測は未)まで実装済み。S0 は道具まで(撮影と認識の実測は未)

## 1. 三層の語彙

| 層 | 担うもの | どこに現れるか |
|---|---|---|
| 構造紋 | 陣・環・ステップ 11 種・委譲・flow | `docs/spec/v2/layout.md` §2 / §3 の図形をそのまま使う |
| 式紋(37 字) | 演算子・括弧・区切り・文字列の括り・エスケープ・語の区切り・真偽・型・欄の区切り・銘環の継ぎ | 銘帯のどこにでも |
| 判別の紋(22 字) | loop / wait / sigil / asset / flow の種別、`on` の event、省略できる欄の印 | **決まった枠**(`slot`)だけ。読み手は枠ごとに 2〜5 個の候補から選ぶ |
| ラテン層 | 名前・数値リテラル・文字列の中身(日本語を含む) | 普通の文字。1 字 1 升 |

式紋の設計規則(設計書 §1.1): ラテン文字・数字に似せない / 対になるもの(括弧・`<` と `>` など)は鏡像 / 1 字 3 画以内。
字形は 1 升 = `viewBox="0 0 100 100"` の線で、`docs/spec/v2/glyphs/<id>.svg` に置く。**字形の正本は `jin_render.v2.glyph_paths`**(S2)で、
SVG は `uv run python scripts/generate_glyph_svgs.py` の生成物(手で編集しない・`--check` を pytest が呼ぶ)。**字形の形は人の承認済み(2026-10-03)**。
S0 の手描き認識の実測(§7)で読めない字が出たときだけ描き直す(id とトークンは確定しており、字形を描き直しても変わらない)。

## 2. 紋の表

`トークン` は、式紋では式の字句(式紋を ASCII に写すときの文字列。`quote_l` / `quote_r` / `esc` / `divider` / 型 / `sep` / `cont` は式の字句ではなく
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
| `divider` | expr | `<space>` | — | ![divider](glyphs/divider.svg) |
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
| `mark_out` | disc | `out` | `optional` | ![mark_out](glyphs/mark_out.svg) |

<!-- /machine-readable -->

## 2.1 構造の印(S2)

銘環の中で銘帯 1 本の頭に置き、どの図形の銘文かを示す(区切りを兼ねる・設計書 §1.1 / §1.3 / §9 #24)。字形は二重の正方形の枠の中に
layout.md §3 の図形を縮めた記号で、式紋・判別の紋のどれとも形が違う。額縁は辺が始まりなので印を持たない。
実装は `jin_core.v2.glyph.STRUCT_MARKS`(並びは §3 の欄の順の表と同じ)。S3 で入れ子の境目の 2 字(`s_else` / `s_end`)を足して 23 字: `if` の銘帯 → then の前順 →(else が空でなければ `s_else` → else の前順)→ `s_end`、`loop` の銘帯 → 本文の前順 → `s_end`(本文が空でも書く)。入れ子は銘文だけで決まる(設計書 §9 #29)。

<!-- machine-readable: struct-marks -->

| id | 図形 | 字形 |
|---|---|---|
| `s_form` | `form` | ![s_form](glyphs/s_form.svg) |
| `s_circle` | `circle` | ![s_circle](glyphs/s_circle.svg) |
| `s_state` | `state` | ![s_state](glyphs/s_state.svg) |
| `s_sigil` | `sigil` | ![s_sigil](glyphs/s_sigil.svg) |
| `s_asset` | `asset` | ![s_asset](glyphs/s_asset.svg) |
| `s_rite` | `rite` | ![s_rite](glyphs/s_rite.svg) |
| `s_set` | `step.set` | ![s_set](glyphs/s_set.svg) |
| `s_let` | `step.let` | ![s_let](glyphs/s_let.svg) |
| `s_cast` | `step.cast` | ![s_cast](glyphs/s_cast.svg) |
| `s_if` | `step.if` | ![s_if](glyphs/s_if.svg) |
| `s_loop` | `step.loop` | ![s_loop](glyphs/s_loop.svg) |
| `s_break` | `step.break` | ![s_break](glyphs/s_break.svg) |
| `s_wait` | `step.wait` | ![s_wait](glyphs/s_wait.svg) |
| `s_emit` | `step.emit` | ![s_emit](glyphs/s_emit.svg) |
| `s_return` | `step.return` | ![s_return](glyphs/s_return.svg) |
| `s_finish` | `step.finish` | ![s_finish](glyphs/s_finish.svg) |
| `s_transfer` | `step.transfer` | ![s_transfer](glyphs/s_transfer.svg) |
| `s_on` | `on` | ![s_on](glyphs/s_on.svg) |
| `s_guard` | `guard` | ![s_guard](glyphs/s_guard.svg) |
| `s_delegate` | `delegate` | ![s_delegate](glyphs/s_delegate.svg) |
| `s_description` | `description` | ![s_description](glyphs/s_description.svg) |
| `s_else` | `else` | ![s_else](glyphs/s_else.svg) |
| `s_end` | `end` | ![s_end](glyphs/s_end.svg) |

<!-- /machine-readable -->

## 3. 銘帯と欄の順

すべての図形は脇に**銘帯**(環に沿った字の帯)を持ち、欄を次の順に、欄の区切りの紋 `sep` で区切って書く。並びは
「**現れる欄をこの順に書く**」の意味で、種別ごとに現れる欄が違うもの(sigil・wait・陣の核)は現れない欄を飛ばす。
省略できる欄(`cast` の `into`・`loop count` の `name`・`guard` の `message`)は判別の紋(枠 `optional`)を欄の頭に置いて示し、
`wait` の `ticks` / `until` は枠 `wait` の紋で示す。`return` の `expr` は唯一の欄なので、銘帯が空かどうかで有無が決まる。
`params` / `args` / 型紙の `fields` のような並びは、要素の間に式紋 `comma` を置く。引数と型紙の欄の 1 つは `名前 colon 型`(型紙名の型もラテンなので、`colon` が無いと名前との境が切れない・S2 の最終レビューで確定)。`args` の `comma` と式の中の `comma` は括弧の深さ 0 で見分ける。

<!-- machine-readable: field-order -->

| 図形 | 欄の並び |
|---|---|
| `frame` | `$schema`・`width`・`height`・`fps`・`seed` |
| `form` | `name`・`fields` |
| `circle` | `name`・`core`・`flow.kind`・`flow.steps`・`flow.exit` |
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
| `else` | — |
| `end` | — |

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
- 文字列は `quote_l` … `quote_r`(帯の両端を閉じる**封**)で挟み、中身は文字のまま。**空白は語の区切りの紋 `divider` 1 升**(碑文の語の区切り。
  空白の升は空の升と見分けられないため。視覚層だけの規則・Issue #129。以前の `esc s` は読まない)。升に描けない文字は `esc` + ラテン文字 1 字で書く
  (表は `jin_core.v2.glyph.ESCAPE_LETTERS`): `"` → `"`、`\` → `\`、改行 → `n`、タブ → `t`、CR → `r`、BS → `b`、FF → `f`。**点から同じ字に読み戻せない字**(制御文字・点の無い全角空白・字形が無く □ で描かれる字・
  同じ点の並びの組の先頭でない字。判定は `jin_render.v2.font.readable`)は `esc` + `u` + 16 進 4 桁。BMP の外は UTF-16 のサロゲートの組
  (`esc u d83d esc u de00`。JSON の `\u` エスケープと同じ・S3)
- 文字列の欄(陣の `description`・guard の `message`・asset の `path`・agent の `file`)も同じ書き方で括る。名前(`Name`)の欄は括らない
  (`emit` の `message`・`host` の `host` も名前。S2 で確定・実装は `jin_render.v2.inscribe`)
- root が `circles[0]` でないときだけ、額縁の銘帯の `seed` の後に root の添字(ラテンの数字・pointer `/root`)を書く(陣の並びは塊の棚の順と root の添字から戻す・S3・設計書 §9 #30)
- `$schema` は標準の URL なら額縁の銘帯に書かない(モデルに必ずあるので、書かれていなければ標準)。核なし陣の `flow.steps` は
  陣の名前の並び(`comma` 区切り)として陣の核の銘帯に書く。`let` の `type` は欄の数(3 つなら型あり)で見分ける
- 型は型紋(`t_num` `t_bool` `t_str`)、`list<T>` は `t_list_l` T `t_list_r`、型紙名はラテン文字
- 数は `str(x)` の書式(runtime.md §6)。額縁の `$schema` は正典の印(標準の URL なら印だけ、他の値なら全文を銘帯に)

## 4. 始まりの印と順序

- 各環の 12 時に**始まりの印**(構造紋。名前は `start`。式紋・判別の紋の表には入れない)を置き、要素の配列順はそこから**時計回り**
- 入れ子のブロック(`then` / `else` / `loop.steps`)は親の弧の中で時計回り(layout.md §3 と同じ)
- 手順の並び(`rites[]`)は陣の周りの軌道の始まりの印(12 時)から時計回り。陣の並び(`circles[]`)は陣の塊の棚の順(root が左上・段ごとに左から・§8・設計書 §2.2)
- 始まりの印が無い環は JIN301(`docs/spec/v2/diagnostics.md` §5)

## 5. 場面グラフ(`.jinscene.json`)

認識器と構文解析器の間の唯一の契約。schema は `schemas/jin-scene.schema.json`(`jin_glyph.scene.JinScene` から
`scripts/generate_schema.py` が生成する。手で編集しない)。形の例は設計書 §3.2。

- `cells[].t` は `latin`(`v` は**ちょうど 1 コードポイント**。名前や数は升ごとに 1 字ずつ並ぶ。0 字・2 字以上は検証エラー)か
  `glyph`(`v` は §2 の id。それ以外は検証エラー)か `struct`(`v` は §2.1 の構造の印か始まりの印 `start`・S3)
- `sheet` は `S` / `M` / `free` / `full`(`full` = Jin が描いた完全陣を決定的デコーダで読んだもの・S3、`S` / `M` = 型紙の写真を Claude 認識器で読んだもの・S4・§10、`free` = 白紙に描いた陣の写真を読んだもの・S6・§12)。`free` の図形の id は `full` と同じ規則。`full` の図形の id は
  `frame` / 陣 `c<k>`(`c0` が root、`c1`… が陣の塊の棚の順・§8)/ 手順陣 `r<k>_<j>`(陣 `c<k>` の衛星を 12 時から時計回り)。
  銘帯は図形ごとに 1 本で、銘環の銘帯は始まりの印と継ぎの紋 `cont` も含む
- `unsure` は迷ったときの他の候補、`box` は画像上の升の矩形(画素)
- 写真の隣に `<写真名>.jinscene.json` として保存し、`image.sha256` が一致すれば認識を呼び直さない(設計書 §3.2)

## 6. 診断

絵の文法の誤りは JIN301〜306(`docs/spec/v2/diagnostics.md` §5)。画像を入力にしたときは JIN3xx も JIN2xx も `.jinscene.json` に対して出し、
画像上の位置はその pointer の `box` から引く。

## 7. S0 の実測(手描き認識の spike)

- 道具は `delivery/20260904-1445-jin/glyph-spike/`(使い捨て。試作の紋・升目シートと写し書きの手本・認識と採点のスクリプト)
- 合格線: 認識後の手直しが**升数の 2% 以内**(fib 75 升・clicker 464 升。設計書 §9 #17)
- 結果は `delivery/20260904-1445-jin/glyph-recognition-probe.md` に残し、ここに要約する。**2026-10-03 時点で未計測**(撮影と API の認証待ち)

## 8. 完全陣(S2)

`jin render FILE --full`(`jin_render.render(model, full=True)` → `jin_render.v2.full.render_full`)。プログラムの情報をすべて載せた 1 枚の SVG で、
`<text>` を 1 つも使わない(銘文は線の紋と 6×8 のドットの字)。`data-jin-kind` は v2 の 13 種のまま、銘環の升は持ち主の kind と欄の pointer を持つ。

- 銘環(設計書 §1.3 / §2.3): 陣の銘環は 陣の核 → `description` → 記憶 → 道具 → `on` → `guard` → 委譲、手順陣の銘環は 手順陣の核 → ステップの前順。
  1 周目の 12 時に始まりの印、周の最後の升が `cont`、外の周の 12 時から続く。字は回さず正立で置く
- **文字列は詠唱帯(Issue #129・設計書 §9 #57)**: `quote_l` … `quote_r` の升の並びを、升の中心から ±0.8 升(周の間隔 1.6 のちょうど半分。
  正立の升が斜め 45° で張り出す √2 / 2 より外で、どの升の枠にもかからず額縁も大きくならない)の 2 本の線で囲む。銘環では同心の弧、額縁の銘帯では
  辺に沿う直線で、同じ周(辺)で続く升を 1 本にまとめ、封の升では中身の側の半分だけ引く。中身のドットの字は点を**珠**(格子の目の中心に半径 0.55 目の円・
  `font.BEAD_RADIUS`)で描く。**帯は飾りで意味を持たない**: 括りは封の紋だけで決まり、デコーダ・場面グラフ・構文解析器は帯を見ない(手描きでは省いてよい)。
  升は正立なので、環の下半分(右から左へ進む区間)では封の腕が帯の外を向く
- 額縁の銘帯: 額縁の内側を左上から時計回り(四隅の護符の区画を飛ばす)。四隅の護符は右上だけ中が丸(向きの印)。1 周に収まらなければ
  1 つ内側の周へ続け、**銘帯と次の 1 升が 3 周(`FRAME_ROWS`)を超えるなら超えた周の分だけ額縁の余白を `FULL_RING_PITCH` ずつ広げる**
  (`frame_margin`。4 周目が陣に食い込まず、位置が尽きて黙って切れることも無い・#119。次の 1 升まで余白に収めるので、デコーダは
  空の升まで読めば陣の升を読み込まずに止まる)
- **陣の塊の詰め方(#118)**: 陣の周りに手順陣を 12 時から等角に置いた塊を、root → 残りの陣(`circles[]` の順)で、額縁の内側(余白の内)の
  左上から棚に詰める(`full_layout.shelf`)。塊の大きさは陣の中心から上下左右への最大の張り出し `e`(正方形 2e)。棚の上端に揃えて左から
  `FULL_ORBIT_GAP` を空けて並べ、入らなければ次の段の左端へ。額縁の一辺は詰められる最小の値(半辺を 0.25 升刻みで広げて探す)。
  陣が 1 つなら塊は額縁の中心に来る(以前と同じで、fib / clicker の完全陣はバイト不変)。設計書 §9 #56
- 図: 既存の陣の図・手順の図をそのまま使い(入れ子の参照は点)、`<text>` を取り除く。円どうしの線はへその緒・`summon`・flow・委譲の 4 種
  (自陣の手順への `cast`・`emit`・`transfer` の線は描かない。参照の正本は銘文)
- **state の `out: true` は記憶の銘帯の 4 つ目の欄に判別の紋 `mark_out` を置く**(図の二重線は隙間が (0.05 − 0.032) × 12 = 0.216 升で
  画素からは読めないため。S2 の最終レビュー #3 → ユーザーの判断で 22 字目を足した・設計書 §9 #28)

定数(`jin_render.v2.geometry`。単位は升・S2 の実装で決めた値):

| 定数 | 値 | 根拠 |
|---|---|---|
| `FULL_DIAGRAM_R` | 12 | 図の R = 1 を 12 升に。紋(半径 0.05)の外接の直径が 1.2 升で銘環の升と同じくらい。20 升では銘文が図に比べて小さすぎた(目視) |
| `FULL_RING_GAP` | 1.5 | 図の外接(陣 1.0 R・手順陣 1.095 R)から銘環の 1 周目の内縁まで |
| `FULL_RING_PITCH` | 1.6 | 周の間隔(升 1 + 行間 0.6) |
| `FULL_CELL_PITCH` | √2 | 銘環の隣り合う升の中心の弦の最小。升は正立の 1×1 なので √2 あればどの向きでも x か y の差が 1 以上で重ならない(1.0 では約 27% の組が重なった・S2 の最終レビュー #2) |
| `FULL_ORBIT_GAP` | 4 | 軌道上の隣り合う円(銘環の最外周まで)の最小の隙間 |
| `FULL_FRAME_MARGIN` | 6 | 最外の円から額縁まで(額縁の銘帯と護符が入る) |
| `FULL_TALISMAN` | 3 | 四隅の護符の一辺 |
| `FULL_CELL_PX` | 12 | SVG の升 1 つの px |

実測(2026-10-04・`uv run python scripts/measure_full_circle.py`。括弧は #118 の前の root を中心にした配置):

| 例 | 一辺(升) | 銘環の周回数の最大 | 升の総数 | A3(280 mm 角)で 1 升(mm) |
|---|---|---|---|---|
| clicker | 137.6(137.6) | 4 | 498 | 2.04(2.04) |
| fib | 115.2(115.2) | 1 | 92 | 2.43(2.43) |
| othello | 447.6(614.5) | 7 | 5209 | 0.63(0.46) |
| paddle | 267.2(307.7) | 5 | 993 | 1.05(0.91) |
| tetris | 386.6(543.1) | 10 | 3835 | 0.72(0.52) |

すべて 1 枚に収まるが、A3 に刷った 1 升は設計書 §2.4 の見積もり(手描き 5 mm・印刷 2 mm)に届かない。tetris を 2 mm(一辺 140 升)にするのは
**データの量で無理**: 升 3835 × 升 1 つの面積(周の間隔 1.6 × 升の幅 √2)に、環ごとの図の円盤(半径 12 升)が乗る。陣と手順陣をばらして
詰めても 1.26 mm が試算の上限で、それは連環の見た目と引き換えになる(#118 でユーザーが塊を保つ案を選んだ・設計書 §9 #56)。
tetris / othello は当面「Jin が描いた PNG をそのまま読む」使い方に限る(設計書 §9 #8 の線引き)

## 9. 読み取り(S3: 決定的デコーダと構文解析器)

Jin が描いた完全陣の PNG は API を使わずに読む(`jin_glyph.decode.decode_png` → 場面グラフ → `jin_glyph.parse.parse_scene` → モデル)。
**往復の契約**: examples-v2 と `tests/fixtures/v2-programs/` の全本で `.jin` → 完全陣 → PNG(2 倍)→ デコード → 構文解析 → `canonical.dumps` が
元の正準形とバイト一致する(`tests/contract/test_glyph_roundtrip.py`)。

- **升の照合**(`jin_glyph.cells.read_cell`): 升を 24 × 24 の格子に縮めた「塗られた割合」と、候補の理想の格子の差の総和の最小を採る。
  候補は線の字(`glyph_paths` の 83 字・線の太さは完全陣と同じ 1/12 升)とドットの字(升を 8 × 8 に縮めた列 1〜6 の点の並びを
  `font.dot_groups` で引いた組の先頭)。**近い候補は ±1 格子目(升の 1/24)ずらした升でも測る**(倍率 2 では 1 px のずれで二重枠の差が
  中の記号の差を上回る)。ドットの字も同じずれで測る(線の字だけずらすと `o` が `flow_loop` に負けた)
- 読める大きさの下限は 1 升 24 px(完全陣の SVG を **2 倍以上**で PNG に。1 倍は線が 1 px で ÷ の点などが潰れる)。
  `UNKNOWN_DISTANCE` = 120(全字形の往復で決めた値)、デコーダは 250(Jin が描いた画像では最も近い候補が正しい)
- **デコーダ**: 左上の護符の中の塗りの暗さの総和から升の px → 額縁の銘帯を空の升まで読み、字数から額縁の余白(`frame_margin`)と
  棚の左上・幅を決める → **陣の塊を棚の順に 1 つずつ探す**: 塊の中心は棚の今の位置 (x, top) から右下への対角線 (x + e, top + e) の上に
  あるので、e を 0.04 升刻みで走査して(1 歩で縦横の両方が動くので、真上の走査の 0.1 升では倍率 3 の画像で始まりの印を踏み外した)陣の始まりの印を探し、±0.3 升の平面で合わせ込んで頭の `s_circle` を確かめる。その陣の衛星は
  陣の中心から真上へ 0.1 升刻みで始まりの印を走査し、前後 0.5 升を 0.02 升刻みで(ずらさない差で)合わせ込んで頭の構造の印を確かめ、
  数は `orbit_centers` の全位置で読める最大の n。読んだ字数から `full_layout` と同じ式で塊の張り出し e を求め、見つけた中心が
  (x + e, top + e) に 0.75 升以内で合い、塊が棚に入るものだけを採る(画像から求めた額縁の半辺は 0.02 升ほどずれる。別の塊の陣なら張り出しの違いの分だけ予測から外れて採られず、走査が続く。3 段・2 段目に 3 塊の完全陣で `test_decode.py` が固定)。この段に見つからなければ
  次の段の左端から探し、どちらにも無ければ終わる。2 回目は数えた字数から求めた中心で読む(走査のずれを持ち越さない)。
  核なし陣(陣の核の銘帯に flow の紋)は衛星を探さない
- 円どうしの線は、両端以外の陣・手順陣の円板の内側で切る(銘環を横切ると升が読めない・S3 で完全陣の出力が変わった)
- 軌道に載る数の上限: 衛星は 12(手順の数の上限 JIN020 と同じ。数は「全位置で読める最大の n」なので、上限を超えると真の数の約数に化ける)。
  陣の塊は棚に詰めるので数の上限は無い
- 画素数の上限は 4 億(`MAX_PIXELS`。PNG の IHDR を読んで先に断り、開く間だけ Pillow の爆弾検査を外す。othello は 2 倍で 2.2 億画素)
- **構文解析器**: 銘帯を構造の印で切り、欄(`sep`)・並び(括弧の深さ 0 の `comma`)・`名前 colon 型`・文字列・式(`to_expr` →
  `canonical_expr`)に割る。ステップの列は `s_else` / `s_end` で木に戻す。組んだ JSON を `check_text` に通し、JIN0xx / 2xx の pointer は
  欄ごとの対応表でモデルから場面グラフの中へ写す。JIN301〜305 が 1 つでもあればモデルを組まない。手書きの場面グラフの壊れ方
  (文字列の中に生の `"` / `\` / 制御文字のラテン升・12 桁を超える数・32 段を超える `list<>`)も例外ではなく JIN302
- **CLI**: `jin check x.png`(隣に `x.jinscene.json` を書いて診断はそれに対して。既にあって `image.sha256` が一致すればデコードせず
  それを読む(手直しを消さない)。別の画像のものやリンクなら上書きせず exit 2)・`jin check x.jinscene.json`・
  `jin fmt <画像|場面グラフ> --out y.jin`(新しいファイルだけ)。画像は名指しのときだけ受け、ディレクトリの走査は `.jin` だけ。
  サブコマンドは 9 個のまま

実測(2026-10-03・2 倍の PNG・cairosvg の描画込み): fib 0.9 秒・paddle 7 秒・tetris 27 秒・othello 42 秒(最大 RSS 2.2 GB)。
1 升の読み取りは約 3 ms(ずらした升の照合を入れる前は 1 ms)。

## 10. 型紙と Claude 認識器(S4・モード 2)

印刷した型紙に手で描いた陣を撮影し、Claude の視覚モデルで場面グラフに読む(設計書 §2.5 / §3.1 / §3.7・決定は設計書 §9 #35〜#41)。
構文解析器(§9)から先は完全陣と共通で、Claude に `.jin` は書かせない。

### 10.1 型紙(`jin render --sheet S|M`)

幾何は `jin_render.v2.sheet_layout.sheet_layout`(純関数)の 1 か所で、型紙を描く `jin_render.v2.sheet` と写真から升を切り出す
`jin_glyph.recognize` が同じ表を読む。完全陣の定数(`FULL_*`)は手描きの升 5 mm では A3 に入らない(S だけで一辺 115 升)ので、
銘環の規則(`ring_capacity` / `ring_slot_center`・1 周目の 12 時に始まりの印・時計回り)と額縁の銘帯(`frame_positions`)・四隅の護符
(`talisman_nodes`)は共有し、大きさだけを型紙の定数で決める(設計書 §2.4「別に組む」・§9 #35)。

| 等級 | 骨格 | 環 1 つの升 | 続きの帯 | 額縁の銘帯 |
|---|---|---|---|---|
| S | 1 陣 × 4 手順。陣を中央、手順陣を斜め 4 方向に**右上から時計回り**(陣 `c0` → 手順陣 `r0_0` … `r0_3`) | 4 周・110 升 | 28 本・232 升 | 190 升 |
| M | 3 陣 × 各 4 手順。15 の環を 4 × 4 の格子に行の順(`c0` `r0_0` … `r0_3` `c1` … `r2_3`)、16 個目の区画は続きの帯 | 2 周・36 升 | 9 本・73 升 | 190 升 |

定数(単位は升・`jin_render.v2.sheet_layout`):

| 定数 | 値 | 根拠 |
|---|---|---|
| `SHEET_CELL_MM` | 5 | 手描きの升 5 mm(設計書 §2.4 / §9 #8) |
| `SHEET_HALF` | 28.5 | 一辺 57 升 = 285 mm。A3 の短辺 297 mm に余白込みで刷れる |
| `SHEET_DIAGRAM_R` / `SHEET_DIAGRAM_R_M` | 2.5 / 2.0 | 環の中の核の円(環の名前「陣1」「手1」を薄く刷る)。手描きの図形は読まない(入れ子は銘文だけで決まる・§9 #29) |
| `SHEET_RING_GAP` | 1.0 | 核の円から銘環の 1 周目の内縁まで |
| `SHEET_TURNS` | S 4 / M 2 | S は clicker の陣の銘環(120 升)の大半が 1 つの環に入る周回数。M は 15 の環を 4 × 4 に並べられる周回数 |
| `SHEET_GAP` | 0.6 | 環どうし・環と帯の隙間 |
| `SHEET_STRIP_PITCH` / `SHEET_STRIP_ROW` | 1.2 / 1.6 | 続きの帯の升の横の間隔と行の間隔(行は銘環の周の間隔と同じ) |
| `SHEET_GRADE_CELL` | 1.5 | 等級の印(ドットの S / M)。額縁の銘帯の上辺の最初の 2 升の位置に刷り、その升は銘帯から外す |

- 刷るもの: 額縁・四隅の護符(完全陣と同じ。右上だけ中が丸)・等級の印・各環の核の円と 12 の目盛りと始まりの印・書く升の枠・
  続きの帯の番号。**色は黒 1 色で、案内(升の枠・目盛り・番号・環の名前)は不透明度 0.35 で薄く刷る**(読み取りは升の内側だけを見る)
- **続きの帯**: 余白を横一列の升に切った帯(先頭の升は印刷の番号)。番号は 上の区画 → 中段の左 → 中段の右 → 下の区画、区画の中は上から。
  銘帯(環・額縁)の**最後の升に継ぎの紋 `cont`** を書いたら、まだ使っていない帯を番号の順に取って続ける(帯の最後の升も同じ)。
  どの帯に続けたかは書かない(読み手は升の並びだけで決まる・§9 #36)
- 書かれていない環は使わない手順(図形ごと出さない)。手順は番号の小さい環から詰めて使う(飛ばすと JIN302)
- `jin render x.jin --sheet S` は x の銘文を清書体で書き込んだ**写し書きの手本**(`fill_sheet`。収まらなければ exit 2)。
  認識器のテストの正解もこの割り付けから作る

実測(2026-10-03・`fill_sheet`): fib(92 升)は S の額縁と環 3 つに収まり帯を使わない。clicker(523 升)は陣の銘環が 120 升で
環の 110 升を超え、手順陣 `r0_1` が 272 升なので、環の継ぎの紋 2 つから帯 1〜25 へ続く(帯の 232 升のうち 197 升。帯の終わりの継ぎの紋 23 個を含む)。

### 10.2 認識(`jin_glyph.recognize.recognize_photo`)

| 段 | 内容 |
|---|---|
| ① 位置合わせ | 写真(EXIF の向きを直し、長辺 1568 px の JPEG)を 1 回送り、四隅の護符の中心(**幅・高さに対する比**)・中が丸か・等級の印を返させる。丸の護符を右上として時計回りに並べ直す(写真が回っていてよい)。受けた位置は護符の中の塗りの重心(±1 升の窓・4 回)で詰め直す(§9 #38) |
| ② 正面化・切り出し | 4 点の射影変換(純 Python の 8 元連立)で 1 升 48 px の正面図にし、`sheet_layout` の書く升を切り出す。升の内側 ±0.38 升で「地より 60 暗い画素が 2% を超える」升だけを送る(空の升は送らない) |
| ③ 記号の認識 | 升の画像(枠を含む ±0.6 升を 96 px 角)を 60 個ずつ、番号の text(`#n (持ち主, cell 順番)`)と交互に 1 要求に並べる。字形表(紋 59 字 + 構造の印 23 字を id 付きで並べた画像・`glyph_table`)は最初の user の先頭に `cache_control` 付きで置く(`system` は text しか受けない・§9 #39)。返させるのは升ごとの `t`(latin / glyph / struct / empty)・`v`・`unsure` |
| ④ 場面グラフ | 持ち主ごとに升を読む順につなぎ、環の銘帯の頭に始まりの印 `start` を積む。継ぎの紋で続きの帯をつなぐ。どの銘帯にもつながらない帯は図形 `strip<n>`(kind `strip`)として残し、構文解析器が JIN305 で知らせる。契約に合わない読み(未知の id・2 字のラテンなど)と返ってこなかった升は `?` + 迷い(JIN306 の warning) |

- 要求: `claude-opus-5-5`・`beta.messages.parse`(構造化出力)・`fallbacks: "default"`(beta `server-side-fallback-2026-07-01`)・
  `output_config.effort: "medium"`・`max_tokens` 16000。`stop_reason` が `refusal`(分類を文に出す)・`max_tokens` なら失敗。
  認証情報が無いときは送らずに失敗する(SDK 1.11.0 は送る前に `TypeError`)。実測と未実測は `delivery/20260904-1445-jin/glyph-recognize-api-probe.md`
- 升の `box` は**写真の座標**(EXIF の向きを直した後)。`image.width` / `height` も直した後の値、`image.sha256` は元のファイルのバイト列

### 10.3 CLI と外部送信(設計書 §3.7 / §9 #37)

- `jin check <写真>` / `jin fmt <写真> --out y.jin` の写真は拡張子 `.jpg` / `.jpeg` / `.webp`。送る前に stderr へ 1 行出す
- 隣に `<写真名>.jinscene.json` があり `image.sha256` が一致すれば**送らずに**それを読む(手直しを消さない)。写真から読んだ場面グラフは
  `fmt` でも隣に書く(読み直すと費用がかかるため)。別の写真の場面グラフやリンクがあれば上書きせず、送らずに exit 2
- **`--offline`**(`check` / `fmt`)は隣の場面グラフだけを読み、無ければ送らずに exit 2
- **PNG は送らない**: `.png` は完全陣の決定的デコーダだけで、デコードに失敗しても API へは回さない(写真なら `.jpg` で渡すよう文に出す)
- 失敗(認証・拒否・接続・型紙が見つからない)は 1 行の文で exit 2(トレースバックを出さない)

### 10.4 テストと評価

- テストはネットワークと API キーを使わない。写真は手本の SVG → PNG → 台形に歪めた JPEG(`tests/glyph_photo.py`)、Claude の応答は
  生の Messages API の JSON を `httpx2.MockTransport` で返す(SDK の parse の経路を通す)。**fixture `tests/fixtures/recognize/fib-S.synthetic/`
  は本物の録画ではなく正解から合成したもの**(実装時に API キーが無かった・§9 #41)。examples-v2 と v2-programs のうち型紙に収まる
  全本(S 13 本・M 11 本。clicker は続きの帯、M は 3 陣と root が先頭でない陣を含む)が元の `.jin` とバイト一致し、写真を 90° 回しても、
  EXIF の向きで持っていても読める
- 本物の写真での評価は `scripts/glyph_recognize_eval.py --photo x.jpg --expect x.jin [--record DIR]`(手動・要 API キー)。
  手直しの升数(持ち主ごとの銘帯の編集距離の和)と割合(合格線 2%・設計書 §9 #17)を出す。**撮影した fib / clicker での実測は未**(設計書 §6 の S4 の完了の条件)

## 11. エディタへの取り込み(S5・`POST /read`)

`jin editor` で開いた陣に、型紙の写真(または完全陣の PNG)を落とすと読み取って開き直す(設計書 §4.3・決定は §9 #42〜#45)。
HTTP の口の正本は `docs/spec/ops.md` §5.3(防御の 5 段と書き出しの 3 規律)。LSP の `jin/…` は 6 種のまま。

- 流れ: ツールバーの「写真を取り込む」かページへのドロップ → `POST /read`(画像の名前と base64)→ サーバが場面グラフにする
  (写真は §10.2 の認識器・PNG は §9 のデコーダ・隣に同じ画像の場面グラフがあればそれ)→ 構文解析(§9)→ 写真・
  `<写真名>.jinscene.json`・`<写真名>.jin` を開いている `.jin` の隣に書く → エディタが `<写真名>.jin` を開き直す
  (URL の `uri` も差し替える)→ 実行パネルで動く
- 書き先は**新しい名前だけ**(`<写真名>.jin` が在れば断る)。写真と場面グラフは同じ画像のものなら再利用する(場面グラフを手で直して
  同じ写真を落とし直すと、API を呼ばずに直した場面グラフから `.jin` を書く・§9 #42)
- `.jin` を書くのはモデルを組めたとき(JIN2xx が残っていても書く・§9 #43)。JIN3xx で組めなければ写真と場面グラフだけを書き、
  直してから取り込み直すよう出す
- **下敷き**: 写真を脇の欄に出し、取り込みの診断(JIN3xx / JIN306 / 場面グラフに写した JIN2xx)を場面グラフの `box`
  (`jin_glyph.scene.box_of`: 升はその `box`、銘帯は升の `box` を囲む矩形、図形・額縁は無し)で写真の上に枠として重ねる(§9 #44)。
  写真と図は幾何が違うので重ねない。取り込み後の正本は `.jin` で、写真は見比べるためのもの
- 外部送信: 写真は Anthropic の API に送る(送る前に `jin editor` の stderr へ 1 行)。API キーはサーバ側だけで読み、ブラウザに渡さない。
  PNG は送らない
- テスト: `packages/jin-cli/tests/test_readserver.py`(書き出しの規律と再利用)・`test_editor.py`(HTTP の 403 / 400 / 409 / 413 / 422)・
  `apps/editor/test/readClient.test.ts` / `importPanel.test.tsx`・`apps/editor/e2e/glyph.spec.ts`(`jin editor` の実プロセスで、
  合成した写真 → ローカルのモック API が S4 の合成した応答を返す → 図 → 写真の下敷き → 実行パネル。同じ写真の 2 回目は断る)

## 12. フリーハンド(S6・モード 1)

白紙に描いた陣の写真を、型紙(§10)と**同じ入口**(`jin check <写真>` / `jin fmt <写真> --out` / エディタの `POST /read`)で読む
(設計書 §3.6・決定は §9 #46〜#51)。描き方は完全陣(§8・`jin render x.jin --full` が手本)と同じ視覚文法: 正方形の額縁(銘帯は
内側を左上から時計回り)・陣と手順陣の円・各環の 12 時の**始まりの印**(描き手が描く・§4)・銘環は時計回りに外の周へ(周の最後に
継ぎの紋 `cont`)。root の陣を額縁の中央に、他の陣を root の周りに、手順陣を持ち主の陣の周りに、どちらも 12 時から時計回りに置く。
構文解析器(§9)から先は完全陣・型紙と共通で、場面グラフの `sheet` は `free`。

### 12.1 認識(`jin_glyph.recognize` の型紙なしの経路 + `jin_glyph.freehand`)

| 段 | 内容 |
|---|---|
| ⓪ 振り分け | §10.2 の位置合わせが等級 `none`(型紙が写っていない)を返したらこの経路へ。指定のフラグは無い(§9 #46) |
| ① 額縁 | 写真(長辺 1568 px)を送り、額縁の四隅を**描き手の**左上・右上・右下・左下の順で返させる(幅・高さに対する比)。手書きの字の正立と始まりの印から上を判断させる。額縁が無ければ失敗 |
| ② 正面化 | 四隅の射影変換で額縁を正方形(一辺は写真の中の額縁の大きさ・800〜3000 px)にする |
| ③ 環の形 | 正面図(長辺 1568 px)を送り、字の大きさ・額縁の行の深さ・環ごとの中心と周の半径(内から)・始まりの印の中心を返させる(一辺に対する比)。**升の位置は返させない**(§9 #47) |
| ④ 向きの直し | 額縁の中心に最も近い環の始まりの印が正面図の上でなければ、その向きへ 90° 単位で回して②からやり直す(Claude が描き手の上を取り違えても直る・§9 #48) |
| ⑤ 詰め直し | 環ごとに、周の帯の墨に同心円を最小二乗で当てはめて中心と半径を詰める(`refine_ring`。中心は周で共有・字の少ない周は当てはめに入れない・帯は隣の周との間隔の 0.48 倍まで・中心が 1.5 字より動いたら Claude の値)。額縁の行は辺ごとに帯の墨の重心で深さを詰める(`refine_inset`) |
| ⑥ 切り分け | 周(円)と額縁の行(正方形の内側を巡る道)に沿って、帯(字の大きさの ±0.75 倍)の墨を道の長さの座標に射影し、字の大きさの 0.3 倍より狭い隙間はつなぐ(`ring_blobs` / `frame_blobs`)。その前に**詠唱帯の線を捨てる**: 帯より 0.25 字広く墨を集め、道に沿った長さが 1.2 字を超え、道を 0.2 字ずつに区切ったどの区間でも厚みが 0.25 字未満の連結成分(`_without_band_lines`。字は縦の画で厚みを持つので捨てない)。周の詰め直し(`refine_ring`)も同じ墨で当てはめる(帯の弧が周どうしを引き寄せないように・Issue #129)。1 つの塊に字が 2〜3 個入ってよく、字を割らない側に寄せる(§9 #49)。周の最初の塊は始まりの角度に最も近い塊で、2 周目以降の 12 時は 1 周目の始まりの印の塊から決め直す(`ring_turns`) |
| ⑦ 読み | 塊の画像(余白 0.25 字・字の大きさ 1.2 倍を 96 px に縮める倍率)を 60 個ずつ、番号と並びの向き(`#n (top to bottom)`)の text と交互に送り、塊ごとに字の列(0 個以上・各 `t` / `v` / `unsure`)を返させる。字形表は始まりの印を含めた版(`glyph_table(with_start=True)`)、`system` はフリーハンド用(`FREE_SYSTEM`) |
| ⑧ 組み立て | 環の種類は銘帯の最初の構造の印(`s_circle` / `s_rite`)で決め、id を完全陣の配置の逆で振る(`assemble`): 陣は完全陣の棚の順(`_reading_order`。陣の塊 = 陣と最も近い陣に属する手順陣の、中心から上下左右への最大の張り出しで左上を求め、上端の差が最も小さい塊の張り出し以内なら同じ段。root `c0` は左上、`c1`… は段ごとに左から・#118 で「額縁の中心に最も近い陣」から変えた)、手順陣 `r<k>_<j>` は最も近い陣の周りを 12 時から時計回り。数え始めは隣との間隔の半分だけ手前(12 時の環が手のずれで最後に回らない・§9 #50)。陣でも手順陣でもない環・陣の無い手順陣は `u<n>`(kind `ring`)で残し、構文解析器が JIN305 で知らせる。始まりの印を読めなかった環は印を補わない(JIN301) |

- 升の `box` は写真の座標(塊の外接矩形を写真へ写したもの。塊に字が複数あれば同じ `box`)。額縁の図形の `at` は額縁の中心
- 要求は 型紙の位置合わせ 1 + 額縁 1 + 環の形 1 + 塊の読み(60 個ずつ)。fib は 5 本、clicker は 12 本
- 画像の処理は Pillow だけ(numpy も OpenCV も入れない)。JIN3xx は増やさない(始まりの印が無い = JIN301・帰属しない環 = JIN305)

### 12.2 テストと評価

- 写真は完全陣を斜めから撮った JPEG に見立て(`tests/glyph_photo.synthetic_free_photo`。手描きの陣と同じ視覚文法で、字はドットの
  清書体)、応答は正解(`full_layout` と `inscribe`)から合成する(`synthetic_free_responses`)。**Claude の座標には 0.3 字のずれ**
  (半径は 0.25 字・字の大きさは 1.1 倍)を入れ、⑤の詰め直しを通す。塊の読みは認識器と同じ切り分けの塊ごとに中の正解の升を返し、
  **正解の升が 2 つの塊に割れたら生成器が落ちる**。fixture `tests/fixtures/recognize/fib-free.synthetic/` は**本物の録画ではない**(§9 #51)
- `packages/jin-glyph/tests/test_recognize_free.py`: fib が元の `.jin` とバイト一致・写真の中で陣が回っていても・Claude が上を取り違えても
  読める・clicker(銘環が何周にもなる)も一致・始まりの印が読めなければ JIN301。`test_freehand.py` は切り分け・詰め直し・組み立ての純関数
- 本物の写真での評価は §10.4 と同じ `scripts/glyph_recognize_eval.py`(フリーハンドの写真もそのまま受ける。周の継ぎの紋は手直しに数えない)。
  **白紙に手で描いた fib の撮影と本物の API での実測は未**(設計書 §6 の S6 の完了の条件)

## 13. 鑑賞ページの銘環の帯(S7)

設計書 §6 の S7・§9 #52〜#55。正典は `docs/spec/v2/stage.md` §2.2(鑑賞ページの側)。

- `jin render x.jin --inscription`(`jin_render.render(..., inscription=True)`・LSP は `jin/renderSvg` の `inscription: true`)が、
  §8 の銘文(`frame_band` → 陣ごとに `circle_ring` → `rite_ring`)を 1 本の帯につなぎ、**通常の図と同じ座標系**の環 1.10〜1.30 に
  §8 の銘環と同じ規則(`full_layout.ring_cells`: 12 時に始まりの印・時計回り・周の終わりに継ぎの紋)で並べた SVG を返す。
  違うのは升の大きさだけ(帯に収まる最大・上限 0.06)。`--full` / `--focus` / `--trace` / `--upto` とは併用できず、v1 は断る
- 字形は §8 と同じ(`glyph_paths.glyph_d` / `font.char_d`)。`<text>` は出さない。升の pointer は欄の pointer、kind は持ち主の 13 種
- 完全陣・型紙の出力と往復の契約には触れない(帯は銘文を読むだけ)。テストは `packages/jin-render/tests/test_inscription.py`
  (同じ升の列・環に収まる・pointer の空間・決定性・fib のスナップショット)

