# Jin v2(陣・第二版)— 汎用ビジュアル言語への拡張 設計

> 状態: ドラフト v0.1 / 2026-09-13
> 用途: Jin v1(ADK エージェント記述)の考え方を汎用言語へ広げ、wasm 上で動く実行系と GUI / グラフィック機能を持たせるための上位設計。v1 の要件書 `jin-requirements.md` と同じ粒度で書き、Claude Code に発注できる形にする。
> 未確定の点は §11 の決定事項表の既定案で進む。決定事項表の先頭 3 件(共存方式・実行ターゲット・式の置き方)を変えると作業量が大きく変わるので、変えるならこの 3 件だけ先に決める。

---

## 0. 目的・スコープ・非目標

### 継承する設計前提(v1 から変えない)

- **テキストは人間が読まない。** `.jin` は JSON の永続化形式で、視覚エディタと LLM の交換形式である
- **視覚表現はモデルからの純関数。** レイアウト情報はファイルに保存しない。同じモデルなら同じ SVG(バイト一致)
- **レンダラは Python 1 本。** エディタは LSP から SVG を受け取り `data-jin` でヒットテストするだけで、1 本の線も描かない
- **ファイルが唯一の状態。** 編集はすべて意味オペレーション(`jin/applyOps`)で、エディタは独自のモデル状態を持たない
- **美的制約 = 意味制約。** 環に載る紋は 12 個まで。超えたら「抽出」のコードアクション
- **デバッグはトレースの事後リプレイ。** トレースの各行は `pointer`(JSON Pointer)で描かれた要素と結ばれる

### 新たに加える前提

- **実行はブラウザで、wasm 上で行う。** `jin build` の出力をブラウザで開けば動く
- **実行は決定的である。** 固定タイムステップ・seed 付き乱数・tick 境界で消費される入力。「seed + 入力ログ」から同じトレースと同じ画面列が再現できる。これが無いと v1 の Phase 6(リプレイ)の機構が再利用できない
- **画面と UI は即時モード(immediate mode)。** 毎 tick「描くもの」を宣言し、結果は**記録可能な表示リスト**になる。ブラウザ無しの Python から画面列をゴールデン比較できる

### 目的

簡単な 2D ゲーム(ボールとパドル、クリッカー、避けゲー程度)を魔法陣として記述・編集・実行・デバッグできる**汎用**言語にする。汎用とは、ゲームでない純粋な計算(数列・文字列処理・状態機械)も同じ語彙で書けることを指す(§2.5 に例)。

### 成功条件

1. `.jin`(v2)1 つから `jin build --out dist/` で**静的ファイル一式**が生成され、ブラウザで開くと動く
2. 同じ `.jin` から常に同じ SVG(v1 と同じスナップショット規律)
3. Claude Code が JSON Schema と `jin check --json` の hint だけでゲームを書き切れる
4. `jin run`(ヘッドレス)が **ブラウザ無し**で tick を回し、トレースと表示リストを出す。ブラウザ(wasm)側の実行と**同じ入力ログから同じトレース**が出る(パリティテスト)
5. エディタの「実行」パネルでゲームを動かし、入力を記録して、タイムラインをスクラブすると魔法陣上に発火がオーバーレイされる(v1 Phase 6 の機構の再利用)

### 非目標(v2 では作らない)

