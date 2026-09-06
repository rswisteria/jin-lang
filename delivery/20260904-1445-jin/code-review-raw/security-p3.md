# Stage 5 review: security — Phase 3 (jin-render)

対象: ブランチ `feat/jin-phase3-render`（ベース origin/main `32c215e`）。`packages/jin-render/src/jin_render/*.py`、
`packages/jin-cli/src/jin_cli/main.py`（`render` / `_read_trace_rows` / `_write_svg` / `_write_atomically(allow_create)`）、
`docs/spec/layout.md` §3〜§7、`decision-conformance.md` P3 行 / §2.24、`implementation-notes.md` P3 節、`README.md`。
正典として `design.yaml` の `DP-JIN-SVG-DETERMINISM-01` / `DP-COMMON-07` の constraints を読んだ。

## 実測した環境・コマンド（隔離コピーのパス・件数）

- 隔離コピー: `/home/wisteria/.claude/jobs/e2bcfe94/tmp/review-security/`（`cp -r` した worktree。`__pycache__` は削除、
  `PYTHONDONTWRITEBYTECODE=1`、`TMPDIR=/home/wisteria/.claude/jobs/e2bcfe94/tmp/sec/tmp`）。
  `PYTHONPATH` にコピーの `packages/*/src` を並べ、`jin_render.__file__` / `jin_cli.__file__` / `jin_core.__file__` が
  コピー側を指すことを起動時に印字して確認した。実ツリーは 1 バイトも変更していない
  （`git status` の差分は本ファイルのみ。同時進行の他エージェントが `auto-decisions.*` / `implement-ledger.md` /
  `docs/pending-decisions.md` / `ADR-019` / `ADR-020` を書いているが本レビューの操作ではない）。
- baseline: `packages/jin-render/tests` + `packages/jin-cli/tests/test_render.py` = **177 passed**（snapshot 4 本含む）。
  `tests/contract/test_render_contract.py` + `test_guard_claims.py` を加えても全緑。
- 無回帰の確認（自分で実行）: `packages/jin-cli/tests/test_cli.py`（`fmt` の既存経路・`_write_atomically(allow_create)` の
  既定側）+ `tests/contract/test_packaging_contract.py` + `tests/contract/test_dependency_direction.py` = **131 passed / 0 failed**。
- 実装者の変異スクリプト `phase3-mutations/mutate_p3.py` をコピー上で実行: baseline 210 passed、**42/42 mutations caught**
  （`CLI-follow-symlink-upfront-only` は宣言どおり GREEN、`CLI-follow-symlink-both` は RED）。
- 悪性入力の実測スクリプト（すべて job tmp `/home/wisteria/.claude/jobs/e2bcfe94/tmp/sec/`）:
  `probe_render_lib.py`（ライブラリ経路: XML 不正文字 / 悪性 rune / 名前の流出 / 長大 pointer / 負の seq）、
  `probe_cli.sh` + `probe_ref.sh` + `probe_misc.sh`（CLI 経路 24 ケース）、`umask_test.sh`、`mutate_unicode.{py,sh}`、
  `e2e_u2028.{py,sh}`（`jin run --model fake --trace` → `jin render --trace` の端到端）。
