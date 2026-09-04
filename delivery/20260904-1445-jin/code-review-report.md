# Stage 5 Code Review Report — 2026-09-04

対象: 実装ラウンド 1（Jin **Phase 0** 仕様書と examples ＋ **Phase 1** jin-core / jin-cli）
実施主体: 親（`/aid auto-deliver` の実行主体）。正本 `skills/implementation/parallel-code-review/DOMAIN-SKILL.md`

## Summary

- **Status: FINAL** — ただし **Jin Phase 0+1 のスコープに対してのみ**。親が全ゲートを再実行して `verification_status.overall = verified`（`scope_labels: [backend-unit-verified]`）を再導出した。
- **本レポートのスコープは Jin Phase 0+1 のみ。** 本ランの全体スコープは Phase 0〜6（ADR-001）であり、
  Phase 2〜6（jin-adk / jin-render / jin-lsp / apps/editor）は未着手。**Jin 成果物全体は FINAL からは程遠い。**
- verification_status.overall: **`verified`**（親が再導出。実装者は最後まで `partially_verified` のまま返し、自己判断で戻していない）
- `pipeline_e2e` は **`passed`**（2026-09-04 の PR #1 マージ時に GitHub Actions が実機で成功。pull_request 2 回 + push/main 1 回とも conclusion=success）。`human_only` 条件は `not_run` のまま PR レビュー送り。**実施済みと報告していない**
- scope_labels: `backend-unit-verified`
- 起動した観点: correctness / conventions / wiring / security（並列度 = 4）
- 各観点の findings 件数: **correctness=33 / conventions=21 / wiring=13 / security=19（合計 86 件）**
- verdict 内訳: fix-now = 約 51 件（confidence 90 以上）＋ 親が格上げした 4 件（W-02 / W-05 / W-08 / N-02）
  / fix-later = 8 件（`DP-REVIEW-JIN-001`〜`008` として起票済み）
- 採用しきい値: `confidence_threshold_fix_now = 90`（design.yaml の既定・変更なし）
- 配置: `after_verify`（`design.yaml.review_policy.stage_order` の既定）
- 関連 DP: DP-IMPL-STAGE-03 / DP-IMPL-VERIFIED-01 / DP-REVIEW-SECURITY-01 / DP-REVIEW-RECALL-01 /
  DP-REVIEW-FIXLOOP-01 / DP-CONFORMANCE-01

### 前提として押さえるべき事実

**レビュー開始時点でテストは 225 件すべて緑だった。** その状態で 86 件の finding が出ている。
テストが緑であることは品質の証拠になっていない。レビューが記録した「テストが素通りした理由」は一貫しており、
fixture が 1 要素だった / 最初から `boundary` を持っていた / `UnexpectedCharacters` 経路のテストが 0 件だった、
といった**テスト側の穴**である。

修正後、テストは **225 → 442 → 491 件**（回帰テスト +266 件）。

## Findings by Aspect

生出力（全 finding の本文）は `code-review-raw/` 配下:
`correctness.md` / `conventions.md` / `wiring.md` / `security.md`（ラウンド 1）、
`*-round1.md`（修正ラウンド 1 の再確認）、`*-round2.md`（修正ラウンド 2 の再確認）。

### 親が独立に再現して確定した重大 finding（8 件）

実装者の報告を根拠にせず、親がコマンドを実行して再現を確認したもの。

