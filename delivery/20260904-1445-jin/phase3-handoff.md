# Jin Phase 3（jin-render）への申し送り

作成: 実装ラウンド 2（Phase 2 / Issue #3）／ 2026-09-04
前提: `phase2-handoff.md` の §7「運用」と §8「守るべき原則」は**そのまま生き続ける**。ここはその差分。

## 0. Phase 2 で実際にやったこと

| design.yaml Phase 2 machine 条件 | 状態 | 実装した検査 |
|---|---|---|
| 生成 agent.py のスナップショット（syrupy）が examples 2 本で安定 | 満たした | `test_codegen.py::test_generated_agent_py_snapshot` |
| 生成モジュールを import して ADK オブジェクト木を検証（tools の型 / sub_agents の名前 / callback の同一性） | 満たした | `test_object_tree.py` |
| 生成プロジェクトの構造が §3.1 と一致 | 満たした | `test_project.py::test_directory_structure_matches_the_requirement`（**ちょうど 3 ファイル**） |
| google-adk 2.8.0 に対する import テスト（NFR-VER-001） | 満たした | `test_object_tree.py::test_every_example_imports_under_the_pinned_adk` / `test_adk_surface.py` |
| `jin run --model fake` が examples 2 本で最後まで通り exit 0 | 満たした | `test_run.py::test_the_cli_exits_zero` |
| トレース JSONL の全行が §3.4 のスキーマを満たす | 満たした | `test_run.py::test_every_trace_line_matches_the_schema` |
| トレース JSONL の全 pointer がモデルに解決できる | 満たした | `test_run.py::test_every_trace_pointer_resolves_against_the_model` |
| ADK に対応物のない Jin 構造がコンパイル時エラー（NFR-FAIL-001） | 満たした | `test_compile_errors.py` + `tests/fixtures/adk-gaps/` 15 本 |

human_only（実 `adk run` / `adk web` での対話動作）は **`not_run`**。実施していない。§4 を読むこと。

**検査が落ちることも確かめた**（申し送り §8-3）。9 種の変異（`AgentTool` の走査を消す /
`keyword.iskeyword` を消す / `max_iterations` を `max` にする / セッション種まきを消す /
`.env` のキー名を変える / `core` の pointer をやめる / 判定エージェントを先頭に置く /
`out: true` 2 件の検査を殺す / `.env.example` を書かない）を入れて**全部赤になる**ことを確認した。
`__pycache__` を毎回削除し `PYTHONDONTWRITEBYTECODE=1` で走らせている（§8-3 の罠）。

## 1. Phase 3 で**必ず赤くなる**テストと、その正しい直し方

### 1.1 `test_later_packages_do_not_exist_yet[jin_render]`

`tests/contract/test_dependency_direction.py`。`packages/jin-render` を作った瞬間に赤くなる。
**直すのはこの 1 行ではなく `CLAUDE.md` の「パッケージを足すときのチェックリスト」の 7 項目。**
Phase 2 では 6 項目だったが **7 項目に増えている**（§2）。

### 1.2 `layers` を素朴な直列にしてはいけない（**Phase 3 が本番**）

現在の `layers` は `["jin_cli", "jin_adk", "jin_core"]`。`jin_render` を足すときは

```toml
layers = ["jin_cli", "jin_adk | jin_render", "jin_core"]
```

と **1 要素に `|` 区切り**で並べる。`test_layers_contract_keeps_sibling_packages_in_one_element` は
「両方が宣言に現れたとき」しか判定しないので、`jin_render` が無い今は**素通りしている**
（`independence_violations` が `len(indexes) < 2` で飛ばす）。Phase 3 で初めて本当に効く。
素朴な直列にすると `jin_adk → jin_render` を静かに許すことになる（wiring W-05 の実測）。

### 1.3 forbidden 契約に `jin_render` を足す（2 箇所）

- 「`jin_core` は google-adk に依存しない」の `source_modules` に **`jin_render` を足す**
  （design.yaml のルール 4「jin-render は google-adk に依存しない」）。
  **`jin_adk` は足さない**（ADK の語彙が現れてよい唯一のパッケージ。pyproject.toml にコメント済み）