- **確認できた防御（finding にしない）**:
  - `jin render` は `ref` を import しない。import 時にマーカーを書く `evil_mod.py` を cwd と `PYTHONPATH` に置き、
    `tools[].ref` / `boundary.guards[].ref` で指す `.jin` を `jin render`（`-o` / `--trace --upto --focus` の両方）で描いても
    マーカーは作られない（exit 0）。**positive control**: 同じ `.jin` を `jin check --resolve` するとマーカーが作られる。
    README の「`jin render` は任意コードを実行しない」は実測どおり
  - `.jin` 由来で SVG に出るのは **rune のテキストノードだけ**。circle 名 / tool 名 / state 名 / delegate 名 / `ref` 文字列は
    SVG に一切現れない（`NAME<INJ>` 等で実測）。pointer（`data-jin` / `data-jin-ref`）は f-string の int 添字、
    `href="#jin-rune-N"` は描画順の連番で、利用者入力は混ざらない
  - 悪性 rune `</svg><script>alert(1)</script>"'&]]><foreignObject/> javascript:alert(1)` は
    `&lt;/svg&gt;&lt;script&gt;…&amp;]]&gt;…` にエスケープされ、`<script` / `<foreignObject` / `]]>` は出力に無い。
    `ET.fromstring` で well-formed。属性の囲みは常に二重引用符（`quoteattr` 不使用）
  - `jin_render` に `open` / `Path` / `os` / `subprocess` / `socket` / `importlib` / `__import__` / `eval` / `exec` /
    `hash(` は無い（grep）。`set` は `fired`（`sorted()` で消費）と `dropped`（membership のみ）だけ。
    `PYTHONHASHSEED` 0 / 4242 の別プロセス一致テストは実在し、`ORN-builtin-hash` 変異で赤くなる
  - `typer.Typer(pretty_exceptions_show_locals=False)` なので、下記 F-S-P3-001 のトレースバックにも
    トレース本文（ローカル変数 `text`）は載らない
  - `-o` の書き出し: シンボリックリンクは事前判定と `os.replace` 直前の `Path(path).is_symlink()` の 2 層で拒む。
    既存ファイルは `--force` 無しで拒む。`--force` で既存モードを保つ。既存ディレクトリ + `--force` は
    `Is a directory` で exit 1。親ディレクトリ無し / 権限無し（`chmod 000`）はどちらも exit 1 でトレースバック無し。
    ENOSPC 系は `except OSError` で一時ファイルを消して `WriteRefused` に分類される（コード読解）
  - `--trace` の非 UTF-8 / ディレクトリ / 不在 / 1 行 2 オブジェクト / `NaN` / float の seq / bool の seq /
    型違いの pointer はすべて exit 2 で診断になる（`_safe` を通る。`--focus` に ESC を入れても `` に可視化）

## Findings

### F-S-P3-001 [confidence 90] `_read_trace_rows` が `json.loads` の `ValueError`（整数桁数上限）と `RecursionError` を捕まえず、トレースバックで exit 1 になる
- 場所: `packages/jin-cli/src/jin_cli/main.py:857-866`（`except json.JSONDecodeError` だけ）
- 内容 / 再現: `{"seq": 999…（5000 桁）, "pointer": null}` の 1 行 → `ValueError: Exceeds the limit (4300 digits) for integer
  string conversion` が素通しになり、typer のトレースバック（exit 1）。`{"seq": 1, "pointer": null, "x": [[[…（10 万段）]]]}`
  → `RecursionError: Stack overflow (used 8152 kB) while decoding a JSON array` で同じくトレースバック exit 1。
  どちらも `json.JSONDecodeError` の派生ではない（前者は素の `ValueError`、後者は `RuntimeError` 系）。
  期待との差: notes P3-7 の 8「それ以外（JSON でない / オブジェクトでない / 型違い）はすべて exit 2」と、
  Phase 2 の T-1（`PermissionError` 以外の `OSError` が未捕捉トレースバックになる同型欠陥）の再発。
  fail-closed ではある（exit 0 にならない）が、`--trace` の内容で CLI がトレースバックを出す経路が残っている。
  4000 桁の seq は通り、`data-jin-seq` に 4000 桁がそのまま出る（`data-jin-seq="…"` の長さ 4015）。
- 変異検証: 該当テストは無い（`test_render.py` の 22 件に巨大整数 / 深い入れ子のケースは無い）
- 提案: `except ValueError as exc:`（`JSONDecodeError` はその派生なので 1 つの枝で両方拾える。`exc.msg` は
  `getattr(exc, "msg", str(exc))`）と `except RecursionError` を足して exit 2。`seq` の桁数は overlay 側で
  上限（例: `abs(seq) < 2**63`）を置くと `data-jin-seq` の長さも有界になる