| ID | 観点 | 内容 |
|---|---|---|
| **S2** | security | `ref` 先モジュールの `sys.exit(0)` で `jin check --resolve` が**出力ゼロ・exit 0** になり、同一ファイル内の本物の JIN060 が消える。CI の赤が緑になる（fail-closed 違反） |
| **S8** | security | `rename` の新名が `re.sub` の置換テンプレートとして解釈され、state 名と rune が食い違う**不整合モデル**を生成。`\1` / `\q` は未捕捉 `re.PatternError` |
| **S9** | security | `rename` だけ circle index の範囲検査が無く未捕捉 `IndexError`（他の op は正しく `OpError`） |
| **A-3** | correctness | `moveTool` / `setState` / `removeGuard` が pointer の経路セグメントを検証せず**別の配列を書き換える**（`state` の pointer で `tools` が並べ替わる） |
| **A-1 / A-2** | correctness | 逆オペレーションが配列順を復元しない／`boundary` を消さず `"boundary": {}` が増える。**要件書 成功条件 5「ファイル→モデル→ファイルがバイト同一」が undo 経路で崩れる** |
| **W-01** | wiring | CI が `uv.lock` の整合を保証せず、裸の `uv run` が lock を書き換えて別の解決結果でテストが走る |
| **W-03** | wiring | `testpaths` のハードコードで新パッケージのテストが 1 件も収集されない |
| **CONV A-1** | conventions | `packages/*/tests/` に `__init__.py` が無く、同名ファイル 1 個で `Interrupted: 1 error during collection` とスイート全体が停止 |

### 仕様書自体の誤り（6 件・Phase 2〜6 が参照する正典）

correctness が S-1〜S-6 として検出。**コード側の欠陥と対になっているものは同時に修正**した
（S-1↔A-1/A-2、S-2↔B-2、S-3↔B-3、S-4↔C-2）。特に **S-1 は `ops.md` §2 の逆オペレーション表が
復元不能を仕様として追認しており**、同文書 §1 の「クライアントが逆 op 列を保持して undo」と両立していなかった。

### 親の誤判定 1 件（記録）

親は 2026-09-04 18:20 に「W-01 は defect-gone」と判定したが、**検証コマンドが ci.yml の実物と異なっていた**
（`--frozen` なしの提案形で確認していた）。wiring reviewer の異議提起により誤りが判明し撤回。
実測し直した結果、uv 0.7.8 ではクリーンツリーでも usage エラー、uv 0.12.9 では警告のみで lock 検証が飛ぶ。
**どちらの版でも ci.yml:44 は lock を検証していなかった。**

## fix-now 対応

修正は 3 ラウンド。**完了確認は同一観点の code-reviewer による再レビューで行い、実装者の「直しました」は
根拠にしていない**（DP-REVIEW-FIXLOOP-01）。

| ラウンド | 対象 | 再レビュー結果 |
|---|---|---|
| 1 | confidence 90 以上の全件 ＋ 親が格上げした 4 件 | conventions **5/5** / security **14/14** / wiring **6/7** / correctness **20/25** = **45/46 defect-gone** |
| 2 | ラウンド 1 の未消滅 5 件 ＋ **修正が持ち込んだ新規欠陥 7 件** | security **2/2** / correctness **7/7** / wiring **3/3** = **12/12 defect-gone・機能面の新規欠陥 0** |
| 3 | R-1（symlink TOCTOU）/ R-2（危険側に誤った docstring） | security **2/2 defect-gone**。変異 6 種が名指しで赤 |
| 4 | T-1（`OSError` 未捕捉）/ U-1（`guard:` の照合が緩い）/ 点 3 の理由づけ訂正 / `ruff` PYI034 | security **4/4 defect-gone**。**コミットに賛成**の判定 |
| 5 | V-1（内容が失われたことが伝わらない） | 親が再現し修正を確認（0 バイトになるが「バックアップから復元してください」と伝える） |

**修正が新たな欠陥を持ち込んだ**のはラウンド 1 → 2 の 7 件。うち 2 件は同一欠陥を security と correctness が
独立に検出した（`jin fmt` がパーミッションを 664 → 600 に落とす。**git は実行ビット以外のモードを追跡しないため
diff にも出ない**）。再レビューを回さなければ検出できなかった。

### 変異ベースの確認（本レポートの中心的な根拠）

