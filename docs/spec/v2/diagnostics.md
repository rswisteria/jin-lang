# Jin v2 診断コード(diagnostics.md)

> 正典。設計書 §6 の実装仕様。v1 `docs/spec/diagnostics.md` の運用(段階: 構文 → スキーマ → 意味。
> 前段が通らなければ後段は出さない。JSON 形式は LSP Diagnostic と 1:1。hint は具体値)を継承する。
> v1 の「診断コードは増やさない」は v1 の意味検査(JIN0xx)についての規則で、v2 は **JIN2xx** の
> 番号帯を別に持つ。`tests/spec/test_v2_spec_consistency.py` が §1 の表を設計書 §6 と突き合わせる。

## 0. v1 と共有する番号

意味が同じものは同じ番号を使う。メッセージ本文は v2 の語彙で出す。

| コード | v2 での内容 |
|---|---|
| JIN001 | JSON 構文エラー |
| JIN002 | スキーマ違反(v2 のスキーマ。`version: 2` の分岐) |
| JIN010 | 名前の重複(circle / form / state / sigil / rite / 局所 / `on` の event / 組み込み `Pointer` との衝突) |
| JIN011 | 未解決の参照(`root` 以外: `core` / `flow.steps` / `summon` / `on.rite` / `delegate` / `transfer` / `emit.circle` / `cast.target` / 型文字列が指す型紙) |
| JIN012 | 参照が循環している(`flow.steps` / `delegate` / `summon` / 型紙の入れ子) |
| JIN013 | circle が複数の親を持つ(`flow.steps` の入次数 2 以上) |
| JIN020 | `state` / `sigils` / `rites` が 12 を超えた |
| JIN022 | `core` と `flow` の両立、または両方欠落 |
| JIN060 | `root` が存在しない circle を指す |

## 1. v2 固有(JIN2xx)

<!-- machine-readable: v2-diagnostics -->

| コード | 重大度 | 内容 | 修正ヒント |
|---|---|---|---|
| JIN201 | error | 式の構文エラー | 期待トークンと式内の位置 |
| JIN202 | error | 型不一致 | 期待型と実際の型 |
| JIN203 | error | 式内の未定義識別子 | 候補名(編集距離)。他陣の非公開 state なら `out: true` を提案 |
| JIN204 | error | 道具環に無い名前空間を使った | `addSigil` のコードアクション |
| JIN205 | error | 未知のホスト能力メンバ / 引数の数の不一致 / 未知のアセット名 / 未知のキー名 | カタログのメンバ一覧 |
| JIN210 | error | 手順のステップ数が 12 を超えた | 「手順に抽出」のコードアクション |
| JIN211 | error | `if` / `loop` の入れ子が 3 段を超えた | 同上 |
| JIN212 | error | summon 先の手順が `wait` を含む | `emit` に置き換える |
| JIN213 | error | `break` が `loop` の外にある / `return` の値が `returns` の無い手順にある | |
| JIN220 | error | `flow.exit` が公開 state 以外を参照している | `out: true` を提案 |
| JIN221 | error | `on` の手順の引数がイベントの形と合わない | 期待する `params` |
| JIN230 | error | `input` を道具環に持たない陣が `key` / `pointer` イベントを受けている | `addSigil` |
| JIN240 | warning | 到達不能ステップ | 削除 |
| JIN250 | error | `state[].init` が定数式でない | |

<!-- /machine-readable -->

## 2. 各コードの補足

- **JIN202** はひとまとまりの型検査で、次を含む: 演算子の型規則(`expr.md` §2)、`set` / `let` / `into` の代入先と値、`cast` の引数、`return` と `returns`、`if.cond` / `loop.while.cond` / `wait.until` / `guards.assert` / `flow.exit` が bool でない、`loop.each.in` が list でない、`loop.count.times` / `wait.ticks` が num でない、型紙コンストラクタの欄の過不足、空 list リテラルの型が決まらない、式の中で戻り値の無いメンバ / summon / agent を呼んだ
- **JIN203** は `陣名.key` で `key` が非公開のとき、自陣を陣名で指したとき、型紙に無い欄を指したときも含む
- **JIN210** は手順直下の `steps` の個数だけを数える。`if.then` / `if.else` / `loop.steps` の個数はそれぞれ別に 12 まで(同じ JIN210)
- **JIN211** の深さは手順直下を 0 とし、`if` / `loop` の中が +1。深さ 3 の中に `if` / `loop` を置いた時点でエラー(そのステップの pointer で出す)
- **JIN212** は「`wait` を直接含む」だけでなく、自陣の `cast` を通じて `wait` に到達する手順を summon したときも含む(到達可能性は静的に閉包を取る)
- **JIN221** は「手順の `params` がイベント引数の前方部分」の規則(`model.md` §3.5)で判定する。`rite` が存在しないのは JIN011。`agent` の sigil を持つ陣の `message` の手順は `(name: str, id: num, text: str)` の前方部分(v2.1・runtime.md §11)
- **JIN240** は `return` / `finish` / `break` / `transfer` の後に同じ列に残るステップ。`if` の両枝が抜けるときの後続も対象。warning なので `jin check` の exit は 0
- **JIN250** の定数式は `model.md` §5.3

## 3. fixture

`tests/fixtures/errors/v2/JIN2xx_*.jin` に各コード 1 つ以上。**対応コードをちょうど 1 つだけ出す**(v1 と同じ規律)。共有番号(§0)の v2 側の fixture も `tests/fixtures/errors/v2/JIN0xx_*.jin` に置く(v1 の fixture とは別ディレクトリ。`jin check` は version で振り分けるので混ざらない)。

## 4. 診断の JSON(v1 §5 と同じ形)

```json
{"file": "paddle.jin", "pointer": "/circles/1/rites/2/steps/0/cond",
 "range": {"start": {"line": 27, "col": 44}, "end": {"line": 27, "col": 53}},
 "code": "JIN203", "severity": "error",
 "message": "識別子 'padle' は定義されていません",
 "hint": "近い名前: paddle"}
```

`range` は式内の区間を JSON 文字列の中の位置に写したもの(`expr.md` §6)。式全体を指すときは文字列リテラル全体。
