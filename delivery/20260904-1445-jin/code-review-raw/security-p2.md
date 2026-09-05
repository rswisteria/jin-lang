# Stage 5 security review — Phase 2（jin-adk: build / run / trace / FakeLlm）

- 対象: ブランチ `feat/jin-phase2-adk` の未コミット作業ツリー（2026-09-05）
- 方法: `git ls-files --cached --others` の隔離コピー（scratchpad）で実測。**実ツリーは変更していない**。
  `PYTHONDONTWRITEBYTECODE=1` + `PYTHONPATH=<copy>/packages/*/src`、`jin_adk.__file__` がコピー側を指すことを確認済み
- baseline: 隔離コピーで `696 passed`（`-p no:cacheprovider`）。`lint-imports`: 3 契約 KEPT
- 必須入力: `decision-conformance.md` §1 P2 行 12 件 / §2.13〜§2.21 / §4.1、`design.yaml` の DP-JIN-CODEGEN-RUNTIME-01 /
  DP-JIN-TRACE-POINTER-01 / DP-COMMON-14 / DP-COMMON-15 / `review_axes_note` (1)、Phase 0+1 の `security*.md`
  （S1 / S2 / S8 / S9 / R-1 / R-2 / T-1 / U-1 / V-1）、`CLAUDE.md`「`--resolve` と `jin run` の危険性」節
- 以下、再現コマンドは隔離コピーを `$S`、`jin` は `$PY -c "from jin_cli.main import app; app()"` の別名とする

## 0. 要約

| ID | severity | conf | 一言 |
|---|---|---|---|
| F-S-P2-001 | **High** | 95 | `.jin` の**ファイル名**が `py_literal` を通らず生成ヘッダへ流れる。改行入りファイル名で生成 `agent.py` にコードが混入し、`jin run` がそれを実行する（`ref` 不要の任意コード実行） |
| F-S-P2-002 | **High** | 92 | 識別子の NFKC 正規化で予約名検査を迂回できる。全角 `ｒｏｏｔ＿ａｇｅｎｔ` という circle が `root_agent` を上書きし、`jin run` が別の agent を root として exit 0・pointer 付きで「正常に」走る |
| F-S-P2-003 | Medium | 95 | `sys.path.insert(0, cwd)` により、**`ref` を 1 つも持たない `.jin`** でも cwd の `authlib/` 等（ADK が実行中に遅延 import する）が実行される。§2.19 の「攻撃面を広げない（同じ相手が ref を書く）」は不正確 |
| F-S-P2-004 | Medium | 92 | `jin build` の `write_project` で `WriteRefused` 以外の `OSError` が未捕捉トレースバック（T-1 と同型・S5→N2→T-1 に続く 4 度目） |
| F-S-P2-005 | Medium | 93 | 不正 UTF-8 バイトを含むファイル名（surrogateescape）で `handle.write` が `UnicodeEncodeError`。`--force` では `ftruncate` 済みの既存 `agent.py` が **0 バイト**になる（V-1 と同型）。`--force` 無しでも 0 バイトのファイルが残る（「中途半端に残さない」の破れ） |
| F-S-P2-006 | Medium | 90 | `--trace` を `generate()` の**前**に `O_TRUNC` で開くため、`BuildError` で落ちる `.jin` を渡すと既存トレースが空になる（内容を失う） |
| F-S-P2-007 | Low | 85 | `<out>` 自体は symlink を辿る（`<out>/<root>` と `--trace` は辿らない設計と不整合） |
| F-S-P2-008 | Low | 80 | トレース JSONL（ツール引数・state・モデル出力入り）が 0644 で作られる。一時ディレクトリは 0700 なのに成果物は world-readable |
| F-S-P2-009 | Info | 90 | `ref` 先から `jin_adk.trace.TraceWriter._emit` を差し替えると「0 イベント」exit 0・空トレース（DP-JIN-RESOLVE-ISOLATION-01 の同型。未決 DP なので**実装は求めない**）。`os._exit(0)` は Phase 1 §4 と同じ受容済み残存だが、一時ディレクトリが残る点は新規観察 |
| F-S-P2-010 | Low | 85 | `guard:` 記法の抜け: E-A 型 2 件（`except BaseException` / CLI `run` の `--trace` `O_NOFOLLOW`）、E-C 型 2 件（危険な操作の所在を「guard」として主張） |
| F-S-P2-011 | Low | 90 | `mutate_p2.py` は `returncode != 0` を caught と数える。`-k` が 0 件を選ぶ exit 5 / ファイル欠落 exit 4 も「RED (expected)」になる（実測）。**今回の 31/31 は本物**（隔離コピーで再実測） |
| F-S-P2-012 | Info | 95 | `.env.example`: 4 キーのみ・`.env` を読む/書くコード無し・`GOOGLE_API_KEY=` は空。ただし `GOOGLE_GENAI_USE_ENTERPRISE=0` は空でない値（§2.13 に根拠あり） |
| F-S-P2-013 | Info | 90 | FakeLlm: socket を塞いでも両 examples が exit 0（ネットワークに出ない・実測）。キー無し・`--model` 省略は `RunError` exit 1、トレースバック無し、キーは stdout/stderr/JSONL に出ない |
| F-S-P2-014 | Info | 70 | ツール出力の U+2028 が `_safe` を素通りして stdout に生で出る（`_CONTROL_TRANSLATION` は C0 / DEL / C1 のみ） |
| F-S-P2-015 | Info | 90 | `CLAUDE.md` / `decision-conformance.md` §4.1 の主張と実装の食い違い（001 / 003 / 005 に起因） |
| F-S-P2-016 | Low | 90 | `_load_model_or_exit` の 2 分岐（ファイル無し / 拡張子違い）だけファイル名を `_safe` に通さず stderr へ出す。制御文字入りのファイル名で診断出力を偽装できる（Phase 1 が `_reject_bad_chars` の根拠にした型） |

