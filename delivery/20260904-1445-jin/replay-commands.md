# replay-commands — 実装ラウンド 1/5（Jin Phase 0 + Phase 1）

Stage 4 verify を実環境で再走するためのワンコマンド集。

> `verification_status.overall = verified` なので本ファイルの生成は**必須ではない**が、
> 後続ラウンドの implementer と PR レビュワーが同じ検証を再現できるよう用意した。
> `pipeline_e2e`（GitHub Actions 上での実行）だけは本ラウンドで未実行であり、§4 がその再走手順である。

前提: リポジトリルート `/Users/toyota/PycharmProjects/jin-lang` で実行する。`uv` が必要。

## 0. 一括（全部まとめて）

```bash
uv sync \
  && uv run lint-imports \
  && uv run ruff check . \
  && uv run ruff format --check . \
  && uv run python scripts/generate_schema.py && git diff --exit-code -- schemas/jin.schema.json \
  && uv run pytest \
  && uv run jin check examples \
  && uv run jin fmt --check examples \
  && echo "ALL GREEN"
```

期待: 最後に `ALL GREEN`。`.github/workflows/ci.yml` と同じコマンド列である。

## 1. Stage 1 pre の再走

```bash
uv sync                                   # 依存解決（dependency-availability-check）
uv --version                              # 期待: uv 0.7.8 系
uv run python -c "import sys; print(sys.version)"   # 実測は 3.14.6（要件は >=3.12）
uv run python -c "import pydantic, lark, typer; print(pydantic.VERSION, lark.__version__, typer.__version__)"
# 期待: 2.13.5 1.3.1 0.27.2
```

## 2. Stage 4 verify の再走（machine 条件 15 件）

### Phase 0（6 条件）

```bash
uv run pytest tests/spec/test_spec_consistency.py -q     # 25 件すべて PASS

# 個別に見る場合
uv run pytest tests/spec/test_spec_consistency.py -k 'diagnostics_canonical or proposed or stage_table or precedence'  # 条件 1
uv run pytest tests/spec/test_spec_consistency.py -k 'ops_match'          # 条件 2
uv run pytest tests/spec/test_spec_consistency.py -k 'ring_radii'         # 条件 3
uv run pytest tests/spec/test_spec_consistency.py -k 'data_jin_kinds'     # 条件 4
uv run pytest tests/spec/test_spec_consistency.py -k 'adk_vocabulary'     # 条件 5
uv run pytest tests/spec/test_spec_consistency.py -k 'example'            # 条件 6

# 条件 5 の件数の食い違いを自分の目で確かめる（期待: 12。design.yaml は 11 と書いている）
awk '/^### 2.1 語彙と ADK 対応/,/^circle は 2 種類/' jin-requirements.md | grep -c '^| `'
```

### Phase 1（9 条件）

```bash
uv run pytest packages/jin-core/tests/test_check.py -k 'exactly_its_own_code or every_documented_code'  # 条件 1
uv run jin check examples; echo "rc=$?"                                                                  # 条件 2（期待 rc=0）
uv run python scripts/generate_schema.py && git diff --exit-code -- schemas/jin.schema.json              # 条件 3
uv run pytest tests/contract/test_canonical_contract.py -k 'idempotent or unformattable_set'             # 条件 4
uv run pytest tests/contract/test_cli_contract.py -k 'refuses_unformattable'                             # 条件 4 の補足
uv run pytest tests/contract/test_canonical_contract.py -k 'semantics_preserved or text_roundtrip'       # 条件 5
uv run pytest tests/contract/test_canonical_contract.py -k 'rule1 or rule2 or rule3 or rule4 or rule5 or rule6'  # 条件 6
uv run pytest tests/contract/test_canonical_contract.py -k 'rule7'                                       # 条件 7
uv run pytest tests/contract/test_cli_contract.py::test_dump_is_stable_across_processes_with_different_hash_seeds tests/contract/test_pointer_contract.py  # 条件 8
uv run jin schema | diff - schemas/jin.schema.json && echo BYTE_IDENTICAL                                # 条件 9
```

## 3. 依存契約（ADR-004 / DP-COMMON-11）

```bash
uv run lint-imports          # 期待: Contracts: 2 kept, 0 broken.