- 「ref の解決実装は jin_cli に閉じる」の `source_modules` にも足す
  （`test_resolver_isolation_contract_covers_every_package_but_the_cli` が強制する）

### 1.4 `test_the_only_module_importing_importlib_is_the_cli_resolver`

現在の期待値は **2 件**:

```python
assert offenders == [
    "packages/jin-adk/src/jin_adk/loader.py",
    "packages/jin-cli/src/jin_cli/resolver.py",
]
```

**`jin_render` をここに足してはいけない。** レンダラは意味モデルしか読まない（要件書 §4
「入力は意味モデル。ファイルを直接読まない」）ので、`importlib` を使う理由が無い。
使いたくなったら設計が曲がっている。

## 2. パッケージ追加時に同時に直すのは **7 箇所**（1 つ増えた）

7 番目は Phase 2 で実際に踏んだ罠:

> **共有 fixture は `packages/<name>/conftest.py`（`tests/` の 1 つ上）に置く。**

`packages/<name>/tests/conftest.py` に置くと、**スイート全体が collection error で止まる**:

```
ValueError: Plugin already registered under a different name:
  packages/jin-adk/tests/conftest.py=<module 'tests.conftest' from 'tests/conftest.py'>
```

理由: `packages/<name>/tests/__init__.py` は必須（A-1）なので、そのディレクトリの Python 上の
名前は `tests` になる。リポジトリ直下の `tests/` も同じ `tests` なので、
`consider_namespace_packages = true` の下ではどちらの `conftest.py` も `tests.conftest` に解決される。

**厄介なのは、パッケージ単体で走らせると緑になること**（リポジトリ直下の `tests/` を収集しないので
衝突しない）。`uv run pytest` で初めて全体が止まる。同じ理由でテストモジュールからの
`from .conftest import ...` も禁止（`tests` パッケージがどちらを指すかが収集順で変わる）。
共有したいものは**すべて fixture として渡す**。

これは `tests/contract/test_packaging_contract.py` の
`test_no_package_puts_conftest_inside_its_tests_package` /
`test_no_test_module_imports_its_conftest_relatively` が機械で固定してある。

## 3. Python は 3.13。**3.14 に上げてはいけない**

`.python-version` を `3.14` から `3.13` に下げた。google-adk 2.8.0 が Python 3.14 で
import できない（pydantic 2.13.5 の `eval_type_backport` が `AssertionError`。
3.14 対応の pydantic は 2026-09-04 時点で存在しない）。実測表は
`decision-conformance.md` §2.14。上げ直すときは
`from google.adk.agents import LlmAgent` を実際に通してから確定すること。

`packages/jin-adk/tests/test_adk_surface.py::test_the_installed_adk_is_the_pinned_version` が
入っている google-adk の版（2.8.x）を固定しているので、版と Python の組は同時に見直す。

## 4. **人間へ上げる残件**

### 4.1 human_only の `not_run`（design.yaml Phase 2）

> 実 `adk run` / `adk web` での対話動作。NFR-TEST-001 によりテストはネットワーク・API キー不要が
> 要件のため CI では実行しない。

**実施していない。** PR レビューで人が確認すること。手順:

```bash
uv run jin build examples/researcher/researcher.jin --out /tmp/jin-out
cp /tmp/jin-out/.env.example /tmp/jin-out/.env   # 値を入れる
PYTHONPATH=examples/researcher adk run /tmp/jin-out/Researcher
```

`PYTHONPATH` が要るのは、`researcher.jin` の `ref` が指す `research` パッケージが
`examples/researcher/` の下にあるため（`jin run` は `.jin` の隣を `sys.path` に足すが、
`adk run` は足さない）。

**researcher は現状 1 ターン目で `KeyError: findings` になる見込み**（§4.2）。
その 1 点を除いて動くかどうかを見てほしい。pipeline のほうは `{state_key}` が
上流 circle の `output_key` を参照するので、2 番目以降の circle は値が入る。

