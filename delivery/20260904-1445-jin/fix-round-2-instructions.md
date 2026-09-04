# fix-now 修正ラウンド 2 — 指示書（親が作成 / DP-REVIEW-FIXLOOP-01）

対象: 修正ラウンド 1 の**再レビューで判明した未消滅 1 件と新規欠陥 4 件**
実施者: `impl-p01`（同一 implementer・ラウンド 2）
完了確認: **同一観点の code-reviewer による再レビューで defect-gone を確認するまでクローズしない。**

## 0. 前提

修正ラウンド 1 の再レビュー結果:

| 観点 | defect-gone | 未消滅 | 新規欠陥 |
|---|---|---|---|
| conventions | 5/5 | 0 | 3（すべて low・本ラウンド対象外） |
| security | 14/14 | 0 | **2（conf 97 / 95）← 本ラウンド対象** |
| wiring | 6/7 | **W-05（部分）← 本ラウンド対象** | **2（conf 92 / 85）← 本ラウンド対象** |

**ラウンド 1 の修正自体は妥当で、S1 / S2 / A-1 / A-2 / A-3 / S8 / S9 / W-03 / CONV A-1 は
親と reviewer の両方が defect-gone を確認しています。本ラウンドは「修正が持ち込んだ回帰」と
「機構は入ったが検査が効いていない箇所」だけを対象にします。**

生出力: `delivery/20260904-1445-jin/code-review-raw/{security,wiring,conventions}-round1.md`

鉄則はラウンド 1 と同じ（指示書 `fix-round-1-instructions.md` §0）:
本指示書の finding のみを直す / 各修正に回帰テストを付ける / テストを消さない・`xfail` しない・
アサーションを緩めない / **git commit しない** / `verification_status.overall` を自己判断で
`verified` に戻さない。

## 1. 修正対象（5 件）

### (1) N-01 [wiring / conf 92] CI の lock 検証が実物では効いていない

`.github/workflows/ci.yml:26`（`UV_LOCKED: "1"`）と `:44`（`run: uv sync --frozen`）が同一コマンドで衝突。

**親と reviewer の実測（両方が一致）**:

| コマンド | uv 0.7.8（ローカル） | uv 0.12.9（`setup-uv@v5` が入れる版） |
|---|---|---|
| `UV_LOCKED=1 uv sync --frozen`（**実物**） | クリーンツリーでも **EXIT=2** `the argument '--frozen' cannot be used with '--locked'`（lock 検出ではない usage エラー） | `warning: Ignoring UV_LOCKED because --frozen was provided` / **EXIT=0**（lock 検証が飛ぶ） |
| `UV_LOCKED=1 uv sync`（提案形） | クリーン EXIT=0 / stale lock **EXIT=2** `The lockfile at uv.lock needs to be updated` | 同左 |

つまり**どちらの uv 版でも `Sync dependencies` ステップは lock を検証していません**。
lock 検証が最初に効くのは次の無関係な名前のステップ（`Check dependency direction`）です。

修正:
1. **`ci.yml:44` を `run: uv sync` にする**（`--frozen` を削る）。
2. **`setup-uv@v5` に `version:` を明示して uv の版を固定する**。現状は版が固定されておらず、
   古い uv が入る状況では上表の左列（無条件失敗）に転びます。**版の値は実在するものを使い、
   決めた根拠を `decision-conformance.md` に書くこと**（捏造しない）。

   > **ピンする版を決めたら、その版で `uv lock --check` が通ることを必ず確認すること**（wiring reviewer の申し送り）。
   > コミット済みの `uv.lock` は uv 0.7.8 が作ったものなので、別の版が「この lock は更新が要る」と
   > 判断すると `UV_LOCKED` 下で **stale な pyproject が無くても CI が毎回赤になります**。
   > `--frozen` を外した後はこれが素通りしなくなるため、ピンと同時に踏む可能性があります。
   >
   > **uv 0.12.9（2026-09-01）は reviewer が隔離コピーで検証済み**:
   > 修正ラウンドが作った lock（markers 無し）と現在の lock（markers 有り）の両方に対して
   > `uv lock --check` EXIT=0 / `UV_LOCKED=1 uv sync` EXIT=0（lock 無変更）。
   > この版を選ぶなら追加作業は不要です。別の版を選ぶ場合は**その版で同じ 2 コマンドを通してから確定**すること。
   > 検証用バイナリ: `/Users/toyota/.claude/jobs/8b3a6b62/tmp/uv-aarch64-apple-darwin/uv`（darwin/arm64 のみ）
