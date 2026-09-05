# Stage 5 security review — Phase 2 修正ラウンド 1（defect-gone 判定）

- 対象: `feat/jin-phase2-adk` 作業ツリー（修正ラウンド 1 反映後・2026-09-05）。隔離コピーを作り直して実測
  （`git ls-files --cached --others` → scratchpad、`__pycache__` 除去、`PYTHONPATH=<copy>/packages/*/src`、
  `jin_adk.__file__` / `jin_cli.__file__` がコピー側を指すことを確認）。**実ツリーはこのレポート以外変更していない**
- baseline: **770 passed**（`-p no:cacheprovider`）
- 判定対象: fix-now の 001 / 002 / 003 / 004 / 005 / 006 / 007 / 008 / 010 / 011 / 014 / 016
- 参照: `implementation-notes.md` P2-R1.1 A-2 / A-3、P2-R1.7、`decision-conformance.md` §2.19 / §2.22 / §2.23 / §4.1、
  `implementation-plan.json` の `DP-IMPL-JIN-P2-SYSPATH-01`（chosen = `sys.path.append(cwd)`）
- **計測方法の訂正（自分の前回分）**: 前回は `python -c` / `python -` で CLI を呼んでいたため `sys.path[0] == ''`（cwd）が
  常に入っており、F-S-P2-003 の「cwd が先頭」を CLI の `insert(0)` だけに帰していた点は計測として不純だった
  （実装者の別プロセス契約テストで `insert(0)` → exit 1 / `append` → exit 0 が独立に確認されているので結論は変わらない）。
  本ラウンドは **`python -P`**（cwd を自動追加しない）で全部やり直し、`insert(0)` に戻した手動変異でも再現を取った（§3）

## 0. 要約

| finding | 判定 | 一言 |
|---|---|---|
| F-S-P2-001 ファイル名 → ヘッダ注入 | **defect-gone** | CLI は exit 2 で拒み、ライブラリ経路でも `# source: "x\nimport os..."` の 1 行リテラル。AST に `Expr` / `Import`（注入分）無し |
| F-S-P2-002 NFKC で `root_agent` 乗っ取り | **defect-gone** | `ｒｏｏｔ＿ａｇｅｎｔ` / `ｊｓｏｎ` / `ＬｌｍＡｇｅｎｔ` / `ｕｓｅｒ` / root 自身、すべて BuildError。`write_project` 直呼びも `WriteRefused`。全コードポイント走査で `isidentifier() ∧ NFKC 安定` と `compile()` の食い違い 0 件 |
| F-S-P2-003 cwd を `sys.path` 先頭 | **部分 defect-gone（残存あり → F-S-P2-101）** | `append` で **インストール済み**の名前（`authlib`）は差し替え不能になった。しかし **未インストール**の任意依存（`anthropic` / `openai` / `a2a` / `bcrypt` / `simplejson` / `chardet` / `socks`）を ADK は**通常の実行経路で毎回** import しようとするので、cwd の `anthropic/` は `ref` 無しの `pipeline.jin --model fake` でも実行される。§2.19 の残存記述（「`_resolve_builtin` が不正な builtin 名を受けたとき」）は狭すぎる |
| F-S-P2-004 `OSError` トレースバック | **defect-gone** | 通常ファイル / dangling symlink / `/proc/nope` / ENAMETOOLONG / EACCES / `<root>` が通常ファイル / `.env.example` がディレクトリ、すべて `WriteRefused` の 1 行・exit 1 |
| F-S-P2-005 surrogateescape で 0 バイト | **defect-gone** | CLI は exit 2。ライブラリ経路でも encode が open より前で、`bad\udcff.jin` は `# source: "bad\udcff.jin"` として書けて import できる。新規ファイルの片付けは実装者のテストと変異 `BUILD-cleanup-only-on-refusal`（赤を再実測）に依る |
| F-S-P2-006 `--trace` の既存内容 | **defect-gone** | BuildError / RunError（import）で既存内容が無傷。成功時は置換、0 行成功も `finish()` で切り詰め |
| F-S-P2-007 `<out>` 自体の symlink | **defect-gone** | `O_NOFOLLOW` + ENOTDIR 分岐で拒否（`--force` でも）。`elsewhere` は空のまま |
| F-S-P2-008 トレース 0644 | **defect-gone** | 新規 0600。既存は変えない（§2.22 のとおり・実測 644 のまま） |
| F-S-P2-010 `guard:` の抜け | **defect-gone（記法の限界 1 件は受容）** | `hazard:` タグで E-C 型を分離、`_open_trace -> os.O_NOFOLLOW` / `_truncate -> os.ftruncate` を追加。`except BaseException` は裸名なので記法上書けないまま（テスト + 変異で代替） |
| F-S-P2-011 ハーネスの偽赤 | **defect-gone** | `returncode == 1 ∧ "failed"`、自己隔離コピー（`jin_adk.__file__` を印字して確認）。59/59 を再実測（§8） |
| F-S-P2-014 U+2028 | **defect-gone** | stdout で `\u2028` に置換（実測） |
| F-S-P2-016 ファイル名の `_safe` 抜け | **defect-gone** | 存在しない改行 / ESC 入りパスも `\u000a` / `\u001b` で表示 |

