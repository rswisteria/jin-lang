# Jin モデル仕様（model.md）

> 正典。要件書 `jin-requirements.md` §2 の実装仕様。LLM（Claude Code）が `.jin` を書くときの参照資料。
> 意味モデルの**唯一の真実**は `packages/jin-core/src/jin_core/model.py` の Pydantic 定義であり、
> `schemas/jin.schema.json` はそこから生成される。本文書と Pydantic 定義が食い違った場合は Pydantic 定義が優先する。

## 0. この文書の読み方（機械可読の約束）

`tests/spec/test_spec_consistency.py` が本文書と `jin-requirements.md` を突合する。
機械が読む表・箇条書きは直前に `<!-- machine-readable: <ID> -->` マーカーを置く。
**マーカー付きブロックの書式を変えるとテストが落ちる。** マーカーの無い散文は自由に書いてよい。

## 1. ファイル形式

- 拡張子は `.jin`、中身は JSON（UTF-8）。`.json` にしないのは Claude Code の LSP ルーティングが拡張子単位で、`.json` を奪うと他の JSON ファイルと衝突するため
- v1 は**単一ファイル**。`import` は無い
- 未知のキーはスキーマ違反（`additionalProperties: false` / JIN002）。将来拡張は `version` を上げる
- 型は**厳格**に判定する（Pydantic strict モード）。`"max": "3"` のような文字列→整数の暗黙変換は行わず JIN002 とする

## 2. ルートオブジェクト

<!-- machine-readable: root-keys -->

| キー | 必須 | 型 | 意味 |
|---|---|---|---|
| `$schema` | 必須 | string | スキーマの URL。正準形では先頭固定 |
| `version` | 必須 | integer（`1` のみ） | 形式バージョン。正準形では 2 番目固定 |
| `root` | 必須 | string | エントリポイントとなる circle 名。生成モジュールの `root_agent` になる |
| `circles` | 必須 | array of Circle | 陣の定義。配列順が描画順（12 時から時計回り） |

<!-- /machine-readable -->

## 3. Circle

circle は 2 種類ある。**核あり**（`core` を持つ → `LlmAgent`）と **核なし**（`flow` だけ → workflow agent）。
両方持つ・両方無いのは JIN022 エラー。

<!-- machine-readable: circle-keys -->

| キー | 必須 | 型 | 既定値 | 意味 |
|---|---|---|---|---|
| `name` | 必須 | string | — | ファイル内一意。名前が ID |
| `core` | 任意 | string | なし | モデル文字列。そのまま `LlmAgent.model` に渡す |
| `description` | 任意 | string | なし | `LlmAgent.description` |
| `instruction` | 任意 | Instruction | なし | 指示。`{ "rune": "..." }` |
| `tools` | 任意 | array of Tool | `[]` | 道具。circle 内で `name` 一意 |
| `delegate` | 任意 | array of string | `[]` | サブ陣への委譲（circle 名）。`LlmAgent.sub_agents` |
| `state` | 任意 | array of State | `[]` | セッション状態の宣言。circle 内で `name` 一意 |
| `flow` | 任意 | Flow | なし | 核なし circle の制御構造 |
| `boundary` | 任意 | Boundary | なし | 境界環（guards / await） |

<!-- /machine-readable -->

キーの並びは上表の順で固定する（正準形のキー順 = スキーマ定義順）。

### 3.1 Instruction

| キー | 必須 | 型 | 意味 |
|---|---|---|---|
| `rune` | 必須 | string | 指示テキスト。`{state_key}` テンプレートは ADK へそのまま渡す。SHA-256 が装飾（識別紋章）の決定的な種になる |

`{key}` の抽出規則: 左から 1 文字ずつ走査し、`{{` と `}}` はリテラルのエスケープとして読み飛ばす。
それ以外の `{` に続く `[A-Za-z_][A-Za-z0-9_]*` が `}` で閉じられていれば state key 参照とみなす。
したがって `"{a}}"` は「参照 `a` + リテラルの `}`」である。解決できない key は JIN050。

> **未確認**: この `{{` / `}}` エスケープ規則は **Jin 側の規則**である。ADK 2.8.0 の
> `instruction` が同じエスケープ規則を持つかは `delivery/20260904-1445-jin/adk-api-probe.md` に
> 実測が無く、**確認できていない**。`rune` を ADK へそのまま渡すため、ADK 側のテンプレート解釈が
> 異なる場合は `{{` を含む rune の挙動が Jin の読みと食い違いうる。
> Phase 2（`jin-adk`）で ADK の実測を取り、この段落を実測に置き換えること。

