# Stage 5 review: security — 実装ラウンド 1（Jin Phase 0+1）

レビュー日: 2026-09-04 / 対象: 言語仕様書 + `packages/jin-core` + `packages/jin-cli` + `.github/workflows/ci.yml` + `scripts/generate_schema.py`
判断材料: コード・生成物・`delivery/` の成果物のみ。実装者の報告・コメント・rationale は未検証の主張として扱い、引用された箇所はすべてコードで実在を確認した。

## Summary

- **finding 総数: 19 件**（通し ID S1〜S19）。うち **S18 は「問題なし」の確認結果**なので、実質の指摘は **18 件**
- **confidence 90 以上: 14 件**（S1, S2, S3, S4, S5, S6, S8, S9, S10, S11, S12, S13, S14, S19）
- **severity 内訳**: High 4（S1, S2, S3, S4）/ Medium 5（S5, S6, S7, S8, S9）/ Low-Medium 2（S10, S13）/ Low 6（S11, S12, S14, S15, S16, S19）/ Info 1（S17）/ 問題なし 1（S18）
- **decision-conformance.md の「反映済み」記述のコード確認**: **乖離あり 1 件 = S14**（DP-COMMON-07 の「`jin_core` は状態を持たない純関数」が `resolve=True` で成立しない）。それ以外は引用先のテスト関数・grep 主張をすべてコードで確認し、**乖離なし**
- **ci.yml の secrets / untrusted PR / pull_request_target**: `pull_request_target` は 0 ヒット、トリガは `push`（main）と `pull_request` のみ、`secrets.*` の参照ゼロ、`--resolve` を CI のどこでも使っていない。**この 3 点については問題なし**。別途 `permissions:` 未指定と actions の可変タグを S16 として指摘
- **PoC 成果物とツリー変更の撤去状況**: **リポジトリツリーへの変更ゼロ・PoC 残骸ゼロ**。PoC は全て `/Users/toyota/.claude/jobs/8b3a6b62/tmp/w/` 配下にのみ作成した

```
$ git status --porcelain
 M delivery/20260904-1445-jin/design.yaml
 M delivery/20260904-1445-jin/implement-ledger.md
?? .github/
?? .gitignore
?? CLAUDE.md
?? README.md
?? delivery/20260904-1445-jin/decision-conformance.md
?? delivery/20260904-1445-jin/implementation-notes.md
?? delivery/20260904-1445-jin/implementation-plan.json
?? delivery/20260904-1445-jin/replay-commands.md
?? delivery/20260904-1445-jin/version-matrix.md
?? docs/spec/
?? examples/
?? packages/
?? pyproject.toml
?? schemas/
?? scripts/
?? tests/
?? uv.lock

$ find . -name "PWNED*" -o -name "evil*.py" -o -name "pwn.jin" -o -name "exit.jin" \
       -o -name "esc.jin" -o -name "deep.jin" -o -name "chain.jin" -o -name "quad*.py" ...
（0 件）
```

上記の `M` / `??` は**すべて実装ラウンド 1 の未コミット成果物**であり、本レビューによる変更は 1 件も含まれない
（リポジトリ内のファイルは読むコマンドしか実行しておらず、`jin fmt` をリポジトリツリーに対して走らせてもいない）。
なお本ファイル `delivery/20260904-1445-jin/code-review-raw/security.md` は親の明示指示による新規追加である。

- **resolve を ws トランスポートから構造的に到達不能にする設計案（3 行）**:
  `resolve` を `bool` フラグではなく `RefResolver` プロトコルの注入にし、実際に import する `ImportResolver` は `jin_cli` 側にのみ置く（`jin_core` からは import しない）。
  `jin-lsp` は `jin_core` にしか依存しないため、ws サーバのコードパスから `ImportResolver` がそもそも到達できなくなる。
  既存の import-linter に forbidden contract（`jin_lsp` → `jin_cli.resolver` を禁止）を 1 行足せば機械的に落とせる（DP-COMMON-11 の仕組みにそのまま乗る）。

---

## Findings

