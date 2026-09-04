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

## 5. Phase 4 で確定させる論点（本ラウンドでは決めない）

- **`jin/open` / `jin/save`**（DP-JIN-EDITOR-PROTOCOL-01・案 C・`ai_provisional`）:
  ws モードのエディタ専用の独自リクエストを 2 本追加する案が採られているが、
  同 DP の `constraints[]` により**リクエスト名は仮称であり、要件書 §6.3 の独自リクエスト 4 種への追加として
  人間の承認を得たうえで本文書で確定させる**。よって本ラウンドでは §2 の表に含めていない
- 逆オペレーションの表現形式のプロトコル露出と、適用失敗時のクライアントへの返し方（同 DP の `constraints[]`）

## 6. 本ラウンドでの実装状況

`jin_core.ops` に 19 オペレーションすべてを**純関数として実装済み**（`apply_op` / `apply_ops`）。
各オペレーションは逆オペレーションを返し、`apply_ops` は 1 つでも失敗したら何も適用しない。
`packages/jin-core/tests/test_ops.py` が全 19 件について
「適用 → 正準形テキスト → 再パース → 期待モデル」と「逆オペレーションで元に戻る（バイト一致）」を検証している。

LSP への露出（`jin/applyOps` / `jin/ops`）は Phase 4、エディタからの利用は Phase 5。