### 3.2 Tool（判別共用体）

`kind` による判別共用体。3 種とも `name` は**必須**（circle 内一意の ID として `boundary.await` /
意味オペレーション `moveTool` / JSON Pointer の安定性に使う）。

<!-- machine-readable: tool-kinds -->

| kind | 追加キー | 型 | ADK 対応 |
|---|---|---|---|
| `tool` | `ref` | string（`module.path:callable`） | `FunctionTool` |
| `builtin` | `builtin` | string | 組み込みツールのインスタンス |
| `summon` | `circle` | string（circle 名） | `AgentTool` |

<!-- /machine-readable -->

キー順は `name`, `kind`, その種別の追加キー。

### 3.3 State

| キー | 必須 | 型 | 既定値 | 意味 |
|---|---|---|---|---|
| `name` | 必須 | string | — | state key。circle 内一意 |
| `type` | 必須 | string | — | 型の表示名。v1 では意味検査に使わず、エディタ表示と読み手のための宣言 |
| `out` | 任意 | boolean | `false` | `true` のものだけが `output_key` になる |

`out: false` は既定値なので正準形では出力しない。

1 つの circle に `out: true` の state が 2 件以上あった場合、ADK の `LlmAgent.output_key` は単一値なので
マップできない。v1 では**診断コードを増やさず**、Phase 2（`jin-adk`）のコード生成時エラーとして落とす
（NFR-FAIL-001「黙って落とさない」。DP-JIN-SEMANTIC-GAPS-01 が追加を認めた新規コードは 2 件のみで、
この論点は同 DP の対象外であるため勝手に 3 件目を採番しない）。

### 3.4 Flow

| キー | 必須 | 型 | 意味 |
|---|---|---|---|
| `kind` | 必須 | `sequence` \| `parallel` \| `loop` | 制御構造 |
| `steps` | 必須 | array of string | circle 名のみ |
| `max` | 任意 | integer（1 以上） | `loop` のみ。`LoopAgent.max_iterations` |
| `exit` | 任意 | FlowExit | `loop` のみ。`{ "key", "equals" }` |

`loop` は `max` と `exit` の少なくとも一方が必要（JIN030）。

`max` / `exit` を `sequence` / `parallel` に書くのは**スキーマ違反**であり、**段 2 で JIN002 として落とす**
（`docs/spec/diagnostics.md` §1 の段。実装は `jin_core.model.Flow` の model_validator）。
黙って無視すると ADK 生成時に捨てられ、書いた人の意図が消える
（要件書 §3.3「ADK に対応物のない Jin 構造はコンパイル時エラー。黙って落とさない」）。
なおこの条件は「`kind` の値に依存するキーの可否」なので `schemas/jin.schema.json`
（公開契約・Pydantic から生成）には現れない。内部検証は Pydantic 一本である（ADR-006）。

`exit.key` が可視な state に解決できない場合は JIN011（`docs/spec/diagnostics.md` §4）。

FlowExit:

| キー | 必須 | 型 | 意味 |
|---|---|---|---|
| `key` | 必須 | string | 比較する state key |
| `equals` | 必須 | boolean \| integer \| number \| string | 等値比較の右辺。v1 は等値比較のみ |

### 3.5 Boundary

| キー | 必須 | 型 | 既定値 | 意味 |
|---|---|---|---|---|
| `guards` | 任意 | array of Guard | `[]` | コールバック |
| `await` | 任意 | array of string | `[]` | 人の介入点。値は自 circle の tool 名 |

Guard:

<!-- machine-readable: guard-on-values -->

| `on` の値 | ADK コールバック引数 |
|---|---|
| `before_agent` | `before_agent_callback` |
| `after_agent` | `after_agent_callback` |
| `before_model` | `before_model_callback` |
| `after_model` | `after_model_callback` |
| `before_tool` | `before_tool_callback` |
| `after_tool` | `after_tool_callback` |

<!-- /machine-readable -->

`ref` は `module.path:callable` 形式のみ。インライン Python は不可。

### 3.6 文字列の制約