### F-S-P3-002 [confidence 90] `pointer_prefixes` が全 prefix を即時に実体化するため、長い pointer 1 行でメモリが二次に膨らむ（DoS）
- 場所: `packages/jin-render/src/jin_render/overlay.py:87-95`（`pointer_prefixes`）、`layout.py:656-663`（`fired_indices`）
- 内容 / 再現（ライブラリ経路・`render(model, trace=[{"seq": 1, "pointer": "/a" * n}])`）:

  | n（セグメント数） | 行の長さ | 時間 | maxrss |
  |---|---|---|---|
  | 2 000 | 4 KB | 0.01 s | 37 MB |
  | 20 000 | 40 KB | 0.95 s | 416 MB |
  | 50 000 | 100 KB | 6.25 s | 2 421 MB |

  `["/" + "/".join(tokens[: n + 1]) for n in reversed(range(len(tokens)))]` は長さ L の pointer に対し O(n·L) 文字を作る。
  モデル由来の pointer は最深 5 セグメント（`/circles/i/boundary/guards/j`）なので、これを超える pointer は
  どの段でも当たらない。`jin run` はこのような行を書かないが、`--trace` は外部ファイルであり、Phase 6 のエディタが
  同じ `render` にトレースを渡す（design.yaml Phase 6）。100 KB の 1 行で 2.4 GB は「壊れた行を黙って読み飛ばさない」
  規律とは別の問題（読み飛ばさなくてよいが、読む前に膨らむ）。
- 変異検証: 該当テストは無い
- 提案: (a) prefix を実体化せず、**鍵側**（`by_pointer` の鍵・要素数で有界）を走査して
  `pointer == key or pointer.startswith(key + "/")` の最長一致を取る（O(要素数 × L)・線形）、または
  (b) `pointer_prefixes` にセグメント数の上限（`jin_core.pointer` の最大深さ + 余裕）を置き、超えたら「どの段でも
  見つからない行」として点だけに数える。どちらも `test_overlay.py::test_a_pointer_with_no_element_falls_back_to_the_nearest_ancestor`
  を緑に保てる。上限を入れた場合は layout.md §7.1 に書く

### F-S-P3-003 [confidence 95] `jin run --trace` が書いた JSONL を `jin render --trace` が読めない行がある（`splitlines()` と `ensure_ascii=False` の不整合・端到端で再現）
- 場所: `packages/jin-cli/src/jin_cli/main.py:853`（`text.splitlines()`）と `packages/jin-adk/src/jin_adk/trace.py:338`
  （`json.dumps(row.to_json_dict(), ensure_ascii=False) + "\n"`）
- 内容 / 再現: `str.splitlines()` は `\n` のほかに U+2028 / U+2029 / U+0085 / `\x1c`〜`\x1e` / `\x0b` / `\x0c` でも行を割る。
  一方 `json.dumps(ensure_ascii=False)` は U+0020 以上の文字を生のまま書くので、トレース行の `name`（`core` のモデル名。
  `Ident` は U+2028 を拒まず、`py_literal` で値として埋め込まれるので `jin build` も通す）やモデル出力（`output` / `input.actual`）に
  U+2028 / U+2029 / U+0085 が 1 文字あるだけで、`jin run` が書いた 1 行が `jin render` では 2 行に割れる
  （circle 名は codegen の `isidentifier()` で `BuildError` になるので経路ではない）。
  **端到端の実測（ネットワーク無し）**: `examples/pipeline/pipeline.jin` の Drafter の `core` を `"gemini-2.5-flash<U+2028>x"` にした
  コピーは `jin check` を通り（error 0）、`jin run … --model fake --trace t.jsonl` は exit 0 で 11 行を書く（`wc -l` 11・raw U+2028 を
  含む行 1）。その同じファイルを `jin render … --trace t.jsonl` すると
  `t.jsonl:1: JSON として読めません（Unterminated string starting at）` exit 2。実測: `{"seq": 1, "pointer": "/circles/0/core", "output": "a b"}` を
  `ensure_ascii=False` で書いた 1 行 → `t_u2028.jsonl:1: JSON として読めません（Unterminated string starting at）` exit 2。
  fail-closed だが、README「`--trace` は `jin run --trace` が書いた JSONL を読み」と layout.md §7.5 の前提が崩れる入力が
  **自分の出力の中に**ある。副次: CR だけで区切ったファイル（`\r` 区切り）も受理する（`splitlines` が `\r` で割る）。
  行番号（`:N:`）もこの割り方で数えるので、writer の行番号とずれうる。