### 4.2 **新しい未決 `DP-JIN-STATE-SEED-01`**（Phase 2 で起票）

`instruction` の `{state_key}` を、生成された ADK プロジェクトが**空セッション**で
展開できるようにするかどうか。

実測: google-adk 2.8.0 の `google/adk/utils/instructions_utils.py` の `_replace_match` は、
`{key}` の `key` が `session.state` に**無い**と `KeyError` を投げる（`{key?}` と書けば空文字）。
`examples/researcher` の rune は自分の `output_key` である `{findings}` を参照するので、
1 ターン目で必ず踏む。

- **`jin run` 側は種まきして通してある**（`jin_adk.run.initial_state`。値は空文字。
  型ごとのゼロ値を当てると要件書に無い値の捏造になる）。machine 条件 5 は満たしている
- **生成コードには何も出していない。** 要件書 §3.3 が「`out: true` 以外の `state[]` は
  静的検証とエディタ表示のための宣言」と定めているため。その結果 `adk run` は空のセッションで
  始まり、同じ `KeyError` に当たる
- 選択肢: (a) 生成物に state 種まきの `before_agent_callback` を出す（§3.3 を緩める）/
  (b) rune 側に `{key?}` を書かせる（§2.1 の「テンプレートは透過」を緩める。JIN050 の扱いも要検討）/
  (c) 現状維持で `adk run` の前に人がセッションを用意する
- **実装者は決めない。** `implementation-plan.json` の `undecided[]` / `undecided_details[]` に
  起票済み。**`docs/pending-decisions.md` は自動生成なので親が再生成すること**
  （`pending-decisions-generator`）

### 4.3 `phase2-handoff.md` §6 の 2 件（**Phase 4 着手の直前**）

そのまま生きている。親の責務として人間へ提示すること。

- `DP-JIN-RESOLVE-ISOLATION-01`（`--resolve` の同一プロセス import が診断を消しうる）
- `DP-REVIEW-JIN-008`（`check_text` が最悪 8.4 秒。§6.4 の「1000 行以下で 1 秒以内」を Phase 4 で実測）

### 4.4 `DP-REVIEW-JIN-005`（ランディレクトリのハードコード）

`tests/contract/test_packaging_contract.py` が `delivery/20260904-1445-jin/design.yaml` を
直接指したまま。**Phase 2 でも直していない**（Phase 2 のスコープ外なので触らなかった）。
次のランで別タイムスタンプが切られると壊れる。直すときはパスの貼り替えではなく、
`delivery/` を走査して辞書順最新の `*-jin` を選ぶ形にすること。

## 5. Phase 3 が使える Phase 2 の資産

- **pointer 対応表** `jin_adk.pointers.PointerMap`: ADK 識別子 → JSON Pointer（ADR-009）。
  レンダラの `data-jin` と**同じ鍵**なので、トレースオーバーレイ（要件書 §4 の `trace` / `upto`）は
  この pointer をそのまま使える
- **トレース JSONL**: `seq` は 1 から**連番**（`upto` で切れる）。`kind` は 5 種、
  `pointer` は必ずモデルに解決できる（`test_run.py` が examples 2 本で毎回確かめている）。
  スキーマ表は `docs/spec/adk-mapping.md` §4.3
- **`examples/researcher/research/`**: `ref` が指す先の雛形（ネットワークに出ない）。
  Phase 3 のレンダリング検証で `.jin` を実行したくなったらそのまま使える

## 6. Phase 2 で新たに確定した値（根拠は `decision-conformance.md`）

| 節 | 内容 |
|---|---|
| §2.13 | `.env.example` の 4 キー（DP-COMMON-15。google-adk 2.8.0 のソース実測） |
| §2.14 | Python 3.13 への固定（google-adk が 3.14 で import できない） |
| §2.15 | `builtin` に許す 9 名前（`google.adk.tools` のインスタンス実測） |
| §2.16 | 生成コードの変数名が衝突したときの別名規則 |