**新規（修正が持ち込んだ / 修正で見えた）**

| ID | severity | conf | 一言 |
|---|---|---|---|
| **F-S-P2-102** | **High** | 97 | **回帰（S2 型・fail-open）**: `ref` のツール関数が実行中に `sys.exit(0)` すると **exit 0**。F-C-P2-019 の修正で `asyncio.run` が `runtime.run_model` の `except BaseException` の外（CLI）へ出たため、asyncio が再送出する `SystemExit` を誰も捕まえない。前回は exit 1 だった |
| **F-S-P2-101** | Medium | 95 | F-S-P2-003 の残存が通常経路で成立: cwd の `anthropic/` が `pipeline.jin --model fake` で走る。契約テストはインストール済みの名前しか見ていない |
| F-S-P2-103 | Low | 90 | 埋め込み `_state_matches` が使う組み込み名（`isinstance` / `str` / `bool` / `int` / `float` / `ValueError` / `object`）が `RESERVED_NAMES` に無い。circle 名 `str` 等で実行時 `TypeError`（fail-closed だが BuildError にならない） |
| F-S-P2-104 | Low | 92 | `--force` で `ftruncate` 後の `os.write` が失敗（ENOSPC 注入）すると既存 `agent.py` が 0 バイト。V-1 の残存を実測。片付けは新規分だけで既存内容は戻らず、メッセージも失ったことを言わない |

---

## 1. F-S-P2-001 / 016 / 005（ファイル名の入口）— defect-gone

```
$ FNAME=$'x\nimport os; os.system("echo PWNED-BY-FILENAME 1>&2")\n#.jin'; cp $S/examples/pipeline/pipeline.jin "$FNAME"
$ jin build "$FNAME" --out out; echo "build exit=$?"
ファイル名に制御文字か不正なバイト列が含まれています: x
import os; os.system("echo PWNED-BY-FILENAME 1>&2")
#.jin（…）
build exit=2                                  # out/ は作られない
$ jin run "$FNAME" go --model fake; echo "run exit=$?"
ファイル名に制御文字か不正なバイト列が含まれています: …
run exit=2                                    # PWNED は出ない
```

ライブラリ経路（CLI の入口検査を迂回して `generate(source_name=...)` を直接呼ぶ）:

```
>>> generate(model, source_name='x\nimport os; os.system("id")\n#.jin').agent_py.splitlines()[1]
'# source: "x\\nimport os; os.system(\\"id\\")\\n#.jin"'
>>> sorted({type(n).__name__ for n in ast.parse(agent_py).body})
['Assign', 'ClassDef', 'FunctionDef', 'Import', 'ImportFrom']     # Import は has_exit の `import json`。Expr 無し
```

F-S-P2-016（存在しないパス・ESC 入り）:

```
$ jin build $'nope\x1b[2K\nfake.jin' --out out
ファイル名に制御文字か不正なバイト列が含まれています: nope\u001b[2K\u000afake.jin（…）    exit=2
```