全ての文字列フィールドに**長さと文字種の上限**がある。違反は**段 2（スキーマ）の JIN002**
（`docs/spec/diagnostics.md` §1 の段）。実装は `packages/jin-core/src/jin_core/model.py` の
`MAX_IDENT_LENGTH` / `MAX_TEXT_LENGTH` / `MAX_URL_LENGTH` と `_reject_bad_chars`。

<!-- machine-readable: string-constraints -->

| 種別 | 対象フィールド | 最大長 | 許す制御文字 |
|---|---|---|---|
| 識別子 | `root` / `circles[].name` / `core` / `tools[].name` / `ref` / `builtin` / `circle` / `state[].name` / `type` / `flow.steps[]` / `flow.exit.key` / `delegate[]` / `boundary.await[]` / `guards[].ref` | 128 | なし |
| 自由記述 | `description` / `instruction.rune` / `flow.exit.equals`（文字列のとき） | 65536 | `\n` `\r` `\t` のみ |
| URL | `$schema` | 2048 | なし |

<!-- /machine-readable -->

どの種別でも**孤立サロゲート（U+D800〜U+DFFF）は受け付けない**。UTF-8 に符号化できず、
`jin fmt` の書き出しが落ちるためである。

識別子で制御文字を一切許さないのは、診断の 1 行が
`file:line:col: severity CODE: message` という形だからである。名前に改行が入れば偽の診断行を作れ、
ESC が入れば端末の表示を消せる。自由記述で `\n` `\r` `\t` だけを許すのは、rune の本文に改行が要るため。

上限値の決定根拠は `delivery/20260904-1445-jin/decision-conformance.md` §2.7。
**上位要件書に規定が無い値**であり、人間の承認待ちである（Q-JIN-IMPL-09）。

### 3.7 `schemas/jin.schema.json` が表現しない制約

`schemas/jin.schema.json` は Pydantic 定義から生成した**公開契約**であり、
**形と `maxLength` しか表現しない**。次の制約はスキーマに現れないので、
**スキーマに適合することは必要条件であって十分条件ではない**。判定の正本は `jin check` である。

<!-- machine-readable: schema-gaps -->

| スキーマに現れない制約 | 実際の検出 | 段 |
|---|---|---|
| §3.6 の文字種（制御文字・孤立サロゲート） | JIN002 | 段 2 |
| `max` / `exit` は `kind: loop` のときだけ許す（§3.4） | JIN002 | 段 2 |
| 同一オブジェクト内のキーの重複（§6） | JIN001 | 段 1 |
| 入れ子の深さ上限（64 段） | JIN001 | 段 1 |
| 名前の一意性・参照の解決・要素数の上限・rune の `{key}` | JIN010 / JIN011 / JIN012 / JIN013 / JIN020 / JIN022 / JIN030 / JIN031 / JIN040 / JIN050 / JIN060 / JIN070 | 段 3 |

<!-- /machine-readable -->

これらを JSON Schema の `pattern` や `if` / `then` で表現していないのは、
**Pydantic の `AfterValidator` / `model_validator` が JSON Schema へ書き出されないため**である
（ADR-006「内部検証は Pydantic 一本」）。表現できていないものを表現できているかのように
書かないこと（要件書 §0 成功条件 3 が求めるのは「スキーマと診断の出力だけで直しきれる」ことであり、
**診断の側でこれらを具体的な hint つきで返す**ことで満たす）。

## 4. 参照グラフと親子関係

Jin の circle 間には 3 種の参照辺がある。**このうち親子（containment）を作るのは 2 種だけ**である。

<!-- machine-readable: reference-edges -->

| 参照元 | 参照先 | 親子辺か | 根拠 |
|---|---|---|---|
| `flow.steps[]` | circle | **親子辺** | workflow agent の `sub_agents` になる |
| `delegate[]` | circle | **親子辺** | `LlmAgent.sub_agents` になる |
| `tools[kind=summon].circle` | circle | 親子辺ではない | `AgentTool(agent=X)` は X の `parent_agent` を設定しない |

<!-- /machine-readable -->

制約:

- 親子辺の入次数が 2 以上の circle は JIN013（多重親）。ADK の `BaseAgent.parent_agent` が単一値であるため
- 3 種すべての参照辺からなる有向グラフに閉路があれば JIN012（循環参照）。summon が親子辺でなくても、
  レンダラの入れ子展開と `jin build` の相互参照は閉路で停止しないため参照辺として数える

## 5. JIN050 の「上流」の定義

`rune` 内の `{key}` は「自 circle または flow 上流 circle の state」で解決する。**上流**を次のとおり定義する。

