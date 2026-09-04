# fix-now 修正ラウンド 1 — 指示書（親が作成 / DP-REVIEW-FIXLOOP-01）

対象: 実装ラウンド 1（Jin Phase 0 + Phase 1）の Stage 5 レビュー finding
実施者: `impl-p01`（同一 implementer・ラウンド 1）
完了確認: **同一観点の code-reviewer による再レビューで defect-gone を確認するまでクローズしない。**
「直しました」という報告は完了根拠にならない（DP-IMPL-VERIFIED-01 / 偽 green 防止）。

## 0. 前提と鉄則

- レビュー生出力は `delivery/20260904-1445-jin/code-review-raw/{correctness,conventions,wiring,security}.md`。
  **finding の本文はこのファイルを読むこと**（本指示書は ID と優先順位のみを示す）。
- finding 総数 86 件（correctness 33 / conventions 21 / security 19 / wiring 13）。
  **テストが 225 件緑の状態で検出されたもの**である。「テストが通っている」ことを反論に使わない。
- **各修正には「その欠陥を捕まえるテスト」の追加までを含める。** レビューは大半の finding について
  「テストが素通りした理由」を書いている（fixture が 1 要素だった / 最初から boundary を持っていた /
  `UnexpectedCharacters` 経路のテストが 0 件だった 等）。テストを足さない修正は未完了とみなす。
- **本指示書に挙げた finding のみを直す。** 無関係なリファクタを混ぜない。
- **テストを消す・`xfail` を付ける・アサーションを緩めることは禁止。**
- **git commit / push はしない。** コミットは親が再レビュー通過後に行う。
- finding が誤検知だと考える場合も、修正の代わりに severity へ反論しない。見解は
  `delivery/20260904-1445-jin/implement-ledger.md` に 1 行 append（行頭に `[R1][<finding ID>]`）し、
  修正できる範囲は修正する。裁定は親のブレーカー経路でのみ行う。

## 1. 修正順序（この順に進める）

依存関係と「後続 Phase が乗る土台か」で並べてある。

### (1) security — fail-closed と ws 到達性（Phase 4 が LSP を ws で公開する前に閉じる）

| ID | 内容 | 備考 |
|---|---|---|
| **S2** | `except Exception` が `SystemExit` を捕まえず、`ref` 先の `sys.exit(0)` で `jin check --resolve` が**出力ゼロ・exit 0** になる | **親が再現確認済み**。CI の赤が緑になる |
| **S1** | `--resolve` が任意モジュールを import し任意コード実行になる | 下記の構造的修正を採用すること |
| **S8** | `rename` の新名が `re.sub` の置換テンプレートとして解釈され、不整合モデル生成と未捕捉 `re.PatternError` | **親が再現確認済み** |
| **S9** | `rename` だけ circle index の範囲検査が無く未捕捉 `IndexError` | **親が再現確認済み**（`setCore` は正しく `OpError`） |
| **S4** | 未捕捉 `RecursionError` 3 箇所（`parser._walk` / `semantic._find_cycle.visit` / `semantic._subtree_states.walk`） | 明示的な深さ上限を設けて JIN 診断として返す |
| **S3** | `levenshtein` によるアルゴリズム DoS（88 KB の正当な `.jin` で 108 秒） | **Phase 4 の LSP は打鍵ごとに `check_text` を呼ぶ**。候補数上限・名前長上限・banded 早期打ち切り |
| **S10** | `isdigit()` と `int()` の不一致 4 箇所（`"²"` は `isdigit()` True だが `int()` は ValueError） | `str.isascii() and str.isdigit()` に置換 |
| **S6** | 人間向け出力への ANSI エスケープ / 偽診断行インジェクション | `--json` 経路は安全（実測済み）。人間向け出力側を対処 |
| **S5** | I/O 例外がそのまま抜けて情報開示つきクラッシュ | `pretty_exceptions_show_locals=False` の明示 + I/O 例外を診断へ落とす |
| **S11** | `jin fmt` の書き戻しが非原子的 | 一時ファイル + `os.replace` |
| **S12** | `jin fmt` がシンボリックリンクを追って対象ディレクトリ外に書き込む | `path.is_symlink()` でスキップ |
| **S13** | モデルの文字列に文字種・長さの制約が一切無い | S6 / S3 / S10 の共通の根。**具体的な上限値は要件書に無いので、決めたら根拠を `decision-conformance.md` に書くこと** |
| **S14** | `decision-conformance.md` の「反映済み」記述と実装の乖離 | DP-COMMON-07「`jin_core` は状態を持たない純関数」が `resolve=True` で不成立。**対照表の記述を実態に合わせて訂正する**（実装を変えて成立させる場合はその旨を書く） |
| **S19** | （`security.md` 参照） | |