F-S-P2-005（`bad\xff.jin`）:

```
$ jin build "$(printf 'bad\xff.jin')" --out out            → 「…: bad\udcff.jin（…）」 exit=2、out/ 無し
$ jin build pipeline.jin --out out; jin build "$(printf 'bad\xff.jin')" --out out --force   → exit=2、agent.py は 4252 バイトのまま
$ jin run "$(printf 'bad\xff.jin')" go --model fake         → exit=2
>>> p = generate(model, source_name="bad\udcff.jin"); write_project(p, d)   # ライブラリ経路
header line: # source: "bad\udcff.jin"   written: ['__init__.py', 'agent.py', '.env.example']   valid utf-8   import ok: Pipeline
```

`_has_unsafe_chars` の集合（C0 / DEL / C1 / U+2028 / U+2029 / サロゲート）は `_CONTROL_TRANSLATION` と同じ辞書を参照しており、
`.jin` 本文の `_reject_bad_chars`（C0 / DEL / C1 / サロゲート）より広い（U+2028 / U+2029 を足している）。妥当。
`py_literal` の `_EXTRA_ESCAPES` にサロゲートを足した判断: 生成物は常に UTF-8 で書けるようになり、`\udcXX` エスケープは
`ast.literal_eval` で元のサロゲートに戻る（往復テストあり）。`.jin` 本文は JIN002 が先に弾くので、実際に `\udcXX` が生成物に
残るのは CLI を迂回した `source_name` のヘッダコメントだけ。**是**（第二層として正しく、生成物が壊れない）。

## 2. F-S-P2-002（NFKC）— defect-gone

```
$ for f in nfkc json llm user root; do jin build $f.jin --out out; done
nfkc.jin: circle 名 'ｒｏｏｔ＿ａｇｅｎｔ' は NFKC 正規形ではありません。…    exit=1
json.jin: circle 名 'ｊｓｏｎ' は …                                          exit=1
llm.jin:  circle 名 'ＬｌｍＡｇｅｎｔ' は …                                  exit=1
user.jin: circle 名 'ｕｓｅｒ' は …                                          exit=1
root.jin: circle 名 'Ｍａｉｎ' は …（root 自身）                              exit=1
$ jin run nfkc.jin hi --model fake                                            exit=1
>>> write_project(GeneratedProject(root_name="ｒｏｏｔ＿ａｇｅｎｔ", ...), d)   → WriteRefused: root 'ｒｏｏｔ＿ａｇｅｎｔ' はディレクトリ名に使えません
```

迂回の探索:

| 経路 | 結果 |
|---|---|
| `_check_root_name`（build）にも NFKC | 入っている（上の `write_project` 直呼び） |
| `ref` の module / callable 名 | `PYTHON_REF` が ASCII 限定なので NFKC 無関係 |
| `builtin` 名 | `name in adk_tools.__all__` の文字列一致なので全角は BuildError |
| `flow.exit.key` / `state[].name` / `tools[].name` | 文字列リテラル（`py_literal`）としてしか出ないので識別子の問題なし |
| `isidentifier()` ∧ NFKC 安定 だが Python の `compile()` が別の束縛をする文字 | 全コードポイント（U+0080〜U+10FFFF、先頭文字 137,662 個 + 継続文字 U+0080〜U+2FFFF）を走査して **0 件**。XID_Start / XID_Continue は NFKC 閉包で定義されているので理論どおり |
| `a` と `ａ` の 2 circle | `ａ` が BuildError（正規形でない）。前回は ADK の import 時検査に頼っていたが、生成前に落ちるようになった |
| 埋め込みテンプレートが使う**組み込み名** | `RESERVED_NAMES` に無い（→ F-S-P2-103・Low） |

## 3. F-S-P2-003（cwd）— 部分 defect-gone、残存は F-S-P2-101

`-P` で `sys.path` に cwd が入らないことを確認したうえで（`sys.path[0]` は `PYTHONPATH` の先頭）:

```
$ ls; cat authlib/__init__.py                  # ADK が実行中に遅延 import する・インストール済み
$ jin run $S/examples/pipeline/pipeline.jin go --model fake 2>&1 | grep -c "SHADOW authlib"
0                                              # append: 本物の authlib が先に解決される  exit=0
--- 隔離コピーの main.py を insert(0, cwd) に戻して同じ入力（手動変異）
SHADOW authlib FROM CWD LOADED                 # insert(0): cwd 側が走る（前回の finding の再現）  exit=1
--- 戻す
```

契約テスト `test_cwd_cannot_shadow_an_installed_package_in_a_real_process` と変異 `CLI-cwd-first` も赤を再確認。
**インストール済みの名前**については塞がった。残存は §4 の F-S-P2-101。

## 4. 新規

### F-S-P2-102 【High / confidence 97】ツール関数の `sys.exit(0)` が exit 0 になる（S2 型 fail-open の**回帰**）

- 前回（ラウンド 0）の実測: ツール実行中の `sys.exit(0)` → `実行に失敗しました（SystemExit: 0）` **exit 1**
  （`runtime.run_model` が `asyncio.run(...)` を自分の `except BaseException` の中で呼んでいた）
- 修正ラウンド 1（F-C-P2-019）で `run_model_async` を公開し、CLI が `asyncio.run(run_model_async(...))` を呼ぶ形に変えた。
  `run_model_async` の中の `except BaseException`（`runtime.py:237`）はコルーチン内にあるが、**asyncio は `SystemExit` /
  `KeyboardInterrupt` をタスクの結果にせず、メインタスクを cancel してからイベントループの外へ再送出する**。
  コルーチン側が見るのは `CancelledError` で、それを `RunError` に変えても、`asyncio.run` 自体が元の `SystemExit(0)` を
  投げ直す。CLI の `except RunError` は当たらず、`SystemExit(0)` が typer に渡って **exit 0**
- 最小再現（Python 3.14・純粋 asyncio）:

```
async def inner(): sys.exit(0)
async def main():
    try: await asyncio.create_task(inner())
    except BaseException as exc: raise RuntimeError(f"converted from {type(exc).__name__}") from exc
asyncio.run(main())
→ RuntimeError: converted from CancelledError  （コルーチン側）
→ asyncio.run re-raised SystemExit 0           （外側。RuntimeError は握り潰される）
```

- jin での再現（台本つき FakeLlm でツールを呼ばせる。`ex/__init__.py` の `fn` が `sys.exit(0)`）:

```
$ cat runexit.py
sys.argv = ["jin", "run", "exitref.jin", "go", "--model", "fake", "--trace", "t.jsonl"]
m.FakeLlm = lambda: orig(responses=[f.FakeToolCall(name="fn", args={"query": "q"}), "done"])
app()
$ python -P runexit.py; echo "REAL exit=$?"
[1] R tool fn /circles/0/tools/0 {"query": "q"}
    ... asyncio.exceptions.CancelledError
    The above exception was the direct cause of the following exception:
    ... runtime.py, line 239, in run_model_async  raise RunError(
jin_adk.runtime.RunError: 実行に失敗しました（CancelledError: ）。--trace で直前のイベントを確認し…
REAL exit=0                                     ← トレースバックを出しながら成功扱い
```

比較: 同じ位置で `RuntimeError("boom")` → `実行に失敗しました（RuntimeError: boom）` exit 1（正常）。`os._exit(0)` → exit 0（Phase 1 §4 で受容済みの残存・変化なし）。

食い違う主張: `runtime.py` モジュール docstring（`:15`「`sys.exit(0)` で成功扱いにしない・Phase 1 の S2 と同型」）と
`decision-conformance.md` §4.1「import 中の `SystemExit` を成功扱いにしない」（import 中は今も正しい。**実行中**が抜けた）。
CLAUDE.md / README には `SystemExit` に関する主張は無い（grep 0 件）。
既存テスト `test_system_exit_in_generated_code_import_is_not_swallowed` は import 時だけを見るので緑のまま。