**守られていたこと（実測）**: `O_EXCL` / `O_NOFOLLOW` / `dir_fd` 相対の書き込み、`<out>/<root>` symlink の拒否、
`WriteRefused` 時の片付け（今作ったものだけ）、`--force` の `ftruncate` 順序、import 中と**ツール実行中**の
`sys.exit(0)` を exit 1 にする（fail-closed）、`--model` の `fake` 限定、`--trace` の symlink 拒否、
`.jin` **本文**由来の全文字列（`name` / `core` / `description` / `rune` / `tools[].name` / `builtin` / `state[].name` /
`flow.exit.key` / `equals` / `delegate` / `await`）の `py_literal` 化と識別子検査、`importlib` の 2 モジュール限定、
import-linter 3 契約、変異 31/31。

---

## 1. コード生成のインジェクション（観点 1）

テンプレート `agent.py.j2` へ渡る変数を全部列挙し、出所を確認した:

| 変数 | 出所 | 保護 |
|---|---|---|
| `header` | `_header(source_name)` — **CLI の `file.name`** | **無し**（F-S-P2-001） |
| `agent_classes` | 固定集合 `_FLOW_CLASS` / `LlmAgent` / `BaseAgent` | 定数 |
| `tool_imports` | `FunctionTool` / `LongRunningFunctionTool` / `tool.builtin` | `builtin` は `isidentifier()` + `in adk_tools.__all__` |
| `uses_agent_tool` / `has_exit` | bool | — |
| `ref_imports` | `from <module> import <attr>[ as <alias>]` | `PYTHON_REF`（ASCII 正規表現）、alias は `module.replace('.', '_') + '__' + attr` |
| `blocks` | `<var> = LlmAgent(...)` | 値は `py_literal` / `py_value`、`<var>` と `sub_agents=[...]` / `AgentTool(agent=...)` は circle 名 → `_check_identifier` |
| `max_iterations={flow.max}` | `Flow.max: int` | Pydantic 型 |

`.jin` **本文**由来の文字列については `py_literal`（`json.dumps` + U+2028/2029/C1 エスケープ）で 1 行のリテラルになり、
`test_jin_strings_cannot_inject_statements` が AST で固定している。`'") ; import os ; os.system("id") #'` 等の NASTY 10 種は
`ast.literal_eval` で往復することも確認した。問題は **本文以外**の 2 経路（ファイル名・識別子の正規化）にある。

### F-S-P2-001 【High / confidence 95】`.jin` のファイル名が `py_literal` を通らずヘッダに流れ、コードとして実行される

- `packages/jin-adk/src/jin_adk/codegen.py:838-839` `_header`: `f"# source: {source_name}\n"` を**生で**連結
- `packages/jin-cli/src/jin_cli/main.py:584` `build` / `:662` `run`: `generate(model, source_name=file.name)`
- `Ident` / `Text` の制御文字検査は `.jin` 本文にしか効かない。Linux のファイル名は `\n` を含めるので、
  `x\n<任意の Python>\n#.jin`（`suffix` は `.jin` のまま）を渡すと、ヘッダのコメントが 2 行目で**文**になる
- `test_jin_strings_cannot_inject_statements` は `source_name` を渡していないので見えない。
  スナップショット 2 本は `"researcher.jin"` / `"pipeline.jin"` 固定

再現:

```
$ FNAME=$'x\nimport os; os.system("echo PWNED-BY-FILENAME 1>&2")\n#.jin'
$ cp $S/examples/pipeline/pipeline.jin "$FNAME"
$ jin build "$FNAME" --out out; echo "build exit=$?"
書き出しました: out/Pipeline/__init__.py
書き出しました: out/Pipeline/agent.py
書き出しました: out/.env.example
build exit=0
$ head -4 out/Pipeline/agent.py | cat -A
# generated by jin M-bM-^@M-^T do not edit$
# source: x$
import os; os.system("echo PWNED-BY-FILENAME 1>&2")$
#.jin$
$ python - <<'EOF'
import ast; m=ast.parse(open('out/Pipeline/agent.py').read())
print(sorted({type(n).__name__ for n in m.body}))
EOF
['Assign', 'ClassDef', 'Expr', 'FunctionDef', 'Import', 'ImportFrom']     # Expr / Import が混入
$ (cd out && python -c "import Pipeline")
PWNED-BY-FILENAME
$ jin run "$FNAME" go --model fake; echo "run exit=$?"
PWNED-BY-FILENAME
[1] Drafter model gemini-2.5-flash /circles/2/core fake-response
...
run exit=0
```

シナリオ: clone したリポジトリ / 受け取ったアーカイブに改行入りの名前の `.jin` がある → `jin run --model fake`
（README が「ネットワークに出ない」と案内する経路）で任意コードが走る。`ref` と違い **import 可能なモジュールを
用意する必要が無い**ので、`.jin` 作者が持つ攻撃面を広げている（`.jin` 本文からは `ref` 経由でしか実行できず、
それは import できるモジュールが cwd / `PYTHONPATH` に要る）。`jin build` 単体では実行されないが、生成物を
`adk run` / `adk web` した時点で実行される。