- 変異検証: 該当テストは無い（fixture `pipeline-fake.jsonl` は ASCII のみ）。再現スクリプト `e2e_u2028.{py,sh}`
- 提案: 読み手を writer の区切りに合わせる。`text.split("\n")`（末尾の `\r` は `rstrip("\r")`）にして
  `splitlines()` を使わない。あるいは writer を `ensure_ascii=True` にする（既存トレースが読めなくなるので読み手側を推奨）。
  U+2028 を含む 1 行の fixture テストを足す

### F-S-P3-004 [confidence 75] `jin render -o` の新規ファイルが umask を無視して 0644 になる（`jin build` は umask が効く）
- 場所: `packages/jin-cli/src/jin_cli/main.py:384-389`（`os.chmod(temporary, 0o644)`）
- 内容 / 再現: `umask 077` で `jin build … --out` と `jin render … -o` を並べて実測 → `build/Pipeline/agent.py` は **600**、
  `r.svg` は **644**。利用者が umask で「自分以外に読ませない」と決めた環境で、`jin render` だけがそれを上書きして
  group / other に読める生成物を作る。notes P3-7 の 9 が自己申告している差だが、論拠のうち
  (b)「umask を取る往復はマルチスレッドの LSP で危険」は成立しない: `_write_atomically` は `jin_cli` にあり、
  Phase 4 の LSP は `jin_render.render` しか呼ばない（CLAUDE.md / layout.md §8）。CLI は単スレッドである。
  (c)「SVG は秘匿対象ではない」も、SVG には rune の先頭 43 文字（`instruction` の本文）が `<textPath>` に載るので言い切れない。
  (a)「何もしないと 0600 のほうへずれる」は正しいが、選択肢は 0644 固定だけではない。
- 変異検証: `CLI-new-file-0600` 変異は赤（0644 を固定するテストが在る）。つまり **現状の仕様（umask 無視）をテストが固定している**
- 提案: `mode = 0o666 & ~umask` にする。umask は `os.umask(0)` → 値を得て → `os.umask(old)` を CLI 起動直後（`app()` の前・
  単スレッド時点）に 1 回読むか、Linux なら `/proc/self/status` の `Umask` を読む。テスト
  `test_the_output_file_is_created_with_the_generated_file_mode` は「`0o666 & ~umask` に一致する」に書き換える。
  人間の好みが割れうる値なので HANDOFF（`ai_provisional`）に載せる判断も妥当だが、その場合は論拠 (b) を記録から外すこと

### F-S-P3-005 [confidence 80] rune に U+FFFE / U+FFFF が通り、`render` の出力が well-formed な XML でなくなる
- 場所: `packages/jin-core/src/jin_core/model.py:49-66`（`_reject_bad_chars` は C0 / DEL / C1 / サロゲートだけ）、
  `packages/jin-render/src/jin_render/svg.py:66-79`（`attr_value` / `text_value` は `&` `<` `>` `"` `'` と `\n\r\t` だけ）
