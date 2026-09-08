# エディタからの実行（Issue #34）— 設計

対象: `apps/editor` から `jin run` を起動し、トレースを逐次オーバーレイに反映する。
正典との関係: 要件書 §7.2 の「ライブ実行(WebSocket で `jin run` からストリーム)は v1.1」の実装。

## 1. 何が無くて何があるか

表示側は Phase 6 で揃っている。欠けているのは**トレースを生成する経路**だけである。

| | 状態 |
|---|---|
| `jin/renderSvg` が `trace` + `upto` を受ける | ある（Phase 3） |
| `apps/editor/src/trace/parse.ts` の JSONL パース | ある |
| `apps/editor/src/debug/` のスクラバ・pointer フィルタ・詳細パネル | ある |
| `jin run --trace` の JSONL 出力 | ある（Phase 2） |
| **実行を起動してトレースを受け取る経路** | **無い** |

`Replay`（`{ name, events, upto }`）を組み立てて `setReplay` すれば図は動く。
`loadTrace(file)` の隣に「実行して `Replay` を作る」経路を足すのがこの設計の骨格である。

## 2. 全体の流れ

```
ブラウザ（エディタ）
  │ POST /run  {prompt, model}   ヘッダ: X-Jin-Token
  ▼
jin editor の HTTP サーバ（既存の静的サーバに do_POST を追加）
  │ 子プロセス: python -m jin_cli.main run <対象> <prompt> [--model fake] --trace <一時ファイル>
  │ 一時ファイルを tail（行が増えたら送る）
  ▼ SSE:  event: row / event: done / event: error
ブラウザ → Replay を組み立てて upto を伸ばす → jin/renderSvg（既存の経路）
```

## 3. 判断とその理由

### 3.1 実行の口は LSP(ws) ではなく `jin editor` の HTTP に開く

**要件書 §7.2 は「WebSocket で `jin run` からストリーム」と書いており、これはそこからの逸脱である。**
`decision-conformance.md` に記録し、PR 本文にも明記する（§2.25.6 の hover と同じ扱い）。

理由は 2 つある。

1. **WebSocket には same-origin 制限が無い。** ブラウザで開いている任意のページが
   `ws://127.0.0.1:<port>` へ繋いでリクエストを打てる（`docs/spec/ops.md` §5.1）。
   防御はトークン一致だけになる。HTTP なら**カスタムヘッダが CORS の preflight を強制する**ので、
   他オリジンのページからは撃てない。`jin run` は `ref` の import で任意コード実行なので、
   ここは一段強い防御が要る。
2. `jin/…` を増やさずに済む。`tests/contract/test_editor_contract.py::test_the_debug_mode_does_not_add_a_new_lsp_request`
   が 6 種（`model` / `renderSvg` / `ops` / `applyOps` / `open` / `save`）で等号固定しており、
   増やすなら要件書 §6.3 と `docs/spec/ops.md` の変更が要る。ストリームには通知メソッドも要る。

CLAUDE.md の「`apps/editor` は LSP プロトコルにのみ依存し、Python パッケージを直接 import しない」は
**import の禁止**であって通信路の限定ではないが、読み違えを防ぐため例外を明記する
（実行だけは同一オリジンの HTTP を使う。Python の import は引き続き行わない）。

### 3.2 トークンは `X-Jin-Token` ヘッダで送る

**body や query に置いてはいけない。** `Content-Type` が `text/plain` / `application/x-www-form-urlencoded` /
`multipart/form-data` の POST は CORS の **simple request** であり、preflight 無しで
他オリジンから送信できる（応答は読めないが、実行は起きてしまう）。
カスタムヘッダを 1 つ付けると preflight（`OPTIONS`）が必須になり、こちらが CORS ヘッダを
返さない限り本要求は飛ばない。**この 1 点が「HTTP は ws より強い」の根拠のすべて**である。

加えて `Origin` を検査し、自分の origin 以外を拒む（安いので入れる。
`docs/spec/ops.md` §5.1 の残存「Origin 未検査」と同じ種類の穴をここでは開けない）。

### 3.3 受信は `EventSource` ではなく `fetch` + `ReadableStream`

`EventSource` はカスタムヘッダを付けられない。3.2 の方針と両立しないので、
SSE のフレーム（`event:` / `data:` / 空行）を自前で読む。
サーバが送るのは SSE の書式だが、クライアントは `EventSource` を使わない。

### 3.4 実行は子プロセス