```
S1 【High / confidence 97】--resolve は任意コード実行そのもの
packages/jin-core/src/jin_core/semantic.py:212-223（_import_ref → importlib.import_module）
packages/jin-cli/src/jin_cli/main.py:75-77（--resolve フラグ）
形式検証（_PYTHON_REF, semantic.py:30-32）は相対 import・".."・パス区切りを弾いており妥当だが、
「形式が正しい任意のモジュール名」は全部 import される。Python の import はトップレベル +
親パッケージ全ての __init__.py を実行する。既定オフ（main.py:77 の "= False"）は fail-closed で正しいが、
--resolve が有用であるためには対象プロジェクトが sys.path に載っている必要があり、
実運用では必然的に PoC の条件が揃う（PYTHONPATH なしでは cwd は載らないことも実測確認済み）。
PoC: 成功（実行済み）。evil.py のトップレベルにファイル書き込みを置き、.jin に "ref": "evil:nonexistent" を書いて
PYTHONPATH=. jin check --resolve pwn.jin を実行 → PWNED.txt が生成された。
診断は「nonexistent がありません」という警告 1 件・exit 0。攻撃成功時に出力が「ほぼ正常」に見える。
緩和案: importlib.util.find_spec で対象モジュール本体の実行を避ける（親パッケージは実行される点は残る）。
それが許されないなら別プロセス + タイムアウトにする。
後続ラウンドへの影響（最重要）: jin lsp --ws PORT が resolve=True で check_text を呼ぶ設計になれば、
ローカル WebSocket に接続できる任意の相手が任意コードを実行できる。Summary の設計案を参照。
なお delivery/.../decision-conformance.md §4 自身が「README / CLAUDE.md に警告が無い」と認めており、実際に無い（S19）。
```

```
S2 【High / confidence 96】fail-closed 違反 — SystemExit で検査が「無言の成功」になる
packages/jin-core/src/jin_core/semantic.py:219（except Exception）
except Exception は SystemExit / KeyboardInterrupt を捕まえない。
untrusted な .jin が検査そのものを黙らせて成功に見せかける。
CI が jin check を使う運用（.github/workflows/ci.yml:43）では赤いはずのビルドが緑になる。
PoC: 成功（実行済み・親も独立に再現確認済み）。トップレベルが sys.exit(0) だけのモジュールを ref で指し、
同じファイルに本物の JIN060 エラーを併記して実行:
  --- without --resolve ---
  exit.jin:4:11: error JIN060: root が指す circle 'NO_SUCH_CIRCLE' は定義されていません
  EXIT=1
  --- with --resolve ---
  EXIT=0          ← 出力ゼロ・終了コード 0
修正: except BaseException ではなく、_import_ref を別プロセス化するか、
少なくとも except (Exception, SystemExit) + 明示的な失敗扱いにする。
```

```
S3 【High / confidence 95】アルゴリズム DoS — 87 KB の .jin で 108 秒
packages/jin-core/src/jin_core/semantic.py:35-49（levenshtein）/ :52-56（close_names）/ :59-65（_name_hint）
呼び出し元: semantic.py:335, 345, 363, 374, 393
_name_hint は未解決参照 1 件ごとに全 circle 名との編集距離を純 Python で計算する。
O(未解決数 × circle 数 × 名前長^2)。
PoC: 実測（実行済み）。すべてスキーマ的に完全に妥当なファイル:
  circle 数 50  / 名前長 100 / 12 KB →   1.75 s
  circle 数 100 / 名前長 100 / 24 KB →   7.04 s
  circle 数 200 / 名前長 100 / 48 KB →  28.34 s
  circle 数 200 / 名前長 200 / 88 KB → 107.82 s
LSP はキーストロークごとに check_text を回す設計（check.py:164 が LSP と共通経路であることが docstring に明記）
なので、Phase 4 で確実に致命傷になる。
対策: close_names の候補数上限・名前長上限・早期打ち切り（距離が閾値を超えたら中断する banded Levenshtein）。
```

```
S4 【High / confidence 96】未捕捉 RecursionError — 3 箇所
packages/jin-core/src/jin_core/parser.py:141-171（_walk の相互再帰）
packages/jin-core/src/jin_core/semantic.py:107-137（_find_cycle.visit）
packages/jin-core/src/jin_core/semantic.py:156-166（_subtree_states.walk）
lark 自体は深い入力を通してしまい、落ちるのは自前の走査側。
PoC: 実行済み。
  - "[" x 2000 の .jin → parser.py:141 で RecursionError
  - 3000 個の circle が数珠つなぎになった「正当な」.jin → RecursionError
    （トレースバック末尾が semantic.py:125 の visit(nxt)）
  - _subtree_states.walk は同型の再帰。未実測だが同じ深さで落ちるはず（confidence 80）
CLI では 137 KB のトレースバックを吐く（S5 参照）。jin check --json でも同様に落ちるため、
JSON 出力を機械が読む前提が壊れる。
対策: 段 1 と段 3 で明示的な深さ上限（例: ネスト 100、circle 数上限）を設けて JIN 診断として返す。
```