- 内容 / 再現: `rune = "x￿y"` は `JinFile.model_validate` を通り（JIN002 にならない）、`render` は例外を投げずに SVG を返すが、
  `ET.fromstring` は `not well-formed (invalid token)` で落ちる（U+FFFE も同じ）。XML 1.0 の `Char` 生成規則は
  `#xFFFE` / `#xFFFF` を含まないので、ブラウザの DOMParser / `innerHTML` でも parsererror になる。Phase 5 のエディタは
  SVG を DOM に埋め込む（layout.md §3）ので、この 2 文字を含む `.jin` は「schema を通るのに描画が壊れる」入力になる。
  layout.md §5「schema を通る `JinFile` なら例外を投げない」は守られているが、「投げずに壊れた SVG を返す」経路。
  U+0085 / U+000B / U+0000 / 孤立サロゲートはモデル検証で拒まれることを実測（正しい）。U+FDD0〜FDEF / U+2028 は XML として
  well-formed（実測 OK）。
- 変異検証: 該当テストは無い（`test_svg.py` のエスケープテストは `< > & " ' \n` のみ）
- 提案: 出力の well-formedness は `jin_render` が保証する側なので、`text_value` / `attr_value` で U+FFFE / U+FFFF を
  U+FFFD に置換する（`guard:` 主張に足す）。加えて `model.py` の `_reject_bad_chars` に U+FFFE / U+FFFF を足すと
  `jin check` の段で JIN002 になる（診断コードは増えない）。layout.md §3 か §4 に「出力は XML 1.0 として well-formed」を明記し、
  `test_layout.py` に「`tests/fixtures/errors/*.jin` を含む全 fixture の出力を `ET.fromstring` できる」検査を足す

### F-S-P3-006 [confidence 70] `_read_trace_rows` の `except UnicodeDecodeError` 枝はテストで固定されていない（変異で緑）
- 場所: `packages/jin-cli/src/jin_cli/main.py:848-850`
- 内容: 枝を丸ごと消しても `packages/jin-cli/tests/test_render.py` は **24 passed** のまま。枝が消えると非 UTF-8 の
  `--trace`（実測 `t_latin1.jsonl`）は `UnicodeDecodeError` のトレースバック exit 1 になる（現状は exit 2 の診断）。
- 変異検証: `mutate_unicode.py`（枝を削除 → `test_render.py` → 復元。復元後の一致を確認）
- 提案: 非 UTF-8 バイト列の fixture（`b'{"seq": 1, "pointer": null, "output": "\xe9"}'`）で exit 2 と文言を固定する。
  `mutate_p3.py` に `CLI-trace-not-utf8` を足す

### F-S-P3-007 [confidence 65] `seq` の負数を黙って受け、`upto=0` でも発火扱いになる（layout.md §7.5「1 始まり」と不一致）
- 場所: `packages/jin-render/src/jin_render/overlay.py:41-64`（`read_trace` は `int` であればよい）、`layout.py:721`
- 内容 / 再現: `{"seq": -5, "pointer": "/circles/0/core"}` + `--upto 0` → exit 0、`data-jin-seq="-5"`、`data-jin-fired="1"`。
  layout.md §7.5 は「`seq`（int・**1 始まり**）」、docstring も同じ。仕様が言う範囲外の値を検査せず通している。
  同じ行に `seq` キーが 2 回あると `json.loads` は後勝ち（`{"seq": 1, "seq": 2, …}` → `data-jin-seq="2"`・実測）。
  セキュリティ影響は小さい（表示の齟齬のみ）が、「黙って受ける」型なので記録する。
- 変異検証: 該当テストは無い
- 提案: `seq < 1` を `ValueError`（exit 2）にして仕様と一致させる。または仕様を「任意の int」に直す。どちらかに揃える