- 3D、物理エンジン、ネットワーク対戦、音声合成(単音 `tone` と音源再生のみ)
- 保持モード(retained mode)の GUI ウィジェット木。テキスト入力欄・スクロール領域は v2.1(文字入力は v2.1 で `input.text()` の読み取りとして足した。欄はウィジェットにしない・§11 #53)
- 高速な JS↔wasm 相互運用の最適化。tick あたりの越境は往復 1 回に固定する(§4.3)
- ホスト言語(Python / JS)のコードを `ref` で参照すること。**v2 に `ref` は無い。** 外部世界へはホスト能力カタログ(§3.4)だけで触る。この結果 v1 の S1(任意コード実行)の危険性が v2 には**無い**(例外は v2.1 の `agent` の sigil・§11 #55。v1 の陣を呼ぶので、その `.jin` の `ref` が v1 と同じ経路で import される。`agent` を持たない v2 には S1 は無い)
- v1 の `.jin`(`version: 1`)の意味を変えること。v1 の契約テストには触れない(§1.3)
- 直接の wasm バイナリ出力(v2.1 候補。§4.5)

---

## 1. 全体アーキテクチャ

### 1.1 技術選定

| 領域 | 選定 | 理由 |
|---|---|---|
| 永続化形式 | JSON + JSON Schema draft 2020-12(v1 と同じ)。`version: 2` | v1 の正準形・位置付きパーサ・pointer→range をそのまま使う |
| 意味モデル | Pydantic v2(`jin_core.v2.model`)。schema はここから生成 | v1 と同じ「モデルが唯一の真実」 |
| 葉の式 | 独自の小さな式文法(§3.3)。Lark で構文解析し、位置を持つ | 制御構造は JSON ノード、葉だけテキスト。全部テキストなら描けず、全部ノードなら LLM が書けない |
| 型 | 静的・最小(`num` / `bool` / `str` / `list<T>` / form)。局所変数は推論 | 診断が式の誤りを位置付きで指せる。IL を静的サブセットに保てる |
| **実行ターゲット** | **中間言語 JIL(Lua 5.4 の静的サブセット)を出力し、ブラウザでは Wasmoon(Lua 5.4 を wasm に コンパイルした VM)で実行**。CI では lupa(Lua 5.4.8 同梱)でヘッドレス実行 | §4.1 の比較表。決定性・コルーチン・ブラウザ無しの CI・将来の直接 wasm 出力の道筋の 4 点で最良 |
| 画面 / UI / 音 | 即時モード。Lua 側のプレリュードが**表示リスト**を組み立て、tick の戻り値として 1 回だけホストへ渡す | 実装が Lua 1 本(ブラウザと Python で同一)。越境コストが tick あたり往復 1 回 |
| ブラウザ側プレイヤー | `apps/player`(TypeScript、依存は Wasmoon のみ)。`<canvas>` に表示リストを描き、入力を tick 単位で集め、WebAudio で音を出す | エディタから iframe で埋め込む。単体でも `dist/index.html` として配れる |
| レンダラ(魔法陣) | `jin_render.v2`(Python、v1 と同じ `fmt_coord` / 2 色 / 属性のみ) | v1 の決定性規律を継承 |
| LSP / エディタ | 既存 `jin-lsp` / `apps/editor` に v2 を載せる。`jin/…` は 6 種のまま | Phase 4〜6 の骨格を使う |
| テスト | pytest + syrupy(SVG / IL / 表示リスト)+ pytest-lsp + Playwright(パリティ 1 本) | ネットワーク・API キー不要 |

外部 API の事実(2026-09-13 の実測。一次証拠は `delivery/20260904-1445-jin/wasm-api-probe.md`。スクリプトと生出力つき):

- Wasmoon 1.16.0 は公式 Lua 5.4 を wasm へコンパイルした VM(`_VERSION` は `Lua 5.4`。パッチ版はバイナリに無い)。配布物は `glue.wasm` 271,581 B(gzip 111,128 B)+ `index.js` 151,652 B(gzip 39,177 B)。`lua.global.set` で JS 関数を Lua へ渡し、`lua.global.call` で Lua 関数を呼ぶ
- **yield はホスト境界を跨げない。** JS 関数の中で `coroutine.yield` すると `attempt to yield across a C-call boundary`、JS から `global.call` で再入した先で yield すると **PANIC + `abort()`**。→ §4.3 の「ホストは Lua を呼ぶ側であり、Lua はホストを呼ばない」契約で回避する。純 Lua のスケジューラを `tick()` から 3 回回して動くことは実測済み
- **Lua→JS のテーブル変換は遅い。** 50 行 × 5 値の入れ子テーブルを `global.call` の戻りで受けると約 600 µs/回。**JSON 文字列で返して `JSON.parse` すると 35.5 µs**。→ `tick` の戻り値は JSON 文字列にする(§4.3)。また Lua→JS で integer / float の区別と 64 bit 精度が落ちる(`math.maxinteger` が `9223372036854776000` になる)ので、境界を越えるのは浮動小数と文字列だけにする
- `global.set('load', null)` は Wasmoon 側の `TypeError` で**失敗して `load` が残る**。`undefined` を渡すか Lua 側で `nil` を代入すれば消える。`openStandardLibs: false` は base ライブラリ(`pairs` / `pcall` / `type` …)ごと無くなるので使わない
- `pairs` の順序は 1 つの engine / runtime の中では安定だが、engine を跨ぐと変わる(Wasmoon・lupa とも実測)。JIL が `pairs` を使わない(§4.4)根拠
- lupa 2.8 の**既定の `LuaRuntime` は Lua 5.5.1**。`import lupa.lua54`(Lua 5.4.8)を明示して Wasmoon と揃える。`register_eval=False` だけでは `python.builtins`(`open` を含む)が残るので `register_builtins=False` と `globals().python = None` も要る
- wasm-GC は Chrome 119 / Firefox 120 / Safari 18.2 で出荷済み。直接 wasm 出力(v2.1)の前提は揃っている。Python 側は `wasmtime` 48.0.0 が既定の `Config()` で wasm-GC を assemble(`wat2wasm`)・実行でき、同じ binary が V8 12.4 / Chrome for Testing 151 で走る(`wasmgc-api-probe.md`。Issue #53 で実測)

### 1.2 リポジトリ構成(追加分)

```
jin/
  schemas/jin.schema.json          # v1(1 バイトも変えない。§11 #16)
  schemas/jin-v2.schema.json       # v2 のスキーマ(jin_core.v2.model から生成。`jin schema --version 2`)
  schemas/abilities.json           # ホスト能力カタログ(jin_core.v2.abilities から生成。§3.4 / §11 #19)
  docs/spec/
    v2/model.md                    # v2 モデル仕様
    v2/expr.md                     # 葉の式文法と型規則
    v2/abilities.md                # ホスト能力カタログの意味論(表示リストの契約を含む)
    v2/runtime.md                  # tick の意味論・決定性・トレース行の契約
    v2/jil.md                      # 中間言語 JIL の契約(許す Lua のサブセット)
    v2/layout.md                   # v2 のレイアウトと data-jin-kind
    v2/diagnostics.md              # JIN2xx(番号帯は v1 と分ける。v1 の diagnostics.md は触らない)
    v2/ops.md                      # v2 のオペレーション(v1 の ops.md は触らない)
  packages/
    jin-core/src/jin_core/         # v1 のモジュールは動かさない(§11 #17。全パッケージがフルパスで import している)
    jin-core/src/jin_core/v2/      # model / expr(文法・型) / spans / abilities(カタログの正本) / semantic / ops
    jin-core/src/jin_core/check.py # root_model_for が version で v1 / v2 へ振り分ける唯一の入口
    jin-wasm/src/jin_wasm/         # jil(契約・禁止語走査)/ prelude.lua / codegen(v2 → JIL)/ runtime(lupa)/ jinrec / bundle。カタログは jin_core.v2.abilities を import
    jin-render/src/jin_render/v2/  # v2 レイアウト
  apps/
    editor/                        # 既存。実行パネル(iframe)と v2 のフォームを足す
    player/                        # 新規。Wasmoon + canvas + 入力 + 音。ビルド物は jin-wasm がバンドルに同梱
  examples-v2/                     # 恒久的に examples/ の外(§11 #18。examples/ は v1 の契約が「3 本」と数える)
    paddle/paddle.jin              # §2.2 の例(ボールとパドル)
    clicker/clicker.jin            # UI だけのゲーム(ui.button / ui.label)。wait を含むループの実例
    fib/fib.jin                    # 純粋な計算(§2.5)
    tetris/tetris.jin              # 後から足した 4 本目(10×20 の盤面を list<num> で持つ・型紙 Piece・wait の重力・random・行消去。README の動画の題材)
  tests/fixtures/errors/v2/        # v2 の診断 fixture(各コードちょうど 1 つ。v1 の走査は非再帰なので混ざらない)
```

依存は一方向のまま:

```
jin-core  ←  jin-adk | jin-render | jin-wasm  ←  jin-lsp  ←  jin-cli
```

`jin-wasm` は `jin-adk` / `jin-render` と**兄弟**(layers 契約の 1 要素に `|` で並べる)。`jin-core` / `jin-render` は引き続き `google-adk` にも `lupa` にも依存しない。`lupa` に依存するのは `jin-wasm` だけ。`apps/player` は Python を import せず、`schemas/abilities.json` だけを読む(`apps/editor` が `jin.schema.json` / `jin-v2.schema.json` / `abilities.json` を読むのと同じ例外)。

### 1.3 v1 との共存(再利用と作り直しの境界)

同一リポジトリ・同一 `.jin` 拡張子・**`version` で振り分け**る。v1 の契約テストが等号で固定している値(サブコマンド 9 個 / `data-jin-kind` 9 種 / `jin/` 6 種 / v1 の診断コードを増やさない)には触れない。v2 は**別の集合**を別のテストで固定する。

| 部品 | v2 での扱い |
|---|---|
| 位置付き JSON パーサ・pointer→range・正準形(`jin_core.canonical`) | **そのまま使う**。正準形の規則(キー順 = スキーマ順、既定値は書かない)は v2 にも適用 |
| ops の枝組み(JSON Pointer 指定・逆オペレーション・合成) | **そのまま使う**。v2 のオペレーション集合を足す |
| LSP 骨格(stdio / ws、デバウンス、last-good、`jin_converter`、`jin/…` 6 種) | **そのまま使う**。`jin/renderSvg` は version で v1 / v2 レンダラへ振る |
| エディタの殻(SVG ヒットテスト、schema フォーム、5 表示状態、undo/redo、スクラバ) | **そのまま使う**。v2 の `data-jin-kind` を選択の種別に足し、実行パネルを 1 枚足す |
| `fmt_coord` / 2 色 / 属性のみ SVG / `xml_chars` | **そのまま使う** |
| モデル・意味検査・診断 | **作り直し**(`jin_core.v2`)。JIN001 / 002 は共通、意味の同じ JIN010 / 011 / 012 / 013 / 020 / 022 / 060 は**同じ番号を使う**(§6) |
| レイアウト規則 | **作り直し**(`jin_render.v2`)。環の半径は v1 と同じ 4 本を使い回す(§7) |
| コード生成・実行系 | **作り直し**(`jin-wasm`)。v1 の `jin_adk` とは無関係 |
| CLI | サブコマンドは 9 個のまま。`build` / `run` / `render` が version で振り分ける(§5) |

**判断**: 別リポジトリにしない理由は、上の「そのまま使う」行が実装量の半分以上を占めるため。別パッケージ群(`jin2-*`)にしない理由は、`.jin` の LSP ルーティングが拡張子単位で 1 サーバに落ちるため、結局 1 つのサーバが両方を知る必要があるから。

---

## 2. モデルとシリアライズ形式

### 2.1 語彙(v1 との対応)

| v2(JSON キー) | 意味 | v1 での対応物 | 描画 |
|---|---|---|---|
| `stage` | 舞台。論理解像度・fps・seed・アセット | (無し) | 最外の額縁 |
| `forms[]` | 型紙。名前付きレコード型 | (無し) | 額縁の隅の印章 |
| `circles[]` | 陣。状態と手順を持つ実行単位、または flow | `circles[]` | 陣(同心円) |
| `core` | 核。**入口の手順名**(陣に入ったとき走る手順) | `core`(モデル名) | 核(中心) |
| `state[]` | 記憶環。型付きの状態。`out: true` は**公開**(他の陣が `Play.score` で読める・陣を出ても残る) | `state[]` / `out` | 記憶環の四角 |
| `sigils[]`(kind: host / summon / agent) | 道具環。**ホスト能力の名前空間**(`canvas` など)の許可、他の陣の手順の召喚、または v1 の陣(LLM)への問い(v2.1・#55) | `tools[]`(builtin / summon) | 道具環の紋、核から放射線 |
| `rites[]` | 手順環。名前付き手続き(引数・戻り値・ステップ列) | (無し。v1 は指示環 = rune) | 手順環の小陣。focus で中を開く |
| `rites[].steps[]` | ステップ(§2.3 の 11 種) | (無し) | 小陣の環に沿った紋・弦・多角形 |
| `boundary.on[]` | 境界環。イベント(`tick` / `key` / `pointer` / `message` / `exit`)→ 手順 | `boundary.guards[]`(コールバック) | 境界環の刻印 |
| `boundary.guards[]` | 不変条件(`assert` 式)。デバッグビルドで毎 tick 検査 | `boundary.guards[]` | 境界環の刻印(別記号) |
| `delegate[]` | 委譲。`transfer` ステップで制御を渡せる相手 | `delegate[]` | 境界環内側の小円、核と破線 |
| `flow.kind = sequence` | 直列(前の陣が `finish` したら次) | `sequence` | 開いた弦列 |
| `flow.kind = parallel` | 同 tick 内で配列順に全員動く(§4.2 の二重バッファで順序非依存) | `parallel` | 弦なし対称配置 |
| `flow.kind = loop` | `exit` 式が真になるまで繰り返す | `loop` | 閉じた多角形 / 星形 |
| `root` | 入口の陣 | `root` | 最外の陣 |

circle は v1 と同じ 2 種。**核あり**(`core` を持つ → 実行単位)と**核なし**(`flow` だけ)。両方持つ / 両方無いのはエラー(JIN022 と同じ意味なので同じ番号)。

### 2.2 ファイル形式(例: ボールとパドル)

```json
{
  "$schema": "https://xtone.internal/jin/schemas/jin-v2.schema.json",
  "version": 2,
  "root": "Game",
  "stage": { "width": 320, "height": 180, "seed": 7 },
  "forms": [
    { "name": "Ball", "fields": [
      { "name": "x", "type": "num" }, { "name": "y", "type": "num" },
      { "name": "vx", "type": "num" }, { "name": "vy", "type": "num" } ] }
  ],
  "circles": [
    { "name": "Game", "flow": { "kind": "loop", "steps": ["Play", "Result"], "exit": "Result.quit" } },
    {
      "name": "Play",
      "core": "begin",
      "state": [
        { "name": "ball",   "type": "Ball", "init": "Ball{x: 160, y: 40, vx: 90, vy: 70}" },
        { "name": "paddle", "type": "num",  "init": "140" },
        { "name": "score",  "type": "num",  "init": "0", "out": true }
      ],
      "sigils": [
        { "name": "canvas", "kind": "host", "host": "canvas" },
        { "name": "input",  "kind": "host", "host": "input" },
        { "name": "audio",  "kind": "host", "host": "audio" }
      ],
      "rites": [
        { "name": "begin", "steps": [
          { "do": "set", "target": "score", "expr": "0" },
          { "do": "cast", "target": "serve" } ] },
        { "name": "serve", "steps": [
          { "do": "set", "target": "ball", "expr": "Ball{x: 160, y: 40, vx: 90, vy: 70}" } ] },
        { "name": "step", "params": [ { "name": "dt", "type": "num" } ], "steps": [
          { "do": "if", "cond": "input.key(\"ArrowLeft\")",
            "then": [ { "do": "set", "target": "paddle", "expr": "max(0, paddle - 180 * dt)" } ] },
          { "do": "if", "cond": "input.key(\"ArrowRight\")",
            "then": [ { "do": "set", "target": "paddle", "expr": "min(280, paddle + 180 * dt)" } ] },
          { "do": "set", "target": "ball.x", "expr": "ball.x + ball.vx * dt" },
          { "do": "set", "target": "ball.y", "expr": "ball.y + ball.vy * dt" },
          { "do": "if", "cond": "ball.x < 0 or ball.x > 320",
            "then": [ { "do": "set", "target": "ball.vx", "expr": "-ball.vx" } ] },
          { "do": "if", "cond": "ball.y < 0",
            "then": [ { "do": "set", "target": "ball.vy", "expr": "-ball.vy" } ] },
          { "do": "if", "cond": "ball.y > 170 and ball.x >= paddle and ball.x <= paddle + 40",
            "then": [
              { "do": "set", "target": "ball.vy", "expr": "-abs(ball.vy) * 1.05" },
              { "do": "set", "target": "score", "expr": "score + 1" },
              { "do": "cast", "target": "audio.tone", "args": ["440", "50"] } ] },
          { "do": "if", "cond": "ball.y > 180", "then": [ { "do": "finish" } ] },
          { "do": "cast", "target": "paint" } ] },
        { "name": "paint", "steps": [
          { "do": "cast", "target": "canvas.clear", "args": ["\"#000\""] },
          { "do": "cast", "target": "canvas.ink",   "args": ["\"#fff\""] },
          { "do": "cast", "target": "canvas.rect",   "args": ["paddle", "172", "40", "4"] },
          { "do": "cast", "target": "canvas.circle", "args": ["ball.x", "ball.y", "3"] },
          { "do": "cast", "target": "canvas.text",   "args": ["\"SCORE \" ++ str(score)", "4", "4"] } ] }
      ],
      "boundary": {
        "on": [ { "event": "tick", "rite": "step" } ],
        "guards": [ { "assert": "score >= 0", "message": "score は負にならない" } ]
      }
    },
    {
      "name": "Result",
      "core": "show",
      "state": [ { "name": "quit", "type": "bool", "init": "false", "out": true } ],
      "sigils": [
        { "name": "canvas", "kind": "host", "host": "canvas" },
        { "name": "ui",     "kind": "host", "host": "ui" }
      ],
      "rites": [
        { "name": "show", "steps": [
          { "do": "set", "target": "quit", "expr": "false" },
          { "do": "wait", "ticks": "20" } ] },
        { "name": "menu", "steps": [
          { "do": "cast", "target": "canvas.clear", "args": ["\"#000\""] },
          { "do": "cast", "target": "canvas.text", "args": ["\"SCORE \" ++ str(Play.score)", "120", "60"] },
          { "do": "if", "cond": "ui.button(\"RETRY\", 120, 100, 80, 24)", "then": [ { "do": "finish" } ] },
          { "do": "if", "cond": "ui.button(\"QUIT\", 120, 130, 80, 24)",
            "then": [ { "do": "set", "target": "quit", "expr": "true" }, { "do": "finish" } ] } ] }
      ],
      "boundary": { "on": [ { "event": "tick", "rite": "menu" } ] }
    }
  ]
}
```

読み方:

- `Game` は核なし陣(loop)。`Play` が `finish` すると `Result` へ、`Result` が `finish` すると `exit` 式 `Result.quit` を評価し、偽なら `Play` からやり直す
- `Play` に入ると核 `begin` が走る。以後、毎 tick `boundary.on` の `tick` → `step(dt)` が走る
- `step` は **9 ステップ**、`paint` は **5 ステップ**。描画を `paint` に分けているのは、`cast paint` の位置に `paint` の 5 つを戻すと 13 ステップになり JIN210(12 超過)で落ちるから。「抽出」のコードアクションがこの分割を機械的に行う(入れ子の中の個数は別勘定なので、`if` の `then` にあるステップは数えない)
- `Result.menu` は `tick` の手順だが `params` を持たない。イベントの引数は**前方部分を省略してよい**(§6 JIN221)。`Result` は `ui.button` を使うが `input` の許可を持たない。`ui` は tick の入力スナップショットを自前で読むので `input` は要らない(§3.4)
- `Result.show` の `wait` は 20 tick 待つ。待っている間も `on tick` は届く(§4.2)ので `menu` は描かれる
- `Play.score` は `out: true` なので `Result` から読め、`Play` を出ても残る
- **文字列リテラルの中の `"`** は JSON のエスケープ。式文法側の文字列は `"…"` のみ(`'` は使わない)

### 2.3 ステップ(11 種)

`do` による判別共用体。**12 種目を足さない**(足すなら要件レベルの変更)。

| `do` | 追加キー | 意味 | JIL への対応 |
|---|---|---|---|
| `set` | `target`(代入先の式: state / 局所 / `a.b` / `xs[i]`)、`expr` | 代入 | `=` |
| `let` | `name`、`expr`、`type`(省略時は推論) | 局所変数の導入(手順内スコープ) | `local` |
| `cast` | `target`(自陣の手順名 / `sigil.member` / summon 名)、`args[]`、`into`(省略可) | 呼び出し。戻り値を `into` へ | 関数呼び出し |
| `if` | `cond`、`then[]`、`else[]`(省略可) | 分岐 | `if` |
| `loop` | `kind: each \| while \| count`、`each` は `name` + `in`、`while` は `cond`、`count` は `times` + `name`(省略可)、`steps[]` | 繰り返し | `for` / `while` |
| `break` | — | 直近の `loop` を抜ける | `break` |
| `wait` | `ticks` または `until`(式) | 次の tick 以降まで手順を中断(コルーチン) | `coroutine.yield` |
| `emit` | `circle`、`message`、`args[]` | 相手の `on message` へ**次の tick に**配達 | メッセージキューへ push |
| `return` | `expr`(省略可) | 手順から戻る | `return` |
| `finish` | — | 陣を終える(親の flow が進む) | 陣の状態を `done` にして戻る |
| `transfer` | `circle` | `delegate[]` の相手へ制御を渡す。相手が `finish` すると戻る(スタック) | 陣スタックへ push |

**アトミックな effect は 3 つだけ**(`push(xs, v)` / `removeAt(xs, i)` / `clear(xs)`)で、これは `cast` の target として**宣言なしで**使える(道具環の枠を消費しない)。数値・文字列の純関数(`abs` / `min` / `max` / `floor` / `ceil` / `round` / `sqrt` / `sin` / `cos` / `atan2` / `clamp` / `len` / `str` / `sub`)は**式の中**で使う(§3.3)。

### 2.4 正準形

v1 §2.3 と同じ規則。加えて:

- 式(`expr` / `cond` / `init` / `assert` / `exit` / `args[]` … schema の印 `x-jin-expr` を持つ欄)は v2 では文字列のまま保存していたが、**v2.1 で AST から書き戻した正準形にする**(expr.md §8・§11 #48)。空白は演算子の両側に 1 つ、括弧は必要なときだけ、数値は `str(x)` の書式、文字列は最小エスケープ。**構文エラーの式は変えない**(入力を失わない)
- `params: []` / `else: []` / `args: []` は既定値なので書かない

### 2.5 汎用性の確認(純粋な計算)

```json
{ "name": "Fib", "core": "main",
  "state": [ { "name": "answer", "type": "num", "init": "0", "out": true } ],
  "rites": [
    { "name": "fib", "params": [ { "name": "n", "type": "num" } ], "returns": "num", "steps": [
      { "do": "let", "name": "a", "expr": "0" }, { "do": "let", "name": "b", "expr": "1" },
      { "do": "loop", "kind": "count", "times": "n", "steps": [
        { "do": "let", "name": "t", "expr": "a + b" },
        { "do": "set", "target": "a", "expr": "b" }, { "do": "set", "target": "b", "expr": "t" } ] },
      { "do": "return", "expr": "a" } ] },
    { "name": "main", "steps": [
      { "do": "cast", "target": "fib", "args": ["20"], "into": "answer" },
      { "do": "finish" } ] } ] }
```

道具環が空でも動く。`jin run examples/fib/fib.jin --ticks 1` が `Fib.answer = 6765` をトレースの `set` 行に残す。

---

## 3. 静的意味論

### 3.1 名前とスコープ

- 名前が ID(v1 と同じ)。`circles[].name` はファイル内一意、`state` / `sigils` / `rites` は陣内一意、`forms[].name` はファイル内一意で circle 名と衝突不可
- 式の中の識別子の解決順: 局所(`let` / `params` / `loop.name`)→ 自陣の `state` → `sigils` の名前空間(`canvas.rect`)→ 他の陣の公開 state(`Play.score`)→ 型紙のコンストラクタ(`Ball{…}`)→ 純関数
- 他の陣の**非公開** state は読めない。書けるのは自陣の state だけ(他陣への影響は `emit` / summon 経由)

### 3.2 型

`num`(f64)/ `bool` / `str`(コードポイント列)/ `list<T>` / form 名。`num` に整数型は無い(添字は `floor` される)。局所変数は初期化式から推論。`state[].init` は**定数式**(リテラル・型紙コンストラクタ・純関数のみ。JIN250)。型紙コンストラクタ `Ball{…}` は**全欄必須**(欠けた欄・余分な欄は JIN202。既定値は v2 では持たない)。

### 3.3 葉の式文法(`docs/spec/v2/expr.md`)

```
expr    := or
or      := and ("or" and)*
and     := not ("and" not)*
not     := "not" not | cmp
cmp     := add (("==" | "!=" | "<" | "<=" | ">" | ">=") add)?
add     := mul (("+" | "-" | "++") mul)*          # ++ は str 連結
mul     := unary (("*" | "/" | "%") unary)*
unary   := "-" unary | postfix
postfix := primary ("." NAME | "[" expr "]" | "(" args ")")*
primary := NUMBER | STRING | "true" | "false" | NAME
         | "(" expr ")" | NAME "{" (NAME ":" expr ("," NAME ":" expr)*)? "}"   # 型紙
         | "[" (expr ("," expr)*)? "]"                                          # list
```

- 位置付きで構文解析する。式の中の誤りは、JSON 文字列の中の**列オフセット**を pointer→range に足して報告する(`/circles/1/rites/2/steps/0/cond` + 式内の列)
- 文字列は `"…"`、エスケープは JSON と同じ集合。`'` は使わない
- 短絡評価(`and` / `or`)。`/` は常に浮動小数。`%` は `a - floor(a/b)*b`
- 比較は同型のみ。`==` は `num` / `bool` / `str` のみ(list / form の構造比較は無い)
- **戻り値を持つホスト能力(`ui.button` / `random.next` / `input.key` …)は式の中で呼べる。** 評価順は左から右で、`and` / `or` の短絡に従う。表示リストへの追記順もこの評価順(決定性はこの規則に掛かる)

### 3.4 ホスト能力カタログ(`schemas/abilities.json`)

Pydantic 定義(`jin_wasm.abilities`)から生成し、**補完・型検査・プレイヤーの TS 型・Lua プレリュード**の 4 つが同じカタログを読む。名前空間の単位で道具環に載せる(`kind: host`)。1 つの名前空間で 1 枠なので、道具環が 12 枠を超えることは実質無い。

| 名前空間 | メンバ(v2) | 純 / 効果 | 戻り |
|---|---|---|---|
| `canvas` | `clear(color)` / `ink(color)` / `rect(x,y,w,h)` / `circle(x,y,r)` / `line(x1,y1,x2,y2)` / `text(s,x,y)` / `sprite(name,x,y)` | 効果(表示リストへ追記) | — |
| `input` | `key(name)`(押下中)/ `pressed(name)`(この tick に押された)/ `pointer()` / `text()`(この tick に確定した文字列。v2.1 で実装・§11 #53) | 純(tick の入力スナップショットを読む) | `bool` / `Pointer{x,y,down}` / `str` |
| `ui` | `button(label,x,y,w,h)` / `label(s,x,y)` | 効果 + 純(描いて、この tick に離されたら真) | `bool` / — |
| `audio` | `tone(hz,ms)` / `play(name)` | 効果(音リストへ追記) | — |
| `random` | `next()` / `range(lo,hi)` | 効果(seed 付き PCG32 の状態を進める) | `num` |
| `storage` | `get(key)` / `set(key,val)` | 純(boot 時の写しと自分の書き込みを読む)/ 効果(書き込みの一覧へ追記。v2.1 で実装・abilities.md §8) | `str` / — |

色は `"#rgb"` / `"#rrggbb"` の文字列。`sprite` の `name` は `stage.assets[]` の名前(JIN205 で未知名を落とす)。**壁時計・`Date` に相当する能力は無い**(決定性)。`ui` は tick の入力スナップショットを自前で読むので、`ui` を使う陣に `input` の許可は要らない(JIN230 は `on key` / `on pointer` を受ける陣だけを見る)。

### 3.5 flow と陣の生存

- 陣は `entered`(核の手順が走り始めた)→ `active`(イベントを受ける)→ `done`(`finish` した)の 3 状態
- `sequence`: 子を配列順に。子が `done` になったら次へ。全員 `done` で自分も `done`
- `parallel`: 全員を同時に `entered`。毎 tick 配列順にイベントを配る。全員 `done` で自分も `done`
- `loop`: `sequence` を繰り返す。1 周終わるごとに `exit` 式(公開 state だけを参照できる。JIN220)を評価
- `transfer` で渡した先が `done` になると、渡した側が `active` に戻る(スタック)。`delegate[]` に無い相手への `transfer` は JIN011

---

## 4. 実行系(`jin-wasm`)

### 4.1 実行ターゲットの比較

| 候補 | wasm 上で動く | 起動サイズ | 決定性 | canvas / 入力の相互運用 | フレーム間 yield | ブラウザ無しの CI | 直接 wasm 出力への道 |
|---|---|---|---|---|---|---|---|
| **JIL(Lua 5.4 静的サブセット)→ Wasmoon** | ○ | wasm 272 kB + JS 152 kB(gzip 111 + 39 kB) | ○(浮動小数は IEEE、反復順序は配列だけ使う) | ○ `global.set` / `global.call` | ○ Lua コルーチン(JS 境界を跨がなければ) | ○ lupa(Lua 5.4.8) | ○ IL が静的なので後から wasm-GC バックエンドを足せる |
| 直接 wasm-GC 出力 | ◎ | 最小 | ◎ | △ 文字列・list のランタイムを自作 | △ 継続を自前で変換(jil.md §6.5 の状態機械) | ○ wasmtime 48(既定で GC 有効。`wasmgc-api-probe.md` で実測) | — |
| Python → Pyodide | ○ | 10 MB 超 | ○ | ○ | ○ | ◎ そのまま Python | × |
| 自作 VM(Rust → wasm) | ○ | 小 | ◎ | ○ | ◎ | ○ 同じ crate | ○ |
| JS 出力 | × | — | ○ | ◎ | △ | △ node | × |

推奨は先頭行。理由は「IL を契約にして VM を差し替え可能にする」設計が最も安く成立するから。自作 VM は最終形として魅力があるが、v2 で書く量が倍になる。JIL の契約(§4.4)を守っている限り、v2.1 でバックエンドを足しても `.jin` とトレースの契約は変わらない。

### 4.2 tick の意味論(`docs/spec/v2/runtime.md`)

固定タイムステップ `dt = 1 / stage.fps`。ホストは tick 番号 `t` と**入力スナップショット**(この tick に属する `key` / `pointer` のイベント列と押下状態)を渡し、Lua は表示リストと音リストを返す。

1. 前 tick に `emit` されたメッセージを、宛先の `on message` の手順へ配達する
2. `wait` 中の手順(コルーチン)を、陣木の深さ優先・配列順に再開する。`ticks` が尽きた / `until` が真になったものだけ
3. `active` な各陣へ、配列順に `key` / `pointer` イベント、次に `tick` を配る(`parallel` の子も配列順)
4. `out: true` の state を**確定**する(二重バッファ。他の陣が読む `Play.score` はこの tick の開始時点の値)。これにより `parallel` の子の実行順が結果に影響しない
5. デバッグビルドなら `guards[].assert` を評価し、偽ならトレースに `assert` 行を残す(実行は止めない)
6. `finish` した陣の親 flow を進める。新しく `entered` になった陣の核の手順を**この tick 内で**走らせる(その陣に今 tick の `tick` イベントは届かない)
7. 表示リスト・音リストを返す。デバッグビルドならトレース行を返す

ゲーム時間はすべて tick 数で表す。`wait` 中も `on` は届く(§2.2 の `Result`)。

### 4.3 ホストと Lua の境界(越境は tick あたり往復 1 回)

**ホストは Lua を呼ぶ側であり、Lua はホストを呼ばない。** ホストが呼ぶ Lua 関数は `boot(seed, manifest)` と `tick(t, inputs)` の 2 つだけ。`canvas` / `ui` / `audio` / `random` / `input` は**すべて Lua のプレリュード**(`prelude.lua`)に実装され、`tick` の戻り値の表示リストとしてホストへ渡る。これで:

- Wasmoon の「JS コールバック内で yield できない」制約に当たらない(`wait` の yield は純 Lua のスケジューラ内で起きる)
- ブラウザ(TS)と Python(lupa)のホストが**同じ Lua を走らせる**。ホスト側の実装は「表示リストを描く」「入力を集める」「音を鳴らす」だけで、ゲームの意味論を 2 度書かない
- 越境コストが tick あたり 1 往復に固定される。**戻り値は JSON 文字列 1 本**(プレリュードが直列化し、ブラウザは `JSON.parse`、Python は `json.loads`)。Wasmoon のテーブル変換(約 600 µs/tick)を避け、integer / float の区別が落ちる経路を通らない(probe A.3 / A.9)

表示リストの形(トレースの `frame` 行と同じ。`tick` の戻り値の JSON の一部):

```json
{ "seq": 41, "tick": 12, "kind": "frame",
  "ops": [["clear","#000"],["rect",140,172,40,4],["circle",178.5,58.2,3],["text","SCORE 1",4,4]],
  "audio": [["tone",440,50]] }
```

### 4.4 中間言語 JIL の契約(`docs/spec/v2/jil.md`)

JIL は **Lua 5.4 の静的サブセット**である。生成物を走査するテスト(v1 の `guard:` 走査と同じ手口)が次を固定する:

- 使わない: `pairs` / `next` / `setmetatable` / `getmetatable` / `load` / `loadstring` / `require` / `dofile` / `os.*` / `io.*` / `debug.*` / `string.dump` / 可変長引数 `...`
- 反復は `ipairs` と数値 `for` だけ。レコードは固定フィールドのテーブルで、**動的キー**(`t[k]` の `k` が文字列)を使わない
- `num` は常に浮動小数(リテラルは `1.0` の形で出す。整数サブタイプを作らない)。list の添字だけ `math.tointeger(math.floor(i))` を通す
- 文字列操作は `utf8` 経由(`len` / `sub` はコードポイント)
- 乱数は `math.random` ではなくプレリュードの PCG32(64 bit 整数演算。Lua 5.4 の整数は 64 bit)
- 各陣は 1 つの Lua テーブル、各手順は 1 つの Lua 関数。**識別子は `.jin` の名前をそのまま使わず**、`c_<index>` / `r_<index>` に写像する(名前は文字列値としてトレースにだけ載せる)。名前を識別子に埋め込まないので、v1 で要った `isidentifier` / 予約語の検査が要らない
- デバッグビルド(`--debug`)は各ステップの前に `T(seq, "<pointer>")` を挿む。リリースビルドは挿まない。**同じ `.jin` からデバッグ / リリースで表示リストは一致する**(トレース行だけが増える)

### 4.5 バンドルと将来の直接 wasm 出力

`jin build game.jin --out dist/` は:

```
dist/
  index.html          # プレイヤーの殻(apps/player のビルド物)
  player.js
  wasmoon.wasm        # 固定版
  game.lua            # JIL
  game.manifest.json  # stage / 使う能力名前空間 / seed / アセット表
  assets/             # stage.assets の実体
```

任意の静的サーバ(`python -m http.server` で足りる)で開けば動く。`--single` で wasm を base64 で埋めた 1 ファイル HTML を出す。`--target wasm-gc`(v2.1・Issue #53 で仕様確定。jil.md §6・§11 #56)は `game.lua` の代わりに `game.wasm` を出し、`index.html` / `player.js` は共通(ホスト境界が §4.3 で固定されているため。wasm では引数も戻りも JSON 1 本を線形メモリで越え、プレイヤーは manifest の `target` で `WasmGcHost` を選ぶ)。

### 4.6 ヘッドレス実行(`jin run`・v2)

```
jin run game.jin --ticks 600 [--seed 7] [--input rec.jsonl] [--storage memory.json] [--trace t.jsonl] [--frames f.jsonl] [--debug]
```

lupa で同じ JIL を走らせ、`--input` のイベント(`{tick, kind: "key"|"pointer", …}`)を tick 境界で渡す。`--frames` は表示リストを 1 tick 1 行で書く。**ブラウザ側のプレイヤーが書き出す録画(`.jinrec` = seed + 入力ログ)を `--input` に渡すと同じトレースになる**ことがパリティテスト(Playwright 1 本、`examples/paddle`)。

v1 の `jin run` が持つ危険性(`ref` の import)は v2 に**無い**。JIL は `require` も `load` も持たず、lupa は `attribute_filter` で `os` / `io` を閉じる。

### 4.7 トレース行の契約(v1 §3.4 の拡張)

```
{ "seq", "tick", "circle", "kind", "name", "pointer", "input", "output" }
kind: enter | exit | event | rite | cast | set | emit | transfer | wait | finish | assert | error | frame
```

`set` は **state の書き込みだけ**を記録する(局所変数は記録しない)。エディタのスクラバは `set` 行を積算して「その tick の記憶環の値」を出す。`frame` 行は §4.3 の表示リスト。`pointer` は発火したステップ / 手順 / 陣の JSON Pointer で、`jin_render.v2` の `data-jin` と同じ鍵。

---

## 5. CLI(サブコマンドは 9 個のまま)

| コマンド | v2 での振る舞い |
|---|---|
| `jin check` / `fmt` / `schema` / `dump` / `lsp` / `editor` | version で振り分けるだけ。`jin schema --version 2` で v2 側だけを出せる(既定は oneOf 全体) |
| `jin build <file> --out <dir> [--single] [--debug]` | v2 なら §4.5 のバンドル。v1 なら従来の ADK プロジェクト |
| `jin run <file> …` | v2 なら §4.6 のヘッドレス実行。v1 なら従来 |
| `jin render <file> [--trace t.jsonl --upto N --focus name]` | v2 なら `jin_render.v2`。`--focus` は陣名または `陣名/手順名`(手順の中を開く) |

`tests/contract/test_cli_contract.py::test_no_command_is_defined_beyond_the_v1_set` は触らない。

---

## 6. 診断(`docs/spec/v2/diagnostics.md`)

v2 固有は **JIN2xx** の番号帯。意味が同じものは v1 の番号を使う(JIN001 / 002 / 010 / 011 / 012 / 013 / 020 / 022 / 060)。v1 の「診断コードを増やさない」は v1 の意味検査についての規則であり、v2 の番号帯は別のテストで固定する。

| コード | 重大度 | 内容 | 修正ヒント |
|---|---|---|---|
| JIN201 | error | 式の構文エラー(位置は式内の列を含む) | 期待トークン |
| JIN202 | error | 型不一致(代入・引数・比較・`return` / `returns`・`exit` が bool でない) | 期待型と実際の型 |
| JIN203 | error | 式内の未定義識別子 | 候補名(編集距離)。他陣の非公開 state なら `out: true` を提案 |
| JIN204 | error | 道具環に無い名前空間を使った(`canvas.rect` を使うのに `sigils` に `canvas` が無い) | `addSigil` のコードアクション |
| JIN205 | error | 未知のホスト能力メンバ / 引数の数の不一致 / 未知のアセット名 | カタログのメンバ一覧 |
| JIN210 | error | 手順のステップ数が 12 を超えた(入れ子の中の個数は別勘定) | 「手順に抽出」のコードアクション |
| JIN211 | error | `if` / `loop` の入れ子が 3 段を超えた | 同上 |
| JIN212 | error | summon 先の手順が `wait` を含む(陣を跨いだ待ちは不可) | `emit` に置き換える |
| JIN213 | error | `break` が `loop` の外にある / `return` の値が `returns` の無い手順にある | |
| JIN220 | error | `flow.exit` が公開 state 以外を参照している | `out: true` を提案 |
| JIN221 | error | `on` の `rite` が存在しない / 引数がイベントの形と合わない(`tick` は `(dt: num)`、`key` は `(name: str, down: bool)`、`pointer` は `(p: Pointer)`、`message` は `(name: str)` + `emit` の引数、`exit` は `()`)。**手順の `params` はイベントの引数の前方部分でよい**(`tick` の手順が `params` を持たなくても合う。型が合わないときだけ落とす) | 期待する `params` |
| JIN230 | error | `input` を道具環に持たない陣が `key` / `pointer` イベントを受けている | `addSigil` |
| JIN240 | warning | 到達不能ステップ(`return` / `finish` / `break` の後) | 削除 |
| JIN250 | error | `state[].init` が定数式でない | |

`tests/fixtures/errors/v2/JIN2xx_*.jin` に各 1 つ。

---

## 7. レイアウト(`docs/spec/v2/layout.md`)

v1 の規律(正方形キャンバス、R=1、12 時から時計回り、`fmt_coord` 1 本、2 色、属性のみ)を継承する。環の半径は v1 と**同じ 4 本**を使い回す:

| 環 | 半径 | v2 での中身 |
|---|---|---|
| 0.35 | 手順環(rites) | 各手順を小さな陣として並べる。核から `core` の手順へ実線 |
| 0.55 | 道具環(sigils) | 名前空間の紋。核から放射線。summon は入れ子の小陣(深さ 1) |
| 0.75 | 記憶環(state) | 四角。`out: true` は二重線 |
| 0.95 | 境界環(boundary) | `on` は刻印(イベント名の記号)、`guards` は別記号の刻印、`delegate` は内側の小円と核への破線 |

**手順の中(focus)**: `--focus Play/step` で手順を 1 つの陣として描く。ステップは環に沿って 12 時から時計回り、配列順。**入れ子は内側の環**に置く(深さ 1 = 0.75、深さ 2 = 0.55、深さ 3 = 0.35)。入れ子深さの上限 3 が「環の本数」と一致するので、JIN211 は描けない構造を落としている。

| ステップ | 図形 |
|---|---|
| `set` | 四角(記憶環と同じ記号) |
| `let` | 小さな四角 |
| `cast` | 紋。target がホスト能力なら外側へ、自陣の手順なら手順環へ放射線 |
| `if` | 弦の分岐(`then` / `else` を内側の環の 2 つの弧に) |
| `loop` | 閉じた多角形(`count` / `while`)/ 星形(`each`、n ≥ 5 は v1 と同じ {n/k}) |
| `wait` | 境界環の欠け(v1 の `await` と同じ記号) |
| `emit` / `transfer` | 相手の陣への破線 |
| `return` / `finish` / `break` | 環の外へ抜ける短い線 |

`data-jin-kind`(v2、**13 種**。v1 の 9 種とは別集合で、別のテストが固定する。v1 と同じく**描かれたすべての要素**が `data-jin` と `data-jin-kind` を持つ):

`stage` / `form` / `circle` / `core` / `rite` / `sigil` / `state` / `on` / `guard` / `delegate` / `flow-edge` / `step` / `step-edge`

`stage` は最外の額縁(1 つ)、`form` は額縁の隅に並ぶ印章(型紙ごとに 1 つ)。

装飾(識別紋章)は v1 の `rune` の代わりに **`core` の手順の正準 JSON の SHA-256** から生成する。トレースのオーバーレイは v1 と同じ(`upto` までに発火した `pointer` を強調色、境界環の外に点)。

---

## 8. LSP とエディタ

- `jin/…` は **6 種のまま**。`jin/renderSvg` の `focus` に `陣名/手順名` を許す。`jin/applyOps` は v2 のオペレーション(§9)を受ける
- hover: 式の型、ホスト能力のシグネチャ(カタログ由来)、state の公開 / 非公開
- completion: 式の中の識別子(スコープ順)、`.` の後の名前空間メンバ、`do` の値、型名
- **実行パネル**: エディタに `apps/player` を **同一オリジンの iframe** で埋め込む。`jin editor` の静的サーバが `dist/` と同じものを `/play/` に配る。実行 / 一時停止 / 1 tick 進める / seed / 入力の記録と `.jinrec` の書き出し。**v1 の `POST /run` は使わない**(v2 の実行はブラウザ内で完結し、子プロセスも `ref` も無い)。トレースは iframe から `postMessage` で親へ流し、Phase 6 のスクラバにそのまま載る
- **ライブリロード**: `jin/applyOps` の応答に v2 なら JIL を含める(`jil` フィールド)。実行パネルは既定で**状態を保って**差し替える(v2.1 で実装。runtime.md §1.3。「編集しても状態を保つ」を外せば `boot` からやり直す)
- フォームは `jin.schema.json` から生成(v1 と同じ)。式の欄だけ「式エディタ」(1 行 + 補完)にする。**式エディタは `jin_core.v2.expr` を再実装しない**。補完候補は LSP の completion をそのまま使う

Phase 5 で確定した実装(§11 #36〜#38):

- **式の欄の印は schema に置く**: `jin_core.v2.model.Expr` が `x-jin-expr: true` を `jin-v2.schema.json` に出し、エディタ(`apps/editor/src/form/schemaForm.ts`)と LSP の completion(`jin_core.v2.model.expr_fields`)はその印だけで「式の欄か」を決める。欄の名前を書き写さない
- **補完の位置**: 式エディタは式のリテラルの**先頭位置**(`jin/model` の `pointers` + 現在のテキストからコードポイント → UTF-16 に換算)で `textDocument/completion` を求め、候補を**カーソル直前のトークン**(識別子と `.`)で自分で絞る。サーバはスコープ順の識別子に `名前空間.メンバ` / `陣名.key` / `局所.欄` の点付きラベルを含めて返す。ドキュメント上で `名前.` の直後にカーソルがあるとき(Claude Code / VS Code)はメンバだけを点なしで返す
- **`jin/model` と `jin/applyOps` の v2 の応答**は `jil` / `manifest` / `jilError`(`jin_lsp.jil.generated`・常に debug ビルド・best-effort)と `warnings` を持つ。`applyOps` は通ったが式に構文 / 型エラーが残っていれば `jil: null` + 理由(ops.md §1 のとおりオペレーションは失敗にしない)
- **実行パネル**(`apps/editor/src/run/RunPanel.tsx`): `jin editor` が `/play/` として配るプレイヤーを同一オリジンの iframe で開き、`jin.load`(JIL + manifest)/ `jin.control`(実行 / 一時停止 / 1 tick / 最初から / 止める・起こす)を送り、`jin.trace` を受ける。編集モードでは隠すだけで外さず(状態を保つため)、隠れている間は `suspend` でプレイヤーを止めておく(見えないゲームが走ると図を 1 秒ごとに描き直し、編集の操作と重なる・§11 #54)。走っている間のオーバーレイの描き直しは 1 秒に 1 回、一時停止 / 1 tick / 最初から では即時。溜める行は 4000 で頭打ち(超えたら古い行を落として理由を出す)。**`POST /run` は使わない**
- **エディタの図の操作**(ops.md §5): 手順の小陣のダブルクリック → focus `陣名/手順名`、パレット(`do` の値は schema の判別共用体から)で `addStep`(選択中のステップの直後 / 手順の末尾)、ステップ / 道具のドラッグで `moveStep` / `moveSigil`(同じ列の中だけ)、選択中の 1 ステップを「if で包む」(`wrapSteps`)/「手順に抽出」(`extractRite`)、記憶の四角のダブルクリックで `setState`(`out`)。範囲選択(Shift クリック)・列を跨ぐステップの移動(`removeStep` + `addStep` の合成)・陣同士を結ぶ操作(`addDelegate` / `addSigil` の `summon`)は v2.1 で実装した(#52)

Phase 6 で確定した実装(§11 #39〜#41):

- **録画の再生はプレイヤー(iframe)の中**: エディタは `.jinrec` を `<input type="file">` で読み、1 行目に `"jinrec"` があれば生のテキストを `jin.replay` で渡す(trace の JSONL ならそのまま載せる)。読み手は書き手と同じ `apps/player`(`src/jinrec.ts` = `jin_wasm.jinrec.read_jinrec` の写し。壊れ方は `tests/fixtures/jinrec/broken/` を Python と TS の両方が同じ行番号で検算)。プレイヤーはヘッダの seed で `boot` し直し、tick 0 からヘッダの `ticks` まで録画の行を**同じ reducer**に通し(`jin run --input` と同じ。`apps/player/e2e/replay.spec.ts` が全行一致を見る)、**止まったまま**終わる。トレースは 1 回にまとめて `jin.trace` で流す
- **記憶環の値と `assert` のバッジはエディタが積算し、HTML で重ねる**(runtime.md §5「スクラバは `set` 行を積算する」): `enter` / `exit` の `output` で陣の state 全部、`set` で 1 つ、`assert` は guard ごとに最後のメッセージと回数(`apps/editor/src/debug/values.ts`)。ラベルは SVG の**外**の HTML 層で、位置は描かれた要素の矩形から取る(`<text>` を作らない。オーバーレイ = 発火の強調と点は引き続き `jin_render` だけ)。値は脇の表にも全部出す
- **スクラブで画面も動く**: `upto` の位置の最後の `frame` 行の表示リストを `jin.frame` でプレイヤーに描かせる(止まっている間だけ。Lua は呼ばない)
- **録画と書き出し**: 実行パネルの「録画」は seed を決めて `boot` し直し、「録画を止めて書き出す」で `jin.recording` の `.jinrec` を親がダウンロードとして渡す(`<jin 名>-seed<seed>-<ticks>t.jinrec`)。「この録画を再生」で読み直せる
- **行数の上限は出どころで分ける**: 走らせている間は `MAX_LIVE_ROWS`(4000)で古い行を落とす(値の積算が最初からでなくなると断る)。録画の再生はヘッダの `ticks` で有界なので落とさず、`MAX_REPLAY_ROWS`(60000)を超えたら載せずに断る。描き直しはプレイヤーが止まった知らせ(`jin.status` の `running: false`)で行う

v2.1(状態を保ったライブリロード)で確定した実装(§11 #42〜#44):

- **snapshot は `tick` 結果に、復元は `boot` の `manifest.resume` に**(runtime.md §1.3): ホストが呼ぶ Lua の関数は `boot` / `tick` のままで、デバッグビルドの `tick` 結果に `snapshot`(seed / tick / seq / PCG32 の 16 進文字列 / 陣ごとの生存・state・公開 state の確定値)を載せ、次の `boot` に**そのまま**渡す。陣は**名前で照合**し、欄も名前で引いて**形が合うものだけ**写す(合わなければ `init`)。root が照合できなければ通常の `boot`。`wait` 中の手順と未配達の `emit` は捨てる。JIL の版は 1 → 2(生成部に `restore` / `prestore` / `pdump` / `JR[k]`。release の生成部は不変)。保証は「途切れずに走らせた列と、途中で差し替えて続けた列が行(`seq` 込み)も画面も乱数列も一致」(`packages/jin-wasm/tests/test_resume.py`)
- **プレイヤーは前のプレイヤーから引き継ぐ**(`Player.resumeFrom`): tick / seed / reducer / 押下状態 / トレース / 直近の画面を持ち越し、走っていたなら走らせ続ける。録画は止める。`fresh` ならその tick を捨てて tick 0 から。`jin.status` の `generation`(`boot` し直すたびに増える)で親が走らせた行を捨てるかを決める。Wasmoon は JS の `null` を Lua に積めない(proxy が欄を読んだ瞬間に PANIC・probe §A.11)ので `boot` の前に `withoutNulls` で落とす(`apps/player/e2e/reload.spec.ts`)
- **エディタは v2 の実行パネルをモード切り替えで外さない**(編集モードでは隠す): 式の欄は編集モードにしか無く、外すと iframe ごとプレイヤーが消えて状態が続かない。「編集しても状態を保つ」(既定 on)が `jin.load` の `keep` になる。e2e(`apps/editor/e2e/v2.spec.ts`)は「走らせて止める → 編集モードで式を直す → 戻ると tick / 記憶環の値 / `upto` がそのまま → 1 tick で続く → 外して編集すると世代が進む」を実ブラウザで通す

v2.1(`storage`)で確定した実装(§11 #45〜#47・abilities.md §8):

- **境界は変えない**: 入りは `boot` の `manifest.storage`(ホストが持つ記憶の写し)、出は `tick` の戻り値の `storage`(書き込みの一覧・書き込みがあった tick だけ・release でも出る)。`get` は自分の書き込み → 写し → `""`。式に `num(str)`(受ける形を閉じてある。expr.md §4.1)。JIL の版は 2 → 3
- **プレイヤーの `Player.store` が正**: すべての boot に写しを渡し、書き込みを反映して `localStorage`(`jin.storage:<file>`)に書き戻す。録画のヘッダ `storage` は録画の boot に渡した写し(`jin run --input` が同じ写しで boot し、トレースが全行一致する・`apps/player/e2e/storage.spec.ts`)。再生はスクラッチで永続化しない。実行パネルの「記憶を消す」(`jin.control` の `forget`)は空にして boot し直す

---

v2.1(式の正準化)で確定した実装(§11 #48・expr.md §8):

- **正準化は `jin_core.canonical.dumps` の 1 か所**: 印 `x-jin-expr` を持つ欄の式を `jin_core.v2.expr.unparse` で書き戻す。`jin fmt` / `jin/save` / `jin/applyOps` の応答 / `jin dump` / 紋章のハッシュがすべて同じ経路を通る。読めない式は元のまま
- **エディタは式を解析しない**(設計書 §8 の原則のまま): 確定した式を `jin/applyOps` に送り、返ってきたモデルの正準形で欄を置き換える。Enter で確定するとフォーカスが欄に残るので、打ち直していなければ返ってきた値に draft を揃える(揃えないと blur で同じ式を二重に確定する)

## 9. オペレーション(`docs/spec/v2/ops.md`)

v1 と同じく JSON Pointer で対象を指し、逆オペレーションを応答に含める。**合成で書けるものは足さない**(v1 の `_reference_replacement` と同じ方針)。

`setStage` / `addForm` / `removeForm` / `setForm` / `addCircle` / `removeCircle` / `setCore` / `addState` / `removeState` / `setState` / `addSigil` / `removeSigil` / `moveSigil` / `addRite` / `removeRite` / `setRiteSignature` / `addStep` / `removeStep` / `moveStep` / `setStep`(1 ステップの欄の書き換え)/ `wrapSteps`(選択範囲を `if` / `loop` で包む)/ `unwrapSteps` / `extractRite`(JIN210 / 211 のコードアクション。`addRite` + `removeStep` × n + `addStep(cast)` の合成)/ `setOn` / `removeOn` / `setGuard` / `removeGuard` / `addDelegate` / `removeDelegate` / `setFlow` / `setRoot` / `rename`

32 件。`rename` は circle / form / state / sigil / rite / 局所変数を対象にし、**式の文字列の中の参照も追随させる**(式を構文解析して識別子の位置を得る。文字列リテラルの中は触らない)。

---

## 10. テスト要件

| 対象 | 方法 |
|---|---|
| スキーマ | v1 / v2 の oneOf が Pydantic から生成した schema と一致(CI)。`schemas/abilities.json` も同様 |
| 式 | 文法の往復(構文解析 → 位置付き AST → 診断位置)。型規則の fixture |
| 診断 | `tests/fixtures/errors/v2/JIN2xx_*.jin` が対応コードを 1 つだけ出す |
| JIL | 生成物のスナップショット(syrupy)。**禁止語の走査**(§4.4)。`examples/*` を lupa で `--ticks 300` 回して例外が出ない |
| 決定性 | 同じ `.jin` + seed + 入力ログで 2 回走らせてトレースと表示リストがバイト一致。`parallel` の子の順序を入れ替えても公開 state の系列が一致 |
| 表示リスト | `examples/paddle` の 60 tick 分のゴールデン(JSONL スナップショット) |
| パリティ | Playwright 2 本(`apps/player/e2e/parity.spec.ts` = ブラウザで録画する側、`replay.spec.ts` = 録画済み `.jinrec` を再生する側・Phase 6): `dist/index.html` を開き、録画 / 再生してトレースを取り出し、`jin run --input` の出力と全行一致 |
| レンダラ | SVG スナップショット。13 種の `data-jin-kind` が `examples/paddle` で全部出る。全 pointer がモデルに解決できる |
| LSP / エディタ | v1 のスモークに「v2 ファイルを開く → ステップを足す → 保存 → 正準形一致」と「実行パネルで 10 tick 進めてスクラブ」を足す。Phase 6 で「`.jinrec` を読んでスクラブするとオーバーレイと記憶環の値が動く」「偽になった `assert` のバッジと一覧」「録画 → 書き出し → `jin run --input` と同じ行数 → 読み直し」の 3 本を足す(`apps/editor/e2e/v2.spec.ts`) |
| 契約 | `jin-wasm` が `jin-adk` / `jin-render` を import しない(import-linter)。`apps/player` が Python を import しない(eslint)。ホストが Lua を呼ぶ関数が `boot` / `tick` の 2 つだけ(TS 側を走査) |

---

## 11. 決定事項

| # | 論点 | 決定(既定案) | 変えると何が変わるか |
|---|---|---|---|
| 1 | v1 との共存 | 同一リポジトリ・`.jin` のまま・`version: 2` で振り分け。v1 の契約テストは不変 | 別リポジトリにすると §1.3 の「そのまま使う」行を全部コピーして保守することになる |
| 2 | 実行ターゲット | JIL(Lua 5.4 静的サブセット)→ ブラウザは Wasmoon、CI は lupa | 直接 wasm-GC / 自作 VM は作業量が倍。IL 契約があるので v2.1 で足せる |
| 3 | 汎用計算の置き方 | 制御構造は JSON ノード(11 種)、葉の式だけテキスト(独自文法) | 全ノード化は LLM が書けず、全テキスト化は描けない |
| 4 | 型 | 静的・最小 5 種。局所は推論 | 動的型にすると IL の静的サブセット契約と直接 wasm 出力の道が消える |
| 5 | GUI / 描画 | 即時モード。表示リストを Lua で組み立て tick の戻り値で返す | 保持モードにするとブラウザ無しのゴールデン比較ができない |
| 6 | ホスト境界 | ホストが呼ぶのは `boot` / `tick` の 2 つ。Lua はホストを呼ばない | 緩めると Wasmoon の yield 制約に当たり、越境コストも増える |
| 7 | 決定性 | 固定 dt、seed 付き PCG32、入力は tick 境界、公開 state は二重バッファ | 緩めるとリプレイとパリティテストが成立しない |
| 8 | `parallel` の意味 | 単一スレッドで配列順。公開 state の二重バッファで順序非依存(例外: `random` は舞台に 1 つなので呼び出し順に依存する。順序は配列順で固定なので決定性は保たれる) | |
| 9 | 陣の終わり方 | `finish` で親の flow が進む。`transfer` はスタック(戻る) | |
| 10 | 外部コード参照 | **無し**(`ref` は v2 に存在しない)。外部世界はホスト能力カタログだけ(v2.1 の `agent` は v1 の `.jin` を名指しで呼ぶ。ヘッドレスだけ・#55) | `ref` を足すと v1 の S1 の危険性が v2 にも入る |
| 11 | 美的制約 | 手順 12 ステップ・入れ子 3 段・記憶環 12・道具環 12 | |
| 12 | 診断の番号帯 | v2 固有は JIN2xx。意味が同じものは v1 の番号を共有 | |
| 13 | `data-jin-kind` | v2 は 13 種の別集合 | |
| 14 | エディタからの実行 | 同一オリジン iframe のプレイヤー。`POST /run` は使わない | |
| 15 | 式の正準化 | v2 では**しない**(文字列のまま保存) | v2.1 で**する**と決めた(#48) |
| 16 | schema のファイル(Phase 1 で確定) | v2 は**別ファイル** `schemas/jin-v2.schema.json`。`jin.schema.json` は 1 バイトも変えない。`jin schema --version 2` で出す | `apps/editor` のフォーム生成がルートの `properties` を直接読むので、ルートを oneOf にすると Phase 5 の前にエディタが壊れる。§1.1 の「oneOf」はこれで置き換える |
| 17 | `jin_core.v1` への物理移動(Phase 1 で確定) | **しない**。v1 のモジュールはそのまま、`jin_core/v2/` を足すだけ | 全パッケージが `jin_core.<mod>` をフルパスで import しており、移動は 4 パッケージ横断の変更で得るものが無い |
| 18 | `examples-v2/` の置き場(Phase 1 で確定) | **恒久的に `examples/` の外**。CI は `examples-v2` にも `check` / `fmt --check` を掛ける | `examples/` は「3 本」を等号で数える契約が複数あり、`jin-adk` / `jin-render` のテストが v1 前提で glob している |
| 19 | ホスト能力カタログの正本(Phase 1 で確定) | `jin_core.v2.abilities`(純データ)。`schemas/abilities.json` はそこから生成し、Phase 2 の `jin_wasm` はそれを import する | `jin_core` は `jin_wasm` を import できず、インストール済みパッケージから `schemas/` も見つけられない。依存方向もこの向きが正しい |
| 20 | 型文字列が指す型紙の未定義(Phase 1 で確定) | JIN011(参照解決の一種) | 新しい番号を切らない |
| 21 | 依存の層(Phase 2 で確定・Phase 5 で改訂) | `jin_wasm` は `jin_adk` / `jin_render` と 3 兄弟(layers 契約の 1 要素 `"jin_adk \| jin_render \| jin_wasm"`)。`jin_lsp` は Phase 5 から `jin_wasm` に依存するが、読むのは **`jin_wasm.codegen`(と `jil`)だけ**で `jin_wasm.runtime`(lupa)/ `bundle` は import しない(`tests/contract/test_lsp_contract.py` が AST で固定)。**インストール依存には `lupa` の wheel が入る**が import しないので LSP の起動時間は変わらない | v1 の `design.yaml` の 8 行は書き換えない(v1 の契約テストがそれを読む)。v2 の依存規則の正本は §1.2 |
| 22 | `tick` の戻り値(Phase 2 で確定) | `ops` / `audio` / `trace`(デバッグのみ)/ `done` に **`error`**(実行時エラーの文)と **`public`**(公開 state の確定値)を足す | リリースビルドにはトレースが無く、`jin run` が実行時エラーの理由と最後の公開 state を返す口が他に無い。ホスト境界は `boot` / `tick` の 2 関数のまま |
| 23 | 数値の書式(Phase 2 で確定) | Python の `repr(float)` と同じ配置(指数形は exp < -4 または exp >= 16、指数は符号付き 2 桁以上)。非整数 700 件で一致を固定 | runtime.md §6 が「JS と Python の両方と同じ」と言っていたが、両者は指数の桁数が違う。パリティは Lua 対 Lua なので影響は無い |
| 24 | 命令数の上限(Phase 2 で確定) | `debug.sethook` の count hook で `boot` / `tick` ごとに 10^7 命令。超えたら `error` 行 + `done` | `while true` の手順で CI が止まらないための多層防御。hook は `debug` を nil にした後も生きる(実測)。Wasmoon 側は Phase 4 で同じ手口を検討 |
| 25 | バンドルのプレイヤー(Phase 2 で確定) | Phase 2 の `jin build` は `game.lua` / `game.manifest.json` / `assets/` だけを書き、プレイヤーが無いことを stderr に出す。`--single` は exit 1 | プレイヤーは Phase 4 の成果物。Phase 4 で `apps/player` のビルド物を `jin_wasm/player/` に同梱する |
| 26 | トレース行の積むタイミング(Phase 2 で確定) | `emit` 行は配達の tick の 1 で積む(`seq` / `tick` は配達時)。`cast` 行は呼び出しの**前**に積み、戻り値は後で埋める | 行は tick の終わりに直列化するので、前の tick に積んだ行を後から書き換えられない。`cast` を前に積むと list の効果で変わる前の引数が載り、実行時エラーの pointer がそのステップになる |
| 27 | 生存と確定の細部(Phase 2 で確定) | `entered` 直後(`init` の値)と `done` 直後(`finish` の書き込み)にその陣の公開 state を確定する。未 `entered` の陣の state は boot で `init` 値にし 4 で確定する。委譲先が `done` になったら `idle` に戻す。休止中の陣の `wait` は再開しない。1 tick の進行は 1000 回で `error` | 同期的に `done` になる子と `exit` の組み合わせが 1 tick で無限に進むのを防ぐ。`summon` で書かれた state を他の陣が読めるようにする |
| 28 | トレースの `seq` の下限(Phase 3 で確定) | v2 の overlay は `seq` の **0 始まり**を受ける(`jin_render.overlay.read_trace(rows, min_seq=0)`)。v1 の既定(1 始まり)は変えない。`frame` 行(`/stage`)は額縁を強調せず点にだけ数える | runtime.md §5 が「`boot` から通しの 0 始まり」と決めており、v1 の 1 始まりの検査のままでは `jin run --trace` の出力を `jin render --trace` が拒む |
| 29 | 手順の図の弧の割り当て(Phase 3 で確定) | 入れ子のブロックは**親の弧**に収め、`if` の `then` / `else` は前半 / 後半、子は等分した区画の中央(v2 layout.md §3) | Phase 0 の §3 は「その環に置くステップの数で等角配置」と「親の弧に収める」を同時に書いており両立しない。前者だと `then` の中身が親から離れた角度に飛び、分岐の弦が環を横切って読めない |
| 30 | Phase 3 の完了条件「13 種が `paddle` で全部出る」(Phase 3 で確定) | paddle の 3 視点(root / `Play` / `Play/step`)で 12 種、`delegate` だけは `tests/fixtures/v2-programs/transfer.jin` で補う(`tests/contract/test_render_contract_v2.py`) | paddle は §2.2 の例と突合されており(`test_paddle_example_matches_the_design_document_section_2_2`)、実行に効かない `delegate` を足すために §2.2 を書き換えない。paddle 単体で `delegate` だけが欠けることも同じテストが固定する |
| 31 | LSP の v2 の範囲(Phase 3 で確定) | `jin/renderSvg`(`focus` に `陣名/手順名`)/ `jin/model` / formatting / `jin/save` は v2 で答える。hover / completion / definition / references / documentSymbol / rename / codeAction / `jin/applyOps` は v1 だけ(v2 は「モデル無し」と同じ振る舞いで落ちない・`jin/applyOps` は JIN002 で断る)。`jin editor` で v2 を開くと図は出るが、エディタは 9 種以外の `data-jin-kind` を `null` として無視するので選択 / 編集は効かない(落ちない) | §8 の hover / completion / applyOps の v2 は Phase 5。`DocumentState.model` を `JinFile \| JinFileV2` に広げ、v1 専用の機能は `model_v1` を見る |
| 32 | 命令数の上限とコルーチン(Phase 4 で確定) | ホストは JIL を読む前に `JIN_ARM()`(今のスレッドに掛け直す)/ `JIN_HOOK(co)`(コルーチンに掛ける)の 2 つのグローバルを置き、読んだ後に消す。プレリュードが読み込み時に `local` へ捕まえ、`boot` / `tick` の先頭と毎 `coroutine.resume` の前に呼ぶ(`jin_wasm.jil.HOST_HOOK_GLOBALS`。lupa と Wasmoon は同じ Lua のチャンク) | #24 の hook はメインスレッドにしか掛からず、`wait` を含む手順(コルーチン)の無限ループを止められていなかった(lupa / Wasmoon とも実測・probe §B.8 / §A.10)。Wasmoon の `Thread.setTimeout`(C の hook)はコルーチンの中で PANIC するので使えない。ホストが呼ぶ Lua の関数は `boot` / `tick` の 2 つのまま(`JIN_ARM` / `JIN_HOOK` はホストが呼ぶのではなくプレリュードが呼ぶ) |
| 33 | `canvas.text` の書体(Phase 4 で確定) | プレイヤーの書体は ASCII(U+0020〜U+007E)の 5×7 を 6×8 の枠に置く。それ以外のコードポイントは □(幅は 1 コードポイント = 6 で abilities.md §2 の `len(s) * 6` は保つ) | abilities.md §2 の「JIS X 0208 の一部」は字形データ(数千字)を持ち込むことになり、Phase 4 の範囲ではない。字形はトレースに載らないのでパリティに影響しない。examples-v2 の文字列は ASCII。**v2.1 で ASCII 以外も k6x8 の字形で描くと決めた(#49)** |
| 34 | `--single` と asset(Phase 4 で確定) | `--single` は `index.html` 1 本(`player.js` をインライン、JIL / manifest / wasm の base64 を `window.JIN_BUNDLE` に)。`stage.assets` があれば拒む | 画像 / 音を base64 で埋めると 1 ファイルが肥大し、`assets/` の相対パスの契約(runtime.md §9)を二重に持つことになる。examples-v2 に asset は無い。asset 付きは `--single` 無しで `assets/` ごと配る |
| 35 | プレイヤーの入力と録画の規則(Phase 4 で確定) | `KeyboardEvent.code`(カタログの `keys` だけ)。`repeat` / 二重押下は捨て、`blur` で押下中を記録してから離す。ポインタは主ボタンだけ、論理座標は整数に切り捨てて枠内に留める。移動は tick 内で最後の 1 つに畳み、down → up は残す。`inputs` と `.jinrec` は同じ reducer(`InputState.apply` の写し)から出す。録画は `boot` し直して tick 0 から | パリティを「検算」ではなく「構成」で保証する。プレイヤーが `keys` を独自に追跡すると blur の押しっぱなし / カタログ外のキーで `jin run --input` と割れる。共有 fixture(`tests/fixtures/jinrec/reducer.*`)を Python と TS の両方が検算する |

| 36 | LSP の v2(Phase 5 で確定) | hover(式の型 / ホスト能力のシグネチャ / state の公開・非公開 / 陣・手順・型紙・`on` の要約)と completion(スコープ順の識別子 / `.` 後のメンバ / `do` / 型名 / 参照名 / キー・enum)は `jin_core.v2.semantic.analyze_model`(式の AST / 型 / 位置ごとのスコープの写し)から引く。`jin/applyOps` は `jin_core.v2.ops` へ振り分け、`jin/model` と共に `jil` / `manifest` / `jilError` を載せる。definition / references / documentSymbol / rename / codeAction の v2 は §8 に無く、引き続き v1 だけ | 式を LSP 側で構文解析 / 型推論しない(§8 の「再実装しない」)。スコープは検査の副産物として記録するのが最も安い |
| 37 | 式の欄の印と補完の位置(Phase 5 で確定) | `Expr = Annotated[Text, Field(json_schema_extra={"x-jin-expr": True})]`(v2 のモジュール内の別名。v1 の `Text` には付けない)。式エディタはリテラルの先頭位置で completion を求め、候補をクライアントで前方一致させる。`args`(`list[Expr]`)だけは配列でも欄にする(行ごとの式エディタ) | `jin.schema.json` を 1 バイトも変えずに印を付ける。カーソル位置ごとに位置換算(エスケープの逆写像)をしなくて済む |
| 38 | 実行パネルの配信と間引き(Phase 5 で確定) | `jin editor` は `/play/` でプレイヤーを配る(`--player-dist` > `apps/player/dist` > `jin_wasm.bundle.PLAYER_DIR`。`translate_path` の正規化を通すので `/play/../` で抜けない)。プレイヤーは iframe の中では fetch せず親の `jin.load` を待ち、`jin.control` を受ける。親は `jin.trace` を tick ごとの配列で積み(`appendRows`)、描き直しは 1 秒に 1 回 + 操作時、行数は 4000 で頭打ち。asset(絵と音)は埋め込みでは読めない(`.jin` の隣にあり、エディタのサーバは配らない・残存) | 60 tick/s × 十数行を毎回 `jin/renderSvg` に送ると ws のペイロードが万行になる。`/play/` を同一オリジンにするのは `postMessage` の相手を `contentWindow` / `window.parent` に限るため |
| 39 | `.jinrec` の読み手と再生の場所(Phase 6 で確定) | 読み手は書き手と同じ `apps/player`(`src/jinrec.ts` = `read_jinrec` の写し。壊れ fixture を両側で同じ行番号で検算)。再生は iframe の中の `Player.replay`(ヘッダの seed で `boot`、tick 0 から同じ reducer、止まったまま終わる)。エディタは 1 行目の `"jinrec"` だけを見て生のテキストを `jin.replay` で渡す | `jin/` は 6 種のまま、`POST /run` は使わないので、再生できる場所はプレイヤーしか無い。エディタに読み手を置くと `apps/player` の TS を import するか写しを 3 つ目に増やすことになる |
| 40 | 記憶環の値と `assert` のバッジ(Phase 6 で確定) | エディタが `set` 行を積算し(runtime.md §5 のとおり)、SVG の**外**の HTML 層に重ねる(位置は描かれた要素の矩形)。`jin_render` はオーバーレイ(発火の強調と点)だけを描き、値は描かない | SVG に `<text>` を足すのは「エディタが陣を描く」ことになり契約テストが落とす。レンダラに積算を持ち込むと `jin/renderSvg` の引数に「値」が増え、同じ `upto` なら同じ SVG という規律の外に状態が出る |
| 41 | 再生の行数と描き直し(Phase 6 で確定) | 走らせている間の行は #38 のまま(4000 で古い行を落とす)。録画の再生は落とさず `MAX_REPLAY_ROWS`(60000)を超えたら載せずに断る。描き直しはプレイヤーの `jin.status`(`running: false`)で即座に、走っている間は 1 秒に 1 回 | 古い行を落とすと `enter` 行(init 値)が消え、以後 `set` されない state の値が黙って狂う。再生はヘッダの `ticks` で有界なので上限を別に置ける。paddle 600 tick は約 7,000 行 |
| 42 | 状態を保った差し替えの経路(v2.1 で確定) | デバッグビルドの `tick` 結果に `snapshot` を載せ、次の `boot` の `manifest.resume` に**そのまま**渡す(runtime.md §1.3)。陣は名前で照合、欄は名前と型の形で写す(合わなければ `init`)。核あり ↔ 核なしが変わった陣は idle、root が照合できなければ通常の `boot`(`resume.mode = "fresh"`)、active な flow の idle な子は `entered`、`wait` 中の手順と未配達の `emit` は捨てる。復元の知らせは直後の tick 結果に 1 回。JIL の版は 1 → 2 | ホストが呼ぶ Lua の関数を `boot` / `tick` の 2 つのままにする(#6)。コルーチンは境界を越えないので `wait` は捨てるしかない。名前で照合すれば式の書き換え・state の追加 / 削除・手順の並べ替えの全部が「続く」側に入り、改名だけが最初からになる |
| 43 | snapshot が越えるもの(v2.1 で確定) | `seed`(snapshot が勝つ)/ `tick` / `seq`(通しのまま)/ PCG32 の状態(`"0x…"` の 16 進文字列。jil.md §5 の唯一の例外)/ 陣ごとの生存と state(`dump`)と公開 state の確定値 P(`pdump`)。復元では `publish_all` を呼ばない。ホストの値の形は `type()` でなく欄の読み取りと `ipairs` で見る | 乱数列と `seq` が続かないと「途切れずに走らせた列と一致」が言えない(`test_resume.py`)。P を別に持つのは、tick の終わりの進行で `set` された値が次 tick の 4 まで P に出ない二重バッファ(#7)を復元でも保つため。lupa は table、Wasmoon は proxy の userdata で届く |
| 44 | エディタ側の差し替え(v2.1 で確定) | `jin.load` に `keep`(既定 on の「編集しても状態を保つ」)。プレイヤーは前のプレイヤーから tick / reducer / 押下 / トレースを引き継ぎ(`resumeFrom`)、`fresh` なら tick 0 から。`jin.status` の `generation` で親が行を捨てる。v2 の実行パネルはモード切り替えで外さず編集モードでは隠す。Wasmoon には `null` を渡さない(`withoutNulls`・probe §A.11) | 式の欄は編集モードにしか無いので、iframe が外れると機能が成立しない。`seq` が 0 に戻る差し替え(keep 無し / fresh)を親が知る口が `generation`。JS の `null` は Wasmoon の proxy が欄を読んだ瞬間に PANIC でエンジンごと落ちる(実測) |
| 45 | `storage` の経路(v2.1 で確定) | 入りは `boot(seed, manifest)` の `manifest.storage`(ホストが持つ記憶の写し。プレリュードは参照のまま読むだけで `pairs` しない)、出は `tick` の戻り値の `storage`(書き込みの一覧 `[[key, val], …]`・書き込みがあった tick だけ・release でも出る。`boot` の核で書いた分は最初の tick に載る)。`get` は自分の書き込み → 写し → `""`。JIL の版は 2 → 3 | ホストが呼ぶ Lua の関数を `boot` / `tick` の 2 つのままにし(#6)、Lua はホストを呼ばない。写しを Lua のテーブルに写すには `pairs` が要るので、写しは読むだけにして書き込みを重ねる 2 段にした。release にこそ保存が要る |
| 46 | `num(str)` と決定性(v2.1 で確定) | 式に純関数 `num`(`str()` が出す形と JSON の数値の形だけを受け、それ以外は 0。`tonumber` は先にパターンで弾く)。記憶の写しは録画のヘッダ `storage`(任意欄・版は 1 のまま)に載り、`jin run --input` が同じ写しで boot する。他のタブの書き込みは次の boot まで見えない | `get` が `str` を返す以上、`num` 無しでは高得点の保存が書けない。受ける形を閉じないと `0x10` / 空白付きで lupa と Wasmoon が割れ得る。写しがヘッダに無いと同じ録画から違う列が出る |
| 47 | プレイヤーの記憶と再生(v2.1 で確定) | `Player.store`(`Map`)が正で、すべての boot に写しを渡し、書き込みを反映して `localStorage`(`jin.storage:<file>`)に丸ごと書き戻す。再生はヘッダの写しから始まるスクラッチに書いて永続化しない。差し替えは前の写しを引き継ぐ。「記憶を消す」(`jin.control` の `forget`・`jin-forget`)は空にして boot し直す。語彙は 7 語のまま | 再生は履歴の再実行であって利用者の本物の記憶を上書きしてはいけない(録画の `boot` に渡した写しがヘッダにあるので再現には足りる)。`Map` なら `__proto__` も普通の鍵。空にする口が無いと開発中に記憶を捨てられない |
| 48 | 式の正準化(v2.1 で確定) | `jin_core.canonical.dumps` が **schema の印 `x-jin-expr` を持つ欄**(`jin_core.v2.model.expr_fields`)の式を AST に読んで書き戻す(`jin_core.v2.expr.unparse`。expr.md §8)。括弧は優先順位と結合で要るときだけ(`(a and b) or c` → `a and b or c`。`cmp` は連鎖しないので `(a < b) == c` の括弧は必須)、空白は演算子の両側に 1 つ、数値は `str(x)` と同じ書式、文字列は最小エスケープ。**読めない式(構文エラー・溢れた数値)は元のまま**。`cast.target` も同じ規則(`canvas . rect` → `canvas.rect`。整形が消す診断は check がこの形に出す JIN202 だけ) | §2.4 が保留した「diff の安定性」と「LLM の書きやすさ」は同じ機構で両立する: 同じ AST が 1 つの字面に落ちるので打ち方の揺れが diff に出ず、雑に書いた式も保存で揃う。欄を名前でなく**印**で見分けるのは、`jin_render.v2.layout` が紋章のハッシュに `Rite` 単体を `dumps` に渡すため(部分モデルでも同じに効く)。読めない式を保つので整形が入力を壊さない。エディタは Enter で確定した後に返ってきた正準形へ欄を揃える(揃えないと blur で同じ式を二重に確定し undo に積まれる) |
| 49 | ASCII 以外の字形(v2.1 で確定) | ASCII は #33 の 5×7 のまま、それ以外は **k6x8ゴシック(2023-10-19 版・Num Kadoma・自由なライセンス)の非 ASCII の全字形 7001 字**を 6×8 の枠に置き、無いものだけ □。JIS X 0208 の全区点を euc_jp と cp932 の両方の対応先で含む。幅は字形によらず 1 コードポイント = 6(半角の字形も左に寄せる)。字形は `player.js` に同梱する(`apps/player/src/glyphs.ts` は `apps/player/fonts/k6x8/k6x8_gothic.bdf` から `scripts/generate_glyphs.py` が生成し、原本の sha256 を固定)。サイズの実測: `player.js` 134.80 kB → 209.80 kB(gzip 44.61 → 91.32 kB)、paddle の `--single` の `index.html` 541,158 → 616,154 バイト(+13.9%) | `stage.assets[]` の `kind: font` にすると、埋め込みのプレイヤーは asset を読めない(runtime.md §10)ので、主な開発面であるエディタの実行パネルで日本語が描けない。同梱なら `PLAYER_FILES` は 3 つのままで schema も変わらない。k6x8 は 6928 字が DWIDTH 6 で 5×7 に収まる(罫線の 62 字だけが右端の列 / 下端の行まで使う)ので、§2 の `len(s) * 6` を変えずに済む。全角を 12 にすると `len` との対応と `ui.button` の中央寄せを書き直すことになる。JIS の変換表の片側だけを持つと `～`(U+FF5E)と `〜`(U+301C)のように打ち方で □ になる。字形はトレースに載らないのでパリティに影響しない |
| 50 | 文字列の順序(v2.1 で確定) | 比較演算子(`<` …)は num のまま広げず、純関数 **`cmp(a: str, b: str) -> num`**(`-1` / `0` / `1`)を足す(expr.md §4.1)。順序は**コードポイント順**(= UTF-8 のバイト順)で、プレリュードの `F.cmp` はバイトを 1 つずつ比べる(Lua の文字列の `<` を使わない)。JIL の版は 3 → 4(プレリュードに `F.cmp`)。パリティは `tests/fixtures/v2-programs/storage.jin` の核の `order = cmp("B", "a") + cmp("ｱ", "😀") * 2`(= -3・`out: false`)を `apps/player/e2e/storage.spec.ts` がトレースの全行一致で見る | 演算子を str に広げると `<` の型規則と正準形の括弧規則(`cmp` の段)が 2 通りの意味を持つ。Lua の文字列の `<` は `strcoll` を通ってプロセスのロケールの照合順に従い、lupa(Python のプロセス)と Wasmoon で揃う保証が無い。JS の `<` は UTF-16 のコード単位順で BMP 外がずれるので、プレイヤーは Lua 側の規則を正典にする(プレイヤーも Lua で評価する)。`order` の 2 つの項はロケールの照合順(1 つ目)と UTF-16 順(2 つ目)でそれぞれ逆になる組で、どちらが割れても値が変わる。`out: false` にしたのは、`set` 行は公開の有無によらずトレースに載るので、公開 state を比べる既存の検査を書き換えずに済むため |
| 51 | ヘッドレスの記憶のファイル(v2.1 で確定) | `jin run --storage <file.json>`: 起動時に読んで `manifest.storage` に渡し(無ければ空)、終了時に最後の記憶を書き戻す(実行時エラーでも書き戻す)。形の検査は録画のヘッダの `storage` と同じ(`jin_wasm.jinrec.check_storage_copy`)、書き出しは鍵の昇順・2 字下げ・末尾改行。`--input` と一緒なら録画のヘッダが正で、`--storage` は読みも書きもしない(stderr に 1 行)。走らせる前にリンク・親ディレクトリ無し・対象の `.jin`・壊れたファイルを exit 2 で断り、書き戻しは `_write_atomically(allow_create=True)`(`jin render -o` と同じ)で書けなければ exit 1(runtime.md §8) | 1 回目の実行にファイルが無いのは普通なので空として始める。録画の再生は履歴の再実行で、abilities.md §8 の「再生は永続化しない」をヘッドレスでも守る(ヘッダの写しとファイルを混ぜると同じ録画から違う列が出る)。プレイヤーは tick ごとに `localStorage` へ書くので、エラーの tick より前の書き込みが残るのが同じ振る舞い。鍵の昇順は、書く順が実行ごとに違っても diff を安定させるため。新規作成のモードをトレースの 0600 にしないのは、中身がツール引数ではなくゲームの記憶で、置き場所を利用者が名指しするから(`jin render -o` と同じ)。走らせてから断ると記憶だけが失われたように見えるので、分かる失敗は先に言う |
| 52 | エディタの範囲選択・列を跨ぐ移動・陣を結ぶ(v2.1 で確定) | 範囲は選択の鍵 `step` に **`count`** を足して持つ(新しい種別を作らない。`path` は先頭、同じ列の連続する添字だけ、Shift クリックで広げて起点を持たない)。包む / 抽出は `from` = 先頭・`count` = 個数、削除は後ろから `removeStep` を並べる。ドラッグは `dropOps` 1 本で落とし先のモデルの要素(`selectionFromPointerV2`)で決め、同じ列は `moveStep`、**列を跨ぐ移動は `removeStep` + `addStep` の合成を 1 回で送る**(2 件目の pointer は削除後に数え直す・自分の子孫の列へは落とさない)、陣 → 陣は `addDelegate`、陣 → 手順は `addSigil`(`summon`・名前は手順名か空き番)。落とした側が呼ぶ側。操作の後に選ぶ要素は操作が返す(`EditV2.select`)。エディタが送らないのは委譲の重複と自分自身への落としだけ(ops.md §5) | 新しい種別は網羅性の分岐を 4 ファイルで増やすのに、中身は「ステップの選択」のままで、変換を `resolveSelectionV2` 1 本に保てる。ステップの選択はパスで持つので、包む / 抽出 / 移動の後に同じ鍵が別の要素を指す(選び直さないと黙って別のステップが選ばれる)。合成を 1 回で送れば `apply_ops` の原子性で「消えただけ」の状態が残らず、undo も 1 回で戻る。閉路や核の有無を先に見ないのはサーバの検査を二重に実装しないためで、委譲の重複だけは断る(サーバが断らず、同じ名前が 2 つ並ぶだけの無意味な編集になる)。結ぶ相手をツールバーの選択肢にしなかったのは、ops.md §5 がキャンバス上の操作として決めていることと、モデルから導いた一覧のウィジェットが要ること。引き換えに、図に描かれていない陣(どこからも参照されていない陣)は結べない(残存) |
| 53 | 文字入力(v2.1 で確定) | **`input.text() -> str`(read)**: この tick に確定した文字列を発生順につなぐ(無ければ `""`)。入力スナップショットの `events` に `{kind: "text", text}` を足し、`keys` / `pointer` の形は変えない。文字列を保つのはプログラムの `state`(`name = name ++ input.text()`)、消すのは `pressed("Backspace")`。プレイヤーは canvas の上に見えない 1 行の `<input>` を置いてフォーカスを移し、合成中でない `input` と `compositionend` のたびに値を取り出して空にする(`event.data` は読まない)。IME の合成中のキー(`isComposing` / `key == "Process"`)は集めず、入力欄からのキーは集めるが既定動作を止めない。`text` は空でなく、制御文字と対にならないサロゲートを含まない(集め手が落とし、`.jinrec` の読み手は Python / TS とも同じ文言で断る)。`.jinrec` の版は 1 のまま、JIL は 4 → 5。あわせてプレリュードの `JS` の制御文字を `%c` ではなく範囲で書く(jil.md §1) | `ui.input(...)` のようなウィジェットにすると、どの欄が文字を受けるか(フォーカス)をプレリュードが持つことになり、snapshot / resume に運ぶ状態が増え、§0 の「保持モードのウィジェット木を作らない」と abilities.md §4 の「フォーカスは無い」に当たる。読み取りなら `pressed` と同じ純関数で、状態を持たない。`event.data` / `inputType` は合成の前後でブラウザごとに届き方が違うので、値を取り出して空にする 1 つの規則にした(どちらのイベントが後に来ても 2 回目は空)。合成中のキーは IME と OS でどの `code` が来るかが違い、録画に載せても意味が無い。`.jinrec` の版を上げると既存の録画(`paddle-120.jinrec` など)が等号の検査で読めなくなる一方、読み手はすべてこのリポジトリにあり、古い読み手は未知の `kind` を行番号付きで断る(黙って読み飛ばさない)。`%c` は C の `iscntrl` でプロセスのロケールに従い、UTF-8 のロケールで動く lupa のホストで非 ASCII の途中のバイトを `\u00xx` にして tick 結果の JSON を壊した(手元の macOS で `jin run --input` が文字入力の録画を読めなかった。C ロケールの出力は変わらない) |
| 54 | 隠れた実行パネルのプレイヤー(Issue #66 で確定) | 編集モードで実行パネルが隠れている間、**プレイヤーを止めておく**(案 B)。親(`RunPanel`)は `hidden` が変わるたびに `jin.control` の **`suspend` / `wake`** を送るだけで、止める / 起こすの判断はプレイヤーが持つ: `suspend` は走っていたかを覚えて止め、止められている間に届いた `jin.load` は(keep で続けるときも最初からのときも)走り出さずに保留し、`wake` で走らせる。語彙は 7 語のまま(action が 2 つ増えるだけ)。編集モードの図に直前のオーバーレイが残るのは v1 のデバッグモードと同じ(トレースは `ViewState` の外)。証拠は `apps/editor/e2e/v2.spec.ts`「編集モードでは隠れたプレイヤーを止め、図を描き直さない」(隠れている間の図の差し替えが 0 回・tick と upto が不変・戻ると走り出す・keep 無しの差し替えも止まったまま)と `tests/contract/test_editor_contract.py` | 見えないゲームが走り続けると、親がトレースを受けて 1 秒ごとに `jin/model` + `jin/renderSvg`(最大 4000 行)を往復して図を差し替え、編集モードのクリック / ドラッグが差し替えと重なって結果がタイミングに依存した(Issue #64 のフレークの根)。A(積むだけで描き直さない)は走り続けるので 4000 行を超えて古い行が落ち、記憶環の値の積算が黙って狂う。C(トレースを載せない)は往復と差し替えが残る。親から `pause` / `start` を送るだけでは、最初の `jin.load`(エディタの初期モードは編集)と keep を外した差し替えが `setUp` で走り出して数 tick の行が届き、1 回描き直す。プレイヤー側で保留するのは、走り出さないことを構成で保証するため。keep の差し替えで `wasRunning` を見るだけだと、止められて偽になっているので起こしても走らない(`wakeRunning` を `setUp` で消さない) |
| 55 | v1 の陣(LLM エージェント)を v2 から呼ぶ(v2.1・Issue #54 で仕様確定) | 道具環に **`kind: agent`**(追加キー `file` = v1 の `.jin` への相対パス)を足す(`summon` は使わない)。`cast target=<sigil 名> args=[prompt: str] into=<id: num>` が**要求 id だけを同期で返し**、答えは後の tick に自陣の `on message` へ `(sigil 名, id, text: str)` で届く(`wait` / `until` で待つ)。ホスト境界は変えない: 問いは tick 結果の **`asks`**(問いがあった tick だけ・`storage` の直後・release でも出る)、答えは入力イベント **`reply`**(`{kind, id, text}`・`.jinrec` の版は 1 のまま)。配達は §2 の 1 で `emit` の後、`emit` 行で残す(`trace-kinds` は 13 のまま)。要求 id の通し番号は snapshot に載せ、未回答の問いは捨てる。v1 を走らせるのは **`jin_cli`**(`run_headless` は答える呼び出し可能を引数で受けるだけで `jin_adk` を知らない)。`file` は v2 の `.jin` の親ディレクトリの中に閉じ(asset と同じ)、答えは v1 トレースの最後のモデル応答(`final` 行、無ければ最後の `model` 行)の output(str)、問いごとに新しいセッション。`jin run --model fake`(FakeLlm)と `--record`(答えを `reply` 行として録画)を v2 に開け、`--input` があれば v1 を**呼ばない**。JIL は 5 → 6。ブラウザは `asks` を無視し(答えは来ない)、`reply` 入りの録画の再生だけできる。意味検査は既存コード(`cast` の解決順に agent・式の中は JIN202・`message` の手順の形は JIN221・`file` の形は schema)。正典は runtime.md §11 / model.md §3.2 / §3.5。実装は Sub-Issue に割る(#68: jin_core + jin_wasm + プレイヤーの読み手、#69: jin_cli のホストと文書) | `summon` を流用しない: `summon` は `circle` + `rite` の同期呼び出しで JIN011 / JIN212 が張り付き、描画・LSP・エディタが `kind == "summon"` で分岐する(v1 の `.jin` に手順は無い)。同期で答えを待たない: LLM は非同期で、tick の中で待つと決定性(§4)とホスト境界(§4.3)が壊れる。`into` に id を受けるのは Issue の「into に受ける」と「emit / on message で届く」を両立させる最も素直な形で、複数の問いを見分けられる。答えを入力にするのは録画の再生が LLM を呼ばないため(`storage` のヘッダの写しと同じ規律)。`text` イベントと同じ検査で版を上げない。答えの値を `str` 一択にしたのは v1 の state 値が文字列(model.md §3.3)で、`final` 行は常に定義される(`out: true` の state は root が flow なら無い・`final_state` は非公開の鍵が `None` で混ざる)。`jin_wasm` に `jin_adk` を入れると層の契約(`jin_adk | jin_render | jin_wasm` は兄弟)が壊れ、プレイヤーのパリティ(同じ Lua)に v1 の語彙が混ざる。「v2 の `jin run` に S1 は無い」は `agent` を持たない v2 についての主張に書き換える(§0 / #10 / CLAUDE.md)。`--model fake` でも `ref` は import される |
| 56 | wasm-GC 直接出力(v2.1・Issue #53 で仕様確定。実装は Sub-Issue #73〜#76・**実装済み**) | `jin build --target wasm-gc` / `jin run --target wasm-gc` は新しい兄弟パッケージ **`jin-wasmgc`**(`jin-core` + `jin-wasm` + `wasmtime` に依存。`jin-lsp` と並ぶ層)。生成系は **WAT を出して `wasmtime.wat2wasm` で束ねる**(自前の binary writer も `wasm-tools` も無し。決定性は実測)。ホスト境界は `boot` / `tick` の 2 関数のまま、**引数も戻りも UTF-8 の JSON 1 本を線形メモリで越える**(ホストが呼ぶ export は `input(n)` / `boot(n)` / `tick(n) -> (ptr, len)` の 3 つ。`boot` に結果は無く核のエラーは最初の `tick` に載る(Lua と同じ)。manifest の `resume` / `storage` に汎用の JSON の読み手が要るので `seed` / `t` / `inputs` も同じ読み手で読む)。**module は trap しない**(実行時エラーは `error` 行)。数値の書式はホストに任せず module の中に最短往復表現を書き、`test_prelude.py` の 700 件を共有 fixture にする。`wait` は静的に求めた閉包だけを**状態機械**(フレームの `struct` + `br_table`)に変換し、観測できる契約(再開のタイミング・トレースの `wait` 行・`resume` で捨てる)だけを仕様にする。命令数の上限は hook も fuel もブラウザに無いので**生成部が戻り辺と呼び出しに埋めるカウンタ**(値と `error` 行の文は同じ・同じ tick で止まる・止まる位置と debug の `seq` / `pointer` は問わない)。ヘッドレスは **wasmtime** で走らせ(Issue の「lupa」から動かした点。CI でブラウザ無しに両経路を突き合わせるため)、パリティは v2-programs 14 本 + examples-v2 3 本の全部で release は `--frames`、debug は `--trace` + `--frames` がバイト一致。manifest に `target`(無ければ `"lua"`)を足してプレイヤーが `JinHost` / `WasmGcHost` を選ぶ。`jil` の版は両経路で共有 | `wasmtime` を `jin-wasm` の必須依存にすると LSP のインストールに 31 MB 乗る。ホストへ数値書式を export するとホストごとに実装が分かれてパリティの根拠が消える。fuel に頼るとブラウザで上限が掛からない。バイナリ writer を自作すると生成系の作業量が倍になり、`wasm-tools` に頼ると CI に新しい実行ファイルが要る |
---

## 12. 実装フェーズ(Claude Code への発注単位)

| Phase | 内容 | 完了条件 |
|---|---|---|
| 0 | `docs/spec/v2/` 8 本、`examples-v2/` 3 本(手書き)、`wasm-api-probe.md`(Wasmoon / lupa の版・API・yield 制約の実測)、`tests/spec/test_v2_spec_consistency.py`(設計書と仕様書と例の突合) | 仕様に自己矛盾がない。§2.2 の例が仕様どおりに読める。probe が §1.1 の事実を確定させる |
| 1 | `jin_core.v2`(model / expr / spans / abilities / semantic / ops)+ `jin-v2.schema.json` / `abilities.json` の生成 + `check_text` の version 振り分け + CLI(`schema --version 2`、`build` / `run` / `render` は v2 を明示的に拒む)+ LSP は v2 の診断だけ運ぶ | v1 の全テストが緑のまま。JIN2xx と共有番号の全部に fixture。`examples-v2` が `check` / `fmt --check` を通る。32 件の ops が往復でバイト一致(**実装済み**) |
| 2 | `jin-wasm`(jil / prelude.lua / codegen / lupa runtime / jinrec / bundle / `jin run` / `jin build`) | examples 3 本が `jin run --ticks 300` で回り、決定性テストが通る。JIL 禁止語の走査が緑(**実装済み**。プレイヤーの同梱は Phase 4・§11 #25) |
| 3 | `jin_render.v2`(陣 / 手順 focus / トレースオーバーレイ)+ `jin render` / `jin/renderSvg` の v2 | SVG スナップショットが安定。13 種が `paddle` で全部出る(**実装済み**。`delegate` だけは `transfer.jin` で補う・§11 #30) |
| 4 | `apps/player`(Wasmoon ホスト / canvas / 入力 / 音 / `.jinrec` 録画)+ `dist/index.html` | `dist/` をブラウザで開いて `paddle` が遊べる。パリティ(Playwright)が通る(**実装済み**。パリティは `apps/player/e2e/parity.spec.ts`(録画 → `jin run --input` → トレース全行一致)、`--single` は `single.spec.ts`。`jin build` の同梱は `scripts/sync_player.py`。命令数の上限がコルーチンに届いていなかった残存は §11 #32 で閉じた) |
| 5 | LSP(hover / completion の v2)+ エディタ(v2 フォーム・式エディタ・実行パネル・ライブリロード) | 開く → ステップを足す → 保存 → 正準形一致。実行パネルで動く(**実装済み**。`apps/editor/e2e/v2.spec.ts` が「開く → ステップを足す → 保存 → `jin fmt` とバイト一致」「式エディタの補完」「実行パネルで 10 tick 進めてスクラブ」を実ブラウザで通す。§11 #36〜#38) |
| 6 | デバッグ(録画のスクラブ・state 値の表示・`assert` のバッジ) | `.jinrec` を読んでスクラブするとオーバーレイと記憶環の値が動く(**実装済み**。`apps/editor/e2e/v2.spec.ts` が「`.jinrec` を読んでスクラブするとオーバーレイと記憶環の値が動く」「偽になった `assert` のバッジと一覧」「録画 → 書き出し → `jin run --input` と同じ行数 → 読み直し」を、`apps/player/e2e/replay.spec.ts` が再生と `jin run --input` の全行一致を実ブラウザで通す。§11 #39〜#41) |
| 7 | v2.1 候補: `--target wasm-gc`(**仕様確定**。§11 #56・jil.md §6・`wasmgc-api-probe.md`。実装は Sub-Issue A〜D = #73 / #74 / #75 / #76 で、A が `jin-wasmgc` + WAT 生成系 + `jin build` / `jin run --target wasm-gc` で fib の公開 state 一致(**実装済み**)、B がランタイム部(文字列 / list / 型紙 / JSON / 数値の書式と strtod / PCG32 / 能力 / 純関数 / エラー機構 / 命令数の上限)+ `on` の配達で 6 本の fixture の release `--frames` 一致(**実装済み**。`tests/contract/test_wasmgc_parity.py` と `tests/fixtures/numbers.jsonl` の 9136 行)、C がスケジューラ(陣の順 / flow / transfer / emit / summon / guard / `asks` + `reply`)+ `wait` の状態機械 + debug(トレース / `snapshot` / `resume`)で 17 本のトレース全行一致(**実装済み**。`tests/contract/test_wasmgc_parity.py` が 17 本 × release / debug をバイト一致で、`packages/jin-wasmgc/tests/test_resume.py` が「途切れずに走らせた列と一致」を通す)、D がプレイヤーの `WasmGcHost`・manifest の `target`・`--single`・ブラウザの e2e(**実装済み**。`apps/player/e2e/wasmgc.spec.ts` が「`game.wasm` を共通のプレイヤーで録画 → Lua と wasm-GC の両方の `jin run --input` と全行一致」と `--single` の wasm-gc 版を実ブラウザで通す。`runtime.wat` は `scripts/generate_runtime_wat.py` の生成物に切り替えた)。**Issue #53 は 4 つの Sub-Issue で完了**)、`storage`(**実装済み**。§11 #45〜#47。`packages/jin-wasm/tests/test_storage.py` が「1 回目の記憶を 2 回目の boot に渡すと続く」を、`apps/player/e2e/storage.spec.ts` が「`localStorage` に残り読み直しで続く → 録画のヘッダの写しで `jin run --input` と全行一致 → 再生は上書きしない → 記憶を消す」を実ブラウザで通す)、テキスト入力欄(**実装済み**。§11 #53。`apps/player/e2e/text_input.spec.ts` が「打つ・貼り付ける・Backspace → 録画 → `jin run --input` とトレース全行一致」を実ブラウザで通す)、式の正準化(**実装済み**。§11 #48・expr.md §8。`tests/contract/test_canonical_contract_v2.py` が examples-v2 と fixture の冪等と式の AST 保存、`tests/fixtures/canonical/v2/messy.jin` → `messy.expected.jin` のバイト一致を、`apps/editor/e2e/v2.spec.ts` が「`score+ (1)` を Enter で確定 → `score + 1` に揃う → 保存が `jin fmt` と一致」を実ブラウザで通す)、状態を保ったライブリロード(**実装済み**。§11 #42〜#44。`packages/jin-wasm/tests/test_resume.py` が「途切れずに走らせた列と一致」を、`apps/player/e2e/reload.spec.ts` と `apps/editor/e2e/v2.spec.ts` が実ブラウザで「式を直しても tick / 記憶環の値が続く」を通す)、v1 の陣(LLM エージェント)を v2 から呼ぶ Python ホスト(**実装済み**。§11 #55・runtime.md §11・model.md §3.2 の `agent`。#68 が `jin_core` + `jin_wasm` + プレイヤーの読み手、#69 が `jin_cli.agents.AgentHost` と `jin run --model fake` / `--record`。`tests/contract/test_cli_contract.py` が「`agent.jin` が v1 の pipeline に問い、`fake-response` が次の tick の `on message` に届く → `--record` の録画を `--input` で再生すると v1 を呼ばずに同じトレース」を実プロセスで、`apps/player/e2e/agent.spec.ts` が `reply` 入りの録画のブラウザ再生と `jin run --input` の全行一致を通す) | 任意 |

Phase 0 の仕様書を先に承認してから Phase 1 に入る(v1 と同じ運び)。