```
S5 【Medium / confidence 90】例外がそのまま抜けて情報開示つきクラッシュ
packages/jin-core/src/jin_core/check.py:200-203（check_file の read_text）
packages/jin-cli/src/jin_cli/main.py:122（fmt の read_text）/ main.py:31-36（typer.Typer）
非 UTF-8 の .jin → UnicodeDecodeError、ディレクトリを jin dump に渡す → IsADirectoryError が
そのまま rich トレースバックになり、ローカル絶対パスとソースコード断片を出力する。
pretty_exceptions_show_locals は既定で無効らしくファイル内容そのものは漏れない（保存した 137 KB の
クラッシュ出力を grep して locals 表示が無いことを確認済み）。
対策: pretty_exceptions_show_locals=False の明示 + check_file の I/O 例外を診断へ落とす。
特に LSP 化後はサーバごと落ちる。
PoC: 実行済み。両方ともトレースバック表示を確認。
```

```
S6 【Medium / confidence 92】人間向け出力への ANSI エスケープ / 偽診断行インジェクション
packages/jin-cli/src/jin_cli/main.py:57-64（_format_human）+ semantic.py の各 f-string
.jin の root に ESC[2J・ESC]0;pwned・改行を仕込むと端末へ生のまま出る。画面クリア、
端末タイトル書き換え、存在しないファイルの偽診断行の捏造ができる。
要件書は「LLM は診断を読んで直す」ループを前提にしているので、偽診断行は LLM への
間接的な指示注入になりうる。Phase 4 の LSP Diagnostic.message も生 ESC をそのままエディタへ運ぶ。
PoC: 実行済み。`fake.jin:1:1: error JIN999: injected line` の捏造行が端末に出力された。
一方 jin check --json は json.dumps が  形式にエスケープするため安全（これも実測確認）。
対策: _format_human で制御文字をエスケープする。根本的には S13 を直すのが一番効く。
```

```
S7 【Medium / confidence 88】メモリ増幅 約 240 倍・入力サイズ無制限
packages/jin-core/src/jin_core/check.py:164-197 / parser.py:141
ファイルサイズ上限も要素数上限も無い。MAX_ELEMENTS=12（diagnostics.py:98）は tools/state の
「診断」であって拒否ではなく、delegate / flow.steps / circles は完全に無制限。
PoC: 実測（実行済み）。delegate 40 万要素（2.0 MB の .jin）→ maxrss 476 MB / 3.8 秒 / 診断 40 万件。
ws 経由で document を受ける Phase 4 では入力上限が必須。
```

```
S8 【Medium / confidence 95】ops.rename の正規表現「置換テンプレート」インジェクション
packages/jin-core/src/jin_core/ops.py:357-359（pattern.sub("{" + new + "}", rune)）
new_name が re.sub の置換テンプレートとして解釈される。OpError ではなく素の例外が飛ぶため、
Phase 4 の jin/applyOps（ws 経由の untrusted JSON-RPC）でサーバが落ちるかプロトコル違反になる。
PoC: 実行済み。
  value = "x\g<0>y" → state 名は 'x\g<0>y' なのに rune が 'hello {x{k}y} world' へ改変
                      （state 名と rune が不整合なモデルが生成された）
  value = "b\1c"    → 未捕捉 re.PatternError: invalid group reference 1
  value = "q\qz"    → 未捕捉 re.PatternError: bad escape \q
  value = "n\n"     → rune に生の改行が混入
修正: pattern.sub(lambda m: "{" + new + "}", rune)
```

```
S9 【Medium / confidence 95】ops.rename だけ circle index の範囲検査が無い
packages/jin-core/src/jin_core/ops.py:365-366
_circle_index(op, len(tokens)) は深さを自分自身と比較するので深さ検査が空回りし、
その後 doc["circles"][circle_index] を素で引く。
PoC: 実行済み。/circles/99 と /circles/9999999999 で未捕捉 IndexError。
一方 setCore / setRune / setFlow / addTool / setGuard / toggleAwait は正しく OpError JIN002 を返す
（＝ rename だけが例外的に穴になっている）。
```