修正案:
1. CLI `run`: `asyncio.run(...)` を `try` で包み、`except KeyboardInterrupt: raise` / `except SystemExit as exc:`（または
   `BaseException`）→ `実行に失敗しました（SystemExit: {exc.code}）` を stderr に出して exit 1。
   `runtime.run_model`（同期版）に同じ包みを入れ、CLI はそちらを使うのでもよい（Phase 4 の pygls は `run_model_async` を使う想定なので、
   **`run_model_async` の docstring に「`SystemExit` は asyncio がループの外へ再送出するので、呼び出し側が `asyncio.run` を包むこと」を明記**）
2. テスト: `test_build_run.py` に「ツールが `sys.exit(0)` → exit 1・`SystemExit` が stderr に見える・トレースバック無し」を追加
   （台本つき FakeLlm はテスト側で `monkeypatch.setattr(jin_cli.main, "FakeLlm", ...)`）。`test_runtime.py` には
   `run_model`（同期）で同じ入力 → `RunError` を追加
3. 変異 `RUN-swallow-systemexit-at-runtime`（CLI の `except SystemExit` を消す）を `mutate_p2.py` に追加

### F-S-P2-101 【Medium / confidence 95】`append` にしても、ADK が**通常経路**で import を試みる未インストール名は cwd から走る

- `google/adk/flows/llm_flows/contents.py:58` `_id_pairing_model_types` が **LLM リクエストのたび**に
  `from ...models.anthropic_llm import AnthropicLlm` を試み（docstring に「各 provider は optional。無ければ飛ばす」）、
  `anthropic_llm.py:39` の `from anthropic import AsyncAnthropic` が `anthropic` を探す。未インストールなので site-packages に無く、
  **末尾に足した cwd で解決される**
- 同じ経路で `openai` も試みる。`builtins.__import__` を差し替えて数えた「CLI 起動後に import に失敗した（= 未インストールで、
  cwd に同名があれば走る）トップレベル名」: `anthropic` `openai` `a2a` `bcrypt` `simplejson` `chardet` `socks`（+ ADK 内部の相対名）

```
$ ls                                            # authlib/ mcp/ anthropic/（各 __init__.py は SHADOW を印字するだけ）
$ jin run $S/examples/pipeline/pipeline.jin go --model fake      # ref 無し・fake・append 後
SHADOW anthropic FROM CWD LOADED
    google/adk/agents/llm_agent.py:576 _run_async_impl
    google/adk/flows/llm_flows/base_llm_flow.py:1278 run_async
    google/adk/flows/llm_flows/base_llm_flow.py:1298 _run_one_step_async
    google/adk/flows/llm_flows/base_llm_flow.py:1411 _preprocess_async
    google/adk/flows/llm_flows/contents.py:100 run_async
    google/adk/flows/llm_flows/contents.py:58 _id_pairing_model_types
    google/adk/models/anthropic_llm.py:39 <module>
11 イベント（session: jin）                     exit=0
$ jin run researcher.jin go --model fake        → SHADOW anthropic FROM CWD LOADED   exit=0
$ jin run badbuiltin.jin go --model fake        → SHADOW mcp FROM CWD LOADED（§2.19 が挙げている経路）exit=1
$ jin run claude.jin go                         → SHADOW anthropic FROM CWD LOADED   exit=1
$ jin build pipeline.jin --out out              → SHADOW 0 件（build は cwd を足さない）
```

つまり §2.19 の残存記述「`_resolve_builtin` が不正な builtin 名を受けたとき」は狭く、**LlmAgent が 1 つでもあれば毎回**踏む。
契約テスト `test_cwd_cannot_shadow_an_installed_package_in_a_real_process` はインストール済みの `authlib` しか置いていない。
同じ形（`raise RuntimeError('SHADOW …')`）の `anthropic/__init__.py` を cwd に置いて実測すると **exit 1**
（`実行に失敗しました（RuntimeError: SHADOW anthropic FROM CWD LOADED）`。ADK の `except ImportError` を素通りする）= 契約テストに
`anthropic` 版を足せば今は赤になる（残存が実在する）。`.jin` 作者と cwd の支配者が別人でありうる点は前回と同じで、
`--model fake`（README が「ネットワークに出ない」と案内する経路）でも成立する。

