# 意味編集オペレーション一覧（ops.md）

> 正典。要件書 `jin-requirements.md` §6.3 の実装仕様。エディタと LSP が共通で使う。
> **サーバ実装は Phase 4（`jin-lsp` の `jin/applyOps` / `jin/ops`）**。
> 本ラウンド（Phase 0 / 1）で確定させたのは**仕様と、`jin_core.ops` の純関数としての契約**である。

## 0. この文書の読み方（機械可読の約束）

`tests/spec/test_spec_consistency.py` が §2 の表のオペレーション名集合を
要件書 §6.3 の 19 件と突合する。`<!-- machine-readable: ops-list -->` マーカー付き表の書式を変えない。

## 1. 共通契約

- 各オペレーションは **JSON Pointer で対象を指定**する
- 失敗時は**診断コードで理由を返す**（`docs/spec/diagnostics.md` のコード体系を使う）
- サーバは各オペレーションの**逆オペレーションを応答に含める**。undo / redo はクライアントが逆オペレーション列を保持する
- 適用結果はモデルであり、テキストへの反映は正準形（`docs/spec/model.md` §7）を通す。
  差分は `workspace/applyEdit` でクライアントに送る
- オペレーションはモデルに対する**純関数**である（`jin_core.ops` は I/O を持たない）
- **逆オペレーションを当てた結果は、順オペレーションを当てる前の正準形テキストとバイト一致する**
  （要件書 成功条件 5）。配列の要素の**位置**も、順オペレーションが副次的に作った**入れ物**も元に戻す。
  この復元条件は §2.1 の表で明示する

## 2. オペレーション（v1: 19 件）

<!-- machine-readable: ops-list -->

| オペレーション | 対象 pointer | 引数 | 逆オペレーション |
|---|---|---|---|
| `addCircle` | `/circles` | 挿入位置 index、circle の初期値 | `removeCircle` |
| `removeCircle` | `/circles/<i>` | — | `addCircle`（元の index と値） |
| `setCore` | `/circles/<i>` | `core`（null で核なしに戻す） | `setCore`（旧値） |
| `setDescription` | `/circles/<i>` | `description`（null で削除） | `setDescription`（旧値） |
| `setRune` | `/circles/<i>` | `rune`（null で instruction ごと削除） | `setRune`（旧値） |
| `addTool` | `/circles/<i>/tools` | 挿入位置 index、tool の値 | `removeTool` |
| `removeTool` | `/circles/<i>/tools/<j>` | — | `addTool`（元の index と値） |
| `moveTool` | `/circles/<i>/tools/<j>` | 移動先 index（= 環上の角度の変更） | `moveTool`（逆向き） |
| `addState` | `/circles/<i>/state` | 挿入位置 index、state の値 | `removeState` |
| `removeState` | `/circles/<i>/state/<j>` | — | `addState`（元の index と値） |
| `setState` | `/circles/<i>/state/<j>` | `name` / `type` / `out` の変更分 | `setState`（旧値） |
| `setFlow` | `/circles/<i>` | `flow`（null で flow なしに戻す） | `setFlow`（旧値） |
| `addDelegate` | `/circles/<i>/delegate` | 挿入位置 index、circle 名 | `removeDelegate` |
| `removeDelegate` | `/circles/<i>/delegate/<j>` | — | `addDelegate`（元の index と値） |
| `setGuard` | `/circles/<i>/boundary/guards/<j>` | `on` / `ref`。`<j>` が末尾+1 なら追加 | `setGuard`（旧値）または `removeGuard`（+ 復元条件 §2.1） |
| `removeGuard` | `/circles/<i>/boundary/guards/<j>` | — | `setGuard`（元の index と値） |
| `toggleAwait` | `/circles/<i>` | tool 名、追加位置 `index`（省略時は末尾） | `toggleAwait`（同じ tool 名 + 復元条件 §2.1） |
| `setRoot` | `` （ルート） | circle 名 | `setRoot`（旧値） |
| `rename` | 対象要素（circle / tool / state） | 新しい名前 | `rename`（旧名） |