3. **`test_uv_locked_is_set_for_the_whole_job`（`tests/contract/test_ci_contract.py:38-59`）を強化する。**
   現状は job env に `UV_LOCKED` があることしか見ておらず、`--frozen` による打ち消しを検出しません。
   これは W-02 で指摘された「検査が存在する ≠ 検査が落ちる」と同型です。
   **ci.yml の各 uv コマンドを走査し、`UV_LOCKED` を打ち消すフラグ（`--frozen` / `--no-locked` 等）が
   付いていないことを検査するテスト**にしてください。

### (2) W-05 残件 [wiring] 兄弟パッケージの同居を契約テストが検査していない

`tests/contract/test_packaging_contract.py:110` の
`{name.strip() for layer in layers for name in layer.split("|")}` が
`layers` をフラットな集合に潰しているため、「各パッケージが宣言に登場するか」しか見ていません。

**reviewer の実測**:
- `layers = [jin_cli, jin_lsp, "jin_adk | jin_render", jin_core]` → `jin_adk→jin_render` と
  `jin_render→jin_adk` の**両方**を BROKEN にする（`|` 構文は正しく効く）
- `layers = [jin_cli, jin_adk, jin_render, jin_core]`（素朴な直列）→ `jin_render→jin_adk` **だけ**を
  BROKEN にし、`jin_adk→jin_render` を**静かに許す**
- **後者でも `test_packaging_contract.py` は 27 passed（全緑）**

**Phase 2 で `jin-adk` / `jin-render` を足す直前なので、文章の防波堤（`pyproject.toml` のコメントと
CLAUDE.md のチェックリスト）のままにはしません。**

修正（根本策を採用すること）:
`delivery/20260904-1445-jin/design.yaml` の `architecture.dependency_direction.rules` から
**「互いに依存しない」と宣言されたペア**を読み取り、そのペアが `[tool.importlinter]` の `layers` の
**同一要素に `|` で並んでいること**を検査するテストを追加する。
簡易版（`jin_adk` と `jin_render` が同じ layer 要素にあることを直書き）でも現状より強くなりますが、
**design.yaml を読む形を優先**してください（Phase 3 以降でルールが増えても追随するため）。

**このテストが実際に赤くなることを、素朴な直列に書き換えて確認し、その出力を報告すること。**

### (3) N-02 [wiring / conf 85 → 親が fix-now に格上げ] tests を持たないパッケージが素通りする

`tests/contract/test_packaging_contract.py:56-58` / `:73-75` の `pytest.skip` により、
`tests/` ディレクトリを持たないパッケージは **testpaths 網羅と `__init__.py` の 2 本を静かに素通り**します。
reviewer の実測: `packages/jin-render/tests` を消すと SKIPPED 2 件でスイートは緑。

**W-03 で塞いだ「新パッケージのテストが CI で走らない」状態に別経路で到達できます。**
格上げの理由は Phase 2 で新パッケージを足す直前だからです。

修正: `tests/` を持たないパッケージは skip ではなく**失敗**させる（テストの無いパッケージを
許すなら、その許可を明示的な allowlist として持ち、allowlist に載っていないものは落とす）。

### (4) N1 [security / conf 97] `jin fmt` がファイルのパーミッションを 0600 に落とす