修正案（推奨は 1）:
1. cwd を足すのを**生成モジュールの import の間だけ**にする: `run_model_async`（または `load_generated`）に `extra_sys_path: str | None`
   を持たせ、`_import_agent_module` の前に `sys.path.append`、直後に `finally` で取り除く。`ref` のモジュールは生成モジュールの
   import 時に読み込まれて `sys.modules` に残るので、その後 Runner が走るときに cwd は要らない。`generate()` の `_resolve_builtin` も
   cwd 追加前に済む。CLI の `sys.path.append(cwd)` は消える（`hazard:` は runtime 側へ移す）。残存は「`ref` 先モジュールが
   **自分の関数の中で**遅延 import する名前」だけになり、それは `.jin` 作者と同じ相手が書くコードなので §2.19 の元の論法が
   そこには当てはまる。**追従が要るもの**: `test_run_adds_cwd_to_sys_path` は実行後も `str(tmp_path) in sys.path` を
   assert している（`test_build_run.py:320`）ので、import の間だけ足して外す形にするとこのテストの書き換えが要る（前ラウンドの 003 と同型の追従漏れに注意）。
   残る窓: 生成モジュールの import 中に `from google.adk.tools import <builtin>` が `google.adk.tools.__getattr__` の遅延 import を踏み、
   その先が任意依存（`mcp` など）を探すことはありうる。`builtin` を書けるのは `.jin` 作者なので、これも §2.19 の元の論法の範囲内
2. 1 が Phase 4 との兼ね合いで難しければ、少なくとも (a) §2.19 / CLAUDE.md / README の残存記述を「LlmAgent があれば毎回 `anthropic` / `openai`
   等を探す」に直し、(b) 契約テストに未インストール名（`anthropic`）版を**期待値 = 残存**として足すか、1 を採った時点で緑になる形で足す

### F-S-P2-103 【Low / confidence 90】埋め込みテンプレートが使う組み込み名が `RESERVED_NAMES` に無い

`agent.py.j2` の `_state_matches` は `isinstance` / `str` / `bool` / `int` / `float` / `ValueError` / `object` を使うが、
これらは `RESERVED_NAMES` に無く、circle 名として通る。生成コードのモジュールスコープで組み込みを上書きするので:

```
circle 'str'        → 実行に失敗しました（TypeError: isinstance() arg 2 must be a type, …）  exit=1
circle 'isinstance' → 実行に失敗しました（TypeError: 'LlmAgent' object is not callable）        exit=1
circle 'ValueError' + equals: true → TypeError: catching classes that do not inherit from BaseException …  exit=1
circle 'ValueError' + equals: "yes" → exit 0（json.loads 経路を通らないので偶然動く）
circle 'object'     → exit 0（型注釈でしか使われない）
```

全部 fail-closed（exit 1）で静かに間違う経路は無いが、`jin check` / `jin build` は通り、`jin run` で初めて意味不明な `TypeError` になる
（NFR-FAIL-001 の「黙って落とさず何が悪いか」から外れる）。修正: `RESERVED_NAMES` に 7 名を足す（`test_jin_strings_cannot_inject_statements`
と同じ形で、テンプレートが参照する `ast.Name` の集合 ⊆ `RESERVED_NAMES ∪ locals` を固定するテストにすると将来のテンプレート変更にも効く）。

### F-S-P2-104 【Low / confidence 92】`--force` で `ftruncate` 後の書き込み失敗は既存内容を戻せない（V-1 の残存・実測）

```
>>> write_project(p, d); write_project(p, d, force=True)   # os.write を 2 回目の呼び出しで ENOSPC にする
WriteRefused: /tmp/… への書き込みに失敗しました: No space left on device
{'Pipeline/__init__.py': (91, 91), 'Pipeline/agent.py': (4227, 0), '.env.example': (990, 990)}
```