<!-- machine-readable: upstream-rule -->

| 位置関係 | 上流に含めるか | 根拠 |
|---|---|---|
| 自 circle の `state[]`（`out` の有無を問わない） | 含める | 自分で宣言した key |
| 祖先が `sequence` のとき、自分の枝より**前**にある兄弟枝の部分木 | 含める | 直列なので必ず先に実行される |
| 祖先が `loop` のとき、**すべての**兄弟枝の部分木 | 含める | 反復するため 2 周目以降はどの兄弟も先に実行されうる |
| 祖先が `parallel` のとき、兄弟枝 | 含めない | 実行順序の保証がない |
| `delegate` の親 circle の `state[]` | 含める（親 → 子の向きのみ） | 親が動いてから transfer される |
| `summon`（AgentTool）の呼び出し元 circle の `state[]` | 含めない | AgentTool は独立した呼び出しで、セッション state の可視性を Jin は保証しない |

<!-- /machine-readable -->

「部分木」とは、その circle 自身と、そこから親子辺で到達できる全 circle を指す。

## 6. JSON Pointer

- ファイル内の位置・描画要素（`data-jin`）・診断・トレースイベントを結ぶ**唯一の鍵**
- 記法は RFC 6901。ルート文書は空文字列 `""`
- 例: `/circles/0/tools/2`、`/circles/0/boundary/await/0`
- `pointer→range 対応表` は**ソーステキストから**作る。したがって表の pointer 集合は
  「ソースに実在するキー・要素」であり、モデル JSON（既定値のキーを省く）の pointer 集合はその**部分集合**になる
- **1 つの pointer は 1 つの値だけを指す**。RFC 8259 は同一オブジェクト内の重複キーの扱いを未定義に
  しているが、Jin は**重複キーを段 1 の構文エラー（JIN001）として落とす**。後勝ちにすると
  同じ pointer に 2 つの range が対応し、この項が成り立たなくなる
- 正準形のファイルではソースとモデルの pointer 集合が一致する。`jin fmt` を通したファイルなら
  「表の全 pointer がモデルに解決できる」が成り立つ

## 7. 正準形（canonical form）

`model → text` は関数である。`jin fmt` とエディタの保存は同じバイト列を出す。

<!-- machine-readable: canonical-rules -->

| # | 規則 |
|---|---|
| 1 | インデントは 2 スペース |
| 2 | キー順はスキーマ定義順（本文書 §2 / §3 の表の順） |
| 3 | 配列は宣言順を保持する |
| 4 | 末尾に改行を 1 つ置く |
| 5 | 非 ASCII はエスケープしない（UTF-8 でそのまま出す） |
| 6 | `$schema` と `version` は先頭固定 |
| 7 | 省略可能なキーは、値が既定値のときは出力しない（`"out": false` は書かない） |

<!-- /machine-readable -->

冪等: `fmt(fmt(x)) == fmt(x)`。意味保存: `model(fmt(x)) == model(x)`。

エスケープは JSON の最小エスケープ規則に従う: `"` `\` と U+0000〜U+001F のみをエスケープし、
制御文字のうち `\b` `\f` `\n` `\r` `\t` は 2 文字表記、それ以外は `\uXXXX`。
U+007F（DEL）および U+0080 以上はエスケープしない。サロゲートペア（BMP 外の文字）はそのまま出す。

> **受理範囲との関係**（§3.6）: モデルは C0 制御文字（`\n` `\r` `\t` を除く）・U+007F・C1・
> 孤立サロゲートを**受け付けない**。したがって正準形の出力にこれらが現れることはなく、
> 実際に出るエスケープは `"` `\` `\n` `\r` `\t` だけである。
> writer 側の規則をそれより広く定めてあるのは、`jin_core.canonical.dumps` を
> モデル検証を通さずに直接呼ぶ経路（他モジュールからの利用）でも壊れないようにするため。
> **孤立サロゲートだけは writer も明示的に拒む**（UTF-8 に符号化できないため）。

## 8. 関連

- `docs/spec/adk-mapping.md` — Jin 要素 → ADK クラスの対応
- `docs/spec/diagnostics.md` — 診断コード一覧
- `docs/spec/layout.md` — 決定的レイアウトと `data-jin` 契約
- `docs/spec/ops.md` — 意味編集オペレーション
- `schemas/jin.schema.json` — Pydantic から生成した JSON Schema（正典）