「検査が存在する」ことと「検査が実際に落ちる」ことを区別するため、修正後に実装を壊して検査が赤くなるかを確認した。

| 対象 | 注入した変異 | 結果 |
|---|---|---|
| E-5（`rename` の `flow.steps` 追随） | `ops.py` の該当行を `pass` に | 2 件が赤（**修正前は 442 件全緑のまま通っていた**） |
| W-05（兄弟パッケージの同居） | `independence_violations` を常に `[]` に | 1 件が赤 |
| W-05（実パッケージ経路） | `jin-adk` / `jin-render` を作り `layers` を素朴な直列に | 名指しで赤。`lint-imports` も直列 1 件 / `\|` 区切り 2 件を end-to-end で確認（wiring 実施） |
| N-01（CI の lock 検証） | ci.yml 変異 5 通り ＋ 走査関数の無力化 ＋ 回避経路 3 通り | すべて捕捉（wiring 実施） |
| N-02（tests 無しパッケージ） | `packages/jin-core/tests` を削除 | SKIPPED 0・FAILED 3（wiring 実施） |
| N1（パーミッション保持） | `shutil.copymode` の 1 行削除 | 3 ケースが赤（security 実施） |
| 追加テスト全般 | 独立ミューテーション 12 本 | **12 本すべて検出・見逃し 0**（correctness 実施） |

## fix-later / backlog

`docs/pending-decisions.md` に `DP-REVIEW-JIN-001`〜`008` として起票済み（schema 駆動・生成器で再生成）。

| 仮 DP ID | 内容 | 参照すべきフェーズ |
|---|---|---|
| DP-REVIEW-JIN-001 | `jin check` のディレクトリ探索が symlink を辿る（読み取りのみ） | — |
| DP-REVIEW-JIN-002 | ruff の `select` が既定のまま（実質ほぼ検査していない） | — |
| DP-REVIEW-JIN-003 | CI に pnpm / Node ジョブの受け皿が無い | **Phase 5 着手時に必須参照** |
| DP-REVIEW-JIN-004 | actions がミュータブルタグ | — |
| DP-REVIEW-JIN-005 | テストが日付入りランディレクトリのパスに依存 | Phase 2 以降 |
| DP-REVIEW-JIN-006 | `MINIMUM_UV_COMMANDS` の引き下げに可視化の門が無い | — |
| DP-REVIEW-JIN-007 | テスト名と守備範囲のずれ（命名調整のみ） | — |
| DP-REVIEW-JIN-008 | `check_text` 最悪 8.4 秒。**LSP は打鍵ごとに呼ぶ** | **Phase 4 着手時に必須参照**（要件書 §6.4「1000 行以下で診断 1 秒以内」） |

別途 `DP-JIN-RESOLVE-ISOLATION-01` を判断ポイントとして起票（実装させていない）:
`--resolve` が同一プロセスで import するため、**1 ファイル目の `ref` が `jin_core.semantic.analyze` を差し替えると
2 ファイル目の本物の JIN060 が消えて「2 ファイル / error 0 件」exit 0 になる**（親が実測）。
S2 修正後も残る別経路で、プロセスが死なずもっともらしい正常レポートを出す点で `os._exit` より実害が大きい。
**Phase 4 で LSP が長寿命プロセスになる前が判断期限。**

## human_only（人間にしか判定できず PR レビューへ送るもの）

design.yaml `implementation_phases` が `verification.machine` と `verification.human_only` に分解した項目のうち、
Phase 0 / Phase 1 の `human_only` は **`not_run`**。実施していないものを実施済みと報告していない。

- Phase 0: 仕様に自己矛盾がないかの最終判断（機械検査は突合テストが代替）
- Phase 1: —

## 未解決の観察（記録のみ・対応不要と判定）