**S1 の構造的修正（採用決定・security reviewer の案）**:
`resolve` を `bool` フラグではなく **`RefResolver` プロトコルの注入**にする。実際に import する
`ImportResolver` は **`jin_cli` 側にのみ置き、`jin_core` からは import しない**。`jin-lsp` は
`jin_core` にしか依存しないため、ws サーバのコードパスから `ImportResolver` に到達できなくなる。
**import-linter に forbidden contract を 1 行足して機械的に落とせるようにすること**（コメントでの約束は不可）。
`--resolve` の危険性を `README.md` と `CLAUDE.md` に明記する（現在どちらにも記述が無い）。

### (2) correctness — 逆オペレーション契約（要件書 §9 と 成功条件 5 に直結）

| ID | 内容 |
|---|---|
| **A-3** | `moveTool` / `setState` / `removeGuard` が pointer の経路セグメント（`tokens[2]`）を検証せず別の配列を書き換える。**親が再現確認済み**（`moveTool` に state の pointer → tools が並べ替わる） |
| **A-1** | `toggleAwait` の逆オペレーションが配列順を復元しない（`["t1","t2","t3"]` → 逆適用で `["t2","t3","t1"]`） |
| **A-2** | `setGuard` / `toggleAwait` が `boundary` を新規作成し逆オペレーションで消さない。正準形に `"boundary": {}` が増え、**ファイル→モデル→ファイルのバイト同一（成功条件 5）が undo 経路で崩れる** |
| **A-4** | `_rename` の深さ検査が空振り（期待深さに実際の長さを渡している） |

**必須の回帰テスト**（これが無い修正は未完了）:
- `toggleAwait` の逆適用を **await 2 要素以上**で検証する
- `setGuard` / `toggleAwait` を **`boundary` を持たない circle** に適用し、逆適用で**正準形テキストがバイト一致**することを検証する
- **全 ops ハンドラ**について、誤った配列を指す pointer を渡すと `OpError` になることを検証する

### (3) correctness — パーサ・正準形・CLI

| ID | 内容 |
|---|---|
| **C-1** | 字句レベルのエラーで常に「入力の終わり」と誤報し、hint が lark の終端名そのまま。**要件書 §5「hint は LLM がそのまま編集に使うので具体的な値にする」と 成功条件 3 に直撃**。`UnexpectedCharacters` は `.token` ではなく `.char` を持つ |
| **C-2** | JSON の重複キーが黙って後勝ちになり、先に出たキーの range が失われる |
| **D-1** | `jin fmt` がロンサロゲートを含むファイルで未捕捉クラッシュ |
| **D-2** | CRLF ファイルが `jin fmt --check` を「差分なし」で通過するが実バイトは正準形と不一致（NFR-DET-002 に影響） |

**必須の回帰テスト**: `UnexpectedCharacters` 経路（現在テスト 0 件）、JSON 重複キー、サロゲート、CRLF。

### (4) correctness — 意味検査

| ID | 内容 |
|---|---|
| **B-1** | JIN013 が「同じ親が 2 回参照した」ケースを多重親として誤報（`circle 'A' が 2 個の親を持っています: P / P`）。検出自体は妥当なのでコードとメッセージを適切化 |
| **B-2** | `flow.exit.key` の未解決参照に診断が無い。`ops.py` の rename は exit.key を参照として追随させており、システム内で「参照かどうか」の扱いが一貫していない |
| **B-3** | `max` / `exit` が `sequence` / `parallel` でも黙って通る。`docs/spec/model.md` §3.4 は「loop のみ」と明記。**要件書 §3.3「ADK に対応物のない Jin 構造はコンパイル時エラー。黙って落とさない」に抵触** |
| **B-8** | rune の `{a}}` が state key 参照として認識されず JIN050 をすり抜ける（`model.md` §3.1 の規則では「参照 a + リテラル `}`」） |

### (5) docs/spec の正典側の誤り（Phase 2〜6 が参照するので早く直す）

**S-1 〜 S-6**（`correctness.md` の S 節）。仕様書 5 本自体の誤り。
**`tests/spec/test_spec_consistency.py` の突合テストがこれらを検出できるよう強化すること**
（検出できていないから残っている）。

> **S-1 は (2) の A-1 / A-2 と同じ欠陥の仕様側**である（high / confidence 90）。
> `docs/spec/ops.md` §2 の逆オペレーション表は `toggleAwait`（配列順が戻らない）と
> `setGuard`（boundary を消す責務が無い）の**復元不能を仕様として追認しており**、
> 同じ文書 §1 の「クライアントが逆 op 列を保持して undo する」と両立しない。
> **コードだけ直して ops.md を放置すると、仕様がバグを是認したまま残る。**
> A-1 / A-2 の修正と S-1 の修正は必ずセットで行い、突合テストで両者の整合を固定すること。

