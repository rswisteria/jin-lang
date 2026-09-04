# ADR-014: JIN050 の loop 上流規則は「すべての兄弟枝」を維持し、1 周目未定義は静的検査の対象外とする

> ⚠️ **AI 仮決定（ai_provisional）** — auto mode の仮判断であり人間確定ではない（DP-AUTOMODE-01）。PR レビュー後、`/decide` で approved / overridden に確定する。

- **ステータス**: proposed (ai_provisional)
- **日付**: 2026-09-04
- **決定者**: auto-decider
- **関連判断ポイント**: DP-JIN-JIN050-LOOP-SCOPE-01（aliases: 現仕様を維持し警告も出さない, 現仕様維持（model.md §5 の loop 行を変更しない））

## コンテキスト

Stage 5 correctness レビュー B-4（confidence 90）が、packages/jin-core/src/jin_core/semantic.py:196-200 は loop の祖先を辿るとき自分以外の全 step の部分木を可視にするため、loop steps: [X, Y] で X の rune が Y の out state を参照しても診断が出ないことを指摘した。1 周目には未定義の値である。実装は docs/spec/model.md §5 の表（祖先が loop のとき、すべての兄弟枝の部分木を含める）に準拠しており実装バグではないため、仕様上のリスクとして起票された。厳格化すると正当な書き直しループを誤検知する恐れがあり、緩いままだと要件書 §0 成功条件 3（LLM が jin check の診断だけで直しきる）が弱まる、というトレードオフの判断である。

## 選択肢

| 選択肢 | 採否 |
|---|---|
| 現仕様を維持する: docs/spec/model.md §5 の loop 行「祖先が loop のとき、すべての兄弟枝の部分木を含める」を変えず、新しい診断コードも警告も追加しない（1 周目に未定義でありうることは仕様上の既知の限界として明記する） | 採用 |
| 厳格化案: loop の祖先でも sequence と同じく『自分より前の兄弟枝の部分木のみ』を可視にする。実測ではバンドル済みの 2 例に影響しないが、後続兄弟の key を自 circle に out: false で宣言すれば通るため安全性が増えず、正当な前周参照に無意味な宣言を強いる | 不採用 |
| warning 級の新診断コードを追加する案: loop の後続兄弟枝の state を参照したときに warning を出す。loop の主要用途で恒常的に鳴り、LLM がバグでないものを直す方向に働く。番号の新規発明も禁止事項 | 不採用 |
| rune に任意キー構文（{key?} 相当）を導入し、厳格版と併用する案: 1 周目未定義を作者が明示できるようになるが、要件書 §2 と model.md §3.1 の rune 抽出規則の変更（言語仕様の拡張）であり、実装ラウンド 1 の範囲を超える | 不採用 |

## 決定

(1) 厳格化（loop を sequence と同じ『前の兄弟枝のみ』にする）は安全性を増やさない。厳格化しても、後続の兄弟枝の out state を読む loop step は、その key を自 circle の state[] に out: false で宣言すれば JIN050 を満たしてしまう（docs/spec/model.md §5 の第 1 行『自 circle の state[]（out の有無を問わない）は含める』、要件書 l.294『out: true 以外は静的検証(JIN050)とエディタ表示のための宣言』）。しかしこの宣言は実行時には何もせず、1 周目に key が未定義であることは変わらない。つまり厳格化は『前周の値を意図して読む正当な設計』と『1 周目に落ちるバグ』を区別できず、どちらにも同じ抜け道を与える。正当な作者には無意味な儀式を課し、バグのある作者には偽陰性を 1 手先に移すだけで、要件書 §0 成功条件 3（LLM が診断だけで直しきる）には寄与しない — 診断が促す『修正』が何も修正しないからである。(2) 1 周目の未定義は静的検査ではなく初期値の問題であり、v1 には表現手段がない。State には初期値のフィールドが無く（packages/jin-core/src/jin_core/model.py:75-78 は name / type / out のみ）、rune にも任意キー構文が無い（semantic.py:27 の抽出正規表現 {[A-Za-z_][A-Za-z0-9_]*} は ? を含まない・実測）。したがって jin-core の可視範囲をどう定義しても静的には閉じられない。(3) 起票時の懸念のうち『厳格化すると examples/pipeline.jin の Critic / Rewriter を誤検知する』は実測すると成立しない。loop の行だけを『前の兄弟枝のみ』に差し替えた semantic.py で examples/pipeline/pipeline.jin と examples/researcher/researcher.jin の全 circle の可視 state key を計算したところ、現行と完全に同一だった（Critic は {approved, draft, review}、Rewriter も {approved, draft, review}）。Critic の {draft} は loop の兄弟規則ではなく sequence 上流の Drafter から届いているためである。人間レビュー時にはこの事実に基づいて厳格化案を再評価できるよう記録しておく。厳格化を退ける理由は (1) の抜け道であって pipeline.jin が壊れるからではない。(4) warning 級の新コードを足す案も採らない。前周の値を参照するのは loop の主要な用途そのものなので、warning は正当なケースで恒常的に鳴り、LLM がバグでないものを『直す』方向に働く。これは成功条件 3 に逆行する。加えて新しいコード番号の発明は本判断の禁止事項である（T-002）。(5) 現行実装は仕様に準拠しており実装バグではない（semantic.py:196-200 と model.md §5 が一致）。confidence は medium とする: 起票時の根拠（pipeline.jin の誤検知）が実測で覆り、厳格化という実在の対案があるためである。

## 影響

docs/spec/model.md §5 と semantic.py の可視範囲計算は変更しない。追加作業は §5 loop 行への限界の注記と、規則を固定するテストの新設の 2 点。examples/ の 2 ファイルと既存 225 テストへの影響はない。1 周目未定義の .jin は jin check を通ってしまうが、本判断では代替の検出手段を定めない（v1 では静的に検出できないことを受容する）。State の初期値宣言または rune の任意キー構文が導入された時点で再評価する。厳格化を後から入れると、それまでに書かれた .jin が無効になる点も再評価時の判断材料になる。