食い違う constraint:
- `decision-conformance.md` §4.1 表 2 行目「`py_literal` … を**全文字列に適用**」
- `CLAUDE.md`「`.jin` 由来の文字列は `jin_adk.codegen.py_literal` で必ず Python リテラルにしてからテンプレートへ渡す（式へ流れない）」
  （厳密には `.jin` 本文ではなくファイル名だが、生成物に生の外部文字列が届く経路である点は同じ）
- `design.yaml` DP-JIN-CODEGEN-RUNTIME-01「生成された agent.py は … import と代入だけ」を `test_jin_strings_cannot_inject_statements` が
  主張しているが、`source_name` 経路が抜けている

修正案（どちらか、両方でもよい）:
1. `_header` で `source_name` を `py_literal` に通す（`# source: "x\nimport os..."` の形。コメント内でも 1 行に収まる）。
   `\n` `\r` を含む名前はそもそも `BuildError` で拒む方が親切
2. `test_jin_strings_cannot_inject_statements` に `source_name='x\nimport os\n#.jin'` を渡すケースを足し、
   AST の body 種類が `ImportFrom` / `Assign`（+ `has_exit` 時の `Import` / `FunctionDef` / `ClassDef`）だけであることを固定
3. CLI 側で `file.name` に制御文字があれば exit 2（`_safe` で表示）

### F-S-P2-016 【Low / confidence 90】ファイル名が `_safe` を通らず stderr に出る分岐が 2 つある

- `main.py` `_load_model_or_exit`: `typer.echo(f"ファイルがありません: {file}", err=True)` と
  `f"'.jin' ではありません: {file}（...）"` の 2 分岐だけ `_safe(str(file))` を通していない（同関数の `JinReadError` 分岐や
  `build` / `run` の他の出力は `_safe` 済み）
- 実測（F-S-P2-001 の最初の試行で偶然踏んだ。存在しない改行入りパスを渡したとき）:

```
$ jin build $'x\nimport os; os.system("...")\n#.jin' --out out
ファイルがありません: x
import os; os.system("echo PWNED-BY-FILENAME > /dev/stderr")
#.jin
build exit=2
```

改行がそのまま出て 3 行に割れている。`\x1b[2K` 等を含む名前なら「診断が無かったように見せる」偽装ができる。
Phase 1 が `_reject_bad_chars` の根拠にした「制御文字で表示を偽装できる」と同型。修正は `_safe(str(file))` に揃えるだけ。
F-S-P2-001 の修正案 3（`file.name` の制御文字を入口で拒む）を採れば両方が同時に消える。

### F-S-P2-002 【High / confidence 92】NFKC 正規化で予約名 / 衝突検査を迂回でき、`root_agent` を乗っ取れる

- `codegen.py` `_check_identifier`（`:299-330`）/ `build.py` `_check_root_name`: `str.isidentifier()` と**文字列一致**で
  `RESERVED_NAMES` / 予約語 / `user` / 相互衝突（`taken`）を判定する
- Python は識別子を **NFKC 正規化して束縛**する（PEP 3131）。全角 `ｒｏｏｔ＿ａｇｅｎｔ` は `isidentifier()` True・
  `"root_agent"` と不一致なので通り、生成コードでは `root_agent` **と同じ変数**になる
- 依存順で root より後に出る circle にこの名前を付けると、`root_agent = LlmAgent(name="Main", ...)` の後に
  `ｒｏｏｔ＿ａｇｅｎｔ = LlmAgent(name="ｒｏｏｔ＿ａｇｅｎｔ", ...)` が来て `root_agent` を上書きする

再現:

```
$ python - <<'EOF'
import json
name = "ｒｏｏｔ＿ａｇｅｎｔ"     # NFKC → root_agent
json.dump({"$schema": "x", "version": 1, "root": "Main", "circles": [
  {"name": "Main", "core": "gemini-2.5-flash", "instruction": {"rune": "main"}},
  {"name": name,   "core": "gemini-2.5-flash", "instruction": {"rune": "evil"}}]},
  open("nfkc.jin","w",encoding="utf-8"), ensure_ascii=False)
EOF
$ jin check nfkc.jin
1 ファイル / error 0 件 / warning 0 件
$ jin build nfkc.jin --out out; grep -n "= LlmAgent" out/Main/agent.py
13:root_agent = LlmAgent(
19:ｒｏｏｔ＿ａｇｅｎｔ = LlmAgent(
$ python -c "import ast;m=ast.parse(open('out/Main/agent.py').read());print([t.id for n in m.body if isinstance(n,ast.Assign) for t in n.targets])"
['root_agent', 'root_agent']                                              # 同じ変数に 2 回代入
$ (cd out && python -c "import Main; print(Main.root_agent.name)")
ｒｏｏｔ＿ａｇｅｎｔ                                                       # root は Main のはず
$ jin run nfkc.jin hi --model fake --trace t.jsonl; echo "exit=$?"; cat t.jsonl
[1] ｒｏｏｔ＿ａｇｅｎｔ final gemini-2.5-flash /circles/1/core fake-response
1 イベント（session: jin）
exit=0
{"seq": 1, ..., "agent": "ｒｏｏｔ＿ａｇｅｎｔ", "kind": "final", "pointer": "/circles/1/core", ...}
```

`jin run` は `.jin` の `root: "Main"` を無視して別の circle を走らせ、**exit 0・pointer 解決済み**で「もっともらしく正常」に
終わる（`unresolved` も空）。同じ手口で `ｊｓｏｎ`（→ `json`、`_state_matches` が壊れる）、`ＬｌｍＡｇｅｎｔ`、
import した callable 名 `ｗｅｂ＿ｓｅａｒｃｈ`（→ `FunctionTool(web_search)` に LlmAgent が渡る）も通るが、
これらは import 時に例外 → `RunError` exit 1 で**fail-closed**。`a` と `ａ` の 2 circle は ADK の重複検査で import 時に
落ちる（実測: `Found duplicate sub-agent names`）。静かに間違うのは `root_agent` 上書きの形。

