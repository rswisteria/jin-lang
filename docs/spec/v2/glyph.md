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
| 判別の紋(22 字) | loop / wait / sigil / asset / flow の種別、`on` の event、省略できる欄の印 | **決まった枠**(`slot`)だけ。読み手は枠ごとに 2〜5 個の候補から選ぶ |
| ラテン層 | 名前・数値リテラル・文字列の中身(日本語を含む) | 普通の文字。1 字 1 升 |

式紋の設計規則(設計書 §1.1): ラテン文字・数字に似せない / 対になるもの(括弧・`<` と `>` など)は鏡像 / 1 字 3 画以内。
字形は 1 升 = `viewBox="0 0 100 100"` の線で、`docs/spec/v2/glyphs/<id>.svg` に置く。**字形の正本は `jin_render.v2.glyph_paths`**(S2)で、
SVG は `uv run python scripts/generate_glyph_svgs.py` の生成物(手で編集しない・`--check` を pytest が呼ぶ)。**字形の形は人の承認済み(2026-10-03)**。
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
- 文字列は `quote_l` … `quote_r` で挟み、中身は文字のまま。升に描けない文字は `esc` + ラテン文字 1 字で書く(表は `jin_core.v2.glyph.ESCAPE_LETTERS`):
  `"` → `"`、`\` → `\`、改行 → `n`、タブ → `t`、CR → `r`、BS → `b`、FF → `f`、**空白 → `s`**(空白の升は空の升と見分けられないため。
  JSON のエスケープには無い、視覚層だけの規則)。その他の制御文字は `esc` + `u` + 16 進 4 桁
- 文字列の欄(陣の `description`・guard の `message`・asset の `path`・agent の `file`)も同じ書き方で括る。名前(`Name`)の欄は括らない
  (`emit` の `message`・`host` の `host` も名前。S2 で確定・実装は `jin_render.v2.inscribe`)
- root が `circles[0]` でないときだけ、額縁の銘帯の `seed` の後に root の添字(ラテンの数字・pointer `/root`)を書く(陣の並びは第 1 軌道の順と root の添字から戻す・S3・設計書 §9 #30)
- `$schema` は標準の URL なら額縁の銘帯に書かない(モデルに必ずあるので、書かれていなければ標準)。核なし陣の `flow.steps` は
  陣の名前の並び(`comma` 区切り)として陣の核の銘帯に書く。`let` の `type` は欄の数(3 つなら型あり)で見分ける
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

## 8. 完全陣(S2)

`jin render FILE --full`(`jin_render.render(model, full=True)` → `jin_render.v2.full.render_full`)。プログラムの情報をすべて載せた 1 枚の SVG で、
`<text>` を 1 つも使わない(銘文は線の紋と 6×8 のドットの字)。`data-jin-kind` は v2 の 13 種のまま、銘環の升は持ち主の kind と欄の pointer を持つ。

- 銘環(設計書 §1.3 / §2.3): 陣の銘環は 陣の核 → `description` → 記憶 → 道具 → `on` → `guard` → 委譲、手順陣の銘環は 手順陣の核 → ステップの前順。
  1 周目の 12 時に始まりの印、周の最後の升が `cont`、外の周の 12 時から続く。字は回さず正立で置く
- 額縁の銘帯: 額縁の内側を左上から時計回り(四隅の護符の区画を飛ばす)。四隅の護符は右上だけ中が丸(向きの印)
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

実測(2026-10-03・`uv run python scripts/measure_full_circle.py`):

| 例 | 一辺(升) | 銘環の周回数の最大 | 升の総数 | A3(280 mm 角)で 1 升(mm) |
|---|---|---|---|---|
| clicker | 137.6 | 4 | 492 | 2.04 |
| fib | 115.2 | 1 | 91 | 2.43 |
| othello | 614.5 | 7 | 5146 | 0.46 |
| paddle | 307.7 | 5 | 985 | 0.91 |
| tetris | 543.1 | 10 | 3793 | 0.52 |

すべて 1 枚に収まるが、A3 に刷ると 1 升は fib でも 2.4 mm、tetris / othello は 0.5 mm で、設計書 §2.4 の見積もり(手描き 5 mm・印刷 2 mm)に届かない。
主因は**配置の詰め方**: 第 1 軌道の距離が最大の塊で決まるので額縁の中が大きく空く(tetris は 3793 升に対して一辺 543 升)。
tetris / othello は当面「Jin が描いた PNG をそのまま読む」使い方に限る(設計書 §9 #8 の線引き)。詰め方の改善は S2 の後の課題