```
S10 【Low-Medium / confidence 93】isdigit() と int() の不一致（4 箇所）
packages/jin-core/src/jin_core/pointer.py:56-59
packages/jin-core/src/jin_core/ops.py:96, 110（_circle_index）
packages/jin-core/src/jin_core/ops.py:117-118（_index_of）
packages/jin-core/src/jin_core/check.py:70（_model_at）
"²".isdigit() は True だが int("²") は ValueError。"٣"（アラビア数字）は両方通り 3 と解釈される。
pointer.py:43-63 の docstring は「解決できない場合は KeyError / IndexError を投げる
（黙って None を返さない・NFR-FAIL-001）」と宣言しており、明文化された契約違反。
PoC: 実行済み。
  resolve_pointer(doc, "/a/²")   → ValueError（契約は KeyError/IndexError）
  resolve_pointer(doc, "/a/--1") → ValueError（lstrip("-") が "--1" を通す）
  resolve_pointer(doc, "/a/٣")   → IndexError（3 として解釈された）
  apply_op(..., "/circles/²")    → 未捕捉 ValueError
修正: str.isdigit() ではなく str.isascii() and str.isdigit()（先頭ゼロ・符号も弾く厳密判定）。
```

```
S11 【Low / confidence 90】jin fmt の書き戻しが非原子的
packages/jin-cli/src/jin_cli/main.py:127（path.write_text(...)）
一時ファイル + os.replace ではなく truncate → write。プロセス kill / ディスクフルで
元ファイルが部分書き込みで壊れる。ディレクトリ再帰で複数ファイルを順に書くので、
途中で落ちれば「一部だけ整形済み」の中途半端な状態になる。
Phase 5 でエディタと LSP が同じファイルを触るようになると競合も加わる。
PoC: なし（コード読解。原子的書き込みの痕跡が無いことをコードで確認）。
付随（confidence 80・correctness 寄り）: read_text / write_text は既定で universal newlines 変換を
行うため、CRLF ファイルは jin fmt --check を「差分なし」で通過するが実バイトは正準形と不一致。
NFR-DET-002 の「バイト同一」に影響。
```

```
S12 【Low / confidence 95】jin fmt がシンボリックリンクを追って対象ディレクトリの外に書き込む
packages/jin-cli/src/jin_cli/main.py:39-50（_collect）+ :127
ディレクトリ symlink には降りない（Python 3.13+ の rglob 既定）ので影響はファイル symlink に限るが、
「指定したディレクトリの中だけを触る」という期待は破れている。
PoC: 実行済み。proj/link.jin -> ../outside/secret.jin を置き jin fmt proj を実行 →
outside/secret.jin が書き換えられ、リンクはリンクのまま残った。
対策: path.is_symlink() でスキップするか警告する。
```

```
S13 【Low-Medium / confidence 92】モデルの文字列に文字種・長さの制約が一切無い
packages/jin-core/src/jin_core/model.py:45, 51, 58-60, 68-69, 76-77, 82, 95, 101, 107, 122-125
name / root / core / ref / builtin / rune / steps[] / delegate[] / state[].name のどれにも
pattern も max_length も無い。docs/spec/model.md:42 も「ファイル内一意。名前が ID」としか書かず
文字種を定めていない。
これが S6（ESC 注入）・S3（名前長^2 の係数）・S10（Unicode 数字）の共通の根。
name 系に pattern=r"^[A-Za-z_][A-Za-z0-9_]*$" + max_length を入れるのが単一で最も効く修正で、
副作用として ADK 側の識別子制約とも整合する。仕様変更にあたるので人間承認が要る。
PoC: なし（model.py と docs/spec/model.md の読解で確認）。
```

```
S14 【Low / confidence 90】decision-conformance の DP-COMMON-07「reflected」が resolve=True で成立しない
delivery/20260904-1445-jin/decision-conformance.md の DP-COMMON-07 行 / semantic.py:218
対照表は「jin_core にモジュールレベルの可変状態は無い」「check_text は毎回フル再計算する純関数」と
主張するが、importlib.import_module は sys.modules をプロセス全体で書き換える。
同じ ref に対する 2 回目の check_text はモジュールを再実行せず、結果が過去の呼び出しに依存する。
しかも import されたコードは同一プロセス内に残り続けるため、長寿命の LSP では
チェッカ自身をモンキーパッチできる位置にいる。「純関数」という主張は resolve=False のときだけ真。
PoC: なし（Python の import セマンティクスとコード読解。S1 の PoC が import 実行を実証済み）。
→ 本レビューで見つかった唯一の「反映済みと書かれているが実際は成立していない」項目。
```