シナリオ: レビューで `.jin` を目視した人は `root: Main` を信じるが、実行される root は別 circle（別の instruction /
ツール）。トレースは `/circles/1/core` を指すので後続 Phase のオーバーレイも「正しく」描く。

食い違う constraint: `decision-conformance.md` §4.1 表 2 行目「識別子は `isidentifier()` + 予約語 + 予約名の検査」は
NFKC を考慮していない。`docs/spec/adk-mapping.md` の「circle 名 = 生成コードの変数名」の前提が破れる。

修正案:
1. `_check_identifier` / `_check_root_name` / `_plan_imports` の `taken` / `bound` を **`unicodedata.normalize("NFKC", name)`
   した値**で判定する（`normalized != name` なら BuildError でもよい: 「生成コードの変数名は NFKC 正規形のみ」）
2. もっと単純には、生成コードの変数名になる circle 名を ASCII 識別子（`[A-Za-z_][A-Za-z0-9_]*`）に限定する
   （`ref` と同じ規則。ADK の agent 名要件 `isidentifier()` より狭いが、生成物の可読性の面でも妥当）
3. `_dependency_order` の出力で同じ NFKC 名が 2 回束縛されないことを AST で固定するテスト（`Assign` の target 集合が
   circle 数 + checker 数と一致）

---

## 2. `jin build` の書き込み経路（観点 2）

`build.py` の主張（`O_EXCL` / `O_NOFOLLOW` / `dir_fd` / `--force` の `ftruncate` 順序 / 片付け）は実測とコード読解で
**成立**。`<out>/<root>` が symlink（`elsewhere` へ）→ `WriteRefused`、`elsewhere` は空のまま。`agent.py` が symlink →
`--force` でも拒否、victim 無傷。`.env.example` だけ既存 → 拒否して `Researcher/` を残さない。`root_name` の `../escape` 7 種 →
拒否。TOCTOU: `mkdir` 後に `<out>/<root>` が差し替えられても `O_DIRECTORY | O_NOFOLLOW` が ELOOP で拒む、
`O_EXCL` 失敗後に symlink へ差し替えられても 2 回目の `O_NOFOLLOW` が拒む（変異 `BUILD-pkg-symlink-both` /
`BUILD-follow-symlink` で本体が `O_NOFOLLOW` であることを確認）。以下は残っていたもの。

### F-S-P2-004 【Medium / confidence 92】`WriteRefused` 以外の `OSError` が未捕捉トレースバック（T-1 と同型）

- `build.py` `write_project` `:145-146`: `out.mkdir(parents=True, exist_ok=True)` / `os.open(out, O_RDONLY | O_DIRECTORY)`、
  `_open_package_dir` `:78`: `os.mkdir(root_name, ...)` は `FileExistsError` しか捕まえない
- `main.py` `build`: `except BuildWriteRefused` だけ。Phase 1 で `fmt` に入れた `_describe_oserror`（T-1）は使っていない
- `pretty_exceptions_show_locals=False` なので環境変数は出ないが、rich の枠付きトレースバックと実装のソース行が出る

再現（4 通り・すべて exit 1 + トレースバック）:

```
$ touch regfile; jin build $S/examples/pipeline/pipeline.jin --out regfile
│   1013 │   │   │   if not parents or self.parent == self:  ...
FileExistsError: [Errno 17] File exists: 'regfile'
$ ln -s /nonexistent/dir dangling; jin build ... --out dangling
FileExistsError: [Errno 17] File exists: 'dangling'
$ jin build ... --out /proc/nope/out
FileNotFoundError: [Errno 2] No such file or directory: '/proc/nope'
$ python -c "import json; n='あ'*100; json.dump({'\$schema':'x','version':1,'root':n,'circles':[{'name':n,'core':'m'}]}, open('long.jin','w'), ensure_ascii=False)"
$ jin build long.jin --out out2
│ ❱  78 │   │   os.mkdir(root_name, mode=0o755, dir_fd=out_fd)
OSError: [Errno 36] File name too long
```

最後のケース: `MAX_IDENT_LENGTH = 128` 文字は UTF-8 で最大 512 バイトなので、非 ASCII 86 文字以上の `root` で
ENAMETOOLONG に到達する（`jin check` は通る）。`out2/` は作られたまま残る。

修正案: `write_project` 内の `OSError` を `WriteRefused(f"{shown} を開けません: {exc.strerror}")` に包む（`_open_for_write` と
同じ形）か、CLI `build` に `except OSError` を足して T-1 の `_describe_oserror` を再利用する。テストは
`--out` が通常ファイルのケース 1 本で十分。

### F-S-P2-005 【Medium / confidence 93】surrogateescape ファイル名で書き込みが途中で失敗し、`--force` では既存 `agent.py` が 0 バイトになる（V-1 と同型）

- Python は不正 UTF-8 バイトを含むファイル名を `\udcXX`（孤立サロゲート）として `file.name` に入れる（surrogateescape）
- `_header` がそれを `agent_py` に埋める → `write_project` `:177` `handle.write(text)` が `UnicodeEncodeError`
- このとき `--force` なら **`os.ftruncate(fd, 0)` を全ファイルに済ませた後**なので既存内容は消えている。
  `--force` 無しでも `O_EXCL` で作った 0 バイトのファイルが残る（片付けは `except WriteRefused` の中だけ）
- `.jin` 本文の孤立サロゲートは `_reject_bad_chars` が JIN002 で弾くが、ファイル名は誰も見ない