# 契約が「効いている」ことを確かめる（違反を注入して落ちることを見る）
uv run pytest tests/contract/test_dependency_direction.py -q
```

## 4. pipeline_e2e（**本ラウンド未実行**）の再走

GitHub Actions 上での実行は行っていない（implementer は push しないため）。
実パイプライン通しを検証するには次のようにする。

```bash
git switch -c feat/jin-phase-0-1     # 親がコミットする際のブランチ
git push -u origin feat/jin-phase-0-1
gh run watch                          # Actions の結果を見る
```

期待: `.github/workflows/ci.yml` の 8 ステップ（sync / lint-imports / ruff / schema drift / pytest /
jin check / jin fmt --check）がすべて緑。**ubuntu-latest 上の Python バージョンはローカル（3.14.6）と
異なりうる**ので、ここで初めて版差の問題が出る可能性がある（`implementation-notes.md` §6 の Q-JIN-IMPL-06）。

## 5. human_only（**実施していない**）

design.yaml `implementation_phases.items[0].verification.human_only`:
「仕様全体に自己矛盾がないことの最終判断」

コマンドでは再走できない。**PR レビューで人間が判定する**（ADR-001）。
レビューの入口として次を読むとよい:

```bash
ls docs/spec/                     # model.md / adk-mapping.md / layout.md / diagnostics.md / ops.md
cat delivery/20260904-1445-jin/decision-conformance.md    # 実装時に決めた値と根拠
cat delivery/20260904-1445-jin/implementation-notes.md    # §6 に確認要求ブロック
```

## 修正ラウンド 1（fix-round-1）の再現手順

### 全体

```bash
UV_LOCKED=1 uv run pytest --color=no            # ← -q を重ねない（addopts に既にある。重ねると -qq で集計行が消える）
uv run ruff check . && uv run ruff format --check .
uv run lint-imports                             # Contracts: 3 kept, 0 broken.
uv run jin check examples && uv run jin fmt --check examples
uv run jin schema | diff -u schemas/jin.schema.json -
```

### finding ごとの再現（修正が効いていることの確認）

```bash
# S2: ref 先の sys.exit(0) で fail-open しない
D=/Users/toyota/.claude/jobs/8b3a6b62/tmp/s2   # evilmod.py（sys.exit(0)）と exit.jin を置いたディレクトリ
PYTHONPATH="$D" uv run jin check --resolve "$D/exit.jin"; echo "EXIT=$?"   # JIN060 が出て EXIT=1

# A-3: 誤った配列を指す pointer は OpError
uv run pytest --color=no -p no:randomly packages/jin-core/tests/test_ops.py -k wrong_array

# S8 / S9: rename の置換テンプレート解釈と添字の範囲
uv run pytest --color=no -p no:randomly packages/jin-core/tests/test_ops.py -k "rename or out_of_range"

# W-03: 新パッケージのテストが収集され、設定の抜けが名指しで落ちる
mkdir -p packages/jin-zz/src/jin_zz packages/jin-zz/tests
printf '[project]\nname = "jin-zz"\nversion = "0.1.0"\nrequires-python = ">=3.12"\n' > packages/jin-zz/pyproject.toml
touch packages/jin-zz/src/jin_zz/__init__.py
echo 'def test_must_be_collected(): assert False' > packages/jin-zz/tests/test_zz.py
uv run pytest --color=no -q 2>&1 | tail -8
rm -rf packages/jin-zz            # ← 必ず撤去する
```

### 非空虚性の実測（ミューテーション）

各修正を 1 つずつ元に戻して、対応するテストが赤くなることを確認する。

```bash
uv run python delivery/20260904-1445-jin/fix-round-1-mutations/mutate.py    # 30 パターン
uv run python delivery/20260904-1445-jin/fix-round-1-mutations/mutate2.py   # 強化した 8 パターン
```

スクリプトは対象ファイルを一時的に書き換えて必ず元に戻す。実行後に `git status --porcelain` で残骸が無いことを確認すること。

## 修正ラウンド 2（fix-round-2）の再現手順

```bash
# N-01: --frozen が UV_LOCKED を打ち消すこと（uv 2 版で確認）
UV=/path/to/uv-0.12.9
UV_LOCKED=1 uv sync --frozen; echo "0.7.8  --frozen EXIT=$?"   # → 2（usage エラー）
UV_LOCKED=1 $UV sync --frozen; echo "0.12.9 --frozen EXIT=$?"  # → 0（lock 検証が飛ぶ）
# stale lock を作って比べる
cp uv.lock /tmp/l.bak; cp pyproject.toml /tmp/p.bak
python3 -c "import re;s=open('pyproject.toml').read();m=re.search(r'\"import-linter[^\"]*\",',s);open('pyproject.toml','w').write(s.replace(m.group(0),m.group(0)+'\n  \"mypy>=1.0\",',1))"
UV_LOCKED=1 uv sync;      echo "0.7.8  stale EXIT=$?"          # → 2
UV_LOCKED=1 $UV sync;     echo "0.12.9 stale EXIT=$?"          # → 1
UV_LOCKED=1 $UV sync --frozen; echo "0.12.9 stale+frozen EXIT=$?"  # → 0（これが欠陥）
cp /tmp/p.bak pyproject.toml; cp /tmp/l.bak uv.lock; uv sync -q