`except BaseException` の片付けは**今作ったもの**だけなので、既存の `agent.py` は `ftruncate` 済みの 0 バイトで残る。
Phase 1 の V-1 と同じ判定（攻撃者が作れる状況ではない・Low）だが、メッセージが「内容を失った」ことを言わない点も V-1 と同じ。
修正案: 既存ファイルは `<name>.jin-tmp` に `O_EXCL | O_NOFOLLOW` で書いてから `os.replace(..., src_dir_fd=, dst_dir_fd=)` で
入れ替える（`dir_fd` 相対のまま原子的に置換できる）。それが重ければ、メッセージに「`--force` で上書き中に失敗したため `agent.py` は
空になっています。`jin build --force` をやり直してください」を足す。

## 5. F-S-P2-004 / 007（`jin build` の書き込み）— defect-gone

```
$ touch regfile; jin build … --out regfile          regfile: regfile を出力先ディレクトリにできません: File exists            exit=1
$ ln -s /nonexistent/dir dangling; … --out dangling dangling: … File exists                                                   exit=1
$ … --out /proc/nope/out                             /proc/nope/out: … No such file or directory                              exit=1
$ … long.jin（root = 'あ'×100）--out out2            out2: あ…/ を作れません: File name too long   exit=1   out2/ は空
$ ln -s elsewhere linkout; … --out linkout           linkout がシンボリックリンクなので書き込みを拒みました（…）              exit=1   elsewhere は空
$ … --out linkout --force                            同上                                                                     exit=1
$ chmod 555 ro; … --out ro                           ro: Pipeline/ を作れません: Permission denied                            exit=1
$ touch o3/Pipeline; … --out o3                      o3: Pipeline がディレクトリではありません                                exit=1
$ mkdir -p o4/.env.example; … --out o4 --force       o4: o4/.env.example を開けません: Is a directory   exit=1   o4/ には .env.example/ だけ（Pipeline/ は片付いた）
```

トレースバックは 1 件も出ない。`_open_out_dir` の ENOTDIR 分岐（Linux は `O_DIRECTORY | O_NOFOLLOW` でリンクを開くと ELOOP でなく
ENOTDIR）は変異 `BUILD-follow-out-symlink` で赤を確認。`encode-before-open` は §1 の `bad\udcff` ライブラリ経路と変異 `BUILD-encode-late`、
`except BaseException` 片付けは上の ENOSPC 注入（新規ファイル無し）と変異 `BUILD-cleanup-only-on-refusal` で確認。

## 6. F-S-P2-006 / 008（`--trace`）— defect-gone

```
$ echo '{"seq":1,"previous":"trace"}' > t.jsonl
$ jin run two_out_states.jin go --model fake --trace t.jsonl     BuildError  exit=1  trace=[{"seq":1,"previous":"trace"}]   # 無傷
$ jin run noref.jin go --model fake --trace t.jsonl              RunError(import) exit=1  trace=[{"seq":1,"previous":"trace"}]   # 無傷
$ （ツールが途中で落ちる）                                       trace=今回の 1 行目まで（切り詰め後に書いた分）
$ jin run pipeline.jin go --model fake --trace t.jsonl           exit=0  11 行に置換   既存ファイルの mode は 644 のまま（§2.22 どおり）
$ rm new.jsonl; … --trace new.jsonl                              new-file mode=600
$ echo OLD > zero.jsonl; （TraceWriter._emit を潰して 0 行成功）  zero.jsonl size=0    # finish() が切り詰める
$ ln -s victim link.jsonl; … --trace link.jsonl                  トレースを開けません（Too many levels of symbolic links）exit=1  victim=keep
$ mkdir tdir; … --trace tdir                                     トレースを開けません（Is a directory）exit=1
```

`_LazyTruncateSink` の順序: `write()` → `_truncate()`（初回のみ `flush` → `ftruncate(0)` → `seek(0)`）→ `write`。
1 行目より前の例外は `_truncate` に到達しないので既存内容が残る（上の BuildError / RunError）。`ftruncate` 後に `write` が失敗する
ケースは「今回の実行のトレースが途中で切れる」だけで、前回の内容を守る責務はもう無い（切り詰めた時点で今回の実行が始まっている）。
`finish()` は成功時にしか呼ばれないので、0 行の失敗（例: import 失敗）は既存内容を残す — 意図どおり。
残る穴は `sink.close()`（`finally`）の `flush` が ENOSPC で落ちたときに `OSError` がそのまま上がる点だけ（T-1 型・極めて稀・Info）。