再現:

```
$ cp $S/examples/pipeline/pipeline.jin "$(printf 'bad\xff.jin')"
$ jin build "$(printf 'bad\xff.jin')" --out out; echo "exit=$?"
UnicodeEncodeError: 'utf-8' codec can't encode character '\udcff' in position 46: surrogates not allowed
exit=1
$ ls -la out out/Pipeline
-rw-r--r-- 0 .env.example          # 0 バイトで残る
-rw-r--r-- 0 agent.py              # 0 バイトで残る
-rw-r--r-- 91 __init__.py
$ rm -rf out; jin build $S/examples/pipeline/pipeline.jin --out out >/dev/null; wc -c out/Pipeline/agent.py
4188 out/Pipeline/agent.py
$ jin build "$(printf 'bad\xff.jin')" --out out --force; wc -c out/Pipeline/agent.py
UnicodeEncodeError: ...
0 out/Pipeline/agent.py             # 既存の生成物が消えた
$ jin run "$(printf 'bad\xff.jin')" go --model fake; echo "exit=$?"
UnicodeEncodeError: ...
exit=1                               # 一時ディレクトリは finally で消えている（/tmp/jin-run-* に残らない）
```

修正案:
1. `write_project` で `text.encode("utf-8")` を **open より前**に済ませ、bytes を `os.write` する（失敗要因を
   `ftruncate` の前に潰す。V-1 の「内容を失わない」規律をそのまま適用）
2. 片付けを `except WriteRefused` から `except BaseException`（今作ったものだけ消す）に広げる
3. F-S-P2-001 の修正 3（`file.name` の検査）で入口も閉じる。`source_name.encode("utf-8")` が失敗したら名前を落とす

### F-S-P2-007 【Low / confidence 85】`<out>` 自体は symlink を辿る

- `write_project` `:145-146`: `out.mkdir(...)` と `os.open(out, O_RDONLY | O_DIRECTORY)` に `O_NOFOLLOW` が無い
- 実測: `ln -s elsewhere linkout; jin build ... --out linkout` → exit 0、`elsewhere/Pipeline/` と `elsewhere/.env.example` が作られる
- `<out>` は利用者が名指しした先なので受容してよいが、`<out>/<root>` は拒み `--trace` も拒む（「利用者が名指ししたが辿らない」）
  のに `<out>` だけ辿るのは規律が揃っていない。docstring「シンボリックリンクを辿らない」は `<out>` 配下の話だと明記するか、
  `O_NOFOLLOW` を足して統一する

---

## 3. `jin run` の実行経路（観点 3）

成立していたこと（実測）: `tempfile.mkdtemp` 0700 + `finally` で `rmtree`（正常終了・`RunError`・`UnicodeEncodeError` のいずれでも消える）、
`sys.modules` は一意名 `_jin_run_<uuid>` で汚さない、import 中の `sys.exit(0)` → `RunError` exit 1（`SystemExit` を可視化）、
**ツール実行中**の `sys.exit(0)` も `asyncio.run` から `BaseException` として届き exit 1:

```
=== ref 先の tool() が sys.exit(0)
[1] R tool tool /circles/0/tools/0 {"query": "q"}
evil.jin: 実行に失敗しました（SystemExit: 0）
exit=1
```

### F-S-P2-003 【Medium / confidence 95】cwd を `sys.path` の先頭に足すため、`ref` の無い `.jin` でも cwd のパッケージが実行される

- `main.py:644` `run`: `sys.path.insert(0, cwd)`（§2.19・`guard: run -> sys.path.insert`）
- `jin_core` / `jin_adk` / `google.adk` / `google.genai` は CLI 起動時に import 済みなので cwd で差し替えられない（実測: `google.adk.*` の子は
  通常パッケージで `__path__` が固定）。しかし ADK は **Runner の実行中に**トップレベルパッケージを遅延 import する。
  CLI 起動後に新たに import されるトップレベル名（実測・researcher / fake）: `authlib` `requests` `urllib3` `charset_normalizer`
  `cryptography` `joserfc` `_cffi_backend`、および namespace package `google` の未ロードの子 `google.oauth2`（`_NamespacePath` は
  `sys.path` 変更で再計算される）
- これらは cwd の同名ディレクトリで**先に**解決される

再現（`pipeline.jin` は `ref` を 1 つも持たない）:

```
$ mkdir authlib; cat > authlib/__init__.py <<'EOF'
import sys, traceback
print("SHADOW authlib FROM CWD LOADED (pipeline.jin has no ref at all)", file=sys.stderr)
...（呼び出し元を印字）
EOF
$ jin run $S/examples/pipeline/pipeline.jin go --model fake
SHADOW authlib FROM CWD LOADED (pipeline.jin has no ref at all)
IMPORTER CHAIN:
    google/adk/workflow/_dynamic_node_scheduler.py:37 <module>
    google/adk/workflow/utils/_rehydration_utils.py:32 <module>
    google/adk/workflow/utils/_workflow_hitl_utils.py:29 <module>
    google/adk/auth/auth_handler.py:25 <module>
    google/adk/auth/exchanger/oauth2_credential_exchanger.py:28 <module>
    google/adk/auth/oauth2_credential_util.py:21 <module>
...: 実行に失敗しました（ModuleNotFoundError: No module named 'authlib.integrations'）
$ jin build $S/examples/pipeline/pipeline.jin --out out 2>&1 | grep -c SHADOW     # build は cwd を足さない
0
$ jin check --resolve $S/examples/pipeline/pipeline.jin 2>&1 | grep -c SHADOW     # Phase 1 の --resolve も足さない
0
```