`jin editor` は LSP を抱えた**長命プロセス**である。そこで `ref` を import すると、
`sys.modules` の汚染（`--resolve` で実測済み・ADR-018）や、ツール関数の `sys.exit()` が
asyncio によってループの外へ再送出されること（F-S-P2-102）が、サーバごと巻き込む。
`--resolve` が子プロセス隔離で閉じた危険を、ここで作り直さない。

子プロセスは `[sys.executable, "-m", "jin_cli.main", "run", ...]` で起こす
（`jin_cli` に `__main__.py` は無いが `main.py` に `if __name__ == "__main__": app()` がある）。
**cwd と env は親から継承する。** `jin editor` を起動した人自身の `jin run` と
`ref` の解決を一致させるためで、cwd を対象ファイルの親へ移すと解決先が CLI と変わる。

**子は同じ権限で走る。任意コード実行（S1）は残る。**

### 3.5 トレースを毎行 flush する

`_LazyTruncateSink` は `os.fdopen(fd, "w")` のブロックバッファで書いており、`flush()` は
切り詰めの 1 回だけである。このままでは tail しても**実行完了まで 1 行も見えず**、
SSE がストリームにならない。`write` に `flush()` を足す。

CLI の表面もトレースの内容も変わらず、変わるのは「途中でも読める」ことだけである。
代案の `--trace -`（stdout へ JSONL）は v1 の CLI 表面の変更になるので採らない。

## 4. HTTP の契約

### `POST /run`

要求:

| | |
|---|---|
| ヘッダ | `X-Jin-Token: <起動トークン>`、`Content-Type: application/json` |
| body | `{"prompt": "...", "model": "fake" \| null}` |

**対象ファイルは body で受けない。** `jin editor` に渡されたファイルに固定する
（クライアントが任意のパスを実行できないようにする）。

応答:

| 状況 | 応答 |
|---|---|
| 正常 | `200` / `Content-Type: text/event-stream` / `Connection: close` |
| トークン不一致・欠落 | `403` |
| `Origin` が自分以外 | `403` |
| 既に 1 本走っている | `409` |
| body が JSON でない・`prompt` が無い | `400` |
| `model` が `fake` 以外の非 null | `400`（`jin run` と同じ規律） |

CORS ヘッダは**一切返さない**。`OPTIONS` には `403` を返す（preflight を通さない）。

### SSE のフレーム

```
event: row
data: {"seq":1,"agent":"...","kind":"...","name":"...","pointer":"...","input":...,"output":...}

event: done
data: {"exit":0,"stderr":"11 イベント（session: jin）\n"}

event: error
data: {"message":"..."}
```

- `row` の `data` は**トレース JSONL の 1 行そのまま**である。TS 側は既存の
  `parse.ts` の行の契約をそのまま使い、二重に実装しない
- `done` は子プロセスの終了で 1 回だけ。`exit` が 0 以外でも `done` を送る
  （`stderr` に理由が入る。図は消さない）
- `error` はサーバ側の事故（子を起こせない・一時ファイルを作れない）。この場合 `done` は送らない
- SSE の応答は `Content-Length` を持てないので `Connection: close` を明示する
  （既存の `_StaticHandler` は HTTP/1.1 で、`SimpleHTTPRequestHandler` が
  `Content-Length` を必ず付けることを前提にしている。ここはその前提の外である）

## 5. 防御と残存

`docs/spec/ops.md` §5.1 に追記する。

段:

1. **`Origin` 検査** — 自分の origin 以外を拒む
2. **カスタムヘッダのトークン一致** — preflight を強制し、他オリジンからの simple request を封じる
3. **対象ファイルの固定** — クライアントはパスを指定できない
4. **同時 1 本** — 2 本目は `409`
5. **終了時の後始末** — `serve` の `finally` で走っている子を必ず終了させる（Issue #32 の教訓）

**残存**:

- **S1（任意コード実行）は残る。** 子は同じ権限で走り、`ref` を import する。
  `--model fake` はモデル呼び出しをネットワークに出さないだけで、import は行う。
  **信頼しないディレクトリの `.jin` を `jin editor` で開かないこと**（従来と同じ）
- トークンを握った攻撃者は、これまで `jin/save` で悪意ある `ref` を**書き込む**ところまでだったが、
  実行の口が開くことで**連鎖が攻撃者だけで完結する**。この上で常時有効とするのは
  「`jin editor` に `.jin` を渡す時点でそのディレクトリを信頼している」という前提に立つ判断である
- キャンセルを持たないので、実モデルでの長い実行はハンドラのスレッドを 1 本占有し続ける