`packages/jin-cli/src/jin_cli/main.py:108-114`。`tempfile.mkstemp` は 0600 で作り、
`os.replace` は置き換える側のモードを引き継ぎます。

**親の実測**: 整形前 `-rw-rw-r--` → 整形後 `-rw-------`。
group / other の読み取りビットが黙って外れ、**git は実行ビット以外のモードを追跡しないので diff にも出ません**。

修正: `os.replace` の前に `shutil.copymode(path, temporary)`。
回帰テストは**実際にモードを比較**すること（`os.stat().st_mode`）。

### (5) N2 [security / conf 95] 書き込めないディレクトリで未捕捉 `PermissionError`

`packages/jin-cli/src/jin_cli/main.py:108` / `:201`。`mkstemp` はファイルではなく
**ディレクトリ**の書き込み権を要求します。

**親の実測**: `chmod 555` のディレクトリ内の `.jin` を `jin fmt` すると `PermissionError` が
素通りし rich のトレースバックが出ます（`locals` は出ないので S5 の対策自体は効いている）。

これは **S5 で塞いだ欠陥型の再導入**であり、かつ**機能後退**を伴います —
修正前は書けたケース（読み取り専用ディレクトリ内の書き込み可能ファイル）が整形できなくなりました。

修正: `PermissionError` を診断として扱う（S5 と同じ経路に乗せる）。
機能後退についても、原子的書き込みができない場合の扱いを決めて
`decision-conformance.md` に根拠を書くこと（**黙って機能を落とさない**）。

### (6) correctness の未消滅 4 件 + 部分消滅 1 件

再レビューで **20/25 は defect-gone** でしたが、次は**手が入っていません**。

| ID | 内容 |
|---|---|
| **D-4** | `main.py` の `_collect` が修正前とバイト同一。`jin check README.md` が今も `.md` を読んで JIN001 を出す |
| **E-1** | `tests/contract/test_canonical_contract.py:86-92` が未変更。今も「インデント幅が偶数」しか見ておらず、**4 スペースに変えてもこのテストは通る**。※ リスク自体は既存の `test_canonical.py::test_examples_are_already_canonical` が覆っている（reviewer がミューテーションで確認済み）が、指摘したアサーション自体は未修正 |
| **E-2** | 同ファイル 144-148 行も未変更。正規表現 `\\u00[2-9a-f][0-9a-f]` は `encode_string` が出しうる **U+0000〜U+001F のエスケープに一致しない** |
| **E-3** | 178 行の `parametrize("explicit_default", [False])` が 1 値のまま（実質パラメタライズになっていない） |

**E-5 は部分消滅**（8 項目中 6 項目解消）。残る 2 つを本ラウンドで塞いでください:
- **BOM のテストが 0 件**
- **`rename(circle)` が `flow.steps` を追随する経路が実質未検証** —
  `ops.py` の `flow["steps"] = [...]` を `pass` に差し替えても **442 テストが全部緑のまま通ります**。
  これは要件書 §6.3「rename は参照を全て追随」の中核경路なので、必ずミューテーションで
  赤くなるテストを足してください。

### (7) N-2 [correctness / medium] 制約を追加したのに正典に書いていない

`model.py:40-81` が制御文字・DEL・C1・孤立サロゲート・長さ上限を段 2 で弾くようになりました（S13 の修正）。
しかし **`docs/spec/model.md` にも `diagnostics.md` にも記載がありません**。
さらに `model.md` §7 は今も「制御文字は `\uXXXX`、DEL はエスケープしない」と、
**モデルが受け付けなくなった文字の書き出し規則を正典として書いています**。

ラウンド 1 で「仕様側とコード側は同じ欠陥」として S-1〜S-4 を直したのと同型の問題です。
**制約を実装に足したなら正典にも書く**こと。突合テストで両者の整合を固定してください。