- **O-4**: 検証中の数分間、BOM / 孤立サロゲート系 3 テストが赤くなった。`impl-p01` のラウンド 2 編集の
  着地前の窓と確定（完了報告 19:06 と一致）。親がフルスイート 6 回連続 491 passed・該当 3 テスト 5 回連続 pass を実測。
  **implementer と reviewer が同一ワーキングツリーを共有する構造上、この窓は再発しうる。**
- **`os._exit(0)` の残存**: `ref` 先が `os._exit` を呼ぶと同一プロセス内では防げない。ただし `--resolve` は既定オフで、
  攻撃者制御のモジュールが `sys.path` に載る前提であり、その時点で任意コード実行が成立しているため権限昇格ではない。
  security reviewer も格上げ不要に同意。


## 最終ゲート（親が実行・2026-09-04 20:12）

```
UV_LOCKED=1 uv run pytest --color=no   → 521 passed
uv run ruff check .                    → All checks passed!            EXIT=0
uv run ruff format --check .           → 40 files already formatted    EXIT=0
uv run lint-imports                    → Contracts: 3 kept, 0 broken.  EXIT=0
uv run jin check examples              → 2 ファイル / error 0 / warning 0  EXIT=0
uv run jin fmt --check examples        →                                EXIT=0
uv run jin schema | diff schemas/...   → ドリフト無し
UV_LOCKED=1 uv sync                    → EXIT=0
```

テスト件数の推移: **225 → 442 → 491 → 496 → 498 → 505 → 518 → 521**（回帰テスト +296 件）。

## 「検査しているつもりで検査していない」が 4 層で見つかった

本レビューの最大の収穫。いずれも**テストが緑の状態で**発見された。

| 層 | 実例 | 発見者 |
|---|---|---|
| **テスト本体** | `rename` の `flow.steps` 追随を `pass` に差し替えても 442 件全緑 | correctness（E-5） |
| **CI** | `uv sync --frozen` が job env の `UV_LOCKED` を打ち消し lock 検証が飛ぶ。uv 版によって「無条件失敗」と「黙って素通り」の間で振れる | wiring（W-01 / N-01） |
| **コメント** | docstring が「`_collect` が symlink を弾いている」と書くが、そこにフィルタは無い（**誤りの向きが危険側**） | security（R-2） |
| **変異ハーネス自体** | `.pyc` の無効化が「mtime 秒 + サイズ」のため、同一サイズの変異が同じ秒内に走ると前の変異のバイトコードで実行される | **implementer 自身**（自己申告） |

4 番目が最も重い。**品質を判定する道具そのものが偽の結果を返していた。** 偽 green の向きにしか転ばないため過剰修正は起きないが、見逃しは起こりうる。
対処: 全 4 ハーネスに `__pycache__` 削除 + `PYTHONDONTWRITEBYTECODE=1` を入れ、ラウンド 1〜5 の全 88 件を再実測（88/88 赤）。
親も主要な結論（E-5 / `guard:` の嘘）をキャッシュ無効化で取り直し、結論が変わらないことを確認。
security reviewer も自分の「緑」報告 4 件を再実測し、E-B / E-B2 が U-1 修正後に赤くなることをもって当時の緑が本物だったと確認。

3 番目に対しては **`guard: <関数名> -> <その関数に在るべきトークン>` 記法**を導入し、
「コメントが実装について嘘をつくこと」自体を CI で落とせるようにした。
照合が部分文字列一致で緩い（`guard: fmt -> os` が素通り）ことまで security が見つけ、AST 照合に修正済み（U-1）。

## 親自身の誤りの記録（2 件）

1. **W-01 の誤判定**（前掲）— 検証コマンドが ci.yml の実物と異なっていた。wiring reviewer の異議で撤回。
2. **V-1 を再現できなかった** — `os.write` をモックしたが、実装は `os.fdopen` のハンドル越しに書くため当たらなかった。
   implementer の説明を受けて正しい方法で再現し、修正も確認した。

いずれも reviewer / implementer からの指摘で判明している。**親の判定も検証の対象にした**ことが機能した。