## 6. 触るもの

Python:

- `packages/jin-cli/src/jin_cli/editor.py` — `_StaticHandler` に `do_POST` / `do_OPTIONS`
- `packages/jin-cli/src/jin_cli/runserver.py`（新規）— 子プロセスの起動・tail・SSE の生成。
  `editor.py` を膨らませない
- `packages/jin-cli/src/jin_cli/main.py` — `_LazyTruncateSink.write` に `flush()`
- `docs/spec/ops.md` §5.1 — 上の防御と残存
- `delivery/20260904-1445-jin/decision-conformance.md` — §7.2 からの逸脱 2 点
  （v1.1 と書かれたものを v1 で実装すること・機構が WebSocket ではなく HTTP であること）

**`jin-requirements.md` は変更しない。** 上位要件書の本文を直すのは人間の承認領域であり、
`docs/superpowers/specs/2026-09-04-jin-overview.md`（写し）との一致を
`tests/spec/test_spec_consistency.py` が担保しているので、片方だけ直すと落ちる。
リポジトリの流儀は**要件書を残したまま逸脱を `decision-conformance.md` に記録する**ことである
（§2.25.6 の hover が同じ形）。要件書の更新が要るという判断になれば、それは別の変更として起こす。

TypeScript:

- `apps/editor/src/run/client.ts`（新規）— `fetch` + `ReadableStream` で SSE を読む
- `apps/editor/src/debug/DebugPanel.tsx` — prompt 入力・model 選択・実行ボタン・実行中の表示
- `apps/editor/src/App.tsx` — 実行中に `Replay` を差し替えていく配線
- `apps/editor/src/main.tsx` — 実行の口の origin（静的サーバと同じ）を App へ渡す

## 7. 状態の置き場

**実行状態は `ViewState` の外に置く**（DP-COMMON-19 の 5 状態を増やさない）。
`Replay` と同じ理由である。実行の有無は「LSP との関係」と直交しており、
混ぜると状態が掛け算で増える。

実行中は `Replay` を差し替えながら `upto` を最大に保つ（新しい行が来るたびに図が進む）。
実行が失敗しても**図は消さない**。`.jin` は壊れていないので、理由をパネルに出すだけにする
（壊れたトレースの扱いと同じ規律）。

## 8. テスト

ネットワークと API キーは要らない（`--model fake`）。

Python（`packages/jin-cli/tests/`）:

- トークン不一致・欠落で `403`
- `Origin` が自分以外で `403`、`OPTIONS` で `403`
- 2 本目が `409`
- body が壊れている / `model` が `fake` 以外で `400`
- tail が行を落とさない（`flush` が効いていること。**flush を外すと落ちるテスト**にする）
- 静的配信が従来どおり動く（`GET` は無傷）

TypeScript（`apps/editor/test/`）:

- SSE フレームの解釈（分割された chunk をまたぐ行、`event:` の種別ごとの分岐）
- 実行中に `Replay` が伸びること

e2e（`apps/editor/e2e/`）:

- `--model fake` で実行 → オーバーレイが出る。既存の e2e は一時ディレクトリに `.jin` を置いて
  `uv run jin editor <file> --no-browser` を spawn する形なので、**`ref` を持たない `.jin`** を使い、
  `PYTHONPATH` の細工を要らなくする（`examples/pipeline` を使うなら
  `PYTHONPATH=tests/fixtures/stubs` が要る。e2e にその依存を持ち込まない）
- 子プロセスを起こすので、Issue #32 と同じ後始末（実行中に `jin editor` を落としても
  子が残らない）を確かめる

契約:

- `jin/…` が 6 種のままであること — **既存の
  `test_the_debug_mode_does_not_add_a_new_lsp_request` がそのまま守る**（変更しない）
- 「エディタは 1 本の線も描かない」も無傷（SVG は従来どおり `jin/renderSvg` から受け取る）

## 9. この設計で決めたこと（Issue #34 の未決事項）

| DP | 決定 | 理由 |
|---|---|---|
| DP-A 配送方式 | 一時ファイルを tail し SSE で流す | `jin run` の CLI 表面を変えない。`--trace -` は v1 の表面変更 |
| DP-B キャンセル | 持たない | v1 のスコープ外。ただし終了時の後始末は必須 |
| DP-C 状態の置き場 | `ViewState` の外 | 5 状態を増やさない（DP-COMMON-19） |
| 有効化 | `jin editor` なら常に有効 | `.jin` を渡す時点でディレクトリを信頼しているという前提（人間判断） |