### (8) N-3 [correctness / low → 親が fix-now に格上げ] 公開スキーマが新しい制約を表現していない

`schemas/jin.schema.json` は `maxLength` は出しますが、N-2 の文字種制約（AfterValidator）と
B-3 の loop 限定（model_validator）を表現しません（実測で `$defs.Flow` に `if`/`then`/`allOf` 無し）。

格上げの理由: **要件書 §0 成功条件 3 は「Claude Code が JSON Schema と診断の出力だけで
構文・意味エラーを修正しきれる」ことを求めており**、スキーマが実際の受け入れ条件より緩いと
LLM がスキーマ的に妥当な `.jin` を書いても `jin check` で落ちます。
JSON Schema で表現できない制約は、**表現できない旨と代替の検出手段（JIN コード）を
`docs/spec/model.md` に明記**すれば足ります（無理に `pattern` を捏造しないこと）。

## 2. 本ラウンドの対象外（手を出さないこと）

- conventions の新規 low 3 件（N-1 は**親が docstring のみ修正済み**。N-2 / N-3 は fix-later）
- `DP-JIN-RESOLVE-ISOLATION-01`（`--resolve` のファイル間汚染）— **判断ポイントとして起票済み**。
  auto-decider の判断が出るまで実装しないこと。Phase 4 着手前がデッドライン
- S3 の残存（最悪 8.4 秒）— Phase 4 への申し送り
- `os._exit(0)` の残存 — security reviewer も格上げ不要に同意
- fix-later 全般（confidence 80 未満）

## 3. 完了時に必ず実行して**出力を報告する**コマンド

```bash
# 全テスト（-q を addopts と重ねない）
UV_LOCKED=1 uv run pytest --color=no 2>&1 | tail -2

# N-01: ci.yml 実物のコマンドが clean で通り、stale lock で落ちること
UV_LOCKED=1 uv sync; echo "clean EXIT=$?"
cp uv.lock /tmp/l.bak; cp pyproject.toml /tmp/p.bak
python3 -c "import re;s=open('pyproject.toml').read();m=re.search(r'\"import-linter[^\"]*\",',s);open('pyproject.toml','w').write(s.replace(m.group(0),m.group(0)+'\n  \"mypy>=1.0\",',1))"
UV_LOCKED=1 uv sync; echo "stale EXIT=$?"
cp /tmp/p.bak pyproject.toml; cp /tmp/l.bak uv.lock; uv sync -q
# 強化した test_ci_contract が --frozen の再導入を捕まえること（変異させて赤を確認 → 戻す）

# W-05: layers を素朴な直列に書き換えると新テストが赤くなること（確認後に戻す）

# N-02: tests/ を持たないパッケージが skip ではなく失敗すること

# N1: パーミッションが保たれること
D=$(mktemp -d); cp examples/researcher/researcher.jin $D/a.jin; chmod 664 $D/a.jin
printf '\n' >> $D/a.jin; uv run jin fmt $D/a.jin >/dev/null; ls -l $D/a.jin

# N2: 書き込めないディレクトリで診断になること（トレースバックが出ないこと）
mkdir -p $D/ro; cp examples/researcher/researcher.jin $D/ro/b.jin
printf '\n' >> $D/ro/b.jin; chmod 555 $D/ro
uv run jin fmt $D/ro/b.jin; echo "EXIT=$?"; chmod 755 $D/ro; rm -rf $D

# 回帰なし確認
uv run lint-imports; uv run ruff check .; uv run ruff format --check .
uv run jin check examples; uv run jin fmt --check examples
git status --porcelain
```

## 4. 締め

最終応答に、対応した finding ID と**それぞれで追加した回帰テストの `file:line`**、
上記コマンドの**実出力**、直せなかったものの ID と理由を含めること。
`code-review-report.md` は書かない（親が書く）。末尾に 4 状態のいずれかを 1 行。