# N1 / N2: パーミッションと書けないディレクトリ
D=$(mktemp -d); cp examples/researcher/researcher.jin $D/a.jin; chmod 664 $D/a.jin
printf '\n' >> $D/a.jin; uv run jin fmt $D/a.jin >/dev/null; ls -l $D/a.jin   # → -rw-rw-r--
mkdir -p $D/ro; cp examples/researcher/researcher.jin $D/ro/b.jin
printf '\n' >> $D/ro/b.jin; chmod 555 $D/ro
uv run jin fmt $D/ro/b.jin; echo "EXIT=$?"   # → 0 + 「原子的に差し替えできません」の警告
chmod 755 $D/ro; rm -rf $D
```

### 非空虚性の実測（ラウンド 2 分）

```bash
uv run python delivery/20260904-1445-jin/fix-round-1-mutations/mutate3.py   # 21 パターン
```

ラウンド 1 の `mutate.py`（32）/ `mutate2.py`（11）と合わせて **64 パターン**。
スクリプトは pytest の「テストが 1 件も収集されなかった」（exit 5）を赤と誤認しないようにしてある。

## 修正ラウンド 3 の再現

```bash
# 全体
UV_LOCKED=1 uv run pytest --color=no          # 496 passed
uv run ruff check . && uv run ruff format --check . && uv run lint-imports

# R-1 / R-2 の回帰テストだけ
uv run pytest packages/jin-cli/tests/test_cli.py -k "symlink or write_in_place or write_atomically or collect_does_not_filter"

# 変異（ラウンド 3 分・6 件すべて赤になること）
uv run python delivery/20260904-1445-jin/fix-round-1-mutations/mutate4.py

# 変異（ラウンド 1・2 分の再実測。合計 70 件）
for f in mutate.py mutate2.py mutate3.py mutate4.py; do
  uv run python delivery/20260904-1445-jin/fix-round-1-mutations/$f
done

# ELOOP の実測（macOS / Linux とも errno 62）
python3 -c "
import os, errno, tempfile, pathlib
d = pathlib.Path(tempfile.mkdtemp()); (d/'victim.txt').write_text('victim')
(d/'lnk').symlink_to(d/'victim.txt')
try:
    os.open(d/'lnk', os.O_WRONLY|os.O_TRUNC|os.O_CREAT|os.O_NOFOLLOW, 0o666)
except OSError as e:
    print(e.errno, errno.errorcode.get(e.errno))
print((d/'victim.txt').read_text())"
```

### ラウンド 3 追記（安全宣言の機械固定）

```bash
uv run pytest packages/jin-cli/tests/test_cli.py -k guard
# 嘘を書き戻すと落ちること（mutate4.py の R-2-lie / R-2-ghost / R-2-scanner / R-2-selfmatch）
uv run python delivery/20260904-1445-jin/fix-round-1-mutations/mutate4.py   # 10/10 赤
```

## 修正ラウンド 4 の再現

```bash
UV_LOCKED=1 uv run pytest --color=no                       # 505 passed
uv run pytest packages/jin-cli/tests/test_cli.py -k "mkstemp_fails or truncating_write or disappears or write_itself_fails or keyboard_interrupt"

# 変異（ハーネスは stale .pyc 対策済み。4 本合計 86 件がすべて赤）
for f in mutate.py mutate2.py mutate3.py mutate4.py; do
  uv run python delivery/20260904-1445-jin/fix-round-1-mutations/$f
done
```

**変異ハーネスの偽 green（ラウンド 4 で発見・修正済み）**: `.pyc` の無効化は
「元ファイルの mtime（秒）+ サイズ」で行われる。連続する 2 変異が同一サイズのファイルを生み
同じ秒内に走ると、2 本目が 1 本目のバイトコードを再利用して緑になる。
4 本すべてに `__pycache__` の毎回削除 + `PYTHONDONTWRITEBYTECODE=1` を入れてある。
自作の変異を足すときはこの経路を通すこと（`_run_pytest`）。

## 修正ラウンド 5（V-1）の再現

`_write_in_place` の書き込み途中失敗は、退避路（書けないディレクトリ）に入ってから
**書き込みモードで開いたハンドル**の `write` を失敗させると決定的に再現できる。
`os.write` のモックでは該当経路に当たらない（実装は `os.fdopen` のハンドル越しに書く）。

```bash
uv run pytest packages/jin-cli/tests/test_cli.py -k "content_was_lost or content_is_intact or diagnostic_failure_still"
uv run python delivery/20260904-1445-jin/fix-round-1-mutations/mutate4.py   # 24/24 赤
```

修正前の出力（欠陥）:

```
w/a.jin: 書き込めません（w/a.jin: ディスクの空き容量がありません（No space left on device））
整形できませんでした（診断を先に直してください）: 1 件
整形後のファイルの中身の長さ: 0 バイト
```

修正後:

```
w/a.jin: 原子的でない書き込みの途中で失敗したため、ファイルの内容が失われています。バックアップから復元してください（ディスクの空き容量がありません（No space left on device））
**書き込みの途中で失敗し、ファイルの内容が失われました。バックアップから復元してください**: 1 件
```