シナリオ: 自分で中身を確認した `.jin`（`ref` 無し、`--model fake`）を、clone したリポジトリのルートで `jin run` する。
リポジトリに `authlib/` や `requests/` ディレクトリがあれば、その `__init__.py` がこのプロセスの権限で走る。
`.jin` 作者と cwd の支配者は別人でありうるので、§2.19 の「`jin run` は元々任意コード実行であり、cwd の追加が攻撃面を
広げるわけではない（同じ相手が `ref` を書く）」は成り立たない。CLAUDE.md の「`--resolve` は自分が中身を確認した `.jin` にだけ」
という利用者向けの防御線が、cwd に対しては効かない。

食い違う constraint: `decision-conformance.md` §2.19 の根拠文、`CLAUDE.md`「`jin run` は `ref` を cwd から解決できるよう
`sys.path` の先頭に cwd を足す」（事実は正しいが危険性の記述が無い）。

修正案（推奨は 1）:
1. `sys.path.insert(0, cwd)` を **`sys.path.append(cwd)`** にする。site-packages にあるものは本物が先に解決され、
   cwd で差し替えられるのは「どこにも無い名前」（= `research.*` のような `ref` 先）だけになる。`test_run_adds_cwd_to_sys_path` は
   そのまま通る（`research` は site-packages に無い）。**追従が要るもの**: `guard: run -> sys.path.insert` を `sys.path.append` に、
   `mutate_p2.py` の `CLI-no-cwd` の `before` 文字列も同様に（そのままだと `SKIP (pattern not found)` になり 31/31 が崩れる）。
   残存: `append` で塞がるのは site-packages に**ある**名前の差し替えだけ。ADK が任意依存として遅延 import する未インストールの
   名前（`mcp` など。`_resolve_builtin` が不正な `builtin` 名を受けたとき `__all__` 全部に `getattr` して候補を作る経路が
   `jin run` の `generate()` 内 = cwd 追加後に踏む・コード読解）は `append` 後も cwd から解決される。したがって 2 の文言修正は
   `append` にしても必要
2. 併せて §2.19 / CLAUDE.md の文言を「cwd のモジュールも実行される。信頼できないディレクトリで `jin run` しない」に直す
3. さらに絞るなら、cwd を足すのは `_import_agent_module` の間だけ（`try/finally` で戻す）にする。ただし ADK の遅延 import は
   Runner 実行中なので、1 を採らない限りこれだけでは塞がらない

### F-S-P2-009 【Info / confidence 90】`ref` 先からの差し替えで「正常」に見える経路（DP-JIN-RESOLVE-ISOLATION-01 の同型・**実装は求めない**）

同一プロセスで import する以上、`ref` 先は `jin_adk` / `jin_cli` のオブジェクトを自由に書き換えられる。実測:

```
=== ref 先の __init__ が jin_adk.trace.TraceWriter._emit = lambda self, row: None
0 イベント（session: jin）
exit=0   trace lines: 0                     # 何も起きなかったように見える
=== ref 先の __init__ が os._exit(0)  /  tool() の中で os._exit(0)
exit=0   trace lines: 0                     # Phase 1 §4 で受容済みの残存と同じ
```

Phase 1 の判定（`os._exit` に到達した時点で任意コード実行は成立済み）はそのまま当てはまる。新規の観察は 2 点:
(a) `os._exit` では `load_generated` の `finally` が走らないので `/tmp/jin-run-*` が 0700 のまま残る
（CLAUDE.md「終了時に必ず消す」は `os._exit` を除く）、(b) `--trace` は `O_TRUNC` 済みなので **空ファイルが「トレース」として残る**。
後続 Phase のデバッグモードが「空トレース = 何も起きなかった」と描くなら、そこで区別できる印（例: 先頭に `run` 開始行を書く、
または正常終了時だけ書き終える）を検討する価値がある。DP が未決なのでここでは記録のみ。

---

## 4. FakeLlm（観点 4）

### F-S-P2-013 【Info / confidence 90】ネットワークに出ない・キーが漏れない（実測で成立）

`test_fake_llm_never_imports_a_network_client` は `fake_llm.py` の**直接の import 文**しか見ない（ADK 経由の HTTP は検出できない）ので、
`socket.socket.connect` / `getaddrinfo` / `create_connection` を `RuntimeError` に差し替えて両 examples を走らせた:

```
pipeline  --model fake: [11] Refine_exit_check escalate ... / 11 イベント / exit 0
researcher --model fake: [1] Researcher final ... / 1 イベント / exit 0
```

`--model` 省略（キー無し・socket 遮断）: `実行に失敗しました（ValueError: No API key was provided. ...）` exit 1、トレースバック無し。
`GOOGLE_API_KEY=AIza-SECRET-KEY-XYZ` を置いて `--model` 省略: `実行に失敗しました（RuntimeError: NETWORK BLOCKED）` exit 1、
stdout / stderr / `t.jsonl`（0 バイト）のいずれにも `SECRET` は出ない（`grep -c` = 0）。ADK の `Direct use of automatic function calling ...`
警告が stderr に出るだけ。提案: socket を塞ぐ autouse fixture を `test_runtime.py` / `test_build_run.py` に足すと、
「ネットワークに出ない」が構造的に固定される（現状は import 文の静的検査のみ）。

---

## 5. トレース JSONL（観点 5）

