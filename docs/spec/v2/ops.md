# Jin v2 意味編集オペレーション(ops.md)

> 正典。設計書 §9 の実装仕様。v1 `docs/spec/ops.md` の運用(JSON Pointer で対象を指す /
> 失敗は診断コードで返す / 逆オペレーションを応答に含める / 合成で書けるものは足さない /
> `jin/applyOps` の往復 / `jin/ops` が一覧を返す)をそのまま使う。プロトコル(`jin/…` 6 種)は増えない。

## 1. 共通

- 各オペレーションは `{ "op": "<名前>", "target": "<JSON Pointer>", … }`。`target` は対象または挿入先の親
- 失敗は `{ "ok": false, "code": "JINxxx", "message", "pointer" }`。成功は新モデル・正準形テキストの差分・逆オペレーション列・診断
- 挿入系は `index`(省略時は末尾)。移動系は `to`(移動後の添字)
- 式を受ける欄は**文字列のまま**受け取り、構文検査(JIN201)と型検査(JIN202)は適用後の診断で返す(オペレーション自体は失敗にしない。エディタが赤バッジで示す)

## 2. 一覧(32 件)

<!-- machine-readable: v2-ops -->

| op | target | 引数 | 逆 |
|---|---|---|---|
| `setStage` | `/stage` | `stage` の欄の部分更新 | `setStage`(旧値) |
| `addForm` | `/forms` | `name`、`fields`、`index` | `removeForm` |
| `removeForm` | `/forms/i` | — | `addForm` |
| `setForm` | `/forms/i` | `name` / `fields` | `setForm`(旧値) |
| `addCircle` | `/circles` | `name`、`core` または `flow`、`index` | `removeCircle` |
| `removeCircle` | `/circles/i` | — | `addCircle`(全内容) |
| `setCore` | `/circles/i` | `core`(手順名) | `setCore`(旧値) |
| `addState` | `/circles/i/state` | `name`、`type`、`init`、`out`、`index` | `removeState` |
| `removeState` | `/circles/i/state/j` | — | `addState` |
| `setState` | `/circles/i/state/j` | `type` / `init` / `out` | `setState`(旧値) |
| `addSigil` | `/circles/i/sigils` | `name`、`kind`、`host` または `circle`+`rite`、`index` | `removeSigil` |
| `removeSigil` | `/circles/i/sigils/j` | — | `addSigil` |
| `moveSigil` | `/circles/i/sigils/j` | `to` | `moveSigil` |
| `addRite` | `/circles/i/rites` | `name`、`params`、`returns`、`steps`(既定 `[]`)、`index` | `removeRite` |
| `removeRite` | `/circles/i/rites/j` | — | `addRite`(全内容) |
| `setRiteSignature` | `/circles/i/rites/j` | `params` / `returns` | `setRiteSignature`(旧値) |
| `addStep` | ステップ列の pointer(`…/steps`、`…/then`、`…/else`) | `step`(1 ステップの JSON)、`index` | `removeStep` |
| `removeStep` | ステップの pointer | — | `addStep` |
| `moveStep` | ステップの pointer | `to`(同じ列の中の添字。列を跨ぐ移動は `removeStep` + `addStep` の合成) | `moveStep` |
| `setStep` | ステップの pointer | `do` 以外の欄の部分更新(`expr` / `cond` / `target` / `args` …) | `setStep`(旧値) |
| `wrapSteps` | ステップ列の pointer | `from`、`count`、`with`(`if` の `cond` または `loop` の `kind` と欄) | `unwrapSteps` |
| `unwrapSteps` | `if` / `loop` ステップの pointer | `branch`(`then` / `else` / `steps`。他の枝は捨てる) | `wrapSteps`(捨てた枝は `addStep` で復元) |
| `extractRite` | ステップ列の pointer | `from`、`count`、`name`(新しい手順名) | `removeRite` + `removeStep` + `addStep` × n |
| `setOn` | `/circles/i/boundary/on` | `event`、`rite`(同じ event があれば置換) | `setOn`(旧値)または `removeOn` |
| `removeOn` | `/circles/i/boundary/on/j` | — | `setOn` |
| `setGuard` | `/circles/i/boundary/guards`(追加)または `…/guards/j`(更新) | `assert`、`message` | `removeGuard` または `setGuard`(旧値) |
| `removeGuard` | `/circles/i/boundary/guards/j` | — | `setGuard` |
| `addDelegate` | `/circles/i/delegate` | `circle`、`index` | `removeDelegate` |
| `removeDelegate` | `/circles/i/delegate/j` | — | `addDelegate` |
| `setFlow` | `/circles/i` | `kind` / `steps` / `exit` | `setFlow`(旧値) |
| `setRoot` | `` (空 pointer) | `root` | `setRoot`(旧値) |
| `rename` | 名前を持つ要素の pointer(circle / form / form の欄 / state / sigil / rite / `let` / `params` / `loop.name`) | `name` | `rename`(旧名) |