> S-2（`diagnostics.md` の優先順位表に `flow.exit.key` が無い）は (4) の **B-2** と、
> S-3（`model.md` が max/exit をどの段で落とすか未記載）は (4) の **B-3** と、
> S-4（`model.md` の pointer 表の主張が重複キーで崩れる）は (3) の **C-2** と同じ欠陥の仕様側。
> いずれもコードと仕様を同時に直すこと。
>
> S-6（`layout.md:55` の星形多角形の説明）は**結論 k=1 は正しく、根拠の説明だけが誤り**
> （「2 と 3 は gcd≠1」の 3 は `2*3 < 6` が偽なので探索範囲外）。説明文のみ修正する。
> S-5（rune の `{{ }}` エスケープと「ADK へ透過」の両立）は **ADK 側に同じエスケープがある証拠が
> `adk-api-probe.md` に無い**。証拠なく「透過する」と書かないこと。確認できなければ
> 仕様に「未確認」と明記し `implement-ledger.md` に 1 行残す（捏造しない・T-002）。

### (6) wiring — CI と拡張性（Phase 2 で新パッケージを足す前に）

| ID | 内容 |
|---|---|
| **W-01** | CI が `uv.lock` の整合を保証しない。`uv sync --frozen` は stale lock を素通りし、後続の裸 `uv run` が lock を書き換える。**親が再現確認済み**。job env に `UV_LOCKED: "1"` |
| **W-03** | `testpaths` のハードコードで新パッケージのテストが収集されない。**親が再現確認済み**。`packages/*/pyproject.toml` をディスク列挙して `testpaths` と `root_packages` の網羅を assert する契約テストを追加 |
| **W-04** | スキーマドリフト検出の 2 重の網が独立していない（CI ステップがテストの前にツリーを書き換える） |
| **W-06** | CI の Python バージョンが浮いている。**親の実測でローカル `.venv` は 3.14.6**（design.yaml の記録は 3.13.1） |
| **W-02** | import-linter の自己テストが実契約ではなくテスト内の手書き複製を検証している（**confidence 85 だが親が fix-now に格上げ**: 実契約が typo で常に KEPT になっても green のまま = 偽 green の温床） |
| **W-05** | layers 契約が兄弟パッケージの追加を想定していない（**confidence 80 だが親が fix-now に格上げ**: Phase 2 で jin-adk / jin-render を足すと兄弟間の一方向が静かに許可される）。`"jin_adk \| jin_render"` の書き方と、forbidden の `source_modules` に jin_render を含める必要 |
| **W-11** | `permissions:` / `concurrency:` / `timeout-minutes` 未指定 |

### (7) conventions — 拡張性

| ID | 内容 |
|---|---|
| **CONV A-1** | `packages/*/tests/` に `__init__.py` が無く、**同名テストファイル 1 個でスイート全体が `Interrupted`**。**親が再現確認済み**。Phase 2 以降で `test_model.py` 等が確実に衝突する |
| **CONV A-2** | パッケージ一覧が `pyproject.toml` に 5 箇所ハードコード。`CLAUDE.md` にパッケージ追加時のチェックリストを明記 |
| **CONV A-3** | （`conventions.md` 参照） |
| **CONV C-1** | （`conventions.md` 参照） |
| **W-08 / CONV** | `tests/conftest.py:40` の `glob("*/*.jin")` を CLI 側と同じ `rglob("*.jin")` にそろえる（**confidence 85 だが親が fix-now に格上げ**） |

## 2. fix-later（本ラウンドでは直さない・親が pending-decisions に起票する）

`W-07`（CI に pnpm ジョブの受け皿が無い / Phase 5 で対応）、`W-09`（ruff の select が既定のまま）、
`W-12`（actions のミュータブルタグ）、`C-3`、`B-5`、`B-6`、`B-7`、および各生出力の
confidence 80 未満の finding。**これらに手を出さないこと。**

`DP-COMMON-11` の 2 本目（`apps/editor` → Python パッケージ）は Phase 5 で対応する。
`test_editor_contract_is_not_yet_enforced` の tripwire を**弱めたり削除したりしないこと**。

## 3. 判断ポイントの結論（実装者が決めてはならない事項）

次の 3 件は仕様と実装のどちらを直すかの判断であり、**auto-decider の仮判断結果に従うこと**。
結論は `delivery/20260904-1445-jin/auto-decisions.md` と `docs/adr/` を読むこと。

- `DP-JIN-DIAGCODE-NUMBERING-01` — JIN012 / JIN013 の採番と要件書 §2.4 への追加
- `DP-JIN-RENAME-SCOPE-01` — correctness A-5。**`docs/spec/ops.md` §3 と `ops.py:405` のコメントが矛盾している。片方を消して矛盾を消すのではなく、決定に従って両方を整合させること**
- `DP-JIN-JIN050-LOOP-SCOPE-01` — correctness B-4