```
S15 【Low / confidence 88】引数なしの既定が "." で、無視ディレクトリを除外しない
packages/jin-cli/src/jin_cli/main.py:53-54（_default_paths）+ :44（rglob("*.jin")）
jin fmt を引数なしで叩くと .venv / node_modules / .git 配下も含め全ての .jin を書き換える。
.gitignore を見ていない。将来 apps/editor/node_modules ができると実害が出る。
PoC: なし（コード読解）。
```

```
S16 【Low / confidence 85】CI の設定
.github/workflows/ci.yml:9-11（permissions 未指定）/ :12, :15（actions が可変タグ）
指摘 1: permissions: ブロックが無い。リポジトリ既定が write の場合、
        push トリガ時の GITHUB_TOKEN が過剰権限になる。permissions: contents: read を明示すべき。
指摘 2: actions/checkout@v4（:12）と astral-sh/setup-uv@v5（:15）が可変タグ。
        サプライチェーン硬化としては SHA ピン推奨。
指摘 3: uv run jin check examples（:43）は S4 の RecursionError や S2 の SystemExit で
        未捕捉例外で落ちる／黙って通る経路を持つ。examples は信頼できるので現状は実害なし。
PoC: なし（設定ファイル読解）。
（secrets / untrusted PR / pull_request_target については下の「確認したが問題が無かった点」を参照）
```

```
S17 【Info / confidence 80】診断へ任意の例外文字列を埋め込む（log-confidentiality）
packages/jin-core/src/jin_core/semantic.py:220
f"モジュール {module_name} を import できません（{type(exc).__name__}: {exc}）"
import された第三者モジュールが送出する例外メッセージ（API キー未設定を知らせる文言、絶対パス、
環境変数名など）がそのまま診断 JSON に載り、LSP 経由でエディタへ、さらに LLM のコンテキストへ流れる。
対策: 例外の型名だけに絞る。
PoC: なし（コード読解。ただし S1 の実行で ModuleNotFoundError のメッセージが診断に載ることは確認済み）。
```

```
S18 【問題なし / confidence 95】scripts/generate_schema.py の書き込み先
scripts/generate_schema.py:14, 18
書き込み先は REPO_ROOT / SCHEMA_PATH（モジュール定数 "schemas/jin.schema.json"）で、
ユーザ入力が混じらずトラバーサル無し。target.parent.mkdir も定数パス。指摘なし。
```

```
S19 【Low / confidence 98】--resolve が任意コードを実行することがドキュメントに一切書かれていない
README.md 全文 / CLAUDE.md 全文
grep で --resolve の記述ゼロ。唯一の記述は CLI ヘルプの 1 行（main.py:76）と
docs/spec/diagnostics.md:49, 177-178 だが、いずれも「実際に import する」までで
「任意コードが走る」とは書いていない。
delivery/20260904-1445-jin/decision-conformance.md §4 自身がこの欠落を認めている（自己申告は正確）。
PoC: 実行済み（grep）。
```

---

## 確認したが問題が無かった点（parent の観点への回答）

| 観点 | 確認結果 |
|---|---|
| **JSON Pointer のエスケープ（`~0` / `~1`）** | `pointer.py:12-19` の `escape_token`（`~`→`~0` を先）/ `unescape_token`（`~1`→`/` を先）は RFC 6901 の順序として**正しい**。`parent_of`（`:36-40`）が `rsplit("/")` を使っても、トークン内の `/` は `~1` になっているので安全 |
| **ユーザ由来文字列の pointer 生連結** | `semantic.py` の `join(...) + "/name"` / `+ "/ref"` / `+ "/rune"` はいずれも**リテラル定数**の連結で、ユーザ入力の生連結は 1 箇所も無い。`join()` は必ず `escape_token` を通る |
| **インジェクション（コマンド / SQL）** | `packages/*/src` に `subprocess` / `os.system` / `eval` / `exec` / `urllib` / `requests` / `httpx` / `socket` は **grep 0 ヒット**。DP-COMMON-09 の「ネットワーク不要」主張は真 |
| **ReDoS** | `_PYTHON_REF`（`semantic.py:30-32`）も `_RUNE_KEY`（`:27`）も曖昧な入れ子量化子を持たず線形。破滅的バックトラックは無し |
| **`jin check --json` の出力衛生** | `json.dumps` が制御文字を `` 形式にエスケープすることを実測確認。JSON 経路は S6 の影響を受けない |
| **CI のトリガと secrets** | `pull_request_target` は **0 ヒット**。トリガは `push`（main）と `pull_request` のみで、fork PR が secrets に触れない正しい形。`secrets.*` の参照ゼロ。`uv sync --frozen`（`:18`）でロック固定。**`--resolve` を CI のどこでも使っていない**（`:43` の `jin check examples`、`:47` の `jin fmt --check examples`）ので S1 の ACE は CI 経路に露出していない |