<!-- /machine-readable -->

### 2.1 逆オペレーションが復元しなければならないもの

`boundary` を持たない circle に `toggleAwait` / `setGuard` を当てると、実装は `boundary` を新設する。
また `toggleAwait` で await を外すと、その要素の**位置**が失われる。どちらも逆オペレーションが
明示的に運ばないと復元できず、undo 後の正準形が元とバイト一致しなくなる（§1 の最後の項）。

<!-- machine-readable: ops-restore-conditions -->

| オペレーション | 失われるもの | 逆オペレーションが運ぶ引数 |
|---|---|---|
| `toggleAwait`（外す） | `boundary.await[]` における要素の位置 | `index` |
| `toggleAwait`（付ける） | 新設した `boundary` の不在 | `pruneBoundary` |
| `setGuard`（追加） | 新設した `boundary` の不在 | `pruneBoundary` |

<!-- /machine-readable -->

`pruneBoundary` は「順オペレーションが `boundary` を新設した」ことを表す印である。
逆オペレーションを当てたあと `boundary` が空（`guards` と `await` が両方空）になっていれば取り除く。
**元のファイルに `"boundary": {}` と書かれていた場合は印が付かない**ので、そのまま残る。

## 3. `rename` の参照追随

名前が ID なので（要件書 §10 #11）、`rename` は参照を全て追随させる。追随対象:

<!-- machine-readable: rename-cascade -->

| 対象 | 追随する参照元 |
|---|---|
| circle 名 | `root` / 全 circle の `delegate[]` / 全 circle の `flow.steps[]` / 全 circle の `tools[kind=summon].circle` |
| tool 名 | 同じ circle の `boundary.await[]` |
| state 名 | 全 circle の `flow.exit.key`（値が一致するもの）/ 全 circle の `instruction.rune` 内の `{key}` |

<!-- /machine-readable -->

rune 内 `{key}` の置換は `docs/spec/model.md` §3.1 の抽出規則に従い、`{{` / `}}` のエスケープを壊さない。

state 名の追随を**可視範囲に絞らず全 circle に対して行う**のは、可視範囲の判定（`docs/spec/model.md` §5）が
flow の構造に依存し、rename の前後で可視範囲が変わりうるためである。同名の state key が別の circle にも
存在する場合は過剰置換になりうるので、rename 後に `jin check` を通して JIN050 を確認すること。

## 4. 失敗時の診断コード

| 状況 | コード |
|---|---|
| 未知のオペレーション名 / pointer が解決できない / 添字が範囲外 / value の形が違う / 適用結果がスキーマ違反 | JIN002 |
| リネーム先の名前が既に使われている（circle / tool / state） | JIN010 |

`jin_core.ops.OpError` が `code` / `message` / `hint` / `pointer` を持つ。

## 5. `jin/open` / `jin/save`（Phase 4 で確定・ADR-011）

DP-JIN-EDITOR-PROTOCOL-01（案 C）の `constraints[]` は「リクエスト名は仮称であり、
人間の承認を得たうえで本文書で確定させる」と定めていた。**2026-09-07 に toyota が
`jin/open` / `jin/save` を正式名として確定し、Phase 4 で実装した。**

**これらは §2 の 19 オペレーションではない。** §2 の表は意味編集オペレーションの一覧であり、
`jin/open` / `jin/save` は要件書 §6.3 の独自リクエスト（`jin/model` / `jin/renderSvg` /
`jin/applyOps` / `jin/ops`）に並ぶ**リクエスト**である。表に足すと 19 件の等号が崩れる。

| リクエスト | params | 応答 |
|---|---|---|
| `jin/open` | `uri` / `token` | `uri` / `text` / `diagnostics[]` |
| `jin/save` | `uri` / `token` / `text`（省略可） | `uri` / `path` / `text` / `diagnostics[]` |