### F-S-P3-008 [confidence 60] 型違いの `seq` / `pointer` を `!r` で長さ無制限に stderr へ出す（log-confidentiality）
- 場所: `packages/jin-render/src/jin_render/overlay.py:53-63`（`{seq!r}` / `{pointer!r}`）、CLI は `_safe(str(exc))` で出す
- 内容 / 再現: `{"seq": {"secret": "S"×200}, "pointer": null}` → stderr に `{'secret': 'SSSS…（200 文字）'}` が丸ごと出る。
  `pointer` が list のときも同じ。`input` / `output` は読まないので漏れないが、`seq` / `pointer` の値に置かれたものは
  長さ・内容を問わず表示される。`_safe` で制御文字は可視化される（ANSI 注入は無い）。
- 変異検証: 該当テストは無い
- 提案: `reprlib.repr`（既定 30 文字程度）か `type(seq).__name__` だけを出す

### F-S-P3-009 [confidence 60] `render` の成功メッセージ `書き出しました: {out}` が `_safe` を通っていない
- 場所: `packages/jin-cli/src/jin_cli/main.py:953`（`build` の 665 行も同じパターン）
- 内容 / 再現: `-o "$dir/o_cr$(printf '\r')FAKE.svg"` → stdout に `\r` が生で出る（`od -c` で確認）。click は ANSI 色コード
  （`ESC[…m`）だけを剥がすので、`\r` / BEL / U+2028 は素通り。`-o` は利用者自身の引数なので影響は小さいが、
  同じ関数の他の 3 箇所（`_safe(str(out))`）と規律が揃っていない（S6「表示側でも閉じる」）。
- 提案: `typer.echo(f"書き出しました: {_safe(str(out))}")`。`build` 側も同時に直す

### F-S-P3-010 [confidence 55] `sys.stdout.write(svg)` が stdout のエンコーディングで落ちる（`jin dump` は同条件で成功）
- 場所: `packages/jin-cli/src/jin_cli/main.py:946`
- 内容 / 再現: `PYTHONIOENCODING=ascii jin render examples/researcher/researcher.jin` → `UnicodeEncodeError` のトレースバック exit 1
  （rune の日本語）。同条件で `jin dump` は exit 0（`typer.echo` が吸収する）。Windows の cp932 コンソールで rune に
  cp932 外の文字があるときも同じ。fail-closed だがトレースバック。
- 提案: `sys.stdout.buffer.write(svg.encode("utf-8"))`。「stdout と `-o` はバイト同一」（`test_stdout_and_the_output_file_are_byte_identical`）の
  主張とも整合する（現状は `-o` が UTF-8 固定なのに stdout はロケール依存）

### F-S-P3-011 [confidence 50] `--trace` を `read_text()` で全読みし `splitlines()` で複製する（上限無し）
- 場所: `packages/jin-cli/src/jin_cli/main.py:845-853`
- 内容: 200 000 行（`/circles/0/core`）で 2.9 s / 512 MB・出力 SVG 29 MB（点 20 万個）。線形で許容範囲だが、ファイルサイズに
  上限が無く、行ごとの `json.loads` の前に全体を 2 度メモリに載せる。F-S-P3-002 と組み合わせなければ問題にならない。情報。
- 提案: `with path.open(encoding="utf-8", newline="") as f: for number, line in enumerate(f, 1)` のストリーム読みに変える
  （F-S-P3-003 の `split("\n")` 化と同時にできる）

### F-S-P3-012 [confidence 50] `-o` の親ディレクトリが無いときの文言が誤誘導（`fmt` 用 ENOENT ヒントの流用）
- 場所: `packages/jin-cli/src/jin_cli/main.py:257-263`（`_WRITE_ERRNO_HINTS[ENOENT]`）、`_write_atomically` の `mkstemp` 失敗経路
- 内容 / 再現: `jin render … -o nope/x.svg` → `書き込む直前にファイルが消えました（No such file or directory）` exit 1。
  実際は出力ディレクトリが無いだけ。fail-closed。
- 提案: `allow_create=True` の経路では ENOENT を「出力先のディレクトリがありません」に言い換える