<!-- /machine-readable -->

## 3. `rename` の参照追随

追随する範囲(v1 の ADR-013 の拡張):

| 対象 | 追随する参照 |
|---|---|
| circle | `root` / `flow.steps` / `delegate` / `summon.circle` / `emit.circle` / `transfer.circle` / 式の中の `陣名.key` |
| form | `state[].type` / `params[].type` / `returns` / `fields[].type` / `let.type`(`list<…>` の中も)/ 式の中のコンストラクタ `Name{` |
| form の欄 | 式の中の `.欄名`(**型が解決できた式だけ**。型が解決できない式は触らず、応答の `warnings` に pointer を列挙する) |
| state | 式の中の裸の識別子(自陣)/ `陣名.key`(他陣)/ `set.target` / `cast.into` / `flow.exit` |
| sigil | `cast.target` / 式の中の `名前.member` |
| rite | `core` / `on.rite` / `summon.rite` / `cast.target` |
| 局所(`let` / `params` / `loop.name`) | その手順(スコープ)内の式 |

式の中の参照は**構文解析して識別子の位置を得て**置換する(文字列リテラルの中は触らない)。構文エラーの式(JIN201)は触らず `warnings` に載せる。

## 4. コードアクションとの対応

| 診断 | オペレーション |
|---|---|
| JIN203(候補あり) | `setStep` / `setState` で識別子を置換(式内置換は `rename` と同じ機構の 1 回版) |
| JIN204 | `addSigil`(`kind: host`) |
| JIN210 / JIN211 | `extractRite` |
| JIN220 | `setState`(`out: true`) |
| JIN230 | `addSigil`(`input`) |
| JIN240 | `removeStep` |

## 5. エディタの操作との対応(設計書 §8)

- 手順環の小陣をダブルクリック → `focus` を `陣名/手順名` に(サーバ側の変更なし)
- 手順の図で環の空き位置をクリック → `addStep`(種別はパレットから)。ドラッグ → `moveStep`
- 範囲選択して「包む」→ `wrapSteps`、「抽出」→ `extractRite`
- 記憶環の四角をダブルクリック → `setState`(`out` の切り替え)
- 陣同士を結ぶ → `addDelegate` または `addSigil`(`summon`)

Phase 5 の実装(`apps/editor/src/v2/actions.ts` / `dispatch.ts`)では次のとおり:

- `addStep` は「空き位置をクリック」ではなく、ツールバーの「ステップを追加」(パレットで `do` を選ぶ。値は schema の判別共用体から引く)で、選択中のステップの**直後**か、選択 / focus 中の手順の**末尾**に入れる。既定値は参照先を捏造しない(式は空、`emit` / `transfer` の陣名は自陣)
- 「包む」「抽出」は**選択中の 1 ステップ**(`from` = その添字、`count` = 1)。範囲選択は残存(v2.1)
- ドラッグの並べ替えは**同じ列の中**だけ(`moveStep` / `moveSigil`)。列を跨ぐ移動と「陣同士を結ぶ」は残存
- 直接のオペレーションが無い欄は合成で書く(**33 個目を作らない**): 陣の `description` は `removeCircle` + `addCircle`、sigil の `host` / `circle` / `rite` は `removeSigil` + `addSigil`、`on` の `event` は `removeOn` + `setOn`、ステップの `do` は `removeStep` + `addStep`、`delegate` は `removeDelegate` + `addDelegate`。`apply_ops` の原子性(§6)で 2 件が 1 回で当たる
- `tests/contract/test_editor_contract.py` が `apps/editor/src/v2/` の op 名が §2 の 32 件に閉じることを固定する(v1 の 19 件とは別集合)