---

## decision-conformance.md「反映済み」記述のコード確認（全件）

依頼で「報告を信じずコードで確認する」よう指定された項目。**乖離は S14 の 1 件のみ**。

| 対照表の主張 | 確認結果 |
|---|---|
| `tests/contract/test_dependency_direction.py:76-104` に「違反を注入して BROKEN になる」テストがある | **実在**。`test_import_linter_actually_bites_on_a_forbidden_import` が `shutil.copytree` で複製に `import google.adk` を注入し `returncode != 0` と `"BROKEN" in stdout` を assert している |
| `packages/jin-core/tests/test_canonical.py` の制御文字・サロゲートペア・DEL/Latin-1 の各テスト | **実在**。`test_control_characters_are_escaped` / `test_surrogate_pair_survives_roundtrip` / `test_del_and_latin1_are_not_escaped` / `test_non_ascii_is_not_escaped` を関数名で確認 |
| `tests/contract/test_pointer_contract.py::test_loc_to_pointer_handles_union_tag_optional_and_alias` | **実在**。併せて `test_loc_to_pointer_for_missing_key_points_at_the_missing_child` も実在 |
| DP-COMMON-09「HTTP クライアントを一切 import していない」 | **真**（`packages/*/src` に `urllib` / `requests` / `httpx` / `socket` / `subprocess` / `eval` / `exec` が grep 0 ヒット）|
| DP-JIN-POINTER-RANGE-01「JIN002 の検出器は Pydantic に一本化」 | **真**。`check.py:139-161` の `_schema_diagnostics` が唯一の生成箇所で、`jsonschema` は依存に無い |
| DP-JIN-CANONICAL-01「canonical.py は `model_dump` を使わない」 | **真**。コード中の `model_dump` はゼロで、docstring の言及のみ |
| DP-COMMON-07「`jin_core` は状態を持たない純関数」 | **偽（`resolve=True` のとき）** → **S14** |

---

## 後続ラウンド（Phase 4 LSP ws / Phase 5 React エディタ）に向けて今固めるべき前提

1. **`resolve=True` を ws トランスポートから構造的に到達不能にする**（型か境界で。フラグの既定値だけに頼らない）。設計案は下記
2. **`check_text` に入力上限**（バイト数・ネスト深さ・circle 数・名前長）を段 1 で導入する。S3 / S4 / S7 はすべて「LSP が毎キーストローク呼ぶ」で致命化する
3. **`jin_core` の公開関数から素の例外を漏らさない契約**を今のうちに敷く。S4 / S5 / S8 / S9 / S10 はすべてこの 1 本の欠落
4. **診断 `message` は制御文字を含まないことを保証する**（モデル側 S13 か出力側 S6 のどちらかで）

### `resolve` を ws から遮断する設計案（3 案・A を推奨）

- **A（推奨・型で落とす）**: `resolve` を `bool` フラグではなく `RefResolver` プロトコルの注入にする。`jin_core.check_text(text, file, resolver: RefResolver = NullResolver())` とし、実際に import する `ImportResolver` は **`jin_cli` 側にのみ置く**（`jin_core` からは import しない）。`jin-lsp` は `jin_core` にしか依存しないので、ws サーバのコードパスから `ImportResolver` が**そもそも到達できなくなる**。import-linter の forbidden contract（`jin_lsp` → `jin_cli.resolver` を禁止）で機械的に落とせるため、既存の DP-COMMON-11 の仕組みにそのまま乗る
- **B（プロセス分離）**: `_import_ref` を `subprocess` + タイムアウト + 使い捨てプロセスで実行する。S1 の ACE 自体は残るが、**S2（`SystemExit` による fail-open）と S14（`sys.modules` 汚染・チェッカのモンキーパッチ）は構造的に消える**。A と併用可
- **C（最小対処・A の代替にはならない）**: `importlib.import_module` を `importlib.util.find_spec` に置換。対象モジュール本体の実行は避けられるが**親パッケージの `__init__.py` は実行される**ので ACE は残る。「import できるか」の検査としては十分だが、単独では緩和として弱い

いずれの案でも **S19（README / CLAUDE.md への明示的な ACE 警告）は別途必要**。