## 4. 完了時に必ず実行して**出力を報告する**コマンド

「テストが通りました」では不可。**各コマンドの実出力を貼ること。**

```bash
# 1. 全テスト（ロック固定で）
UV_LOCKED=1 uv run pytest --color=no -q 2>&1 | tail -3

# 2. S2 の再現が塞がったか（JIN060 が報告され exit 1 になること）
D=/Users/toyota/.claude/jobs/8b3a6b62/tmp/s2
PYTHONPATH="$D" uv run jin check --resolve "$D/exit.jin"; echo "EXIT=$?"

# 3. W-03 の再現が塞がったか（新パッケージのテストが収集され失敗すること→確認後に必ず撤去）
mkdir -p packages/jin-zz/src/jin_zz packages/jin-zz/tests
printf '[project]\nname = "jin-zz"\nversion = "0.1.0"\nrequires-python = ">=3.12"\n' > packages/jin-zz/pyproject.toml
touch packages/jin-zz/src/jin_zz/__init__.py
echo 'def test_must_be_collected(): assert False' > packages/jin-zz/tests/test_zz.py
uv run pytest --color=no -q 2>&1 | tail -3     # ← test_must_be_collected が collected & failed になること
rm -rf packages/jin-zz && uv run pytest --color=no -q 2>&1 | tail -2

# 4. A-3 の再現が塞がったか（OpError になること）
uv run python -c "
from jin_core.model import JinFile, DEFAULT_SCHEMA_URL
from jin_core.ops import apply_op, Op
d={'\$schema':DEFAULT_SCHEMA_URL,'version':1,'root':'A','circles':[{'name':'A','core':'m','instruction':{'rune':'r'},'tools':[{'name':'t1','kind':'tool','ref':'m:a'},{'name':'t2','kind':'tool','ref':'m:b'}],'state':[{'name':'s1','type':'str'},{'name':'s2','type':'str'}]}]}
m=JinFile.model_validate(d)
try:
    apply_op(m, Op(op='moveTool', pointer='/circles/0/state/1', index=0)); print('NG: 例外にならなかった')
except Exception as e: print('OK:', type(e).__name__, e)
"

# 5. S8 / S9 の再現が塞がったか（いずれも OpError になること）
uv run python -c "
from jin_core.model import JinFile, DEFAULT_SCHEMA_URL
from jin_core.ops import apply_op, Op
b={'\$schema':DEFAULT_SCHEMA_URL,'version':1,'root':'A','circles':[{'name':'A','core':'m','instruction':{'rune':'hello {k} world'},'state':[{'name':'k','type':'str'}]}]}
for val in ['x\\\\g<0>y','b\\\\1c','q\\\\qz']:
    try:
        r=apply_op(JinFile.model_validate(b), Op(op='rename', pointer='/circles/0/state/0', value=val))
        n=getattr(r,'model',None) or r[0]
        print('S8', repr(val), '->', repr(n.circles[0].state[0].name), repr(n.circles[0].instruction.rune))
    except Exception as e: print('S8', repr(val), '->', type(e).__name__, e)
for p in ['/circles/99']:
    try:
        apply_op(JinFile.model_validate(b), Op(op='rename', pointer=p, value='Z')); print('S9 NG: 例外なし')
    except Exception as e: print('S9', p, '->', type(e).__name__, e)
"

# 6. 依存方向・lint・examples
uv run lint-imports; echo "EXIT=$?"
uv run ruff check .; echo "EXIT=$?"
uv run jin check examples; echo "EXIT=$?"
uv run jin fmt --check examples; echo "EXIT=$?"

# 7. 作業ツリーに残骸が無いこと
git status --porcelain
```

## 5. 成果物の更新

- `implementation-plan.json`: `tasks` と `verification_status.evidence[]` に本修正ラウンドを **append**
  （`jin_phase: 1` / `fix_round: 1` のタグを付ける)。**既存要素を置換しない。**
  `verification_status.overall` を自己判断で `verified` に戻さないこと — **親が再レビュー後に再導出する。**
- `decision-conformance.md`: S14 の乖離を訂正。S13 等で新たに値を確定したらその根拠を追記。
- `implement-ledger.md`: finding への見解があれば `[R1][<finding ID>]` で 1 行 append。

## 6. 締め

修正完了後、最終応答に次を含めて終了すること（`code-review-report.md` は書かない — 親が書く）:

- 対応した finding ID の一覧と、**それぞれで追加した回帰テストのファイル:行**
- 上記 §4 の全コマンドの**実出力**
- 直せなかった finding があればその ID と理由（**未対応を対応済みと書かない**）
- 末尾に `DONE` / `DONE_WITH_CONCERNS` / `BLOCKED` / `NEEDS_CONTEXT` を 1 行