- **ws モードのエディタだけが使う。** stdio のクライアント（Claude Code / VS Code）は
  従来どおりクライアントがファイル I/O を担うので、stdio では常に拒否する
- `jin/save` が書くのは**正準形**である（§1「テキストへの反映は正準形を通す」/
  要件書 成功条件 5「エディタ保存と `jin fmt` の出力がバイト一致」）。
  `text` を省略するとサーバが持っているモデルの正準形を書く
- 構文エラー（JIN001）のあるテキストは保存しない。壊れたファイルを残さない

### 5.1 防御（`jin lsp --ws` は same-origin 制限の無い口である）

WebSocket にはブラウザの same-origin 制限が無い。任意のページが `ws://127.0.0.1:PORT` へ
繋いで `jin/save` を打てるので、4 段で閉じる（実装は `jin_lsp.fileio`）:

| 段 | 内容 |
|---|---|
| 1 | **既定で無効。** `jin lsp --ws PORT --root <ディレクトリ>` と明示したときだけ有効 |
| 2 | **起動トークン。** 起動時に生成して stderr へ出す。params の `token` で毎回示す |
| 3 | **場所と種類。** 解決後のパスが `--root` の実体の配下にあり、拡張子が `.jin` であること |
| 4 | **symlink 拒否。** 書き先そのものが symlink なら拒む。書き込みは `os.replace`（リンクを辿らない） |

**`jin editor` は同じ口を、ユーザーが `--root` を書かずに開く。** 対象ファイルの
**親ディレクトリ**だけを root にし（`jin_cli.editor.editor_root`）、トークンは URL の
**フラグメント**（`#token=`）で渡す — フラグメントは HTTP 要求にも `Referer` にも載らないので、
`jin editor` が動かす静的サーバのアクセスログにも出ない。
**残存**: ブラウザの履歴には残り、同じページの JS からは読める。
信頼しないディレクトリの `.jin` を `jin editor` で開かないこと。

**残存**: Origin ヘッダは見ていない（pygls 2.1.1 の `start_ws(host, port)` は
`websockets` のサーバ生成オプションを露出しない・実測）。トークンで代替している。
同じマシンの別プロセスはポートに繋げるが、トークンを知らなければこの 2 本は通らない。

### 5.2 実行エンドポイント `POST /run`（Issue #34）

**これは LSP ではない。** `jin editor` が配る静的サーバ（同一オリジンの HTTP）に生えており、
**`jin lsp --ws` にこの口は無い**。要件書 §7.2 は「WebSocket で `jin run` からストリーム」と
書いているが、そこから意図的に逸れている（`delivery/20260904-1445-jin/decision-conformance.md`）。
理由は防御の強さで、下の段 2 がその核心である。

設計の正本は `docs/superpowers/specs/2026-09-08-editor-run-design.md`。実装は
`jin_cli.runserver`（子プロセスと tail と SSE）と `jin_cli.editor`（HTTP と検査）。

| 段 | 内容 |
|---|---|
| 1 | **`Origin` 検査。** 自分の origin 以外を拒む。`Origin` の無い要求（端末から自分で叩く）は通す |
| 2 | **カスタムヘッダのトークン。** `X-Jin-Token` で `jin/open` / `jin/save` と同じ起動トークンを要求し、`secrets.compare_digest` で比べる |
| 3 | **対象ファイルの固定。** 実行するのは `jin editor` に渡されたファイルだけ。クライアントはパスを指定できない |
| 4 | **同時 1 本。** 走っている間の 2 本目は 409 |
| 5 | **終了時の後始末。** `serve` の `finally` が走っている子を終わらせる（Issue #32 と同じ規律） |