### F-S-P3-013 [confidence 40] `_write_svg` の `exists()` 判定と `_write_atomically` 内の `exists()` の間に窓がある
- 場所: `packages/jin-cli/src/jin_cli/main.py:876-880` と `384`
- 内容: `--force` 無しで `path.exists()` が False → その後（`mkstemp` 〜 `os.replace` の間）に同名ファイルが現れると、
  `copymode` して `os.replace` で上書きする。同一ユーザーのローカル競合だけで成立し、シンボリックリンクは
  `Path(path).is_symlink()` が直前で拒む（リンク先は書き換わらない）。情報として記録。
- 提案: `--force` 無しの新規作成は `os.link(temporary, path)`（存在すれば EEXIST）にすると競合しない。優先度は低い

## 変異で緑のままだったテスト（偽 green の候補）

| 変異 | 対象 | 結果 | 備考 |
|---|---|---|---|
| `except UnicodeDecodeError` 枝の削除（`_read_trace_rows`） | `packages/jin-cli/tests/test_render.py` | **24 passed（緑のまま）** | F-S-P3-006。非 UTF-8 の fixture が無い |
| （実装者の 42 変異） | `mutate_p3.py` | 42/42 caught | `CLI-follow-symlink-upfront-only` は宣言どおり GREEN（二層目が守る）。`CLI-new-file-0600` は赤だが、固定している値そのものが F-S-P3-004 |

テストが**存在しない**ため変異を作れなかった観点（上の finding の根拠）: 4300 桁超の整数 / 深い入れ子 / 長大 pointer /
U+2028 を含む 1 行 / rune の U+FFFE・U+FFFF / 負の seq / `!r` の長さ / `_safe` 無しの echo / stdout エンコーディング。

## 実装者の記録（notes / conformance / plan / layout.md）と実物の不一致

1. **notes P3-7 の 8**「それ以外（JSON でない / オブジェクトでない / 型違い）はすべて exit 2 にした」 ↔ 4300 桁超の整数と
   深い入れ子は未捕捉トレースバックで exit 1（F-S-P3-001）。
2. **README「`--trace` は `jin run --trace` が書いた JSONL を読み」 / layout.md §7.5** ↔ `jin run` が `ensure_ascii=False` で書く
   U+2028 / U+2029 / U+0085 を含む行は `jin render` が読めない（F-S-P3-003）。
3. **notes P3-7 の 9 の論拠 (b)**「umask を取る往復はマルチスレッドの LSP で危険」 ↔ `_write_atomically` は `jin_cli` にあり LSP から
   呼ばれない。論拠 (c)「SVG は秘匿対象ではない」 ↔ SVG は rune の先頭 43 文字を含む（F-S-P3-004）。
4. **layout.md §7.5「`seq`（int・1 始まり）」** ↔ 実装は負の int を受けて発火させる（F-S-P3-007）。
5. **layout.md §3 / §4・svg.py の docstring「属性値とテキストノードは必ずエスケープを通す」** は正しいが、「出力が XML 1.0 として
   well-formed である」という保証はどこにも書かれておらず、実際に U+FFFE / U+FFFF で崩れる（F-S-P3-005）。
   `decision-conformance.md` §2.24 にも該当行は無い（constraints の範囲外なので不一致ではないが、Phase 5 の前提として抜けている）。
6. **decision-conformance.md P3 行（DP-JIN-SVG-DETERMINISM-01 5 行 / DP-COMMON-07 2 行）**: 記載の根拠（`fmt_coord` 1 本・
   `hashlib.sha256`・別プロセス 2 回・`star_step`・キャッシュ無し・モジュール状態無し・動的 import 無し）はすべてコードと
   一致することを確認した。不一致なし。
7. **README「`jin render` は任意コードを実行しない。`ref` を import せず」**: 実測どおり（マーカー方式 + positive control）。不一致なし。