`input` / `output` に入るもの（実測）: `model` / `final` 行はモデル出力テキスト（`input` は null。**プロンプト全文は入らない**）、
`tool` 行はツール引数（`{"query": "q"}`）と戻り値（`{"result": ...}`）、`escalate` 行は `state[key]` の実値。
ANSI エスケープを含むツール出力は stdout（`_safe` が `\u001b` に置換）でも JSONL（`json.dumps` は C0 を必ず `\uXXXX` 形式にする）でも無害化されていた（実測: `{"result": "\u001b[31mANSI-RED\u001b[0m..."}`）。

### F-S-P2-006 【Medium / confidence 90】`--trace` を `generate()` の前に `O_TRUNC` で開くため、失敗時に既存トレースを失う

- `main.py:649-651` `run`: `os.open(trace, O_WRONLY | O_CREAT | O_TRUNC | O_NOFOLLOW, 0o644)` → その後 `run_model()` 内で `generate()`
- `BuildError`（ADK に対応物のない構造）/ `RunError`（import 失敗・キー無し）のいずれでも、前回のトレースは既に 0 バイト

```
$ echo '{"seq":1,"previous":"trace"}' > t.jsonl
$ jin run $S/tests/fixtures/build-errors/two_out_states.jin go --model fake --trace t.jsonl; echo "exit=$?"
...: circle 'Root' に out: true の state が 2 件あります。...
exit=1
$ stat -c %s t.jsonl
0
```

Phase 1 の V-1（内容を失う）と同じ規律違反。修正案: `generate()` が通ってから開く（`run_model` に「開く」コールバックを渡すか、
CLI 側で `generate` → open → `run_model(project=...)` に分ける）。または `O_TRUNC` 無しで開き、最初の行を書く直前に
`ftruncate`（`build.py` と同じやり方）。

### F-S-P2-008 【Low / confidence 80】トレース JSONL が 0644 で作られる

- `main.py:650` `run`: `0o644`（umask 022 で `-rw-r--r--`・実測）。一時ディレクトリは 0700 なのに、ツール引数・state の実値・
  モデル出力を含む成果物は world-readable
- DP-COMMON-14 の axis「秘密情報（プロンプト・モデル出力）の扱い」に照らして、既定は `0o600` にし、緩めるのは利用者の `chmod` に
  委ねる方が安全側。`jin build` の 0644（コードなので共有前提）とは性質が違う

### F-S-P2-014 【Info / confidence 70】U+2028 が stdout に生で出る

`_CONTROL_TRANSLATION` は C0 / DEL / C1 のみ。ツール出力の U+2028（LINE SEPARATOR）は `_format_row` → `_safe` を素通りして
stdout に出た（`cat -A` で `M-bM-^@M-(`）。一部の端末は改行として描くので、1 行 1 イベント表示の偽装に使える程度。
`py_literal` は U+2028 をエスケープしているので、同じ表を `_safe` にも使えば揃う。

---

## 6. `.env.example`（観点 6）

### F-S-P2-012 【Info / confidence 95】

- `_env_example()` の有効行は `GOOGLE_GENAI_USE_ENTERPRISE=0` と `GOOGLE_API_KEY=` の 2 行、コメント行に `GOOGLE_CLOUD_PROJECT=` /
  `GOOGLE_CLOUD_LOCATION=`。4 キーはすべて §2.13 の実測表に出典がある（DP-COMMON-15 prohibition: 推測キー無し ✔）
- `packages/*/src` に `dotenv` / `load_dotenv` / `.env` を読む・書くコードは無い（grep 0 件・コメント文のみ）
- 依頼の「値が空であること」に対して `GOOGLE_GENAI_USE_ENTERPRISE=0` だけは空でない。`adk create` の写し（`cli_create.py:127-135`）
  という根拠が §2.13 にあり、秘密ではないので受容可。親が「値は全部空」を要求するなら `=` だけにしてコメントで案内する

---

## 7. `guard:` 主張の検査（観点 7）

`guarded_modules()` は `jin_cli.main` / `jin_adk.build` / `jin_adk.runtime` / `jin_adk.codegen` の 4 つを対象にしており、
`test_guard_claims_point_at_real_guards` は各主張を AST で突き合わせる（U-1 の裸名禁止・土台不一致も生きている）。
変異 `BUILD-guard-lie` で赤を再確認。

### F-S-P2-010 【Low / confidence 85】記法の抜け

| 型 | 箇所 | 内容 |
|---|---|---|
| E-A（散文で主張・`guard:` 無し） | `runtime.py` `_import_agent_module` | 「`KeyboardInterrupt` 以外の `BaseException` を捕まえる」は本文で最重要の主張だが、`BaseException` は裸の名前なので記法上書けない。テスト `test_system_exit_in_generated_code_import_is_not_swallowed` + 変異 `RUN-swallow-systemexit` で代替されている |
| E-A | `main.py` `run` | `--trace` の `os.O_NOFOLLOW` は散文（コメント）だけ。実コードにあるので `guard: run -> os.O_NOFOLLOW` を足せば通る |
| E-C（実在するが安全ガードではない） | `runtime.py` `_import_agent_module -> importlib.util.spec_from_file_location`、`main.py` `run -> sys.path.insert` | 「危険な操作の所在」を `guard:` で書いている。記法の意味が「防御の所在」と「危険の所在」で二重化し、読み手が防御と誤読しうる。別のタグ（例: `hazard:`）に分けるか、docstring で区別を明記する |
| 件数の水増し | `codegen.py` | 同じ 3 主張をモジュール docstring と関数 docstring に書いて `MINIMUM_GUARD_CLAIMS = 4` を満たしている（6 件中 3 種）。build / runtime も同様に 2 回ずつ。検査は通るが「最低 4 件」の意図（走査が壊れて 0 件になる検出）には 1 回ずつで十分 |

---

## 8. 変異検証（観点 8）