**段 2 が「HTTP は ws より強い」の根拠のすべてである。** トークンを body や query に置くと、
`Content-Type` 次第で POST が CORS の **simple request** になり、preflight 無しに他オリジンの
ページから送れてしまう（応答は読めないが、実行は起きる）。カスタムヘッダを 1 つ要求すると
preflight（`OPTIONS`）が必須になり、こちらが CORS ヘッダを 1 つも返さない限り本要求は飛ばない。
`OPTIONS` には 403 を返す。

**残存**:

- **S1（任意コード実行）は残る。** 子は同じ権限で走り、`.jin` の `ref` を import する。
  `--model fake` はモデル呼び出しをネットワークに出さないだけで、import は行う。
  **信頼しないディレクトリの `.jin` を `jin editor` で開かないこと**（従来と同じ）
- トークンを握った攻撃者は、これまで `jin/save` で悪意ある `ref` を**書き込む**ところまでで、
  実行にはユーザーの手が要った。実行の口が開くことで**その連鎖が攻撃者だけで完結する**。
  それでも `jin editor` で常時有効にしているのは、「`.jin` を `jin editor` に渡す時点で
  そのディレクトリを信頼している」という前提に立つ判断である（人間確定）
- **キャンセルを持たない。** 実モデルでの長い実行は、終わるまでハンドラのスレッドを 1 本占有する
- 子は `python -P -m jin_cli.main run` で起こす。`-P` が無いと cwd が子の `sys.path[0]` に
  居座り、F-S-P2-101 の経路が復活する（`--resolve` の子が `-P` を付けるのと同じ理由）
- **prompt は `--` の後ろに置く**（argv のフラグ密輸を断つ）。prompt は利用者が打つ文字列で
  `-` で始まりうる。区切りが無いと typer がそれをオプションとして食う。いまの `jin run` では
  positional が足りなくなって exit 2 で落ちるだけだが（実測）、それは「たまたま `run` の
  引数の形がそうだから」であって防御ではない。`-` 始まりの prompt を**拒みはしない**
  （`--` で無害化できるので拒む必要が無く、拒むと「-1 と入力したら?」のような正当な
  問いかけが打てなくなる）

## 6. 応答の `stale`

`jin/model` と `jin/renderSvg` は `stale`（真偽値）を返す。真なら**現在のテキストが
壊れていて、直前の正常なモデル（last-good）で答えた**ことを表す（NFR-AVAIL-001 の
エラー回復・DP-COMMON-07）。黙って古い図を返すとエディタからは「編集が効かない」ように
見えるので、必ず伝える（NFR-FAIL-001「黙って落とさない」と同じ精神）。

`jin/applyOps` は last-good に当てない。ユーザーが見ていない版を書き戻すことになるためで、
構文エラー中の適用要求は JIN001 で拒む。

## 7. 実装状況

`jin_core.ops` に 19 オペレーションすべてを**純関数として実装済み**（`apply_op` / `apply_ops`）。
各オペレーションは逆オペレーションを返し、`apply_ops` は 1 つでも失敗したら何も適用しない。
`packages/jin-core/tests/test_ops.py` が全 19 件について
「適用 → 正準形テキスト → 再パース → 期待モデル」と「逆オペレーションで元に戻る（バイト一致）」を検証している。

**Phase 4 で LSP へ露出済み**（`jin/applyOps` / `jin/ops`）。
`packages/jin-lsp/tests/test_apply_ops_roundtrip.py` が同じ 19 件を**プロトコル越しに**回し、
サーバが返した `inverses` をそのまま送り返すと元の正準形テキストへバイト単位で戻ることを確認している。
**Phase 5 でエディタから使っている。** `apps/editor` は編集をすべて `jin/applyOps` に流し、
undo / redo はサーバが返した `inverses` を積むだけである（モデルの写しを積まない）。
schema にあってもオペレーションで到達できない欄（tool の `ref` / `builtin` / `circle`）は
`removeTool` + `addTool` の合成で書く。**20 個目を作らない**ことは
`tests/contract/test_editor_contract.py::test_the_editor_does_not_add_a_twentieth_operation` が固定する。