## 7. F-S-P2-010 / 014 / 016 — defect-gone

- `tests/contract/test_guard_claims.py` が `packages/*/src` を走査（列挙しない）。`guard:` 23 種 / `hazard:` 2 種（重複を除く 25 主張）を AST で照合、21 件緑。
  `_open_trace -> os.O_NOFOLLOW` / `_truncate -> os.ftruncate` / `_header -> py_literal(source_name)` / `_check_identifier -> unicodedata.normalize` /
  `_check_root_name -> unicodedata.normalize` / `write_project -> text.encode("utf-8")` / `_require_jin_file -> _has_unsafe_chars(file.name)` /
  `_open_out_dir -> os.O_NOFOLLOW` が新設。危険の所在は `hazard:`（`_import_agent_module -> importlib.util.spec_from_file_location` /
  `run -> sys.path.append`）に分離された
- 受容した残り: `_import_agent_module` / `run_model_async` の `except BaseException` は裸名なので記法上書けない（テスト + 変異で代替）。
  各主張がモジュール docstring と関数 docstring に 2 回ずつ書かれている（build 18 行 / 9 種など）のは前回と同じで、検査には無害
- F-S-P2-014: ツール出力 `"a\u2028b\x1bc"` → stdout `{"result": "a\u2028b\u001bc"}`（`_UNSAFE_CODES` に U+2028 / U+2029 / サロゲート）
- F-S-P2-016: §1 のとおり `_require_jin_file` に統合され、存在しないパスも `_safe` 経由

## 8. F-S-P2-011（ハーネス）— defect-gone・59/59 を再実測

隔離コピーの `delivery/.../mutate_p2.py` をそのまま起動（`ROOT` はスクリプト位置から解決されるので**コピー側**、さらにハーネス自身が
`tempfile.mkdtemp` へ `packages` / `tests` / `examples` / `pyproject.toml` を複製して `PYTHONPATH` で優先させる）:

```
copy: /tmp/jin-mutate-vlq83yqq
imports from: /tmp/jin-mutate-vlq83yqq/packages/jin-adk/src/jin_adk/__init__.py
imports from: /tmp/jin-mutate-vlq83yqq/packages/jin-cli/src/jin_cli/__init__.py
baseline: green (241 passed, 59 warnings in 2.34s)
…（57 件 RED (expected)、BUILD-overwrite-dir-only / BUILD-pkg-symlink-upfront-only は GREEN (expected: 二層目が守る)）
59/59 mutations caught
HARNESS EXIT 0
```

判定は `_is_red = returncode == 1 and "failed" in summary`、`_is_green = returncode == 0 and "passed" in summary`、
`SKIP (pattern not found)` は caught に数えず exit 1。前回指摘した exit 5 / 4 の偽赤は構造的に消えた。
`RUN-plain-mkdir` は `tempfile.mktemp` + `Path.mkdir` の本来の形になっている。

**ただし F-S-P2-102 が示すとおり、59 件の網には「実行中の `SystemExit`」が無い**（`RUN-swallow-systemexit` は import 時のみ）。
回帰は変異ハーネスでは検出できなかった。§4 の修正案 3 を参照。

## 9. 総評

fix-now 12 件のうち **11 件が defect-gone**、F-S-P2-003 は部分（インストール済み名は塞がったが、通常経路で毎回踏む未インストール名の
残存 = F-S-P2-101 を §2.19 が狭く書いている）。修正が持ち込んだ回帰が 1 件あり、**F-S-P2-102（ツール内 `sys.exit(0)` で exit 0）は
Phase 1 の S2 と同じ fail-open**で、`asyncio.run` を `except BaseException` の外へ出したことが原因。1 箇所の `try/except` で直るが、
S2 → 今回と 2 度目なので「`asyncio.run` は必ず `SystemExit` を包む」をテストと変異で固定すること。

DONE_WITH_CONCERNS