`mutate_p2.py` を隔離コピーで走らせた。`uv run pytest` は editable install の `.pth` 経由で**実ツリー**を import するので、
コピー用に `ROOT = Path($S)`・`[sys.executable, "-m", "pytest", ...]` に置き換え、走らせる前に `ROOT` と `jin_adk.__file__` を印字した:

```
ROOT = .../scratchpad/review-security
jin_adk from .../scratchpad/review-security/packages/jin-adk/src/jin_adk/__init__.py
baseline: green
```

| 変異 | 結果 | 備考 |
|---|---|---|
| ESC-no-escape / ESC-repr | RED | 8 / 9 failed |
| FAIL-skip-validate / -no-keyword-check / -two-outs / -rune-conflict / -ref-format | RED | 15 / 2 / 1 / 6 / 2 failed |
| ADR8-header / ADR9-header | RED | 1 failed |
| BUILD-overwrite-file / -force-truncates-early / -overwrite-both / -leftover-dir / -follow-symlink / -no-root-check / -pkg-symlink-both / -guard-lie | RED | 1 / 1 / 2 / 1 / 1 / 5 / 1 / 1 failed |
| BUILD-overwrite-dir-only / BUILD-pkg-symlink-upfront-only | GREEN（期待どおり: 二層目が守る） | `O_EXCL` / `O_NOFOLLOW` が本体であることの実測 |
| RUN-swallow-systemexit / -no-agenttool-swap / -no-seed / -no-cleanup / -plain-mkdir | RED | 1 / 1 / 2 / 2 / 2 failed |
| TRACE-drop-unknown / -dup-first-wins / -no-final / -escalate-pointer | RED | 1 failed each |
| CLI-no-cwd / -trace-follow-symlink / -accept-any-model | RED | 1 failed each |
| **合計** | **31/31 caught** | 申告と一致 |

### F-S-P2-011 【Low / confidence 90】ハーネスの構造: 「テストが 0 件」も caught に数える

- `main()`: `red += result.returncode != 0`。pytest は `-k` が 1 件も選ばないと exit **5**、対象ファイルが無いと exit **4** を返す。
  実測: `pytest test_build.py -k no_such_test_xyz` → 5、`pytest no_such_file.py` → 4。どちらも「RED (expected)」と表示される
- 今回は全行の summary に `N failed` が出ているので本物。だがテスト名を改名した瞬間に偽赤になる
- `RUN-plain-mkdir` は `str(pathlib_mkdir())` という未定義名で `NameError` を起こす変異なので、どんなテストでも赤くなる
  （「`mkdtemp` を `os.mkdir` に変えたら 0700 の検査が落ちる」を示す変異にはなっていない。`tempfile.mkdtemp` → `os.mkdir(tempfile.mktemp())` 等が本来の形）

修正案: `status` 判定を `result.returncode == 1 and "failed" in summary` にする。`SKIP (pattern not found)` も `red` に数えないのは
正しいが、最終行が `31/31` にならないだけで exit 1 になるので現状で可。

---

## 9. 文書の主張と実装の突合（観点: CLAUDE.md 節）

### F-S-P2-015 【Info / confidence 90】

| 文書 | 主張 | 実装 |
|---|---|---|
| `CLAUDE.md`「`.jin` 由来の文字列は `py_literal` で必ず Python リテラルにしてからテンプレートへ渡す（式へ流れない）」 | `.jin` 本文については真 | ファイル名（`source_name`）は生で流れる（F-S-P2-001） |
| `decision-conformance.md` §4.1「`py_literal` … を全文字列に適用。識別子は `isidentifier()` + 予約語 + 予約名の検査」 | — | `source_name` が抜け、識別子検査は NFKC を見ない（001 / 002） |
| §2.19「cwd の追加が攻撃面を広げるわけではない（同じ相手が `ref` を書く）」 | — | `ref` 無しでも cwd のパッケージが実行される（003） |
| `CLAUDE.md`「一時ディレクトリ（`tempfile.mkdtemp`・0700）に書いて import」「終了時に必ず消す」 | 真（`os._exit` を除く） | 009 |
| `build.py` docstring「中途半端に残さない」「既存ファイルの内容は無傷のまま残す」 | `WriteRefused` 経路では真 | `UnicodeEncodeError` 経路では 0 バイトが残る / 既存が消える（005） |
| `CLAUDE.md`「`importlib` を使うモジュールは 2 つだけ」「安全主張は `guard:` 記法で固定」 | 真（契約テスト・`guarded_modules` で確認） | 010 は記法の限界の記録 |
| `main.py` 「人間向け出力に載せる前に制御文字を可視表現へ置き換える」（`_safe`） | ほぼ真 | `_load_model_or_exit` の 2 分岐が例外（016） |

`README.md` の「`jin run` も任意コードを実行する」節と CLI ヘルプの【危険】表記は実装と一致している。

---

## 10. 総評

Phase 1 で確立した規律（`O_EXCL` / `O_NOFOLLOW` / `dir_fd` / fail-closed / `guard:` / 変異検証）は Phase 2 の `build.py` / `runtime.py` に
きちんと持ち込まれており、`.jin` 本文からの注入は閉じている。残っているのは**本文以外の入力**（ファイル名・識別子の正規化・cwd）で、
うち 001 と 002 は「`ref` 無しで任意コード実行」「root を静かに乗っ取る」という質のもので、コミット前に直す価値がある。
003 は 1 行（`insert` → `append`）で塞がり、004〜006 は Phase 1 で 3 度出た T-1 / V-1 と同型なので、同じヘルパを流用すれば小さい。

DONE_WITH_CONCERNS
